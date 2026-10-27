# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Cloud Save & Google Drive Ecosystem Module
--------------------------------------------------------------------
- Pure Python 3.11 + standard libraries (urllib.request, json, zipfile, hashlib, ctypes).
- Zero third-party dependencies (keeps PyInstaller Portable build 0 MB extra bloat).
- OAuth2 PKCE Desktop Flow for personal Google Drive accounts (Zero Backend Cost).
- 3-Way Save Sync & Conflict Resolution (Local vs Cloud vs Last Synced).
- Local Safe Backup rotation before overwrite (up to 3 slots).
- Windows DPAPI (CryptProtectData) token encryption.
- Seamless Post-Exit Auto Sync for Playtime & Achievements.
"""

import os
import sys
import time
import json
import socket
import zipfile
import hashlib
import secrets
import base64
import urllib.request
import urllib.parse
import urllib.error
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Windows DPAPI Token Encryption
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    def dpapi_encrypt(data_bytes: bytes) -> bytes:
        in_blob = DATA_BLOB(len(data_bytes), ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), 'VietModHub_Token', None, None, None, 0, ctypes.byref(out_blob)):
            raise RuntimeError("CryptProtectData failed")
        enc = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        return enc

    def dpapi_decrypt(enc_bytes: bytes) -> bytes:
        in_blob = DATA_BLOB(len(enc_bytes), ctypes.cast(ctypes.create_string_buffer(enc_bytes), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise RuntimeError("CryptUnprotectData failed")
        dec = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        return dec
else:
    def dpapi_encrypt(data_bytes: bytes) -> bytes:
        return b"ENC:" + base64.b64encode(data_bytes)
    def dpapi_decrypt(enc_bytes: bytes) -> bytes:
        if enc_bytes.startswith(b"ENC:"):
            return base64.b64decode(enc_bytes[4:])
        return enc_bytes


DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email"
]

CLOUD_ROOT_FOLDER_NAME = "VietModHub_Cloud"


def base64url_encode(data: bytes) -> str:
    """Encode bytes using URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Xử lý redirect URL của Google OAuth2 sau khi người dùng xác thực."""

    def log_message(self, format, *args):
        pass  # Tắt log stdout của HTTP handler

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>CỔ NGỮ - Kết Nối Google Drive Thành Công</title>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                        background: #090d16;
                        color: #f1f5f9;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        margin: 0;
                    }
                    .card {
                        background: #111827;
                        border: 1px solid #10b981;
                        box-shadow: 0 10px 25px -5px rgba(16, 185, 129, 0.2);
                        border-radius: 16px;
                        padding: 40px;
                        text-align: center;
                        max-width: 450px;
                    }
                    h1 { color: #10b981; font-size: 24px; margin-bottom: 12px; }
                    p { color: #94a3b8; font-size: 15px; line-height: 1.6; }
                    .badge {
                        display: inline-block;
                        background: rgba(16, 185, 129, 0.15);
                        color: #34d399;
                        font-weight: 600;
                        padding: 6px 14px;
                        border-radius: 9999px;
                        margin-bottom: 20px;
                    }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="badge">CỔ NGỮ CLOUD ECOSYSTEM</div>
                    <h1>Đăng Nhập Thành Công!</h1>
                    <p>Tài khoản Google Drive của bạn đã được liên kết với CỔ NGỮ (VietModHub Pro).<br>Bạn có thể đóng tab này và quay lại ứng dụng.</p>
                </div>
                <script>setTimeout(function(){ window.close(); }, 3000);</script>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            err = params.get("error", ["Unknown error"])[0]
            self.server.auth_error = err
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h1>Dang nhap that bai: {err}</h1>".encode("utf-8"))


class GoogleDriveClient:
    """Client giao tiếp trực tiếp với Google Drive REST API v3 qua urllib (Zero-Bloat)."""

    def __init__(self, token_data: dict, token_save_callback=None):
        self.access_token = token_data.get("access_token", "")
        self.refresh_token = token_data.get("refresh_token", "")
        self.expires_at = token_data.get("expires_at", 0)
        self.client_id = token_data.get("client_id", "")
        self.client_secret = token_data.get("client_secret", "")
        self.user_profile = token_data.get("user_profile", {})
        self.token_save_callback = token_save_callback
        self.lock = threading.Lock()
        self._cached_root_folder_id = None
        self._cached_saves_folder_id = None

    def refresh_access_token_if_needed(self) -> bool:
        """Tự động làm mới access_token nếu sắp hết hạn (còn dưới 120s)."""
        now = time.time()
        if self.access_token and (self.expires_at - now) > 120:
            return True

        if not self.refresh_token:
            return False

        with self.lock:
            if self.access_token and (self.expires_at - time.time()) > 120:
                return True

            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token"
            }
            if self.client_secret:
                data["client_secret"] = self.client_secret

            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(token_url, data=encoded_data, headers={
                "Content-Type": "application/x-www-form-urlencoded"
            })

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    self.access_token = resp_data["access_token"]
                    self.expires_at = time.time() + resp_data.get("expires_in", 3600)
                    if self.token_save_callback:
                        self.token_save_callback(self.to_dict())
                    return True
            except Exception as e:
                print(f"[GoogleDriveClient] Token refresh failed: {e}")
                return False

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "user_profile": self.user_profile
        }

    def _api_request(self, url: str, method: str = "GET", headers: dict = None, body: bytes = None, timeout: int = 30):
        """Thực thi request REST API kèm Bearer Token và cơ chế tự refresh khi 401."""
        self.refresh_access_token_if_needed()

        req_headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "CoNgu-VietModHub/2.0"
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                content = resp.read()
                return status, content
        except urllib.error.HTTPError as e:
            if e.code == 401:
                # Token hết hạn bất ngờ -> Refresh 1 lần và retry
                if self.refresh_access_token_if_needed():
                    req_headers["Authorization"] = f"Bearer {self.access_token}"
                    req2 = urllib.request.Request(url, data=body, headers=req_headers, method=method)
                    with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                        return resp2.status, resp2.read()
            err_body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            raise RuntimeError(f"Google Drive API error ({e.code}): {err_body}")

    def get_or_create_folder(self, folder_name: str, parent_id: str = None) -> str:
        """Tìm hoặc tạo thư mục trên Google Drive."""
        q_parts = [
            f"name = '{folder_name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false"
        ]
        if parent_id:
            q_parts.append(f"'{parent_id}' in parents")
        else:
            q_parts.append("'root' in parents")

        query = " and ".join(q_parts)
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id,name)"
        status, data = self._api_request(url)
        res = json.loads(data.decode("utf-8"))
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        # Chưa có -> Tạo mới
        create_url = "https://www.googleapis.com/drive/v3/files?fields=id,name"
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_id:
            meta["parents"] = [parent_id]

        body = json.dumps(meta).encode("utf-8")
        status, data = self._api_request(create_url, method="POST", headers={"Content-Type": "application/json"}, body=body)
        created = json.loads(data.decode("utf-8"))
        return created["id"]

    def get_cloud_root_folders(self) -> tuple[str, str]:
        """Lấy hoặc khởi tạo cấu trúc thư mục VietModHub_Cloud/saves."""
        if self._cached_root_folder_id and self._cached_saves_folder_id:
            return self._cached_root_folder_id, self._cached_saves_folder_id

        root_id = self.get_or_create_folder(CLOUD_ROOT_FOLDER_NAME)
        saves_id = self.get_or_create_folder("saves", parent_id=root_id)
        self._cached_root_folder_id = root_id
        self._cached_saves_folder_id = saves_id
        return root_id, saves_id

    def list_files_in_folder(self, folder_id: str) -> dict:
        """Liệt kê toàn bộ file trong thư mục Drive kèm metadata và appProperties."""
        query = f"'{folder_id}' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id,name,size,modifiedTime,appProperties)"
        status, data = self._api_request(url)
        res = json.loads(data.decode("utf-8"))
        file_map = {}
        for f in res.get("files", []):
            file_map[f["name"]] = f
        return file_map

    def upload_file_multipart(self, name: str, file_path_or_bytes, parent_id: str, app_properties: dict = None, existing_file_id: str = None) -> dict:
        """Tải file lên Drive qua Multipart Upload v3 (Hỗ trợ tạo mới hoặc ghi đè in-place)."""
        boundary = f"----VietModHubBoundary{secrets.token_hex(8)}"
        
        metadata = {
            "name": name,
        }
        if not existing_file_id and parent_id:
            metadata["parents"] = [parent_id]
        if app_properties:
            metadata["appProperties"] = app_properties

        meta_json = json.dumps(metadata)

        if isinstance(file_path_or_bytes, str):
            with open(file_path_or_bytes, "rb") as f:
                file_content = f.read()
        else:
            file_content = file_path_or_bytes

        # Tạo payload Multipart chuẩn MIME
        parts = []
        parts.append(f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta_json}\r\n".encode("utf-8"))
        parts.append(f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        parts.append(file_content)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(parts)

        headers = {
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body))
        }

        if existing_file_id:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_file_id}?uploadType=multipart&fields=id,name,modifiedTime,size,appProperties"
            method = "PATCH"
        else:
            url = f"https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,modifiedTime,size,appProperties"
            method = "POST"

        status, resp_bytes = self._api_request(url, method=method, headers=headers, body=body, timeout=60)
        return json.loads(resp_bytes.decode("utf-8"))

    def download_file(self, file_id: str, dest_path: str):
        """Tải file từ Drive và lưu an toàn vào đĩa cứng (nguyên tử qua file tạm)."""
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        self.refresh_access_token_if_needed()

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "CoNgu-VietModHub/2.0"
        })

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        tmp_dest = dest_path + f".tmp_{secrets.token_hex(4)}"

        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_dest, "wb") as out_f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_f.write(chunk)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.replace(tmp_dest, dest_path)
        except Exception:
            if os.path.exists(tmp_dest):
                try:
                    os.remove(tmp_dest)
                except Exception:
                    pass
            raise


class CloudSyncManager:
    """
    Quản lý toàn bộ hệ sinh thái Cloud Save, Đồng bộ 3 Chiều & Bảo vệ Dữ liệu Cục bộ.
    """

    def __init__(self, appdata_dir: str):
        self.appdata_dir = appdata_dir
        self.token_file = os.path.join(appdata_dir, "gdrive_token.enc")
        self.profile_path = os.path.join(appdata_dir, "user_profile.json")
        self.backups_dir = os.path.join(appdata_dir, "save_backups")
        os.makedirs(self.backups_dir, exist_ok=True)
        os.makedirs(self.appdata_dir, exist_ok=True)

        self.lock = threading.RLock()
        self.client = None
        self._load_saved_client()

    def _load_saved_client(self):
        """Tải và giải mã token đã lưu từ đĩa."""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "rb") as f:
                    encrypted = f.read()
                decrypted = dpapi_decrypt(encrypted)
                token_data = json.loads(decrypted.decode("utf-8"))
                self.client = GoogleDriveClient(token_data, token_save_callback=self._save_token)
            except Exception as e:
                print(f"[CloudSyncManager] Không thể nạp token Drive đã lưu: {e}")
                self.client = None

    def _save_token(self, token_data: dict):
        """Mã hóa bằng DPAPI và ghi token vào đĩa."""
        try:
            raw = json.dumps(token_data, ensure_ascii=False).encode("utf-8")
            enc = dpapi_encrypt(raw)
            with open(self.token_file, "wb") as f:
                f.write(enc)
        except Exception as e:
            print(f"[CloudSyncManager] Lưu token thất bại: {e}")

    def is_connected(self) -> bool:
        """Kiểm tra xem người dùng đã liên kết Google Drive chưa."""
        return self.client is not None and bool(self.client.refresh_token or self.client.access_token)

    def get_connection_info(self) -> dict:
        """Lấy thông tin tài khoản Google Drive đang liên kết."""
        if not self.is_connected():
            return {"connected": False}
        prof = self.client.user_profile or {}
        return {
            "connected": True,
            "email": prof.get("email", ""),
            "name": prof.get("name", ""),
            "picture": prof.get("picture", "")
        }

    def start_oauth_flow(self, client_id: str, client_secret: str = "") -> dict:
        """
        Bắt đầu luồng OAuth2 PKCE Desktop Flow:
        1. Tạo code_verifier & code_challenge (S256).
        2. Mở ephemeral local server trên 127.0.0.1:0.
        3. Mở trình duyệt mặc định để người dùng đăng nhập.
        4. Thu nhận Authorization Code, đổi lấy Tokens và lưu trữ mã hóa.
        """
        if not client_id:
            return {"success": False, "error": "Chưa cấu hình Google Client ID"}

        # 1. Sinh PKCE Verifier & Challenge
        code_verifier = secrets.token_urlsafe(64)
        hashed = hashlib.sha256(code_verifier.encode('ascii')).digest()
        code_challenge = base64url_encode(hashed)

        # 2. Khởi tạo Local Server tạm thời
        server = HTTPServer(("127.0.0.1", 0), OAuthCallbackHandler)
        port = server.server_port
        redirect_uri = f"http://127.0.0.1:{port}"
        server.auth_code = None
        server.auth_error = None

        # 3. Mở trình duyệt đến Google OAuth2
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent"
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

        import webbrowser
        webbrowser.open(auth_url)

        # Chờ callback từ trình duyệt trong luồng riêng để không treo ứng dụng
        server.timeout = 180  # Cho phép tối đa 3 phút để đăng nhập
        server.handle_request()

        if getattr(server, "auth_error", None):
            return {"success": False, "error": f"Lỗi xác thực Google: {server.auth_error}"}

        auth_code = getattr(server, "auth_code", None)
        if not auth_code:
            return {"success": False, "error": "Hết thời gian chờ đăng nhập (Timeout)"}

        # 4. Trao đổi Auth Code lấy Access & Refresh Token
        token_url = "https://oauth2.googleapis.com/token"
        token_payload = {
            "client_id": client_id,
            "code": auth_code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        if client_secret:
            token_payload["client_secret"] = client_secret

        enc_payload = urllib.parse.urlencode(token_payload).encode("utf-8")
        req = urllib.request.Request(token_url, data=enc_payload, headers={
            "Content-Type": "application/x-www-form-urlencoded"
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                token_resp = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Đổi token thất bại: {e}"}

        access_token = token_resp.get("access_token", "")
        refresh_token = token_resp.get("refresh_token", "")
        expires_in = token_resp.get("expires_in", 3600)

        # 5. Lấy User Profile (Tên, Email, Avatar)
        user_info = {}
        try:
            u_req = urllib.request.Request("https://www.googleapis.com/oauth2/v3/userinfo", headers={
                "Authorization": f"Bearer {access_token}"
            })
            with urllib.request.urlopen(u_req, timeout=10) as u_resp:
                user_info = json.loads(u_resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[CloudSyncManager] Không thể lấy userinfo: {e}")

        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in,
            "client_id": client_id,
            "client_secret": client_secret,
            "user_profile": user_info
        }

        self._save_token(token_data)
        self.client = GoogleDriveClient(token_data, token_save_callback=self._save_token)

        # Đảm bảo tạo sẵn thư mục VietModHub_Cloud/saves trên Drive
        try:
            self.client.get_cloud_root_folders()
        except Exception as e:
            print(f"[CloudSyncManager] Khởi tạo folder ban đầu: {e}")

        return {
            "success": True,
            "user": user_info
        }

    def logout(self) -> dict:
        """Đăng xuất và hủy token cục bộ."""
        with self.lock:
            self.client = None
            if os.path.exists(self.token_file):
                try:
                    os.remove(self.token_file)
                except Exception:
                    pass
        return {"success": True}

    def _load_user_profile_data(self) -> dict:
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"games": {}}

    def _save_user_profile_data(self, data: dict):
        with self.lock:
            try:
                tmp = self.profile_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.profile_path)
            except Exception as e:
                print(f"[CloudSyncManager] Lưu user_profile.json thất bại: {e}")

    # ==========================================
    # CÁC THUẬT TOÁN XỬ LÝ SAVE GAME CỤC BỘ
    # ==========================================

    def resolve_save_path(self, raw_path: str, game_dir: str = None) -> str:
        """
        Phân giải biến môi trường Windows và định danh đặc biệt sang đường dẫn tuyệt đối:
        - %USERPROFILE%, %APPDATA%, %LOCALAPPDATA%, %PUBLIC%, %DOCUMENTS%, %SAVEDGAMES%
        - <GameDir>
        - <SteamUserdata>
        """
        if not raw_path:
            return ""

        path_str = raw_path

        # Biến GameDir
        if game_dir and "<GameDir>" in path_str:
            path_str = path_str.replace("<GameDir>", game_dir)

        # Biến Saved Games & Documents
        user_prof = os.environ.get("USERPROFILE", "")
        if "%SAVEDGAMES%" in path_str:
            saved_games_dir = os.path.join(user_prof, "Saved Games")
            path_str = path_str.replace("%SAVEDGAMES%", saved_games_dir)
        if "%DOCUMENTS%" in path_str:
            docs_dir = os.path.join(user_prof, "Documents")
            path_str = path_str.replace("%DOCUMENTS%", docs_dir)

        # Biến SteamUserdata
        if "<SteamUserdata>" in path_str:
            steam_path = self._find_steam_userdata_dir()
            if steam_path:
                path_str = path_str.replace("<SteamUserdata>", steam_path)

        # Phân giải chuẩn Windows %VAR%
        expanded = os.path.expandvars(path_str)
        return os.path.normpath(os.path.abspath(expanded))

    def _find_steam_userdata_dir(self) -> str:
        """Tìm đường dẫn thư mục Steam/userdata trên máy người dùng."""
        candidates = [
            r"C:\Program Files (x86)\Steam\userdata",
            r"C:\Program Files\Steam\userdata",
            r"D:\Steam\userdata",
            r"E:\Steam\userdata",
        ]
        for c in candidates:
            if os.path.isdir(c):
                # Lấy subfolder account id đầu tiên có sẵn
                try:
                    subs = [s for s in os.listdir(c) if s.isdigit()]
                    if subs:
                        return os.path.join(c, subs[0])
                except Exception:
                    pass
                return c
        return ""

    def get_existing_save_directory(self, game_config: dict, game_dir: str = None) -> str:
        """Kiểm tra và trả về đường dẫn thư mục save game thực tế đang tồn tại trên máy."""
        cloud_cfg = game_config.get("cloud_sync", {})
        save_paths = cloud_cfg.get("save_paths", [])
        if not save_paths:
            # Gợi ý mặc định theo tên game
            title = game_config.get("title", game_config.get("id", ""))
            user_prof = os.environ.get("USERPROFILE", "")
            save_paths = [
                os.path.join(user_prof, "Documents", title),
                os.path.join(user_prof, "Saved Games", title),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), title),
            ]

        for p in save_paths:
            resolved = self.resolve_save_path(p, game_dir)
            if resolved and os.path.isdir(resolved):
                return resolved

        # Nếu không có đường dẫn nào tồn tại, trả về đường dẫn đầu tiên được phân giải làm mục tiêu
        if save_paths:
            return self.resolve_save_path(save_paths[0], game_dir)
        return ""

    def hash_save_directory(self, folder_path: str, exclude_patterns: list = None) -> tuple[str, float, int, int]:
        """
        Tính toán tổng hợp:
        - SHA-256 fingerprint của toàn bộ cây thư mục save.
        - Modified timestamp (mtime) mới nhất.
        - Tổng dung lượng byte.
        - Tổng số file.
        """
        if not folder_path or not os.path.isdir(folder_path):
            return "", 0.0, 0, 0

        excludes = set(exclude_patterns or ["*.bak", "*.tmp", "steam_autocloud.vdf", "*.log"])
        hasher = hashlib.sha256()
        latest_mtime = 0.0
        total_size = 0
        file_count = 0

        import fnmatch

        for root, dirs, files in os.walk(folder_path):
            # Lọc bỏ file loại trừ
            filtered_files = []
            for f in sorted(files):
                skip = False
                for pat in excludes:
                    if fnmatch.fnmatch(f, pat):
                        skip = True
                        break
                if not skip:
                    filtered_files.append(f)

            for f in filtered_files:
                full_path = os.path.join(root, f)
                try:
                    st = os.stat(full_path)
                    mtime = st.st_mtime
                    size = st.st_size
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                    total_size += size
                    file_count += 1

                    rel_path = os.path.relpath(full_path, folder_path).replace("\\", "/")
                    hasher.update(rel_path.encode("utf-8"))
                    hasher.update(str(size).encode("ascii"))

                    with open(full_path, "rb") as rf:
                        while chunk := rf.read(65536):
                            hasher.update(chunk)
                except (OSError, PermissionError):
                    continue

        return hasher.hexdigest(), latest_mtime, total_size, file_count

    def zip_save_directory(self, folder_path: str, dest_zip_path: str, exclude_patterns: list = None) -> bool:
        """Nén thư mục save thành tệp .zip an toàn."""
        import fnmatch
        excludes = set(exclude_patterns or ["*.bak", "*.tmp", "steam_autocloud.vdf"])
        os.makedirs(os.path.dirname(os.path.abspath(dest_zip_path)), exist_ok=True)
        tmp_zip = dest_zip_path + f".tmp_{secrets.token_hex(4)}"

        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for root, dirs, files in os.walk(folder_path):
                    for f in sorted(files):
                        skip = False
                        for pat in excludes:
                            if fnmatch.fnmatch(f, pat):
                                skip = True
                                break
                        if skip:
                            continue
                        full_path = os.path.join(root, f)
                        rel_path = os.path.relpath(full_path, folder_path)
                        zf.write(full_path, arcname=rel_path)
            if os.path.exists(dest_zip_path):
                os.remove(dest_zip_path)
            os.replace(tmp_zip, dest_zip_path)
            return True
        except Exception as e:
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                except Exception:
                    pass
            print(f"[CloudSyncManager] Nén zip save thất bại: {e}")
            return False

    def unzip_save_directory(self, zip_path: str, target_folder: str) -> bool:
        """Giải nén tệp .zip với bảo vệ Zip-Slip (chống Path Traversal)."""
        if not os.path.exists(zip_path):
            return False

        target_real = os.path.realpath(target_folder)
        os.makedirs(target_real, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                norm_name = os.path.normpath(member.filename)
                if norm_name.startswith("..") or os.path.isabs(norm_name):
                    raise RuntimeError(f"Cảnh báo bảo mật Zip Slip: '{member.filename}'")

                dest_file = os.path.realpath(os.path.join(target_real, norm_name))
                if not dest_file.startswith(target_real):
                    raise RuntimeError(f"Zip Slip detected outside target folder: '{dest_file}'")

                if member.is_dir():
                    os.makedirs(dest_file, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    with zf.open(member) as src, open(dest_file, "wb") as dst:
                        while chunk := src.read(65536):
                            dst.write(chunk)
        return True

    def create_local_backup(self, game_id: str, save_folder: str) -> str:
        """
        Tự động tạo bản sao lưu cục bộ trước khi ghi đè save mới từ Cloud.
        Duy trì tối đa 3 bản sao lưu gần nhất (xoay vòng an toàn).
        """
        if not os.path.isdir(save_folder):
            return ""

        game_backup_dir = os.path.join(self.backups_dir, game_id)
        os.makedirs(game_backup_dir, exist_ok=True)

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"save_backup_{now_str}.zip"
        backup_path = os.path.join(game_backup_dir, backup_filename)

        if self.zip_save_directory(save_folder, backup_path):
            # Xoay vòng giữ 3 bản mới nhất
            try:
                files = sorted(
                    [f for f in os.listdir(game_backup_dir) if f.startswith("save_backup_") and f.endswith(".zip")],
                    key=lambda x: os.path.getmtime(os.path.join(game_backup_dir, x)),
                    reverse=True
                )
                if len(files) > 3:
                    for old_file in files[3:]:
                        os.remove(os.path.join(game_backup_dir, old_file))
            except Exception as e:
                print(f"[CloudSyncManager] Xoay vòng backup lỗi: {e}")
            return backup_path
        return ""

    def list_local_backups(self, game_id: str) -> list:
        """Liệt kê danh sách các bản backup cục bộ của game."""
        game_backup_dir = os.path.join(self.backups_dir, game_id)
        if not os.path.isdir(game_backup_dir):
            return []
        res = []
        for f in sorted(os.listdir(game_backup_dir), reverse=True):
            if f.startswith("save_backup_") and f.endswith(".zip"):
                fp = os.path.join(game_backup_dir, f)
                try:
                    st = os.stat(fp)
                    res.append({
                        "filename": f,
                        "path": fp,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "formatted_time": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
                    })
                except Exception:
                    pass
        return res

    def restore_local_backup(self, game_id: str, backup_filename: str, game_config: dict, game_dir: str = None) -> dict:
        """Khôi phục lại save từ một bản backup cục bộ đã lưu."""
        backup_path = os.path.join(self.backups_dir, game_id, backup_filename)
        if not os.path.isfile(backup_path):
            return {"success": False, "error": "Tệp backup không tồn tại"}

        target_dir = self.get_existing_save_directory(game_config, game_dir)
        if not target_dir:
            return {"success": False, "error": "Không xác định được thư mục save game"}

        try:
            self.unzip_save_directory(backup_path, target_dir)
            return {"success": True, "message": f"Đã khôi phục thành công từ '{backup_filename}'"}
        except Exception as e:
            return {"success": False, "error": f"Lỗi khôi phục: {e}"}

    # ==========================================
    # CƠ CHẾ ĐỒNG BỘ 3 CHIỀU (3-WAY CLOUD SYNC)
    # ==========================================

    def check_game_sync_status(self, game_config: dict, game_dir: str = None) -> dict:
        """
        Kiểm tra trạng thái đồng bộ Save Game 3 Chiều giữa:
        - Local Disk
        - Google Drive Cloud
        - Lần đồng bộ trước đó (user_profile.json)
        """
        game_id = game_config["id"]
        save_folder = self.get_existing_save_directory(game_config, game_dir)
        local_exists = bool(save_folder and os.path.isdir(save_folder))

        local_hash, local_mtime, local_size, local_files = self.hash_save_directory(
            save_folder, game_config.get("cloud_sync", {}).get("exclude_patterns", [])
        ) if local_exists else ("", 0.0, 0, 0)

        profile = self._load_user_profile_data()
        game_profile = profile.get("games", {}).get(game_id, {})
        last_sync_hash = game_profile.get("save_hash", "")
        last_sync_mtime = game_profile.get("save_mtime", 0.0)

        cloud_connected = self.is_connected()
        cloud_info = {}
        cloud_file = None

        if cloud_connected:
            try:
                root_id, saves_id = self.client.get_cloud_root_folders()
                cloud_files = self.client.list_files_in_folder(saves_id)
                cloud_file_name = f"{game_id}_save.zip"
                cloud_file = cloud_files.get(cloud_file_name)
                if cloud_file:
                    app_props = cloud_file.get("appProperties") or {}
                    cloud_info = {
                        "id": cloud_file["id"],
                        "name": cloud_file["name"],
                        "size": int(cloud_file.get("size", 0)),
                        "modifiedTime": cloud_file.get("modifiedTime", ""),
                        "sha256": app_props.get("sha256", ""),
                        "mtime": float(app_props.get("mtime", 0.0)),
                        "file_count": int(app_props.get("file_count", 0))
                    }
            except Exception as e:
                print(f"[CloudSyncManager] Không thể lấy thông tin Cloud: {e}")

        # Đánh giá trạng thái
        status = "NO_SAVE"
        if not local_exists and not cloud_file:
            status = "NO_SAVE"
        elif not local_exists and cloud_file:
            status = "DOWNLOAD_NEEDED"
        elif local_exists and not cloud_file:
            status = "UPLOAD_NEEDED"
        elif local_exists and cloud_file:
            cloud_hash = cloud_info.get("sha256", "")
            if local_hash == cloud_hash:
                status = "IN_SYNC"
            else:
                # Cả hai bên đều tồn tại nhưng hash khác nhau
                if local_hash == last_sync_hash and cloud_hash != last_sync_hash:
                    status = "DOWNLOAD_NEEDED"
                elif local_hash != last_sync_hash and cloud_hash == last_sync_hash:
                    status = "UPLOAD_NEEDED"
                else:
                    # Cả 2 bên đều thay đổi khác với lần sync trước -> XUNG ĐỘT!
                    status = "CONFLICT"

        return {
            "game_id": game_id,
            "connected": cloud_connected,
            "status": status,
            "save_folder": save_folder,
            "local": {
                "exists": local_exists,
                "sha256": local_hash,
                "mtime": local_mtime,
                "size": local_size,
                "file_count": local_files,
                "formatted_mtime": datetime.fromtimestamp(local_mtime).strftime("%d/%m/%Y %H:%M:%S") if local_mtime else ""
            },
            "cloud": cloud_info,
            "last_sync": {
                "hash": last_sync_hash,
                "mtime": last_sync_mtime,
                "formatted_mtime": datetime.fromtimestamp(last_sync_mtime).strftime("%d/%m/%Y %H:%M:%S") if last_sync_mtime else ""
            }
        }

    def sync_game_save(self, game_config: dict, game_dir: str = None, force_action: str = None) -> dict:
        """
        Thực hiện đồng bộ Save Game lên Google Drive hoặc tải về:
        - force_action: None (tự động theo 3-way), "upload" (giữ bản máy), "download" (giữ bản cloud)
        """
        if not self.is_connected():
            return {"success": False, "error": "Chưa kết nối Google Drive"}

        game_id = game_config["id"]
        check = self.check_game_sync_status(game_config, game_dir)
        status = check["status"]
        action = force_action or status

        save_folder = check["save_folder"]

        if action == "IN_SYNC":
            return {"success": True, "action": "noop", "message": "Save game đã đồng bộ khớp 100%!"}

        if action in ["UPLOAD_NEEDED", "upload"]:
            if not check["local"]["exists"]:
                return {"success": False, "error": "Không tìm thấy thư mục save cục bộ để tải lên"}

            # Nén save ra tệp zip tạm
            zip_tmp = os.path.join(self.appdata_dir, f"temp_{game_id}_upload.zip")
            try:
                ok = self.zip_save_directory(
                    save_folder, zip_tmp, game_config.get("cloud_sync", {}).get("exclude_patterns", [])
                )
                if not ok:
                    return {"success": False, "error": "Nén save thất bại"}

                root_id, saves_id = self.client.get_cloud_root_folders()
                cloud_file_id = check["cloud"].get("id")

                app_props = {
                    "sha256": check["local"]["sha256"],
                    "mtime": str(check["local"]["mtime"]),
                    "game_id": game_id,
                    "file_count": str(check["local"]["file_count"])
                }

                upload_res = self.client.upload_file_multipart(
                    name=f"{game_id}_save.zip",
                    file_path_or_bytes=zip_tmp,
                    parent_id=saves_id,
                    app_properties=app_props,
                    existing_file_id=cloud_file_id
                )

                # Cập nhật user_profile.json
                prof = self._load_user_profile_data()
                gp = prof.setdefault("games", {}).setdefault(game_id, {})
                gp["save_hash"] = check["local"]["sha256"]
                gp["save_mtime"] = check["local"]["mtime"]
                gp["last_sync_ts"] = int(time.time())
                self._save_user_profile_data(prof)

                # Đồng bộ profile_meta.json lên Drive
                self._sync_profile_meta_to_cloud()

                return {
                    "success": True,
                    "action": "uploaded",
                    "message": "Đã tải bản save cục bộ lên Google Drive thành công!"
                }
            finally:
                if os.path.exists(zip_tmp):
                    try:
                        os.remove(zip_tmp)
                    except Exception:
                        pass

        elif action in ["DOWNLOAD_NEEDED", "download"]:
            cloud_file_id = check["cloud"].get("id")
            if not cloud_file_id:
                return {"success": False, "error": "Không tìm thấy bản save trên Google Drive"}

            # Bước an toàn: Tạo bản sao lưu máy hiện tại trước khi đè
            if check["local"]["exists"]:
                backup_path = self.create_local_backup(game_id, save_folder)
                if backup_path:
                    print(f"[CloudSyncManager] Đã sao lưu bản máy hiện tại vào '{backup_path}' trước khi tải đè")

            # Tải tệp zip từ Cloud về
            zip_tmp = os.path.join(self.appdata_dir, f"temp_{game_id}_download.zip")
            try:
                self.client.download_file(cloud_file_id, zip_tmp)
                self.unzip_save_directory(zip_tmp, save_folder)

                # Cập nhật hash mới sau khi bung
                new_hash, new_mtime, _, _ = self.hash_save_directory(
                    save_folder, game_config.get("cloud_sync", {}).get("exclude_patterns", [])
                )
                prof = self._load_user_profile_data()
                gp = prof.setdefault("games", {}).setdefault(game_id, {})
                gp["save_hash"] = new_hash
                gp["save_mtime"] = new_mtime
                gp["last_sync_ts"] = int(time.time())
                self._save_user_profile_data(prof)

                return {
                    "success": True,
                    "action": "downloaded",
                    "message": "Đã tải bản save từ Google Drive và bung vào máy thành công!"
                }
            finally:
                if os.path.exists(zip_tmp):
                    try:
                        os.remove(zip_tmp)
                    except Exception:
                        pass

        elif action == "CONFLICT":
            return {
                "success": False,
                "action": "conflict",
                "message": "Phát hiện xung đột: Bản save trên máy và trên Cloud đều có thay đổi mới!",
                "conflict_data": check
            }

        return {"success": False, "error": f"Hành động không xác định: {action}"}

    def _sync_profile_meta_to_cloud(self):
        """Đồng bộ profile_meta.json (tổng hợp playtime và achievements) lên thư mục VietModHub_Cloud."""
        if not self.is_connected():
            return
        try:
            root_id, _ = self.client.get_cloud_root_folders()
            cloud_files = self.client.list_files_in_folder(root_id)
            meta_file = cloud_files.get("profile_meta.json")
            existing_id = meta_file["id"] if meta_file else None

            local_profile = self._load_user_profile_data()
            meta_bytes = json.dumps(local_profile, ensure_ascii=False, indent=2).encode("utf-8")

            self.client.upload_file_multipart(
                name="profile_meta.json",
                file_path_or_bytes=meta_bytes,
                parent_id=root_id,
                existing_file_id=existing_id
            )
        except Exception as e:
            print(f"[CloudSyncManager] Đồng bộ profile_meta lên Cloud thất bại: {e}")

    def post_session_sync(self, game_id: str, game_dir: str, game_config: dict):
        """Hàm tự động kích hoạt sau khi tắt game (Post-Session Auto Upload)."""
        if not self.is_connected():
            return
        if not game_config or not game_config.get("cloud_sync"):
            return

        def _worker():
            try:
                time.sleep(1.5)  # Chờ tiến trình game đóng hoàn toàn việc ghi file save
                res = self.sync_game_save(game_config, game_dir, force_action=None)
                print(f"[CloudSyncManager] Post-session auto sync cho '{game_id}': {res.get('action', res.get('message'))}")
            except Exception as e:
                print(f"[CloudSyncManager] Post-session sync error cho '{game_id}': {e}")

        threading.Thread(target=_worker, daemon=True).start()
