# -*- coding: utf-8 -*-
"""Path boundary regressions for destructive/data-writing pipeline actions."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.installer_pipeline.actions import execute_pipeline_step


class PipelineActionPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-action-path-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.source = self.root / "source"
        self.outside = self.root / "outside"
        self.game.mkdir()
        self.source.mkdir()
        self.outside.mkdir()
        self.protected = self.outside / "protected.dat"
        self.protected.write_bytes(b"outside data")

    def assert_rejected(self, step):
        with self.assertRaises(Exception):
            execute_pipeline_step("fake-game", str(self.game), str(self.source), step)
        self.assertEqual(self.protected.read_bytes(), b"outside data")

    def test_delete_rejects_parent_traversal_and_drive_path(self):
        for target in ("../outside/protected.dat", str(self.protected), "Z:/outside/protected.dat"):
            with self.subTest(target=target):
                self.assert_rejected({"action": "delete", "target": target})

    def test_rename_rejects_outside_source_or_destination(self):
        inside = self.game / "inside.dat"
        inside.write_bytes(b"inside")
        self.assert_rejected({"action": "rename", "source": str(self.protected), "destination": "inside.dat"})
        self.assert_rejected({"action": "rename", "source": "inside.dat", "destination": "../outside/renamed.dat"})
        self.assertTrue(inside.exists())

    def test_patch_ini_rejects_outside_target(self):
        self.assert_rejected({"action": "patch_ini", "file": "../outside/protected.dat", "section": "x", "key": "k", "value": "v"})

    def test_copy_file_rejects_outside_destination(self):
        payload = self.source / "payload.dat"
        payload.write_bytes(b"new")
        self.assert_rejected({"action": "copy_file", "source": "payload.dat", "destination": "../outside/protected.dat"})

    def test_extract_zip_rejects_zip_slip(self):
        package = self.source / "payload.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("../outside/protected.dat", b"overwritten")
        with self.assertRaises(Exception):
            execute_pipeline_step("fake-game", str(self.game), str(self.source), {
                "action": "extract_zip", "source": "payload.zip", "destination": "content"
            })
        self.assertEqual(self.protected.read_bytes(), b"outside data")


if __name__ == "__main__":
    unittest.main()
