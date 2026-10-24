"""Local scheduler for Afterglow ScheduleTask extension items."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone, tzinfo
import logging
from pathlib import Path
import sqlite3
import time

from afterglow_client import ScheduleTask

from .api import QQBotAPI

logger = logging.getLogger("qqbot.schedule_tasks")

_WEEKDAY_TO_INT = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


@dataclass(frozen=True)
class _DueTask:
    openid: str
    task_id: str
    trigger_at: str
    recurrence: str | None
    message: str
    title: str
    source: str
    next_trigger_at: str
    sent_count: int


class QQScheduleTaskRunner:
    """Persist and deliver Afterglow-extracted schedule tasks through QQ."""

    def __init__(
        self,
        api: QQBotAPI,
        db_path: str | Path,
        *,
        poll_interval: float = 1.0,
        retry_delay: float = 60.0,
    ) -> None:
        self._api = api
        self._db_path = Path(db_path)
        self._poll_interval = max(0.5, poll_interval)
        self._retry_delay = max(5.0, retry_delay)
        self._conn = self._connect(self._db_path)
        self._init_schema()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="qq-schedule-tasks")
            logger.info("定时任务调度器已启动 db=%s", self._db_path)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._conn.close()

    async def add_tasks(self, openid: str, tasks: tuple[ScheduleTask, ...]) -> None:
        """Register tasks for a QQ user, deduplicated by (openid, task id)."""
        if not tasks:
            return

        now = int(time.time())
        added = 0
        for task in tasks:
            try:
                trigger_at = _parse_absolute_time(task.trigger_at)
            except ValueError as exc:
                logger.warning(
                    "忽略 trigger_at 非法的定时任务 openid=%s task_id=%s：%s",
                    openid,
                    task.id,
                    exc,
                )
                continue

            result = self._conn.execute(
                """
                INSERT OR IGNORE INTO scheduled_tasks (
                    openid, task_id, trigger_at, recurrence, message, title, source,
                    next_trigger_at, status, sent_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (
                    openid,
                    task.id,
                    task.trigger_at,
                    task.recurrence,
                    task.message,
                    task.title,
                    task.source,
                    _utc_iso(trigger_at),
                    now,
                    now,
                ),
            )
            added += result.rowcount

        self._conn.commit()
        if added:
            logger.info("已登记 %d 条定时任务 openid=%s", added, openid)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self._deliver_due_tasks()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
            except asyncio.TimeoutError:
                pass

    async def _deliver_due_tasks(self) -> None:
        rows = self._conn.execute(
            """
            SELECT openid, task_id, trigger_at, recurrence, message, title, source,
                   next_trigger_at, sent_count
            FROM scheduled_tasks
            WHERE status = 'pending' AND next_trigger_at <= ?
            ORDER BY next_trigger_at ASC
            LIMIT 20
            """,
            (_utc_iso(datetime.now(timezone.utc)),),
        ).fetchall()

        for row in rows:
            task = _DueTask(**dict(row))
            await self._deliver_task(task)

    async def _deliver_task(self, task: _DueTask) -> None:
        try:
            await self._api.send_c2c_text(task.openid, task.message)
        except Exception as exc:
            logger.exception(
                "发送定时任务失败 openid=%s task_id=%s", task.openid, task.task_id
            )
            self._postpone_task(task, str(exc))
            return

        sent_count = task.sent_count + 1
        next_trigger_at = _next_recurrence_time(
            trigger_at=_parse_absolute_time(task.trigger_at),
            recurrence=task.recurrence,
            after=datetime.now(timezone.utc),
            sent_count=sent_count,
        )
        now = int(time.time())

        if next_trigger_at is None:
            self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET status = 'completed',
                    sent_count = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE openid = ? AND task_id = ?
                """,
                (sent_count, now, task.openid, task.task_id),
            )
            logger.info(
                "定时任务已完成 openid=%s task_id=%s title=%s",
                task.openid,
                task.task_id,
                task.title,
            )
        else:
            self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET next_trigger_at = ?,
                    sent_count = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE openid = ? AND task_id = ?
                """,
                (
                    _utc_iso(next_trigger_at),
                    sent_count,
                    now,
                    task.openid,
                    task.task_id,
                ),
            )
            logger.info(
                "定时任务已发送并更新下次触发 openid=%s task_id=%s next=%s",
                task.openid,
                task.task_id,
                _utc_iso(next_trigger_at),
            )
        self._conn.commit()

    def _postpone_task(self, task: _DueTask, error: str) -> None:
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=self._retry_delay)
        self._conn.execute(
            """
            UPDATE scheduled_tasks
            SET next_trigger_at = ?,
                last_error = ?,
                updated_at = ?
            WHERE openid = ? AND task_id = ?
            """,
            (
                _utc_iso(retry_at),
                error[:500],
                int(time.time()),
                task.openid,
                task.task_id,
            ),
        )
        self._conn.commit()

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                openid TEXT NOT NULL,
                task_id TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                recurrence TEXT,
                message TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                next_trigger_at TEXT NOT NULL,
                status TEXT NOT NULL,
                sent_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (openid, task_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due
            ON scheduled_tasks (status, next_trigger_at)
            """
        )
        self._conn.commit()


def _parse_absolute_time(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法解析 ISO 8601 时间 {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"trigger_at 必须包含时区：{value!r}")
    return parsed


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_rrule(recurrence: str | None) -> dict[str, str]:
    if not recurrence:
        return {}

    parts: dict[str, str] = {}
    for item in recurrence.split(";"):
        key, sep, value = item.partition("=")
        if not sep:
            continue
        parts[key.strip().upper()] = value.strip().upper()
    return parts


def _parse_int_list(
    params: dict[str, str], key: str, *, minimum: int, maximum: int
) -> list[int] | None:
    raw = params.get(key)
    if not raw:
        return None

    values: list[int] = []
    for item in raw.split(","):
        try:
            value = int(item)
        except ValueError:
            return None
        if value < minimum or value > maximum:
            return None
        values.append(value)
    return sorted(set(values))


def _parse_positive_int(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_byday(params: dict[str, str]) -> set[int] | None:
    raw = params.get("BYDAY")
    if not raw:
        return None

    weekdays: set[int] = set()
    for item in raw.split(","):
        weekday = _WEEKDAY_TO_INT.get(item)
        if weekday is None:
            return None
        weekdays.add(weekday)
    return weekdays


def _parse_until(params: dict[str, str], default_tz: tzinfo) -> datetime | None:
    raw = params.get("UNTIL")
    if not raw:
        return None

    normalized = raw.replace("Z", "+00:00")
    parsed: datetime
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S%z")
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed


def _next_recurrence_time(
    *,
    trigger_at: datetime,
    recurrence: str | None,
    after: datetime,
    sent_count: int,
) -> datetime | None:
    params = _parse_rrule(recurrence)
    if not params:
        return None

    freq = params.get("FREQ")
    interval = _parse_positive_int(params.get("INTERVAL")) or 1
    count = _parse_positive_int(params.get("COUNT"))
    if count is not None and sent_count >= count:
        return None

    tz = trigger_at.tzinfo
    if tz is None:
        return None

    hours = _parse_int_list(params, "BYHOUR", minimum=0, maximum=23)
    minutes = _parse_int_list(params, "BYMINUTE", minimum=0, maximum=59)
    seconds = _parse_int_list(params, "BYSECOND", minimum=0, maximum=59)
    byday = _parse_byday(params)
    until = _parse_until(params, tz)

    if hours is None:
        hours = [trigger_at.hour]
    if minutes is None:
        minutes = [trigger_at.minute]
    if seconds is None:
        seconds = [trigger_at.second]

    after_local = after.astimezone(tz)
    start_local = trigger_at.astimezone(tz)

    if freq == "DAILY":
        return _next_daily(
            start_local,
            after_local,
            interval,
            hours,
            minutes,
            seconds,
            byday,
            until,
        )
    if freq == "WEEKLY":
        return _next_weekly(
            start_local,
            after_local,
            interval,
            hours,
            minutes,
            seconds,
            byday,
            until,
        )

    logger.warning("暂不支持的 ScheduleTask recurrence=%r，任务不会重复", recurrence)
    return None


def _next_daily(
    start: datetime,
    after: datetime,
    interval: int,
    hours: list[int],
    minutes: list[int],
    seconds: list[int],
    byday: set[int] | None,
    until: datetime | None,
) -> datetime | None:
    base_date = start.date()
    start_offset = max(0, (after.date() - base_date).days)
    for offset in range(start_offset, start_offset + 3660):
        if offset % interval != 0:
            continue
        day = base_date + timedelta(days=offset)
        if byday is not None and day.weekday() not in byday:
            continue
        candidate = _first_candidate_after(day, start, after, hours, minutes, seconds)
        if candidate is None:
            continue
        if until is not None and candidate > until:
            return None
        return candidate
    return None


def _next_weekly(
    start: datetime,
    after: datetime,
    interval: int,
    hours: list[int],
    minutes: list[int],
    seconds: list[int],
    byday: set[int] | None,
    until: datetime | None,
) -> datetime | None:
    allowed_days = byday or {start.weekday()}
    base_week_start = start.date() - timedelta(days=start.weekday())
    start_offset = max(0, (after.date() - base_week_start).days)

    for day_offset in range(start_offset, start_offset + 7 * 520):
        day = base_week_start + timedelta(days=day_offset)
        week_index = day_offset // 7
        if week_index % interval != 0:
            continue
        if day.weekday() not in allowed_days:
            continue
        candidate = _first_candidate_after(day, start, after, hours, minutes, seconds)
        if candidate is None:
            continue
        if until is not None and candidate > until:
            return None
        return candidate
    return None


def _first_candidate_after(
    day: date,
    start: datetime,
    after: datetime,
    hours: list[int],
    minutes: list[int],
    seconds: list[int],
) -> datetime | None:
    for hour in hours:
        for minute in minutes:
            for second in seconds:
                candidate = datetime.combine(
                    day,
                    dt_time(hour, minute, second, tzinfo=start.tzinfo),
                )
                if candidate >= start and candidate > after:
                    return candidate
    return None
