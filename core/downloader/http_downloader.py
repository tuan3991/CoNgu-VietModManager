# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Unified Downloader Module
---------------------------------------------------
Quản lý tải xuống toàn diện cho ứng dụng:
1. Direct HTTP/HTTPS & Google Drive:
   - Tải file đa luồng, hỗ trợ Google Drive tự vượt trang cảnh báo file lớn (virus scan confirmation token).
   - Báo cáo tiến độ: số byte đã tải, tổng dung lượng, phần trăm (0-100%) và tốc độ tải thực (KB/s).
2. Torrent & Magnet Downloader:
   - Tích hợp aria2c.exe thông qua TorrentDownloadManager.
   - Quản lý tải xuống, tạm dừng, tiếp tục, hủy, và mở thư mục lưu trữ.
3. Hydra Community Sources:
   - Quản lý danh sách nguồn tải game cộng đồng (FitGirl, DODI, GOG, OnlineFix...).
   - Tìm kiếm liên kết tải (Direct Link, Magnet Link, Torrent) theo tên game hoặc Steam AppID.
"""

import os
import sys
import time
import re
import json
import urllib.request
import urllib.parse
import http.cookiejar
from typing import Optional, Callable, Dict, Any, List

from core.config_manager import APPDATA_DIR
from torrent_downloader import TorrentDownloader, TorrentDownloadManager, BEST_PUBLIC_TRACKERS
from hydra_source_manager import HydraSourceManager, DEFAULT_HYDRA_SOURCES


def download_file_with_progress(
    url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[int, int, int, float], None]] = None
) -> bool:
    """
    Download file from HTTP/HTTPS URL or Google Drive with progress tracking.
    Handles Google Drive large file confirmation tokens automatically.

    :param url: URL nguồn tải (HTTP/HTTPS/Google Drive share URL).
    :param dest_path: Đường dẫn lưu file trên ổ cứng.
    :param progress_callback: Callback(downloaded_bytes, total_bytes, percent, speed_kb_s).
    :return: True nếu tải thành công, ngược lại False hoặc ném lỗi.
    """
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    # Convert Google Drive share URL to direct download URL
    gdrive_match = re.search(r'(?:drive\.google\.com/file/d/|drive\.google\.com/uc\?id=|id=)([a-zA-Z0-9_-]{25,})', url)
    if gdrive_match:
        file_id = gdrive_match.group(1)
        url = f"https://drive.google.com/uc?export=download&id={file_id}"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    req = urllib.request.Request(url, headers=headers)
    resp = opener.open(req)

    # Check for Google Drive virus scan confirmation
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        body = resp.read().decode("utf-8", errors="ignore")
        confirm_token = re.search(r'confirm=([0-9A-Za-z_]+)', body)
        if not confirm_token:
            confirm_token = re.search(r'name="confirm"\s+value="([^"]+)"', body)
        if confirm_token:
            token = confirm_token.group(1)
            confirm_url = f"{url}&confirm={token}"
            req2 = urllib.request.Request(confirm_url, headers=headers)
            resp = opener.open(req2)

    total_size = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 65536
    start_time = time.time()

    with open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                percent = int(downloaded * 100 / total_size) if total_size > 0 else 50
                elapsed = time.time() - start_time
                speed_kb = (downloaded / 1024) / elapsed if elapsed > 0 else 0
                progress_callback(downloaded, total_size, percent, speed_kb)

    return True


