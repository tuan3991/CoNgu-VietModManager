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

