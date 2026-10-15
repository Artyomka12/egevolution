import hashlib
import json
import struct
import zlib
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock
from test_thematic_admin import AdminTests
from features.thematic import media, repository
from features.thematic.bank import safe_path


class MediaTests(AdminTests):
    # Inherit fixtures, not the HTTP test suite (loader filters below).
    def test_media_snapshots_survive_bank_mutation(self):
        image_dir = self.bank / 'task_01/images'
        image_dir.mkdir()
        image = image_dir / 'pixel.png'
        def chunk(kind, value):
            return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))
        original = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff')) + chunk(b'IEND', b'')
        image.write_bytes(original)
        source = json.loads(self.source.read_text())
        source['tasks'][0]['images'] = [{'path': 'pixel.png', 'alt': 'Historical caption', 'after_paragraph': 0}]
        self.source.write_text(json.dumps(source), encoding='utf-8')
        result = self.publish(self.create())
        self.assertEqual(result.status_code, 200, result.text)
        db = self.open()
        version = repository.get_version(db, result.json['version_id'])
        material = version['items'][0]['snapshot']['materials'][0]
        self.assertEqual(material['alt_text'], 'Historical caption')
        private = self.root / 'private-media' / hashlib.sha256(original).hexdigest()
        self.assertEqual(private.read_bytes(), original)
        image.write_bytes(b'changed bank')
        response = self.call(f'/api/admin/thematic-variants/{result.json["draft"]["id"]}/media/{material["media_id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, original)
        response.close()
        self.assertEqual(repository.get_version(db, version['id']), version)
        with self.assertRaises(ValueError):
            media.stage(self.root / 'private-media', image, True)

    def test_paths_formats_and_private_integrity(self):
        outside = self.root / 'outside.txt'
        outside.write_text('outside')
        for name in ['../outside.txt', str(outside), 'C:\\fake.png']:
            with self.assertRaises((ValueError, FileNotFoundError)):
                safe_path(self.bank, name)
        with self.assertRaises(ValueError):
            media.inspect_bytes(b'<svg onload="alert(1)"></svg>', 'image.svg', True)
        with self.assertRaises(ValueError):
            media.inspect_bytes(b'<html>not xlsx</html>', 'test.xlsx')
        # One real bank attachment is OOXML with a legacy .xls filename.
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('[Content_Types].xml', '<Types/>')
        self.assertEqual(media.inspect_bytes(archive.getvalue(), 'legacy.xls')[0], 'application/octet-stream')
        info = media.stage(self.root / 'private', outside)
        (self.root / 'private' / info['storage_key']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            media.stage(self.root / 'private', outside)


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(MediaTests(name) for name in MediaTests.__dict__ if name.startswith('test_'))
