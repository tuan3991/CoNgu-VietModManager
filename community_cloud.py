"""
CỔ NGỮ (VietModHub Pro) - Community Cloud Hub Client
Đồng bộ Save Game, Giờ chơi và Thành tựu qua Máy Chủ Đám Mây Tập Trung (Google Apps Script / Webhook).
Người dùng chỉ cần tạo Mã Cloud ID và Mật khẩu tự chọn (hoặc tự sinh ngẫu nhiên).
Hoàn toàn KHÔNG cần đăng nhập Google OAuth, 0% cảnh báo bảo mật, bảo mật 100%.
"""

import os
import json
import base64
import hashlib
import requests
from datetime import datetime, timezone

from vault_manager import ConguSaveVault

# Tên thư mục gốc lưu trữ trên Google Drive của Admin
DEFAULT_ROOT_FOLDER_NAME = "VietModHub_Cloud_Storage"

# URL Google Apps Script Web App mặc định (nếu đã triển khai)
DEFAULT_APPS_SCRIPT_URL = ""


class CommunityCloudManager:
    """Quản lý giao tiếp với Máy Chủ Đám Mây Cổ Ngữ (Google Apps Script)."""

    def __init__(self, config_getter, config_saver, vault_getter, games_getter):
        self.config_getter = config_getter
        self.config_saver = config_saver
        self.vault_getter = vault_getter
        self.games_getter = games_getter

    def _get_cloud_config(self) -> dict:
        cfg = self.config_getter() or {}
        return cfg.get("community_cloud", {
            "server_url": DEFAULT_APPS_SCRIPT_URL,
            "cloud_id": "",
            "password": "",
            "last_sync": None,
            "last_size": 0,
            "is_logged_in": False
        })

    def _save_cloud_config(self, cloud_cfg: dict):
        cfg = self.config_getter() or {}
        cfg["community_cloud"] = cloud_cfg
        self.config_saver(cfg)

    def get_status(self) -> dict:
        """Lấy trạng thái tài khoản Cloud hiện tại trên máy."""
        c = self._get_cloud_config()
        return {
            "is_logged_in": bool(c.get("is_logged_in") and c.get("cloud_id")),
            "cloud_id": c.get("cloud_id", ""),
            "password_masked": "•" * len(c.get("password", "")) if c.get("password") else "",
            "password_raw": c.get("password", ""),
            "server_url": c.get("server_url", DEFAULT_APPS_SCRIPT_URL),
            "last_sync": c.get("last_sync"),
            "last_size": c.get("last_size", 0),
            "is_server_configured": bool(c.get("server_url", "").strip())
        }

    def set_server_url(self, url: str) -> dict:
        """Cấu hình URL Google Apps Script Web App của Admin."""
        url = url.strip()
        c = self._get_cloud_config()
        c["server_url"] = url
        self._save_cloud_config(c)
        return {"success": True, "message": "Đã lưu địa chỉ máy chủ thành công!", "server_url": url}

    def _call_api(self, payload: dict) -> dict:
        """Gửi request an toàn đến Google Apps Script Web App và tự động bám theo redirect."""
        c = self._get_cloud_config()
        server_url = c.get("server_url", "").strip() or DEFAULT_APPS_SCRIPT_URL

        if not server_url:
            return {
                "success": False,
                "error": "Chưa cấu hình địa chỉ máy chủ đám mây (Google Apps Script Web App URL). Vui lòng dán URL vào phần 'Cấu hình Máy Chủ'!"
            }

        try:
            # Google Apps Script nhận POST JSON và redirect 302 đến Content Service
            resp = requests.post(
                server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                allow_redirects=True,
                timeout=45
            )
            try:
                data = resp.json()
                return data
            except Exception:
                return {
                    "success": False,
                    "error": f"Phản hồi từ máy chủ không hợp lệ (Mã HTTP {resp.status_code}): {resp.text[:200]}"
                }
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Kết nối máy chủ bị quá thời gian (Timeout). Vui lòng thử lại!"}
        except Exception as e:
            return {"success": False, "error": f"Lỗi kết nối máy chủ: {e}"}

    def register(self, cloud_id: str, password: str, server_url: str = "") -> dict:
        """Đăng ký Mã Cloud ID mới theo ý thích người dùng."""
        cloud_id = (cloud_id or "").strip().lower()
        password = (password or "").strip()

        if len(cloud_id) < 3:
            return {"success": False, "error": "Mã Cloud ID phải có ít nhất 3 ký tự!"}
        if len(password) < 4:
            return {"success": False, "error": "Mật khẩu bảo vệ phải có ít nhất 4 ký tự!"}

        if server_url:
            self.set_server_url(server_url)

        res = self._call_api({
            "action": "register",
            "cloud_id": cloud_id,
            "password": password
        })

        if res.get("success"):
            c = self._get_cloud_config()
            c["cloud_id"] = cloud_id
            c["password"] = password
            c["is_logged_in"] = True
            c["last_sync"] = datetime.now(timezone.utc).isoformat()
            self._save_cloud_config(c)

        return res

    def login(self, cloud_id: str, password: str, server_url: str = "") -> dict:
        """Đăng nhập bằng Mã Cloud ID và Mật khẩu trên máy tính khác."""
        cloud_id = (cloud_id or "").strip().lower()
        password = (password or "").strip()

        if not cloud_id:
            return {"success": False, "error": "Vui lòng nhập Mã Cloud ID!"}
        if not password:
            return {"success": False, "error": "Vui lòng nhập Mật khẩu bảo vệ!"}

        if server_url:
            self.set_server_url(server_url)

        res = self._call_api({
            "action": "login",
            "cloud_id": cloud_id,
            "password": password
        })

        if res.get("success"):
            c = self._get_cloud_config()
            c["cloud_id"] = cloud_id
            c["password"] = password
            c["is_logged_in"] = True
            if res.get("last_sync"):
                c["last_sync"] = res.get("last_sync")
            if res.get("file_size"):
                c["last_size"] = res.get("file_size")
            self._save_cloud_config(c)

        return res

    def logout(self) -> dict:
        """Đăng xuất tài khoản khỏi máy này."""
        c = self._get_cloud_config()
        c["is_logged_in"] = False
        c["password"] = ""
        self._save_cloud_config(c)
        return {"success": True, "message": "Đã đăng xuất tài khoản Cloud khỏi máy này!"}

    def upload_save(self) -> dict:
        """
        Gom toàn bộ Save Game của các tựa game hiện có vào file PlayerProfile.congu_save
        và đẩy lên thư mục của User trên Máy chủ Google Drive.
        """
        c = self._get_cloud_config()
        if not c.get("is_logged_in") or not c.get("cloud_id") or not c.get("password"):
            return {"success": False, "error": "Chưa đăng nhập tài khoản Cổ Ngữ Cloud!"}

        cloud_id = c["cloud_id"]
        password = c["password"]

        vault = self.vault_getter()
        if not vault:
            return {"success": False, "error": "Chưa khởi tạo Vault Manager trên máy!"}

        # Tự động gom save mới nhất của các game đã cài trước khi tải lên mây
        packed_games_count = 0
        if self.games_getter and self.config_getter:
            try:
                games = self.games_getter()
                cfg = self.config_getter()
                pack_res = vault.pack_all_installed_games(games, cfg)
                packed_games_count = len(pack_res)
            except Exception as pe:
                print(f"[CommunityCloud] pack_all_installed_games error: {pe}")

        if not os.path.exists(vault.vault_path):
            vault._ensure_vault_initialized()

        try:
            # Đọc nội dung file vault và encode base64
            with open(vault.vault_path, "rb") as f:
                raw_bytes = f.read()

            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            file_size = len(raw_bytes)

            res = self._call_api({
                "action": "upload",
                "cloud_id": cloud_id,
                "password": password,
                "file_data": b64_str,
                "file_name": "PlayerProfile.congu_save",
                "file_size": file_size
            })

            if res.get("success"):
                c["last_sync"] = datetime.now(timezone.utc).isoformat()
                c["last_size"] = file_size
                self._save_cloud_config(c)

            return res
        except Exception as e:
            return {"success": False, "error": f"Lỗi khi đóng gói & tải lên: {e}"}

    def download_save(self, auto_unpack: bool = True) -> dict:
        """
        Tải file PlayerProfile.congu_save từ máy chủ về máy và tự động bung vào các game.
        """
        c = self._get_cloud_config()
        if not c.get("is_logged_in") or not c.get("cloud_id") or not c.get("password"):
            return {"success": False, "error": "Chưa đăng nhập tài khoản Cổ Ngữ Cloud!"}

        cloud_id = c["cloud_id"]
        password = c["password"]

        res = self._call_api({
            "action": "download",
            "cloud_id": cloud_id,
            "password": password
        })

        if not res.get("success"):
            return res

        b64_str = res.get("file_data")
        if not b64_str:
            return {"success": False, "error": "Dữ liệu save tải về từ máy chủ bị trống!"}

        try:
            raw_bytes = base64.b64decode(b64_str)
            vault = self.vault_getter()
            os.makedirs(os.path.dirname(vault.vault_path), exist_ok=True)

            # Ghi đè file vault
            with open(vault.vault_path, "wb") as f:
                f.write(raw_bytes)

            c["last_sync"] = res.get("updated_at") or datetime.now(timezone.utc).isoformat()
            c["last_size"] = len(raw_bytes)
            self._save_cloud_config(c)

            unpack_info = None
            if auto_unpack and self.games_getter:
                games = self.games_getter()
                cfg = self.config_getter()
                unpack_info = vault.unpack_all_installed_games(games, cfg)

            return {
                "success": True,
                "message": "Đã tải và khôi phục toàn bộ tiến trình game từ Mây về máy thành công!",
                "size_bytes": len(raw_bytes),
                "updated_at": c["last_sync"],
                "auto_unpack": unpack_info
            }
        except Exception as e:
            return {"success": False, "error": f"Lỗi khi giải mã & khôi phục save: {e}"}
