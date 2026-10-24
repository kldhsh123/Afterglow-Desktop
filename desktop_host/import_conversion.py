"""Safe, declarative conversion fallback for chat exports unknown to Afterglow.

The model only produces field paths. It never produces executable code; the
desktop applies the small, validated mapping locally to the complete export.
"""
from __future__ import annotations

import json
import hashlib
import math
import random
import re

try:
    from .i18n import tr
except ImportError:
    from i18n import tr
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from typing import Any


MAX_SAMPLE_CHARS = 48_000
MAX_MESSAGES = 2_000_000
MAX_EXPORT_BYTES = 64 * 1024 * 1024
FIELDS = {"sender_id", "sender_name", "text", "timestamp", "kind"}


def parse_mapping_response(content: Any) -> dict[str, str]:
    """Parse only the final answer, never reasoning or executable snippets."""
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content
                          if isinstance(part, dict) and isinstance(part.get('text'), str))
    if not isinstance(content, str) or not content.strip():
        raise ValueError(tr('import.error.response_empty'))
    content = content.lstrip('\ufeff').strip()
    # Some compatible services ignore response_format and add a Markdown fence.
    # Accept the wrapper without relaxing mapping/path validation in any way.
    fenced = re.fullmatch(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content, flags=re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(tr('import.error.response_json')) from None
    return validate_spec(value)


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "div", "p", "tr", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"div", "p", "tr", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _get(value: Any, path: str) -> Any:
    if path == "" or path == "$":
        return value
    current = value
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")] if path.startswith("/") else path.removeprefix("$.").split(".")
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


def read_export(path: Path) -> tuple[Any, list[Any], str]:
    """Read JSON/JSONL and return a structured payload plus source records."""
    suffix = path.suffix.lower()
    if suffix not in {".json", ".jsonl", ".ndjson", ".txt", ".md", ".html", ".htm"}:
        raise ValueError(tr("import.error.unsupported"))
    if path.stat().st_size > MAX_EXPORT_BYTES:
        raise ValueError(tr('import.error.conversion_size'))
    with path.open('rb') as stream:
        raw = stream.read(MAX_EXPORT_BYTES + 1)
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError(tr('import.error.conversion_size'))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError(tr('import.error.encoding')) from None
    if suffix in {".txt", ".md", ".html", ".htm"}:
        if suffix in {".html", ".htm"}:
            parser = _PlainHTML()
            parser.feed(text)
            text = "".join(parser.parts)
        return {"_text": text}, [], text
    if suffix in {".jsonl", ".ndjson"}:
        records = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                return _unstructured_json(text, number, exc.colno, exc.msg)
            if isinstance(value, dict):
                records.append(value)
        return records, records, text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        # A .json suffix does not guarantee valid JSON. Keep the WHOLE source
        # for model analysis; never silently discard the trailing contents.
        return _unstructured_json(text, exc.lineno, exc.colno, exc.msg)
    return payload, _find_record_list(payload), text


def _unstructured_json(text, line, column, reason):
    explanation = tr('import.error.json_extra' if reason == 'Extra data' else 'import.error.json_invalid')
    warning = tr('import.warning.source_json', line=line, column=column, reason=explanation)
    return {'_text': text, '_source_warning': warning}, [], text


def _find_record_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        preferred = ("messages", "records", "items", "chats", "data", "history")
        for key in preferred:
            candidate = value.get(key)
            if isinstance(candidate, list) and candidate and all(isinstance(i, dict) for i in candidate[:20]):
                return candidate
        candidates = [v for v in value.values() if isinstance(v, list) and v and all(isinstance(i, dict) for i in v[:20])]
        if len(candidates) == 1:
            return candidates[0]
    return []


def describe_structure(payload: Any) -> str:
    """Give the model exact container paths without including message values."""
    lines = []
    def visit(value, path, depth=0):
        if depth > 6 or len(lines) >= 100:
            return
        if isinstance(value, dict):
            lines.append(f'{path or "/"}: object keys={json.dumps(list(value)[:40], ensure_ascii=False)}')
            for key, child in list(value.items())[:40]:
                if isinstance(child, (dict, list)):
                    visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'), depth + 1)
        elif isinstance(value, list):
            lines.append(f'{path or "/"}: array, {len(value)} entries')
            for child in value[:1]:
                if isinstance(child, (dict, list)):
                    visit(child, path + '/0', depth + 1)
    visit(payload, '')
    return '\n'.join(lines)


def format_signature(payload, records):
    """Compare field structure without storing any chat values in the signature."""
    if not records or isinstance(payload, dict) and '_text' in payload:
        return None
    def structure(value, depth=0):
        if depth > 5:
            return type(value).__name__
        if isinstance(value, dict):
            return {key: structure(value[key], depth + 1) for key in sorted(value)[:80]}
        if isinstance(value, list):
            return [structure(value[0], depth + 1)] if value else []
        return type(value).__name__
    shape = [structure(payload), [structure(record) for record in records[:3]]]
    return hashlib.sha256(json.dumps(shape, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _preview(value: Any, depth=0) -> Any:
    if depth > 6:
        return "[nested data omitted]"
    if isinstance(value, str):
        return value[:1000] + (" … [truncated]" if len(value) > 1000 else "")
    if isinstance(value, dict):
        return {str(k): _preview(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_preview(v, depth + 1) for v in value[:5]]
    return value


def make_sample(text: str, records: list[Any] | None = None) -> str:
    # Preserve only the first 20 lines and a reservoir of 300 later lines.
    # This avoids a second full in-memory list for large text exports.
    lines, later = [], []
    cursor, number = 0, 0
    rng = random.SystemRandom()
    while cursor < len(text):
        end = text.find("\n", cursor)
        if end < 0:
            end = len(text)
        line = text[cursor:end].rstrip("\r")
        if number < 20:
            lines.append(line)
        elif not records:
            if len(later) < 300:
                later.append((number, line[:1000]))
            else:
                index = rng.randrange(number - 19)
                if index < 300:
                    later[index] = (number, line[:1000])
        cursor = end + 1
        number += 1
        if records and number == 20:
            break
    # Reserve a separate budget for both portions. A one-line JSON export
    # must not consume the whole sample before the random records are seen.
    first = [line[:600] + (" … [truncated]" if len(line) > 600 else "") for line in lines[:20]]
    if records:
        indices = sorted(random.SystemRandom().sample(range(len(records)), min(300, len(records))))
        sampled = [f"[record {i + 1}] {json.dumps(_preview(records[i]), ensure_ascii=False, separators=(',', ':'))}" for i in indices]
    elif later:
        sampled = [f"[line {i + 1}] {line}" for i, line in sorted(later)]
    else:
        sampled = []
    header = "\n".join(f"[line {i + 1}] {line}" for i, line in enumerate(first))
    parts = [header, "--- random sample ---"]
    remaining = MAX_SAMPLE_CHARS - len("\n".join(parts)) - 100
    omitted = 0
    for item in sampled:
        if len(item) + 1 <= remaining:
            parts.append(item)
            remaining -= len(item) + 1
        else:
            omitted += 1
    if omitted:
        parts.append(f"[{omitted} sampled entries omitted to fit the sample size limit]")
    return "\n".join(parts)


def _valid_path(path: Any, limit: int) -> bool:
    if not isinstance(path, str) or len(path) > limit or any(ord(c) < 32 for c in path):
        return False
    if path.startswith("/"):
        return not re.search(r"~(?![01])", path)
    if path in {"", "$"}:
        return True
    # JSON pointers handle keys containing spaces, dots or punctuation.
    return bool(re.fullmatch(r"(?:\$\.)?[\w-]+(?:\.[\w-]+)*", path))


def validate_spec(spec: Any) -> dict[str, str]:
    if not isinstance(spec, dict):
        raise ValueError(tr("import.error.missing_mapping"))
    if spec.get("format") == "text":
        import regex
        pattern = spec.get("record_pattern")
        timestamp_format = spec.get("timestamp_format", "")
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 2000 or not pattern.startswith("^"):
            raise ValueError(tr("import.error.text_pattern"))
        if not isinstance(timestamp_format, str) or len(timestamp_format) > 100:
            raise ValueError(tr("import.error.date_format"))
        try:
            compiled = regex.compile(pattern, regex.MULTILINE)
        except regex.error:
            raise ValueError(tr("import.error.pattern_compile")) from None
        groups = compiled.groupindex
        if not {"text", "timestamp"}.issubset(groups) or not {"sender_id", "sender_name"}.intersection(groups):
            raise ValueError(tr("import.error.pattern_fields"))
        return {"format": "text", "record_pattern": pattern, "timestamp_format": timestamp_format,
                "messages_path": "", **{field: field if field in groups else "" for field in FIELDS}}
    messages_path = spec.get("messages_path", "")
    if not _valid_path(messages_path, 240):
        raise ValueError(tr("import.error.message_path"))
    result = {"messages_path": messages_path}
    for field in FIELDS:
        path = spec.get(field, "")
        if not _valid_path(path, 160):
            raise ValueError(tr("import.error.field_path", field=field))
        result[field] = path
    if not result["text"] or not (result["sender_id"] or result["sender_name"]) or not result["timestamp"]:
        raise ValueError(tr("import.error.missing_fields"))
    return result


def _timestamp_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        number = int(value)
        return number if abs(number) >= 100_000_000_000 else number * 1000
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return _timestamp_ms(int(raw))
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
        except (ValueError, OverflowError, OSError):
            return None
    return None


def convert(payload: Any, records: list[Any], spec: dict[str, str], title: str) -> dict[str, Any]:
    if spec.get("format") == "text":
        import regex
        text = payload.get("_text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise ValueError(tr("import.error.text_required"))
        source_records = []
        try:
            for match in regex.finditer(spec["record_pattern"], text, regex.MULTILINE, timeout=5):
                source_records.append(match.groupdict())
                if len(source_records) > MAX_MESSAGES:
                    raise ValueError(tr("import.error.text_limit"))
        except TimeoutError:
            raise ValueError(tr("import.error.pattern_timeout")) from None
    elif spec["messages_path"]:
        source_records = _get(payload, spec["messages_path"])
    else:
        source_records = records if isinstance(records, list) else []
    if not isinstance(source_records, list) or not source_records:
        raise ValueError(tr("import.error.empty_list"))
    if len(source_records) > MAX_MESSAGES:
        raise ValueError(tr('import.error.message_limit'))
    messages = []
    participants: dict[str, str] = {}
    for seq, raw in enumerate(source_records):
        if not isinstance(raw, dict):
            continue
        sender_name = _get(raw, spec["sender_name"]) if spec["sender_name"] else None
        sender_id = _get(raw, spec["sender_id"]) if spec["sender_id"] else None
        identity = sender_id if sender_id is not None and sender_id != "" else sender_name
        uid = str(identity).strip() if isinstance(identity, (str, int)) and not isinstance(identity, bool) else ""
        text = _get(raw, spec["text"])
        timestamp = _timestamp_ms(_get(raw, spec["timestamp"]))
        if timestamp is None and spec.get("timestamp_format"):
            try:
                timestamp = int(datetime.strptime(str(_get(raw, spec["timestamp"])), spec["timestamp_format"]).timestamp() * 1000)
            except (ValueError, OverflowError, OSError):
                pass
        if not uid or len(uid) > 240 or any(c in uid for c in "\r\n\0,") or not isinstance(text, str) or timestamp is None:
            continue
        name = str(sender_name or uid).strip()[:240] or uid
        participants.setdefault(uid, name)
        # The ID identifies message content across overlapping exports as well
        # as different files; duplicates within one export remain distinct.
        content = json.dumps([uid, timestamp, text], ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(content.encode()).hexdigest()[:32]
        kind = _get(raw, spec["kind"]) if spec["kind"] else "text"
        messages.append({"id": f"ai-{digest}", "seq": seq, "timestamp_ms": timestamp,
                         "sender_uid": uid, "sender_name": name, "kind": str(kind or "text"),
                         "text": text})
    if not messages or len(participants) < 2:
        raise ValueError(tr("import.error.no_conversation"))
    counts: dict[str, int] = {}
    for message in messages:
        identity = message["id"]
        duplicate = counts.get(identity, 0)
        counts[identity] = duplicate + 1
        if duplicate:
            message["id"] += f"-{duplicate}"
    return {"afterglow": {"format": "afterglow-chat", "version": "1.0"},
            "conversation": {"id": title, "type": "private"},
            "participants": [{"uid": uid, "name": name, "role": "unknown"} for uid, name in participants.items()],
            "messages": messages,
            "desktop_conversion": {"source_records": len(source_records), "converted_messages": len(messages),
                                   "skipped_records": len(source_records) - len(messages),
                                   **({'source_warning': payload['_source_warning']} if isinstance(payload, dict) and payload.get('_source_warning') else {})}}
