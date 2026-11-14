# -*- coding: utf-8 -*-
"""Regression: script cập nhật phải sao lưu bản cũ trước khi ghi và rollback khi lỗi."""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.updater_apply import build_apply_script, build_copy_verifier


class UpdaterApplyScriptTests(unittest.TestCase):
    SRC = r"C:\appdata\update\new"
    DST = r"C:\app"
    BACKUP = r"C:\appdata\update\backup_prev"

    def setUp(self):
        self.probe_args = {"startup_probe": r"C:\appdata\update\probe.ps1",
                           "transaction_token": "a" * 64, "version": "2.0.4"}
        self.script = build_apply_script(self.SRC, self.DST, self.BACKUP, 1234, watchdog_seconds=5,
                                         **self.probe_args)

    def test_backup_copy_runs_before_replacing_app(self):
        backup_copy = 'robocopy "%s" "%s" /MIR' % (self.DST, self.BACKUP)
        new_copy = 'robocopy "%s" "%s" /E' % (self.SRC, self.DST)
        self.assertIn(backup_copy, self.script)
        self.assertIn(new_copy, self.script)
        self.assertLess(self.script.index(backup_copy), self.script.index(new_copy))

    def test_backup_failure_aborts_without_touching_app(self):
        self.assertIn("if !BRC! GEQ 8", self.script)
        self.assertIn("exit /b 20", self.script)
        abort_index = self.script.index("exit /b 20")
        replace_index = self.script.index('robocopy "%s" "%s" /E' % (self.SRC, self.DST))
        self.assertLess(abort_index, replace_index)

    def test_rollback_restores_backup_and_requires_it(self):
        rollback_copy = 'robocopy "%s" "%s" /MIR' % (self.BACKUP, self.DST)
        self.assertIn(":rollback", self.script)
        self.assertIn(rollback_copy, self.script)
        self.assertIn('if not exist "%s\\VietModHub.exe"' % self.BACKUP, self.script)
        self.assertIn("exit /b 21", self.script)
        self.assertIn("exit /b 22", self.script)

    def test_missing_new_exe_and_failed_start_trigger_rollback(self):
        self.assertIn('if not exist "%s\\VietModHub.exe"' % self.DST, self.script)
        self.assertNotIn("IMAGENAME", self.script)
        self.assertIn("-TimeoutSeconds 5", self.script)
        self.assertIn("if !START_RC! EQU 34 exit /b 34", self.script)
        self.assertIn("goto rollback", self.script)

    def test_errorlevel_captured_inside_blocks(self):
        self.assertIn("setlocal EnableDelayedExpansion", self.script)
        self.assertIn("set RC=!ERRORLEVEL!", self.script)
        self.assertIn("set RRC=!ERRORLEVEL!", self.script)
        self.assertNotIn("pause", self.script.lower())

    def test_rejects_overlapping_directories(self):
        for source, destination, backup in (
            (self.DST, self.DST, self.BACKUP),
            (self.DST + r"\new", self.DST, self.BACKUP),
            (self.SRC, self.DST, self.DST + r"\backup"),
        ):
            with self.subTest(paths=(source, destination, backup)):
                with self.assertRaises(ValueError):
                    build_apply_script(source, destination, backup, 1234, **self.probe_args)

    def test_rejects_batch_expansion_characters(self):
        for name in ("%TEMP%", "app!name", 'app"name', "app\nname"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    build_apply_script(self.SRC, "C:\\" + name, self.BACKUP, 1234, **self.probe_args)


@unittest.skipUnless(sys.platform == "win32" and shutil.which("robocopy"), "Windows robocopy required")
class UpdaterApplyFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-batch-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "new"
        self.app = self.root / "app"
        self.backup = self.root / "backup"
        self.source.mkdir()
        self.app.mkdir()
        self.backup.mkdir()
        (self.app / "VietModHub.exe").write_bytes(b"old fake executable")
        (self.app / "data.bin").write_bytes(b"original application data")
        (self.source / "VietModHub.exe").write_bytes(b"new fake executable")
        (self.source / "data.bin").write_bytes(b"new application data - different size")

    def lock_file(self, path):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        def release():
            nonlocal handle
            if handle is not None:
                kernel.CloseHandle(handle)
                handle = None
        self.addCleanup(release)
        return release

    def run_script(self, before_rollback=None, after_backup=None, stop_at_checkpoint=False):
        pending = self.root / "pending_update.json"
        pending.write_text("pending fixture")
        (self.root / "probe.ps1.verify.ps1").write_text(build_copy_verifier(), encoding="utf-8-sig")
        script = build_apply_script(
            str(self.source), str(self.app), str(self.backup), 4294967294,
            startup_probe=str(self.root / "probe.ps1"), transaction_token="a" * 64, version="2.0.4",
            pending_update=str(pending),
        )
        lines = []
        for line in script.splitlines():
            if line.strip().startswith("timeout /t"):
                lines.append("rem test: no interactive delay")
            elif 'start ""' in line:
                lines.append('type nul > "%s"' % (self.root / "launched.txt"))
            elif after_backup and '-PathsOnly' not in line and '.verify.ps1" -Source "%s"' % self.app in line:
                lines.extend([
                    'type nul > "%s"' % (self.root / "rollback-waiting"),
                    ":wait_for_test",
                    'if not exist "%s" goto wait_for_test' % (self.root / "rollback-continue"),
                    line,
                ])
            elif line == ":rollback" and before_rollback:
                lines.extend([
                    line,
                    'type nul > "%s"' % (self.root / "rollback-waiting"),
                    ":wait_for_test",
                    'if not exist "%s" goto wait_for_test' % (self.root / "rollback-continue"),
                ])
            else:
                lines.append(line)
        path = self.root / "apply-test.bat"
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(path)]
        checkpoint = after_backup or before_rollback
        if not checkpoint:
            return subprocess.run(command, cwd=self.root, capture_output=True, timeout=60, creationflags=0x08000000)
        process = subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=0x08000000)
        try:
            import time
            deadline = time.monotonic() + 15
            while not (self.root / "rollback-waiting").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    self.fail("Script did not reach rollback boundary")
                time.sleep(0.02)
            checkpoint()
            if stop_at_checkpoint:
                process.terminate()
            else:
                (self.root / "rollback-continue").touch()
            stdout, stderr = process.communicate(timeout=30)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

    def assert_recovery_retained(self, phase):
        self.assertEqual((self.backup / "data.bin").read_bytes(), b"original application data")
        self.assertEqual((self.backup / "VietModHub.exe").read_bytes(), b"old fake executable")
        self.assertTrue((self.root / "pending_update.json").exists())
        self.assertTrue((self.root / "apply-test.bat").exists())
        self.assertTrue((self.root / "probe.ps1.robocopy.log").exists())
        self.assertEqual((self.root / "probe.ps1.phase").read_text().strip(), phase)
        self.assertFalse((self.root / "launched.txt").exists())

    def test_terminated_after_backup_retains_pristine_application_and_recovery(self):
        result = self.run_script(after_backup=lambda: None, stop_at_checkpoint=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.app / "data.bin").read_bytes(), b"original application data")
        self.assertEqual((self.app / "VietModHub.exe").read_bytes(), b"old fake executable")
        self.assert_recovery_retained("backing_up")

    def test_terminated_after_partial_apply_keeps_full_old_version_for_recovery(self):
        self.lock_file(self.source / "VietModHub.exe")
        result = self.run_script(before_rollback=lambda: None, stop_at_checkpoint=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.app / "data.bin").read_bytes(), b"new application data - different size")
        self.assert_recovery_retained("applying")

    def test_locked_backup_aborts_before_application_changes(self):
        locked = self.backup / "VietModHub.exe"
        locked.write_bytes(b"previous recovery backup")
        self.lock_file(locked)
        result = self.run_script()
        self.assertEqual(result.returncode, 20, result.stdout + result.stderr)
        self.assertEqual((self.app / "VietModHub.exe").read_bytes(), b"old fake executable")
        self.assertEqual((self.app / "data.bin").read_bytes(), b"original application data")

    def test_locked_update_source_rolls_back_partial_copy(self):
        self.lock_file(self.source / "VietModHub.exe")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.root / "pending_update.json").exists())
        self.assertEqual((self.root / "probe.ps1.phase").read_text().strip(), "rolled_back")
        self.assertEqual((self.app / "VietModHub.exe").read_bytes(), b"old fake executable")
        self.assertEqual((self.app / "data.bin").read_bytes(), b"original application data")
        self.assertEqual((self.backup / "data.bin").read_bytes(), b"original application data")

    def test_rollback_copy_failure_keeps_backup_and_does_not_launch_partial_app(self):
        self.lock_file(self.source / "VietModHub.exe")
        release_backup = []

        def block_recovery_copy():
            self.assertEqual((self.app / "data.bin").read_bytes(), b"new application data - different size")
            release_backup.append(self.lock_file(self.backup / "data.bin"))

        result = self.run_script(before_rollback=block_recovery_copy)
        self.assertEqual(result.returncode, 22, result.stdout + result.stderr)
        self.assertTrue((self.root / "pending_update.json").exists())
        self.assertEqual((self.root / "probe.ps1.phase").read_text().strip(), "rolling_back")
        release_backup[0]()
        self.assertEqual((self.backup / "data.bin").read_bytes(), b"original application data")
        self.assertEqual((self.backup / "VietModHub.exe").read_bytes(), b"old fake executable")
        self.assertTrue((self.root / "apply-test.bat").exists())
        self.assertTrue(self.source.exists())
        self.assertFalse((self.root / "launched.txt").exists())

    def test_missing_recovery_executable_never_launches_partial_app(self):
        self.lock_file(self.source / "VietModHub.exe")
        result = self.run_script(before_rollback=lambda: (self.backup / "VietModHub.exe").unlink())
        self.assertEqual(result.returncode, 21, result.stdout + result.stderr)
        self.assertEqual((self.backup / "data.bin").read_bytes(), b"original application data")
        self.assertFalse((self.root / "launched.txt").exists())
        self.assertTrue((self.root / "apply-test.bat").exists())

    def test_junction_in_application_is_rejected_before_copy(self):
        outside = self.root / "outside"
        outside.mkdir()
        protected = outside / "protected.dat"
        protected.write_bytes(b"outside original")
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(self.app / "linked"), str(outside)],
            capture_output=True, timeout=10, creationflags=0x08000000,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_script()
        self.assertEqual(result.returncode, 26, result.stdout + result.stderr)
        self.assertEqual(protected.read_bytes(), b"outside original")
        self.assertEqual((self.app / "data.bin").read_bytes(), b"original application data")
        self.assertEqual(list(self.backup.iterdir()), [])
        self.assertFalse((self.root / "launched.txt").exists())

    def test_backup_hash_mismatch_stops_before_application_changes(self):
        def corrupt_same_metadata():
            target = self.backup / "data.bin"
            stamp = target.stat().st_mtime
            target.write_bytes(b"x" * target.stat().st_size)
            os.utime(target, (stamp, stamp))
        result = self.run_script(after_backup=corrupt_same_metadata)
        self.assertEqual(result.returncode, 24, result.stdout + result.stderr)
        self.assertEqual((self.app / "data.bin").read_bytes(), b"original application data")
        self.assertTrue((self.root / "pending_update.json").exists())
        self.assertFalse((self.root / "launched.txt").exists())

    def test_backup_is_refreshed_even_when_size_and_timestamp_match(self):
        current = self.app / "data.bin"
        previous = self.backup / "data.bin"
        previous.write_bytes(b"x" * current.stat().st_size)
        stamp = current.stat().st_mtime
        os.utime(previous, (stamp, stamp))
        self.lock_file(self.source / "VietModHub.exe")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        log = (self.root / "probe.ps1.robocopy.log").read_text(errors="replace")
        self.assertEqual(previous.read_bytes(), b"original application data", log)
        self.assertEqual(current.read_bytes(), b"original application data", log)


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell required")
class UpdaterCopyVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-tree-verify-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        self.source.mkdir()
        self.destination.mkdir()
        (self.source / "data.bin").write_bytes(b"expected bytes")
        shutil.copy2(self.source / "data.bin", self.destination / "data.bin")
        self.verifier = self.root / "verify.ps1"
        self.verifier.write_text(build_copy_verifier(), encoding="utf-8-sig")

    def verify(self, exact=False):
        powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        command = [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.verifier),
                   "-Source", str(self.source), "-Destination", str(self.destination)]
        if exact:
            command.append("-Exact")
        return subprocess.run(command, capture_output=True, timeout=20, creationflags=0x08000000)

    def test_matching_trees_are_accepted(self):
        self.assertEqual(self.verify(exact=True).returncode, 0)

    def test_wrong_bytes_with_same_size_and_timestamp_are_rejected(self):
        target = self.destination / "data.bin"
        stamp = target.stat().st_mtime
        target.write_bytes(b"x" * target.stat().st_size)
        os.utime(target, (stamp, stamp))
        self.assertEqual(self.verify().returncode, 41)

    def test_missing_files_and_wrong_file_types_are_rejected(self):
        target = self.destination / "data.bin"
        target.unlink()
        self.assertEqual(self.verify().returncode, 41)
        target.mkdir()
        self.assertEqual(self.verify().returncode, 41)

    def test_extra_files_only_allowed_in_apply_mode(self):
        (self.destination / "extra.dat").write_bytes(b"preexisting file")
        self.assertEqual(self.verify().returncode, 0)
        self.assertEqual(self.verify(exact=True).returncode, 42)

    def test_junction_is_rejected_without_traversing_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "protected.dat").write_bytes(b"outside bytes")
        junction = self.destination / "linked"
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True, timeout=10, creationflags=0x08000000,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.verify().returncode, 43)
        self.assertEqual((outside / "protected.dat").read_bytes(), b"outside bytes")


if __name__ == "__main__":
    unittest.main()
