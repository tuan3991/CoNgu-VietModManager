# -*- coding: utf-8 -*-
"""
Core Backup Rollback - Emergency Deep Restore
"""
import os
import shutil
from typing import Optional, Callable

from core.config_manager import load_user_config, save_user_config, get_games
from .manifest_manager import load_backup_manifest, save_backup_manifest


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
