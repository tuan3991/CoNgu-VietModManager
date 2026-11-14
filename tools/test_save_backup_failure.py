import io
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloud_sync import CloudSyncManager
from vault_manager import ConguSaveVault


class SaveBackupFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-save-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.save_dir = self.root / "save"
        self.save_dir.mkdir()
        self.save = self.save_dir / "slot.dat"
        self.original = b"original fake save"
        self.save.write_bytes(self.original)
        self.config = {"id": "fake-game"}

    def archive(self, entries):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return data.getvalue()

    def test_zip_save_replace_failure_preserves_existing_archive(self):
        manager = CloudSyncManager(str(self.root / "appdata"))
        destination = self.root / "existing.zip"
        destination.write_bytes(b"previous archive")
        with patch("cloud_sync.os.replace", side_effect=PermissionError("locked")):
            result = manager.zip_save_directory(str(self.save_dir), str(destination))
        self.assertFalse(result)
        self.assertEqual(destination.read_bytes(), b"previous archive")
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob("existing.zip.tmp_*")), [])

    def test_cloud_sync_temp_creation_failure_does_not_touch_save_or_cloud(self):
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.create_local_backup = Mock(return_value="fake-backup")
        check = {"status": "UPLOAD_NEEDED", "save_folder": str(self.save_dir),
                 "local": {"exists": True}, "cloud": {"id": "fake"}}
        manager.check_game_sync_status = Mock(return_value=check)
        with patch("cloud_sync.tempfile.mkstemp", side_effect=PermissionError("denied")):
            for action in ("upload", "download"):
                result = manager.sync_game_save(self.config, force_action=action)
                self.assertFalse(result["success"], result)
                self.assertIn("file tạm", result["error"])
                self.assertEqual(self.save.read_bytes(), self.original)
        manager.client.download_file.assert_not_called()
        manager.client.upload_file_multipart.assert_not_called()

    def test_cloud_upload_records_checksum_of_uploaded_zip(self):
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.client.get_cloud_root_folders.return_value = ("root", "saves")
        manager.check_game_sync_status = Mock(return_value={
            "status": "UPLOAD_NEEDED", "save_folder": str(self.save_dir),
            "local": {"exists": True, "sha256": "directory-fingerprint", "mtime": 123, "file_count": 1},
            "cloud": {},
        })
        manager._load_user_profile_data = Mock(return_value={})
        manager._save_user_profile_data = Mock()
        manager._sync_profile_meta_to_cloud = Mock()
        captured = {}
        def upload(**kwargs):
            payload = Path(kwargs["file_path_or_bytes"]).read_bytes()
            captured.update(kwargs)
            captured["payload"] = payload
            return {"id": "fake"}
        manager.client.upload_file_multipart.side_effect = upload
        result = manager.sync_game_save(self.config)
        self.assertTrue(result["success"], result)
        self.assertEqual(captured["app_properties"]["zip_sha256"], hashlib.sha256(captured["payload"]).hexdigest())
        self.assertEqual(captured["app_properties"]["sha256"], "directory-fingerprint")
        with zipfile.ZipFile(io.BytesIO(captured["payload"])) as archive:
            self.assertEqual(archive.read("slot.dat"), self.original)
        self.assertFalse(Path(captured["file_path_or_bytes"]).exists())

    def test_cloud_download_checks_zip_hash_before_restore(self):
        payload = self.archive({"slot.dat": b"downloaded save"})
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.create_local_backup = Mock(return_value="fake-backup")
        manager._load_user_profile_data = Mock(return_value={})
        manager._save_user_profile_data = Mock()
        manager.client.download_file.side_effect = lambda _id, path: Path(path).write_bytes(payload)
        check = {"status": "DOWNLOAD_NEEDED", "save_folder": str(self.save_dir),
                 "local": {"exists": True}, "cloud": {"id": "fake", "zip_sha256": "0" * 64}}
        manager.check_game_sync_status = Mock(return_value=check)
        for checksum in ("0" * 64, "bad-hash"):
            check["cloud"]["zip_sha256"] = checksum
            result = manager.sync_game_save(self.config)
            self.assertFalse(result["success"], result)
            self.assertEqual(self.save.read_bytes(), self.original)
            manager._save_user_profile_data.assert_not_called()
        check["cloud"]["zip_sha256"] = hashlib.sha256(payload).hexdigest()
        result = manager.sync_game_save(self.config)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.save.read_bytes(), b"downloaded save")
        self.assertEqual(list(Path(manager.appdata_dir).glob("congu-save-download-*")), [])

    def test_cloud_download_stops_when_local_backup_fails(self):
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.check_game_sync_status = Mock(return_value={
            "status": "DOWNLOAD_NEEDED", "save_folder": str(self.save_dir),
            "local": {"exists": True}, "cloud": {"id": "fake-cloud-id"},
        })
        manager.create_local_backup = Mock(return_value="")
        payload = self.archive({"slot.dat": b"cloud save"})
        manager.client.download_file.side_effect = lambda file_id, path: Path(path).write_bytes(payload)

        result = manager.sync_game_save(self.config)

        self.assertEqual(self.save.read_bytes(), self.original, "backup thất bại nhưng save bị ghi đè")
        self.assertFalse(result.get("success"))
        self.assertTrue(result.get("error"))
        manager.client.download_file.assert_not_called()

    def test_vault_unpack_single_file_save(self):
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/saves/main_saves/_meta.json": json.dumps({"original_type": "file"}),
            "fake-game/saves/main_saves/old-name.dat": b"restored single save",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save))
        result = vault.unpack_game_from_vault(self.config)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.save.read_bytes(), b"restored single save")
        self.assertEqual(Path(str(self.save) + ".congu_bak").read_bytes(), self.original)

    def test_vault_file_slot_rejects_multiple_entries_before_any_write(self):
        for revision in (False, True):
            prefix = "fake-game/prev_1/saves/main_saves/" if revision else "fake-game/saves/main_saves/"
            vault_path = self.root / "fake.congu_save"
            vault_path.write_bytes(self.archive({
                prefix + "_meta.json": json.dumps({"original_type": "file"}),
                prefix + "first.dat": b"first", prefix + "second.dat": b"second",
            }))
            vault = ConguSaveVault(str(vault_path))
            vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save)}], [], []))
            vault.resolve_macro_path = Mock(return_value=str(self.save))
            result = vault.restore_game_revision(self.config) if revision else vault.unpack_game_from_vault(self.config)
            self.assertFalse(result["success"], result)
            self.assertEqual(self.save.read_bytes(), self.original)

    def test_vault_unpack_rejects_sibling_prefix_traversal(self):
        sibling = self.root / "save_evil"
        sibling.mkdir()
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/saves/main_saves/../save_evil/escaped.dat": b"must not write",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        result = vault.unpack_game_from_vault(self.config)
        self.assertFalse(result.get("success"))
        self.assertFalse((sibling / "escaped.dat").exists())
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_vault_unpack_rejects_existing_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.save_dir / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Môi trường không cho tạo symlink test: {exc}")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({"fake-game/saves/main_saves/linked/escaped.dat": b"must not write"}))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        result = vault.unpack_game_from_vault(self.config)
        self.assertFalse(result.get("success"))
        self.assertFalse((outside / "escaped.dat").exists())

    def test_standard_zip_restore_rejects_absolute_drive_and_traversal_entries(self):
        outside = self.root / "outside"
        outside.mkdir()
        malicious_names = [
            "../outside/escaped.dat",
            "C:/outside/escaped.dat",
            "/outside/escaped.dat",
            "..\\outside\\escaped.dat",
        ]
        vault = ConguSaveVault(str(self.root / "vault.congu_save"))
        for index, entry_name in enumerate(malicious_names):
            archive = self.root / f"malicious-{index}.zip"
            manifest = {
                "format": "congu_standard_save_zip",
                "games": [{
                    "game_id": "fake-game", "folder_in_zip": "FakeGame",
                    "save_locations": [{"slot": "main_saves", "portable_path": str(self.save_dir)}],
                }],
            }
            archive.write_bytes(self.archive({
                "save_manifest.json": json.dumps(manifest),
                f"FakeGame/saves/main_saves/{entry_name}": b"must not escape",
            }))
            result = vault.import_standard_zip(str(archive), [{"id": "fake-game", "vault_config": {"save_locations": [{"slot": "main_saves", "path": str(self.save_dir)}]}}], {"fake-game_path": ""})
            self.assertFalse(result.get("success"), entry_name)
            self.assertFalse((outside / "escaped.dat").exists())
            self.assertEqual(self.save.read_bytes(), self.original)

    def test_cloud_restore_rejects_absolute_drive_and_traversal_entries(self):
        outside = self.root / "outside"
        outside.mkdir()
        manager = CloudSyncManager(str(self.root / "appdata"))
        malicious_names = ["../outside/escaped.dat", "C:/outside/escaped.dat", "/outside/escaped.dat", "..\\outside\\escaped.dat"]
        for entry_name in malicious_names:
            archive = self.root / "cloud-malicious.zip"
            archive.write_bytes(self.archive({entry_name: b"must not escape"}))
            with self.assertRaises(ValueError, msg=entry_name):
                manager.unzip_save_directory(str(archive), str(self.save_dir))
            self.assertFalse((outside / "escaped.dat").exists())
            self.assertEqual(self.save.read_bytes(), self.original)

    def test_cloud_restore_rejects_sibling_prefix_traversal(self):
        sibling = self.root / "save_evil"
        sibling.mkdir()
        archive = self.root / "restore.zip"
        archive.write_bytes(self.archive({"../save_evil/escaped.dat": b"must not write"}))
        manager = CloudSyncManager(str(self.root / "appdata"))
        with self.assertRaises(ValueError):
            manager.unzip_save_directory(str(archive), str(self.save_dir))
        self.assertFalse((sibling / "escaped.dat").exists())
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_vault_backup_collision_does_not_overwrite_other_save(self):
        second = self.save_dir / "slot.dat.congu_bak"
        second.write_bytes(b"independent save")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/saves/main_saves/slot.dat": b"new first",
            "fake-game/saves/main_saves/slot.dat.congu_bak": b"new second",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        result = vault.unpack_game_from_vault(self.config)
        self.assertFalse(result.get("success"), result)
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"independent save")

    def test_revision_uses_configured_slot_not_archive_macro(self):
        outside = self.root / "outside"
        outside.mkdir()
        outside_save = outside / "slot.dat"
        outside_save.write_bytes(b"outside original")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/prev_1/saves/main_saves/_meta.json": json.dumps({
                "original_type": "directory", "macro_path": str(outside),
            }),
            "fake-game/prev_1/saves/main_saves/slot.dat": b"revision save",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = lambda raw, _root="": raw
        result = vault.restore_game_revision(self.config)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.save.read_bytes(), b"revision save")
        self.assertEqual(outside_save.read_bytes(), b"outside original")

    def test_revision_rejects_malformed_metadata_before_writing(self):
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/prev_1/saves/main_saves/_meta.json": b"invalid json",
            "fake-game/prev_1/saves/main_saves/slot.dat": b"revision save",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        result = vault.restore_game_revision(self.config)
        self.assertFalse(result["success"], result)
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_revision_backup_collision_does_not_overwrite_other_save(self):
        second = self.save_dir / "slot.dat.congu_prevbak"
        second.write_bytes(b"independent revision save")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/prev_1/saves/main_saves/slot.dat": b"new first",
            "fake-game/prev_1/saves/main_saves/slot.dat.congu_prevbak": b"new second",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        result = vault.restore_game_revision(self.config)
        self.assertFalse(result.get("success"), result)
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"independent revision save")

    def test_vault_incomplete_backup_copy_preserves_existing_backup_and_save(self):
        backup = Path(str(self.save) + ".congu_bak")
        backup.write_bytes(b"previous backup")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({"fake-game/saves/main_saves/slot.dat": b"new save"}))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        import shutil
        real_copy = shutil.copy2

        def fail_partial_backup(source, destination, *args, **kwargs):
            if Path(destination).name.startswith(".congu-backup-"):
                Path(destination).write_bytes(b"partial")
                raise OSError("simulated disk full")
            return real_copy(source, destination, *args, **kwargs)

        with patch("vault_manager.shutil.copy2", side_effect=fail_partial_backup):
            result = vault.unpack_game_from_vault(self.config)
        self.assertFalse(result.get("success"), result)
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(backup.read_bytes(), b"previous backup")
        self.assertEqual(list(self.save_dir.glob(".congu-backup-*")), [])

    def test_vault_unpack_stops_when_backup_fails(self):
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({"fake-game/saves/main_saves/slot.dat": b"vault save"}))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))

        with patch("vault_manager.shutil.copy2", side_effect=PermissionError("backup denied")):
            try:
                result = vault.unpack_game_from_vault(self.config)
            except OSError:
                result = {"success": False}

        self.assertEqual(self.save.read_bytes(), self.original, "backup thất bại nhưng save bị ghi đè")
        self.assertFalse(result.get("success"))

    def test_cloud_restore_rolls_back_after_second_replace_fails(self):
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        archive = self.root / "restore.zip"
        archive.write_bytes(self.archive({"slot.dat": b"new one", "second.dat": b"new two"}))
        manager = CloudSyncManager(str(self.root / "appdata"))
        replace = os.replace
        calls = []

        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise PermissionError("file locked")
            return replace(source, destination)

        with patch("cloud_sync.os.replace", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                manager.unzip_save_directory(str(archive), str(self.save_dir))
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"second original")

    def test_cloud_restore_preserves_recovery_if_rollback_fails(self):
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        archive = self.root / "restore.zip"
        archive.write_bytes(self.archive({"slot.dat": b"new one", "second.dat": b"new two"}))
        manager = CloudSyncManager(str(self.root / "appdata"))
        replace = os.replace
        copy = __import__("shutil").copy2
        calls = []

        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise PermissionError("file locked")
            return replace(source, destination)

        def fail_rollback(source, destination, *args, **kwargs):
            if Path(source).name.startswith("old-"):
                Path(destination).write_bytes(b"partial rollback")
                raise PermissionError("rollback locked")
            return copy(source, destination, *args, **kwargs)

        with patch("cloud_sync.os.replace", side_effect=fail_second), patch("cloud_sync.shutil.copy2", side_effect=fail_rollback):
            with self.assertRaisesRegex(RuntimeError, "rollback thất bại"):
                manager.unzip_save_directory(str(archive), str(self.save_dir))
        recovery = list(Path(manager.backups_dir).glob("restore-*"))
        self.assertEqual(len(recovery), 1)
        manifest = json.loads((recovery[0] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest[0]["backup"]).read_bytes(), self.original)
        self.assertEqual(self.save.read_bytes(), b"new one")
        self.assertEqual(second.read_bytes(), b"second original")
        self.assertEqual(list(self.save_dir.glob(".congu-rollback-*")), [])

    def test_cloud_restore_success_keeps_unmentioned_files(self):
        archive = self.root / "restore.zip"
        archive.write_bytes(self.archive({"slot.dat": b"restored", "new.dat": b"new"}))
        untouched = self.save_dir / "untouched.dat"
        untouched.write_bytes(b"keep")
        manager = CloudSyncManager(str(self.root / "appdata"))
        self.assertTrue(manager.unzip_save_directory(str(archive), str(self.save_dir)))
        self.assertEqual(self.save.read_bytes(), b"restored")
        self.assertEqual((self.save_dir / "new.dat").read_bytes(), b"new")
        self.assertEqual(untouched.read_bytes(), b"keep")

    def test_cloud_restore_rejects_corrupt_zip_before_writing(self):
        archive = self.root / "broken.zip"
        archive.write_bytes(b"not a zip")
        manager = CloudSyncManager(str(self.root / "appdata"))
        with self.assertRaises(zipfile.BadZipFile):
            manager.unzip_save_directory(str(archive), str(self.save_dir))
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_vault_rollback_copy_failure_preserves_applied_file_and_snapshot(self):
        import shutil
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/saves/main_saves/slot.dat": b"new first",
            "fake-game/saves/main_saves/second.dat": b"new second",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        replace, copy = os.replace, shutil.copy2
        calls = []
        def fail_second(source, destination):
            if Path(source).name.startswith(".congu-restore-"):
                calls.append(destination)
                if len(calls) == 2:
                    raise PermissionError("locked")
            return replace(source, destination)
        def partial_rollback(source, destination, *args, **kwargs):
            if Path(destination).name.startswith(".congu-rollback-"):
                Path(destination).write_bytes(b"partial")
                raise OSError("disk full")
            return copy(source, destination, *args, **kwargs)
        with tempfile.TemporaryDirectory(dir=self.root) as staging_root:
            with patch("vault_manager.tempfile.tempdir", staging_root), \
                 patch("vault_manager.os.replace", side_effect=fail_second), \
                 patch("vault_manager.shutil.copy2", side_effect=partial_rollback):
                result = vault.unpack_game_from_vault(self.config)
            self.assertFalse(result["success"])
            self.assertIn("rollback thất bại", result["error"])
            self.assertEqual(self.save.read_bytes(), b"new first")
            snapshots = list(Path(staging_root).glob("congu-vault-restore-*/old-0"))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].read_bytes(), self.original)
            self.assertEqual(second.read_bytes(), b"second original")
            self.assertEqual(list(self.save_dir.glob(".congu-rollback-*")), [])

    def test_vault_unpack_rolls_back_batch_when_second_replace_fails(self):
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/saves/main_saves/slot.dat": b"new first",
            "fake-game/saves/main_saves/second.dat": b"new second",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        real_replace = os.replace
        calls = []

        def fail_second_replace(source, destination):
            if Path(source).name.startswith(".congu-restore-"):
                calls.append(destination)
                if len(calls) == 2:
                    raise PermissionError("file locked")
            return real_replace(source, destination)

        with patch("vault_manager.os.replace", side_effect=fail_second_replace):
            result = vault.unpack_game_from_vault(self.config)
        self.assertFalse(result.get("success"))
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"second original")

    def test_revision_rolls_back_batch_when_second_replace_fails(self):
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({
            "fake-game/prev_1/saves/main_saves/slot.dat": b"old first",
            "fake-game/prev_1/saves/main_saves/second.dat": b"old second",
        }))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        real_replace = os.replace
        calls = []

        def fail_second_replace(source, destination):
            if Path(source).name.startswith(".congu-restore-"):
                calls.append(destination)
                if len(calls) == 2:
                    raise PermissionError("file locked")
            return real_replace(source, destination)

        with patch("vault_manager.os.replace", side_effect=fail_second_replace):
            result = vault.restore_game_revision(self.config)
        self.assertFalse(result.get("success"))
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"second original")

    def test_revision_stops_when_backup_fails(self):
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({"fake-game/prev_1/saves/main_saves/slot.dat": b"old save"}))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))
        with patch("vault_manager.shutil.copy2", side_effect=PermissionError("backup denied")):
            result = vault.restore_game_revision(self.config)
        self.assertFalse(result.get("success"))
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_import_vault_replace_failure_preserves_original(self):
        vault_path = self.root / "current.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        source = self.root / "incoming.congu_save"
        source.write_bytes(self.archive({"profile_manifest.json": json.dumps({"version": "new"})}))
        vault = ConguSaveVault(str(vault_path))
        real_replace = os.replace
        def fail_vault_replace(src, dst):
            if str(dst) == str(vault_path):
                raise PermissionError("file locked")
            return real_replace(src, dst)
        with patch("vault_manager.os.replace", side_effect=fail_vault_replace):
            result = vault.import_vault(str(source))
        self.assertFalse(result.get("success"))
        self.assertEqual(vault_path.read_bytes(), original)
        self.assertEqual(Path(str(vault_path) + ".congu_vault_bak").read_bytes(), original)

    def test_import_vault_partial_backup_keeps_previous_backup(self):
        vault_path = self.root / "current.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        backup = Path(str(vault_path) + ".congu_vault_bak")
        backup.write_bytes(b"previous backup")
        source = self.root / "incoming.congu_save"
        source.write_bytes(self.archive({"profile_manifest.json": json.dumps({"version": "new"})}))
        vault = ConguSaveVault(str(vault_path))
        def partial_copy(src, dst, *args, **kwargs):
            Path(dst).write_bytes(b"partial")
            raise OSError("simulated disk full")
        with patch("vault_manager.shutil.copy2", side_effect=partial_copy):
            result = vault.import_vault(str(source))
        self.assertFalse(result["success"], result)
        self.assertEqual(vault_path.read_bytes(), original)
        self.assertEqual(backup.read_bytes(), b"previous backup")
        self.assertEqual(list(self.root.glob(".congu-vault-backup-*")), [])

    def test_import_vault_success(self):
        vault_path = self.root / "current.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        source = self.root / "incoming.congu_save"
        incoming = self.archive({"profile_manifest.json": json.dumps({"version": "new"})})
        source.write_bytes(incoming)
        vault = ConguSaveVault(str(vault_path))
        result = vault.import_vault(str(source))
        self.assertTrue(result.get("success"))
        self.assertEqual(vault_path.read_bytes(), incoming)
        self.assertEqual(Path(str(vault_path) + ".congu_vault_bak").read_bytes(), original)

    def test_standard_zip_ignores_archive_destination_and_rejects_unknown_game(self):
        outside = self.root / "outside"
        outside.mkdir()
        outside_save = outside / "slot.dat"
        outside_save.write_bytes(b"outside original")
        archive = self.root / "redirect.zip"
        manifest = {"format": "congu_standard_save_zip", "games": [{
            "game_id": "fake-game", "folder_in_zip": "FakeGame",
            "save_locations": [{"slot": "main_saves", "portable_path": str(outside)}],
        }]}
        archive.write_bytes(self.archive({"save_manifest.json": json.dumps(manifest),
            "FakeGame/saves/main_saves/slot.dat": b"restored"}))
        vault = ConguSaveVault(str(self.root / "vault.congu_save"))
        rejected = vault.import_standard_zip(str(archive), [], {})
        self.assertFalse(rejected["success"], rejected)
        self.assertEqual(self.save.read_bytes(), self.original)
        game = {"id": "fake-game", "vault_config": {"save_locations": [{"slot": "main_saves", "path": str(self.save_dir)}]}}
        result = vault.import_standard_zip(str(archive), [game], {})
        self.assertTrue(result["success"], result)
        self.assertEqual(self.save.read_bytes(), b"restored")
        self.assertEqual(outside_save.read_bytes(), b"outside original")

    def test_standard_zip_import_success_restores_and_counts_backups(self):
        archive = self.root / "standard-success.zip"
        manifest = {"format": "congu_standard_save_zip", "games": [{
            "game_id": "fake-game", "folder_in_zip": "FakeGame",
            "save_locations": [{"slot": "main_saves", "portable_path": str(self.save_dir)}],
        }]}
        archive.write_bytes(self.archive({
            "save_manifest.json": json.dumps(manifest),
            "FakeGame/saves/main_saves/slot.dat": b"restored",
        }))
        vault = ConguSaveVault(str(self.root / "vault.congu_save"))
        result = vault.import_standard_zip(str(archive), [{"id": "fake-game", "vault_config": {"save_locations": [{"slot": "main_saves", "path": str(self.save_dir)}]}}], {"fake-game_path": ""})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result["total_files"], 1)
        self.assertEqual(result["backups_created"], 1)
        self.assertEqual(self.save.read_bytes(), b"restored")
        self.assertEqual(Path(str(self.save) + ".congu_bak").read_bytes(), self.original)

    def test_standard_zip_import_rolls_back_batch_when_second_replace_fails(self):
        second = self.save_dir / "second.dat"
        second.write_bytes(b"second original")
        archive = self.root / "standard.zip"
        manifest = {
            "format": "congu_standard_save_zip",
            "games": [{
                "game_id": "fake-game", "folder_in_zip": "FakeGame",
                "save_locations": [{"slot": "main_saves", "portable_path": str(self.save_dir)}],
            }],
        }
        archive.write_bytes(self.archive({
            "save_manifest.json": json.dumps(manifest),
            "FakeGame/saves/main_saves/slot.dat": b"new first",
            "FakeGame/saves/main_saves/second.dat": b"new second",
        }))
        vault = ConguSaveVault(str(self.root / "vault.congu_save"))
        real_replace = os.replace
        calls = []

        def fail_second_replace(source, destination):
            if Path(source).name.startswith(".congu-restore-"):
                calls.append(destination)
                if len(calls) == 2:
                    raise PermissionError("file locked")
            return real_replace(source, destination)

        with patch("vault_manager.os.replace", side_effect=fail_second_replace):
            result = vault.import_standard_zip(str(archive), [{"id": "fake-game", "vault_config": {"save_locations": [{"slot": "main_saves", "path": str(self.save_dir)}]}}], {"fake-game_path": ""})
        self.assertFalse(result.get("success"))
        self.assertEqual(len(calls), 2, result)
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), b"second original")

    def test_import_vault_stops_when_backup_fails(self):
        vault_path = self.root / "current.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        source = self.root / "incoming.congu_save"
        source.write_bytes(self.archive({"profile_manifest.json": json.dumps({"version": "new"})}))
        vault = ConguSaveVault(str(vault_path))
        with patch("vault_manager.shutil.copy2", side_effect=PermissionError("backup denied")):
            result = vault.import_vault(str(source))
        self.assertFalse(result.get("success"))
        self.assertEqual(vault_path.read_bytes(), original)

    def test_downloaded_vault_verifies_optional_sha256_before_backup(self):
        vault_path = self.root / "fake.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        incoming = self.archive({"profile_manifest.json": json.dumps({"games": {}})})
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.client.get_cloud_root_folders.return_value = ("root", "saves")
        manager.client.download_file.side_effect = lambda _id, path: Path(path).write_bytes(incoming)
        for checksum in ("0" * 64, "bad-hash"):
            vault_path.write_bytes(original)
            manager.client.list_files_in_folder.return_value = {"fake.congu_save": {"id": "id", "appProperties": {"sha256": checksum}}}
            result = manager.download_vault_from_drive(str(vault_path))
            self.assertFalse(result["success"], result)
            self.assertEqual(vault_path.read_bytes(), original)
            self.assertFalse(Path(str(vault_path) + ".congu_vault_bak").exists())
        manager.client.list_files_in_folder.return_value = {"fake.congu_save": {"id": "id", "appProperties": {"sha256": hashlib.sha256(incoming).hexdigest().upper()}}}
        result = manager.download_vault_from_drive(str(vault_path))
        self.assertTrue(result["success"], result)
        self.assertEqual(vault_path.read_bytes(), incoming)
        self.assertEqual(Path(str(vault_path) + ".congu_vault_bak").read_bytes(), original)

    def test_downloaded_vault_rejects_bad_payload_crc_before_backup(self):
        vault_path = self.root / "fake.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        payload = bytearray(self.archive({"profile_manifest.json": json.dumps({"games": {}}), "save.dat": b"unique-payload-for-crc"}))
        offset = payload.index(b"unique-payload-for-crc")
        payload[offset] ^= 1
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.client.get_cloud_root_folders.return_value = ("root", "saves")
        manager.client.list_files_in_folder.return_value = {"fake.congu_save": {"id": "id"}}
        manager.client.download_file.side_effect = lambda _id, path: Path(path).write_bytes(payload)
        result = manager.download_vault_from_drive(str(vault_path))
        self.assertFalse(result["success"], result)
        self.assertEqual(vault_path.read_bytes(), original)
        self.assertFalse(Path(str(vault_path) + ".congu_vault_bak").exists())
        self.assertEqual(list(self.root.glob(".congu-vault-download-*")), [])

    def test_downloaded_vault_partial_backup_preserves_old_backup(self):
        vault_path = self.root / "fake.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        backup = Path(str(vault_path) + ".congu_vault_bak")
        backup.write_bytes(b"old backup")
        payload = self.archive({"profile_manifest.json": json.dumps({"games": {}})})
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.client.get_cloud_root_folders.return_value = ("root", "saves")
        manager.client.list_files_in_folder.return_value = {"fake.congu_save": {"id": "id"}}
        manager.client.download_file.side_effect = lambda _id, path: Path(path).write_bytes(payload)
        def partial(_source, destination, *args, **kwargs):
            Path(destination).write_bytes(b"partial")
            raise OSError("disk full")
        with patch("cloud_sync.shutil.copy2", side_effect=partial):
            result = manager.download_vault_from_drive(str(vault_path))
        self.assertFalse(result["success"], result)
        self.assertEqual(vault_path.read_bytes(), original)
        self.assertEqual(backup.read_bytes(), b"old backup")
        self.assertEqual(list(self.root.glob(".congu-vault-download-*")), [])
        self.assertEqual(list(self.root.glob(".congu-vault-backup-*")), [])

    def test_downloaded_vault_does_not_replace_existing_when_backup_fails(self):
        vault_path = self.root / "fake.congu_save"
        original = self.archive({"profile_manifest.json": json.dumps({"version": "old"})})
        vault_path.write_bytes(original)
        payload = self.archive({"profile_manifest.json": json.dumps({"version": "new"})})
        manager = CloudSyncManager(str(self.root / "appdata"))
        manager.client = Mock()
        manager.is_connected = Mock(return_value=True)
        manager.client.get_cloud_root_folders.return_value = ("fake-root", "fake-saves")
        manager.client.list_files_in_folder.return_value = {"fake.congu_save": {"id": "fake-id"}}
        manager.client.download_file.side_effect = lambda file_id, path: Path(path).write_bytes(payload)

        with patch("shutil.copy2", side_effect=PermissionError("backup denied")):
            result = manager.download_vault_from_drive(str(vault_path))

        self.assertEqual(vault_path.read_bytes(), original, "backup thất bại nhưng Vault bị thay thế")
        self.assertFalse(result.get("success"))
        self.assertTrue(result.get("error"))


    def _make_junction(self, link, target):
        if sys.platform != "win32":
            self.skipTest("junction chỉ có trên Windows")
        import subprocess
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, creationflags=0x08000000,
        )
        if result.returncode != 0:
            self.skipTest(f"Không tạo được junction: {result.stderr or result.stdout}")

    def test_vault_unpack_rejects_junction_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        self._make_junction(self.save_dir / "linked", outside)
        vault_path = self.root / "fake.congu_save"
        vault_path.write_bytes(self.archive({"fake-game/saves/main_saves/linked/escaped.dat": b"must not write"}))
        vault = ConguSaveVault(str(vault_path))
        vault._extract_game_locations = Mock(return_value=([{"slot": "main_saves", "path": str(self.save_dir)}], [], []))
        vault.resolve_macro_path = Mock(return_value=str(self.save_dir))

        result = vault.unpack_game_from_vault(self.config)

        self.assertFalse(result.get("success"), result)
        self.assertFalse((outside / "escaped.dat").exists())
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_cloud_restore_rejects_junction_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        self._make_junction(self.save_dir / "linked", outside)
        manager = CloudSyncManager(str(self.root / "appdata"))
        archive = self.root / "malicious.zip"
        archive.write_bytes(self.archive({"linked/escaped.dat": b"must not write"}))

        with self.assertRaisesRegex(ValueError, "không an toàn"):
            manager.unzip_save_directory(str(archive), str(self.save_dir))

        self.assertFalse((outside / "escaped.dat").exists())
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_cloud_restore_rejects_case_insensitive_duplicate_paths(self):
        if sys.platform != "win32":
            self.skipTest("trùng đường dẫn không phân biệt hoa/thường chỉ áp dụng trên Windows")
        manager = CloudSyncManager(str(self.root / "appdata"))
        archive = self.root / "duplicates.zip"
        archive.write_bytes(self.archive({"slot.dat": b"first", "SLOT.DAT": b"second"}))

        with self.assertRaisesRegex(ValueError, "trùng lặp"):
            manager.unzip_save_directory(str(archive), str(self.save_dir))

        self.assertEqual(self.save.read_bytes(), self.original)

    def _local_backup_manager(self, backup_entries):
        manager = CloudSyncManager(str(self.root / "appdata"))
        game_backup_dir = Path(manager.backups_dir) / "fake-game"
        game_backup_dir.mkdir(parents=True)
        backup_path = game_backup_dir / "save_backup_20260101_000000.zip"
        backup_path.write_bytes(self.archive(backup_entries))
        config = {"id": "fake-game", "cloud_sync": {"save_paths": [str(self.save_dir)]}}
        return manager, backup_path, config

    def test_local_backup_restore_stops_when_snapshot_fails(self):
        manager, backup_path, config = self._local_backup_manager({"slot.dat": b"backup content"})
        manager.create_local_backup = Mock(return_value="")

        with patch.object(manager, "unzip_save_directory") as unzip:
            result = manager.restore_local_backup(
                "fake-game", backup_path.name, config, str(self.save_dir)
            )

        self.assertFalse(result.get("success"), result)
        self.assertIn("sao lưu", result.get("error", ""))
        self.assertEqual(self.save.read_bytes(), self.original, "backup thất bại nhưng save bị ghi đè")
        unzip.assert_not_called()

    def test_local_backup_restore_snapshots_current_save_first(self):
        manager, backup_path, config = self._local_backup_manager({"slot.dat": b"restored from backup"})

        result = manager.restore_local_backup(
            "fake-game", backup_path.name, config, str(self.save_dir)
        )

        self.assertTrue(result.get("success"), result)
        self.assertEqual(self.save.read_bytes(), b"restored from backup")
        snapshots = sorted(Path(manager.backups_dir).glob("fake-game/save_backup_*.zip"))
        self.assertEqual(len(snapshots), 2, snapshots)
        self.assertTrue(backup_path.exists(), "bản backup nguồn bị xóa trong lúc khôi phục")
        snapshot = next(path for path in snapshots if path.name != backup_path.name)
        with zipfile.ZipFile(snapshot) as archive:
            self.assertEqual(archive.read("slot.dat"), self.original)

    def test_local_backup_restore_rejects_path_like_identifiers(self):
        manager = CloudSyncManager(str(self.root / "appdata"))
        config = {"id": "fake-game", "cloud_sync": {"save_paths": [str(self.save_dir)]}}
        for game_id, filename in (
            ("fake-game", "../evil.zip"),
            ("../fake-game", "save_backup_20260101_000000.zip"),
            ("fake-game", "C:evil.zip"),
        ):
            result = manager.restore_local_backup(game_id, filename, config, str(self.save_dir))
            self.assertFalse(result.get("success"), (game_id, filename))
            self.assertIn("không hợp lệ", result.get("error", ""))
        self.assertEqual(self.save.read_bytes(), self.original)

    def test_local_backup_restore_requires_existing_save_directory(self):
        manager, backup_path, _config = self._local_backup_manager({"slot.dat": b"backup content"})
        config = {"id": "fake-game", "cloud_sync": {"save_paths": [str(self.root / "missing-save")]}}

        with patch.object(manager, "unzip_save_directory") as unzip:
            result = manager.restore_local_backup(
                "fake-game", backup_path.name, config, str(self.root / "missing-save")
            )

        self.assertFalse(result.get("success"), result)
        self.assertIn("Không tìm thấy thư mục save", result.get("error", ""))
        self.assertFalse((self.root / "missing-save").exists())
        unzip.assert_not_called()


if __name__ == "__main__":
    unittest.main()
