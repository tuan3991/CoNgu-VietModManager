# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Quick-Save Checkpoint
================================================
Nhánh checkpoint "nóng" của Hồ sơ `.congu_save`, phục vụ phím tắt toàn cục Ctrl+F5 / Ctrl+F9
trong lúc đang chơi game (Roguelike permadeath, Soulslike 1 slot save...).

Thiết kế:
- Checkpoint được lưu thành các gói ZIP RIÊNG trong
  ``%APPDATA%/VietModHub/quick_checkpoints/<game_id>/<timestamp>.zip``
  (kèm file metadata ``.json`` cùng tên).
- Vì sao không ghi trực tiếp vào file ``PlayerProfile.congu_save``?
  Vault là 1 file ZIP chứa save của TẤT CẢ game (có thể vài trăm MB). Mỗi lần checkpoint mà
  phải đọc-ghi lại toàn bộ vault sẽ mất vài giây và có nguy cơ hỏng két nếu mất điện.
  Sidecar này là "nhánh quick_checkpoint" của vault: chỉ nén đúng thư mục save của game đang chơi
  nên đạt tốc độ ~0.1s và tuyệt đối không đụng tới dữ liệu vault chính.
"""

import os
import io
import json
import time
import shutil
import zipfile
import fnmatch
import tempfile
from datetime import datetime
from typing import Dict, List, Tuple

MAX_CHECKPOINTS_PER_GAME = 10


def get_checkpoint_root(appdata_dir: str) -> str:
    root = os.path.join(appdata_dir, "quick_checkpoints")
    os.makedirs(root, exist_ok=True)
    return root


def _is_excluded(rel_name: str, patterns: List[str]) -> bool:
    base = os.path.basename(rel_name).lower()
    for pat in patterns or []:
        p = str(pat).lower()
        if fnmatch.fnmatch(base, p) or fnmatch.fnmatch(rel_name.lower(), p):
            return True
    return False


def _iter_location_files(real_path: str, slot: str, exclude_patterns: List[str]):
    """Sinh ra (đường dẫn thực, arcname) cho 1 vị trí save (file hoặc thư mục)."""
    if os.path.isfile(real_path):
        yield real_path, f"{slot}/{os.path.basename(real_path)}"
        return
    if os.path.isdir(real_path):
        for root, dirs, files in os.walk(real_path):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, real_path).replace("\\", "/")
                if _is_excluded(rel, exclude_patterns):
                    continue
                yield full, f"{slot}/{rel}"


def _collect_save_locations(vault, game_config: dict, game_root: str) -> List[Tuple[str, str]]:
    """Trả về [{'slot', 'path', 'is_dir'}] đã phân giải macro và còn tồn tại trên đĩa."""
    save_locs, _ach_locs, _excl = vault._extract_game_locations(game_config, game_root)
    result = []
    for idx, loc in enumerate(save_locs or []):
        slot = str(loc.get("slot") or f"slot_{idx + 1}")
        raw = loc.get("path") or ""
        real = vault.resolve_macro_path(raw, game_root) if raw else ""
        if real and os.path.exists(real):
            result.append({"slot": slot, "path": real, "is_dir": os.path.isdir(real)})
    return result


def save_checkpoint(vault, game_config: dict, game_root: str, appdata_dir: str,
                    label: str = "") -> Dict:
    """
    Nén nóng toàn bộ vị trí save hiện tại của game thành 1 checkpoint.
    Trả về {success, checkpoint_id, files, size_bytes, duration_ms, path}.
    """
    started = time.time()
    game_id = game_config.get("id") or "unknown"
    locations = _collect_save_locations(vault, game_config, game_root)
    if not locations:
        return {
            "success": False,
            "error": "Không tìm thấy thư mục save nào của game này trên máy.",
            "game_id": game_id,
        }

    _sl, _al, exclude_patterns = vault._extract_game_locations(game_config)

    root = get_checkpoint_root(appdata_dir)
    game_dir = os.path.join(root, game_id)
    os.makedirs(game_dir, exist_ok=True)

    ts = time.time()
    checkpoint_id = datetime.fromtimestamp(ts).strftime("%Y%m%d_%H%M%S") + f"_{int(ts * 1000) % 1000:03d}"
    zip_path = os.path.join(game_dir, f"{checkpoint_id}.zip")
    tmp_path = zip_path + ".tmp"

    file_count = 0
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for loc in locations:
                for full, arc in _iter_location_files(loc["path"], loc["slot"], exclude_patterns):
                    try:
                        try:
                            from core.cloud_save.auto_save_detector import wait_file_stable
                            wait_file_stable(full, timeout_sec=0.4)
                        except Exception:
                            pass
                        zf.write(full, arc)
                        file_count += 1
                    except (OSError, PermissionError):
                        # File đang bị game khóa -> bỏ qua, không làm hỏng checkpoint
                        continue
        os.replace(tmp_path, zip_path)
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return {"success": False, "error": f"Không tạo được checkpoint: {e}", "game_id": game_id}

    size_bytes = os.path.getsize(zip_path)
    duration_ms = int((time.time() - started) * 1000)
        # Upgrade 4: Chụp ảnh màn hình trực quan (Visual Save State)
    thumb_name = f"{checkpoint_id}.jpg"
    thumb_path = os.path.join(game_dir, thumb_name)
    has_thumb = False
    try:
        from PIL import ImageGrab
        sc = ImageGrab.grab()
        if sc:
            sc.thumbnail((320, 180))
            sc.save(thumb_path, format="JPEG", quality=75)
            has_thumb = True
    except Exception:
        has_thumb = False

    meta = {
        "thumbnail": thumb_name if has_thumb else "",
        "checkpoint_id": checkpoint_id,
        "game_id": game_id,
        "game_title": game_config.get("vietnamese_title") or game_config.get("title") or game_id,
        "created_at": ts,
        "created_at_text": datetime.fromtimestamp(ts).strftime("%H:%M:%S %d/%m/%Y"),
        "files": file_count,
        "size_bytes": size_bytes,
        "duration_ms": duration_ms,
        "label": label or "Quick Checkpoint",
        "slots": [loc["slot"] for loc in locations],
        # Lưu lại đường dẫn gốc + kiểu (file/thư mục) để hoàn nguyên chính xác kể cả khi save bị xóa
        "locations": [
            {"slot": loc["slot"], "path": loc["path"], "is_dir": loc["is_dir"]}
            for loc in locations
        ],
    }
    try:
        with open(os.path.join(game_dir, f"{checkpoint_id}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    _prune_old_checkpoints(game_dir)
    meta["success"] = True
    meta["path"] = zip_path
    return meta


def _prune_old_checkpoints(game_dir: str, keep: int = MAX_CHECKPOINTS_PER_GAME) -> int:
    """Giữ tối đa `keep` checkpoint mới nhất mỗi game (tránh phình ổ đĩa)."""
    removed = 0
    try:
        zips = sorted(
            [f for f in os.listdir(game_dir) if f.lower().endswith(".zip")],
            key=lambda f: os.path.getmtime(os.path.join(game_dir, f)),
            reverse=True,
        )
        for old in zips[keep:]:
            base = os.path.join(game_dir, old[:-4])
            for p in (os.path.join(game_dir, old), base + ".json"):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        removed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def list_checkpoints(game_id: str, appdata_dir: str) -> List[Dict]:
    """Liệt kê checkpoint của 1 game, mới nhất trước."""
    game_dir = os.path.join(get_checkpoint_root(appdata_dir), game_id)
    if not os.path.isdir(game_dir):
        return []
    items = []
    for fn in os.listdir(game_dir):
        if not fn.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(game_dir, fn), "r", encoding="utf-8") as f:
                meta = json.load(f)
            zip_path = os.path.join(game_dir, fn[:-5] + ".zip")
            if os.path.exists(zip_path):
                meta["path"] = zip_path
                items.append(meta)
        except Exception:
            continue
    items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return items


def restore_checkpoint(vault, game_config: dict, game_root: str, appdata_dir: str,
                       checkpoint_id: str = "") -> Dict:
    """
    Hoàn nguyên checkpoint mới nhất (hoặc theo checkpoint_id) trở lại đúng thư mục save của game.
    Trả về {success, restored_files, checkpoint_id, duration_ms}.
    """
    started = time.time()
    game_id = game_config.get("id") or "unknown"

    items = list_checkpoints(game_id, appdata_dir)
    if not items:
        return {"success": False, "error": "Chưa có checkpoint nào cho game này.", "game_id": game_id}

    meta = items[0]
    if checkpoint_id:
        match = next((i for i in items if i.get("checkpoint_id") == checkpoint_id), None)
        if not match:
            return {"success": False, "error": f"Không tìm thấy checkpoint '{checkpoint_id}'.", "game_id": game_id}
        meta = match

    zip_path = meta.get("path")
    if not zip_path or not os.path.exists(zip_path):
        return {"success": False, "error": "Tệp checkpoint không còn tồn tại.", "game_id": game_id}

    # Ưu tiên đường dẫn gốc đã lưu trong metadata (hoàn nguyên được cả khi save đã bị xóa)
    slot_to_real = {}
    slot_is_dir = {}
    for loc in (meta.get("locations") or []):
        slot = str(loc.get("slot") or "")
        if not slot:
            continue
        slot_to_real[slot] = loc.get("path") or ""
        slot_is_dir[slot] = bool(loc.get("is_dir"))

    # Fallback: phân giải lại từ macro nếu metadata cũ không có 'locations'
    if not slot_to_real:
        save_locs, _al, _excl = vault._extract_game_locations(game_config)
        for idx, loc in enumerate(save_locs or []):
            slot = str(loc.get("slot") or f"slot_{idx + 1}")
            raw = loc.get("path") or ""
            real = vault.resolve_macro_path(raw, game_root) if raw else ""
            if real:
                slot_to_real[slot] = real
                slot_is_dir[slot] = os.path.isdir(real)

    restored = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.split("/", 1)
                if len(parts) != 2:
                    continue
                slot, rel = parts[0], parts[1]
                target_root = slot_to_real.get(slot)
                if not target_root:
                    continue
                if slot_is_dir.get(slot, True):
                    target_path = os.path.join(target_root, rel.replace("/", os.sep))
                else:
                    # Vị trí save là 1 file cụ thể -> ghi đè đúng file đó
                    target_path = target_root
                parent = os.path.dirname(target_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 256)
                restored += 1
    except Exception as e:
        return {"success": False, "error": f"Hoàn nguyên thất bại: {e}", "game_id": game_id}

    return {
        "success": True,
        "game_id": game_id,
        "checkpoint_id": meta.get("checkpoint_id"),
        "restored_files": restored,
        "created_at_text": meta.get("created_at_text"),
        "duration_ms": int((time.time() - started) * 1000),
    }
