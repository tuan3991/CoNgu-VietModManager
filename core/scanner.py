import os
import sys
import time
import re
import json
import ctypes
import threading
import glob
import subprocess
from typing import List, Dict, Any, Optional, Tuple

# ==============================================================================
# BỘ NHỚ ĐỆM RAM & KHÓA ĐỒNG BỘ CHO VIỆC PHÁT HIỆN THƯ VIỆN GAME
# ==============================================================================
_LIBRARY_CACHE_LOCK = threading.Lock()
_STEAM_LIBRARIES_CACHE = {"timestamp": 0.0, "data": []}
_EPIC_GAMES_CACHE = {"timestamp": 0.0, "data": []}
_GOG_GAMES_CACHE = {"timestamp": 0.0, "data": []}
_STANDALONE_DIRS_CACHE = {"timestamp": 0.0, "data": []}
_LIBRARY_CACHE_TTL = 60.0  # 60 giây TTL trong RAM để phản hồi tức thì


def invalidate_library_caches():
    """Xóa trắng cache phát hiện thư viện game trong RAM để quét lại khi cần."""
    with _LIBRARY_CACHE_LOCK:
        _STEAM_LIBRARIES_CACHE["timestamp"] = 0.0
        _EPIC_GAMES_CACHE["timestamp"] = 0.0
        _GOG_GAMES_CACHE["timestamp"] = 0.0
        _STANDALONE_DIRS_CACHE["timestamp"] = 0.0


def get_available_drives() -> List[str]:
    """Lấy danh sách các phân vùng ổ đĩa đang gắn thực tế trên Windows (tránh quét ổ đĩa ảo hoặc đầu đọc thẻ trống)."""
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [chr(65 + i) for i in range(26) if (mask >> i) & 1]
        return [d for d in drives if d not in ("A", "B")]
    except Exception:
        return [d for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]


def is_running_as_admin() -> bool:
    """Check if current process has Windows Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_directory_writable(dir_path: str) -> bool:
    """
    Check if a directory has write permissions for the current user.
    Creates and removes a temporary test file (.congu_write_test) to reliably detect Windows ACL restrictions.
    """
    if not dir_path or not os.path.exists(dir_path):
        return False
    test_file = os.path.join(dir_path, f".congu_write_test_{os.getpid()}_{int(time.time())}.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except (PermissionError, OSError):
        return False


def request_uac_elevation() -> bool:
    """
    Relaunch current executable with Administrator rights via Windows ShellExecute 'runas'.
    """
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    else:
        exe = sys.executable
        script = os.path.abspath(sys.argv[0])
        params = f'"{script}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if ret > 32:
            sys.exit(0)
            return True
    except Exception as e:
        print(f"Failed to elevate UAC: {e}")
    return False


def detect_steam_libraries(force_refresh: bool = False) -> List[str]:
    """Detect all Steam library folders across drives on Windows with robust RAM caching (TTL 60s)"""
    now = time.time()
    with _LIBRARY_CACHE_LOCK:
        if not force_refresh and (now - _STEAM_LIBRARIES_CACHE["timestamp"] < _LIBRARY_CACHE_TTL) and _STEAM_LIBRARIES_CACHE["data"]:
            return list(_STEAM_LIBRARIES_CACHE["data"])

    libraries = []
    potential_roots = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"E:\SteamLibrary",
        r"D:\SteamLibrary",
        r"E:\Steam",
        r"D:\Steam",
        r"F:\SteamLibrary",
        r"G:\SteamLibrary",
    ]
    
    # 1. Try reading from Windows registry
    reg_keys = [
        (r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (r"SOFTWARE\Valve\Steam", "InstallPath"),
        (r"Software\Valve\Steam", "SteamPath"),
    ]
    try:
        import winreg
        for subkey, valname in reg_keys:
            try:
                for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        k = winreg.OpenKey(hkey, subkey)
                        steam_val, _ = winreg.QueryValueEx(k, valname)
                        if steam_val:
                            clean_val = steam_val.replace("/", "\\")
                            if os.path.exists(clean_val) and clean_val not in potential_roots:
                                potential_roots.insert(0, clean_val)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    # 2. Check mounted drives only (không quét mù 24 ổ đĩa)
    for drive_letter in get_available_drives():
        candidate_steam = f"{drive_letter}:\\SteamLibrary"
        if candidate_steam not in potential_roots and os.path.exists(candidate_steam):
            potential_roots.append(candidate_steam)

    found_roots = [p for p in potential_roots if os.path.exists(p)]
    for root in found_roots:
        norm_root = os.path.normpath(root)
        if norm_root not in libraries:
            libraries.append(norm_root)
        
        # Parse libraryfolders.vdf
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                matches = re.findall(r'"path"\s+"([^"]+)"', content)
                for lib_path in matches:
                    clean_p = os.path.normpath(lib_path.replace("\\\\", "\\"))
                    if os.path.exists(clean_p) and clean_p not in libraries:
                        libraries.append(clean_p)
            except Exception as e:
                print(f"Error reading libraryfolders.vdf: {e}")

    with _LIBRARY_CACHE_LOCK:
        _STEAM_LIBRARIES_CACHE["timestamp"] = now
        _STEAM_LIBRARIES_CACHE["data"] = list(libraries)

    return libraries


def detect_epic_games(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Detect all installed Epic Games by parsing manifest .item files with RAM caching (TTL 60s)"""
    now = time.time()
    with _LIBRARY_CACHE_LOCK:
        if not force_refresh and (now - _EPIC_GAMES_CACHE["timestamp"] < _LIBRARY_CACHE_TTL) and _EPIC_GAMES_CACHE["data"]:
            return list(_EPIC_GAMES_CACHE["data"])

    epic_games = []
    prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
    manifests_dir = os.path.join(prog_data, "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if os.path.exists(manifests_dir):
        try:
            for fname in os.listdir(manifests_dir):
                if fname.endswith(".item"):
                    item_path = os.path.join(manifests_dir, fname)
                    try:
                        with open(item_path, "r", encoding="utf-8", errors="ignore") as f:
                            data = json.load(f)
                        loc = data.get("InstallLocation")
                        name = data.get("DisplayName", "")
                        app_name = data.get("AppName", "")
                        if loc and os.path.exists(loc):
                            epic_games.append({
                                "platform": "Epic Games",
                                "name": name,
                                "app_name": app_name,
                                "path": os.path.normpath(loc)
                            })
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error reading Epic Games manifests: {e}")

    with _LIBRARY_CACHE_LOCK:
        _EPIC_GAMES_CACHE["timestamp"] = now
        _EPIC_GAMES_CACHE["data"] = list(epic_games)

    return epic_games


def detect_gog_games(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Detect all installed GOG Galaxy games from Windows Registry with RAM caching (TTL 60s)"""
    now = time.time()
    with _LIBRARY_CACHE_LOCK:
        if not force_refresh and (now - _GOG_GAMES_CACHE["timestamp"] < _LIBRARY_CACHE_TTL) and _GOG_GAMES_CACHE["data"]:
            return list(_GOG_GAMES_CACHE["data"])

    gog_games = []
    try:
        import winreg
        gog_reg_roots = [
            r"SOFTWARE\WOW6432Node\GOG.com\Games",
            r"SOFTWARE\GOG.com\Games"
        ]
        for root_key in gog_reg_roots:
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_key)
                num_subkeys, _, _ = winreg.QueryInfoKey(k)
                for i in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(k, i)
                        sk = winreg.OpenKey(k, subkey_name)
                        game_path, _ = winreg.QueryValueEx(sk, "path")
                        game_name = ""
                        try:
                            game_name, _ = winreg.QueryValueEx(sk, "gameName")
                        except Exception:
                            pass
                        if game_path and os.path.exists(game_path):
                            gog_games.append({
                                "platform": "GOG Galaxy",
                                "name": game_name,
                                "path": os.path.normpath(game_path)
                            })
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        print(f"Error reading GOG Galaxy registry: {e}")

    with _LIBRARY_CACHE_LOCK:
        _GOG_GAMES_CACHE["timestamp"] = now
        _GOG_GAMES_CACHE["data"] = list(gog_games)

    return gog_games


def detect_standalone_game_dirs(force_refresh: bool = False) -> List[str]:
    """Detect existing standalone game directories across mounted drives with RAM caching (TTL 60s)"""
    now = time.time()
    with _LIBRARY_CACHE_LOCK:
        if not force_refresh and (now - _STANDALONE_DIRS_CACHE["timestamp"] < _LIBRARY_CACHE_TTL) and _STANDALONE_DIRS_CACHE["data"]:
            return list(_STANDALONE_DIRS_CACHE["data"])

    existing_bases = []
    for drive_letter in get_available_drives():
        candidate_bases = [
            f"{drive_letter}:\\Games",
            f"{drive_letter}:\\GOG Games",
            f"{drive_letter}:\\Epic Games",
            f"{drive_letter}:\\XboxGames",
        ]
        for base_dir in candidate_bases:
            try:
                if os.path.exists(base_dir):
                    existing_bases.append(base_dir)
            except Exception:
                pass

    with _LIBRARY_CACHE_LOCK:
        _STANDALONE_DIRS_CACHE["timestamp"] = now
        _STANDALONE_DIRS_CACHE["data"] = list(existing_bases)

    return existing_bases


def find_game_install_path(
    game_def: Dict[str, Any],
    libraries: List[str],
    epic_games: Optional[List[Dict[str, Any]]] = None,
    gog_games: Optional[List[Dict[str, Any]]] = None,
    standalone_dirs: Optional[List[str]] = None
) -> Optional[str]:
    """
    Find the installation folder of a game across Steam, Epic Games, GOG Galaxy,
    and standalone installation folders across drives (using cached discovery).
    """
    appid = game_def.get("steam_appid")
    folder_names = game_def.get("default_folder_names", [game_def.get("title")])
    gid = game_def.get("id", "").lower()
    game_title = game_def.get("title", "").lower()
    targets = [fn.lower() for fn in folder_names if fn] + [gid, game_title]

    # 1. Check Steam libraries
    for lib in libraries:
        steamapps = os.path.join(lib, "steamapps")
        
        # Check by appmanifest_{appid}.acf
        if appid:
            manifest_file = os.path.join(steamapps, f"appmanifest_{appid}.acf")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                    m = re.search(r'"installdir"\s+"([^"]+)"', txt)
                    if m:
                        candidate = os.path.join(steamapps, "common", m.group(1))
                        if os.path.exists(candidate):
                            return os.path.normpath(candidate)
                except Exception:
                    pass

        # Check by common folder names in steamapps/common
        common_dir = os.path.join(steamapps, "common")
        if os.path.exists(common_dir):
            for fname in folder_names:
                if not fname:
                    continue
                candidate = os.path.join(common_dir, fname)
                if os.path.exists(candidate):
                    return os.path.normpath(candidate)

    # 2. Check Epic Games Launcher manifests (dùng danh sách đã cache trong RAM)
    epic_list = epic_games if epic_games is not None else detect_epic_games()
    for ep in epic_list:
        ep_name = ep.get("name", "").lower()
        ep_app = ep.get("app_name", "").lower()
        ep_path = ep.get("path", "")
        ep_base = os.path.basename(ep_path).lower()
        if any(t in ep_name or t in ep_app or t in ep_base for t in targets):
            is_valid, resolved, _ = verify_and_resolve_game_path(game_def, ep_path)
            if is_valid:
                return resolved

    # 3. Check GOG Galaxy registry entries (dùng danh sách đã cache trong RAM)
    gog_list = gog_games if gog_games is not None else detect_gog_games()
    for gog in gog_list:
        gog_name = gog.get("name", "").lower()
        gog_path = gog.get("path", "")
        gog_base = os.path.basename(gog_path).lower()
        if any(t in gog_name or t in gog_base for t in targets):
            is_valid, resolved, _ = verify_and_resolve_game_path(game_def, gog_path)
            if is_valid:
                return resolved

    # 4. Check common standalone game directories across mounted drives (dùng danh sách đã cache trong RAM)
    bases_list = standalone_dirs if standalone_dirs is not None else detect_standalone_game_dirs()
    for base_dir in bases_list:
        for fname in folder_names:
            if not fname:
                continue
            cand = os.path.join(base_dir, fname)
            if os.path.exists(cand):
                is_valid, resolved, _ = verify_and_resolve_game_path(game_def, cand)
                if is_valid:
                    return resolved

    return None


def verify_and_resolve_game_path(game_def: Dict[str, Any], input_path: str) -> Tuple[bool, str, str]:
    """
    Intelligently verify if input_path is a valid game directory for game_def.
    Auto-resolves if user selected parent or child directory.
    Returns: (is_valid: bool, resolved_path: str, message: str)
    """
    if not input_path or not os.path.exists(input_path):
        return False, "", "Thư mục không tồn tại trên máy tính!"

    clean_path = os.path.normpath(input_path)
    exe_name = game_def.get("executable_name", "").lower()
    folder_names = [f.lower() for f in game_def.get("default_folder_names", [])]
    game_title = game_def.get("title", "").lower()
    gid = game_def.get("id", "").lower()
    viet_title = game_def.get("vietnamese_title", "tựa game này")
    expected_exe = os.path.basename(game_def.get("executable_name", "file chạy game"))
    
    def check_folder(dir_path: str) -> bool:
        if not os.path.isdir(dir_path):
            return False
        # 1. Direct executable check
        if exe_name:
            if os.path.exists(os.path.join(dir_path, game_def.get("executable_name", ""))):
                return True
            base_exe = os.path.basename(exe_name)
            if os.path.exists(os.path.join(dir_path, base_exe)):
                return True
            try:
                for f in os.listdir(dir_path):
                    if f.lower() == base_exe:
                        return True
            except Exception:
                pass
                
        # 2. Check engine-specific folders
        rel_install = game_def.get("relative_install_path", "")
        if rel_install:
            first_part = rel_install.split("/")[0].split("\\")[0]
            if first_part and os.path.exists(os.path.join(dir_path, first_part)):
                return True

        # 3. Check for any exe matching title or id or folder names
        try:
            for f in os.listdir(dir_path):
                if f.lower().endswith(".exe"):
                    f_clean = re.sub(r'[^a-z0-9]', '', f.lower())
                    for target in folder_names + [gid, game_title]:
                        t_clean = re.sub(r'[^a-z0-9]', '', target)
                        if t_clean and (t_clean in f_clean or f_clean in t_clean):
                            return True
        except Exception:
            pass

        return False

    # A. Check directly in input_path
    if check_folder(clean_path):
        return True, clean_path, f"Đã xác nhận thư mục hợp lệ cho {viet_title}!"

    # B. Auto-resolve: Parent directory (e.g. steamapps/common)
    try:
        subdirs = [os.path.join(clean_path, d) for d in os.listdir(clean_path) if os.path.isdir(os.path.join(clean_path, d))]
        for sub in subdirs:
            sub_name = os.path.basename(sub).lower()
            if any(fn in sub_name or sub_name in fn for fn in folder_names) or (gid in sub_name):
                if check_folder(sub):
                    return True, sub, f"Đã tự động định vị đúng thư mục game: {os.path.basename(sub)}"
            if check_folder(sub):
                return True, sub, f"Đã tự động định vị đúng thư mục game: {os.path.basename(sub)}"
    except Exception:
        pass

    # C. Auto-resolve: Subfolder
    parent = os.path.dirname(clean_path)
    if parent and parent != clean_path and check_folder(parent):
        return True, parent, f"Đã tự động trỏ về thư mục gốc của game: {os.path.basename(parent)}"

    parent2 = os.path.dirname(parent)
    if parent2 and parent2 != parent and check_folder(parent2):
        return True, parent2, f"Đã tự động trỏ về thư mục gốc của game: {os.path.basename(parent2)}"

    return False, clean_path, f"Thư mục không hợp lệ! Không tìm thấy file chạy '{expected_exe}' của {viet_title}."


def extract_local_steam_appid(game_dir: str) -> Optional[str]:
    """Lớp 1: Quét nhanh steam_appid có sẵn trong các file cấu hình của game lẻ/repack (Độ chính xác 100%, 0 giây)."""
    if not game_dir or not os.path.exists(game_dir):
        return None

    # 1. Tìm trực tiếp file steam_appid.txt (ở gốc hoặc trong các thư mục con gần nhất)
    for pattern in ["steam_appid.txt", "*/steam_appid.txt", "*/*/steam_appid.txt"]:
        for path in glob.glob(os.path.join(game_dir, pattern)):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                    if lines and lines[0].isdigit() and int(lines[0]) > 0:
                        return lines[0]
            except OSError:
                pass

    # 2. Quét trong các file .ini phổ biến của game cài ngoài (steam_emu.ini, tenoke.ini, rune.ini...)
    ini_patterns = [
        "steam_emu.ini", "*/steam_emu.ini", "*/*/steam_emu.ini",
        "*tenoke*.ini", "*/*tenoke*.ini",
        "*rune*.ini", "*/*rune*.ini",
        "*codex*.ini", "*/*codex*.ini",
        "*onlinefix*.ini", "*/*onlinefix*.ini",
        "*flt*.ini", "*/*flt*.ini",
        "*ali213*.ini", "*/*ali213*.ini",
        "cream_api.ini", "*/cream_api.ini"
    ]
    for pattern in ini_patterns:
        for path in glob.glob(os.path.join(game_dir, pattern)):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    match = re.search(r"(?:^|\n)\s*#?\s*(?:AppId|SteamAppId|TargetAppId)\s*=\s*(\d{3,10})", text, re.IGNORECASE)
                    if match and match.group(1) != "0":
                        return match.group(1)
            except OSError:
                pass

    # Quét đệ quy nếu file .ini nằm sâu trong thư mục Engine hoặc Plugins (như Unreal Engine / Unity)
    deep_ini_patterns = [
        os.path.join(game_dir, "**", "steam_emu.ini"),
        os.path.join(game_dir, "**", "*tenoke*.ini"),
        os.path.join(game_dir, "**", "*rune*.ini"),
        os.path.join(game_dir, "**", "*codex*.ini"),
        os.path.join(game_dir, "**", "cream_api.ini")
    ]
    for deep_pat in deep_ini_patterns:
        for path in glob.glob(deep_pat, recursive=True):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    match = re.search(r"(?:^|\n)\s*#?\s*(?:AppId|SteamAppId|TargetAppId)\s*=\s*(\d{3,10})", text, re.IGNORECASE)
                    if match and match.group(1) != "0":
                        return match.group(1)
            except OSError:
                pass

    # 3. Quét tệp goggame-*.info (JSON metadata của GOG)
    for path in glob.glob(os.path.join(game_dir, "goggame-*.info")) + glob.glob(os.path.join(game_dir, "*", "goggame-*.info")):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                gog_data = json.load(f)
                gog_appid = gog_data.get("steam_appid") or gog_data.get("gameId")
                if gog_appid and str(gog_appid).isdigit():
                    return str(gog_appid)
        except Exception:
            pass

    return None


def resolve_clean_game_title(game_dir: str, exe_name: str = "") -> str:
    """Lớp 2: Trích xuất và làm sạch tên game thật từ thư mục hoặc Unity app.info."""
    if not game_dir:
        return ""

    # 1. Nếu là game Unity, đọc dòng thứ 2 trong *_Data/app.info (chứa Product Name chuẩn)
    for app_info in glob.glob(os.path.join(game_dir, "*_Data", "app.info")) + glob.glob(os.path.join(game_dir, "*", "*_Data", "app.info")):
        try:
            with open(app_info, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                if len(lines) >= 2 and len(lines[1]) > 1:
                    return lines[1]
        except OSError:
            pass

    # 2. Lấy từ tên thư mục gốc hoặc tên exe và lọc bỏ rác kỹ thuật
    raw_name = os.path.basename(os.path.normpath(game_dir))
    if raw_name.lower() in ("binaries", "win64", "win32", "x64", "x86", "game", "bin") and exe_name:
        raw_name = os.path.splitext(os.path.basename(exe_name))[0]
    elif raw_name.lower() in ("binaries", "win64", "win32", "x64", "x86", "game", "bin"):
        raw_name = os.path.basename(os.path.dirname(os.path.normpath(game_dir)))

    # Xóa các hậu tố Engine, phiên bản và nhóm Repack
    clean = re.sub(r"(-Win64-Shipping|-Win32-Shipping|_x64|_x86|_DX11|_DX12|-Shipping)", "", raw_name, flags=re.IGNORECASE)
    clean = re.sub(r"\[.*?\]|\(.*?\)", " ", clean)
    clean = re.sub(r"\b(v?\d+(\.\d+)+|repack|portable|gog|fitgirl|dodi|elamigos|tenoke|rune|codex|flt|goldberg|cpi|skidrow)\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[._\-]+", " ", clean)
    # Tách chữ CamelCase (VD: RavenousDevils -> Ravenous Devils)
    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", clean)
    return re.sub(r"\s+", " ", clean).strip()


def extract_exe_icon(exe_path: str, output_img_path: str) -> bool:
    """Lớp 4 Fallback: Trích xuất icon gốc từ file .exe trên Windows thành file PNG."""
    if not exe_path or not os.path.exists(exe_path) or not sys.platform.startswith("win"):
        return False
    try:
        clean_exe = os.path.abspath(exe_path).replace("'", "''")
        clean_out = os.path.abspath(output_img_path).replace("'", "''")
        ps_cmd = (
            f"Add-Type -AssemblyName System.Drawing; "
            f"$icon = [System.Drawing.Icon]::ExtractAssociatedIcon('{clean_exe}'); "
            f"if ($icon) {{ $bitmap = $icon.ToBitmap(); $bitmap.Save('{clean_out}', [System.Drawing.Imaging.ImageFormat]::Png); exit 0 }} else {{ exit 1 }}"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd], capture_output=True, timeout=5)
        return res.returncode == 0 and os.path.exists(output_img_path) and os.path.getsize(output_img_path) > 500
    except Exception:
        return False

