# -*- coding: utf-8 -*-
"""Regression tests cho downloader atomic; dùng HTTP server chỉ trong localhost."""
import http.server
import json
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.downloader.http_downloader import download_file_with_progress


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b"new verified payload"

    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        if self.path == "/short":
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.payload) + 10))
            self.end_headers()
            self.wfile.write(self.payload)
            return
        if self.path == "/drop":
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.payload) * 4))
            self.end_headers()
            self.wfile.write(self.payload[:4])
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)


class _Server(socketserver.TCPServer):
    allow_reuse_address = True


class HttpDownloaderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="congu-download-test-")
        self.addCleanup(self.temp.cleanup)
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def destination(self):
        dest = Path(self.temp.name) / "cache" / "package.congu"
        dest.parent.mkdir()
        dest.write_bytes(b"old good package")
        return dest

    def test_short_response_keeps_existing_destination(self):
        dest = self.destination()
        with self.assertRaisesRegex(IOError, "không đầy đủ"):
            download_file_with_progress(self.base_url + "/short", str(dest))
        self.assertEqual(dest.read_bytes(), b"old good package")
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_cancel_keeps_existing_destination(self):
        dest = self.destination()
        with self.assertRaises(InterruptedError):
            download_file_with_progress(self.base_url + "/ok", str(dest), cancel_check=lambda: True)
        self.assertEqual(dest.read_bytes(), b"old good package")
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_installer_bad_checksum_preserves_previous_cache(self):
        from core.installer_pipeline import install_ops
        root = Path(self.temp.name)
        game_dir = root / "game"
        game_dir.mkdir()
        cache = root / "cache" / "fake-game"
        cache.mkdir(parents=True)
        previous = cache / "mod_package.congu"
        previous.write_bytes(b"previous cache")
        games_file = root / "games.json"
        games_file.write_text(json.dumps([{"id": "fake-game", "title": "Fake", "vietnamese_title": "Fake",
                                          "download_url": self.base_url + "/bad.congu", "sha256": "0" * 64}]), encoding="utf-8")
        with patch.object(install_ops, "APPDATA_DIR", str(root)), \
             patch.object(install_ops, "get_active_games_json_path", return_value=str(games_file)), \
             patch.object(install_ops, "load_user_config", return_value={"fake-game_path": str(game_dir)}), \
             patch.object(install_ops, "verify_and_resolve_game_path", return_value=(True, str(game_dir), ""), create=True), \
             patch.object(install_ops, "record_preexisting_environment"), \
             patch.object(install_ops, "is_running_as_admin", return_value=True), \
             patch.object(install_ops, "check_game_running", return_value=(False, "")), \
             patch.object(install_ops, "find_mod_source_dir", return_value=str(root / "missing")), \
             patch.object(install_ops, "check_has_mod_files", return_value=False), \
             patch.object(install_ops, "find_reusable_cached_package", return_value=""), \
             patch.object(install_ops, "get_repo_dir", return_value=str(root / "missing"), create=True), \
             patch.multiple(install_ops, DEFAULT_REPO_DIR=str(root / "missing"), FALLBACK_REPO_DIR=str(root / "missing"), USER_DOCS_DIR=str(root / "missing"), APP_DIR=str(root / "missing"), create=True), \
             patch.object(install_ops.security, "execute_secure_install") as secure_install:
            result = install_ops.install_mod_impl("fake-game")
        self.assertFalse(result["success"], result)
        self.assertEqual(previous.read_bytes(), b"previous cache")
        secure_install.assert_not_called()
        self.assertEqual(list(cache.glob(".congu-download-*.tmp")), [])

    def test_validator_failure_preserves_existing_destination(self):
        dest = self.destination()
        def reject(path):
            self.assertEqual(Path(path).read_bytes(), _Handler.payload)
            raise ValueError("bad checksum")
        with self.assertRaisesRegex(ValueError, "bad checksum"):
            download_file_with_progress(self.base_url + "/ok", str(dest), validate_download=reject)
        self.assertEqual(dest.read_bytes(), b"old good package")
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_success_replaces_existing_destination_atomically(self):
        dest = self.destination()
        self.assertTrue(download_file_with_progress(self.base_url + "/ok", str(dest)))
        self.assertEqual(dest.read_bytes(), _Handler.payload)
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_connection_dropped_keeps_existing_destination(self):
        dest = self.destination()
        with self.assertRaises(Exception):
            download_file_with_progress(self.base_url + "/drop", str(dest))
        self.assertEqual(dest.read_bytes(), b"old good package")
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_unreachable_server_keeps_existing_destination(self):
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        dest = self.destination()
        with self.assertRaises(Exception):
            download_file_with_progress(f"http://127.0.0.1:{port}/ok", str(dest), timeout=5.0)
        self.assertEqual(dest.read_bytes(), b"old good package")
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])

    def test_two_downloads_same_destination_do_not_share_temp_file(self):
        dest = self.destination()
        errors = []

        def worker():
            try:
                download_file_with_progress(self.base_url + "/ok", str(dest))
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=worker)
        second = threading.Thread(target=worker)
        first.start()
        second.start()
        first.join()
        second.join()
        self.assertEqual(errors, [])
        self.assertEqual(dest.read_bytes(), _Handler.payload)
        self.assertEqual(list(dest.parent.glob(".congu-download-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
