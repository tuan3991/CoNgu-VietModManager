# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Atomic Actions & Step Executor
"""
import os
import sys
import shutil
import zipfile
import hashlib
from typing import Optional, Any

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch
except ImportError:
    pass

from core.config_manager import BACKUP_ROOT, get_active_games_json_path, get_games
from core.backup_rollback import (
    backup_file_inplace, load_backup_manifest, save_backup_manifest,
    record_backup_manifest, record_modded_state, norm_rel_path,
    compute_file_sha256
)


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


