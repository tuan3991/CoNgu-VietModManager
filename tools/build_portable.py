# -*- coding: utf-8 -*-
"""
Script đóng gói và đồng bộ bản VietModHub Portable (.exe).
Tự động copy bản build PyInstaller từ dist/VietModHub sang VietModHub_Portable,
đồng bộ tài nguyên static, tools, games.json, bảo mật .pyd và đóng gói file zip.
"""
import os
import sys
import shutil
import zipfile
import subprocess

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(ROOT_DIR, "dist", "VietModHub")
PORTABLE_DIR = os.path.join(ROOT_DIR, "VietModHub_Portable")
ZIP_NAME = "CoNgu_v2.0.6_Portable.zip"
ZIP_PATH = os.path.join(ROOT_DIR, ZIP_NAME)

# Dữ liệu cá nhân của máy build TUYỆT ĐỐI không được đóng gói phát hành.
PERSONAL_FILES = [
    "PlayerProfile.congu_save",
    "user_config.json",
    "user_data.json",
    "accounts_index.json",
    ".congu_playtime.json",
    "playtime.json",
    "achievements_progress.json",
    "community_requests.json",
    "custom_games.json",
    "active_downloads.json",
    "startup.log",
]
PERSONAL_DIRS = [
    "account_profiles",
    "save_backups",
    "quick_checkpoints",
    "webview2_profile",
    "cache",
    "temp",
]
PERSONAL_GLOBS = ["*.congu_save", "*.congu_save_tmp", "*.log", "congu-save-*.zip*"]


def purge_personal_data():
    """Xóa mọi dữ liệu cá nhân còn sót trong thư mục portable trước khi nén."""
    import glob

    removed = []
    for name in PERSONAL_FILES:
        target = os.path.join(PORTABLE_DIR, name)
        if os.path.isfile(target):
            try:
                os.remove(target)
                removed.append(name)
            except OSError as e:
                print(f"    [!] Không thể xóa dữ liệu cá nhân {name}: {e}")

    for name in PERSONAL_DIRS:
        target = os.path.join(PORTABLE_DIR, name)
        if os.path.isdir(target):
            try:
                shutil.rmtree(target)
                removed.append(name + "/")
            except OSError as e:
                print(f"    [!] Không thể xóa thư mục cá nhân {name}: {e}")

    for pattern in PERSONAL_GLOBS:
        for target in glob.glob(os.path.join(PORTABLE_DIR, pattern)):
            try:
                if os.path.isfile(target):
                    os.remove(target)
                    removed.append(os.path.basename(target))
            except OSError:
                pass

    if removed:
        print(f"    [AN TOÀN] Đã loại bỏ dữ liệu cá nhân: {', '.join(sorted(set(removed)))}")
    else:
        print("    [AN TOÀN] Không có dữ liệu cá nhân trong thư mục portable.")
    return removed

def sync_portable():
    print(f"[*] Đồng bộ từ {DIST_DIR} -> {PORTABLE_DIR}...")
    if not os.path.exists(DIST_DIR):
        print(f"[!] Không tìm thấy thư mục build: {DIST_DIR}")
        return False

    os.makedirs(PORTABLE_DIR, exist_ok=True)
    # Dọn dữ liệu cá nhân còn sót từ lần build trước trước khi copy bản mới.
    purge_personal_data()

    # 1. Copy VietModHub.exe
    exe_src = os.path.join(DIST_DIR, "VietModHub.exe")
    exe_dst = os.path.join(PORTABLE_DIR, "VietModHub.exe")
    if os.path.exists(exe_src):
        shutil.copy2(exe_src, exe_dst)
        print(f"    [OK] Đã cập nhật: VietModHub.exe ({os.path.getsize(exe_dst):,} bytes)")

    # 2. Đồng bộ _internal
    internal_src = os.path.join(DIST_DIR, "_internal")
    internal_dst = os.path.join(PORTABLE_DIR, "_internal")
    if os.path.exists(internal_src):
        print("    [*] Đang đồng bộ thư mục _internal...")
        # Xóa các file cũ trong internal_dst nếu cần hoặc copy đè
        shutil.copytree(internal_src, internal_dst, dirs_exist_ok=True)
        print("    [OK] Thư mục _internal đã được đồng bộ.")

    # 3. Đồng bộ static, tools, metadata
    for folder in ["static", "tools"]:
        f_src = os.path.join(ROOT_DIR, folder)
        f_dst = os.path.join(PORTABLE_DIR, folder)
        if os.path.exists(f_src):
            shutil.copytree(f_src, f_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"    [OK] Đồng bộ thư mục {folder}/")

    for file_name in [
        "games.json", "version.json", "app_icon.ico", "app_icon.png",
        "security.cp311-win_amd64.pyd", "security.pyd"
    ]:
        file_src = os.path.join(ROOT_DIR, file_name)
        file_dst = os.path.join(PORTABLE_DIR, file_name)
        if os.path.exists(file_src):
            shutil.copy2(file_src, file_dst)
            print(f"    [OK] Đã sao chép: {file_name}")

    # 4. Dọn dẹp các file thừa không thuộc bản phát hành
    cleanup_patterns = [
        "security.py", "controller_engine.py", "discovery_manager.py",
        "games_DESKTOP-8CQDJE9_Oct-30-133115-2026_Conflict.json"
    ]
    for item in cleanup_patterns:
        target = os.path.join(PORTABLE_DIR, item)
        if os.path.exists(target):
            try:
                os.remove(target)
                print(f"    [OK] Đã dọn dẹp file thừa: {item}")
            except Exception as e:
                print(f"    [!] Không thể xóa {item}: {e}")

    # Tuyệt đối không để lộ file security.py
    for root, dirs, files in os.walk(PORTABLE_DIR):
        if "security.py" in files:
            os.remove(os.path.join(root, "security.py"))
            print("    [AN TOÀN] Đã xóa security.py mã nguồn trong thư mục con.")

    return True

def create_zip():
    print(f"[*] Đang đóng gói bản nén: {ZIP_NAME}...")
    temp_zip = ZIP_PATH + ".tmp"
    if os.path.exists(temp_zip):
        os.remove(temp_zip)

    ignored_exts = {".pyc", ".tmp", ".log"}
    ignored_names = {"security.py", "__pycache__"}
    # Chặn cứng dữ liệu cá nhân, kể cả khi file lọt vào thư mục portable.
    blocked_files = set(PERSONAL_FILES)
    blocked_dirs = set(PERSONAL_DIRS) | {"__pycache__"}

    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(PORTABLE_DIR):
            # Lọc bỏ thư mục không cần thiết
            dirs[:] = [d for d in dirs if d not in ignored_names and d not in blocked_dirs]
            for file in files:
                if file in ignored_names or file in blocked_files:
                    continue
                if any(file.endswith(ext) for ext in ignored_exts):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PORTABLE_DIR)
                # Đưa vào thư mục gốc VietModHub_Portable trong zip
                arc_name = os.path.join("VietModHub_Portable", rel_path)
                zf.write(full_path, arc_name)

    if os.path.exists(ZIP_PATH):
        try:
            os.remove(ZIP_PATH)
        except Exception:
            pass
    os.replace(temp_zip, ZIP_PATH)
    print(f"[OK] Đã tạo thành công {ZIP_PATH} ({os.path.getsize(ZIP_PATH):,} bytes)")

if __name__ == "__main__":
    if sync_portable():
        create_zip()
        print("\n====================================================")
        print("HOÀN TẤT ĐÓNG GÓI ỨNG DỤNG RA FILE EXE & PORTABLE ZIP!")
        print(f"- File chạy trực tiếp: {os.path.join(PORTABLE_DIR, 'VietModHub.exe')}")
        print(f"- Thư mục Portable:    {PORTABLE_DIR}")
        print(f"- File nén phát hành:  {ZIP_PATH}")
        print("====================================================")
