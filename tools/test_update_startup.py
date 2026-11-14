import ctypes
import json
import os
import shutil
import subprocess
import time
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.update_startup import acknowledge_update_startup, build_startup_probe


class UpdateStartupAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-startup-ack-")
        self.addCleanup(self.temp.cleanup)
        self.marker = Path(self.temp.name) / "ready.json"
        self.environment = {
            "CONGU_UPDATE_TOKEN": "a" * 64,
            "CONGU_UPDATE_VERSION": "2.0.4",
            "CONGU_UPDATE_MARKER": str(self.marker),
        }

    def test_acknowledges_running_version_and_exact_process(self):
        with patch.dict(os.environ, self.environment):
            self.assertTrue(acknowledge_update_startup("2.0.4"))
        payload = json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertEqual(payload, {
            "token": "a" * 64, "version": "2.0.4", "pid": os.getpid(),
            "executable": os.path.realpath(sys.executable),
        })
        self.assertEqual(list(self.marker.parent.glob(".startup-*")), [])

    def test_wrong_version_or_token_never_writes_acknowledgement(self):
        for changed in ({"CONGU_UPDATE_VERSION": "2.0.5"}, {"CONGU_UPDATE_TOKEN": "invalid"}):
            with patch.dict(os.environ, dict(self.environment, **changed)):
                self.assertFalse(acknowledge_update_startup("2.0.4"))
            self.assertFalse(self.marker.exists())

    def test_incomplete_write_preserves_existing_marker(self):
        self.marker.write_bytes(b"previous marker")
        with patch.dict(os.environ, self.environment), \
             patch("core.update_startup.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                acknowledge_update_startup("2.0.4")
        self.assertEqual(self.marker.read_bytes(), b"previous marker")
        self.assertEqual(list(self.marker.parent.glob(".startup-*")), [])


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell required")
class UpdateStartupProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="congu-startup-probe-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        cls.executable = cls.root / "FakeUpdatedApp.exe"
        cls.probe = cls.root / "probe.ps1"
        cls.probe.write_text(build_startup_probe(), encoding="utf-8-sig")
        code = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
public class FakeUpdatedApp {
    public static void Main() {
        string mode = Environment.GetEnvironmentVariable("CONGU_TEST_MODE");
        string flag = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "old.flag");
        if (File.Exists(flag) && File.ReadAllText(flag) == "old") {
            string started = Environment.GetEnvironmentVariable("CONGU_TEST_OLD_STARTED");
            File.WriteAllText(started + ".pid", Process.GetCurrentProcess().Id.ToString());
            File.WriteAllText(started, "old version started");
            return;
        }
        int pid = Process.GetCurrentProcess().Id;
        File.WriteAllText(Environment.GetEnvironmentVariable("CONGU_TEST_PID_FILE"), pid.ToString());
        if (mode == "exit") return;
        if (mode == "unrelated") { Thread.Sleep(30000); return; }
        string token = Environment.GetEnvironmentVariable("CONGU_UPDATE_TOKEN");
        string version = Environment.GetEnvironmentVariable("CONGU_UPDATE_VERSION");
        string executable = Process.GetCurrentProcess().MainModule.FileName;
        if (mode == "wrong-token") token = new string('b', 64);
        if (mode == "wrong-version") version = "0.0.0";
        if (mode == "wrong-pid") pid += 123456;
        if (mode == "wrong-path") executable += ".other";
        string payload = "{\"token\":\"" + token + "\",\"version\":\"" + version +
            "\",\"pid\":" + pid.ToString() + ",\"executable\":\"" +
            executable.Replace("\\", "\\\\") + "\"}";
        File.WriteAllText(Environment.GetEnvironmentVariable("CONGU_UPDATE_MARKER"), payload);
        Thread.Sleep(mode == "valid" ? 1500 : 30000);
    }
}
'''
        source = cls.root / "FakeUpdatedApp.cs"
        source.write_text(code, encoding="utf-8")
        compiler = cls.root / "compile.ps1"
        compiler.write_text(
            "param([string]$Source, [string]$Output)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "Add-Type -Path $Source -OutputAssembly $Output -OutputType ConsoleApplication\n",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [cls.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(compiler),
             "-Source", str(source), "-Output", str(cls.executable)],
            capture_output=True, timeout=60, creationflags=0x08000000,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def run_probe(self, mode):
        marker = self.root / (mode + ".json")
        pid_file = self.root / (mode + ".pid")
        environment = dict(os.environ, CONGU_TEST_MODE=mode, CONGU_TEST_PID_FILE=str(pid_file))
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.probe),
             "-Executable", str(self.executable), "-Marker", str(marker),
             "-Token", "a" * 64, "-Version", "2.0.4", "-TimeoutSeconds", "2"],
            env=environment, capture_output=True, timeout=20, creationflags=0x08000000,
        )
        return result, int(pid_file.read_text())

    def assert_process_exited(self, pid):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
            finally:
                kernel.CloseHandle(handle)

    def test_accepts_only_matching_transaction_version_pid_and_path(self):
        result, _pid = self.run_probe("valid")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_acknowledgements_timeout_and_stop_only_launched_process(self):
        environment = dict(os.environ, CONGU_TEST_MODE="unrelated",
                           CONGU_TEST_PID_FILE=str(self.root / "unrelated.pid"))
        unrelated = subprocess.Popen([str(self.executable)], env=environment, creationflags=0x08000000)
        try:
            for mode in ("wrong-token", "wrong-version", "wrong-pid", "wrong-path"):
                with self.subTest(mode=mode):
                    result, pid = self.run_probe(mode)
                    self.assertEqual(result.returncode, 32, result.stdout + result.stderr)
                    self.assert_process_exited(pid)
                    self.assertIsNone(unrelated.poll())
        finally:
            if unrelated.poll() is None:
                unrelated.terminate()
            unrelated.wait(timeout=10)

    def test_batch_valid_ack_commits_verified_update(self):
        from core.updater_apply import build_apply_script, build_copy_verifier
        Path(str(self.probe) + ".verify.ps1").write_text(build_copy_verifier(), encoding="utf-8-sig")
        with tempfile.TemporaryDirectory(prefix="congu-startup-success-") as temporary:
            root = Path(temporary)
            source, app, backup = root / "new", root / "app", root / "backup"
            source.mkdir()
            app.mkdir()
            for directory, content in ((source, "new"), (app, "old")):
                shutil.copyfile(self.executable, directory / "VietModHub.exe")
                (directory / "old.flag").write_text(content)
                (directory / "data.bin").write_text(content + " application data")
            pending = root / "pending.json"
            pending.write_text("pending")
            pid_file = root / "new.pid"
            environment = dict(os.environ, CONGU_TEST_MODE="valid", CONGU_TEST_PID_FILE=str(pid_file))
            script = build_apply_script(
                str(source), str(app), str(backup), 4294967294, watchdog_seconds=3,
                startup_probe=str(self.probe), transaction_token="a" * 64, version="2.0.4",
                pending_update=str(pending),
            )
            lines = ["rem test: skip wait" if line.strip().startswith("timeout /t") else line
                     for line in script.splitlines()]
            batch = root / "apply.bat"
            batch.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", str(batch)], env=environment,
                capture_output=True, timeout=30, creationflags=0x08000000,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_process_exited(int(pid_file.read_text()))
            self.assertFalse(pending.exists())
            self.assertEqual((app / "data.bin").read_text(), "new application data")
            self.assertEqual((backup / "data.bin").read_text(), "old application data")
            self.assertEqual(Path(str(self.probe) + ".phase").read_text().strip(), "complete")

    def test_batch_startup_failure_restores_and_launches_old_fixture(self):
        from core.updater_apply import build_apply_script, build_copy_verifier
        Path(str(self.probe) + ".verify.ps1").write_text(build_copy_verifier(), encoding="utf-8-sig")
        with tempfile.TemporaryDirectory(prefix="congu-startup-rollback-") as temporary:
            root = Path(temporary)
            source, app, backup = root / "new", root / "app", root / "backup"
            source.mkdir()
            app.mkdir()
            for directory, content in ((source, "new"), (app, "old")):
                shutil.copyfile(self.executable, directory / "VietModHub.exe")
                (directory / "old.flag").write_text(content)
                (directory / "data.bin").write_text(content + " application data")
            old_started = root / "old-started.txt"
            pid_file = root / "new.pid"
            environment = dict(os.environ, CONGU_TEST_MODE="exit",
                               CONGU_TEST_PID_FILE=str(pid_file), CONGU_TEST_OLD_STARTED=str(old_started))
            script = build_apply_script(
                str(source), str(app), str(backup), 4294967294,
                watchdog_seconds=3, startup_probe=str(self.probe),
                transaction_token="a" * 64, version="2.0.4",
            )
            lines = ["rem test: skip wait" if line.strip().startswith("timeout /t") else line
                     for line in script.splitlines()]
            batch = root / "apply.bat"
            batch.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", str(batch)], env=environment,
                capture_output=True, timeout=30, creationflags=0x08000000,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            deadline = time.monotonic() + 5
            while not old_started.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(old_started.read_text(), "old version started")
            self.assert_process_exited(int(Path(str(old_started) + ".pid").read_text()))
            self.assertEqual((app / "data.bin").read_text(), "old application data")
            self.assertEqual((backup / "data.bin").read_text(), "old application data")
            self.assert_process_exited(int(pid_file.read_text()))

    def test_exited_child_is_not_successful_startup(self):
        result, pid = self.run_probe("exit")
        self.assertEqual(result.returncode, 31, result.stdout + result.stderr)
        self.assert_process_exited(pid)


if __name__ == "__main__":
    unittest.main()
