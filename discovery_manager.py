# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - DISCOVERY HUB ENGINE (Bộ Tổng Hợp Khám Phá)
----------------------------------------------------------------------
Kết hợp 3 nguồn dữ liệu để tab "Khám Phá" không bao giờ hiển thị game "rỗng":

  1. Steam Trending / New Releases  -> API công khai featuredcategories + appdetails (tiếng Việt).
  2. Kho cache .json của Hydra      -> fitgirl.json, dodi.json, gog.json, onlinefix.json, tinyrepacks.json...
                                       (uploadDate + fileSize + magnet) => "đã có link tải ngay".
  3. Kho Việt hóa games.json        -> trạng thái đã dịch + ngày cập nhật + mô tả tiếng Việt.

Toàn bộ feed được cache 6 tiếng tại %APPDATA%/VietModHub/discovery_feed_cache.json
nên thao tác chuyển tab chỉ mất vài mili giây (không chờ mạng).

Ngoài ra module còn cung cấp:
  - Đánh giá tương thích cấu hình máy (Smart PC Check) dựa trên pc_requirements.
  - Lấy link Micro-Trailer (hover preview) từ appdetails.
  - Danh sách theo dõi (watchlist) + hàng đợi "Yêu cầu Việt hóa".
"""

import os
import re
import json
import time
import html
import ctypes
import platform
import threading
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from core.config_manager import APPDATA_DIR, get_active_games_json_path
from core.steam_client import steam_direct_request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
STEAM_CDN = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"
FEATURED_URL = "https://store.steampowered.com/api/featuredcategories/?l=vietnamese&cc=VN"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese&cc=VN"

# Thể loại Steam (tiếng Anh) -> nhãn tiếng Việt dùng cho bộ lọc nhanh
STEAM_GENRE_VN = {
    "action": "Hành động",
    "adventure": "Phiêu lưu",
    "rpg": "Nhập vai",
    "role-playing": "Nhập vai",
    "horror": "Kinh dị",
    "strategy": "Chiến thuật",
    "simulation": "Mô phỏng",
    "racing": "Đua xe",
    "sports": "Thể thao",
    "puzzle": "Giải đố",
    "indie": "Indie",
    "massively multiplayer": "Co-op",
    "free to play": "Miễn phí",
    "casual": "Thư giãn",
    "platformer": "Platformer",
    "shooter": "Bắn súng",
}

# Đoán thể loại nhanh từ tên bản Repack (khi chưa có Steam appid)
TITLE_GENRE_HINTS = [
    ("Kinh dị", ("horror", "resident evil", "silent hill", "outlast", "dead space", "amnesia",
                 "evil within", "dying light", "left 4 dead", "phantasmophobia", "fears to fathom",
                 "visage", "layers of fear", "the forest", "sons of the forest")),
    ("Nhập vai", ("rpg", "final fantasy", "elden ring", "witcher", "skyrim", "fallout", "persona",
                  "dragon age", "mass effect", "baldur", "diablo", "dark souls", "sekiro", "yakuza",
                  "assassin", "horizon", "cyberpunk")),
    ("Phiêu lưu", ("adventure", "tomb raider", "uncharted", "zelda", "journey", "toem", "stray",
                   "little nightmare", "inside", "limbo", "life is strange", "backbone", "tails")),
    ("Hành động", ("action", "call of duty", "battlefield", "doom", "devil may cry", "bayonetta",
                   "metal gear", "gta", "grand theft", "far cry", "just cause", "saint row", "wolfenstein")),
    ("Chiến thuật", ("strategy", "civilization", "total war", "xcom", "tropico", "anno", "frostpunk",
                     "age of empires", "command", "stellaris", "crusader kings")),
    ("Co-op", ("co-op", "coop", "online fix", "onlinefix", "multiplayer", "multi-player")),
    ("Đua xe", ("forza", "need for speed", "dirt", "assetto", "gran turismo", "trackmania")),
    ("Thư giãn", ("cozy", "stardew", "animal crossing", "harvest", "unpacking", "spiritfarer", "palia")),
]

STOP_WORDS = {"the", "a", "an", "of", "in", "on", "and", "to", "for", "is", "edition", "pc"}


# ==============================================================================
# TIỆN ÍCH CHUỖI / DUNG LƯỢNG
# ==============================================================================

def clean_title_key(title: str) -> str:
    """Chuẩn hóa tên game về khóa so khớp (bỏ dấu, bỏ tag edition/version/repack)."""
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", str(title))
    t = t.encode("ASCII", "ignore").decode("utf-8", "ignore").lower()
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)
    t = re.sub(r"\b(complete edition|game of the year|goty|deluxe edition|definitive edition|"
               r"special edition|standard edition|enhanced edition|repack|portable|onlinefix|"
               r"online-fix|gog|drm-free|multi\d+|v\d+[\.\d_]*|build \d+)\b", " ", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def display_title_from_repack(raw_title: str) -> str:
    """Rút gọn tiêu đề repack dài thành tên game gọn gàng để hiển thị trên thẻ."""
    if not raw_title:
        return ""
    t = str(raw_title).replace("®", "").replace("™", "").replace("©", "")
    t = re.sub(r"\[.*?\]", " ", t)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.split(r"\s+[-–—|/]\s+", t)[0]
    t = re.sub(r"\b(v\.?\s?\d+[\d\._]*|build\s*\d+|multi\d+|repack|fitgirl|dodi|xatab|gog|steamrip|"
               r"portable|onlinefix|drm-?free|pre-?installed|edition|inc\.?|all dlc)\b.*$", " ", t, flags=re.I)
    t = t.replace(".", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[-–—:|/\\_]+$", "", t).strip()
    return t or str(raw_title).strip()


def parse_size_gb(size_text: str) -> Optional[float]:
    """Đổi "850 MB" / "12,4 GB" / "19GB" -> số GB (float). Trả None nếu không đọc được."""
    if not size_text:
        return None
    s = str(size_text).lower().replace(",", ".").replace("~", " ")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb|kb)", s)
    if not m:
        m2 = re.search(r"(\d+(?:\.\d+)?)", s)
        return float(m2.group(1)) if m2 else None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "tb":
        return round(value * 1024, 2)
    if unit == "gb":
        return round(value, 2)
    if unit == "mb":
        return round(value / 1024, 2)
    return round(value / 1024 / 1024, 2)


def guess_genres(title: str) -> List[str]:
    """Đoán thể loại từ tên game (dùng cho game chưa có metadata Steam)."""
    low = (title or "").lower()
    found = [genre for genre, keys in TITLE_GENRE_HINTS if any(k in low for k in keys)]
    return found[:3] or ["Phiêu lưu"]


def days_ago(date_str: str) -> Optional[int]:
    """Số ngày kể từ uploadDate (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        t = time.mktime(time.strptime(date_str[:10], "%Y-%m-%d"))
    except Exception:
        return None
    return max(0, int((time.time() - t) // 86400))


def strip_html(text: str) -> str:
    if not text:
        return ""
    raw = re.sub(r"<\s*(br|/li|/p|/tr|/h\d)\s*/?\s*>", " ", str(text), flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


# ==============================================================================
# DISCOVERY MANAGER
# ==============================================================================

class DiscoveryManager:
    """Bộ tổng hợp dữ liệu tab Khám Phá: Steam + Hydra (.json) + Kho Việt hóa (games.json)."""

    FEED_CACHE_NAME = "discovery_feed_cache.json"
    APPDETAILS_CACHE_NAME = "discovery_appdetails_cache.json"
    WATCHLIST_NAME = "discovery_watchlist.json"
    CACHE_TTL = 6 * 3600           # Feed sống 6 tiếng
    APPDETAILS_TTL = 7 * 86400     # Metadata Steam sống 7 ngày
    MAX_TRENDING = 60

    def __init__(self, hydra_manager=None, congu_games_path: Optional[str] = None,
                 appdata_dir: Optional[str] = None):
        self.appdata_dir = os.path.abspath(appdata_dir or APPDATA_DIR or
                                           os.path.join(os.environ.get("APPDATA", ""), "VietModHub"))
        try:
            os.makedirs(self.appdata_dir, exist_ok=True)
        except OSError:
            pass
        self.cache_file = os.path.join(self.appdata_dir, self.FEED_CACHE_NAME)
        self.appdetails_cache_file = os.path.join(self.appdata_dir, self.APPDETAILS_CACHE_NAME)
        self.watchlist_file = os.path.join(self.appdata_dir, self.WATCHLIST_NAME)
        self.hydra_manager = hydra_manager
        self._explicit_congu_path = congu_games_path
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._index_cache: Dict[str, Any] = {"sig": None, "items": []}
        self._congu_cache: Dict[str, Any] = {"sig": None, "games": []}
        self._appdetails_cache: Dict[str, Dict[str, Any]] = {}
        self._appdetails_loaded = False
        self._appdetails_dirty = False
        self._clip_locks: Dict[Tuple[str, int], threading.Lock] = {}

    # ==================================================================
    # ĐỌC KHO VIỆT HÓA (games.json)
    # ==================================================================
    def _congu_path(self) -> str:
        if self._explicit_congu_path and os.path.isfile(self._explicit_congu_path):
            return self._explicit_congu_path
        try:
            p = get_active_games_json_path()
            if p and os.path.isfile(p):
                return p
        except Exception:
            pass
        for cand in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "games.json"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games.json"),
        ):
            if os.path.isfile(cand):
                return cand
        return ""

    def congu_games(self, force: bool = False) -> List[Dict[str, Any]]:
        """Đọc danh sách game đã Việt hóa trong kho CỔ NGỮ (có cache theo mtime)."""
        path = self._congu_path()
        if not path:
            return []
        try:
            sig = (path, os.path.getsize(path), int(os.path.getmtime(path)))
        except OSError:
            return []
        with self._lock:
            if not force and self._congu_cache.get("sig") == sig:
                return self._congu_cache["games"]
        games: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                games = [g for g in data if isinstance(g, dict)]
        except Exception as e:
            print(f"[Discovery] Không đọc được games.json: {e}")
        with self._lock:
            self._congu_cache = {"sig": sig, "games": games}
        return games

    def congu_map(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        """Bản đồ tra cứu nhanh: steam_appid -> game và tên đã chuẩn hóa -> game."""
        mapping: Dict[str, Dict[str, Any]] = {}
        for g in self.congu_games(force=force):
            appid = str(g.get("steam_appid") or "").strip()
            if appid:
                mapping[appid] = g
            for key in (
                clean_title_key(g.get("title", "")),
                clean_title_key(g.get("vietnamese_title", "")),
                clean_title_key(g.get("id", "")),
            ):
                if key:
                    mapping[key] = g
        return mapping

    @staticmethod
    def _congu_lookup(congu_map: Dict[str, Dict[str, Any]], title: str, appid: str = "") -> Optional[Dict[str, Any]]:
        if appid and appid in congu_map:
            return congu_map[appid]
        key = clean_title_key(title)
        if key and key in congu_map:
            return congu_map[key]
        # Khớp lỏng: tên Cổ Ngữ là chuỗi con hoặc ngược lại
        if key:
            for k, g in congu_map.items():
                if len(k) > 6 and (k in key or key in k):
                    return g
        return None

    @staticmethod
    def _congu_posters(game: Optional[Dict[str, Any]], appid: str = "") -> Tuple[str, str]:
        """(poster_dọc_600x900, banner_ngang) của game Cổ Ngữ, fallback sang CDN Steam."""
        assets = (game or {}).get("assets") or {}
        poster = assets.get("poster") or assets.get("header") or ""
        banner = assets.get("banner") or assets.get("header") or ""
        if not poster and appid:
            poster = f"{STEAM_CDN}/{appid}/library_600x900.jpg"
        if not banner and appid:
            banner = f"{STEAM_CDN}/{appid}/library_hero.jpg"
        return poster, banner

    # ==================================================================
    # CHỈ MỤC NGUỒN TẢI HYDRA (.json cache)
    # ==================================================================
    def hydra_index(self, force: bool = False) -> List[Dict[str, Any]]:
        """Quét toàn bộ file .json nguồn Hydra 1 lần và giữ trong RAM để tra cứu 0.01s."""
        mgr = self.hydra_manager
        cache_dir = getattr(mgr, "cache_dir", "") if mgr else ""
        if not cache_dir or not os.path.isdir(cache_dir):
            return []

        try:
            files = [f for f in os.listdir(cache_dir) if f.lower().endswith(".json")]
        except OSError:
            return []
        if not files:
            return []

        sig_items = []
        for fname in files:
            fpath = os.path.join(cache_dir, fname)
            try:
                st = os.stat(fpath)
                sig_items.append((fname, st.st_size, int(st.st_mtime)))
            except OSError:
                continue
        sig = tuple(sorted(sig_items))

        with self._lock:
            if not force and self._index_cache.get("sig") == sig:
                return self._index_cache["items"]

        items: List[Dict[str, Any]] = []
        for fname, _size, _mtime in sig_items:
            fpath = os.path.join(cache_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            source_name = str(data.get("name") or fname.replace(".json", "").replace("_json", "")).upper()
            source_low = (source_name + " " + fname).lower()
            is_onlinefix_source = "onlinefix" in source_low or "online-fix" in source_low

            for dl in data.get("downloads") or []:
                if not isinstance(dl, dict):
                    continue
                raw_title = str(dl.get("title") or "").strip()
                if not raw_title:
                    continue
                uris = [u for u in (dl.get("uris") or []) if isinstance(u, str) and u]
                if not uris:
                    continue
                uri = next((u for u in uris if u.startswith("magnet:")), uris[0])
                low = raw_title.lower()
                repacker = str(dl.get("repacker") or "").strip()
                if not repacker:
                    if "fitgirl" in low:
                        repacker = "FitGirl"
                    elif "dodi" in low:
                        repacker = "DODI"
                    elif "xatab" in low:
                        repacker = "Xatab"
                    elif "gog" in low:
                        repacker = "GOG"
                    elif "steamrip" in low:
                        repacker = "SteamRIP"
                    elif "onlinefix" in low or "online-fix" in low:
                        repacker = "OnlineFix"
                    else:
                        repacker = source_name
                size_raw = str(dl.get("fileSize") or "").strip()
                upload_date = str(dl.get("uploadDate") or "")[:10]
                items.append({
                    "title": raw_title,
                    "display_title": display_title_from_repack(raw_title),
                    "norm": clean_title_key(raw_title),
                    "repacker": repacker,
                    "source": source_name,
                    "upload_date": upload_date,
                    "days_ago": days_ago(upload_date),
                    "file_size": size_raw or "Không rõ",
                    "size_gb": parse_size_gb(size_raw),
                    "uri": uri,
                    "uris": uris,
                    "is_onlinefix": is_onlinefix_source or "onlinefix" in low or "online-fix" in low or "co-op" in low,
                    "is_portable": ("gog" in low or "portable" in low or "drm-free" in low or
                                    "pre-installed" in low or "gog" in source_low),
                    "genres": guess_genres(raw_title),
                    "steam_appid_hint": str(dl.get("steam_appid") or "").strip(),
                })

        # Mới nhất lên đầu
        items.sort(key=lambda x: (x.get("upload_date") or "", x.get("title") or ""), reverse=True)

        with self._lock:
            self._index_cache = {"sig": sig, "items": items}
        return items

    @staticmethod
    def _score_match(target: str, cand: str, tokens: List[str]) -> float:
        """
        Chấm điểm khớp tên game rất chặt để tránh gắn nhầm link tải:
          - Chuỗi con phải chiếm >= 55% độ dài tên còn lại (tránh "Zombi" khớp "Zombie Assault...").
          - Khác số thứ tự / phần game (Phần 4 vs Phần 2) => loại.
          - Khớp mờ chỉ nhận khi độ tương đồng >= 0.90 và từ khóa đầu tiên trùng.
        """
        if not target or not cand:
            return 0.0
        if target == cand:
            return 1.0

        nums_target = {w for w in target.split() if w.isdigit()}
        nums_cand = {w for w in cand.split() if w.isdigit()}
        if nums_target and nums_target != nums_cand:
            return 0.0

        short, long_ = (target, cand) if len(target) <= len(cand) else (cand, target)
        if len(short) >= 6 and short in long_ and len(short) >= 0.55 * len(long_):
            return 0.94 if short == target else 0.90

        if len(tokens) >= 2 and all(tok in cand for tok in tokens):
            return 0.90

        if abs(len(target) - len(cand)) > 0.45 * max(len(target), len(cand)):
            return 0.0
        ratio = SequenceMatcher(None, target, cand).ratio()
        if ratio >= 0.90 and tokens and tokens[0] in cand:
            return round(ratio, 3)
        return 0.0

    @classmethod
    def _match_downloads(cls, index: List[Dict[str, Any]], title: str,
                         limit: int = 6) -> List[Dict[str, Any]]:
        """So khớp tên game với chỉ mục Hydra (chuẩn hóa + token + độ tương đồng)."""
        target = clean_title_key(title)
        if not target:
            return []
        tokens = [w for w in target.split() if len(w) > 1 and w not in STOP_WORDS]
        matched: List[Tuple[float, Dict[str, Any]]] = []
        for it in index:
            cand = it.get("norm") or ""
            if not cand:
                continue
            score = cls._score_match(target, cand, tokens)
            if score:
                matched.append((score, it))

        matched.sort(key=lambda pair: (-pair[0], 0 if pair[1].get("is_portable") else 1,
                                       -(pair[1].get("size_gb") or 0)))

        out: List[Dict[str, Any]] = []
        seen = set()
        for score, it in matched:
            key = (it.get("repacker"), it.get("norm"), it.get("upload_date"))
            if key in seen:
                continue
            seen.add(key)
            entry = dict(it)
            entry["match_score"] = round(score, 3)
            entry.pop("norm", None)
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    # ==================================================================
    # STEAM: FEATURED + APPDETAILS
    # ==================================================================
    @staticmethod
    def _http_json(url: str, timeout: float = 6.0) -> Optional[Any]:
        """GET JSON: ưu tiên steam_direct_request (vượt DPI), fallback urllib thường."""
        try:
            raw = steam_direct_request(url, timeout=timeout)
            if raw:
                return json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception:
            return None

    def _load_appdetails_cache(self):
        if self._appdetails_loaded:
            return
        self._appdetails_loaded = True
        try:
            if os.path.isfile(self.appdetails_cache_file):
                with open(self.appdetails_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._appdetails_cache = data
        except Exception:
            self._appdetails_cache = {}

    def _save_appdetails_cache(self):
        if not self._appdetails_dirty:
            return
        try:
            # Dọn bớt mục quá 30 ngày để file cache không phình to
            cutoff = time.time() - 30 * 86400
            pruned = {k: v for k, v in self._appdetails_cache.items()
                      if isinstance(v, dict) and v.get("ts", 0) >= cutoff}
            with open(self.appdetails_cache_file, "w", encoding="utf-8") as f:
                json.dump(pruned, f, ensure_ascii=False)
            self._appdetails_cache = pruned
            self._appdetails_dirty = False
        except Exception:
            pass

    def appdetails(self, appid: str, force: bool = False) -> Optional[Dict[str, Any]]:
        """Metadata Steam (tiếng Việt) cho 1 appid, cache 7 ngày."""
        appid = str(appid or "").strip()
        if not appid.isdigit():
            return None
        self._load_appdetails_cache()
        with self._lock:
            entry = self._appdetails_cache.get(appid)
        if entry and not force and (time.time() - entry.get("ts", 0)) < self.APPDETAILS_TTL:
            return entry.get("data")

        raw = self._http_json(APPDETAILS_URL.format(appid=appid), timeout=6.0)
        data = None
        try:
            node = (raw or {}).get(appid) or {}
            if node.get("success") and isinstance(node.get("data"), dict):
                d = node["data"]
                movies = []
                for m in (d.get("movies") or [])[:3]:
                    dash_url = m.get("dash_h264") or m.get("dash_av1") or ""
                    hls_url = m.get("hls_h264") or ""
                    legacy = ((m.get("webm") or {}).get("480") or (m.get("mp4") or {}).get("480")
                              or (m.get("mp4") or {}).get("max") or "")
                    if not (dash_url or hls_url or legacy):
                        continue
                    movies.append({
                        "name": m.get("name") or "",
                        "dash": dash_url,
                        "hls": hls_url,
                        "url": legacy,
                        "thumbnail": m.get("thumbnail") or "",
                        "highlight": bool(m.get("highlight")),
                    })
                genres = [STEAM_GENRE_VN.get(str(g.get("description", "")).lower(), g.get("description", ""))
                          for g in (d.get("genres") or []) if isinstance(g, dict)]
                pc_min = ((d.get("pc_requirements") or {}).get("minimum") or "")
                data = {
                    "name": d.get("name") or "",
                    "short_description": strip_html(d.get("short_description") or ""),
                    "detailed_description": strip_html(d.get("detailed_description") or "")[:600],
                    "header_image": d.get("header_image") or "",
                    "genres": [g for g in genres if g][:4],
                    "movies": movies,
                    "release_date": ((d.get("release_date") or {}).get("date") or ""),
                    "is_free": bool(d.get("is_free")),
                    "developers": (d.get("developers") or [])[:2],
                    "pc_requirements_min": strip_html(pc_min)[:800],
                    "price": ((d.get("price_overview") or {}).get("final_formatted") or
                              ("Miễn phí" if d.get("is_free") else "")),
                }
        except Exception:
            data = None

        if data:
            with self._lock:
                self._appdetails_cache[appid] = {"ts": time.time(), "data": data}
            self._appdetails_dirty = True
        return data

    def _steam_featured_raw(self) -> List[Dict[str, Any]]:
        """Gộp New Releases + Top Sellers + Specials từ API featuredcategories."""
        raw = self._http_json(FEATURED_URL, timeout=7.0)
        if not isinstance(raw, dict):
            return []
        items: List[Dict[str, Any]] = []
        seen = set()
        for cat_key, cat_label in (("new_releases", "Mới phát hành"),
                                   ("top_sellers", "Bán chạy nhất"),
                                   ("specials", "Đang giảm giá"),
                                   ("coming_soon", "Sắp ra mắt")):
            for it in (raw.get(cat_key) or {}).get("items") or []:
                appid = str(it.get("id") or "").strip()
                if not appid.isdigit() or appid in seen:
                    continue
                seen.add(appid)
                items.append({
                    "steam_appid": appid,
                    "title": it.get("name") or "",
                    "categories": [cat_label],
                    "header_image": it.get("large_capsule_image") or it.get("header_image") or "",
                    "discount": it.get("discount_percent") or 0,
                })
        # Gộp nhãn category cho game xuất hiện ở nhiều bảng
        by_id = {}
        for it in items:
            by_id.setdefault(it["steam_appid"], it)
        return list(by_id.values())[: self.MAX_TRENDING]

    # ==================================================================
    # XÂY DỰNG 4 TẦNG DỮ LIỆU
    # ==================================================================
    def _build_trending(self, index: List[Dict[str, Any]], congu_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        raw_items = self._steam_featured_raw()

        if not raw_items:
            # Fallback offline: dùng chính kho Việt hóa để tab Khám Phá vẫn có nội dung
            for g in self.congu_games()[:12]:
                appid = str(g.get("steam_appid") or "").strip()
                if not appid:
                    continue
                raw_items.append({
                    "steam_appid": appid,
                    "title": g.get("title") or g.get("id") or "",
                    "categories": ["Kho CỔ NGỮ"],
                    "header_image": "",
                    "discount": 0,
                })

        if not raw_items:
            return []

        def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
            appid = item["steam_appid"]
            title = item["title"]
            detail = self.appdetails(appid) or {}
            if detail.get("name"):
                title = detail["name"]
            downloads = self._match_downloads(index, title, limit=5)
            congu = self._congu_lookup(congu_map, title, appid)
            poster, banner = self._congu_posters(congu, appid)
            best = downloads[0] if downloads else {}

            real_header = (detail.get("header_image") or item.get("header_image") or banner
                           or f"{STEAM_CDN}/{appid}/header.jpg")

            if congu and (congu.get("assets") or {}).get("poster"):
                final_poster = congu["assets"]["poster"]
            elif appid and str(appid).isdigit():
                final_poster = f"{STEAM_CDN}/{appid}/library_600x900.jpg"
            elif poster:
                final_poster = poster
            elif real_header:
                final_poster = f"/api/game/poster_preview?url={urllib.parse.quote(real_header)}"
            else:
                final_poster = ""

            return {
                "steam_appid": appid,
                "title": title,
                "poster_url": final_poster,
                "header_url": real_header,
                "hero_url": f"{STEAM_CDN}/{appid}/library_hero.jpg",
                "description": detail.get("short_description") or "",
                "genres": detail.get("genres") or guess_genres(title),
                "release_date": detail.get("release_date") or "",
                "is_free": detail.get("is_free", False),
                "price": detail.get("price") or "",
                "developers": detail.get("developers") or [],
                "categories": item.get("categories") or [],
                "discount": item.get("discount", 0),
                "trailer": (detail.get("movies") or [{}])[0].get("url") if detail.get("movies") else "",
                "pc_requirements_min": detail.get("pc_requirements_min") or "",
                "has_vietnamese": bool(congu),
                "viet_game_id": (congu or {}).get("id", ""),
                "vietnamese_title": (congu or {}).get("vietnamese_title", ""),
                "has_download": bool(downloads),
                "best_size": best.get("file_size") or "",
                "best_size_gb": best.get("size_gb"),
                "repackers": list({d.get("repacker", "") for d in downloads if d.get("repacker")})[:3],
                "downloads": downloads,
            }

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = [r for r in pool.map(enrich, raw_items) if r]

        # Ưu tiên: có Việt hóa + có link tải -> có link tải -> còn lại
        results.sort(key=lambda x: (not x["has_vietnamese"], not x["has_download"]))
        return results[: self.MAX_TRENDING]

    def _build_recent(self, index: List[Dict[str, Any]],
                      congu_map: Dict[str, Dict[str, Any]],
                      limit: int = 20) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Tầng 2 (Mới lên kệ) và Tầng 4 (Co-op / OnlineFix) theo uploadDate mới nhất."""
        recent: List[Dict[str, Any]] = []
        coop: List[Dict[str, Any]] = []
        seen_recent = set()
        seen_coop = set()

        for it in index:  # index đã sort mới nhất trước
            congu = self._congu_lookup(congu_map, it.get("display_title") or it.get("title", ""))
            appid = (congu or {}).get("steam_appid") or it.get("steam_appid_hint") or ""
            poster, banner = self._congu_posters(congu, str(appid))
            entry = {
                "title": it.get("display_title") or it.get("title") or "",
                "release_title": it.get("title") or "",
                "repacker": it.get("repacker") or "",
                "source": it.get("source") or "",
                "upload_date": it.get("upload_date") or "",
                "days_ago": it.get("days_ago"),
                "file_size": it.get("file_size") or "Không rõ",
                "size_gb": it.get("size_gb"),
                "uri": it.get("uri") or "",
                "is_portable": bool(it.get("is_portable")),
                "is_onlinefix": bool(it.get("is_onlinefix")),
                "genres": it.get("genres") or guess_genres(it.get("title", "")),
                "steam_appid": str(appid or ""),
                "poster_url": poster or "",
                "header_url": banner or "",
                "has_vietnamese": bool(congu),
                "viet_game_id": (congu or {}).get("id", ""),
                "vietnamese_title": (congu or {}).get("vietnamese_title", ""),
            }
            key = clean_title_key(entry["title"])
            if it.get("is_onlinefix"):
                if key and key not in seen_coop:
                    seen_coop.add(key)
                    coop.append(entry)
            elif key and key not in seen_recent:
                seen_recent.add(key)
                recent.append(entry)

        return recent[:limit], coop[:limit]

    def _build_hero(self, trending: List[Dict[str, Any]],
                    recent: List[Dict[str, Any]],
                    coop: List[Dict[str, Any]],
                    congu_games: List[Dict[str, Any]],
                    index: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Tầng 1: 1-3 tựa game tâm điểm (ưu tiên Việt hóa mới cập nhật + có link tải)."""
        heroes: List[Dict[str, Any]] = []
        used = set()

        def add(entry: Dict[str, Any]):
            if not entry:
                return
            key = clean_title_key(entry.get("title", ""))
            if not key or key in used:
                return
            used.add(key)
            heroes.append(entry)

        # A. Game Cổ Ngữ vừa cập nhật bản Việt hóa
        def _updated_ts(g: Dict[str, Any]) -> Tuple[int, int, int]:
            raw = str(((g.get("translation_stats") or {}).get("last_updated")) or "")
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
            if m:
                return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return (0, 0, 0)

        for g in sorted(congu_games, key=_updated_ts, reverse=True)[:3]:
            title = g.get("title") or g.get("id") or ""
            appid = str(g.get("steam_appid") or "")
            poster, banner = self._congu_posters(g, appid)
            downloads = self._match_downloads(index, title, limit=5)
            add({
                "kind": "viet",
                "title": title,
                "display_title": g.get("vietnamese_title") or g.get("title") or title,
                "vietnamese_title": g.get("vietnamese_title") or "",
                "steam_appid": appid,
                "viet_game_id": g.get("id", ""),
                "description": g.get("description") or "",
                "genres": [x.strip() for x in re.split(r"[,;]", g.get("genre") or "") if x.strip()][:3],
                "hero_url": banner,
                "poster_url": poster,
                "release_date": ((g.get("translation_stats") or {}).get("last_updated") or ""),
                "has_vietnamese": True,
                "has_download": bool(downloads),
                "best_size": downloads[0]["file_size"] if downloads else "",
                "repackers": list({d.get("repacker", "") for d in downloads})[:3],
                "downloads": downloads,
            })

        # B. Bom tấn Steam vừa ra mắt đã có link tải + Việt hóa
        for t in trending:
            if len(heroes) >= 2:
                break
            if t.get("has_download") and t.get("has_vietnamese"):
                add({
                    "kind": "trending",
                    "title": t["title"],
                    "display_title": t.get("vietnamese_title") or t["title"],
                    "vietnamese_title": t.get("vietnamese_title", ""),
                    "steam_appid": t["steam_appid"],
                    "viet_game_id": t.get("viet_game_id", ""),
                    "description": t.get("description", ""),
                    "genres": t.get("genres", [])[:3],
                    "hero_url": t.get("hero_url", ""),
                    "poster_url": t.get("poster_url", ""),
                    "release_date": t.get("release_date", ""),
                    "has_vietnamese": True,
                    "has_download": True,
                    "best_size": t.get("best_size", ""),
                    "repackers": t.get("repackers", []),
                    "downloads": t.get("downloads", []),
                })

        # C. Bản repack mới nhất đã có Việt hóa trong kho
        for r in recent:
            if len(heroes) >= 3:
                break
            if r.get("has_vietnamese"):
                add({
                    "kind": "repack",
                    "title": r["title"],
                    "display_title": r.get("vietnamese_title") or r["title"],
                    "vietnamese_title": r.get("vietnamese_title", ""),
                    "steam_appid": r.get("steam_appid", ""),
                    "viet_game_id": r.get("viet_game_id", ""),
                    "description": (f"Bản tải {r.get('repacker')} ({r.get('file_size')}) vừa lên kệ "
                                    f"ngày {r.get('upload_date') or 'gần đây'} — đã có Việt hóa trong CỔ NGỮ."),
                    "genres": r.get("genres", [])[:3],
                    "hero_url": r.get("header_url") or "",
                    "poster_url": r.get("poster_url") or "",
                    "release_date": r.get("upload_date", ""),
                    "has_vietnamese": True,
                    "has_download": True,
                    "best_size": r.get("file_size", ""),
                    "repackers": [r.get("repacker", "")],
                    "downloads": [{
                        "title": r.get("release_title") or r["title"],
                        "repacker": r.get("repacker", ""),
                        "file_size": r.get("file_size", ""),
                        "size_gb": r.get("size_gb"),
                        "upload_date": r.get("upload_date", ""),
                        "uri": r.get("uri", ""),
                        "is_portable": r.get("is_portable", False),
                        "is_onlinefix": r.get("is_onlinefix", False),
                    }],
                })

        # D. Chưa đủ 1 game -> lấy bản repack mới nhất bất kỳ
        if not heroes:
            pool = recent or coop
            if pool:
                r = pool[0]
                add({
                    "kind": "repack",
                    "title": r["title"],
                    "display_title": r["title"],
                    "vietnamese_title": "",
                    "steam_appid": r.get("steam_appid", ""),
                    "viet_game_id": "",
                    "description": (f"Bản tải {r.get('repacker')} ({r.get('file_size')}) cập nhật "
                                    f"{r.get('upload_date') or 'gần đây'}."),
                    "genres": r.get("genres", [])[:3],
                    "hero_url": r.get("header_url") or "",
                    "poster_url": r.get("poster_url") or "",
                    "release_date": r.get("upload_date", ""),
                    "has_vietnamese": False,
                    "has_download": True,
                    "best_size": r.get("file_size", ""),
                    "repackers": [r.get("repacker", "")],
                    "downloads": [{
                        "title": r.get("release_title") or r["title"],
                        "repacker": r.get("repacker", ""),
                        "file_size": r.get("file_size", ""),
                        "size_gb": r.get("size_gb"),
                        "upload_date": r.get("upload_date", ""),
                        "uri": r.get("uri", ""),
                        "is_portable": r.get("is_portable", False),
                        "is_onlinefix": r.get("is_onlinefix", False),
                    }],
                })

        return heroes[:3]

    def _build_recommendations(self, congu_games: List[Dict[str, Any]],
                              trending: List[Dict[str, Any]],
                              recent: List[Dict[str, Any]],
                              coop: List[Dict[str, Any]],
                              index: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Tạo danh sách 24-36 game đề xuất phong phú mọi thể loại (Kinh dị, Nhập vai, Hành động, Co-op, v.v.)."""
        recs: List[Dict[str, Any]] = []
        seen = set()

        def add_rec(entry: Dict[str, Any]):
            if not entry:
                return
            key = clean_title_key(entry.get("title", ""))
            if not key or key in seen:
                return
            seen.add(key)
            recs.append(entry)

        # 1. Toàn bộ game đã Việt hóa của Cổ Ngữ
        for g in congu_games:
            title = g.get("title") or g.get("id") or ""
            appid = str(g.get("steam_appid") or "")
            poster, banner = self._congu_posters(g, appid)
            downloads = self._match_downloads(index, title, limit=3)
            genres_list = [x.strip() for x in re.split(r"[,;]", g.get("genre") or "") if x.strip()]
            if not genres_list:
                genres_list = guess_genres(title)
            add_rec({
                "kind": "viet",
                "title": title,
                "display_title": g.get("vietnamese_title") or g.get("title") or title,
                "vietnamese_title": g.get("vietnamese_title") or "",
                "steam_appid": appid,
                "viet_game_id": g.get("id", ""),
                "description": g.get("description") or "",
                "genres": genres_list[:3],
                "hero_url": banner,
                "poster_url": poster,
                "release_date": ((g.get("translation_stats") or {}).get("last_updated") or ""),
                "has_vietnamese": True,
                "has_download": bool(downloads),
                "best_size": downloads[0]["file_size"] if downloads else "",
                "best_size_gb": downloads[0].get("size_gb") if downloads else None,
                "repackers": list({d.get("repacker", "") for d in downloads})[:3],
                "downloads": downloads,
            })

        # 2. Bổ sung các game hot từ trending
        for t in trending:
            add_rec(t)

        # 3. Bổ sung các bản co-op và repack mới
        for c in coop[:20]:
            add_rec(c)
        for r in recent[:20]:
            add_rec(r)

        return recs[:36]

    # ==================================================================
    # API CHÍNH: FEED
    # ==================================================================
    def get_feed(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Trả về toàn bộ dữ liệu tab Khám Phá (cache 6h, mở tab tức thì)."""
        if not force_refresh and os.path.isfile(self.cache_file):
            try:
                if time.time() - os.path.getmtime(self.cache_file) < self.CACHE_TTL:
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    if isinstance(cached, dict) and cached.get("steam_trending") is not None:
                        cached["cached"] = True
                        cached["watchlist"] = self.get_watchlist()
                        return cached
            except Exception:
                pass

        if not self._build_lock.acquire(timeout=45):
            return {"updated_at": int(time.time()), "cached": False, "building": True,
                    "hero": [], "recent_repacks": [], "steam_trending": [], "online_coop": [],
                    "stats": {}, "watchlist": self.get_watchlist()}
        try:
            index = self.hydra_index(force=force_refresh)
            congu_games = self.congu_games(force=force_refresh)
            congu_map = self.congu_map(force=force_refresh)

            trending = self._build_trending(index, congu_map)
            recent, coop = self._build_recent(index, congu_map, limit=60)
            hero = self._build_hero(trending, recent, coop, congu_games, index)
            recommendations = self._build_recommendations(congu_games, trending, recent, coop, index)

            source_counts: Dict[str, int] = {}
            for it in index:
                source_counts[it.get("source") or "Khác"] = source_counts.get(it.get("source") or "Khác", 0) + 1

            feed = {
                "updated_at": int(time.time()),
                "cached": False,
                "stats": {
                    "repacks": len(index),
                    "vietnamese": len([g for g in congu_games if g.get("id")]),
                    "trending": len(trending),
                    "online_coop": len(coop),
                    "sources": [{"name": k, "count": v}
                                for k, v in sorted(source_counts.items(), key=lambda kv: -kv[1])],
                },
                "hero": hero,
                "recommendations": recommendations,
                "recent_repacks": recent,
                "steam_trending": trending,
                "online_coop": coop,
                "watchlist": self.get_watchlist(),
            }

            try:
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(feed, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
            self._save_appdetails_cache()
            return feed
        finally:
            self._build_lock.release()

    # ==================================================================
    # TRAILER (HOVER PREVIEW) & SMART PC CHECK
    # ==================================================================
    def get_trailer(self, steam_appid: str, seconds: int = 12) -> Dict[str, Any]:
        """
        Trả về thông tin trailer + link clip MP4 cục bộ (proxy qua DPI-bypass) để phát khi hover thẻ.
        Steam hiện chỉ phát trailer qua DASH/HLS nên CỔ NGỮ tự cắt 12-20 giây đầu, lưu cache trong
        %APPDATA%/VietModHub/discovery_trailers và phát lại tức thì (kể cả khi mất mạng).
        """
        appid = str(steam_appid or "").strip()
        detail = self.appdetails(appid)
        if not detail:
            return {"success": False, "message": "Không lấy được thông tin trailer từ Steam."}
        movies = detail.get("movies") or []
        if not movies:
            return {"success": False, "message": "Tựa game này chưa có trailer trên Steam."}
        self._save_appdetails_cache()
        movie = next((m for m in movies if m.get("highlight")), movies[0])
        return {
            "success": True,
            "steam_appid": appid,
            "title": detail.get("name", ""),
            "thumbnail": movie.get("thumbnail", ""),
            "clip_url": f"/api/discovery/clip?appid={appid}&seconds={int(seconds)}",
            "movies": [{"name": m.get("name", ""), "thumbnail": m.get("thumbnail", "")} for m in movies],
        }

    def _trailer_dir(self) -> str:
        d = os.path.join(self.appdata_dir, "discovery_trailers")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    @staticmethod
    def _http_text(url: str, timeout: float = 10.0) -> str:
        """Tải nội dung text (XML/MPD) qua kênh vượt DPI."""
        try:
            raw = steam_direct_request(url, timeout=timeout)
            if raw:
                return raw.decode("utf-8", "ignore")
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    @staticmethod
    def _parse_dash_manifest(mpd_text: str) -> Optional[Dict[str, Any]]:
        """Bóc MPD của Steam -> chọn representation video nhẹ nhất + template segment."""
        if not mpd_text or "<MPD" not in mpd_text:
            return None
        dur_sec = 0.0
        m = re.search(r'mediaPresentationDuration="PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?"', mpd_text)
        if m:
            dur_sec = int(m.group(1) or 0) * 60 + float(m.group(2) or 0)

        best = None
        for block in re.findall(r'<AdaptationSet[^>]*contentType="video"[^>]*>(.*?)</AdaptationSet>',
                                mpd_text, re.S):
            tmpl = re.search(r"<SegmentTemplate\b[^>]*>", block)
            if not tmpl:
                continue
            init_m = re.search(r'initialization="([^"]+)"', tmpl.group(0))
            media_m = re.search(r'media="([^"]+)"', tmpl.group(0))
            dur_m = re.search(r'duration="(\d+)"', tmpl.group(0))
            ts_m = re.search(r'timescale="(\d+)"', tmpl.group(0))
            if not (init_m and media_m):
                continue
            seg_dur = 3.0
            if dur_m and ts_m:
                try:
                    seg_dur = float(dur_m.group(1)) / float(ts_m.group(1))
                except Exception:
                    seg_dur = 3.0
            for rep in re.findall(r"<Representation\b[^>]*>", block):
                if 'mimeType="video/mp4"' not in rep:
                    continue
                rep_id = re.search(r'id="(\d+)"', rep)
                bw = re.search(r'bandwidth="(\d+)"', rep)
                if not (rep_id and bw):
                    continue
                cand = {
                    "rep_id": rep_id.group(1),
                    "bandwidth": int(bw.group(1)),
                    "init": init_m.group(1),
                    "media": media_m.group(1),
                    "seg_dur": seg_dur or 3.0,
                    "duration": dur_sec,
                }
                if best is None or cand["bandwidth"] < best["bandwidth"]:
                    best = cand
        return best

    def build_preview_clip(self, steam_appid: str, seconds: int = 12) -> Dict[str, Any]:
        """Cắt N giây đầu của trailer (chỉ luồng video, nhẹ ~1-2MB) và lưu thành file MP4 cục bộ."""
        appid = str(steam_appid or "").strip()
        if not appid.isdigit():
            return {"success": False, "message": "Steam AppID không hợp lệ."}
        try:
            seconds = max(6, min(int(seconds or 12), 40))
        except Exception:
            seconds = 12

        out_path = os.path.join(self._trailer_dir(), f"{appid}_{seconds}s.mp4")

        def _done(cached: bool) -> Dict[str, Any]:
            return {"success": True, "cached": cached, "path": out_path,
                    "file": os.path.basename(out_path), "size": os.path.getsize(out_path)}

        if os.path.isfile(out_path) and os.path.getsize(out_path) > 20000:
            return _done(True)

        detail = self.appdetails(appid) or {}
        movies = detail.get("movies") or []
        if not movies:
            return {"success": False, "message": "Tựa game này chưa có trailer trên Steam."}
        movie = next((m for m in movies if m.get("highlight")), movies[0])
        mpd_url = movie.get("dash") or ""
        if not mpd_url:
            return {"success": False, "message": "Trailer không có định dạng DASH phù hợp."}

        lock = self._clip_locks.setdefault((appid, seconds), threading.Lock())
        with lock:
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 20000:
                return _done(True)

            rep = self._parse_dash_manifest(self._http_text(mpd_url, timeout=10.0))
            if not rep:
                return {"success": False, "message": "Không đọc được manifest trailer của Steam."}

            base = mpd_url.split("?")[0].rsplit("/", 1)[0] + "/"
            seg_dur = rep["seg_dur"] or 3.0
            total_segments = max(1, int(-(-seconds // seg_dur)))
            if rep.get("duration"):
                total_segments = min(total_segments, max(1, int(-(-rep["duration"] // seg_dur))))

            init_rel = rep["init"].replace("$RepresentationID$", rep["rep_id"])
            init_bytes = steam_direct_request(base + init_rel, timeout=12.0)
            if not init_bytes:
                return {"success": False, "message": "Không tải được init segment của trailer."}

            blob = bytearray(init_bytes)
            for idx in range(1, total_segments + 1):
                rel = (rep["media"]
                       .replace("$RepresentationID$", rep["rep_id"])
                       .replace("$Number%05d$", f"{idx:05d}")
                       .replace("$Number$", str(idx)))
                chunk = steam_direct_request(base + rel, timeout=10.0)
                if not chunk:
                    break
                blob.extend(chunk)
                if len(blob) > 14 * 1024 * 1024:  # Giới hạn 14MB để preview luôn nhẹ
                    break

            if len(blob) < 20000:
                return {"success": False, "message": "Trailer quá ngắn hoặc Steam không trả dữ liệu."}

            try:
                tmp_path = out_path + ".part"
                with open(tmp_path, "wb") as f:
                    f.write(bytes(blob))
                os.replace(tmp_path, out_path)
            except OSError as e:
                return {"success": False, "message": f"Không ghi được file trailer: {e}"}

            return _done(False)

    def system_specs(self) -> Dict[str, Any]:
        """Đọc nhanh RAM / CPU / GPU của máy người dùng (không cần thư viện ngoài)."""
        specs: Dict[str, Any] = {"ram_gb": None, "cpu": "", "gpu": "", "os": platform.platform()}
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                specs["ram_gb"] = round(mem.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                specs["cpu"] = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except Exception:
            pass

        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(8):
                    try:
                        with winreg.OpenKey(root, f"{i:04d}") as sub:
                            desc = str(winreg.QueryValueEx(sub, "DriverDesc")[0]).strip()
                            if desc and "Microsoft Basic" not in desc:
                                specs["gpu"] = desc
                                break
                    except OSError:
                        continue
        except Exception:
            pass
        return specs

    def pc_check(self, steam_appid: str) -> Dict[str, Any]:
        """Đối chiếu RAM máy với pc_requirements tối thiểu của game -> câu kết luận thân thiện."""
        appid = str(steam_appid or "").strip()
        specs = self.system_specs()
        detail = self.appdetails(appid) if appid else None
        req_text = (detail or {}).get("pc_requirements_min") or ""

        need_gb = None
        if req_text:
            for pattern in (r"(?:memory|ram)\s*:?\s*(\d+(?:[.,]\d+)?)\s*(gb|mb)",
                            r"(\d+(?:[.,]\d+)?)\s*(gb|mb)\s*(?:ram|memory)"):
                m = re.search(pattern, req_text, re.I)
                if m:
                    val = float(m.group(1).replace(",", "."))
                    unit = m.group(2).lower()
                    need_gb = round(val if unit == "gb" else val / 1024, 1)
                    break

        have_gb = specs.get("ram_gb")
        status, message = "unknown", "Chưa đủ dữ liệu cấu hình để đối chiếu."
        if need_gb and have_gb:
            if have_gb >= need_gb * 1.5:
                status = "great"
                message = f"🟢 Máy bạn dư sức chiến mượt (Cần RAM {need_gb:g}GB - Máy bạn có {have_gb:g}GB)"
            elif have_gb >= need_gb:
                status = "good"
                message = f"🟢 Đủ cấu hình chơi tốt (Cần RAM {need_gb:g}GB - Máy bạn có {have_gb:g}GB)"
            else:
                status = "weak"
                message = (f"🟠 Máy bạn hơi thiếu RAM (Cần {need_gb:g}GB - Máy bạn có {have_gb:g}GB). "
                           f"Hãy hạ đồ họa hoặc đóng ứng dụng nền.")
        elif have_gb:
            status = "unknown"
            message = f"⚪ Máy bạn có {have_gb:g}GB RAM. Game chưa công bố cấu hình tối thiểu rõ ràng."

        return {
            "success": True,
            "steam_appid": appid,
            "status": status,
            "message": message,
            "need_ram_gb": need_gb,
            "system": specs,
            "requirements_text": req_text[:400],
        }

    # ==================================================================
    # WATCHLIST ("THEO DÕI") & YÊU CẦU VIỆT HÓA
    # ==================================================================
    def get_watchlist(self) -> List[Dict[str, Any]]:
        try:
            if os.path.isfile(self.watchlist_file):
                with open(self.watchlist_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [w for w in data if isinstance(w, dict)]
        except Exception:
            pass
        return []

    def _save_watchlist(self, items: List[Dict[str, Any]]) -> bool:
        try:
            with open(self.watchlist_file, "w", encoding="utf-8") as f:
                json.dump(items[:200], f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def update_watchlist(self, action: str, title: str, steam_appid: str = "",
                         poster_url: str = "") -> Dict[str, Any]:
        title = (title or "").strip()
        if not title:
            return {"success": False, "message": "Thiếu tên game cần theo dõi."}
        items = self.get_watchlist()
        key = clean_title_key(title)
        items = [w for w in items if clean_title_key(w.get("title", "")) != key]

        if action == "remove":
            ok = self._save_watchlist(items)
            return {"success": ok, "watching": False, "watchlist": items,
                    "message": f"Đã bỏ theo dõi '{title}'."}

        items.insert(0, {
            "title": title,
            "steam_appid": str(steam_appid or ""),
            "poster_url": poster_url or "",
            "added_at": int(time.time()),
        })
        ok = self._save_watchlist(items)
        return {"success": ok, "watching": True, "watchlist": items,
                "message": f"Đã theo dõi '{title}'. CỔ NGỮ sẽ báo ngay khi các nguồn .json có bản tải!"}

    def request_vietnamese(self, title: str, steam_appid: str = "", note: str = "",
                           api_instance=None) -> Dict[str, Any]:
        """Ghi nhận yêu cầu Việt hóa: lưu watchlist + đẩy vào hàng đợi yêu cầu của app."""
        title = (title or "").strip()
        if not title:
            return {"success": False, "message": "Thiếu tên game cần Việt hóa."}
        result = {"success": True, "message": f"Đã ghi nhận yêu cầu Việt hóa '{title}'!"}
        try:
            if api_instance is not None:
                res = api_instance.submit_game_request(
                    game_name=title,
                    note=note or "Yêu cầu Việt hóa gửi từ tab Khám Phá",
                    steam_id=str(steam_appid or "") or None,
                    capsule=(f"{STEAM_CDN}/{steam_appid}/header.jpg" if str(steam_appid).isdigit() else None),
                )
                if isinstance(res, dict):
                    result.update({k: v for k, v in res.items() if k in ("success", "message")})
        except Exception as e:
            result["warning"] = f"Không đẩy được lên hàng đợi trung tâm: {e}"
        try:
            self.update_watchlist("add", title, steam_appid)
        except Exception:
            pass
        return result


# ==============================================================================
# SINGLETON DÙNG CHUNG TOÀN APP
# ==============================================================================
_DISCOVERY_INSTANCE: Optional[DiscoveryManager] = None
_DISCOVERY_LOCK = threading.Lock()


def get_discovery_manager(hydra_manager=None) -> DiscoveryManager:
    """Singleton tiện dụng cho các module khác (api/, app.py)."""
    global _DISCOVERY_INSTANCE
    if _DISCOVERY_INSTANCE is None:
        with _DISCOVERY_LOCK:
            if _DISCOVERY_INSTANCE is None:
                _DISCOVERY_INSTANCE = DiscoveryManager(hydra_manager=hydra_manager)
    elif hydra_manager is not None and _DISCOVERY_INSTANCE.hydra_manager is None:
        _DISCOVERY_INSTANCE.hydra_manager = hydra_manager
    return _DISCOVERY_INSTANCE
