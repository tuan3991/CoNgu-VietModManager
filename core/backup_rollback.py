# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - In-Place Backup & Rollback Engine
------------------------------------------------------------
Động cơ sao lưu tại chỗ và hoàn nguyên game an toàn tuyệt đối:
1. In-Place Atomic Backup (.congu_bak):
   - Đổi tên trực tiếp file gốc thành {file}.congu_bak ngay trong thư mục game (0s, 0 bytes copy phụ).
   - Smart Update Detection: Tự động phát hiện khi Steam/Epic cập nhật file mới để xóa backup lỗi thời.
2. Bảo vệ tiền tồn tại (Pre-existing Environment Guard):
   - Lưu trạng thái có sẵn của winhttp.dll, BepInEx, Doorstop trước khi cài mod (chống xóa nhầm khi gỡ).
3. In-Place Restore & Rollback:
   - Xóa file mod và đổi tên .congu_bak trở về nguyên bản.
   - Chống crash nếu người dùng đã bấm Verify Files trên Steam trước khi gỡ mod.
4. Emergency Deep Restore:
   - Quét đệ quy toàn bộ thư mục game để cứu hộ và khôi phục 100% file .congu_bak.
"""

import os
import sys
import json
import shutil
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

from core.config_manager import BACKUP_ROOT, load_user_config, save_user_config, get_active_games_json_path, get_games
from security import validate_safe_path, SecurityError, PathTraversalError


def compute_file_sha256(file_path: str) -> Optional[str]:
    """Tính mã băm SHA-256 an toàn theo từng khối 1MB."""
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


def norm_rel_path(rel_path: str) -> str:
    """Chuẩn hóa mọi đường dẫn tương đối về dấu / và loại bỏ khoảng trắng / gạch chéo thừa."""
    p = str(rel_path or "").replace("\\", "/").strip("/ ")
    while "//" in p:
        p = p.replace("//", "/")
    return p


_norm_rel = norm_rel_path


def load_backup_manifest(game_id: str, backup_root: str = None) -> dict:
    """Tải manifest sao lưu an toàn của game từ AppData."""
    if not game_id:
        return {}
    b_root = backup_root or BACKUP_ROOT
    manifest_path = os.path.join(b_root, game_id, "backup_manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Manifest Load Warning] Lỗi đọc backup_manifest.json cho {game_id}: {e}")
    return {"game_id": game_id, "backup_type": "inplace", "files": []}


def save_backup_manifest(game_id: str, manifest: dict, backup_root: str = None) -> bool:
    """Lưu manifest sao lưu an toàn của game vào AppData."""
    if not game_id:
        return False
    b_root = backup_root or BACKUP_ROOT
    game_backup_dir = os.path.join(b_root, game_id)
    os.makedirs(game_backup_dir, exist_ok=True)
    manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Manifest Save Warning] Lỗi ghi backup_manifest.json cho {game_id}: {e}")
        return False


def record_preexisting_environment(game_id: str, game_path: str, backup_root: str = None) -> Tuple[bool, bool]:
    """
    Ghi nhận môi trường tiền tồn tại của game (BepInEx, winhttp.dll, Doorstop).
    Đặc biệt: Nếu manifest đã từng lưu giá trị bool, TUYỆT ĐỐI giữ nguyên để không bị sai lệch khi cài đè lần 2.
    """
    if not game_id or not game_path or not os.path.exists(game_path):
        return False, False
    manifest = load_backup_manifest(game_id, backup_root=backup_root)

    # 1. winhttp.dll check
    winhttp_preexisting = manifest.get("winhttp_preexisting")
    if winhttp_preexisting is None:
        w_file = os.path.join(game_path, "winhttp.dll")
        w_bak = os.path.join(game_path, "winhttp.dll.congu_bak")
        winhttp_preexisting = bool(os.path.exists(w_file) or os.path.exists(w_bak))
        manifest["winhttp_preexisting"] = winhttp_preexisting

    # 2. BepInEx folder check
    bepinex_preexisting = manifest.get("bepinex_preexisting")
    if bepinex_preexisting is None:
        b_dir = os.path.join(game_path, "BepInEx")
        b_bak = os.path.join(game_path, "BepInEx.congu_bak")
        bepinex_preexisting = bool(os.path.isdir(b_dir) or os.path.isdir(b_bak))
        manifest["bepinex_preexisting"] = bepinex_preexisting

    # 3. Doorstop files check
    doorstop_preexisting = manifest.get("doorstop_preexisting")
    if doorstop_preexisting is None:
        d_cfg = os.path.join(game_path, "doorstop_config.ini")
        d_ver = os.path.join(game_path, ".doorstop_version")
        doorstop_preexisting = bool(os.path.exists(d_cfg) or os.path.exists(d_ver))
        manifest["doorstop_preexisting"] = doorstop_preexisting

    save_backup_manifest(game_id, manifest, backup_root=backup_root)
    return bool(winhttp_preexisting), bool(bepinex_preexisting)


def backup_file_inplace(game_id: str, original_abs_path: str, relative_in_game: str, return_details: bool = False, backup_root: str = None):
    """
    In-Place Atomic Backup với Anti-Crash Steam/Epic Update Detection:
    Đổi tên trực tiếp file gốc thành {file}.congu_bak ngay trong thư mục game.
    Không tốn băng thông ghi đĩa C, thao tác tức thì 0 giây.
    """
    relative_in_game = norm_rel_path(relative_in_game)
    if not os.path.exists(original_abs_path) and not os.path.exists(f"{original_abs_path}.congu_bak"):
        return (None, False) if return_details else None

    bak_file = f"{original_abs_path}.congu_bak"
    is_ini = original_abs_path.lower().endswith(('.ini', '.cfg', '.conf'))
    created_new_bak = False

    manifest = load_backup_manifest(game_id, backup_root=backup_root)
    tracked_item = next((it for it in manifest.get("files", []) if norm_rel_path(it.get("relative_in_game")) == relative_in_game), None)

    # Kiểm tra xem file .congu_bak có bị cũ do Steam/Epic vừa cập nhật game không
    if os.path.exists(bak_file) and os.path.exists(original_abs_path):
        modded_hash = tracked_item.get("modded_sha256") if tracked_item else None
        if modded_hash:
            curr_hash = compute_file_sha256(original_abs_path)
            if curr_hash and curr_hash.lower() != modded_hash.lower():
                print(f"[Smart Update Detection] Tệp '{relative_in_game}' đã được Steam/Epic cập nhật mới. Đang làm mới .congu_bak.")
                try:
                    os.remove(bak_file)
                except Exception:
                    pass

    orig_hash = None
    orig_size = 0
    orig_mtime = 0

    if not os.path.exists(bak_file):
        if os.path.exists(original_abs_path):
            orig_hash = compute_file_sha256(original_abs_path)
            orig_size = os.path.getsize(original_abs_path)
            orig_mtime = os.path.getmtime(original_abs_path)
            if is_ini:
                try:
                    shutil.copy2(original_abs_path, bak_file)
                    created_new_bak = True
                except Exception as e:
                    print(f"Error creating INI backup copy: {e}")
            else:
                try:
                    os.replace(original_abs_path, bak_file)
                    created_new_bak = True
                except Exception:
                    try:
                        os.rename(original_abs_path, bak_file)
                        created_new_bak = True
                    except Exception:
                        try:
                            shutil.copy2(original_abs_path, bak_file)
                            if os.path.isdir(original_abs_path):
                                shutil.rmtree(original_abs_path, ignore_errors=True)
                            else:
                                os.remove(original_abs_path)
                            created_new_bak = True
                        except Exception as e2:
                            print(f"Error creating in-place backup: {e2}")
    else:
        orig_hash = tracked_item.get("original_sha256") if tracked_item else compute_file_sha256(bak_file)
        orig_size = os.path.getsize(bak_file) if os.path.exists(bak_file) else 0
        orig_mtime = os.path.getmtime(bak_file) if os.path.exists(bak_file) else 0
        if not is_ini and os.path.exists(original_abs_path):
            try:
                if os.path.isdir(original_abs_path):
                    shutil.rmtree(original_abs_path, ignore_errors=True)
                else:
                    os.remove(original_abs_path)
            except Exception:
                pass

    file_record = {
        "relative_in_game": relative_in_game,
        "target_file": original_abs_path,
        "backup_file": bak_file,
        "size_bytes": os.path.getsize(bak_file) if os.path.exists(bak_file) else 0,
        "original_sha256": orig_hash,
        "original_size": orig_size,
        "original_mtime": orig_mtime
    }
    existing_idx = next((i for i, f in enumerate(manifest.get("files", [])) if norm_rel_path(f.get("relative_in_game")) == relative_in_game), -1)
    if existing_idx >= 0:
        manifest["files"][existing_idx].update(file_record)
    else:
        manifest.setdefault("files", []).append(file_record)

    save_backup_manifest(game_id, manifest, backup_root=backup_root)

    if return_details:
        return bak_file, created_new_bak
    return bak_file


def record_backup_manifest(game_id: str, backed_up_files: list, backup_root: str = None) -> bool:
    """Ghi nhận danh sách tệp đã sao lưu an toàn vào manifest AppData."""
    if not game_id or not backed_up_files:
        return False
    manifest = load_backup_manifest(game_id, backup_root=backup_root)
    existing_files = manifest.setdefault("files", [])

    for item in backed_up_files:
        rel = norm_rel_path(item.get("relative_in_game"))
        idx = next((i for i, f in enumerate(existing_files) if norm_rel_path(f.get("relative_in_game")) == rel), -1)
        if idx >= 0:
            existing_files[idx].update(item)
        else:
            existing_files.append(item)

    return save_backup_manifest(game_id, manifest, backup_root=backup_root)


def record_modded_state(game_id: str, target_file: str, relative_in_game: str, backup_root: str = None) -> bool:
    """Lưu mã băm SHA-256 của file sau khi cài mod xong để phục vụ tự động phát hiện cập nhật Steam."""
    if not game_id or not target_file or not os.path.isfile(target_file):
        return False
    rel = norm_rel_path(relative_in_game)
    modded_hash = compute_file_sha256(target_file)
    if not modded_hash:
        return False

    manifest = load_backup_manifest(game_id, backup_root=backup_root)
    for it in manifest.get("files", []):
        if norm_rel_path(it.get("relative_in_game")) == rel:
            it["modded_sha256"] = modded_hash
            it["modded_size"] = os.path.getsize(target_file)
            it["modded_mtime"] = os.path.getmtime(target_file)
            return save_backup_manifest(game_id, manifest, backup_root=backup_root)
    return False


def restore_files_inplace(game_id: str, game_path: str, backup_root: str = None) -> bool:
    """
    In-Place Restore:
    Xóa file mod và đổi tên {file}.congu_bak trở về nguyên bản.
    Bảo toàn file game sạch nếu Steam/Epic đã verify/update trước đó.
    """
    restored_any = False
    b_root = backup_root or BACKUP_ROOT
    game_backup_dir = os.path.join(b_root, game_id)
    manifest = load_backup_manifest(game_id, backup_root=b_root)
    manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")

    # 1. Xử lý các file trong manifest
    files = manifest.get("files", [])
    for item in files:
        rel = norm_rel_path(item.get("relative_in_game"))
        if not rel or not game_path:
            continue
        try:
            target_file = validate_safe_path(game_path, rel, allow_base_itself=False)
            bak_file = f"{target_file}.congu_bak"
        except Exception as se:
            print(f"[Restore Safe Guard] Bỏ qua đường dẫn không an toàn: {rel} ({se})")
            continue

        if bak_file and os.path.exists(bak_file):
            try:
                is_still_modded = True
                modded_hash = item.get("modded_sha256")
                if modded_hash and target_file and os.path.exists(target_file):
                    curr_hash = compute_file_sha256(target_file)
                    if curr_hash and curr_hash.lower() != modded_hash.lower():
                        print(f"[Anti-Crash] Tệp '{rel}' không khớp bản mod (Steam/Epic đã cập nhật). Giữ nguyên tệp game sạch.")
                        is_still_modded = False
                        try:
                            os.remove(bak_file)
                        except Exception:
                            pass
                        continue

                if is_still_modded:
                    if target_file and os.path.exists(target_file):
                        try:
                            os.remove(target_file)
                        except Exception:
                            pass
                    os.rename(bak_file, target_file)
                    restored_any = True
            except Exception as e:
                print(f"Error restoring in-place backup {bak_file}: {e}")

        # Legacy AppData file restore
        b_legacy = item.get("backup_file", "")
        if b_legacy and not os.path.isabs(b_legacy):
            legacy_appdata_file = os.path.join(game_backup_dir, b_legacy)
            if os.path.exists(legacy_appdata_file) and target_file and not os.path.exists(target_file):
                try:
                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    shutil.copy2(legacy_appdata_file, target_file)
                    restored_any = True
                except Exception as e:
                    print(f"Error restoring legacy AppData backup: {e}")

    # Xử lý thư mục locale.congu_bak (Fallout Tactics...)
    if game_path and os.path.exists(game_path):
        locale_bak = os.path.join(game_path, "core", "locale.congu_bak")
        orig_locale = os.path.join(game_path, "core", "locale")
        if os.path.exists(locale_bak):
            try:
                if os.path.exists(orig_locale):
                    shutil.rmtree(orig_locale, ignore_errors=True)
                os.rename(locale_bak, orig_locale)
                restored_any = True
            except Exception as e:
                print(f"Error restoring in-place locale folder: {e}")

    # Bảo tồn cờ tiền tồn tại (preexisting flags)
    cleaned_manifest = {
        "game_id": game_id,
        "backup_type": "inplace",
        "files": []
    }
    has_preexisting_flags = False
    for flag in ("winhttp_preexisting", "bepinex_preexisting", "doorstop_preexisting"):
        if flag in manifest:
            cleaned_manifest[flag] = manifest[flag]
            has_preexisting_flags = True

    if has_preexisting_flags:
        save_backup_manifest(game_id, cleaned_manifest, backup_root=b_root)
    else:
        if os.path.exists(manifest_path):
            try:
                os.remove(manifest_path)
            except Exception:
                pass

    # Dọn dẹp thư mục AppData
    if os.path.exists(game_backup_dir):
        try:
            for entry in os.listdir(game_backup_dir):
                if entry == "backup_manifest.json" and has_preexisting_flags:
                    continue
                entry_path = os.path.join(game_backup_dir, entry)
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path, ignore_errors=True)
                else:
                    try:
                        os.remove(entry_path)
                    except Exception:
                        pass
            if not os.listdir(game_backup_dir):
                os.rmdir(game_backup_dir)
        except Exception as e:
            print(f"[AppData Cleanup Warning] {e}")

    return restored_any


def emergency_restore_game(game_id: str, progress_callback: Optional[Callable[[int, str, str], None]] = None) -> dict:
    """
    Khôi phục gốc khẩn cấp / Sửa lỗi game (Emergency Deep Restore):
    Quét đệ quy toàn bộ thư mục game để tìm mọi file .congu_bak và khôi phục về file gốc ban đầu.
    """
    def _report(pct, msg, status="running"):
        if progress_callback:
            progress_callback(pct, msg, status)

    _report(10, "Đang bắt đầu quét khôi phục gốc khẩn cấp...")
    try:
        games = {g["id"]: g for g in get_games()}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy thông tin game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if not game_path or not os.path.exists(game_path):
            return {"success": False, "message": "Thư mục cài đặt game không tồn tại hoặc chưa được chọn!"}

        _report(30, "Đang quét sâu tìm tệp tin sao lưu (.congu_bak)...")

        restored_count = 0
        error_count = 0

        for root, dirs, files in os.walk(game_path):
            for f in files:
                if f.endswith(".congu_bak"):
                    bak_abs = os.path.join(root, f)
                    orig_abs = bak_abs[:-10]  # Bỏ đuôi '.congu_bak'
                    try:
                        if os.path.exists(orig_abs):
                            if os.path.isdir(orig_abs):
                                shutil.rmtree(orig_abs, ignore_errors=True)
                            else:
                                os.remove(orig_abs)
                        os.rename(bak_abs, orig_abs)
                        restored_count += 1
                    except Exception as e:
                        print(f"[Emergency Restore Error] {bak_abs}: {e}")
                        error_count += 1

        _report(80, "Đang dọn dẹp bộ nhớ đệm và thiết lập lại trạng thái...")

        manifest = load_backup_manifest(game_id)
        cleaned_manifest = {"game_id": game_id, "backup_type": "inplace", "files": []}
        has_preexisting_flags = False
        for flag in ("winhttp_preexisting", "bepinex_preexisting", "doorstop_preexisting"):
            if flag in manifest:
                cleaned_manifest[flag] = manifest[flag]
                has_preexisting_flags = True

        if has_preexisting_flags:
            save_backup_manifest(game_id, cleaned_manifest)

        cfg[f"{game_id}_status"] = "not_installed"
        save_user_config(cfg)

        _report(100, f"Đã hoàn thành khôi phục khẩn cấp {restored_count} tệp tin gốc!", status="success")
        msg = f"Đã khôi phục thành công {restored_count} tệp tin gốc (.congu_bak) cho game {g.get('vietnamese_title', game_id)}!"
        if error_count > 0:
            msg += f" (Gặp sự cố ở {error_count} tệp)"

        return {
            "success": True,
            "restored_count": restored_count,
            "message": msg,
            "games": get_games()
        }
    except Exception as e:
        _report(0, f"Lỗi khôi phục khẩn cấp: {str(e)}", status="error")
        return {"success": False, "message": f"Lỗi khôi phục khẩn cấp: {str(e)}"}
