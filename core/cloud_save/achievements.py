# -*- coding: utf-8 -*-
"""
Core Cloud Save - Achievements Engine
"""
import os
import sys
import time
import json
import re
import glob
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from core.steam_client import steam_direct_request
from core.scanner import extract_local_steam_appid
from . import process_utils as pu
from .process_utils import _internal_log, get_default_appdata_dir


class AchievementManager:
    """
    Bộ quản lý phát hiện, đọc tiến độ và đồng bộ Thành tựu cho game lẻ
    theo chuẩn cơ chế không can thiệp RAM của Hydra Launcher & Achievement Watcher.
    Hỗ trợ tự động nhận diện Emulator: Goldberg, GSE, RUNE, CODEX, TENOKE, OnlineFix, FLT, ALI213, SmartSteamEmu.
    """

    def __init__(self, steam_api_key: str = "", appdata_dir: str = None):
        self.appdata_dir = appdata_dir or get_default_appdata_dir()
        self.schema_dir = os.path.join(self.appdata_dir, "achievements_schema")
        self.progress_file = os.path.join(self.appdata_dir, "achievements_progress.json")
        os.makedirs(self.schema_dir, exist_ok=True)
        self.steam_api_key = steam_api_key
        self.lock = threading.RLock()
        self.unlocked_cache = {}  # {appid_or_gid: {"ACH_ID": ts, ...}}
        self.newly_unlocked_queue = []  # [{"game_id": ..., "id": ..., "title": ..., "description": ..., "icon": ...}]
        self._progress_data = self._load_progress()

    def _load_progress(self) -> dict:
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_progress(self):
        with self.lock:
            try:
                tmp = self.progress_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._progress_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.progress_file)
            except Exception:
                pass

    def _resolve_appid_from_metadata(self, game_id: str) -> str:
        """Tìm steam_appid của game từ custom_games.json hoặc games.json."""
        if not game_id:
            return ""
        # 1. Kiểm tra custom_games.json
        try:
            if pu._CUSTOM_GAMES_GETTER:
                for cg in pu._CUSTOM_GAMES_GETTER():
                    if cg.get("id") == game_id:
                        aid = str(cg.get("steam_appid") or "").strip()
                        if aid:
                            return aid
        except Exception:
            pass
        # 2. Kiểm tra games.json
        try:
            p = pu._GAMES_JSON_PATH_GETTER() if pu._GAMES_JSON_PATH_GETTER else "games.json"
            if p and os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for g in json.load(f):
                        if g.get("id") == game_id:
                            return str(g.get("steam_appid") or "").strip()
        except Exception:
            pass
        return ""

    def _get_candidate_save_files(self, appid: str, game_dir: str = "") -> List[Tuple[str, str]]:
        """Trả về danh sách các đường dẫn file lưu thành tựu có thể tồn tại của mọi Steam Emulator."""
        if not appid and not game_dir:
            return []

        candidates = []
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        public_doc = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents")
        user_profile = os.environ.get("USERPROFILE", "")
        documents = os.path.join(user_profile, "Documents")

        if appid:
            s_appid = str(appid)
            candidates.extend([
                # 1. Goldberg / GSE Saves (Định dạng JSON)
                ("goldberg_json", os.path.join(appdata, "Goldberg SteamEmu Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(appdata, "GSE Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(localappdata, "Goldberg SteamEmu Saves", s_appid, "achievements.json")),
                ("goldberg_json", os.path.join(localappdata, "GSE Saves", s_appid, "achievements.json")),
                # 2. RUNE / CODEX / FLT / OnlineFix / SmartSteamEmu (Định dạng INI)
                ("ini", os.path.join(public_doc, "Steam", "RUNE", s_appid, "achievements.ini")),
                ("ini", os.path.join(public_doc, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(appdata, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(public_doc, "OnlineFix", s_appid, "Stats", "Achievements.ini")),
                ("ini", os.path.join(appdata, "FLT", s_appid, "stats", "achievements.ini")),
                ("ini", os.path.join(appdata, "SmartSteamEmu", s_appid, "achievements.ini")),
                ("ini", os.path.join(appdata, "SmartSteamEmu", s_appid, "stats", "achievements.ini")),
                ("ini", os.path.join(documents, "Steam", "CODEX", s_appid, "achievements.ini")),
                ("ini", os.path.join(documents, "Steam", "RUNE", s_appid, "achievements.ini")),
                ("ini", os.path.join(documents, "OnlineFix", s_appid, "Stats", "Achievements.ini")),
            ])

        # 3. Các file lưu ngay bên trong thư mục cài đặt game (TENOKE, ALI213, OnlineFix portable, Goldberg local)
        if game_dir and os.path.isdir(game_dir):
            for pattern, fmt in [
                ("**/steam_settings/achievements.json", "goldberg_local_schema"),
                ("**/SteamData/user_stats.ini", "tenoke_ini"),
                ("**/Profile/Stats/Achievements.ini", "ini"),
                ("**/OnlineFix/**/Achievements.ini", "ini"),
                ("**/achievements.ini", "ini"),
                ("**/achievements.json", "goldberg_json"),
            ]:
                try:
                    for found_path in glob.glob(os.path.join(game_dir, pattern), recursive=True):
                        item = (fmt, found_path)
                        if fmt != "goldberg_local_schema" and item not in candidates:
                            candidates.append(item)
                except Exception:
                    pass

        return candidates

    def scan_unlocked_achievements(self, appid: str, game_dir: str = "") -> Dict[str, int]:
        """
        Quét toàn bộ các nguồn emulator và trả về dict: { "ACH_ID": unlock_timestamp }
        """
        unlocked = {}
        for fmt, file_path in self._get_candidate_save_files(str(appid or ""), game_dir):
            if not os.path.isfile(file_path):
                continue
            try:
                mtime_fallback = int(os.path.getmtime(file_path))
                if fmt == "goldberg_json":
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for ach_id, info in data.items():
                            if isinstance(info, dict):
                                if info.get("earned") is True or info.get("unlocked") is True:
                                    ts = int(info.get("earned_time") or info.get("time") or mtime_fallback)
                                    unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)
                            elif isinstance(info, (int, float)) and info > 0:
                                unlocked[ach_id] = min(unlocked.get(ach_id, int(info)), int(info))
                            elif info is True:
                                unlocked[ach_id] = min(unlocked.get(ach_id, mtime_fallback), mtime_fallback)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                ach_id = item.get("name") or item.get("id")
                                if ach_id and (item.get("earned") is True or item.get("unlocked") is True):
                                    ts = int(item.get("earned_time") or item.get("time") or mtime_fallback)
                                    unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)

                elif fmt == "tenoke_ini":
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    for match in re.finditer(r'"([^"]+)"\s*=\s*\{[^}]*unlocked\s*=\s*true(?:[^}]*time\s*=\s*(\d+))?', text, re.I):
                        ach_id = match.group(1)
                        ts = int(match.group(2)) if match.group(2) else mtime_fallback
                        unlocked[ach_id] = min(unlocked.get(ach_id, ts), ts)

                elif fmt == "ini":
                    import configparser
                    cp = configparser.ConfigParser(strict=False)
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        cp.read_file(f)
                    for section in cp.sections():
                        sec_lower = section.lower()
                        if sec_lower in ("steamachievements", "achievements", "stats"):
                            for k, v in cp.items(section):
                                if v.strip().lower() in ("1", "true") and not k.isdigit():
                                    unlocked[k] = min(unlocked.get(k, mtime_fallback), mtime_fallback)
                            continue
                        achieved_val = (
                            cp.get(section, "Achieved", fallback=None)
                            or cp.get(section, "achieved", fallback=None)
                            or cp.get(section, "State", fallback="0")
                        )
                        if str(achieved_val).strip().lower() in ("1", "true"):
                            ts_str = (
                                cp.get(section, "UnlockTime", fallback=None)
                                or cp.get(section, "Timestamp", fallback=None)
                                or cp.get(section, "Time", fallback="0")
                            )
                            ts = int(ts_str) if str(ts_str).isdigit() and int(ts_str) > 0 else mtime_fallback
                            unlocked[section] = min(unlocked.get(section, ts), ts)
            except Exception:
                continue

        return unlocked

    def get_or_fetch_schema(self, appid: str, game_dir: str = "", game_id: str = "") -> List[Dict[str, Any]]:
        """Lấy danh sách thành tựu gốc (Tên, Mô tả, Icon) từ Cache, thư mục game hoặc Steam Store API."""
        if not appid and not game_id:
            return []

        # 0. Kiểm tra cache theo appid hoặc game_id (chỉ chấp nhận nếu có cách thực hiện / description)
        for ckey in [appid, game_id]:
            if not ckey:
                continue
            cache_file = os.path.join(self.schema_dir, f"{ckey}.json")
            if os.path.isfile(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data and isinstance(data, list) and any(bool(item.get("description")) for item in data):
                            return data
                except Exception:
                    pass

        schema_list = []

        # 1. Nguồn 1: Quét trực tiếp file steam_settings/achievements.json có sẵn trong thư mục game lẻ (Offline 0s)
        if game_dir and os.path.isdir(game_dir):
            for pattern in ["**/steam_settings/achievements.json", "**/achievements.json"]:
                for path in glob.glob(os.path.join(game_dir, pattern), recursive=True):
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            raw = json.load(f)
                        if isinstance(raw, list):
                            for item in raw:
                                if not isinstance(item, dict):
                                    continue
                                ach_id = item.get("name") or item.get("id")
                                if not ach_id:
                                    continue
                                disp_name = item.get("displayName", item.get("name", ""))
                                if isinstance(disp_name, dict):
                                    disp_name = disp_name.get("english", next(iter(disp_name.values()), ""))
                                desc = item.get("description", "")
                                if isinstance(desc, dict):
                                    desc = desc.get("english", next(iter(desc.values()), ""))

                                icon_val = item.get("icon", "")
                                icongray_val = item.get("icongray", item.get("icon_gray", ""))
                                if icon_val and not icon_val.startswith("http") and os.path.exists(os.path.join(os.path.dirname(path), icon_val)):
                                    icon_val = os.path.abspath(os.path.join(os.path.dirname(path), icon_val))
                                if icongray_val and not icongray_val.startswith("http") and os.path.exists(os.path.join(os.path.dirname(path), icongray_val)):
                                    icongray_val = os.path.abspath(os.path.join(os.path.dirname(path), icongray_val))

                                schema_list.append({
                                    "id": ach_id,
                                    "title": disp_name or ach_id,
                                    "description": desc or "",
                                    "icon": icon_val,
                                    "icongray": icongray_val,
                                    "hidden": bool(item.get("hidden", 0)),
                                    "group": item.get("group", "")
                                })
                            if schema_list:
                                break
                    except Exception:
                        pass
                if schema_list:
                    break

        pct_map = {}
        if appid and str(appid).isdigit():
            try:
                pct_url = f"https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
                raw_pct = steam_direct_request(pct_url, timeout=4.0)
                if raw_pct:
                    pct_data = json.loads(raw_pct.decode("utf-8", "ignore"))
                    for p in pct_data.get("achievementpercentages", {}).get("achievements", []):
                        pct_map[p["name"].lower()] = round(float(p.get("percent", 0)), 1)
            except Exception:
                pass

        # 2. Nguồn 2: Steam Community SSR Data (Toàn bộ 100% Thành tựu + DLC Packs)
        if not schema_list and appid and str(appid).isdigit():
            try:
                comm_url = f"https://steamcommunity.com/achievements/{appid}"
                raw_comm = steam_direct_request(comm_url, timeout=5.0)
                if raw_comm:
                    html_text = raw_comm.decode("utf-8", "ignore")
                    m = re.search(r'<script[^>]*id=["\']valve-ssr-data["\'][^>]*>(.*?)</script>', html_text, re.DOTALL)
                    if m:
                        root_data = json.loads(m.group(1).strip())
                        query_data_raw = root_data.get("renderContext", {}).get("queryData", {})
                        if isinstance(query_data_raw, str):
                            query_data = json.loads(query_data_raw)
                        else:
                            query_data = query_data_raw or {}

                        for q in query_data.get("queries", []):
                            data_node = q.get("state", {}).get("data")
                            if isinstance(data_node, dict) and "groups" in data_node:
                                for g in data_node.get("groups", []):
                                    group_title = g.get("name") or ""
                                    for a in g.get("achievements", []):
                                        ach_id = a.get("api_name")
                                        if not ach_id:
                                            continue
                                        disp_name = a.get("name") or ach_id
                                        desc = a.get("description") or ""
                                        icon_url = a.get("icon_achieved") or ""
                                        icongray_url = a.get("icon_unachieved") or icon_url
                                        is_hidden = bool(a.get("hidden", False))
                                        schema_list.append({
                                            "id": ach_id,
                                            "title": disp_name,
                                            "description": desc,
                                            "icon": icon_url,
                                            "icongray": icongray_url,
                                            "hidden": is_hidden,
                                            "group": group_title,
                                            "global_percent": pct_map.get(ach_id.lower(), None)
                                        })
            except Exception as e:
                print(f"[AchievementManager] Steam Community SSR fetch error: {e}")

        # 3. Nguồn 3: Nếu có Steam Web API Key
        if not schema_list and self.steam_api_key and appid and str(appid).isdigit():
            try:
                url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={self.steam_api_key}&appid={appid}&l=english"
                raw_s = steam_direct_request(url, timeout=4.0)
                if raw_s:
                    data = json.loads(raw_s.decode("utf-8", "ignore"))
                    raw_ach = data.get("game", {}).get("availableGameStats", {}).get("achievements", [])
                    for a in raw_ach:
                        ach_id = a.get("name")
                        schema_list.append({
                            "id": ach_id,
                            "title": a.get("displayName", ach_id),
                            "description": a.get("description", ""),
                            "icon": a.get("icon", ""),
                            "icongray": a.get("icongray", ""),
                            "hidden": bool(a.get("hidden", 0)),
                            "global_percent": pct_map.get(str(ach_id).lower(), None)
                        })
            except Exception:
                pass

        # 4. Nguồn 4: Fallback qua Steam Store API appdetails
        if not schema_list and appid and str(appid).isdigit():
            try:
                details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=achievements"
                raw_det = steam_direct_request(details_url, timeout=4.0)
                if raw_det:
                    det = json.loads(raw_det.decode("utf-8", "ignore"))
                    app_info = det.get(str(appid), {}) if isinstance(det, dict) else {}
                    data_obj = app_info.get("data") if isinstance(app_info, dict) else {}
                    ach_data = data_obj.get("achievements") if isinstance(data_obj, dict) else {}
                    highlighted = ach_data.get("highlighted", []) if isinstance(ach_data, dict) else []
                    for a in highlighted:
                        ach_name = a.get("name") or a.get("localized_name")
                        icon_url = a.get("path")
                        if not icon_url and a.get("icon"):
                            icon_url = f"https://shared.akamai.steamstatic.com/community_assets/images/apps/{appid}/{a['icon']}"
                        schema_list.append({
                            "id": a.get("name", ach_name),
                            "title": a.get("localized_name") or ach_name,
                            "description": "",
                            "icon": icon_url or "",
                            "icongray": "",
                            "hidden": bool(a.get("hidden", 0)),
                            "global_percent": pct_map.get(str(a.get("name", ach_name)).lower(), None)
                        })
            except Exception as e:
                print(f"[AchievementManager] Store API fetch error: {e}")

        # Gắn thêm tỷ lệ global_percent nếu chưa có
        for s in schema_list:
            if s.get("global_percent") is None:
                s["global_percent"] = pct_map.get(str(s.get("id", "")).lower(), None)

        # Lưu cache nếu lấy được schema có cách thực hiện
        if schema_list:
            save_key = appid or game_id
            cache_file = os.path.join(self.schema_dir, f"{save_key}.json")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(schema_list, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

        return schema_list

    def get_game_achievements_view(self, appid: str = "", game_dir: str = "", game_id: str = "") -> dict:
        """Hàm trả dữ liệu hoàn chỉnh cho Frontend static/index.html hiển thị."""
        # 1. Tự động tìm game_dir từ user_config hoặc custom_games.json
        if not game_dir and game_id:
            if pu._CONFIG_GETTER:
                cfg = pu._CONFIG_GETTER()
                game_dir = cfg.get(f"{game_id}_path", "")
            if not game_dir and pu._CUSTOM_GAMES_GETTER:
                try:
                    for cg in pu._CUSTOM_GAMES_GETTER():
                        if cg.get("id") == game_id:
                            game_dir = cg.get("game_root", "")
                            break
                except Exception:
                    pass

        # 2. Tự động xác định effective_appid
        effective_appid = str(appid or "").strip()
        if not effective_appid and game_dir:
            effective_appid = extract_local_steam_appid(game_dir) or ""
        if not effective_appid and game_id:
            effective_appid = self._resolve_appid_from_metadata(game_id)

        schema = self.get_or_fetch_schema(effective_appid, game_dir, game_id)
        unlocked_map = self.scan_unlocked_achievements(effective_appid, game_dir) if (effective_appid or game_dir) else {}

        # Nếu chưa có schema nhưng file save có danh sách mã thành tựu đã mở
        schema_ids = {str(item.get("id", "")).lower(): item for item in schema if item.get("id")}
        for unlocked_id, u_ts in unlocked_map.items():
            if unlocked_id.lower() not in schema_ids:
                clean_title = re.sub(r"[_\-]+", " ", unlocked_id).title()
                schema.append({
                    "id": unlocked_id,
                    "title": clean_title,
                    "description": "Thành tựu đạt được trong khi chơi game",
                    "icon": "",
                    "icongray": "",
                    "hidden": False
                })

        items = []
        unlocked_count = 0
        unlocked_lower = {k.lower(): v for k, v in unlocked_map.items()}

        for ach in schema:
            ach_id = ach.get("id", "")
            unlock_ts = unlocked_lower.get(ach_id.lower())
            is_unlocked = unlock_ts is not None
            if is_unlocked:
                unlocked_count += 1

            unlock_str = None
            if unlock_ts:
                try:
                    unlock_str = datetime.fromtimestamp(unlock_ts).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    unlock_str = "Đã mở khóa"

            items.append({
                "id": ach_id,
                "title": ach.get("title_vi") or ach.get("title") or ach_id,
                "description": ach.get("description_vi") or ach.get("description") or "",
                "icon": ach.get("icon") if is_unlocked else (ach.get("icongray") or ach.get("icon")),
                "unlocked": is_unlocked,
                "unlock_ts": unlock_ts or 0,
                "unlock_time_str": unlock_str,
                "global_percent": ach.get("global_percent", None),
                "hidden": bool(ach.get("hidden", False)),
                "group": ach.get("group", "")
            })

        # Sắp xếp: Thành tựu đã mở khóa lên trước (mới nhất xếp trên cùng)
        items.sort(key=lambda x: (not x["unlocked"], -x["unlock_ts"]))
        total = len(items)
        percent = int(round((unlocked_count / total) * 100)) if total > 0 else 0

        # Cập nhật cache trạng thái
        cache_key = effective_appid or game_id
        if cache_key:
            with self.lock:
                self.unlocked_cache[cache_key] = unlocked_map
                self._progress_data[cache_key] = {
                    "total": total,
                    "unlocked_count": unlocked_count,
                    "percent": percent,
                    "last_updated": int(time.time())
                }
                self._save_progress()

        return {
            "appid": effective_appid,
            "game_id": game_id,
            "total": total,
            "unlocked_count": unlocked_count,
            "percent": percent,
            "achievements": items
        }

    def check_for_new_unlocks(self, game_id: str, appid: str, game_dir: str = "") -> list:
        """Kiểm tra thời gian thực xem có thành tựu nào vừa được mở khóa không."""
        if not appid and not game_dir:
            return []

        effective_appid = str(appid or "").strip()
        if not effective_appid and game_dir:
            effective_appid = extract_local_steam_appid(game_dir) or ""

        cache_key = effective_appid or game_id
        if not cache_key:
            return []

        current_unlocked = self.scan_unlocked_achievements(effective_appid, game_dir)
        if not current_unlocked:
            return []

        new_items = []
        with self.lock:
            prev_unlocked = self.unlocked_cache.get(cache_key)
            if prev_unlocked is None:
                self.unlocked_cache[cache_key] = current_unlocked
                return []

            schema = self.get_or_fetch_schema(effective_appid, game_dir, game_id)
            schema_map = {str(item.get("id", "")).lower(): item for item in schema}

            for ach_id, ts in current_unlocked.items():
                if ach_id.lower() not in {k.lower(): v for k, v in prev_unlocked.items()}:
                    meta = schema_map.get(ach_id.lower(), {})
                    title = meta.get("title_vi") or meta.get("title") or re.sub(r"[_\-]+", " ", ach_id).title()
                    desc = meta.get("description_vi") or meta.get("description") or "Mở khóa khi chơi game"
                    icon = meta.get("icon") or ""

                    item_info = {
                        "game_id": game_id,
                        "appid": effective_appid,
                        "id": ach_id,
                        "title": title,
                        "description": desc,
                        "icon": icon,
                        "unlock_ts": ts
                    }
                    new_items.append(item_info)
                    self.newly_unlocked_queue.append(item_info)
                    _internal_log(f"[AchievementTracker] 🏆 Chúc mừng! Mở khóa thành tựu mới: '{title}' ({ach_id})!")

            self.unlocked_cache[cache_key] = current_unlocked

        return new_items

    def check_game_live_achievements(self, game_id: str, game_dir: str = "") -> list:
        """Tự động phân giải appid và quét thành tựu mới mở khóa trong thời gian thực."""
        appid = ""
        if game_dir and os.path.isdir(game_dir):
            appid = extract_local_steam_appid(game_dir) or ""
        if not appid and game_id:
            if pu._CONFIG_GETTER:
                cfg = pu._CONFIG_GETTER()
                g_path = cfg.get(f"{game_id}_path")
                if g_path and os.path.isdir(g_path):
                    appid = extract_local_steam_appid(g_path) or ""
            if not appid:
                appid = self._resolve_appid_from_metadata(game_id)

        return self.check_for_new_unlocks(game_id, appid, game_dir)

    def pop_newly_unlocked(self) -> list:
        """Lấy toàn bộ danh sách thành tựu mới để Frontend hiện Toast thông báo, sau đó xóa hàng đợi."""
        with self.lock:
            items = list(self.newly_unlocked_queue)
            self.newly_unlocked_queue.clear()
            return items



ACHIEVEMENT_MGR = AchievementManager()
