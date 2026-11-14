# -*- coding: utf-8 -*-
"""Regression: journal bền vững giúp phát hiện/khôi phục install bị gián đoạn."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from core.backup_rollback import save_backup_manifest
from core.installer_pipeline import pipeline_runner


class PipelineCrashRecoveryTests(unittest.TestCase):
    def test_pending_journal_detection_preserves_game_backup_and_manifest(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            root = Path(root)
            game = root / "game"
            game.mkdir()
            target = game / "data.bin"
            target.write_bytes(b"interrupted mod")
            backup = Path(str(target) + ".congu_bak")
            backup.write_bytes(b"original game")
            backup_root = str(root / "backups")
            game_id = "fake-game"
            save_backup_manifest(game_id, {
                "game_id": game_id,
                "backup_type": "inplace",
                "files": [{"relative_in_game": "data.bin", "modded_sha256": ""}],
            }, backup_root=backup_root)
            pipeline_runner._save_transaction_journal(game_id, {
                "version": 1, "game_id": game_id, "game_path": str(game),
                "operation": "install", "status": "running", "completed_steps": 1,
            }, backup_root=backup_root)
            self.assertEqual(pipeline_runner.get_pending_transaction(game_id, backup_root)["completed_steps"], 1)
            self.assertTrue(Path(pipeline_runner._transaction_journal_path(game_id, backup_root)).exists())

            result = pipeline_runner.recover_pending_transaction(game_id, str(game), backup_root=backup_root)
            self.assertFalse(result["success"])
            self.assertFalse(result["recovered"])
            self.assertEqual(target.read_bytes(), b"interrupted mod")
            self.assertEqual(backup.read_bytes(), b"original game")
            self.assertTrue(pipeline_runner.get_pending_transaction(game_id, backup_root))
            self.assertTrue((Path(backup_root) / game_id / "backup_manifest.json").exists())

    def test_recovery_without_restored_backup_keeps_journal(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            game = Path(root) / "game"
            game.mkdir()
            backup_root = str(Path(root) / "backups")
            pipeline_runner._save_transaction_journal("orphaned", {
                "version": 1, "game_id": "orphaned", "operation": "install", "status": "running"
            }, backup_root=backup_root)
            with patch("core.installer_pipeline.pipeline_runner.restore_files_inplace", return_value=False):
                result = pipeline_runner.recover_pending_transaction("orphaned", str(game), backup_root=backup_root)
            self.assertFalse(result["success"])
            self.assertTrue(pipeline_runner.get_pending_transaction("orphaned", backup_root))

    def test_successful_pipeline_removes_pending_journal(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            root = Path(root)
            game = root / "game"
            game.mkdir()
            with patch("core.installer_pipeline.pipeline_runner.BACKUP_ROOT", str(root / "backups")), \
                 patch("core.installer_pipeline.pipeline_runner.execute_pipeline_step", return_value={"action": "copy_file"}):
                self.assertTrue(pipeline_runner.execute_action_pipeline(
                    "successful-game", str(game), str(root), [{"action": "copy_file"}]
                ))
                self.assertEqual(pipeline_runner.get_pending_transaction("successful-game"), {})

    def test_rollback_failure_keeps_pending_journal(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            root = Path(root)
            game = root / "game"
            game.mkdir()
            (game / "data.bin").write_bytes(b"modded")
            (game / "data.bin.congu_bak").write_bytes(b"original")
            results = [
                {"action": "backup", "target": "data.bin", "created_new_bak": True},
                RuntimeError("simulated failure"),
            ]

            def fake_step(*_args, **_kwargs):
                value = results.pop(0)
                if isinstance(value, Exception):
                    raise value
                return value

            real_replace = __import__("os").replace

            def fail_rollback_replace(source, destination):
                if ".pending-transaction-" in str(source):
                    return real_replace(source, destination)
                raise PermissionError("locked")

            with patch("core.installer_pipeline.pipeline_runner.BACKUP_ROOT", str(root / "backups")), \
                 patch("core.installer_pipeline.pipeline_runner.execute_pipeline_step", side_effect=fake_step), \
                 patch("core.installer_pipeline.pipeline_runner.os.replace", side_effect=fail_rollback_replace), \
                 patch("core.installer_pipeline.pipeline_runner.shutil.copy2", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(RuntimeError, "CHƯA hoàn tất"):
                    pipeline_runner.execute_action_pipeline(
                        "failed-game", str(game), str(root), [{"action": "backup"}, {"action": "copy_file"}]
                    )
                self.assertTrue(pipeline_runner.get_pending_transaction("failed-game"))

    def test_existing_even_corrupt_journal_blocks_new_pipeline(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            game = Path(root) / "game"
            game.mkdir()
            backups = Path(root) / "backups"
            path = Path(pipeline_runner._transaction_journal_path("blocked-game", str(backups)))
            path.parent.mkdir(parents=True)
            path.write_bytes(b"invalid journal")
            with patch("core.installer_pipeline.pipeline_runner.BACKUP_ROOT", str(backups)), \
                 patch("core.installer_pipeline.pipeline_runner.execute_pipeline_step") as execute:
                with self.assertRaisesRegex(RuntimeError, "journal"):
                    pipeline_runner.execute_action_pipeline("blocked-game", str(game), root, [{"action": "copy_file"}])
                execute.assert_not_called()
            self.assertEqual(path.read_bytes(), b"invalid journal")

    def test_no_pending_journal_does_nothing(self):
        with tempfile.TemporaryDirectory(prefix="congu-crash-recovery-") as root:
            result = pipeline_runner.recover_pending_transaction("missing", root, backup_root=root)
            self.assertEqual(result, {"success": True, "recovered": False})


if __name__ == "__main__":
    unittest.main()
