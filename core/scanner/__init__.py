# -*- coding: utf-8 -*-
"""
Core Package: scanner
"""
from .platform_detector import (
    invalidate_library_caches,
    get_available_drives,
    detect_steam_libraries,
    detect_epic_games,
    detect_gog_games,
    detect_standalone_game_dirs,
)

from .path_verifier import (
    is_running_as_admin,
    check_directory_writable,
    request_uac_elevation,
    find_game_install_path,
    verify_and_resolve_game_path,
)

from .metadata_extractor import (
    extract_local_steam_appid,
    resolve_clean_game_title,
    extract_exe_icon,
)

__all__ = [
    "invalidate_library_caches",
    "get_available_drives",
    "detect_steam_libraries",
    "detect_epic_games",
    "detect_gog_games",
    "detect_standalone_game_dirs",
    "is_running_as_admin",
    "check_directory_writable",
    "request_uac_elevation",
    "find_game_install_path",
    "verify_and_resolve_game_path",
    "extract_local_steam_appid",
    "resolve_clean_game_title",
    "extract_exe_icon",
]
