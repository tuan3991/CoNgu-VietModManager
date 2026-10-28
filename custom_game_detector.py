# -*- coding: utf-8 -*-
"""
Module: custom_game_detector.py
Mục đích: Tự động nhận diện Tên Game, Hãng Sản Xuất, Ảnh Bìa HD (Steam Poster),
Steam AppID, Engine, Thư mục Save Game & Thành tựu từ bất kỳ file .exe nào
được người dùng thêm vào thư viện CỔ NGỮ (VietModHub).
Hoàn toàn độc lập - 0 MB Thư viện ngoài (chỉ dùng chuẩn Python ctypes/urllib/re/json).
"""

import os
import sys
import re
import json
import ctypes
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Tuple, Optional


class CustomGameDetector:
    """
    Hệ thống 4 phễu tự động nhận diện thông minh (Smart Auto-Discovery Pipeline)
    cho tính năng Non-Steam / Custom Game của CỔ NGỮ.
    """

    @staticmethod
    def detect_from_exe(exe_path: str, covers_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Nhận diện toàn diện từ một file .exe:
        1. Tìm steam_appid nội bộ (steam_appid.txt, ini files)
        2. Bóc tách PE Header (CompanyName, ProductName) hoặc Unity app.info
        3. Nhận diện Engine của game
        4. Tra cứu Steam Store API để lấy Tên chuẩn & Ảnh bìa HD
        5. Tự động tải ảnh bìa về thư mục covers cục bộ (nếu có covers_dir)
        6. Dò tìm thư mục Save Game & Thành tựu thực tế trên PC
        """
        if not exe_path or not os.path.isfile(exe_path):
            raise FileNotFoundError(f"File thực thi không tồn tại: '{exe_path}'")

        exe_path = os.path.abspath(exe_path)
        game_dir = os.path.dirname(exe_path)
        exe_name = os.path.basename(exe_path)

        # 1. Nhận diện Engine
        engine_name = CustomGameDetector._detect_engine(game_dir, exe_path)

        # 2. Tìm kiếm Steam AppID trong thư mục game (Phễu 1)
        steam_appid = CustomGameDetector._find_local_steam_appid(game_dir)

        # 3. Đọc siêu dữ liệu từ PE Header hoặc Unity app.info (Phễu 2)
        company_name, product_name = CustomGameDetector._extract_exe_metadata(exe_path, game_dir)

        # Tên thô dự phòng
        clean_exe_base = os.path.splitext(exe_name)[0]
        # Loại bỏ các hậu tố thường gặp trong exe game
        clean_exe_base = re.sub(
            r"[-_]*(Win64|Win32|Shipping|x64|x86|dx11|dx12|Vulkan|Game|Launcher|Release|Final)$",
            "",
            clean_exe_base,
            flags=re.IGNORECASE
        ).strip()
        fallback_title = product_name or clean_exe_base or "Game Không Tên"

        # 4. Tra cứu thông tin chính thức & Ảnh bìa từ Steam Store API
        steam_info = CustomGameDetector._query_steam_metadata(steam_appid, fallback_title)
        final_title = steam_info.get("title") or fallback_title
        final_appid = steam_info.get("steam_appid") or steam_appid
        developer = steam_info.get("developer") or company_name or "Chưa rõ"
        publisher = steam_info.get("publisher") or company_name or "Chưa rõ"
        header_url = steam_info.get("header_url", "")
        cover_url = steam_info.get("cover_url", "")
        summary = steam_info.get("summary", "")

        # Tạo Game ID duy nhất chuẩn hóa
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", final_title.strip().lower()).strip("_")
        game_id = f"custom_{final_appid}" if final_appid else f"custom_{safe_name}"

        # 5. Tự động tải ảnh bìa về covers_dir nếu có
        local_cover_path = ""
        if covers_dir and os.path.isdir(covers_dir):
            local_cover_path = CustomGameDetector._download_cover_poster(
                cover_url or header_url,
                game_id,
                covers_dir
            )

        # 6. Tự động dò tìm thư mục Save Game & Thành tựu (Phễu 4)
        save_locations = CustomGameDetector._guess_save_locations(
            game_dir, final_title, company_name, product_name, engine_name
        )
        achievement_locations = CustomGameDetector._guess_achievement_locations(final_appid)

        return {
            "id": game_id,
            "is_custom_game": True,
            "steam_appid": str(final_appid) if final_appid else "",
            "title": final_title,
            "vietnamese_title": f"{final_title} (Tự Thêm)",
            "developer": developer,
            "publisher": publisher,
            "engine": engine_name,
            "description": summary or f"Tựa game '{final_title}' được người dùng tự thêm vào thư viện CỔ NGỮ.",
            "game_root": game_dir.replace("\\", "/"),
            "executable_name": exe_name,
            "cover_url": cover_url,
            "header_url": header_url,
            "local_cover": local_cover_path,
            "status_code": "INSTALLED",
            "status_label": "SẴN SÀNG CHƠI",
            "is_game_found": True,
            "translation_stats": {
                "total_lines": "Game gốc",
                "version": "v1.0.0",
                "last_updated": "Tự nhận diện",
                "font": "Mặc định",
                "mod_size": "0 MB"
            },
            "vault_config": {
                "save_locations": save_locations,
                "achievement_locations": achievement_locations,
                "exclude_patterns": ["*.bak", "*.tmp", "*.log", "*.congu_bak"]
            }
        }

    # =========================================================================
    # PHỄU 1: TÌM STEAM APPID TRONG THƯ MỤC GAME (ĐỘ CHÍNH XÁC 100%)
    # =========================================================================
    @staticmethod
    def _find_local_steam_appid(game_dir: str) -> str:
        """Quét tìm file steam_appid.txt và các file cấu hình Steam Emulator."""
        search_dirs = [game_dir]
        parent = os.path.dirname(game_dir)
        if parent and parent != game_dir:
            search_dirs.append(parent)

        # 1. Kiểm tra file steam_appid.txt tiêu chuẩn
        for d in search_dirs:
            for rel in [
                "steam_appid.txt",
                "steam_settings/steam_appid.txt",
                "steam_settings/settings/app_id.txt",
                "steam_interfaces.txt"
            ]:
                p = os.path.join(d, rel)
                if os.path.isfile(p):
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            val = f.read().strip()
                            # Lấy số đầu tiên
                            m = re.search(r"(\d{3,10})", val)
                            if m:
                                return m.group(1)
                    except OSError:
                        pass

        # 2. Kiểm tra các file .ini cấu hình Steam Emu phổ biến
        ini_patterns = [
            "steam_emu.ini", "codex.ini", "rune.ini", "tenoke.ini", "OnlineFix.ini",
            "flt.ini", "cream_api.ini", "SmartSteamEmu.ini", "ALI213.ini", "valve.ini"
        ]
        for d in search_dirs:
            for ini_name in ini_patterns:
                p = os.path.join(d, ini_name)
                if os.path.isfile(p):
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            match = re.search(r"(?:AppId|App_Id|TargetAppId|appid)\s*=\s*(\d+)", content, re.IGNORECASE)
                            if match:
                                return match.group(1)
                    except OSError:
                        pass
        return ""

    # =========================================================================
    # PHỄU 2: BÓC TÁCH PE HEADER & UNITY APP.INFO
    # =========================================================================
    @staticmethod
    def _extract_exe_metadata(exe_path: str, game_dir: str) -> Tuple[str, str]:
        """
        Lấy CompanyName và ProductName:
        Ưu tiên 1: Đọc Unity *_Data/app.info
        Ưu tiên 2: Đọc Windows PE FileVersionInfo qua ctypes (version.dll)
        """
        # 1. Unity app.info check
        if os.path.isdir(game_dir):
            try:
                for item in os.listdir(game_dir):
                    if item.endswith("_Data") and os.path.isdir(os.path.join(game_dir, item)):
                        app_info = os.path.join(game_dir, item, "app.info")
                        if os.path.isfile(app_info):
                            with open(app_info, "r", encoding="utf-8", errors="ignore") as f:
                                lines = [line.strip() for line in f.read().splitlines() if line.strip()]
                                if len(lines) >= 2:
                                    return lines[0], lines[1]
                                elif len(lines) == 1:
                                    return "", lines[0]
            except Exception:
                pass

        # 2. Windows PE Version Info qua version.dll (ctypes)
        try:
            version_dll = ctypes.windll.version
            size = version_dll.GetFileVersionInfoSizeW(exe_path, None)
            if size > 0:
                res = ctypes.create_string_buffer(size)
                if version_dll.GetFileVersionInfoW(exe_path, 0, size, res):
                    r_ptr = ctypes.c_void_p()
                    l_size = ctypes.c_uint()
                    # Lấy bảng mã ngôn ngữ
                    if version_dll.VerQueryValueW(res, r"\VarFileInfo\Translation", ctypes.byref(r_ptr), ctypes.byref(l_size)):
                        lang, codepage = ctypes.cast(r_ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
                        prefix = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\"

                        def _query_str(key: str) -> str:
                            if version_dll.VerQueryValueW(res, prefix + key, ctypes.byref(r_ptr), ctypes.byref(l_size)):
                                return ctypes.wstring_at(r_ptr.value).strip()
                            return ""

                        company = _query_str("CompanyName")
                        product = _query_str("ProductName") or _query_str("FileDescription")
                        if company or product:
                            return company, product
        except Exception:
            pass

        return "", ""

    # =========================================================================
    # PHỄU 3: NHẬN DIỆN ENGINE GAME
    # =========================================================================
    @staticmethod
    def _detect_engine(game_dir: str, exe_path: str) -> str:
        """Quét cấu trúc thư mục để xác định Game Engine."""
        if not os.path.isdir(game_dir):
            return "PC Game"

        try:
            files_and_dirs = os.listdir(game_dir)
            files_lower = {f.lower() for f in files_and_dirs}
        except Exception:
            return "PC Game"

        # 1. Unity
        if "unityplayer.dll" in files_lower or "unitycrashhandler64.exe" in files_lower or "unitycrashhandler32.exe" in files_lower:
            return "Unity"
        for item in files_and_dirs:
            if item.endswith("_Data") and os.path.isdir(os.path.join(game_dir, item)):
                return "Unity"

        # 2. Unreal Engine
        if "engine" in files_lower and os.path.isdir(os.path.join(game_dir, "Engine")):
            return "Unreal Engine"
        for root, dirs, files in os.walk(game_dir):
            if "Content" in dirs and "Paks" in os.listdir(os.path.join(root, "Content")):
                return "Unreal Engine"
            # Giới hạn tìm kiếm 2 cấp thư mục
            if os.path.relpath(root, game_dir).count(os.sep) >= 2:
                dirs.clear()

        # 3. Godot
        for f in files_lower:
            if f.endswith(".pck"):
                return "Godot"

        # 4. GameMaker Studio
        if "data.win" in files_lower or any(f.endswith(".win") for f in files_lower):
            return "GameMaker Studio"

        # 5. RPG Maker
        if "game.rpgproject" in files_lower or "rgss3a" in files_lower or "rgss2a" in files_lower or "rgssad" in files_lower:
            return "RPG Maker"
        if "package.json" in files_lower:
            try:
                pkg_p = os.path.join(game_dir, "package.json")
                with open(pkg_p, "r", encoding="utf-8", errors="ignore") as pf:
                    pdata = json.load(pf)
                    if "rpg" in pdata.get("name", "").lower() or "rpg" in pdata.get("main", "").lower():
                        return "RPG Maker MV/MZ"
            except Exception:
                pass

        # 6. Ren'Py
        if "renpy" in files_lower or any(f.endswith(".rpy") or f.endswith(".rpa") for f in files_lower):
            return "Ren'Py"

        return "PC Executable"

    # =========================================================================
    # PHỄU 4: STEAM STORE API METADATA & POSTER SCRAPER
    # =========================================================================
    @staticmethod
    def _query_steam_metadata(steam_appid: str, fallback_query: str) -> Dict[str, Any]:
        """
        Tra cứu thông tin chính thức của game từ Steam Store API:
        - Tên chính thức
        - Poster chuẩn HD (library_600x900.jpg)
        - Header banner
        - Nhà phát triển / phát hành
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
        }

        # 1. Nếu chưa có steam_appid nhưng có tên query, dùng Steam Store Search
        if not steam_appid and fallback_query:
            try:
                q = urllib.parse.quote(fallback_query)
                search_url = f"https://store.steampowered.com/api/storesearch/?term={q}&l=english&cc=US"
                req = urllib.request.Request(search_url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                        items = data.get("items", [])
                        if items:
                            first = items[0]
                            steam_appid = str(first.get("id"))
            except Exception as e:
                print(f"[CustomGameDetector] Steam storesearch error: {e}")

        # 2. Truy vấn appdetails khi đã có steam_appid
        if steam_appid:
            try:
                details_url = f"https://store.steampowered.com/api/appdetails?appids={steam_appid}&l=vietnamese"
                req = urllib.request.Request(details_url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                        entry = data.get(str(steam_appid), {})
                        if entry.get("success"):
                            info = entry.get("data", {})
                            name = info.get("name")
                            devs = ", ".join(info.get("developers", []))
                            pubs = ", ".join(info.get("publishers", []))
                            summary = info.get("short_description", "")

                            # Steam Library vertical cover 600x900 (Chuẩn Steam Library & Hydra)
                            poster_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/library_600x900_2x.jpg"
                            header_url = info.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{steam_appid}/header.jpg"

                            return {
                                "steam_appid": str(steam_appid),
                                "title": name,
                                "developer": devs,
                                "publisher": pubs,
                                "summary": summary,
                                "cover_url": poster_url,
                                "header_url": header_url
                            }
            except Exception as e:
                print(f"[CustomGameDetector] Steam appdetails error: {e}")

        return {}

    @staticmethod
    def _download_cover_poster(url: str, game_id: str, covers_dir: str) -> str:
        """Tải ảnh bìa Poster từ CDN về thư mục covers cục bộ."""
        if not url:
            return ""
        os.makedirs(covers_dir, exist_ok=True)
        safe_gid = re.sub(r"[^\w\-]", "_", game_id)
        local_file = os.path.join(covers_dir, f"{safe_gid}.jpg")

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=7) as resp:
                if resp.status == 200:
                    with open(local_file, "wb") as f:
                        f.write(resp.read())
                    if os.path.exists(local_file) and os.path.getsize(local_file) > 1000:
                        return f"/api/covers/{safe_gid}.jpg"
        except Exception as e:
            print(f"[CustomGameDetector] Tải ảnh bìa thất bại cho {game_id}: {e}")

        return ""

    # =========================================================================
    # PHỄU 5: HEURISTIC SAVE & ACHIEVEMENT DETECTOR
    # =========================================================================
    @staticmethod
    def _guess_save_locations(
        game_dir: str,
        title: str,
        company: str,
        product: str,
        engine: str
    ) -> List[Dict[str, str]]:
        """
        Dò tìm các thư mục Save Game thực tế trên PC người dùng.
        Chỉ đề xuất các đường dẫn thực sự tồn tại hoặc có xác suất cao nhất.
        """
        candidates: List[Dict[str, str]] = []
        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        localappdata = os.environ.get("LOCALAPPDATA", os.path.join(user_profile, "AppData", "Local"))
        appdata = os.environ.get("APPDATA", os.path.join(user_profile, "AppData", "Roaming"))
        documents = os.path.join(user_profile, "Documents")
        savedgames = os.path.join(user_profile, "Saved Games")

        # Tập hợp các tên biến thể của game để tìm kiếm
        game_names = set()
        for s in [product, title, os.path.basename(game_dir)]:
            if s:
                clean_s = s.strip()
                game_names.add(clean_s)
                game_names.add(re.sub(r"[:\-_]+", " ", clean_s).strip())
                game_names.add(re.sub(r"[^a-zA-Z0-9]", "", clean_s).strip())

        # 1. Quy tắc Unity Engine: AppData/LocalLow/<Company>/<Product>
        if engine == "Unity" and company and product:
            u_path = os.path.join(user_profile, "AppData", "LocalLow", company, product)
            if os.path.isdir(u_path):
                candidates.append({
                    "slot": "unity_locallow",
                    "path": f"{{LOCALAPPDATA_LOW}}/{company}/{product}"
                })

        # Quét thêm tất cả Company/Product con trong LocalLow nếu là Unity
        if engine == "Unity" and not candidates:
            locallow_root = os.path.join(user_profile, "AppData", "LocalLow")
            if os.path.isdir(locallow_root):
                try:
                    for comp in os.listdir(locallow_root):
                        comp_p = os.path.join(locallow_root, comp)
                        if os.path.isdir(comp_p):
                            for prod in os.listdir(comp_p):
                                for gn in game_names:
                                    if gn.lower() == prod.lower():
                                        candidates.append({
                                            "slot": "unity_locallow",
                                            "path": f"{{LOCALAPPDATA_LOW}}/{comp}/{prod}"
                                        })
                                        break
                except Exception:
                    pass

        # 2. Quy tắc Unreal Engine: Local/<GameFolder>/Saved/SaveGames
        for gn in game_names:
            ue_path = os.path.join(localappdata, gn, "Saved", "SaveGames")
            if os.path.isdir(ue_path):
                candidates.append({
                    "slot": "unreal_saved_games",
                    "path": f"{{LOCALAPPDATA}}/{gn}/Saved/SaveGames"
                })
                break

        # 3. Thư mục Saved Games tiêu chuẩn của Windows
        for gn in game_names:
            sg_path = os.path.join(savedgames, gn)
            if os.path.isdir(sg_path):
                candidates.append({
                    "slot": "windows_saved_games",
                    "path": f"{{SAVEDGAMES}}/{gn}"
                })
                break

        # 4. Thư mục Documents (My Documents)
        for gn in game_names:
            doc_path = os.path.join(documents, gn)
            if os.path.isdir(doc_path):
                candidates.append({
                    "slot": "documents_save",
                    "path": f"{{DOCUMENTS}}/{gn}"
                })
                break
            # Một số game để trong Documents/My Games/<GameName>
            my_games = os.path.join(documents, "My Games", gn)
            if os.path.isdir(my_games):
                candidates.append({
                    "slot": "my_games_save",
                    "path": f"{{DOCUMENTS}}/My Games/{gn}"
                })
                break

        # 5. Thư mục AppData/Roaming hoặc AppData/Local
        for gn in game_names:
            roam_path = os.path.join(appdata, gn)
            if os.path.isdir(roam_path):
                candidates.append({
                    "slot": "appdata_roaming",
                    "path": f"{{APPDATA}}/{gn}"
                })
                break
            loc_path = os.path.join(localappdata, gn)
            if os.path.isdir(loc_path) and not any(c.get("slot") == "unreal_saved_games" for c in candidates):
                candidates.append({
                    "slot": "appdata_local",
                    "path": f"{{LOCALAPPDATA}}/{gn}"
                })
                break

        # 6. Fallback mặc định nếu chưa tìm thấy thư mục nào cụ thể
        if not candidates:
            gn = list(game_names)[0] if game_names else "CustomGame"
            candidates.append({
                "slot": "default_documents",
                "path": f"{{DOCUMENTS}}/{gn}"
            })

        return candidates

    @staticmethod
    def _guess_achievement_locations(steam_appid: str) -> List[Dict[str, str]]:
        """Dò tìm đường dẫn lưu thành tựu theo Steam Emulator (Goldberg, CODEX, RUNE, Tenoke)."""
        if not steam_appid:
            return []

        return [
            {
                "emu": "goldberg",
                "path": f"{{APPDATA}}/Goldberg SteamEmu Saves/{steam_appid}/achievements.json"
            },
            {
                "emu": "codex",
                "path": f"{{PUBLIC_DOCS}}/Steam/CODEX/{steam_appid}/achievements.ini"
            },
            {
                "emu": "rune",
                "path": f"{{PUBLIC_DOCS}}/Steam/RUNE/{steam_appid}/achievements.ini"
            },
            {
                "emu": "onlinefix",
                "path": f"{{PUBLIC_DOCS}}/Steam/OnlineFix/{steam_appid}/stats/achievements.ini"
            }
        ]
