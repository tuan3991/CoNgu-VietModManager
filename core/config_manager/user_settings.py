# -*- coding: utf-8 -*-
"""
Core Config Manager - User Settings, Repo & Data Caches
"""
import os
import re
import sys
import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List

from .paths import (
    APP_DIR, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR, CONFIG_JSON,
    USER_DATA_FILE, COVERS_CACHE_FILE, APPDATA_DIR
)
from core.scanner import get_available_drives


DEFAULT_USER_CONFIG = {
    "general": {
        "theme": "cyberpunk_default",
        "auto_check_update": True,
        "achievement_sound": True
    },
    "scanner": {
        "auto_scan_on_startup": True,
        "custom_library_paths": [],
        "scan_steam": True,
        "scan_epic": True,
        "scan_gog": True
    },
    "in_game": {
        "game_booster_enabled": True,
        "auto_minimize_on_launch": True,
        "quick_checkpoint_enabled": True,
        "checkpoint_sound": True,
        "show_session_summary": True,
        "hotkey_save": "Ctrl+F5",
        "hotkey_load": "Ctrl+F9"
    },
    "downloader": {
        "preferred_source": "github_cdn",
        "keep_congu_cache": False,
        "max_concurrent_downloads": 3,
        "max_download_limit_kb": 0,
        "pause_on_gameplay": True
    },
    "cloud_save": {
        "cloud_id": "",
        "password": "",
        "auto_sync_on_exit": True,
        "track_playtime": True,
        "offline_achievements_scan": True
    },
    "controller": {
        "enabled": True,
        "vibration": True,
        "sound_effects": True,
        "deadzone": 0.15
    }
}


def _normalize_nested_config(cfg: dict) -> bool:
    """Đảm bảo cấu hình luôn có đầy đủ 4 nhánh nested: general, scanner, downloader, cloud_save và đồng bộ tương thích ngược."""
    changed = False
    for section, defaults in DEFAULT_USER_CONFIG.items():
        if section not in cfg or not isinstance(cfg[section], dict):
            cfg[section] = {}
            changed = True
        for k, v in defaults.items():
            if k not in cfg[section]:
                cfg[section][k] = v
                changed = True

    # Đồng bộ tương thích ngược với các trường cũ
    # 1. Theme
    if "active_theme" in cfg and cfg["active_theme"]:
        if cfg["general"]["theme"] != cfg["active_theme"]:
            cfg["general"]["theme"] = cfg["active_theme"]
    else:
        cfg["active_theme"] = cfg["general"].get("theme", "cyberpunk_default")

    # 2. Cloud ID & Password
    comm_cloud = cfg.get("community_cloud")
    if isinstance(comm_cloud, dict):
        if not cfg["cloud_save"]["cloud_id"] and comm_cloud.get("cloud_id"):
            cfg["cloud_save"]["cloud_id"] = comm_cloud["cloud_id"]
        if not cfg["cloud_save"]["password"] and comm_cloud.get("password"):
            cfg["cloud_save"]["password"] = comm_cloud["password"]
    else:
        cfg["community_cloud"] = {
            "server_url": "https://script.google.com/macros/s/AKfycbyCj_X491qIq1Ew4-hI1j9dK0g1o2T0F8/exec",
            "cloud_id": cfg["cloud_save"]["cloud_id"],
            "password": cfg["cloud_save"]["password"],
            "last_sync": None,
            "last_size": 0,
            "is_logged_in": bool(cfg["cloud_save"]["cloud_id"])
        }

    # 3. Custom library paths
    if "custom_library_paths" in cfg and isinstance(cfg["custom_library_paths"], list):
        for p in cfg["custom_library_paths"]:
            if p not in cfg["scanner"]["custom_library_paths"]:
                cfg["scanner"]["custom_library_paths"].append(p)
    cfg['custom_library_paths'] = list(cfg['scanner']['custom_library_paths'])

    return changed


def load_user_config() -> dict:
    """Nạp tệp cấu hình user_config.json (tự di chuyển cấu hình cũ sang APPDATA nếu cần)."""
    cfg = {"repo_dir": DEFAULT_REPO_DIR}
    legacy_config = os.path.join(APP_DIR, "user_config.json")
    if not os.path.exists(CONFIG_JSON) and os.path.exists(legacy_config):
        try:
            with open(legacy_config, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
            _normalize_nested_config(cfg)
            save_user_config(cfg)
            return cfg
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass

    if _normalize_nested_config(cfg):
        save_user_config(cfg)

    return cfg


def save_user_config(cfg: dict) -> bool:
    """Lưu an toàn tệp cấu hình user_config.json vào APPDATA."""
    try:
        os.makedirs(os.path.dirname(CONFIG_JSON), exist_ok=True)
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ConfigManager] Error saving config: {e}")
        return False


def get_repo_dir() -> str:
    """Lấy đường dẫn kho mod Viethoagame với khả năng tự động nhận diện thông minh đa ổ đĩa."""
    cfg = load_user_config()
    repo = cfg.get("repo_dir")
    if repo and os.path.exists(repo):
        return repo

    candidates = [
        DEFAULT_REPO_DIR,
        FALLBACK_REPO_DIR,
        os.path.join(APP_DIR, "..", "Viethoagame"),
        os.path.join(APP_DIR, "mods"),
    ]
    for d in get_available_drives():
        candidates.append(f"{d}:\\My Drive\\Viethoagame")
        candidates.append(f"{d}:\\Google Drive\\Viethoagame")
        candidates.append(f"{d}:\\Viethoagame")

    for c in candidates:
        if os.path.exists(c):
            cfg["repo_dir"] = os.path.normpath(c)
            save_user_config(cfg)
            return cfg["repo_dir"]

    return DEFAULT_REPO_DIR


def get_all_configured_game_paths() -> dict:
    """Lấy danh sách toàn bộ thư mục game đã được định danh trên máy."""
    try:
        cfg = load_user_config()
        paths = {}
        for k, v in cfg.items():
            if k.endswith("_path") and v and os.path.isdir(v):
                gid = k[:-5]
                paths[gid] = v
        return paths
    except Exception:
        return {}


def get_favorite_games() -> list:
    """
    Lấy danh sách game_id người dùng đã thả tim (key 'favorite_games' trong user_config.json).
    Luôn trả về list[str] hợp lệ, kể cả khi dữ liệu thiếu hoặc sai kiểu.
    """
    try:
        cfg = load_user_config()
        favs = cfg.get("favorite_games", [])
        if not isinstance(favs, list):
            return []
        result = []
        for gid in favs:
            if isinstance(gid, str) and gid and gid not in result:
                result.append(gid)
        return result
    except Exception as e:
        print(f"[ConfigManager] Error loading favorite games: {e}")
        return []


def is_favorite(game_id: str) -> bool:
    """Kiểm tra game_id có nằm trong danh sách yêu thích của người dùng hay không."""
    try:
        if not isinstance(game_id, str) or not game_id:
            return False
        return game_id in get_favorite_games()
    except Exception as e:
        print(f"[ConfigManager] Error checking favorite game: {e}")
        return False


def toggle_favorite(game_id: str) -> dict:
    """
    Đảo trạng thái yêu thích của game (thêm nếu chưa có, xóa nếu đã có),
    lưu vào user_config.json và trả về trạng thái mới cùng danh sách yêu thích.
    """
    try:
        if not isinstance(game_id, str):
            game_id = "" if game_id is None else str(game_id)
        game_id = game_id.strip()
        if not game_id:
            return {"success": False, "message": "Thiếu game_id để thả tim."}

        cfg = load_user_config()
        raw_favs = cfg.get("favorite_games", [])
        if not isinstance(raw_favs, list):
            raw_favs = []

        # Chuẩn hóa & chống trùng lặp id
        favorites = []
        for gid in raw_favs:
            if isinstance(gid, str) and gid and gid not in favorites:
                favorites.append(gid)

        if game_id in favorites:
            favorites.remove(game_id)
            is_fav = False
        else:
            favorites.append(game_id)
            is_fav = True

        cfg["favorite_games"] = favorites
        if not save_user_config(cfg):
            return {"success": False, "message": "Không thể lưu danh sách yêu thích."}

        return {
            "success": True,
            "game_id": game_id,
            "is_favorite": is_fav,
            "favorites": favorites,
        }
    except Exception as e:
        print(f"[ConfigManager] Error toggling favorite: {e}")
        return {"success": False, "message": f"Lỗi khi lưu yêu thích: {e}"}


def get_installed_mod_receipt(game_id: str) -> dict:
    """Lấy biên nhận cài đặt bản mod đã lưu trong user_config.json."""
    try:
        if not game_id:
            return {}
        cfg = load_user_config()
        mods = cfg.get("installed_mods", {})
        if isinstance(mods, dict) and game_id in mods:
            item = mods[game_id]
            return item if isinstance(item, dict) else {}
        return {}
    except Exception as e:
        print(f"[ConfigManager] Error reading mod receipt for {game_id}: {e}")
        return {}


def record_installed_mod_receipt(game_id: str, version: str, sha256: str = "", metadata: dict = None) -> bool:
    """Ghi nhận phiên bản mod đã cài đặt thành công vào user_config.json."""
    try:
        if not game_id:
            return False
        cfg = load_user_config()
        if "installed_mods" not in cfg or not isinstance(cfg["installed_mods"], dict):
            cfg["installed_mods"] = {}

        entry = {
            "game_id": game_id,
            "version": version or "v1.0.0",
            "sha256": sha256 or "",
            "installed_at": datetime.now().isoformat(),
            "status": "installed",
        }
        if metadata and isinstance(metadata, dict):
            for k, v in metadata.items():
                if k not in entry:
                    entry[k] = v

        cfg["installed_mods"][game_id] = entry
        return save_user_config(cfg)
    except Exception as e:
        print(f"[ConfigManager] Error recording mod receipt for {game_id}: {e}")
        return False


def remove_installed_mod_receipt(game_id: str) -> bool:
    """Đánh dấu hoặc xóa biên nhận bản mod khi người dùng gỡ cài đặt."""
    try:
        if not game_id:
            return False
        cfg = load_user_config()
        mods = cfg.get("installed_mods", {})
        if isinstance(mods, dict) and game_id in mods:
            mods[game_id]["status"] = "uninstalled"
            mods[game_id]["uninstalled_at"] = datetime.now().isoformat()
            cfg["installed_mods"] = mods
            return save_user_config(cfg)
        return True
    except Exception as e:
        print(f"[ConfigManager] Error removing mod receipt for {game_id}: {e}")
        return False


def _slug_key(text: str) -> str:
    """Chuẩn hóa chuỗi thành khóa so khớp: chữ thường, chỉ giữ chữ số và 1 khoảng trắng."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _safe_bookmark_url(url: str) -> str:
    """Chỉ chấp nhận URL http(s) cho ảnh bìa — chặn scheme lạ từ nguồn ngoài."""
    url = str(url or "").strip()
    return url if re.match(r"^https?://", url, re.IGNORECASE) else ""


def _new_bookmark_id(payload: dict) -> str:
    appid = str(payload.get("steam_appid") or "").strip()
    if appid.isdigit():
        return f"steam_{appid}"
    slug = _slug_key(payload.get("slug") or "")
    if slug:
        source = _slug_key(payload.get("source") or "web").replace(" ", "_") or "web"
        return f"{source}_{slug.replace(' ', '_')}"
    title_key = _slug_key(payload.get("title") or "")
    if title_key:
        return "bm_" + title_key.replace(" ", "_")
    return "bm_" + uuid.uuid4().hex[:10]


def _normalize_bookmark(raw: dict) -> dict:
    entry = {
        "id": str(raw.get("id") or raw.get("game_id") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "vietnamese_title": str(raw.get("vietnamese_title") or "").strip(),
        "steam_appid": str(raw.get("steam_appid") or "").strip(),
        "cover_url": _safe_bookmark_url(raw.get("cover_url") or raw.get("poster_url")),
        "header_url": _safe_bookmark_url(raw.get("header_url")),
        "genre": str(raw.get("genre") or "").strip(),
        "source": str(raw.get("source") or "web").strip(),
        "slug": str(raw.get("slug") or "").strip(),
        "added_ts": int(raw.get("added_ts") or 0),
    }
    # Id được chèn vào onclick/HTML ở frontend nên chỉ giữ ký tự an toàn
    entry["id"] = re.sub(r"[^A-Za-z0-9_.-]", "_", entry["id"])[:120]
    if not entry["id"]:
        entry["id"] = _new_bookmark_id(entry)
    if not entry["title"]:
        entry["title"] = entry["id"]
    if not entry["vietnamese_title"]:
        entry["vietnamese_title"] = entry["title"]
    return entry


def _bookmark_matches(entry: dict, candidate: dict) -> bool:
    if entry["id"] == candidate["id"]:
        return True
    if entry["steam_appid"] and entry["steam_appid"] == candidate["steam_appid"]:
        return True
    if entry["title"] and candidate["title"]:
        return _slug_key(entry["title"]) == _slug_key(candidate["title"])
    return False


def get_bookmarked_games() -> list:
    """
    Lấy danh sách game người dùng đã "Thêm vào Thư viện" (key 'bookmarked_games').
    Mỗi phần tử là snapshot metadata để game chưa tải vẫn hiển thị được trong Thư Viện.
    """
    try:
        cfg = load_user_config()
        raw = cfg.get("bookmarked_games", [])
        if not isinstance(raw, list):
            return []
        result = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            entry = _normalize_bookmark(item)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            result.append(entry)
        return result
    except Exception as e:
        print(f"[ConfigManager] Error loading bookmarked games: {e}")
        return []


def save_bookmarked_games(entries: list) -> bool:
    """Lưu danh sách bookmark vào user_config.json (đã chuẩn hóa & chống trùng id)."""
    try:
        normalized = []
        seen = set()
        for item in entries or []:
            if not isinstance(item, dict):
                continue
            entry = _normalize_bookmark(item)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            normalized.append(entry)

        cfg = load_user_config()
        cfg["bookmarked_games"] = normalized
        return save_user_config(cfg)
    except Exception as e:
        print(f"[ConfigManager] Error saving bookmarked games: {e}")
        return False


def toggle_bookmark(payload: dict) -> dict:
    """
    Đảo trạng thái "Thêm vào Thư viện" của một game.
    payload cần tối thiểu 'title' hoặc 'steam_appid'/game_id; metadata còn lại là snapshot
    để Thư Viện hiển thị được game chưa tải.
    Trả về trạng thái mới + toàn bộ danh sách bookmark.
    """
    try:
        if not isinstance(payload, dict):
            payload = {"game_id": payload}
        candidate = _normalize_bookmark(payload)

        bookmarks = get_bookmarked_games()
        existing = next((b for b in bookmarks if _bookmark_matches(b, candidate)), None)

        if existing:
            bookmarks = [b for b in bookmarks if b["id"] != existing["id"]]
            is_bookmarked = False
        else:
            candidate["added_ts"] = int(candidate.get("added_ts") or 0) or int(time.time())
            bookmarks.append(candidate)
            is_bookmarked = True

        if not save_bookmarked_games(bookmarks):
            return {"success": False, "message": "Không thể lưu danh sách Thư Viện."}

        return {
            "success": True,
            "game_id": candidate["id"],
            "is_bookmarked": is_bookmarked,
            "bookmarks": bookmarks,
        }
    except Exception as e:
        print(f"[ConfigManager] Error toggling bookmark: {e}")
        return {"success": False, "message": f"Lỗi khi lưu Thư Viện: {e}"}


def merge_bookmarked_games(entries: list) -> int:
    """
    Hợp nhất bookmark từ Hồ Sơ .congu_save vào máy hiện tại (chỉ thêm, không xóa).
    Dùng khi nạp hồ sơ ở PC mới để danh sách "Chưa tải" đi theo người chơi.
    """
    try:
        current = get_bookmarked_games()
        added = 0
        for raw in entries or []:
            if not isinstance(raw, dict):
                continue
            candidate = _normalize_bookmark(raw)
            if any(_bookmark_matches(b, candidate) for b in current):
                continue
            current.append(candidate)
            added += 1
        if added:
            save_bookmarked_games(current)
        return added
    except Exception as e:
        print(f"[ConfigManager] Error merging bookmarked games: {e}")
        return 0


def load_user_data() -> dict:
    """Nạp dữ liệu đánh giá, bình luận, machine_id từ user_data.json."""
    data = {"ratings": {}, "comments": {}, "bug_reports": [], "game_requests": [], "voted_requests": [], "machine_id": None}
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                data.update(saved)
        except Exception:
            pass
    if not data.get("machine_id"):
        data["machine_id"] = str(uuid.uuid4())
        save_user_data(data)
    if "voted_requests" not in data:
        data["voted_requests"] = []
    return data


def save_user_data(data: dict) -> bool:
    """Lưu dữ liệu người dùng vào user_data.json."""
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ConfigManager] Error saving user data: {e}")
        return False


def load_covers_cache() -> dict:
    """Nạp cache metadata & avatar đã tìm được của game lẻ từ tệp JSON."""
    if os.path.exists(COVERS_CACHE_FILE):
        try:
            with open(COVERS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_covers_cache(cache: dict) -> bool:
    """Lưu cache metadata & avatar của game lẻ vào tệp JSON."""
    try:
        with open(COVERS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ConfigManager] Error saving covers cache: {e}")
        return False


def get_unified_settings() -> dict:
    """L?y c?u h?nh h?p nh?t 6 tab (General, Scanner, In-Game, Downloader, Cloud Save, Controller)."""
    cfg = load_user_config()
    return {
        "general": dict(cfg.get("general", DEFAULT_USER_CONFIG["general"])),
        "scanner": dict(cfg.get("scanner", DEFAULT_USER_CONFIG["scanner"])),
        "in_game": dict(cfg.get("in_game", DEFAULT_USER_CONFIG["in_game"])),
        "downloader": dict(cfg.get("downloader", DEFAULT_USER_CONFIG["downloader"])),
        "cloud_save": dict(cfg.get("cloud_save", DEFAULT_USER_CONFIG["cloud_save"])),
        "controller": dict(cfg.get("controller", DEFAULT_USER_CONFIG["controller"])),
    }


def update_unified_settings(new_config: dict) -> dict:
    """Cập nhật toàn bộ hoặc từng phần cài đặt từ 4 tab của Menu Cài Đặt."""
    try:
        cfg = load_user_config()
        if not isinstance(new_config, dict):
            return {"success": False, "message": "Dữ liệu cấu hình không hợp lệ."}

        for section in ["general", "scanner", "in_game", "downloader", "cloud_save", "controller"]:
            if section in new_config and isinstance(new_config[section], dict):
                if section not in cfg or not isinstance(cfg[section], dict):
                    cfg[section] = {}
                cfg[section].update(new_config[section])

        # Đồng bộ ngược tương thích với theme hệ thống
        if "general" in cfg and "theme" in cfg["general"]:
            cfg["active_theme"] = cfg["general"]["theme"]
            try:
                from core.theme_manager import set_active_theme
                set_active_theme(cfg["general"]["theme"])
            except Exception:
                pass

        # Đồng bộ ngược với tài khoản Community Cloud (Đám Mây Cổ Ngữ)
        if "cloud_save" in cfg and isinstance(cfg["cloud_save"], dict):
            if "community_cloud" not in cfg or not isinstance(cfg["community_cloud"], dict):
                cfg["community_cloud"] = {}
            cc = cfg["community_cloud"]
            cs = cfg["cloud_save"]

            old_id = str(cc.get("cloud_id") or "")
            old_pass = str(cc.get("password") or "")
            new_id = str(cs.get("cloud_id") or "").strip()
            new_pass = str(cs.get("password") or "").strip()

            cc["cloud_id"] = new_id
            cc["password"] = new_pass
            cc["is_logged_in"] = bool(new_id and new_pass)

            # Đổi tài khoản/mật khẩu trong Cài đặt thì mốc đồng bộ cũ không còn đúng
            if new_id != old_id or new_pass != old_pass:
                cc["last_sync"] = None
                cc["last_size"] = 0

        # Đồng bộ ngược với danh sách thư mục quét ngoài
        if "scanner" in cfg and isinstance(cfg["scanner"], dict) and "custom_library_paths" in cfg["scanner"]:
            cfg["custom_library_paths"] = cfg["scanner"]["custom_library_paths"]

        # Áp dụng giới hạn băng thông aria2c NGAY nếu daemon đang chạy
        # (nếu chưa chạy, TorrentDownloader sẽ tự đọc cấu hình lúc khởi động daemon)
        if "downloader" in cfg and isinstance(cfg["downloader"], dict):
            try:
                from core.downloader import get_torrent_manager
                mgr = get_torrent_manager()
                if mgr is not None and getattr(mgr, "daemon_proc", None) is not None:
                    mgr.set_speed_limit(int(cfg["downloader"].get("max_download_limit_kb", 0) or 0))
                    mgr.set_max_concurrent(int(cfg["downloader"].get("max_concurrent_downloads", 3) or 3))
            except Exception as exc:
                print(f"[ConfigManager] Bỏ qua áp dụng giới hạn aria2c: {exc}")

        ok = save_user_config(cfg)
        if not ok:
            return {"success": False, "message": "Không thể lưu tệp user_config.json."}

        return {
            "success": True,
            "message": "Đã lưu toàn bộ cài đặt thành công!",
            "settings": get_unified_settings()
        }
    except Exception as e:
        print(f"[ConfigManager] Error updating unified settings: {e}")
        return {"success": False, "message": f"Lỗi lưu cài đặt: {e}"}


def get_cache_stats() -> dict:
    """Tính toán dung lượng bộ nhớ đệm cache các gói mod .congu, file tạm và hydra cache."""
    cache_dirs = [
        os.path.join(APPDATA_DIR, "cache"),
        os.path.join(APPDATA_DIR, "temp"),
    ]
    total_bytes = 0
    file_count = 0

    for cdir in cache_dirs:
        if os.path.exists(cdir):
            for root, _, files in os.walk(cdir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total_bytes += os.path.getsize(fp)
                        file_count += 1
                    except Exception:
                        pass

    if total_bytes >= 1024 * 1024 * 1024:
        formatted = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif total_bytes >= 1024 * 1024:
        formatted = f"{total_bytes / (1024 * 1024):.1f} MB"
    elif total_bytes >= 1024:
        formatted = f"{total_bytes / 1024:.1f} KB"
    else:
        formatted = f"{total_bytes} B"

    return {
        "success": True,
        "total_bytes": total_bytes,
        "file_count": file_count,
        "formatted_size": formatted
    }


def clear_app_cache() -> dict:
    """Dọn dẹp sạch sẽ bộ nhớ đệm cache các gói .congu và tệp tạm thời."""
    cache_dirs = [
        os.path.join(APPDATA_DIR, "cache"),
        os.path.join(APPDATA_DIR, "temp"),
    ]
    freed_bytes = 0
    deleted_files = 0

    for cdir in cache_dirs:
        if os.path.exists(cdir):
            for root, dirs, files in os.walk(cdir, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        os.remove(fp)
                        freed_bytes += sz
                        deleted_files += 1
                    except Exception:
                        pass
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        os.rmdir(dp)
                    except Exception:
                        pass

    for cdir in cache_dirs:
        try:
            os.makedirs(cdir, exist_ok=True)
        except Exception:
            pass

    if freed_bytes >= 1024 * 1024 * 1024:
        freed_str = f"{freed_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif freed_bytes >= 1024 * 1024:
        freed_str = f"{freed_bytes / (1024 * 1024):.1f} MB"
    else:
        freed_str = f"{freed_bytes / 1024:.1f} KB"

    return {
        "success": True,
        "freed_bytes": freed_bytes,
        "deleted_files": deleted_files,
        "formatted_freed": freed_str,
        "message": f"Đã dọn dẹp {deleted_files} tệp cache, giải phóng {freed_str} dung lượng ổ đĩa!"
    }


def open_appdata_directory() -> dict:
    """Mở nhanh thư mục dữ liệu %APPDATA%/VietModHub/ trên Windows Explorer."""
    import subprocess
    target = os.path.normpath(APPDATA_DIR)
    os.makedirs(target, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.Popen(["xdg-open", target])
        return {"success": True, "path": target, "message": f"Đã mở thư mục: {target}"}
    except Exception as e:
        print(f"[ConfigManager] Error opening AppData: {e}")
        return {"success": False, "error": str(e), "message": f"Không thể mở thư mục: {e}"}

