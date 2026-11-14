# -*- coding: utf-8 -*-
"""Regression: pipeline không được báo rollback 100% khi chính rollback lỗi."""
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
from core.installer_pipeline import pipeline_runner


class PipelineRollbackStatusTests(unittest.TestCase):
    def test_rollback_failure_is_reported_truthfully(self):
        with tempfile.TemporaryDirectory(prefix="congu-pipeline-test-") as root:
            game = Path(root) / "game"
            game.mkdir()
            target = game / "data.bin"
            target.write_bytes(b"modded")
            (game / "data.bin.congu_bak").write_bytes(b"original")
            results = [
                {"action": "backup", "target": "data.bin", "created_new_bak": True},
                RuntimeError("simulated install failure"),
            ]

            def fake_step(*_args, **_kwargs):
                result = results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            # Backup rollback thử os.replace rồi copy2; journal atomically vẫn phải ghi được.
            real_replace = __import__("os").replace

            def fail_rollback_replace(source, destination):
                if ".pending-transaction-" in str(source):
                    return real_replace(source, destination)
                raise PermissionError("locked")

            with patch("core.installer_pipeline.pipeline_runner.BACKUP_ROOT", str(Path(root) / "backups")), \
                 patch("core.installer_pipeline.pipeline_runner.execute_pipeline_step", side_effect=fake_step), \
                 patch("core.installer_pipeline.pipeline_runner.os.replace", side_effect=fail_rollback_replace), \
                 patch("core.installer_pipeline.pipeline_runner.shutil.copy2", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(RuntimeError, "CHƯA hoàn tất"):
                    pipeline_runner.execute_action_pipeline(
                        "fake-game", str(game), str(root),
                        [{"action": "backup"}, {"action": "copy_file"}],
                    )


if __name__ == "__main__":
    unittest.main()
