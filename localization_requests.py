# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Trung Tâm Yêu Cầu Việt Hóa Game Lẻ (Non-Steam)
-------------------------------------------------------------------------
Module xử lý tính năng "Yêu Cầu Việt Hóa" cho các tựa game ngoài danh mục
`games.json`, gồm 3 nhiệm vụ chính:

1. QUÉT ENGINE TỰ ĐỘNG (Engine Telemetry):
   Dò nhanh cấu trúc thư mục game trên ổ cứng người chơi để biết game dùng
   Unity (IL2CPP / Mono), Unreal (.pak / .locres), GameMaker (data.win),
   REDengine (.w3strings), Godot (.pck), RPG Maker, Ren'Py, BepInEx...
   => Admin nhìn vào danh sách yêu cầu là biết ngay game dễ hay khó dịch.

2. LƯU VĨNH VIỄN VÀO HỒ SƠ DI ĐỘNG (.congu_save):
   Ghi `player_id`, `localization_requests` và `custom_games` vào
   profile_manifest.json bên trong tệp .congu_save duy nhất, để yêu cầu
   đi theo người chơi sang bất kỳ PC nào khác.

3. ĐỒNG BỘ HAI CHIỀU VỚI MÁY CHỦ:
   - Gửi/đề cử yêu cầu lên bảng nguyện vọng cộng đồng (Firebase RTDB) kèm
     telemetry engine; nếu game đã có người yêu cầu trước đó thì Server
     tự cộng +1 lượt bình chọn.
   - Khi mở app / nạp lại file .congu_save ở PC khác: đối chiếu lại trạng
     thái mới nhất và tự phát hiện game đã có bản Việt Hóa chính thức
     trong games.json để bắn thông báo "Tin vui!" cho người chơi.
"""

import os
import secrets
import threading
from datetime import datetime, timezone

# Giới hạn quét để phản hồi tức thì (< 100ms) kể cả game nặng vài chục GB
MAX_SCAN_DEPTH = 3
MAX_SAMPLE_FILES = 6
MAX_SCAN_ENTRIES = 6000

PRUNE_DIRS = {
    "_commonredist", "redist", "vcredist", "directx", "dotnet", "__pycache__",
    ".git", ".svn", "node_modules", "shadercache", "derivedatacache",
    "logs", "crashreports", "movies", "video", "audio"
}

# Bảng nhận diện Engine: (ưu tiên, điều kiện tên file, nhãn engine, họ engine)
ENGINE_RULES = (
    (100, lambda f, rel: f == "gameassembly.dll",
     "Unity Engine (IL2CPP)", "unity"),
    (98, lambda f, rel: f in ("resources.assets", "sharedassets0.assets", "globalgamemanagers", "level0", "unityplayer.dll"),
     "Unity Engine (Mono / Assets)", "unity"),
    (96, lambda f, rel: f.endswith(".locres"),
     "Unreal Engine (LocRes Text)", "unreal"),
    (94, lambda f, rel: f.endswith(".pak") and ("content/paks" in rel or "/paks/" in rel or rel.startswith("paks/")),
     "Unreal Engine (.pak)", "unreal"),
    (92, lambda f, rel: f in ("engine.dll", "ue4game.exe") or (f.endswith(".pak") and "pak" in rel),
     "Unreal Engine (.pak)", "unreal"),
    (90, lambda f, rel: f == "data.win",
     "GameMaker Studio (data.win)", "gamemaker"),
    (86, lambda f, rel: f.endswith(".w3strings"),
     "REDengine (.w3strings)", "redengine"),
    (84, lambda f, rel: f.endswith(".pck"),
     "Godot Engine (.pck)", "godot"),
    (82, lambda f, rel: f in ("game.rgss3a", "game.rgssad"),
     "RPG Maker (RGSS)", "rpgmaker"),
    (80, lambda f, rel: f.endswith(".rvdata2") or f.endswith(".rxdata") or f.endswith(".rgssad"),
     "RPG Maker (MV / MZ / XP)", "rpgmaker"),
    (78, lambda f, rel: f.endswith(".rpa") or f.endswith(".rpyc") or f.endswith(".rpy"),
     "Ren'Py Engine", "renpy"),
    (74, lambda f, rel: f.endswith(".assets") or f.endswith(".unity3d") or f.endswith(".bundle"),
     "Unity Engine (AssetBundle)", "unity"),
    (72, lambda f, rel: f.endswith(".cpk") or f == "cri_ware_unity.dll",
     "CRI / Custom Engine (.cpk)", "custom"),
    (70, lambda f, rel: f.endswith(".dat") and ("text" in f or "lang" in f or "loc" in f),
     "Custom Engine (.dat text)", "custom"),
)

LANG_ASSET_EXTS = (
    ".locres", ".w3strings", ".po", ".pot", ".csv", ".tsv", ".strings",
    ".resx", ".xliff", ".xlif", ".json.txt", ".txt", ".xml"
)

STATUS_LABELS = {
    "pending": "Đang chờ duyệt",
    "voting": "Đang bình chọn",
    "reviewing": "Đã tiếp nhận",
    "in_progress": "Đang dịch",
    "translating": "Đang dịch",
    "completed": "Đã hoàn thành",
    "rejected": "Đã từ chối",
    "offline": "Đã lưu máy (chờ gửi lại)",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(raw: str) -> str:
    """Chuẩn hóa trạng thái từ nhiều nguồn về bộ trạng thái nội bộ của CỔ NGỮ."""
    s = str(raw or "").strip().lower()
    if s in ("completed", "done", "finished", "hoàn thành"):
        return "completed"
    if s in ("in_progress", "translating", "dang_dich", "đang dịch"):
        return "in_progress"
    if s in ("reviewing", "accepted", "received", "tiếp nhận"):
        return "reviewing"
    if s in ("rejected", "declined", "từ chối"):
        return "rejected"
    if s in ("pending", "voting", "queued", "chờ duyệt"):
        return "pending"
    return "pending"


class LocalizationRequestManager:
    """
    Quản lý vòng đời Yêu cầu Việt hóa cho game lẻ:
    Quét Engine -> Gửi Server (cộng dồn Vote) -> Lưu .congu_save -> Đồng bộ lại khi mở app.
    """

    def __init__(self, vault_getter, games_getter=None,
                 create_community_request=None, get_community_requests=None,
                 cloud_sync=None, logger=None):
        """
        vault_getter: () -> ConguSaveVault
        games_getter: () -> list (danh mục games.json chính thức + custom games)
        create_community_request: (game_key, title, capsule, note) -> dict  (đề cử/bình chọn server)
        get_community_requests: () -> dict {success, items:[...]}  (đọc bảng nguyện vọng)
        cloud_sync: CloudSyncManager (để tự đẩy .congu_save lên Google Drive)
        """
        self.vault_getter = vault_getter
        self.games_getter = games_getter
        self.create_community_request = create_community_request
        self.get_community_requests = get_community_requests
        self.cloud_sync = cloud_sync
        self.logger = logger or (lambda msg: print(msg))
        self._lock = threading.RLock()

    # =========================================================================
    # 1. QUÉT ENGINE & CẤU TRÚC FILE NGÔN NGỮ (ENGINE TELEMETRY)
    # =========================================================================
    @staticmethod
    def inspect_game_engine(game_root: str) -> dict:
        """
        Quét nhanh thư mục game (tối đa 3 tầng) để báo cho Admin biết:
        - Game dùng Engine gì (Unity IL2CPP / Unreal .pak / GameMaker...).
        - Có BepInEx (mod loader) hay không.
        - Các file/thư mục ngôn ngữ tiềm năng để dịch.
        """
        result = {
            "engine": "Unknown / Custom Engine",
            "engine_family": "unknown",
            "confidence": 0,
            "sample_files": [],
            "language_assets": [],
            "has_bepinex": False,
            "scanned_entries": 0,
            "game_root": game_root or ""
        }
        if not game_root or not os.path.isdir(game_root):
            return result

        best_rank = -1
        best_label = result["engine"]
        best_family = "unknown"
        sample_files = []
        lang_assets = []
        scanned = 0

        try:
            for root, dirs, files in os.walk(game_root):
                rel_dir = os.path.relpath(root, game_root)
                if rel_dir == ".":
                    rel_dir = ""
                depth = 0 if not rel_dir else rel_dir.count(os.sep) + 1
                if depth > MAX_SCAN_DEPTH:
                    dirs[:] = []
                    continue

                # Bỏ qua các thư mục rác / quá nặng để quét tức thì
                dirs[:] = [d for d in dirs if d.lower() not in PRUNE_DIRS]

                # BepInEx / Doorstop mod loader
                for d in dirs:
                    if d.lower() == "bepinex":
                        result["has_bepinex"] = True

                for f in files:
                    scanned += 1
                    if scanned > MAX_SCAN_ENTRIES:
                        break

                    f_lower = f.lower()
                    rel_file = (f"{rel_dir}/{f}" if rel_dir else f).replace("\\", "/")

                    if f_lower in ("winhttp.dll", "doorstop_config.ini", "bepinex.dll"):
                        result["has_bepinex"] = True

                    for rank, matcher, label, family in ENGINE_RULES:
                        try:
                            if matcher(f_lower, rel_file.lower()):
                                if rank > best_rank:
                                    best_rank = rank
                                    best_label = label
                                    best_family = family
                                if rel_file not in sample_files and len(sample_files) < MAX_SAMPLE_FILES:
                                    sample_files.append(rel_file)
                                break
                        except Exception:
                            continue

                    # Gom các file ngôn ngữ tiềm năng (giới hạn 8 mục)
                    if len(lang_assets) < 8 and f_lower.endswith(LANG_ASSET_EXTS):
                        lowered = rel_file.lower()
                        if any(k in lowered for k in ("loc", "lang", "text", "string", "dialog", "subtitle", "translat")):
                            lang_assets.append(rel_file)

                if scanned > MAX_SCAN_ENTRIES:
                    break
        except Exception as e:
            result["scan_error"] = str(e)

        result["engine"] = best_label
        result["engine_family"] = best_family
        result["confidence"] = max(0, best_rank)
        result["sample_files"] = sample_files[:MAX_SAMPLE_FILES]
        result["language_assets"] = lang_assets
        result["scanned_entries"] = scanned
        if result["has_bepinex"] and best_family == "unity":
            result["engine"] = "Unity Engine + BepInEx (Mod-friendly)"
        return result

    # =========================================================================
    # 2. TIỆN ÍCH HỒ SƠ (.CONGU_SAVE)
    # =========================================================================
    def _vault(self):
        return self.vault_getter() if self.vault_getter else None

    def _read_manifest(self) -> dict:
        vault = self._vault()
        if not vault:
            return {}
        return vault.read_manifest() or {}

    @staticmethod
    def _ensure_identity(manifest: dict) -> str:
        """Mỗi hồ sơ .congu_save có 1 player_id cố định, đi theo người chơi mọi PC."""
        if not manifest.get("player_id"):
            manifest["player_id"] = "usr_" + secrets.token_hex(8)
        if not manifest.get("player_name"):
            manifest["player_name"] = os.environ.get("USERNAME", "Game Thủ Cổ Ngữ")
        return manifest["player_id"]

    def _sync_drive_async(self, vault):
        """Tự động đẩy file .congu_save mới lên Google Drive nếu người chơi đã kết nối."""
        if not vault or not self.cloud_sync:
            return
        try:
            if not self.cloud_sync.is_connected():
                return
        except Exception:
            return

        def _worker():
            try:
                self.cloud_sync.sync_vault_to_drive(vault.vault_path)
                self.logger(f"[LocalizationRequest] Đã đồng bộ .congu_save lên Google Drive.")
            except Exception as e:
                self.logger(f"[LocalizationRequest] Drive sync warning: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _request_key(game_config: dict) -> str:
        return str(
            game_config.get("steam_appid")
            or game_config.get("id")
            or game_config.get("title")
            or ""
        ).strip()

    # =========================================================================
    # 3. GHI NHẬN YÊU CẦU VÀO FILE .CONGU_SAVE (PERSIST)
    # =========================================================================
    def register_request(self, game_key: str, title: str, steam_appid: str = "",
                         game_id: str = "", executable_name: str = "",
                         detected_engine: str = "", engine_family: str = "unknown",
                         sample_files=None, language_assets=None,
                         has_bepinex: bool = False, user_note: str = "",
                         status: str = "pending", community_votes: int = 1,
                         synced_to_server: bool = False,
                         custom_game: dict = None, extra: dict = None) -> dict:
        """
        Ghi (hoặc cập nhật) 1 yêu cầu Việt hóa vào localization_requests trong
        profile_manifest.json của tệp .congu_save, đồng thời lưu cấu hình
        game lẻ vào custom_games để mang sang PC khác.
        """
        with self._lock:
            vault = self._vault()
            if not vault:
                return {"success": False, "error": "Chưa khởi tạo Hồ Sơ Cổ Ngữ (.congu_save)"}

            manifest = self._read_manifest()
            player_id = self._ensure_identity(manifest)

            reqs = manifest.get("localization_requests")
            if not isinstance(reqs, dict):
                reqs = {}
            manifest["localization_requests"] = reqs

            key = str(game_key or steam_appid or game_id or title).strip()
            existing = reqs.get(key) if isinstance(reqs.get(key), dict) else None

            prev = existing or {}
            record = {
                "game_id": game_id or prev.get("game_id") or key,
                "title": title or prev.get("title", ""),
                "steam_appid": str(steam_appid or prev.get("steam_appid") or ""),
                "executable_name": executable_name or prev.get("executable_name", ""),
                "detected_engine": detected_engine or prev.get("detected_engine") or "Chưa quét",
                "engine_family": engine_family or prev.get("engine_family") or "unknown",
                "has_bepinex": bool(has_bepinex or prev.get("has_bepinex", False)),
                "sample_files": (sample_files or prev.get("sample_files") or [])[:MAX_SAMPLE_FILES],
                "language_assets": (language_assets or prev.get("language_assets") or [])[:8],
                "user_note": ((user_note or "").strip()[:300]) or prev.get("user_note", ""),
                "requested_at": prev.get("requested_at") or _now_iso(),
                "updated_at": _now_iso(),
                "status": normalize_status(status),
                "server_status": str(status or prev.get("server_status") or "pending"),
                "status_label": STATUS_LABELS.get(normalize_status(status), "Đang chờ duyệt"),
                "community_votes": int(community_votes or prev.get("community_votes") or 1),
                "request_ticket_id": prev.get("request_ticket_id")
                                       or ("CGR-" + secrets.token_hex(4).upper()),
                "player_id": player_id,
                "synced_to_server": bool(synced_to_server),
            }
            if existing and existing.get("official_game_id"):
                record["official_game_id"] = existing["official_game_id"]
            if extra and isinstance(extra, dict):
                record.update(extra)
            reqs[key] = record

            # Lưu luôn cấu hình game lẻ vào custom_games (mang sang PC khác)
            if custom_game and custom_game.get("id"):
                cg_store = manifest.get("custom_games")
                if not isinstance(cg_store, dict):
                    cg_store = {}
                manifest["custom_games"] = cg_store
                prev_cg = cg_store.get(custom_game["id"]) if isinstance(cg_store.get(custom_game["id"]), dict) else {}
                slim = {
                    "title": custom_game.get("title") or prev_cg.get("title", ""),
                    "steam_appid": str(custom_game.get("steam_appid") or prev_cg.get("steam_appid") or ""),
                    "executable_name": custom_game.get("executable_name") or prev_cg.get("executable_name", ""),
                    "engine": custom_game.get("engine") or prev_cg.get("engine", ""),
                    "last_known_root": (custom_game.get("game_root") or "").replace("\\", "/") or prev_cg.get("last_known_root", ""),
                    "vault_config": custom_game.get("vault_config") or prev_cg.get("vault_config", {})
                }
                cg_store[custom_game["id"]] = slim

            write_res = vault.update_manifest_only(manifest)
            if not write_res.get("success"):
                return {"success": False, "error": write_res.get("error", "Không ghi được Hồ Sơ (.congu_save)")}

            self._sync_drive_async(vault)
            return {"success": True, "request": record, "already_existed": bool(existing)}

    # =========================================================================
    # 4. GỬI YÊU CẦU LÊN SERVER + LƯU VÀO HỒ SƠ
    # =========================================================================
    def submit_game_request(self, game_config: dict, game_root: str = "",
                            user_note: str = "") -> dict:
        """
        Luồng đầy đủ khi người chơi bấm [Yêu Cầu Việt Hóa] trên 1 game lẻ:
        1. Kiểm tra trùng lặp trong hồ sơ (kể cả yêu cầu từ PC cũ).
        2. Quét Engine + file ngôn ngữ trên ổ cứng (telemetry).
        3. Đề cử/bình chọn lên máy chủ (game mới +1 Vote, game đã có thì cộng dồn Vote).
        4. Lưu vĩnh viễn vào .congu_save + tự đẩy Google Drive.
        """
        game_config = dict(game_config or {})
        key = self._request_key(game_config)
        if not key:
            return {"success": False, "message": "Không xác định được tựa game cần yêu cầu!"}

        # 1. Chống gửi trùng lặp (Hồ sơ đã có yêu cầu này từ bất kỳ PC nào)
        manifest = self._read_manifest()
        existing = (manifest.get("localization_requests") or {}).get(key)
        if isinstance(existing, dict):
            return {
                "success": False,
                "already_requested": True,
                "message": (f"Bạn đã gửi yêu cầu Việt hóa cho '{existing.get('title') or game_config.get('title')}' "
                            f"trong Hồ Sơ Cổ Ngữ rồi! ({STATUS_LABELS.get(existing.get('status'), 'Đang chờ duyệt')})"),
                "request_data": existing
            }

        if not game_root:
            game_root = game_config.get("game_root") or ""

        # 2. Quét Engine
        engine_info = self.inspect_game_engine(game_root)

        title = game_config.get("vietnamese_title") or game_config.get("title") or key
        capsule = (game_config.get("cover_url") or game_config.get("local_cover")
                   or game_config.get("header_url") or "")

        # 3. Gửi lên máy chủ (nếu có cấu hình)
        server = {}
        if self.create_community_request:
            try:
                server = self.create_community_request(key, title, capsule, user_note) or {}
            except Exception as e:
                server = {"success": False, "error": str(e)}

        item = server.get("item") if isinstance(server.get("item"), dict) else {}
        votes = item.get("votes") or server.get("votes") or 1
        raw_status = item.get("status") or "voting"
        synced = bool(server.get("success"))

        # 4. Ghi vào .congu_save
        reg = self.register_request(
            game_key=key,
            title=title,
            steam_appid=str(game_config.get("steam_appid") or ""),
            game_id=game_config.get("id", ""),
            executable_name=game_config.get("executable_name", ""),
            detected_engine=engine_info.get("engine", ""),
            engine_family=engine_info.get("engine_family", "unknown"),
            sample_files=engine_info.get("sample_files"),
            language_assets=engine_info.get("language_assets"),
            has_bepinex=engine_info.get("has_bepinex", False),
            user_note=user_note,
            status=raw_status,
            community_votes=votes,
            synced_to_server=synced,
            custom_game=game_config,
        )
        if not reg.get("success"):
            return {"success": False, "message": reg.get("error", "Không lưu được yêu cầu vào Hồ Sơ!")}

        action = server.get("action") or ("created" if synced else "offline")
        if not synced:
            message = ("Đã lưu yêu cầu Việt hóa vào Hồ Sơ Cổ Ngữ (.congu_save)! "
                       "Hiện chưa kết nối được máy chủ, yêu cầu sẽ được gửi bù khi có mạng.")
        elif action == "voted":
            message = f"Đã bình chọn (+1 Vote) cho '{title}'! Cộng đồng hiện có {votes} lượt yêu cầu tựa game này."
        elif action == "already_exists":
            message = f"'{title}' đã có trên bảng nguyện vọng ({votes} Vote) và đã lưu vào Hồ Sơ của bạn!"
        else:
            message = f"Đã gửi yêu cầu Việt hóa '{title}' lên máy chủ và lưu vào Hồ Sơ Cổ Ngữ của bạn!"

        return {
            "success": True,
            "already_requested": False,
            "action": action,
            "synced_to_server": synced,
            "message": message,
            "request_data": reg.get("request"),
            "engine_info": engine_info,
        }

    # =========================================================================
    # 5. ĐỌC DANH SÁCH YÊU CẦU CỦA TÔI (GHÉP TRẠNG THÁI SERVER + games.json)
    # =========================================================================
    def list_requests(self, live_items=None, official_games=None) -> dict:
        """
        Trả về danh sách yêu cầu Việt hóa đọc từ .congu_save, đã ghép:
        - Số lượt Vote & trạng thái mới nhất từ máy chủ (live_items).
        - Cờ "đã có bản Việt Hóa chính thức" nếu game nay nằm trong games.json.
        """
        manifest = self._read_manifest()
        reqs = manifest.get("localization_requests")
        if not isinstance(reqs, dict):
            reqs = {}

        live_index = {}
        for it in (live_items or []):
            if isinstance(it, dict) and it.get("id") is not None:
                live_index[str(it.get("id"))] = it

        off_by_appid, off_by_title = {}, {}
        for g in (official_games or []):
            if not isinstance(g, dict) or g.get("is_custom_game"):
                continue
            appid = str(g.get("steam_appid") or "").strip()
            if appid:
                off_by_appid[appid] = g
            t = (g.get("title") or "").strip().lower()
            if t:
                off_by_title.setdefault(t, g)

        items = []
        for key, rec in reqs.items():
            if not isinstance(rec, dict):
                continue
            item = dict(rec)
            item["request_key"] = key

            live = live_index.get(str(key)) or live_index.get(str(rec.get("game_id") or ""))
            if live:
                if isinstance(live.get("votes"), (int, float)):
                    item["community_votes"] = int(live["votes"])
                if live.get("status"):
                    item["server_status"] = str(live["status"])
                    item["status"] = normalize_status(live["status"])
                if live.get("name"):
                    item["server_name"] = live["name"]
                if live.get("capsule"):
                    item["capsule"] = live["capsule"]
                item["has_voted"] = bool(live.get("has_voted", item.get("has_voted", False)))

            appid = str(rec.get("steam_appid") or "").strip()
            matched = (off_by_appid.get(appid)
                       or off_by_appid.get(str(key).strip())
                       or off_by_title.get((rec.get("title") or "").strip().lower()))
            if matched:
                item["is_official_available"] = True
                item["official_game_id"] = matched.get("id")
                item["vietnamese_title"] = matched.get("vietnamese_title") or matched.get("title")
                item["status"] = "completed"
            else:
                item.setdefault("is_official_available",
                                item.get("status") == "completed" and bool(item.get("official_game_id")))

            item["status_label"] = STATUS_LABELS.get(item.get("status"), "Đang chờ duyệt")
            item.setdefault("capsule", "")
            items.append(item)

        items.sort(key=lambda x: (0 if x.get("status") == "completed" else 1,
                                  -(x.get("community_votes") or 0)))
        return {
            "player_id": manifest.get("player_id", ""),
            "player_name": manifest.get("player_name", ""),
            "total": len(items),
            "items": items,
            "vault_updated_at": manifest.get("updated_at")
        }

    def get_my_history(self) -> list:
        """Danh sách gọn các game đã được người chơi yêu cầu (dùng cho UI local)."""
        return self.list_requests().get("items", [])

    # =========================================================================
    # 6. ĐỒNG BỘ KHI MỞ APP / NẠP LẠI .CONGU_SAVE Ở PC KHÁC
    # =========================================================================
    def sync_with_official(self, official_games=None, live_items=None) -> dict:
        """
        Đối chiếu localization_requests trong hồ sơ với games.json chính thức:
        - Nếu game từng yêu cầu nay đã có bản Việt Hóa => đánh dấu completed và
          trả về thông báo "Tin vui!" để app hiển thị cho người chơi.
        - Cập nhật song song trạng thái tiến độ dịch mới nhất từ máy chủ.
        """
        if official_games is None and self.games_getter:
            try:
                official_games = self.games_getter() or []
            except Exception:
                official_games = []

        live_items = live_items
        if live_items is None and self.get_community_requests:
            try:
                live = self.get_community_requests() or {}
                if live.get("success"):
                    live_items = live.get("items") or []
            except Exception:
                live_items = []

        with self._lock:
            vault = self._vault()
            notifications = []
            changed = False
            if vault:
                manifest = self._read_manifest()
                player_id = self._ensure_identity(manifest)
                reqs = manifest.get("localization_requests")
                if isinstance(reqs, dict) and reqs:
                    off_by_appid, off_by_title = {}, {}
                    for g in (official_games or []):
                        if not isinstance(g, dict) or g.get("is_custom_game"):
                            continue
                        appid = str(g.get("steam_appid") or "").strip()
                        if appid:
                            off_by_appid[appid] = g
                        t = (g.get("title") or "").strip().lower()
                        if t:
                            off_by_title.setdefault(t, g)

                    for key, rec in reqs.items():
                        if not isinstance(rec, dict):
                            continue
                        appid = str(rec.get("steam_appid") or "").strip()
                        matched = (off_by_appid.get(appid)
                                   or off_by_appid.get(str(key).strip())
                                   or off_by_title.get((rec.get("title") or "").strip().lower()))
                        if not matched:
                            continue
                        rec["official_game_id"] = matched.get("id")
                        rec["vietnamese_title"] = matched.get("vietnamese_title") or matched.get("title")
                        if rec.get("status") != "completed":
                            rec["status"] = "completed"
                            rec["server_status"] = "completed"
                            rec["status_label"] = STATUS_LABELS["completed"]
                            rec["completed_at"] = _now_iso()
                            changed = True
                            notifications.append({
                                "title": rec.get("title"),
                                "vietnamese_title": rec.get("vietnamese_title") or rec.get("title"),
                                "official_game_id": matched.get("id"),
                                "capsule": matched.get("local_cover") or matched.get("header_url") or "",
                                "message": (f"Tin vui! Tựa game '{matched.get('vietnamese_title') or matched.get('title')}' "
                                            f"bạn yêu cầu đã có bản Việt Hóa chính thức! Bấm để cài đặt ngay.")
                            })

                    # Ghi lại nếu trạng thái thay đổi
                    if changed:
                        manifest["player_id"] = player_id
                        vault.update_manifest_only(manifest)
                        self._sync_drive_async(vault)

            listed = self.list_requests(live_items=live_items, official_games=official_games)
            return {
                "changed": changed,
                "notifications": notifications,
                "items": listed.get("items", []),
                "total": listed.get("total", 0),
                "player_id": listed.get("player_id", "")
            }

    # =========================================================================
    # 7. DỌN DẸP
    # =========================================================================
    def forget_request(self, request_key: str) -> dict:
        """Xóa 1 yêu cầu khỏi hồ sơ (không hủy vote đã gửi lên server)."""
        with self._lock:
            vault = self._vault()
            manifest = self._read_manifest()
            reqs = manifest.get("localization_requests")
            if not vault or not isinstance(reqs, dict) or request_key not in reqs:
                return {"success": False, "message": "Không tìm thấy yêu cầu này trong Hồ Sơ!"}
            reqs.pop(request_key, None)
            res = vault.update_manifest_only(manifest)
            if res.get("success"):
                self._sync_drive_async(vault)
            return {"success": bool(res.get("success")), "message": "Đã xóa yêu cầu khỏi Hồ Sơ Cổ Ngữ."}
