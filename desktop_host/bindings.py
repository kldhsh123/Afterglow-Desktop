"""Per-instance channel authorization, shared by the manager and worker processes."""
from __future__ import annotations

from contextlib import contextmanager
import secrets
import sqlite3
import time
from pathlib import Path


class BindingStore:
    TTL = 600

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS contacts (
                    uid TEXT PRIMARY KEY, authorized INTEGER NOT NULL DEFAULT 0,
                    code TEXT, created_at REAL NOT NULL, name TEXT NOT NULL DEFAULT ''
                );
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _uid(uid):
        if not isinstance(uid, str) or not uid or len(uid) > 240 or any(ord(c) < 32 for c in uid):
            raise ValueError("Invalid contact ID")
        return uid

    def authorized(self, uid):
        self._uid(uid)
        with self._connect() as connection:
            row = connection.execute("SELECT authorized FROM contacts WHERE uid=?", (uid,)).fetchone()
        return bool(row and row[0])

    def request(self, uid, name=""):
        self._uid(uid)
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM contacts WHERE authorized=0 AND created_at<?", (now - self.TTL,))
            row = connection.execute("SELECT * FROM contacts WHERE uid=?", (uid,)).fetchone()
            if row:
                return "" if row["authorized"] else row["code"]
            if connection.execute("SELECT COUNT(*) FROM contacts WHERE authorized=0").fetchone()[0] >= 100:
                return ""
            code = f"{secrets.randbelow(1_000_000):06d}"
            connection.execute("INSERT INTO contacts(uid, code, created_at, name) VALUES(?,?,?,?)",
                               (uid, code, now, str(name)[:80]))
        return code

    def approve(self, uid, code):
        self._uid(uid)
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError("Invalid binding code")
        with self._connect() as connection:
            cursor = connection.execute("""UPDATE contacts SET authorized=1, code=NULL
                WHERE uid=? AND code=? AND authorized=0 AND created_at>=?""", (uid, code, time.time() - self.TTL))
            if cursor.rowcount != 1:
                raise ValueError("Binding code expired or does not match")

    def trust_owner(self, uid):
        self._uid(uid)
        with self._connect() as connection:
            connection.execute("""INSERT INTO contacts(uid, authorized, created_at) VALUES(?,1,?)
                ON CONFLICT(uid) DO UPDATE SET authorized=1, code=NULL""", (uid, time.time()))

    def revoke(self, uid):
        self._uid(uid)
        with self._connect() as connection:
            connection.execute("DELETE FROM contacts WHERE uid=?", (uid,))

    def list(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM contacts WHERE authorized=1 OR created_at>=? ORDER BY created_at DESC",
                                      (time.time() - self.TTL,)).fetchall()
        return [{"uid": row["uid"], "name": row["name"], "authorized": bool(row["authorized"]),
                 "code": row["code"] or "", "createdAt": row["created_at"]} for row in rows]
