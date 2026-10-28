# -*- coding: utf-8 -*-
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
