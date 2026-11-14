# -*- coding: utf-8 -*-
"""Regression: khóa thao tác phải độc lập theo game, không phải một khóa toàn cục."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.installer_pipeline.pipeline_runner import get_game_operation_lock
from core.installer_pipeline import install_ops, pipeline_runner


class GameOperationLockTests(unittest.TestCase):
    def test_pending_journal_blocks_all_wrappers_without_touching_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "backups" / "test-game" / "pending_transaction.json"
            journal.parent.mkdir(parents=True)
            journal.write_bytes(b"broken journal")
            with patch.object(pipeline_runner, "BACKUP_ROOT", str(root / "backups")), \
                 patch.object(install_ops, "install_mod_impl") as install, \
                 patch.object(install_ops, "uninstall_mod_impl") as uninstall, \
                 patch.object(install_ops, "deep_emergency_restore") as restore:
                for wrapper in (install_ops.install_mod, install_ops.uninstall_mod, install_ops.emergency_restore_game):
                    result = wrapper("test-game")
                    self.assertFalse(result["success"])
                    self.assertTrue(result["recovery_required"])
                install.assert_not_called()
                uninstall.assert_not_called()
                restore.assert_not_called()
            self.assertEqual(journal.read_bytes(), b"broken journal")

    def test_wrappers_dispatch_when_no_journal(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(pipeline_runner, "BACKUP_ROOT", directory), \
             patch.object(install_ops, "install_mod_impl", return_value={"success": True}) as install:
            self.assertTrue(install_ops.install_mod("test-game")["success"])
            install.assert_called_once()

    def test_same_game_returns_same_lock(self):
        self.assertIs(get_game_operation_lock("same-game"), get_game_operation_lock("same-game"))

    def test_same_game_cannot_acquire_twice_concurrently(self):
        lock = get_game_operation_lock("busy-game")
        self.assertTrue(lock.acquire(blocking=False))
        try:
            self.assertFalse(get_game_operation_lock("busy-game").acquire(blocking=False))
        finally:
            lock.release()

    def test_different_games_have_independent_locks(self):
        first = get_game_operation_lock("game-a")
        second = get_game_operation_lock("game-b")
        self.assertTrue(first.acquire(blocking=False))
        try:
            self.assertTrue(second.acquire(blocking=False))
            second.release()
        finally:
            first.release()


if __name__ == "__main__":
    unittest.main()
