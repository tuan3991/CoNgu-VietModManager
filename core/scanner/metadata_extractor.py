# -*- coding: utf-8 -*-
import os
import sys
import re
import json
import glob
import subprocess
from typing import Optional


def extract_local_steam_appid(game_dir: str) -> Optional[str]:
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

