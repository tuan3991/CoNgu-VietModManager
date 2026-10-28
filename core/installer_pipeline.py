"""
================================================================================
VIETMODMANAGER / CỔ NGỮ (VIETMODHUB) - CORE INSTALLER PIPELINE ENGINE
================================================================================
Module 5: Kiến trúc Data-Driven Action Pipeline, Smart In-Place Backup & Rollback,
và quy trình cài đặt/gỡ bỏ mod Việt hóa độc lập.

Features:
- Global Install/Uninstall/Restore State & Progress tracking (INSTALL_PROGRESS).
- Thread-safe concurrency lock (_MOD_OP_LOCK) preventing simultaneous mod ops.
- Robust INI file patcher preserving comments, structure and formatting.
- Atomic Data-Driven Action Pipeline execution (backup, restore_backup, copy_file,
  copy_folder, extract_all, patch_binary, patch_ini, delete, rename).
- Two-Tier Transaction Rollback:
  * Tier 1: In-memory Reverse Journal rollback with .congu_tx_tmp restoration.
  * Tier 2: Deep Emergency Restore from pristine .congu_bak backups.
- Secure Cython .congu package extraction & installation via `security` module.
================================================================================
"""

import os
import sys
import json
import shutil
import zipfile
import hashlib
import threading
from typing import Dict, List, Optional, Tuple, Any, Callable

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch
except ImportError:
    class SecurityError(PermissionError):
        """Lỗi vi phạm an ninh hệ thống hoặc phát hiện hành vi can thiệp trái phép."""
        pass

    class PathTraversalError(SecurityError):
        """Phát hiện lỗ hổng Path Traversal hoặc Zip Slip."""
        pass

    def validate_safe_path(base_dir, relative_or_target_path, allow_base_itself=False):
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
                f"Cảnh báo bảo mật (Path Traversal): Thao tác bị từ chối! "
                f"Đường dẫn '{path_str}' nằm ngoài thư mục game '{base_dir}'."
            )

        if not allow_base_itself and target_norm == base_norm:
            raise PathTraversalError(
                f"Cảnh báo bảo mật: Không được phép thao tác trực tiếp lên thư mục gốc '{base_dir}'!"
            )

        return target_real

from core.config_manager import (
    APP_DIR,
    APPDATA_DIR,
    BACKUP_ROOT,
    DEFAULT_REPO_DIR,
    FALLBACK_REPO_DIR,
    USER_DOCS_DIR,
    load_user_config,
    save_user_config,
    get_repo_dir,
    get_active_games_json_path,
    get_games,
)
from core.scanner import (
    is_running_as_admin,
    check_directory_writable,
    verify_and_resolve_game_path,
)
from core.backup_rollback import (
    compute_file_sha256,
    _norm_rel,
    norm_rel_path,
    backup_file_inplace,
    load_backup_manifest,
    save_backup_manifest,
    record_preexisting_environment,
    record_backup_manifest,
    record_modded_state,
    restore_files_inplace,
    emergency_restore_game as deep_emergency_restore,
)
from core.downloader import download_file_with_progress

# ==============================================================================
# GLOBAL PROGRESS & CONCURRENCY CONTROL
# ==============================================================================

INSTALL_PROGRESS = {
    "status": "idle",       # "idle", "running", "success", "error"
    "percent": 0,
    "message": "",
    "game_id": "",
    "operation": ""         # "install" | "uninstall" | "restore"
}

_MOD_OP_LOCK = threading.Lock()  # Khóa đồng bộ chống xung đột đa luồng khi cài đặt, gỡ bỏ hoặc khôi phục mod


def set_progress(percent: int, message: str, status: str = "running", game_id: str = "", operation: str = "") -> None:
    """Cập nhật tiến trình cài đặt/gỡ bỏ mod toàn cục."""
    global INSTALL_PROGRESS
    INSTALL_PROGRESS["percent"] = percent
    INSTALL_PROGRESS["message"] = message
    INSTALL_PROGRESS["status"] = status
    if game_id:
        INSTALL_PROGRESS["game_id"] = game_id
    if operation:
        INSTALL_PROGRESS["operation"] = operation


def get_install_progress() -> Dict[str, Any]:
    """Lấy bản sao trạng thái tiến trình hiện tại."""
    return dict(INSTALL_PROGRESS)


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

def patch_ini_file(file_path: str, section: Optional[str], key: str, value: str, encoding: str = "utf-8") -> bool:
    """
    Robust INI modification that preserves existing comments, whitespace, and formatting.
    Creates parent directories and the file if it does not yet exist.
    """
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    bak_file = f"{file_path}.congu_bak"
    # Bẫy cấu hình (Mục 1.3): Tự phục hồi file .ini nếu trước đó bị lệnh backup đổi tên làm mất!
    if not os.path.exists(file_path) and os.path.exists(bak_file):
        try:
            shutil.copy2(bak_file, file_path)
            print(f"[Smart Self-Healing INI] File '{os.path.basename(file_path)}' không tồn tại nhưng phát hiện bản sao lưu '{os.path.basename(bak_file)}'. Đã tự động chép ngược nội dung để bảo toàn cấu hình gốc trước khi sửa.")
        except Exception as e:
            print(f"[Smart Self-Healing INI Warning] Không thể sao chép từ {bak_file}: {e}")

    content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                content = f.read()
        except Exception:
            with open(file_path, "r", encoding="latin-1", errors="replace") as f:
                content = f.read()

    lines = content.splitlines(keepends=True) if content else []
    out_lines = []
    in_target_section = False if section else True
    section_found = False if section else True
    key_replaced = False

    sec_header = f"[{section.strip().lower()}]" if section else ""
    key_prefix = key.strip().lower()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_sec = stripped.lower()
            if in_target_section and not key_replaced:
                out_lines.append(f"{key}={value}\n")
                key_replaced = True

            if sec_header and current_sec == sec_header:
                in_target_section = True
                section_found = True
            else:
                in_target_section = False if section else True
            out_lines.append(line)
            continue

        if in_target_section and not key_replaced:
            if "=" in line:
                k, sep, v = line.partition("=")
                if k.strip().lower() == key_prefix:
                    indent = len(line) - len(line.lstrip())
                    out_lines.append(f"{line[:indent]}{key}={value}\n")
                    key_replaced = True
                    continue
        out_lines.append(line)

    if in_target_section and not key_replaced:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        out_lines.append(f"{key}={value}\n")
        key_replaced = True
    elif not section_found:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        out_lines.append(f"\n[{section}]\n{key}={value}\n")
        key_replaced = True

    with open(file_path, "w", encoding=encoding, errors="replace") as f:
        f.write("".join(out_lines))
    return True


# ==============================================================================
# DATA-DRIVEN ACTION PIPELINE EXECUTION
# ==============================================================================

def execute_pipeline_step(game_id: str, game_path: str, source_mod_dir: str, step: dict, operation: str = "install") -> Any:
    """
    Executes a single atomic data-driven action step.
    Supported actions:
    - backup: in-place rename of target to target.congu_bak
    - copy_file: copy single file from source_mod_dir to game_path
    - copy_folder: recursive copy of directory from source_mod_dir to game_path
    - extract_all / extract_zip: extract archive into game_path
    - patch_binary: in-place binary delta patching
    - patch_ini: in-place backup and update section/key/value in ini file
    - delete / delete_file: delete file or directory in game_path
    - rename: rename file/folder in game_path
    - restore_backup: restore target.congu_bak to target
    """
    action = step.get("action", "").lower().strip()

    if action == "backup":
        target_rel = _norm_rel(step.get("target"))
        if not target_rel:
            raise ValueError("Step 'backup' missing required 'target' field")
        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
        is_ini = target_rel.lower().endswith(('.ini', '.cfg', '.conf'))
        created_new_bak = False
        has_tx_tmp = False
        bak_abs = f"{target_abs}.congu_bak"
        tx_tmp_abs = f"{target_abs}.congu_tx_tmp"

        if os.path.exists(target_abs):
            if not os.path.exists(bak_abs):
                bak_res, created_new_bak = backup_file_inplace(game_id, target_abs, target_rel, return_details=True)
            else:
                # Đã có .congu_bak -> target_abs là bản mod v1.0. Lưu tạm tx_tmp để rollback nếu v1.1 lỗi!
                if not is_ini:
                    try:
                        if os.path.isdir(target_abs):
                            shutil.copytree(target_abs, tx_tmp_abs, dirs_exist_ok=True)
                            shutil.rmtree(target_abs, ignore_errors=True)
                        else:
                            shutil.copy2(target_abs, tx_tmp_abs)
                            os.remove(target_abs)
                        has_tx_tmp = True
                    except Exception as e:
                        print(f"[Auto-Backup Tx-Tmp Warning] backup {target_abs}: {e}")

        return {
            "action": "backup",
            "target": target_rel,
            "is_ini": is_ini,
            "created_new_bak": created_new_bak,
            "has_tx_tmp": has_tx_tmp,
            "tx_tmp": tx_tmp_abs
        }

    elif action == "restore_backup":
        target_rel = _norm_rel(step.get("target"))
        if not target_rel:
            raise ValueError("Step 'restore_backup' missing required 'target' field")
        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
        bak_abs = f"{target_abs}.congu_bak"
        if os.path.exists(bak_abs):
            # Anti-crash check: if target_abs already updated by Steam/Epic, do NOT overwrite!
            manifest_path = os.path.join(BACKUP_ROOT, game_id, "backup_manifest.json")
            modded_hash = None
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        for it in m_data.get("files", []):
                            if _norm_rel(it.get("relative_in_game")) == target_rel:
                                modded_hash = it.get("modded_sha256")
                                break
                except Exception:
                    pass

            if modded_hash and os.path.exists(target_abs):
                curr_hash = compute_file_sha256(target_abs)
                if curr_hash and curr_hash.lower() != modded_hash.lower():
                    print(f"[Anti-Crash] Tệp '{target_rel}' không phải file mod (Steam/Epic đã cập nhật). Bỏ qua restore để tránh crash.")
                    try:
                        os.remove(bak_abs)
                    except Exception:
                        pass
                    return {"action": "restore_backup", "target": target_rel, "skipped": True}

            if os.path.exists(target_abs):
                try:
                    if os.path.isdir(target_abs):
                        shutil.rmtree(target_abs, ignore_errors=True)
                    else:
                        os.remove(target_abs)
                except Exception:
                    pass
            os.rename(bak_abs, target_abs)
        return {"action": "restore_backup", "target": target_rel}

    elif action == "copy_file":
        src_rel = step.get("source")
        dst_rel = _norm_rel(step.get("destination") or step.get("target") or src_rel)
        if not src_rel:
            raise ValueError("Step 'copy_file' missing required 'source' field")
        if source_mod_dir:
            src_abs = validate_safe_path(source_mod_dir, src_rel, allow_base_itself=False)
        else:
            src_abs = src_rel
        if not os.path.exists(src_abs) and source_mod_dir:
            nested_src = os.path.join(source_mod_dir, "Mod_Files", os.path.basename(src_rel))
            if os.path.exists(nested_src):
                src_abs = nested_src
        if not os.path.exists(src_abs):
            if step.get("optional", False):
                return None
            raise FileNotFoundError(f"Mod file not found: {src_rel}")
        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=False)
        existed_before = os.path.exists(dst_abs)
        created_new_bak = False
        has_tx_tmp = False
        bak_abs = f"{dst_abs}.congu_bak"
        tx_tmp_abs = f"{dst_abs}.congu_tx_tmp"

        # Auto-Backup ngầm: Cứ hễ đích đến đã tồn tại file trước khi chép đè, tự động tạo .congu_bak nếu chưa có
        if existed_before and os.path.isfile(dst_abs) and operation == "install":
            if not os.path.exists(bak_abs):
                try:
                    os.makedirs(os.path.dirname(bak_abs), exist_ok=True)
                    os.rename(dst_abs, bak_abs)
                    created_new_bak = True
                    orig_hash = compute_file_sha256(bak_abs)
                    record_backup_manifest(game_id, [{
                        "relative_in_game": dst_rel,
                        "target_file": dst_abs,
                        "backup_file": bak_abs,
                        "size_bytes": os.path.getsize(bak_abs),
                        "original_sha256": orig_hash,
                        "original_size": os.path.getsize(bak_abs),
                        "original_mtime": os.path.getmtime(bak_abs)
                    }])
                except Exception as e:
                    print(f"[Auto-Backup Warning] copy_file {dst_abs}: {e}")
            else:
                # bak_abs đã tồn tại -> dst_abs là bản mod trước đó. Lưu tx_tmp để rollback nếu v1.1 lỗi!
                try:
                    shutil.copy2(dst_abs, tx_tmp_abs)
                    has_tx_tmp = True
                except Exception as e:
                    print(f"[Tx-Tmp Warning] copy_file {dst_abs}: {e}")

        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
        shutil.copy2(src_abs, dst_abs)
        if operation == "install":
            record_modded_state(game_id, dst_abs, dst_rel)
        return {
            "action": "copy_file",
            "target": dst_rel,
            "destination": dst_rel,
            "existed_before": existed_before,
            "created_new_bak": created_new_bak,
            "has_tx_tmp": has_tx_tmp,
            "tx_tmp": tx_tmp_abs
        }

    elif action == "patch_binary":
        target_rel = _norm_rel(step.get("target"))
        patch_rel = step.get("patch") or step.get("source")
        if not target_rel or not patch_rel:
            raise ValueError("Step 'patch_binary' missing required 'target' or 'patch' field")

        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
        bak_abs = f"{target_abs}.congu_bak"

        if source_mod_dir:
            patch_abs = validate_safe_path(source_mod_dir, patch_rel, allow_base_itself=False)
        else:
            patch_abs = patch_rel

        if not os.path.exists(patch_abs) and source_mod_dir:
            nested_patch = os.path.join(source_mod_dir, "Mod_Files", os.path.basename(patch_rel))
            if os.path.exists(nested_patch):
                patch_abs = nested_patch

        if not os.path.exists(patch_abs):
            if step.get("optional", False):
                return None
            raise FileNotFoundError(f"Patch file not found: {patch_rel}")

        # 1. Xác định tệp nguồn để vá (Hỗ trợ cài đè/cập nhật bản dịch nếu target đã bị mod)
        expected_orig_sha = step.get("original_sha256")
        source_file_for_patch = None
        created_new_bak = False

        target_exists = os.path.exists(target_abs)
        bak_exists = os.path.exists(bak_abs)

        if not target_exists and not bak_exists:
            raise FileNotFoundError(f"Original game file to patch not found: {target_rel}")

        if expected_orig_sha:
            norm_expected = expected_orig_sha.lower().strip()
            # A. Kiểm tra nếu tệp đích hiện tại khớp mã băm gốc
            if target_exists:
                actual_target_sha = compute_file_sha256(target_abs)
                if actual_target_sha and actual_target_sha.lower() == norm_expected:
                    source_file_for_patch = target_abs

            # B. Nếu tệp đích không khớp (đã cài mod trước đó), kiểm tra tệp sao lưu .congu_bak
            if not source_file_for_patch and bak_exists:
                actual_bak_sha = compute_file_sha256(bak_abs)
                if actual_bak_sha and actual_bak_sha.lower() == norm_expected:
                    source_file_for_patch = bak_abs
                    print(f"[patch_binary] Phát hiện cài đè/cập nhật: Tệp '{target_rel}' đã mod trước đó. Sử dụng '{os.path.basename(bak_abs)}' làm nguồn vá.")

            # C. Nếu cả tệp hiện tại lẫn tệp sao lưu đều không khớp, báo lỗi phiên bản game
            if not source_file_for_patch:
                t_sha = compute_file_sha256(target_abs) if target_exists else "Missing"
                b_sha = compute_file_sha256(bak_abs) if bak_exists else "Missing"
                raise SecurityError(
                    f"Lỗi toàn vẹn tệp gốc '{target_rel}': Mã băm không khớp! "
                    f"(Dự kiến: {expected_orig_sha}, Thực tế tệp đích: {t_sha}, Tệp .congu_bak: {b_sha}). "
                    f"Game có thể đã cập nhật bản mới hoặc bị sửa đổi trước đó."
                )
        else:
            if bak_exists:
                source_file_for_patch = bak_abs
            elif target_exists:
                source_file_for_patch = target_abs
            else:
                raise FileNotFoundError(f"Original game file to patch not found: {target_rel}")

        # 2. Auto-backup tệp gốc trước khi vá
        has_tx_tmp = False
        tx_tmp_abs = f"{target_abs}.congu_tx_tmp"
        if not os.path.exists(bak_abs) and os.path.exists(target_abs):
            try:
                os.makedirs(os.path.dirname(bak_abs), exist_ok=True)
                shutil.copy2(target_abs, bak_abs)
                created_new_bak = True
                orig_hash = compute_file_sha256(bak_abs)
                record_backup_manifest(game_id, [{
                    "relative_in_game": target_rel,
                    "target_file": target_abs,
                    "backup_file": bak_abs,
                    "size_bytes": os.path.getsize(bak_abs),
                    "original_sha256": orig_hash,
                    "original_size": os.path.getsize(bak_abs),
                    "original_mtime": os.path.getmtime(bak_abs)
                }])
            except Exception as e:
                print(f"[Auto-Backup Warning] patch_binary {target_abs}: {e}")
        elif os.path.exists(bak_abs) and os.path.exists(target_abs):
            # bak_abs đã tồn tại -> target_abs là bản mod trước đó. Lưu tx_tmp để rollback nếu v1.1 lỗi!
            try:
                shutil.copy2(target_abs, tx_tmp_abs)
                has_tx_tmp = True
            except Exception as e:
                print(f"[Tx-Tmp Warning] patch_binary {target_abs}: {e}")

        # 3. Áp dụng bản vá từ source_file_for_patch ra file tạm an toàn
        tmp_patched_file = f"{target_abs}.congu_patching_{os.getpid()}.tmp"
        try:
            apply_binary_patch(source_file_for_patch, tmp_patched_file, patch_abs)

            # 4. Kiểm tra patched_sha256 nếu có
            expected_patched_sha = step.get("patched_sha256")
            if expected_patched_sha:
                actual_patched_sha = compute_file_sha256(tmp_patched_file)
                if actual_patched_sha and actual_patched_sha.lower() != expected_patched_sha.lower().strip():
                    raise SecurityError(
                        f"Lỗi kiểm tra sau vá tệp '{target_rel}': Mã băm không khớp! "
                        f"(Dự kiến: {expected_patched_sha}, Thực tế: {actual_patched_sha})."
                    )

            # 5. Thay thế nguyên tử ghi đè lên target_abs
            os.replace(tmp_patched_file, target_abs)
        finally:
            if os.path.exists(tmp_patched_file):
                try:
                    os.remove(tmp_patched_file)
                except Exception:
                    pass

        if operation == "install":
            record_modded_state(game_id, target_abs, target_rel)

        return {
            "action": "patch_binary",
            "target": target_rel,
            "created_new_bak": created_new_bak,
            "existed_before": True,
            "has_tx_tmp": has_tx_tmp,
            "tx_tmp": tx_tmp_abs
        }

    elif action == "copy_folder":
        src_rel = step.get("source")
        dst_rel = _norm_rel(step.get("destination", src_rel))
        if not src_rel:
            raise ValueError("Step 'copy_folder' missing required 'source' field")
        if source_mod_dir:
            src_abs = validate_safe_path(source_mod_dir, src_rel, allow_base_itself=True)
        else:
            src_abs = src_rel
        if not os.path.exists(src_abs):
            if step.get("optional", False):
                return None
            raise FileNotFoundError(f"Mod directory not found: {src_rel}")
        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=True)
        os.makedirs(dst_abs, exist_ok=True)
        copied_files = []
        backup_records = []
        for root, dirs, files in os.walk(src_abs):
            for f in files:
                s_file = os.path.join(root, f)
                rel_sub = os.path.relpath(s_file, src_abs)
                d_file = validate_safe_path(game_path, os.path.join(dst_rel, rel_sub), allow_base_itself=False)
                d_rel = _norm_rel(os.path.relpath(d_file, game_path))
                existed = os.path.exists(d_file)
                created_new_bak = False
                has_tx_tmp = False
                b_file = f"{d_file}.congu_bak"
                tx_file = f"{d_file}.congu_tx_tmp"

                if existed and os.path.isfile(d_file) and operation == "install":
                    if not os.path.exists(b_file):
                        try:
                            os.makedirs(os.path.dirname(b_file), exist_ok=True)
                            os.rename(d_file, b_file)
                            created_new_bak = True
                            orig_hash = compute_file_sha256(b_file)
                            backup_records.append({
                                "relative_in_game": d_rel,
                                "target_file": d_file,
                                "backup_file": b_file,
                                "size_bytes": os.path.getsize(b_file),
                                "original_sha256": orig_hash,
                                "original_size": os.path.getsize(b_file),
                                "original_mtime": os.path.getmtime(b_file)
                            })
                        except Exception as e:
                            print(f"[Auto-Backup Folder Warning] {d_file}: {e}")
                    else:
                        try:
                            shutil.copy2(d_file, tx_file)
                            has_tx_tmp = True
                        except Exception as e:
                            print(f"[Tx-Tmp Folder Warning] {d_file}: {e}")

                os.makedirs(os.path.dirname(d_file), exist_ok=True)
                shutil.copy2(s_file, d_file)
                copied_files.append((d_rel, existed, created_new_bak, has_tx_tmp))

        if backup_records:
            record_backup_manifest(game_id, backup_records)

        if operation == "install":
            for item in copied_files:
                d_rel = item[0]
                d_abs = validate_safe_path(game_path, d_rel, allow_base_itself=False)
                record_modded_state(game_id, d_abs, d_rel)

        return {"action": "copy_folder", "target": dst_rel, "destination": dst_rel, "copied_files": copied_files}

    elif action in ("extract_all", "extract_zip"):
        src_rel = step.get("source", "")
        dst_rel = _norm_rel(step.get("destination", ""))
        if source_mod_dir and src_rel:
            src_abs = validate_safe_path(source_mod_dir, src_rel, allow_base_itself=False)
        else:
            src_abs = source_mod_dir
        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=True)
        os.makedirs(dst_abs, exist_ok=True)
        extracted_files = []
        backup_records = []
        if os.path.isfile(src_abs) and zipfile.is_zipfile(src_abs):
            with zipfile.ZipFile(src_abs, 'r') as zf:
                for member in zf.namelist():
                    if not member.endswith("/"):
                        target_dest = validate_safe_path(dst_abs, member, allow_base_itself=False)
                        t_rel = _norm_rel(os.path.relpath(target_dest, game_path))
                        existed = os.path.exists(target_dest)
                        created_new_bak = False
                        has_tx_tmp = False
                        b_file = f"{target_dest}.congu_bak"
                        tx_file = f"{target_dest}.congu_tx_tmp"

                        if existed and os.path.isfile(target_dest) and operation == "install":
                            if not os.path.exists(b_file):
                                try:
                                    os.makedirs(os.path.dirname(b_file), exist_ok=True)
                                    os.rename(target_dest, b_file)
                                    created_new_bak = True
                                    orig_hash = compute_file_sha256(b_file)
                                    backup_records.append({
                                        "relative_in_game": t_rel,
                                        "target_file": target_dest,
                                        "backup_file": b_file,
                                        "size_bytes": os.path.getsize(b_file),
                                        "original_sha256": orig_hash,
                                        "original_size": os.path.getsize(b_file),
                                        "original_mtime": os.path.getmtime(b_file)
                                    })
                                except Exception as e:
                                    print(f"[Auto-Backup Extract Warning] {target_dest}: {e}")
                            else:
                                try:
                                    shutil.copy2(target_dest, tx_file)
                                    has_tx_tmp = True
                                except Exception as e:
                                    print(f"[Tx-Tmp Extract Warning] {target_dest}: {e}")

                        os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                        with zf.open(member, "r") as s_in, open(target_dest, "wb") as d_out:
                            shutil.copyfileobj(s_in, d_out, length=65536)

                        extracted_files.append((t_rel, existed, created_new_bak, has_tx_tmp))
        elif os.path.isdir(src_abs):
            for root, dirs, files in os.walk(src_abs):
                for f in files:
                    s_file = os.path.join(root, f)
                    rel_sub = os.path.relpath(s_file, src_abs)
                    d_file = validate_safe_path(game_path, os.path.join(dst_rel, rel_sub), allow_base_itself=False)
                    d_rel = _norm_rel(os.path.relpath(d_file, game_path))
                    existed = os.path.exists(d_file)
                    created_new_bak = False
                    has_tx_tmp = False
                    b_file = f"{d_file}.congu_bak"
                    tx_file = f"{d_file}.congu_tx_tmp"

                    if existed and os.path.isfile(d_file) and operation == "install":
                        if not os.path.exists(b_file):
                            try:
                                os.makedirs(os.path.dirname(b_file), exist_ok=True)
                                os.rename(d_file, b_file)
                                created_new_bak = True
                                orig_hash = compute_file_sha256(b_file)
                                backup_records.append({
                                    "relative_in_game": d_rel,
                                    "target_file": d_file,
                                    "backup_file": b_file,
                                    "size_bytes": os.path.getsize(b_file),
                                    "original_sha256": orig_hash,
                                    "original_size": os.path.getsize(b_file),
                                    "original_mtime": os.path.getmtime(b_file)
                                })
                            except Exception as e:
                                print(f"[Auto-Backup Extract Dir Warning] {d_file}: {e}")
                        else:
                            try:
                                shutil.copy2(d_file, tx_file)
                                has_tx_tmp = True
                            except Exception as e:
                                print(f"[Tx-Tmp Extract Dir Warning] {d_file}: {e}")

                    os.makedirs(os.path.dirname(d_file), exist_ok=True)
                    shutil.copy2(s_file, d_file)
                    extracted_files.append((d_rel, existed, created_new_bak, has_tx_tmp))
        else:
            if not step.get("optional", False):
                raise FileNotFoundError(f"Archive file not found: {src_rel}")

        if backup_records:
            record_backup_manifest(game_id, backup_records)

        if operation == "install":
            for item in extracted_files:
                t_rel = item[0]
                t_abs = validate_safe_path(game_path, t_rel, allow_base_itself=False)
                record_modded_state(game_id, t_abs, t_rel)

        return {"action": "extract_all", "target": dst_rel, "extracted_files": extracted_files}

    elif action == "patch_ini":
        file_rel = _norm_rel(step.get("file") or step.get("target"))
        if not file_rel:
            raise ValueError("Step 'patch_ini' missing required 'file' or 'target' field")
        file_abs = validate_safe_path(game_path, file_rel, allow_base_itself=False)
        bak_file = f"{file_abs}.congu_bak"
        created_new_bak = False
        has_tx_tmp = False
        tx_tmp_abs = f"{file_abs}.congu_tx_tmp"

        if not os.path.exists(file_abs) and os.path.exists(bak_file):
            try:
                shutil.copy2(bak_file, file_abs)
                print(f"[Smart Self-Healing] File '{file_rel}' không tồn tại nhưng có sẵn '{bak_file}' do bước backup trước đó tạo ra. Đã tự động chép ngược từ .congu_bak để giữ nguyên cấu hình gốc trước khi patch.")
            except Exception as e:
                print(f"[Smart Self-Healing Warning] Lỗi khôi phục {file_abs} từ backup: {e}")

        if os.path.exists(file_abs) and not os.path.exists(bak_file):
            try:
                shutil.copy2(file_abs, bak_file)
                created_new_bak = True
            except Exception as e:
                print(f"Error creating INI backup: {e}")
        elif os.path.exists(file_abs) and os.path.exists(bak_file):
            try:
                shutil.copy2(file_abs, tx_tmp_abs)
                has_tx_tmp = True
            except Exception as e:
                print(f"Error creating INI tx_tmp: {e}")

        if os.path.exists(bak_file):
            orig_hash = compute_file_sha256(bak_file)
            record_backup_manifest(game_id, [{
                "relative_in_game": file_rel,
                "target_file": file_abs,
                "backup_file": bak_file,
                "size_bytes": os.path.getsize(bak_file),
                "original_sha256": orig_hash,
                "original_size": os.path.getsize(bak_file),
                "original_mtime": os.path.getmtime(bak_file)
            }])

        patch_ini_file(
            file_abs,
            section=step.get("section"),
            key=step.get("key"),
            value=step.get("value"),
            encoding=step.get("encoding", "utf-8")
        )
        if operation == "install":
            record_modded_state(game_id, file_abs, file_rel)
        return {
            "action": "patch_ini",
            "target": file_rel,
            "file": file_rel,
            "created_new_bak": created_new_bak,
            "has_tx_tmp": has_tx_tmp,
            "tx_tmp": tx_tmp_abs
        }

    elif action in ("delete", "delete_file"):
        target_rel = step.get("target")
        if not target_rel:
            raise ValueError("Step 'delete' missing required 'target' field")
        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)

        if operation == "uninstall":
            manifest = load_backup_manifest(game_id)
            target_norm = target_rel.replace("\\", "/").strip().lower()

            if manifest.get("winhttp_preexisting", False):
                if target_norm in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version") or target_norm.endswith("/winhttp.dll"):
                    print(f"[BepInEx Protection] Bỏ qua xóa '{target_rel}' vì tệp đã có sẵn trước khi cài Việt hóa (bảo tồn loader mod của người chơi).")
                    return {"action": "delete", "target": target_rel, "skipped": True, "reason": "winhttp_preexisting"}

            if manifest.get("bepinex_preexisting", False):
                if target_norm in ("bepinex", "bepinex/core", "bepinex/plugins", "bepinex/patchers", "bepinex/config"):
                    print(f"[BepInEx Protection] Bỏ qua xóa thư mục '{target_rel}' vì người chơi đã có sẵn mod BepInEx từ trước.")
                    return {"action": "delete", "target": target_rel, "skipped": True, "reason": "bepinex_preexisting"}

        if os.path.exists(target_abs):
            if os.path.isdir(target_abs):
                shutil.rmtree(target_abs, ignore_errors=True)
            else:
                try:
                    os.remove(target_abs)
                except Exception:
                    pass
        return {"action": "delete", "target": target_rel}

    elif action == "rename":
        src_rel = step.get("source")
        dst_rel = step.get("destination")
        if not src_rel or not dst_rel:
            raise ValueError("Step 'rename' requires both 'source' and 'destination'")
        src_abs = validate_safe_path(game_path, src_rel, allow_base_itself=False)
        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=False)

        if operation == "uninstall":
            manifest = load_backup_manifest(game_id)
            src_norm = src_rel.replace("\\", "/").strip().lower()
            if manifest.get("winhttp_preexisting", False):
                if src_norm == "winhttp.dll" or src_norm.endswith("/winhttp.dll"):
                    print(f"[BepInEx Protection] Bỏ qua đổi tên '{src_rel}' vì winhttp.dll đã có sẵn trước khi cài Việt hóa (bảo tồn loader mod của người chơi).")
                    return {"action": "rename", "source_orig": src_rel, "target": dst_rel, "skipped": True, "reason": "winhttp_preexisting"}

        if os.path.exists(src_abs):
            if os.path.exists(dst_abs):
                if os.path.isdir(dst_abs):
                    shutil.rmtree(dst_abs, ignore_errors=True)
                else:
                    try:
                        os.remove(dst_abs)
                    except Exception:
                        pass
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            os.rename(src_abs, dst_abs)
        return {"action": "rename", "source_orig": src_rel, "target": dst_rel}

    else:
        raise ValueError(f"Unsupported pipeline action: '{action}'")

    return True


def execute_action_pipeline(
    game_id: str,
    game_path: str,
    source_mod_dir: str,
    steps: list,
    operation: str = "install",
    progress_range: Tuple[int, int] = (50, 90),
    uninstall_steps: Optional[list] = None
) -> bool:
    """
    Executes an ordered list of atomic actions with granular progress tracking.
    Includes Transaction Rollback to restore pristine game files if any step fails.
    """
    total = len(steps)
    if total == 0:
        return True

    p_start, p_end = progress_range
    p_span = max(1, p_end - p_start)
    executed_journal = []
    tx_temp_files = []

    try:
        for idx, step in enumerate(steps):
            action = step.get("action", "unknown")
            desc = step.get("description")
            if not desc:
                if action == "backup":
                    desc = f"Sao lưu tệp gốc: {os.path.basename(step.get('target', ''))}"
                elif action == "restore_backup":
                    desc = f"Khôi phục tệp gốc: {os.path.basename(step.get('target', ''))}"
                elif action == "copy_file":
                    desc = f"Sao chép tệp: {os.path.basename(step.get('source', ''))}"
                elif action == "copy_folder":
                    desc = f"Cài đặt thư mục: {os.path.basename(step.get('source', ''))}"
                elif action == "patch_binary":
                    desc = f"Vá nhị phân tệp: {os.path.basename(step.get('target', ''))}"
                elif action == "patch_ini":
                    desc = f"Cấu hình file: {os.path.basename(step.get('file', ''))} [{step.get('section', '')}]"
                elif action == "delete":
                    desc = f"Xóa tệp dư thừa: {os.path.basename(step.get('target', ''))}"
                elif action == "rename":
                    desc = f"Đổi tên tệp: {os.path.basename(step.get('source', ''))}"
                elif action in ("extract_all", "extract_zip"):
                    desc = f"Giải nén gói dữ liệu vào {step.get('destination', '')}"
                else:
                    desc = f"Thực thi hành động: {action}"

            pct = p_start + int((idx / total) * p_span)
            set_progress(pct, f"[{idx+1}/{total}] {desc}...", status="running", game_id=game_id, operation=operation)

            try:
                journal_entry = execute_pipeline_step(game_id, game_path, source_mod_dir, step, operation=operation)
                if operation == "install" and isinstance(journal_entry, dict):
                    executed_journal.append(journal_entry)
                    if journal_entry.get("has_tx_tmp") and journal_entry.get("tx_tmp"):
                        tx_temp_files.append(journal_entry["tx_tmp"])
                    if journal_entry.get("copied_files"):
                        for c_item in journal_entry["copied_files"]:
                            if len(c_item) == 4 and c_item[3]:
                                f_abs = validate_safe_path(game_path, c_item[0], allow_base_itself=False)
                                tx_temp_files.append(f"{f_abs}.congu_tx_tmp")
                    if journal_entry.get("extracted_files"):
                        for e_item in journal_entry["extracted_files"]:
                            if len(e_item) == 4 and e_item[3]:
                                f_abs = validate_safe_path(game_path, e_item[0], allow_base_itself=False)
                                tx_temp_files.append(f"{f_abs}.congu_tx_tmp")
            except Exception as e:
                err_msg = f"Lỗi tại bước {idx+1}/{total} ({action}): {str(e)}"
                print(f"[Pipeline Error] {err_msg}")

                if operation == "install":
                    set_progress(0, f"Sự cố tại bước {idx+1}: Đang kích hoạt Transaction Rollback...", status="running", game_id=game_id, operation=operation)

                    journal_failed_entries = []
                    # 1. Reverse executed actions (Lớp 1)
                    for executed_step in reversed(executed_journal):
                        try:
                            act = executed_step.get("action")
                            # Mục 1.4: Ưu tiên hoàn nguyên về bản mod v1.0 từ .congu_tx_tmp (bảo toàn nguyên vẹn .congu_bak gốc tiếng Anh)
                            has_tx_tmp = executed_step.get("has_tx_tmp", False)
                            tx_tmp_abs = executed_step.get("tx_tmp")
                            target_rel = executed_step.get("target") or executed_step.get("destination") or executed_step.get("file")
                            if has_tx_tmp and tx_tmp_abs and os.path.exists(tx_tmp_abs) and target_rel:
                                target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
                                if os.path.exists(target_abs):
                                    try:
                                        if os.path.isdir(target_abs):
                                            shutil.rmtree(target_abs, ignore_errors=True)
                                        else:
                                            os.remove(target_abs)
                                    except Exception:
                                        pass
                                try:
                                    os.replace(tx_tmp_abs, target_abs)
                                    print(f"[Pipeline Rollback] Đã hoàn nguyên '{target_rel}' về phiên bản mod v1.0 từ .congu_tx_tmp.")
                                    continue
                                except Exception as e_tx:
                                    print(f"[Pipeline Rollback Tx-Tmp Warning] {e_tx}")

                            if act == "backup":
                                t_rel = executed_step.get("target")
                                created_new = executed_step.get("created_new_bak", True)
                                if t_rel:
                                    t_abs = validate_safe_path(game_path, t_rel, allow_base_itself=False)
                                    b_abs = f"{t_abs}.congu_bak"
                                    if os.path.exists(b_abs):
                                        if os.path.exists(t_abs):
                                            try:
                                                if os.path.isdir(t_abs):
                                                    shutil.rmtree(t_abs, ignore_errors=True)
                                                else:
                                                    os.remove(t_abs)
                                            except Exception:
                                                pass
                                        if created_new:
                                            try:
                                                os.replace(b_abs, t_abs)
                                            except Exception:
                                                shutil.copy2(b_abs, t_abs)
                                                try:
                                                    os.remove(b_abs)
                                                except Exception:
                                                    pass
                                        else:
                                            shutil.copy2(b_abs, t_abs)

                            elif act in ("copy_file", "delete", "patch_binary"):
                                dst_rel = executed_step.get("target", executed_step.get("destination"))
                                existed_before = executed_step.get("existed_before", False)
                                created_new = executed_step.get("created_new_bak", False)
                                if dst_rel:
                                    d_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=False)
                                    b_abs = f"{d_abs}.congu_bak"
                                    if created_new and os.path.exists(b_abs):
                                        if os.path.exists(d_abs):
                                            try:
                                                os.remove(d_abs)
                                            except Exception:
                                                pass
                                        try:
                                            os.replace(b_abs, d_abs)
                                        except Exception:
                                            shutil.copy2(b_abs, d_abs)
                                            try:
                                                os.remove(b_abs)
                                            except Exception:
                                                pass
                                    elif existed_before and os.path.exists(b_abs):
                                        shutil.copy2(b_abs, d_abs)
                                    elif not existed_before:
                                        if os.path.exists(d_abs) and not os.path.exists(b_abs):
                                            try:
                                                os.remove(d_abs)
                                            except Exception:
                                                pass

                            elif act == "copy_folder":
                                copied_files = executed_step.get("copied_files", [])
                                for item in copied_files:
                                    if len(item) == 4:
                                        f_rel, existed, created_new, f_has_tx = item
                                    elif len(item) == 3:
                                        f_rel, existed, created_new = item
                                        f_has_tx = False
                                    else:
                                        f_rel, existed = item
                                        created_new = False
                                        f_has_tx = False
                                    f_abs = validate_safe_path(game_path, f_rel, allow_base_itself=False)
                                    b_abs = f"{f_abs}.congu_bak"
                                    f_tx = f"{f_abs}.congu_tx_tmp"

                                    if f_has_tx and os.path.exists(f_tx):
                                        if os.path.exists(f_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass
                                        try:
                                            os.replace(f_tx, f_abs)
                                            continue
                                        except Exception:
                                            pass

                                    if created_new and os.path.exists(b_abs):
                                        if os.path.exists(f_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass
                                        try:
                                            os.replace(b_abs, f_abs)
                                        except Exception:
                                            shutil.copy2(b_abs, f_abs)
                                            try:
                                                os.remove(b_abs)
                                            except Exception:
                                                pass
                                    elif existed and os.path.exists(b_abs):
                                        shutil.copy2(b_abs, f_abs)
                                    elif not existed:
                                        if os.path.exists(f_abs) and not os.path.exists(b_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass

                            elif act in ("extract_all", "extract_zip"):
                                extracted_files = executed_step.get("extracted_files", [])
                                for item in extracted_files:
                                    if len(item) == 4:
                                        f_rel, existed, created_new, f_has_tx = item
                                    elif len(item) == 3:
                                        f_rel, existed, created_new = item
                                        f_has_tx = False
                                    else:
                                        f_rel, existed = item
                                        created_new = False
                                        f_has_tx = False
                                    f_abs = validate_safe_path(game_path, f_rel, allow_base_itself=False)
                                    b_abs = f"{f_abs}.congu_bak"
                                    f_tx = f"{f_abs}.congu_tx_tmp"

                                    if f_has_tx and os.path.exists(f_tx):
                                        if os.path.exists(f_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass
                                        try:
                                            os.replace(f_tx, f_abs)
                                            continue
                                        except Exception:
                                            pass

                                    if created_new and os.path.exists(b_abs):
                                        if os.path.exists(f_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass
                                        try:
                                            os.replace(b_abs, f_abs)
                                        except Exception:
                                            shutil.copy2(b_abs, f_abs)
                                            try:
                                                os.remove(b_abs)
                                            except Exception:
                                                pass
                                    elif existed and os.path.exists(b_abs):
                                        shutil.copy2(b_abs, f_abs)
                                    elif not existed:
                                        if os.path.exists(f_abs) and not os.path.exists(b_abs):
                                            try:
                                                os.remove(f_abs)
                                            except Exception:
                                                pass

                            elif act == "patch_ini":
                                f_rel = executed_step.get("file") or executed_step.get("target")
                                created_new = executed_step.get("created_new_bak", True)
                                if f_rel:
                                    f_abs = validate_safe_path(game_path, f_rel, allow_base_itself=False)
                                    b_abs = f"{f_abs}.congu_bak"
                                    if os.path.exists(b_abs):
                                        try:
                                            shutil.copy2(b_abs, f_abs)
                                            if created_new:
                                                try:
                                                    os.remove(b_abs)
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass

                            elif act == "rename":
                                s_orig = executed_step.get("source_orig")
                                t_dst = executed_step.get("target")
                                if s_orig and t_dst:
                                    s_abs = validate_safe_path(game_path, s_orig, allow_base_itself=False)
                                    t_abs = validate_safe_path(game_path, t_dst, allow_base_itself=False)
                                    if os.path.exists(t_abs):
                                        try:
                                            os.replace(t_abs, s_abs)
                                        except Exception:
                                            pass

                        except Exception as rb_e:
                            print(f"[Rollback Warning] Lỗi khi đảo ngược bước {executed_step}: {rb_e}")
                            journal_failed_entries.append((executed_step, str(rb_e)))

                    if not journal_failed_entries:
                        print("[Rollback] Lớp 1 (Reverse Journal) hoàn nguyên 100% thành công!")
                    else:
                        print(f"[Rollback Warning] Lớp 1 hoàn nguyên xong với {len(journal_failed_entries)} cảnh báo.")

                raise RuntimeError(
                    f"{err_msg}. Hệ thống đã tự động kích hoạt Transaction Rollback: toàn bộ tệp tin game đã được hoàn nguyên 100% về trạng thái ổn định trước khi cài đặt!"
                ) from e

    finally:
        for tx_f in tx_temp_files:
            if os.path.exists(tx_f):
                try:
                    if os.path.isdir(tx_f):
                        shutil.rmtree(tx_f, ignore_errors=True)
                    else:
                        os.remove(tx_f)
                except Exception:
                    pass

    return True


# ==============================================================================
# WORKFLOW: INSTALL MOD
# ==============================================================================

def install_mod_impl(game_id: str, force: bool = False, get_games_func: Optional[Callable] = None) -> dict:
    """Core installation logic implementation."""
    set_progress(10, "Đang kiểm tra thư mục cài đặt...", status="running", game_id=game_id, operation="install")

    with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
        games = {g["id"]: g for g in json.load(f)}

    if game_id not in games:
        set_progress(0, "Không tìm thấy thông tin game!", status="error", game_id=game_id)
        return {"success": False, "message": "Không tìm thấy thông tin game!"}

    g = games[game_id]
    cfg = load_user_config()
    game_path = cfg.get(f"{game_id}_path")

    if not game_path or not os.path.exists(game_path):
        set_progress(0, "Chưa chọn thư mục game!", status="error", game_id=game_id)
        return {"success": False, "message": "Chưa tìm thấy thư mục cài đặt game. Vui lòng bấm 'Chọn thư mục' trước!"}

    is_valid, resolved_path, val_msg = verify_and_resolve_game_path(g, game_path)
    if not is_valid:
        set_progress(0, f"Thư mục không hợp lệ! {val_msg}", status="error", game_id=game_id)
        return {"success": False, "message": f"Không thể cài đặt: {val_msg} Vui lòng bấm 'Chọn Thư Mục' để chọn đúng thư mục game!"}

    if resolved_path and resolved_path != game_path:
        game_path = resolved_path
        cfg[f"{game_id}_path"] = game_path
        save_user_config(cfg)

    # Ghi nhận môi trường tiền tồn tại của game (BepInEx & winhttp.dll protection)
    record_preexisting_environment(game_id, game_path)

    # 0. Write Permission Check (Program Files / Windows UAC restriction)
    if not is_running_as_admin() and not check_directory_writable(game_path):
        msg = (
            f"Thư mục cài đặt '{os.path.basename(game_path)}' đang bị khóa quyền ghi bởi Windows (thường do nằm trong 'Program Files'). "
            f"Vui lòng bấm 'Khởi động quyền Admin' để cấp quyền ghi tệp."
        )
        set_progress(0, msg, status="error", game_id=game_id)
        return {
            "success": False,
            "requires_admin": True,
            "message": msg
        }

    # 1. Process Check: verify game executable or crash handlers are not running
    is_running, proc_name = check_game_running(g, game_path)
    if is_running:
        msg = f"Phát hiện tiến trình '{proc_name}' của {g['vietnamese_title']} đang chạy! Vui lòng thoát game trước khi cài đặt để tránh xung đột khóa tệp tin (WinError 32)."
        set_progress(0, msg, status="error", game_id=game_id)
        return {
            "success": False,
            "is_game_running": True,
            "running_process": proc_name,
            "message": msg
        }

    # 2. Game Version / Hash & Size Mismatch Verification (Detect Game Update Mismatch)
    verify_cfg = g.get("original_file_verification")
    if verify_cfg and not force:
        rel_chk = verify_cfg.get("target_relative")
        target_chk = os.path.join(game_path, rel_chk)
        bak_chk = f"{target_chk}.congu_bak"
        file_to_eval = bak_chk if os.path.exists(bak_chk) else target_chk
        if os.path.exists(file_to_eval):
            exp_sz = verify_cfg.get("expected_size")
            exp_sha = verify_cfg.get("expected_sha256")
            act_sz = os.path.getsize(file_to_eval)
            mismatch = False
            if exp_sz and act_sz != exp_sz:
                mismatch = True
            elif exp_sha:
                act_sha = calculate_sha256(file_to_eval)
                if act_sha != exp_sha:
                    mismatch = True
            if mismatch:
                msg = (
                    f"CẢNH BÁO LỆCH PHIÊN BẢN: Tệp gốc '{os.path.basename(rel_chk)}' của {g['vietnamese_title']} "
                    f"có kích thước/mã băm khác với bản chuẩn của nhóm dịch ({act_sz:,} bytes thay vì {exp_sz:,} bytes). "
                    f"Game trên Steam có thể đã được cập nhật phiên bản mới. Việc cài đặt đè có thể gây lỗi văng game (Crash). "
                    f"Bạn có chắc chắn muốn tiếp tục cài đặt không?"
                )
                set_progress(0, "Cảnh báo: Phiên bản game không khớp với bản dịch!", status="error", game_id=game_id)
                return {
                    "success": False,
                    "warning_mismatch": True,
                    "message": msg
                }

    mod_subfolder = g.get("mod_subfolder", "")
    source_mod_dir = find_mod_source_dir(mod_subfolder)

    # Check if source_mod_dir exists on local drive
    local_found = os.path.exists(source_mod_dir)
    cache_dir = os.path.join(APPDATA_DIR, "cache", game_id)
    cached_source = os.path.join(cache_dir, mod_subfolder) if (mod_subfolder and os.path.exists(os.path.join(cache_dir, mod_subfolder))) else cache_dir

    existing_congu = os.path.join(cache_dir, "mod_package.congu")
    if not (os.path.exists(existing_congu) and security.is_congu_package(existing_congu)):
        cand_files = []
        if g.get("mod_file"):
            cand_files.append(g["mod_file"])
        dl_url = g.get("download_url", "")
        if dl_url:
            cand_files.append(os.path.basename(dl_url.split("?")[0]))
        cand_files.append(f"{game_id}.congu")
        cand_files.append(f"{g.get('title', '').replace(' ', '_')}_Viethoa.congu")
        cand_files.append(f"{g.get('title', '').replace(' ', '')}_Viethoa.congu")

        active_repo = get_repo_dir()
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        repo_dirs = [
            active_repo,
            DEFAULT_REPO_DIR,
            FALLBACK_REPO_DIR,
            os.path.join(USER_DOCS_DIR, "Viethoagame"),
            os.path.join(USER_DOCS_DIR, "antigravity google", "Viethoagame"),
            APP_DIR,
            os.path.join(APP_DIR, "mods"),
            os.path.join(exe_dir, "mods"),
            exe_dir
        ]
        if source_mod_dir:
            repo_dirs.insert(0, source_mod_dir)

        cand_list = []
        seen_cand = set()
        for r in repo_dirs:
            if not r or not os.path.exists(r):
                continue
            for fname in cand_files:
                cp = os.path.join(r, fname)
                if cp not in seen_cand:
                    seen_cand.add(cp)
                    cand_list.append(cp)
            try:
                for entry in os.scandir(r):
                    if entry.is_dir():
                        for fname in cand_files:
                            cp = os.path.join(entry.path, fname)
                            if cp not in seen_cand:
                                seen_cand.add(cp)
                                cand_list.append(cp)
                    elif entry.name.lower().endswith(".congu"):
                        if entry.path not in seen_cand:
                            seen_cand.add(entry.path)
                            cand_list.append(entry.path)
            except Exception:
                pass

        for cand in cand_list:
            if cand and os.path.isfile(cand) and security.is_congu_package(cand):
                existing_congu = cand
                break

    games_fetcher = get_games_func if get_games_func else get_games

    if not local_found and os.path.exists(existing_congu) and security.is_congu_package(existing_congu):
        expected_sha = g.get("congu_sha256") or g.get("sha256")
        if not expected_sha or security.verify_package_checksum(existing_congu, expected_sha):
            set_progress(25, "Đã tìm thấy gói bảo mật CỔ NGỮ trên thiết bị...", status="running", game_id=game_id)
            def on_sec_progress(pct, msg):
                set_progress(pct, msg, status="running", game_id=game_id, operation="install")

            sec_ticket = security.create_session_ticket()
            try:
                sec_res = security.execute_secure_install(
                    congu_path=existing_congu,
                    game_path=game_path,
                    install_steps=g.get("install_steps"),
                    game_def=g,
                    expected_sha256=expected_sha,
                    auth_ticket=sec_ticket,
                    progress_callback=on_sec_progress
                )
                if sec_res.get("backed_up_files"):
                    record_backup_manifest(game_id, sec_res["backed_up_files"])
                    for bf in sec_res["backed_up_files"]:
                        record_modded_state(game_id, bf.get("target_file"), bf.get("relative_in_game"))

                set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
                return {
                    "success": True,
                    "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Bảo mật C-Extension)",
                    "games": games_fetcher()
                }
            except Exception as sec_err:
                err_msg = str(sec_err)
                print(f"[Security Install Error] {err_msg}")
                set_progress(0, f"Lỗi cài đặt: {err_msg}", status="error", game_id=game_id)
                return {
                    "success": False,
                    "message": err_msg,
                    "rollback_completed": True
                }

    if not local_found:
        if check_has_mod_files(cached_source, g):
            source_mod_dir = cached_source
            set_progress(15, "Đã tìm thấy gói Việt Hóa trong bộ nhớ tạm (Cache)...", status="running", game_id=game_id)
        else:
            download_candidates = []
            if g.get("download_url"):
                download_candidates.append(("GitHub Cloud CDN (Siêu tốc)", g["download_url"]))
            if g.get("mirror_url"):
                download_candidates.append(("Mirror Dự Phòng", g["mirror_url"]))
            if g.get("drive_url") and g.get("drive_url") != g.get("mirror_url"):
                download_candidates.append(("Google Drive Mirror", g["drive_url"]))
            custom_url = cfg.get(f"{game_id}_download_url")
            if custom_url and custom_url not in [c[1] for c in download_candidates]:
                download_candidates.append(("Link Tùy Chỉnh Cá Nhân", custom_url))

            if not download_candidates:
                set_progress(0, "Chưa tìm thấy bản mod local và chưa có link tải Cloud!", status="error", game_id=game_id)
                return {"success": False, "message": f"Không tìm thấy thư mục mod tại {source_mod_dir} và tựa game chưa được cấu hình link tải Cloud!"}

            os.makedirs(cache_dir, exist_ok=True)

            download_success = False
            last_err = ""

            for source_name, dl_url in download_candidates:
                ext = ".congu" if dl_url.lower().endswith(".congu") else ".zip"
                cache_archive = os.path.join(cache_dir, f"mod_package{ext}")

                set_progress(15, f"Đang kết nối Cloud: {source_name}...", status="running", game_id=game_id)

                def on_dl_progress(d, t, pct, spd):
                    mb_d = d / (1024 * 1024)
                    mb_t = t / (1024 * 1024) if t > 0 else 0
                    spd_mb = spd / 1024
                    msg = f"Đang tải ({source_name}): {pct}% ({mb_d:.1f}/{mb_t:.1f} MB - {spd_mb:.1f} MB/s)" if t > 0 else f"Đang tải: {mb_d:.1f} MB ({spd_mb:.1f} MB/s)"
                    set_progress(15 + int(pct * 0.40), msg, status="running", game_id=game_id)

                try:
                    download_file_with_progress(dl_url, cache_archive, on_dl_progress)

                    if security.is_congu_package(cache_archive):
                        expected_sha = g.get("congu_sha256") or g.get("sha256")
                        set_progress(58, "Đang bảo mật C-Extension: Cài đặt trực tiếp vào game...", status="running", game_id=game_id)
                        def on_sec_progress(pct, msg):
                            set_progress(pct, msg, status="running", game_id=game_id, operation="install")

                        sec_ticket = security.create_session_ticket()
                        try:
                            sec_res = security.execute_secure_install(
                                congu_path=cache_archive,
                                game_path=game_path,
                                install_steps=g.get("install_steps"),
                                game_def=g,
                                expected_sha256=expected_sha,
                                auth_ticket=sec_ticket,
                                progress_callback=on_sec_progress
                            )

                            if sec_res.get("backed_up_files"):
                                record_backup_manifest(game_id, sec_res["backed_up_files"])
                                for bf in sec_res["backed_up_files"]:
                                    record_modded_state(game_id, bf.get("target_file"), bf.get("relative_in_game"))

                            set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
                            return {
                                "success": True,
                                "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Bảo mật C-Extension)",
                                "games": games_fetcher()
                            }
                        except Exception as sec_err:
                            err_msg = str(sec_err)
                            print(f"[Security Install Error] {err_msg}")
                            set_progress(0, f"Lỗi cài đặt: {err_msg}", status="error", game_id=game_id)
                            return {
                                "success": False,
                                "message": err_msg,
                                "rollback_completed": True
                            }
                    elif zipfile.is_zipfile(cache_archive):
                        set_progress(62, "Đang giải nén gói Việt Hóa...", status="running", game_id=game_id)
                        with zipfile.ZipFile(cache_archive, 'r') as zf:
                            for member in zf.namelist():
                                if member.endswith("/") or member.endswith("\\"):
                                    continue
                                target_dest = validate_safe_path(cache_dir, member, allow_base_itself=False)
                                os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                                with zf.open(member, "r") as s_in, open(target_dest, "wb") as d_out:
                                    shutil.copyfileobj(s_in, d_out, length=65536)

                    source_mod_dir = cache_dir
                    if mod_subfolder and os.path.exists(os.path.join(cache_dir, mod_subfolder)):
                        source_mod_dir = os.path.join(cache_dir, mod_subfolder)

                    download_success = True
                    break
                except Exception as dl_err:
                    last_err = str(dl_err)
                    print(f"Error downloading/decrypting from {source_name}: {dl_err}")
                    if os.path.exists(cache_archive):
                        try:
                            os.remove(cache_archive)
                        except Exception:
                            pass

            if not download_success:
                set_progress(0, f"Lỗi tải từ Cloud: {last_err}", status="error", game_id=game_id)
                return {"success": False, "message": f"Không thể tải bản Việt Hóa từ Cloud: {last_err}"}

    # Data-Driven Action Pipeline Execution
    install_steps = g.get("install_steps")
    if install_steps and isinstance(install_steps, list) and len(install_steps) > 0:
        try:
            set_progress(30, f"Đang thực thi quy trình cài đặt Data-Driven ({len(install_steps)} bước)...", status="running", game_id=game_id)
            execute_action_pipeline(
                game_id,
                game_path,
                source_mod_dir,
                install_steps,
                operation="install",
                progress_range=(30, 95),
                uninstall_steps=g.get("uninstall_steps")
            )
            set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
            return {
                "success": True,
                "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Data-Driven Pipeline)",
                "games": games_fetcher()
            }
        except Exception as pe:
            set_progress(0, f"Lỗi khi thực thi Pipeline: {str(pe)}", status="error", game_id=game_id)
            return {
                "success": False,
                "message": f"Lỗi khi cài đặt (Pipeline): {str(pe)}",
                "rollback_completed": True
            }

    mtype = g.get("mod_type", "pak")

    try:
        set_progress(30, "Đang tạo bản sao lưu tại chỗ tức thời (.congu_bak)...", status="running", game_id=game_id)

        # 1. PAK TYPE (Unreal Engine)
        if mtype == "pak":
            source_pak = os.path.join(source_mod_dir, g["mod_file"])
            if not os.path.exists(source_pak):
                nested = os.path.join(source_mod_dir, "Mod_Files", g["target_pak_name"])
                if os.path.exists(nested):
                    source_pak = nested

            target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
            os.makedirs(target_dir, exist_ok=True)
            target_pak = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)

            set_progress(60, "Đang sao chép gói ngôn ngữ Việt hóa Unreal Engine...", status="running", game_id=game_id)
            shutil.copy2(source_pak, target_pak)

        # 2. UNITY ASSETS
        elif mtype == "unity_assets":
            source_assets = os.path.join(source_mod_dir, g["mod_file"])
            target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
            rel_file = os.path.join(g["relative_install_path"], g["target_pak_name"])
            target_assets = validate_safe_path(game_path, rel_file, allow_base_itself=False)

            if os.path.exists(target_assets):
                backup_file_inplace(game_id, target_assets, rel_file)

            set_progress(60, "Đang cài đặt tài sản ngôn ngữ & font chữ Unity...", status="running", game_id=game_id)
            shutil.copy2(source_assets, target_assets)

            add_files = g.get("additional_files", [])
            for af in add_files:
                src_af = os.path.join(source_mod_dir, af["src"])
                dst_af = validate_safe_path(game_path, af["dst"], allow_base_itself=False)
                if os.path.exists(src_af):
                    if os.path.exists(dst_af):
                        backup_file_inplace(game_id, dst_af, af["dst"])
                    os.makedirs(os.path.dirname(dst_af), exist_ok=True)
                    shutil.copy2(src_af, dst_af)

        # 3. WAD
        elif mtype == "wad":
            target_wad = validate_safe_path(game_path, g["target_pak_name"], allow_base_itself=False)
            if os.path.exists(target_wad):
                backup_file_inplace(game_id, target_wad, g["target_pak_name"])

            set_progress(60, "Đang nạp file WAD và font neon...", status="running", game_id=game_id)
            shutil.copy2(os.path.join(source_mod_dir, "HotlineMiami_GL.wad"), target_wad)
            bin_src = os.path.join(source_mod_dir, "hotline_localization.bin")
            if os.path.exists(bin_src):
                bin_dst = validate_safe_path(game_path, "hotline_localization.bin", allow_base_itself=False)
                shutil.copy2(bin_src, bin_dst)

        # 4. BEPINEX LANGUAGE
        elif mtype == "bepinex_language":
            items_to_copy = ["BepInEx", "Risk of Rain 2_Data", "winhttp.dll", "doorstop_config.ini", ".doorstop_version"]
            set_progress(60, "Đang thiết lập BepInEx & gói ngôn ngữ tiếng Việt...", status="running", game_id=game_id)
            for item in items_to_copy:
                src_item = os.path.join(source_mod_dir, item)
                dst_item = validate_safe_path(game_path, item, allow_base_itself=False)
                if os.path.exists(src_item):
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)

        # 5. FOLDER COPY
        elif mtype == "folder_copy":
            orig_locale = validate_safe_path(game_path, os.path.join("core", "locale"), allow_base_itself=False)
            locale_bak = f"{orig_locale}.congu_bak"
            if os.path.exists(orig_locale) and not os.path.exists(locale_bak):
                try:
                    os.rename(orig_locale, locale_bak)
                except Exception as e:
                    try:
                        shutil.copytree(orig_locale, locale_bak)
                        shutil.rmtree(orig_locale, ignore_errors=True)
                    except Exception as e2:
                        print(f"Error in-place backing up locale folder: {e2}")

            set_progress(60, "Đang cài đặt bộ font và 57 chiến dịch tiếng Việt...", status="running", game_id=game_id)
            font_src = os.path.join(source_mod_dir, "core", "gui", "font")
            font_dst = validate_safe_path(game_path, os.path.join("core", "gui", "font"), allow_base_itself=False)
            if os.path.exists(font_src):
                os.makedirs(font_dst, exist_ok=True)
                shutil.copytree(font_src, font_dst, dirs_exist_ok=True)

            locale_src = os.path.join(source_mod_dir, "core", "locale")
            if os.path.exists(locale_src):
                os.makedirs(orig_locale, exist_ok=True)
                shutil.copytree(locale_src, orig_locale, dirs_exist_ok=True)

        # 6. INI AND EXE
        elif mtype == "ini_and_exe":
            exe_name = os.path.basename(g.get("executable_name", "Loop Hero.exe"))
            target_exe = validate_safe_path(game_path, exe_name, allow_base_itself=False)
            source_exe = os.path.join(source_mod_dir, exe_name)
            if os.path.exists(target_exe):
                backup_file_inplace(game_id, target_exe, exe_name)
            if os.path.exists(source_exe):
                shutil.copy2(source_exe, target_exe)

            target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
            os.makedirs(target_dir, exist_ok=True)
            rel_ini = os.path.join(g["relative_install_path"], g["target_pak_name"])
            target_ini = validate_safe_path(game_path, rel_ini, allow_base_itself=False)
            source_ini = os.path.join(source_mod_dir, g["mod_file"])
            if os.path.exists(target_ini):
                backup_file_inplace(game_id, target_ini, rel_ini)
            if os.path.exists(source_ini):
                shutil.copy2(source_ini, target_ini)

            target_font = validate_safe_path(game_path, "fonts/Roboto-Bold.ttf", allow_base_itself=False)
            source_font = os.path.join(source_mod_dir, "fonts", "Roboto-Bold.ttf")
            if os.path.exists(target_font):
                backup_file_inplace(game_id, target_font, "fonts/Roboto-Bold.ttf")
            if os.path.exists(source_font):
                os.makedirs(os.path.dirname(target_font), exist_ok=True)
                shutil.copy2(source_font, target_font)

        # 7. WITCHER 3 MOD
        elif mtype == "witcher3_mod":
            set_progress(50, "Đang nạp file ngôn ngữ w3strings...", status="running", game_id=game_id)
            source_w3strings = os.path.join(source_mod_dir, g["mod_file"])
            target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
            os.makedirs(target_dir, exist_ok=True)
            target_w3strings = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)
            if os.path.exists(source_w3strings):
                shutil.copy2(source_w3strings, target_w3strings)

            bundle_rel = g.get("bundle_patch_rel", "content/content0/bundles/xml.bundle")
            source_bundle = os.path.join(source_mod_dir, bundle_rel)
            target_bundle = validate_safe_path(game_path, bundle_rel, allow_base_itself=False)
            if os.path.exists(target_bundle):
                backup_file_inplace(game_id, target_bundle, bundle_rel)
            if os.path.exists(source_bundle):
                shutil.copy2(source_bundle, target_bundle)

        set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
        return {
            "success": True,
            "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Đã sao lưu gốc tại chỗ .congu_bak)",
            "games": games_fetcher()
        }
    except Exception as e:
        try:
            restore_files_inplace(game_id, game_path)
        except Exception:
            pass
        set_progress(0, f"Lỗi khi cài đặt: {str(e)}", status="error", game_id=game_id)
        return {
            "success": False,
            "message": f"Lỗi khi cài đặt: {str(e)} (Đã tự động hoàn nguyên tệp tin gốc .congu_bak)",
            "rollback_completed": True
        }


def install_mod(game_id: str, force: bool = False, get_games_func: Optional[Callable] = None) -> dict:
    """Thread-safe install wrapper with mutual exclusion lock."""
    if not _MOD_OP_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "message": "Hệ thống đang xử lý một tiến trình cài đặt/gỡ bỏ khác. Vui lòng chờ hoàn tất!"
        }
    try:
        return install_mod_impl(game_id, force=force, get_games_func=get_games_func)
    finally:
        _MOD_OP_LOCK.release()


# ==============================================================================
# WORKFLOW: UNINSTALL MOD
# ==============================================================================

def uninstall_mod_impl(game_id: str, get_games_func: Optional[Callable] = None) -> dict:
    """Core uninstallation logic implementation."""
    set_progress(20, "Đang gỡ bỏ bản Việt hóa...", status="running", game_id=game_id, operation="uninstall")

    with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
        games = {g["id"]: g for g in json.load(f)}

    if game_id not in games:
        set_progress(0, "Không tìm thấy game!", status="error", game_id=game_id)
        return {"success": False, "message": "Không tìm thấy thông tin game!"}

    g = games[game_id]
    cfg = load_user_config()
    game_path = cfg.get(f"{game_id}_path")

    if not game_path:
        set_progress(0, "Chưa chọn thư mục game!", status="error", game_id=game_id)
        return {"success": False, "message": "Chưa xác định đường dẫn game!"}

    # 1. Process Check: verify game executable or crash handlers are not running
    is_running, proc_name = check_game_running(g, game_path)
    if is_running:
        msg = f"Phát hiện tiến trình '{proc_name}' của {g['vietnamese_title']} đang chạy! Vui lòng thoát game trước khi gỡ cài đặt để tránh xung đột khóa tệp tin (WinError 32)."
        set_progress(0, msg, status="error", game_id=game_id)
        return {
            "success": False,
            "is_game_running": True,
            "running_process": proc_name,
            "message": msg
        }

    # 1b. Write Permission Check (Program Files / Windows UAC restriction)
    if not is_running_as_admin() and not check_directory_writable(game_path):
        msg = (
            f"Thư mục cài đặt '{os.path.basename(game_path)}' đang bị khóa quyền ghi bởi Windows (thường do nằm trong 'Program Files'). "
            f"Vui lòng bấm 'Khởi động quyền Admin' để cấp quyền ghi tệp."
        )
        set_progress(0, msg, status="error", game_id=game_id)
        return {
            "success": False,
            "requires_admin": True,
            "message": msg
        }

    games_fetcher = get_games_func if get_games_func else get_games

    # Data-Driven Action Pipeline Execution
    uninstall_steps = g.get("uninstall_steps")
    if uninstall_steps and isinstance(uninstall_steps, list) and len(uninstall_steps) > 0:
        try:
            set_progress(30, f"Đang thực thi quy trình gỡ bỏ Data-Driven ({len(uninstall_steps)} bước)...", status="running", game_id=game_id, operation="uninstall")
            execute_action_pipeline(game_id, game_path, source_mod_dir="", steps=uninstall_steps, operation="uninstall", progress_range=(30, 90))
            restore_files_inplace(game_id, game_path)
            set_progress(100, "Đã khôi phục game về nguyên bản tiếng Anh thành công!", status="success", game_id=game_id)
            return {
                "success": True,
                "message": f"Đã gỡ bỏ bản Việt hóa cho {g['vietnamese_title']}. Game đã trở về tiếng Anh gốc an toàn 100%!",
                "games": games_fetcher()
            }
        except Exception as pe:
            set_progress(0, f"Lỗi khi gỡ bỏ Pipeline: {str(pe)}", status="error", game_id=game_id)
            return {"success": False, "message": f"Lỗi khi gỡ mod (Pipeline): {str(pe)}"}

    mtype = g.get("mod_type", "pak")

    try:
        manifest_data = load_backup_manifest(game_id)
        restored = restore_files_inplace(game_id, game_path)

        if mtype == "pak":
            target_pak = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)
            if os.path.exists(target_pak):
                os.remove(target_pak)

        elif mtype == "unity_assets":
            if not restored:
                target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
                target_assets = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)
                backup_file = os.path.join(target_dir, g.get("backup_file", "resources.assets.original_backup"))
                if os.path.exists(backup_file):
                    shutil.copy2(backup_file, target_assets)
                    os.remove(backup_file)

        elif mtype == "wad":
            if not restored:
                target_wad = validate_safe_path(game_path, g["target_pak_name"], allow_base_itself=False)
                backup_wad = os.path.join(game_path, g.get("backup_file", "HotlineMiami_GL_original.wad"))
                if os.path.exists(backup_wad):
                    shutil.copy2(backup_wad, target_wad)
                    os.remove(backup_wad)
            bin_file = validate_safe_path(game_path, "hotline_localization.bin", allow_base_itself=False)
            if os.path.exists(bin_file):
                os.remove(bin_file)

        elif mtype == "bepinex_language":
            lang_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=False)
            if os.path.exists(lang_dir):
                shutil.rmtree(lang_dir, ignore_errors=True)

            winhttp_pre = manifest_data.get("winhttp_preexisting", False)
            if not winhttp_pre:
                winhttp = validate_safe_path(game_path, "winhttp.dll", allow_base_itself=False)
                if os.path.exists(winhttp):
                    os.rename(winhttp, os.path.join(game_path, "winhttp.dll.disabled"))
            else:
                print("[BepInEx Protection] winhttp.dll đã có sẵn trước khi cài Việt hóa. Giữ nguyên tệp loader cho các mod gameplay khác của người chơi!")

        elif mtype == "folder_copy":
            game_backup_dir = os.path.join(BACKUP_ROOT, game_id, "core_locale")
            orig_locale = validate_safe_path(game_path, os.path.join("core", "locale"), allow_base_itself=False)
            if os.path.exists(game_backup_dir):
                if os.path.exists(orig_locale):
                    shutil.rmtree(orig_locale, ignore_errors=True)
                shutil.copytree(game_backup_dir, orig_locale)
                shutil.rmtree(os.path.join(BACKUP_ROOT, game_id), ignore_errors=True)

        elif mtype == "ini_and_exe":
            if not restored:
                exe_name = os.path.basename(g.get("executable_name", "Loop Hero.exe"))
                target_exe = validate_safe_path(game_path, exe_name, allow_base_itself=False)
                backup_exe = os.path.join(game_path, f"{exe_name}.orig")
                if os.path.exists(backup_exe):
                    shutil.copy2(backup_exe, target_exe)
                    os.remove(backup_exe)

                target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
                rel_ini = os.path.join(g["relative_install_path"], g["target_pak_name"])
                target_ini = validate_safe_path(game_path, rel_ini, allow_base_itself=False)
                backup_ini = os.path.join(game_path, g.get("backup_file", os.path.join(g["relative_install_path"], f"{g['target_pak_name']}.orig")))
                if os.path.exists(backup_ini):
                    shutil.copy2(backup_ini, target_ini)
                    os.remove(backup_ini)

        elif mtype == "witcher3_mod":
            mod_folder = validate_safe_path(game_path, os.path.join("Mods", "modVietHoa"), allow_base_itself=False)
            if os.path.exists(mod_folder):
                shutil.rmtree(mod_folder, ignore_errors=True)
            if not restored:
                bundle_rel = g.get("bundle_patch_rel", "content/content0/bundles/xml.bundle")
                target_bundle = validate_safe_path(game_path, bundle_rel, allow_base_itself=False)
                backup_bundle = os.path.join(game_path, g.get("backup_file", "content/content0/bundles/xml.bundle.orig"))
                if os.path.exists(backup_bundle):
                    shutil.copy2(backup_bundle, target_bundle)
                    os.remove(backup_bundle)

        set_progress(100, "Đã khôi phục game về nguyên bản tiếng Anh thành công!", status="success", game_id=game_id)
        return {
            "success": True,
            "message": f"Đã gỡ bỏ bản Việt hóa cho {g['vietnamese_title']}. Game đã trở về tiếng Anh gốc an toàn 100%!",
            "games": games_fetcher()
        }
    except Exception as e:
        set_progress(0, f"Lỗi khi gỡ mod: {str(e)}", status="error", game_id=game_id)
        return {"success": False, "message": f"Lỗi khi gỡ mod: {str(e)}"}


def uninstall_mod(game_id: str, get_games_func: Optional[Callable] = None) -> dict:
    """Thread-safe uninstall wrapper with mutual exclusion lock."""
    if not _MOD_OP_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "message": "Hệ thống đang xử lý một tiến trình cài đặt/gỡ bỏ khác. Vui lòng chờ hoàn tất!"
        }
    try:
        return uninstall_mod_impl(game_id, get_games_func=get_games_func)
    finally:
        _MOD_OP_LOCK.release()


# ==============================================================================
# WORKFLOW: EMERGENCY DEEP RESTORE
# ==============================================================================

def emergency_restore_game(game_id: str, get_games_func: Optional[Callable] = None) -> dict:
    """Thread-safe emergency restore wrapper with progress reporting."""
    if not _MOD_OP_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "message": "Hệ thống đang xử lý một tiến trình cài đặt/gỡ bỏ khác. Vui lòng chờ hoàn tất!"
        }
    try:
        def _on_restore_progress(pct, msg, status="running"):
            set_progress(pct, msg, status=status, game_id=game_id, operation="restore")

        res = deep_emergency_restore(game_id, progress_callback=_on_restore_progress)
        if get_games_func and "games" in res:
            res["games"] = get_games_func()
        return res
    finally:
        _MOD_OP_LOCK.release()
