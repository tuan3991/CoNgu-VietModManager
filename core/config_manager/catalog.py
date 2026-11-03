# -*- coding: utf-8 -*-
"""
Core Config Manager - Games Catalog & App Updates
"""
import os
import sys
import json
import re
import urllib.request
from typing import List, Dict, Any, Optional

from .paths import (
    GAMES_JSON, CACHE_GAMES_JSON, CUSTOM_GAMES_JSON,
    CURRENT_VERSION, GITHUB_REPO, REMOTE_CATALOG_URLS, REMOTE_VERSION_URLS
)

_API_INSTANCE_REF = None


def set_api_instance_ref(inst):
    """Gắn thể hiện ModManagerAPI để get_games có thể tra cứu nhanh."""
    global _API_INSTANCE_REF
    _API_INSTANCE_REF = inst


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
    """Tải danh mục games.json mới nhất từ GitHub CDN và cập nhật bộ đệm cục bộ."""
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
                        "version": remote_ver,
                        "latest_version": remote_ver,
                        "has_update": has_update,
                        "title": info.get("name") or info.get("title", f"Bản cập nhật v{remote_ver}"),
                        "release_date": info.get("release_date", ""),
                        "changelog": info.get("changelog", []),
                        "download_url": info.get("download_url", f"https://github.com/{GITHUB_REPO}/releases/latest"),
                        "portable_zip_url": info.get("portable_zip_url", ""),
                        # SHA-256 phải do quy trình phát hành tạo cùng ZIP, không lấy
                        # từ chính archive/source tải xuống.
                        "portable_zip_sha256": info.get("portable_zip_sha256", ""),
                        # Chữ ký Ed25519 trên (version, portable_zip_url, portable_zip_sha256).
                        "manifest_signature": info.get("manifest_signature", ""),
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
