# -*- coding: utf-8 -*-
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.update_release_checksum import update_checksum


class ReleaseChecksumToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.zip_path = self.root / "CoNgu_v9.9.9_Portable.zip"
        self.zip_path.write_bytes(b"fake portable release")
        self.version_path = self.root / "version.json"
        self.version_path.write_text(json.dumps({
            "version": "9.9.9",
            "portable_zip_url": "https://example.invalid/CoNgu_v9.9.9_Portable.zip",
        }), encoding="utf-8")

    def test_write_persists_correct_sha256(self):
        digest, _ = update_checksum(str(self.zip_path), str(self.version_path), write=True)
        metadata = json.loads(self.version_path.read_text(encoding="utf-8"))
        self.assertEqual(digest, hashlib.sha256(b"fake portable release").hexdigest())
        self.assertEqual(metadata["portable_zip_sha256"], digest)

    def test_rejects_artifact_different_from_metadata_url(self):
        wrong = self.root / "other.zip"
        wrong.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "không khớp"):
            update_checksum(str(wrong), str(self.version_path), write=True)
        metadata = json.loads(self.version_path.read_text(encoding="utf-8"))
        self.assertNotIn("portable_zip_sha256", metadata)


if __name__ == "__main__":
    unittest.main()
