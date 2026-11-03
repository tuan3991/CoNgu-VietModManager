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
import tempfile
import threading
import urllib.request
import urllib.parse
import http.cookiejar
from typing import Optional, Callable, Dict, Any, List

from core.config_manager import APPDATA_DIR
from torrent_downloader import TorrentDownloader, TorrentDownloadManager, BEST_PUBLIC_TRACKERS
from hydra_source_manager import HydraSourceManager, DEFAULT_HYDRA_SOURCES


_replace_locks: Dict[str, threading.Lock] = {}
_replace_locks_guard = threading.Lock()


def _replace_lock_for(dest_path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(dest_path))
    with _replace_locks_guard:
        lock = _replace_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _replace_locks[key] = lock
        return lock


def download_file_with_progress(
    url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[int, int, int, float], None]] = None,
    timeout: float = 15.0,
    cancel_check: Optional[Callable[[], bool]] = None,
    validate_download: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Download file from HTTP/HTTPS URL or Google Drive with progress tracking.
    Handles Google Drive large file confirmation tokens automatically.
    Includes connection and read timeout protection (prevents hanging indefinitely).

    :param url: URL nguồn tải (HTTP/HTTPS/Google Drive share URL).
    :param dest_path: Đường dẫn lưu file trên ổ cứng.
    :param progress_callback: Callback(downloaded_bytes, total_bytes, percent, speed_kb_s).
    :param timeout: Giới hạn thời gian kết nối và đọc socket (mặc định 15s).
    :param cancel_check: Hàm kiểm tra xem người dùng có yêu cầu hủy tải hay không.
    :param validate_download: Kiểm tra file tạm, ném lỗi nếu không hợp lệ trước khi thay đích.
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
    resp = opener.open(req, timeout=timeout)

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
            resp = opener.open(req2, timeout=timeout)

    total_size = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 65536
    start_time = time.time()

    # File tạm cùng ổ với file đích: tên unique theo mỗi job để không va chạm
    # khi hai request cùng tải về một cache archive.
    temp_dir = dest_dir or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".congu-download-", suffix=".tmp", dir=temp_dir)

    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("Tiến trình tải xuống đã bị hủy.")

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

        # Content-Length là cam kết của response; thiếu byte thì giữ file cũ.
        if total_size > 0 and downloaded != total_size:
            raise IOError(f"Tải không đầy đủ: nhận {downloaded} / {total_size} byte.")

        if validate_download is not None:
            validate_download(tmp_path)

        # os.replace thay thế nguyên tử file cùng filesystem, không xóa đích trước.
        # Khóa theo đích: Windows từ chối replace khi hai job cùng thay một file.
        with _replace_lock_for(dest_path):
            os.replace(tmp_path, dest_path)
        return True

    except Exception:
        # Tự động dọn tệp tạm không hoàn chỉnh khi lỗi/hủy, không tác động tệp đích.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise
    finally:
        try:
            resp.close()
        except Exception:
            pass


