# -*- coding: utf-8 -*-
"""
Core Config Manager - Paths & System Constants
"""
import os
import sys

CURRENT_VERSION = "2.0.4"
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
    # 3 levels up from core/config_manager/paths.py -> VietModManager root
    APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    STATIC_DIR = os.path.join(APP_DIR, "static")

USER_DOCS_DIR = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")
DEFAULT_REPO_DIR = os.path.join(USER_DOCS_DIR, "Viethoagame")
FALLBACK_REPO_DIR = os.path.join(APP_DIR, "Viethoagame")
GAMES_JSON = os.path.join(APP_DIR, "games.json")

# AppData safe directory
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
