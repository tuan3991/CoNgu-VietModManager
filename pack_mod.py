#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoNgu Mod Packaging & Auto-Hashing Utility (pack_mod.py)
-------------------------------------------------------------------------
Tiện ích tự động hóa đóng gói mod Việt Hóa thành container mã hóa .congu V2,
tự động tính toán mã băm SHA-256 chính xác và tự động cập nhật vào games.json.

Khắc phục triệt để lỗi copy-paste mã băm rỗng (e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855)
trong tài liệu mẫu khiến bước kiểm tra toàn vẹn từ chối giải mã mod.
"""

import os
import sys
import io
import json
import shutil
import zipfile
import hashlib
import argparse
import tempfile
from pathlib import Path

# 1. Sửa khối khởi tạo Windows ở đầu file (Bật ANSI Color + UTF-8)
if sys.platform == "win32":
    try:
        os.system("")  # Kích hoạt ANSI Escape Codes trên Windows CMD / PowerShell
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Thêm thư mục hiện tại vào sys.path để import security
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Nạp pack_security (module đóng gói chuyên dụng của Developer)
try:
    import pack_security
except Exception:
    pack_security = None

# Ưu tiên nạp trực tiếp security.py (nếu đang ở môi trường Dev) để tránh nạp nhầm bản .pyd cũ chưa biên dịch lại
import importlib.util

try:
    _sec_py_path = os.path.join(CURRENT_DIR, "security.py")
    if os.path.exists(_sec_py_path):
        _spec = importlib.util.spec_from_file_location("security", _sec_py_path)
        security = importlib.util.module_from_spec(_spec)
        sys.modules["security"] = security
        _spec.loader.exec_module(security)
    else:
        import security
except Exception as e:
    print(f"[!] Lỗi: Không thể nạp module 'security': {e}")
    print("Vui lòng đảm bảo file security.py hoặc security.pyd nằm cùng thư mục với script này.")
    sys.exit(1)


# 2. Bổ sung YELLOW vào class Colors để không bị crash ở make_diff()
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    WARNING = "\033[93m"
    YELLOW = "\033[93m"   # Khắc phục lỗi AttributeError trong make_diff()
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


def format_size(bytes_size):
    """Định dạng dung lượng byte thành chuỗi KB / MB / GB thân thiện."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"~{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"~{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"~{bytes_size / (1024 * 1024 * 1024):.2f} GB"


def compute_sha256(file_path):
    """Tính mã băm SHA-256 an toàn từng chunk 1MB."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest().lower()


# 3. Nâng cấp zip_directory: Lọc file rác hệ thống & trả về danh sách archive_names
IGNORED_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}
IGNORED_EXTS = (".congu", ".congu_bak", ".congu_tx_tmp", ".bak", ".pyc")

def zip_directory(dir_path, output_zip_path, exclude_abs_paths=None):
    """Nén đệ quy thư mục thành file zip chuẩn, loại bỏ file rác hệ thống."""
    file_count = 0
    total_raw_bytes = 0
    packed_entries = set()
    exclude_abs_paths = {os.path.normcase(os.path.abspath(p)) for p in (exclude_abs_paths or [])}

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(dir_path):
            # Bỏ qua các thư mục ẩn hoặc __pycache__
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            for file in files:
                lower_name = file.lower()
                if lower_name in IGNORED_FILES or lower_name.endswith(IGNORED_EXTS):
                    continue

                full_path = os.path.abspath(os.path.join(root, file))
                if os.path.normcase(full_path) in exclude_abs_paths:
                    continue

                rel_path = os.path.relpath(full_path, dir_path)
                archive_name = rel_path.replace(os.sep, "/")
                zf.write(full_path, archive_name)
                packed_entries.add(archive_name)
                file_count += 1
                try:
                    total_raw_bytes += os.path.getsize(full_path)
                except Exception:
                    pass

    if file_count == 0 or total_raw_bytes == 0:
        raise ValueError(f"Thư mục nguồn '{dir_path}' không chứa tệp hợp lệ nào (0 bytes)!")

    return file_count, total_raw_bytes, packed_entries


# 4. Hàm mới: Kiểm tra chéo gói ZIP với install_steps trong games.json
def validate_zip_against_games_json(zip_path, games_json_path, game_id):
    """Đảm bảo mọi file 'source' và 'patch' khai báo trong games.json đều có mặt trong gói mod."""
    if not game_id or not games_json_path or not os.path.exists(games_json_path):
        return

    with open(games_json_path, "r", encoding="utf-8") as f:
        games = json.load(f)

    target_game = next((g for g in games if isinstance(g, dict) and g.get("id") == game_id), None)
    if not target_game or not target_game.get("install_steps"):
        return

    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_names = set(zf.namelist())
        lower_to_actual = {name.lower(): name for name in zip_names}

    if not zip_names:
        raise ValueError(f"Gói nén ZIP '{zip_path}' hoàn toàn trống (0 tệp)!")

    missing_sources = []
    for step in target_game.get("install_steps", []):
        action = step.get("action")
        if action in ("copy_file", "extract_zip") and not step.get("optional", False):
            src = step.get("source", "").replace("\\", "/").strip("/")
            if src and src not in zip_names:
                hint = f" (Có phải ý bạn là '{lower_to_actual[src.lower()]}'? Chú ý phân biệt Hoa/Thường!)" if src.lower() in lower_to_actual else ""
                missing_sources.append((action, src + hint))
        elif action == "patch_binary":
            patch_file = step.get("patch", "").replace("\\", "/").strip("/")
            if patch_file and patch_file not in zip_names:
                hint = f" (Có phải ý bạn là '{lower_to_actual[patch_file.lower()]}'? Chú ý phân biệt Hoa/Thường!)" if patch_file.lower() in lower_to_actual else ""
                missing_sources.append((action, patch_file + hint))
        elif action == "copy_folder":
            src_folder = step.get("source", "").replace("\\", "/").strip("/")
            if src_folder and not any(name == src_folder or name.startswith(src_folder + "/") for name in zip_names):
                missing_sources.append((action, src_folder + "/"))

    if missing_sources:
        err_msg = "\n".join([f"  - Bước '{act}' yêu cầu '{src}' nhưng KHÔNG TÌM THẤY trong gói nén!" for act, src in missing_sources])
        raise ValueError(
            f"Cấu trúc tệp đóng gói bị lệch so với 'install_steps' của game '{game_id}' trong games.json:\n{err_msg}\n"
            f"  (Gợi ý: Kiểm tra xem bạn có nén dư 1 tầng thư mục cha bên ngoài hay đặt sai tên file không)"
        )


def update_games_json(games_json_path, game_id, sha256_hash, mod_size_str=None):
    """
    Tự động cập nhật trường congu_sha256 và mod_size vào games.json.
    Tự động sao lưu dự phòng games.json.bak để chống mất dữ liệu.
    """
    if not os.path.exists(games_json_path):
        raise FileNotFoundError(f"Không tìm thấy file cấu hình {games_json_path}")

    # Đọc games.json
    with open(games_json_path, "r", encoding="utf-8") as f:
        games = json.load(f)

    if not isinstance(games, list):
        raise ValueError("Cấu trúc games.json không hợp lệ (phải là một danh sách JSON array).")

    # Tìm game theo id
    target_game = None
    for g in games:
        if isinstance(g, dict) and g.get("id") == game_id:
            target_game = g
            break

    if not target_game:
        available_ids = [g.get("id") for g in games if isinstance(g, dict) and g.get("id")]
        raise ValueError(
            f"Không tìm thấy game có id='{game_id}' trong games.json.\nCác id hiện có: {', '.join(available_ids[:10])}..."
        )

    # Backup file trước khi ghi đè
    bak_path = games_json_path + ".bak"
    shutil.copy2(games_json_path, bak_path)

    old_sha = target_game.get("congu_sha256", "chưa có")
    target_game["congu_sha256"] = sha256_hash

    if mod_size_str:
        target_game["mod_size"] = mod_size_str
        if "translation_stats" in target_game and isinstance(target_game["translation_stats"], dict):
            target_game["translation_stats"]["mod_size"] = mod_size_str

    # Ghi lại games.json với định dạng đẹp mắt
    with open(games_json_path, "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False, indent=2)

    return old_sha, target_game.get("title", game_id)


def pack_mod(
    source_path,
    output_congu_path=None,
    game_id=None,
    version=2,
    games_json_path=None,
    auto_update_json=False,
):
    """
    Thực hiện toàn bộ quy trình:
    1. Kiểm tra nguồn (thư mục hoặc file .zip).
    2. Nén thành zip (nếu nguồn là thư mục).
    3. Mã hóa thành .congu (AES-256-GCM V2 Streaming).
    4. Tính toán mã băm SHA-256 thực tế.
    5. Cập nhật vào games.json (nếu được yêu cầu).
    """
    source_path = os.path.abspath(source_path)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Đường dẫn nguồn không tồn tại: {source_path}")

    # Xác định đường dẫn output .congu
    if not output_congu_path:
        if game_id:
            output_dir = os.path.join(CURRENT_DIR, "dist_mods")
            os.makedirs(output_dir, exist_ok=True)
            output_congu_path = os.path.join(output_dir, f"{game_id}.congu")
        else:
            base_name = os.path.splitext(os.path.basename(source_path))[0]
            output_congu_path = os.path.join(os.path.dirname(source_path), f"{base_name}.congu")

    output_congu_path = os.path.abspath(output_congu_path)
    os.makedirs(os.path.dirname(output_congu_path), exist_ok=True)

    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")
    print(f"{Colors.BOLD}   CÔNG CỤ ĐÓNG GÓI & TÍNH MÃ BĂM CONGU MOD (CoNgu Packager V2){Colors.ENDC}")
    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")
    print(f"📦 Nguồn mod:       {source_path}")
    print(f"🎯 File đích:       {output_congu_path}")
    print(f"🔒 Phiên bản mã hóa: V{version} (AES-256-GCM Streaming Chunked)")

    temp_zip_file = None
    try:
        # Bước 1: Chuẩn bị file zip
        if os.path.isdir(source_path):
            print(f"\n{Colors.CYAN}[1/4] Đang nén thư mục thành gói dữ liệu trung gian...{Colors.ENDC}")
            fd, temp_zip_path = tempfile.mkstemp(suffix=".zip", prefix="congu_pack_")
            os.close(fd)
            temp_zip_file = temp_zip_path
            count, raw_size, packed_entries = zip_directory(
                source_path,
                temp_zip_path,
                exclude_abs_paths=[output_congu_path, temp_zip_path],
            )
            print(f"  -> Đã nén {count} tệp ({format_size(raw_size)})")
            zip_to_encrypt = temp_zip_path
        elif zipfile.is_zipfile(source_path):
            print(f"\n{Colors.CYAN}[1/4] Nguồn đã là file nén ZIP hợp lệ.{Colors.ENDC}")
            zip_to_encrypt = source_path
        else:
            raise ValueError(f"Nguồn '{source_path}' không phải là thư mục hoặc tệp ZIP hợp lệ.")

        # Bước 1.5: Kiểm tra chéo tính toàn vẹn với install_steps trong games.json (nếu có game_id)
        if game_id:
            g_json = games_json_path or os.path.join(CURRENT_DIR, "games.json")
            validate_zip_against_games_json(zip_to_encrypt, g_json, game_id)
            print(f"  -> {Colors.GREEN}Xác thực thành công: Gói mod khớp chính xác với install_steps trong games.json!{Colors.ENDC}")

        # Bước 2: Mã hóa sang định dạng .congu
        print(f"{Colors.CYAN}[2/4] Đang mã hóa bảo mật container .congu (Zero-Leakage Streaming)...{Colors.ENDC}")
        encrypt_func = pack_security.encrypt_mod_package if pack_security else security.encrypt_mod_package
        out_bytes = encrypt_func(
            zip_to_encrypt,
            output_congu_path,
            version=version,
            chunk_size=4 * 1024 * 1024,
        )
        mod_size_str = format_size(out_bytes)
        print(f"  -> Mã hóa hoàn tất! Kích thước container: {mod_size_str} ({out_bytes:,} bytes)")

        # Bước 3: Tính toán mã băm SHA-256 thực tế
        print(f"{Colors.CYAN}[3/4] Đang tính toán mã băm SHA-256 thực tế của file .congu...{Colors.ENDC}")
        sha256_hash = compute_sha256(output_congu_path)
        print(f"  -> {Colors.BOLD}SHA-256: {Colors.GREEN}{sha256_hash}{Colors.ENDC}")

        # Kiểm tra tính an toàn: Tuyệt đối không phải hash chuỗi rỗng
        EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        if sha256_hash == EMPTY_SHA256:
            raise ValueError("LỖI BẢO MẬT: File .congu sinh ra rỗng (0 byte)! Vui lòng kiểm tra lại dữ liệu nguồn.")

        # Bước 4: Tự động cập nhật games.json nếu có yêu cầu
        if auto_update_json and game_id:
            if not games_json_path:
                games_json_path = os.path.join(CURRENT_DIR, "games.json")
            print(f"{Colors.CYAN}[4/4] Đang cập nhật mã băm vào games.json...{Colors.ENDC}")
            old_sha, game_title = update_games_json(
                games_json_path, game_id, sha256_hash, mod_size_str
            )
            print(f"  -> Đã cập nhật game: {Colors.BOLD}{game_title}{Colors.ENDC} ({game_id})")
            print(f"     Mã cũ: {old_sha}")
            print(f"     Mã mới: {Colors.GREEN}{sha256_hash}{Colors.ENDC}")
            print(f"     File games.json đã được lưu và sao lưu an toàn tại games.json.bak")
        else:
            print(f"{Colors.WARNING}[4/4] Bỏ qua cập nhật games.json (sử dụng cờ --update-json để tự động hóa).{Colors.ENDC}")

        print(f"\n{Colors.GREEN}{Colors.BOLD}✔ ĐÓNG GÓI MOD THÀNH CÔNG RỰC RỠ!{Colors.ENDC}")
        print(f"------------------------------------------------------------------------")
        print(f"Tệp đầu ra : {output_congu_path}")
        print(f"Dung lượng : {mod_size_str}")
        print(f"congu_sha256: {Colors.BOLD}{sha256_hash}{Colors.ENDC}")
        print(f"------------------------------------------------------------------------")
        print(f"💡 Hướng dẫn tiếp theo:")
        print(f" 1. Tải tệp '{os.path.basename(output_congu_path)}' lên GitHub Releases hoặc Google Drive.")
        print(f" 2. Đảm bảo 'congu_sha256' trong games.json khớp chính xác với mã băm trên.")
        print(f" 3. Khởi chạy ứng dụng VietModHub để trải nghiệm cài đặt mượt mà!")
        print(f"========================================================================\n")

        return {
            "output_path": output_congu_path,
            "sha256": sha256_hash,
            "size_str": mod_size_str,
            "size_bytes": out_bytes,
        }

    finally:
        # Dọn dẹp tệp tạm thời
        if temp_zip_file and os.path.exists(temp_zip_file):
            try:
                os.remove(temp_zip_file)
            except Exception:
                pass


def interactive_mode():
    """Giao diện dòng lệnh tương tác trực quan khi chạy không có đối số."""
    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")
    print(f"{Colors.BOLD}      TRÌNH ĐÓNG GÓI GÓI MOD TIẾNG VIỆT - VIETMOD MANAGER (CoNgu V2){Colors.ENDC}")
    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")

    games_json_path = os.path.join(CURRENT_DIR, "games.json")
    games_list = []
    if os.path.exists(games_json_path):
        try:
            with open(games_json_path, "r", encoding="utf-8") as f:
                raw_games = json.load(f)
                if isinstance(raw_games, list):
                    games_list = raw_games
        except Exception:
            pass

    selected_game_id = None
    if games_list:
        print(f"\n{Colors.CYAN}Danh sách tựa game được hỗ trợ trong hệ thống:{Colors.ENDC}")
        for idx, g in enumerate(games_list, 1):
            title = g.get("title") or g.get("vietnamese_title") or g.get("id")
            gid = g.get("id")
            sha = g.get("congu_sha256", "chưa có")
            short_sha = (sha[:12] + "...") if len(sha) > 12 else sha
            print(f" [{idx:2d}] {title:<35} (id: {gid}) [SHA: {short_sha}]")
        print(" [ 0] Tự chỉ định đường dẫn / Không dùng danh sách trên\n")

        choice = input("👉 Nhập số thứ tự game cần đóng gói (hoặc 0): ").strip()
        if choice.isdigit():
            c_int = int(choice)
            if 1 <= c_int <= len(games_list):
                selected_game_id = games_list[c_int - 1].get("id")
                print(f"-> Đã chọn game: {Colors.BOLD}{games_list[c_int - 1].get('title')}{Colors.ENDC} ({selected_game_id})")

    source_path = input("📁 Nhập hoặc kéo thả thư mục mod / file .zip vào đây: ").strip().strip('"').strip("'")
    if not source_path or not os.path.exists(source_path):
        print(f"{Colors.FAIL}[!] Đường dẫn không tồn tại. Hủy thao tác.{Colors.ENDC}")
        return

    update_json = False
    if selected_game_id:
        confirm = input(f"❓ Tự động cập nhật 'congu_sha256' vào games.json? [Y/n]: ").strip().lower()
        update_json = (confirm != "n")

    pack_mod(
        source_path=source_path,
        game_id=selected_game_id,
        version=2,
        games_json_path=games_json_path,
        auto_update_json=update_json,
    )


def make_diff(orig_file, modded_file, output_patch=None, algorithm="auto"):
    """
    Tạo tệp vá nhị phân siêu nhẹ giữa tệp gốc và tệp đã mod.
    Hỗ trợ cơ chế Streaming Sliding Window (xdelta3/hdiffz) chống tràn RAM (MemoryError) cho tệp hàng GB.
    In ra mã băm SHA-256 cùng cấu hình mẫu patch_binary cho games.json.
    """
    orig_path = os.path.abspath(orig_file)
    mod_path = os.path.abspath(modded_file)

    if not os.path.exists(orig_path):
        raise FileNotFoundError(f"Không tìm thấy tệp gốc: {orig_path}")
    if not os.path.exists(mod_path):
        raise FileNotFoundError(f"Không tìm thấy tệp mod: {mod_path}")

    if not output_patch:
        output_patch = mod_path + ".diff"
    output_patch = os.path.abspath(output_patch)

    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")
    print(f"{Colors.BOLD}   CÔNG CỤ TẠO BẢN VÁ NHỊ PHÂN SIÊU NHẸ (STREAMING BINARY DIFF PATCHER){Colors.ENDC}")
    print(f"{Colors.HEADER}========================================================================{Colors.ENDC}")
    print(f"📄 Tệp gốc (Original) : {orig_path}")
    print(f"✨ Tệp mod (Modded)   : {mod_path}")
    print(f"🎯 Tệp diff đích      : {output_patch}")
    print(f"⚙ Thuật toán cấu hình: {algorithm.upper()}")

    orig_size = os.path.getsize(orig_path)
    mod_size = os.path.getsize(mod_path)
    print(f"\n{Colors.CYAN}[1/3] Đang tính mã băm SHA-256 của các tệp...{Colors.ENDC}")
    orig_sha = compute_sha256(orig_path)
    mod_sha = compute_sha256(mod_path)
    print(f"  -> File gốc SHA-256: {orig_sha}")
    print(f"  -> File mod SHA-256: {mod_sha}")

    if orig_size > 150 * 1024 * 1024:
        print(f"\n{Colors.YELLOW}⚡ [Streaming Diff Activated] Tệp gốc {format_size(orig_size)} > 150 MB.{Colors.ENDC}")
        print(f"{Colors.YELLOW}   Kích hoạt cơ chế cửa sổ trượt (Sliding Window 64MB RAM) chống văng MemoryError!{Colors.ENDC}")

    print(f"\n{Colors.CYAN}[2/3] Đang phân tích nhị phân và tạo bản vá streaming...{Colors.ENDC}")
    patch_size = security.create_binary_patch(orig_path, mod_path, output_patch, algorithm=algorithm)
    patch_sha = compute_sha256(output_patch)

    saved_pct = (1.0 - (patch_size / max(1, mod_size))) * 100.0

    print(f"\n{Colors.GREEN}{Colors.BOLD}✔ TẠO BẢN VÁ NHỊ PHÂN THÀNH CÔNG RỰC RỠ!{Colors.ENDC}")
    print(f"------------------------------------------------------------------------")
    print(f"Dung lượng tệp gốc : {format_size(orig_size)} ({orig_size:,} bytes)")
    print(f"Dung lượng tệp mod : {format_size(mod_size)} ({mod_size:,} bytes)")
    print(f"Dung lượng bản vá  : {Colors.BOLD}{Colors.GREEN}{format_size(patch_size)}{Colors.ENDC} ({patch_size:,} bytes)")
    print(f"Tiết kiệm băng thông: {Colors.BOLD}{Colors.GREEN}{saved_pct:.1f}%{Colors.ENDC} dung lượng phân phối!")
    print(f"Mã SHA-256 file diff: {patch_sha}")
    print(f"------------------------------------------------------------------------")
    print(f"\n💡 Cấu hình mẫu 'patch_binary' để dán vào 'install_steps' trong games.json:")
    sample_target = os.path.basename(orig_path)
    sample_patch = os.path.basename(output_patch)
    sample_json = f"""{{
  "action": "patch_binary",
  "target": "{sample_target}",
  "patch": "{sample_patch}",
  "original_sha256": "{orig_sha}",
  "patched_sha256": "{mod_sha}"
}}"""
    print(f"{Colors.CYAN}{sample_json}{Colors.ENDC}")
    print(f"========================================================================\n")


def main():
    parser = argparse.ArgumentParser(
        description="Đóng gói mod Việt Hóa thành container .congu V2 và tự động tính mã băm SHA-256.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  # Chế độ tương tác từng bước:
  python pack_mod.py

  # Đóng gói thư mục mod cho game 'preludes' và tự động cập nhật games.json:
  python pack_mod.py "mods/Tails The Backbone Preludes" --game-id preludes --update-json

  # Tạo file vá nhị phân diff siêu nhẹ (tiết kiệm 99% dung lượng cho game Unity/GameMaker):
  python pack_mod.py --diff resources.assets.orig resources.assets.mod -o resources.assets.diff
  
  # Tạo file vá nhị phân với thuật toán streaming xdelta3 cho file dung lượng hàng GB:
  python pack_mod.py --diff bigfile.pak.orig bigfile.pak.mod --algorithm xdelta -o bigfile.pak.diff
        """,
    )
    parser.add_argument("source", nargs="?", help="Đường dẫn thư mục mod hoặc file zip nguồn.")
    parser.add_argument("-o", "--output", help="Đường dẫn file .congu hoặc .diff đầu ra (tùy chọn).")
    parser.add_argument("-g", "--game-id", help="Mã ID của game trong games.json.")
    parser.add_argument("-v", "--version", type=int, default=2, choices=[1, 2], help="Phiên bản định dạng .congu (1: Legacy, 2: Streaming Chunked). Mặc định: 2.")
    parser.add_argument("-j", "--games-json", help="Đường dẫn file games.json (mặc định: ./games.json).")
    parser.add_argument("--update-json", action="store_true", help="Tự động cập nhật mã băm SHA-256 và dung lượng vào games.json.")
    parser.add_argument("--diff", nargs=2, metavar=("ORIGINAL", "MODDED"), help="Tạo tệp vá nhị phân giữa tệp gốc và tệp mod.")
    parser.add_argument("--algorithm", default="auto", choices=["auto", "xdelta", "hdiff", "bsdiff"], help="Thuật toán tạo diff: 'auto' (tự động chọn xdelta/hdiff cho file > 150MB), 'xdelta' (VCDIFF), 'hdiff' (HDiffPatch), 'bsdiff' (BSDIFF40). Mặc định: auto.")

    args = parser.parse_args()

    if args.diff:
        orig_file, mod_file = args.diff
        make_diff(orig_file, mod_file, args.output, algorithm=args.algorithm)
        return

    if not args.source:
        interactive_mode()
        return

    pack_mod(
        source_path=args.source,
        output_congu_path=args.output,
        game_id=args.game_id,
        version=args.version,
        games_json_path=args.games_json,
        auto_update_json=args.update_json,
    )


if __name__ == "__main__":
    main()
