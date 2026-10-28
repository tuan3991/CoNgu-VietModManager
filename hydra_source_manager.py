import os
import sys
import re
import json
import time
import urllib.request
import threading
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional

DEFAULT_HYDRA_SOURCES = [
    "https://hydralinks.cloud/sources/fitgirl.json",
    "https://hydralinks.cloud/sources/dodi.json",
    "https://hydralinks.cloud/sources/gog.json",
    "https://hydralinks.cloud/sources/onlinefix.json",
    "https://hydralinks.cloud/sources/tinyrepacks.json",
    "https://hydralinks.cloud/sources/xatab.json",
    "https://hydralinks.cloud/sources/steamrip.json"
]


KNOWN_GAME_METADATA = {
    "god of war": {
        "title": "God of War",
        "steam_appid": "1593500",
        "genres": "Action, Adventure, RPG",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1593500/header.jpg"
    },
    "god of war iii remastered": {
        "title": "God of War III Remastered",
        "steam_appid": "",
        "genres": "Action, Hack and Slash",
        "cover_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/co1r7a.jpg"
    },
    "god of war ragnarok": {
        "title": "God of War Ragnarök",
        "steam_appid": "2322010",
        "genres": "Action, Adventure, RPG",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2322010/header.jpg"
    },
    "call of duty black ops cold war": {
        "title": "Call of Duty®: Black Ops Cold War",
        "steam_appid": "1985810",
        "genres": "Action, FPS, Multiplayer",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1985810/header.jpg"
    },
    "call of duty world at war": {
        "title": "Call of Duty: World at War",
        "steam_appid": "10090",
        "genres": "Action, FPS, Historical",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/10090/header.jpg"
    },
    "call of duty modern warfare 3": {
        "title": "Call of Duty®: Modern Warfare® 3 (2011)",
        "steam_appid": "42680",
        "genres": "Action, FPS, Multiplayer",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/42680/header.jpg"
    },
    "middle earth shadow of war": {
        "title": "Middle-earth™: Shadow of War™",
        "steam_appid": "356190",
        "genres": "Action, Adventure, RPG",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/356190/header.jpg"
    },
    "black myth wukong": {
        "title": "Black Myth: Wukong",
        "steam_appid": "2358720",
        "genres": "Action, RPG, Soulslike",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2358720/header.jpg"
    },
    "cyberpunk 2077": {
        "title": "Cyberpunk 2077",
        "steam_appid": "1091500",
        "genres": "RPG, Open World, Sci-Fi",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1091500/header.jpg"
    },
    "elden ring": {
        "title": "ELDEN RING",
        "steam_appid": "1245620",
        "genres": "Action RPG, Open World, Dark Fantasy",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1245620/header.jpg"
    },
    "the witcher 3 wild hunt": {
        "title": "The Witcher 3: Wild Hunt",
        "steam_appid": "292030",
        "genres": "RPG, Open World, Story Rich",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/292030/header.jpg"
    },
    "toem a photo adventure": {
        "title": "TOEM: A Photo Adventure",
        "steam_appid": "1307580",
        "genres": "Adventure, Cozy, Casual",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1307580/header.jpg"
    },
    "toem 2": {
        "title": "TOEM 2",
        "steam_appid": "1307580",
        "genres": "Adventure, Cozy, Casual",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1307580/header.jpg"
    },
    "hollow knight": {
        "title": "Hollow Knight",
        "steam_appid": "367520",
        "genres": "Metroidvania, Action, Souls-like",
        "cover_url": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/367520/header.jpg"
    }
}


class HydraSourceManager:
    """
    Quản lý các nguồn dữ liệu tải game theo chuẩn Hydra Launcher (.json)
    Lưu cấu hình độc lập tại %APPDATA%/VietModHub/hydra_sources.json
    và cache tại %APPDATA%/VietModHub/hydra_cache để tìm kiếm offline siêu tốc.
    """

    def __init__(self, appdata_dir: Optional[str] = None):
        if not appdata_dir:
            appdata_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VietModHub")
        self.appdata_dir = os.path.abspath(appdata_dir)
        self.cache_dir = os.path.join(self.appdata_dir, "hydra_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.sources_file = os.path.join(self.appdata_dir, "hydra_sources.json")
        self.sources = self._load_sources()
        self.is_syncing = False
        self.sync_progress = {"current": 0, "total": 0, "status": "idle", "message": ""}
        self.lock = threading.Lock()
        self._init_game_metadata()

    def _init_game_metadata(self):
        """Tự động tích hợp toàn bộ các tựa game có trong games.json của CỔ NGỮ vào bộ dữ liệu tìm kiếm."""
        try:
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            candidates = [
                os.path.join(cur_dir, "games.json"),
                os.path.join(os.path.dirname(cur_dir), "games.json"),
                os.path.join(getattr(sys, "_MEIPASS", cur_dir), "games.json")
            ]
            games_file = next((c for c in candidates if os.path.isfile(c)), None)
            if games_file:
                with open(games_file, "r", encoding="utf-8") as f:
                    games = json.load(f)
                for g in games:
                    title = g.get("title") or g.get("name") or g.get("id")
                    appid = str(g.get("steam_appid") or "").strip()
                    genre = g.get("genre") or "Bản Dịch Tiếng Việt Cổ Ngữ"
                    header_img = ""
                    if appid:
                        header_img = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                    elif g.get("assets", {}).get("header"):
                        header_img = g["assets"]["header"]

                    norm_key = self._normalize_title(title)
                    meta_entry = {
                        "title": title,
                        "steam_appid": appid,
                        "genres": genre,
                        "cover_url": header_img,
                        "has_viet_mod": True,
                        "vietnamese_title": g.get("vietnamese_title", ""),
                        "game_id": g.get("id")
                    }
                    KNOWN_GAME_METADATA[norm_key] = meta_entry
                    if g.get("id"):
                        KNOWN_GAME_METADATA[g.get("id")] = meta_entry
        except Exception as e:
            print(f"[HydraSourceManager] Lỗi nạp metadata từ games.json: {e}")

    def _load_sources(self) -> List[str]:
        if os.path.isfile(self.sources_file):
            try:
                with open(self.sources_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        return data
            except Exception as e:
                print(f"[HydraSourceManager] Lỗi đọc hydra_sources.json: {e}")
        
        # Tạo mặc định nếu chưa có
        self._save_sources(DEFAULT_HYDRA_SOURCES)
        return list(DEFAULT_HYDRA_SOURCES)

    def _save_sources(self, sources_list: List[str]) -> bool:
        try:
            with open(self.sources_file, "w", encoding="utf-8") as f:
                json.dump(sources_list, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[HydraSourceManager] Lỗi ghi hydra_sources.json: {e}")
            return False

    def get_sources_status(self) -> Dict[str, Any]:
        """Trả về thông tin chi tiết từng nguồn kèm số lượng game đã cache."""
        result = []
        total_downloads = 0

        for url in self.sources:
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.basename(url))
            cache_path = os.path.join(self.cache_dir, slug)
            cached = os.path.isfile(cache_path)
            count = 0
            name = slug.replace(".json", "").replace("_json", "").upper()
            updated_at = ""
            file_size_str = "0 KB"

            if cached:
                try:
                    fsize = os.path.getsize(cache_path)
                    file_size_str = f"{round(fsize / (1024 * 1024), 2)} MB" if fsize >= 1024*1024 else f"{round(fsize / 1024, 1)} KB"
                    mtime = os.path.getmtime(cache_path)
                    updated_at = time.strftime("%d/%m/%Y %H:%M", time.localtime(mtime))
                    with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                        name = data.get("name") or name
                        downloads = data.get("downloads", [])
                        count = len(downloads)
                        total_downloads += count
                except Exception:
                    pass

            result.append({
                "url": url,
                "name": name,
                "cached": cached,
                "downloads_count": count,
                "file_size": file_size_str,
                "last_updated": updated_at
            })

        # Bổ sung các file cache có sẵn trong thư mục hydra_cache (như community_repacks.json)
        handled_slugs = set(re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.basename(u)) for u in self.sources)
        if os.path.isdir(self.cache_dir):
            for fn in os.listdir(self.cache_dir):
                if fn in handled_slugs or not fn.endswith(".json"):
                    continue
                cache_path = os.path.join(self.cache_dir, fn)
                if os.path.isfile(cache_path):
                    try:
                        fsize = os.path.getsize(cache_path)
                        file_size_str = f"{round(fsize / (1024 * 1024), 2)} MB" if fsize >= 1024*1024 else f"{round(fsize / 1024, 1)} KB"
                        mtime = os.path.getmtime(cache_path)
                        updated_at = time.strftime("%d/%m/%Y %H:%M", time.localtime(mtime))
                        with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                            data = json.load(f)
                            name = data.get("name") or fn.replace(".json", "").upper()
                            downloads = data.get("downloads", [])
                            count = len(downloads)
                            total_downloads += count
                        result.insert(0, {
                            "url": f"local://{fn}",
                            "name": name,
                            "cached": True,
                            "downloads_count": count,
                            "file_size": file_size_str,
                            "last_updated": updated_at
                        })
                    except Exception:
                        pass

        return {
            "total_sources": len(result),
            "total_downloads": total_downloads,
            "is_syncing": self.is_syncing,
            "sync_progress": self.sync_progress,
            "sources": result
        }

    def get_sources(self) -> List[str]:
        """Trả về danh sách URL hoặc key của các nguồn đã cấu hình."""
        with self.lock:
            return list(self.sources)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Lấy thống kê số bản repack trong cache và số nguồn."""
        total_downloads = 0
        if os.path.isdir(self.cache_dir):
            for fn in os.listdir(self.cache_dir):
                fp = os.path.join(self.cache_dir, fn)
                if os.path.isfile(fp):
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            d = json.load(f)
                            total_downloads += len(d.get("downloads", []))
                    except Exception:
                        pass
        return {
            "total_repacks": total_downloads,
            "total_sources": len(self.sources),
            "is_syncing": self.is_syncing
        }

    def add_sources(self, urls_or_text) -> Dict[str, Any]:
        """Thêm nguồn từ string URL hoặc list URLs."""
        if isinstance(urls_or_text, list):
            raw = " ".join(str(u) for u in urls_or_text)
        else:
            raw = str(urls_or_text)
        return self.add_sources_from_text(raw)

    def add_sources_from_text(self, raw_text: str) -> Dict[str, Any]:
        """Tự động phát hiện và thêm các đường dẫn link .json từ văn bản người dùng dán vào."""
        urls = re.findall(r"https?://[^\s\"'<>]+\.json", raw_text, re.IGNORECASE)
        added = 0
        with self.lock:
            for url in urls:
                clean_url = url.strip()
                if clean_url not in self.sources:
                    self.sources.append(clean_url)
                    added += 1
            if added > 0:
                self._save_sources(self.sources)

        # Chạy đồng bộ nền các nguồn mới
        if added > 0:
            self.start_async_sync()

        return {
            "success": True,
            "added_count": added,
            "total_sources": len(self.sources),
            "message": f"Đã thêm thành công {added} nguồn mới! Đang đồng bộ trong nền..." if added > 0 else "Không có nguồn mới nào cần thêm."
        }

    def remove_source(self, url: str) -> Dict[str, Any]:
        """Xóa một nguồn tải khỏi danh sách và xóa file cache tương ứng."""
        with self.lock:
            if url in self.sources:
                self.sources.remove(url)
                self._save_sources(self.sources)

                slug = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.basename(url))
                cache_path = os.path.join(self.cache_dir, slug)
                if os.path.isfile(cache_path):
                    try:
                        os.remove(cache_path)
                    except OSError:
                        pass
                return {"success": True, "message": "Đã xóa nguồn thành công."}
        return {"success": False, "message": "Nguồn không tồn tại trong danh sách."}

    def import_local_json_files(self, file_paths: List[str]) -> Dict[str, Any]:
        """Cho phép người dùng nạp trực tiếp các file .json (fitgirl.json, dodi.json...) từ máy tính."""
        import shutil
        imported = 0
        total_items = 0

        for fp in file_paths:
            if not os.path.isfile(fp):
                continue
            fname = os.path.basename(fp)
            if not fname.lower().endswith(".json"):
                continue

            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                
                # Kiểm tra định dạng Hydra
                downloads = data.get("downloads", [])
                if not downloads and isinstance(data, list):
                    downloads = data
                    data = {"name": os.path.splitext(fname)[0].upper(), "downloads": downloads}

                dest_path = os.path.join(self.cache_dir, fname)
                with open(dest_path, "w", encoding="utf-8") as f_out:
                    json.dump(data, f_out, ensure_ascii=False, indent=2)

                source_key = f"local://{fname}"
                with self.lock:
                    if source_key not in self.sources:
                        self.sources.append(source_key)
                        self._save_sources(self.sources)

                imported += 1
                total_items += len(downloads)
            except Exception as e:
                print(f"[HydraSourceManager] Lỗi import file {fname}: {e}")

        return {
            "success": imported > 0,
            "imported_files": imported,
            "total_downloads": total_items,
            "message": f"Đã nhập thành công {imported} tệp nguồn ({total_items} bản game)!" if imported > 0 else "Không tìm thấy dữ liệu hợp lệ trong các tệp đã chọn."
        }

    def browse_local_json_files(self) -> List[str]:
        """Mở hộp thoại chọn tệp .json từ Windows Explorer."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            paths = filedialog.askopenfilenames(
                title="Chọn các tệp nguồn Hydra JSON (fitgirl.json, dodi.json, gog.json...)",
                filetypes=[("Hydra JSON Sources", "*.json"), ("All Files", "*.*")]
            )
            root.destroy()
            return list(paths) if paths else []
        except Exception:
            return []

    def start_async_sync(self, force: bool = False):
        """Khởi động luồng tải đồng bộ cache ngầm không làm đơ giao diện."""
        if self.is_syncing:
            return
        thread = threading.Thread(target=self._sync_all_sources_worker, args=(force,), daemon=True)
        thread.start()

    def _sync_all_sources_worker(self, force: bool = False):
        self.is_syncing = True
        total = len(self.sources)
        self.sync_progress = {"current": 0, "total": total, "status": "syncing", "message": "Bắt đầu đồng bộ..."}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        for idx, url in enumerate(list(self.sources)):
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", os.path.basename(url))
            cache_path = os.path.join(self.cache_dir, slug)
            self.sync_progress["current"] = idx + 1
            self.sync_progress["message"] = f"Đang tải: {os.path.basename(url)} ({idx + 1}/{total})"

            # Bỏ qua nếu đã tải gần đây (dưới 12 tiếng) trừ khi force
            if not force and os.path.isfile(cache_path):
                if time.time() - os.path.getmtime(cache_path) < 12 * 3600:
                    continue

            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    if resp.status == 200:
                        content = resp.read()
                        with open(cache_path, "wb") as f:
                            f.write(content)
            except Exception as e:
                print(f"[HydraSourceManager] Lỗi tải nguồn {url}: {e}")

        self.is_syncing = False
        self.sync_progress = {"current": total, "total": total, "status": "completed", "message": "Đã đồng bộ xong toàn bộ nguồn."}

    # ========================================================
    # THUẬT TOÁN TÌM KIẾM & SO KHỚP TỰ ĐỘNG THÔNG MINH
    # ========================================================
    @staticmethod
    def _normalize_title(text: str) -> str:
        """Làm sạch tên game để so khớp chính xác giữa games.json và tên bản Repack."""
        if not text:
            return ""
        t = text.lower()
        # Bỏ phần ngoặc đơn/vuông chứa version, DLC, ngôn ngữ, tag repack
        t = re.sub(r"[\(\[].*?[\)\]]", " ", t)
        t = re.sub(r"\b(complete edition|game of the year|goty|deluxe edition|definitive edition|special edition|repack|portable|onlinefix|gog|v\d+[\.\d_]*)\b", " ", t)
        t = re.sub(r"[:\-_+~#&!?',.]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def search_download_links_for_game(self, game_title: str, game_id: str = "", steam_appid: str = "") -> List[Dict[str, Any]]:
        """
        Tìm kiếm tất cả các bản cài đặt (Magnet / Torrent / Direct) khớp với tựa game
        từ toàn bộ các file cache nguồn Hydra. Tốc độ tìm kiếm: dưới 0.05 giây!
        """
        target_norm = self._normalize_title(game_title)
        if not target_norm and not steam_appid:
            return []

        # Tách các từ khóa chính (bỏ các từ nối thông thường)
        stop_words = {"the", "a", "an", "of", "in", "on", "and", "to", "for", "is"}
        target_tokens = [w for w in target_norm.split() if w not in stop_words and len(w) > 1]

        matches = []
        if not os.path.isdir(self.cache_dir):
            return []

        for filename in os.listdir(self.cache_dir):
            cache_path = os.path.join(self.cache_dir, filename)
            if not os.path.isfile(cache_path):
                continue

            try:
                with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)

                source_name = data.get("name") or filename.replace(".json", "").replace("_json", "").upper()
                downloads = data.get("downloads", [])

                for item in downloads:
                    raw_title = item.get("title", "")
                    cand_norm = self._normalize_title(raw_title)
                    if not cand_norm:
                        continue

                    # 1. So khớp tuyệt đối hoặc chuỗi con
                    is_match = False
                    ratio = 0.0

                    if target_norm == cand_norm:
                        is_match = True
                        ratio = 1.0
                    elif target_norm in cand_norm:
                        is_match = True
                        ratio = 0.95
                    elif target_tokens and all(token in cand_norm for token in target_tokens):
                        is_match = True
                        ratio = 0.90
                    else:
                        ratio = SequenceMatcher(None, target_norm, cand_norm).ratio()
                        if ratio >= 0.80:
                            is_match = True

                    if is_match:
                        uris = item.get("uris", [])
                        magnet_uri = next((u for u in uris if u.startswith("magnet:")), uris[0] if uris else "")
                        if not magnet_uri:
                            continue

                        # Nhận diện phân loại bản Repack
                        lower_raw = raw_title.lower()
                        badge_type = "REPACK"
                        badge_color = "amber"
                        if "gog" in lower_raw or "portable" in lower_raw or "direct" in lower_raw:
                            badge_type = "PORTABLE / GOG"
                            badge_color = "emerald"
                        elif "onlinefix" in lower_raw or "online-fix" in lower_raw or "co-op" in lower_raw:
                            badge_type = "ONLINE CO-OP"
                            badge_color = "cyan"
                        elif "fitgirl" in lower_raw or "fitgirl" in source_name.lower():
                            badge_type = "FITGIRL"
                            badge_color = "purple"
                        elif "dodi" in lower_raw or "dodi" in source_name.lower():
                            badge_type = "DODI"
                            badge_color = "rose"

                        matches.append({
                            "title": raw_title,
                            "release_title": raw_title,
                            "source_name": source_name,
                            "source_file": filename,
                            "repacker": source_name,
                            "file_size": item.get("fileSize") or "Không rõ",
                            "upload_date": (item.get("uploadDate") or "")[:10],
                            "uri": magnet_uri,
                            "uris": uris if uris else [magnet_uri],
                            "all_uris": uris,
                            "badge_type": badge_type,
                            "badge_color": badge_color,
                            "match_score": ratio
                        })
            except Exception:
                continue

        # Sắp xếp kết quả: Ưu tiên điểm khớp cao nhất, sau đó đến Portable/GOG
        matches.sort(key=lambda x: (
            -x["match_score"],
            0 if "PORTABLE" in x["badge_type"] else 1,
            x["source_name"]
        ))

        return matches

    @staticmethod
    def extract_canonical_game_title(raw_title: str) -> str:
        """Trích xuất tên game gốc chuẩn hóa từ chuỗi repack title đầy đủ."""
        if not raw_title:
            return ""
        t = raw_title.replace("®", "").replace("™", "")
        # Bỏ phần ngoặc vuông [FitGirl Repack], [GOG], [v 1.0.13...]
        t = re.sub(r"\[.*?\]", " ", t)
        # Bỏ phần ngoặc đơn: (Campaign + Zombies), (Complete Edition), (2011), (v1.0.1...), etc.
        t = re.sub(r"\(.*?\)", " ", t)
        # Cắt từ dấu gạch nối nếu theo sau là version, DLC, repacker indicator, edition
        t = re.split(r"\s+[-–—|/]\s+(?:v\d+|build|\d+|all dlc|repack|gog|portable|dodi|fitgirl|xatab|recompiled|definitive|complete|deluxe)", t, flags=re.IGNORECASE)[0]
        # Bỏ chữ Nga và tag đuôi
        t = re.sub(r"[\u0400-\u04FF]+.*$", " ", t)
        t = re.sub(r"\b(?:v\.?\d+[\.\d_]*|build\s*\d+|multi\d+|repack.*?|repack|portable|kaos|dodi|fitgirl|xatab|gog|steamrip)\b.*$", " ", t, flags=re.IGNORECASE)
        # Bỏ các cụm từ Edition ở đuôi nếu còn sót
        t = re.sub(r"\b(?:definitive edition|complete edition|deluxe edition|special edition|standard edition|game of the year|goty)\b.*$", " ", t, flags=re.IGNORECASE)
        # Bỏ standalone PC ở đuôi
        t = re.sub(r"\bPC\b\s*$", " ", t, flags=re.IGNORECASE)
        # Chuẩn hóa dấu chấm ngăn cách thành dấu cách (VD: God.Of.War -> God Of War)
        t = t.replace(".", " ")
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"[-–—:|/\\_.]+$", "", t).strip()
        return t

    def search_catalogue_games(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Tìm kiếm và gom nhóm các bản Repack theo Tựa Game (Catalogue View giống Hydra Launcher).
        Mỗi tựa game trả về:
          - title: Tên game chuẩn
          - slug: Mã định danh
          - genres: Thể loại
          - cover_url: Ảnh bìa
          - sources: Danh sách repacker
          - total_repacks: Số lượng bản repack
          - repacks: Chi tiết từng bản repack để mở Download Options
        """
        query_raw = (query or "").strip()
        clean_q = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", query_raw.lower()).strip()
        clean_q = re.sub(r"\s+", " ", clean_q)
        q_tokens = [w for w in clean_q.split() if len(w) > 0 and w not in {"the", "a", "an", "of", "in", "to", "and"}]

        # Bảng ánh xạ số La Mã & số Ả Rập
        roman_map = {"3": "iii", "iii": "3", "2": "ii", "ii": "2", "4": "iv", "iv": "4", "1": "i", "i": "1", "v": "5", "5": "v"}
        specific_number = next((t for t in q_tokens if t.isdigit() or t in roman_map), None)

        grouped: Dict[str, Dict[str, Any]] = {}

        if not os.path.isdir(self.cache_dir):
            return []

        for filename in os.listdir(self.cache_dir):
            cache_path = os.path.join(self.cache_dir, filename)
            if not os.path.isfile(cache_path):
                continue
            try:
                with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                default_source = data.get("name") or filename.replace(".json", "").replace("_json", "").upper()
                downloads = data.get("downloads", [])

                for item in downloads:
                    raw_title = item.get("title", "")
                    if not raw_title:
                        continue

                    canonical = self.extract_canonical_game_title(raw_title)
                    if not canonical:
                        canonical = raw_title

                    # Chuẩn hóa key nhóm (loại bỏ dấu diacritics ö->o và ký tự đặc biệt)
                    import unicodedata
                    norm_c = unicodedata.normalize('NFKD', canonical).encode('ASCII', 'ignore').decode('utf-8')
                    group_key = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", norm_c.lower()).strip()
                    group_key = re.sub(r"\s+", " ", group_key)

                    # Nhận diện repacker
                    item_repacker = item.get("repacker")
                    if not item_repacker:
                        lower_t = raw_title.lower()
                        if "fitgirl" in lower_t:
                            item_repacker = "fitgirl"
                        elif "dodi" in lower_t:
                            item_repacker = "DODI"
                        elif "gog" in lower_t:
                            item_repacker = "GOG"
                        elif "xatab" in lower_t:
                            item_repacker = "Xatab"
                        elif "kaos" in lower_t:
                            item_repacker = "KaOsKrew"
                        elif "atopgames" in lower_t:
                            item_repacker = "AtopGames"
                        else:
                            item_repacker = default_source

                    uris = item.get("uris", [])
                    magnet_uri = next((u for u in uris if u.startswith("magnet:")), uris[0] if uris else "")
                    if not magnet_uri:
                        continue

                    repack_obj = {
                        "title": raw_title,
                        "file_size": item.get("fileSize") or "Không rõ",
                        "upload_date": (item.get("uploadDate") or "")[:10] or "Gần đây",
                        "repacker": item_repacker,
                        "source_name": default_source,
                        "uri": magnet_uri,
                        "uris": uris if uris else [magnet_uri]
                    }

                    if group_key not in grouped:
                        grouped[group_key] = {
                            "title": canonical,
                            "slug": re.sub(r"[^a-zA-Z0-9_-]", "_", group_key),
                            "sources": set(),
                            "repacks": []
                        }

                    grouped[group_key]["sources"].add(item_repacker)
                    grouped[group_key]["repacks"].append(repack_obj)
            except Exception:
                continue

        # Hoàn thiện danh sách, tính điểm liên quan và gán metadata
        catalogue_list = []
        for key, g in grouped.items():
            meta = KNOWN_GAME_METADATA.get(key)
            if not meta:
                # Khớp chính xác sau chuẩn hóa
                for k, v in KNOWN_GAME_METADATA.items():
                    clean_k = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", k.lower()).strip()
                    if clean_k == key:
                        meta = v
                        break

            cover_url = meta.get("cover_url", "") if meta else ""
            genres = meta.get("genres", "Hành Động, Phiêu Lưu") if meta else "Hành Động, Phiêu Lưu"
            display_title = meta.get("title", g["title"]) if meta else g["title"]

            # Fallback cover nếu chưa có: lấy Steam placeholder đẹp
            if not cover_url:
                cover_url = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/480/header.jpg"

            # Tính điểm liên quan chính xác cho toàn bộ Game
            relevance = 0
            if q_tokens:
                title_clean = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", display_title.lower()).strip()
                title_clean = re.sub(r"\s+", " ", title_clean)
                title_words = set(title_clean.split())
                all_repack_text = " ".join([r["title"].lower() for r in g["repacks"]])

                # 1. Khớp chính xác toàn bộ chuỗi
                if clean_q == title_clean or clean_q == key:
                    relevance += 1200
                elif clean_q in title_clean or clean_q in key:
                    relevance += 600

                # 2. Khớp từng token trong query
                matched_tokens = 0
                has_number_match = False
                for tok in q_tokens:
                    tok_variants = {tok, roman_map.get(tok, "")} - {""}
                    if any(v in title_words or v in title_clean for v in tok_variants):
                        matched_tokens += 1
                        if tok.isdigit() or tok in roman_map:
                            has_number_match = True
                    elif any(v in all_repack_text for v in tok_variants):
                        matched_tokens += 0.8
                        if tok.isdigit() or tok in roman_map:
                            has_number_match = True

                if matched_tokens > 0:
                    relevance += int((matched_tokens / len(q_tokens)) * 300)
                    if matched_tokens >= len(q_tokens):
                        relevance += 250  # Khớp toàn bộ token
                    if has_number_match:
                        relevance += 200  # Đúng phiên bản phần game

                # Nếu người dùng tìm phần cụ thể (ví dụ '3', '2') mà tựa game này KHÔNG có số đó -> loại bỏ hoặc phạt nặng
                if specific_number and not has_number_match:
                    relevance -= 400

                # Nếu không có điểm relevance dương -> không đưa vào kết quả tìm kiếm
                if relevance <= 0:
                    continue
            else:
                relevance = 1

            has_viet = bool(
                (meta and meta.get("has_viet_mod"))
                or any(r.get("has_viet_mod") for r in g["repacks"])
            )
            # Ưu tiên đưa các game có sẵn bản dịch tiếng Việt của CỔ NGỮ lên hàng đầu!
            if has_viet:
                relevance += 500

            catalogue_list.append({
                "title": display_title,
                "slug": g["slug"],
                "genres": genres,
                "cover_url": cover_url,
                "sources": sorted(list(g["sources"])),
                "total_repacks": len(g["repacks"]),
                "repacks": g["repacks"],
                "relevance": relevance,
                "has_viet_mod": has_viet
            })

        # Sắp xếp theo độ liên quan giảm dần, rồi đến số lượng repack
        catalogue_list.sort(key=lambda x: (-x["relevance"], -x["total_repacks"], x["title"]))
        return catalogue_list[:limit]

