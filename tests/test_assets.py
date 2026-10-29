"""Deployment must fail closed on corrupted or unavailable binary assets."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.fetch_assets import destination, install_group, verified


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = b'checked binary content'
        self.entry = {'path': 'public/assets/test.png', 'sha256': hashlib.sha256(self.data).hexdigest(), 'size': len(self.data)}
        self.upstream = {'repository': 'twofly653/lingxi', 'commit': 'a' * 40}

    def tearDown(self):
        self.temp.cleanup()

    def test_checksum_rejects_same_length_corruption(self):
        path = self.root / 'asset'
        path.write_bytes(self.data)
        self.assertTrue(verified(path, self.entry))
        path.write_bytes(b'x' * len(self.data))
        self.assertFalse(verified(path, self.entry))

    def test_download_reuses_content_for_alias_and_installs_real_files(self):
        alias = {**self.entry, 'path': 'public/downloads/alias.bin'}
        with patch('tools.fetch_assets.urlopen', return_value=io.BytesIO(self.data)) as fetch:
            self.assertEqual(install_group(self.root, self.upstream, [self.entry, alias]), 2)
            self.assertEqual(fetch.call_count, 1)
        for entry in (self.entry, alias):
            self.assertTrue(verified(self.root / entry['path'], entry))
        with patch('tools.fetch_assets.urlopen', side_effect=AssertionError('must work offline')):
            self.assertEqual(install_group(self.root, self.upstream, [self.entry, alias]), 0)

    def test_corrupt_response_never_replaces_existing_asset(self):
        target = self.root / self.entry['path']
        target.parent.mkdir(parents=True)
        target.write_bytes(b'previous version')
        with patch('tools.fetch_assets.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'bad')), patch('tools.fetch_assets.time.sleep'):
            with self.assertRaises(ValueError):
                install_group(self.root, self.upstream, [self.entry])
        self.assertEqual(target.read_bytes(), b'previous version')
        self.assertEqual(list((self.root / '.asset-cache').glob('*.part')), [])

    def test_manifest_path_cannot_escape_project(self):
        with self.assertRaises(ValueError):
            destination(self.root, '../outside.bin')


if __name__ == '__main__':
    unittest.main()
