# -*- coding: utf-8 -*-
"""Updater integration tests with signed metadata, fake packages and no processes."""
import base64
import hashlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.ipc_bridge import ModManagerAPI
from core.update_manifest import canonical_manifest_payload
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class UpdaterIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="congu-updater-test-")))
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "VietModHub.exe").write_bytes(b"old application")
        self.update_dir = self.root / "update"
        self.update_dir.mkdir()
        self.old_package = self.update_dir / "package.zip"
        self.old_package.write_bytes(b"old verified package")
        self.incoming = self.root / "incoming.zip"
        with zipfile.ZipFile(self.incoming, "w") as archive:
            archive.writestr("VietModHub/VietModHub.exe", b"new application")
        self.key = Ed25519PrivateKey.generate()
        public_pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.info = {
            "success": True, "has_update": True, "current_version": "2.0.3",
            "version": "2.0.4", "latest_version": "2.0.4",
            "portable_zip_url": "https://example.invalid/app.zip",
            "portable_zip_sha256": hashlib.sha256(self.incoming.read_bytes()).hexdigest(),
        }
        self.sign()
        for target, value in (
            ("api.ipc_bridge.APPDATA_DIR", str(self.root)),
            ("api.ipc_bridge.APP_DIR", str(self.app)),
            ("api.ipc_bridge.INSTALL_PROGRESS", {"status": "idle"}),
            ("core.update_manifest.RELEASE_PUBLIC_KEY_PEM", public_pem),
        ):
            self.stack.enter_context(patch(target, value))
        self.stack.enter_context(patch.object(sys, "frozen", True, create=True))
        self.stack.enter_context(patch.object(sys, "executable", str(self.app / "VietModHub.exe")))
        self.stack.enter_context(patch("api.ipc_bridge.log_startup"))
        self.stack.enter_context(patch("api.ipc_bridge.any_game_operation_running", return_value=False))
        self.stack.enter_context(patch("api.ipc_bridge.check_app_update", return_value=self.info))
        self.stack.enter_context(patch("api.ipc_bridge.PLAYTIME_MGR", Mock()))
        self.download = self.stack.enter_context(patch(
            "core.downloader.download_file_with_progress", side_effect=self.download_package
        ))
        self.process = self.stack.enter_context(patch("api.ipc_bridge.subprocess.Popen"))
        self.timer = self.stack.enter_context(patch("api.ipc_bridge.threading.Timer"))

    def sign(self):
        self.info["manifest_signature"] = base64.b64encode(
            self.key.sign(canonical_manifest_payload(self.info))
        ).decode("ascii")

    def download_package(self, url, destination, **kwargs):
        self.assertEqual(url, self.info["portable_zip_url"])
        kwargs["validate_download"](str(self.incoming))
        shutil.copyfile(self.incoming, destination)
        return True

    def apply(self):
        result = ModManagerAPI().apply_app_update()
        self.assertEqual((self.app / "VietModHub.exe").read_bytes(), b"old application")
        return result

    def assert_not_applied(self, result):
        self.assertFalse(result["success"], result)
        self.process.assert_not_called()
        self.timer.assert_not_called()

    def test_checksum_failure_keeps_existing_package(self):
        self.incoming.write_bytes(b"wrong content after signing")
        result = self.apply()
        self.assert_not_applied(result)
        self.assertIn("SHA-256", result["message"])
        self.download.assert_called_once()
        self.assertEqual(self.old_package.read_bytes(), b"old verified package")

    def test_rejects_update_without_release_sha256_before_download(self):
        self.info["portable_zip_sha256"] = ""
        result = self.apply()
        self.assert_not_applied(result)
        self.assertIn("SHA-256", result["message"])
        self.download.assert_not_called()

    def test_rejects_malformed_release_sha256_before_download(self):
        self.info["portable_zip_sha256"] = "not-a-hash"
        self.assert_not_applied(self.apply())
        self.download.assert_not_called()

    def test_rejects_missing_signature_before_download(self):
        del self.info["manifest_signature"]
        result = self.apply()
        self.assert_not_applied(result)
        self.assertIn("Chữ ký", result["message"])
        self.download.assert_not_called()

    def test_rejects_tampered_signed_url_before_download(self):
        self.info["portable_zip_url"] = "https://example.invalid/changed.zip"
        self.assert_not_applied(self.apply())
        self.download.assert_not_called()

    def test_never_falls_back_to_unsigned_download_url(self):
        self.info["portable_zip_url"] = ""
        self.info["download_url"] = "https://example.invalid/unsigned.zip"
        self.sign()
        self.assert_not_applied(self.apply())
        self.download.assert_not_called()

    def test_valid_signed_package_reaches_handoff_without_executing_it(self):
        result = self.apply()
        self.assertTrue(result["success"], result)
        self.download.assert_called_once()
        self.process.assert_called_once()
        self.timer.assert_called_once()
        jobs = list(self.update_dir.glob("job-*"))
        self.assertEqual(len(jobs), 1)
        self.assertTrue((jobs[0] / "apply_update.bat").is_file())
        self.assertTrue((self.update_dir / "pending_update.json").is_file())
        self.assertEqual(
            (jobs[0] / "new" / "VietModHub" / "VietModHub.exe").read_bytes(), b"new application"
        )

    def test_update_targets_executable_directory_not_internal_resources(self):
        with patch("api.ipc_bridge.APP_DIR", str(self.app / "_internal")):
            result = self.apply()
        self.assertTrue(result["success"], result)
        script = next(self.update_dir.glob("job-*/apply_update.bat")).read_text(encoding="utf-8")
        self.assertNotIn(str(self.app / "_internal"), script)
        self.assertIn(str(self.app / "VietModHub.exe"), script)

    def test_pending_update_even_corrupt_blocks_without_touching_recovery(self):
        pending = self.update_dir / "pending_update.json"
        pending.write_bytes(b"corrupt pending journal")
        recovery = self.update_dir / "job-previous" / "backup_prev"
        recovery.mkdir(parents=True)
        (recovery / "VietModHub.exe").write_bytes(b"recovery executable")
        self.assert_not_applied(self.apply())
        self.download.assert_not_called()
        self.assertEqual(pending.read_bytes(), b"corrupt pending journal")
        self.assertEqual((recovery / "VietModHub.exe").read_bytes(), b"recovery executable")

    def test_script_launch_failure_releases_only_new_handoff_marker(self):
        self.process.side_effect = OSError("launch denied")
        result = self.apply()
        self.assertFalse(result["success"], result)
        self.assertFalse((self.update_dir / "pending_update.json").exists())
        self.timer.assert_not_called()
        self.assertEqual(len(list(self.update_dir.glob("job-*/apply_update.bat"))), 1)
        self.assertEqual(self.old_package.read_bytes(), b"old verified package")

    def test_existing_handoff_wins_race_before_launch(self):
        original_download = self.download_package
        pending = self.update_dir / "pending_update.json"
        def raced_download(*args, **kwargs):
            result = original_download(*args, **kwargs)
            pending.write_bytes(b"other transaction")
            return result
        self.download.side_effect = raced_download
        self.assert_not_applied(self.apply())
        self.assertEqual(pending.read_bytes(), b"other transaction")

    def test_signed_package_missing_executable_is_not_applied(self):
        with zipfile.ZipFile(self.incoming, "w") as archive:
            archive.writestr("readme.txt", b"no executable")
        self.info["portable_zip_sha256"] = hashlib.sha256(self.incoming.read_bytes()).hexdigest()
        self.sign()
        result = self.apply()
        self.assert_not_applied(result)
        self.assertIn("VietModHub.exe", result["message"])
        self.download.assert_called_once()

    def test_download_failure_preserves_existing_package_and_application(self):
        for error in (ConnectionError("network lost"), PermissionError("locked"), OSError(28, "disk full")):
            with self.subTest(error=error):
                self.download.side_effect = error
                self.assert_not_applied(self.apply())
                self.assertEqual(self.old_package.read_bytes(), b"old verified package")

    def test_extraction_write_failure_never_launches_updater(self):
        with patch("api.ipc_bridge.shutil.copyfileobj", side_effect=OSError(28, "disk full")):
            result = self.apply()
        self.assert_not_applied(result)
        self.assertIn("Giải nén", result["message"])
        self.download.assert_called_once()

    def test_signed_zip_slip_is_not_applied(self):
        with zipfile.ZipFile(self.incoming, "w") as archive:
            archive.writestr("../escaped.dat", b"must not escape")
        self.info["portable_zip_sha256"] = hashlib.sha256(self.incoming.read_bytes()).hexdigest()
        self.sign()
        self.assert_not_applied(self.apply())
        self.assertEqual(list(self.update_dir.glob("job-*/escaped.dat")), [])


if __name__ == "__main__":
    unittest.main()
