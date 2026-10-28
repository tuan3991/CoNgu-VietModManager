# -*- coding: utf-8 -*-
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
