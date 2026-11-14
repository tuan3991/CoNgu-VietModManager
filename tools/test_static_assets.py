# -*- coding: utf-8 -*-
"""Regression test: mọi asset tĩnh mà index.html tham chiếu phải được server phục vụ.

Lỗi từng gặp: index.html nạp Tailwind/Lucide bằng đường dẫn tương đối
(`vendor/...`, `app_icon.png`) nhưng Bottle chỉ có route `/static/...`, khiến
toàn bộ CSS utility 404 -> logo hiển thị đúng kích thước gốc 1024px và tràn
màn hình.

Test gọi thẳng WSGI app trong bộ nhớ (không mở cổng mạng) và kiểm tra:
  1. Các thư mục asset ở gốc (vendor/, icons/, css/, js/ ...) trả 200.
  2. Mọi `src`/`href` nội bộ trong static/index.html đều trả 200.
  3. Route bắt tất cả không che lỗi 404 của /api/.
"""
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import routes  # noqa: E402


def _request(path, method="GET"):
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "1",
        "wsgi.url_scheme": "http",
        "wsgi.version": (1, 0),
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "CONTENT_LENGTH": "0",
    }
    captured = []

    def start_response(status, headers, exc_info=None):
        captured.append((status, headers))

    body = b"".join(routes.server_app(environ, start_response))
    status_code = int(captured[0][0].split()[0])
    return status_code, body, dict(captured[0][1])


class StaticAssetTests(unittest.TestCase):
    def test_vendor_bundle_is_served(self):
        """Tailwind/Lucide bundle local là điều kiện sống còn của giao diện."""
        for path in (
            "/static/vendor/tailwindcss-3.4.17.js",
            "/vendor/tailwindcss-3.4.17.js",
            "/static/vendor/lucide.min.js",
        ):
            with self.subTest(path=path):
                status, body, _ = _request(path)
                self.assertEqual(status, 200)
                self.assertGreater(len(body), 1000)

    def test_root_relative_assets_are_served(self):
        for path in (
            "/app_icon.png",
            "/pixel_city_bg.png",
            "/icons/game_placeholder.png",
            "/static/app_icon.png",
            "/static/css/styles.css",
        ):
            with self.subTest(path=path):
                status, body, _ = _request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)

    def test_every_local_asset_referenced_by_index_html_resolves(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        refs = set()
        for match in re.finditer(r'(?:src|href)="([^"]+)"', html):
            ref = match.group(1).strip()
            if not ref or ref.startswith(("http://", "https://", "data:", "#", "mailto:")):
                continue
            refs.add(ref.split("?", 1)[0])
        self.assertTrue(refs, "index.html phải tham chiếu ít nhất một asset nội bộ")
        for ref in sorted(refs):
            path = "/" + ref.lstrip("./")
            with self.subTest(ref=ref):
                status, _, _ = _request(path)
                self.assertEqual(status, 200, f"{ref} phải được server phục vụ")

    def test_unknown_api_path_still_returns_404(self):
        # Không có token -> 403 từ hook bảo mật; có token -> 404. Cả hai đều chứng minh
        # route asset bắt-tất-cả không trả 200 cho đường dẫn API không tồn tại.
        status, _, _ = _request("/api/khong-ton-tai-dau")
        self.assertIn(status, (403, 404))


if __name__ == "__main__":
    unittest.main()
