# -*- coding: utf-8 -*-
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
