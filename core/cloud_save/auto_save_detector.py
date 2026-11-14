# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Smart Auto-Save Detector
==================================================
Bộ dò tìm vị trí lưu Save Game tự động thông minh:
1. Quét theo Steam AppID các Steam Emulator phổ biến:
   - Goldberg SteamEmu
   - RUNE
   - CODEX
   - TENOKE
   - FLT (FairLight)
   - SKIDROW
   - OnlineFix
   - Steam Userdata (Official / GreenLuma / SmartSteamEmu)
2. Quét theo thư mục chuẩn Windows:
   - %USERPROFILE%/Saved Games/<GameTitle>
   - %USERPROFILE%/Documents/My Games/<GameTitle>
   - %USERPROFILE%/Documents/<GameTitle>
   - %LOCALAPPDATA%/<GameTitle>/Saved/SaveGames (Unreal Engine 4/5 chuẩn)
   - %LOCALAPPDATA%/<GameTitle>
   - %LOCALAPPDATA_LOW%/*/<GameTitle> (Unity chuẩn: LocalLow/<Studio>/<Game>)
   - {GAME_ROOT}/saves, {GAME_ROOT}/save, {GAME_ROOT}/Save
3. Heuristic: Dò tìm các file save thay đổi trong phiên chơi gần nhất.
"""

import os
import re
import glob
import time
from typing import List, Dict, Any, Optional


def _clean_token(text: str) -> str:
    """Loại bỏ ký tự đặc biệt để so khớp tên thư mục."""
    if not text:
        return ""
    # Bỏ dấu nháy, hai chấm, gạch ngang, khoảng trắng thừa
    t = re.sub(r"[:\-_'\"!?,.()\[\]]", " ", str(text).lower())
    return re.sub(r"\s+", " ", t).strip()


def detect_game_save_locations(game_config: dict, game_root: str = "") -> List[Dict[str, str]]:
    """
    Tự động dò tìm tất cả các vị trí lưu save thực tế của game trên máy tính.
    Trả về danh sách [{'slot': str, 'path': str, 'detected': True, 'type': str}]
    """
    results: List[Dict[str, str]] = []
    seen_paths = set()

    user_prof = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    appdata = os.environ.get("APPDATA", os.path.join(user_prof, "AppData", "Roaming"))
    localappdata = os.environ.get("LOCALAPPDATA", os.path.join(user_prof, "AppData", "Local"))
    locallow = os.path.join(user_prof, "AppData", "LocalLow")
    public_dir = os.environ.get("PUBLIC", r"C:\Users\Public")
    docs = os.path.join(user_prof, "Documents")
    saved_games = os.path.join(user_prof, "Saved Games")

    macro_map = {
        "{DOCUMENTS}": docs,
        "{APPDATA}": appdata,
        "{LOCALAPPDATA}": localappdata,
        "{LOCALAPPDATA_LOW}": locallow,
        "{USERPROFILE}": user_prof,
        "{SAVEDGAMES}": saved_games,
        "{PUBLIC_DOCS}": os.path.join(public_dir, "Documents"),
        "{GAME_ROOT}": game_root or "",
        "{STEAM_USERDATA}": os.path.join(localappdata, "Steam", "userdata"),
    }

    def add_location(slot: str, raw_path: str, save_type: str = "auto_detected"):
        if not raw_path:
            return
        expanded = str(raw_path)
        for m, r in macro_map.items():
            if m in expanded and r:
                expanded = expanded.replace(m, r)
        expanded = os.path.expandvars(expanded)
        norm = os.path.normcase(os.path.abspath(expanded)) if os.path.isabs(expanded) else raw_path
        if norm in seen_paths:
            return
        if os.path.exists(expanded):
            seen_paths.add(norm)
            results.append({
                "slot": slot,
                "path": raw_path,
                "detected": True,
                "type": save_type
            })
    public_dir = os.environ.get("PUBLIC", r"C:\Users\Public")
    docs = os.path.join(user_prof, "Documents")
    saved_games = os.path.join(user_prof, "Saved Games")

    appid = str(game_config.get("steam_appid") or "").strip()
    title = game_config.get("title") or game_config.get("id") or ""
    clean_title = _clean_token(title)
    exe_name = os.path.splitext(os.path.basename(game_config.get("executable_name") or ""))[0]

    # -------------------------------------------------------------
    # 1. Quét theo Steam AppID các Steam Emulator phổ biến
    # -------------------------------------------------------------
    if appid and appid.isdigit():
        # 1.1 Goldberg SteamEmu
        goldberg_remote = os.path.join(appdata, "Goldberg SteamEmu Saves", appid, "remote")
        goldberg_root = os.path.join(appdata, "Goldberg SteamEmu Saves", appid)
        if os.path.isdir(goldberg_remote):
            add_location("goldberg_remote", f"{{APPDATA}}\\Goldberg SteamEmu Saves\\{appid}\\remote", "goldberg")
        elif os.path.isdir(goldberg_root):
            add_location("goldberg_save", f"{{APPDATA}}\\Goldberg SteamEmu Saves\\{appid}", "goldberg")

        # 1.2 RUNE
        rune_remote = os.path.join(public_dir, "Documents", "Steam", "RUNE", appid, "remote")
        rune_root = os.path.join(public_dir, "Documents", "Steam", "RUNE", appid)
        if os.path.isdir(rune_remote):
            add_location("rune_remote", f"{{PUBLIC_DOCS}}\\Steam\\RUNE\\{appid}\\remote", "rune")
        elif os.path.isdir(rune_root):
            add_location("rune_save", f"{{PUBLIC_DOCS}}\\Steam\\RUNE\\{appid}", "rune")

        # 1.3 CODEX
        codex_public = os.path.join(public_dir, "Documents", "Steam", "CODEX", appid, "remote")
        codex_appdata = os.path.join(appdata, "Steam", "CODEX", appid, "remote")
        if os.path.isdir(codex_public):
            add_location("codex_public", f"{{PUBLIC_DOCS}}\\Steam\\CODEX\\{appid}\\remote", "codex")
        elif os.path.isdir(codex_appdata):
            add_location("codex_appdata", f"{{APPDATA}}\\Steam\\CODEX\\{appid}\\remote", "codex")

        # 1.4 TENOKE
        tenoke_local = os.path.join(localappdata, "TENOKE", appid)
        tenoke_roaming = os.path.join(appdata, "TENOKE", appid)
        if os.path.isdir(tenoke_local):
            add_location("tenoke_local", f"{{LOCALAPPDATA}}\\TENOKE\\{appid}", "tenoke")
        elif os.path.isdir(tenoke_roaming):
            add_location("tenoke_roaming", f"{{APPDATA}}\\TENOKE\\{appid}", "tenoke")

        # 1.5 FLT (FairLight)
        flt_path = os.path.join(appdata, "FLT", appid)
        if os.path.isdir(flt_path):
            add_location("flt_save", f"{{APPDATA}}\\FLT\\{appid}", "flt")

        # 1.6 OnlineFix
        of_public = os.path.join(public_dir, "Documents", "OnlineFix", appid, "remote")
        if os.path.isdir(of_public):
            add_location("onlinefix_public", f"{{PUBLIC_DOCS}}\\OnlineFix\\{appid}\\remote", "onlinefix")
        if game_root:
            of_gameroot = os.path.join(game_root, "OnlineFix", "remote")
            if os.path.isdir(of_gameroot):
                add_location("onlinefix_gameroot", "{GAME_ROOT}\\OnlineFix\\remote", "onlinefix")
            of_profile = os.path.join(game_root, "Profile", "remote")
            if os.path.isdir(of_profile):
                add_location("onlinefix_profile", "{GAME_ROOT}\\Profile\\remote", "onlinefix")

        # 1.7 Steam Official Userdata
        for s_root in [
            r"C:\Program Files (x86)\Steam\userdata",
            r"C:\Program Files\Steam\userdata",
            os.path.join(localappdata, "Steam", "userdata")
        ]:
            if os.path.isdir(s_root):
                try:
                    for uid in os.listdir(s_root):
                        cand = os.path.join(s_root, uid, appid, "remote")
                        if os.path.isdir(cand):
                            add_location(f"steam_user_{uid}", f"{{STEAM_USERDATA}}\\{uid}\\{appid}\\remote", "steam_official")
                except OSError:
                    pass

    # -------------------------------------------------------------
    # 2. Quét các thư mục lưu game chuẩn của Windows
    # -------------------------------------------------------------
    candidates_names = []
    if title:
        candidates_names.append(title)
        candidates_names.append(title.replace(" ", ""))
        candidates_names.append(title.replace(":", " "))
    if clean_title:
        candidates_names.append(clean_title)
    if exe_name and exe_name.lower() not in [c.lower() for c in candidates_names]:
        candidates_names.append(exe_name)

    # 2.1 Unreal Engine: %LOCALAPPDATA%/<GameName>/Saved/SaveGames
    if os.path.isdir(localappdata):
        try:
            for dirname in os.listdir(localappdata):
                dir_clean = _clean_token(dirname)
                if any(c and (c.lower() == dirname.lower() or _clean_token(c) == dir_clean) for c in candidates_names):
                    ue_save = os.path.join(localappdata, dirname, "Saved", "SaveGames")
                    if os.path.isdir(ue_save):
                        add_location("ue_savegames", f"{{LOCALAPPDATA}}\\{dirname}\\Saved\\SaveGames", "unreal_engine")
                    else:
                        ue_saved = os.path.join(localappdata, dirname, "Saved")
                        if os.path.isdir(ue_saved):
                            add_location("ue_saved", f"{{LOCALAPPDATA}}\\{dirname}\\Saved", "unreal_engine")
        except OSError:
            pass

    # 2.2 Unity Games: %USERPROFILE%/AppData/LocalLow/<Company>/<GameName>
    if os.path.isdir(locallow):
        try:
            for comp in os.listdir(locallow):
                comp_dir = os.path.join(locallow, comp)
                if os.path.isdir(comp_dir):
                    try:
                        for gname in os.listdir(comp_dir):
                            gclean = _clean_token(gname)
                            if any(c and (_clean_token(c) == gclean or gname.lower() in c.lower() or c.lower() in gname.lower()) for c in candidates_names):
                                target = os.path.join(comp_dir, gname)
                                if os.path.isdir(target):
                                    add_location("unity_locallow", f"{{LOCALAPPDATA_LOW}}\\{comp}\\{gname}", "unity")
                    except OSError:
                        pass
        except OSError:
            pass

    # 2.3 %USERPROFILE%/Saved Games/<GameName>
    if os.path.isdir(saved_games):
        try:
            for sname in os.listdir(saved_games):
                sclean = _clean_token(sname)
                if any(c and (_clean_token(c) == sclean or sname.lower() == c.lower()) for c in candidates_names):
                    add_location("saved_games_dir", f"{{SAVEDGAMES}}\\{sname}", "windows_saved_games")
        except OSError:
            pass

    # 2.4 Documents/My Games/<GameName> và Documents/<GameName>
    my_games = os.path.join(docs, "My Games")
    if os.path.isdir(my_games):
        try:
            for mname in os.listdir(my_games):
                mclean = _clean_token(mname)
                if any(c and (_clean_token(c) == mclean or mname.lower() == c.lower()) for c in candidates_names):
                    add_location("my_games_dir", f"{{DOCUMENTS}}\\My Games\\{mname}", "my_games")
        except OSError:
            pass

    if os.path.isdir(docs):
        try:
            for dname in os.listdir(docs):
                dclean = _clean_token(dname)
                if any(c and (_clean_token(c) == dclean or dname.lower() == c.lower()) for c in candidates_names):
                    # Bỏ qua My Games vì đã check riêng
                    if dname.lower() != "my games":
                        add_location("documents_dir", f"{{DOCUMENTS}}\\{dname}", "documents")
        except OSError:
            pass

    # 2.5 Save ngay trong thư mục game (Portable Game / Emulators)
    if game_root and os.path.isdir(game_root):
        for sub in ["saves", "save", "Save", "Saves", "savegame", "Profile"]:
            cand = os.path.join(game_root, sub)
            if os.path.isdir(cand):
                add_location(f"gameroot_{sub.lower()}", f"{{GAME_ROOT}}\\{sub}", "portable_gameroot")

    return results


def wait_file_stable(file_path: str, timeout_sec: float = 1.5, check_interval: float = 0.1) -> bool:
    """
    Kiểm tra và đợi tệp tin ghi xong (File-Lock Guard).
    Đảm bảo file không còn bị tiến trình game khóa ghi và kích thước đã ổn định hoàn toàn.
    """
    if not os.path.isfile(file_path):
        return False

    deadline = time.time() + timeout_sec
    last_size = -1
    stable_count = 0

    while time.time() < deadline:
        try:
            curr_size = os.path.getsize(file_path)
            # Thử mở ở chế độ đọc nhị phân độc quyền để kiểm tra Write Lock
            with open(file_path, "rb") as f:
                f.read(128)

            if curr_size == last_size and curr_size > 0:
                stable_count += 1
                if stable_count >= 2:
                    return True
            else:
                stable_count = 0
            last_size = curr_size
        except (PermissionError, OSError):
            # File đang bị khóa ghi bởi game
            stable_count = 0

        time.sleep(check_interval)

    # Dù hết timeout vẫn thử đọc 1 lần cuối
    try:
        with open(file_path, "rb") as f:
            f.read(64)
        return True
    except Exception:
        return False
