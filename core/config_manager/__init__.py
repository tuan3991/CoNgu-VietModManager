# -*- coding: utf-8 -*-
"""
Core Package: config_manager
"""
from .paths import (
    CURRENT_VERSION, GITHUB_REPO, REMOTE_CATALOG_URLS, REMOTE_VERSION_URLS,
    APP_DIR, STATIC_DIR, USER_DOCS_DIR, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR,
    GAMES_JSON, APPDATA_DIR, CONFIG_JSON, BACKUP_ROOT, USER_DATA_FILE,
    COVERS_DIR, COVERS_CACHE_FILE, PLAYTIME_FILE, CACHE_GAMES_JSON, CUSTOM_GAMES_JSON,
)

from .user_settings import (
    load_user_config, save_user_config, get_repo_dir, get_all_configured_game_paths,
    load_user_data, save_user_data, load_covers_cache, save_covers_cache,
)

from .catalog import (
    set_api_instance_ref, get_active_games_json_path, get_games,
    load_custom_games, save_custom_games, sync_remote_catalog, check_app_update,
)

__all__ = [
    "CURRENT_VERSION", "GITHUB_REPO", "REMOTE_CATALOG_URLS", "REMOTE_VERSION_URLS",
    "APP_DIR", "STATIC_DIR", "USER_DOCS_DIR", "DEFAULT_REPO_DIR", "FALLBACK_REPO_DIR",
    "GAMES_JSON", "APPDATA_DIR", "CONFIG_JSON", "BACKUP_ROOT", "USER_DATA_FILE",
    "COVERS_DIR", "COVERS_CACHE_FILE", "PLAYTIME_FILE", "CACHE_GAMES_JSON", "CUSTOM_GAMES_JSON",
    "load_user_config", "save_user_config", "get_repo_dir", "get_all_configured_game_paths",
    "load_user_data", "save_user_data", "load_covers_cache", "save_covers_cache",
    "set_api_instance_ref", "get_active_games_json_path", "get_games",
    "load_custom_games", "save_custom_games", "sync_remote_catalog", "check_app_update",
]
