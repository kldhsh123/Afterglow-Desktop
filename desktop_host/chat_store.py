"""Desktop conversation persistence; generation stays in the original core."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

try:
    from .i18n import tr
except ImportError:
    from i18n import tr


def valid_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class ChatStore:
    def __init__(self, root: Path):
        self.path = root / "desktop-chat.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    content TEXT NOT NULL, reply TEXT, response TEXT,
                    state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_by_conversation ON turns(conversation_id, created_at);
            """)
            if 'attachments' not in {row['name'] for row in db.execute('PRAGMA table_info(turns)')}:
                db.execute("ALTER TABLE turns ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'")
            if 'position' not in {row['name'] for row in db.execute('PRAGMA table_info(conversations)')}:
                db.execute('ALTER TABLE conversations ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
                existing = list(db.execute('SELECT id FROM conversations ORDER BY updated_at DESC, rowid DESC'))
                db.executemany('UPDATE conversations SET position = ? WHERE id = ?',
                               [(len(existing) - index, row['id']) for index, row in enumerate(existing)])
            # A pending turn cannot survive a manager restart as an active request.
            db.execute("UPDATE turns SET state = 'failed', error = '' WHERE state = 'pending'")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def create(self):
        key, now = str(uuid.uuid4()), time.time_ns() // 1_000_000
        with self.connection() as db:
            db.execute("INSERT INTO conversations(id, title, created_at, updated_at, position) SELECT ?, '', ?, ?, COALESCE(MAX(position), 0) + 1 FROM conversations", (key, now, now))
        return self.get(key)

    def list(self):
        with self.connection() as db:
            rows = db.execute("SELECT id, title, created_at, updated_at FROM conversations ORDER BY position DESC, rowid DESC LIMIT 500")
            return [dict(row) for row in rows]

    def get(self, key):
        if not valid_uuid(key):
            raise ValueError(tr("host.invalid_conversation_id"))
        with self.connection() as db:
            row = db.execute("SELECT * FROM conversations WHERE id = ?", (key,)).fetchone()
            if row is None:
                raise ValueError(tr("chat.not_found"))
            turns = db.execute("SELECT id, content, reply, state, error, created_at, attachments FROM (SELECT rowid AS position, * FROM turns WHERE conversation_id = ? ORDER BY rowid DESC LIMIT 500) ORDER BY position", (key,))
            return {**dict(row), "turns": [{**dict(turn), 'attachments': json.loads(turn['attachments'])} for turn in turns]}

    def begin(self, key, request_id, content, attachments=None):
        attachments = attachments or []
        encoded = json.dumps(attachments, ensure_ascii=False)
        if not valid_uuid(request_id) or not isinstance(content, str) or (not content.strip() and not attachments) or len(content) > 16000:
            raise ValueError(tr("host.enter_a_message_of_16000_characters_or_fewer"))
        self.get(key)
        with self.connection() as db:
            previous = db.execute("SELECT * FROM turns WHERE id = ?", (request_id,)).fetchone()
            if previous is not None:
                if previous["conversation_id"] != key or previous["content"] != content or previous['attachments'] != encoded:
                    raise ValueError(tr("chat.request_mismatch"))
                if previous["state"] == "completed":
                    return json.loads(previous["response"])
                if previous["state"] == "pending":
                    raise ValueError(tr("chat.already_sending"))
                later = db.execute("SELECT 1 FROM turns WHERE conversation_id = ? AND rowid > (SELECT rowid FROM turns WHERE id = ?) LIMIT 1", (key, request_id)).fetchone()
                if later:
                    raise ValueError(tr("chat.retry_latest"))
                db.execute("UPDATE turns SET state = 'pending', error = '' WHERE id = ?", (request_id,))
            else:
                now = time.time_ns() // 1_000_000
                db.execute("INSERT INTO turns(id, conversation_id, content, state, created_at, attachments) VALUES (?, ?, ?, 'pending', ?, ?)", (request_id, key, content, now, encoded))
                db.execute("UPDATE conversations SET title = CASE WHEN title = '' THEN ? ELSE title END, updated_at = ? WHERE id = ?", (content[:60] or tr('chat.image_message'), now, key))
        return None

    def history(self, key):
        with self.connection() as db:
            turns = list(db.execute("SELECT content, reply, attachments FROM turns WHERE conversation_id = ? AND state = 'completed' ORDER BY rowid DESC LIMIT 200", (key,)))
        messages, size = [], 0
        for turn in turns:
            content = turn['content']
            if json.loads(turn['attachments']):
                content += '\n' + tr('chat.image_message')
            chunk = [{"role": "user", "content": content}]
            if turn["reply"]:
                chunk.append({"role": "assistant", "content": turn["reply"]})
            size += sum(len(m["content"]) for m in chunk)
            if size > 200_000:
                break
            messages[0:0] = chunk
        return messages

    def complete(self, request_id, response):
        silent = response.get("policy", {}).get("should_reply") is False
        choices = response.get("choices") or []
        reply = choices[0].get("message", {}).get("content") if choices else None
        if not silent and (not isinstance(reply, str) or not reply.strip()):
            raise ValueError(tr("ui.the_core_returned_no_text_reply"))
        with self.connection() as db:
            db.execute("UPDATE turns SET state = 'completed', reply = ?, response = ?, error = '' WHERE id = ?", (None if silent else reply, json.dumps(response, ensure_ascii=False), request_id))

    def fail(self, request_id, error):
        with self.connection() as db:
            db.execute("UPDATE turns SET state = 'failed', error = ? WHERE id = ? AND state = 'pending'", (error[:2000], request_id))

    def delete(self, key):
        if not valid_uuid(key):
            raise ValueError(tr('host.invalid_conversation_id'))
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM conversations WHERE id = ?', (key,)).fetchone() is None:
                raise ValueError(tr('chat.not_found'))
            if db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] <= 1:
                raise ValueError(tr('chat.keep_last'))
            db.execute("DELETE FROM conversations WHERE id = ?", (key,))

    def rename(self, key, title):
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 80:
            raise ValueError(tr('chat.invalid_title'))
        self.get(key)
        with self.connection() as db:
            db.execute('UPDATE conversations SET title = ? WHERE id = ?', (title.strip(), key))
        return self.get(key)

    def move(self, key, direction):
        if not valid_uuid(key):
            raise ValueError(tr('host.invalid_conversation_id'))
        if direction not in ('up', 'down'):
            raise ValueError(tr('chat.invalid_move'))
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = list(db.execute('SELECT id, position FROM conversations ORDER BY position DESC, rowid DESC'))
            index = next((index for index, row in enumerate(rows) if row['id'] == key), None)
            if index is None:
                raise ValueError(tr('chat.not_found'))
            target = index + (-1 if direction == 'up' else 1)
            if 0 <= target < len(rows):
                current, neighbour = rows[index], rows[target]
                db.executemany('UPDATE conversations SET position = ? WHERE id = ?',
                               [(neighbour['position'], current['id']), (current['position'], neighbour['id'])])
        return {'ok': True}
