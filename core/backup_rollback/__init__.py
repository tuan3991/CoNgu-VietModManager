# -*- coding: utf-8 -*-
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
