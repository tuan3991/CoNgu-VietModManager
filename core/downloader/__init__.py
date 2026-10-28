# -*- coding: utf-8 -*-
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
