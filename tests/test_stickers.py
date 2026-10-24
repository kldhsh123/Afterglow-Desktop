import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from desktop_host.stickers import Stickers


class StickerTransportTests(unittest.TestCase):
    def setUp(self):
        self.manager = SimpleNamespace(core_request=Mock(return_value={'ok': True}))
        self.stickers = Stickers(self.manager)

    def test_original_core_owner_names_and_tag_limits_are_enforced(self):
        for owner in ['self', 'ai', 'shared']:
            self.stickers.dispatch('stickers_update', {'name': 'happy', 'owner': owner,
                                                      'description': 'A warm greeting', 'tags': ['greeting']})
            self.assertEqual(self.manager.core_request.call_args.kwargs['method'], 'PATCH')
        with self.assertRaises(ValueError):
            self.stickers.dispatch('stickers_update', {'name': 'happy', 'owner': 'friend', 'description': 'No'})

    def test_sticker_names_cannot_be_used_as_paths(self):
        for name in ['../secret', 'happy/image', 'invalid:name', 'x' * 33]:
            with self.assertRaises(ValueError):
                self.stickers.dispatch('stickers_delete', {'name': name})
        self.manager.core_request.assert_not_called()

    def test_upload_keeps_gif_bytes_and_does_not_call_a_vision_model(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'wave.gif'
            image.write_bytes(b'GIF89a\x01\x00\x01\x00')
            self.stickers.dispatch('stickers_create', {'name': 'wave', 'description': 'Greeting',
                                                      'owner': 'self', 'path': str(image)})
            endpoint, payload = self.manager.core_request.call_args.args
            self.assertEqual(endpoint, '/v1/stickers')
            self.assertTrue(payload['data_url'].startswith('data:image/gif;base64,'))

    def test_oversize_images_never_reach_the_core(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'large.gif'
            image.write_bytes(b'GIF89a' + b'x' * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                self.stickers.dispatch('stickers_create', {'name': 'large', 'description': 'Too big',
                                                          'owner': 'shared', 'path': str(image)})
            self.manager.core_request.assert_not_called()
