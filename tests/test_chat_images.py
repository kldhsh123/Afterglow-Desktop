import base64
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import Mock

from desktop_host.chat_images import ChatImages, image_data, read_sources
from desktop_host.chat_store import ChatStore
from desktop_host.host import Manager


JPEG = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xff\xe0test-image\xff\xd9').decode()


class ChatImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = Manager.__new__(Manager)
        self.host.root = self.root
        self.host.chat_store = ChatStore(self.root)
        self.host.chat_images = ChatImages(self.root)
        self.host.identity_needs_restart = Mock(return_value=False)
        self.host.settings = Mock(return_value={'services': {'vision': 'main'}})
        self.host.redact = lambda message: message
        self.host.core_request = Mock(return_value={'choices': [{'message': {'content': 'An image reply'}}]})
        self.conversation = self.host.chat_store.create()['id']
        self.request = {'conversationId': self.conversation, 'requestId': str(uuid.uuid4()), 'content': '',
                        'attachments': [{'name': 'photo.jpg', 'dataUrl': JPEG, 'preview': JPEG}]}

    def test_image_only_message_reaches_original_core_and_survives_restart(self):
        self.host.send_chat(self.request)
        content = self.host.core_request.call_args.args[1]['messages'][-1]['content']
        self.assertEqual(content, [{'type': 'image_url', 'image_url': {'url': JPEG}}])
        store = ChatStore(self.root)
        turn = store.get(self.conversation)['turns'][0]
        self.assertEqual(turn['reply'], 'An image reply')
        self.assertEqual(turn['attachments'][0]['preview'], JPEG)
        self.assertNotIn('dataUrl', turn['attachments'][0])
        self.assertTrue(store.list()[0]['title'])
        self.assertTrue(store.history(self.conversation)[0]['content'])
        # Repeating a completed request must not issue another model call.
        self.host.send_chat(self.request)
        self.assertEqual(self.host.core_request.call_count, 1)

    def test_failed_image_request_can_retry_with_persisted_metadata(self):
        self.host.core_request.side_effect = ValueError('connection failed')
        with self.assertRaises(ValueError): self.host.send_chat(self.request)
        turn = self.host.chat_store.get(self.conversation)['turns'][0]
        self.assertEqual(turn['state'], 'failed')
        self.request['attachments'] = turn['attachments']
        self.host.core_request.side_effect = None
        self.host.send_chat(self.request)
        self.assertEqual(self.host.chat_store.get(self.conversation)['turns'][0]['state'], 'completed')

    def test_disabled_vision_and_invalid_images_never_reach_core(self):
        self.host.settings.return_value = {'services': {'vision': 'off'}}
        with self.assertRaises(ValueError): self.host.send_chat(self.request)
        self.host.settings.return_value = {'services': {'vision': 'main'}}
        for attachments in (
            self.request['attachments'] * 5,
            [{'name': 'unsafe.svg', 'dataUrl': 'https://example.test/image.jpg', 'preview': JPEG}],
            [{'id': '../../outside', 'name': 'photo.jpg', 'preview': JPEG}],
        ):
            with self.subTest(attachments=attachments), self.assertRaises(ValueError):
                self.host.send_chat({**self.request, 'attachments': attachments})
        self.host.core_request.assert_not_called()
        self.assertEqual(self.host.chat_store.get(self.conversation)['turns'], [])

    def test_images_are_scoped_to_conversation_and_removed_with_it(self):
        saved = self.host.chat_images.save(self.conversation, self.request['attachments'])
        other = self.host.chat_store.create()['id']
        with self.assertRaises(ValueError): self.host.chat_images.save(other, saved)
        self.host.dispatch('delete_conversation', {'id': self.conversation})
        self.assertFalse((self.root / 'chat-images' / self.conversation).exists())

    def test_source_file_type_and_encoded_size_are_bounded(self):
        source = self.root / 'image.jpg'
        source.write_bytes(image_data(JPEG))
        self.assertEqual(read_sources([str(source)])['images'][0]['dataUrl'], JPEG)
        source.write_text('<svg onload="alert(1)"></svg>')
        with self.assertRaises(ValueError): read_sources([str(source)])
        with self.assertRaises(ValueError): image_data(JPEG, 3)

    def test_existing_text_history_migrates_without_losing_messages(self):
        legacy = self.root / 'legacy'
        legacy.mkdir()
        with sqlite3.connect(legacy / 'desktop-chat.sqlite3') as database:
            database.executescript('''CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
                CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, content TEXT NOT NULL, reply TEXT, response TEXT, state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);''')
            database.execute('INSERT INTO conversations VALUES (?, ?, 1, 1)', (self.conversation, 'Original'))
            database.execute('INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, 1)', (self.request['requestId'], self.conversation, 'Hello', 'Hi', '{}', 'completed', ''))
        database.close()
        store = ChatStore(legacy)
        self.assertEqual(store.get(self.conversation)['turns'][0]['content'], 'Hello')
        self.assertEqual(store.get(self.conversation)['turns'][0]['attachments'], [])
