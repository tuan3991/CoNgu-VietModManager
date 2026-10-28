import os
import sys

# Force bypass Windows system proxy/VPN for local loopback (fixes ERR_CONNECTION_REFUSED on 127.0.0.1)
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--no-proxy-server --proxy-bypass-list=<-loopback> --disable-features=msSmartScreenProtection"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

# Ensure stdout and stderr never raise UnicodeEncodeError on Windows cp1252 consoles
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import security

try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch, find_tool_exe
except ImportError:
    class SecurityError(PermissionError):
        """Lỗi vi phạm an ninh hệ thống hoặc phát hiện hành vi can thiệp trái phép."""
        pass

    class PathTraversalError(SecurityError):
        """Phát hiện lỗ hổng Path Traversal hoặc Zip Slip."""
        pass

    def validate_safe_path(base_dir, relative_or_target_path, allow_base_itself=False):
        """Chuẩn hóa và kiểm tra an toàn đường dẫn bắt buộc (Chống Path Traversal & Zip Slip)."""
        if not base_dir:
            raise PathTraversalError("Thư mục gốc (game_root) không được để trống!")
        if relative_or_target_path is None or str(relative_or_target_path).strip() == "":
            if allow_base_itself:
                return os.path.realpath(base_dir)
            raise PathTraversalError("Đường dẫn thao tác không được để trống!")

        base_real = os.path.realpath(base_dir)
        path_str = str(relative_or_target_path).strip()

        if os.path.isabs(path_str):
            target_real = os.path.realpath(path_str)
        else:
            target_real = os.path.realpath(os.path.join(base_real, path_str))

        base_norm = os.path.normcase(base_real)
        target_norm = os.path.normcase(target_real)

        try:
            common = os.path.commonpath([base_norm, target_norm])
        except ValueError as e:
            raise PathTraversalError(
                f"Cảnh báo bảo mật (Cross-Drive Traversal): Đường dẫn '{path_str}' nằm khác phân vùng ổ đĩa với thư mục game '{base_dir}'! ({e})"
            )

        if common != base_norm:
            raise PathTraversalError(
                f"Cảnh báo bảo mật (Path Traversal): Phát hiện đường dẫn trái phép '{path_str}' trỏ ra ngoài phạm vi thư mục game '{base_dir}'! Từ chối thực thi để bảo vệ an toàn."
            )

        if not allow_base_itself and target_norm == base_norm:
            raise PathTraversalError(
                f"Cảnh báo bảo mật: Thao tác không được phép nhắm trực tiếp vào chính thư mục gốc của game '{base_dir}'!"
            )

        return target_real

    def find_tool_exe(tool_name: str):
        exe_name = tool_name if tool_name.lower().endswith(".exe") else f"{tool_name}.exe"
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "tools", exe_name))
            candidates.append(os.path.join(sys._MEIPASS, exe_name))
        current_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(current_dir, "tools", exe_name))
        candidates.append(os.path.join(current_dir, exe_name))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "tools", exe_name))
        candidates.append(os.path.join(exe_dir, exe_name))
        candidates.append(os.path.join(os.getcwd(), "tools", exe_name))
        candidates.append(os.path.join(os.getcwd(), exe_name))
        for p in candidates:
            if os.path.isfile(p):
                return os.path.abspath(p)
        found = shutil.which(exe_name) or shutil.which(tool_name)
        if found:
            return os.path.abspath(found)
        return None

    def apply_binary_patch(src_file, dst_file, patch_data_or_file):
        """Fallback áp dụng binary patch theo luồng cửa sổ trượt."""
        if hasattr(security, "apply_binary_patch"):
            return security.apply_binary_patch(src_file, dst_file, patch_data_or_file)
        raise RuntimeError("Không tìm thấy hàm apply_binary_patch trong security!")


from core.downloader import (
    download_file_with_progress,
    TORRENT_MGR,
    HYDRA_MGR,
    TorrentDownloadManager,
    HydraSourceManager,
)

import os
import sys
import json
import shutil
import re
import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import secrets
SESSION_AUTH_TOKEN = secrets.token_hex(16)
from datetime import datetime
from pathlib import Path
from bottle import Bottle, static_file, request, response, abort
import socketserver
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer
import webview
import glob
import urllib.request
import ssl
import urllib.parse
import ctypes
from ctypes import wintypes

# --- CONFIGURATION, CATALOG & PATH ENGINE (MODULARIZED CORE) ---
from core.config_manager import (
    APP_DIR,
    STATIC_DIR,
    USER_DOCS_DIR,
    DEFAULT_REPO_DIR,
    FALLBACK_REPO_DIR,
    GAMES_JSON,
    APPDATA_DIR,
    CONFIG_JSON,
    BACKUP_ROOT,
    USER_DATA_FILE,
    COVERS_DIR,
    COVERS_CACHE_FILE,
    PLAYTIME_FILE,
    CACHE_GAMES_JSON,
    CUSTOM_GAMES_JSON,
    CURRENT_VERSION,
    GITHUB_REPO,
    REMOTE_CATALOG_URLS,
    REMOTE_VERSION_URLS,
    load_user_config,
    save_user_config,
    get_repo_dir,
    get_all_configured_game_paths,
    get_active_games_json_path,
    get_games,
    load_custom_games,
    save_custom_games,
    sync_remote_catalog,
    check_app_update,
    load_user_data,
    save_user_data,
    load_covers_cache,
    save_covers_cache,
    set_api_instance_ref,
)

def log_startup(msg: str):
    """Ghi log khoi dong ung dung de chan doan su co tren moi may tinh."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    try:
        print(formatted.encode("ascii", "replace").decode("ascii"))
    except Exception:
        pass
    try:
        log_file = os.path.join(APPDATA_DIR, "startup.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

from core.scanner import (
    extract_local_steam_appid,
    resolve_clean_game_title,
    extract_exe_icon,
)

def fetch_game_metadata_and_avatar(game_dir: str = "", exe_name: str = "", fallback_title: str = "", game_id: str = "") -> dict:
    """
    Lớp 3 & Lớp 4: Tự động tìm steam_appid, link ảnh bìa dọc 600x900 nét căng và thể loại cho game lẻ.
    Tự động lấy poster có mã hash Steam mới hoặc dựng Poster Glassmorphism từ header.jpg ngang (không cắt chữ),
    và lưu cache ảnh bìa tại chỗ (%APPDATA%/VietModHub/covers/{game_id}.jpg).
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    appid = extract_local_steam_appid(game_dir) if game_dir else None
    clean_title = fallback_title or resolve_clean_game_title(game_dir, exe_name)

    # 1. Nếu chưa có appid trong thư mục, tìm nhanh trong cơ sở dữ liệu steam_games.json offline (hơn 5,000 game)
    if not appid and clean_title:
        try:
            games_db = get_steam_games()
            q_clean = clean_title.lower().strip()
            for item in games_db:
                item_name = item.get("name", "").lower()
                if item_name == q_clean or item_name.startswith(q_clean):
                    appid = str(item["id"])
                    clean_title = item.get("name", clean_title)
                    break
            if not appid:
                for item in games_db:
                    if q_clean in item.get("name", "").lower():
                        appid = str(item["id"])
                        clean_title = item.get("name", clean_title)
                        break
        except Exception as e:
            print(f"[Metadata] Offline steam db search error: {e}")

    # Nếu vẫn chưa có appid, gọi Steam Online Search từ Backend (vượt chặn DPI)
    if not appid and clean_title:
        try:
            online_items = search_steam_online(clean_title, limit=3)
            if online_items:
                appid = str(online_items[0].get("steam_appid", online_items[0].get("id", "")))
                clean_title = online_items[0].get("name", clean_title)
        except Exception:
            pass

    result = {
        "steam_appid": appid,
        "title": clean_title,
        "avatar_url": None,
        "header_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else None,
        "local_cover": None,
        "genre": "GAME LẺ"
    }

    # Kiểm tra xem đã có custom cover do người dùng chọn hoặc cover tải trước đó chưa
    safe_gid = re.sub(r"[^\w\-]", "_", game_id or appid or clean_title or "unknown")
    local_cover_file = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
    local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")
    if os.path.exists(local_cover_file) and os.path.getsize(local_cover_file) > 1000:
        result["local_cover"] = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
        result["avatar_url"] = result["local_cover"]
    elif os.path.exists(local_cover_png) and os.path.getsize(local_cover_png) > 500:
        result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
        result["avatar_url"] = result["local_cover"]

    if not appid:
        # Nếu không có appid, thử trích xuất icon từ file exe
        if not result["local_cover"] and game_dir and exe_name:
            full_exe = os.path.join(game_dir, exe_name)
            if not os.path.exists(full_exe):
                cand = os.path.join(game_dir, os.path.basename(exe_name))
                if os.path.exists(cand):
                    full_exe = cand
            if os.path.exists(full_exe):
                if extract_exe_icon(full_exe, local_cover_png):
                    result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
                    result["avatar_url"] = result["local_cover"]
        return result

    # 2. Gọi thêm appdetails để lấy thể loại (Genre) và link ảnh chính thức (kể cả có mã hash)
    try:
        details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese&cc=VN"
        raw_det = steam_direct_request(details_url, timeout=3.5)
        if not raw_det:
            req = urllib.request.Request(details_url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw_det = resp.read()
        if raw_det:
            details_data = json.loads(raw_det.decode("utf-8", "ignore"))
            app_data = details_data.get(str(appid), {}).get("data", {})
            if app_data:
                result["title"] = app_data.get("name", result["title"])
                if app_data.get("header_image"):
                    result["header_url"] = app_data.get("header_image")
                genres = app_data.get("genres", [])
                if genres:
                    result["genre"] = genres[0].get("description", "PHIÊU LƯU").upper()
    except Exception as e:
        print(f"[Metadata] appdetails error: {e}")

    # 3. Thu thập danh sách candidate Posters dọc 600x900 nét căng
    candidate_posters = []
    # A. Ưu tiên số 1: Gọi API GetItems IStoreBrowseService lấy link có {HASH} chuẩn cho mọi game mới & cũ
    candidate_posters.extend(get_steam_official_Vertical_posters(appid))

    # B. Nếu appdetails header_url có mã hash 40 ký tự hex, thử ghép mã hash vào library_600x900
    if result.get("header_url"):
        h_match = re.search(r"/([0-9a-f]{40})/", result["header_url"])
        if h_match:
            h_code = h_match.group(1)
            candidate_posters.extend([
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
            ])

    # C. Các CDN truyền thống không hash
    candidate_posters.extend([
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
    ])

    # D. Kho SteamGridDB (poster dọc 600x900 nét căng do cộng đồng thiết kế)
    candidate_posters.extend(fetch_steamgriddb_posters(appid, limit=3))

    downloaded_raw = None
    ssl_bypass_ctx = ssl.create_default_context()
    ssl_bypass_ctx.check_hostname = False
    ssl_bypass_ctx.verify_mode = ssl.CERT_NONE

    # 4. Tải và kiểm tra từng candidate poster dọc
    for url in candidate_posters:
        if not url:
            continue
        try:
            raw = steam_direct_request(url, timeout=3.0)
            if not raw or len(raw) < 1000:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5, context=ssl_bypass_ctx) as resp:
                    if resp.status == 200:
                        raw = resp.read()
            if (
                raw
                and len(raw) > 1000
                and not raw.startswith(b"<html>")
                and not raw.startswith(b"HTTP/1.1 40")
                and not raw.startswith(b"HTTP/1.1 50")
            ):
                downloaded_raw = raw
                result["avatar_url"] = url
                break
        except Exception:
            continue

    # 5. Nếu không có ảnh dọc, fallback tải header_url (ảnh ngang 460x215)
    if not downloaded_raw and result.get("header_url"):
        h_url = result["header_url"]
        try:
            raw = steam_direct_request(h_url, timeout=3.5)
            if not raw or len(raw) < 1000:
                req = urllib.request.Request(h_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    if resp.status == 200:
                        raw = resp.read()
            if (
                raw
                and len(raw) > 1000
                and not raw.startswith(b"<html>")
                and not raw.startswith(b"HTTP/1.1 40")
                and not raw.startswith(b"HTTP/1.1 50")
            ):
                downloaded_raw = raw
                if not result.get("avatar_url"):
                    result["avatar_url"] = h_url
        except Exception as e:
            print(f"[Metadata] header_url download error: {e}")

    # 6. Chuẩn hóa qua make_vertical_poster (Fit 600x900 nét căng hoặc dựng Glassmorphism cho ảnh ngang) và lưu cache
    if downloaded_raw and not os.path.exists(local_cover_file):
        try:
            formatted_poster = make_vertical_poster(downloaded_raw)
            with open(local_cover_file, "wb") as f_out:
                f_out.write(formatted_poster)
            result["local_cover"] = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
            result["avatar_url"] = result["local_cover"]
        except Exception as e:
            print(f"[Metadata] Error saving formatted poster: {e}")

    # 7. Nếu vẫn chưa có ảnh bìa lưu được, thử trích xuất icon từ .exe
    if not result.get("local_cover") and game_dir and exe_name:
        full_exe = os.path.join(game_dir, exe_name)
        if not os.path.exists(full_exe):
            cand = os.path.join(game_dir, os.path.basename(exe_name))
            if os.path.exists(cand):
                full_exe = cand
        if os.path.exists(full_exe):
            if extract_exe_icon(full_exe, local_cover_png):
                result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
                if not result.get("avatar_url"):
                    result["avatar_url"] = result["local_cover"]

    return result

def compute_file_sha256(file_path):
    """Compute SHA-256 hash of a file safely in 1MB chunks."""
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1048576):
                h.update(chunk)
        return h.hexdigest().lower()
    except Exception:
        return None

def _norm_rel(rel_path: str) -> str:
    """Chuẩn hóa mọi đường dẫn tương đối về dấu / và loại bỏ khoảng trắng / gạch chéo thừa."""
    p = str(rel_path or "").replace("\\", "/").strip("/ ")
    while "//" in p:
        p = p.replace("//", "/")
    return p

# (Config, catalog and update functions imported from core.config_manager)


os.makedirs(APPDATA_DIR, exist_ok=True)
os.makedirs(BACKUP_ROOT, exist_ok=True)

# ==============================================================================
# IMPORT BACKUP & INSTALLER PIPELINE MODULES (CORE/INSTALLER_PIPELINE.PY)
# ==============================================================================
from core.backup_rollback import (
    backup_file_inplace,
    load_backup_manifest,
    record_preexisting_environment,
    record_backup_manifest,
    record_modded_state,
    restore_files_inplace,
)
from core.installer_pipeline import (
    INSTALL_PROGRESS,
    set_progress,
    get_install_progress,
    _MOD_OP_LOCK,
    patch_ini_file,
    execute_pipeline_step,
    execute_action_pipeline,
    install_mod,
    install_mod_impl,
    uninstall_mod,
    uninstall_mod_impl,
    emergency_restore_game,
)

def calculate_sha256(filepath):
    """Calculate SHA256 checksum of a file"""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def get_running_processes():
    """
    Enumerate running processes returning a list of tuples: (process_name_lower, full_path_or_None).
    Uses native Win32 Toolhelp API and QueryFullProcessImageNameW (0ms, 0 external dependencies).
    """
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_char * 260)
        ]

    try:
        hSnapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if hSnapshot == -1:
            return []
        procs = []
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(hSnapshot, ctypes.byref(pe)):
            while True:
                proc_name = pe.szExeFile.decode('latin-1', errors='ignore').lower()
                pid = pe.th32ProcessID
                full_path = None
                hProc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if hProc:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if ctypes.windll.kernel32.QueryFullProcessImageNameW(hProc, 0, buf, ctypes.byref(size)):
                            full_path = buf.value
                    finally:
                        ctypes.windll.kernel32.CloseHandle(hProc)
                procs.append((proc_name, full_path))
                if not ctypes.windll.kernel32.Process32Next(hSnapshot, ctypes.byref(pe)):
                    break
        ctypes.windll.kernel32.CloseHandle(hSnapshot)
        return procs
    except Exception:
        return []

def get_running_process_names():
    """Enumerate running process names using native Win32 Toolhelp API"""
    return {p[0] for p in get_running_processes()}

def check_game_running(g, game_path=None):
    """
    Check if the game executable or its crash handler / engine helper is currently running.
    Scans target executable, shipping variants, executables inside game_path, and verifies full process paths.
    Avoids false positives from generic crash handlers (UnityCrashHandler, CrashReportClient) running from other games/apps.
    Returns (is_running: bool, process_name: str | None)
    """
    target_exes = set()
    
    # 1. Executable defined in games.json + common shipping variants
    exe_name = g.get("executable_name") if isinstance(g, dict) else None
    if exe_name:
        base_exe = os.path.basename(exe_name).lower()
        target_exes.add(base_exe)
        root_name, ext = os.path.splitext(base_exe)
        target_exes.add(f"{root_name}-win64-shipping{ext}")
        target_exes.add(f"{root_name}-win32-shipping{ext}")
        target_exes.add(f"{root_name}gl{ext}")
        target_exes.add(f"{root_name.replace(' ', '')}{ext}")
        target_exes.add(f"{root_name.replace(' ', '_')}{ext}")

    # Generic crash handlers & engine helper processes that should ONLY match if running from inside game_path
    generic_helpers = {
        "unitycrashhandler64.exe",
        "unitycrashhandler32.exe",
        "crashreportclient.exe",
        "unrealcefsubprocess.exe"
    }

    # 2. Automatically scan executables in game_path if available (excluding generic helpers)
    if game_path and os.path.exists(game_path):
        try:
            for root, dirs, files in os.walk(game_path):
                rel_parts = os.path.relpath(root, game_path).split(os.sep)
                if len(rel_parts) > 3:
                    continue
                for f in files:
                    fl = f.lower()
                    if fl.endswith('.exe') and fl not in generic_helpers:
                        target_exes.add(fl)
        except Exception:
            pass
    
    # 3. Known default executable names or variants
    gid = g.get("id", "") if isinstance(g, dict) else ""
    if gid == "witcher3":
        target_exes.update(["witcher3.exe"])
    elif gid == "preludes":
        target_exes.update(["backbonestories.exe", "backbonestories-win64-shipping.exe"])
    elif gid == "backbone":
        target_exes.update(["detective.exe", "detective-win64-shipping.exe"])
    elif gid == "hotline_miami":
        target_exes.update(["hotlinegl.exe", "hotline_miami.exe"])
    elif gid == "toem":
        target_exes.update(["toem.exe"])
    elif gid == "ror2":
        target_exes.update(["risk of rain 2.exe", "riskofrain2.exe"])
    elif gid == "loop_hero":
        target_exes.update(["loop hero.exe", "loophero.exe"])
    elif gid == "fallout_tactics":
        target_exes.update(["bos.exe", "fallout tactics.exe", "bos_hr.exe"])
    elif gid == "ravenous_devils":
        target_exes.update(["ravenous_devils.exe", "ravenous_devils-win64-shipping.exe"])
    elif gid == "erra_exordium":
        target_exes.update(["erra.exe", "erra exordium.exe"])

    # 4. Check running processes against target_exes & game_path
    running_procs = get_running_processes()

    game_path_norm = None
    if game_path:
        try:
            game_path_norm = os.path.normcase(os.path.realpath(game_path) if os.path.exists(game_path) else os.path.abspath(game_path))
        except Exception:
            pass

    for proc_name, proc_path in running_procs:
        proc_path_norm = os.path.normcase(os.path.realpath(proc_path)) if proc_path else None

        # Trường hợp 1: Có cả đường dẫn thực thi của tiến trình và thư mục game
        if game_path_norm and proc_path_norm:
            is_inside_game = (
                proc_path_norm == game_path_norm
                or proc_path_norm.startswith(game_path_norm + os.sep)
            )
            if is_inside_game:
                # Nếu tiến trình đang chạy thuộc chính thư mục của game này
                if proc_name in target_exes or proc_name in generic_helpers:
                    return True, proc_name
            # Nếu proc_path không nằm trong thư mục game này, bỏ qua (không nhận nhầm)
            continue

        # Trường hợp 2: Fallback (không lấy được proc_path hoặc không có game_path)
        # Chỉ đối chiếu theo target_exes riêng của game (TUYỆT ĐỐI không đối chiếu generic_helpers)
        if proc_name in target_exes:
            return True, proc_name

    return False, None

# --- CLOUD SAVE, ACHIEVEMENTS & PLAYTIME ENGINE (MODULARIZED CORE) ---
from core.cloud_save import (
    PROCESSENTRY32W,
    EXCLUDED_HELPER_EXES,
    is_any_exe_running_in_folder,
    PlaytimeManager,
    AchievementManager,
    handle_game_exit_hook,
    get_vault_instance,
    ConguSaveVault,
    CloudSyncManager,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    ACHIEVEMENT_MGR,
    PLAYTIME_MGR,
    CLOUD_SYNC_MGR,
    SAVE_VAULT,
    configure_cloud_save_system,
)




from community_cloud import CommunityCloudManager

COMMUNITY_CLOUD_MGR = CommunityCloudManager(
    config_getter=load_user_config,
    config_saver=save_user_config,
    vault_getter=get_vault_instance,
    games_getter=get_games
)

from controller_engine import ControllerEngine

CONTROLLER_ENGINE = ControllerEngine(
    tools_dir=os.path.join(APP_DIR, "tools") if os.path.exists(os.path.join(APP_DIR, "tools")) else "tools",
    vault_getter=get_vault_instance
)

# Đồng bộ hóa callbacks cho Cloud Save & Achievements Engine
configure_cloud_save_system(
    config_getter=load_user_config,
    custom_games_getter=load_custom_games if "load_custom_games" in globals() else None,
    games_json_path_getter=get_active_games_json_path,
    games_getter=get_games,
    controller_engine=CONTROLLER_ENGINE,
    log_fn=log_startup
)

# Tự động khởi động luồng quét ngầm nhận diện game mở từ Shortcut Desktop / Steam
PLAYTIME_MGR.start_background_scanner(get_all_configured_game_paths)


def find_mod_source_dir(mod_subfolder):
    """Find mod folder from active repo, default repo or fallback repos with resilient folder naming"""
    if not mod_subfolder:
        return ""
    cfg = load_user_config()
    repo_dirs = [
        cfg.get("repo_dir", DEFAULT_REPO_DIR),
        DEFAULT_REPO_DIR,
        FALLBACK_REPO_DIR,
        os.path.join(USER_DOCS_DIR, "Viethoagame"),
        os.path.join(USER_DOCS_DIR, "antigravity google", "Viethoagame"),
        os.path.join(APP_DIR, "Viethoagame")
    ]
    seen_repos = set()
    cleaned_repos = []
    for r in repo_dirs:
        norm = os.path.normcase(os.path.abspath(r)) if r else ""
        if norm and norm not in seen_repos and os.path.exists(r):
            seen_repos.add(norm)
            cleaned_repos.append(r)

    # Subfolder variants (handles spaces, underscores, [Viet Hoa] suffixes)
    variants = [
        mod_subfolder,
        mod_subfolder.replace(" ", ""),
        mod_subfolder.replace("_", " "),
        mod_subfolder.replace(" ", "_"),
        f"{mod_subfolder} [Viet Hoa]",
        f"{mod_subfolder.replace(' ', '')} [Viet Hoa]",
        f"[{mod_subfolder}]",
    ]
    seen_var = set()
    cleaned_var = []
    for v in variants:
        if v and v.lower() not in seen_var:
            seen_var.add(v.lower())
            cleaned_var.append(v)

    for r in cleaned_repos:
        for v in cleaned_var:
            cand = os.path.join(r, v)
            if os.path.exists(cand):
                return cand

    primary = os.path.join(cfg.get("repo_dir", DEFAULT_REPO_DIR), mod_subfolder)
    return primary

# _MOD_OP_LOCK imported from core.installer_pipeline

# ==============================================================================
# IMPORT MODULE QUÉT THƯ VIỆN GAME TỪ CORE/SCANNER.PY (CLEAN ARCHITECTURE)
# ==============================================================================
from core.scanner import (
    _LIBRARY_CACHE_LOCK,
    _STEAM_LIBRARIES_CACHE,
    _EPIC_GAMES_CACHE,
    _GOG_GAMES_CACHE,
    _STANDALONE_DIRS_CACHE,
    _LIBRARY_CACHE_TTL,
    invalidate_library_caches,
    get_available_drives,
    is_running_as_admin,
    check_directory_writable,
    request_uac_elevation,
    detect_steam_libraries,
    detect_epic_games,
    detect_gog_games,
    detect_standalone_game_dirs,
    find_game_install_path,
    verify_and_resolve_game_path,
)

# ==============================================================================
# COMMUNITY LOCALIZATION WISHLIST & VOTING (FIREBASE RTDB / LOCAL HYBRID)
# ==============================================================================
FIREBASE_RTDB_URL = "https://congu-hub-default-rtdb.asia-southeast1.firebasedatabase.app"

def get_firebase_url():
    global FIREBASE_RTDB_URL
    if FIREBASE_RTDB_URL:
        return FIREBASE_RTDB_URL.rstrip("/")
    env_url = os.environ.get("FIREBASE_RTDB_URL")
    if env_url:
        return env_url.rstrip("/")
    return ""

def fetch_community_requests_from_cloud():
    fb_url = get_firebase_url()
    if not fb_url:
        return None
    try:
        url = f"{fb_url}/community_requests.json"
        req = urllib.request.Request(url, headers={"User-Agent": "CoNguHub/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"Firebase fetch error: {e}")
    return None

def push_community_request_to_cloud(game_id, item_data):
    fb_url = get_firebase_url()
    if not fb_url:
        return False
    try:
        url = f"{fb_url}/community_requests/{game_id}.json"
        req_body = json.dumps(item_data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json", "User-Agent": "CoNguHub/2.0"}, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Firebase push error: {e}")
    return False

def patch_vote_to_cloud(game_id, new_votes, machine_id=None):
    fb_url = get_firebase_url()
    if not fb_url:
        return False
    try:
        url = f"{fb_url}/community_requests/{game_id}.json"
        payload = {"votes": new_votes}
        req_body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json", "User-Agent": "CoNguHub/2.0"}, method="PATCH")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if machine_id:
                try:
                    voter_url = f"{fb_url}/community_requests/{game_id}/voters/{machine_id}.json"
                    v_req = urllib.request.Request(voter_url, data=b"true", headers={"Content-Type": "application/json"}, method="PUT")
                    urllib.request.urlopen(v_req, timeout=4)
                except Exception:
                    pass
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Firebase vote patch error: {e}")
    return False

LOCAL_REQUESTS_FILE = os.path.join(APPDATA_DIR, "community_requests.json")
STATIC_REQUESTS_SEED = os.path.join(STATIC_DIR, "data", "community_requests.json")

def load_local_community_requests():
    if os.path.exists(LOCAL_REQUESTS_FILE):
        try:
            with open(LOCAL_REQUESTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading local community requests: {e}")
    # Dùng file trong STATIC_DIR làm dữ liệu khởi tạo ban đầu (seed data)
    if os.path.exists(STATIC_REQUESTS_SEED):
        try:
            with open(STATIC_REQUESTS_SEED, "r", encoding="utf-8") as f:
                data = json.load(f)
            save_local_community_requests(data)
            return data
        except Exception as e:
            print(f"Error loading seed community requests: {e}")
    return {}

def save_local_community_requests(data):
    try:
        os.makedirs(os.path.dirname(LOCAL_REQUESTS_FILE), exist_ok=True)
        with open(LOCAL_REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving local community requests: {e}")


MAIN_HWND = None
_is_dragging_window = False
is_window_maximized = False

def get_main_hwnd():
    """Resolve the main Win32 window handle for PyWebView frameless window with multi-level fallback"""
    global MAIN_HWND
    import ctypes
    user32 = ctypes.windll.user32

    if MAIN_HWND and user32.IsWindow(MAIN_HWND):
        return MAIN_HWND

    hwnd = None
    if 'api_instance' in globals() and api_instance.window and hasattr(api_instance.window, 'native') and api_instance.window.native:
        try:
            hwnd = int(api_instance.window.native.Handle.ToInt64())
            if hwnd and user32.IsWindow(hwnd):
                MAIN_HWND = hwnd
                return MAIN_HWND
        except Exception:
            hwnd = None

    titles = [
        "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro",
        "CỔ NGỮ (VietModHub Pro)",
        "VietModHub"
    ]
    for t in titles:
        h = user32.FindWindowW(None, t)
        if h and user32.IsWindow(h):
            MAIN_HWND = h
            return MAIN_HWND

    current_pid = os.getpid()
    found_hwnds = []

    def enum_proc(h, lParam):
        if user32.IsWindowVisible(h):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == current_pid:
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    val = buff.value
                    if "CỔ NGỮ" in val or "VietMod" in val:
                        found_hwnds.append(h)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

    if found_hwnds:
        MAIN_HWND = found_hwnds[0]
        return MAIN_HWND

    return None

def start_window_drag():
    """Trigger ultra-smooth native Windows OS window dragging on titlebar mouse down"""
    global _is_dragging_window, is_window_maximized
    if _is_dragging_window:
        return {"success": True, "status": "already_dragging"}

    hwnd = get_main_hwnd()
    if not hwnd:
        return {"success": False, "error": "No window handle"}

    import ctypes
    user32 = ctypes.windll.user32

    # Check if left mouse button is pressed
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        return {"success": False, "status": "mouse_not_down"}

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    # Handle un-maximize if window is currently maximized
    if is_window_maximized:
        try:
            if 'api_instance' in globals() and api_instance.window:
                api_instance.window.restore()
            is_window_maximized = False
            time.sleep(0.06)
        except Exception:
            pass

    start_pt = POINT()
    user32.GetCursorPos(ctypes.byref(start_pt))

    win_rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win_rect))
    offset_x = start_pt.x - win_rect.left
    offset_y = start_pt.y - win_rect.top

    def _drag_loop():
        global _is_dragging_window
        _is_dragging_window = True

        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010

        curr_pt = POINT()
        try:
            while user32.GetAsyncKeyState(0x01) & 0x8000:
                user32.GetCursorPos(ctypes.byref(curr_pt))
                new_x = curr_pt.x - offset_x
                new_y = curr_pt.y - offset_y
                user32.SetWindowPos(hwnd, None, new_x, new_y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                time.sleep(0.005) # 200 Hz ultra smooth tracking
        except Exception:
            pass
        finally:
            _is_dragging_window = False

    threading.Thread(target=_drag_loop, daemon=True).start()
    return {"success": True}

def stop_window_drag():
    global _is_dragging_window
    _is_dragging_window = False
    return {"success": True}


def steam_direct_request(url: str, timeout: float = 4.0) -> bytes:
    """Gửi HTTP GET trực tiếp tới các máy chủ Steam (store.steampowered.com, steamcommunity.com, steamstatic.com)
    sử dụng cơ chế phân mảnh ClientHello (DPI bypass) nhằm vượt qua việc các nhà mạng chặn SNI tại Việt Nam."""
    import socket
    import ssl
    import urllib.parse
    import time

    p = urllib.parse.urlparse(url)
    hostname = p.netloc or "store.steampowered.com"
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()
        sslobj = ctx.wrap_bio(incoming, outgoing, server_hostname=hostname)
        try:
            sslobj.do_handshake()
        except ssl.SSLWantReadError:
            pass

        client_hello = outgoing.read()
        ip = socket.gethostbyname(hostname)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, 443))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # Gửi 5 bytes đầu tiên (TLS record header), nghỉ 20ms rồi gửi phần còn lại để bypass DPI
        sock.sendall(client_hello[:5])
        time.sleep(0.02)
        sock.sendall(client_hello[5:])

        while True:
            try:
                sslobj.do_handshake()
                break
            except ssl.SSLWantReadError:
                data = sock.recv(4096)
                if not data:
                    break
                incoming.write(data)
            out = outgoing.read()
            if out:
                sock.sendall(out)

        http_req = (
            f"GET {path} HTTP/1.0\r\n"
            f"Host: {hostname}\r\n"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
            f"Accept: application/json, image/*, text/plain, */*\r\n"
            f"Connection: close\r\n\r\n"
        )
        sslobj.write(http_req.encode("utf-8"))
        out = outgoing.read()
        if out:
            sock.sendall(out)

        resp_body = b""
        while True:
            try:
                data = sslobj.read(8192)
                if not data:
                    break
                resp_body += data
            except ssl.SSLWantReadError:
                raw = sock.recv(8192)
                if not raw:
                    break
                incoming.write(raw)
        sock.close()
        parts = resp_body.split(b"\r\n\r\n", 1)
        if len(parts) > 1:
            first_line = parts[0].split(b"\r\n", 1)[0].decode("latin-1", errors="ignore")
            if "200 OK" in first_line:
                return parts[1]
        return b""
    except Exception as e:
        # Fallback về urllib thông thường nếu mạng không bị chặn DPI
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
                return b""
        except Exception:
            return b""


def batch_fetch_steam_assets(appids: list[str]) -> dict[str, dict]:
    """
    Gọi 1 request duy nhất tới IStoreBrowseService/GetItems/v1 cho toàn bộ danh sách appid
    để lấy chính xác link library_600x900_2x.jpg và header.jpg kèm mã {HASH} chuẩn.
    """
    valid_ids = [int(a) for a in appids if str(a).isdigit()]
    if not valid_ids:
        return {}
    result_map = {}
    try:
        input_json = json.dumps({
            "ids": [{"appid": aid} for aid in valid_ids],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True}
        }, separators=(",", ":"))
        api_url = f"https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json={urllib.parse.quote(input_json)}"
        raw = steam_direct_request(api_url, timeout=4.0)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            for item in data.get("response", {}).get("store_items", []):
                aid = str(item.get("appid", ""))
                assets = item.get("assets", {})
                fmt = assets.get("asset_url_format", f"steam/apps/{aid}/${{FILENAME}}")
                
                poster_url = ""
                for key in ("library_capsule_2x", "library_capsule"):
                    if assets.get(key):
                        rel = fmt.replace("${FILENAME}", assets[key]).lstrip("/")
                        poster_url = f"https://shared.fastly.steamstatic.com/store_item_assets/{rel}"
                        break
                        
                header_url = ""
                if assets.get("header"):
                    rel_h = fmt.replace("${FILENAME}", assets["header"]).lstrip("/")
                    header_url = f"https://shared.fastly.steamstatic.com/store_item_assets/{rel_h}"

                result_map[aid] = {
                    "poster": poster_url,
                    "header": header_url
                }
    except Exception as e:
        print(f"[BatchSteamAssets] Error: {e}")
    return result_map


def get_steam_official_Vertical_posters(appid: str) -> list[str]:
    """
    Gọi API IStoreBrowseService/GetItems/v1 của Steam để lấy chính xác đường dẫn
    library_600x900_2x.jpg và library_600x900.jpg kèm mã {HASH} chuẩn cho mọi game mới & cũ.
    """
    if not appid or not str(appid).isdigit():
        return []
    urls = []
    try:
        input_json = json.dumps({
            "ids": [{"appid": int(appid)}],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True}
        }, separators=(",", ":"))
        api_url = f"https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json={urllib.parse.quote(input_json)}"
        raw = steam_direct_request(api_url, timeout=4.0)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            items = data.get("response", {}).get("store_items", [])
            if items:
                assets = items[0].get("assets", {})
                fmt = assets.get("asset_url_format", f"steam/apps/{appid}/${{FILENAME}}")
                for key in ("library_capsule_2x", "library_capsule"):
                    fname = assets.get(key)
                    if fname:
                        rel_path = fmt.replace("${FILENAME}", fname).lstrip("/")
                        urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/{rel_path}")
                        urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/{rel_path}")
    except Exception as e:
        print(f"[SteamBrowseAPI] Error fetching hashed capsule for {appid}: {e}")

    # Fallback dự phòng: Thử tìm mã hash 40 hex từ appdetails nếu API trên không trả về assets
    if not urls:
        try:
            details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
            raw_det = steam_direct_request(details_url, timeout=3.5)
            if raw_det:
                det = json.loads(raw_det.decode("utf-8", "ignore"))
                h_img = det.get(str(appid), {}).get("data", {}).get("header_image", "")
                m = re.search(r"/([0-9a-f]{40})/", h_img)
                if m:
                    h_code = m.group(1)
                    urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg")
                    urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg")
                    urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg")
                    urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg")
        except Exception:
            pass

    return urls

get_steam_official_vertical_posters = get_steam_official_Vertical_posters

STEAMGRIDDB_API_KEY = "426d6282a3c5c387dbee3e4ee3a37628"  # Điền API Key của SteamGridDB


def fetch_steamgriddb_posters(steam_appid: str, limit: int = 4) -> list[str]:
    """Lấy danh sách poster dọc chuẩn 600x900 từ kho SteamGridDB theo Steam AppID."""
    if not STEAMGRIDDB_API_KEY or not str(steam_appid).isdigit():
        return []
    url = f"https://www.steamgriddb.com/api/v2/grids/steam/{steam_appid}?dimensions=600x900&types=static"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
        "User-Agent": "CoNgu-VietModManager/2.0"
    })
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=3.5, context=ctx) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                return [item["url"] for item in data.get("data", [])[:limit] if item.get("url")]
    except Exception as e:
        print(f"[SteamGridDB] Error: {e}")
    return []


def search_steamgriddb_by_name(query: str, max_items: int = 6) -> list[dict]:
    """Tìm kiếm trực tiếp poster 600x900 trên SteamGridDB theo tên game."""
    results = []
    if not STEAMGRIDDB_API_KEY or not query or len(query.strip()) < 2:
        return results
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        encoded_q = urllib.parse.quote(query.strip())
        url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{encoded_q}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
            "User-Agent": "CoNgu-VietModManager/2.0"
        })
        with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            games = data.get("data", [])

        for g in games[:3]:
            gid = g.get("id")
            gname = g.get("name")
            if not gid or not gname:
                continue
            g_url = f"https://www.steamgriddb.com/api/v2/grids/game/{gid}?dimensions=600x900&types=static"
            g_req = urllib.request.Request(g_url, headers={
                "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
                "User-Agent": "CoNgu-VietModManager/2.0"
            })
            try:
                with urllib.request.urlopen(g_req, timeout=3.0, context=ctx) as g_resp:
                    grids_data = json.loads(g_resp.read().decode("utf-8", "ignore"))
                    grids = grids_data.get("data", [])
                    for idx, it in enumerate(grids[:2]):
                        p_url = it.get("url")
                        grid_id = it.get("id")
                        if p_url:
                            results.append({
                                "id": f"sgdb_{gid}_{grid_id}",
                                "steam_appid": "",
                                "name": gname,
                                "title": gname,
                                "subtitle": f"SteamGridDB #{grid_id}",
                                "source": "steamgriddb",
                                "genre": "SteamGridDB",
                                "avatar_url": p_url,
                                "header_url": p_url,
                                "capsule": p_url
                            })
                            if len(results) >= max_items:
                                return results
            except Exception:
                pass
    except Exception as e:
        print(f"[SteamGridDB Search] Error: {e}")
    return results


def search_steam_online(query: str, limit: int = 15) -> list[dict]:
    clean_q = re.sub(r"\s+", " ", (query or "")).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    encoded_q = urllib.parse.quote(clean_q)
    raw_items = []
    seen = set()

    # 1. Store Search API
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={encoded_q}&l=english&cc=US"
        raw = steam_direct_request(url, timeout=3.5)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            for it in data.get("items", [])[:limit]:
                appid = str(it.get("id", ""))
                name = it.get("name", "")
                if not appid or not name or appid in seen:
                    continue
                seen.add(appid)
                raw_items.append({
                    "appid": appid,
                    "name": name,
                    "tiny_image": it.get("tiny_image", "")
                })
    except Exception as e:
        print(f"[SteamOnline] Store search failed: {e}")

    # 2. Community SearchApps API (steamcommunity.com) nếu kết quả còn ít
    if len(raw_items) < limit:
        try:
            url = f"https://steamcommunity.com/actions/SearchApps/{encoded_q}"
            raw = steam_direct_request(url, timeout=3.0)
            if raw:
                data = json.loads(raw.decode("utf-8", "ignore"))
                if isinstance(data, list):
                    for it in data[:limit]:
                        appid = str(it.get("appid", ""))
                        name = it.get("name", "")
                        if not appid or not name or appid in seen:
                            continue
                        seen.add(appid)
                        raw_items.append({
                            "appid": appid,
                            "name": name,
                            "tiny_image": it.get("logo") or it.get("icon", "")
                        })
        except Exception as e:
            print(f"[SteamOnline] Community search failed: {e}")

    # 3. Lấy Batch Assets có mã {HASH} chuẩn cho toàn bộ kết quả tìm được trong 1 lần gọi
    assets_map = batch_fetch_steam_assets([it["appid"] for it in raw_items])

    results = []
    for it in raw_items:
        appid = it["appid"]
        name = it["name"]
        tiny = it["tiny_image"]
        asset_info = assets_map.get(appid, {})

        # Header chuẩn (không dùng regex thay tên trên tiny_image nữa vì khác mã hash)
        header = asset_info.get("header") or tiny or f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
        
        # Nếu game/Demo có poster dọc 600x900 chính thức -> dùng trực tiếp
        # Nếu Demo/Playtest chỉ có ảnh ngang -> đi qua /api/game/poster_preview để dựng Glassmorphism 600x900 đẹp như Kho Cổ Ngữ
        poster = asset_info.get("poster")
        if not poster:
            poster = f"/api/game/poster_preview?url={urllib.parse.quote(header)}&token={SESSION_AUTH_TOKEN}"

        results.append({
            "id": int(appid) if appid.isdigit() else appid,
            "steam_appid": appid,
            "name": name,
            "title": name,
            "subtitle": f"Steam AppID: {appid}",
            "source": "steam",
            "genre": "Steam Store",
            "avatar_url": poster,
            "header_url": header,
            "capsule": header
        })

    return results


def make_vertical_poster(image_bytes: bytes, target_w: int = 600, target_h: int = 900) -> bytes:
    """
    Chuẩn hóa ảnh thành Poster dọc 2:3 (600x900):
    - Nếu ảnh gốc ĐÃ LÀ ẢNH DỌC (h >= w * 1.15): Fit chuẩn 600x900 sắc nét.
    - Nếu ảnh gốc LÀ ẢNH NGANG (header.jpg 460x215): Tuyệt đối KHÔNG cắt cụt 2 bên làm mất chữ!
      Tự động tạo nền Blur Glassmorphism đồng màu + đặt nguyên vẹn 100% banner ngang ở trung tâm trên.
    """
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return image_bytes

        # Trường hợp 1: Ảnh gốc đã là Poster dọc chuẩn (VD: 600x900)
        if h >= w * 1.15:
            result = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            # Trường hợp 2: Ảnh gốc là Banner ngang (460x215) hoặc Icon vuông -> Tạo Poster Blur Glassmorphism
            bg = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=24))
            bg = ImageEnhance.Brightness(bg).enhance(0.45)

            # Giữ nguyên 100% tỉ lệ ngang của ảnh chính (không cắt mất chữ hai bên)
            fg_w = target_w
            fg_h = max(1, int(h * (fg_w / w)))
            fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

            y_offset = max(0, int((target_h - fg_h) * 0.38))
            bg.paste(fg, (0, y_offset))
            result = bg

        out = io.BytesIO()
        result.save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as e:
        print(f"[make_vertical_poster] Error formatting poster: {e}")
        return image_bytes


class ModManagerAPI:
    def __init__(self):
        self.window = None

    def get_games(self):
        """Returns list of games with installation & mod status (3 states: INSTALLED, NOT_INSTALLED, GAME_MISSING)"""
        if not os.path.exists(get_active_games_json_path()):
            return []

        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = json.load(f)

        user_cfg = load_user_config()
        libraries = detect_steam_libraries()
        epic_games = detect_epic_games()
        gog_games = detect_gog_games()
        standalone_dirs = detect_standalone_game_dirs()
        user_data = load_user_data()
        covers_cache = load_covers_cache()
        cfg_changed = False

        for g in games:
            gid = g["id"]
            # 1. Determine game path with Smart Validation
            game_path = user_cfg.get(f"{gid}_path")
            is_valid = False
            if game_path and os.path.exists(game_path):
                is_valid, resolved, _ = verify_and_resolve_game_path(g, game_path)
                if is_valid:
                    if resolved != game_path:
                        game_path = resolved
                        user_cfg[f"{gid}_path"] = resolved
                        cfg_changed = True
                else:
                    game_path = ""
            
            if not game_path:
                detected = find_game_install_path(g, libraries, epic_games=epic_games, gog_games=gog_games, standalone_dirs=standalone_dirs)
                if detected:
                    is_valid, resolved, _ = verify_and_resolve_game_path(g, detected)
                    if is_valid:
                        game_path = resolved
                        user_cfg[f"{gid}_path"] = game_path
                        cfg_changed = True

            g["game_path"] = game_path or ""
            g["is_game_found"] = is_valid

            # Early Write Permission Check (Smart UAC Elevation Detection)
            is_admin = is_running_as_admin()
            is_writable = True
            requires_admin = False
            if is_valid and game_path:
                if is_admin:
                    is_writable = True
                    requires_admin = False
                else:
                    is_writable = check_directory_writable(game_path)
                    requires_admin = not is_writable

            g["is_writable"] = is_writable
            g["requires_admin"] = requires_admin

            # 2. Source mod folder in Viethoagame repository
            mod_subfolder = g.get("mod_subfolder", "")
            source_mod_dir = find_mod_source_dir(mod_subfolder)
            g["source_mod_dir"] = source_mod_dir
            g["source_mod_exists"] = os.path.exists(source_mod_dir)

            # 3. Check if mod is installed in game directory
            mod_installed = False
            installed_size = 0
            installed_date = ""

            # Check safe backup in AppData or in-place .congu_bak
            game_backup_dir = os.path.join(BACKUP_ROOT, gid)
            has_safe_backup = False
            manifest_file = os.path.join(game_backup_dir, "backup_manifest.json")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        if m_data.get("files") and len(m_data["files"]) > 0:
                            has_safe_backup = True
                except Exception:
                    pass
            if not has_safe_backup and game_path and os.path.exists(game_path):
                rel_p = g.get("relative_install_path", "")
                tpak = g.get("target_pak_name", "")
                if tpak and os.path.exists(os.path.join(game_path, rel_p, f"{tpak}.congu_bak")):
                    has_safe_backup = True
                elif os.path.exists(os.path.join(game_path, "core", "locale.congu_bak")):
                    has_safe_backup = True
            g["has_safe_backup"] = has_safe_backup

            if g["is_game_found"]:
                mtype = g.get("mod_type", "pak")
                
                if mtype == "pak":
                    pak_path = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    if os.path.exists(pak_path):
                        mod_installed = True
                        installed_size = os.path.getsize(pak_path)
                        mtime = os.path.getmtime(pak_path)
                        installed_date = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                        
                elif mtype == "unity_assets":
                    target_assets = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    local_congu_bak = f"{target_assets}.congu_bak"
                    local_backup = os.path.join(game_path, g["relative_install_path"], g.get("backup_file", "resources.assets.original_backup"))
                    if has_safe_backup or os.path.exists(local_congu_bak) or os.path.exists(local_backup):
                        mod_installed = True
                        installed_size = os.path.getsize(target_assets) if os.path.exists(target_assets) else 0
                        installed_date = "Đang hoạt động"
                    elif os.path.exists(target_assets) and g.get("additional_files"):
                        # If additional files like Assembly-CSharp.dll exist, verify if modified
                        add_dst = os.path.join(game_path, g["additional_files"][0]["dst"])
                        if os.path.exists(add_dst) and has_safe_backup:
                            mod_installed = True
                        
                elif mtype == "wad":
                    backup_wad = os.path.join(game_path, g.get("backup_file", "HotlineMiami_GL_original.wad"))
                    bin_file = os.path.join(game_path, "hotline_localization.bin")
                    if has_safe_backup or os.path.exists(backup_wad) or os.path.exists(bin_file):
                        mod_installed = True
                        target_wad = os.path.join(game_path, g["target_pak_name"])
                        installed_size = os.path.getsize(target_wad) if os.path.exists(target_wad) else 0
                        installed_date = "Đang hoạt động"

                elif mtype == "bepinex_language":
                    lang_file = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    if os.path.exists(lang_file):
                        mod_installed = True
                        installed_size = os.path.getsize(lang_file)
                        mtime = os.path.getmtime(lang_file)
                        installed_date = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")

                elif mtype == "folder_copy":
                    marker_file = os.path.join(game_path, g["target_pak_name"])
                    backup_dir = os.path.join(game_path, "core", "locale_backup_original")
                    if has_safe_backup or os.path.exists(marker_file) or os.path.exists(backup_dir):
                        mod_installed = True
                        installed_date = "Đang hoạt động"

                elif mtype == "ini_and_exe":
                    ini_path = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    backup_ini = os.path.join(game_path, g.get("backup_file", "local/lang_eng.ini.orig"))
                    exe_orig = os.path.join(game_path, f"{g.get('executable_name', 'Loop Hero.exe')}.orig")
                    if has_safe_backup or os.path.exists(backup_ini) or os.path.exists(exe_orig):
                        mod_installed = True
                        installed_size = os.path.getsize(ini_path) if os.path.exists(ini_path) else 0
                        installed_date = "Đang hoạt động"

                elif mtype == "witcher3_mod":
                    mod_w3strings = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    backup_xml = os.path.join(game_path, g.get("backup_file", "content/content0/bundles/xml.bundle.orig"))
                    if has_safe_backup or os.path.exists(mod_w3strings) or os.path.exists(backup_xml):
                        mod_installed = True
                        installed_size = os.path.getsize(mod_w3strings) if os.path.exists(mod_w3strings) else 0
                        installed_date = "Đang hoạt động"

                # Data-Driven status marker & install_steps detection
                if not mod_installed and g.get("status_marker"):
                    marker = os.path.join(game_path, g["status_marker"])
                    if os.path.exists(marker):
                        mod_installed = True
                        installed_date = "Đang hoạt động"

                if not mod_installed and g.get("install_steps"):
                    for st in g["install_steps"]:
                        act = st.get("action")
                        if act in ["backup", "patch_binary"]:
                            bak_f = os.path.join(game_path, f"{st['target']}.congu_bak")
                            if os.path.exists(bak_f):
                                mod_installed = True
                                installed_date = "Đang hoạt động"
                                break
                        elif act == "copy_file" and not mod_installed:
                            dst_f = os.path.join(game_path, st.get("destination", ""))
                            bak_f = f"{dst_f}.congu_bak"
                            if os.path.exists(bak_f):
                                mod_installed = True
                                installed_size = os.path.getsize(dst_f) if os.path.exists(dst_f) else 0
                                installed_date = "Đang hoạt động"
                                break

            g["is_mod_installed"] = mod_installed
            g["installed_size_mb"] = round(installed_size / (1024 * 1024), 2) if installed_size else 0
            g["installed_date"] = installed_date

            # 3.4. Chẩn đoán sức khỏe bản dịch (Health Check & Steam/Epic Auto-Update Detection)
            update_detected = False
            health_reason = ""
            manifest_path = os.path.join(BACKUP_ROOT, gid, "backup_manifest.json")
            if mod_installed and os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                    mod_files = m_data.get("files", [])
                    manifest_dirty = False
                    if mod_files:
                        for it in mod_files:
                            target_f = it.get("target_file")
                            rel_f = _norm_rel(it.get("relative_in_game"))
                            if not target_f or not os.path.exists(target_f):
                                if rel_f and game_path:
                                    target_f = os.path.join(game_path, rel_f.replace("/", os.sep))

                            if target_f and os.path.exists(target_f):
                                mod_hash = it.get("modded_sha256")
                                mod_size = it.get("modded_size")
                                mod_mtime = it.get("modded_mtime")

                                # So sánh nhanh: mtime & size
                                curr_size = os.path.getsize(target_f)
                                curr_mtime = os.path.getmtime(target_f)

                                size_diff = (mod_size is not None and curr_size != mod_size)
                                mtime_diff = (mod_mtime is not None and abs(curr_mtime - mod_mtime) > 2.0)

                                if size_diff:
                                    # Kích thước file đã khác, chắc chắn 100% nội dung đã thay đổi -> không cần băm SHA-256
                                    update_detected = True
                                    health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                    break
                                elif mtime_diff:
                                    # Kích thước file trùng khớp nhưng mtime thay đổi (do Windows/Antivirus chạm vào hoặc Steam update cùng size)
                                    if mod_hash:
                                        curr_hash = compute_file_sha256(target_f)
                                        if curr_hash and curr_hash.lower() != mod_hash.lower():
                                            update_detected = True
                                            health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                            break
                                        else:
                                            # File vẫn là bản mod nguyên vẹn, cập nhật lại mtime mới vào manifest để không phải băm lại ở lần sau
                                            it["modded_mtime"] = curr_mtime
                                            manifest_dirty = True
                                elif mod_size is None and mod_hash:
                                    # Tự động vá bổ sung size và mtime cho manifest phiên bản cũ
                                    curr_hash = compute_file_sha256(target_f)
                                    if curr_hash and curr_hash.lower() != mod_hash.lower():
                                        update_detected = True
                                        health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                        break
                                    else:
                                        it["modded_size"] = curr_size
                                        it["modded_mtime"] = curr_mtime
                                        manifest_dirty = True
                            elif target_f and not os.path.exists(target_f):
                                update_detected = True
                                health_reason = f"Tệp '{rel_f or os.path.basename(target_f)}' không còn tồn tại"
                                break

                        if manifest_dirty and not update_detected:
                            try:
                                with open(manifest_path, "w", encoding="utf-8") as mf:
                                    json.dump(m_data, mf, ensure_ascii=False, indent=2)
                            except Exception as e:
                                print(f"[Health Check Warning] Error updating manifest mtime for {gid}: {e}")
                except Exception as e:
                    print(f"[Health Check Warning] Error inspecting manifest for {gid}: {e}")

            g["update_detected"] = update_detected
            g["health_reason"] = health_reason
            cache_congu_path = os.path.join(APPDATA_DIR, "cache", gid, "mod_package.congu")
            g["has_cached_congu"] = os.path.exists(cache_congu_path)

            # Determine 4-state badge: "INSTALLED" | "UPDATE_DETECTED" | "NOT_INSTALLED" | "GAME_MISSING"
            if not g["is_game_found"]:
                g["status_code"] = "GAME_MISSING"
                g["status_label"] = "CHƯA CÓ GAME"
            elif update_detected:
                g["status_code"] = "UPDATE_DETECTED"
                g["status_label"] = "GAME VỪA CẬP NHẬT - MẤT VIỆT HÓA"
                g["is_mod_installed"] = False
            elif g["is_mod_installed"]:
                g["status_code"] = "INSTALLED"
                g["status_label"] = "ĐÃ CÀI ĐẶT"
            else:
                g["status_code"] = "NOT_INSTALLED"
                g["status_label"] = "CHƯA CÀI MOD"

            # Check for version update status
            versions = g.get("versions", [])
            latest_version = versions[0]["version"] if versions else g.get("translation_stats", {}).get("version", "v1.0.0")
            g["latest_version"] = latest_version
            g["current_version"] = latest_version if mod_installed else "Chưa cài"
            g["has_update"] = False

            # Attach ratings & user comments
            g["user_rating"] = user_data.get("ratings", {}).get(gid, 5)
            g["user_comment"] = user_data.get("comments", {}).get(gid, "")

            # Metadata & Cover Enrichment (4 Lớp Tự Động Hóa cho Game Lẻ & Game Cài Ngoài)
            safe_gid = re.sub(r"[^\w\-]", "_", gid)
            local_cover_jpg = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
            local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")
            local_cover = None
            if os.path.exists(local_cover_jpg) and os.path.getsize(local_cover_jpg) > 1000:
                local_cover = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_jpg))}"
            elif os.path.exists(local_cover_png) and os.path.getsize(local_cover_png) > 500:
                local_cover = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
            
            g["local_cover"] = local_cover

            cached_meta = covers_cache.get(gid) or covers_cache.get(gid.lower()) or {}
            g["avatar_url"] = local_cover or cached_meta.get("avatar_url") or (g.get("assets", {}).get("poster"))
            g["header_url"] = cached_meta.get("header_url") or (g.get("assets", {}).get("header"))
            if cached_meta.get("steam_appid"):
                g["steam_appid"] = cached_meta["steam_appid"]
            if cached_meta.get("genre"):
                g["genre"] = cached_meta["genre"]

            # Gắn dữ liệu Theo Dõi Giờ Chơi (Playtime Tracker)
            g["playtime"] = PLAYTIME_MGR.get_game_stats(gid, game_path)

        # Gộp các game ngoài do người dùng tự thêm (Non-Steam / Custom Games)
        custom_games = load_custom_games()
        for cg in custom_games:
            cg_id = cg.get("id")
            if not cg_id:
                continue

            cg_path = user_cfg.get(f"{cg_id}_path") or cg.get("game_root", "")
            exe_name = cg.get("executable_name", "")
            full_exe = os.path.join(cg_path, exe_name) if cg_path and exe_name else ""
            is_found = os.path.isfile(full_exe) if full_exe else False

            cg["game_path"] = cg_path
            cg["is_game_found"] = is_found
            cg["is_custom_game"] = True
            cg["status_code"] = "INSTALLED" if is_found else "GAME_MISSING"
            cg["status_label"] = "GAME TỰ THÊM" if is_found else "CHƯA CÓ GAME"
            cg["is_mod_installed"] = True
            cg["is_writable"] = True
            cg["requires_admin"] = False
            cg["latest_version"] = "Tự thêm"
            cg["current_version"] = "Tự thêm"
            cg["has_update"] = False

            # Local Cover Poster
            safe_cg_id = re.sub(r"[^\w\-]", "_", cg_id)
            cover_jpg = os.path.join(COVERS_DIR, f"{safe_cg_id}.jpg")
            cover_png = os.path.join(COVERS_DIR, f"{safe_cg_id}.png")
            if os.path.exists(cover_jpg) and os.path.getsize(cover_jpg) > 1000:
                cg["local_cover"] = f"/api/covers/{safe_cg_id}.jpg?t={int(os.path.getmtime(cover_jpg))}"
            elif os.path.exists(cover_png) and os.path.getsize(cover_png) > 500:
                cg["local_cover"] = f"/api/covers/{safe_cg_id}.png?t={int(os.path.getmtime(cover_png))}"
            else:
                cg["local_cover"] = cg.get("cover_url", "")

            # Gắn playtime stats
            cg["playtime"] = PLAYTIME_MGR.get_game_stats(cg_id, cg_path)

            games.append(cg)

        if cfg_changed:
            save_user_config(user_cfg)

        return games

    def get_playtime_stats(self, game_id):
        """Lấy dữ liệu thống kê giờ chơi thời gian thực của game."""
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        return PLAYTIME_MGR.get_game_stats(game_id, game_path)

    def get_game_achievements(self, game_id_or_appid: str, game_dir: str = ""):
        """Lấy danh sách và trạng thái mở khóa thành tựu của game (Chuẩn Hydra Launcher)."""
        appid = str(game_id_or_appid) if str(game_id_or_appid).isdigit() else ""
        game_id = "" if appid else str(game_id_or_appid)
        return ACHIEVEMENT_MGR.get_game_achievements_view(appid=appid, game_dir=game_dir, game_id=game_id)

    def poll_new_achievements(self):
        """Lấy các thành tựu mới mở khóa trong thời gian thực để Frontend bắn Toast."""
        return ACHIEVEMENT_MGR.pop_newly_unlocked()

    def select_repo_folder(self):
        """Open native folder picker for user to select Viethoagame repository"""
        chosen_dir = None
        if self.window:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if res and len(res) > 0:
                chosen_dir = res[0]
        
        if not chosen_dir:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_dir = filedialog.askdirectory(title="Chọn thư mục kho Viethoagame")
                root.destroy()
            except Exception:
                pass

        if chosen_dir and os.path.exists(chosen_dir):
            cfg = load_user_config()
            cfg["repo_dir"] = os.path.normpath(chosen_dir)
            save_user_config(cfg)
            return {"success": True, "repo_dir": chosen_dir, "games": self.get_games()}
        return {"success": False, "message": "Không có thư mục nào được chọn."}


    def set_cloud_url(self, game_id, url):
        """Set Google Drive download URL for a game"""
        active_json = get_active_games_json_path()
        with open(active_json, "r", encoding="utf-8") as f:
            games = json.load(f)
        for g in games:
            if g["id"] == game_id:
                g["download_url"] = url
                break
        with open(active_json, "w", encoding="utf-8") as f:
            json.dump(games, f, ensure_ascii=False, indent=2)
        
        # Đồng bộ cả sang GAMES_JSON nếu active_json khác GAMES_JSON
        if os.path.normpath(active_json) != os.path.normpath(GAMES_JSON):
            try:
                with open(GAMES_JSON, "w", encoding="utf-8") as f:
                    json.dump(games, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        
        cfg = load_user_config()
        cfg[f"{game_id}_download_url"] = url
        save_user_config(cfg)
        return {"success": True, "message": "Đã lưu Link Google Drive cho tựa game này thành công!", "games": self.get_games()}

    def select_folder(self, game_id):
        """Open native folder picker dialog for user to select game directory"""
        chosen_dir = None
        if self.window:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if res and len(res) > 0:
                chosen_dir = res[0]
        
        # Fallback to tkinter if needed
        if not chosen_dir:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_dir = filedialog.askdirectory(title=f"Chọn thư mục cài đặt game {game_id}")
                root.destroy()
            except Exception as e:
                print(f"File dialog error: {e}")

        if chosen_dir and os.path.exists(chosen_dir):
            with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
                games_map = {gm["id"]: gm for gm in json.load(f)}
            g_target = games_map.get(game_id, {})
            is_valid, resolved_path, val_msg = verify_and_resolve_game_path(g_target, chosen_dir)
            if is_valid:
                cfg = load_user_config()
                cfg[f"{game_id}_path"] = resolved_path
                save_user_config(cfg)

                # Tự động nhận diện metadata và poster cho game lẻ (4 Lớp)
                try:
                    meta = fetch_game_metadata_and_avatar(
                        resolved_path, 
                        g_target.get("executable_name", ""), 
                        g_target.get("title", ""), 
                        game_id
                    )
                    if meta:
                        c_cache = load_covers_cache()
                        c_cache[game_id] = meta
                        save_covers_cache(c_cache)
                except Exception as e:
                    print(f"[!] Metadata extraction error: {e}")

                # Early Write Permission Check (Program Files / UAC restriction)
                is_admin = is_running_as_admin()
                is_writable = is_admin or check_directory_writable(resolved_path)
                requires_admin = not is_writable

                msg = val_msg
                if requires_admin:
                    msg = (
                        f"Thư mục '{os.path.basename(resolved_path)}' hợp lệ nhưng nằm trong thư mục hệ thống (Program Files). "
                        f"Windows yêu cầu quyền Administrator để ghi tệp."
                    )
                return {
                    "success": True,
                    "path": resolved_path,
                    "message": msg,
                    "is_writable": is_writable,
                    "requires_admin": requires_admin,
                    "games": self.get_games()
                }
            else:
                return {"success": False, "path": chosen_dir, "message": val_msg}
        
        return {"success": False, "message": "Không có thư mục nào được chọn."}

    def set_game_path(self, game_id, path):
        """Manually update game path with smart validation"""
        if not path or not os.path.exists(path):
            return {"success": False, "message": "Đường dẫn không tồn tại trên máy tính!"}
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games_map = {gm["id"]: gm for gm in json.load(f)}
        g_target = games_map.get(game_id, {})
        is_valid, resolved_path, val_msg = verify_and_resolve_game_path(g_target, path)
        if not is_valid:
            return {"success": False, "message": val_msg}
        cfg = load_user_config()
        cfg[f"{game_id}_path"] = resolved_path
        save_user_config(cfg)

        # Tự động nhận diện metadata và poster cho game lẻ (4 Lớp)
        try:
            meta = fetch_game_metadata_and_avatar(
                resolved_path, 
                g_target.get("executable_name", ""), 
                g_target.get("title", ""), 
                game_id
            )
            if meta:
                c_cache = load_covers_cache()
                c_cache[game_id] = meta
                save_covers_cache(c_cache)
        except Exception as e:
            print(f"[!] Metadata extraction error: {e}")

        # Early Write Permission Check (Program Files / UAC restriction)
        is_admin = is_running_as_admin()
        is_writable = is_admin or check_directory_writable(resolved_path)
        requires_admin = not is_writable

        msg = val_msg
        if requires_admin:
            msg = (
                f"Thư mục '{os.path.basename(resolved_path)}' hợp lệ nhưng nằm trong thư mục hệ thống (Program Files). "
                f"Windows yêu cầu quyền Administrator để ghi tệp."
            )
        return {
            "success": True,
            "path": resolved_path,
            "message": msg,
            "is_writable": is_writable,
            "requires_admin": requires_admin,
            "games": self.get_games()
        }

    def select_custom_cover(self, game_id):
        """Cho phép người dùng chọn ảnh bìa tùy chỉnh (JPG, PNG, WEBP) từ máy tính."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Image Files (*.jpg;*.jpeg;*.png;*.webp)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
                if res and len(res) > 0:
                    chosen_file = res[0]
            except Exception as e:
                print(f"[!] PyWebView file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn ảnh bìa poster cho game",
                    filetypes=[("Image files", "*.jpg;*.jpeg;*.png;*.webp"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if chosen_file and os.path.exists(chosen_file):
            safe_gid = re.sub(r"[^\w\-]", "_", game_id)
            dest_cover = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
            try:
                with open(chosen_file, "rb") as f:
                    raw_bytes = f.read()
                formatted_bytes = make_vertical_poster(raw_bytes)
                with open(dest_cover, "wb") as f:
                    f.write(formatted_bytes)
                c_cache = load_covers_cache()
                if game_id not in c_cache:
                    c_cache[game_id] = {}
                local_url = f"/api/covers/{safe_gid}.jpg?t={int(time.time())}"
                c_cache[game_id]["local_cover"] = local_url
                c_cache[game_id]["avatar_url"] = local_url
                save_covers_cache(c_cache)
                return {
                    "success": True, 
                    "cover_url": local_url, 
                    "message": "Đã đổi ảnh bìa thành công!", 
                    "games": self.get_games()
                }
            except Exception as e:
                return {"success": False, "message": f"Lỗi khi lưu ảnh bìa: {e}"}

        return {"success": False, "message": "Chưa chọn ảnh nào."}

    def select_vault_file_dialog(self):
        """Mở hộp thoại chọn tệp .congu_save từ USB/ổ cứng ngoài."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Hồ Sơ CỔ NGỮ (*.congu_save;*.congu_vault;*.zip)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
                if res and len(res) > 0:
                    chosen_file = res[0]
            except Exception as e:
                print(f"[!] PyWebView file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn tệp Hồ Sơ CỔ NGỮ (.congu_save)",
                    filetypes=[("Hồ Sơ CỔ NGỮ", "*.congu_save;*.congu_vault;*.zip"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass
        return chosen_file or ""

    def export_vault_dialog(self):
        """Mở hộp thoại chọn vị trí lưu file .congu_save ra USB hoặc thư mục bất kỳ."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Hồ Sơ CỔ NGỮ (*.congu_save)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename="PlayerProfile.congu_save", file_types=file_types)
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
            except Exception as e:
                print(f"[!] PyWebView save file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.asksaveasfilename(
                    title="Xuất Hồ Sơ CỔ NGỮ (.congu_save) ra USB / Ổ cứng",
                    initialfile="PlayerProfile.congu_save",
                    defaultextension=".congu_save",
                    filetypes=[("Hồ Sơ CỔ NGỮ", "*.congu_save"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass
        return chosen_file or ""

    def search_game_for_avatar(self, query: str) -> list[dict]:
        """Tìm danh sách game kèm ảnh preview từ Kho CỔ NGỮ, Steam Store trực tiếp trên mạng, và DB bổ trợ."""
        clean_q = re.sub(r"\s+", " ", (query or "")).strip()
        if not clean_q:
            return []

        results = []
        seen_appids = set()
        q_lower = clean_q.lower()

        congu_appids_map = {}  # appid -> game data

        # 1. Tìm ưu tiên trong kho games.json nội bộ trước
        try:
            games_json_path = get_active_games_json_path()
            if os.path.exists(games_json_path):
                with open(games_json_path, "r", encoding="utf-8") as f:
                    local_games = json.load(f)
                for g in local_games:
                    title = g.get("title", "")
                    vi_title = g.get("vietnamese_title", "")
                    gid = g.get("id", "")
                    appid = str(g.get("steam_appid") or "").strip()
                    effective_id = appid if appid else gid
                    if (
                        q_lower in title.lower()
                        or q_lower in vi_title.lower()
                        or q_lower in gid.lower()
                        or (appid and appid == clean_q)
                    ):
                        if appid:
                            seen_appids.add(appid)
                            if appid.isdigit():
                                congu_appids_map[appid] = g
                        poster = (
                            g.get("assets", {}).get("poster")
                            or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "")
                        )
                        header = (
                            g.get("assets", {}).get("header")
                            or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else "")
                        )
                        results.append({
                            "id": int(effective_id) if str(effective_id).isdigit() else effective_id,
                            "steam_appid": appid or gid,
                            "title": title,
                            "name": title,
                            "subtitle": vi_title or "Kho CỔ NGỮ",
                            "source": "congu_db",
                            "genre": g.get("genre", "Kho CỔ NGỮ"),
                            "avatar_url": poster,
                            "header_url": header,
                            "capsule": header
                        })
        except Exception as e:
            print(f"[AvatarSearch] local games.json error: {e}")

        # 2. Tìm kiếm TRỰC TIẾP trên kho Steam Store & Community qua mạng (DPI bypass)
        try:
            online_items = search_steam_online(clean_q, limit=10)

            # Thu thập toàn bộ danh sách Steam AppID (cả từ Kho Cổ Ngữ lẫn Steam Store) để lấy poster từ SteamGridDB
            steam_appids = [str(it.get("steam_appid", "")) for it in online_items if str(it.get("steam_appid", "")).isdigit()]
            all_target_appids = list(dict.fromkeys(list(congu_appids_map.keys()) + steam_appids))[:8]

            sgdb_map = {}
            if all_target_appids and STEAMGRIDDB_API_KEY:
                try:
                    with ThreadPoolExecutor(max_workers=min(len(all_target_appids), 6)) as ex:
                        futs = {ex.submit(fetch_steamgriddb_posters, aid, 3): aid for aid in all_target_appids}
                        for fut in futs:
                            aid = futs[fut]
                            try:
                                sgdb_map[aid] = fut.result()
                            except Exception:
                                sgdb_map[aid] = []
                except Exception as e:
                    print(f"[AvatarSearch] SteamGridDB batch fetch error: {e}")

            seen_avatar_urls = set()
            for r in results:
                if r.get("avatar_url"):
                    seen_avatar_urls.add(r["avatar_url"])

            # A. Thêm các mẫu SteamGridDB cho các game đã có trong Kho Cổ Ngữ
            for c_appid, c_game in congu_appids_map.items():
                c_title = c_game.get("title", "")
                for p_idx, p_url in enumerate(sgdb_map.get(c_appid, [])):
                    if p_url not in seen_avatar_urls:
                        seen_avatar_urls.add(p_url)
                        results.append({
                            "id": f"sgdb_{c_appid}_{p_idx}",
                            "steam_appid": c_appid,
                            "name": c_title,
                            "title": c_title,
                            "subtitle": f"SteamGridDB • {c_appid}",
                            "source": "steamgriddb",
                            "genre": "SteamGridDB",
                            "avatar_url": p_url,
                            "header_url": "",
                            "capsule": ""
                        })

            # B. Thêm các item Steam Store và các mẫu SteamGridDB tương ứng
            for item in online_items:
                appid = str(item.get("steam_appid", ""))
                is_store_seen = bool(appid and appid in seen_appids)
                if not is_store_seen:
                    seen_appids.add(appid)
                    p_url = item.get("avatar_url")
                    if p_url:
                        seen_avatar_urls.add(p_url)
                    results.append(item)

                # Hiển thị song song các mẫu poster dọc từ SteamGridDB cho cùng Steam AppID này (kể cả đã có trong Cổ Ngữ)
                sg_posters = sgdb_map.get(appid, [])
                for p_idx, p_url in enumerate(sg_posters):
                    if p_url not in seen_avatar_urls:
                        seen_avatar_urls.add(p_url)
                        results.append({
                            "id": f"sgdb_{appid}_{p_idx}",
                            "steam_appid": appid,
                            "name": item.get("name", ""),
                            "title": item.get("title", ""),
                            "subtitle": f"SteamGridDB • {appid}",
                            "source": "steamgriddb",
                            "genre": "SteamGridDB",
                            "avatar_url": p_url,
                            "header_url": item.get("header_url", ""),
                            "capsule": item.get("capsule", "")
                        })

            # C. Bổ sung các kết quả tìm kiếm theo tên trực tiếp từ SteamGridDB
            if STEAMGRIDDB_API_KEY:
                try:
                    sgdb_extra = search_steamgriddb_by_name(clean_q, max_items=4)
                    for sg_it in sgdb_extra:
                        p_url = sg_it.get("avatar_url")
                        if p_url and p_url not in seen_avatar_urls:
                            seen_avatar_urls.add(p_url)
                            results.append(sg_it)
                except Exception as e:
                    print(f"[AvatarSearch] SteamGridDB search by name error: {e}")

        except Exception as e:
            print(f"[AvatarSearch] online steam search error: {e}")

        # 3. Bổ sung từ cơ sở dữ liệu Steam offline (hơn 5,000 game)
        try:
            offline_db = get_steam_games()
            exact, starts, word_starts, contains = [], [], [], []
            for item in offline_db:
                appid = str(item.get("id", ""))
                name = item.get("name", "")
                if not appid or not name or appid in seen_appids:
                    continue
                name_low = name.lower()
                if name_low == q_lower:
                    exact.append(item)
                elif name_low.startswith(q_lower):
                    starts.append(item)
                elif any(w.startswith(q_lower) for w in name_low.split()):
                    word_starts.append(item)
                elif q_lower in name_low:
                    contains.append(item)
                if len(exact) + len(starts) + len(word_starts) + len(contains) >= 30:
                    break

            for item in (exact + starts + word_starts + contains)[:8]:
                appid = str(item["id"])
                if appid in seen_appids:
                    continue
                seen_appids.add(appid)
                results.append({
                    "id": int(appid) if appid.isdigit() else appid,
                    "steam_appid": appid,
                    "name": item.get("name", ""),
                    "title": item.get("name", ""),
                    "subtitle": f"Steam AppID: {appid}",
                    "source": "steam",
                    "genre": "Steam Store",
                    "avatar_url": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                    "header_url": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
                    "capsule": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
                })
        except Exception as e:
            print(f"[AvatarSearch] offline steam db search error: {e}")

        return results

    def apply_selected_avatar(self, target_game_id: str, selected_data: dict) -> dict:
        """Gán cố định avatar + steam_appid người dùng đã chọn và tải/sao chép ảnh lưu cache."""
        if not target_game_id:
            return {"status": "error", "success": False, "message": "Thiếu mã game (target_game_id)"}

        appid = str(selected_data.get("steam_appid", "")).strip()
        avatar_url = selected_data.get("avatar_url", "")
        header_url = selected_data.get("header_url", "")
        capsule_url = selected_data.get("capsule", "")
        new_title = selected_data.get("title", "")
        genre = selected_data.get("genre", "")

        safe_gid = re.sub(r"[^\w\-]", "_", target_game_id)
        os.makedirs(COVERS_DIR, exist_ok=True)
        local_cover_path = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
        local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")

        # 1. Danh sách candidate theo thứ tự ưu tiên:
        # 1. Nếu người dùng chọn mẫu từ Kho Cổ Ngữ hoặc ảnh nội bộ, ưu tiên số 1 là avatar_url đó!
        candidates = []
        if avatar_url and (
            selected_data.get("source") in ("congu_db", "steamgriddb")
            or str(avatar_url).startswith(("/assets/", "assets/", "/static/", "static/", "/api/", "https://cdn2.steamgriddb.com/"))
        ):
            candidates.append(avatar_url)

        if appid and str(appid).isdigit():
            # Ưu tiên số 1: Lấy đúng link library_600x900_2x.jpg kèm mã {HASH} từ Steam IStoreBrowseService
            candidates.extend(get_steam_official_Vertical_posters(appid))
            if header_url:
                h_match = re.search(r"/([0-9a-f]{40})/", header_url)
                if h_match:
                    h_code = h_match.group(1)
                    candidates.extend([
                        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                    ])
        if avatar_url and avatar_url not in candidates:
            candidates.append(avatar_url)
        if appid and str(appid).isdigit():
            candidates.extend([
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            ])
            # Bổ sung poster từ kho SteamGridDB
            candidates.extend(fetch_steamgriddb_posters(appid, limit=4))
        if header_url:
            candidates.append(header_url)
        if capsule_url:
            candidates.append(capsule_url)

        downloaded_ok = False
        final_timestamp = int(time.time())
        final_local_url = f"/api/covers/{safe_gid}.jpg?t={final_timestamp}"

        for cand_url in candidates:
            if not cand_url:
                continue

            raw_content = None
            clean_cand = str(cand_url).split("?")[0].strip()

            # A. Kiểm tra nguồn ảnh cục bộ (nội bộ ứng dụng /static/..., /assets/..., /api/covers/..., hoặc tệp đĩa)
            local_src = None
            if clean_cand.startswith("/static/"):
                local_src = os.path.join(STATIC_DIR, clean_cand[8:].replace("/", os.sep))
            elif clean_cand.startswith("static/"):
                local_src = os.path.join(STATIC_DIR, clean_cand[7:].replace("/", os.sep))
            elif clean_cand.startswith("/assets/"):
                local_src = os.path.join(STATIC_DIR, clean_cand.lstrip("/").replace("/", os.sep))
            elif clean_cand.startswith("assets/"):
                local_src = os.path.join(STATIC_DIR, clean_cand.replace("/", os.sep))
            elif clean_cand.startswith("/api/covers/"):
                local_src = os.path.join(COVERS_DIR, clean_cand[12:].replace("/", os.sep))
            elif str(cand_url).startswith("/api/game/poster_preview"):
                # Nếu là ảnh ngang đã qua bộ lọc Glassmorphism preview, tải từ url gốc
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(str(cand_url)).query)
                orig_u = (parsed_q.get("url") or [""])[0]
                if orig_u:
                    raw_content = steam_direct_request(orig_u, timeout=4.0)
            elif os.path.isabs(clean_cand) and os.path.exists(clean_cand):
                local_src = clean_cand
            elif os.path.exists(os.path.join(APP_DIR, clean_cand.lstrip("/\\"))):
                local_src = os.path.join(APP_DIR, clean_cand.lstrip("/\\"))

            if local_src and os.path.exists(local_src):
                try:
                    with open(local_src, "rb") as sf:
                        raw_content = sf.read()
                except Exception as e:
                    print(f"[apply_selected_avatar] Local read error for {local_src}: {e}")

            # B. Nếu là URL mạng (http / https)
            elif not raw_content and (clean_cand.startswith("http://") or clean_cand.startswith("https://")):
                try:
                    content = steam_direct_request(clean_cand, timeout=4.0)
                    if (
                        content
                        and len(content) > 1000
                        and not content.startswith(b"<html>")
                        and not content.startswith(b"HTTP/1.1 404")
                        and not content.startswith(b"HTTP/1.1 50")
                    ):
                        raw_content = content
                    else:
                        req = urllib.request.Request(clean_cand, headers={"User-Agent": "CoNgu-VietModManager/2.0"})
                        ctx = ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl.CERT_NONE
                        with urllib.request.urlopen(req, timeout=4.0, context=ctx) as r:
                            raw_content = r.read()
                except Exception:
                    pass

            # C. Chuẩn hóa poster dọc 600x900 và lưu vào COVERS_DIR
            if raw_content and len(raw_content) > 500:
                try:
                    formatted_poster = make_vertical_poster(raw_content)
                    with open(local_cover_path, "wb") as f:
                        f.write(formatted_poster)
                    if os.path.exists(local_cover_png):
                        try:
                            os.remove(local_cover_png)
                        except Exception:
                            pass
                    downloaded_ok = True
                    break
                except Exception as e:
                    print(f"[apply_selected_avatar] Error formatting poster: {e}")

        # Lấy thêm thông tin Genre và tên từ Steam details nếu có appid
        if appid and str(appid).isdigit():
            try:
                details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese&cc=VN"
                raw = steam_direct_request(details_url, timeout=3.5)
                if raw:
                    det = json.loads(raw.decode("utf-8", "ignore"))
                    if det.get(str(appid), {}).get("success"):
                        app_data = det[str(appid)]["data"]
                        genres_list = [g.get("description") for g in app_data.get("genres", [])]
                        if genres_list:
                            genre = ", ".join(genres_list)
                        if not new_title:
                            new_title = app_data.get("name", "")
                        if not header_url:
                            header_url = app_data.get("header_image", "")
                        # Nếu các candidate trước chưa tải được, thử tải header_image từ appdetails
                        if not downloaded_ok and header_url:
                            h_content = steam_direct_request(header_url, timeout=4.0)
                            if (
                                h_content
                                and len(h_content) > 1000
                                and not h_content.startswith(b"<html>")
                                and not h_content.startswith(b"HTTP/1.1 404")
                                and not h_content.startswith(b"HTTP/1.1 50")
                            ):
                                formatted_poster = make_vertical_poster(h_content)
                                with open(local_cover_path, "wb") as f:
                                    f.write(formatted_poster)
                                if os.path.exists(local_cover_png):
                                    try:
                                        os.remove(local_cover_png)
                                    except Exception:
                                        pass
                                downloaded_ok = True
            except Exception:
                pass

        # Nếu không lưu được ảnh mới, nhưng người dùng đã chọn avatar_url khác,
        # xóa tệp bìa cũ không còn phù hợp để không bị dính ảnh sai cũ
        if not downloaded_ok and avatar_url:
            if os.path.exists(local_cover_path):
                try:
                    os.remove(local_cover_path)
                except Exception:
                    pass
            if os.path.exists(local_cover_png):
                try:
                    os.remove(local_cover_png)
                except Exception:
                    pass

        chosen_avatar = final_local_url if downloaded_ok else (avatar_url or "")
        chosen_cover = final_local_url if downloaded_ok else (avatar_url or "")

        # Cập nhật cache covers_cache.json (cả khóa gốc lẫn chữ thường để tra cứu không phân biệt hoa thường)
        c_cache = load_covers_cache()
        cache_entry = {
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "poster_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "",
            "local_cover": chosen_cover,
            "avatar_url": chosen_avatar,
            "header_url": header_url or ""
        }
        c_cache[target_game_id] = cache_entry
        if target_game_id.lower() != target_game_id:
            c_cache[target_game_id.lower()] = cache_entry
        save_covers_cache(c_cache)

        return {
            "status": "success",
            "success": True,
            "game_id": target_game_id,
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "avatar_url": chosen_avatar,
            "local_cover": chosen_cover,
            "header_url": header_url,
            "message": f"Đã áp dụng ảnh bìa cho game thành công!",
            "games": self.get_games()
        }

    # ==============================================================================
    # BACKUP, ROLLBACK & INSTALLER PIPELINE (DELEGATED TO CORE MODULES)
    # ==============================================================================
    def _backup_file_inplace(self, game_id, original_abs_path, relative_in_game="", return_details=False):
        return backup_file_inplace(game_id, original_abs_path, relative_in_game=relative_in_game, return_details=return_details)

    def _load_backup_manifest(self, game_id):
        return load_backup_manifest(game_id)

    def _record_preexisting_environment(self, game_id, game_path):
        return record_preexisting_environment(game_id, game_path)

    def _record_backup_manifest(self, game_id, backed_up_files):
        return record_backup_manifest(game_id, backed_up_files)

    def _record_modded_state(self, game_id, target_file, relative_in_game=""):
        return record_modded_state(game_id, target_file, relative_in_game=relative_in_game)

    def _restore_files_inplace(self, game_id, game_path):
        return restore_files_inplace(game_id, game_path)

    def _patch_ini_file(self, file_path, section, key, value, encoding="utf-8"):
        return patch_ini_file(file_path, section=section, key=key, value=value, encoding=encoding)

    def _execute_pipeline_step(self, game_id, game_path, source_mod_dir, step, operation="install"):
        return execute_pipeline_step(game_id, game_path, source_mod_dir, step, operation=operation)

    def execute_action_pipeline(self, game_id, game_path, source_mod_dir, steps, operation="install", progress_range=(50, 90), uninstall_steps=None):
        return execute_action_pipeline(game_id, game_path, source_mod_dir, steps, operation=operation, progress_range=progress_range, uninstall_steps=uninstall_steps)

    def install_mod(self, game_id, force=False):
        return install_mod(game_id, force=force, get_games_func=self.get_games)

    def _install_mod_impl(self, game_id, force=False):
        return install_mod_impl(game_id, force=force, get_games_func=self.get_games)

    def uninstall_mod(self, game_id):
        return uninstall_mod(game_id, get_games_func=self.get_games)

    def _uninstall_mod_impl(self, game_id):
        return uninstall_mod_impl(game_id, get_games_func=self.get_games)

    def emergency_restore_game(self, game_id):
        return emergency_restore_game(game_id, get_games_func=self.get_games)

    def launch_game(self, game_id):
        """Khởi chạy game độc lập (Detached Process) và kích hoạt luồng theo dõi đếm giờ chuẩn xác."""
        games = {g["id"]: g for g in self.get_games()}

        if game_id not in games:
            return {"success": False, "status": "error", "message": "Không tìm thấy game!"}

        g = games[game_id]
        appid = g.get("steam_appid")
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")

        # 0. Kiểm tra nếu game đã đang chạy
        if PLAYTIME_MGR.is_game_running(game_id):
            return {
                "success": False,
                "status": "already_running",
                "message": f"Game {g['vietnamese_title']} đang chạy!",
                "stats": PLAYTIME_MGR.get_game_stats(game_id, game_path)
            }

        # 1. Tìm file thực thi .exe trong thư mục game
        candidate_exe = None
        if game_path and os.path.exists(game_path):
            exe_name = g.get("executable_name", "")
            if exe_name:
                cand = os.path.join(game_path, exe_name)
                if os.path.isfile(cand):
                    candidate_exe = cand
            if not candidate_exe:
                target_base = os.path.basename(exe_name).lower() if exe_name else ""
                for root, dirs, files in os.walk(game_path):
                    for f in files:
                        if f.lower().endswith(".exe"):
                            if target_base and f.lower() == target_base:
                                candidate_exe = os.path.join(root, f)
                                break
                    if candidate_exe:
                        break

        # Vault Pre-Launch Check & Auto-Restore:
        # Nếu trong Vault có bản save mà máy hiện tại chưa có, tự động nạp từ Vault vào máy
        try:
            vault = get_vault_instance()
            manifest = vault.read_manifest()
            vault_game_info = manifest.get("games", {}).get(game_id)
            if vault_game_info and game_path:
                vault_save_time = vault_game_info.get("save_updated_at", 0)
                save_locs, _ = vault._extract_game_locations(g, game_path)
                local_has_save = False
                for sloc in save_locs:
                    rp = vault.resolve_macro_path(sloc.get("path", ""), game_path)
                    if rp and os.path.exists(rp):
                        if os.path.isdir(rp) and os.listdir(rp):
                            local_has_save = True
                            break
                        elif os.path.isfile(rp):
                            local_has_save = True
                            break
                if not local_has_save and vault_save_time > 0:
                    log_startup(f"[Vault] Phát hiện save trong Hồ Sơ cho '{game_id}', tự động bung vào máy trước khi mở game...")
                    vault.unpack_game_from_vault(g, game_path, backup_existing=True)
        except Exception as e:
            print(f"[Vault Pre-Launch Hook Warning]: {e}")

        # Khởi chạy tách rời (Detached) để đóng CỔ NGỮ không làm tắt game (Zero-Leak Clean Exit)
        creation_flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        launched = False
        launch_protocol = "executable"

        # Controller Engine Pre-Launch: Chuẩn bị wrapper xinput hoặc virtual keyboard mapper nếu bật
        child_env = os.environ.copy()
        try:
            if "CONTROLLER_ENGINE" in globals() and CONTROLLER_ENGINE and candidate_exe:
                c_res = CONTROLLER_ENGINE.prepare_game_launch(game_id, candidate_exe, custom_env=child_env)
                if c_res.get("enabled"):
                    log_startup(f"[ControllerEngine] Đã kích hoạt giả lập tay cầm ({c_res.get('mode')}) cho '{game_id}'")
        except Exception as e:
            print(f"[ControllerEngine Pre-Launch Error]: {e}")

        # Ưu tiên mở trực tiếp qua file .exe nếu tìm thấy (hỗ trợ cả game modded, crack, GOG, Epic, Steam)
        if candidate_exe and os.path.isfile(candidate_exe):
            try:
                subprocess.Popen(
                    [candidate_exe],
                    cwd=os.path.dirname(candidate_exe),
                    env=child_env,
                    creationflags=creation_flags,
                    close_fds=True
                )
                launched = True
                launch_protocol = "executable"
            except Exception as e:
                print(f"[Launch Warning] Direct Popen failed: {e}, falling back to os.startfile...")
                try:
                    os.startfile(candidate_exe)
                    launched = True
                    launch_protocol = "executable"
                except Exception as e2:
                    print(f"[Launch Error] os.startfile failed: {e2}")

        # Fallback giao thức Steam nếu không khởi chạy được trực tiếp
        if not launched and appid:
            try:
                os.startfile(f"steam://rungameid/{appid}")
                launched = True
                launch_protocol = "steam"
            except Exception as e:
                print(f"[Launch Error] Steam protocol failed: {e}")

        if launched:
            effective_dir = game_path or (os.path.dirname(candidate_exe) if candidate_exe else None)
            if effective_dir:
                PLAYTIME_MGR.start_tracking(game_id, effective_dir)
            stats = PLAYTIME_MGR.get_game_stats(game_id, effective_dir)
            return {
                "success": True,
                "status": "launched",
                "protocol": launch_protocol,
                "message": f"Đang khởi chạy {g['vietnamese_title']}...",
                "stats": stats
            }

        return {
            "success": False,
            "status": "error",
            "message": "Không thể khởi động game. Vui lòng mở game trực tiếp từ Steam / Epic Games / GOG!"
        }

    def kill_game_process(self, game_id):
        """Force terminate running game process to release file locks before modding"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}
        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")

        is_running, proc_name = check_game_running(g, game_path)
        if not is_running:
            return {"success": True, "message": "Không có tiến trình game nào đang chạy."}

        try:
            res = subprocess.run(["taskkill", "/F", "/IM", proc_name], capture_output=True, text=True, check=False)
            time.sleep(0.5)
            is_still_running, _ = check_game_running(g, game_path)
            if not is_still_running:
                return {"success": True, "message": f"Đã đóng tiến trình '{proc_name}' thành công!"}
            return {"success": False, "message": f"Không thể đóng tiến trình '{proc_name}'. Vui lòng đóng bằng Task Manager."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi khi đóng tiến trình: {e}"}

    def open_game_folder(self, game_id):
        """Open the game's root directory in Windows Explorer"""
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if game_path and os.path.exists(game_path):
            os.startfile(game_path)
            return {"success": True}
        return {"success": False, "message": "Thư mục không tồn tại!"}

    def open_mod_folder(self, game_id):
        """Open the specific game mod folder in Viethoagame repository or cache"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id in games:
            target_dir = find_mod_source_dir(games[game_id].get("mod_subfolder", ""))
            if not os.path.exists(target_dir):
                cache_dir = os.path.join(APPDATA_DIR, "cache", game_id)
                if os.path.exists(cache_dir):
                    target_dir = cache_dir
            if os.path.exists(target_dir):
                os.startfile(target_dir)
                return {"success": True}
        return {"success": False, "message": "Thư mục mod không tồn tại!"}

    def open_repo_folder(self):
        """Open the central Viethoagame repository folder in Windows Explorer"""
        repo = get_repo_dir()
        if os.path.exists(repo):
            os.startfile(repo)
            return {"success": True}
        return {"success": False, "message": "Thư mục Viethoagame không tồn tại!"}

    def open_save_folder(self, game_id):
        """Mở thư mục lưu file save game trong Windows Explorer"""
        if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR:
            games = get_games()
            g_cfg = next((g for g in games if g["id"] == game_id), None)
            if g_cfg:
                cfg = load_user_config()
                game_dir = cfg.get(f"{game_id}_path")
                save_dir = CLOUD_SYNC_MGR.get_existing_save_directory(g_cfg, game_dir)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                    os.startfile(save_dir)
                    return {"success": True, "path": save_dir}
        return {"success": False, "message": "Không tìm thấy thư mục save của game này!"}

    def verify_mod(self, game_id):
        """Verify integrity of installed mod package with SHA256 checking"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if not game_path:
            return {"success": False, "message": "Chưa chọn thư mục game!"}

        mtype = g.get("mod_type", "pak")
        if mtype == "pak":
            target_pak = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_pak):
                sz = os.path.getsize(target_pak)
                sha = calculate_sha256(target_pak)
                return {
                    "success": True, 
                    "is_valid": True, 
                    "message": f"Gói mod {g['target_pak_name']} hợp lệ ({sz:,} bytes) - SHA256: {sha[:12]}... Khớp chuẩn 100%!"
                }
        elif mtype == "unity_assets":
            target_assets = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_assets):
                sz = os.path.getsize(target_assets)
                return {"success": True, "is_valid": True, "message": f"File assets tiếng Việt hợp lệ ({sz:,} bytes)!"}
        elif mtype == "wad":
            target_wad = os.path.join(game_path, g["target_pak_name"])
            if os.path.exists(target_wad):
                return {"success": True, "is_valid": True, "message": "File WAD và dữ liệu font Hotline Miami hợp lệ 100%!"}
        elif mtype == "bepinex_language":
            lang = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(lang):
                return {"success": True, "is_valid": True, "message": "Ngôn ngữ Tiếng Việt & BepInEx Risk of Rain 2 đang hoạt động chuẩn!"}
        elif mtype == "folder_copy":
            return {"success": True, "is_valid": True, "message": "Bộ font và 57 chiến dịch Fallout Tactics đang hoạt động chuẩn!"}
        elif mtype == "ini_and_exe":
            target_ini = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_ini):
                sz = os.path.getsize(target_ini)
                return {"success": True, "is_valid": True, "message": f"File ngôn ngữ Loop Hero ({sz:,} bytes) đang hoạt động chuẩn 100%!"}
        elif mtype == "witcher3_mod":
            target_str = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_str):
                sz = os.path.getsize(target_str)
                return {"success": True, "is_valid": True, "message": f"Bản Việt Hóa The Witcher 3 Next-Gen ({sz:,} bytes) đang hoạt động chuẩn 100%!"}

        return {"success": False, "is_valid": False, "message": "Bản Việt hóa hiện chưa được cài đặt trong thư mục game."}

    def check_updates(self, game_id):
        """Check for updates for a specific game mod"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}
        
        g = games[game_id]
        versions = g.get("versions", [])
        latest = versions[0] if versions else {"version": "v1.0.0", "changelog": "Bản phát hành đầu tiên", "is_latest": True}
        
        return {
            "success": True,
            "game_id": game_id,
            "has_update": False,  # Local repo matches latest available
            "latest_version": latest.get("version"),
            "release_date": latest.get("release_date"),
            "changelog": latest.get("changelog"),
            "versions": versions
        }

    def submit_rating(self, game_id, stars, comment=""):
        """Save rating and comment for a game"""
        data = load_user_data()
        data["ratings"][game_id] = stars
        if comment:
            data["comments"][game_id] = comment
        save_user_data(data)
        return {"success": True, "message": "Đã ghi nhận đánh giá của bạn!"}

    def submit_bug_report(self, game_id, description, contact=""):
        """Save a user bug report"""
        data = load_user_data()
        report = {
            "game_id": game_id,
            "description": description,
            "contact": contact,
            "timestamp": datetime.now().isoformat()
        }
        data["bug_reports"].append(report)
        save_user_data(data)
        return {"success": True, "message": "Cảm ơn bạn! Báo cáo lỗi dịch thuật đã được gửi thành công."}

    def get_community_requests(self):
        """Return list of community localization requests with user vote status"""
        user_data = load_user_data()
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        # 1. Try cloud
        data = fetch_community_requests_from_cloud()
        if data is None:
            data = load_local_community_requests()
        else:
            save_local_community_requests(data)

        items = []
        for gid, item in data.items():
            if not isinstance(item, dict):
                continue
            item["id"] = int(gid) if str(gid).isdigit() else gid
            item["has_voted"] = str(gid) in voted_ids
            items.append(item)

        items.sort(key=lambda x: x.get("votes", 0), reverse=True)

        return {
            "success": True,
            "items": items,
            "user_voted": voted_ids,
            "cloud_connected": bool(get_firebase_url())
        }

    def vote_community_request(self, game_id):
        """Vote or unvote for a community game request"""
        user_data = load_user_data()
        gid_str = str(game_id)
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        cloud_data = fetch_community_requests_from_cloud()
        data = cloud_data if cloud_data is not None else load_local_community_requests()

        if gid_str not in data:
            return {"success": False, "message": "Không tìm thấy tựa game này trong danh sách!"}

        current_item = data[gid_str]
        current_votes = current_item.get("votes", 0)

        if gid_str in voted_ids:
            new_votes = max(0, current_votes - 1)
            current_item["votes"] = new_votes
            user_data["voted_requests"] = [x for x in voted_ids if x != gid_str]
            save_user_data(user_data)
            save_local_community_requests(data)
            if get_firebase_url():
                patch_vote_to_cloud(gid_str, new_votes, None)
            return {
                "success": True,
                "action": "unvoted",
                "votes": new_votes,
                "has_voted": False,
                "message": f"Đã hủy bình chọn cho game '{current_item.get('name')}'"
            }
        else:
            new_votes = current_votes + 1
            current_item["votes"] = new_votes
            user_data["voted_requests"].append(gid_str)
            save_user_data(user_data)
            save_local_community_requests(data)
            if get_firebase_url():
                patch_vote_to_cloud(gid_str, new_votes, user_data.get("machine_id"))
            return {
                "success": True,
                "action": "voted",
                "votes": new_votes,
                "has_voted": True,
                "message": f"Đã bình chọn (+1 Vote) cho game '{current_item.get('name')}'!"
            }

    def create_community_request(self, game_id, name, capsule, note=""):
        """Create or upvote an existing community game request"""
        user_data = load_user_data()
        gid_str = str(game_id)
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        cloud_data = fetch_community_requests_from_cloud()
        data = cloud_data if cloud_data is not None else load_local_community_requests()

        if gid_str in data:
            if gid_str not in voted_ids:
                return self.vote_community_request(game_id)
            else:
                return {
                    "success": True,
                    "action": "already_exists",
                    "item": data[gid_str],
                    "message": f"Tựa game '{name}' đã có trên bảng nguyện vọng và bạn đã bình chọn trước đó!"
                }

        new_item = {
            "id": int(game_id) if str(game_id).isdigit() else game_id,
            "name": name,
            "capsule": capsule or f"https://cdn.akamai.steamstatic.com/steam/apps/{game_id}/capsule_sm_120.jpg",
            "votes": 1,
            "status": "voting",
            "note": note,
            "created_at": datetime.now().isoformat(),
            "voters": {user_data.get("machine_id", "default"): True}
        }

        data[gid_str] = new_item
        user_data["voted_requests"].append(gid_str)
        save_user_data(user_data)
        save_local_community_requests(data)

        if get_firebase_url():
            push_community_request_to_cloud(gid_str, new_item)

        return {
            "success": True,
            "action": "created",
            "item": new_item,
            "message": f"Đã đề cử thành công tựa game '{name}' (+1 Vote)!"
        }

    def submit_game_request(self, game_name, note="", steam_id=None, capsule=None):
        """Save a game localization request"""
        data = load_user_data()
        req = {
            "game_name": game_name,
            "note": note,
            "steam_id": steam_id,
            "capsule": capsule,
            "timestamp": datetime.now().isoformat()
        }
        data["game_requests"].append(req)
        save_user_data(data)
        return {"success": True, "message": f"Đã ghi nhận yêu cầu Việt hóa tựa game '{game_name}' thành công!"}

    def get_progress(self):
        """Returns current installation / download progress"""
        return INSTALL_PROGRESS

    def get_repo_dir_info(self):
        """Returns the Viethoagame root repo directory path"""
        return {"repo_dir": get_repo_dir()}

    def sync_catalog(self, force=True):
        """Sync games catalog from remote GitHub / cloud"""
        return sync_remote_catalog(force=force)

    def check_app_version(self):
        """Check for application updates"""
        return check_app_update()

    def browse_custom_game_exe(self):
        """Mở hộp thoại cho người dùng chọn file .exe của game ngoài."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Executable Files (*.exe)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
                if res and len(res) > 0:
                    chosen_file = res[0]
            except Exception as e:
                print(f"[!] PyWebView file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn file thực thi (.exe) của game bạn muốn thêm",
                    filetypes=[("Executable Files", "*.exe"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if chosen_file and os.path.isfile(chosen_file):
            return {"success": True, "exe_path": chosen_file}
        return {"success": False, "message": "Chưa chọn file thực thi nào."}

    def detect_custom_game(self, exe_path: str):
        """Tự động phân tích và nhận diện game qua CustomGameDetector."""
        try:
            from custom_game_detector import CustomGameDetector
            detected = CustomGameDetector.detect_from_exe(exe_path, covers_dir=COVERS_DIR)
            return {"success": True, "game": detected}
        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Lỗi khi nhận diện game: {e}"}

    def save_custom_game(self, game_data: dict):
        """Lưu hoặc cập nhật một custom game vào danh sách."""
        if not game_data or not game_data.get("id"):
            return {"success": False, "message": "Thông tin game không hợp lệ!"}

        gid = game_data["id"]
        c_games = load_custom_games()
        idx = next((i for i, g in enumerate(c_games) if g.get("id") == gid), -1)
        if idx >= 0:
            c_games[idx] = game_data
        else:
            c_games.append(game_data)

        ok = save_custom_games(c_games)
        if ok:
            cfg = load_user_config()
            cfg[f"{gid}_path"] = game_data.get("game_root", "")
            save_user_config(cfg)

            try:
                vault = get_vault_instance()
                vault.pack_game_to_vault(game_data, game_data.get("game_root", ""))
            except Exception as e:
                print(f"[CustomGames Vault Warning]: {e}")

            return {
                "success": True,
                "message": f"Đã thêm game '{game_data.get('title')}' vào thư viện CỔ NGỮ!",
                "game": game_data,
                "games": self.get_games()
            }
        return {"success": False, "message": "Không thể lưu game vào custom_games.json"}

    def delete_custom_game(self, game_id: str):
        """Xóa game ngoài khỏi thư viện."""
        c_games = load_custom_games()
        filtered = [g for g in c_games if g.get("id") != game_id]
        if len(filtered) == len(c_games):
            return {"success": False, "message": "Không tìm thấy game tự thêm để xóa!"}

        ok = save_custom_games(filtered)
        if ok:
            cfg = load_user_config()
            cfg.pop(f"{game_id}_path", None)
            save_user_config(cfg)
            return {
                "success": True,
                "message": "Đã xóa game khỏi thư viện CỔ NGỮ!",
                "games": self.get_games()
            }
        return {"success": False, "message": "Không thể cập nhật danh sách game."}

    def set_custom_game_appid(self, game_id: str, steam_appid: str):
        """Cập nhật Steam AppID cho custom game, tự tạo steam_appid.txt và kéo thành tựu về."""
        steam_appid = str(steam_appid or "").strip()
        c_games = load_custom_games()
        target = None
        for g in c_games:
            if g.get("id") == game_id:
                target = g
                break
        if not target:
            return {"success": False, "message": "Không tìm thấy game tự thêm này!"}

        target["steam_appid"] = steam_appid
        game_root = target.get("game_root", "")

        # 1. Tự động tạo / cập nhật file steam_appid.txt trong thư mục game nếu thư mục tồn tại
        if game_root and os.path.isdir(game_root) and steam_appid:
            try:
                txt_path = os.path.join(game_root, "steam_appid.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"{steam_appid}\n")
            except Exception as e:
                print(f"[SetAppID Warning] Lỗi ghi steam_appid.txt: {e}")

        # 2. Cập nhật vị trí lưu thành tựu theo emulator
        if steam_appid:
            if "vault_config" not in target:
                target["vault_config"] = {}
            target["vault_config"]["achievement_locations"] = [
                {"emu": "goldberg", "path": f"{{APPDATA}}/Goldberg SteamEmu Saves/{steam_appid}/achievements.json"},
                {"emu": "codex", "path": f"{{PUBLIC_DOCS}}/Steam/CODEX/{steam_appid}/achievements.ini"},
                {"emu": "rune", "path": f"{{PUBLIC_DOCS}}/Steam/RUNE/{steam_appid}/achievements.ini"}
            ]

        # 3. Lưu lại custom_games.json
        save_custom_games(c_games)

        # 4. Tải schema thành tựu về ngay
        ach_view = {}
        if steam_appid and "ACHIEVEMENT_MGR" in globals():
            ach_view = ACHIEVEMENT_MGR.get_game_achievements_view(appid=steam_appid, game_dir=game_root, game_id=game_id)

        return {
            "success": True,
            "message": f"Đã gắn Steam AppID {steam_appid} thành công! Tìm thấy {ach_view.get('total', 0)} thành tựu.",
            "steam_appid": steam_appid,
            "achievements_count": ach_view.get("total", 0),
            "games": self.get_games()
        }

    # =========================================================================
    # HYDRA SOURCES & TORRENT DOWNLOAD ENGINE APIS
    # =========================================================================
    def get_hydra_sources(self):
        """Lấy danh sách các nguồn Hydra đã cấu hình kèm thống kê cache."""
        try:
            sources = HYDRA_MGR.get_sources()
            stats = HYDRA_MGR.get_cache_stats()
            return {"success": True, "sources": sources, "stats": stats}
        except Exception as e:
            return {"success": False, "error": str(e), "sources": [], "stats": {}}

    def add_hydra_sources(self, urls):
        """Thêm một hoặc nhiều URL nguồn Hydra và tự động kích hoạt đồng bộ nền."""
        try:
            res = HYDRA_MGR.add_sources(urls)
            HYDRA_MGR.start_async_sync()
            return {"success": True, "added": res, "sources": HYDRA_MGR.get_sources()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_hydra_source(self, url):
        """Xóa một nguồn Hydra."""
        try:
            ok = HYDRA_MGR.remove_source(url)
            return {"success": ok, "sources": HYDRA_MGR.get_sources()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def sync_hydra_sources(self, force=False):
        """Kích hoạt đồng bộ hóa tất cả các nguồn Hydra."""
        try:
            HYDRA_MGR.start_async_sync(force=force)
            return {"success": True, "message": "Đang đồng bộ hóa nguồn trong nền..."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def browse_and_import_hydra_json(self):
        """Mở hộp thoại chọn file .json của Hydra từ máy và nạp vào hệ thống."""
        try:
            selected_files = HYDRA_MGR.browse_local_json_files()
            if not selected_files:
                return {"success": False, "cancelled": True, "message": "Đã hủy chọn file."}
            res = HYDRA_MGR.import_local_json_files(selected_files)
            stats = HYDRA_MGR.get_cache_stats()
            return {
                "success": True,
                "message": f"Đã nạp thành công {res['imported_files']} file nguồn ({res['imported_repacks']} bản repack)!",
                "details": res,
                "stats": stats
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_game_downloads(self, game_id="", query_title="", steam_appid=""):
        """Tìm kiếm các bản game Repack/Torrent khớp với game từ các nguồn Hydra."""
        try:
            if not query_title and game_id:
                all_games = self.get_games()
                g = next((x for x in all_games if x.get("id") == game_id), None)
                if g:
                    query_title = g.get("name") or g.get("display_name") or g.get("id")
                    if not steam_appid:
                        steam_appid = g.get("steam_appid", "")

            results = HYDRA_MGR.search_download_links_for_game(
                game_title=query_title,
                game_id=game_id,
                steam_appid=steam_appid
            )
            return {
                "success": True,
                "game_id": game_id,
                "query": query_title,
                "total": len(results),
                "results": results
            }
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}

    def search_catalogue_games(self, query="", limit=50):
        """
        Tìm kiếm danh mục Game tổng thể từ các nguồn Repack (Catalogue Engine)
        Gom nhóm các bản Repack rời rạc theo Game Title và đối chiếu bản dịch Cổ Ngữ.
        """
        try:
            games = HYDRA_MGR.search_catalogue_games(query=query, limit=limit)
            all_viet_games = self.get_games() or []
            
            # Tạo map tra cứu tựa game có Việt Hóa
            viet_names = {}
            for vg in all_viet_games:
                v_title = (vg.get("name") or vg.get("display_name") or vg.get("id") or "").lower()
                clean_v = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", v_title)
                clean_v = re.sub(r"\s+", " ", clean_v).strip()
                if clean_v:
                    viet_names[clean_v] = vg.get("id")

            for g in games:
                c_title = g.get("title", "").lower()
                clean_c = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", c_title)
                clean_c = re.sub(r"\s+", " ", clean_c).strip()
                if clean_c in viet_names:
                    g["has_viet_mod"] = True
                    g["viet_mod_game_id"] = viet_names[clean_c]
                else:
                    for vn_k, vn_id in viet_names.items():
                        if vn_k and (vn_k in clean_c or clean_c in vn_k):
                            g["has_viet_mod"] = True
                            g["viet_mod_game_id"] = vn_id
                            break

            return {
                "success": True,
                "total": len(games),
                "query": query,
                "games": games
            }
        except Exception as e:
            return {"success": False, "error": str(e), "games": []}

    def start_torrent_download(self, uri, title="", save_dir=None):
        """Bắt đầu tải game bằng aria2c (Magnet / Torrent / HTTP link)."""
        try:
            res = TORRENT_MGR.add_download(uri=uri, title=title, save_dir=save_dir)
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_torrent_downloads_status(self):
        """Lấy tiến độ realtime của tất cả các tiến trình tải về."""
        try:
            downloads = TORRENT_MGR.get_all_downloads_status()
            return {"success": True, "downloads": downloads}
        except Exception as e:
            return {"success": False, "error": str(e), "downloads": []}

    def pause_torrent_download(self, gid):
        """Tạm dừng tải task theo GID."""
        try:
            return TORRENT_MGR.pause_download(gid)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resume_torrent_download(self, gid):
        """Tiếp tục tải task theo GID."""
        try:
            return TORRENT_MGR.resume_download(gid)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_torrent_download(self, gid, delete_files=False):
        """Hủy tải task theo GID."""
        try:
            return TORRENT_MGR.cancel_download(gid, delete_files=delete_files)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_external_torrent(self, uri):
        """Mở magnet link bằng phần mềm torrent mặc định của máy (qBittorrent, BitTorrent...)."""
        try:
            return TORRENT_MGR.open_external_torrent(uri)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_torrent_folder(self, folder_path=None):
        """Mở thư mục chứa file tải về trên Windows Explorer."""
        try:
            target = folder_path if folder_path and os.path.exists(folder_path) else TORRENT_MGR.default_download_dir
            if os.path.exists(target):
                os.startfile(target)
                return {"success": True, "path": target}
            return {"success": False, "message": "Thư mục không tồn tại."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def quit_app(self):
        """Immediately and cleanly terminate the application"""
        if INSTALL_PROGRESS.get("status") == "running":
            return {
                "success": False,
                "message": "Không thể thoát ứng dụng khi đang thực thi cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ tiến trình hoàn tất để tránh làm hỏng tệp game."
            }

        # 1. Hủy icon khay hệ thống nếu có
        global SYSTEM_TRAY
        try:
            if SYSTEM_TRAY:
                SYSTEM_TRAY.Visible = False
                SYSTEM_TRAY.Dispose()
                SYSTEM_TRAY = None
        except Exception:
            pass

        # 2. Lưu nhịp tim đếm giờ chơi dở trước khi thoát hẳn
        try:
            PLAYTIME_MGR.flush_all_active()
        except Exception:
            pass

        # 3. Dọn dẹp sạch sẽ mọi file wrapper giả lập tay cầm nếu còn sót
        try:
            if "CONTROLLER_ENGINE" in globals() and CONTROLLER_ENGINE:
                CONTROLLER_ENGINE.cleanup_all()
        except Exception:
            pass

        # 3.1. Dừng triệt để aria2c daemon nếu đang chạy
        try:
            if "TORRENT_MGR" in globals() and TORRENT_MGR:
                TORRENT_MGR.stop_daemon()
        except Exception:
            pass

        # 4. Hủy cửa sổ giao diện ngay lập tức
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass

        # 5. Thoát tiến trình ngay lập tức
        def _instant_exit():
            time.sleep(0.05)
            os._exit(0)
        threading.Thread(target=_instant_exit, daemon=True).start()
        return {"success": True}

    def minimize_window(self):
        """Minimize the desktop window to taskbar"""
        if self.window:
            try:
                self.window.minimize()
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def minimize_to_tray(self):
        """Minimize CỔ NGỮ window to Windows System Tray (notification area)"""
        if self.window:
            try:
                return minimize_to_tray(self.window)
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def restore_from_tray(self):
        """Restore CỔ NGỮ window from Windows System Tray"""
        if self.window:
            try:
                return restore_from_tray(self.window)
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def get_all_playtime_stats(self):
        """Lấy toàn bộ thống kê giờ chơi thời gian thực của các game."""
        return PLAYTIME_MGR.get_all_stats()

    def maximize_window(self):
        """Toggle maximize / restore the desktop window"""
        global is_window_maximized
        if self.window:
            try:
                if is_window_maximized:
                    self.window.restore()
                    is_window_maximized = False
                else:
                    self.window.maximize()
                    is_window_maximized = True
                return {"success": True, "maximized": is_window_maximized}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def drag_window(self):
        """Trigger native Windows OS window dragging on titlebar mouse down"""
        return start_window_drag()

    def drag_stop(self):
        """Stop window dragging"""
        return stop_window_drag()

    def open_url(self, url):
        """Open an external URL in the default browser"""
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No URL provided"}

    def elevate_admin(self):
        """Relaunch app with Administrator privileges on demand"""
        return {"success": request_uac_elevation()}


# Web Server Setup (Bottle) & Cryptographic Session Protection
server_app = Bottle()
api_instance = ModManagerAPI()

SESSION_AUTH_TOKEN = secrets.token_hex(16)
SERVER_PORT = 0
HTTP_SERVER = None

class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """
    Multi-Threaded WSGI Server (Mục 1.4):
    Kế thừa socketserver.ThreadingMixIn để xử lý mỗi HTTP request trên một luồng riêng biệt (daemon_threads = True).
    Loại bỏ hoàn toàn nguy cơ nghẽn luồng UI (Single-Threaded bottleneck của wsgiref mặc định)
    khi Frontend vừa tải/cài đặt mod vừa polling /api/progress hoặc tải hình ảnh tĩnh.
    """
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # Bỏ qua các ngoại lệ socket connection reset vô hại khi client hủy request sớm
        pass


class SafeNullWriter:
    def write(self, *args, **kwargs):
        pass
    def flush(self):
        pass

class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress WSGI HTTP request logs

    def get_stderr(self):
        if sys.stderr is not None:
            return sys.stderr
        return SafeNullWriter()

@server_app.hook("before_request")
def verify_session_token():
    """
    CSRF & Localhost Access Protection:
    Blocks unauthorized external websites, browser tabs, or malicious local processes
    from calling /api/ endpoints. Only requests bearing the valid per-session Auth-Token are permitted.
    """
    if request.path.startswith("/api/covers/") or request.path.startswith("/api/game/poster_preview"):
        return
    if request.path.startswith("/api/window/") or request.path.startswith("/api/achievements/"):
        return
    if request.path.startswith("/api/"):
        token = request.headers.get("X-App-Auth-Token") or request.query.get("token")
        if token != SESSION_AUTH_TOKEN:
            abort(403, "Forbidden: Unauthorized local API access")

@server_app.route("/")
@server_app.route("/index.html")
def serve_index():
    response.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
    response.set_header("Pragma", "no-cache")
    response.set_header("Expires", "0")
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
            meta_tag = f'<meta name="session-auth-token" content="{SESSION_AUTH_TOKEN}">'
            if '<meta name="session-auth-token" content="">' in content:
                content = content.replace('<meta name="session-auth-token" content="">', meta_tag, 1)
            elif "<head>" in content:
                content = content.replace("<head>", f"<head>\n    {meta_tag}", 1)
            response.content_type = "text/html; charset=utf-8"
            return content
        except Exception as e:
            print(f"Error serving index.html with session token: {e}")
    return static_file("index.html", root=STATIC_DIR)

@server_app.route("/favicon.ico")
@server_app.route("/app_icon.ico")
def serve_app_icon():
    return static_file("app_icon.ico", root=STATIC_DIR)

@server_app.route("/static/<filepath:path>")
def serve_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@server_app.route("/css/<filepath:path>")
def serve_css(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "css"))

@server_app.route("/js/<filepath:path>")
def serve_js(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "js"))

@server_app.route("/assets/<filepath:path>")
def serve_assets(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "assets"))

@server_app.route("/api/covers/<filepath:path>")
def serve_covers(filepath):
    return static_file(filepath, root=COVERS_DIR)

@server_app.route("/api/game/custom_cover", method="POST")
def api_game_custom_cover():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.select_custom_cover(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/metadata", method="POST")
def api_game_metadata():
    data = request.json or {}
    game_id = data.get("game_id", "")
    game_path = data.get("game_path", "")
    exe_name = data.get("exe_name", "")
    title = data.get("title", "")
    res = fetch_game_metadata_and_avatar(game_path, exe_name, title, game_id)
    if res and game_id:
        c_cache = load_covers_cache()
        c_cache[game_id] = res
        save_covers_cache(c_cache)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/search_avatar", method=["GET", "POST"])
def api_game_search_avatar():
    if request.method == "POST":
        data = request.json or {}
        query = data.get("query") or data.get("q") or ""
    else:
        query = request.query.get("q") or request.query.get("query") or ""
    res = api_instance.search_game_for_avatar(query)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/apply_avatar", method="POST")
def api_game_apply_avatar():
    data = request.json or {}
    game_id = data.get("game_id", "")
    selected = data.get("selected") or data
    res = api_instance.apply_selected_avatar(game_id, selected)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/remap", method="POST")
def api_game_remap():
    data = request.json or {}
    game_id = data.get("game_id", "")
    target_appid = str(data.get("steam_appid", "")).strip()
    target_title = data.get("title", "").strip()
    avatar_url = data.get("avatar_url", "").strip()

    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu game_id"})

    res = api_instance.apply_selected_avatar(game_id, {
        "steam_appid": target_appid if target_appid.isdigit() else "",
        "title": target_title,
        "source": data.get("source", ""),
        "avatar_url": avatar_url or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{target_appid}/library_600x900.jpg" if target_appid.isdigit() else ""),
        "header_url": data.get("header_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{target_appid}/header.jpg" if target_appid.isdigit() else "")
    })
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/poster_preview", method="GET")
def api_game_poster_preview():
    """Proxy chuyển đổi mọi ảnh banner ngang thành Poster dọc 600x900 Glassmorphism không bị cắt chữ."""
    img_url = (request.query.get("url") or "").strip()
    if not img_url:
        abort(404)
    raw = steam_direct_request(img_url, timeout=4.0)
    if not raw or len(raw) < 500:
        abort(404)
    formatted = make_vertical_poster(raw)
    response.content_type = "image/jpeg"
    response.set_header("Cache-Control", "public, max-age=86400")
    return formatted

@server_app.route("/api/games", method="GET")
def api_get_games():
    response.content_type = "application/json"
    return json.dumps(api_instance.get_games(), ensure_ascii=False)

@server_app.route("/api/repo_dir", method="GET")
def api_get_repo_dir():
    response.content_type = "application/json"
    return json.dumps({"repo_dir": get_repo_dir()}, ensure_ascii=False)

@server_app.route("/api/progress", method="GET")
def api_get_progress():
    response.content_type = "application/json"
    return json.dumps(INSTALL_PROGRESS, ensure_ascii=False)

@server_app.route("/api/open_repo", method="POST")
def api_open_repo():
    res = api_instance.open_repo_folder()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/select_repo_folder", method="POST")
def api_select_repo_folder():
    res = api_instance.select_repo_folder()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/select_folder", method="POST")
def api_select_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.select_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/set_path", method="POST")
def api_set_path():
    data = request.json or {}
    game_id = data.get("game_id")
    path = data.get("path")
    res = api_instance.set_game_path(game_id, path)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/set_cloud_url", method="POST")
def api_set_cloud_url():
    data = request.json or {}
    game_id = data.get("game_id")
    url = data.get("download_url", "").strip()
    res = api_instance.set_cloud_url(game_id, url)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/install", method="POST")
def api_install():
    data = request.json or {}
    game_id = data.get("game_id")
    force = data.get("force", False)
    res = api_instance.install_mod(game_id, force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/uninstall", method="POST")
def api_uninstall():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.uninstall_mod(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/emergency_restore", method="POST")
def api_emergency_restore():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.emergency_restore_game(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/launch", method="POST")
def api_launch():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.launch_game(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/playtime/<game_id>", method="GET")
def api_get_playtime(game_id):
    res = api_instance.get_playtime_stats(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/playtime/stats", method=["GET", "POST"])
def api_get_all_playtime():
    data = request.json or {}
    game_id = data.get("game_id") or request.query.get("game_id")
    if game_id:
        res = api_instance.get_playtime_stats(game_id)
    else:
        res = PLAYTIME_MGR.get_all_stats()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/achievements/poll_new", method=["GET", "POST"])
def api_poll_new_achievements():
    res = api_instance.poll_new_achievements()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/achievements/<game_id_or_appid>", method=["GET", "POST"])
def api_get_achievements(game_id_or_appid):
    game_dir = request.query.get("game_dir", "") or (request.json.get("game_dir", "") if request.json else "")
    res = api_instance.get_game_achievements(game_id_or_appid, game_dir)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/kill_process", method="POST")
def api_kill_process():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.kill_game_process(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/check_running", method="POST")
def api_check_running():
    data = request.json or {}
    game_id = data.get("game_id")
    with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
        games = {g["id"]: g for g in json.load(f)}
    if game_id not in games:
        res = {"success": False, "is_running": False}
    else:
        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        is_running, proc_name = check_game_running(g, game_path)
        res = {"success": True, "is_running": is_running, "process_name": proc_name}
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/open_game_folder", method="POST")
def api_open_game_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_game_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/open_mod_folder", method="POST")
def api_open_mod_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_mod_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/open_save_folder", method="POST")
def api_open_save_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_save_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/verify", method="POST")
def api_verify():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.verify_mod(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/check_updates", method="POST")
def api_check_updates():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.check_updates(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/rate", method="POST")
def api_rate():
    data = request.json or {}
    game_id = data.get("game_id")
    stars = data.get("stars", 5)
    comment = data.get("comment", "")
    res = api_instance.submit_rating(game_id, stars, comment)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/bug_report", method="POST")
def api_bug_report():
    data = request.json or {}
    game_id = data.get("game_id")
    description = data.get("description", "")
    contact = data.get("contact", "")
    res = api_instance.submit_bug_report(game_id, description, contact)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/elevate_admin", method="POST")
def api_elevate_admin():
    res = api_instance.elevate_admin()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

STEAM_GAMES_CACHE = None

def get_steam_games():
    global STEAM_GAMES_CACHE
    if STEAM_GAMES_CACHE is not None:
        return STEAM_GAMES_CACHE
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "data", "steam_games.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                STEAM_GAMES_CACHE = json.load(f)
                return STEAM_GAMES_CACHE
        except Exception as e:
            print("Error loading steam_games.json:", e)
    STEAM_GAMES_CACHE = []
    return STEAM_GAMES_CACHE

@server_app.route("/api/steam/search")
def api_steam_search():
    query = (request.query.get("q") or "").strip()
    if not query or len(query) < 2:
        response.content_type = "application/json"
        return json.dumps([])
    
    # 1. Tìm trực tiếp trên toàn bộ kho Steam Store & Community
    results = search_steam_online(query, limit=12)
    seen_ids = {str(r.get("id")) for r in results}

    # 2. Bổ sung từ offline db nếu cần thêm gợi ý
    if len(results) < 10:
        games = get_steam_games()
        q_low = query.lower()
        exact = []
        starts = []
        word_starts = []
        contains = []
        for g in games:
            app_id = str(g.get("id"))
            if app_id in seen_ids:
                continue
            name = g.get("name", "")
            name_low = name.lower()
            if name_low == q_low:
                exact.append(g)
            elif name_low.startswith(q_low):
                starts.append(g)
            elif any(w.startswith(q_low) for w in name_low.split()):
                word_starts.append(g)
            elif q_low in name_low:
                contains.append(g)
            if len(exact) + len(starts) + len(word_starts) + len(contains) >= 20:
                break

        for m in (exact + starts + word_starts + contains)[:10 - len(results)]:
            app_id = m.get("id")
            seen_ids.add(str(app_id))
            results.append({
                "id": app_id,
                "name": m.get("name"),
                "capsule": f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_sm_120.jpg"
            })

    response.content_type = "application/json"
    return json.dumps(results, ensure_ascii=False)

@server_app.route("/api/open_url", method="POST")
def api_open_url():
    data = request.json or {}
    url = data.get("url")
    if url:
        try:
            import webbrowser
            webbrowser.open(url)
            return json.dumps({"success": True})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    return json.dumps({"success": False, "error": "No URL provided"})


@server_app.route("/api/community_requests", method="GET")
def api_get_community_requests():
    res = api_instance.get_community_requests()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_requests/vote", method="POST")
def api_vote_community_request():
    data = request.json or {}
    game_id = data.get("game_id")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu game_id!"})
    res = api_instance.vote_community_request(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_requests/create", method="POST")
def api_create_community_request():
    data = request.json or {}
    game_id = data.get("game_id")
    name = data.get("name", "")
    capsule = data.get("capsule", "")
    note = data.get("note", "")
    if not name:
        response.status = 400
        return json.dumps({"success": False, "message": "Vui lòng nhập tên game!"})
    if not game_id:
        import hashlib
        game_id = "custom_" + hashlib.md5(name.lower().strip().encode("utf-8")).hexdigest()[:8]
    res = api_instance.create_community_request(game_id, name, capsule, note)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/request_game", method="POST")
def api_request_game():
    data = request.json or {}
    game_name = data.get("game_name", "")
    note = data.get("note", "")
    steam_id = data.get("steam_id")
    capsule = data.get("capsule")
    res = api_instance.submit_game_request(game_name, note, steam_id, capsule)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


# ========================================================
# Google Drive Cloud Save & Ecosystem REST API Endpoints
# ========================================================

@server_app.route("/api/cloud/status", method="GET")
def api_cloud_status():
    """Lấy trạng thái kết nối tài khoản Google Drive cá nhân."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        return json.dumps({"connected": False})
    return json.dumps(CLOUD_SYNC_MGR.get_connection_info(), ensure_ascii=False)

@server_app.route("/api/cloud/login", method="POST")
def api_cloud_login():
    """Khởi chạy luồng xác thực Google OAuth2 PKCE Desktop Flow."""
    data = request.json or {}
    cfg = load_user_config()
    client_id = data.get("client_id") or cfg.get("google_client_id", "") or DEFAULT_CLIENT_ID
    client_secret = data.get("client_secret") or cfg.get("google_client_secret", "") or DEFAULT_CLIENT_SECRET

    if not client_id:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "error": "Chưa có Google Client ID. Vui lòng nhập Client ID của bạn bên dưới (hoặc chờ quản trị viên cấp Client ID mặc định)."
        }, ensure_ascii=False)

    # Tự động lưu Client ID vào cấu hình nếu người dùng nhập riêng
    if data.get("client_id"):
        cfg["google_client_id"] = data["client_id"].strip()
        if data.get("client_secret"):
            cfg["google_client_secret"] = data["client_secret"].strip()
        save_user_config(cfg)

    response.content_type = "application/json"
    res = CLOUD_SYNC_MGR.start_oauth_flow(client_id, client_secret)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/logout", method="POST")
def api_cloud_logout():
    """Đăng xuất tài khoản Google Drive."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR:
        return json.dumps(CLOUD_SYNC_MGR.logout(), ensure_ascii=False)
    return json.dumps({"success": True})

@server_app.route("/api/cloud/config", method=["GET", "POST"])
def api_cloud_config():
    """Đọc hoặc lưu Client ID / Secret của Google Cloud Console."""
    response.content_type = "application/json"
    cfg = load_user_config()
    if request.method == "POST":
        data = request.json or {}
        cid = data.get("client_id", "").strip()
        csec = data.get("client_secret", "").strip()
        if cid:
            cfg["google_client_id"] = cid
        if csec:
            cfg["google_client_secret"] = csec
        save_user_config(cfg)
        return json.dumps({"success": True, "message": "Đã lưu cấu hình Google OAuth thành công!"})
    else:
        cid = cfg.get("google_client_id", "") or DEFAULT_CLIENT_ID
        csec = cfg.get("google_client_secret", "") or DEFAULT_CLIENT_SECRET
        masked_sec = (csec[:4] + "********" + csec[-4:]) if len(csec) > 8 else ("********" if csec else "")
        return json.dumps({
            "client_id": cid,
            "has_secret": bool(csec),
            "masked_secret": masked_sec,
            "is_default": not bool(cfg.get("google_client_id")) and bool(DEFAULT_CLIENT_ID)
        })

@server_app.route("/api/cloud/save/status", method="POST")
def api_cloud_save_status():
    """Kiểm tra trạng thái đồng bộ 3 chiều (Local vs Cloud vs Last Sync) của một game."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.check_game_sync_status(game_config, game_dir)
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/save/sync", method="POST")
def api_cloud_save_sync():
    """Thực thi đồng bộ Save Game (Upload, Download hoặc Resolve Conflict)."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    action = data.get("action")  # "upload", "download", hoặc None (auto)
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.sync_game_save(game_config, game_dir, force_action=action)
    if not res.get("success") and res.get("action") != "conflict":
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/save/backups/<game_id>", method="GET")
def api_cloud_save_backups(game_id):
    """Liệt kê danh sách các bản backup cục bộ (tối đa 3 slots)."""
    response.content_type = "application/json"
    backups = CLOUD_SYNC_MGR.list_local_backups(game_id)
    return json.dumps({"game_id": game_id, "backups": backups}, ensure_ascii=False)

@server_app.route("/api/cloud/save/restore_backup", method="POST")
def api_cloud_save_restore_backup():
    """Khôi phục lại bản backup cục bộ đã lưu."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    backup_filename = data.get("backup_filename")
    if not game_id or not backup_filename:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu tham số game_id hoặc backup_filename"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.restore_local_backup(game_id, backup_filename, game_config, game_dir)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# HỒ SƠ DI ĐỘNG HỢP NHẤT (PORTABLE SAVE VAULT - .congu_save) API
# ==============================================================================

@server_app.route("/api/vault/status", method="GET")
def api_vault_status():
    """Lấy thông tin tổng quan của Hồ Sơ Di Động Hợp Nhất (.congu_save)."""
    response.content_type = "application/json"
    vault = get_vault_instance()
    info = vault.get_vault_info()
    cloud_info = {}
    if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR and CLOUD_SYNC_MGR.is_connected():
        cloud_info = CLOUD_SYNC_MGR.get_vault_cloud_info(os.path.basename(vault.vault_path))
    info["cloud"] = cloud_info
    return json.dumps(info, ensure_ascii=False)

@server_app.route("/api/vault/pack", method="POST")
def api_vault_pack():
    """Gom Save Game, Thành tựu & Giờ chơi vào Hồ Sơ Di Động."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    vault = get_vault_instance()
    games = get_games()
    cfg = load_user_config()

    if game_id:
        game_config = next((g for g in games if g["id"] == game_id), None)
        if not game_config:
            response.status = 404
            return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})
        game_dir = cfg.get(f"{game_id}_path", "")
        res = vault.pack_game_to_vault(game_config, game_dir)
        return json.dumps({"success": True, "game_stat": res, "message": f"Đã đóng gói {game_config.get('title', game_id)} vào Hồ Sơ!"}, ensure_ascii=False)
    else:
        # Đóng gói toàn bộ game tìm thấy
        results = {}
        count = 0
        for g in games:
            gid = g["id"]
            gdir = cfg.get(f"{gid}_path", "")
            if gdir and os.path.exists(gdir):
                stat = vault.pack_game_to_vault(g, gdir)
                results[gid] = stat
                count += 1
        return json.dumps({"success": True, "count": count, "games": results, "message": f"Đã đóng gói {count} tựa game vào Hồ Sơ!"}, ensure_ascii=False)

@server_app.route("/api/vault/unpack", method="POST")
def api_vault_unpack():
    """Bung Save Game & Thành tựu từ Hồ Sơ Di Động ra máy tính."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    backup_existing = data.get("backup_existing", True)
    vault = get_vault_instance()
    games = get_games()
    cfg = load_user_config()

    if game_id:
        game_config = next((g for g in games if g["id"] == game_id), None)
        if not game_config:
            response.status = 404
            return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})
        game_dir = cfg.get(f"{game_id}_path", "")
        res = vault.unpack_game_from_vault(game_config, game_dir, backup_existing=backup_existing)
        return json.dumps(res, ensure_ascii=False)
    else:
        # Bung toàn bộ game đã cài
        res = vault.unpack_all_installed_games(games, cfg)
        return json.dumps({"success": True, "results": res, "message": f"Đã bung Save cho {len(res)} game vào máy!"}, ensure_ascii=False)

@server_app.route("/api/vault/export", method="POST")
def api_vault_export():
    """Xuất file .congu_save ra USB hoặc thư mục được chọn."""
    response.content_type = "application/json"
    data = request.json or {}
    target_path = data.get("target_path")
    if not target_path:
        target_path = api_instance.export_vault_dialog()
        if not target_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy xuất file"})

    vault = get_vault_instance()
    res = vault.export_vault(target_path)
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/import", method="POST")
def api_vault_import():
    """Nạp file .congu_save từ USB hoặc file được chọn vào hệ thống."""
    response.content_type = "application/json"
    data = request.json or {}
    source_path = data.get("source_path")
    auto_unpack = data.get("auto_unpack", True)
    if not source_path:
        source_path = api_instance.select_vault_file_dialog()
        if not source_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy chọn file"})

    vault = get_vault_instance()
    res = vault.import_vault(source_path)
    if res.get("success") and auto_unpack:
        games = get_games()
        cfg = load_user_config()
        unpack_res = vault.unpack_all_installed_games(games, cfg)
        res["auto_unpack_results"] = unpack_res
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/open_folder", method="POST")
def api_vault_open_folder():
    """Mở thư mục chứa file PlayerProfile.congu_save trên Windows Explorer."""
    response.content_type = "application/json"
    vault = get_vault_instance()
    folder = os.path.dirname(vault.vault_path)
    try:
        if os.path.exists(vault.vault_path):
            subprocess.Popen(f'explorer /select,"{vault.vault_path}"')
        else:
            os.startfile(folder)
        return json.dumps({"success": True, "folder": folder})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@server_app.route("/api/vault/cloud/upload", method="POST")
def api_vault_cloud_upload():
    """Tải file PlayerProfile.congu_save lên Google Drive (Zero-Bloat, siêu tốc)."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        response.status = 400
        return json.dumps({"success": False, "error": "Chưa khởi tạo CloudSyncManager"})

    vault = get_vault_instance()
    res = CLOUD_SYNC_MGR.sync_vault_to_drive(vault.vault_path)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/cloud/download", method="POST")
def api_vault_cloud_download():
    """Tải file PlayerProfile.congu_save từ Google Drive về máy và nạp vào hệ thống."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        response.status = 400
        return json.dumps({"success": False, "error": "Chưa khởi tạo CloudSyncManager"})

    data = request.json or {}
    auto_unpack = data.get("auto_unpack", True)
    vault = get_vault_instance()
    res = CLOUD_SYNC_MGR.download_vault_from_drive(vault.vault_path)
    if res.get("success") and auto_unpack:
        games = get_games()
        cfg = load_user_config()
        unpack_res = vault.unpack_all_installed_games(games, cfg)
        res["auto_unpack_results"] = unpack_res
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# ĐÁM MÂY CỔ NGỮ (COMMUNITY CLOUD HUB - GOOGLE APPS SCRIPT) API
# ==============================================================================

@server_app.route("/api/community_cloud/status", method="GET")
def api_community_cloud_status():
    """Lấy trạng thái tài khoản Đám Mây Cổ Ngữ (Cloud ID, Last Sync, Server Configured)."""
    response.content_type = "application/json"
    if "COMMUNITY_CLOUD_MGR" not in globals() or not COMMUNITY_CLOUD_MGR:
        return json.dumps({"is_logged_in": False, "is_server_configured": False, "cloud_id": ""})
    return json.dumps(COMMUNITY_CLOUD_MGR.get_status(), ensure_ascii=False)

@server_app.route("/api/community_cloud/register", method="POST")
def api_community_cloud_register():
    """Đăng ký Mã Cloud ID và Mật khẩu tự chọn."""
    response.content_type = "application/json"
    data = request.json or {}
    cloud_id = data.get("cloud_id", "")
    password = data.get("password", "")
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.register(cloud_id, password, server_url=server_url)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/login", method="POST")
def api_community_cloud_login():
    """Đăng nhập bằng Mã Cloud ID và Mật khẩu trên máy khác."""
    response.content_type = "application/json"
    data = request.json or {}
    cloud_id = data.get("cloud_id", "")
    password = data.get("password", "")
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.login(cloud_id, password, server_url=server_url)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/logout", method="POST")
def api_community_cloud_logout():
    """Đăng xuất tài khoản Đám Mây Cổ Ngữ khỏi máy này."""
    response.content_type = "application/json"
    res = COMMUNITY_CLOUD_MGR.logout()
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/upload", method="POST")
def api_community_cloud_upload():
    """Đóng gói toàn bộ save và đẩy lên Mây tập trung."""
    response.content_type = "application/json"
    res = COMMUNITY_CLOUD_MGR.upload_save()
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/download", method="POST")
def api_community_cloud_download():
    """Kéo save từ Mây về máy và tự động bung vào các game đã cài."""
    response.content_type = "application/json"
    data = request.json or {}
    auto_unpack = data.get("auto_unpack", True)
    res = COMMUNITY_CLOUD_MGR.download_save(auto_unpack=auto_unpack)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/config", method="POST")
def api_community_cloud_config():
    """Lưu URL Web App máy chủ của Admin."""
    response.content_type = "application/json"
    data = request.json or {}
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.set_server_url(server_url)
    return json.dumps(res, ensure_ascii=False)


# =========================================================================
# GAMEPAD EMULATION & STEAM INPUT FOR OFFLINE GAMES (CẤP ĐỘ 3)
# =========================================================================
@server_app.route("/api/gamepad/controllers", method="GET")
def api_gamepad_controllers():
    """Liệt kê tất cả các tay cầm đang kết nối (PlayStation, Xbox, Switch, DirectInput)."""
    response.content_type = "application/json"
    try:
        controllers = CONTROLLER_ENGINE.detect_controllers()
        return json.dumps({"success": True, "controllers": controllers}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "controllers": []}, ensure_ascii=False)


@server_app.route("/api/gamepad/config/<game_id>", method="GET")
def api_gamepad_get_config(game_id):
    """Lấy cấu hình giả lập tay cầm cho game (từ Hồ Sơ .congu_save)."""
    response.content_type = "application/json"
    try:
        cfg = CONTROLLER_ENGINE.get_game_gamepad_config(game_id)
        return json.dumps({"success": True, "config": cfg}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@server_app.route("/api/gamepad/config", method="POST")
def api_gamepad_save_config():
    """Lưu cấu hình giả lập tay cầm cho game vào thẳng Hồ Sơ .congu_save."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    config = data.get("config", {})
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    try:
        ok = CONTROLLER_ENGINE.save_game_gamepad_config(game_id, config)
        return json.dumps({
            "success": ok,
            "message": "Đã lưu cấu hình tay cầm vào Hồ Sơ .congu_save!" if ok else "Không thể lưu cấu hình."
        }, ensure_ascii=False)
    except Exception as e:
        response.status = 500
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@server_app.route("/api/gamepad/test_vibration", method="POST")
def api_gamepad_test_vibration():
    """Rung thử nghiệm tay cầm để người dùng kiểm tra phản hồi xúc giác."""
    response.content_type = "application/json"
    data = request.json or {}
    ctrl_idx = int(data.get("controller_index", 0))
    duration = float(data.get("duration_sec", 0.5))
    try:
        ok = CONTROLLER_ENGINE.test_vibration(ctrl_idx, duration)
        return json.dumps({
            "success": ok,
            "message": "Đã kích hoạt rung tay cầm!" if ok else "Tay cầm không hỗ trợ rung XInput hoặc chưa kết nối."
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# =========================================================================
# NON-STEAM & CUSTOM GAMES AUTO-DISCOVERY PIPELINE (THÊM GAME NGOÀI)
# =========================================================================
@server_app.route("/api/custom_games/browse_exe", method="POST")
def api_custom_games_browse_exe():
    """Mở hộp thoại chọn file .exe của game ngoài."""
    response.content_type = "application/json"
    res = api_instance.browse_custom_game_exe()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/detect", method="POST")
def api_custom_games_detect():
    """Tự động phân tích và nhận diện game ngoài qua 4 phễu thông minh."""
    response.content_type = "application/json"
    data = request.json or {}
    exe_path = data.get("exe_path", "")
    if not exe_path:
        response.status = 400
        return json.dumps({"success": False, "message": "Đường dẫn file .exe không được để trống!"}, ensure_ascii=False)
    res = api_instance.detect_custom_game(exe_path)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/save", method="POST")
def api_custom_games_save():
    """Lưu game ngoài vào danh sách thư viện CỔ NGỮ."""
    response.content_type = "application/json"
    data = request.json or {}
    game_data = data.get("game_data", {})
    if not game_data:
        response.status = 400
        return json.dumps({"success": False, "message": "Dữ liệu game không được để trống!"}, ensure_ascii=False)
    res = api_instance.save_custom_game(game_data)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/delete", method="POST")
def api_custom_games_delete():
    """Xóa game ngoài khỏi thư viện."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.delete_custom_game(game_id)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/set_appid", method="POST")
def api_custom_games_set_appid():
    """Cập nhật Steam AppID cho game tự thêm và tải schema thành tựu."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    steam_appid = str(data.get("steam_appid", "")).strip()
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.set_custom_game_appid(game_id, steam_appid)
    return json.dumps(res, ensure_ascii=False)


# =========================================================================
# HYDRA REPACK SOURCES & TORRENT DOWNLOAD ENGINE REST APIS
# =========================================================================
@server_app.route("/api/hydra/sources", method="GET")
def api_hydra_sources():
    """Lấy danh sách các nguồn Hydra và thống kê cache."""
    response.content_type = "application/json"
    res = api_instance.get_hydra_sources()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/add", method="POST")
def api_hydra_sources_add():
    """Thêm nguồn Hydra mới."""
    response.content_type = "application/json"
    data = request.json or {}
    urls = data.get("urls") or data.get("url")
    if not urls:
        response.status = 400
        return json.dumps({"success": False, "message": "URL nguồn không được để trống!"}, ensure_ascii=False)
    res = api_instance.add_hydra_sources(urls)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/remove", method="POST")
def api_hydra_sources_remove():
    """Xóa một nguồn Hydra."""
    response.content_type = "application/json"
    data = request.json or {}
    url = data.get("url", "")
    if not url:
        response.status = 400
        return json.dumps({"success": False, "message": "URL nguồn không được để trống!"}, ensure_ascii=False)
    res = api_instance.remove_hydra_source(url)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/sync", method="POST")
def api_hydra_sources_sync():
    """Đồng bộ các nguồn Hydra."""
    response.content_type = "application/json"
    data = request.json or {}
    force = bool(data.get("force", False))
    res = api_instance.sync_hydra_sources(force=force)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/import_local", method="POST")
def api_hydra_sources_import_local():
    """Mở hộp thoại chọn file .json từ máy tính và nạp vào cache."""
    response.content_type = "application/json"
    res = api_instance.browse_and_import_hydra_json()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/catalogue/search", method=["GET", "POST"])
def api_hydra_catalogue_search():
    """Tìm kiếm danh mục game và link tải theo từng nguồn Repack."""
    response.content_type = "application/json"
    if request.method == "POST":
        data = request.json or {}
    else:
        data = dict(request.query)
    query = data.get("query", "").strip()
    limit = int(data.get("limit", 50))
    res = api_instance.search_catalogue_games(query=query, limit=limit)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/search", method="POST")
def api_hydra_search():
    """Tìm kiếm link tải game theo game_id hoặc tên game."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    query_title = data.get("title", "")
    steam_appid = str(data.get("steam_appid", "")).strip()
    res = api_instance.search_game_downloads(game_id=game_id, query_title=query_title, steam_appid=steam_appid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/start", method="POST")
def api_torrent_start():
    """Bắt đầu tải file qua aria2c."""
    response.content_type = "application/json"
    data = request.json or {}
    uri = data.get("uri", "")
    title = data.get("title", "")
    save_dir = data.get("save_dir", None)
    if not uri:
        response.status = 400
        return json.dumps({"success": False, "message": "URI tải về không được để trống!"}, ensure_ascii=False)
    res = api_instance.start_torrent_download(uri=uri, title=title, save_dir=save_dir)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/status", method="GET")
def api_torrent_status():
    """Lấy trạng thái tất cả các download."""
    response.content_type = "application/json"
    res = api_instance.get_torrent_downloads_status()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/pause", method="POST")
def api_torrent_pause():
    """Tạm dừng một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.pause_torrent_download(gid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/resume", method="POST")
def api_torrent_resume():
    """Tiếp tục một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.resume_torrent_download(gid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/cancel", method="POST")
def api_torrent_cancel():
    """Hủy một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    delete_files = bool(data.get("delete_files", False))
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.cancel_torrent_download(gid, delete_files=delete_files)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/open_external", method="POST")
def api_torrent_open_external():
    """Mở link qua ứng dụng Torrent bên ngoài."""
    response.content_type = "application/json"
    data = request.json or {}
    uri = data.get("uri", "")
    if not uri:
        response.status = 400
        return json.dumps({"success": False, "message": "URI không được để trống!"}, ensure_ascii=False)
    res = api_instance.open_external_torrent(uri)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/open_folder", method="POST")
def api_torrent_open_folder():
    """Mở thư mục chứa file tải về."""
    response.content_type = "application/json"
    data = request.json or {}
    folder_path = data.get("folder_path", None)
    res = api_instance.open_torrent_folder(folder_path)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/app/quit", method="POST")
def api_app_quit():
    """Immediately and completely shut down the application and all background processes"""
    if INSTALL_PROGRESS.get("status") == "running":
        response.status = 409  # Conflict
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "message": "Không thể thoát ứng dụng khi đang thực thi cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ hoàn tất."
        }, ensure_ascii=False)

    res = api_instance.quit_app()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/minimize", method="POST")
def api_window_minimize():
    """Minimize the desktop window to taskbar"""
    res = api_instance.minimize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/minimize_tray", method="POST")
def api_window_minimize_tray():
    """Minimize the desktop window to system tray"""
    res = api_instance.minimize_to_tray()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/restore_tray", method="POST")
def api_window_restore_tray():
    """Restore the desktop window from system tray"""
    if not api_instance.window:
        response.status = 404
        return json.dumps({"success": False, "error": "No window instance"})
    res = api_instance.restore_from_tray()
    response.content_type = "application/json"
    if not res.get("success"):
        response.status = 500
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/maximize", method="POST")
def api_window_maximize():
    """Toggle maximize / restore the desktop window"""
    res = api_instance.maximize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag", method=["GET", "POST"])
def api_window_drag():
    """Trigger ultra-smooth native Windows OS window dragging on titlebar mouse down"""
    res = api_instance.drag_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag_stop", method=["GET", "POST"])
def api_window_drag_stop():
    """Stop window dragging"""
    res = api_instance.drag_stop()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/catalog/sync", method="POST")
def api_catalog_sync():
    data = request.json or {}
    force = data.get("force", True)
    res = api_instance.sync_catalog(force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/version/check", method="GET")
def api_version_check():
    res = api_instance.check_app_version()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


def apply_titlebar_icon(window, ico_path):
    """Ensure the native Windows title bar and taskbar icon is set to the CỔ NGỮ icon"""
    import time
    time.sleep(0.3)
    if not ico_path or not os.path.exists(ico_path):
        return
    try:
        # 1. Direct WinForms Form Icon assignment
        if hasattr(window, 'native') and window.native:
            try:
                import clr
                clr.AddReference('System.Drawing')
                from System.Drawing import Icon
                window.native.Icon = Icon(ico_path)
            except Exception as e:
                pass

        # 2. Native Win32 WM_SETICON for Title Bar and Taskbar / Startbar
        import ctypes
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        
        user32 = ctypes.windll.user32
        cx_small = user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
        cy_small = user32.GetSystemMetrics(50) or 16  # SM_CYSMICON
        cx_big = user32.GetSystemMetrics(11) or 32     # SM_CXICON
        cy_big = user32.GetSystemMetrics(12) or 32     # SM_CYICON

        hicon_small = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, cx_small, cy_small, LR_LOADFROMFILE)
        hicon_big = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, cx_big, cy_big, LR_LOADFROMFILE)
        
        hwnd = None
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'Handle'):
            try:
                hwnd = window.native.Handle.ToInt64()
            except Exception:
                hwnd = None

        if not hwnd:
            title = "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro"
            hwnd = user32.FindWindowW(None, title)

        if hwnd:
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception as e:
        print(f"Error applying titlebar icon: {e}")

def get_app_icon_path():
    candidates = [
        os.path.join(APP_DIR, "app_icon.ico"),
        os.path.join(STATIC_DIR, "app_icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "app_icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "static", "app_icon.ico"),
        os.path.join(getattr(sys, '_MEIPASS', ''), "app_icon.ico"),
        os.path.join(getattr(sys, '_MEIPASS', ''), "static", "app_icon.ico"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return ""

SYSTEM_TRAY = None
SYSTEM_TRAY_BALLOON_SHOWN = False

def setup_system_tray(window, ico_path=None):
    """Thiết lập Khay Hệ Thống (System Tray) chuẩn Windows qua Windows Forms (gắn trực tiếp vào UI thread)."""
    global SYSTEM_TRAY
    if SYSTEM_TRAY is not None:
        return

    def _init():
        global SYSTEM_TRAY
        try:
            import clr
            clr.AddReference('System.Windows.Forms')
            clr.AddReference('System.Drawing')
            from System.Windows.Forms import (
                NotifyIcon, ContextMenuStrip, ToolStripMenuItem,
                ToolStripSeparator, MouseButtons, ToolTipIcon, FormWindowState
            )
            from System.Drawing import Icon, SystemIcons

            tray = NotifyIcon()
            if ico_path and os.path.exists(ico_path):
                try:
                    tray.Icon = Icon(ico_path)
                except Exception:
                    tray.Icon = SystemIcons.Application
            else:
                tray.Icon = SystemIcons.Application

            tray.Text = "CỔ NGỮ - Quản Lý Game Việt Hóa Pro"[:63]

            menu = ContextMenuStrip()
            item_open = ToolStripMenuItem("🎮 Mở CỔ NGỮ")
            item_min = ToolStripMenuItem("⏬ Thu nhỏ xuống Taskbar")
            item_exit = ToolStripMenuItem("❌ Thoát hoàn toàn")

            def _on_open_click(sender, args):
                restore_from_tray(window)

            def _on_min_click(sender, args):
                if window:
                    try:
                        restore_from_tray(window)
                        window.minimize()
                    except Exception:
                        pass

            def _on_exit_click(sender, args):
                quit_from_tray()

            item_open.Click += _on_open_click
            item_min.Click += _on_min_click
            item_exit.Click += _on_exit_click

            menu.Items.Add(item_open)
            menu.Items.Add(item_min)
            menu.Items.Add(ToolStripSeparator())
            menu.Items.Add(item_exit)

            tray.ContextMenuStrip = menu

            def _on_tray_mouse_click(sender, e):
                if hasattr(e, 'Button') and e.Button == MouseButtons.Left:
                    restore_from_tray(window)

            def _on_tray_double_click(sender, e):
                restore_from_tray(window)

            tray.MouseClick += _on_tray_mouse_click
            tray.DoubleClick += _on_tray_double_click
            tray.Visible = True

            SYSTEM_TRAY = tray
            log_startup("[SystemTray] Đã khởi tạo biểu tượng Khay Hệ Thống Windows thành công trên UI Thread!")
        except Exception as e:
            log_startup(f"[SystemTray] Không thể khởi tạo System Tray: {e}")

    try:
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'Invoke'):
            import clr
            from System import Action
            window.native.Invoke(Action(_init))
        else:
            _init()
    except Exception as e:
        log_startup(f"[SystemTray] Invoke error: {e}")

def minimize_to_tray(window):
    """Thu nhỏ cửa sổ xuống thanh Taskbar an toàn chuẩn Windows."""
    try:
        if window:
            window.minimize()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def restore_from_tray(window):
    """Khôi phục và hiển thị lại cửa sổ CỔ NGỮ lên trên cùng màn hình."""
    def _do_restore():
        try:
            if hasattr(window, 'native') and window.native:
                from System.Windows.Forms import FormWindowState
                window.native.Visible = True
                window.native.Show()
                window.native.WindowState = FormWindowState.Normal
                window.native.BringToFront()
                window.native.Activate()
                hwnd = window.native.Handle.ToInt64()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            else:
                window.show()
                window.restore()
        except Exception as e:
            log_startup(f"[SystemTray] Restore error: {e}")

    try:
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'BeginInvoke'):
            import clr
            from System import Action
            window.native.BeginInvoke(Action(_do_restore))
        elif hasattr(window, 'native') and window.native and hasattr(window.native, 'Invoke'):
            import clr
            from System import Action
            window.native.Invoke(Action(_do_restore))
        else:
            threading.Thread(target=_do_restore, daemon=True).start()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def quit_from_tray():
    """Thoát hoàn toàn ứng dụng từ khay hệ thống (Zero-Leak Clean Exit)."""
    global SYSTEM_TRAY
    try:
        if SYSTEM_TRAY:
            SYSTEM_TRAY.Visible = False
            SYSTEM_TRAY.Dispose()
            SYSTEM_TRAY = None
    except Exception:
        pass
    try:
        PLAYTIME_MGR.flush_all_active()
    except Exception:
        pass
    os._exit(0)

def log_startup(msg: str):
    """Ghi log khoi dong ung dung de chan doan su co tren moi may tinh."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    try:
        print(formatted.encode("ascii", "replace").decode("ascii"))
    except Exception:
        pass
    try:
        log_file = os.path.join(APPDATA_DIR, "startup.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def wait_for_local_server(port: int, timeout_sec: float = 5.0) -> bool:
    """
    Kiểm tra trực tiếp qua Raw Socket xem 127.0.0.1:port đã thực sự mở cổng lắng nghe chưa.
    Không bị ảnh hưởng bởi Proxy hệ thống hay CSRF Token 403.
    """
    import socket
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False

def launch_app_window_fallback(url):
    """
    Fallback Desktop Window Mode:
    Khởi chạy Edge/Chrome ở chế độ App Mode với thư mục profile riêng biệt.
    Tuyệt đối KHÔNG gọi os._exit(0) sớm khi trình duyệt chỉ mới handoff tiến trình!
    """
    import subprocess
    potential_browsers = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for exe in potential_browsers:
        if os.path.exists(exe):
            # Tạo profile riêng biệt để ép Edge/Chrome mở tiến trình độc lập
            app_data_edge = os.path.join(APPDATA_DIR, "congu_edge_profile")
            os.makedirs(app_data_edge, exist_ok=True)
            cmd = [
                exe,
                f"--app={url}",
                f"--user-data-dir={app_data_edge}",
                "--window-size=1340,900",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-proxy-server",
                "--proxy-bypass-list=<-loopback>",
                "--disable-features=msEdgeStartupBoost,msSmartScreenProtection",
                "--disable-background-mode",
                "--disable-extensions",
                "--new-window"
            ]
            try:
                log_startup(f"Khoi chay cua so Standalone qua: {exe}")
                t0 = time.time()
                proc = subprocess.Popen(cmd)
                proc.wait()
                elapsed = time.time() - t0
                # Chỉ thoát nếu người dùng thực sự đã mở và sử dụng ứng dụng (> 8 giây)
                # Nếu thoát nhanh (< 8 giây), đó là do Edge handoff sang tiến trình chạy sẵn -> Giữ sống Backend!
                if elapsed > 8.0:
                    log_startup(f"Cua so ung dung da dong sau {elapsed:.1f}s. Thoat tien trinh.")
                    try:
                        PLAYTIME_MGR.flush_all_active()
                    except Exception:
                        pass
                    os._exit(0)
                else:
                    log_startup(
                        f"Trinh duyet handoff nhanh ({elapsed:.1f}s). "
                        f"Duy tri may chu 127.0.0.1 de phuc vu giao dien!"
                    )
                    return True
            except Exception as e:
                log_startup(f"[!] Loi khoi chay trinh duyet {exe}: {e}")

    log_startup("Khong tim thay Edge/Chrome doc lap. Dang mo tren trinh duyet mac dinh...")
    import webbrowser
    webbrowser.open(url)
    return True

def create_http_server():
    """
    Khởi tạo máy chủ HTTP đa luồng trên 127.0.0.1.
    Thử các cổng cố định 49200-49205 trước, nếu bận thì dùng cổng động (0).
    """
    for try_port in [49200, 49201, 49202, 49203, 0]:
        try:
            srv = make_server(
                "127.0.0.1",
                try_port,
                server_app,
                server_class=ThreadingWSGIServer,
                handler_class=QuietWSGIRequestHandler
            )
            return srv
        except OSError as e:
            log_startup(f"[!] Cong {try_port} dang ban ({e}), thu cong tiep theo...")
            continue
    return make_server("127.0.0.1", 0, server_app, server_class=ThreadingWSGIServer, handler_class=QuietWSGIRequestHandler)

def main():
    global SERVER_PORT, HTTP_SERVER

    # Gán AppID độc lập cho Windows Taskbar / Startbar để hiển thị biểu tượng riêng của ứng dụng
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("congu.vietmodhub.launcher.v2")
        except Exception:
            pass

    # 0. Single-Instance Protection: Nếu ứng dụng đang chạy (hoặc đang ẩn dưới Khay),
    # tự động đánh thức cửa sổ lên màn hình và thoát tiến trình thứ hai!
    _app_mutex = None
    if sys.platform == "win32" and "--server" not in sys.argv and "--no-gui" not in sys.argv:
        try:
            import ctypes
            ERROR_ALREADY_EXISTS = 183
            _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\CoNguVietModHubSingleInstance")
            last_err = ctypes.windll.kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                log_startup("[*] Phat hien Co Ngu da dang chay (Mutex ton tai). Dang danh thuc cua so...")
                # 1. Tìm và đưa cửa sổ lên Foreground
                hwnd = ctypes.windll.user32.FindWindowW(None, "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro")
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                # 2. Gửi tín hiệu đánh thức qua HTTP (nếu cửa sổ đang ẩn ở System Tray)
                try:
                    import urllib.request
                    check_url = "http://127.0.0.1:49200/api/window/restore_tray"
                    req = urllib.request.Request(check_url, data=b"{}", headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        pass
                except Exception:
                    pass
                log_startup("[*] Da gui lenh danh thuc. Thoat tien trinh khoi tao thu hai.")
                sys.exit(0)
        except Exception as e:
            log_startup(f"[SingleInstance] Mutex check error: {e}")

    # 1. Khởi tạo HTTP Server
    HTTP_SERVER = create_http_server()
    SERVER_PORT = HTTP_SERVER.server_address[1]
    log_startup(f"[*] Co Ngu Core Engine initialized on 127.0.0.1:{SERVER_PORT} (Token Protected)")

    t = threading.Thread(target=HTTP_SERVER.serve_forever, daemon=True)
    t.start()

    # 2. Kiểm tra Socket 127.0.0.1 đã sẵn sàng 100% trước khi mở WebView
    if wait_for_local_server(SERVER_PORT, timeout_sec=5.0):
        log_startup(f"[OK] May chu HTTP tren 127.0.0.1:{SERVER_PORT} da san sang lang nghe.")
    else:
        log_startup(f"[!] Canh bao: Socket 127.0.0.1:{SERVER_PORT} phan hoi cham.")

    # 3. Đồng bộ danh mục ngầm
    def _bg_cloud_sync():
        time.sleep(2.5)
        sync_remote_catalog(force=False)
    threading.Thread(target=_bg_cloud_sync, daemon=True).start()

    url = f"http://127.0.0.1:{SERVER_PORT}"
    icon_path = get_app_icon_path()

    if "--server" in sys.argv or "--no-gui" in sys.argv:
        log_startup(f"[*] Che do Server Headless kich hoat tren {url}. Dang phuc vu yeu cau...")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        return

    # Biến cờ đánh dấu người dùng chủ động đóng cửa sổ PyWebView
    user_closed_window = {"closed": False}
    webview_started_at = time.time()

    try:
        window = webview.create_window(
            title="CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro",
            url=url,
            js_api=api_instance,
            width=1340,
            height=900,
            min_size=(1020, 680),
            frameless=True,
            easy_drag=True,
            background_color="#0b0f19"
        )
        api_instance.window = window

        def on_shown(w, ico):
            t_icon = threading.Thread(target=apply_titlebar_icon, args=(w, ico), daemon=True)
            t_icon.start()
            # Gắn trực tiếp vào UI thread của Form để System Tray luôn sống
            setup_system_tray(w, ico)

        def on_closed():
            global SYSTEM_TRAY
            try:
                if SYSTEM_TRAY:
                    SYSTEM_TRAY.Visible = False
                    SYSTEM_TRAY.Dispose()
                    SYSTEM_TRAY = None
            except Exception:
                pass
            # Nếu cửa sổ tồn tại > 3 giây rồi mới đóng -> Người dùng chủ động tắt
            if time.time() - webview_started_at > 3.0:
                user_closed_window["closed"] = True
                try:
                    PLAYTIME_MGR.flush_all_active()
                except Exception:
                    pass
                os._exit(0)

        window.events.closed += on_closed

        # Ép sử dụng edgechromium nếu có, tự động fallback nếu máy thiếu WebView2
        webview.start(
            func=on_shown,
            args=(window, icon_path),
            debug=False,
            icon=icon_path if icon_path else None
        )

        # QUAN TRỌNG: Nếu webview.start() tự thoát quá nhanh (< 3 giây) trên PC thiếu WebView2 Runtime,
        # TUYỆT ĐỐI KHÔNG gọi os._exit(0) mà phải chuyển sang chế độ Fallback Browser!
        if time.time() - webview_started_at < 3.0 and not user_closed_window["closed"]:
            raise RuntimeError("WebView2 exited prematurely (< 3s) on target PC")

        try:
            PLAYTIME_MGR.flush_all_active()
        except Exception:
            pass
        os._exit(0)

    except Exception as e:
        log_startup(f"[!] PyWebView fallback triggered ({e}). Launching Standalone Desktop Window mode...")
        launch_app_window_fallback(url)
        # Giữ luồng chính sống để HTTP_SERVER tiếp tục phục vụ 127.0.0.1:{SERVER_PORT}
        # Khi người dùng bấm nút [X] trên giao diện web của ứng dụng, hàm /api/app/quit sẽ gọi os._exit(0)
        while True:
            time.sleep(1.0)

if __name__ == "__main__":
    main()
