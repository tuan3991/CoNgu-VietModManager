# -*- coding: utf-8 -*-
"""
Core Config Manager - User Settings, Repo & Data Caches
"""
import os
import json
import uuid
from typing import Dict, Any

from .paths import (
    APP_DIR, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR, CONFIG_JSON,
    USER_DATA_FILE, COVERS_CACHE_FILE
)
from core.scanner import get_available_drives


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
