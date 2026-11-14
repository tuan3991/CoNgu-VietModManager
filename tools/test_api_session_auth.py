# -*- coding: utf-8 -*-
"""Regression test: API localhost bắt buộc session token và window chỉ nhận POST.

Không khởi động HTTP server thật; gọi Bottle WSGI trong memory để không mở cổng.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import routes


class ApiSessionAuthTests(unittest.TestCase):
    TOKEN = "test-session-token-123"

    def setUp(self):
        self.old_token = routes.SESSION_AUTH_TOKEN
        self.old_api = routes.api_instance
        routes.SESSION_AUTH_TOKEN = self.TOKEN
        routes.api_instance = Mock()
        routes.api_instance.drag_window.return_value = {"success": True}
        routes.api_instance.request_close.return_value = {"success": True}

    def tearDown(self):
        routes.SESSION_AUTH_TOKEN = self.old_token
        routes.api_instance = self.old_api

    def request(self, path, method="POST", token=None, query="", origin=None, host=None):
        body = b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "1",
            "wsgi.url_scheme": "http",
            "wsgi.version": (1, 0),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "CONTENT_LENGTH": "0",
        }
        if token is not None:
            environ["HTTP_X_APP_AUTH_TOKEN"] = token
        if origin is not None:
            environ["HTTP_ORIGIN"] = origin
        if host is not None:
            environ["HTTP_HOST"] = host
        status = []
        response = b"".join(routes.server_app(environ, lambda s, h, e=None: status.append(s)))
        return int(status[0].split()[0]), response

    def test_window_close_rejects_missing_token(self):
        status, _ = self.request("/api/window/close")
        self.assertEqual(status, 403)
        routes.api_instance.request_close.assert_not_called()

    def test_window_close_rejects_query_token(self):
        status, _ = self.request("/api/window/close", query="token=" + self.TOKEN)
        self.assertEqual(status, 403)
        routes.api_instance.request_close.assert_not_called()

    def test_window_close_allows_valid_header_token(self):
        status, body = self.request("/api/window/close", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8"))["success"])
        routes.api_instance.request_close.assert_called_once()

    def test_window_close_rejects_foreign_origin(self):
        status, _ = self.request("/api/window/close", token=self.TOKEN, origin="https://evil.example")
        self.assertEqual(status, 403)
        routes.api_instance.request_close.assert_not_called()

    def test_window_close_allows_loopback_origin(self):
        status, _ = self.request("/api/window/close", token=self.TOKEN, origin="http://127.0.0.1:49200")
        self.assertEqual(status, 200)
        routes.api_instance.request_close.assert_called_once()

    def test_window_drag_rejects_get_even_with_token(self):
        status, _ = self.request("/api/window/drag", method="GET", token=self.TOKEN)
        self.assertEqual(status, 405)
        routes.api_instance.drag_window.assert_not_called()

    def test_window_drag_allows_authenticated_post(self):
        status, body = self.request("/api/window/drag", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8"))["success"])
        routes.api_instance.drag_window.assert_called_once()

    def test_api_rejects_foreign_host_header(self):
        status, _ = self.request("/api/window/close", token=self.TOKEN, host="evil.example:8080")
        self.assertEqual(status, 403)
        routes.api_instance.request_close.assert_not_called()

    def test_api_allows_loopback_host_with_port(self):
        status, _ = self.request("/api/window/close", token=self.TOKEN, host="127.0.0.1:49200")
        self.assertEqual(status, 200)
        routes.api_instance.request_close.assert_called_once()

    def test_api_requires_token_even_with_loopback_host(self):
        status, _ = self.request("/api/window/close", host="localhost:49200")
        self.assertEqual(status, 403)
        routes.api_instance.request_close.assert_not_called()

    def test_only_authenticated_local_post_can_acknowledge_update_startup(self):
        for kwargs in (
            {}, {"token": "wrong"}, {"token": self.TOKEN, "method": "GET"},
            {"token": self.TOKEN, "origin": "https://evil.example"},
            {"token": self.TOKEN, "host": "evil.example"},
        ):
            with self.subTest(request=kwargs), \
                 patch("core.update_startup.acknowledge_update_startup") as acknowledge:
                self.request("/api/heartbeat", **kwargs)
                acknowledge.assert_not_called()
        with patch("core.update_startup.acknowledge_update_startup") as acknowledge:
            self.request("/api/heartbeat", token=self.TOKEN, host="127.0.0.1:1", origin="http://127.0.0.1:1")
            acknowledge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
