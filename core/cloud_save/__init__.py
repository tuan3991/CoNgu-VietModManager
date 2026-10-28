# -*- coding: utf-8 -*-
"""
Core Package: cloud_save
"""
from .process_utils import (
    PROCESSENTRY32W,
    EXCLUDED_HELPER_EXES,
    is_any_exe_running_in_folder,
    _internal_log,
    get_default_appdata_dir,
    configure_cloud_save_system,
    register_exit_hook,
)

from .playtime import (
    PlaytimeManager,
    PLAYTIME_MGR,
)

from .achievements import (
    AchievementManager,
    ACHIEVEMENT_MGR,
)

from .gdrive_sync import (
    get_vault_instance,
    ConguSaveVault,
    CloudSyncManager,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    CLOUD_SYNC_MGR,
    SAVE_VAULT,
    handle_game_exit_hook,
)

__all__ = [
    "PROCESSENTRY32W",
    "EXCLUDED_HELPER_EXES",
    "is_any_exe_running_in_folder",
    "PlaytimeManager",
    "AchievementManager",
    "handle_game_exit_hook",
    "register_exit_hook",
    "get_vault_instance",
    "ConguSaveVault",
    "CloudSyncManager",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_CLIENT_SECRET",
    "ACHIEVEMENT_MGR",
    "PLAYTIME_MGR",
    "CLOUD_SYNC_MGR",
    "SAVE_VAULT",
    "configure_cloud_save_system",
]
