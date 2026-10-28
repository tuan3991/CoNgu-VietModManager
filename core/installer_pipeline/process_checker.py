# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Process Checker & File Detection
"""
import os
import sys
import ctypes
import hashlib
from typing import List, Tuple, Optional, Any

from core.config_manager import (
    load_user_config, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR, APP_DIR, USER_DOCS_DIR
)
from core.backup_rollback import compute_file_sha256
from core.scanner import get_available_drives


def calculate_sha256(filepath: str) -> Optional[str]:
    """Tính mã băm SHA256 của tệp tin."""
    return compute_file_sha256(filepath)


# ==============================================================================
# PROCESS DETECTION UTILITIES
# ==============================================================================

def get_running_processes() -> List[Tuple[str, Optional[str]]]:
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


def get_running_process_names() -> set:
    """Enumerate running process names using native Win32 Toolhelp API"""
    return {p[0] for p in get_running_processes()}


def check_game_running(g: Any, game_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
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
                if proc_name in target_exes or proc_name in generic_helpers:
                    return True, proc_name
            continue

        # Trường hợp 2: Fallback (không lấy được proc_path hoặc không có game_path)
        if proc_name in target_exes:
            return True, proc_name

    return False, None


# ==============================================================================
# MOD SOURCE DIRECTORY RESOLUTION
# ==============================================================================

def find_mod_source_dir(mod_subfolder: str) -> str:
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


def check_has_mod_files(chk_dir: str, g: dict) -> bool:
    """Kiểm tra xem thư mục có chứa tệp tin mod tương ứng hay không."""
    if not os.path.exists(chk_dir):
        return False
    mtype = g.get("mod_type", "pak")
    if mtype == "pak":
        return os.path.exists(os.path.join(chk_dir, g.get("mod_file", ""))) or os.path.exists(os.path.join(chk_dir, "Mod_Files", g.get("target_pak_name", "")))
    elif mtype == "unity_assets":
        return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
    elif mtype == "wad":
        return os.path.exists(os.path.join(chk_dir, "HotlineMiami_GL.wad"))
    elif mtype == "bepinex_language":
        return os.path.exists(os.path.join(chk_dir, "winhttp.dll")) or os.path.exists(os.path.join(chk_dir, "BepInEx"))
    elif mtype == "folder_copy":
        return os.path.exists(os.path.join(chk_dir, "core", "locale")) or os.path.exists(os.path.join(chk_dir, "core", "gui", "font"))
    elif mtype == "ini_and_exe":
        return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
    elif mtype == "witcher3_mod":
        return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
    return False


# ==============================================================================
# INI FILE PATCHER
# ==============================================================================

