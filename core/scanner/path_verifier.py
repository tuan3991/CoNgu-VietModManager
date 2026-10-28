# -*- coding: utf-8 -*-
import os
import sys
import time
import re
import json
import ctypes
from typing import List, Dict, Any, Optional, Tuple

from .platform_detector import (
    detect_steam_libraries, detect_epic_games, detect_gog_games, detect_standalone_game_dirs
)


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


