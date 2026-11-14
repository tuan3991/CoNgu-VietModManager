# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Cloud Save, Achievements & Playtime Session Module
-----------------------------------------------------------------------------
Quản lý hợp nhất:
1. PlaytimeManager: Đếm giờ chơi thời gian thực, lưu nhịp tim 60s, Portable Sync (.congu_playtime.json).
2. AchievementManager: Đọc thành tựu offline từ mọi Steam Emulator (Goldberg, RUNE, CODEX, TENOKE, OnlineFix...),
   cào dữ liệu Steam Community SSR / Store API (vượt chặn DPI) và hàng đợi thông báo mở khóa (Toast Notification).
3. ConguSaveVault: Quản lý Hồ Sơ Di Động Hợp Nhất (.congu_save) mang save sang mọi PC khác nhau.
4. CloudSyncManager: Đồng bộ Google Drive OAuth2 PKCE 3 chiều tự động sau khi tắt game.
5. handle_game_exit_hook: Post-Exit Hook kết nối vòng đời đóng game.
"""

import os
import sys
import time
import json
import re
import glob
import ctypes
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Callable

# Win32 Process Enumeration Definitions
if sys.platform == "win32":
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
else:
    PROCESSENTRY32W = None
    kernel32 = None
    INVALID_HANDLE_VALUE = -1

# Các file thực thi phụ trợ không tính là game đang chạy
EXCLUDED_HELPER_EXES = {
    "unitycrashhandler64.exe",
    "unitycrashhandler32.exe",
    "crashreportclient.exe",
    "crashreportclienteditor.exe",
    "unins000.exe",
    "unins001.exe",
    "uninstall.exe",
    "dxwebsetup.exe",
    "vcredist_x64.exe",
    "vcredist_x86.exe",
    "vc_redist.x64.exe",
    "vc_redist.x86.exe",
    "cmd.exe",
    "powershell.exe",
    "conhost.exe"
}

# Imports from sibling modules
from core.steam_client import steam_direct_request
from core.scanner import extract_local_steam_appid
from vault_manager import ConguSaveVault
from cloud_sync import CloudSyncManager, DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET

# Default directories
_DEFAULT_APPDATA = os.path.join(os.environ.get("APPDATA", os.getcwd()), "VietModHub")
_DEFAULT_APP_DIR = os.getcwd()


def get_default_appdata_dir() -> str:
    """Trả về thư mục AppData chuẩn của Cổ Ngữ (%APPDATA%/VietModHub)."""
    d = os.path.join(os.environ.get("APPDATA", os.getcwd()), "VietModHub")
    os.makedirs(d, exist_ok=True)
    return d


import core.config_manager as cm

# Global hooks & provider callbacks
_HOOK_LOCK = threading.RLock()
_CUSTOM_EXIT_HOOKS: List[Callable[[str, str], None]] = []
_CONFIG_GETTER: Optional[Callable[[], dict]] = cm.load_user_config
_CUSTOM_GAMES_GETTER: Optional[Callable[[], list]] = cm.load_custom_games
_GAMES_JSON_PATH_GETTER: Optional[Callable[[], str]] = cm.get_active_games_json_path
_GAMES_GETTER: Optional[Callable[[], list]] = cm.get_games
_LOG_STARTUP_FN: Optional[Callable[[str], None]] = None
_CONTROLLER_ENGINE_REF = None


def register_exit_hook(callback_fn: Callable[[str, str], None]):
    """Đăng ký hàm lắng nghe sự kiện sau khi game đóng (Post-Exit Hook)."""
    with _HOOK_LOCK:
        if callback_fn not in _CUSTOM_EXIT_HOOKS:
            _CUSTOM_EXIT_HOOKS.append(callback_fn)


def configure_cloud_save_system(
    config_getter: Optional[Callable[[], dict]] = None,
    custom_games_getter: Optional[Callable[[], list]] = None,
    games_json_path_getter: Optional[Callable[[], str]] = None,
    games_getter: Optional[Callable[[], list]] = None,
    controller_engine=None,
    log_fn: Optional[Callable[[str], None]] = None
):
    """Cung cấp các hàm Callback hệ thống để module hoạt động độc lập và đồng bộ."""
    global _CONFIG_GETTER, _CUSTOM_GAMES_GETTER, _GAMES_JSON_PATH_GETTER, _GAMES_GETTER, _CONTROLLER_ENGINE_REF, _LOG_STARTUP_FN
    if config_getter is not None:
        _CONFIG_GETTER = config_getter
    if custom_games_getter is not None:
        _CUSTOM_GAMES_GETTER = custom_games_getter
    if games_json_path_getter is not None:
        _GAMES_JSON_PATH_GETTER = games_json_path_getter
    if games_getter is not None:
        _GAMES_GETTER = games_getter
    if controller_engine is not None:
        _CONTROLLER_ENGINE_REF = controller_engine
    if log_fn is not None:
        _LOG_STARTUP_FN = log_fn


def _internal_log(msg: str):
    if _LOG_STARTUP_FN:
        try:
            _LOG_STARTUP_FN(msg)
            return
        except Exception:
            pass
    print(msg)


def is_any_exe_running_in_folder(game_dir: str) -> bool:
    """
    Kiểm tra xem có bất kỳ file .exe nào nằm trong thư mục `game_dir` đang chạy không.
    Giải quyết triệt để trường hợp Launcher gọi tiến trình con (-Win64-Shipping.exe) rồi tự tắt.
    Tự động bỏ qua các tiến trình phụ trợ (Crash Reporter, Trình gỡ cài đặt, DirectX Setup).
    Đặc biệt hỗ trợ nhận diện cả TIẾN TRÌNH CHẠY QUYỀN ADMINISTRATOR (Elevated Process)
    khi OpenProcess bị từ chối truy cập (Access Denied / NULL handle).
    """
    if not game_dir or not os.path.isdir(game_dir) or sys.platform != "win32" or not kernel32:
        return False

    target_root = os.path.normcase(os.path.realpath(game_dir))
    if not target_root.endswith(os.sep):
        target_root += os.sep

    # Thu thập danh sách tên các file .exe có trong thư mục game để đối chiếu dự phòng
    folder_exes = set()
    try:
        for f in os.listdir(game_dir):
            if f.lower().endswith(".exe") and f.lower() not in EXCLUDED_HELPER_EXES:
                folder_exes.add(f.lower())
    except Exception:
        pass

    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not h_snap or h_snap == INVALID_HANDLE_VALUE or h_snap == -1:
        return False

    try:
        pe32 = PROCESSENTRY32W()
        pe32.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(h_snap, ctypes.byref(pe32)):
            return False

        buf_len = wintypes.DWORD(1024)
        path_buf = ctypes.create_unicode_buffer(1024)

        while True:
            pid = pe32.th32ProcessID
            if pid > 4:
                exe_name = str(pe32.szExeFile).lower()
                h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h_proc:
                    try:
                        buf_len.value = 1024
                        if kernel32.QueryFullProcessImageNameW(h_proc, 0, path_buf, ctypes.byref(buf_len)):
                            raw_val = path_buf.value
                            if raw_val:
                                proc_path = os.path.normcase(os.path.realpath(raw_val))
                                proc_name = os.path.basename(proc_path).lower()
                                if proc_name not in EXCLUDED_HELPER_EXES and proc_path.startswith(target_root):
                                    return True
                    except Exception:
                        pass
                    finally:
                        kernel32.CloseHandle(h_proc)
                else:
                    # h_proc là NULL thường do tiến trình game chạy quyền Elevated (Run As Administrator)
                    # Trong khi Cổ Ngữ chạy quyền user thường. Ta đối chiếu pe32.szExeFile với danh sách .exe của game!
                    if exe_name in folder_exes:
                        return True

            if not kernel32.Process32NextW(h_snap, ctypes.byref(pe32)):
                break
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(h_snap)

    return False


# ==============================================================================
# QUẢN LÝ GIỜ CHƠI (PlaytimeManager)
# ==============================================================================

