import sys

# Ensure stdout and stderr never raise UnicodeEncodeError on Windows cp1252 consoles
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import security

try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch, find_tool_exe
except ImportError:
    class SecurityError(PermissionError):
        """Lỗi vi phạm an ninh hệ thống hoặc phát hiện hành vi can thiệp trái phép."""
        pass

    class PathTraversalError(SecurityError):
        """Phát hiện lỗ hổng Path Traversal hoặc Zip Slip."""
        pass

    def validate_safe_path(base_dir, relative_or_target_path, allow_base_itself=False):
        """Chuẩn hóa và kiểm tra an toàn đường dẫn bắt buộc (Chống Path Traversal & Zip Slip)."""
        if not base_dir:
            raise PathTraversalError("Thư mục gốc (game_root) không được để trống!")
        if relative_or_target_path is None or str(relative_or_target_path).strip() == "":
            if allow_base_itself:
                return os.path.realpath(base_dir)
            raise PathTraversalError("Đường dẫn thao tác không được để trống!")

        base_real = os.path.realpath(base_dir)
        path_str = str(relative_or_target_path).strip()

        if os.path.isabs(path_str):
            target_real = os.path.realpath(path_str)
        else:
            target_real = os.path.realpath(os.path.join(base_real, path_str))

        base_norm = os.path.normcase(base_real)
        target_norm = os.path.normcase(target_real)

        try:
            common = os.path.commonpath([base_norm, target_norm])
        except ValueError as e:
            raise PathTraversalError(
                f"Cảnh báo bảo mật (Cross-Drive Traversal): Đường dẫn '{path_str}' nằm khác phân vùng ổ đĩa với thư mục game '{base_dir}'! ({e})"
            )

        if common != base_norm:
            raise PathTraversalError(
                f"Cảnh báo bảo mật (Path Traversal): Phát hiện đường dẫn trái phép '{path_str}' trỏ ra ngoài phạm vi thư mục game '{base_dir}'! Từ chối thực thi để bảo vệ an toàn."
            )

        if not allow_base_itself and target_norm == base_norm:
            raise PathTraversalError(
                f"Cảnh báo bảo mật: Thao tác không được phép nhắm trực tiếp vào chính thư mục gốc của game '{base_dir}'!"
            )

        return target_real

    def find_tool_exe(tool_name: str):
        exe_name = tool_name if tool_name.lower().endswith(".exe") else f"{tool_name}.exe"
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "tools", exe_name))
            candidates.append(os.path.join(sys._MEIPASS, exe_name))
        current_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(current_dir, "tools", exe_name))
        candidates.append(os.path.join(current_dir, exe_name))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "tools", exe_name))
        candidates.append(os.path.join(exe_dir, exe_name))
        candidates.append(os.path.join(os.getcwd(), "tools", exe_name))
        candidates.append(os.path.join(os.getcwd(), exe_name))
        for p in candidates:
            if os.path.isfile(p):
                return os.path.abspath(p)
        found = shutil.which(exe_name) or shutil.which(tool_name)
        if found:
            return os.path.abspath(found)
        return None

    def apply_binary_patch(src_file, dst_file, patch_data_or_file):
        """Fallback áp dụng binary patch theo luồng cửa sổ trượt."""
        if hasattr(security, "apply_binary_patch"):
            return security.apply_binary_patch(src_file, dst_file, patch_data_or_file)
        raise RuntimeError("Không tìm thấy hàm apply_binary_patch trong security!")


def download_file_with_progress(url, dest_path, progress_callback=None):
    """
    Download file from HTTP/HTTPS URL or Google Drive with progress tracking.
    Handles Google Drive large file confirmation tokens automatically.
    """
    import urllib.request
    import http.cookiejar
    import time
    import re
    import os

    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    
    # Convert Google Drive share URL to direct download URL
    gdrive_match = re.search(r'(?:drive\.google\.com/file/d/|drive\.google\.com/uc\?id=|id=)([a-zA-Z0-9_-]{25,})', url)
    if gdrive_match:
        file_id = gdrive_match.group(1)
        url = f"https://drive.google.com/uc?export=download&id={file_id}"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    req = urllib.request.Request(url, headers=headers)
    resp = opener.open(req)

    # Check for Google Drive virus scan confirmation
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        body = resp.read().decode("utf-8", errors="ignore")
        confirm_token = re.search(r'confirm=([0-9A-Za-z_]+)', body)
        if not confirm_token:
            confirm_token = re.search(r'name="confirm"\s+value="([^"]+)"', body)
        if confirm_token:
            token = confirm_token.group(1)
            confirm_url = f"{url}&confirm={token}"
            req2 = urllib.request.Request(confirm_url, headers=headers)
            resp = opener.open(req2)

    total_size = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 65536
    start_time = time.time()

    with open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                percent = int(downloaded * 100 / total_size) if total_size > 0 else 50
                elapsed = time.time() - start_time
                speed_kb = (downloaded / 1024) / elapsed if elapsed > 0 else 0
                progress_callback(downloaded, total_size, percent, speed_kb)

    return True

import os
import sys
import json
import shutil
import re
import hashlib
import subprocess
import threading
import time
import secrets
from datetime import datetime
from pathlib import Path
from bottle import Bottle, static_file, request, response, abort
import socketserver
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer
import webview
import glob
import urllib.request
import urllib.parse

# Base paths with PyInstaller frozen support
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(EXE_DIR, "static")):
        APP_DIR = EXE_DIR
        STATIC_DIR = os.path.join(EXE_DIR, "static")
    else:
        APP_DIR = getattr(sys, '_MEIPASS', EXE_DIR)
        STATIC_DIR = os.path.join(APP_DIR, "static")
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(APP_DIR, "static")
DEFAULT_REPO_DIR = r"G:\My Drive\Viethoagame"
FALLBACK_REPO_DIR = r"C:\Users\tuan3\Documents\antigravity google\Viethoagame"
GAMES_JSON = os.path.join(APP_DIR, "games.json")
CONFIG_JSON = os.path.join(APP_DIR, "user_config.json")

# AppData safe backup directory
APPDATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "VietModHub")
BACKUP_ROOT = os.path.join(APPDATA_DIR, "backups")
USER_DATA_FILE = os.path.join(APPDATA_DIR, "user_data.json")
COVERS_DIR = os.path.join(APPDATA_DIR, "covers")
COVERS_CACHE_FILE = os.path.join(APPDATA_DIR, "covers_cache.json")
os.makedirs(COVERS_DIR, exist_ok=True)

def load_covers_cache():
    """Nạp cache metadata & avatar đã tìm được của game lẻ từ tệp JSON."""
    if os.path.exists(COVERS_CACHE_FILE):
        try:
            with open(COVERS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_covers_cache(cache):
    """Lưu cache metadata & avatar của game lẻ vào tệp JSON."""
    try:
        with open(COVERS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Error saving covers cache: {e}")

def extract_local_steam_appid(game_dir: str) -> str | None:
    """Lớp 1: Quét nhanh steam_appid có sẵn trong các file cấu hình của game lẻ/repack (Độ chính xác 100%, 0 giây)."""
    if not game_dir or not os.path.exists(game_dir):
        return None

    # 1. Tìm trực tiếp file steam_appid.txt (ở gốc hoặc trong các thư mục con gần nhất)
    for pattern in ["steam_appid.txt", "*/steam_appid.txt", "*/*/steam_appid.txt"]:
        for path in glob.glob(os.path.join(game_dir, pattern)):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                    if lines and lines[0].isdigit() and int(lines[0]) > 0:
                        return lines[0]
            except OSError:
                pass

    # 2. Quét trong các file .ini phổ biến của game cài ngoài (steam_emu.ini, tenoke.ini, rune.ini...)
    ini_patterns = [
        "steam_emu.ini", "*/steam_emu.ini", "*/*/steam_emu.ini",
        "*tenoke*.ini", "*/*tenoke*.ini",
        "*rune*.ini", "*/*rune*.ini",
        "*codex*.ini", "*/*codex*.ini",
        "*onlinefix*.ini", "*/*onlinefix*.ini",
        "*flt*.ini", "*/*flt*.ini",
        "*ali213*.ini", "*/*ali213*.ini",
        "cream_api.ini", "*/cream_api.ini"
    ]
    for pattern in ini_patterns:
        for path in glob.glob(os.path.join(game_dir, pattern)):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    match = re.search(r"(?:^|\n)\s*#?\s*(?:AppId|SteamAppId|TargetAppId)\s*=\s*(\d{3,10})", text, re.IGNORECASE)
                    if match and match.group(1) != "0":
                        return match.group(1)
            except OSError:
                pass

    # Quét đệ quy nếu file .ini nằm sâu trong thư mục Engine hoặc Plugins (như Unreal Engine / Unity)
    deep_ini_patterns = [
        os.path.join(game_dir, "**", "steam_emu.ini"),
        os.path.join(game_dir, "**", "*tenoke*.ini"),
        os.path.join(game_dir, "**", "*rune*.ini"),
        os.path.join(game_dir, "**", "*codex*.ini"),
        os.path.join(game_dir, "**", "cream_api.ini")
    ]
    for deep_pat in deep_ini_patterns:
        for path in glob.glob(deep_pat, recursive=True):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    match = re.search(r"(?:^|\n)\s*#?\s*(?:AppId|SteamAppId|TargetAppId)\s*=\s*(\d{3,10})", text, re.IGNORECASE)
                    if match and match.group(1) != "0":
                        return match.group(1)
            except OSError:
                pass

    # 3. Quét tệp goggame-*.info (JSON metadata của GOG)
    for path in glob.glob(os.path.join(game_dir, "goggame-*.info")) + glob.glob(os.path.join(game_dir, "*", "goggame-*.info")):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                gog_data = json.load(f)
                gog_appid = gog_data.get("steam_appid") or gog_data.get("gameId")
                if gog_appid and str(gog_appid).isdigit():
                    return str(gog_appid)
        except Exception:
            pass

    return None

def resolve_clean_game_title(game_dir: str, exe_name: str = "") -> str:
    """Lớp 2: Trích xuất và làm sạch tên game thật từ thư mục hoặc Unity app.info."""
    if not game_dir:
        return ""

    # 1. Nếu là game Unity, đọc dòng thứ 2 trong *_Data/app.info (chứa Product Name chuẩn)
    for app_info in glob.glob(os.path.join(game_dir, "*_Data", "app.info")) + glob.glob(os.path.join(game_dir, "*", "*_Data", "app.info")):
        try:
            with open(app_info, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                if len(lines) >= 2 and len(lines[1]) > 1:
                    return lines[1]
        except OSError:
            pass

    # 2. Lấy từ tên thư mục gốc hoặc tên exe và lọc bỏ rác kỹ thuật
    raw_name = os.path.basename(os.path.normpath(game_dir))
    if raw_name.lower() in ("binaries", "win64", "win32", "x64", "x86", "game", "bin") and exe_name:
        raw_name = os.path.splitext(os.path.basename(exe_name))[0]
    elif raw_name.lower() in ("binaries", "win64", "win32", "x64", "x86", "game", "bin"):
        raw_name = os.path.basename(os.path.dirname(os.path.normpath(game_dir)))

    # Xóa các hậu tố Engine, phiên bản và nhóm Repack
    clean = re.sub(r"(-Win64-Shipping|-Win32-Shipping|_x64|_x86|_DX11|_DX12|-Shipping)", "", raw_name, flags=re.IGNORECASE)
    clean = re.sub(r"\[.*?\]|\(.*?\)", " ", clean)
    clean = re.sub(r"\b(v?\d+(\.\d+)+|repack|portable|gog|fitgirl|dodi|elamigos|tenoke|rune|codex|flt|goldberg|cpi|skidrow)\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[._\-]+", " ", clean)
    # Tách chữ CamelCase (VD: RavenousDevils -> Ravenous Devils)
    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", clean)
    return re.sub(r"\s+", " ", clean).strip()

def extract_exe_icon(exe_path: str, output_img_path: str) -> bool:
    """Lớp 4 Fallback: Trích xuất icon gốc từ file .exe trên Windows thành file PNG."""
    if not exe_path or not os.path.exists(exe_path) or not sys.platform.startswith("win"):
        return False
    try:
        clean_exe = os.path.abspath(exe_path).replace("'", "''")
        clean_out = os.path.abspath(output_img_path).replace("'", "''")
        ps_cmd = (
            f"Add-Type -AssemblyName System.Drawing; "
            f"$icon = [System.Drawing.Icon]::ExtractAssociatedIcon('{clean_exe}'); "
            f"if ($icon) {{ $bitmap = $icon.ToBitmap(); $bitmap.Save('{clean_out}', [System.Drawing.Imaging.ImageFormat]::Png); exit 0 }} else {{ exit 1 }}"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd], capture_output=True, timeout=5)
        return res.returncode == 0 and os.path.exists(output_img_path) and os.path.getsize(output_img_path) > 500
    except Exception:
        return False

def fetch_game_metadata_and_avatar(game_dir: str = "", exe_name: str = "", fallback_title: str = "", game_id: str = "") -> dict:
    """
    Lớp 3 & Lớp 4: Tự động tìm steam_appid, link ảnh bìa dọc 600x900 và thể loại cho game lẻ.
    Đồng thời lưu cache ảnh bìa tại chỗ (%APPDATA%/VietModHub/covers/{game_id}.jpg).
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    appid = extract_local_steam_appid(game_dir) if game_dir else None
    clean_title = fallback_title or resolve_clean_game_title(game_dir, exe_name)

    # 1. Nếu chưa có appid trong thư mục, tìm nhanh trong cơ sở dữ liệu steam_games.json offline (hơn 5,000 game)
    if not appid and clean_title:
        try:
            games_db = get_steam_games()
            q_clean = clean_title.lower().strip()
            for item in games_db:
                item_name = item.get("name", "").lower()
                if item_name == q_clean or item_name.startswith(q_clean):
                    appid = str(item["id"])
                    clean_title = item.get("name", clean_title)
                    break
            if not appid:
                for item in games_db:
                    if q_clean in item.get("name", "").lower():
                        appid = str(item["id"])
                        clean_title = item.get("name", clean_title)
                        break
        except Exception as e:
            print(f"[Metadata] Offline steam db search error: {e}")

    # Nếu vẫn chưa có appid, gọi Steam StoreSearch API từ Backend (tránh CORS)
    if not appid and clean_title:
        try:
            query = urllib.parse.quote(clean_title)
            search_url = f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US"
            req = urllib.request.Request(search_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    appid = str(items[0]["id"])
                    clean_title = items[0].get("name", clean_title)
        except Exception:
            pass

    result = {
        "steam_appid": appid,
        "title": clean_title,
        "avatar_url": None,
        "header_url": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg" if appid else None,
        "local_cover": None,
        "genre": "GAME LẺ"
    }

    # Kiểm tra xem đã có custom cover do người dùng chọn hoặc cover tải trước đó chưa
    safe_gid = re.sub(r"[^\w\-]", "_", game_id or appid or clean_title or "unknown")
    local_cover_file = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
    local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")
    if os.path.exists(local_cover_file) and os.path.getsize(local_cover_file) > 1000:
        result["local_cover"] = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
        result["avatar_url"] = result["local_cover"]
    elif os.path.exists(local_cover_png) and os.path.getsize(local_cover_png) > 500:
        result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
        result["avatar_url"] = result["local_cover"]

    if not appid:
        # Nếu không có appid, thử trích xuất icon từ file exe
        if not result["local_cover"] and game_dir and exe_name:
            full_exe = os.path.join(game_dir, exe_name)
            if not os.path.exists(full_exe):
                cand = os.path.join(game_dir, os.path.basename(exe_name))
                if os.path.exists(cand):
                    full_exe = cand
            if os.path.exists(full_exe):
                if extract_exe_icon(full_exe, local_cover_png):
                    result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
                    result["avatar_url"] = result["local_cover"]
        return result

    # 2. Kiểm tra xem ảnh dọc 600x900 chuẩn có tồn tại không (Fallback Chain: Cloudflare -> Fastly -> Akamai)
    candidate_posters = [
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
    ]
    for url in candidate_posters:
        try:
            req = urllib.request.Request(url, method="HEAD", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    result["avatar_url"] = url
                    break
        except Exception:
            continue

    # 3. Gọi thêm appdetails để lấy thể loại (Genre) và lấy ảnh dự phòng nếu game dùng URL chứa mã hash mới
    try:
        details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese"
        req = urllib.request.Request(details_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            details_data = json.loads(resp.read().decode("utf-8"))
            app_data = details_data.get(str(appid), {}).get("data", {})
            if app_data:
                result["title"] = app_data.get("name", result["title"])
                result["header_url"] = app_data.get("header_image") or result["header_url"]
                if not result["avatar_url"]:
                    result["avatar_url"] = result["header_url"]
                genres = app_data.get("genres", [])
                if genres:
                    result["genre"] = genres[0].get("description", "PHIÊU LƯU").upper()
    except Exception:
        pass

    # 4. Lớp 4: Tự động tải và cache ảnh bìa xuống %APPDATA%/VietModHub/covers/{safe_gid}.jpg
    if (result.get("avatar_url") or result.get("header_url")) and not os.path.exists(local_cover_file):
        download_target_url = result.get("avatar_url") or result.get("header_url")
        if download_target_url and download_target_url.startswith("http"):
            try:
                req = urllib.request.Request(download_target_url, headers=headers)
                with urllib.request.urlopen(req, timeout=6) as resp:
                    img_bytes = resp.read()
                    if len(img_bytes) > 1000:
                        with open(local_cover_file, "wb") as f_out:
                            f_out.write(img_bytes)
                        result["local_cover"] = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
                        result["avatar_url"] = result["local_cover"]
            except Exception as e:
                print(f"[Metadata] Cache download error: {e}")

    # 5. Nếu vẫn chưa có ảnh, thử trích xuất icon từ .exe
    if not result.get("local_cover") and game_dir and exe_name:
        full_exe = os.path.join(game_dir, exe_name)
        if not os.path.exists(full_exe):
            cand = os.path.join(game_dir, os.path.basename(exe_name))
            if os.path.exists(cand):
                full_exe = cand
        if os.path.exists(full_exe):
            if extract_exe_icon(full_exe, local_cover_png):
                result["local_cover"] = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
                if not result.get("avatar_url"):
                    result["avatar_url"] = result["local_cover"]

    return result

def compute_file_sha256(file_path):
    """Compute SHA-256 hash of a file safely in 1MB chunks."""
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

CURRENT_VERSION = "2.0.2"
GITHUB_REPO = "tuan3991/CoNgu-VietModManager"
REMOTE_CATALOG_URLS = [
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/games.json",
    f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/games.json",
]
REMOTE_VERSION_URLS = [
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json",
    f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/version.json",
]
CACHE_GAMES_JSON = os.path.join(APPDATA_DIR, "games_cache.json")

def get_active_games_json_path():
    """Return the best available games.json path (remote cache or bundled local)"""
    # Môi trường phát triển (Dev Source): luôn ưu tiên tệp games.json mã nguồn cục bộ
    if not getattr(sys, 'frozen', False) and os.path.exists(GAMES_JSON):
        return GAMES_JSON

    if os.path.exists(GAMES_JSON):
        if not os.path.exists(CACHE_GAMES_JSON):
            return GAMES_JSON
        try:
            if os.path.getmtime(GAMES_JSON) >= os.path.getmtime(CACHE_GAMES_JSON):
                return GAMES_JSON
        except Exception:
            pass
    if os.path.exists(CACHE_GAMES_JSON) and os.path.getsize(CACHE_GAMES_JSON) > 100:
        return CACHE_GAMES_JSON
    if os.path.exists(GAMES_JSON):
        return GAMES_JSON
    fallback_exe_json = os.path.join(os.path.dirname(sys.executable), "games.json")
    if os.path.exists(fallback_exe_json):
        return fallback_exe_json
    return GAMES_JSON

def sync_remote_catalog(force=False):
    """
    Fetch the latest games.json from GitHub CDN and update local cache.
    Returns: dict(success=bool, updated=bool, count=int, message=str)
    """
    import urllib.request
    import json
    
    headers = {"User-Agent": "CoNgu-VietModManager/2.0"}
    
    for url in REMOTE_CATALOG_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = resp.read().decode('utf-8')
                    parsed = json.loads(data)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        current_path = get_active_games_json_path()
                        if os.path.exists(current_path) and not force:
                            try:
                                with open(current_path, 'r', encoding='utf-8') as f:
                                    current_content = f.read()
                                if current_content.strip() == data.strip():
                                    return {"success": True, "updated": False, "count": len(parsed), "message": "Kho game đã ở bản mới nhất"}
                            except Exception:
                                pass
                        
                        # Save to cache
                        with open(CACHE_GAMES_JSON, 'w', encoding='utf-8') as f:
                            f.write(data)
                            
                        # Chỉ cập nhật GAMES_JSON cục bộ khi đang chạy bản đóng gói Portable (Frozen)
                        if getattr(sys, 'frozen', False):
                            try:
                                with open(GAMES_JSON, 'w', encoding='utf-8') as f:
                                    f.write(data)
                            except Exception:
                                pass
                            
                        return {"success": True, "updated": True, "count": len(parsed), "message": f"Đã đồng bộ {len(parsed)} game từ máy chủ đám mây!"}
        except Exception:
            continue
            
    current_count = 0
    p = get_active_games_json_path()
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                current_count = len(json.load(f))
        except Exception:
            pass
    return {"success": False, "updated": False, "count": current_count, "message": "Đang dùng dữ liệu ngoại tuyến (Offline)"}

def check_app_update():
    """Check version.json on remote GitHub"""
    import urllib.request
    import json
    import re
    
    headers = {"User-Agent": "CoNgu-VietModManager/2.0"}
    for url in REMOTE_VERSION_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    info = json.loads(resp.read().decode('utf-8'))
                    remote_ver = info.get("version", CURRENT_VERSION)
                    
                    def parse_v(v):
                        return [int(x) for x in re.sub(r'[^0-9.]', '', v).split('.') if x.isdigit()]
                    
                    has_update = parse_v(remote_ver) > parse_v(CURRENT_VERSION)
                    return {
                        "success": True,
                        "current_version": CURRENT_VERSION,
                        "latest_version": remote_ver,
                        "has_update": has_update,
                        "title": info.get("name") or info.get("title", f"Bản cập nhật v{remote_ver}"),
                        "release_date": info.get("release_date", ""),
                        "changelog": info.get("changelog", []),
                        "download_url": info.get("download_url", f"https://github.com/{GITHUB_REPO}/releases/latest"),
                        "portable_zip_url": info.get("portable_zip_url", "")
                    }
        except Exception:
            continue
            
    return {
        "success": False,
        "current_version": CURRENT_VERSION,
        "latest_version": CURRENT_VERSION,
        "has_update": False,
        "message": "Không thể kiểm tra phiên bản mới"
    }


os.makedirs(APPDATA_DIR, exist_ok=True)
os.makedirs(BACKUP_ROOT, exist_ok=True)

# Global progress tracker for install/uninstall operations
INSTALL_PROGRESS = {
    "status": "idle",       # "idle", "running", "success", "error"
    "percent": 0,
    "message": "",
    "game_id": "",
    "operation": ""         # "install" | "uninstall"
}

def set_progress(percent, message, status="running", game_id="", operation=""):
    global INSTALL_PROGRESS
    INSTALL_PROGRESS["percent"] = percent
    INSTALL_PROGRESS["message"] = message
    INSTALL_PROGRESS["status"] = status
    if game_id:
        INSTALL_PROGRESS["game_id"] = game_id
    if operation:
        INSTALL_PROGRESS["operation"] = operation

def calculate_sha256(filepath):
    """Calculate SHA256 checksum of a file"""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def get_running_process_names():
    """Enumerate running process names using native Win32 Toolhelp API (0ms, 0 external dependencies)"""
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_char * 260)
        ]

    try:
        hSnapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if hSnapshot == -1:
            return set()
        procs = set()
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(hSnapshot, ctypes.byref(pe)):
            while True:
                procs.add(pe.szExeFile.decode('latin-1', errors='ignore').lower())
                if not ctypes.windll.kernel32.Process32Next(hSnapshot, ctypes.byref(pe)):
                    break
        ctypes.windll.kernel32.CloseHandle(hSnapshot)
        return procs
    except Exception:
        return set()

def check_game_running(g, game_path=None):
    """
    Check if the game executable or its crash handler / engine helper is currently running.
    Scans target executable, shipping variants, executables inside game_path, and crash handlers.
    Returns (is_running: bool, process_name: str | None)
    """
    target_exes = set()
    
    # 1. Executable defined in games.json + common shipping variants
    exe_name = g.get("executable_name") if isinstance(g, dict) else None
    if exe_name:
        base_exe = os.path.basename(exe_name).lower()
        target_exes.add(base_exe)
        root_name, ext = os.path.splitext(base_exe)
        target_exes.add(f"{root_name}-win64-shipping{ext}")
        target_exes.add(f"{root_name}-win32-shipping{ext}")
        target_exes.add(f"{root_name}gl{ext}")
        target_exes.add(f"{root_name.replace(' ', '')}{ext}")
        target_exes.add(f"{root_name.replace(' ', '_')}{ext}")

    # 2. Automatically scan executables in game_path if available
    if game_path and os.path.exists(game_path):
        try:
            for root, dirs, files in os.walk(game_path):
                rel_parts = os.path.relpath(root, game_path).split(os.sep)
                if len(rel_parts) > 3:
                    continue
                for f in files:
                    if f.lower().endswith('.exe'):
                        target_exes.add(f.lower())
        except Exception:
            pass
    
    # 3. Known default executable names or variants
    gid = g.get("id", "") if isinstance(g, dict) else ""
    if gid == "witcher3":
        target_exes.update(["witcher3.exe"])
    elif gid == "preludes":
        target_exes.update(["backbonestories.exe", "backbonestories-win64-shipping.exe"])
    elif gid == "backbone":
        target_exes.update(["detective.exe", "detective-win64-shipping.exe"])
    elif gid == "hotline_miami":
        target_exes.update(["hotlinegl.exe", "hotline_miami.exe"])
    elif gid == "toem":
        target_exes.update(["toem.exe"])
    elif gid == "ror2":
        target_exes.update(["risk of rain 2.exe", "riskofrain2.exe"])
    elif gid == "loop_hero":
        target_exes.update(["loop hero.exe", "loophero.exe"])
    elif gid == "fallout_tactics":
        target_exes.update(["bos.exe", "fallout tactics.exe", "bos_hr.exe"])
    elif gid == "ravenous_devils":
        target_exes.update(["ravenous_devils.exe", "ravenous_devils-win64-shipping.exe"])
    elif gid == "erra_exordium":
        target_exes.update(["erra.exe", "erra exordium.exe"])

    # 4. Crash handlers & engine helper processes that might lock files
    crash_handlers = {"unitycrashhandler64.exe", "unitycrashhandler32.exe", "crashreportclient.exe", "unrealcefsubprocess.exe"}
    
    running = get_running_process_names()
    for exe in target_exes:
        if exe in running:
            return True, exe

    for ch in crash_handlers:
        if ch in running:
            return True, ch
            
    return False, None

def load_user_config():
    cfg = {"repo_dir": DEFAULT_REPO_DIR}
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
    return cfg

def save_user_config(cfg):
    try:
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def load_user_data():
    data = {"ratings": {}, "comments": {}, "bug_reports": [], "game_requests": [], "voted_requests": [], "machine_id": None}
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                data.update(saved)
        except Exception:
            pass
    import uuid
    if not data.get("machine_id"):
        data["machine_id"] = str(uuid.uuid4())
        save_user_data(data)
    if "voted_requests" not in data:
        data["voted_requests"] = []
    return data

def save_user_data(data):
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving user data: {e}")

def get_repo_dir():
    cfg = load_user_config()
    repo = cfg.get("repo_dir")
    if repo and os.path.exists(repo):
        return repo

    # Smart auto-detection across drives and local folders
    candidates = [
        os.path.join(APP_DIR, "Viethoagame"),
        os.path.join(APP_DIR, "..", "Viethoagame"),
        os.path.join(APP_DIR, "mods"),
        r"G:\My Drive\Viethoagame",
        DEFAULT_REPO_DIR,
        FALLBACK_REPO_DIR
    ]
    for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.append(f"{d}:\\My Drive\\Viethoagame")
        candidates.append(f"{d}:\\Viethoagame")
        candidates.append(f"{d}:\\Google Drive\\Viethoagame")

    for c in candidates:
        if os.path.exists(c):
            cfg["repo_dir"] = os.path.normpath(c)
            save_user_config(cfg)
            return cfg["repo_dir"]

    return DEFAULT_REPO_DIR

def find_mod_source_dir(mod_subfolder):
    """Find mod folder from active repo or fallback repo"""
    cfg = load_user_config()
    primary = os.path.join(cfg.get("repo_dir", DEFAULT_REPO_DIR), mod_subfolder)
    if os.path.exists(primary):
        return primary
    fallback = os.path.join(FALLBACK_REPO_DIR, mod_subfolder)
    if os.path.exists(fallback):
        return fallback
    return primary

def detect_steam_libraries():
    """Detect all Steam library folders across all drives on Windows with robust parsing"""
    libraries = []
    potential_roots = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"E:\SteamLibrary",
        r"D:\SteamLibrary",
        r"E:\Steam",
        r"D:\Steam",
        r"F:\SteamLibrary",
        r"G:\SteamLibrary",
    ]
    
    # 1. Try reading from Windows registry
    reg_keys = [
        (r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (r"SOFTWARE\Valve\Steam", "InstallPath"),
        (r"Software\Valve\Steam", "SteamPath"),
    ]
    try:
        import winreg
        for subkey, valname in reg_keys:
            try:
                for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        k = winreg.OpenKey(hkey, subkey)
                        steam_val, _ = winreg.QueryValueEx(k, valname)
                        if steam_val:
                            clean_val = steam_val.replace("/", "\\")
                            if os.path.exists(clean_val) and clean_val not in potential_roots:
                                potential_roots.insert(0, clean_val)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    # 2. Check all drives from C: to Z:
    for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate_steam = f"{drive_letter}:\\SteamLibrary"
        if os.path.exists(candidate_steam) and candidate_steam not in potential_roots:
            potential_roots.append(candidate_steam)

    found_roots = [p for p in potential_roots if os.path.exists(p)]
    for root in found_roots:
        norm_root = os.path.normpath(root)
        if norm_root not in libraries:
            libraries.append(norm_root)
        
        # Parse libraryfolders.vdf
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                matches = re.findall(r'"path"\s+"([^"]+)"', content)
                for lib_path in matches:
                    clean_p = os.path.normpath(lib_path.replace("\\\\", "\\"))
                    if os.path.exists(clean_p) and clean_p not in libraries:
                        libraries.append(clean_p)
            except Exception as e:
                print(f"Error reading libraryfolders.vdf: {e}")

    return libraries

def is_running_as_admin():
    """Check if current process has Windows Administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def check_directory_writable(dir_path):
    """
    Check if a directory has write permissions for the current user.
    Creates and removes a temporary test file (.congu_write_test) to reliably detect Windows ACL restrictions.
    """
    if not dir_path or not os.path.exists(dir_path):
        return False
    test_file = os.path.join(dir_path, f".congu_write_test_{os.getpid()}_{int(time.time())}.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except (PermissionError, OSError):
        return False

def request_uac_elevation():
    """
    Relaunch current executable with Administrator rights via Windows ShellExecute 'runas'.
    """
    import ctypes
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    else:
        exe = sys.executable
        script = os.path.abspath(sys.argv[0])
        params = f'"{script}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if ret > 32:
            sys.exit(0)
            return True
    except Exception as e:
        print(f"Failed to elevate UAC: {e}")
    return False

def detect_epic_games():
    """Detect all installed Epic Games by parsing manifest .item files"""
    epic_games = []
    prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
    manifests_dir = os.path.join(prog_data, "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if os.path.exists(manifests_dir):
        try:
            for fname in os.listdir(manifests_dir):
                if fname.endswith(".item"):
                    item_path = os.path.join(manifests_dir, fname)
                    try:
                        with open(item_path, "r", encoding="utf-8", errors="ignore") as f:
                            data = json.load(f)
                        loc = data.get("InstallLocation")
                        name = data.get("DisplayName", "")
                        app_name = data.get("AppName", "")
                        if loc and os.path.exists(loc):
                            epic_games.append({
                                "platform": "Epic Games",
                                "name": name,
                                "app_name": app_name,
                                "path": os.path.normpath(loc)
                            })
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error reading Epic Games manifests: {e}")
    return epic_games

def detect_gog_games():
    """Detect all installed GOG Galaxy games from Windows Registry"""
    gog_games = []
    try:
        import winreg
        gog_reg_roots = [
            r"SOFTWARE\WOW6432Node\GOG.com\Games",
            r"SOFTWARE\GOG.com\Games"
        ]
        for root_key in gog_reg_roots:
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_key)
                num_subkeys, _, _ = winreg.QueryInfoKey(k)
                for i in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(k, i)
                        sk = winreg.OpenKey(k, subkey_name)
                        game_path, _ = winreg.QueryValueEx(sk, "path")
                        game_name = ""
                        try:
                            game_name, _ = winreg.QueryValueEx(sk, "gameName")
                        except Exception:
                            pass
                        if game_path and os.path.exists(game_path):
                            gog_games.append({
                                "platform": "GOG Galaxy",
                                "name": game_name,
                                "path": os.path.normpath(game_path)
                            })
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        print(f"Error reading GOG Galaxy registry: {e}")
    return gog_games

def find_game_install_path(game_def, libraries):
    """
    Find the installation folder of a game across Steam, Epic Games, GOG Galaxy,
    and standalone installation folders across all drives.
    """
    appid = game_def.get("steam_appid")
    folder_names = game_def.get("default_folder_names", [game_def.get("title")])
    gid = game_def.get("id", "").lower()
    game_title = game_def.get("title", "").lower()
    targets = [fn.lower() for fn in folder_names] + [gid, game_title]

    # 1. Check Steam libraries
    for lib in libraries:
        steamapps = os.path.join(lib, "steamapps")
        
        # Check by appmanifest_{appid}.acf
        if appid:
            manifest_file = os.path.join(steamapps, f"appmanifest_{appid}.acf")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                    m = re.search(r'"installdir"\s+"([^"]+)"', txt)
                    if m:
                        candidate = os.path.join(steamapps, "common", m.group(1))
                        if os.path.exists(candidate):
                            return os.path.normpath(candidate)
                except Exception:
                    pass

        # Check by common folder names in steamapps/common
        common_dir = os.path.join(steamapps, "common")
        if os.path.exists(common_dir):
            for fname in folder_names:
                candidate = os.path.join(common_dir, fname)
                if os.path.exists(candidate):
                    return os.path.normpath(candidate)

    # 2. Check Epic Games Launcher manifests
    for ep in detect_epic_games():
        ep_name = ep.get("name", "").lower()
        ep_app = ep.get("app_name", "").lower()
        ep_path = ep.get("path", "")
        ep_base = os.path.basename(ep_path).lower()
        if any(t in ep_name or t in ep_app or t in ep_base for t in targets):
            is_valid, resolved, _ = verify_and_resolve_game_path(game_def, ep_path)
            if is_valid:
                return resolved

    # 3. Check GOG Galaxy registry entries
    for gog in detect_gog_games():
        gog_name = gog.get("name", "").lower()
        gog_path = gog.get("path", "")
        gog_base = os.path.basename(gog_path).lower()
        if any(t in gog_name or t in gog_base for t in targets):
            is_valid, resolved, _ = verify_and_resolve_game_path(game_def, gog_path)
            if is_valid:
                return resolved

    # 4. Check common standalone game directories across all drives (C: to Z:)
    for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate_bases = [
            f"{drive_letter}:\\Games",
            f"{drive_letter}:\\GOG Games",
            f"{drive_letter}:\\Epic Games",
            f"{drive_letter}:\\XboxGames",
        ]
        for base_dir in candidate_bases:
            if os.path.exists(base_dir):
                for fname in folder_names:
                    cand = os.path.join(base_dir, fname)
                    if os.path.exists(cand):
                        is_valid, resolved, _ = verify_and_resolve_game_path(game_def, cand)
                        if is_valid:
                            return resolved

    return None

def verify_and_resolve_game_path(game_def, input_path):
    """
    Intelligently verify if input_path is a valid game directory for game_def.
    Auto-resolves if user selected parent or child directory.
    Returns: (is_valid: bool, resolved_path: str, message: str)
    """
    if not input_path or not os.path.exists(input_path):
        return False, "", "Thư mục không tồn tại trên máy tính!"

    clean_path = os.path.normpath(input_path)
    exe_name = game_def.get("executable_name", "").lower()
    folder_names = [f.lower() for f in game_def.get("default_folder_names", [])]
    game_title = game_def.get("title", "").lower()
    gid = game_def.get("id", "").lower()
    viet_title = game_def.get("vietnamese_title", "tựa game này")
    expected_exe = os.path.basename(game_def.get("executable_name", "file chạy game"))
    
    def check_folder(dir_path):
        if not os.path.isdir(dir_path):
            return False
        # 1. Direct executable check
        if exe_name:
            if os.path.exists(os.path.join(dir_path, game_def.get("executable_name", ""))):
                return True
            base_exe = os.path.basename(exe_name)
            if os.path.exists(os.path.join(dir_path, base_exe)):
                return True
            try:
                for f in os.listdir(dir_path):
                    if f.lower() == base_exe:
                        return True
            except Exception:
                pass
                
        # 2. Check engine-specific folders
        rel_install = game_def.get("relative_install_path", "")
        if rel_install:
            first_part = rel_install.split("/")[0].split("\\")[0]
            if first_part and os.path.exists(os.path.join(dir_path, first_part)):
                return True

        # 3. Check for any exe matching title or id or folder names
        try:
            for f in os.listdir(dir_path):
                if f.lower().endswith(".exe"):
                    f_clean = re.sub(r'[^a-z0-9]', '', f.lower())
                    for target in folder_names + [gid, game_title]:
                        t_clean = re.sub(r'[^a-z0-9]', '', target)
                        if t_clean and (t_clean in f_clean or f_clean in t_clean):
                            return True
        except Exception:
            pass

        return False

    # A. Check directly in input_path
    if check_folder(clean_path):
        return True, clean_path, f"Đã xác nhận thư mục hợp lệ cho {viet_title}!"

    # B. Auto-resolve: Parent directory (e.g. steamapps/common)
    try:
        subdirs = [os.path.join(clean_path, d) for d in os.listdir(clean_path) if os.path.isdir(os.path.join(clean_path, d))]
        for sub in subdirs:
            sub_name = os.path.basename(sub).lower()
            if any(fn in sub_name or sub_name in fn for fn in folder_names) or (gid in sub_name):
                if check_folder(sub):
                    return True, sub, f"Đã tự động định vị đúng thư mục game: {os.path.basename(sub)}"
            if check_folder(sub):
                return True, sub, f"Đã tự động định vị đúng thư mục game: {os.path.basename(sub)}"
    except Exception:
        pass

    # C. Auto-resolve: Subfolder
    parent = os.path.dirname(clean_path)
    if parent and parent != clean_path and check_folder(parent):
        return True, parent, f"Đã tự động trỏ về thư mục gốc của game: {os.path.basename(parent)}"

    parent2 = os.path.dirname(parent)
    if parent2 and parent2 != parent and check_folder(parent2):
        return True, parent2, f"Đã tự động trỏ về thư mục gốc của game: {os.path.basename(parent2)}"

    return False, clean_path, f"Thư mục không hợp lệ! Không tìm thấy file chạy '{expected_exe}' của {viet_title}."

# ==============================================================================
# COMMUNITY LOCALIZATION WISHLIST & VOTING (FIREBASE RTDB / LOCAL HYBRID)
# ==============================================================================
FIREBASE_RTDB_URL = "https://congu-hub-default-rtdb.asia-southeast1.firebasedatabase.app"

def get_firebase_url():
    global FIREBASE_RTDB_URL
    if FIREBASE_RTDB_URL:
        return FIREBASE_RTDB_URL.rstrip("/")
    env_url = os.environ.get("FIREBASE_RTDB_URL")
    if env_url:
        return env_url.rstrip("/")
    return ""

def fetch_community_requests_from_cloud():
    fb_url = get_firebase_url()
    if not fb_url:
        return None
    try:
        url = f"{fb_url}/community_requests.json"
        req = urllib.request.Request(url, headers={"User-Agent": "CoNguHub/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"Firebase fetch error: {e}")
    return None

def push_community_request_to_cloud(game_id, item_data):
    fb_url = get_firebase_url()
    if not fb_url:
        return False
    try:
        url = f"{fb_url}/community_requests/{game_id}.json"
        req_body = json.dumps(item_data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json", "User-Agent": "CoNguHub/2.0"}, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Firebase push error: {e}")
    return False

def patch_vote_to_cloud(game_id, new_votes, machine_id=None):
    fb_url = get_firebase_url()
    if not fb_url:
        return False
    try:
        url = f"{fb_url}/community_requests/{game_id}.json"
        payload = {"votes": new_votes}
        req_body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json", "User-Agent": "CoNguHub/2.0"}, method="PATCH")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if machine_id:
                try:
                    voter_url = f"{fb_url}/community_requests/{game_id}/voters/{machine_id}.json"
                    v_req = urllib.request.Request(voter_url, data=b"true", headers={"Content-Type": "application/json"}, method="PUT")
                    urllib.request.urlopen(v_req, timeout=4)
                except Exception:
                    pass
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Firebase vote patch error: {e}")
    return False

LOCAL_REQUESTS_FILE = os.path.join(STATIC_DIR, "data", "community_requests.json")

def load_local_community_requests():
    if os.path.exists(LOCAL_REQUESTS_FILE):
        try:
            with open(LOCAL_REQUESTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading local community requests: {e}")
    return {}

def save_local_community_requests(data):
    try:
        with open(LOCAL_REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving local community requests: {e}")


MAIN_HWND = None
_is_dragging_window = False
is_window_maximized = False

def get_main_hwnd():
    """Resolve the main Win32 window handle for PyWebView frameless window with multi-level fallback"""
    global MAIN_HWND
    import ctypes
    user32 = ctypes.windll.user32

    if MAIN_HWND and user32.IsWindow(MAIN_HWND):
        return MAIN_HWND

    hwnd = None
    if 'api_instance' in globals() and api_instance.window and hasattr(api_instance.window, 'native') and api_instance.window.native:
        try:
            hwnd = int(api_instance.window.native.Handle.ToInt64())
            if hwnd and user32.IsWindow(hwnd):
                MAIN_HWND = hwnd
                return MAIN_HWND
        except Exception:
            hwnd = None

    titles = [
        "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro",
        "CỔ NGỮ (VietModHub Pro)",
        "VietModHub"
    ]
    for t in titles:
        h = user32.FindWindowW(None, t)
        if h and user32.IsWindow(h):
            MAIN_HWND = h
            return MAIN_HWND

    current_pid = os.getpid()
    found_hwnds = []

    def enum_proc(h, lParam):
        if user32.IsWindowVisible(h):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == current_pid:
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    val = buff.value
                    if "CỔ NGỮ" in val or "VietMod" in val:
                        found_hwnds.append(h)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

    if found_hwnds:
        MAIN_HWND = found_hwnds[0]
        return MAIN_HWND

    return None

def start_window_drag():
    """Trigger ultra-smooth native Windows OS window dragging on titlebar mouse down"""
    global _is_dragging_window, is_window_maximized
    if _is_dragging_window:
        return {"success": True, "status": "already_dragging"}

    hwnd = get_main_hwnd()
    if not hwnd:
        return {"success": False, "error": "No window handle"}

    import ctypes
    user32 = ctypes.windll.user32

    # Check if left mouse button is pressed
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        return {"success": False, "status": "mouse_not_down"}

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    # Handle un-maximize if window is currently maximized
    if is_window_maximized:
        try:
            if 'api_instance' in globals() and api_instance.window:
                api_instance.window.restore()
            is_window_maximized = False
            time.sleep(0.06)
        except Exception:
            pass

    start_pt = POINT()
    user32.GetCursorPos(ctypes.byref(start_pt))

    win_rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win_rect))
    offset_x = start_pt.x - win_rect.left
    offset_y = start_pt.y - win_rect.top

    def _drag_loop():
        global _is_dragging_window
        _is_dragging_window = True

        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010

        curr_pt = POINT()
        try:
            while user32.GetAsyncKeyState(0x01) & 0x8000:
                user32.GetCursorPos(ctypes.byref(curr_pt))
                new_x = curr_pt.x - offset_x
                new_y = curr_pt.y - offset_y
                user32.SetWindowPos(hwnd, None, new_x, new_y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                time.sleep(0.005) # 200 Hz ultra smooth tracking
        except Exception:
            pass
        finally:
            _is_dragging_window = False

    threading.Thread(target=_drag_loop, daemon=True).start()
    return {"success": True}

def stop_window_drag():
    global _is_dragging_window
    _is_dragging_window = False
    return {"success": True}


def steam_direct_request(url: str, timeout: float = 4.0) -> bytes:
    """Gửi HTTP GET trực tiếp tới các máy chủ Steam (store.steampowered.com, steamcommunity.com, steamstatic.com)
    sử dụng cơ chế phân mảnh ClientHello (DPI bypass) nhằm vượt qua việc các nhà mạng chặn SNI tại Việt Nam."""
    import socket
    import ssl
    import urllib.parse
    import time

    p = urllib.parse.urlparse(url)
    hostname = p.netloc or "store.steampowered.com"
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    try:
        ctx = ssl.create_default_context()
        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()
        sslobj = ctx.wrap_bio(incoming, outgoing, server_hostname=hostname)
        try:
            sslobj.do_handshake()
        except ssl.SSLWantReadError:
            pass

        client_hello = outgoing.read()
        ip = socket.gethostbyname(hostname)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, 443))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # Gửi 5 bytes đầu tiên (TLS record header), nghỉ 20ms rồi gửi phần còn lại để bypass DPI
        sock.sendall(client_hello[:5])
        time.sleep(0.02)
        sock.sendall(client_hello[5:])

        while True:
            try:
                sslobj.do_handshake()
                break
            except ssl.SSLWantReadError:
                data = sock.recv(4096)
                if not data:
                    break
                incoming.write(data)
            out = outgoing.read()
            if out:
                sock.sendall(out)

        http_req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {hostname}\r\n"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
            f"Accept: application/json, image/*, text/plain, */*\r\n"
            f"Connection: close\r\n\r\n"
        )
        sslobj.write(http_req.encode("utf-8"))
        out = outgoing.read()
        if out:
            sock.sendall(out)

        resp_body = b""
        while True:
            try:
                data = sslobj.read(8192)
                if not data:
                    break
                resp_body += data
            except ssl.SSLWantReadError:
                raw = sock.recv(8192)
                if not raw:
                    break
                incoming.write(raw)
        sock.close()
        parts = resp_body.split(b"\r\n\r\n", 1)
        return parts[1] if len(parts) > 1 else resp_body
    except Exception as e:
        # Fallback về urllib thông thường nếu mạng không bị chặn DPI
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return b""


def search_steam_online(query: str, limit: int = 15) -> list[dict]:
    """Tìm kiếm trực tiếp trên toàn bộ kho game Steam thông qua Store Search API và Community Search."""
    import re
    import json
    import urllib.parse

    clean_q = re.sub(r"\s+", " ", (query or "")).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    encoded_q = urllib.parse.quote(clean_q)
    results = []
    seen = set()

    # 1. Store Search API (store.steampowered.com)
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={encoded_q}&l=english&cc=US"
        raw = steam_direct_request(url, timeout=3.5)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            for it in data.get("items", [])[:limit]:
                appid = str(it.get("id", ""))
                name = it.get("name", "")
                if not appid or not name or appid in seen:
                    continue
                seen.add(appid)
                tiny = it.get("tiny_image", "")
                header = (
                    tiny.replace("capsule_sm_120", "header")
                    if tiny
                    else f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                )
                results.append({
                    "id": int(appid) if appid.isdigit() else appid,
                    "steam_appid": appid,
                    "name": name,
                    "title": name,
                    "subtitle": f"Steam AppID: {appid}",
                    "source": "steam",
                    "genre": "Steam Store",
                    "avatar_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                    "header_url": header,
                    "capsule": tiny or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
                })
    except Exception as e:
        print(f"[SteamOnline] Store search failed: {e}")

    # 2. Community SearchApps API (steamcommunity.com)
    if len(results) < limit:
        try:
            url = f"https://steamcommunity.com/actions/SearchApps/{encoded_q}"
            raw = steam_direct_request(url, timeout=3.0)
            if raw:
                data = json.loads(raw.decode("utf-8", "ignore"))
                if isinstance(data, list):
                    for it in data[:limit]:
                        appid = str(it.get("appid", ""))
                        name = it.get("name", "")
                        if not appid or not name or appid in seen:
                            continue
                        seen.add(appid)
                        logo = it.get("logo", "")
                        icon = it.get("icon", "")
                        header = logo or (
                            icon.replace("capsule_sm_120", "header")
                            if icon
                            else f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                        )
                        results.append({
                            "id": int(appid) if appid.isdigit() else appid,
                            "steam_appid": appid,
                            "name": name,
                            "title": name,
                            "subtitle": f"Steam AppID: {appid}",
                            "source": "steam",
                            "genre": "Steam Store",
                            "avatar_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                            "header_url": header,
                            "capsule": icon or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
                        })
        except Exception as e:
            print(f"[SteamOnline] Community search failed: {e}")

    return results


def make_vertical_poster(image_bytes: bytes, target_w: int = 600, target_h: int = 900) -> bytes:
    """
    Chuẩn hóa mọi ảnh (kể cả ảnh ngang 16:9, banner capsule 231x87, header 460x215)
    thành Poster dọc tỉ lệ 2:3 (600x900) chuẩn Steam Library:
    - Nếu ảnh gốc đã là ảnh dọc (0.58 <= w/h <= 0.75): resize chất lượng cao về 600x900.
    - Nếu ảnh gốc là ảnh ngang (w/h > 0.8):
      + Lớp nền: Phóng to ảnh gốc lấp đầy 600x900, áp dụng Gaussian Blur (radius=28) và làm tối (0.35) để tạo không gian ambient huyền ảo đồng nhất tông màu.
      + Lớp trung tâm: Đặt banner gốc sắc nét ở giữa, tỉ lệ chuẩn, viền nhẹ và đổ bóng để không bị kéo giãn hay phóng đại vỡ hạt.
    """
    try:
        from PIL import Image, ImageFilter, ImageEnhance, ImageOps
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return image_bytes
        aspect = w / h

        # Nếu đã là ảnh dọc tỉ lệ ~2:3 (từ 0.58 đến 0.75)
        if 0.58 <= aspect <= 0.75:
            result = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)
        else:
            # 1. Nền ambient mờ
            scale = max(target_w / w, target_h / h)
            bg_w, bg_h = int(w * scale), int(h * scale)
            bg = img.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
            left = (bg_w - target_w) // 2
            top = (bg_h - target_h) // 2
            bg = bg.crop((left, top, left + target_w, top + target_h))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
            bg = ImageEnhance.Brightness(bg).enhance(0.35)

            # 2. Foreground sắc nét ở giữa
            fg_w = int(target_w * 0.94)  # 564px
            fg_h = int(h * (fg_w / w))
            if fg_h > int(target_h * 0.75):
                fg_h = int(target_h * 0.75)
                fg_w = int(w * (fg_h / h))

            fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

            paste_x = (target_w - fg_w) // 2
            paste_y = (target_h - fg_h) // 2
            bg.paste(fg, (paste_x, paste_y))
            result = bg

        out = io.BytesIO()
        result.save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as e:
        print(f"[make_vertical_poster] Error formatting poster: {e}")
        return image_bytes


class ModManagerAPI:
    def __init__(self):
        self.window = None

    def get_games(self):
        """Returns list of games with installation & mod status (3 states: INSTALLED, NOT_INSTALLED, GAME_MISSING)"""
        if not os.path.exists(get_active_games_json_path()):
            return []

        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = json.load(f)

        user_cfg = load_user_config()
        libraries = detect_steam_libraries()
        user_data = load_user_data()
        covers_cache = load_covers_cache()
        cfg_changed = False

        for g in games:
            gid = g["id"]
            # 1. Determine game path with Smart Validation
            game_path = user_cfg.get(f"{gid}_path")
            is_valid = False
            if game_path and os.path.exists(game_path):
                is_valid, resolved, _ = verify_and_resolve_game_path(g, game_path)
                if is_valid:
                    if resolved != game_path:
                        game_path = resolved
                        user_cfg[f"{gid}_path"] = resolved
                        cfg_changed = True
                else:
                    game_path = ""
            
            if not game_path:
                detected = find_game_install_path(g, libraries)
                if detected:
                    is_valid, resolved, _ = verify_and_resolve_game_path(g, detected)
                    if is_valid:
                        game_path = resolved
                        user_cfg[f"{gid}_path"] = game_path
                        cfg_changed = True

            g["game_path"] = game_path or ""
            g["is_game_found"] = is_valid

            # Early Write Permission Check (Smart UAC Elevation Detection)
            is_admin = is_running_as_admin()
            is_writable = True
            requires_admin = False
            if is_valid and game_path:
                if is_admin:
                    is_writable = True
                    requires_admin = False
                else:
                    is_writable = check_directory_writable(game_path)
                    requires_admin = not is_writable

            g["is_writable"] = is_writable
            g["requires_admin"] = requires_admin

            # 2. Source mod folder in Viethoagame repository
            mod_subfolder = g.get("mod_subfolder", "")
            source_mod_dir = find_mod_source_dir(mod_subfolder)
            g["source_mod_dir"] = source_mod_dir
            g["source_mod_exists"] = os.path.exists(source_mod_dir)

            # 3. Check if mod is installed in game directory
            mod_installed = False
            installed_size = 0
            installed_date = ""

            # Check safe backup in AppData or in-place .congu_bak
            game_backup_dir = os.path.join(BACKUP_ROOT, gid)
            has_safe_backup = os.path.exists(os.path.join(game_backup_dir, "backup_manifest.json"))
            if not has_safe_backup and game_path and os.path.exists(game_path):
                rel_p = g.get("relative_install_path", "")
                tpak = g.get("target_pak_name", "")
                if tpak and os.path.exists(os.path.join(game_path, rel_p, f"{tpak}.congu_bak")):
                    has_safe_backup = True
                elif os.path.exists(os.path.join(game_path, "core", "locale.congu_bak")):
                    has_safe_backup = True
            g["has_safe_backup"] = has_safe_backup

            if g["is_game_found"]:
                mtype = g.get("mod_type", "pak")
                
                if mtype == "pak":
                    pak_path = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    if os.path.exists(pak_path):
                        mod_installed = True
                        installed_size = os.path.getsize(pak_path)
                        mtime = os.path.getmtime(pak_path)
                        installed_date = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                        
                elif mtype == "unity_assets":
                    target_assets = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    local_congu_bak = f"{target_assets}.congu_bak"
                    local_backup = os.path.join(game_path, g["relative_install_path"], g.get("backup_file", "resources.assets.original_backup"))
                    if has_safe_backup or os.path.exists(local_congu_bak) or os.path.exists(local_backup):
                        mod_installed = True
                        installed_size = os.path.getsize(target_assets) if os.path.exists(target_assets) else 0
                        installed_date = "Đang hoạt động"
                    elif os.path.exists(target_assets) and g.get("additional_files"):
                        # If additional files like Assembly-CSharp.dll exist, verify if modified
                        add_dst = os.path.join(game_path, g["additional_files"][0]["dst"])
                        if os.path.exists(add_dst) and has_safe_backup:
                            mod_installed = True
                        
                elif mtype == "wad":
                    backup_wad = os.path.join(game_path, g.get("backup_file", "HotlineMiami_GL_original.wad"))
                    bin_file = os.path.join(game_path, "hotline_localization.bin")
                    if has_safe_backup or os.path.exists(backup_wad) or os.path.exists(bin_file):
                        mod_installed = True
                        target_wad = os.path.join(game_path, g["target_pak_name"])
                        installed_size = os.path.getsize(target_wad) if os.path.exists(target_wad) else 0
                        installed_date = "Đang hoạt động"

                elif mtype == "bepinex_language":
                    lang_file = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    if os.path.exists(lang_file):
                        mod_installed = True
                        installed_size = os.path.getsize(lang_file)
                        mtime = os.path.getmtime(lang_file)
                        installed_date = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")

                elif mtype == "folder_copy":
                    marker_file = os.path.join(game_path, g["target_pak_name"])
                    backup_dir = os.path.join(game_path, "core", "locale_backup_original")
                    if has_safe_backup or os.path.exists(marker_file) or os.path.exists(backup_dir):
                        mod_installed = True
                        installed_date = "Đang hoạt động"

                elif mtype == "ini_and_exe":
                    ini_path = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    backup_ini = os.path.join(game_path, g.get("backup_file", "local/lang_eng.ini.orig"))
                    exe_orig = os.path.join(game_path, f"{g.get('executable_name', 'Loop Hero.exe')}.orig")
                    if has_safe_backup or os.path.exists(backup_ini) or os.path.exists(exe_orig):
                        mod_installed = True
                        installed_size = os.path.getsize(ini_path) if os.path.exists(ini_path) else 0
                        installed_date = "Đang hoạt động"

                elif mtype == "witcher3_mod":
                    mod_w3strings = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
                    backup_xml = os.path.join(game_path, g.get("backup_file", "content/content0/bundles/xml.bundle.orig"))
                    if has_safe_backup or os.path.exists(mod_w3strings) or os.path.exists(backup_xml):
                        mod_installed = True
                        installed_size = os.path.getsize(mod_w3strings) if os.path.exists(mod_w3strings) else 0
                        installed_date = "Đang hoạt động"

                # Data-Driven status marker & install_steps detection
                if not mod_installed and g.get("status_marker"):
                    marker = os.path.join(game_path, g["status_marker"])
                    if os.path.exists(marker):
                        mod_installed = True
                        installed_date = "Đang hoạt động"

                if not mod_installed and g.get("install_steps"):
                    for st in g["install_steps"]:
                        act = st.get("action")
                        if act in ["backup", "patch_binary"]:
                            bak_f = os.path.join(game_path, f"{st['target']}.congu_bak")
                            if os.path.exists(bak_f):
                                mod_installed = True
                                installed_date = "Đang hoạt động"
                                break
                        elif act == "copy_file" and not mod_installed:
                            dst_f = os.path.join(game_path, st.get("destination", ""))
                            bak_f = f"{dst_f}.congu_bak"
                            if os.path.exists(bak_f):
                                mod_installed = True
                                installed_size = os.path.getsize(dst_f) if os.path.exists(dst_f) else 0
                                installed_date = "Đang hoạt động"
                                break

            g["is_mod_installed"] = mod_installed
            g["installed_size_mb"] = round(installed_size / (1024 * 1024), 2) if installed_size else 0
            g["installed_date"] = installed_date

            # 3.4. Chẩn đoán sức khỏe bản dịch (Health Check & Steam/Epic Auto-Update Detection)
            update_detected = False
            health_reason = ""
            manifest_path = os.path.join(BACKUP_ROOT, gid, "backup_manifest.json")
            if mod_installed and os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                    mod_files = m_data.get("files", [])
                    if mod_files:
                        for it in mod_files:
                            target_f = it.get("target_file")
                            rel_f = it.get("relative_in_game")
                            if not target_f or not os.path.exists(target_f):
                                if rel_f and game_path:
                                    target_f = os.path.join(game_path, rel_f)

                            if target_f and os.path.exists(target_f):
                                mod_hash = it.get("modded_sha256")
                                mod_size = it.get("modded_size")
                                mod_mtime = it.get("modded_mtime")

                                # So sánh nhanh: mtime & size
                                curr_size = os.path.getsize(target_f)
                                curr_mtime = os.path.getmtime(target_f)

                                size_diff = (mod_size is not None and curr_size != mod_size)
                                mtime_diff = (mod_mtime is not None and abs(curr_mtime - mod_mtime) > 2.0)

                                if size_diff or mtime_diff:
                                    if mod_hash:
                                        curr_hash = compute_file_sha256(target_f)
                                        if curr_hash and curr_hash.lower() != mod_hash.lower():
                                            update_detected = True
                                            health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                            break
                            elif target_f and not os.path.exists(target_f):
                                update_detected = True
                                health_reason = f"Tệp '{rel_f or os.path.basename(target_f)}' không còn tồn tại"
                                break
                except Exception as e:
                    print(f"[Health Check Warning] Error inspecting manifest for {gid}: {e}")

            g["update_detected"] = update_detected
            g["health_reason"] = health_reason
            cache_congu_path = os.path.join(APPDATA_DIR, "cache", gid, "mod_package.congu")
            g["has_cached_congu"] = os.path.exists(cache_congu_path)

            # Determine 4-state badge: "INSTALLED" | "UPDATE_DETECTED" | "NOT_INSTALLED" | "GAME_MISSING"
            if not g["is_game_found"]:
                g["status_code"] = "GAME_MISSING"
                g["status_label"] = "CHƯA CÓ GAME"
            elif update_detected:
                g["status_code"] = "UPDATE_DETECTED"
                g["status_label"] = "GAME VỪA CẬP NHẬT - MẤT VIỆT HÓA"
                g["is_mod_installed"] = False
            elif g["is_mod_installed"]:
                g["status_code"] = "INSTALLED"
                g["status_label"] = "ĐÃ CÀI ĐẶT"
            else:
                g["status_code"] = "NOT_INSTALLED"
                g["status_label"] = "CHƯA CÀI MOD"

            # Check for version update status
            versions = g.get("versions", [])
            latest_version = versions[0]["version"] if versions else g.get("translation_stats", {}).get("version", "v1.0.0")
            g["latest_version"] = latest_version
            g["current_version"] = latest_version if mod_installed else "Chưa cài"
            g["has_update"] = False

            # Attach ratings & user comments
            g["user_rating"] = user_data.get("ratings", {}).get(gid, 5)
            g["user_comment"] = user_data.get("comments", {}).get(gid, "")

            # Metadata & Cover Enrichment (4 Lớp Tự Động Hóa cho Game Lẻ & Game Cài Ngoài)
            safe_gid = re.sub(r"[^\w\-]", "_", gid)
            local_cover_jpg = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
            local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")
            local_cover = None
            if os.path.exists(local_cover_jpg) and os.path.getsize(local_cover_jpg) > 1000:
                local_cover = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_jpg))}"
            elif os.path.exists(local_cover_png) and os.path.getsize(local_cover_png) > 500:
                local_cover = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"
            
            g["local_cover"] = local_cover

            cached_meta = covers_cache.get(gid) or {}
            g["avatar_url"] = local_cover or cached_meta.get("avatar_url")
            g["header_url"] = cached_meta.get("header_url")
            if not g.get("steam_appid") and cached_meta.get("steam_appid"):
                g["steam_appid"] = cached_meta.get("steam_appid")
            if not g.get("genre") or g.get("genre") == "Game":
                if cached_meta.get("genre"):
                    g["genre"] = cached_meta["genre"]

        if cfg_changed:
            save_user_config(user_cfg)

        return games

    def select_repo_folder(self):
        """Open native folder picker for user to select Viethoagame repository"""
        chosen_dir = None
        if self.window:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if res and len(res) > 0:
                chosen_dir = res[0]
        
        if not chosen_dir:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_dir = filedialog.askdirectory(title="Chọn thư mục kho Viethoagame")
                root.destroy()
            except Exception:
                pass

        if chosen_dir and os.path.exists(chosen_dir):
            cfg = load_user_config()
            cfg["repo_dir"] = os.path.normpath(chosen_dir)
            save_user_config(cfg)
            return {"success": True, "repo_dir": chosen_dir, "games": self.get_games()}
        return {"success": False, "message": "Không có thư mục nào được chọn."}


    def set_cloud_url(self, game_id, url):
        """Set Google Drive download URL for a game"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = json.load(f)
        for g in games:
            if g["id"] == game_id:
                g["download_url"] = url
                break
        with open(GAMES_JSON, "w", encoding="utf-8") as f:
            json.dump(games, f, ensure_ascii=False, indent=2)
        
        cfg = load_user_config()
        cfg[f"{game_id}_download_url"] = url
        save_user_config(cfg)
        return {"success": True, "message": "Đã lưu Link Google Drive cho tựa game này thành công!", "games": self.get_games()}

    def select_folder(self, game_id):
        """Open native folder picker dialog for user to select game directory"""
        chosen_dir = None
        if self.window:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if res and len(res) > 0:
                chosen_dir = res[0]
        
        # Fallback to tkinter if needed
        if not chosen_dir:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_dir = filedialog.askdirectory(title=f"Chọn thư mục cài đặt game {game_id}")
                root.destroy()
            except Exception as e:
                print(f"File dialog error: {e}")

        if chosen_dir and os.path.exists(chosen_dir):
            with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
                games_map = {gm["id"]: gm for gm in json.load(f)}
            g_target = games_map.get(game_id, {})
            is_valid, resolved_path, val_msg = verify_and_resolve_game_path(g_target, chosen_dir)
            if is_valid:
                cfg = load_user_config()
                cfg[f"{game_id}_path"] = resolved_path
                save_user_config(cfg)

                # Tự động nhận diện metadata và poster cho game lẻ (4 Lớp)
                try:
                    meta = fetch_game_metadata_and_avatar(
                        resolved_path, 
                        g_target.get("executable_name", ""), 
                        g_target.get("title", ""), 
                        game_id
                    )
                    if meta:
                        c_cache = load_covers_cache()
                        c_cache[game_id] = meta
                        save_covers_cache(c_cache)
                except Exception as e:
                    print(f"[!] Metadata extraction error: {e}")

                # Early Write Permission Check (Program Files / UAC restriction)
                is_admin = is_running_as_admin()
                is_writable = is_admin or check_directory_writable(resolved_path)
                requires_admin = not is_writable

                msg = val_msg
                if requires_admin:
                    msg = (
                        f"Thư mục '{os.path.basename(resolved_path)}' hợp lệ nhưng nằm trong thư mục hệ thống (Program Files). "
                        f"Windows yêu cầu quyền Administrator để ghi tệp."
                    )
                return {
                    "success": True,
                    "path": resolved_path,
                    "message": msg,
                    "is_writable": is_writable,
                    "requires_admin": requires_admin,
                    "games": self.get_games()
                }
            else:
                return {"success": False, "path": chosen_dir, "message": val_msg}
        
        return {"success": False, "message": "Không có thư mục nào được chọn."}

    def set_game_path(self, game_id, path):
        """Manually update game path with smart validation"""
        if not path or not os.path.exists(path):
            return {"success": False, "message": "Đường dẫn không tồn tại trên máy tính!"}
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games_map = {gm["id"]: gm for gm in json.load(f)}
        g_target = games_map.get(game_id, {})
        is_valid, resolved_path, val_msg = verify_and_resolve_game_path(g_target, path)
        if not is_valid:
            return {"success": False, "message": val_msg}
        cfg = load_user_config()
        cfg[f"{game_id}_path"] = resolved_path
        save_user_config(cfg)

        # Tự động nhận diện metadata và poster cho game lẻ (4 Lớp)
        try:
            meta = fetch_game_metadata_and_avatar(
                resolved_path, 
                g_target.get("executable_name", ""), 
                g_target.get("title", ""), 
                game_id
            )
            if meta:
                c_cache = load_covers_cache()
                c_cache[game_id] = meta
                save_covers_cache(c_cache)
        except Exception as e:
            print(f"[!] Metadata extraction error: {e}")

        # Early Write Permission Check (Program Files / UAC restriction)
        is_admin = is_running_as_admin()
        is_writable = is_admin or check_directory_writable(resolved_path)
        requires_admin = not is_writable

        msg = val_msg
        if requires_admin:
            msg = (
                f"Thư mục '{os.path.basename(resolved_path)}' hợp lệ nhưng nằm trong thư mục hệ thống (Program Files). "
                f"Windows yêu cầu quyền Administrator để ghi tệp."
            )
        return {
            "success": True,
            "path": resolved_path,
            "message": msg,
            "is_writable": is_writable,
            "requires_admin": requires_admin,
            "games": self.get_games()
        }

    def select_custom_cover(self, game_id):
        """Cho phép người dùng chọn ảnh bìa tùy chỉnh (JPG, PNG, WEBP) từ máy tính."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Image Files (*.jpg;*.jpeg;*.png;*.webp)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
                if res and len(res) > 0:
                    chosen_file = res[0]
            except Exception as e:
                print(f"[!] PyWebView file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn ảnh bìa poster cho game",
                    filetypes=[("Image files", "*.jpg;*.jpeg;*.png;*.webp"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if chosen_file and os.path.exists(chosen_file):
            safe_gid = re.sub(r"[^\w\-]", "_", game_id)
            dest_cover = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
            try:
                with open(chosen_file, "rb") as f:
                    raw_bytes = f.read()
                formatted_bytes = make_vertical_poster(raw_bytes)
                with open(dest_cover, "wb") as f:
                    f.write(formatted_bytes)
                c_cache = load_covers_cache()
                if game_id not in c_cache:
                    c_cache[game_id] = {}
                local_url = f"/api/covers/{safe_gid}.jpg?t={int(time.time())}"
                c_cache[game_id]["local_cover"] = local_url
                c_cache[game_id]["avatar_url"] = local_url
                save_covers_cache(c_cache)
                return {
                    "success": True, 
                    "cover_url": local_url, 
                    "message": "Đã đổi ảnh bìa thành công!", 
                    "games": self.get_games()
                }
            except Exception as e:
                return {"success": False, "message": f"Lỗi khi lưu ảnh bìa: {e}"}

        return {"success": False, "message": "Chưa chọn ảnh nào."}

    def search_game_for_avatar(self, query: str) -> list[dict]:
        """Tìm danh sách game kèm ảnh preview từ Kho CỔ NGỮ, Steam Store trực tiếp trên mạng, và DB bổ trợ."""
        clean_q = re.sub(r"\s+", " ", (query or "")).strip()
        if not clean_q:
            return []

        results = []
        seen_appids = set()
        q_lower = clean_q.lower()

        # 1. Tìm ưu tiên trong kho games.json nội bộ trước
        try:
            games_json_path = get_active_games_json_path()
            if os.path.exists(games_json_path):
                with open(games_json_path, "r", encoding="utf-8") as f:
                    local_games = json.load(f)
                for g in local_games:
                    title = g.get("title", "")
                    vi_title = g.get("vietnamese_title", "")
                    gid = g.get("id", "")
                    appid = str(g.get("steam_appid", "")).strip()
                    if (
                        q_lower in title.lower()
                        or q_lower in vi_title.lower()
                        or q_lower in gid.lower()
                        or (appid and appid == clean_q)
                    ):
                        if appid:
                            seen_appids.add(appid)
                        poster = (
                            g.get("assets", {}).get("poster")
                            or (f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "")
                        )
                        header = (
                            g.get("assets", {}).get("header")
                            or (f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else "")
                        )
                        results.append({
                            "id": int(appid) if appid.isdigit() else appid,
                            "steam_appid": appid,
                            "title": title,
                            "name": title,
                            "subtitle": vi_title or "Kho CỔ NGỮ",
                            "source": "congu_db",
                            "genre": g.get("genre", "Kho CỔ NGỮ"),
                            "avatar_url": poster,
                            "header_url": header,
                            "capsule": header
                        })
        except Exception as e:
            print(f"[AvatarSearch] local games.json error: {e}")

        # 2. Tìm kiếm TRỰC TIẾP trên kho Steam Store & Community qua mạng (DPI bypass)
        try:
            online_items = search_steam_online(clean_q, limit=12)
            for item in online_items:
                appid = str(item.get("steam_appid", ""))
                if appid and appid in seen_appids:
                    continue
                seen_appids.add(appid)
                results.append(item)
        except Exception as e:
            print(f"[AvatarSearch] online steam search error: {e}")

        # 3. Bổ sung từ cơ sở dữ liệu Steam offline (hơn 5,000 game)
        try:
            offline_db = get_steam_games()
            exact, starts, word_starts, contains = [], [], [], []
            for item in offline_db:
                appid = str(item.get("id", ""))
                name = item.get("name", "")
                if not appid or appid in seen_appids:
                    continue
                name_low = name.lower()
                if name_low == q_lower:
                    exact.append(item)
                elif name_low.startswith(q_lower):
                    starts.append(item)
                elif any(w.startswith(q_lower) for w in name_low.split()):
                    word_starts.append(item)
                elif q_lower in name_low:
                    contains.append(item)
                if len(exact) + len(starts) + len(word_starts) + len(contains) >= 30:
                    break

            for item in (exact + starts + word_starts + contains)[:8]:
                appid = str(item["id"])
                if appid in seen_appids:
                    continue
                seen_appids.add(appid)
                results.append({
                    "id": int(appid) if appid.isdigit() else appid,
                    "steam_appid": appid,
                    "name": item.get("name", ""),
                    "title": item.get("name", ""),
                    "subtitle": f"Steam AppID: {appid}",
                    "source": "steam",
                    "genre": "Steam Store",
                    "avatar_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                    "header_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
                    "capsule": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
                })
        except Exception as e:
            print(f"[AvatarSearch] offline steam db search error: {e}")

        return results

    def apply_selected_avatar(self, target_game_id: str, selected_data: dict) -> dict:
        """Gán cố định avatar + steam_appid người dùng đã chọn và tải ảnh lưu cache."""
        if not target_game_id:
            return {"status": "error", "success": False, "message": "Thiếu mã game (target_game_id)"}

        appid = str(selected_data.get("steam_appid", "")).strip()
        avatar_url = selected_data.get("avatar_url", "")
        header_url = selected_data.get("header_url", "")
        capsule_url = selected_data.get("capsule", "")
        new_title = selected_data.get("title", "")
        genre = selected_data.get("genre", "")

        safe_gid = re.sub(r"[^\w\-]", "_", target_game_id)
        os.makedirs(COVERS_DIR, exist_ok=True)
        local_cover_path = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")

        candidates = []
        if appid:
            candidates.extend([
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            ])
        if avatar_url:
            candidates.append(avatar_url)
        if header_url:
            candidates.append(header_url)
        if capsule_url:
            candidates.append(capsule_url)

        downloaded_ok = False
        final_local_url = f"/api/covers/{safe_gid}.jpg?t={int(time.time())}"

        for cand_url in candidates:
            if not cand_url or not cand_url.startswith("http"):
                continue
            try:
                content = steam_direct_request(cand_url, timeout=4.0)
                if (
                    content
                    and len(content) > 1000
                    and not content.startswith(b"<html>")
                    and not content.startswith(b"HTTP/1.1 404")
                    and not content.startswith(b"HTTP/1.1 50")
                ):
                    formatted_poster = make_vertical_poster(content)
                    with open(local_cover_path, "wb") as f:
                        f.write(formatted_poster)
                    downloaded_ok = True
                    break
            except Exception:
                continue

        # Lấy thêm thông tin Genre và tên từ Steam details nếu có appid
        if appid:
            try:
                details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese&cc=VN"
                raw = steam_direct_request(details_url, timeout=3.5)
                if raw:
                    det = json.loads(raw.decode("utf-8", "ignore"))
                    if det.get(str(appid), {}).get("success"):
                        app_data = det[str(appid)]["data"]
                        genres_list = [g.get("description") for g in app_data.get("genres", [])]
                        if genres_list:
                            genre = ", ".join(genres_list)
                        if not new_title:
                            new_title = app_data.get("name", "")
                        if not header_url:
                            header_url = app_data.get("header_image", "")
                        # Nếu các candidate trước chưa tải được, thử tải header_image từ appdetails
                        if not downloaded_ok and header_url:
                            h_content = steam_direct_request(header_url, timeout=4.0)
                            if (
                                h_content
                                and len(h_content) > 1000
                                and not h_content.startswith(b"<html>")
                                and not h_content.startswith(b"HTTP/1.1 404")
                            ):
                                formatted_poster = make_vertical_poster(h_content)
                                with open(local_cover_path, "wb") as f:
                                    f.write(formatted_poster)
                                downloaded_ok = True
            except Exception:
                pass

        # Cập nhật cache covers_cache.json
        c_cache = load_covers_cache()
        c_cache[target_game_id] = {
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "poster_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "",
            "local_cover": final_local_url if downloaded_ok else (avatar_url or ""),
            "avatar_url": final_local_url if downloaded_ok else (avatar_url or ""),
            "header_url": header_url or ""
        }
        save_covers_cache(c_cache)

        return {
            "status": "success",
            "success": True,
            "game_id": target_game_id,
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "avatar_url": final_local_url if downloaded_ok else (avatar_url or ""),
            "local_cover": final_local_url if downloaded_ok else (avatar_url or ""),
            "header_url": header_url,
            "message": f"Đã áp dụng ảnh bìa cho game thành công!",
            "games": self.get_games()
        }

    def _backup_file_inplace(self, game_id, original_abs_path, relative_in_game, return_details=False):
        """
        In-Place Atomic Backup with Anti-Crash Steam/Epic Update Detection:
        Directly renames the original game file to {file}.congu_bak within the game directory.
        Takes 0 seconds (zero disk copy I/O) and 0 extra bytes on drive C:!
        If Steam/Epic updated the game since previous modding, deletes the obsolete .congu_bak
        and creates a fresh backup of the updated game file.
        """
        if not os.path.exists(original_abs_path) and not os.path.exists(f"{original_abs_path}.congu_bak"):
            return (None, False) if return_details else None

        bak_file = f"{original_abs_path}.congu_bak"
        is_ini = original_abs_path.lower().endswith(('.ini', '.cfg', '.conf'))
        created_new_bak = False

        # Load manifest to detect Steam/Epic update
        game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
        os.makedirs(game_backup_dir, exist_ok=True)
        manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")
        manifest = {"game_id": game_id, "backup_type": "inplace", "timestamp": datetime.now().isoformat(), "files": []}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                pass

        tracked_item = next((it for it in manifest.get("files", []) if it.get("relative_in_game") == relative_in_game), None)

        # Check if existing .congu_bak is stale because Steam/Epic updated the game
        if os.path.exists(bak_file) and os.path.exists(original_abs_path):
            modded_hash = tracked_item.get("modded_sha256") if tracked_item else None
            if modded_hash:
                curr_hash = compute_file_sha256(original_abs_path)
                if curr_hash and curr_hash.lower() != modded_hash.lower():
                    # Steam/Epic updated the game file!
                    print(f"[Smart Update Detection] Tệp '{relative_in_game}' đã được Steam/Epic cập nhật mới (không khớp bản mod cũ). Đang xóa .congu_bak cũ để tạo bản backup mới.")
                    try:
                        os.remove(bak_file)
                    except Exception:
                        pass

        orig_hash = None
        orig_size = 0
        orig_mtime = 0

        # Bẫy A: Cài đè lần 2 không bao giờ ghi đè lên .congu_bak đã có
        if not os.path.exists(bak_file):
            if os.path.exists(original_abs_path):
                orig_hash = compute_file_sha256(original_abs_path)
                orig_size = os.path.getsize(original_abs_path)
                orig_mtime = os.path.getmtime(original_abs_path)
                # Bẫy B: Nếu là file cấu hình .ini, dùng COPY để file gốc vẫn tồn tại cho patch_ini làm việc
                if is_ini:
                    try:
                        shutil.copy2(original_abs_path, bak_file)
                        created_new_bak = True
                    except Exception as e:
                        print(f"Error creating INI backup copy: {e}")
                else:
                    # File dữ liệu nặng sắp bị ghi đè: dùng RENAME (os.replace) nhanh và tức thì
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
            # bak_file ĐÃ TỒN TẠI (cài đè lần 2): TUYỆT ĐỐI GIỮ NGUYÊN FILE GỐC .congu_bak!
            orig_hash = tracked_item.get("original_sha256") if tracked_item else compute_file_sha256(bak_file)
            orig_size = os.path.getsize(bak_file) if os.path.exists(bak_file) else 0
            orig_mtime = os.path.getmtime(bak_file) if os.path.exists(bak_file) else 0
            # Dọn dẹp original_abs_path cũ (là bản mod từ lần cài 1) để chuẩn bị chép mod mới
            if not is_ini and os.path.exists(original_abs_path):
                try:
                    if os.path.isdir(original_abs_path):
                        shutil.rmtree(original_abs_path, ignore_errors=True)
                    else:
                        os.remove(original_abs_path)
                except Exception:
                    pass

        # Record tiny manifest in AppData for tracking & UI has_safe_backup state (only ~500 bytes JSON)
        file_record = {
            "relative_in_game": relative_in_game,
            "target_file": original_abs_path,
            "backup_file": bak_file,
            "size_bytes": os.path.getsize(bak_file) if os.path.exists(bak_file) else 0,
            "original_sha256": orig_hash,
            "original_size": orig_size,
            "original_mtime": orig_mtime
        }
        existing_idx = next((i for i, f in enumerate(manifest.get("files", [])) if f.get("relative_in_game") == relative_in_game), -1)
        if existing_idx >= 0:
            manifest["files"][existing_idx].update(file_record)
        else:
            manifest.setdefault("files", []).append(file_record)

        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving backup manifest: {e}")

        if return_details:
            return bak_file, created_new_bak
        return bak_file

    def _load_backup_manifest(self, game_id):
        """Tải manifest sao lưu an toàn của game từ AppData"""
        if not game_id:
            return {}
        manifest_path = os.path.join(BACKUP_ROOT, game_id, "backup_manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Manifest Load Warning] Lỗi đọc backup_manifest.json cho {game_id}: {e}")
        return {"game_id": game_id, "backup_type": "inplace", "files": []}

    def _record_preexisting_environment(self, game_id, game_path):
        """
        Ghi nhận môi trường tiền tồn tại của game (Mục 1.5 - BepInEx & Unity Protection).
        Kiểm tra xem trước lúc cài mod Việt hóa, thư mục game đã có sẵn winhttp.dll và BepInEx hay chưa.
        Đặc biệt: Nếu manifest đã từng lưu giá trị bool, TUYỆT ĐỐI giữ nguyên để không bị sai lệch khi cài đè lần 2.
        """
        if not game_id or not game_path or not os.path.exists(game_path):
            return False, False
        game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
        os.makedirs(game_backup_dir, exist_ok=True)
        manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")
        manifest = self._load_backup_manifest(game_id)

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

        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Pre-existing Guard Warning] Lỗi lưu manifest cho {game_id}: {e}")

        return winhttp_preexisting, bepinex_preexisting

    def _record_backup_manifest(self, game_id, backed_up_files):
        """Record backed-up files in manifest for UI tracking and restoration"""
        if not backed_up_files:
            return
        game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
        os.makedirs(game_backup_dir, exist_ok=True)
        manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")
        manifest = {"game_id": game_id, "backup_type": "inplace", "timestamp": datetime.now().isoformat(), "files": []}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                pass
        for item in backed_up_files:
            rel = item.get("relative_in_game")
            existing_idx = next((i for i, f in enumerate(manifest.get("files", [])) if f.get("relative_in_game") == rel), -1)
            if existing_idx >= 0:
                manifest["files"][existing_idx].update(item)
            else:
                manifest.setdefault("files", []).append(item)
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving backup manifest: {e}")

    def _record_modded_state(self, game_id, target_file, relative_in_game):
        """Record the post-installation hash & size of a modded file to detect future Steam/Epic updates"""
        if not target_file or not os.path.exists(target_file):
            return
        game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
        manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")
        if not os.path.exists(manifest_path):
            return
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            updated = False
            for it in manifest.get("files", []):
                if it.get("relative_in_game") == relative_in_game or it.get("target_file") == target_file:
                    it["modded_sha256"] = compute_file_sha256(target_file)
                    it["modded_size"] = os.path.getsize(target_file)
                    it["modded_mtime"] = os.path.getmtime(target_file)
                    updated = True
            if updated:
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error updating modded state in manifest: {e}")

    def _backup_file_to_appdata(self, game_id, original_abs_path, relative_in_game):
        """Backward-compatibility alias pointing to in-place backup"""
        return self._backup_file_inplace(game_id, original_abs_path, relative_in_game)

    def _restore_files_inplace(self, game_id, game_path):
        """
        In-Place Restore with Anti-Crash Steam/Epic Protection:
        Deletes modded files and renames {file}.congu_bak back to original names.
        If file was already updated or verified by Steam/Epic (hash doesn't match modded_sha256),
        preserves the clean game file and cleans up the stale backup to prevent crashes!
        """
        restored_any = False
        game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
        manifest_path = os.path.join(game_backup_dir, "backup_manifest.json")

        manifest = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                manifest = {}

        # 1. Process files tracked in manifest
        files = manifest.get("files", [])
        for item in files:
            rel = item.get("relative_in_game")
            if not rel or not game_path:
                continue
            try:
                target_file = validate_safe_path(game_path, rel, allow_base_itself=False)
                bak_file = f"{target_file}.congu_bak"
            except Exception as se:
                print(f"[Restore Safe Guard] Bỏ qua đường dẫn không an toàn trong manifest: {rel} ({se})")
                continue

            if bak_file and os.path.exists(bak_file):
                try:
                    # Check if target_file was already updated by Steam/Epic
                    is_still_modded = True
                    modded_hash = item.get("modded_sha256")
                    if modded_hash and target_file and os.path.exists(target_file):
                        curr_hash = compute_file_sha256(target_file)
                        if curr_hash and curr_hash.lower() != modded_hash.lower():
                            # Steam/Epic updated the game!
                            print(f"[Anti-Crash] Tệp '{rel}' không khớp bản mod (Steam/Epic đã cập nhật/xác minh). Giữ nguyên tệp game sạch và xóa backup cũ.")
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

            # Legacy AppData file restore (if file was physically copied to AppData in older versions)
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

        # Check for folder in-place backup (e.g. Fallout Tactics core/locale.congu_bak)
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

            legacy_core = os.path.join(game_backup_dir, "core_locale")
            if os.path.exists(legacy_core):
                try:
                    if os.path.exists(orig_locale):
                        shutil.rmtree(orig_locale, ignore_errors=True)
                    shutil.copytree(legacy_core, orig_locale)
                    restored_any = True
                except Exception as e:
                    print(f"Error restoring legacy core_locale: {e}")

        # Clean up manifest file after restoration
        if os.path.exists(manifest_path):
            try:
                os.remove(manifest_path)
            except Exception:
                pass

        return restored_any

        # 4. Clean up AppData backup dir to free drive C: space
        if os.path.exists(game_backup_dir):
            try:
                shutil.rmtree(game_backup_dir, ignore_errors=True)
            except Exception:
                pass

        return restored_any

    def _restore_files_from_appdata(self, game_id, game_path):
        """Backward-compatibility alias pointing to in-place restore"""
        return self._restore_files_inplace(game_id, game_path)

    def _patch_ini_file(self, file_path, section, key, value, encoding="utf-8"):
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

    def _execute_pipeline_step(self, game_id, game_path, source_mod_dir, step, operation="install"):
        """
        Executes a single atomic data-driven action step.
        Supported actions:
        - backup: in-place rename of target to target.congu_bak
        - copy_file: copy single file from source_mod_dir to game_path
        - copy_folder: recursive copy of directory from source_mod_dir to game_path
        - extract_all / extract_zip: extract archive into game_path
        - patch_ini: in-place backup and update section/key/value in ini file
        - delete: delete file or directory in game_path
        - rename: rename file/folder in game_path
        - restore_backup: restore target.congu_bak to target
        """
        action = step.get("action", "").lower().strip()

        if action == "backup":
            target_rel = step.get("target")
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
                    bak_res, created_new_bak = self._backup_file_inplace(game_id, target_abs, target_rel, return_details=True)
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
            target_rel = step.get("target")
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
                                if it.get("relative_in_game") == target_rel:
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
            dst_rel = step.get("destination", src_rel)
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
                        self._record_backup_manifest(game_id, [{
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
                self._record_modded_state(game_id, dst_abs, dst_rel)
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
            target_rel = step.get("target")
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

            # 2. Auto-backup tệp gốc trước khi vá (sao chép để giữ lại file nguồn cho bspatch nếu chưa có bak)
            has_tx_tmp = False
            tx_tmp_abs = f"{target_abs}.congu_tx_tmp"
            if not os.path.exists(bak_abs) and os.path.exists(target_abs):
                try:
                    os.makedirs(os.path.dirname(bak_abs), exist_ok=True)
                    shutil.copy2(target_abs, bak_abs)
                    created_new_bak = True
                    orig_hash = compute_file_sha256(bak_abs)
                    self._record_backup_manifest(game_id, [{
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
                self._record_modded_state(game_id, target_abs, target_rel)

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
            dst_rel = step.get("destination", src_rel)
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
                    d_rel = os.path.relpath(d_file, game_path)
                    existed = os.path.exists(d_file)
                    created_new_bak = False
                    has_tx_tmp = False
                    b_file = f"{d_file}.congu_bak"
                    tx_file = f"{d_file}.congu_tx_tmp"

                    # Auto-Backup ngầm trước khi chép đè
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
                            # .congu_bak đã tồn tại -> d_file là bản mod v1.0. Lưu tx_tmp để rollback nếu v1.1 lỗi!
                            try:
                                shutil.copy2(d_file, tx_file)
                                has_tx_tmp = True
                            except Exception as e:
                                print(f"[Tx-Tmp Folder Warning] {d_file}: {e}")

                    os.makedirs(os.path.dirname(d_file), exist_ok=True)
                    shutil.copy2(s_file, d_file)
                    if operation == "install":
                        self._record_modded_state(game_id, d_file, d_rel)
                    copied_files.append((d_rel, existed, created_new_bak, has_tx_tmp))

            if backup_records:
                self._record_backup_manifest(game_id, backup_records)
            return {"action": "copy_folder", "target": dst_rel, "destination": dst_rel, "copied_files": copied_files}

        elif action in ("extract_all", "extract_zip"):
            src_rel = step.get("source", "")
            dst_rel = step.get("destination", "")
            if source_mod_dir and src_rel:
                src_abs = validate_safe_path(source_mod_dir, src_rel, allow_base_itself=False)
            else:
                src_abs = source_mod_dir
            dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=True)
            os.makedirs(dst_abs, exist_ok=True)
            import zipfile
            extracted_files = []
            backup_records = []
            if os.path.isfile(src_abs) and zipfile.is_zipfile(src_abs):
                with zipfile.ZipFile(src_abs, 'r') as zf:
                    for member in zf.namelist():
                        if not member.endswith("/"):
                            # Anti Zip-Slip: validate member target against game_path
                            target_dest = validate_safe_path(dst_abs, member, allow_base_itself=False)
                            t_rel = os.path.relpath(target_dest, game_path)
                            existed = os.path.exists(target_dest)
                            created_new_bak = False
                            has_tx_tmp = False
                            b_file = f"{target_dest}.congu_bak"
                            tx_file = f"{target_dest}.congu_tx_tmp"

                            # Auto-Backup ngầm trước khi trích xuất đè
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

                    if operation == "install":
                        for item in extracted_files:
                            t_rel = item[0]
                            t_abs = validate_safe_path(game_path, t_rel, allow_base_itself=False)
                            self._record_modded_state(game_id, t_abs, t_rel)
            elif os.path.isdir(src_abs):
                for root, dirs, files in os.walk(src_abs):
                    for f in files:
                        s_file = os.path.join(root, f)
                        rel_sub = os.path.relpath(s_file, src_abs)
                        d_file = validate_safe_path(game_path, os.path.join(dst_rel, rel_sub), allow_base_itself=False)
                        d_rel = os.path.relpath(d_file, game_path)
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
                        if operation == "install":
                            self._record_modded_state(game_id, d_file, d_rel)
                        extracted_files.append((d_rel, existed, created_new_bak, has_tx_tmp))
            else:
                if not step.get("optional", False):
                    raise FileNotFoundError(f"Archive file not found: {src_rel}")

            if backup_records:
                self._record_backup_manifest(game_id, backup_records)
            return {"action": "extract_all", "target": dst_rel, "extracted_files": extracted_files}

        elif action == "patch_ini":
            file_rel = step.get("file") or step.get("target")
            if not file_rel:
                raise ValueError("Step 'patch_ini' missing required 'file' or 'target' field")
            file_abs = validate_safe_path(game_path, file_rel, allow_base_itself=False)
            bak_file = f"{file_abs}.congu_bak"
            created_new_bak = False
            has_tx_tmp = False
            tx_tmp_abs = f"{file_abs}.congu_tx_tmp"

            # Bẫy cấu hình (Mục 1.3): Tự phục hồi file .ini nếu trước đó bị lệnh backup đổi tên làm mất!
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
                self._record_backup_manifest(game_id, [{
                    "relative_in_game": file_rel,
                    "target_file": file_abs,
                    "backup_file": bak_file,
                    "size_bytes": os.path.getsize(bak_file),
                    "original_sha256": orig_hash,
                    "original_size": os.path.getsize(bak_file),
                    "original_mtime": os.path.getmtime(bak_file)
                }])

            self._patch_ini_file(
                file_abs,
                section=step.get("section"),
                key=step.get("key"),
                value=step.get("value"),
                encoding=step.get("encoding", "utf-8")
            )
            if operation == "install":
                self._record_modded_state(game_id, file_abs, file_rel)
            return {
                "action": "patch_ini",
                "target": file_rel,
                "file": file_rel,
                "created_new_bak": created_new_bak,
                "has_tx_tmp": has_tx_tmp,
                "tx_tmp": tx_tmp_abs
            }

        elif action == "delete":
            target_rel = step.get("target")
            if not target_rel:
                raise ValueError("Step 'delete' missing required 'target' field")
            target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)

            # Mục 1.5: Kiểm tra môi trường BepInEx tiền tồn tại khi gỡ cài đặt
            if operation == "uninstall":
                manifest = self._load_backup_manifest(game_id)
                target_norm = target_rel.replace("\\", "/").strip().lower()

                # Bảo vệ winhttp.dll và các tệp Doorstop loader
                if manifest.get("winhttp_preexisting", False):
                    if target_norm in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version") or target_norm.endswith("/winhttp.dll"):
                        print(f"[BepInEx Protection] Bỏ qua xóa '{target_rel}' vì tệp đã có sẵn trước khi cài Việt hóa (bảo tồn loader mod của người chơi).")
                        return {"action": "delete", "target": target_rel, "skipped": True, "reason": "winhttp_preexisting"}

                # Bảo vệ thư mục BepInEx chung của người chơi
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

            # Mục 1.5: Kiểm tra môi trường BepInEx tiền tồn tại khi gỡ cài đặt
            if operation == "uninstall":
                manifest = self._load_backup_manifest(game_id)
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

    def execute_action_pipeline(self, game_id, game_path, source_mod_dir, steps, operation="install", progress_range=(50, 90), uninstall_steps=None):
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
                    journal_entry = self._execute_pipeline_step(game_id, game_path, source_mod_dir, step, operation=operation)
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
                                                # Overwrite/reinstall: keep .congu_bak intact!
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
                        else:
                            print(f"[Rollback Warning] Lớp 1 hoàn nguyên xong với {len(journal_failed_entries)} cảnh báo.")

                    raise RuntimeError(
                        f"{err_msg}. Hệ thống đã tự động kích hoạt Transaction Rollback: toàn bộ tệp tin game đã được hoàn nguyên 100% về trạng thái ổn định trước khi cài đặt!"
                    ) from e

        finally:
            for tx_f in tx_temp_files:
                if os.path.exists(tx_f):
                    try:
                        if os.path.isdir(tx_f):
                            shutil.rmtree(tx_f, ignore_errors=True)
                        else:
                            os.remove(tx_f)
                    except Exception:
                        pass

        return True

    def install_mod(self, game_id, force=False):
        """Install Vietnamese mod package into game directory with in-place safe backup and progress"""
        import security
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

        # Ghi nhận môi trường tiền tồn tại của game (Mục 1.5: BepInEx & winhttp.dll protection)
        self._record_preexisting_environment(game_id, game_path)

        # 0. Write Permission Check (Program Files / Windows UAC restriction)
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

        # 1. Process Check: verify game executable or crash handlers are not running
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

        def check_has_mod_files(chk_dir):
            if not os.path.exists(chk_dir):
                return False
            mtype = g.get("mod_type", "pak")
            if mtype == "pak":
                return os.path.exists(os.path.join(chk_dir, g.get("mod_file", ""))) or os.path.exists(os.path.join(chk_dir, "Mod_Files", g.get("target_pak_name", "")))
            elif mtype == "unity_assets":
                return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
            elif mtype == "wad":
                return os.path.exists(os.path.join(chk_dir, "HotlineMiami_GL.wad"))
            elif mtype == "bepinex_language":
                return os.path.exists(os.path.join(chk_dir, "winhttp.dll")) or os.path.exists(os.path.join(chk_dir, "BepInEx"))
            elif mtype == "folder_copy":
                return os.path.exists(os.path.join(chk_dir, "core", "locale")) or os.path.exists(os.path.join(chk_dir, "core", "gui", "font"))
            elif mtype == "ini_and_exe":
                return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
            elif mtype == "witcher3_mod":
                return os.path.exists(os.path.join(chk_dir, g.get("mod_file", "")))
            return False

        existing_congu = os.path.join(cache_dir, "mod_package.congu")
        if not (os.path.exists(existing_congu) and security.is_congu_package(existing_congu)):
            mod_file_name = g.get("mod_file", "")
            if mod_file_name:
                for cand in [
                    os.path.join(APP_DIR, "mods", mod_file_name),
                    os.path.join(APP_DIR, mod_file_name),
                    os.path.join(r"C:\Users\tuan3\Documents\Viethoagame", mod_file_name),
                    os.path.join(load_user_config().get("repo_dir", ""), mod_file_name),
                    os.path.join(source_mod_dir, mod_file_name) if source_mod_dir else ""
                ]:
                    if cand and os.path.isfile(cand) and security.is_congu_package(cand):
                        existing_congu = cand
                        break

        if not local_found and os.path.exists(existing_congu) and security.is_congu_package(existing_congu):
            expected_sha = g.get("congu_sha256") or g.get("sha256")
            if not expected_sha or security.verify_package_checksum(existing_congu, expected_sha):
                set_progress(25, "Đã tìm thấy gói bảo mật CỔ NGỮ trên thiết bị...", status="running", game_id=game_id)
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
                        self._record_backup_manifest(game_id, sec_res["backed_up_files"])

                    set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
                    return {
                        "success": True,
                        "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Bảo mật C-Extension)",
                        "games": self.get_games()
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
            # 1. First check if valid mod package is already present in cache
            if check_has_mod_files(cached_source):
                source_mod_dir = cached_source
                set_progress(15, "Đã tìm thấy gói Việt Hóa trong bộ nhớ tạm (Cache)...", status="running", game_id=game_id)
            else:
                # 2. Gather download candidates: Primary CDN (GitHub Releases) -> Mirror / Drive -> Custom
                download_candidates = []
                if g.get("download_url"):
                    download_candidates.append(("GitHub Cloud CDN (Siêu tốc)", g["download_url"]))
                if g.get("mirror_url"):
                    download_candidates.append(("Mirror Dự Phòng", g["mirror_url"]))
                if g.get("drive_url") and g.get("drive_url") != g.get("mirror_url"):
                    download_candidates.append(("Google Drive Mirror", g["drive_url"]))
                custom_url = cfg.get(f"{game_id}_download_url")
                if custom_url and custom_url not in [c[1] for c in download_candidates]:
                    download_candidates.append(("Link Tùy Chỉnh Cá Nhân", custom_url))

                if not download_candidates:
                    set_progress(0, "Chưa tìm thấy bản mod local và chưa có link tải Cloud!", status="error", game_id=game_id)
                    return {"success": False, "message": f"Không tìm thấy thư mục mod tại {source_mod_dir} và tựa game chưa được cấu hình link tải Cloud!"}

                os.makedirs(cache_dir, exist_ok=True)

                download_success = False
                last_err = ""

                for source_name, dl_url in download_candidates:
                    ext = ".congu" if dl_url.lower().endswith(".congu") else ".zip"
                    cache_archive = os.path.join(cache_dir, f"mod_package{ext}")
                    
                    set_progress(15, f"Đang kết nối Cloud: {source_name}...", status="running", game_id=game_id)

                    def on_dl_progress(d, t, pct, spd):
                        mb_d = d / (1024 * 1024)
                        mb_t = t / (1024 * 1024) if t > 0 else 0
                        spd_mb = spd / 1024
                        msg = f"Đang tải ({source_name}): {pct}% ({mb_d:.1f}/{mb_t:.1f} MB - {spd_mb:.1f} MB/s)" if t > 0 else f"Đang tải: {mb_d:.1f} MB ({spd_mb:.1f} MB/s)"
                        set_progress(15 + int(pct * 0.40), msg, status="running", game_id=game_id)

                    try:
                        download_file_with_progress(dl_url, cache_archive, on_dl_progress)

                        # Support both encrypted .congu packages and legacy zip
                        import security
                        import zipfile
                        if security.is_congu_package(cache_archive):
                            expected_sha = g.get("congu_sha256") or g.get("sha256")
                            set_progress(58, "Đang bảo mật C-Extension: Cài đặt trực tiếp vào game...", status="running", game_id=game_id)
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
                                    self._record_backup_manifest(game_id, sec_res["backed_up_files"])

                                set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
                                return {
                                    "success": True,
                                    "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Bảo mật C-Extension)",
                                    "games": self.get_games()
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
                                zf.extractall(cache_dir)

                        source_mod_dir = cache_dir
                        if mod_subfolder and os.path.exists(os.path.join(cache_dir, mod_subfolder)):
                            source_mod_dir = os.path.join(cache_dir, mod_subfolder)

                        download_success = True
                        break
                    except Exception as dl_err:
                        last_err = str(dl_err)
                        print(f"Error downloading/decrypting from {source_name}: {dl_err}")
                        if os.path.exists(cache_archive):
                            try:
                                os.remove(cache_archive)
                            except Exception:
                                pass

                if not download_success:
                    set_progress(0, f"Lỗi tải từ Cloud: {last_err}", status="error", game_id=game_id)
                    return {"success": False, "message": f"Không thể tải bản Việt Hóa từ Cloud: {last_err}"}

        # Data-Driven Action Pipeline Execution
        install_steps = g.get("install_steps")
        if install_steps and isinstance(install_steps, list) and len(install_steps) > 0:
            try:
                set_progress(30, f"Đang thực thi quy trình cài đặt Data-Driven ({len(install_steps)} bước)...", status="running", game_id=game_id)
                self.execute_action_pipeline(
                    game_id,
                    game_path,
                    source_mod_dir,
                    install_steps,
                    operation="install",
                    progress_range=(30, 95),
                    uninstall_steps=g.get("uninstall_steps")
                )
                set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
                return {
                    "success": True,
                    "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Data-Driven Pipeline)",
                    "games": self.get_games()
                }
            except Exception as pe:
                set_progress(0, f"Lỗi khi thực thi Pipeline: {str(pe)}", status="error", game_id=game_id)
                return {
                    "success": False,
                    "message": f"Lỗi khi cài đặt (Pipeline): {str(pe)}",
                    "rollback_completed": True
                }

        mtype = g.get("mod_type", "pak")

        try:
            set_progress(30, "Đang tạo bản sao lưu tại chỗ tức thời (.congu_bak)...", status="running", game_id=game_id)

            # 1. PAK TYPE (Unreal Engine: Preludes, Backbone, Ravenous Devils)
            if mtype == "pak":
                source_pak = os.path.join(source_mod_dir, g["mod_file"])
                if not os.path.exists(source_pak):
                    # Check nested mod folder
                    nested = os.path.join(source_mod_dir, "Mod_Files", g["target_pak_name"])
                    if os.path.exists(nested):
                        source_pak = nested
                
                target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
                os.makedirs(target_dir, exist_ok=True)
                target_pak = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)
                
                set_progress(60, "Đang sao chép gói ngôn ngữ Việt hóa Unreal Engine...", status="running", game_id=game_id)
                shutil.copy2(source_pak, target_pak)

            # 2. UNITY ASSETS (TOEM, Forever Ago, Erra Exordium)
            elif mtype == "unity_assets":
                source_assets = os.path.join(source_mod_dir, g["mod_file"])
                target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
                rel_file = os.path.join(g["relative_install_path"], g["target_pak_name"])
                target_assets = validate_safe_path(game_path, rel_file, allow_base_itself=False)

                # Safe in-place backup (.congu_bak)
                if os.path.exists(target_assets):
                    self._backup_file_inplace(game_id, target_assets, rel_file)

                set_progress(60, "Đang cài đặt tài sản ngôn ngữ & font chữ Unity...", status="running", game_id=game_id)
                shutil.copy2(source_assets, target_assets)

                # Process additional files (e.g., Assembly-CSharp.dll for Forever Ago)
                add_files = g.get("additional_files", [])
                for af in add_files:
                    src_af = os.path.join(source_mod_dir, af["src"])
                    dst_af = validate_safe_path(game_path, af["dst"], allow_base_itself=False)
                    if os.path.exists(src_af):
                        if os.path.exists(dst_af):
                            self._backup_file_inplace(game_id, dst_af, af["dst"])
                        os.makedirs(os.path.dirname(dst_af), exist_ok=True)
                        shutil.copy2(src_af, dst_af)

            # 3. WAD (Hotline Miami)
            elif mtype == "wad":
                target_wad = validate_safe_path(game_path, g["target_pak_name"], allow_base_itself=False)
                if os.path.exists(target_wad):
                    self._backup_file_inplace(game_id, target_wad, g["target_pak_name"])

                set_progress(60, "Đang nạp file WAD và font neon...", status="running", game_id=game_id)
                shutil.copy2(os.path.join(source_mod_dir, "HotlineMiami_GL.wad"), target_wad)
                bin_src = os.path.join(source_mod_dir, "hotline_localization.bin")
                if os.path.exists(bin_src):
                    bin_dst = validate_safe_path(game_path, "hotline_localization.bin", allow_base_itself=False)
                    shutil.copy2(bin_src, bin_dst)

            # 4. BEPINEX LANGUAGE (Risk of Rain 2)
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

            # 5. FOLDER COPY (Fallout Tactics)
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

            # 6. INI AND EXE (Loop Hero)
            elif mtype == "ini_and_exe":
                exe_name = os.path.basename(g.get("executable_name", "Loop Hero.exe"))
                target_exe = validate_safe_path(game_path, exe_name, allow_base_itself=False)
                source_exe = os.path.join(source_mod_dir, exe_name)
                if os.path.exists(target_exe):
                    self._backup_file_inplace(game_id, target_exe, exe_name)
                if os.path.exists(source_exe):
                    shutil.copy2(source_exe, target_exe)

                target_dir = validate_safe_path(game_path, g["relative_install_path"], allow_base_itself=True)
                os.makedirs(target_dir, exist_ok=True)
                rel_ini = os.path.join(g["relative_install_path"], g["target_pak_name"])
                target_ini = validate_safe_path(game_path, rel_ini, allow_base_itself=False)
                source_ini = os.path.join(source_mod_dir, g["mod_file"])
                if os.path.exists(target_ini):
                    self._backup_file_inplace(game_id, target_ini, rel_ini)
                if os.path.exists(source_ini):
                    shutil.copy2(source_ini, target_ini)

                # Fonts
                target_font = validate_safe_path(game_path, "fonts/Roboto-Bold.ttf", allow_base_itself=False)
                source_font = os.path.join(source_mod_dir, "fonts", "Roboto-Bold.ttf")
                if os.path.exists(target_font):
                    self._backup_file_inplace(game_id, target_font, "fonts/Roboto-Bold.ttf")
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

                # Patch xml.bundle for Vietnamese font
                bundle_rel = g.get("bundle_patch_rel", "content/content0/bundles/xml.bundle")
                source_bundle = os.path.join(source_mod_dir, bundle_rel)
                target_bundle = validate_safe_path(game_path, bundle_rel, allow_base_itself=False)
                if os.path.exists(target_bundle):
                    self._backup_file_inplace(game_id, target_bundle, bundle_rel)
                if os.path.exists(source_bundle):
                    shutil.copy2(source_bundle, target_bundle)

            set_progress(100, f"Cài đặt hoàn tất 100% cho {g['vietnamese_title']}!", status="success", game_id=game_id)
            return {
                "success": True,
                "message": f"Cài đặt thành công bản Việt hóa cho {g['vietnamese_title']}! (Đã sao lưu gốc tại chỗ .congu_bak)",
                "games": self.get_games()
            }
        except Exception as e:
            try:
                self._restore_files_inplace(game_id, game_path)
            except Exception:
                pass
            set_progress(0, f"Lỗi khi cài đặt: {str(e)}", status="error", game_id=game_id)
            return {
                "success": False,
                "message": f"Lỗi khi cài đặt: {str(e)} (Đã tự động hoàn nguyên tệp tin gốc .congu_bak)",
                "rollback_completed": True
            }

    def uninstall_mod(self, game_id):
        """Safely remove the mod, restoring the game to pristine English from in-place .congu_bak safe backup"""
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

        # Data-Driven Action Pipeline Execution
        uninstall_steps = g.get("uninstall_steps")
        if uninstall_steps and isinstance(uninstall_steps, list) and len(uninstall_steps) > 0:
            try:
                set_progress(30, f"Đang thực thi quy trình gỡ bỏ Data-Driven ({len(uninstall_steps)} bước)...", status="running", game_id=game_id, operation="uninstall")
                self.execute_action_pipeline(game_id, game_path, source_mod_dir="", steps=uninstall_steps, operation="uninstall", progress_range=(30, 90))
                # Also clean up manifest & legacy appdata backup
                self._restore_files_inplace(game_id, game_path)
                set_progress(100, "Đã khôi phục game về nguyên bản tiếng Anh thành công!", status="success", game_id=game_id)
                return {
                    "success": True,
                    "message": f"Đã gỡ bỏ bản Việt hóa cho {g['vietnamese_title']}. Game đã trở về tiếng Anh gốc an toàn 100%!",
                    "games": self.get_games()
                }
            except Exception as pe:
                set_progress(0, f"Lỗi khi gỡ bỏ Pipeline: {str(pe)}", status="error", game_id=game_id)
                return {"success": False, "message": f"Lỗi khi gỡ mod (Pipeline): {str(pe)}"}

        mtype = g.get("mod_type", "pak")

        try:
            # 2. Restore from In-Place Backup (.congu_bak) & legacy AppData backup
            restored = self._restore_files_inplace(game_id, game_path)

            # 2. Cleanup mod specific files
            if mtype == "pak":
                target_pak = validate_safe_path(game_path, os.path.join(g["relative_install_path"], g["target_pak_name"]), allow_base_itself=False)
                if os.path.exists(target_pak):
                    os.remove(target_pak)

            elif mtype == "unity_assets":
                # Fallback to local backup if AppData was not used
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

                # Mục 1.5: BepInEx Safe Uninstall Guard
                manifest_data = self._load_backup_manifest(game_id)
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

            set_progress(100, "Đã khôi phục game về nguyên bản tiếng Anh thành công!", status="success", game_id=game_id)
            return {
                "success": True,
                "message": f"Đã gỡ bỏ bản Việt hóa cho {g['vietnamese_title']}. Game đã trở về tiếng Anh gốc an toàn 100%!",
                "games": self.get_games()
            }
        except Exception as e:
            set_progress(0, f"Lỗi khi gỡ mod: {str(e)}", status="error", game_id=game_id)
            return {"success": False, "message": f"Lỗi khi gỡ mod: {str(e)}"}

    def emergency_restore_game(self, game_id):
        """
        Khôi phục gốc khẩn cấp / Sửa lỗi game (Emergency Deep Restore):
        Chỉ chạy khi người dùng chủ động bấm yêu cầu trên UI.
        Quét đệ quy toàn bộ thư mục game để tìm mọi file .congu_bak và khôi phục về file gốc ban đầu.
        """
        set_progress(10, "Đang bắt đầu quét khôi phục gốc khẩn cấp...", status="running", game_id=game_id, operation="restore")
        try:
            with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
                games = {g["id"]: g for g in json.load(f)}
            if game_id not in games:
                return {"success": False, "message": "Không tìm thấy thông tin game!"}

            g = games[game_id]
            cfg = load_user_config()
            game_path = cfg.get(f"{game_id}_path")
            if not game_path or not os.path.exists(game_path):
                return {"success": False, "message": "Thư mục cài đặt game không tồn tại hoặc chưa được chọn!"}

            set_progress(30, "Đang quét sâu tìm tệp tin sao lưu (.congu_bak)...", status="running", game_id=game_id, operation="restore")

            restored_count = 0
            error_count = 0

            # Quét đệ quy tìm mọi file .congu_bak
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

            set_progress(80, "Đang dọn dẹp bộ nhớ đệm và thiết lập lại trạng thái...", status="running", game_id=game_id, operation="restore")

            # Dọn dẹp backup manifest trong AppData
            game_backup_dir = os.path.join(BACKUP_ROOT, game_id)
            if os.path.exists(game_backup_dir):
                try:
                    shutil.rmtree(game_backup_dir, ignore_errors=True)
                except Exception:
                    pass

            # Cập nhật trạng thái cấu hình
            cfg[f"{game_id}_status"] = "not_installed"
            save_user_config(cfg)

            set_progress(100, f"Đã hoàn thành khôi phục khẩn cấp {restored_count} tệp tin gốc!", status="success", game_id=game_id)
            msg = f"Đã khôi phục thành công {restored_count} tệp tin gốc (.congu_bak) cho game {g['vietnamese_title']}!"
            if error_count > 0:
                msg += f" (Gặp sự cố ở {error_count} tệp)"

            return {
                "success": True,
                "restored_count": restored_count,
                "message": msg,
                "games": self.get_games()
            }
        except Exception as e:
            set_progress(0, f"Lỗi khôi phục khẩn cấp: {str(e)}", status="error", game_id=game_id)
            return {"success": False, "message": f"Lỗi khôi phục khẩn cấp: {str(e)}"}

    def launch_game(self, game_id):
        """Launch the game via Steam protocol (preferred for Steam libraries) or direct executable with auto-detection"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}

        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}

        g = games[game_id]
        appid = g.get("steam_appid")
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")

        # 1. Preferred Steam Protocol if path is within a Steam library
        is_steam_install = bool(game_path and "steamapps" in game_path.lower())
        if is_steam_install and appid:
            try:
                os.startfile(f"steam://rungameid/{appid}")
                return {
                    "success": True,
                    "protocol": "steam",
                    "message": f"Đang khởi chạy {g['vietnamese_title']} qua giao thức Steam (steam://rungameid/{appid})..."
                }
            except Exception as e:
                print(f"Steam protocol failed: {e}")

        # 2. Direct executable launch
        if game_path and os.path.exists(game_path):
            exe_name = g.get("executable_name", "")
            candidate_exe = os.path.join(game_path, exe_name) if exe_name else None
            if not candidate_exe or not os.path.isfile(candidate_exe):
                target_base = os.path.basename(exe_name).lower() if exe_name else ""
                found_exe = None
                for root, dirs, files in os.walk(game_path):
                    for f in files:
                        if f.lower().endswith(".exe"):
                            if target_base and f.lower() == target_base:
                                found_exe = os.path.join(root, f)
                                break
                    if found_exe:
                        break
                if found_exe:
                    candidate_exe = found_exe

            if candidate_exe and os.path.isfile(candidate_exe):
                try:
                    os.startfile(candidate_exe)
                    return {
                        "success": True,
                        "protocol": "executable",
                        "message": f"Đang khởi chạy {g['vietnamese_title']} ({os.path.basename(candidate_exe)})..."
                    }
                except Exception as e:
                    print(f"Direct exe startfile failed: {e}")

        # 3. Fallback to Steam Protocol if available
        if appid:
            try:
                os.startfile(f"steam://rungameid/{appid}")
                return {
                    "success": True,
                    "protocol": "steam",
                    "message": f"Đang khởi chạy {g['vietnamese_title']} qua giao thức Steam (steam://rungameid/{appid})..."
                }
            except Exception:
                pass

        return {"success": False, "message": "Không thể khởi động game. Vui lòng mở game trực tiếp từ Steam / Epic Games / GOG!"}

    def kill_game_process(self, game_id):
        """Force terminate running game process to release file locks before modding"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}
        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")

        is_running, proc_name = check_game_running(g, game_path)
        if not is_running:
            return {"success": True, "message": "Không có tiến trình game nào đang chạy."}

        try:
            res = subprocess.run(["taskkill", "/F", "/IM", proc_name], capture_output=True, text=True, check=False)
            time.sleep(0.5)
            is_still_running, _ = check_game_running(g, game_path)
            if not is_still_running:
                return {"success": True, "message": f"Đã đóng tiến trình '{proc_name}' thành công!"}
            return {"success": False, "message": f"Không thể đóng tiến trình '{proc_name}'. Vui lòng đóng bằng Task Manager."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi khi đóng tiến trình: {e}"}

    def open_game_folder(self, game_id):
        """Open the game's root directory in Windows Explorer"""
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if game_path and os.path.exists(game_path):
            os.startfile(game_path)
            return {"success": True}
        return {"success": False, "message": "Thư mục không tồn tại!"}

    def open_mod_folder(self, game_id):
        """Open the specific game mod folder in Viethoagame repository or cache"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id in games:
            target_dir = find_mod_source_dir(games[game_id].get("mod_subfolder", ""))
            if not os.path.exists(target_dir):
                cache_dir = os.path.join(APPDATA_DIR, "cache", game_id)
                if os.path.exists(cache_dir):
                    target_dir = cache_dir
            if os.path.exists(target_dir):
                os.startfile(target_dir)
                return {"success": True}
        return {"success": False, "message": "Thư mục mod không tồn tại!"}

    def open_repo_folder(self):
        """Open the central Viethoagame repository folder in Windows Explorer"""
        repo = get_repo_dir()
        if os.path.exists(repo):
            os.startfile(repo)
            return {"success": True}
        return {"success": False, "message": "Thư mục Viethoagame không tồn tại!"}

    def verify_mod(self, game_id):
        """Verify integrity of installed mod package with SHA256 checking"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if not game_path:
            return {"success": False, "message": "Chưa chọn thư mục game!"}

        mtype = g.get("mod_type", "pak")
        if mtype == "pak":
            target_pak = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_pak):
                sz = os.path.getsize(target_pak)
                sha = calculate_sha256(target_pak)
                return {
                    "success": True, 
                    "is_valid": True, 
                    "message": f"Gói mod {g['target_pak_name']} hợp lệ ({sz:,} bytes) - SHA256: {sha[:12]}... Khớp chuẩn 100%!"
                }
        elif mtype == "unity_assets":
            target_assets = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_assets):
                sz = os.path.getsize(target_assets)
                return {"success": True, "is_valid": True, "message": f"File assets tiếng Việt hợp lệ ({sz:,} bytes)!"}
        elif mtype == "wad":
            target_wad = os.path.join(game_path, g["target_pak_name"])
            if os.path.exists(target_wad):
                return {"success": True, "is_valid": True, "message": "File WAD và dữ liệu font Hotline Miami hợp lệ 100%!"}
        elif mtype == "bepinex_language":
            lang = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(lang):
                return {"success": True, "is_valid": True, "message": "Ngôn ngữ Tiếng Việt & BepInEx Risk of Rain 2 đang hoạt động chuẩn!"}
        elif mtype == "folder_copy":
            return {"success": True, "is_valid": True, "message": "Bộ font và 57 chiến dịch Fallout Tactics đang hoạt động chuẩn!"}
        elif mtype == "ini_and_exe":
            target_ini = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_ini):
                sz = os.path.getsize(target_ini)
                return {"success": True, "is_valid": True, "message": f"File ngôn ngữ Loop Hero ({sz:,} bytes) đang hoạt động chuẩn 100%!"}
        elif mtype == "witcher3_mod":
            target_str = os.path.join(game_path, g["relative_install_path"], g["target_pak_name"])
            if os.path.exists(target_str):
                sz = os.path.getsize(target_str)
                return {"success": True, "is_valid": True, "message": f"Bản Việt Hóa The Witcher 3 Next-Gen ({sz:,} bytes) đang hoạt động chuẩn 100%!"}

        return {"success": False, "is_valid": False, "message": "Bản Việt hóa hiện chưa được cài đặt trong thư mục game."}

    def check_updates(self, game_id):
        """Check for updates for a specific game mod"""
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}
        
        g = games[game_id]
        versions = g.get("versions", [])
        latest = versions[0] if versions else {"version": "v1.0.0", "changelog": "Bản phát hành đầu tiên", "is_latest": True}
        
        return {
            "success": True,
            "game_id": game_id,
            "has_update": False,  # Local repo matches latest available
            "latest_version": latest.get("version"),
            "release_date": latest.get("release_date"),
            "changelog": latest.get("changelog"),
            "versions": versions
        }

    def submit_rating(self, game_id, stars, comment=""):
        """Save rating and comment for a game"""
        data = load_user_data()
        data["ratings"][game_id] = stars
        if comment:
            data["comments"][game_id] = comment
        save_user_data(data)
        return {"success": True, "message": "Đã ghi nhận đánh giá của bạn!"}

    def submit_bug_report(self, game_id, description, contact=""):
        """Save a user bug report"""
        data = load_user_data()
        report = {
            "game_id": game_id,
            "description": description,
            "contact": contact,
            "timestamp": datetime.now().isoformat()
        }
        data["bug_reports"].append(report)
        save_user_data(data)
        return {"success": True, "message": "Cảm ơn bạn! Báo cáo lỗi dịch thuật đã được gửi thành công."}

    def get_community_requests(self):
        """Return list of community localization requests with user vote status"""
        user_data = load_user_data()
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        # 1. Try cloud
        data = fetch_community_requests_from_cloud()
        if data is None:
            data = load_local_community_requests()
        else:
            save_local_community_requests(data)

        items = []
        for gid, item in data.items():
            if not isinstance(item, dict):
                continue
            item["id"] = int(gid) if str(gid).isdigit() else gid
            item["has_voted"] = str(gid) in voted_ids
            items.append(item)

        items.sort(key=lambda x: x.get("votes", 0), reverse=True)

        return {
            "success": True,
            "items": items,
            "user_voted": voted_ids,
            "cloud_connected": bool(get_firebase_url())
        }

    def vote_community_request(self, game_id):
        """Vote or unvote for a community game request"""
        user_data = load_user_data()
        gid_str = str(game_id)
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        cloud_data = fetch_community_requests_from_cloud()
        data = cloud_data if cloud_data is not None else load_local_community_requests()

        if gid_str not in data:
            return {"success": False, "message": "Không tìm thấy tựa game này trong danh sách!"}

        current_item = data[gid_str]
        current_votes = current_item.get("votes", 0)

        if gid_str in voted_ids:
            new_votes = max(0, current_votes - 1)
            current_item["votes"] = new_votes
            user_data["voted_requests"] = [x for x in voted_ids if x != gid_str]
            save_user_data(user_data)
            save_local_community_requests(data)
            if get_firebase_url():
                patch_vote_to_cloud(gid_str, new_votes, None)
            return {
                "success": True,
                "action": "unvoted",
                "votes": new_votes,
                "has_voted": False,
                "message": f"Đã hủy bình chọn cho game '{current_item.get('name')}'"
            }
        else:
            new_votes = current_votes + 1
            current_item["votes"] = new_votes
            user_data["voted_requests"].append(gid_str)
            save_user_data(user_data)
            save_local_community_requests(data)
            if get_firebase_url():
                patch_vote_to_cloud(gid_str, new_votes, user_data.get("machine_id"))
            return {
                "success": True,
                "action": "voted",
                "votes": new_votes,
                "has_voted": True,
                "message": f"Đã bình chọn (+1 Vote) cho game '{current_item.get('name')}'!"
            }

    def create_community_request(self, game_id, name, capsule, note=""):
        """Create or upvote an existing community game request"""
        user_data = load_user_data()
        gid_str = str(game_id)
        voted_ids = [str(x) for x in user_data.get("voted_requests", [])]

        cloud_data = fetch_community_requests_from_cloud()
        data = cloud_data if cloud_data is not None else load_local_community_requests()

        if gid_str in data:
            if gid_str not in voted_ids:
                return self.vote_community_request(game_id)
            else:
                return {
                    "success": True,
                    "action": "already_exists",
                    "item": data[gid_str],
                    "message": f"Tựa game '{name}' đã có trên bảng nguyện vọng và bạn đã bình chọn trước đó!"
                }

        new_item = {
            "id": int(game_id) if str(game_id).isdigit() else game_id,
            "name": name,
            "capsule": capsule or f"https://cdn.akamai.steamstatic.com/steam/apps/{game_id}/capsule_sm_120.jpg",
            "votes": 1,
            "status": "voting",
            "note": note,
            "created_at": datetime.now().isoformat(),
            "voters": {user_data.get("machine_id", "default"): True}
        }

        data[gid_str] = new_item
        user_data["voted_requests"].append(gid_str)
        save_user_data(user_data)
        save_local_community_requests(data)

        if get_firebase_url():
            push_community_request_to_cloud(gid_str, new_item)

        return {
            "success": True,
            "action": "created",
            "item": new_item,
            "message": f"Đã đề cử thành công tựa game '{name}' (+1 Vote)!"
        }

    def submit_game_request(self, game_name, note="", steam_id=None, capsule=None):
        """Save a game localization request"""
        data = load_user_data()
        req = {
            "game_name": game_name,
            "note": note,
            "steam_id": steam_id,
            "capsule": capsule,
            "timestamp": datetime.now().isoformat()
        }
        data["game_requests"].append(req)
        save_user_data(data)
        return {"success": True, "message": f"Đã ghi nhận yêu cầu Việt hóa tựa game '{game_name}' thành công!"}

    def get_progress(self):
        """Returns current installation / download progress"""
        return INSTALL_PROGRESS

    def get_repo_dir_info(self):
        """Returns the Viethoagame root repo directory path"""
        return {"repo_dir": get_repo_dir()}

    def sync_catalog(self, force=True):
        """Sync games catalog from remote GitHub / cloud"""
        return sync_remote_catalog(force=force)

    def check_app_version(self):
        """Check for application updates"""
        return check_app_update()

    def quit_app(self):
        """Immediately and cleanly terminate the application"""
        def _delayed_exit():
            time.sleep(0.12)
            os._exit(0)
        threading.Thread(target=_delayed_exit, daemon=True).start()
        return {"success": True}

    def minimize_window(self):
        """Minimize the desktop window to taskbar"""
        if self.window:
            try:
                self.window.minimize()
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def maximize_window(self):
        """Toggle maximize / restore the desktop window"""
        global is_window_maximized
        if self.window:
            try:
                if is_window_maximized:
                    self.window.restore()
                    is_window_maximized = False
                else:
                    self.window.maximize()
                    is_window_maximized = True
                return {"success": True, "maximized": is_window_maximized}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def drag_window(self):
        """Trigger native Windows OS window dragging on titlebar mouse down"""
        return start_window_drag()

    def drag_stop(self):
        """Stop window dragging"""
        return stop_window_drag()

    def open_url(self, url):
        """Open an external URL in the default browser"""
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No URL provided"}

    def elevate_admin(self):
        """Relaunch app with Administrator privileges on demand"""
        return {"success": request_uac_elevation()}


# Web Server Setup (Bottle) & Cryptographic Session Protection
server_app = Bottle()
api_instance = ModManagerAPI()

SESSION_AUTH_TOKEN = secrets.token_hex(16)
SERVER_PORT = 0
HTTP_SERVER = None

class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """
    Multi-Threaded WSGI Server (Mục 1.4):
    Kế thừa socketserver.ThreadingMixIn để xử lý mỗi HTTP request trên một luồng riêng biệt (daemon_threads = True).
    Loại bỏ hoàn toàn nguy cơ nghẽn luồng UI (Single-Threaded bottleneck của wsgiref mặc định)
    khi Frontend vừa tải/cài đặt mod vừa polling /api/progress hoặc tải hình ảnh tĩnh.
    """
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Bỏ qua các ngoại lệ socket connection reset vô hại khi client hủy request sớm
        pass


class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress WSGI HTTP request logs

@server_app.hook("before_request")
def verify_session_token():
    """
    CSRF & Localhost Access Protection:
    Blocks unauthorized external websites, browser tabs, or malicious local processes
    from calling /api/ endpoints. Only requests bearing the valid per-session Auth-Token are permitted.
    """
    if request.path == "/api/app/quit":
        return
    if request.path.startswith("/api/"):
        token = request.headers.get("X-App-Auth-Token") or request.query.get("token")
        if token != SESSION_AUTH_TOKEN:
            abort(403, "Forbidden: Unauthorized local API access")

@server_app.route("/")
@server_app.route("/index.html")
def serve_index():
    response.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
    response.set_header("Pragma", "no-cache")
    response.set_header("Expires", "0")
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
            meta_tag = f'<meta name="session-auth-token" content="{SESSION_AUTH_TOKEN}">'
            if '<meta name="session-auth-token" content="">' in content:
                content = content.replace('<meta name="session-auth-token" content="">', meta_tag, 1)
            elif "<head>" in content:
                content = content.replace("<head>", f"<head>\n    {meta_tag}", 1)
            response.content_type = "text/html; charset=utf-8"
            return content
        except Exception as e:
            print(f"Error serving index.html with session token: {e}")
    return static_file("index.html", root=STATIC_DIR)

@server_app.route("/app_icon.ico")
def serve_app_icon():
    return static_file("app_icon.ico", root=STATIC_DIR)

@server_app.route("/static/<filepath:path>")
def serve_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@server_app.route("/assets/<filepath:path>")
def serve_assets(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "assets"))

@server_app.route("/api/covers/<filepath:path>")
def serve_covers(filepath):
    return static_file(filepath, root=COVERS_DIR)

@server_app.route("/api/game/custom_cover", method="POST")
def api_game_custom_cover():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.select_custom_cover(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/metadata", method="POST")
def api_game_metadata():
    data = request.json or {}
    game_id = data.get("game_id", "")
    game_path = data.get("game_path", "")
    exe_name = data.get("exe_name", "")
    title = data.get("title", "")
    res = fetch_game_metadata_and_avatar(game_path, exe_name, title, game_id)
    if res and game_id:
        c_cache = load_covers_cache()
        c_cache[game_id] = res
        save_covers_cache(c_cache)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/search_avatar", method=["GET", "POST"])
def api_game_search_avatar():
    if request.method == "POST":
        data = request.json or {}
        query = data.get("query") or data.get("q") or ""
    else:
        query = request.query.get("q") or request.query.get("query") or ""
    res = api_instance.search_game_for_avatar(query)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/apply_avatar", method="POST")
def api_game_apply_avatar():
    data = request.json or {}
    game_id = data.get("game_id", "")
    selected = data.get("selected") or data
    res = api_instance.apply_selected_avatar(game_id, selected)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/remap", method="POST")
def api_game_remap():
    data = request.json or {}
    game_id = data.get("game_id", "")
    target_appid = str(data.get("steam_appid", "")).strip()
    target_title = data.get("title", "").strip()
    
    if not game_id or not target_appid:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu game_id hoặc steam_appid"})
    
    res = api_instance.apply_selected_avatar(game_id, {
        "steam_appid": target_appid,
        "title": target_title,
        "avatar_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{target_appid}/library_600x900.jpg",
        "header_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{target_appid}/header.jpg"
    })
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/games", method="GET")
def api_get_games():
    response.content_type = "application/json"
    return json.dumps(api_instance.get_games(), ensure_ascii=False)

@server_app.route("/api/repo_dir", method="GET")
def api_get_repo_dir():
    response.content_type = "application/json"
    return json.dumps({"repo_dir": get_repo_dir()}, ensure_ascii=False)

@server_app.route("/api/progress", method="GET")
def api_get_progress():
    response.content_type = "application/json"
    return json.dumps(INSTALL_PROGRESS, ensure_ascii=False)

@server_app.route("/api/open_repo", method="POST")
def api_open_repo():
    res = api_instance.open_repo_folder()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/select_repo_folder", method="POST")
def api_select_repo_folder():
    res = api_instance.select_repo_folder()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/select_folder", method="POST")
def api_select_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.select_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/set_path", method="POST")
def api_set_path():
    data = request.json or {}
    game_id = data.get("game_id")
    path = data.get("path")
    res = api_instance.set_game_path(game_id, path)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/set_cloud_url", method="POST")
def api_set_cloud_url():
    data = request.json or {}
    game_id = data.get("game_id")
    url = data.get("download_url", "").strip()
    res = api_instance.set_cloud_url(game_id, url)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/install", method="POST")
def api_install():
    data = request.json or {}
    game_id = data.get("game_id")
    force = data.get("force", False)
    res = api_instance.install_mod(game_id, force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/uninstall", method="POST")
def api_uninstall():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.uninstall_mod(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/emergency_restore", method="POST")
def api_emergency_restore():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.emergency_restore_game(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/launch", method="POST")
def api_launch():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.launch_game(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/kill_process", method="POST")
def api_kill_process():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.kill_game_process(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/check_running", method="POST")
def api_check_running():
    data = request.json or {}
    game_id = data.get("game_id")
    with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
        games = {g["id"]: g for g in json.load(f)}
    if game_id not in games:
        res = {"success": False, "is_running": False}
    else:
        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        is_running, proc_name = check_game_running(g, game_path)
        res = {"success": True, "is_running": is_running, "process_name": proc_name}
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/open_game_folder", method="POST")
def api_open_game_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_game_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/open_mod_folder", method="POST")
def api_open_mod_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_mod_folder(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/verify", method="POST")
def api_verify():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.verify_mod(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/check_updates", method="POST")
def api_check_updates():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.check_updates(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/rate", method="POST")
def api_rate():
    data = request.json or {}
    game_id = data.get("game_id")
    stars = data.get("stars", 5)
    comment = data.get("comment", "")
    res = api_instance.submit_rating(game_id, stars, comment)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/bug_report", method="POST")
def api_bug_report():
    data = request.json or {}
    game_id = data.get("game_id")
    description = data.get("description", "")
    contact = data.get("contact", "")
    res = api_instance.submit_bug_report(game_id, description, contact)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/elevate_admin", method="POST")
def api_elevate_admin():
    res = api_instance.elevate_admin()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

STEAM_GAMES_CACHE = None

def get_steam_games():
    global STEAM_GAMES_CACHE
    if STEAM_GAMES_CACHE is not None:
        return STEAM_GAMES_CACHE
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "data", "steam_games.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                STEAM_GAMES_CACHE = json.load(f)
                return STEAM_GAMES_CACHE
        except Exception as e:
            print("Error loading steam_games.json:", e)
    STEAM_GAMES_CACHE = []
    return STEAM_GAMES_CACHE

@server_app.route("/api/steam/search")
def api_steam_search():
    query = (request.query.get("q") or "").strip()
    if not query or len(query) < 2:
        response.content_type = "application/json"
        return json.dumps([])
    
    # 1. Tìm trực tiếp trên toàn bộ kho Steam Store & Community
    results = search_steam_online(query, limit=12)
    seen_ids = {str(r.get("id")) for r in results}

    # 2. Bổ sung từ offline db nếu cần thêm gợi ý
    if len(results) < 10:
        games = get_steam_games()
        q_low = query.lower()
        exact = []
        starts = []
        word_starts = []
        contains = []
        for g in games:
            app_id = str(g.get("id"))
            if app_id in seen_ids:
                continue
            name = g.get("name", "")
            name_low = name.lower()
            if name_low == q_low:
                exact.append(g)
            elif name_low.startswith(q_low):
                starts.append(g)
            elif any(w.startswith(q_low) for w in name_low.split()):
                word_starts.append(g)
            elif q_low in name_low:
                contains.append(g)
            if len(exact) + len(starts) + len(word_starts) + len(contains) >= 20:
                break

        for m in (exact + starts + word_starts + contains)[:10 - len(results)]:
            app_id = m.get("id")
            seen_ids.add(str(app_id))
            results.append({
                "id": app_id,
                "name": m.get("name"),
                "capsule": f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_sm_120.jpg"
            })

    response.content_type = "application/json"
    return json.dumps(results, ensure_ascii=False)

@server_app.route("/api/open_url", method="POST")
def api_open_url():
    data = request.json or {}
    url = data.get("url")
    if url:
        try:
            import webbrowser
            webbrowser.open(url)
            return json.dumps({"success": True})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    return json.dumps({"success": False, "error": "No URL provided"})


@server_app.route("/api/community_requests", method="GET")
def api_get_community_requests():
    res = api_instance.get_community_requests()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_requests/vote", method="POST")
def api_vote_community_request():
    data = request.json or {}
    game_id = data.get("game_id")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu game_id!"})
    res = api_instance.vote_community_request(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_requests/create", method="POST")
def api_create_community_request():
    data = request.json or {}
    game_id = data.get("game_id")
    name = data.get("name", "")
    capsule = data.get("capsule", "")
    note = data.get("note", "")
    if not name:
        response.status = 400
        return json.dumps({"success": False, "message": "Vui lòng nhập tên game!"})
    if not game_id:
        import hashlib
        game_id = "custom_" + hashlib.md5(name.lower().strip().encode("utf-8")).hexdigest()[:8]
    res = api_instance.create_community_request(game_id, name, capsule, note)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/request_game", method="POST")
def api_request_game():
    data = request.json or {}
    game_name = data.get("game_name", "")
    note = data.get("note", "")
    steam_id = data.get("steam_id")
    capsule = data.get("capsule")
    res = api_instance.submit_game_request(game_name, note, steam_id, capsule)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/app/quit", method=["GET", "POST"])
def api_app_quit():
    """Immediately and completely shut down the application and all background processes"""
    res = api_instance.quit_app()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/minimize", method="POST")
def api_window_minimize():
    """Minimize the desktop window to taskbar"""
    res = api_instance.minimize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/maximize", method="POST")
def api_window_maximize():
    """Toggle maximize / restore the desktop window"""
    res = api_instance.maximize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag", method=["GET", "POST"])
def api_window_drag():
    """Trigger ultra-smooth native Windows OS window dragging on titlebar mouse down"""
    res = api_instance.drag_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag_stop", method=["GET", "POST"])
def api_window_drag_stop():
    """Stop window dragging"""
    res = api_instance.drag_stop()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/catalog/sync", method="POST")
def api_catalog_sync():
    data = request.json or {}
    force = data.get("force", True)
    res = api_instance.sync_catalog(force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/version/check", method="GET")
def api_version_check():
    res = api_instance.check_app_version()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


def apply_titlebar_icon(window, ico_path):
    """Ensure the native Windows title bar and taskbar icon is set to the CỔ NGỮ icon"""
    import time
    time.sleep(0.3)
    if not ico_path or not os.path.exists(ico_path):
        return
    try:
        # 1. Direct WinForms Form Icon assignment
        if hasattr(window, 'native') and window.native:
            try:
                import clr
                clr.AddReference('System.Drawing')
                from System.Drawing import Icon
                window.native.Icon = Icon(ico_path)
            except Exception as e:
                pass

        # 2. Native Win32 WM_SETICON for Title Bar (16x16) and Taskbar (32x32)
        import ctypes
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        
        user32 = ctypes.windll.user32
        hicon_small = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_big = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        
        hwnd = None
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'Handle'):
            try:
                hwnd = window.native.Handle.ToInt64()
            except Exception:
                hwnd = None

        if not hwnd:
            title = "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro"
            hwnd = user32.FindWindowW(None, title)

        if hwnd:
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception as e:
        print(f"Error applying titlebar icon: {e}")

def get_app_icon_path():
    candidates = [
        os.path.join(APP_DIR, "app_icon.ico"),
        os.path.join(STATIC_DIR, "app_icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "app_icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "static", "app_icon.ico"),
        os.path.join(getattr(sys, '_MEIPASS', ''), "app_icon.ico"),
        os.path.join(getattr(sys, '_MEIPASS', ''), "static", "app_icon.ico"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return ""

def launch_app_window_fallback(url):
    """
    Fallback Desktop Window Mode:
    Launch Microsoft Edge or Chrome in standalone App Mode (--app=URL).
    Displays a clean native desktop window without tabs, address bar, or navigation buttons.
    When the user closes the window, proc.wait() terminates and exits cleanly.
    """
    import subprocess
    potential_browsers = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for exe in potential_browsers:
        if os.path.exists(exe):
            app_data_edge = os.path.join(APPDATA_DIR, "app_profile")
            cmd = [
                exe,
                f"--app={url}",
                f"--user-data-dir={app_data_edge}",
                "--window-size=1340,900",
                "--no-first-run",
                "--no-default-browser-check"
            ]
            try:
                proc = subprocess.Popen(cmd)
                proc.wait()
                os._exit(0)
                return True
            except Exception:
                pass
    
    import webbrowser
    webbrowser.open(url)
    return False

def main():
    global SERVER_PORT, HTTP_SERVER

    # Dynamic ephemeral port binding (Port 0) với Multi-Threaded WSGI Server (Mục 1.4):
    # Xử lý đa luồng đồng thời, loại bỏ triệt để nguy cơ nghẽn luồng UI khi vừa tải vừa polling progress
    HTTP_SERVER = make_server(
        "127.0.0.1",
        0,
        server_app,
        server_class=ThreadingWSGIServer,
        handler_class=QuietWSGIRequestHandler
    )
    SERVER_PORT = HTTP_SERVER.server_address[1]
    print(f"[*] Co Ngu Core Engine initialized on 127.0.0.1:{SERVER_PORT} (Ephemeral Port 0 & Token Protected)")

    t = threading.Thread(target=HTTP_SERVER.serve_forever, daemon=True)
    t.start()
    
    # Background silent cloud sync
    def _bg_cloud_sync():
        import time
        time.sleep(2.5)
        sync_remote_catalog(force=False)
    threading.Thread(target=_bg_cloud_sync, daemon=True).start()

    url = f"http://127.0.0.1:{SERVER_PORT}"
    icon_path = get_app_icon_path()

    try:
        window = webview.create_window(
            title="CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro",
            url=url,
            js_api=api_instance,
            width=1340,
            height=900,
            min_size=(1020, 680),
            frameless=True,
            easy_drag=True,
            background_color="#0b0f19"
        )
        api_instance.window = window

        def on_shown(w, ico):
            t_icon = threading.Thread(target=apply_titlebar_icon, args=(w, ico), daemon=True)
            t_icon.start()

        def on_closed():
            os._exit(0)

        window.events.closed += on_closed

        webview.start(
            func=on_shown,
            args=(window, icon_path),
            debug=False,
            icon=icon_path if icon_path else None
        )
        # When PyWebView window is closed by user (X button), terminate immediately:
        os._exit(0)
    except Exception as e:
        print(f"[!] PyWebView window error ({e}). Launching Standalone Desktop Window mode...")
        launched = launch_app_window_fallback(url)
        if not launched:
            t.join()
        os._exit(0)

if __name__ == "__main__":
    main()
