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
    """
    if not game_dir or not os.path.isdir(game_dir) or sys.platform != "win32" or not kernel32:
        return False

    target_root = os.path.normcase(os.path.realpath(game_dir))
    if not target_root.endswith(os.sep):
        target_root += os.sep

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

class PlaytimeManager:
    """Bộ quản lý khởi chạy game và đếm giờ chơi chuẩn xác theo thời gian thực (Zero-Leak Clean Exit)."""

    def __init__(self, db_path: str = None, on_game_exit_callback=None, appdata_dir: str = None):
        self.appdata_dir = appdata_dir or get_default_appdata_dir()
        os.makedirs(self.appdata_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(self.appdata_dir, "playtime.json")
        self.lock = threading.RLock()
        self.active_games = {}  # {game_id: {"start_ts": float, "last_chk": float, "last_active": float, "game_dir": str}}
        self.on_game_exit_callback = on_game_exit_callback
        self.get_installed_paths = None
        self._data = self._load_db()

    def _load_db(self) -> dict:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[PlaytimeManager] Load DB error: {e}")
        return {}

    def _save_db(self, game_id: str = None, game_dir: str = None):
        with self.lock:
            try:
                tmp_path = self.db_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.db_path)
            except Exception as e:
                print(f"[PlaytimeManager] Save DB error: {e}")

            # Lưu đồng bộ 1 bản Portable ngay trong thư mục game (nếu có quyền ghi)
            if game_id:
                target_dir = game_dir
                if not target_dir or not os.path.isdir(target_dir):
                    try:
                        if _CONFIG_GETTER:
                            cfg = _CONFIG_GETTER()
                            target_dir = cfg.get(f"{game_id}_path")
                    except Exception:
                        pass
                if target_dir and os.path.isdir(target_dir):
                    try:
                        local_file = os.path.join(target_dir, ".congu_playtime.json")
                        with open(local_file, "w", encoding="utf-8") as lf:
                            json.dump(self._data.get(game_id, {}), lf, ensure_ascii=False, indent=2)
                    except OSError:
                        pass

    def is_game_running(self, game_id: str) -> bool:
        with self.lock:
            return game_id in self.active_games

    def get_game_stats(self, game_id: str, game_dir: str = None) -> dict:
        """Lấy thông tin giờ chơi đã định dạng đẹp để gửi lên Frontend (Hỗ trợ Live Playtime khi đang chơi)."""
        with self.lock:
            rec = self._data.get(game_id)
            if not game_dir:
                try:
                    if _CONFIG_GETTER:
                        cfg = _CONFIG_GETTER()
                        game_dir = cfg.get(f"{game_id}_path")
                except Exception:
                    pass

            # Khôi phục / đồng bộ hai chiều từ file portable trong thư mục game (Bảo toàn dữ liệu tuyệt đối)
            if game_dir and os.path.isdir(game_dir):
                local_file = os.path.join(game_dir, ".congu_playtime.json")
                if os.path.exists(local_file):
                    try:
                        with open(local_file, "r", encoding="utf-8") as lf:
                            local_rec = json.load(lf)
                            local_sec = int(local_rec.get("total_seconds", 0))
                            current_sec = int(rec.get("total_seconds", 0)) if rec else 0
                            if local_sec > current_sec:
                                rec = local_rec
                                self._data[game_id] = rec
                                self._save_db(game_id, game_dir)
                            elif current_sec > local_sec:
                                # Đồng bộ ngược vào file portable nếu máy có giờ chơi mới hơn
                                try:
                                    with open(local_file, "w", encoding="utf-8") as wlf:
                                        json.dump(rec, wlf, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                elif rec and int(rec.get("total_seconds", 0)) > 0:
                    try:
                        with open(local_file, "w", encoding="utf-8") as wlf:
                            json.dump(rec, wlf, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

            rec = rec or {"total_seconds": 0, "last_played_ts": None, "sessions_count": 0}
            total_sec = int(rec.get("total_seconds", 0))

            # Tự nhận diện cả khi người dùng mở game bằng Shortcut ngoài Desktop
            is_running = game_id in self.active_games
            if not is_running and game_dir and os.path.isdir(game_dir):
                if is_any_exe_running_in_folder(game_dir):
                    self.start_tracking(game_id, game_dir)
                    is_running = True

            # Tính Live Playtime trực tiếp nếu game đang chạy
            if is_running:
                active_info = self.active_games.get(game_id)
                if active_info:
                    start_session_ts = active_info.get("start_ts", time.time())
                    live_seconds = int(time.time() - active_info.get("last_chk", start_session_ts))
                    total_sec += max(0, live_seconds)

            # Định dạng chuỗi hiển thị thông minh giống Steam
            if total_sec == 0:
                formatted_time = "Chưa chơi"
            elif total_sec < 60:
                formatted_time = f"{total_sec} giây" if is_running else "< 1 phút"
            elif total_sec < 3600:
                formatted_time = f"{max(1, total_sec // 60)} phút"
            else:
                formatted_time = f"{round(total_sec / 3600, 1)} giờ"

            last_ts = rec.get("last_played_ts")
            if is_running:
                last_played_str = "Đang chơi"
            elif not last_ts:
                last_played_str = "Chưa từng mở"
            else:
                try:
                    diff_days = (datetime.now().date() - datetime.fromtimestamp(last_ts).date()).days
                    if diff_days == 0:
                        last_played_str = "Hôm nay"
                    elif diff_days == 1:
                        last_played_str = "Hôm qua"
                    else:
                        last_played_str = datetime.fromtimestamp(last_ts).strftime("%d/%m/%Y")
                except Exception:
                    last_played_str = "Vừa xong"

            return {
                "game_id": game_id,
                "is_running": is_running,
                "total_seconds": total_sec,
                "formatted_time": formatted_time,
                "last_played_str": last_played_str,
                "sessions_count": rec.get("sessions_count", 0)
            }

    def start_background_scanner(self, get_installed_paths_callback):
        """Khởi động luồng quét ngầm nhận diện game mở từ Shortcut Desktop / Steam."""
        if hasattr(self, '_scanner_running') and self._scanner_running:
            return
        self._scanner_running = True
        self.get_installed_paths = get_installed_paths_callback

        def _scan_loop():
            # Chờ 4s đầu để app khởi động mượt mà
            time.sleep(4)
            while self._scanner_running:
                try:
                    time.sleep(5)
                    if not self.get_installed_paths:
                        continue
                    installed_paths = self.get_installed_paths()
                    if not installed_paths:
                        continue
                    for gid, gpath in installed_paths.items():
                        if not gpath or not os.path.isdir(gpath):
                            continue
                        with self.lock:
                            is_active = gid in self.active_games
                        if not is_active:
                            if is_any_exe_running_in_folder(gpath):
                                _internal_log(f"[PlaytimeTracker] Tự động phát hiện game '{gid}' mở từ Shortcut Desktop/Steam tại '{gpath}'!")
                                self.start_tracking(gid, gpath)
                except Exception:
                    pass

        t = threading.Thread(target=_scan_loop, daemon=True)
        t.start()

    def start_tracking(self, game_id: str, game_dir: str):
        """Bắt đầu luồng theo dõi đếm giờ tự động (Daemon Watcher)."""
        with self.lock:
            if game_id in self.active_games:
                return
            now = time.time()
            self.active_games[game_id] = {
                "start_ts": now,
                "last_chk": now,
                "last_active": now,
                "game_dir": game_dir
            }
            rec = self._data.setdefault(game_id, {
                "total_seconds": 0, "last_played_ts": int(now), "sessions_count": 0, "daily_log": {}
            })
            rec["last_played_ts"] = int(now)
            rec["sessions_count"] = rec.get("sessions_count", 0) + 1
            self._save_db(game_id, game_dir)

        t = threading.Thread(
            target=self._monitor_loop,
            args=(game_id, game_dir),
            daemon=True
        )
        t.start()
        _internal_log(f"[PlaytimeTracker] Đã kích hoạt luồng theo dõi cho '{game_id}'")

    def _monitor_loop(self, game_id: str, game_dir: str):
        """Vòng lặp kiểm tra mỗi 3s và lưu checkpoint nhịp tim mỗi 60s."""
        time.sleep(3)
        start_ts = time.time()
        last_checkpoint = start_ts
        last_active = start_ts
        session_saved_sec = 0
        unseen_streak = 0

        try:
            while True:
                time.sleep(3)
                now = time.time()

                if is_any_exe_running_in_folder(game_dir):
                    unseen_streak = 0
                    last_active = now

                    # Quét phát hiện thành tựu thời gian thực (Cơ chế Hydra Launcher / Achievement Watcher)
                    try:
                        if ACHIEVEMENT_MGR:
                            ACHIEVEMENT_MGR.check_game_live_achievements(game_id, game_dir)
                    except Exception:
                        pass

                    elapsed_delta = int(now - last_checkpoint)
                    # Lưu nhịp tim mỗi 60 giây chống mất dữ liệu khi mất điện hoặc crash
                    if elapsed_delta >= 60:
                        self._add_seconds(game_id, game_dir, elapsed_delta)
                        session_saved_sec += elapsed_delta
                        last_checkpoint = now
                        with self.lock:
                            if game_id in self.active_games:
                                self.active_games[game_id]["last_chk"] = now
                                self.active_games[game_id]["last_active"] = now
                else:
                    # Chờ xác nhận 2 nhịp liên tiếp (~6s) phòng lúc Launcher đang chuyển sang Shipping.exe
                    unseen_streak += 1
                    if unseen_streak >= 2:
                        session_elapsed = int(max(0, last_active - start_ts))
                        remaining_delta = max(0, session_elapsed - session_saved_sec)
                        if remaining_delta > 0:
                            self._add_seconds(game_id, game_dir, remaining_delta)
                        break
        except Exception as e:
            print(f"[PlaytimeTracker] Monitor loop error: {e}")
        finally:
            with self.lock:
                self.active_games.pop(game_id, None)

        _internal_log(f"[PlaytimeTracker] Phiên chơi của '{game_id}' đã kết thúc.")
        if self.on_game_exit_callback:
            try:
                self.on_game_exit_callback(game_id, game_dir)
            except Exception as e:
                print(f"[PlaytimeTracker] Post-exit hook error: {e}")

    def _add_seconds(self, game_id: str, game_dir: str, seconds: int):
        if seconds <= 0:
            return
        with self.lock:
            today_key = datetime.now().strftime("%Y-%m-%d")
            now_ts = int(time.time())
            rec = self._data.setdefault(game_id, {
                "total_seconds": 0, "last_played_ts": now_ts, "sessions_count": 1, "daily_log": {}
            })
            rec["total_seconds"] = int(rec.get("total_seconds", 0)) + seconds
            rec["last_played_ts"] = now_ts
            daily = rec.setdefault("daily_log", {})
            daily[today_key] = int(daily.get(today_key, 0)) + seconds
            self._save_db(game_id, game_dir)

    def flush_all_active(self):
        """Lưu nốt số giây đang chơi dở trước khi CỔ NGỮ đóng hẳn (Zero-Leak Clean Exit)."""
        with self.lock:
            now = time.time()
            for gid, info in list(self.active_games.items()):
                last_chk = info.get("last_chk", info.get("start_ts", now))
                delta = int(now - last_chk)
                if delta > 0:
                    gdir = info.get("game_dir")
                    self._add_seconds(gid, gdir, delta)
                    info["last_chk"] = now

    def get_all_stats(self) -> dict:
        """Trả về toàn bộ thống kê giờ chơi và trạng thái đang chạy cho tất cả game."""
        with self.lock:
            result = {}
            for gid, rec in self._data.items():
                is_running = gid in self.active_games
                total_sec = int(rec.get("total_seconds", 0))
                if is_running:
                    active_info = self.active_games.get(gid)
                    if active_info:
                        start_session_ts = active_info.get("start_ts", time.time())
                        live_seconds = int(time.time() - active_info.get("last_chk", start_session_ts))
                        total_sec += max(0, live_seconds)

                if total_sec == 0:
                    formatted_time = "Chưa chơi"
                elif total_sec < 60:
                    formatted_time = f"{total_sec} giây" if is_running else "< 1 phút"
                elif total_sec < 3600:
                    formatted_time = f"{max(1, total_sec // 60)} phút"
                else:
                    formatted_time = f"{round(total_sec / 3600, 1)} giờ"

                result[gid] = {
                    "game_id": gid,
                    "is_running": is_running,
                    "total_seconds": total_sec,
                    "formatted_time": formatted_time,
                    "last_played_str": "Đang chơi" if is_running else (rec.get("last_played_str") or "Gần đây"),
                    "sessions_count": rec.get("sessions_count", 0)
                }
            return result


# ==============================================================================
# QUẢN LÝ THÀNH TỰU (AchievementManager)
# ==============================================================================

class AchievementManager:
    """
    Bộ quản lý phát hiện, đọc tiến độ và đồng bộ Thành tựu cho game lẻ
    theo chuẩn cơ chế không can thiệp RAM của Hydra Launcher & Achievement Watcher.
    Hỗ trợ tự động nhận diện Emulator: Goldberg, GSE, RUNE, CODEX, TENOKE, OnlineFix, FLT, ALI213, SmartSteamEmu.
    """

    def __init__(self, steam_api_key: str = "", appdata_dir: str = None):
        self.appdata_dir = appdata_dir or get_default_appdata_dir()
        self.schema_dir = os.path.join(self.appdata_dir, "achievements_schema")
        self.progress_file = os.path.join(self.appdata_dir, "achievements_progress.json")
        os.makedirs(self.schema_dir, exist_ok=True)
        self.steam_api_key = steam_api_key
        self.lock = threading.RLock()
        self.unlocked_cache = {}  # {appid_or_gid: {"ACH_ID": ts, ...}}
        self.newly_unlocked_queue = []  # [{"game_id": ..., "id": ..., "title": ..., "description": ..., "icon": ...}]
        self._progress_data = self._load_progress()

    def _load_progress(self) -> dict:
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_progress(self):
        with self.lock:
            try:
                tmp = self.progress_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._progress_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.progress_file)
            except Exception:
                pass

    def _resolve_appid_from_metadata(self, game_id: str) -> str:
        """Tìm steam_appid của game từ custom_games.json hoặc games.json."""
        if not game_id:
            return ""
        # 1. Kiểm tra custom_games.json
        try:
            if _CUSTOM_GAMES_GETTER:
                for cg in _CUSTOM_GAMES_GETTER():
                    if cg.get("id") == game_id:
                        aid = str(cg.get("steam_appid") or "").strip()
                        if aid:
                            return aid
        except Exception:
            pass
        # 2. Kiểm tra games.json
        try:
            p = _GAMES_JSON_PATH_GETTER() if _GAMES_JSON_PATH_GETTER else "games.json"
            if p and os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for g in json.load(f):
                        if g.get("id") == game_id:
                            return str(g.get("steam_appid") or "").strip()
        except Exception:
            pass
        return ""

    def _get_candidate_save_files(self, appid: str, game_dir: str = "") -> List[Tuple[str, str]]:
        """Trả về danh sách các đường dẫn file lưu thành tựu có thể tồn tại của mọi Steam Emulator."""
        if not appid and not game_dir:
            return []

        candidates = []
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        public_doc = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents")
        user_profile = os.environ.get("USERPROFILE", "")
        documents = os.path.join(user_profile, "Documents")

        if appid:
            s_appid = str(appid)
            candidates.extend([
                # 1. Goldberg / GSE Saves (Định dạng JSON)
                ("goldberg_json", os.path.join(appdata, "Goldberg SteamEmu Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(appdata, "GSE Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(localappdata, "Goldberg SteamEmu Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(localappdata, "GSE Saves", s_appid, "achievements.json")),
                # 2. RUNE / CODEX / FLT / OnlineFix / SmartSteamEmu (Định dạng INI)
                ("ini", os.path.join(public_doc, "Steam", "RUNE", s_appid, "achievements.ini")),
                ("ini", os.path.join(public_doc, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(appdata, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(public_doc, "OnlineFix", s_appid, "Stats", "Achievements.ini")),
                ("ini", os.path.join(appdata, "FLT", s_appid, "stats", "achievements.ini")),
                ("ini", os.path.join(appdata, "SmartSteamEmu", s_appid, "achievements.ini")),
                ("ini", os.path.join(appdata, "SmartSteamEmu", s_appid, "stats", "achievements.ini")),
                ("ini", os.path.join(documents, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(documents, "Steam", "RUNE", s_appid, "achievements.ini")),
                ("ini", os.path.join(documents, "OnlineFix", s_appid, "Stats", "Achievements.ini")),
            ])

        # 3. Các file lưu ngay bên trong thư mục cài đặt game (TENOKE, ALI213, OnlineFix portable, Goldberg local)
        if game_dir and os.path.isdir(game_dir):
            for pattern, fmt in [
                ("**/steam_settings/achievements.json", "goldberg_local_schema"),
                ("**/SteamData/user_stats.ini", "tenoke_ini"),
                ("**/Profile/Stats/Achievements.ini", "ini"),
                ("**/OnlineFix/**/Achievements.ini", "ini"),
                ("**/achievements.ini", "ini"),
                ("**/achievements.json", "goldberg_json"),
            ]:
                try:
                    for found_path in glob.glob(os.path.join(game_dir, pattern), recursive=True):
                        item = (fmt, found_path)
                        if fmt != "goldberg_local_schema" and item not in candidates:
                            candidates.append(item)
                except Exception:
                    pass

        return candidates

    def scan_unlocked_achievements(self, appid: str, game_dir: str = "") -> Dict[str, int]:
        """
        Quét toàn bộ các nguồn emulator và trả về dict: { "ACH_ID": unlock_timestamp }
        """
        unlocked = {}
        for fmt, file_path in self._get_candidate_save_files(str(appid or ""), game_dir):
            if not os.path.isfile(file_path):
                continue
            try:
                mtime_fallback = int(os.path.getmtime(file_path))
                if fmt == "goldberg_json":
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for ach_id, info in data.items():
                            if isinstance(info, dict):
                                if info.get("earned") is True or info.get("unlocked") is True:
                                    ts = int(info.get("earned_time") or info.get("time") or mtime_fallback)
                                    unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)
                            elif isinstance(info, (int, float)) and info > 0:
                                unlocked[ach_id] = min(unlocked.get(ach_id, int(info)), int(info))
                            elif info is True:
                                unlocked[ach_id] = min(unlocked.get(ach_id, mtime_fallback), mtime_fallback)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                ach_id = item.get("name") or item.get("id")
                                if ach_id and (item.get("earned") is True or item.get("unlocked") is True):
                                    ts = int(item.get("earned_time") or item.get("time") or mtime_fallback)
                                    unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)

                elif fmt == "tenoke_ini":
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    for match in re.finditer(r'"([^"]+)"\s*=\s*\{[^}]*unlocked\s*=\s*true(?:[^}]*time\s*=\s*(\d+))?', text, re.I):
                        ach_id = match.group(1)
                        ts = int(match.group(2)) if match.group(2) else mtime_fallback
                        unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)

                elif fmt == "ini":
                    import configparser
                    cp = configparser.ConfigParser(strict=False)
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        cp.read_file(f)
                    for section in cp.sections():
                        sec_lower = section.lower()
                        if sec_lower in ("steamachievements", "achievements", "stats"):
                            for k, v in cp.items(section):
                                if v.strip().lower() in ("1", "true") and not k.isdigit():
                                    unlocked[k] = min(unlocked.get(k, mtime_fallback), mtime_fallback)
                            continue
                        achieved_val = (
                            cp.get(section, "Achieved", fallback=None)
                            or cp.get(section, "achieved", fallback=None)
                            or cp.get(section, "State", fallback="0")
                        )
                        if str(achieved_val).strip().lower() in ("1", "true"):
                            ts_str = (
                                cp.get(section, "UnlockTime", fallback=None)
                                or cp.get(section, "Timestamp", fallback=None)
                                or cp.get(section, "Time", fallback="0")
                            )
                            ts = int(ts_str) if str(ts_str).isdigit() and int(ts_str) > 0 else mtime_fallback
                            unlocked[section] = min(unlocked.get(section, ts), ts)
            except Exception:
                continue

        return unlocked

    def get_or_fetch_schema(self, appid: str, game_dir: str = "", game_id: str = "") -> List[Dict[str, Any]]:
        """Lấy danh sách thành tựu gốc (Tên, Mô tả, Icon) từ Cache, thư mục game hoặc Steam Store API."""
        if not appid and not game_id:
            return []

        # 0. Kiểm tra cache theo appid hoặc game_id (chỉ chấp nhận nếu có cách thực hiện / description)
        for ckey in [appid, game_id]:
            if not ckey:
                continue
            cache_file = os.path.join(self.schema_dir, f"{ckey}.json")
            if os.path.isfile(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data and isinstance(data, list) and any(bool(item.get("description")) for item in data):
                            return data
                except Exception:
                    pass

        schema_list = []

        # 1. Nguồn 1: Quét trực tiếp file steam_settings/achievements.json có sẵn trong thư mục game lẻ (Offline 0s)
        if game_dir and os.path.isdir(game_dir):
            for pattern in ["**/steam_settings/achievements.json", "**/achievements.json"]:
                for path in glob.glob(os.path.join(game_dir, pattern), recursive=True):
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            raw = json.load(f)
                        if isinstance(raw, list):
                            for item in raw:
                                if not isinstance(item, dict):
                                    continue
                                ach_id = item.get("name") or item.get("id")
                                if not ach_id:
                                    continue
                                disp_name = item.get("displayName", item.get("name", ""))
                                if isinstance(disp_name, dict):
                                    disp_name = disp_name.get("english", next(iter(disp_name.values()), ""))
                                desc = item.get("description", "")
                                if isinstance(desc, dict):
                                    desc = desc.get("english", next(iter(desc.values()), ""))

                                icon_val = item.get("icon", "")
                                icongray_val = item.get("icongray", item.get("icon_gray", ""))
                                if icon_val and not icon_val.startswith("http") and os.path.exists(os.path.join(os.path.dirname(path), icon_val)):
                                    icon_val = os.path.abspath(os.path.join(os.path.dirname(path), icon_val))
                                if icongray_val and not icongray_val.startswith("http") and os.path.exists(os.path.join(os.path.dirname(path), icongray_val)):
                                    icongray_val = os.path.abspath(os.path.join(os.path.dirname(path), icongray_val))

                                schema_list.append({
                                    "id": ach_id,
                                    "title": disp_name or ach_id,
                                    "description": desc or "",
                                    "icon": icon_val,
                                    "icongray": icongray_val,
                                    "hidden": bool(item.get("hidden", 0)),
                                    "group": item.get("group", "")
                                })
                            if schema_list:
                                break
                    except Exception:
                        pass
                if schema_list:
                    break

        pct_map = {}
        if appid and str(appid).isdigit():
            try:
                pct_url = f"https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
                raw_pct = steam_direct_request(pct_url, timeout=4.0)
                if raw_pct:
                    pct_data = json.loads(raw_pct.decode("utf-8", "ignore"))
                    for p in pct_data.get("achievementpercentages", {}).get("achievements", []):
                        pct_map[p["name"].lower()] = round(float(p.get("percent", 0)), 1)
            except Exception:
                pass

        # 2. Nguồn 2: Steam Community SSR Data (Toàn bộ 100% Thành tựu + DLC Packs)
        if not schema_list and appid and str(appid).isdigit():
            try:
                comm_url = f"https://steamcommunity.com/achievements/{appid}"
                raw_comm = steam_direct_request(comm_url, timeout=5.0)
                if raw_comm:
                    html_text = raw_comm.decode("utf-8", "ignore")
                    m = re.search(r'<script[^>]*id=["\']valve-ssr-data["\'][^>]*>(.*?)</script>', html_text, re.DOTALL)
                    if m:
                        root_data = json.loads(m.group(1).strip())
                        query_data_raw = root_data.get("renderContext", {}).get("queryData", {})
                        if isinstance(query_data_raw, str):
                            query_data = json.loads(query_data_raw)
                        else:
                            query_data = query_data_raw or {}

                        for q in query_data.get("queries", []):
                            data_node = q.get("state", {}).get("data")
                            if isinstance(data_node, dict) and "groups" in data_node:
                                for g in data_node.get("groups", []):
                                    group_title = g.get("name") or ""
                                    for a in g.get("achievements", []):
                                        ach_id = a.get("api_name")
                                        if not ach_id:
                                            continue
                                        disp_name = a.get("name") or ach_id
                                        desc = a.get("description") or ""
                                        icon_url = a.get("icon_achieved") or ""
                                        icongray_url = a.get("icon_unachieved") or icon_url
                                        is_hidden = bool(a.get("hidden", False))
                                        schema_list.append({
                                            "id": ach_id,
                                            "title": disp_name,
                                            "description": desc,
                                            "icon": icon_url,
                                            "icongray": icongray_url,
                                            "hidden": is_hidden,
                                            "group": group_title,
                                            "global_percent": pct_map.get(ach_id.lower(), None)
                                        })
            except Exception as e:
                print(f"[AchievementManager] Steam Community SSR fetch error: {e}")

        # 3. Nguồn 3: Nếu có Steam Web API Key
        if not schema_list and self.steam_api_key and appid and str(appid).isdigit():
            try:
                url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={self.steam_api_key}&appid={appid}&l=english"
                raw_s = steam_direct_request(url, timeout=4.0)
                if raw_s:
                    data = json.loads(raw_s.decode("utf-8", "ignore"))
                    raw_ach = data.get("game", {}).get("availableGameStats", {}).get("achievements", [])
                    for a in raw_ach:
                        ach_id = a.get("name")
                        schema_list.append({
                            "id": ach_id,
                            "title": a.get("displayName", ach_id),
                            "description": a.get("description", ""),
                            "icon": a.get("icon", ""),
                            "icongray": a.get("icongray", ""),
                            "hidden": bool(a.get("hidden", 0)),
                            "global_percent": pct_map.get(str(ach_id).lower(), None)
                        })
            except Exception:
                pass

        # 4. Nguồn 4: Fallback qua Steam Store API appdetails
        if not schema_list and appid and str(appid).isdigit():
            try:
                details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=achievements"
                raw_det = steam_direct_request(details_url, timeout=4.0)
                if raw_det:
                    det = json.loads(raw_det.decode("utf-8", "ignore"))
                    ach_data = det.get(str(appid), {}).get("data", {}).get("achievements", {})
                    highlighted = ach_data.get("highlighted", [])
                    for a in highlighted:
                        ach_name = a.get("name") or a.get("localized_name")
                        icon_url = a.get("path")
                        if not icon_url and a.get("icon"):
                            icon_url = f"https://shared.akamai.steamstatic.com/community_assets/images/apps/{appid}/{a['icon']}"
                        schema_list.append({
                            "id": a.get("name", ach_name),
                            "title": a.get("localized_name") or ach_name,
                            "description": "",
                            "icon": icon_url or "",
                            "icongray": "",
                            "hidden": bool(a.get("hidden", 0)),
                            "global_percent": pct_map.get(str(a.get("name", ach_name)).lower(), None)
                        })
            except Exception as e:
                print(f"[AchievementManager] Store API fetch error: {e}")

        # Gắn thêm tỷ lệ global_percent nếu chưa có
        for s in schema_list:
            if s.get("global_percent") is None:
                s["global_percent"] = pct_map.get(str(s.get("id", "")).lower(), None)

        # Lưu cache nếu lấy được schema có cách thực hiện
        if schema_list:
            save_key = appid or game_id
            cache_file = os.path.join(self.schema_dir, f"{save_key}.json")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(schema_list, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

        return schema_list

    def get_game_achievements_view(self, appid: str = "", game_dir: str = "", game_id: str = "") -> dict:
        """Hàm trả dữ liệu hoàn chỉnh cho Frontend static/index.html hiển thị."""
        # 1. Tự động tìm game_dir từ user_config hoặc custom_games.json
        if not game_dir and game_id:
            if _CONFIG_GETTER:
                cfg = _CONFIG_GETTER()
                game_dir = cfg.get(f"{game_id}_path", "")
            if not game_dir and _CUSTOM_GAMES_GETTER:
                try:
                    for cg in _CUSTOM_GAMES_GETTER():
                        if cg.get("id") == game_id:
                            game_dir = cg.get("game_root", "")
                            break
                except Exception:
                    pass

        # 2. Tự động xác định effective_appid
        effective_appid = str(appid or "").strip()
        if not effective_appid and game_dir:
            effective_appid = extract_local_steam_appid(game_dir) or ""
        if not effective_appid and game_id:
            effective_appid = self._resolve_appid_from_metadata(game_id)

        schema = self.get_or_fetch_schema(effective_appid, game_dir, game_id)
        unlocked_map = self.scan_unlocked_achievements(effective_appid, game_dir) if (effective_appid or game_dir) else {}

        # Nếu chưa có schema nhưng file save có danh sách mã thành tựu đã mở
        schema_ids = {str(item.get("id", "")).lower(): item for item in schema if item.get("id")}
        for unlocked_id, u_ts in unlocked_map.items():
            if unlocked_id.lower() not in schema_ids:
                clean_title = re.sub(r"[_\-]+", " ", unlocked_id).title()
                schema.append({
                    "id": unlocked_id,
                    "title": clean_title,
                    "description": "Thành tựu đạt được trong khi chơi game",
                    "icon": "",
                    "icongray": "",
                    "hidden": False
                })

        items = []
        unlocked_count = 0
        unlocked_lower = {k.lower(): v for k, v in unlocked_map.items()}

        for ach in schema:
            ach_id = ach.get("id", "")
            unlock_ts = unlocked_lower.get(ach_id.lower())
            is_unlocked = unlock_ts is not None
            if is_unlocked:
                unlocked_count += 1

            unlock_str = None
            if unlock_ts:
                try:
                    unlock_str = datetime.fromtimestamp(unlock_ts).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    unlock_str = "Đã mở khóa"

            items.append({
                "id": ach_id,
                "title": ach.get("title_vi") or ach.get("title") or ach_id,
                "description": ach.get("description_vi") or ach.get("description") or "",
                "icon": ach.get("icon") if is_unlocked else (ach.get("icongray") or ach.get("icon")),
                "unlocked": is_unlocked,
                "unlock_ts": unlock_ts or 0,
                "unlock_time_str": unlock_str,
                "global_percent": ach.get("global_percent", None),
                "hidden": bool(ach.get("hidden", False)),
                "group": ach.get("group", "")
            })

        # Sắp xếp: Thành tựu đã mở khóa lên trước (mới nhất xếp trên cùng)
        items.sort(key=lambda x: (not x["unlocked"], -x["unlock_ts"]))
        total = len(items)
        percent = int(round((unlocked_count / total) * 100)) if total > 0 else 0

        # Cập nhật cache trạng thái
        cache_key = effective_appid or game_id
        if cache_key:
            with self.lock:
                self.unlocked_cache[cache_key] = unlocked_map
                self._progress_data[cache_key] = {
                    "total": total,
                    "unlocked_count": unlocked_count,
                    "percent": percent,
                    "last_updated": int(time.time())
                }
                self._save_progress()

        return {
            "appid": effective_appid,
            "game_id": game_id,
            "total": total,
            "unlocked_count": unlocked_count,
            "percent": percent,
            "achievements": items
        }

    def check_for_new_unlocks(self, game_id: str, appid: str, game_dir: str = "") -> list:
        """Kiểm tra thời gian thực xem có thành tựu nào vừa được mở khóa không."""
        if not appid and not game_dir:
            return []

        effective_appid = str(appid or "").strip()
        if not effective_appid and game_dir:
            effective_appid = extract_local_steam_appid(game_dir) or ""

        cache_key = effective_appid or game_id
        if not cache_key:
            return []

        current_unlocked = self.scan_unlocked_achievements(effective_appid, game_dir)
        if not current_unlocked:
            return []

        new_items = []
        with self.lock:
            prev_unlocked = self.unlocked_cache.get(cache_key)
            if prev_unlocked is None:
                self.unlocked_cache[cache_key] = current_unlocked
                return []

            schema = self.get_or_fetch_schema(effective_appid, game_dir, game_id)
            schema_map = {str(item.get("id", "")).lower(): item for item in schema}

            for ach_id, ts in current_unlocked.items():
                if ach_id.lower() not in {k.lower(): v for k, v in prev_unlocked.items()}:
                    meta = schema_map.get(ach_id.lower(), {})
                    title = meta.get("title_vi") or meta.get("title") or re.sub(r"[_\-]+", " ", ach_id).title()
                    desc = meta.get("description_vi") or meta.get("description") or "Mở khóa khi chơi game"
                    icon = meta.get("icon") or ""

                    item_info = {
                        "game_id": game_id,
                        "appid": effective_appid,
                        "id": ach_id,
                        "title": title,
                        "description": desc,
                        "icon": icon,
                        "unlock_ts": ts
                    }
                    new_items.append(item_info)
                    self.newly_unlocked_queue.append(item_info)
                    _internal_log(f"[AchievementTracker] 🏆 Chúc mừng! Mở khóa thành tựu mới: '{title}' ({ach_id})!")

            self.unlocked_cache[cache_key] = current_unlocked

        return new_items

    def check_game_live_achievements(self, game_id: str, game_dir: str = "") -> list:
        """Tự động phân giải appid và quét thành tựu mới mở khóa trong thời gian thực."""
        appid = ""
        if game_dir and os.path.isdir(game_dir):
            appid = extract_local_steam_appid(game_dir) or ""
        if not appid and game_id:
            if _CONFIG_GETTER:
                cfg = _CONFIG_GETTER()
                g_path = cfg.get(f"{game_id}_path")
                if g_path and os.path.isdir(g_path):
                    appid = extract_local_steam_appid(g_path) or ""
            if not appid:
                appid = self._resolve_appid_from_metadata(game_id)

        return self.check_for_new_unlocks(game_id, appid, game_dir)

    def pop_newly_unlocked(self) -> list:
        """Lấy toàn bộ danh sách thành tựu mới để Frontend hiện Toast thông báo, sau đó xóa hàng đợi."""
        with self.lock:
            items = list(self.newly_unlocked_queue)
            self.newly_unlocked_queue.clear()
            return items


# ==============================================================================
# HỒ SƠ DI ĐỘNG (ConguSaveVault) & POST-EXIT HOOKS
# ==============================================================================

SAVE_VAULT: Optional[ConguSaveVault] = None


def get_vault_instance(app_dir: str = "", appdata_dir: str = "") -> ConguSaveVault:
    """Lấy thể hiện quản lý Hồ Sơ Di Động Hợp Nhất (PlayerProfile.congu_save)."""
    global SAVE_VAULT
    app_d = app_dir or _DEFAULT_APP_DIR
    appdata_d = appdata_dir or get_default_appdata_dir()

    custom_path = None
    if _CONFIG_GETTER:
        try:
            cfg = _CONFIG_GETTER()
            custom_path = cfg.get("custom_vault_path")
        except Exception:
            pass

    if custom_path:
        target = os.path.abspath(custom_path)
    elif os.path.exists(os.path.join(app_d, "PlayerProfile.congu_save")):
        target = os.path.join(app_d, "PlayerProfile.congu_save")
    else:
        target = os.path.join(appdata_d, "PlayerProfile.congu_save")

    if SAVE_VAULT is None or SAVE_VAULT.vault_path != target:
        SAVE_VAULT = ConguSaveVault(target)
    return SAVE_VAULT


def handle_game_exit_hook(game_id: str, game_dir: str):
    """
    Điểm móc nối tự động sau khi thoát game (Post-Exit Hook):
    - Ghi log và đồng bộ trạng thái.
    - Sẵn sàng kích hoạt: Đồng bộ Cloud Save & Quét Thành Tựu mới mở khóa.
    - Tự động đóng gói Save + Thành tựu vào Hồ Sơ Di Động Hợp Nhất (PlayerProfile.congu_save).
    """
    _internal_log(f"[PlaytimeTracker] Kích hoạt Post-Exit Hook cho '{game_id}' tại '{game_dir}'")
    try:
        if ACHIEVEMENT_MGR:
            ACHIEVEMENT_MGR.check_game_live_achievements(game_id, game_dir)
    except Exception as e:
        print(f"[AchievementTracker] Post-exit scan error: {e}")

    try:
        vault = get_vault_instance()
        games = _GAMES_GETTER() if _GAMES_GETTER else []
        g_cfg = next((g for g in games if g.get("id") == game_id), None)
        if g_cfg:
            vault.pack_game_to_vault(g_cfg, game_dir)
            _internal_log(f"[SaveVault] Đã tự động gom Save + Thành tựu của '{game_id}' vào Hồ Sơ Di Động (.congu_save)")
    except Exception as e:
        print(f"[SaveVault] Post-exit vault pack error: {e}")

    try:
        if CLOUD_SYNC_MGR:
            games = _GAMES_GETTER() if _GAMES_GETTER else []
            g_cfg = next((g for g in games if g.get("id") == game_id), None)
            if g_cfg:
                CLOUD_SYNC_MGR.post_session_sync(game_id, game_dir, g_cfg)
    except Exception as e:
        print(f"[CloudSync] Post-exit sync hook error: {e}")

    try:
        if _CONTROLLER_ENGINE_REF:
            _CONTROLLER_ENGINE_REF.handle_game_exit(game_id)
            _internal_log(f"[ControllerEngine] Đã dọn dẹp sạch sẽ wrapper và dừng mapper cho '{game_id}'")
    except Exception as e:
        print(f"[ControllerEngine] Post-exit cleanup error: {e}")

    # Chạy các custom exit hooks bổ sung nếu có
    with _HOOK_LOCK:
        for hook_fn in _CUSTOM_EXIT_HOOKS:
            try:
                hook_fn(game_id, game_dir)
            except Exception as e:
                print(f"[ExitHook] Custom hook error: {e}")


# ==============================================================================
# KHỞI TẠO CÁC SINGLETON MẶC ĐỊNH
# ==============================================================================

ACHIEVEMENT_MGR = AchievementManager()
PLAYTIME_MGR = PlaytimeManager(
    db_path=os.path.join(get_default_appdata_dir(), "playtime.json"),
    on_game_exit_callback=handle_game_exit_hook
)
CLOUD_SYNC_MGR = CloudSyncManager(get_default_appdata_dir())
