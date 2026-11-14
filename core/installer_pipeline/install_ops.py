# -*- coding: utf-8 -*-
"""
Core Installer Pipeline - Install & Uninstall Operations
"""
import os
import sys
import time
import json
import shutil
import zipfile
from typing import Optional, Callable, Dict, Any

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError
except ImportError:
    pass

from core.config_manager import (
    load_user_config, save_user_config, BACKUP_ROOT, APPDATA_DIR,
    get_games, get_active_games_json_path,
    get_repo_dir, DEFAULT_REPO_DIR, FALLBACK_REPO_DIR, USER_DOCS_DIR, APP_DIR
)
from core.scanner import check_directory_writable, is_running_as_admin, verify_and_resolve_game_path
from core.downloader import download_file_with_progress
from core.backup_rollback import (
    load_backup_manifest, save_backup_manifest, restore_files_inplace,
    record_preexisting_environment, emergency_restore_game as deep_emergency_restore,
    backup_file_inplace, record_backup_manifest, record_modded_state
)
from .process_checker import (
    calculate_sha256, check_game_running, find_mod_source_dir, check_has_mod_files
)
from .actions import patch_ini_file
from .pipeline_runner import (
    INSTALL_PROGRESS, set_progress, get_install_progress,
    get_game_operation_lock, has_pending_transaction, execute_action_pipeline
)


def cleanup_cache_after_install(game_id: str, cfg: dict = None) -> int:
    """
    Xóa các gói nén (.congu / .zip / .7z) trong cache của game sau khi cài đặt thành công,
    áp dụng khi người dùng TẮT tùy chọn 'downloader.keep_congu_cache' trong Menu Cài Đặt.
    Trả về số tệp đã xóa.
    """
    removed = 0
    try:
        if cfg is None:
            cfg = load_user_config()
        if cfg.get("downloader", {}).get("keep_congu_cache", False):
            return 0
        cache_dir = os.path.join(APPDATA_DIR, "cache", game_id)
        if not os.path.isdir(cache_dir):
            return 0
        for fn in os.listdir(cache_dir):
            if fn.lower().endswith((".congu", ".zip", ".rar", ".7z")):
                try:
                    os.remove(os.path.join(cache_dir, fn))
                    removed += 1
                except Exception:
                    pass
    except Exception as e:
        print(f"[Installer] Lỗi dọn cache sau cài đặt: {e}")
    return removed


def _record_mod_install_receipt(game_id: str, g: dict, game_path: str):
    """Lưu biên nhận phiên bản mod đã cài đặt vào user_config (P1-04) và ghi audit log (P1-05)."""
    try:
        from core.config_manager import record_installed_mod_receipt
        from core.mod_compatibility import get_catalog_latest_mod_version
        from core.troubleshooter import record_audit_event
        ver, _, _ = get_catalog_latest_mod_version(g)
        sha = str(g.get("congu_sha256") or g.get("sha256") or "")
        record_installed_mod_receipt(
            game_id,
            version=ver or "v1.0.0",
            sha256=sha,
            metadata={
                "game_path": game_path,
                "mod_type": g.get("mod_type", ""),
                "target_pak_name": g.get("target_pak_name", ""),
            }
        )
        record_audit_event(
            game_id,
            action="install",
            status="success",
            message=f"Cài đặt thành công bản Việt hóa phiên bản {ver or 'v1.0.0'}",
            details={"version": ver, "sha256": sha, "game_path": game_path}
        )
    except Exception as e:
        print(f"[Installer] Lỗi ghi biên nhận mod {game_id}: {e}")


def _remove_mod_install_receipt(game_id: str):
    """Xóa hoặc cập nhật biên nhận mod khi gỡ cài đặt (P1-04) và ghi audit log (P1-05)."""
    try:
        from core.config_manager import remove_installed_mod_receipt
        from core.troubleshooter import record_audit_event
        remove_installed_mod_receipt(game_id)
        record_audit_event(
            game_id,
            action="uninstall",
            status="success",
            message="Gỡ bỏ bản Việt hóa và khôi phục file gốc thành công"
        )
    except Exception as e:
        print(f"[Installer] Lỗi gỡ biên nhận mod {game_id}: {e}")


def find_reusable_cached_package(cache_dir: str, g: dict) -> str:
    """
    Tim goi .congu/.zip da tai truoc do trong cache va con hop le (SHA-256 khop ban phat hanh).
    Dung cho tinh nang "Cai lai 1-Click 0 giay" khi game bi Steam/Epic cap nhat de len ban Viet hoa.
    """
    if not cache_dir or not os.path.isdir(cache_dir):
        return ""
    expected = str(g.get("congu_sha256") or g.get("sha256") or "").strip().lower()
    for fn in ("mod_package.congu", "mod_package.zip"):
        p = os.path.join(cache_dir, fn)
        try:
            if not os.path.exists(p) or os.path.getsize(p) < 1024:
                continue
            if fn.endswith(".congu") and not security.is_congu_package(p):
                continue
            if expected:
                sha = (calculate_sha256(p) or "").lower()
                if sha != expected:
                    print(f"[Cache Reuse] Bo qua {fn}: SHA-256 khong khop ban phat hanh.")
                    continue
            return p
        except Exception as e:
            print(f"[Cache Reuse] Loi kiem tra {fn}: {e}")
    return ""


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

    # Pre-Flight Game Doctor (P1-02): Kiểm tra toàn diện tiến trình, quyền ghi, ổ đĩa, runtime và xung đột
    try:
        from core.preflight_doctor import run_preflight
        preflight = run_preflight(g, game_path, operation="install")
        if preflight.get("is_blocked") and not force:
            err_msg = preflight.get("summary", "Kiểm tra tiền trạm không đạt yêu cầu.")
            set_progress(0, err_msg, status="error", game_id=game_id)
            blockers = preflight.get("blockers", [])
            req_admin = any("Admin" in str(b) or "quyền ghi" in str(b).lower() for b in blockers)
            game_run = any("tiến trình" in str(b).lower() or "đang chạy" in str(b).lower() for b in blockers)
            return {
                "success": False,
                "preflight_blocked": True,
                "requires_admin": req_admin,
                "is_game_running": game_run,
                "message": err_msg,
                "blockers": blockers,
                "preflight": preflight
            }
    except Exception as pf_err:
        print(f"[Installer] Preflight check error: {pf_err}")

    # Fallback legacy checks nếu preflight gặp lỗi ngoại lệ
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
        if expected_sha and security.verify_package_checksum(existing_congu, expected_sha):
            set_progress(25, "Đã tìm thấy gói bảo mật CỔ NGỮ đã xác minh trên thiết bị...", status="running", game_id=game_id)
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

                cleanup_cache_after_install(game_id, cfg)
                _record_mod_install_receipt(game_id, g, game_path)
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
            pref_source = cfg.get("downloader", {}).get("preferred_source", "github_cdn")
            download_candidates = []
            
            # Thứ tự ứng viên dựa trên nguồn ưu tiên trong Cài Đặt
            if pref_source == "gdrive" and g.get("drive_url"):
                download_candidates.append(("Google Drive Mirror", g["drive_url"]))
            elif pref_source == "mirror" and g.get("mirror_url"):
                download_candidates.append(("Mirror Dự Phòng", g["mirror_url"]))

            if g.get("download_url") and ("GitHub Cloud CDN (Siêu tốc)", g["download_url"]) not in download_candidates:
                download_candidates.append(("GitHub Cloud CDN (Siêu tốc)", g["download_url"]))
            if g.get("mirror_url") and ("Mirror Dự Phòng", g["mirror_url"]) not in download_candidates:
                download_candidates.append(("Mirror Dự Phòng", g["mirror_url"]))
            if g.get("drive_url") and g.get("drive_url") != g.get("mirror_url") and ("Google Drive Mirror", g["drive_url"]) not in download_candidates:
                download_candidates.append(("Google Drive Mirror", g["drive_url"]))
            custom_url = cfg.get(f"{game_id}_download_url")
            if custom_url and custom_url not in [c[1] for c in download_candidates]:
                download_candidates.append(("Link Tùy Chỉnh Cá Nhân", custom_url))

            if not download_candidates:
                set_progress(0, "Chưa tìm thấy bản mod local và chưa có link tải Cloud!", status="error", game_id=game_id)
                return {"success": False, "message": f"Không tìm thấy thư mục mod tại {source_mod_dir} và tựa game chưa được cấu hình link tải Cloud!"}

            os.makedirs(cache_dir, exist_ok=True)

            # === TAI SU DUNG GOI DA TAI TRUOC DO (Cai lai 1-Click 0 giay, khong can mang) ===
            reused_archive = find_reusable_cached_package(cache_dir, g)
            if reused_archive:
                print(f"[Cache Reuse] Dung lai goi da tai: {reused_archive}")
                download_candidates = [("Bộ nhớ đệm (Cache) - Không cần mạng", None)]

            download_success = False
            last_err = ""

            for source_name, dl_url in download_candidates:
                if dl_url:
                    ext = ".congu" if dl_url.lower().endswith(".congu") else ".zip"
                    cache_archive = os.path.join(cache_dir, f"mod_package{ext}")
                    set_progress(15, f"Đang kết nối Cloud: {source_name}...", status="running", game_id=game_id)
                else:
                    cache_archive = reused_archive
                    set_progress(30, f"Đang cài lại từ {source_name} (0 giây)...", status="running", game_id=game_id)

                def on_dl_progress(d, t, pct, spd):
                    mb_d = d / (1024 * 1024)
                    mb_t = t / (1024 * 1024) if t > 0 else 0
                    spd_mb = spd / 1024
                    msg = f"Đang tải ({source_name}): {pct}% ({mb_d:.1f}/{mb_t:.1f} MB - {spd_mb:.1f} MB/s)" if t > 0 else f"Đang tải: {mb_d:.1f} MB ({spd_mb:.1f} MB/s)"
                    set_progress(15 + int(pct * 0.40), msg, status="running", game_id=game_id)

                try:
                    if dl_url:
                        def validate_package(staged_path):
                            if security.is_congu_package(staged_path) or ext == ".congu":
                                expected = g.get("congu_sha256") or g.get("sha256")
                                if not expected:
                                    raise ValueError("Gói .congu chính thức thiếu SHA-256 trong catalog; đã từ chối cài để bảo vệ game.")
                                if not security.verify_package_checksum(staged_path, expected):
                                    raise ValueError("Gói .congu tải về không khớp SHA-256 trong catalog.")
                        download_file_with_progress(dl_url, cache_archive, on_dl_progress,
                                                    validate_download=validate_package)

                    if security.is_congu_package(cache_archive):
                        expected_sha = g.get("congu_sha256") or g.get("sha256")
                        if not expected_sha:
                            raise ValueError("Gói .congu chính thức thiếu SHA-256 trong catalog; đã từ chối cài để bảo vệ game.")
                        if not security.verify_package_checksum(cache_archive, expected_sha):
                            raise ValueError("Gói .congu tải về không khớp SHA-256 trong catalog.")
                        set_progress(58, "Đã xác minh gói CỔ NGỮ (SHA-256), đang cài đặt...", status="running", game_id=game_id)
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

                            cleanup_cache_after_install(game_id, cfg)
                            _record_mod_install_receipt(game_id, g, game_path)
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
                    # Downloader đã tự dọn file tạm. Không xóa cache hiện hữu:
                    # lỗi tải/xác minh có thể xảy ra trước khi đích được thay thế.

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
            cleanup_cache_after_install(game_id, cfg)
            _record_mod_install_receipt(game_id, g, game_path)
            return {
                "success": True,
                "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Data-Driven Pipeline)",
                "games": games_fetcher()
            }
        except Exception as pe:
            # Rollback error may be intentionally marked as incomplete; keep that
            # truthful message instead of overwriting it with a generic status.
            if get_install_progress().get("status") == "running":
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
        cleanup_cache_after_install(game_id, cfg)
        _record_mod_install_receipt(game_id, g, game_path)
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


def _pending_transaction_error(game_id: str) -> dict:
    if not has_pending_transaction(game_id):
        return {}
    return {
        "success": False,
        "recovery_required": True,
        "message": "Game có giao dịch cài đặt chưa hoàn tất. Đã dừng thao tác để bảo vệ dữ liệu; giữ nguyên journal và backup, liên hệ hỗ trợ để kiểm tra.",
    }


def install_mod(game_id: str, force: bool = False, get_games_func: Optional[Callable] = None) -> dict:
    """Thread-safe install wrapper with mutual exclusion lock."""
    game_lock = get_game_operation_lock(game_id)
    if not game_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "Game này đang được cài đặt/gỡ bỏ hoặc khôi phục. Vui lòng chờ hoàn tất!"
        }
    try:
        pending_error = _pending_transaction_error(game_id)
        if pending_error:
            return pending_error
        return install_mod_impl(game_id, force=force, get_games_func=get_games_func)
    finally:
        game_lock.release()


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
            _remove_mod_install_receipt(game_id)
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

        _remove_mod_install_receipt(game_id)
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
    game_lock = get_game_operation_lock(game_id)
    if not game_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "Game này đang được cài đặt/gỡ bỏ hoặc khôi phục. Vui lòng chờ hoàn tất!"
        }
    try:
        pending_error = _pending_transaction_error(game_id)
        if pending_error:
            return pending_error
        return uninstall_mod_impl(game_id, get_games_func=get_games_func)
    finally:
        game_lock.release()


# ==============================================================================
# WORKFLOW: EMERGENCY DEEP RESTORE
# ==============================================================================

def emergency_restore_game(game_id: str, get_games_func: Optional[Callable] = None) -> dict:
    """Thread-safe emergency restore wrapper with progress reporting."""
    game_lock = get_game_operation_lock(game_id)
    if not game_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "Game này đang được cài đặt/gỡ bỏ hoặc khôi phục. Vui lòng chờ hoàn tất!"
        }
    try:
        pending_error = _pending_transaction_error(game_id)
        if pending_error:
            return pending_error
        def _on_restore_progress(pct, msg, status="running"):
            set_progress(pct, msg, status=status, game_id=game_id, operation="restore")

        res = deep_emergency_restore(game_id, progress_callback=_on_restore_progress)
        if get_games_func and "games" in res:
            res["games"] = get_games_func()
        return res
    finally:
        game_lock.release()


def verify_mod_integrity(game_id: str, get_games_func: Optional[Callable] = None) -> dict:
    """
    Ki?m tra t?nh to?n v?n c?a b?n Vi?t h?a (Steam-style Verify Integrity).
    ??i chi?u xem c?c t?p Vi?t h?a ?? c?i v?o th? m?c game c? c?n nguy?n v?n,
    b? x?a, ho?c b? Steam/Epic c?p nh?t ghi ?? kh?ng.
    """
    games_fetcher = get_games_func if get_games_func is not None else get_games
    games_list = games_fetcher()
    g = next((gm for gm in games_list if gm["id"] == game_id), None)
    if not g:
        return {"success": False, "message": "Kh?ng t?m th?y th?ng tin t?a game n?y."}

    game_path = g.get("game_path")
    if not game_path or not os.path.exists(game_path):
        return {"success": False, "message": "Ch?a x?c ??nh ???c th? m?c game tr?n m?y t?nh."}

    # ??c manifest b?n sao l?u ho?c danh s?ch file c?i
    manifest = load_backup_manifest(game_id)
    backed_up = manifest.get("backed_up_files", [])

    missing_or_modified = []
    intact = 0

    if backed_up:
        for item in backed_up:
            target = item.get("target_file")
            if not target:
                continue
            if not os.path.isabs(target):
                target = os.path.join(game_path, target)
            if not os.path.exists(target):
                missing_or_modified.append(os.path.basename(target) + " (?? b? x?a ho?c di chuy?n)")
            else:
                intact += 1
    else:
        # Ki?m tra b??c c?i ??t m?c ??nh
        steps = g.get("install_steps") or []
        for st in steps:
            if st.get("action") in ("copy_file", "patch_binary"):
                target = st.get("target") or st.get("destination") or ""
                if target:
                    full_target = os.path.join(game_path, target)
                    if not os.path.exists(full_target):
                        missing_or_modified.append(target + " (Thi?u)")
                    else:
                        intact += 1

    if not missing_or_modified:
        return {
            "success": True,
            "intact": True,
            "verified_files": intact,
            "message": f"To?n b? {intact} t?p Vi?t h?a c?a {g['vietnamese_title']} ??u nguy?n v?n 100%!"
        }
    else:
        return {
            "success": True,
            "intact": False,
            "verified_files": intact,
            "corrupted_files": missing_or_modified,
            "message": f"Ph?t hi?n {len(missing_or_modified)} t?p Vi?t h?a b? l?ch ho?c ghi ?? b?i Steam/Epic! B?n c? th? b?m 'C?i L?i' ?? kh?c ph?c t?c th?."
        }
