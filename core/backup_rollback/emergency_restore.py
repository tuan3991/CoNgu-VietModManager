# -*- coding: utf-8 -*-
"""
Core Backup Rollback - Emergency Deep Restore
"""
import os
import shutil
from typing import Optional, Callable

from core.config_manager import load_user_config, save_user_config, get_games
from core.scanner import check_directory_writable, is_running_as_admin
from .manifest_manager import load_backup_manifest, save_backup_manifest


def emergency_restore_game(game_id: str, progress_callback: Optional[Callable[[int, str, str], None]] = None) -> dict:
    """
    Khôi phục gốc khẩn cấp / Sửa lỗi game (Emergency Deep Restore):
    Quét đệ quy toàn bộ thư mục game để tìm mọi file và thư mục .congu_bak và khôi phục về file/thư mục gốc ban đầu.
    Tự động kiểm tra game đang chạy (chống WinError 32) và kiểm tra quyền ghi thư mục.
    """
    def _report(pct, msg, status="running"):
        if progress_callback:
            progress_callback(pct, msg, status)

    _report(5, "Đang kiểm tra trạng thái trước khi khôi phục gốc...")
    try:
        games = {g["id"]: g for g in get_games()}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy thông tin game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if not game_path or not os.path.exists(game_path):
            return {"success": False, "message": "Thư mục cài đặt game không tồn tại hoặc chưa được chọn!"}

        # 1. Kiểm tra xem tiến trình game có đang chạy hay không (Chống WinError 32 khóa file)
        try:
            from core.installer_pipeline.process_checker import check_game_running
            is_running, proc_name = check_game_running(g, game_path)
            if is_running:
                msg = f"Tiến trình game '{proc_name or g.get('title')}' đang chạy! Vui lòng đóng game hoàn toàn trước khi khôi phục gốc."
                _report(0, msg, status="error")
                return {
                    "success": False,
                    "message": msg,
                    "is_running": True,
                    "process_name": proc_name
                }
        except Exception as e:
            print(f"[Emergency Restore] Lỗi kiểm tra tiến trình: {e}")

        # 2. Kiểm tra quyền ghi thư mục game (Windows ACL & Administrator)
        if not is_running_as_admin() and not check_directory_writable(game_path):
            msg = f"Thư mục game '{game_path}' bị khóa quyền ghi (cần quyền Administrator). Vui lòng chạy ứng dụng dưới quyền Quản trị viên (Run as administrator)."
            _report(0, msg, status="error")
            return {
                "success": False,
                "message": msg,
                "requires_admin": True
            }

        _report(25, "Đang quét sâu tìm tệp tin và thư mục sao lưu (.congu_bak)...")

        restored_count = 0
        error_count = 0

        # Duyệt topdown=True để xử lý các thư mục sao lưu và loại bỏ khỏi dirs để tránh đệ quy vào đường dẫn đã đổi tên
        for root, dirs, files in os.walk(game_path, topdown=True):
            # A. Dọn dẹp tệp tạm giao dịch .congu_tx_tmp nếu có
            for f in files:
                if f.endswith(".congu_tx_tmp"):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass

            # B. Khôi phục các THƯ MỤC sao lưu (.congu_bak) - ví dụ core/locale.congu_bak
            bak_dirs = [d for d in dirs if d.endswith(".congu_bak")]
            for d in bak_dirs:
                bak_abs = os.path.join(root, d)
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
                    print(f"[Emergency Restore Dir Error] {bak_abs}: {e}")
                    error_count += 1
                dirs.remove(d)

            # C. Khôi phục các TỆP TIN sao lưu (.congu_bak)
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
                        print(f"[Emergency Restore File Error] {bak_abs}: {e}")
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

        _report(100, f"Đã hoàn thành khôi phục khẩn cấp {restored_count} mục gốc!", status="success")
        msg = f"Đã khôi phục thành công {restored_count} tệp tin và thư mục gốc (.congu_bak) cho game {g.get('vietnamese_title', game_id)}!"
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
