# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Configuration & Catalog Manager Module
------------------------------------------------------------------
Quản lý hợp nhất:
1. Đường dẫn thư mục chuẩn (APP_DIR, APPDATA_DIR, STATIC_DIR, REPO_DIR...).
2. Cấu hình người dùng (load_user_config, save_user_config, get_repo_dir...).
3. Danh mục game (get_active_games_json_path, get_games, sync_remote_catalog).
4. Game ngoài tự thêm (load_custom_games, save_custom_games).
5. Dữ liệu đánh giá, bình luận và cập nhật phiên bản (load_user_data, check_app_update).
"""

import os
import sys
import json
import uuid
import re
import urllib.request
from typing import List, Dict, Any, Optional

from core.scanner import get_available_drives

CURRENT_VERSION = "2.0.3"
GITHUB_REPO = "tuan3991/CoNgu-VietModManager"
REMOTE_CATALOG_URLS = [
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/games.json",
    f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/games.json",
]
REMOTE_VERSION_URLS = [
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json",
    f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/version.json",
]

# Base paths with PyInstaller frozen support
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(EXE_DIR, "static")):
        APP_DIR = EXE_DIR
        STATIC_DIR = os.path.join(EXE_DIR, "static")
    else:
        APP_DIR = getattr(sys, '_MEIPASS', EXE_DIR)
        STATIC_DIR = os.path.join(APP_DIR, "static")
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    STATIC_DIR = os.path.join(APP_DIR, "static")

USER_DOCS_DIR = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")
DEFAULT_REPO_DIR = os.path.join(USER_DOCS_DIR, "Viethoagame")
FALLBACK_REPO_DIR = os.path.join(APP_DIR, "Viethoagame")
GAMES_JSON = os.path.join(APP_DIR, "games.json")

# AppData safe directory (chống mất cấu hình và lỗi quyền ghi khi đóng gói PyInstaller)
APPDATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "VietModHub")
CONFIG_JSON = os.path.join(APPDATA_DIR, "user_config.json")
BACKUP_ROOT = os.path.join(APPDATA_DIR, "backups")
USER_DATA_FILE = os.path.join(APPDATA_DIR, "user_data.json")
COVERS_DIR = os.path.join(APPDATA_DIR, "covers")
COVERS_CACHE_FILE = os.path.join(APPDATA_DIR, "covers_cache.json")
PLAYTIME_FILE = os.path.join(APPDATA_DIR, "playtime.json")
CACHE_GAMES_JSON = os.path.join(APPDATA_DIR, "games_cache.json")
CUSTOM_GAMES_JSON = os.path.join(APPDATA_DIR, "custom_games.json")

os.makedirs(APPDATA_DIR, exist_ok=True)
os.makedirs(COVERS_DIR, exist_ok=True)
os.makedirs(BACKUP_ROOT, exist_ok=True)

_API_INSTANCE_REF = None


def set_api_instance_ref(inst):
    """Gắn thể hiện ModManagerAPI để get_games có thể tra cứu nhanh."""
    global _API_INSTANCE_REF
    _API_INSTANCE_REF = inst


# ==============================================================================
# CẤU HÌNH NGƯỜI DÙNG (user_config.json)
# ==============================================================================

def load_user_config() -> dict:
    """Nạp tệp cấu hình user_config.json (tự di chuyển cấu hình cũ sang APPDATA nếu cần)."""
    cfg = {"repo_dir": DEFAULT_REPO_DIR}
    legacy_config = os.path.join(APP_DIR, "user_config.json")
    if not os.path.exists(CONFIG_JSON) and os.path.exists(legacy_config):
        try:
            with open(legacy_config, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
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


# ==============================================================================
# DANH MỤC GAME (games.json & custom_games.json)
# ==============================================================================

def get_active_games_json_path() -> str:
    """Trả về đường dẫn games.json tốt nhất (Remote Cache trong AppData hoặc file đính kèm cục bộ)."""
    if not getattr(sys, 'frozen', False) and os.path.exists(GAMES_JSON):
        return GAMES_JSON

    if os.path.exists(GAMES_JSON):
        if not os.path.exists(CACHE_GAMES_JSON):
            return GAMES_JSON
        try:
            if os.path.getmtime(GAMES_JSON) >= os.path.getmtime(CACHE_GAMES_JSON):
                return GAMES_JSON
        except Exception:
            pass
    if os.path.exists(CACHE_GAMES_JSON) and os.path.getsize(CACHE_GAMES_JSON) > 100:
        return CACHE_GAMES_JSON
    if os.path.exists(GAMES_JSON):
        return GAMES_JSON
    fallback_exe_json = os.path.join(os.path.dirname(sys.executable), "games.json")
    if os.path.exists(fallback_exe_json):
        return fallback_exe_json
    return GAMES_JSON


def get_games() -> list:
    """Lấy danh sách các game từ games.json hoặc api_instance."""
    global _API_INSTANCE_REF
    if _API_INSTANCE_REF:
        try:
            return _API_INSTANCE_REF.get_games()
        except Exception:
            pass
    gp = get_active_games_json_path()
    if os.path.exists(gp):
        try:
            with open(gp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def load_custom_games() -> list:
    """Tải danh sách game ngoài do người dùng tự thêm từ custom_games.json."""
    if not os.path.exists(CUSTOM_GAMES_JSON):
        return []
    try:
        with open(CUSTOM_GAMES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[CustomGames] Lỗi đọc custom_games.json: {e}")
        return []


def save_custom_games(games_list: list) -> bool:
    """Lưu danh sách game ngoài vào custom_games.json."""
    try:
        os.makedirs(os.path.dirname(CUSTOM_GAMES_JSON), exist_ok=True)
        with open(CUSTOM_GAMES_JSON, "w", encoding="utf-8") as f:
            json.dump(games_list, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[CustomGames] Lỗi ghi custom_games.json: {e}")
        return False


def sync_remote_catalog(force: bool = False) -> dict:
    """
    Tải danh mục games.json mới nhất từ GitHub CDN và cập nhật bộ đệm cục bộ.
    Returns: dict(success=bool, updated=bool, count=int, message=str)
    """
    headers = {"User-Agent": "CoNgu-VietModManager/2.0"}

    for url in REMOTE_CATALOG_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = resp.read().decode('utf-8')
                    parsed = json.loads(data)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        current_path = get_active_games_json_path()
                        if os.path.exists(current_path) and not force:
                            try:
                                with open(current_path, 'r', encoding='utf-8') as f:
                                    current_content = f.read()
                                if current_content.strip() == data.strip():
                                    return {"success": True, "updated": False, "count": len(parsed), "message": "Kho game đã ở bản mới nhất"}
                            except Exception:
                                pass

                        with open(CACHE_GAMES_JSON, 'w', encoding='utf-8') as f:
                            f.write(data)

                        if getattr(sys, 'frozen', False):
                            try:
                                with open(GAMES_JSON, 'w', encoding='utf-8') as f:
                                    f.write(data)
                            except Exception:
                                pass

                        return {"success": True, "updated": True, "count": len(parsed), "message": f"Đã đồng bộ {len(parsed)} game từ máy chủ đám mây!"}
        except Exception:
            continue

    current_count = 0
    p = get_active_games_json_path()
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                current_count = len(json.load(f))
        except Exception:
            pass
    return {"success": False, "updated": False, "count": current_count, "message": "Đang dùng dữ liệu ngoại tuyến (Offline)"}


def check_app_update() -> dict:
    """Kiểm tra bản cập nhật mới trên GitHub (version.json)."""
    headers = {"User-Agent": "CoNgu-VietModManager/2.0"}
    for url in REMOTE_VERSION_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    info = json.loads(resp.read().decode('utf-8'))
                    remote_ver = info.get("version", CURRENT_VERSION)

                    def parse_v(v):
                        return [int(x) for x in re.sub(r'[^0-9.]', '', v).split('.') if x.isdigit()]

                    has_update = parse_v(remote_ver) > parse_v(CURRENT_VERSION)
                    return {
                        "success": True,
                        "current_version": CURRENT_VERSION,
                        "latest_version": remote_ver,
                        "has_update": has_update,
                        "title": info.get("name") or info.get("title", f"Bản cập nhật v{remote_ver}"),
                        "release_date": info.get("release_date", ""),
                        "changelog": info.get("changelog", []),
                        "download_url": info.get("download_url", f"https://github.com/{GITHUB_REPO}/releases/latest"),
                        "portable_zip_url": info.get("portable_zip_url", "")
                    }
        except Exception:
            continue

    return {
        "success": False,
        "current_version": CURRENT_VERSION,
        "latest_version": CURRENT_VERSION,
        "has_update": False,
        "message": "Không thể kiểm tra phiên bản mới"
    }


# ==============================================================================
# DỮ LIỆU NGƯỜI DÙNG & BỘ ĐỆM ẢNH BÌA (user_data.json & covers_cache.json)
# ==============================================================================

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
