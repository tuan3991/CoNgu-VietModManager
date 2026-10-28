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

