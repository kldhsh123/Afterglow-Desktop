import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from desktop_host.chat_store import ChatStore


class ConversationManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ChatStore(self.root)

    def test_newest_conversation_can_be_deleted_but_last_one_is_kept(self):
        first = self.store.create()['id']
        newest = self.store.create()['id']
        self.store.delete(newest)
        self.assertEqual([item['id'] for item in self.store.list()], [first])
        with self.assertRaises(ValueError):
            self.store.delete(first)
        self.assertEqual(self.store.get(first)['turns'], [])

    def test_renamed_title_survives_new_messages_and_store_restart(self):
        key = self.store.create()['id']
        self.store.rename(key, '  我的会话  ')
        self.store.begin(key, str(uuid.uuid4()), 'Hello')
        self.assertEqual(ChatStore(self.root).get(key)['title'], '我的会话')

    def test_rename_rejects_empty_overlong_and_invalid_values(self):
        key = self.store.create()['id']
        for title in ['', '   ', 'a' * 81, None, 123]:
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.store.rename(key, title)

    def test_move_order_survives_messages_and_restart(self):
        first, second, third = [self.store.create()['id'] for _ in range(3)]
        self.store.move(first, 'up')
        self.assertEqual([item['id'] for item in self.store.list()], [third, first, second])
        self.store.move(third, 'down')
        self.store.begin(second, str(uuid.uuid4()), 'New message')
        self.assertEqual([item['id'] for item in ChatStore(self.root).list()], [first, third, second])
        self.assertEqual(self.store.create()['id'], self.store.list()[0]['id'])

    def test_move_boundaries_and_invalid_arguments(self):
        first, second = [self.store.create()['id'] for _ in range(2)]
        self.store.move(second, 'up')
        self.store.move(first, 'down')
        self.assertEqual([item['id'] for item in self.store.list()], [second, first])
        for direction in ['sideways', None, 1]:
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                self.store.move(first, direction)
        with self.assertRaises(ValueError):
            self.store.move(str(uuid.uuid4()), 'up')

    def test_delete_removes_turns_and_keeps_other_conversations(self):
        retained, removed = [self.store.create()['id'] for _ in range(2)]
        self.store.begin(removed, str(uuid.uuid4()), 'Deleted message')
        self.store.delete(removed)
        self.assertEqual(self.store.get(retained)['turns'], [])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0], 0)

    def test_existing_database_migrates_in_its_original_display_order(self):
        older, newer = str(uuid.uuid4()), str(uuid.uuid4())
        legacy = self.root / 'legacy'
        legacy.mkdir()
        with sqlite3.connect(legacy / 'desktop-chat.sqlite3') as db:
            db.execute('CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)')
            db.execute('INSERT INTO conversations VALUES (?, ?, 1, 1)', (older, 'Older'))
            db.execute('INSERT INTO conversations VALUES (?, ?, 2, 2)', (newer, 'Newer'))
        store = ChatStore(legacy)
        self.assertEqual([item['id'] for item in store.list()], [newer, older])
        store.move(older, 'up')
        self.assertEqual([item['id'] for item in ChatStore(legacy).list()], [older, newer])
