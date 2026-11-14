# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Hệ Thống Quản Lý Đa Tài Khoản & Kích Dữ Liệu Phiên
Hỗ trợ chuyển đổi linh hoạt giữa các tài khoản Offline và Online.
Khi đổi tài khoản, hệ thống tự động:
1. Sao lưu cách ly dữ liệu tài khoản hiện tại vào sandbox riêng (nếu cần).
2. KÍCH HẾT toàn bộ dữ liệu phiên cũ ra khỏi ứng dụng:
   - Đăng xuất tài khoản Đám mây (Community Cloud & Google Drive), thu hồi token.
   - Xóa trắng danh sách game cài đặt, game ngoài (custom_games.json = []).
   - Reset giờ chơi (playtime.json = {}), thành tựu (achievements_progress.json = {}).
   - Xóa bỏ file Hồ sơ Save (.congu_save) và các bản backup đang active.
   - Reset các đường dẫn game và cài đặt cá nhân, để lại app ở trạng thái TRỐNG hoàn toàn!
3. Nếu chuyển sang tài khoản đã có hoặc tài khoản Online: nạp đúng dữ liệu của tài khoản đó.
"""

import os
import sys
import json
import time
import shutil
import secrets
from typing import Dict, Any, List, Optional

from core.config_manager import (
    APPDATA_DIR,
    load_user_config,
    save_user_config,
    load_custom_games,
    save_custom_games,
)


class AccountManager:
    """Quản lý các tài khoản Offline / Online và cách ly dữ liệu."""

    def __init__(
        self,
        appdata_dir: str = "",
        config_getter=None,
        config_saver=None,
        playtime_mgr=None,
        achievement_mgr=None,
        community_cloud_mgr=None,
        cloud_sync_mgr=None,
    ):
        self.appdata_dir = appdata_dir or APPDATA_DIR
        self.config_getter = config_getter or load_user_config
        self.config_saver = config_saver or save_user_config
        self.playtime_mgr = playtime_mgr
        self.achievement_mgr = achievement_mgr
        self.community_cloud_mgr = community_cloud_mgr
        self.cloud_sync_mgr = cloud_sync_mgr

        self.profiles_root = os.path.join(self.appdata_dir, "account_profiles")
        self.index_file = os.path.join(self.appdata_dir, "accounts_index.json")
        self.custom_games_file = os.path.join(self.appdata_dir, "custom_games.json")
        self.playtime_file = os.path.join(self.appdata_dir, "playtime.json")
        self.achievements_file = os.path.join(self.appdata_dir, "achievements_progress.json")
        self.vault_file = os.path.join(self.appdata_dir, "PlayerProfile.congu_save")
        self.user_data_file = os.path.join(self.appdata_dir, "user_data.json")
        self.community_requests_file = os.path.join(self.appdata_dir, "community_requests.json")
        self.gdrive_token_file = os.path.join(self.appdata_dir, "gdrive_token.enc")
        self.save_backups_dir = os.path.join(self.appdata_dir, "save_backups")

        os.makedirs(self.profiles_root, exist_ok=True)
        self._ensure_initial_account()

    def _load_index(self) -> dict:
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "accounts" in data:
                        return data
            except Exception as e:
                print(f"[AccountManager] Lỗi đọc accounts_index.json: {e}")

        # Khởi tạo mặc định
        cfg = self.config_getter() or {}
        p_cfg = cfg.get("profile", {})
        cc_cfg = cfg.get("community_cloud", {})
        is_cc_online = bool(cc_cfg.get("is_logged_in") and cc_cfg.get("cloud_id"))

        init_acc_id = f"acc_{'online' if is_cc_online else 'offline'}_default"
        init_name = cc_cfg.get("cloud_id") if is_cc_online else p_cfg.get("player_name", "Game Thủ")

        default_data = {
            "active_account_id": init_acc_id,
            "accounts": [
                {
                    "id": init_acc_id,
                    "name": init_name or "Game Thủ",
                    "type": "online" if is_cc_online else "offline",
                    "cloud_id": cc_cfg.get("cloud_id", "") if is_cc_online else "",
                    "avatar_url": p_cfg.get("avatar_url", "preset:space_astro"),
                    "cover_url": p_cfg.get("cover_url", "preset:synthwave"),
                    "bio": p_cfg.get("bio", ""),
                    "created_at": int(time.time()),
                    "last_active": int(time.time()),
                }
            ],
        }
        self._save_index(default_data)
        return default_data

    def _save_index(self, data: dict):
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[AccountManager] Lỗi lưu accounts_index.json: {e}")

    def _ensure_initial_account(self):
        """Đảm bảo tài khoản ban đầu được đăng ký và đồng bộ tên."""
        idx = self._load_index()
        # Cập nhật thời gian hoạt động của tài khoản hiện tại
        active_id = idx.get("active_account_id")
        for acc in idx.get("accounts", []):
            if acc["id"] == active_id:
                acc["last_active"] = int(time.time())
                break
        self._save_index(idx)

    def save_account_snapshot(self, account_id: str) -> bool:
        """Sao lưu cách ly toàn bộ dữ liệu của một tài khoản vào thư mục riêng."""
        if not account_id:
            return False
        acc_dir = os.path.join(self.profiles_root, account_id)
        os.makedirs(acc_dir, exist_ok=True)

        try:
            # 1. Lưu các file JSON dữ liệu
            files_to_copy = [
                (self.custom_games_file, "custom_games.json"),
                (self.playtime_file, "playtime.json"),
                (self.achievements_file, "achievements_progress.json"),
                (self.user_data_file, "user_data.json"),
                (self.community_requests_file, "community_requests.json"),
            ]
            for src, filename in files_to_copy:
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(acc_dir, filename))

            # 2. Lưu file Save Vault
            if os.path.exists(self.vault_file):
                shutil.copy2(self.vault_file, os.path.join(acc_dir, "PlayerProfile.congu_save"))

            # 3. Lưu Save Backups
            if os.path.isdir(self.save_backups_dir):
                dst_backups = os.path.join(acc_dir, "save_backups")
                shutil.copytree(self.save_backups_dir, dst_backups, dirs_exist_ok=True)

            # 4. Trích xuất các cài đặt thuộc về cá nhân tài khoản trong user_config.json
            cfg = self.config_getter() or {}
            profile_snapshot = {
                "profile": cfg.get("profile", {}),
                "community_cloud": cfg.get("community_cloud", {}),
                "cloud_save": cfg.get("cloud_save", {}),
                "favorite_games": cfg.get("favorite_games", []),
                "game_paths": {k: v for k, v in cfg.items() if k.endswith("_path")},
                "scanner_custom_paths": cfg.get("scanner", {}).get("custom_library_paths", []),
            }
            with open(os.path.join(acc_dir, "user_config_profile.json"), "w", encoding="utf-8") as f:
                json.dump(profile_snapshot, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"[AccountManager] Lỗi sao lưu snapshot tài khoản '{account_id}': {e}")
            return False

    def purge_active_session_data(self, is_new_blank: bool = True):
        """
        KÍCH HẾT TOÀN BỘ DỮ LIỆU CŨ RA KHỎI ỨNG DỤNG.
        Làm rỗng app hoàn toàn:
        - Đăng xuất Community Cloud & Google Drive (xóa token).
        - Xóa sạch custom games, playtime, achievements, save vault.
        - Xóa toàn bộ đường dẫn game liên kết, favorites.
        - Reset in-memory trackers về 0.
        """
        # 1. Đăng xuất các dịch vụ online
        if self.community_cloud_mgr:
            try:
                self.community_cloud_mgr.logout()
            except Exception as e:
                print(f"[AccountManager] Lỗi logout community cloud: {e}")

        if self.cloud_sync_mgr:
            try:
                self.cloud_sync_mgr.logout()
            except Exception as e:
                print(f"[AccountManager] Lỗi logout gdrive: {e}")

        if os.path.exists(self.gdrive_token_file):
            try:
                os.remove(self.gdrive_token_file)
            except Exception:
                pass

        # 2. Xóa dữ liệu các file active trên đĩa
        try:
            with open(self.custom_games_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        try:
            with open(self.playtime_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        try:
            with open(self.achievements_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        try:
            with open(self.community_requests_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        try:
            if os.path.exists(self.user_data_file):
                with open(self.user_data_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "ratings": {},
                        "comments": {},
                        "bug_reports": [],
                        "game_requests": [],
                        "voted_requests": [],
                    }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # Xóa file vault hiện tại và file tmp
        try:
            if os.path.exists(self.vault_file):
                os.remove(self.vault_file)
            for fname in os.listdir(self.appdata_dir):
                if fname.startswith("PlayerProfile.") and fname.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(self.appdata_dir, fname))
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. Kích sạch các thiết lập game cá nhân trong user_config.json
        try:
            cfg = self.config_getter() or {}
            keys_to_delete = [k for k in cfg.keys() if k.endswith("_path")]
            for k in keys_to_delete:
                del cfg[k]

            cfg["favorite_games"] = []

            if "scanner" in cfg and isinstance(cfg["scanner"], dict):
                cfg["scanner"]["custom_library_paths"] = []
                if is_new_blank:
                    # Để lại app trống tinh khôi: không tự động quét game cũ
                    cfg["scanner"]["auto_scan_on_startup"] = False

            # Reset thông tin hồ sơ về mặc định
            cfg["profile"] = {
                "player_name": "Game Thủ Mới",
                "avatar_url": "preset:space_astro",
                "cover_url": "preset:synthwave",
                "bio": ""
            }

            cfg["community_cloud"] = {
                "server_url": "https://script.google.com/macros/s/AKfycbwm4nz-G5bBSEW02P5y8ZiFW7ngSOiLvYE79UtWO7BVxofxS1PpGZESH6L5vmVs2soA/exec",
                "cloud_id": "",
                "password": "",
                "last_sync": None,
                "last_size": 0,
                "is_logged_in": False
            }

            cfg["cloud_save"] = {
                "cloud_id": "",
                "password": "",
                "auto_sync_on_exit": True,
                "track_playtime": True,
                "offline_achievements_scan": True
            }

            self.config_saver(cfg)
        except Exception as e:
            print(f"[AccountManager] Lỗi reset user_config: {e}")

        # 4. Kích sạch các đối tượng trong RAM
        if self.playtime_mgr:
            try:
                self.playtime_mgr.db = {}
                self.playtime_mgr.active_sessions.clear()
            except Exception:
                pass

        if self.achievement_mgr:
            try:
                self.achievement_mgr.progress = {}
            except Exception:
                pass

    def restore_account_snapshot(self, account_id: str) -> bool:
        """Khôi phục dữ liệu từ sandbox của một tài khoản vào app."""
        acc_dir = os.path.join(self.profiles_root, account_id)
        if not os.path.isdir(acc_dir):
            return False

        try:
            # 1. Khôi phục các file JSON
            files_to_restore = [
                ("custom_games.json", self.custom_games_file),
                ("playtime.json", self.playtime_file),
                ("achievements_progress.json", self.achievements_file),
                ("user_data.json", self.user_data_file),
                ("community_requests.json", self.community_requests_file),
                ("PlayerProfile.congu_save", self.vault_file),
            ]
            for filename, dst in files_to_restore:
                src = os.path.join(acc_dir, filename)
                if os.path.exists(src):
                    shutil.copy2(src, dst)

            # 2. Khôi phục Save Backups nếu có
            src_backups = os.path.join(acc_dir, "save_backups")
            if os.path.isdir(src_backups):
                shutil.copytree(src_backups, self.save_backups_dir, dirs_exist_ok=True)

            # 3. Khôi phục cấu hình riêng của tài khoản vào user_config.json
            profile_snap_file = os.path.join(acc_dir, "user_config_profile.json")
            if os.path.exists(profile_snap_file):
                with open(profile_snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                cfg = self.config_getter() or {}

                if "profile" in snap:
                    cfg["profile"] = snap["profile"]
                if "community_cloud" in snap:
                    cfg["community_cloud"] = snap["community_cloud"]
                if "cloud_save" in snap:
                    cfg["cloud_save"] = snap["cloud_save"]
                if "favorite_games" in snap:
                    cfg["favorite_games"] = snap["favorite_games"]
                if "game_paths" in snap:
                    for k, v in snap["game_paths"].items():
                        cfg[k] = v
                if "scanner_custom_paths" in snap:
                    if "scanner" not in cfg:
                        cfg["scanner"] = {}
                    cfg["scanner"]["custom_library_paths"] = snap["scanner_custom_paths"]

                self.config_saver(cfg)

            # 4. Tải lại in-memory trackers
            if self.playtime_mgr and hasattr(self.playtime_mgr, "_load_db"):
                try:
                    self.playtime_mgr.db = self.playtime_mgr._load_db()
                    self.playtime_mgr.active_sessions.clear()
                except Exception:
                    pass

            if self.achievement_mgr and hasattr(self.achievement_mgr, "_load_progress"):
                try:
                    self.achievement_mgr.progress = self.achievement_mgr._load_progress()
                except Exception:
                    pass

            return True
        except Exception as e:
            print(f"[AccountManager] Lỗi khôi phục snapshot '{account_id}': {e}")
            return False

    def create_blank_account(self, name: str = "Tài Khoản Mới", account_type: str = "offline") -> dict:
        """
        Tạo tài khoản mới và KÍCH HẾT DỮ LIỆU CŨ RA, để lại app hoàn toàn trống.
        """
        name = name.strip() or ("Tài Khoản Mới" if account_type == "offline" else "Online User")
        idx = self._load_index()
        curr_active = idx.get("active_account_id")

        # 1. Lưu snapshot tài khoản hiện tại trước khi kích
        if curr_active:
            self.save_account_snapshot(curr_active)

        # 2. KÍCH HẾT DỮ LIỆU CŨ RA KHỎI APP
        self.purge_active_session_data(is_new_blank=True)

        # 3. Sinh ID tài khoản mới
        new_id = f"acc_{account_type}_{int(time.time())}_{secrets.token_hex(2)}"

        # 4. Cập nhật hồ sơ tài khoản mới
        cfg = self.config_getter() or {}
        cfg["profile"]["player_name"] = name
        self.config_saver(cfg)

        new_acc = {
            "id": new_id,
            "name": name,
            "type": account_type,
            "cloud_id": "",
            "avatar_url": "preset:space_astro",
            "cover_url": "preset:synthwave",
            "bio": "",
            "created_at": int(time.time()),
            "last_active": int(time.time()),
        }

        idx["accounts"].append(new_acc)
        idx["active_account_id"] = new_id
        self._save_index(idx)

        # Lưu snapshot rỗng cho tài khoản mới
        self.save_account_snapshot(new_id)

        return {
            "success": True,
            "message": f"Đã kích hết dữ liệu cũ và khởi tạo tài khoản '{name}' thành công! Ứng dụng đang ở trạng thái trống.",
            "active_account": new_acc,
            "accounts": idx["accounts"],
        }

    def switch_to_account(self, target_account_id: str) -> dict:
        """
        Chuyển sang một tài khoản khác trong danh sách:
        - Tự động kích hết dữ liệu của tài khoản hiện tại ra.
        - Khôi phục dữ liệu riêng của tài khoản đích.
        """
        idx = self._load_index()
        curr_active = idx.get("active_account_id")

        if curr_active == target_account_id:
            return {"success": True, "message": "Bạn đang ở trong tài khoản này rồi!", "active_account_id": target_account_id}

        target_acc = next((a for a in idx["accounts"] if a["id"] == target_account_id), None)
        if not target_acc:
            return {"success": False, "error": f"Không tìm thấy tài khoản có mã '{target_account_id}'"}

        # 1. Lưu snapshot tài khoản hiện tại
        if curr_active:
            self.save_account_snapshot(curr_active)

        # 2. KÍCH HẾT DỮ LIỆU CŨ RA
        self.purge_active_session_data(is_new_blank=False)

        # 3. Khôi phục dữ liệu tài khoản đích
        restored = self.restore_account_snapshot(target_account_id)

        # 4. Đặt làm active account
        idx["active_account_id"] = target_account_id
        target_acc["last_active"] = int(time.time())
        self._save_index(idx)

        return {
            "success": True,
            "message": f"Đã chuyển sang tài khoản '{target_acc['name']}' ({target_acc['type'].upper()})! Dữ liệu cũ đã được cách ly an toàn.",
            "active_account": target_acc,
            "accounts": idx["accounts"],
            "restored_snapshot": restored,
        }

    def switch_to_online_account(self, cloud_id: str, password: str, server_url: str = "") -> dict:
        """
        Đổi sang tài khoản Online:
        1. Kích hết dữ liệu cũ ra để lại app trống.
        2. Đăng nhập vào Máy Chủ Đám Mây Cổ Ngữ với Cloud ID & Password.
        3. Tự động tải save game và đồng bộ hồ sơ đám mây về app.
        """
        cloud_id = cloud_id.strip()
        if not cloud_id:
            return {"success": False, "error": "Vui lòng nhập Mã Cloud ID!"}

        if not self.community_cloud_mgr:
            return {"success": False, "error": "Module Community Cloud chưa sẵn sàng!"}

        idx = self._load_index()
        curr_active = idx.get("active_account_id")

        # 1. Lưu snapshot tài khoản hiện tại
        if curr_active:
            self.save_account_snapshot(curr_active)

        # 2. KÍCH HẾT DỮ LIỆU CŨ RA KHỎI APP
        self.purge_active_session_data(is_new_blank=True)

        # 3. Cấu hình máy chủ nếu có
        if server_url and hasattr(self.community_cloud_mgr, "set_server_url"):
            self.community_cloud_mgr.set_server_url(server_url)

        # 4. Thực hiện đăng nhập Community Cloud
        login_res = self.community_cloud_mgr.login(cloud_id, password)
        if not login_res.get("success"):
            # Nếu đăng nhập thất bại, tạo một tài khoản online offline-mode tạm thời với cloud_id này
            print(f"[AccountManager] Cloud login notice: {login_res.get('error')}")

        # 5. Cập nhật hoặc thêm vào danh sách tài khoản
        target_id = f"acc_online_{cloud_id.lower()}"
        existing = next((a for a in idx["accounts"] if a["id"] == target_id or a.get("cloud_id") == cloud_id), None)

        if existing:
            existing["last_active"] = int(time.time())
            existing["type"] = "online"
            existing["cloud_id"] = cloud_id
            target_id = existing["id"]
        else:
            new_acc = {
                "id": target_id,
                "name": cloud_id,
                "type": "online",
                "cloud_id": cloud_id,
                "avatar_url": "preset:space_astro",
                "cover_url": "preset:synthwave",
                "bio": "Cổ Ngữ Cloud Member",
                "created_at": int(time.time()),
                "last_active": int(time.time()),
            }
            idx["accounts"].append(new_acc)

        idx["active_account_id"] = target_id
        self._save_index(idx)

        # 6. Tải save đám mây về máy (nếu có)
        dl_res = {}
        try:
            dl_res = self.community_cloud_mgr.download_save()
        except Exception as e:
            dl_res = {"success": False, "error": str(e)}

        # Cập nhật tên hiển thị trong profile
        cfg = self.config_getter() or {}
        cfg["profile"]["player_name"] = cloud_id
        self.config_saver(cfg)

        return {
            "success": True,
            "message": f"Đã đăng nhập tài khoản Online '{cloud_id}'! Dữ liệu cũ đã được dọn sạch và nạp dữ liệu đám mây mới.",
            "login_result": login_res,
            "download_result": dl_res,
            "active_account_id": target_id,
            "accounts": idx["accounts"],
        }

    def delete_account(self, account_id: str) -> dict:
        """Xóa vĩnh viễn một tài khoản khỏi danh sách và xóa toàn bộ dữ liệu lưu trữ của nó."""
        idx = self._load_index()
        curr_active = idx.get("active_account_id")

        if account_id == curr_active:
            return {
                "success": False,
                "error": "Không thể xóa tài khoản đang hoạt động! Vui lòng chuyển sang tài khoản khác trước.",
            }

        target = next((a for a in idx["accounts"] if a["id"] == account_id), None)
        if not target:
            return {"success": False, "error": "Không tìm thấy tài khoản cần xóa!"}

        idx["accounts"] = [a for a in idx["accounts"] if a["id"] != account_id]
        self._save_index(idx)

        # Xóa thư mục snapshot
        acc_dir = os.path.join(self.profiles_root, account_id)
        if os.path.isdir(acc_dir):
            try:
                shutil.rmtree(acc_dir)
            except Exception as e:
                print(f"[AccountManager] Lỗi xóa thư mục '{acc_dir}': {e}")

        return {
            "success": True,
            "message": f"Đã xóa vĩnh viễn tài khoản '{target['name']}' cùng toàn bộ dữ liệu lưu trữ của nó!",
            "accounts": idx["accounts"],
        }

    def purge_and_logout(self) -> dict:
        """
        KÍCH SẠCH 100% DỮ LIỆU VÀ ĐĂNG XUẤT RA KHỎI MỌI TÀI KHOẢN.
        Trả app về chế độ 'Khách Vô Danh' hoàn toàn trống.
        """
        idx = self._load_index()
        curr_active = idx.get("active_account_id")
        if curr_active:
            self.save_account_snapshot(curr_active)

        self.purge_active_session_data(is_new_blank=True)

        guest_id = f"acc_offline_guest_{int(time.time())}"
        guest_acc = {
            "id": guest_id,
            "name": "Khách (App Trống)",
            "type": "offline",
            "cloud_id": "",
            "avatar_url": "preset:space_astro",
            "cover_url": "preset:synthwave",
            "bio": "Chế độ app trống sau khi kích dữ liệu",
            "created_at": int(time.time()),
            "last_active": int(time.time()),
        }
        idx["accounts"].append(guest_acc)
        idx["active_account_id"] = guest_id
        self._save_index(idx)

        return {
            "success": True,
            "message": "Đã kích toàn bộ dữ liệu cũ ra khỏi máy! Ứng dụng đã được đưa về trạng thái trống hoàn toàn.",
            "active_account": guest_acc,
            "accounts": idx["accounts"],
        }

    def get_status(self) -> dict:
        """Lấy danh sách tất cả tài khoản và tài khoản hiện đang active."""
        idx = self._load_index()
        active_id = idx.get("active_account_id")
        active_acc = next((a for a in idx.get("accounts", []) if a["id"] == active_id), None)

        if not active_acc and idx.get("accounts"):
            active_acc = idx["accounts"][0]
            idx["active_account_id"] = active_acc["id"]
            self._save_index(idx)

        # Cập nhật thông tin thực tế từ config hiện tại nếu có
        cfg = self.config_getter() or {}
        p_cfg = cfg.get("profile", {})
        cc_cfg = cfg.get("community_cloud", {})

        if active_acc:
            if p_cfg.get("player_name"):
                active_acc["name"] = p_cfg["player_name"]
            if p_cfg.get("avatar_url"):
                active_acc["avatar_url"] = p_cfg["avatar_url"]
            if p_cfg.get("cover_url"):
                active_acc["cover_url"] = p_cfg["cover_url"]
            if p_cfg.get("bio"):
                active_acc["bio"] = p_cfg["bio"]
            if cc_cfg.get("is_logged_in") and cc_cfg.get("cloud_id"):
                active_acc["type"] = "online"
                active_acc["cloud_id"] = cc_cfg["cloud_id"]

        return {
            "success": True,
            "active_account": active_acc,
            "accounts": idx.get("accounts", []),
            "total_accounts": len(idx.get("accounts", [])),
        }
