# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Pipeline Runner & Progress Tracking
"""
import os
import sys
import json
import shutil
import tempfile
import threading
import time
from typing import Dict, Any, List, Optional, Tuple, Callable

from core.config_manager import (
    load_user_config, save_user_config, BACKUP_ROOT, get_games
)
from core.backup_rollback import (
    load_backup_manifest, save_backup_manifest, restore_files_inplace
)
from .actions import execute_pipeline_step
from security import validate_safe_path

_GAME_LOCKS_GUARD = threading.Lock()
_GAME_OPERATION_LOCKS: Dict[str, threading.Lock] = {}


def any_game_operation_running() -> bool:
    """True khi ít nhất một lock theo game đang được giữ trong process."""
    with _GAME_LOCKS_GUARD:
        return any(lock.locked() for lock in _GAME_OPERATION_LOCKS.values())


def get_game_operation_lock(game_id: str) -> threading.Lock:
    """Trả về lock riêng cho mỗi game trong cùng tiến trình.

    Không để install/uninstall/restore của cùng game chạy chồng; game khác vẫn
    không phải chờ thao tác I/O dài của nhau.
    """
    key = str(game_id or "").strip()
    if not key:
        raise ValueError("game_id không được để trống khi khóa thao tác")
    with _GAME_LOCKS_GUARD:
        lock = _GAME_OPERATION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _GAME_OPERATION_LOCKS[key] = lock
        return lock


INSTALL_PROGRESS = {
    "status": "idle",       # "idle", "running", "success", "error"
    "percent": 0,
    "message": "",
    "game_id": "",
    "operation": ""         # "install" | "uninstall" | "restore"
}

# Alias tương thích ngược. Wrapper mới phải dùng get_game_operation_lock(game_id).
_MOD_OP_LOCK = threading.Lock()


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


def _transaction_journal_path(game_id: str, backup_root: str = None) -> str:
    root = backup_root or BACKUP_ROOT
    return os.path.join(root, str(game_id), "pending_transaction.json")


def has_pending_transaction(game_id: str, backup_root: str = None) -> bool:
    """Kiểm tra sự tồn tại, kể cả journal rỗng, hỏng hoặc là symlink."""
    return os.path.lexists(_transaction_journal_path(game_id, backup_root))


def _save_transaction_journal(game_id: str, data: dict, backup_root: str = None) -> str:
    """Ghi journal atomically để crash/kill không để JSON nửa chừng."""
    path = _transaction_journal_path(game_id, backup_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".pending-transaction-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, path)
        return path
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _remove_transaction_journal(game_id: str, backup_root: str = None) -> None:
    try:
        os.remove(_transaction_journal_path(game_id, backup_root))
    except OSError:
        pass


def get_pending_transaction(game_id: str, backup_root: str = None) -> dict:
    """Đọc transaction gián đoạn; trả {} nếu không có hoặc journal lỗi."""
    try:
        with open(_transaction_journal_path(game_id, backup_root), "r", encoding="utf-8") as source:
            data = json.load(source)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def recover_pending_transaction(game_id: str, game_path: str, backup_root: str = None) -> dict:
    """Phát hiện transaction chưa hoàn tất, không tự thay đổi file game.

    Journal hiện chỉ ghi số bước, không đủ để tái tạo rollback. Hàm restore cũ
    có thể bỏ qua lỗi từng file và dọn manifest nên không được dùng tự động.
    """
    pending = get_pending_transaction(game_id, backup_root)
    if not pending:
        return {"success": True, "recovered": False}
    return {
        "success": False,
        "recovered": False,
        "message": "Phát hiện giao dịch gián đoạn; chưa thể khôi phục tự động an toàn. Giữ nguyên journal và backup để kiểm tra thủ công.",
    }


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
    # Chỉ dọn transaction temp khi rollback đã hoàn tất hoặc pipeline thành công.
    # Nếu rollback lỗi, chúng có thể là con đường khôi phục thủ công duy nhất.
    preserve_tx_temp = False
    journal_state = {
        "version": 1,
        "game_id": game_id,
        "game_path": os.path.abspath(game_path),
        "operation": operation,
        "status": "running",
        "started_at": int(time.time()),
        "completed_steps": 0,
        "total_steps": total,
    }
    # Chỉ install có transaction rollback chuẩn; persist trước thao tác đầu tiên
    # để lần khởi động sau biết rõ install đã gián đoạn.
    if operation == "install":
        if has_pending_transaction(game_id):
            raise RuntimeError("Game có journal giao dịch chưa xử lý; không bắt đầu pipeline mới để tránh ghi đè dữ liệu phục hồi.")
        _save_transaction_journal(game_id, journal_state)

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
                if operation == "install":
                    journal_state["completed_steps"] = idx + 1
                    journal_state["last_action"] = action
                    _save_transaction_journal(game_id, journal_state)
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
                        if operation == "install":
                            _remove_transaction_journal(game_id)
                        rollback_message = (
                            f"{err_msg}. Hệ thống đã tự động kích hoạt Transaction Rollback: "
                            "toàn bộ tệp tin game đã được hoàn nguyên về trạng thái ổn định trước khi cài đặt!"
                        )
                    else:
                        preserve_tx_temp = True
                        failed_targets = []
                        for failed_step, _reason in journal_failed_entries:
                            target = (failed_step.get("target") or failed_step.get("destination")
                                      or failed_step.get("file") or failed_step.get("source_orig") or "không xác định")
                            failed_targets.append(str(target))
                        print(f"[Rollback Warning] Lớp 1 chưa hoàn tất: {len(journal_failed_entries)} bước lỗi; giữ transaction temp để khôi phục.")
                        rollback_message = (
                            f"{err_msg}. Transaction Rollback CHƯA hoàn tất cho: "
                            f"{', '.join(failed_targets)}. Dữ liệu transaction tạm được giữ lại; "
                            "không tự chạy thêm thao tác. Hãy dùng Khôi Phục Gốc Khẩn Cấp hoặc liên hệ hỗ trợ."
                        )
                else:
                    rollback_message = err_msg

                set_progress(0, rollback_message, status="error", game_id=game_id, operation=operation)
                raise RuntimeError(rollback_message) from e

    finally:
        if not preserve_tx_temp:
            for tx_f in tx_temp_files:
                if os.path.exists(tx_f):
                    try:
                        if os.path.isdir(tx_f):
                            shutil.rmtree(tx_f, ignore_errors=True)
                        else:
                            os.remove(tx_f)
                    except Exception:
                        pass

    if operation == "install":
        _remove_transaction_journal(game_id)
    return True


# ==============================================================================
# WORKFLOW: INSTALL MOD
# ==============================================================================

