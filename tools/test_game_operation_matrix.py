# -*- coding: utf-8 -*-
"""Ma trận thao tác trên game giả: cài lần đầu, cài lại, cập nhật, gỡ, lỗi giữa pipeline."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backup_rollback import inplace_backup, manifest_manager
from core.installer_pipeline import actions, pipeline_runner
from core.installer_pipeline.pipeline_runner import execute_action_pipeline, has_pending_transaction


class GameOperationMatrixTests(unittest.TestCase):
    GAME_ID = "fake-game"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-op-matrix-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.source = self.root / "source"
        self.backups = self.root / "backups"
        self.game.mkdir()
        self.source.mkdir()
        self.original = b"original english data"
        self.game_file = self.game / "data.bin"
        self.game_file.write_bytes(self.original)
        (self.source / "data.bin").write_bytes(b"mod v1")
        (self.source / "extra.dat").write_bytes(b"extra v1")

        self._patchers = [
            patch.object(pipeline_runner, "BACKUP_ROOT", str(self.backups)),
            patch.object(actions, "BACKUP_ROOT", str(self.backups)),
            patch.object(manifest_manager, "BACKUP_ROOT", str(self.backups)),
            patch.object(inplace_backup, "BACKUP_ROOT", str(self.backups)),
        ]
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def install_steps(self):
        return [
            {"action": "backup", "target": "data.bin"},
            {"action": "copy_file", "source": "data.bin", "destination": "data.bin"},
            {"action": "copy_file", "source": "extra.dat", "destination": "extra.dat"},
        ]

    def uninstall_steps(self):
        return [
            {"action": "restore_backup", "target": "data.bin"},
            {"action": "delete", "target": "extra.dat"},
        ]

    def install(self):
        return execute_action_pipeline(
            self.GAME_ID, str(self.game), str(self.source), self.install_steps(), operation="install"
        )

    def test_first_install_backs_up_original_and_copies_mod(self):
        self.assertTrue(self.install())

        self.assertEqual(self.game_file.read_bytes(), b"mod v1")
        self.assertEqual(Path(str(self.game_file) + ".congu_bak").read_bytes(), self.original)
        self.assertEqual((self.game / "extra.dat").read_bytes(), b"extra v1")
        self.assertFalse(has_pending_transaction(self.GAME_ID))

    def test_reinstall_keeps_original_backup_and_updates_files(self):
        self.install()
        (self.source / "data.bin").write_bytes(b"mod v2")

        self.assertTrue(self.install())

        self.assertEqual(self.game_file.read_bytes(), b"mod v2")
        self.assertEqual(
            Path(str(self.game_file) + ".congu_bak").read_bytes(),
            self.original,
            "bản gốc tiếng Anh bị ghi đè khi cài lại",
        )
        self.assertFalse(has_pending_transaction(self.GAME_ID))

    def test_uninstall_restores_original_and_removes_mod_files(self):
        self.install()

        result = execute_action_pipeline(
            self.GAME_ID, str(self.game), str(self.source), self.uninstall_steps(), operation="uninstall"
        )

        self.assertTrue(result)
        self.assertEqual(self.game_file.read_bytes(), self.original)
        self.assertFalse((self.game / "extra.dat").exists())
        self.assertFalse(Path(str(self.game_file) + ".congu_bak").exists())

    def test_failure_mid_install_rolls_back_every_change(self):
        steps = self.install_steps()
        steps[2]["source"] = "missing.dat"

        with self.assertRaises(RuntimeError):
            execute_action_pipeline(self.GAME_ID, str(self.game), str(self.source), steps, operation="install")

        self.assertEqual(self.game_file.read_bytes(), self.original)
        self.assertFalse((self.game / "extra.dat").exists())
        self.assertFalse(Path(str(self.game_file) + ".congu_bak").exists())
        self.assertFalse(has_pending_transaction(self.GAME_ID))

    def test_locked_destination_rolls_back_previous_step(self):
        real_copy2 = shutil.copy2

        def flaky_copy2(src, dst, *args, **kwargs):
            if Path(str(dst)).name == "extra.dat":
                raise PermissionError("file is locked")
            return real_copy2(src, dst, *args, **kwargs)

        with patch.object(actions.shutil, "copy2", side_effect=flaky_copy2):
            with self.assertRaises(RuntimeError):
                execute_action_pipeline(
                    self.GAME_ID,
                    str(self.game),
                    str(self.source),
                    [
                        {"action": "backup", "target": "data.bin"},
                        {"action": "copy_file", "source": "data.bin", "destination": "data.bin"},
                        {"action": "copy_file", "source": "extra.dat", "destination": "extra.dat"},
                    ],
                    operation="install",
                )

        self.assertEqual(self.game_file.read_bytes(), self.original)
        self.assertFalse(Path(str(self.game_file) + ".congu_bak").exists())
        self.assertFalse((self.game / "extra.dat").exists())
        self.assertFalse(has_pending_transaction(self.GAME_ID))

    def test_uninstall_keeps_steam_updated_file(self):
        self.install()
        steam_update = b"steam updated the game file"
        self.game_file.write_bytes(steam_update)

        execute_action_pipeline(
            self.GAME_ID, str(self.game), str(self.source), self.uninstall_steps(), operation="uninstall"
        )

        self.assertEqual(
            self.game_file.read_bytes(),
            steam_update,
            "restore đã ghi đè file game mới của Steam/Epic",
        )
        self.assertFalse(Path(str(self.game_file) + ".congu_bak").exists())

    def test_pending_journal_blocks_new_install(self):
        journal = self.backups / self.GAME_ID / "pending_transaction.json"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({"version": 1}), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "journal"):
            self.install()

        self.assertEqual(self.game_file.read_bytes(), self.original)
        self.assertFalse((self.game / "extra.dat").exists())


if __name__ == "__main__":
    unittest.main()
