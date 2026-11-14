# -*- coding: utf-8 -*-
"""
Script to complete modularization of all core modules into 6 subpackages.
"""
import os
import sys
import shutil

CORE_DIR = os.path.abspath("core")

def step2_scanner():
    print("Converting core/scanner.py to package core/scanner/...")
    src_file = os.path.join(CORE_DIR, "scanner.py")
    with open(src_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pkg_dir = os.path.join(CORE_DIR, "scanner_pkg")
    os.makedirs(pkg_dir, exist_ok=True)

    # 1. platform_detector.py
    # Lines 1 to 40 (cache & drives), lines 88 to 280 (detect_steam_libraries, detect_epic_games, detect_gog_games, detect_standalone_game_dirs)
    part1 = "".join(lines[0:41])
    part2 = "".join(lines[87:280])
    detector_content = part1 + "\n" + part2
    with open(os.path.join(pkg_dir, "platform_detector.py"), "w", encoding="utf-8") as f:
        f.write(detector_content)

    # 2. path_verifier.py
    # Lines 42 to 86 (admin & writable & uac), lines 282 to 448 (find_game_install_path, verify_and_resolve_game_path)
    pv_header = '''# -*- coding: utf-8 -*-
import os
import sys
import time
import re
import json
import ctypes
from typing import List, Dict, Any, Optional, Tuple

from .platform_detector import (
    detect_steam_libraries, detect_epic_games, detect_gog_games, detect_standalone_game_dirs
)

'''
    part_admin = "".join(lines[41:86])
    part_verify = "".join(lines[281:449])
    pv_content = pv_header + "\n" + part_admin + "\n" + part_verify
    with open(os.path.join(pkg_dir, "path_verifier.py"), "w", encoding="utf-8") as f:
        f.write(pv_content)

    # 3. metadata_extractor.py
    # Lines 450 to 570 (extract_local_steam_appid, resolve_clean_game_title, extract_exe_icon)
    me_header = '''# -*- coding: utf-8 -*-
import os
import sys
import re
import json
import glob
import subprocess
from typing import Optional

'''
    part_me = "".join(lines[449:])
    me_content = me_header + "\n" + part_me
    with open(os.path.join(pkg_dir, "metadata_extractor.py"), "w", encoding="utf-8") as f:
        f.write(me_content)

    # 4. __init__.py
    init_content = '''# -*- coding: utf-8 -*-
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
'''
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_content)

    # Backup old file & swap
    shutil.move(src_file, src_file + ".bak")
    final_dir = os.path.join(CORE_DIR, "scanner")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.rename(pkg_dir, final_dir)
    print("Done converting core/scanner!")


def step3_downloader():
    print("Converting core/downloader.py to package core/downloader/...")
    src_file = os.path.join(CORE_DIR, "downloader.py")
    with open(src_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pkg_dir = os.path.join(CORE_DIR, "downloader_pkg")
    os.makedirs(pkg_dir, exist_ok=True)

    # 1. http_downloader.py (lines 1 to 96)
    http_content = "".join(lines[0:96])
    with open(os.path.join(pkg_dir, "http_downloader.py"), "w", encoding="utf-8") as f:
        f.write(http_content)

    # 2. torrent_engine.py
    torrent_content = '''# -*- coding: utf-8 -*-
"""
Core Downloader - Torrent Engine (aria2c daemon integration)
"""
import os
from typing import Optional
from core.config_manager import APPDATA_DIR
from torrent_downloader import TorrentDownloader, TorrentDownloadManager, BEST_PUBLIC_TRACKERS

_TORRENT_MGR_INSTANCE: Optional[TorrentDownloadManager] = None

def get_torrent_manager(appdata_dir: Optional[str] = None) -> TorrentDownloadManager:
    """Lấy thể hiện quản lý tải Torrent (Aria2c Daemon)."""
    global _TORRENT_MGR_INSTANCE
    if _TORRENT_MGR_INSTANCE is None:
        target_dir = appdata_dir or APPDATA_DIR
        _TORRENT_MGR_INSTANCE = TorrentDownloadManager(target_dir)
    return _TORRENT_MGR_INSTANCE

TORRENT_MGR = get_torrent_manager()
'''
    with open(os.path.join(pkg_dir, "torrent_engine.py"), "w", encoding="utf-8") as f:
        f.write(torrent_content)

    # 3. hydra_sources.py
    hydra_content = '''# -*- coding: utf-8 -*-
"""
Core Downloader - Hydra Repack Community Sources
"""
import os
from typing import Optional
from core.config_manager import APPDATA_DIR
from hydra_source_manager import HydraSourceManager, DEFAULT_HYDRA_SOURCES

_HYDRA_MGR_INSTANCE: Optional[HydraSourceManager] = None

def get_hydra_manager(appdata_dir: Optional[str] = None) -> HydraSourceManager:
    """Lấy thể hiện quản lý kho nguồn Hydra Launcher."""
    global _HYDRA_MGR_INSTANCE
    if _HYDRA_MGR_INSTANCE is None:
        target_dir = appdata_dir or APPDATA_DIR
        _HYDRA_MGR_INSTANCE = HydraSourceManager(target_dir)
    return _HYDRA_MGR_INSTANCE

HYDRA_MGR = get_hydra_manager()
'''
    with open(os.path.join(pkg_dir, "hydra_sources.py"), "w", encoding="utf-8") as f:
        f.write(hydra_content)

    # 4. __init__.py
    init_content = '''# -*- coding: utf-8 -*-
"""
Core Package: downloader
"""
from .http_downloader import download_file_with_progress
from .torrent_engine import get_torrent_manager, TORRENT_MGR, TorrentDownloadManager, TorrentDownloader
from .hydra_sources import get_hydra_manager, HYDRA_MGR, HydraSourceManager

__all__ = [
    "download_file_with_progress",
    "get_torrent_manager",
    "TORRENT_MGR",
    "TorrentDownloadManager",
    "TorrentDownloader",
    "get_hydra_manager",
    "HYDRA_MGR",
    "HydraSourceManager",
]
'''
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_content)

    # Backup old file & swap
    shutil.move(src_file, src_file + ".bak")
    final_dir = os.path.join(CORE_DIR, "downloader")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.rename(pkg_dir, final_dir)
    print("Done converting core/downloader!")


def step4_backup_rollback():
    print("Converting core/backup_rollback.py to package core/backup_rollback/...")
    src_file = os.path.join(CORE_DIR, "backup_rollback.py")
    with open(src_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pkg_dir = os.path.join(CORE_DIR, "backup_rollback_pkg")
    os.makedirs(pkg_dir, exist_ok=True)

    # 1. manifest_manager.py
    # Lines 1 to 86, 221 to 256
    mm_header = "".join(lines[0:86])
    mm_records = "".join(lines[220:256])
    mm_content = mm_header + "\n" + mm_records
    with open(os.path.join(pkg_dir, "manifest_manager.py"), "w", encoding="utf-8") as f:
        f.write(mm_content)

    # 2. inplace_backup.py
    # Lines 87 to 220, 258 to 375
    ib_header = '''# -*- coding: utf-8 -*-
"""
Core Backup Rollback - In-place Backup & Environment Guards
"""
import os
import sys
import shutil
from typing import Tuple, Dict, Any, Optional

from core.config_manager import BACKUP_ROOT
from security import validate_safe_path, SecurityError, PathTraversalError
from .manifest_manager import (
    compute_file_sha256, norm_rel_path, load_backup_manifest, save_backup_manifest
)

'''
    part_env = "".join(lines[86:123])
    part_inplace = "".join(lines[123:220])
    part_restore = "".join(lines[257:375])
    ib_content = ib_header + "\n" + part_env + "\n" + part_inplace + "\n" + part_restore
    with open(os.path.join(pkg_dir, "inplace_backup.py"), "w", encoding="utf-8") as f:
        f.write(ib_content)

    # 3. emergency_restore.py
    # Lines 377 to 449
    er_header = '''# -*- coding: utf-8 -*-
"""
Core Backup Rollback - Emergency Deep Restore
"""
import os
import shutil
from typing import Optional, Callable

from core.config_manager import load_user_config, save_user_config, get_games
from .manifest_manager import load_backup_manifest, save_backup_manifest

'''
    part_er = "".join(lines[376:])
    er_content = er_header + "\n" + part_er
    with open(os.path.join(pkg_dir, "emergency_restore.py"), "w", encoding="utf-8") as f:
        f.write(er_content)

    # 4. __init__.py
    init_content = '''# -*- coding: utf-8 -*-
"""
Core Package: backup_rollback
"""
from .manifest_manager import (
    compute_file_sha256,
    norm_rel_path,
    _norm_rel,
    load_backup_manifest,
    save_backup_manifest,
    record_backup_manifest,
    record_modded_state,
)

from .inplace_backup import (
    record_preexisting_environment,
    backup_file_inplace,
    restore_files_inplace,
)

from .emergency_restore import (
    emergency_restore_game,
)

__all__ = [
    "compute_file_sha256",
    "norm_rel_path",
    "_norm_rel",
    "load_backup_manifest",
    "save_backup_manifest",
    "record_backup_manifest",
    "record_modded_state",
    "record_preexisting_environment",
    "backup_file_inplace",
    "restore_files_inplace",
    "emergency_restore_game",
]
'''
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_content)

    # Backup old file & swap
    shutil.move(src_file, src_file + ".bak")
    final_dir = os.path.join(CORE_DIR, "backup_rollback")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.rename(pkg_dir, final_dir)
    print("Done converting core/backup_rollback!")


def step5_installer_pipeline():
    print("Converting core/installer_pipeline.py to package core/installer_pipeline/...")
    src_file = os.path.join(CORE_DIR, "installer_pipeline.py")
    with open(src_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pkg_dir = os.path.join(CORE_DIR, "installer_pipeline_pkg")
    os.makedirs(pkg_dir, exist_ok=True)

    # 1. process_checker.py
    # Lines 146 to 388 (calculate_sha256, get_running_processes, get_running_process_names, check_game_running, find_mod_source_dir, check_has_mod_files)
    pc_header = '''# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Process Checker & File Detection
"""
import os
import sys
import ctypes
import hashlib
from typing import List, Tuple, Optional, Any

from core.config_manager import (
    load_user_config, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR, APP_DIR
)
from core.scanner import get_available_drives

'''
    pc_body = "".join(lines[145:388])
    with open(os.path.join(pkg_dir, "process_checker.py"), "w", encoding="utf-8") as f:
        f.write(pc_header + "\n" + pc_body)

    # 2. actions.py
    # Lines 389 to 1064 (patch_ini_file, execute_pipeline_step)
    act_header = '''# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Atomic Actions & Step Executor
"""
import os
import sys
import shutil
import zipfile
import hashlib
from typing import Optional, Any

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch
except ImportError:
    pass

from core.config_manager import BACKUP_ROOT, get_active_games_json_path, get_games
from core.backup_rollback import (
    backup_file_inplace, load_backup_manifest, save_backup_manifest,
    record_backup_manifest, record_modded_state, norm_rel_path
)

'''
    act_body = "".join(lines[388:1064])
    with open(os.path.join(pkg_dir, "actions.py"), "w", encoding="utf-8") as f:
        f.write(act_header + "\n" + act_body)

    # 3. pipeline_runner.py
    # Lines 118 to 145 (INSTALL_PROGRESS, set_progress, get_install_progress) and 1065 to 1383 (execute_action_pipeline)
    pr_header = '''# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Pipeline Runner & Progress Tracking
"""
import os
import sys
import threading
from typing import Dict, Any, List, Optional, Tuple, Callable

from core.config_manager import (
    load_user_config, save_user_config, BACKUP_ROOT, get_games
)
from core.backup_rollback import (
    load_backup_manifest, save_backup_manifest, restore_files_inplace
)
from .actions import execute_pipeline_step

_MOD_OP_LOCK = threading.Lock()

'''
    part_progress = "".join(lines[117:145])
    part_runner = "".join(lines[1064:1383])
    pr_content = pr_header + "\n" + part_progress + "\n" + part_runner
    with open(os.path.join(pkg_dir, "pipeline_runner.py"), "w", encoding="utf-8") as f:
        f.write(pr_content)

    # 4. install_ops.py
    # Lines 1384 to 2083 (install_mod_impl, install_mod, uninstall_mod_impl, uninstall_mod, emergency_restore_game)
    ops_header = '''# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Install & Uninstall Operations
"""
import os
import sys
import time
import json
import shutil
import zipfile
from typing import Optional, Callable, Dict, Any

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError
except ImportError:
    pass

from core.config_manager import (
    load_user_config, save_user_config, BACKUP_ROOT, get_games
)
from core.scanner import check_directory_writable, is_running_as_admin
from core.downloader import download_file_with_progress
from core.backup_rollback import (
    load_backup_manifest, save_backup_manifest, restore_files_inplace,
    record_preexisting_environment
)
from .process_checker import (
    calculate_sha256, check_game_running, find_mod_source_dir, check_has_mod_files
)
from .actions import patch_ini_file
from .pipeline_runner import (
    INSTALL_PROGRESS, set_progress, get_install_progress,
    _MOD_OP_LOCK, execute_action_pipeline
)

'''
    ops_body = "".join(lines[1383:])
    with open(os.path.join(pkg_dir, "install_ops.py"), "w", encoding="utf-8") as f:
        f.write(ops_header + "\n" + ops_body)

    # 5. __init__.py
    init_content = '''# -*- coding: utf-8 -*-
"""
Core Package: installer_pipeline
"""
from .process_checker import (
    calculate_sha256,
    get_running_processes,
    get_running_process_names,
    check_game_running,
    find_mod_source_dir,
    check_has_mod_files,
)

from .actions import (
    patch_ini_file,
    execute_pipeline_step,
)

from .pipeline_runner import (
    INSTALL_PROGRESS,
    set_progress,
    get_install_progress,
    _MOD_OP_LOCK,
    execute_action_pipeline,
)

from .install_ops import (
    install_mod_impl,
    install_mod,
    uninstall_mod_impl,
    uninstall_mod,
    emergency_restore_game,
)

__all__ = [
    "calculate_sha256",
    "get_running_processes",
    "get_running_process_names",
    "check_game_running",
    "find_mod_source_dir",
    "check_has_mod_files",
    "patch_ini_file",
    "execute_pipeline_step",
    "INSTALL_PROGRESS",
    "set_progress",
    "get_install_progress",
    "_MOD_OP_LOCK",
    "execute_action_pipeline",
    "install_mod_impl",
    "install_mod",
    "uninstall_mod_impl",
    "uninstall_mod",
    "emergency_restore_game",
]
'''
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_content)

    # Backup old file & swap
    shutil.move(src_file, src_file + ".bak")
    final_dir = os.path.join(CORE_DIR, "installer_pipeline")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.rename(pkg_dir, final_dir)
    print("Done converting core/installer_pipeline!")


def step6_cloud_save():
    print("Converting core/cloud_save.py to package core/cloud_save/...")
    src_file = os.path.join(CORE_DIR, "cloud_save.py.bak")
    with open(src_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pkg_dir = os.path.join(CORE_DIR, "cloud_save_pkg")
    os.makedirs(pkg_dir, exist_ok=True)

    # 1. process_utils.py (lines 1 to 224)
    pu_content = "".join(lines[0:224])
    with open(os.path.join(pkg_dir, "process_utils.py"), "w", encoding="utf-8") as f:
        f.write(pu_content)

    # 2. playtime.py (lines 225 to 555)
    pt_header = '''# -*- coding: utf-8 -*-
"""
Core Cloud Save - Playtime Tracker
"""
import os
import sys
import time
import json
import threading
from typing import Dict, Any, Optional, Callable

from .process_utils import is_any_exe_running_in_folder, _internal_log, get_default_appdata_dir

'''
    pt_body = "".join(lines[224:555])
    pt_footer = '''
PLAYTIME_MGR = PlaytimeManager()
'''
    with open(os.path.join(pkg_dir, "playtime.py"), "w", encoding="utf-8") as f:
        f.write(pt_header + "\n" + pt_body + "\n" + pt_footer)

    # 3. achievements.py (lines 556 to 1097)
    ach_header = '''# -*- coding: utf-8 -*-
"""
Core Cloud Save - Achievements Engine
"""
import os
import sys
import time
import json
import re
import glob
import threading
from typing import List, Dict, Any, Optional, Tuple

from core.steam_client import steam_direct_request
from core.scanner import extract_local_steam_appid
from .process_utils import _internal_log, get_default_appdata_dir

'''
    ach_body = "".join(lines[555:1097])
    ach_footer = '''
ACHIEVEMENT_MGR = AchievementManager()
'''
    with open(os.path.join(pkg_dir, "achievements.py"), "w", encoding="utf-8") as f:
        f.write(ach_header + "\n" + ach_body + "\n" + ach_footer)

    # 4. vault.py & gdrive_sync.py (lines 1098 to end)
    vg_header = '''# -*- coding: utf-8 -*-
"""
Core Cloud Save - Vault & Google Drive Sync
"""
import os
import sys
import time
from typing import Optional, Callable, Dict, Any, List, Tuple

from vault_manager import ConguSaveVault
from cloud_sync import CloudSyncManager
from .process_utils import (
    get_default_appdata_dir, _internal_log, _DEFAULT_APP_DIR,
    _CONFIG_GETTER, _CUSTOM_GAMES_GETTER, _GAMES_JSON_PATH_GETTER,
    _GAMES_GETTER, _CONTROLLER_ENGINE, _LOG_FN
)
from .playtime import PLAYTIME_MGR
from .achievements import ACHIEVEMENT_MGR

'''
    vg_body = "".join(lines[1097:])
    with open(os.path.join(pkg_dir, "gdrive_sync.py"), "w", encoding="utf-8") as f:
        f.write(vg_header + "\n" + vg_body)

    # 5. __init__.py
    init_content = '''# -*- coding: utf-8 -*-
"""
Core Package: cloud_save
"""
from .process_utils import (
    PROCESSENTRY32W,
    EXCLUDED_HELPER_EXES,
    is_any_exe_running_in_folder,
    _internal_log,
    get_default_appdata_dir,
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
    configure_cloud_save_system,
    handle_game_exit_hook,
    register_exit_hook,
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
'''
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_content)

    final_dir = os.path.join(CORE_DIR, "cloud_save")
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.rename(pkg_dir, final_dir)
    print("Done converting core/cloud_save!")


if __name__ == "__main__":
    step2_scanner()
    step3_downloader()
    step4_backup_rollback()
    step5_installer_pipeline()
    step6_cloud_save()
    print("All 6 packages converted successfully!")
