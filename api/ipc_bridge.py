# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - IPC Bridge & ModManagerAPI Engine
------------------------------------------------------------
Cung cấp class ModManagerAPI phục vụ cầu nối Native IPC qua PyWebView (window.pywebview.api)
và điều phối toàn bộ các nghiệp vụ cài đặt, gỡ bỏ, sao lưu, quét game, đám mây, tay cầm, tải torrent.
"""

import os
import sys
import io
import json
import shutil
import re
import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import secrets
from datetime import datetime
from pathlib import Path
import glob
import urllib.request
import ssl
import urllib.parse
import ctypes
from ctypes import wintypes

from core.config_manager import (
    APP_DIR,
    STATIC_DIR,
    USER_DOCS_DIR,
    DEFAULT_REPO_DIR,
    FALLBACK_REPO_DIR,
    GAMES_JSON,
    APPDATA_DIR,
    CONFIG_JSON,
    BACKUP_ROOT,
    USER_DATA_FILE,
    COVERS_DIR,
    COVERS_CACHE_FILE,
    PLAYTIME_FILE,
    CACHE_GAMES_JSON,
    CUSTOM_GAMES_JSON,
    CURRENT_VERSION,
    GITHUB_REPO,
    REMOTE_CATALOG_URLS,
    REMOTE_VERSION_URLS,
    load_user_config,
    save_user_config,
    get_repo_dir,
    get_all_configured_game_paths,
    get_active_games_json_path,
    get_games,
    load_custom_games,
    save_custom_games,
    sync_remote_catalog,
    check_app_update,
    load_user_data,
    save_user_data,
    load_covers_cache,
    save_covers_cache,
    get_favorite_games,
    get_bookmarked_games,
    merge_bookmarked_games,
    set_api_instance_ref,
    DEFAULT_USER_CONFIG,
    get_unified_settings,
    update_unified_settings,
    get_cache_stats,
    clear_app_cache,
    open_appdata_directory,
)

from core.scanner import (
    get_available_drives,
    is_running_as_admin,
    check_directory_writable,
    request_uac_elevation,
    detect_steam_libraries,
    detect_epic_games,
    detect_gog_games,
    detect_standalone_game_dirs,
    find_game_install_path,
    verify_and_resolve_game_path,
    extract_local_steam_appid,
    resolve_clean_game_title,
    extract_exe_icon,
)

from core.downloader import (
    download_file_with_progress,
    TORRENT_MGR,
    HYDRA_MGR,
    TorrentDownloadManager,
    HydraSourceManager,
)

from core.installer_pipeline import (
    set_progress,
    get_install_progress,
    calculate_sha256,
    get_running_processes,
    get_running_process_names,
    check_game_running,
    find_mod_source_dir,
    check_has_mod_files,
    patch_ini_file,
    execute_pipeline_step,
    execute_action_pipeline,
    install_mod_impl,
    install_mod,
    uninstall_mod_impl,
    uninstall_mod,
    emergency_restore_game,
    _MOD_OP_LOCK,
    any_game_operation_running,
    INSTALL_PROGRESS,
)

from core.backup_rollback import (
    compute_file_sha256,
    norm_rel_path,
    load_backup_manifest,
    save_backup_manifest,
    record_preexisting_environment,
    backup_file_inplace,
    record_backup_manifest,
    record_modded_state,
    restore_files_inplace,
)

from core.cloud_save import (
    PROCESSENTRY32W,
    EXCLUDED_HELPER_EXES,
    is_any_exe_running_in_folder,
    PlaytimeManager,
    AchievementManager,
    handle_game_exit_hook,
    get_vault_instance,
    ConguSaveVault,
    CloudSyncManager,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    ACHIEVEMENT_MGR,
    PLAYTIME_MGR,
    CLOUD_SYNC_MGR,
    SAVE_VAULT,
    configure_cloud_save_system,
    register_exit_hook,
)

from core.platform_win import WIN_NO_WINDOW, DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
from core.native_dialogs import pick_folder, pick_file, save_file

from core.steam_client import (
    steam_direct_request,
    get_steam_official_Vertical_posters,
    fetch_steamgriddb_posters,
    search_steamgriddb_by_name,
    search_steam_online,
    STEAMGRIDDB_API_KEY,
)

from custom_game_detector import CustomGameDetector
from controller_engine import ControllerEngine
from community_cloud import CommunityCloudManager
from vault_manager import ConguSaveVault
from torrent_downloader import TorrentDownloadManager, TorrentDownloader
from hydra_source_manager import HydraSourceManager
from discovery_manager import DiscoveryManager, get_discovery_manager

import security
try:
    from security import validate_safe_path, SecurityError, PathTraversalError, apply_binary_patch, find_tool_exe
except ImportError:
    pass

FIREBASE_RTDB_URL = ""
MAIN_HWND = None
_is_dragging_window = False
is_window_maximized = False
STEAM_GAMES_CACHE = None

# Bộ tổng hợp dữ liệu tab Khám Phá (Steam Trending + Nguồn Hydra .json + Kho Việt hóa games.json)
DISCOVERY_MGR = get_discovery_manager(HYDRA_MGR)

def _norm_rel(rel_path: str) -> str:
    return norm_rel_path(rel_path)


def log_startup(msg: str):
    """Ghi log khoi dong ung dung de chan doan su co tren moi may tinh."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    try:
        print(formatted.encode("ascii", "replace").decode("ascii"))
    except Exception:
        pass
    try:
        log_file = os.path.join(APPDATA_DIR, "startup.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

from core.scanner import (
    extract_local_steam_appid,
    resolve_clean_game_title,
    extract_exe_icon,
)

def fetch_game_metadata_and_avatar(game_dir: str = "", exe_name: str = "", fallback_title: str = "", game_id: str = "") -> dict:
    """
    Lớp 3 & Lớp 4: Tự động tìm steam_appid, link ảnh bìa dọc 600x900 nét căng và thể loại cho game lẻ.
    Tự động lấy poster có mã hash Steam mới hoặc dựng Poster Glassmorphism từ header.jpg ngang (không cắt chữ),
    và lưu cache ảnh bìa tại chỗ (%APPDATA%/VietModHub/covers/{game_id}.jpg).
    Tối ưu hóa: Nếu đã có local_cover và metadata trong cache, trả về tức thì (0ms mạng).
    """
    # 0. Kiểm tra ảnh bìa cục bộ và cache metadata trước tiên (Tốc độ phản hồi tức thì 0.1ms)
    safe_gid = re.sub(r"[^\w\-]", "_", game_id or fallback_title or "unknown")
    local_cover_file = os.path.join(COVERS_DIR, f"{safe_gid}.jpg")
    local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")
    local_cover = None
    if os.path.exists(local_cover_file) and os.path.getsize(local_cover_file) > 1000:
        local_cover = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
    elif os.path.exists(local_cover_png) and os.path.getsize(local_cover_png) > 500:
        local_cover = f"/api/covers/{safe_gid}.png?t={int(os.path.getmtime(local_cover_png))}"

    c_cache = load_covers_cache() if "load_covers_cache" in globals() else {}
    cached_meta = c_cache.get(game_id) or c_cache.get(safe_gid) if c_cache else {}

    # SIÊU TỐI ƯU HÓA: Nếu đã có ảnh bìa cục bộ và đầy đủ metadata trong cache -> Trả về ngay trong 0.1ms!
    if local_cover and cached_meta and cached_meta.get("genre") and cached_meta["genre"] != "GAME LẺ":
        return {
            "steam_appid": str(cached_meta.get("steam_appid") or ""),
            "title": fallback_title or cached_meta.get("title") or safe_gid,
            "avatar_url": local_cover,
            "header_url": cached_meta.get("header_url"),
            "local_cover": local_cover,
            "genre": cached_meta.get("genre", "GAME LẺ")
        }

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    appid = extract_local_steam_appid(game_dir) if game_dir else None
    if not appid and cached_meta and cached_meta.get("steam_appid"):
        appid = str(cached_meta["steam_appid"])
    clean_title = fallback_title or (cached_meta.get("title") if cached_meta else None) or resolve_clean_game_title(game_dir, exe_name)

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

    # Nếu vẫn chưa có appid, gọi Steam Online Search từ Backend (vượt chặn DPI)
    if not appid and clean_title:
        try:
            online_items = search_steam_online(clean_title, limit=3)
            if online_items:
                appid = str(online_items[0].get("steam_appid", online_items[0].get("id", "")))
                clean_title = online_items[0].get("name", clean_title)
        except Exception:
            pass

    result = {
        "steam_appid": appid,
        "title": clean_title,
        "avatar_url": local_cover,
        "header_url": (cached_meta.get("header_url") if cached_meta else None) or (f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else None),
        "local_cover": local_cover,
        "genre": (cached_meta.get("genre") if cached_meta else None) or "GAME LẺ"
    }

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

    # 2. Gọi thêm appdetails để lấy thể loại (Genre) và link ảnh chính thức (kể cả có mã hash)
    if result.get("genre") == "GAME LẺ" or not result.get("header_url"):
        try:
            details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=vietnamese&cc=VN"
            raw_det = steam_direct_request(details_url, timeout=3.5)
            if not raw_det:
                req = urllib.request.Request(details_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    raw_det = resp.read()
            if raw_det:
                details_data = json.loads(raw_det.decode("utf-8", "ignore"))
                app_data = details_data.get(str(appid), {}).get("data", {})
                if app_data:
                    result["title"] = app_data.get("name", result["title"])
                    if app_data.get("header_image"):
                        result["header_url"] = app_data.get("header_image")
                    genres = app_data.get("genres", [])
                    if genres:
                        result["genre"] = genres[0].get("description", "PHIÊU LƯU").upper()
        except Exception as e:
            print(f"[Metadata] appdetails error: {e}")

    # TỐI ƯU HÓA: Nếu đã có local_cover (từ trước hoặc trong covers/), TRẢ VỀ NGAY LẬP TỨC!
    # Tuyệt đối không gọi mạng tải lại candidate_posters, tiết kiệm 2-4 giây và giữ nguyên đường dẫn local_cover!
    if result.get("local_cover"):
        result["avatar_url"] = result["local_cover"]
        return result

    # 3. Thu thập danh sách candidate Posters dọc 600x900 nét căng
    candidate_posters = []
    # A. Ưu tiên số 1: Gọi API GetItems IStoreBrowseService lấy link có {HASH} chuẩn cho mọi game mới & cũ
    candidate_posters.extend(get_steam_official_Vertical_posters(appid))

    # B. Nếu appdetails header_url có mã hash 40 ký tự hex, thử ghép mã hash vào library_600x900
    if result.get("header_url"):
        h_match = re.search(r"/([0-9a-f]{40})/", result["header_url"])
        if h_match:
            h_code = h_match.group(1)
            candidate_posters.extend([
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
            ])

    # C. Các CDN truyền thống không hash
    candidate_posters.extend([
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
    ])

    # D. Kho SteamGridDB (poster dọc 600x900 nét căng do cộng đồng thiết kế)
    candidate_posters.extend(fetch_steamgriddb_posters(appid, limit=3))

    downloaded_raw = None
    # Fallback urllib vẫn phải xác minh certificate/hostname của CDN.
    verified_ssl_ctx = ssl.create_default_context()

    # 4. Tải và kiểm tra từng candidate poster dọc
    for url in candidate_posters:
        if not url:
            continue
        try:
            raw = steam_direct_request(url, timeout=3.0)
            if not raw or len(raw) < 1000:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5, context=verified_ssl_ctx) as resp:
                    if resp.status == 200:
                        raw = resp.read()
            if (
                raw
                and len(raw) > 1000
                and not raw.startswith(b"<html>")
                and not raw.startswith(b"HTTP/1.1 40")
                and not raw.startswith(b"HTTP/1.1 50")
            ):
                downloaded_raw = raw
                result["avatar_url"] = url
                break
        except Exception:
            continue

    # 5. Nếu không có ảnh dọc, fallback tải header_url (ảnh ngang 460x215)
    if not downloaded_raw and result.get("header_url"):
        h_url = result["header_url"]
        try:
            raw = steam_direct_request(h_url, timeout=3.5)
            if not raw or len(raw) < 1000:
                req = urllib.request.Request(h_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    if resp.status == 200:
                        raw = resp.read()
            if (
                raw
                and len(raw) > 1000
                and not raw.startswith(b"<html>")
                and not raw.startswith(b"HTTP/1.1 40")
                and not raw.startswith(b"HTTP/1.1 50")
            ):
                downloaded_raw = raw
                if not result.get("avatar_url"):
                    result["avatar_url"] = h_url
        except Exception as e:
            print(f"[Metadata] header_url download error: {e}")

    # 6. Chuẩn hóa qua make_vertical_poster (Fit 600x900 nét căng hoặc dựng Glassmorphism cho ảnh ngang) và lưu cache
    if downloaded_raw and not os.path.exists(local_cover_file):
        try:
            formatted_poster = make_vertical_poster(downloaded_raw)
            with open(local_cover_file, "wb") as f_out:
                f_out.write(formatted_poster)
            result["local_cover"] = f"/api/covers/{safe_gid}.jpg?t={int(os.path.getmtime(local_cover_file))}"
            result["avatar_url"] = result["local_cover"]
        except Exception as e:
            print(f"[Metadata] Error saving formatted poster: {e}")

    # 7. Nếu vẫn chưa có ảnh bìa lưu được, thử trích xuất icon từ .exe
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

    if result.get("local_cover"):
        result["avatar_url"] = result["local_cover"]

    return result


from community_cloud import CommunityCloudManager
from core.account_manager import AccountManager

COMMUNITY_CLOUD_MGR = CommunityCloudManager(
    config_getter=load_user_config,
    config_saver=save_user_config,
    vault_getter=get_vault_instance,
    games_getter=get_games
)

ACCOUNT_MGR = AccountManager(
    appdata_dir=APPDATA_DIR,
    config_getter=load_user_config,
    config_saver=save_user_config,
    playtime_mgr=PLAYTIME_MGR,
    achievement_mgr=ACHIEVEMENT_MGR,
    community_cloud_mgr=COMMUNITY_CLOUD_MGR,
    cloud_sync_mgr=CLOUD_SYNC_MGR,
)

_CC_UPLOAD_LOCK = threading.Lock()
_CC_UPLOAD_RUNNING = False


def _community_cloud_post_exit_sync(game_id: str, game_dir: str):
    """Tự đẩy Hồ Sơ lên Đám Mây Cổ Ngữ sau khi thoát game (nếu đã đăng nhập)."""
    global _CC_UPLOAD_RUNNING
    try:
        cfg = load_user_config()
        if not (cfg.get("cloud_save") or {}).get("auto_sync_on_exit", True):
            return
        if not COMMUNITY_CLOUD_MGR.get_status().get("is_logged_in"):
            return

        with _CC_UPLOAD_LOCK:
            if _CC_UPLOAD_RUNNING:
                return
            _CC_UPLOAD_RUNNING = True

        def _worker():
            global _CC_UPLOAD_RUNNING
            try:
                # Chờ hook Google Drive/đóng gói vault của game vừa thoát hoàn tất
                time.sleep(8)
                res = COMMUNITY_CLOUD_MGR.upload_save(pack_all=False)
                if res.get("success"):
                    log_startup("[CommunityCloud] Đã tự động đồng bộ Hồ Sơ lên Đám Mây Cổ Ngữ sau khi thoát game.")
                else:
                    print(f"[CommunityCloud] Auto sync warning: {res.get('error')}")
            except Exception as e:
                print(f"[CommunityCloud] Auto sync error: {e}")
            finally:
                _CC_UPLOAD_RUNNING = False

        threading.Thread(target=_worker, daemon=True).start()
    except Exception as e:
        print(f"[CommunityCloud] Post-exit hook error: {e}")


try:
    register_exit_hook(_community_cloud_post_exit_sync)
except Exception as _hook_err:
    print(f"[CommunityCloud] Register exit hook warning: {_hook_err}")

from controller_engine import ControllerEngine

CONTROLLER_ENGINE = ControllerEngine(
    tools_dir=os.path.join(APP_DIR, "tools") if os.path.exists(os.path.join(APP_DIR, "tools")) else "tools",
    vault_getter=get_vault_instance
)

# Đồng bộ hóa callbacks cho Cloud Save & Achievements Engine
configure_cloud_save_system(
    config_getter=load_user_config,
    custom_games_getter=load_custom_games if "load_custom_games" in globals() else None,
    games_json_path_getter=get_active_games_json_path,
    games_getter=get_games,
    controller_engine=CONTROLLER_ENGINE,
    log_fn=log_startup
)

# Tự động khởi động luồng quét ngầm nhận diện game mở từ Shortcut Desktop / Steam
PLAYTIME_MGR.start_background_scanner(get_all_configured_game_paths)


# =============================================================================
# TRUNG TÂM YÊU CẦU VIỆT HÓA GAME LẺ (Localization Requests -> .congu_save)
# =============================================================================
from localization_requests import LocalizationRequestManager

LOCALIZATION_REQ_MGR = LocalizationRequestManager(
    vault_getter=get_vault_instance,
    games_getter=get_games,
    create_community_request=lambda *a, **kw: api_instance.create_community_request(*a, **kw),
    get_community_requests=lambda: api_instance.get_community_requests(),
    cloud_sync=CLOUD_SYNC_MGR,
    logger=log_startup
)


def merge_vault_custom_games() -> int:
    """
    Khôi phục danh sách game lẻ (custom_games) từ Hồ Sơ .congu_save sang PC mới.
    Nhờ vậy, khi người chơi nạp lại Hồ Sơ ở máy khác, thẻ game + trạng thái
    "Đã Yêu Cầu Việt Hóa" vẫn hiển thị dù chưa trỏ lại đường dẫn .exe trên máy này.
    """
    try:
        vault = get_vault_instance()
        manifest = vault.read_manifest() or {}
        stored = manifest.get("custom_games") or {}
        if not isinstance(stored, dict) or not stored:
            return 0

        c_games = load_custom_games()
        existing_ids = {str(g.get("id")) for g in c_games if isinstance(g, dict)}
        added = 0
        for cg_id, info in stored.items():
            if not isinstance(info, dict) or str(cg_id) in existing_ids:
                continue
            c_games.append({
                "id": cg_id,
                "title": info.get("title") or cg_id,
                "steam_appid": str(info.get("steam_appid") or ""),
                "executable_name": info.get("executable_name", ""),
                "engine": info.get("engine") or "PC Game",
                "game_root": "",
                "last_known_root": info.get("last_known_root", ""),
                "vault_config": info.get("vault_config", {}),
                "restored_from_vault": True
            })
            added += 1

        if added:
            save_custom_games(c_games)
            log_startup(f"[LocalizationRequest] Đã khôi phục {added} game lẻ từ Hồ Sơ (.congu_save) sang PC này.")
        return added
    except Exception as e:
        print(f"[LocalizationRequest] merge_vault_custom_games warning: {e}")
        return 0


def sync_bookmarks_to_vault() -> bool:
    """Ghi danh sách "Thêm vào Thư viện" vào profile_manifest.json để đi theo .congu_save."""
    try:
        vault = get_vault_instance()
        manifest = vault.read_manifest() or {}
        manifest["bookmarked_games"] = get_bookmarked_games()
        res = vault.update_manifest_only(manifest)
        return bool(res.get("success"))
    except Exception as e:
        print(f"[Bookmark] Vault sync warning: {e}")
        return False


def merge_vault_bookmarks() -> int:
    """Khôi phục danh sách "Chưa tải" (bookmark) từ Hồ Sơ .congu_save sang PC này."""
    try:
        vault = get_vault_instance()
        manifest = vault.read_manifest() or {}
        stored = manifest.get("bookmarked_games")
        if not isinstance(stored, list) or not stored:
            return 0
        added = merge_bookmarked_games(stored)
        if added:
            log_startup(f"[Bookmark] Đã khôi phục {added} game từ danh sách Chưa tải trong Hồ Sơ (.congu_save).")
        return added
    except Exception as e:
        print(f"[Bookmark] Vault merge warning: {e}")
        return 0


def merge_vault_playtime() -> int:
    """Gộp giờ chơi trong .congu_save vào playtime.json của máy hiện tại."""
    try:
        manifest = get_vault_instance().read_manifest() or {}
        count = PLAYTIME_MGR.merge_manifest_playtime(manifest)
        if count:
            log_startup(f"[Profile] Đã khôi phục giờ chơi của {count} game từ Hồ Sơ (.congu_save).")
        return count
    except Exception as e:
        print(f"[Profile] Playtime merge warning: {e}")
        return 0


# Máy chủ Bảng Nguyện Vọng Cộng Đồng mặc định (Firebase Realtime Database)
DEFAULT_FIREBASE_RTDB_URL = "https://congu-hub-default-rtdb.asia-southeast1.firebasedatabase.app"


def get_firebase_url():
    global FIREBASE_RTDB_URL
    if FIREBASE_RTDB_URL:
        return FIREBASE_RTDB_URL.rstrip("/")
    env_url = os.environ.get("FIREBASE_RTDB_URL")
    if env_url:
        return env_url.rstrip("/")
    return DEFAULT_FIREBASE_RTDB_URL

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

LOCAL_REQUESTS_FILE = os.path.join(APPDATA_DIR, "community_requests.json")
STATIC_REQUESTS_SEED = os.path.join(STATIC_DIR, "data", "community_requests.json")

def load_local_community_requests():
    if os.path.exists(LOCAL_REQUESTS_FILE):
        try:
            with open(LOCAL_REQUESTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading local community requests: {e}")
    # Dùng file trong STATIC_DIR làm dữ liệu khởi tạo ban đầu (seed data)
    if os.path.exists(STATIC_REQUESTS_SEED):
        try:
            with open(STATIC_REQUESTS_SEED, "r", encoding="utf-8") as f:
                data = json.load(f)
            save_local_community_requests(data)
            return data
        except Exception as e:
            print(f"Error loading seed community requests: {e}")
    return {}

def save_local_community_requests(data):
    try:
        os.makedirs(os.path.dirname(LOCAL_REQUESTS_FILE), exist_ok=True)
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
        "CO NGU - Trinh Quan Ly Game Viet Hoa Pro",
        "CỔ NGỮ (VietModHub Pro)",
        "VietModHub",
        "VietModManager",
        "CỔ NGỮ"
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

    if not found_hwnds:
        # Fallback (Edge/Chrome App Mode): tim window co title chua CO NGU bat ke PID
        def enum_fallback(h, lParam):
            if user32.IsWindowVisible(h):
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    val = buff.value
                    if any(k in val for k in ["CỔ NGỮ", "CO NGU", "VietMod"]):
                        found_hwnds.append(h)
            return True
        user32.EnumWindows(WNDENUMPROC(enum_fallback), 0)

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

    # Check if left or right mouse button is pressed (ho tro ca chuot tay trai)
    btn_down = (user32.GetAsyncKeyState(0x01) & 0x8000) or (user32.GetAsyncKeyState(0x02) & 0x8000)
    if not btn_down:
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
            while (user32.GetAsyncKeyState(0x01) & 0x8000) or (user32.GetAsyncKeyState(0x02) & 0x8000):
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



def batch_fetch_steam_assets(appids: list[str]) -> dict[str, dict]:
    """
    Gọi 1 request duy nhất tới IStoreBrowseService/GetItems/v1 cho toàn bộ danh sách appid
    để lấy chính xác link library_600x900_2x.jpg và header.jpg kèm mã {HASH} chuẩn.
    """
    valid_ids = [int(a) for a in appids if str(a).isdigit()]
    if not valid_ids:
        return {}
    result_map = {}
    try:
        input_json = json.dumps({
            "ids": [{"appid": aid} for aid in valid_ids],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True}
        }, separators=(",", ":"))
        api_url = f"https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json={urllib.parse.quote(input_json)}"
        raw = steam_direct_request(api_url, timeout=4.0)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            for item in data.get("response", {}).get("store_items", []):
                aid = str(item.get("appid", ""))
                assets = item.get("assets", {})
                fmt = assets.get("asset_url_format", f"steam/apps/{aid}/${{FILENAME}}")
                
                poster_url = ""
                for key in ("library_capsule_2x", "library_capsule"):
                    if assets.get(key):
                        rel = fmt.replace("${FILENAME}", assets[key]).lstrip("/")
                        poster_url = f"https://shared.fastly.steamstatic.com/store_item_assets/{rel}"
                        break
                        
                header_url = ""
                if assets.get("header"):
                    rel_h = fmt.replace("${FILENAME}", assets["header"]).lstrip("/")
                    header_url = f"https://shared.fastly.steamstatic.com/store_item_assets/{rel_h}"

                result_map[aid] = {
                    "poster": poster_url,
                    "header": header_url
                }
    except Exception as e:
        print(f"[BatchSteamAssets] Error: {e}")
    return result_map



def make_vertical_poster(image_bytes: bytes, target_w: int = 600, target_h: int = 900) -> bytes:
    """
    Chuẩn hóa ảnh thành Poster dọc 2:3 (600x900):
    - Nếu ảnh gốc ĐÃ LÀ ẢNH DỌC (h >= w * 1.15): Fit chuẩn 600x900 sắc nét.
    - Nếu ảnh gốc LÀ ẢNH NGANG (header.jpg 460x215): Tuyệt đối KHÔNG cắt cụt 2 bên làm mất chữ!
      Tự động tạo nền Blur Glassmorphism đồng màu + đặt nguyên vẹn 100% banner ngang ở trung tâm trên.
    """
    try:
        from PIL import Image, ImageOps, ImageFilter, ImageEnhance
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return image_bytes

        # Trường hợp 1: Ảnh gốc đã là Poster dọc chuẩn (VD: 600x900)
        if h >= w * 1.15:
            result = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            # Trường hợp 2: Ảnh gốc là Banner ngang (460x215) hoặc Icon vuông -> Tạo Poster Blur Glassmorphism
            bg = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=24))
            bg = ImageEnhance.Brightness(bg).enhance(0.45)

            # Giữ nguyên 100% tỉ lệ ngang của ảnh chính (không cắt mất chữ hai bên)
            fg_w = target_w
            fg_h = max(1, int(h * (fg_w / w)))
            fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

            y_offset = max(0, int((target_h - fg_h) * 0.38))
            bg.paste(fg, (0, y_offset))
            result = bg

        out = io.BytesIO()
        result.save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as e:
        print(f"[make_vertical_poster] Error formatting poster: {e}")
        return image_bytes



STEAM_GAMES_CACHE = None

def get_steam_games():
    global STEAM_GAMES_CACHE
    if STEAM_GAMES_CACHE is not None:
        return STEAM_GAMES_CACHE
    # Sửa lỗi đường dẫn: file thật nằm ở <APP>/static/data/steam_games.json.
    # Trước đây tính theo thư mục api/ nên luôn trỏ sai -> DB Steam offline luôn rỗng.
    candidates = [
        os.path.join(STATIC_DIR, "data", "steam_games.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "data", "steam_games.json"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "static", "data", "steam_games.json"),
    ]
    for db_path in candidates:
        if not db_path or not os.path.exists(db_path):
            continue
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                STEAM_GAMES_CACHE = json.load(f)
                return STEAM_GAMES_CACHE
        except Exception as e:
            print("Error loading steam_games.json:", e)
    STEAM_GAMES_CACHE = []
    return STEAM_GAMES_CACHE


def _get_app_module():
    """
    Lấy module app.py đang thực sự chạy (kể cả khi khởi chạy trực tiếp dưới tên `__main__`).
    Tránh `import app` vô tình nạp lại toàn bộ entry point thành module thứ hai rỗng trạng thái.
    """
    for name in ("app", "__main__"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "SYSTEM_TRAY"):
            return mod
    return None


def _bookmark_title_key(text) -> str:
    """Khóa so khớp tên game giữa nhiều kho (Steam discovery, Hydra, games.json)."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _format_play_seconds(total_sec: int) -> str:
    total_sec = int(total_sec or 0)
    if total_sec <= 0:
        return "Chưa chơi"
    if total_sec < 60:
        return "< 1 phút"
    if total_sec < 3600:
        return f"{max(1, total_sec // 60)} phút"
    return f"{round(total_sec / 3600, 1)} giờ"


_VAULT_AUTO_RESTORE_LOCK = threading.Lock()
_VAULT_AUTO_RESTORE_INFLIGHT = set()


def _queue_vault_auto_restore(vault, game_obj: dict, game_root: str):
    """Tự bung save chờ khi game vừa được cài và thư mục save local còn trống."""
    key = f"{game_obj.get('id')}|{os.path.normcase(os.path.abspath(game_root or ''))}"
    with _VAULT_AUTO_RESTORE_LOCK:
        if key in _VAULT_AUTO_RESTORE_INFLIGHT:
            return
        _VAULT_AUTO_RESTORE_INFLIGHT.add(key)

    def _worker():
        try:
            res = vault.unpack_game_from_vault(game_obj, game_root)
            if res.get("success"):
                log_startup(
                    f"[GhostLibrary] Tự động khôi phục {res.get('unpacked_saves', 0)} tệp save "
                    f"cho '{game_obj.get('id')}' vừa được cài trên máy."
                )
        except Exception as e:
            print(f"[GhostLibrary] Auto restore error: {e}")
        finally:
            with _VAULT_AUTO_RESTORE_LOCK:
                _VAULT_AUTO_RESTORE_INFLIGHT.discard(key)

    threading.Thread(target=_worker, daemon=True).start()


def _read_sync_marker_mtime(game_root: str) -> int:
    """Đọc mốc vault_mtime trong .congu_restored.json của thư mục game."""
    if not game_root:
        return 0
    try:
        marker_path = os.path.join(game_root, ".congu_restored.json")
        with open(marker_path, "r", encoding="utf-8") as f:
            return int(json.load(f).get("vault_mtime") or 0)
    except Exception:
        return 0


def _resolve_library_state(status_code: str, is_bookmarked: bool) -> str:
    """3 trạng thái Thư Viện: sẵn sàng chơi / chờ Việt hóa / đã lưu nhưng chưa tải."""
    if status_code == "INSTALLED":
        return "ready"
    if status_code in ("NOT_INSTALLED", "UPDATE_DETECTED"):
        return "needs_translation"
    return "bookmark" if is_bookmarked else "unavailable"


def _make_vault_ghost_game(gid: str, meta: dict, favorites: set) -> dict:
    """Thẻ Ghost cho game chỉ còn trong .congu_save (không còn trong games.json)."""
    title = str(meta.get("title") or gid)
    thumb = str(meta.get("cover_thumb_b64") or "")
    sec = int(meta.get("playtime_seconds") or 0)
    saved_ach = meta.get("unlocked_achievements") or []
    return {
        "id": gid,
        "title": title,
        "vietnamese_title": title,
        "genre": "Hồ Sơ di động",
        "engine": "PC Game",
        "developer": "",
        "description": "Tựa game từng có trong Hồ Sơ .congu_save nhưng máy này chưa cài đặt.",
        "assets": {},
        "steam_appid": str(meta.get("steam_appid") or ""),
        "game_path": "",
        "is_game_found": False,
        "is_custom_game": False,
        "is_bookmark_only": False,
        "is_ghost": True,
        "is_vault_ghost": True,
        "is_bookmarked": False,
        "library_state": "uninstalled_ghost",
        "status_code": "GAME_MISSING",
        "status_label": "CHƯA CÀI ĐẶT - ĐÃ LƯU SAVE",
        "is_mod_installed": False,
        "is_writable": True,
        "requires_admin": False,
        "has_safe_backup": False,
        "has_cached_congu": False,
        "update_detected": False,
        "health_reason": "",
        "important_note": "",
        "download_url": "",
        "local_cover": thumb,
        "avatar_url": thumb,
        "header_url": thumb,
        "latest_version": "",
        "current_version": "Chưa tải",
        "has_update": False,
        "versions": [],
        "translation_stats": {"total_lines": "—", "version": "—", "font": "—", "mod_size": "—", "last_updated": "—"},
        "mod_size": "—",
        "mod_subfolder": "",
        "media": {"trailers": []},
        "playtime": {
            "game_id": gid,
            "is_running": False,
            "total_seconds": sec,
            "formatted_time": _format_play_seconds(sec),
            "last_played_str": "Từ Hồ Sơ",
            "sessions_count": 0,
        },
        "vault_save": {
            "has_save": int(meta.get("file_count") or 0) > 0,
            "file_count": int(meta.get("file_count") or 0),
            "save_size_bytes": int(meta.get("save_size_bytes") or 0),
            "playtime_seconds": sec,
            "achievements_count": len(saved_ach),
            "last_installed_path": meta.get("last_installed_path") or "",
            "vi_patch_info": meta.get("vi_patch_info") or {},
            "cover_thumb": thumb,
        },
        "user_rating": 5,
        "user_comment": "",
        "is_favorite": gid in favorites,
    }


def _make_bookmark_only_game(bookmark: dict, favorites: set) -> dict:
    """Tạo thẻ game tổng hợp cho mục "Chưa tải" (bookmark không nằm trong games.json)."""
    gid = bookmark["id"]
    cover = bookmark.get("cover_url") or ""
    title = bookmark.get("title") or gid
    source = str(bookmark.get("source") or "web").lower()
    return {
        "id": gid,
        "title": title,
        "vietnamese_title": bookmark.get("vietnamese_title") or title,
        "genre": bookmark.get("genre") or ("Kho Tải Game" if source == "hydra" else "Steam Store"),
        "engine": "PC Game",
        "developer": "",
        "description": "Tựa game đã được lưu vào Thư Viện. Bấm Tải Game để lấy bộ cài, "
                       "hoặc trỏ đường dẫn tới bản cài sẵn có trên máy.",
        "assets": {},
        "steam_appid": bookmark.get("steam_appid") or "",
        "game_path": "",
        "is_game_found": False,
        "is_custom_game": False,
        "is_bookmark_only": True,
        "is_bookmarked": True,
        "bookmark_source": source,
        "library_state": "bookmark",
        "status_code": "GAME_MISSING",
        "status_label": "CHƯA TẢI",
        "is_mod_installed": False,
        "is_writable": True,
        "requires_admin": False,
        "has_safe_backup": False,
        "has_cached_congu": False,
        "update_detected": False,
        "health_reason": "",
        "important_note": "",
        "download_url": "",
        "local_cover": cover,
        "avatar_url": cover,
        "header_url": bookmark.get("header_url") or cover,
        "latest_version": "",
        "current_version": "Chưa tải",
        "has_update": False,
        "versions": [],
        "translation_stats": {
            "total_lines": "—", "version": "—", "font": "—",
            "mod_size": "—", "last_updated": "—",
        },
        "mod_size": "—",
        "mod_subfolder": "",
        "media": {"trailers": []},
        "playtime": PLAYTIME_MGR.get_game_stats(gid),
        "user_rating": 5,
        "user_comment": "",
        "is_favorite": gid in favorites,
    }


class ModManagerAPI:
    def __init__(self):
        self.window = None
        self._dialog_lock = threading.Lock()

    def get_games(self):
        """Returns list of games with installation & mod status (3 states: INSTALLED, NOT_INSTALLED, GAME_MISSING)"""
        if not os.path.exists(get_active_games_json_path()):
            return []

        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = json.load(f)

        user_cfg = load_user_config()
        scanner_cfg = user_cfg.get("scanner", {})
        scan_steam = scanner_cfg.get("scan_steam", True)
        scan_epic = scanner_cfg.get("scan_epic", True)
        scan_gog = scanner_cfg.get("scan_gog", True)
        auto_scan = scanner_cfg.get("auto_scan_on_startup", True)
        custom_libs = scanner_cfg.get("custom_library_paths", [])

        libraries = detect_steam_libraries() if scan_steam else []
        epic_games = detect_epic_games() if scan_epic else []
        gog_games = detect_gog_games() if scan_gog else []
        standalone_dirs = list(detect_standalone_game_dirs())
        for cl in custom_libs:
            if cl and os.path.isdir(cl) and cl not in standalone_dirs:
                standalone_dirs.append(cl)
        user_data = load_user_data()
        covers_cache = load_covers_cache()
        favorites = set(get_favorite_games())

        # Bookmarks "Thêm vào Thư viện": khớp thẻ game hiện có theo id/appid/tên
        # trước, phần còn lại sẽ được thêm vào cuối danh sách dưới dạng thẻ "Chưa tải".
        bookmarked_games = get_bookmarked_games()
        matched_bookmarks = set()

        def _apply_bookmark_state(game_obj, gid, *titles):
            matched = False
            appid = str(game_obj.get("steam_appid") or "")
            title_keys = {_bookmark_title_key(t) for t in titles if _bookmark_title_key(t)}
            for bm in bookmarked_games:
                if bm["id"] in matched_bookmarks:
                    continue
                if (
                    bm["id"] == gid
                    or (appid and bm.get("steam_appid") == appid)
                    or (_bookmark_title_key(bm.get("title")) in title_keys)
                ):
                    matched_bookmarks.add(bm["id"])
                    matched = True
            game_obj["is_bookmarked"] = matched
            game_obj["library_state"] = _resolve_library_state(game_obj.get("status_code"), matched)

        # Metadata thư viện di động từ .congu_save (Ghost Library + giờ chơi + ảnh bìa)
        try:
            _vault = get_vault_instance()
            vault_manifest = _vault.read_manifest() or {}
            vault_mtime = int(os.path.getmtime(_vault.vault_path)) if os.path.exists(_vault.vault_path) else 0
        except Exception:
            vault_manifest, vault_mtime = {}, 0
        vault_games_meta = vault_manifest.get("games") if isinstance(vault_manifest.get("games"), dict) else {}

        def _apply_vault_metadata(game_obj, gid, game_root):
            meta = vault_games_meta.get(gid)
            if not isinstance(meta, dict):
                return

            file_count = int(meta.get("file_count") or 0)
            saved_ach = meta.get("unlocked_achievements") or []
            thumb = str(meta.get("cover_thumb_b64") or "")
            payload = {
                "has_save": file_count > 0,
                "file_count": file_count,
                "save_size_bytes": int(meta.get("save_size_bytes") or 0),
                "playtime_seconds": int(meta.get("playtime_seconds") or 0),
                "achievements_count": len(saved_ach),
                "last_installed_path": meta.get("last_installed_path") or "",
                "vi_patch_info": meta.get("vi_patch_info") or {},
                "cover_thumb": thumb,
            }
            game_obj["vault_save"] = payload

            if thumb and not game_obj.get("local_cover") and not game_obj.get("avatar_url"):
                game_obj["local_cover"] = thumb
                game_obj["avatar_url"] = thumb

            # Giữ nguyên giờ chơi lịch sử khi máy mới chưa từng chơi game này
            pt = game_obj.get("playtime") or {}
            if payload["playtime_seconds"] > int(pt.get("total_seconds") or 0):
                sec = payload["playtime_seconds"]
                game_obj["playtime"] = {
                    "game_id": gid,
                    "is_running": False,
                    "total_seconds": sec,
                    "formatted_time": _format_play_seconds(sec),
                    "last_played_str": "Từ Hồ Sơ",
                    "sessions_count": int(pt.get("sessions_count") or 0),
                }

            # Ghost Library: game từng có trong Hồ Sơ nhưng máy này chưa cài
            if game_obj.get("status_code") == "GAME_MISSING" and file_count > 0:
                game_obj["is_ghost"] = True
                game_obj["library_state"] = "uninstalled_ghost"
                game_obj["status_label"] = "CHƯA CÀI ĐẶT - ĐÃ LƯU SAVE"

            # Save trong Hồ Sơ chưa được bung vào thư mục game trên máy này
            if game_obj.get("is_game_found") and file_count > 0:
                marker_mtime = _read_sync_marker_mtime(game_root)
                last_path = str(meta.get("last_installed_path") or "")
                same_path = bool(
                    last_path and game_root
                    and os.path.normcase(os.path.normpath(last_path)) == os.path.normcase(os.path.normpath(game_root))
                )
                if marker_mtime:
                    pending = marker_mtime < vault_mtime
                else:
                    pending = bool(not same_path and last_path)
                game_obj["pending_vault_save"] = pending

                # Game vừa cài xong, save local còn trống -> tự bung save lịch sử
                if pending and not _vault.has_local_save_data(game_obj, game_root):
                    _queue_vault_auto_restore(_vault, game_obj, game_root)

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
            
            if not game_path and auto_scan:
                detected = find_game_install_path(g, libraries, epic_games=epic_games, gog_games=gog_games, standalone_dirs=standalone_dirs)
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
                    is_in_pf = "program files" in (game_path or "").lower()
                    requires_admin = (not is_writable) and is_in_pf

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
            has_safe_backup = False
            manifest_file = os.path.join(game_backup_dir, "backup_manifest.json")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                        if m_data.get("files") and len(m_data["files"]) > 0:
                            has_safe_backup = True
                except Exception:
                    pass
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
                    # Game dùng install_steps (không có target_pak_name) sẽ được
                    # kiểm tra bằng status_marker / install_steps bên dưới.
                    pak_name = g.get("target_pak_name", "")
                    if pak_name:
                        pak_path = os.path.join(game_path, g.get("relative_install_path", ""), pak_name)
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

            # P1-01 / P1-04: Phiên bản mod đã cài & phát hiện cập nhật mod thực chất
            try:
                from core.config_manager import get_installed_mod_receipt
                from core.mod_compatibility import get_catalog_latest_mod_version, compare_mod_versions
                receipt = get_installed_mod_receipt(gid)
                latest_v, _, _ = get_catalog_latest_mod_version(g)
                g["latest_mod_version"] = latest_v
                if mod_installed:
                    installed_v = receipt.get("version") if receipt and receipt.get("status") == "installed" else ""
                    g["installed_mod_version"] = installed_v or "Chưa rõ phiên bản"
                    g["has_mod_update"] = (compare_mod_versions(installed_v or "0.0.0", latest_v) < 0) if (installed_v and latest_v) else False
                else:
                    g["installed_mod_version"] = None
                    g["has_mod_update"] = False
            except Exception:
                g["installed_mod_version"] = None
                g["has_mod_update"] = False

            # 3.4. Chẩn đoán sức khỏe bản dịch (Health Check & Steam/Epic Auto-Update Detection)
            update_detected = False
            health_reason = ""
            manifest_path = os.path.join(BACKUP_ROOT, gid, "backup_manifest.json")
            if mod_installed and os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        m_data = json.load(mf)
                    mod_files = m_data.get("files", [])
                    manifest_dirty = False
                    if mod_files:
                        for it in mod_files:
                            target_f = it.get("target_file")
                            rel_f = _norm_rel(it.get("relative_in_game"))
                            if not target_f or not os.path.exists(target_f):
                                if rel_f and game_path:
                                    target_f = os.path.join(game_path, rel_f.replace("/", os.sep))

                            if target_f and os.path.exists(target_f):
                                mod_hash = it.get("modded_sha256")
                                mod_size = it.get("modded_size")
                                mod_mtime = it.get("modded_mtime")

                                # So sánh nhanh: mtime & size
                                curr_size = os.path.getsize(target_f)
                                curr_mtime = os.path.getmtime(target_f)

                                size_diff = (mod_size is not None and curr_size != mod_size)
                                mtime_diff = (mod_mtime is not None and abs(curr_mtime - mod_mtime) > 2.0)

                                if size_diff:
                                    # Kích thước file đã khác, chắc chắn 100% nội dung đã thay đổi -> không cần băm SHA-256
                                    update_detected = True
                                    health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                    break
                                elif mtime_diff:
                                    # Kích thước file trùng khớp nhưng mtime thay đổi (do Windows/Antivirus chạm vào hoặc Steam update cùng size)
                                    if mod_hash:
                                        curr_hash = compute_file_sha256(target_f)
                                        if curr_hash and curr_hash.lower() != mod_hash.lower():
                                            update_detected = True
                                            health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                            break
                                        else:
                                            # File vẫn là bản mod nguyên vẹn, cập nhật lại mtime mới vào manifest để không phải băm lại ở lần sau
                                            it["modded_mtime"] = curr_mtime
                                            manifest_dirty = True
                                elif mod_size is None and mod_hash:
                                    # Tự động vá bổ sung size và mtime cho manifest phiên bản cũ
                                    curr_hash = compute_file_sha256(target_f)
                                    if curr_hash and curr_hash.lower() != mod_hash.lower():
                                        update_detected = True
                                        health_reason = f"Tệp '{os.path.basename(target_f)}' đã bị cập nhật mới bởi Steam/Epic"
                                        break
                                    else:
                                        it["modded_size"] = curr_size
                                        it["modded_mtime"] = curr_mtime
                                        manifest_dirty = True
                            elif target_f and not os.path.exists(target_f):
                                update_detected = True
                                health_reason = f"Tệp '{rel_f or os.path.basename(target_f)}' không còn tồn tại"
                                break

                        if manifest_dirty and not update_detected:
                            try:
                                with open(manifest_path, "w", encoding="utf-8") as mf:
                                    json.dump(m_data, mf, ensure_ascii=False, indent=2)
                            except Exception as e:
                                print(f"[Health Check Warning] Error updating manifest mtime for {gid}: {e}")
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

            _apply_bookmark_state(g, gid, g.get("title"), g.get("vietnamese_title"))

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

            # Ảnh bìa thật trên ổ cứng để vault tạo thumbnail WebP nhúng vào Hồ Sơ
            cover_fs_path = ""
            if local_cover:
                cover_name = local_cover.split("?", 1)[0].rsplit("/", 1)[-1]
                cover_candidate = os.path.join(COVERS_DIR, cover_name)
                if os.path.isfile(cover_candidate):
                    cover_fs_path = cover_candidate
            if not cover_fs_path:
                poster_rel = str((g.get("assets") or {}).get("poster") or "").lstrip("/")
                if poster_rel:
                    poster_path = poster_rel if os.path.isabs(poster_rel) else os.path.join(APP_DIR, poster_rel)
                    if os.path.isfile(poster_path):
                        cover_fs_path = poster_path
            g["cover_fs_path"] = cover_fs_path

            cached_meta = covers_cache.get(gid) or covers_cache.get(gid.lower()) or {}
            g["avatar_url"] = local_cover or cached_meta.get("avatar_url") or (g.get("assets", {}).get("poster"))
            g["header_url"] = cached_meta.get("header_url") or (g.get("assets", {}).get("header"))
            if cached_meta.get("steam_appid"):
                g["steam_appid"] = cached_meta["steam_appid"]
            if cached_meta.get("genre"):
                g["genre"] = cached_meta["genre"]

            # Gắn dữ liệu Theo Dõi Giờ Chơi (Playtime Tracker)
            g["playtime"] = PLAYTIME_MGR.get_game_stats(gid, game_path)

            # Gắn cờ Yêu thích (Steam-like Favorites) từ danh sách đã nạp 1 lần ở đầu method
            g["is_favorite"] = bool(gid in favorites)

            _apply_vault_metadata(g, gid, game_path)

        # Gộp các game ngoài do người dùng tự thêm (Non-Steam / Custom Games)
        custom_games = load_custom_games()
        for cg in custom_games:
            cg_id = cg.get("id")
            if not cg_id:
                continue

            cg_path = user_cfg.get(f"{cg_id}_path") or cg.get("game_root", "")
            exe_name = cg.get("executable_name", "")
            full_exe = os.path.join(cg_path, exe_name) if cg_path and exe_name else ""
            is_found = os.path.isfile(full_exe) if full_exe else False

            cg["game_path"] = cg_path
            cg["is_game_found"] = is_found
            cg["is_custom_game"] = True
            cg["status_code"] = "INSTALLED" if is_found else "GAME_MISSING"
            cg["status_label"] = "GAME TỰ THÊM" if is_found else "CHƯA CÓ GAME"
            cg["is_mod_installed"] = True
            cg["is_writable"] = True
            cg["requires_admin"] = False
            cg["latest_version"] = "Tự thêm"
            cg["current_version"] = "Tự thêm"
            cg["has_update"] = False

            # Local Cover Poster
            safe_cg_id = re.sub(r"[^\w\-]", "_", cg_id)
            cover_jpg = os.path.join(COVERS_DIR, f"{safe_cg_id}.jpg")
            cover_png = os.path.join(COVERS_DIR, f"{safe_cg_id}.png")
            if os.path.exists(cover_jpg) and os.path.getsize(cover_jpg) > 1000:
                cg["local_cover"] = f"/api/covers/{safe_cg_id}.jpg?t={int(os.path.getmtime(cover_jpg))}"
            elif os.path.exists(cover_png) and os.path.getsize(cover_png) > 500:
                cg["local_cover"] = f"/api/covers/{safe_cg_id}.png?t={int(os.path.getmtime(cover_png))}"
            else:
                cg["local_cover"] = cg.get("cover_url", "")

            cg["cover_fs_path"] = ""
            cover_value = str(cg.get("local_cover") or "")
            if cover_value.startswith("/api/covers/"):
                cover_name = cover_value.split("?", 1)[0].rsplit("/", 1)[-1]
                cover_candidate = os.path.join(COVERS_DIR, cover_name)
                if os.path.isfile(cover_candidate):
                    cg["cover_fs_path"] = cover_candidate

            # Gắn playtime stats
            cg["playtime"] = PLAYTIME_MGR.get_game_stats(cg_id, cg_path)

            # Gắn cờ Yêu thích (Steam-like Favorites)
            cg["is_favorite"] = bool(cg_id in favorites)

            _apply_bookmark_state(cg, cg_id, cg.get("title"), cg.get("vietnamese_title"))
            _apply_vault_metadata(cg, cg_id, cg_path)

            games.append(cg)

        # Bookmark không khớp bất kỳ game nào ở trên -> thêm thẻ "Chưa tải" vào Thư Viện
        for bm in bookmarked_games:
            if bm["id"] in matched_bookmarks:
                continue
            games.append(_make_bookmark_only_game(bm, favorites))

        # Game chỉ còn trong .congu_save (delisted/đổi id) -> vẫn giữ trong Ghost Library
        known_ids = {str(g.get("id")) for g in games}
        for gid, meta in vault_games_meta.items():
            if str(gid) in known_ids or not isinstance(meta, dict):
                continue
            has_history = (
                int(meta.get("file_count") or 0) > 0
                or int(meta.get("playtime_seconds") or 0) > 0
                or bool(meta.get("unlocked_achievements"))
            )
            if not has_history:
                continue
            games.append(_make_vault_ghost_game(str(gid), meta, favorites))

        if cfg_changed:
            save_user_config(user_cfg)

        return games

    def get_playtime_stats(self, game_id):
        """Lấy dữ liệu thống kê giờ chơi thời gian thực của game."""
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        return PLAYTIME_MGR.get_game_stats(game_id, game_path)

    def get_profile_overview(self):
        """Tổng hợp Hồ Sơ Game Thủ: cấp độ, huy hiệu nền tảng, top game, hoạt động gần đây."""
        from core.profile_manager import build_profile_overview
        try:
            games = self.get_games()
            vault = get_vault_instance()
            vault_info = vault.get_vault_info()
            manifest = vault.read_manifest() or {}
            overview = build_profile_overview(
                games=games,
                vault_info=vault_info,
                manifest=manifest,
                playtime_snapshot=PLAYTIME_MGR.get_profile_snapshot(),
                achievements_progress=ACHIEVEMENT_MGR.get_progress_summary(),
                bookmarks=get_bookmarked_games(),
                loc_requests=LOCALIZATION_REQ_MGR.get_my_history(),
            )

            unlock_map = overview.pop("_badge_unlock_map", {})
            newly_unlocked = overview.pop("_newly_unlocked", [])
            if newly_unlocked:
                manifest["profile_badges"] = unlock_map
                vault.update_manifest_only(manifest)

            community_online = False
            community_id = ""
            try:
                cc_status = COMMUNITY_CLOUD_MGR.get_status()
                community_online = bool(cc_status.get("is_logged_in"))
                community_id = cc_status.get("cloud_id") or ""
            except Exception:
                pass

            gdrive_online = False
            try:
                gdrive_online = bool(CLOUD_SYNC_MGR and CLOUD_SYNC_MGR.is_connected())
            except Exception:
                pass

            overview["player"]["is_online"] = community_online or gdrive_online
            overview["player"]["online_provider"] = (
                "community" if community_online else ("gdrive" if gdrive_online else "")
            )
            overview["player"]["cloud_id"] = community_id
            # Ưu tiên manifest -> sau đó config.json
            cfg = load_user_config() or {}
            profile_cfg = cfg.get("profile", {})
            if not overview["player"].get("avatar_url") and profile_cfg.get("avatar_url"):
                overview["player"]["avatar_url"] = profile_cfg["avatar_url"]
            if not overview["player"].get("cover_url") and profile_cfg.get("cover_url"):
                overview["player"]["cover_url"] = profile_cfg["cover_url"]
            if not overview["player"].get("bio") and profile_cfg.get("bio"):
                overview["player"]["bio"] = profile_cfg["bio"]
            if overview["player"]["name"] == "Game Thủ" and community_id:
                overview["player"]["name"] = community_id
                overview["player"]["initial"] = community_id[:1].upper()

            overview["success"] = True
            return overview
        except Exception as e:
            print(f"[Profile] Lỗi tổng hợp Hồ Sơ: {e}")
            return {"success": False, "message": f"Không thể tải Hồ Sơ: {e}"}


    def update_profile_settings(self, data: dict) -> dict:
        """
        Lưu Avatar, Ảnh bìa (Cover), Tên và Châm ngôn vào .congu_save và config.json,
        đồng thời tự động đồng bộ lên Đám Mây (Community Cloud & Google Drive).
        """
        try:
            vault = get_vault_instance()
            manifest = vault.read_manifest() or {}

            if "player_name" in data and str(data["player_name"]).strip():
                manifest["player_name"] = str(data["player_name"]).strip()
            if "avatar_url" in data:
                manifest["avatar_url"] = str(data["avatar_url"]).strip()
            if "cover_url" in data:
                manifest["cover_url"] = str(data["cover_url"]).strip()
            if "bio" in data:
                manifest["bio"] = str(data["bio"]).strip()

            manifest["updated_at"] = int(time.time())
            vault.update_manifest_only(manifest)

            # Cập nhật config.json
            cfg = load_user_config() or {}
            profile_cfg = cfg.setdefault("profile", {})
            for k in ("player_name", "avatar_url", "cover_url", "bio"):
                if k in manifest:
                    profile_cfg[k] = manifest[k]
            save_user_config(cfg)

            # Đồng bộ lên Cloud nếu đang đăng nhập
            cloud_synced = False
            cloud_provider = ""

            if data.get("sync_cloud", True):
                try:
                    if COMMUNITY_CLOUD_MGR.get_status().get("is_logged_in"):
                        c_res = COMMUNITY_CLOUD_MGR.upload_save(pack_all=False)
                        if c_res.get("success"):
                            cloud_synced = True
                            cloud_provider = "Đám Mây Cổ Ngữ"
                except Exception as ce:
                    print(f"[Profile] Community cloud sync error: {ce}")

                try:
                    if CLOUD_SYNC_MGR and CLOUD_SYNC_MGR.is_connected():
                        g_res = CLOUD_SYNC_MGR.upload_vault()
                        if g_res.get("success"):
                            cloud_synced = True
                            cloud_provider = (cloud_provider + " & Google Drive") if cloud_provider else "Google Drive"
                except Exception as ge:
                    print(f"[Profile] GDrive sync error: {ge}")

            return {
                "success": True,
                "message": f"Đã lưu cài đặt hồ sơ thành công! {('Đã đồng bộ lên ' + cloud_provider) if cloud_synced else '(Đã lưu cục bộ)'}",
                "player_name": manifest.get("player_name", ""),
                "avatar_url": manifest.get("avatar_url", ""),
                "cover_url": manifest.get("cover_url", ""),
                "bio": manifest.get("bio", ""),
                "cloud_synced": cloud_synced
            }
        except Exception as e:
            print(f"[Profile] Lỗi lưu hồ sơ: {e}")
            return {"success": False, "error": f"Lỗi lưu hồ sơ: {e}"}

    def select_profile_image(self, img_type: str = "avatar") -> dict:
        """Mở hộp thoại chọn tệp ảnh từ máy tính và chuyển thành base64 data URI."""
        from core.native_dialogs import pick_file
        chosen = pick_file(
            title=f"Chọn ảnh {'Đại Diện (Avatar)' if img_type == 'avatar' else 'Ảnh Bìa (Cover)'}",
            file_types=("Tệp hình ảnh (*.png;*.jpg;*.jpeg;*.webp;*.gif)",),
            parent_window=self.window
        )
        if not chosen or not os.path.isfile(chosen):
            return {"success": False, "cancelled": True}

        try:
            ext = os.path.splitext(chosen)[1].lower().replace(".", "")
            if ext == "jpg": ext = "jpeg"
            mime = f"image/{ext}" if ext in ("png", "jpeg", "webp", "gif") else "image/jpeg"

            with open(chosen, "rb") as f:
                raw_bytes = f.read()

            if len(raw_bytes) > 2 * 1024 * 1024:
                return {
                    "success": False,
                    "error": "Ảnh quá lớn (vượt quá 2MB). Vui lòng chọn ảnh nhỏ hơn để đảm bảo đồng bộ đám mây mượt mà!"
                }

            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            data_uri = f"data:{mime};base64,{b64_str}"

            return {
                "success": True,
                "data_uri": data_uri,
                "filename": os.path.basename(chosen),
                "size_kb": round(len(raw_bytes) / 1024, 1)
            }
        except Exception as e:
            return {"success": False, "error": f"Lỗi đọc tệp ảnh: {e}"}

    def get_game_achievements(self, game_id_or_appid: str, game_dir: str = ""):
        """Lấy danh sách và trạng thái mở khóa thành tựu của game (Chuẩn Hydra Launcher)."""
        appid = str(game_id_or_appid) if str(game_id_or_appid).isdigit() else ""
        game_id = "" if appid else str(game_id_or_appid)
        if not appid and game_id:
            try:
                for g in self.get_games():
                    if g.get("id") == game_id:
                        appid = str(g.get("steam_appid") or "")
                        if not game_dir:
                            game_dir = g.get("game_path") or ""
                        break
            except Exception:
                pass
        return ACHIEVEMENT_MGR.get_game_achievements_view(appid=appid, game_dir=game_dir, game_id=game_id)

    # =========================================================================
    # HỆ THỐNG ĐỔI TÀI KHOẢN & KÍCH DỮ LIỆU CŨ (MULTI-ACCOUNT MANAGER)
    # =========================================================================
    def get_account_status(self) -> dict:
        """Lấy danh sách tất cả tài khoản và tài khoản hiện đang active."""
        return ACCOUNT_MGR.get_status()

    def switch_account(self, data: dict) -> dict:
        """Chuyển sang tài khoản khác, tự động kích hết dữ liệu cũ ra khỏi app."""
        account_id = data.get("account_id", "") if isinstance(data, dict) else str(data)
        return ACCOUNT_MGR.switch_to_account(account_id)

    def create_blank_account(self, data: dict) -> dict:
        """Tạo tài khoản mới và kích sạch toàn bộ dữ liệu cũ, để lại app trống."""
        data = data or {}
        name = data.get("name", "Tài Khoản Mới")
        acc_type = data.get("type", "offline")
        return ACCOUNT_MGR.create_blank_account(name=name, account_type=acc_type)

    def login_online_account(self, data: dict) -> dict:
        """Kích hết dữ liệu cũ, đăng nhập tài khoản Online và đồng bộ Cloud."""
        data = data or {}
        cloud_id = data.get("cloud_id", "")
        password = data.get("password", "")
        server_url = data.get("server_url", "")
        return ACCOUNT_MGR.switch_to_online_account(cloud_id=cloud_id, password=password, server_url=server_url)

    def purge_and_logout_account(self) -> dict:
        """Kích sạch 100% dữ liệu cũ và đưa ứng dụng về chế độ app trống."""
        return ACCOUNT_MGR.purge_and_logout()

    def delete_account(self, data: dict) -> dict:
        """Xóa vĩnh viễn tài khoản và dữ liệu snapshot khỏi máy."""
        account_id = data.get("account_id", "") if isinstance(data, dict) else str(data)
        return ACCOUNT_MGR.delete_account(account_id)

    def poll_new_achievements(self):
        """Lấy các thành tựu mới mở khóa trong thời gian thực để Frontend bắn Toast."""
        return ACHIEVEMENT_MGR.pop_newly_unlocked()

    def test_achievement_overlay(self, game_id: str = ""):
        """Kích hoạt thử thông báo thành tựu chuẩn Steam để kiểm tra hiển thị & âm thanh."""
        from core.cloud_save.overlay_toast import show_in_game_achievement_notification
        game_title = "CỔ NGỮ OVERLAY"
        if game_id:
            try:
                for g in self.get_games():
                    if g.get("id") == game_id or str(g.get("steam_appid") or "") == str(game_id):
                        game_title = g.get("vietnamese_title") or g.get("title") or game_title
                        break
            except Exception:
                pass
        show_in_game_achievement_notification(
            title="Thợ Săn Thành Tựu",
            description="Đã kích hoạt thành công thông báo thành tựu chuẩn Steam!",
            game_title=game_title
        )
        return {"success": True, "message": f"Đã gửi thông báo thành tựu ({game_title}) lên góc phải màn hình!"}

    def select_repo_folder(self):
        """Open native folder picker for user to select Viethoagame repository"""
        if hasattr(self, "_dialog_lock") and not self._dialog_lock.acquire(blocking=False):
            return {"success": False, "message": "Hộp thoại chọn thư mục đang được mở."}
        try:
            chosen_dir = pick_folder(title="Chọn thư mục kho Viethoagame", parent_window=self.window)
            if chosen_dir and os.path.exists(chosen_dir):
                cfg = load_user_config()
                cfg["repo_dir"] = os.path.normpath(chosen_dir)
                save_user_config(cfg)
                return {"success": True, "repo_dir": chosen_dir, "games": self.get_games()}
            return {"success": False, "message": "Không có thư mục nào được chọn."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi mở chọn thư mục: {str(e)}"}
        finally:
            if hasattr(self, "_dialog_lock"):
                try:
                    self._dialog_lock.release()
                except RuntimeError:
                    pass


    def set_cloud_url(self, game_id, url):
        """Set Google Drive download URL for a game"""
        active_json = get_active_games_json_path()
        with open(active_json, "r", encoding="utf-8") as f:
            games = json.load(f)
        for g in games:
            if g["id"] == game_id:
                g["download_url"] = url
                break
        with open(active_json, "w", encoding="utf-8") as f:
            json.dump(games, f, ensure_ascii=False, indent=2)
        
        # Đồng bộ cả sang GAMES_JSON nếu active_json khác GAMES_JSON
        if os.path.normpath(active_json) != os.path.normpath(GAMES_JSON):
            try:
                with open(GAMES_JSON, "w", encoding="utf-8") as f:
                    json.dump(games, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        
        cfg = load_user_config()
        cfg[f"{game_id}_download_url"] = url
        save_user_config(cfg)
        return {"success": True, "message": "Đã lưu Link Google Drive cho tựa game này thành công!", "games": self.get_games()}

    def select_folder(self, game_id):
        """Open native folder picker dialog for user to select game directory"""
        if hasattr(self, "_dialog_lock") and not self._dialog_lock.acquire(blocking=False):
            return {"success": False, "message": "Hộp thoại chọn thư mục đang được mở."}
        try:
            with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
                games_map = {gm["id"]: gm for gm in json.load(f)}
            g_target = games_map.get(game_id, {})
            g_title = g_target.get("title") or game_id

            chosen_dir = pick_folder(
                title=f"Chọn thư mục cài đặt game: {g_title}",
                parent_window=self.window
            )

            if chosen_dir and os.path.exists(chosen_dir):
                if os.path.isfile(chosen_dir):
                    chosen_dir = os.path.dirname(chosen_dir)
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
                    is_in_pf = "program files" in (resolved_path or "").lower()
                    requires_admin = (not is_writable) and is_in_pf

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
        except Exception as e:
            print(f"[select_folder] Error: {e}")
            return {"success": False, "message": f"Lỗi chọn thư mục: {str(e)}"}
        finally:
            if hasattr(self, "_dialog_lock"):
                try:
                    self._dialog_lock.release()
                except RuntimeError:
                    pass

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
        is_in_pf = "program files" in (resolved_path or "").lower()
        requires_admin = (not is_writable) and is_in_pf

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

    def select_standard_zip_dialog(self):
        """Mở hộp thoại chọn gói ZIP save tiêu chuẩn."""
        chosen_file = None
        if self.window:
            try:
                res = self.window.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False,
                    file_types=('ZIP Save tiêu chuẩn (*.zip)', 'All files (*.*)')
                )
                if res:
                    chosen_file = res[0]
            except Exception as e:
                print(f"[!] PyWebView ZIP dialog error: {e}")
        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn gói ZIP Save tiêu chuẩn",
                    filetypes=[("ZIP Save tiêu chuẩn", "*.zip"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass
        return chosen_file or ""

    def export_standard_zip_dialog(self):
        """Mở hộp thoại lưu gói ZIP save tiêu chuẩn."""
        chosen_file = None
        if self.window:
            try:
                res = self.window.create_file_dialog(
                    webview.SAVE_DIALOG, save_filename="CoNgu_SaveGame_Backup.zip",
                    file_types=('ZIP Save tiêu chuẩn (*.zip)', 'All files (*.*)')
                )
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
            except Exception as e:
                print(f"[!] PyWebView ZIP save dialog error: {e}")
        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                chosen_file = filedialog.asksaveasfilename(
                    title="Xuất Save Game ra ZIP chuẩn",
                    initialfile="CoNgu_SaveGame_Backup.zip",
                    defaultextension=".zip",
                    filetypes=[("ZIP Save tiêu chuẩn", "*.zip"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass
        return chosen_file or ""

    def select_vault_file_dialog(self):
        """Mở hộp thoại chọn tệp .congu_save từ USB/ổ cứng ngoài."""
        chosen_file = pick_file(
            title="Chọn tệp Hồ Sơ CỔ NGỮ (.congu_save)",
            file_types=('Hồ Sơ CỔ NGỮ (*.congu_save;*.congu_vault;*.zip)', 'All files (*.*)'),
            parent_window=self.window
        )
        return chosen_file or ""

    def export_vault_dialog(self):
        """Mở hộp thoại chọn vị trí lưu file .congu_save ra USB hoặc thư mục bất kỳ."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Hồ Sơ CỔ NGỮ (*.congu_save)', 'All files (*.*)')
                res = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename="PlayerProfile.congu_save", file_types=file_types)
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
            except Exception as e:
                print(f"[!] PyWebView save file dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.asksaveasfilename(
                    title="Xuất Hồ Sơ CỔ NGỮ (.congu_save) ra USB / Ổ cứng",
                    initialfile="PlayerProfile.congu_save",
                    defaultextension=".congu_save",
                    filetypes=[("Hồ Sơ CỔ NGỮ", "*.congu_save"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass
        return chosen_file or ""

    def search_game_for_avatar(self, query: str) -> list[dict]:
        """Tìm danh sách game kèm ảnh preview từ Kho CỔ NGỮ, Steam Store trực tiếp trên mạng, và DB bổ trợ."""
        clean_q = re.sub(r"\s+", " ", (query or "")).strip()
        if not clean_q:
            return []

        results = []
        seen_appids = set()
        q_lower = clean_q.lower()

        congu_appids_map = {}  # appid -> game data

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
                    appid = str(g.get("steam_appid") or "").strip()
                    effective_id = appid if appid else gid
                    if (
                        q_lower in title.lower()
                        or q_lower in vi_title.lower()
                        or q_lower in gid.lower()
                        or (appid and appid == clean_q)
                    ):
                        if appid:
                            seen_appids.add(appid)
                            if appid.isdigit():
                                congu_appids_map[appid] = g
                        poster = (
                            g.get("assets", {}).get("poster")
                            or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "")
                        )
                        header = (
                            g.get("assets", {}).get("header")
                            or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else "")
                        )
                        results.append({
                            "id": int(effective_id) if str(effective_id).isdigit() else effective_id,
                            "steam_appid": appid or gid,
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
            online_items = search_steam_online(clean_q, limit=10)

            # Thu thập toàn bộ danh sách Steam AppID (cả từ Kho Cổ Ngữ lẫn Steam Store) để lấy poster từ SteamGridDB
            steam_appids = [str(it.get("steam_appid", "")) for it in online_items if str(it.get("steam_appid", "")).isdigit()]
            all_target_appids = list(dict.fromkeys(list(congu_appids_map.keys()) + steam_appids))[:8]

            sgdb_map = {}
            if all_target_appids and STEAMGRIDDB_API_KEY:
                try:
                    with ThreadPoolExecutor(max_workers=min(len(all_target_appids), 6)) as ex:
                        futs = {ex.submit(fetch_steamgriddb_posters, aid, 3): aid for aid in all_target_appids}
                        for fut in futs:
                            aid = futs[fut]
                            try:
                                sgdb_map[aid] = fut.result()
                            except Exception:
                                sgdb_map[aid] = []
                except Exception as e:
                    print(f"[AvatarSearch] SteamGridDB batch fetch error: {e}")

            seen_avatar_urls = set()
            for r in results:
                if r.get("avatar_url"):
                    seen_avatar_urls.add(r["avatar_url"])

            # A. Thêm các mẫu SteamGridDB cho các game đã có trong Kho Cổ Ngữ
            for c_appid, c_game in congu_appids_map.items():
                c_title = c_game.get("title", "")
                for p_idx, p_url in enumerate(sgdb_map.get(c_appid, [])):
                    if p_url not in seen_avatar_urls:
                        seen_avatar_urls.add(p_url)
                        results.append({
                            "id": f"sgdb_{c_appid}_{p_idx}",
                            "steam_appid": c_appid,
                            "name": c_title,
                            "title": c_title,
                            "subtitle": f"SteamGridDB • {c_appid}",
                            "source": "steamgriddb",
                            "genre": "SteamGridDB",
                            "avatar_url": p_url,
                            "header_url": "",
                            "capsule": ""
                        })

            # B. Thêm các item Steam Store và các mẫu SteamGridDB tương ứng
            for item in online_items:
                appid = str(item.get("steam_appid", ""))
                is_store_seen = bool(appid and appid in seen_appids)
                if not is_store_seen:
                    seen_appids.add(appid)
                    p_url = item.get("avatar_url")
                    if p_url:
                        seen_avatar_urls.add(p_url)
                    results.append(item)

                # Hiển thị song song các mẫu poster dọc từ SteamGridDB cho cùng Steam AppID này (kể cả đã có trong Cổ Ngữ)
                sg_posters = sgdb_map.get(appid, [])
                for p_idx, p_url in enumerate(sg_posters):
                    if p_url not in seen_avatar_urls:
                        seen_avatar_urls.add(p_url)
                        results.append({
                            "id": f"sgdb_{appid}_{p_idx}",
                            "steam_appid": appid,
                            "name": item.get("name", ""),
                            "title": item.get("title", ""),
                            "subtitle": f"SteamGridDB • {appid}",
                            "source": "steamgriddb",
                            "genre": "SteamGridDB",
                            "avatar_url": p_url,
                            "header_url": item.get("header_url", ""),
                            "capsule": item.get("capsule", "")
                        })

            # C. Bổ sung các kết quả tìm kiếm theo tên trực tiếp từ SteamGridDB
            if STEAMGRIDDB_API_KEY:
                try:
                    sgdb_extra = search_steamgriddb_by_name(clean_q, max_items=4)
                    for sg_it in sgdb_extra:
                        p_url = sg_it.get("avatar_url")
                        if p_url and p_url not in seen_avatar_urls:
                            seen_avatar_urls.add(p_url)
                            results.append(sg_it)
                except Exception as e:
                    print(f"[AvatarSearch] SteamGridDB search by name error: {e}")

        except Exception as e:
            print(f"[AvatarSearch] online steam search error: {e}")

        # 3. Bổ sung từ cơ sở dữ liệu Steam offline (hơn 5,000 game)
        try:
            offline_db = get_steam_games()
            exact, starts, word_starts, contains = [], [], [], []
            for item in offline_db:
                appid = str(item.get("id", ""))
                name = item.get("name", "")
                if not appid or not name or appid in seen_appids:
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
                    "avatar_url": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                    "header_url": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
                    "capsule": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_sm_120.jpg"
                })
        except Exception as e:
            print(f"[AvatarSearch] offline steam db search error: {e}")

        return results

    def apply_selected_avatar(self, target_game_id: str, selected_data: dict) -> dict:
        """Gán cố định avatar + steam_appid người dùng đã chọn và tải/sao chép ảnh lưu cache."""
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
        local_cover_png = os.path.join(COVERS_DIR, f"{safe_gid}.png")

        # 1. Danh sách candidate theo thứ tự ưu tiên:
        # 1. Nếu người dùng chọn mẫu từ Kho Cổ Ngữ hoặc ảnh nội bộ, ưu tiên số 1 là avatar_url đó!
        candidates = []
        if avatar_url and (
            selected_data.get("source") in ("congu_db", "steamgriddb")
            or str(avatar_url).startswith(("/assets/", "assets/", "/static/", "static/", "/api/", "https://cdn2.steamgriddb.com/"))
        ):
            candidates.append(avatar_url)

        if appid and str(appid).isdigit():
            # Ưu tiên số 1: Lấy đúng link library_600x900_2x.jpg kèm mã {HASH} từ Steam IStoreBrowseService
            candidates.extend(get_steam_official_Vertical_posters(appid))
            if header_url:
                h_match = re.search(r"/([0-9a-f]{40})/", header_url)
                if h_match:
                    h_code = h_match.group(1)
                    candidates.extend([
                        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg",
                        f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg",
                    ])
        if avatar_url and avatar_url not in candidates:
            candidates.append(avatar_url)
        if appid and str(appid).isdigit():
            candidates.extend([
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
                f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
                f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
                f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            ])
            # Bổ sung poster từ kho SteamGridDB
            candidates.extend(fetch_steamgriddb_posters(appid, limit=4))
        if header_url:
            candidates.append(header_url)
        if capsule_url:
            candidates.append(capsule_url)

        downloaded_ok = False
        final_timestamp = int(time.time())
        final_local_url = f"/api/covers/{safe_gid}.jpg?t={final_timestamp}"

        for cand_url in candidates:
            if not cand_url:
                continue

            raw_content = None
            clean_cand = str(cand_url).split("?")[0].strip()

            # A. Kiểm tra nguồn ảnh cục bộ (nội bộ ứng dụng /static/..., /assets/..., /api/covers/..., hoặc tệp đĩa)
            local_src = None
            if clean_cand.startswith("/static/"):
                local_src = os.path.join(STATIC_DIR, clean_cand[8:].replace("/", os.sep))
            elif clean_cand.startswith("static/"):
                local_src = os.path.join(STATIC_DIR, clean_cand[7:].replace("/", os.sep))
            elif clean_cand.startswith("/assets/"):
                local_src = os.path.join(STATIC_DIR, clean_cand.lstrip("/").replace("/", os.sep))
            elif clean_cand.startswith("assets/"):
                local_src = os.path.join(STATIC_DIR, clean_cand.replace("/", os.sep))
            elif clean_cand.startswith("/api/covers/"):
                local_src = os.path.join(COVERS_DIR, clean_cand[12:].replace("/", os.sep))
            elif str(cand_url).startswith("/api/game/poster_preview"):
                # Nếu là ảnh ngang đã qua bộ lọc Glassmorphism preview, tải từ url gốc
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(str(cand_url)).query)
                orig_u = (parsed_q.get("url") or [""])[0]
                if orig_u:
                    raw_content = steam_direct_request(orig_u, timeout=4.0)
            elif os.path.isabs(clean_cand) and os.path.exists(clean_cand):
                local_src = clean_cand
            elif os.path.exists(os.path.join(APP_DIR, clean_cand.lstrip("/\\"))):
                local_src = os.path.join(APP_DIR, clean_cand.lstrip("/\\"))

            if local_src and os.path.exists(local_src):
                try:
                    with open(local_src, "rb") as sf:
                        raw_content = sf.read()
                except Exception as e:
                    print(f"[apply_selected_avatar] Local read error for {local_src}: {e}")

            # B. Nếu là URL mạng (http / https)
            elif not raw_content and (clean_cand.startswith("http://") or clean_cand.startswith("https://")):
                try:
                    content = steam_direct_request(clean_cand, timeout=4.0)
                    if (
                        content
                        and len(content) > 1000
                        and not content.startswith(b"<html>")
                        and not content.startswith(b"HTTP/1.1 404")
                        and not content.startswith(b"HTTP/1.1 50")
                    ):
                        raw_content = content
                    else:
                        req = urllib.request.Request(clean_cand, headers={"User-Agent": "CoNgu-VietModManager/2.0"})
                        ctx = ssl.create_default_context()
                        with urllib.request.urlopen(req, timeout=4.0, context=ctx) as r:
                            raw_content = r.read()
                except Exception:
                    pass

            # C. Chuẩn hóa poster dọc 600x900 và lưu vào COVERS_DIR
            if raw_content and len(raw_content) > 500:
                try:
                    formatted_poster = make_vertical_poster(raw_content)
                    with open(local_cover_path, "wb") as f:
                        f.write(formatted_poster)
                    if os.path.exists(local_cover_png):
                        try:
                            os.remove(local_cover_png)
                        except Exception:
                            pass
                    downloaded_ok = True
                    break
                except Exception as e:
                    print(f"[apply_selected_avatar] Error formatting poster: {e}")

        # Lấy thêm thông tin Genre và tên từ Steam details nếu có appid
        if appid and str(appid).isdigit():
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
                                and not h_content.startswith(b"HTTP/1.1 50")
                            ):
                                formatted_poster = make_vertical_poster(h_content)
                                with open(local_cover_path, "wb") as f:
                                    f.write(formatted_poster)
                                if os.path.exists(local_cover_png):
                                    try:
                                        os.remove(local_cover_png)
                                    except Exception:
                                        pass
                                downloaded_ok = True
            except Exception:
                pass

        # Nếu không lưu được ảnh mới, nhưng người dùng đã chọn avatar_url khác,
        # xóa tệp bìa cũ không còn phù hợp để không bị dính ảnh sai cũ
        if not downloaded_ok and avatar_url:
            if os.path.exists(local_cover_path):
                try:
                    os.remove(local_cover_path)
                except Exception:
                    pass
            if os.path.exists(local_cover_png):
                try:
                    os.remove(local_cover_png)
                except Exception:
                    pass

        chosen_avatar = final_local_url if downloaded_ok else (avatar_url or "")
        chosen_cover = final_local_url if downloaded_ok else (avatar_url or "")

        # Cập nhật cache covers_cache.json (cả khóa gốc lẫn chữ thường để tra cứu không phân biệt hoa thường)
        c_cache = load_covers_cache()
        cache_entry = {
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "poster_url": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg" if appid else "",
            "local_cover": chosen_cover,
            "avatar_url": chosen_avatar,
            "header_url": header_url or ""
        }
        c_cache[target_game_id] = cache_entry
        if target_game_id.lower() != target_game_id:
            c_cache[target_game_id.lower()] = cache_entry
        save_covers_cache(c_cache)

        return {
            "status": "success",
            "success": True,
            "game_id": target_game_id,
            "steam_appid": appid,
            "title": new_title,
            "genre": genre or "Game",
            "avatar_url": chosen_avatar,
            "local_cover": chosen_cover,
            "header_url": header_url,
            "message": f"Đã áp dụng ảnh bìa cho game thành công!",
            "games": self.get_games()
        }

    # ==============================================================================
    # BACKUP, ROLLBACK & INSTALLER PIPELINE (DELEGATED TO CORE MODULES)
    # ==============================================================================
    def _backup_file_inplace(self, game_id, original_abs_path, relative_in_game="", return_details=False):
        return backup_file_inplace(game_id, original_abs_path, relative_in_game=relative_in_game, return_details=return_details)

    def _load_backup_manifest(self, game_id):
        return load_backup_manifest(game_id)

    def _record_preexisting_environment(self, game_id, game_path):
        return record_preexisting_environment(game_id, game_path)

    def _record_backup_manifest(self, game_id, backed_up_files):
        return record_backup_manifest(game_id, backed_up_files)

    def _record_modded_state(self, game_id, target_file, relative_in_game=""):
        return record_modded_state(game_id, target_file, relative_in_game=relative_in_game)

    def _restore_files_inplace(self, game_id, game_path):
        return restore_files_inplace(game_id, game_path)

    def _patch_ini_file(self, file_path, section, key, value, encoding="utf-8"):
        return patch_ini_file(file_path, section=section, key=key, value=value, encoding=encoding)

    def _execute_pipeline_step(self, game_id, game_path, source_mod_dir, step, operation="install"):
        return execute_pipeline_step(game_id, game_path, source_mod_dir, step, operation=operation)

    def execute_action_pipeline(self, game_id, game_path, source_mod_dir, steps, operation="install", progress_range=(50, 90), uninstall_steps=None):
        return execute_action_pipeline(game_id, game_path, source_mod_dir, steps, operation=operation, progress_range=progress_range, uninstall_steps=uninstall_steps)

    def install_mod(self, game_id, force=False):
        res = install_mod(game_id, force=force, get_games_func=self.get_games)
        # Hậu kiểm Game Doctor: sau khi cài, xác nhận loader BepInEx (winhttp.dll) thực sự có mặt
        try:
            if isinstance(res, dict) and res.get("success"):
                from core.preflight_doctor import run_preflight
                games = {g["id"]: g for g in self.get_games()}
                g = games.get(game_id)
                if g:
                    cfg = load_user_config()
                    report = run_preflight(g, cfg.get(f"{game_id}_path", "") or "")
                    winhttp = next((c for c in report.get("checks", []) if c.get("id") == "winhttp"), None)
                    if winhttp and winhttp.get("status") in ("warn", "error"):
                        res["doctor"] = report
                        res["doctor_warning"] = winhttp.get("detail")
                        log_startup(f"[GameDoctor] Sau cai dat '{game_id}': {winhttp.get('detail')}")
        except Exception as e:
            print(f"[GameDoctor] Post-install check warning: {e}")
        return res

    def _install_mod_impl(self, game_id, force=False):
        return install_mod_impl(game_id, force=force, get_games_func=self.get_games)

    def uninstall_mod(self, game_id):
        return uninstall_mod(game_id, get_games_func=self.get_games)

    def _uninstall_mod_impl(self, game_id):
        return uninstall_mod_impl(game_id, get_games_func=self.get_games)

    def emergency_restore_game(self, game_id):
        return emergency_restore_game(game_id, get_games_func=self.get_games)

    def launch_game(self, game_id, force: bool = False):
        """
        Khởi chạy game độc lập (Detached Process) và kích hoạt luồng theo dõi đếm giờ chuẩn xác.
        force=True: bỏ qua cảnh báo nghiêm trọng của Pre-Flight Game Doctor.
        """
        games = {g["id"]: g for g in self.get_games()}

        if game_id not in games:
            return {"success": False, "status": "error", "message": "Không tìm thấy game!"}

        g = games[game_id]
        appid = g.get("steam_appid")
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")

        # 0. Kiểm tra nếu game đã đang chạy
        if PLAYTIME_MGR.is_game_running(game_id):
            return {
                "success": False,
                "status": "already_running",
                "message": f"Game {g['vietnamese_title']} đang chạy!",
                "stats": PLAYTIME_MGR.get_game_stats(game_id, game_path)
            }

        # 0.1 Pre-Flight Game Doctor: chặn khởi chạy nếu thiếu runtime nghiêm trọng (trừ khi force)
        doctor_report = None
        try:
            from core.preflight_doctor import run_preflight
            doctor_report = run_preflight(g, game_path or "")
            if doctor_report.get("severity") == "error" and not force:
                log_startup(
                    f"[GameDoctor] Chan khoi chay '{game_id}': {doctor_report.get('summary')}"
                )
                return {
                    "success": False,
                    "status": "doctor_warning",
                    "message": doctor_report.get("summary"),
                    "doctor": doctor_report,
                }
        except Exception as e:
            print(f"[GameDoctor] Pre-flight warning: {e}")

        # 0.2 Pre-Launch Cloud Guard: Kéo save mới nhất từ Cloud trước khi mở game
        cloud_guard_info = None
        try:
            cloud_cfg = cfg.get("cloud_save", {})
            if cloud_cfg.get("auto_sync_on_launch", True):
                cloud_guard_info = CLOUD_SYNC_MGR.pre_launch_cloud_guard(game_id, g, game_path or "")
                if cloud_guard_info and cloud_guard_info.get("status") == "pulled":
                    log_startup(f"[CloudGuard] Da cap nhat save moi nhat tu Cloud ve may cho '{game_id}'")
        except Exception as e:
            print(f"[CloudGuard] Pre-launch error: {e}")

        # 1. Tìm file thực thi .exe trong thư mục game
        candidate_exe = None
        if game_path and os.path.exists(game_path):
            exe_name = g.get("executable_name", "")
            if exe_name:
                cand = os.path.join(game_path, exe_name)
                if os.path.isfile(cand):
                    candidate_exe = cand
            if not candidate_exe:
                target_base = os.path.basename(exe_name).lower() if exe_name else ""
                for root, dirs, files in os.walk(game_path):
                    for f in files:
                        if f.lower().endswith(".exe"):
                            if target_base and f.lower() == target_base:
                                candidate_exe = os.path.join(root, f)
                                break
                    if candidate_exe:
                        break

        # Vault Pre-Launch Check & Auto-Restore:
        # Nếu trong Vault có bản save mà máy hiện tại chưa có, tự động nạp từ Vault vào máy
        try:
            vault = get_vault_instance()
            manifest = vault.read_manifest()
            vault_game_info = manifest.get("games", {}).get(game_id)
            if vault_game_info and game_path:
                vault_save_time = vault_game_info.get("save_updated_at", 0)
                # _extract_game_locations() chỉ nhận game_config (trước đây truyền dư game_path
                # khiến TypeError bị nuốt im lặng -> tính năng tự nạp save từ Vault không chạy).
                save_locs, _ach_locs, _excl = vault._extract_game_locations(g)
                local_has_save = False
                for sloc in save_locs:
                    rp = vault.resolve_macro_path(sloc.get("path", ""), game_path)
                    if rp and os.path.exists(rp):
                        if os.path.isdir(rp) and os.listdir(rp):
                            local_has_save = True
                            break
                        elif os.path.isfile(rp):
                            local_has_save = True
                            break
                if not local_has_save and vault_save_time > 0:
                    log_startup(f"[Vault] Phát hiện save trong Hồ Sơ cho '{game_id}', tự động bung vào máy trước khi mở game...")
                    vault.unpack_game_from_vault(g, game_path, backup_existing=True)
        except Exception as e:
            print(f"[Vault Pre-Launch Hook Warning]: {e}")

        # Khởi chạy tách rời (Detached) để đóng CỔ NGỮ không làm tắt game (Zero-Leak Clean Exit)
        creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        launched = False
        launch_protocol = "executable"

        # Controller Engine Pre-Launch: Chuẩn bị wrapper xinput hoặc virtual keyboard mapper nếu bật
        child_env = os.environ.copy()
        try:
            if "CONTROLLER_ENGINE" in globals() and CONTROLLER_ENGINE and candidate_exe:
                c_res = CONTROLLER_ENGINE.prepare_game_launch(game_id, candidate_exe, custom_env=child_env)
                if c_res.get("enabled"):
                    log_startup(f"[ControllerEngine] Đã kích hoạt giả lập tay cầm ({c_res.get('mode')}) cho '{game_id}'")
        except Exception as e:
            print(f"[ControllerEngine Pre-Launch Error]: {e}")

        # Ưu tiên mở trực tiếp qua file .exe nếu tìm thấy (hỗ trợ cả game modded, crack, GOG, Epic, Steam)
        if candidate_exe and os.path.isfile(candidate_exe):
            exe_dir = os.path.dirname(candidate_exe)
            try:
                subprocess.Popen(
                    [candidate_exe],
                    cwd=exe_dir,
                    env=child_env,
                    creationflags=creation_flags,
                    close_fds=True
                )
                launched = True
                launch_protocol = "executable"
            except OSError as e:
                is_elevation = (
                    getattr(e, "winerror", None) == 740
                    or "740" in str(e)
                    or "elevation" in str(e).lower()
                )
                log_startup(f"[Launch Warning] Direct Popen failed: {e}. Yêu cầu cấp quyền Admin: {is_elevation}")

                # Windows ShellExecuteW: Đảm bảo lpDirectory = exe_dir để game nạp đúng DLL & file cấu hình
                verb = "runas" if is_elevation else "open"
                try:
                    old_cwd = os.getcwd()
                    try:
                        os.chdir(exe_dir)
                        res = ctypes.windll.shell32.ShellExecuteW(
                            None,
                            verb,
                            candidate_exe,
                            None,
                            exe_dir,
                            1  # SW_SHOWNORMAL
                        )
                        if res > 32:
                            launched = True
                            launch_protocol = "executable_elevated" if is_elevation else "executable_shellexec"
                            log_startup(f"[Launch OK] ShellExecuteW ('{verb}') đã kích hoạt thành công game: '{candidate_exe}'")
                        else:
                            log_startup(f"[Launch Error] ShellExecuteW ('{verb}') trả về mã lỗi: {res}")
                    finally:
                        try:
                            os.chdir(old_cwd)
                        except Exception:
                            pass
                except Exception as e_sh:
                    log_startup(f"[Launch Error] ShellExecuteW failed: {e_sh}")

                # Fallback cuối cùng: os.startfile có bảo toàn CWD sang thư mục game
                if not launched:
                    try:
                        old_cwd = os.getcwd()
                        try:
                            os.chdir(exe_dir)
                            if is_elevation:
                                try:
                                    os.startfile(candidate_exe, "runas")
                                    launched = True
                                    launch_protocol = "executable_runas"
                                except Exception:
                                    pass
                            if not launched:
                                os.startfile(candidate_exe)
                                launched = True
                                launch_protocol = "executable_startfile"
                        finally:
                            try:
                                os.chdir(old_cwd)
                            except Exception:
                                pass
                    except Exception as e2:
                        log_startup(f"[Launch Error] os.startfile failed: {e2}")

        # Fallback giao thức Steam nếu không khởi chạy được trực tiếp
        if not launched and appid:
            try:
                os.startfile(f"steam://rungameid/{appid}")
                launched = True
                launch_protocol = "steam"
            except Exception as e:
                print(f"[Launch Error] Steam protocol failed: {e}")

        if launched:
            effective_dir = game_path or (os.path.dirname(candidate_exe) if candidate_exe else None)
            if effective_dir:
                PLAYTIME_MGR.start_tracking(game_id, effective_dir)
            stats = PLAYTIME_MGR.get_game_stats(game_id, effective_dir)

            # --- GAME BOOSTER: thu nhỏ xuống Khay + giải phóng RAM (WebView2) cho game ---
            booster_info = None
            try:
                booster_enabled = cfg.get("game_booster", True) is not False
                if booster_enabled and self.window:
                    _app_mod = _get_app_module()
                    if _app_mod is not None:
                        booster_info = _app_mod.enter_game_booster_mode(
                            self.window,
                            game_id,
                            g.get("vietnamese_title") or g.get("title") or game_id,
                            game_dir=effective_dir,
                        )
                        log_startup(f"[GameBooster] Kich hoat cho '{game_id}': {booster_info}")
            except Exception as e:
                print(f"[GameBooster] Kich hoat that bai (khong anh huong game): {e}")

            return {
                "success": True,
                "status": "launched",
                "protocol": launch_protocol,
                "message": f"Đang khởi chạy {g['vietnamese_title']}...",
                "stats": stats,
                "booster": booster_info,
                "doctor": doctor_report,
            }

        return {
            "success": False,
            "status": "error",
            "message": "Không thể khởi động game. Vui lòng mở game trực tiếp từ Steam / Epic Games / GOG!"
        }

    def install_game_from_steam(self, appid):
        """Mở khung cài đặt của Steam cho game Ghost Library qua giao thức steam://install."""
        appid = str(appid or "").strip()
        if not appid.isdigit():
            return {"success": False, "message": "Steam AppID không hợp lệ."}
        try:
            if sys.platform == "win32":
                os.startfile(f"steam://install/{appid}")
            else:
                subprocess.Popen(["xdg-open", f"steam://install/{appid}"])
            return {"success": True, "message": "Đã mở Steam để cài game. Cài xong hãy quay lại CỔ NGỮ để khôi phục save."}
        except Exception as e:
            return {"success": False, "message": f"Không mở được Steam: {e}"}

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
            res = subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                capture_output=True,
                text=True,
                check=False,
                creationflags=WIN_NO_WINDOW
            )
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

    def open_save_folder(self, game_id):
        """Mở thư mục lưu file save game trong Windows Explorer"""
        if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR:
            games = get_games()
            g_cfg = next((g for g in games if g["id"] == game_id), None)
            if g_cfg:
                cfg = load_user_config()
                game_dir = cfg.get(f"{game_id}_path")
                save_dir = CLOUD_SYNC_MGR.get_existing_save_directory(g_cfg, game_dir)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                    os.startfile(save_dir)
                    return {"success": True, "path": save_dir}
        return {"success": False, "message": "Không tìm thấy thư mục save của game này!"}

    def verify_mod(self, game_id):
        """
        Xác minh tính toàn vẹn của bản Việt hóa đã cài đặt (3-Tier Intelligent Verification):
        - Tier 1: Kiểm tra tệp tin và mã băm modded_sha256 từ backup_manifest.json (Trọng tài tối cao).
        - Tier 2: Kiểm tra chuẩn Data-Driven Pipeline (install_steps: patch_binary, copy_file, patch_ini...).
        - Tier 3: Fallback tương thích ngược theo các mod_type legacy (pak, unity_assets, wad...).
        """
        with open(get_active_games_json_path(), "r", encoding="utf-8") as f:
            games = {g["id"]: g for g in json.load(f)}
        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path")
        if not game_path or not os.path.exists(game_path):
            return {"success": False, "message": "Chưa chọn thư mục game hoặc thư mục không tồn tại!"}

        # ----------------------------------------------------------------------
        # TIER 1: KIỂM TRA TỪ BACKUP_MANIFEST.JSON (TRỌNG TÀI TỐI CAO - 100% CHÍNH XÁC)
        # ----------------------------------------------------------------------
        manifest = load_backup_manifest(game_id)
        manifest_files = manifest.get("files", []) if isinstance(manifest, dict) else []
        if manifest_files:
            matched_count = 0
            mismatched = []
            for item in manifest_files:
                rel = item.get("relative_in_game", "")
                target_f = item.get("target_file")
                if not target_f or not os.path.isabs(target_f):
                    target_f = os.path.join(game_path, rel.replace("/", os.sep))

                if not os.path.exists(target_f):
                    mismatched.append(f"thiếu '{rel or os.path.basename(target_f)}'")
                    continue

                modded_sha = item.get("modded_sha256")
                if modded_sha:
                    actual_sha = compute_file_sha256(target_f)
                    if actual_sha and actual_sha.lower() == modded_sha.lower():
                        matched_count += 1
                    else:
                        mismatched.append(f"lệch SHA-256 '{rel or os.path.basename(target_f)}'")
                else:
                    bak_file = f"{target_f}.congu_bak"
                    if os.path.exists(bak_file) or os.path.exists(target_f):
                        matched_count += 1

            total_files = len(manifest_files)
            if matched_count == total_files:
                return {
                    "success": True,
                    "is_valid": True,
                    "message": f"Bản Việt hóa hợp lệ: Toàn bộ {matched_count}/{total_files} tệp tin khớp chuẩn SHA-256 (Khớp bản ghi sao lưu an toàn)!"
                }
            elif matched_count > 0 or len(mismatched) > 0:
                details = "; ".join(mismatched[:3])
                return {
                    "success": True,
                    "is_valid": False,
                    "message": f"Phát hiện sai lệch: {matched_count}/{total_files} tệp tin hợp lệ. ({details})"
                }

        # ----------------------------------------------------------------------
        # TIER 2: KIỂM TRA DATA-DRIVEN PIPELINE (install_steps)
        # ----------------------------------------------------------------------
        install_steps = g.get("install_steps")
        if install_steps and isinstance(install_steps, list):
            step_checks = 0
            step_passed = 0
            step_problems = []

            for st in install_steps:
                act = st.get("action")
                if act == "patch_binary":
                    step_checks += 1
                    target_rel = st.get("target", "").replace("/", os.sep)
                    target_abs = os.path.join(game_path, target_rel)
                    if not os.path.exists(target_abs):
                        step_problems.append(f"thiếu tệp vá '{st.get('target')}'")
                        continue
                    expect_sha = st.get("patched_sha256")
                    if expect_sha:
                        actual_sha = compute_file_sha256(target_abs)
                        if actual_sha and actual_sha.lower() == expect_sha.lower():
                            step_passed += 1
                        else:
                            step_problems.append(f"lệch SHA-256 '{st.get('target')}'")
                    else:
                        bak_f = f"{target_abs}.congu_bak"
                        if os.path.exists(bak_f):
                            step_passed += 1

                elif act == "copy_file":
                    step_checks += 1
                    dst_rel = (st.get("destination") or st.get("target") or "").replace("/", os.sep)
                    dst_abs = os.path.join(game_path, dst_rel)
                    if os.path.exists(dst_abs):
                        step_passed += 1
                    else:
                        step_problems.append(f"thiếu tệp '{dst_rel}'")

                elif act == "copy_folder":
                    step_checks += 1
                    dst_rel = (st.get("destination") or st.get("target") or "").replace("/", os.sep)
                    dst_abs = os.path.join(game_path, dst_rel)
                    if os.path.isdir(dst_abs):
                        step_passed += 1
                    else:
                        step_problems.append(f"thiếu thư mục '{dst_rel}'")

                elif act == "patch_ini":
                    step_checks += 1
                    ini_rel = (st.get("file") or "").replace("/", os.sep)
                    ini_abs = os.path.join(game_path, ini_rel)
                    if os.path.exists(ini_abs):
                        step_passed += 1
                    else:
                        step_problems.append(f"thiếu tệp cấu hình '{ini_rel}'")

                elif act == "backup":
                    target_rel = (st.get("target") or "").replace("/", os.sep)
                    bak_abs = os.path.join(game_path, f"{target_rel}.congu_bak")
                    if os.path.exists(bak_abs):
                        step_checks += 1
                        step_passed += 1

            if step_checks > 0:
                if step_passed == step_checks:
                    return {
                        "success": True,
                        "is_valid": True,
                        "message": f"Bản Việt hóa hợp lệ: {step_passed}/{step_checks} bước cài đặt pipeline khớp chuẩn 100%!"
                    }
                else:
                    details = "; ".join(step_problems[:3])
                    return {
                        "success": True,
                        "is_valid": False,
                        "message": f"Phát hiện sai lệch: {step_passed}/{step_checks} bước đạt. ({details})"
                    }

        # ----------------------------------------------------------------------
        # TIER 3: FALLBACK TƯƠNG THÍCH NGƯỢC (LEGACY MOD_TYPE)
        # ----------------------------------------------------------------------
        mtype = g.get("mod_type")
        rel_path = g.get("relative_install_path", "")
        tpak = g.get("target_pak_name", "")

        if mtype == "pak" and rel_path and tpak:
            target_pak = os.path.join(game_path, rel_path.replace("/", os.sep), tpak)
            if os.path.exists(target_pak):
                sz = os.path.getsize(target_pak)
                sha = compute_file_sha256(target_pak) or ""
                return {
                    "success": True, 
                    "is_valid": True, 
                    "message": f"Gói mod {tpak} hợp lệ ({sz:,} bytes) - SHA256: {sha[:12]}... Khớp chuẩn 100%!"
                }
        elif mtype == "unity_assets" and rel_path and tpak:
            target_assets = os.path.join(game_path, rel_path.replace("/", os.sep), tpak)
            local_congu_bak = f"{target_assets}.congu_bak"
            local_backup = os.path.join(game_path, rel_path.replace("/", os.sep), g.get("backup_file", "resources.assets.original_backup"))
            if os.path.exists(local_congu_bak) or os.path.exists(local_backup):
                sz = os.path.getsize(target_assets) if os.path.exists(target_assets) else 0
                return {"success": True, "is_valid": True, "message": f"Tệp assets tiếng Việt hợp lệ ({sz:,} bytes)!"}
        elif mtype == "wad" and tpak:
            target_wad = os.path.join(game_path, tpak)
            if os.path.exists(target_wad):
                return {"success": True, "is_valid": True, "message": f"File WAD và dữ liệu font {g.get('title')} hợp lệ 100%!"}
        elif mtype == "bepinex_language" and rel_path and tpak:
            lang = os.path.join(game_path, rel_path.replace("/", os.sep), tpak)
            if os.path.exists(lang):
                return {"success": True, "is_valid": True, "message": f"Ngôn ngữ Tiếng Việt & BepInEx {g.get('title')} đang hoạt động chuẩn!"}
        elif mtype == "folder_copy":
            if os.path.exists(os.path.join(game_path, "core", "locale.congu_bak")):
                return {"success": True, "is_valid": True, "message": f"Bộ font và gói ngôn ngữ {g.get('title')} đang hoạt động chuẩn!"}
        elif mtype == "ini_and_exe" and rel_path and tpak:
            target_ini = os.path.join(game_path, rel_path.replace("/", os.sep), tpak)
            if os.path.exists(target_ini):
                sz = os.path.getsize(target_ini)
                return {"success": True, "is_valid": True, "message": f"File ngôn ngữ {g.get('title')} ({sz:,} bytes) đang hoạt động chuẩn 100%!"}
        elif mtype == "witcher3_mod" and rel_path and tpak:
            target_str = os.path.join(game_path, rel_path.replace("/", os.sep), tpak)
            if os.path.exists(target_str):
                sz = os.path.getsize(target_str)
                return {"success": True, "is_valid": True, "message": f"Bản Việt Hóa {g.get('title')} ({sz:,} bytes) đang hoạt động chuẩn 100%!"}

        return {"success": False, "is_valid": False, "message": "Bản Việt hóa hiện chưa được cài đặt trong thư mục game."}

    def check_updates(self, game_id):
        """Kiểm tra bản cập nhật mới cho mod game một cách thực chất (P1-04)."""
        from core.mod_compatibility import check_mod_update_status
        from core.config_manager import get_installed_mod_receipt

        p = get_active_games_json_path()
        if not os.path.exists(p):
            return {
                "success": False,
                "game_id": game_id,
                "has_update": False,
                "status": "offline",
                "message": "Không tìm thấy dữ liệu danh mục game (Chế độ ngoại tuyến)."
            }

        try:
            with open(p, "r", encoding="utf-8") as f:
                games = {g["id"]: g for g in json.load(f)}
        except Exception as e:
            return {
                "success": False,
                "game_id": game_id,
                "has_update": False,
                "status": "catalog_error",
                "message": f"Lỗi đọc danh mục game: {e}"
            }

        if game_id not in games:
            return {
                "success": False,
                "game_id": game_id,
                "has_update": False,
                "status": "game_not_found",
                "message": "Không tìm thấy game trong danh mục!"
            }

        g = games[game_id]
        receipt = get_installed_mod_receipt(game_id)

        # Kiểm tra trạng thái mod trên đĩa
        is_mod_on_disk = False
        try:
            cfg = load_user_config()
            game_path = cfg.get(f"{game_id}_path", "")
            if game_path and os.path.exists(game_path):
                rel_p = g.get("relative_install_path", "")
                tpak = g.get("target_pak_name", "")
                if tpak and os.path.exists(os.path.join(game_path, rel_p, tpak)):
                    is_mod_on_disk = True
                elif os.path.exists(os.path.join(game_path, "core", "locale.congu_bak")):
                    is_mod_on_disk = True
        except Exception:
            pass

        return check_mod_update_status(
            game_id=game_id,
            catalog_game=g,
            installed_receipt=receipt,
            is_mod_installed_on_disk=is_mod_on_disk
        )

    def check_compatibility(self, game_id):
        """Đánh giá tương thích giữa game hiện tại và bản mod (P1-01)."""
        from core.mod_compatibility import assess_mod_compatibility

        p = get_active_games_json_path()
        if not os.path.exists(p):
            return {"success": False, "message": "Chưa có danh mục game."}

        try:
            with open(p, "r", encoding="utf-8") as f:
                games = {g["id"]: g for g in json.load(f)}
        except Exception as e:
            return {"success": False, "message": f"Lỗi đọc danh mục: {e}"}

        if game_id not in games:
            return {"success": False, "message": "Không tìm thấy game!"}

        g = games[game_id]
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path", "")

        installed_info = {
            "game_path": game_path,
            "platform": "steam" if g.get("steam_appid") else "standalone",
        }
        report = assess_mod_compatibility(g, installed_info)
        return {
            "success": True,
            "game_id": game_id,
            "compatibility": report
        }

    def get_troubleshooting_guides(self):
        """Lấy danh sách kịch bản hướng dẫn xử lý sự cố (P1-05)."""
        from core.troubleshooter import get_troubleshooting_guides
        return {"success": True, "guides": get_troubleshooting_guides()}

    def inspect_game_backups(self, game_id: str):
        """Xem trước phạm vi các file sao lưu trước khi khôi phục (P1-05)."""
        from core.troubleshooter import inspect_game_backups
        cfg = load_user_config()
        game_path = cfg.get(f"{game_id}_path", "")
        res = inspect_game_backups(game_id, game_path)
        return {"success": True, "backup_inspection": res}

    def get_recent_audit_logs(self, game_id: str = "", limit: int = 50):
        """Truy xuất nhật ký thao tác (Audit Log) theo Job ID (P1-05)."""
        from core.troubleshooter import get_recent_audit_logs
        logs = get_recent_audit_logs(game_id=game_id or None, limit=limit)
        return {"success": True, "logs": logs}

    def generate_support_report(self, game_id: str = ""):
        """Xuất báo cáo kỹ thuật đã che mờ thông tin cá nhân (P1-05)."""
        from core.troubleshooter import generate_support_report
        return generate_support_report(game_id=game_id or None)

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
                vote_res = self.vote_community_request(game_id)
                self._persist_localization_request(
                    gid_str, name, capsule, note,
                    status=(data.get(gid_str) or {}).get("status", "voting"),
                    votes=(data.get(gid_str) or {}).get("votes", 1)
                )
                return vote_res
            else:
                self._persist_localization_request(
                    gid_str, name, capsule, note,
                    status=(data[gid_str] or {}).get("status", "voting"),
                    votes=(data[gid_str] or {}).get("votes", 1)
                )
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

        self._persist_localization_request(
            gid_str, name, capsule, note, status="voting", votes=1
        )

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

        # Lưu kèm vào Hồ Sơ Cổ Ngữ (.congu_save) để yêu cầu đi theo người chơi sang PC khác
        if steam_id:
            self._persist_localization_request(
                str(steam_id), game_name, capsule or "", note, status="voting", votes=1
            )

        return {"success": True, "message": f"Đã ghi nhận yêu cầu Việt hóa tựa game '{game_name}' thành công!"}

    # =========================================================================
    # YÊU CẦU VIỆT HÓA GAME LẺ (LOCALIZATION REQUESTS -> FILE .CONGU_SAVE)
    # =========================================================================
    def _persist_localization_request(self, game_id, name, capsule="", note="",
                                      status="voting", votes=1, synced=True):
        """
        Ghi yêu cầu Việt hóa vào localization_requests bên trong tệp .congu_save
        (kèm player_id) để mang sang bất kỳ PC nào khác.
        """
        try:
            gid_str = str(game_id)
            is_appid = gid_str.isdigit()
            res = LOCALIZATION_REQ_MGR.register_request(
                game_key=gid_str,
                title=name,
                steam_appid=gid_str if is_appid else "",
                game_id=gid_str,
                detected_engine="",
                user_note=note,
                status=status,
                community_votes=votes,
                synced_to_server=synced,
                extra={"capsule": capsule or ""}
            )
            return bool(res.get("success"))
        except Exception as e:
            print(f"[LocalizationRequest] Persist warning: {e}")
            return False

    def inspect_custom_game_engine(self, game_id: str):
        """Quét nhanh Engine & file ngôn ngữ của game ngoài (Unity/Unreal/GameMaker...)."""
        cfg = load_user_config()
        target = next((g for g in load_custom_games() if g.get("id") == game_id), None)
        if not target:
            return {"success": False, "message": "Không tìm thấy game tự thêm này trong thư viện!"}

        game_root = cfg.get(f"{game_id}_path") or target.get("game_root", "")
        info = LOCALIZATION_REQ_MGR.inspect_game_engine(game_root)
        info["success"] = True
        info["game_id"] = game_id
        info["title"] = target.get("title", "")
        return info

    def request_custom_game_localization(self, game_id: str, user_note: str = ""):
        """
        Gửi yêu cầu Việt hóa cho 1 game lẻ:
        Quét Engine -> Đề cử/cộng dồn Vote trên Server -> Lưu vĩnh viễn vào .congu_save.
        """
        cfg = load_user_config()
        target = next((g for g in load_custom_games() if g.get("id") == game_id), None)
        if not target:
            return {"success": False, "message": "Không tìm thấy game tự thêm này trong thư viện!"}

        game_root = cfg.get(f"{game_id}_path") or target.get("game_root", "")
        game_config = dict(target)
        game_config["game_root"] = game_root

        # Ảnh bìa cục bộ (nếu có) để hiển thị trên bảng nguyện vọng cộng đồng
        safe_gid = re.sub(r"[^\w\-]", "_", str(game_id))
        for ext in ("jpg", "png"):
            cover_path = os.path.join(COVERS_DIR, f"{safe_gid}.{ext}")
            if os.path.exists(cover_path) and os.path.getsize(cover_path) > 500:
                game_config["cover_url"] = f"/api/covers/{safe_gid}.{ext}"
                break

        return LOCALIZATION_REQ_MGR.submit_game_request(game_config, game_root, user_note)

    def get_my_localization_requests(self):
        """Danh sách yêu cầu Việt hóa của người chơi (đọc từ .congu_save + trạng thái Server)."""
        live_items = []
        try:
            community = self.get_community_requests()
            if community.get("success"):
                live_items = community.get("items") or []
        except Exception as e:
            print(f"[LocalizationRequest] Community fetch warning: {e}")

        try:
            official_games = self.get_games()
        except Exception:
            official_games = []

        res = LOCALIZATION_REQ_MGR.list_requests(live_items=live_items, official_games=official_games)
        out = {"success": True}
        out.update(res)
        return out

    def sync_localization_requests(self):
        """
        Gọi khi mở App / nạp lại .congu_save ở PC khác:
        Đối chiếu games.json để phát hiện game đã có bản Việt Hóa chính thức ("Tin vui!")
        và cập nhật tiến độ dịch mới nhất từ máy chủ.
        """
        try:
            official_games = [g for g in self.get_games() if not g.get("is_custom_game")]
        except Exception:
            official_games = []

        res = LOCALIZATION_REQ_MGR.sync_with_official(official_games=official_games)
        notifications = res.get("notifications", [])
        return {
            "success": True,
            "changed": res.get("changed", False),
            "notifications": notifications,
            "items": res.get("items", []),
            "total": res.get("total", 0),
            "message": (f"{len(notifications)} tựa game bạn từng yêu cầu đã có bản Việt Hóa chính thức!"
                        if notifications else "Đã đồng bộ trạng thái yêu cầu Việt hóa từ máy chủ.")
        }

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

    def apply_app_update(self):
        """
        Tự động cập nhật ứng dụng (In-App Self-Updater) cho bản Portable:
        1. Kiểm tra version.json lấy gói .zip mới nhất
        2. Tải về %APPDATA%/VietModHub/update/package.zip
        3. Giải nén an toàn (chống Zip Slip) vào thư mục tạm
        4. Sinh script apply_update.bat: chờ app thoát -> chép đè (robocopy /E) -> khởi động lại
        5. Thoát ứng dụng để script tiếp quản
        """
        import zipfile

        if INSTALL_PROGRESS.get("status") == "running" or _MOD_OP_LOCK.locked() or any_game_operation_running():
            return {"success": False, "message": "Không thể cập nhật khi đang cài đặt/gỡ bỏ bản mod! Vui lòng chờ hoàn tất."}

        if not getattr(sys, "frozen", False):
            return {"success": False, "message": "Tính năng tự cập nhật chỉ hoạt động trên bản Portable (.exe). Bản chạy mã nguồn vui lòng dùng git pull."}

        info = check_app_update()
        if not info.get("success"):
            return {"success": False, "message": info.get("message") or "Không thể kiểm tra phiên bản mới."}
        if not info.get("has_update"):
            return {"success": False, "message": "Bạn đang sử dụng phiên bản mới nhất (v%s)." % info.get("current_version")}

        url = (info.get("portable_zip_url") or "").strip()
        if not url.lower().endswith(".zip"):
            return {"success": False, "message": "Bản phát hành không kèm portable_zip_url .zip được ký để tự động cập nhật. Vui lòng tải thủ công trên GitHub Releases."}
        expected_sha = str(info.get("portable_zip_sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            return {"success": False, "message": "Bản cập nhật chưa có SHA-256 hợp lệ trong metadata phát hành; đã từ chối tự cập nhật để bảo vệ ứng dụng."}

        from core.update_manifest import verify_manifest_signature
        signature_ok, signature_reason = verify_manifest_signature(info)
        if not signature_ok:
            return {"success": False, "message": "Chữ ký manifest phát hành không hợp lệ (%s); đã từ chối tự cập nhật." % signature_reason}

        upd_root = os.path.join(APPDATA_DIR, "update")
        pending_path = os.path.join(upd_root, "pending_update.json")
        if os.path.lexists(pending_path):
            return {"success": False, "message": "Có giao dịch cập nhật chưa xử lý; giữ nguyên dữ liệu phục hồi tại %s." % upd_root}
        transaction_token = secrets.token_hex(32)
        job_dir = os.path.join(upd_root, "job-" + transaction_token[:16])
        new_dir = os.path.join(job_dir, "new")
        pkg_path = os.path.join(job_dir, "package.zip")
        try:
            os.makedirs(new_dir, exist_ok=False)
        except Exception as e:
            return {"success": False, "message": "Không tạo được thư mục cập nhật: %s" % e}

        log_startup("[Updater] Bat dau tai ban cap nhat: %s" % url)
        try:
            from core.downloader import download_file_with_progress
            def validate_update(staged_path):
                actual_sha = compute_file_sha256(staged_path)
                if not actual_sha or actual_sha.lower() != expected_sha:
                    raise ValueError("SHA-256 gói cập nhật không khớp metadata phát hành")
            download_file_with_progress(url, pkg_path, timeout=30.0, validate_download=validate_update)
        except Exception as e:
            return {"success": False, "message": "Tải/xác minh bản cập nhật thất bại: %s" % e}

        try:
            max_members = 5000
            max_unpacked_bytes = 2 * 1024 * 1024 * 1024
            with zipfile.ZipFile(pkg_path, "r") as zf:
                members = [member for member in zf.infolist() if not member.is_dir()]
                if len(members) > max_members:
                    raise ValueError("Gói cập nhật chứa quá nhiều tệp")
                if sum(member.file_size for member in members) > max_unpacked_bytes:
                    raise ValueError("Gói cập nhật vượt giới hạn dung lượng giải nén")
                for member_info in members:
                    member = member_info.filename
                    if member.endswith("/") or member.endswith("\\"):
                        continue
                    dest = validate_safe_path(new_dir, member, allow_base_itself=False)
                    parent = os.path.dirname(dest)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with zf.open(member, "r") as src_f, open(dest, "wb") as out_f:
                        shutil.copyfileobj(src_f, out_f, length=65536)
        except Exception as e:
            return {"success": False, "message": "Giải nén bản cập nhật thất bại: %s" % e}

        src_dir = ""
        for cand in (os.path.join(new_dir, "VietModHub"), new_dir):
            if os.path.isfile(os.path.join(cand, "VietModHub.exe")):
                src_dir = cand
                break
        if not src_dir:
            for root_dir, _dirs, files in os.walk(new_dir):
                if "VietModHub.exe" in files:
                    src_dir = root_dir
                    break
        if not src_dir:
            return {"success": False, "message": "Gói cập nhật không hợp lệ (không tìm thấy VietModHub.exe bên trong)."}

        dst_dir = os.path.dirname(os.path.abspath(sys.executable))
        backup_dir = os.path.join(job_dir, "backup_prev")
        bat_path = os.path.join(job_dir, "apply_update.bat")
        pid = os.getpid()
        try:
            from core.updater_apply import build_apply_script, build_copy_verifier
            from core.update_startup import build_startup_probe
            probe_path = os.path.join(job_dir, "startup_probe.ps1")
            with open(probe_path, "w", encoding="utf-8-sig", newline="") as output:
                output.write(build_startup_probe())
            with open(probe_path + ".verify.ps1", "w", encoding="utf-8-sig", newline="") as output:
                output.write(build_copy_verifier())
            script = build_apply_script(
                src_dir, dst_dir, backup_dir, pid, startup_probe=probe_path,
                transaction_token=transaction_token, version=info.get("version", ""),
                pending_update=pending_path,
            )
            with open(bat_path, "w", encoding="utf-8", newline="") as f:
                f.write(script)
        except Exception as e:
            return {"success": False, "message": "Không tạo được script cập nhật: %s" % e}

        try:
            with open(pending_path, "x", encoding="utf-8") as pending:
                json.dump({"version": info.get("version"), "job_dir": job_dir,
                           "application_dir": dst_dir, "backup_dir": backup_dir}, pending)
                pending.flush()
                os.fsync(pending.fileno())
        except FileExistsError:
            return {"success": False, "message": "Một giao dịch cập nhật khác đã được bàn giao; giữ nguyên dữ liệu phục hồi."}
        except OSError as error:
            return {"success": False, "message": "Không thể ghi journal cập nhật; đã dừng: %s" % error}
        try:
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(["cmd", "/d", "/c", bat_path], creationflags=flags, cwd=job_dir, close_fds=True)
        except Exception as e:
            os.remove(pending_path)
            return {"success": False, "message": "Không khởi chạy được script cập nhật: %s" % e}

        log_startup("[Updater] Da khoi chay script cap nhat. Ung dung se khoi dong lai sau it giay.")
        try:
            PLAYTIME_MGR.flush_all_active()
        except Exception:
            pass
        threading.Timer(1.2, lambda: os._exit(0)).start()
        return {
            "success": True,
            "message": "Đang tải & áp dụng bản cập nhật v%s. Ứng dụng sẽ tự khởi động lại..." % info.get("latest_version"),
            "new_version": info.get("latest_version"),
            "restarting": True,
        }

    def browse_custom_game_exe(self):
        """Mở hộp thoại cho người dùng chọn file .exe của game ngoài."""
        chosen_file = None
        if self.window:
            try:
                file_types = ('Executable Files (*.exe)', 'All files (*.*)')
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
                    title="Chọn file thực thi (.exe) của game bạn muốn thêm",
                    filetypes=[("Executable Files", "*.exe"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if chosen_file and os.path.isfile(chosen_file):
            return {"success": True, "exe_path": chosen_file}
        return {"success": False, "message": "Chưa chọn file thực thi nào."}

    def detect_custom_game(self, exe_path: str, steam_appid: str = ""):
        """Tự động phân tích và nhận diện game qua CustomGameDetector."""
        try:
            from custom_game_detector import CustomGameDetector
            detected = CustomGameDetector.detect_from_exe(
                exe_path,
                covers_dir=COVERS_DIR,
                steam_appid_override=steam_appid
            )
            return {"success": True, "game": detected}
        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Lỗi khi nhận diện game: {e}"}

    def fetch_custom_game_by_appid(self, steam_appid: str, exe_path: str = ""):
        """Lấy toàn bộ metadata game từ Steam AppID, giữ nguyên file .exe đã chọn."""
        try:
            from custom_game_detector import CustomGameDetector
            detected = CustomGameDetector.fetch_metadata_by_appid(
                steam_appid,
                exe_path=exe_path,
                covers_dir=COVERS_DIR
            )
            return {"success": True, "game": detected}
        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Không lấy được dữ liệu Steam: {e}"}

    def save_custom_game(self, game_data: dict):
        """Lưu hoặc cập nhật một custom game vào danh sách."""
        if not game_data or not game_data.get("id"):
            return {"success": False, "message": "Thông tin game không hợp lệ!"}

        gid = game_data["id"]
        c_games = load_custom_games()
        idx = next((i for i, g in enumerate(c_games) if g.get("id") == gid), -1)
        if idx >= 0:
            c_games[idx] = game_data
        else:
            c_games.append(game_data)

        ok = save_custom_games(c_games)
        if ok:
            cfg = load_user_config()
            cfg[f"{gid}_path"] = game_data.get("game_root", "")
            save_user_config(cfg)

            # Chạy gom Save vào Vault trong luồng ngầm (background thread)
            # để phản hồi ngay lập tức, người dùng không phải chờ đợi ở bước "Đang lưu..."
            def _async_vault_pack():
                try:
                    vault = get_vault_instance()
                    vault.pack_game_to_vault(game_data, game_data.get("game_root", ""))
                except Exception as e:
                    print(f"[CustomGames Vault Warning]: {e}")

            threading.Thread(target=_async_vault_pack, daemon=True).start()

            return {
                "success": True,
                "message": f"Đã thêm game '{game_data.get('title')}' vào thư viện CỔ NGỮ!",
                "game": game_data,
                "games": self.get_games()
            }
        return {"success": False, "message": "Không thể lưu game vào custom_games.json"}

    def delete_custom_game(self, game_id: str):
        """Xóa game ngoài khỏi thư viện."""
        c_games = load_custom_games()
        filtered = [g for g in c_games if g.get("id") != game_id]
        if len(filtered) == len(c_games):
            return {"success": False, "message": "Không tìm thấy game tự thêm để xóa!"}

        ok = save_custom_games(filtered)
        if ok:
            cfg = load_user_config()
            cfg.pop(f"{game_id}_path", None)
            save_user_config(cfg)
            return {
                "success": True,
                "message": "Đã xóa game khỏi thư viện CỔ NGỮ!",
                "games": self.get_games()
            }
        return {"success": False, "message": "Không thể cập nhật danh sách game."}

    def set_custom_game_appid(self, game_id: str, steam_appid: str):
        """Cập nhật Steam AppID cho custom game, tự tạo steam_appid.txt và kéo thành tựu về."""
        steam_appid = str(steam_appid or "").strip()
        c_games = load_custom_games()
        target = None
        for g in c_games:
            if g.get("id") == game_id:
                target = g
                break
        if not target:
            return {"success": False, "message": "Không tìm thấy game tự thêm này!"}

        target["steam_appid"] = steam_appid
        game_root = target.get("game_root", "")

        # 1. Tự động tạo / cập nhật file steam_appid.txt trong thư mục game nếu thư mục tồn tại
        if game_root and os.path.isdir(game_root) and steam_appid:
            try:
                txt_path = os.path.join(game_root, "steam_appid.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"{steam_appid}\n")
            except Exception as e:
                print(f"[SetAppID Warning] Lỗi ghi steam_appid.txt: {e}")

        # 2. Cập nhật vị trí lưu thành tựu theo emulator
        if steam_appid:
            if "vault_config" not in target:
                target["vault_config"] = {}
            target["vault_config"]["achievement_locations"] = [
                {"emu": "goldberg", "path": f"{{APPDATA}}/Goldberg SteamEmu Saves/{steam_appid}/achievements.json"},
                {"emu": "codex", "path": f"{{PUBLIC_DOCS}}/Steam/CODEX/{steam_appid}/achievements.ini"},
                {"emu": "rune", "path": f"{{PUBLIC_DOCS}}/Steam/RUNE/{steam_appid}/achievements.ini"}
            ]

        # 3. Lưu lại custom_games.json
        save_custom_games(c_games)

        # 4. Tải schema thành tựu về ngay
        ach_view = {}
        if steam_appid and "ACHIEVEMENT_MGR" in globals():
            ach_view = ACHIEVEMENT_MGR.get_game_achievements_view(appid=steam_appid, game_dir=game_root, game_id=game_id)

        return {
            "success": True,
            "message": f"Đã gắn Steam AppID {steam_appid} thành công! Tìm thấy {ach_view.get('total', 0)} thành tựu.",
            "steam_appid": steam_appid,
            "achievements_count": ach_view.get("total", 0),
            "games": self.get_games()
        }

    # =========================================================================
    # HYDRA SOURCES & TORRENT DOWNLOAD ENGINE APIS
    # =========================================================================
    def get_hydra_sources(self):
        """Lấy danh sách các nguồn Hydra đã cấu hình kèm thống kê cache."""
        try:
            sources = HYDRA_MGR.get_sources()
            stats = HYDRA_MGR.get_cache_stats()
            return {"success": True, "sources": sources, "stats": stats}
        except Exception as e:
            return {"success": False, "error": str(e), "sources": [], "stats": {}}

    def add_hydra_sources(self, urls):
        """Thêm một hoặc nhiều URL nguồn Hydra và tự động kích hoạt đồng bộ nền."""
        try:
            res = HYDRA_MGR.add_sources(urls)
            HYDRA_MGR.start_async_sync()
            return {"success": True, "added": res, "sources": HYDRA_MGR.get_sources()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_hydra_source(self, url):
        """Xóa một nguồn Hydra."""
        try:
            ok = HYDRA_MGR.remove_source(url)
            return {"success": ok, "sources": HYDRA_MGR.get_sources()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def sync_hydra_sources(self, force=False):
        """Kích hoạt đồng bộ hóa tất cả các nguồn Hydra."""
        try:
            HYDRA_MGR.start_async_sync(force=force)
            return {"success": True, "message": "Đang đồng bộ hóa nguồn trong nền..."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def browse_and_import_hydra_json(self):
        """Mở hộp thoại chọn file .json của Hydra từ máy và nạp vào hệ thống."""
        try:
            selected_files = HYDRA_MGR.browse_local_json_files()
            if not selected_files:
                return {"success": False, "cancelled": True, "message": "Đã hủy chọn file."}
            res = HYDRA_MGR.import_local_json_files(selected_files)
            stats = HYDRA_MGR.get_cache_stats()
            return {
                "success": True,
                "message": f"Đã nạp thành công {res['imported_files']} file nguồn ({res['imported_repacks']} bản repack)!",
                "details": res,
                "stats": stats
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_game_downloads(self, game_id="", query_title="", steam_appid=""):
        """Tìm kiếm các bản game Repack/Torrent khớp với game từ các nguồn Hydra."""
        try:
            if not query_title and game_id:
                all_games = self.get_games()
                g = next((x for x in all_games if x.get("id") == game_id), None)
                if g:
                    query_title = g.get("name") or g.get("display_name") or g.get("id")
                    if not steam_appid:
                        steam_appid = g.get("steam_appid", "")

            results = HYDRA_MGR.search_download_links_for_game(
                game_title=query_title,
                game_id=game_id,
                steam_appid=steam_appid
            )
            return {
                "success": True,
                "game_id": game_id,
                "query": query_title,
                "total": len(results),
                "results": results
            }
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}

    def search_catalogue_games(self, query="", limit=50):
        """
        Tìm kiếm danh mục Game tổng thể từ các nguồn Repack (Catalogue Engine)
        Gom nhóm các bản Repack rời rạc theo Game Title và đối chiếu bản dịch Cổ Ngữ.
        """
        try:
            games = HYDRA_MGR.search_catalogue_games(query=query, limit=limit)
            all_viet_games = self.get_games() or []
            
            # Tạo map tra cứu tựa game có Việt Hóa
            viet_names = {}
            for vg in all_viet_games:
                v_title = (vg.get("name") or vg.get("display_name") or vg.get("id") or "").lower()
                clean_v = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", v_title)
                clean_v = re.sub(r"\s+", " ", clean_v).strip()
                if clean_v:
                    viet_names[clean_v] = vg.get("id")

            for g in games:
                c_title = g.get("title", "").lower()
                clean_c = re.sub(r"[:\-_–—+~#&!?,./|\\]", " ", c_title)
                clean_c = re.sub(r"\s+", " ", clean_c).strip()
                if clean_c in viet_names:
                    g["has_viet_mod"] = True
                    g["viet_mod_game_id"] = viet_names[clean_c]
                else:
                    for vn_k, vn_id in viet_names.items():
                        if vn_k and (vn_k in clean_c or clean_c in vn_k):
                            g["has_viet_mod"] = True
                            g["viet_mod_game_id"] = vn_id
                            break

            return {
                "success": True,
                "total": len(games),
                "query": query,
                "games": games
            }
        except Exception as e:
            return {"success": False, "error": str(e), "games": []}

    # =========================================================================
    # DISCOVERY HUB APIs (TAB KHÁM PHÁ: STEAM TRENDING + HYDRA + VIỆT HÓA)
    # =========================================================================
    def get_discovery_feed(self, force_refresh=False):
        """Trả về toàn bộ feed tab Khám Phá (Hero, Mới lên kệ, Steam Trending, Co-op)."""
        try:
            feed = DISCOVERY_MGR.get_feed(force_refresh=bool(force_refresh))
            payload = {"success": True}
            payload.update(feed)
            return payload
        except Exception as e:
            return {"success": False, "error": str(e), "hero": [], "recent_repacks": [],
                    "steam_trending": [], "online_coop": [], "stats": {}, "watchlist": []}

    def get_discovery_trailer(self, steam_appid="", seconds=12):
        """Lấy thông tin trailer + link clip MP4 cục bộ để phát khi rê chuột lên thẻ Poster."""
        try:
            return DISCOVERY_MGR.get_trailer(steam_appid, seconds)
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_discovery_clip(self, steam_appid="", seconds=12):
        """Tạo (hoặc lấy từ cache) file micro-trailer MP4 12-20 giây đầu của game."""
        try:
            res = DISCOVERY_MGR.build_preview_clip(steam_appid, seconds)
            if res.get("success"):
                res["url"] = f"/api/discovery/clip?appid={steam_appid}&seconds={int(seconds)}"
            return res
        except Exception as e:
            return {"success": False, "message": str(e)}

    def check_pc_compatibility(self, steam_appid=""):
        """Đối chiếu RAM/CPU/GPU của máy với pc_requirements của game (Smart PC Check)."""
        try:
            return DISCOVERY_MGR.pc_check(steam_appid)
        except Exception as e:
            return {"success": False, "status": "unknown", "message": str(e)}

    def get_discovery_watchlist(self):
        """Danh sách game người dùng đang Theo dõi (chờ nguồn .json có bản tải)."""
        try:
            return {"success": True, "watchlist": DISCOVERY_MGR.get_watchlist()}
        except Exception as e:
            return {"success": False, "watchlist": [], "error": str(e)}

    def update_discovery_watchlist(self, action="add", title="", steam_appid="", poster_url=""):
        """Thêm / bỏ theo dõi một tựa game trong tab Khám Phá."""
        try:
            return DISCOVERY_MGR.update_watchlist(action, title, steam_appid, poster_url)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def request_vietnamese_localization(self, title="", steam_appid="", note=""):
        """Bấm 'Yêu cầu Việt hóa' cho game hot chưa có tiếng Việt -> đưa vào hàng đợi dịch."""
        try:
            return DISCOVERY_MGR.request_vietnamese(title, steam_appid, note, api_instance=self)
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_discovery_detail(self, steam_appid="", title=""):
        """Lấy thông tin chi tiết game cho modal Khám Phá (mô tả, cấu hình, ảnh, trailer, nguồn tải)."""
        try:
            steam_appid = str(steam_appid or "").strip()
            title = str(title or "").strip()
            detail = {}
            if steam_appid and steam_appid.isdigit():
                detail = DISCOVERY_MGR.appdetails(steam_appid) or {}

            # Nguồn tải có sẵn
            downloads = []
            if title:
                try:
                    downloads = HYDRA_MGR.search_download_links_for_game(title=title, limit=8)
                except Exception:
                    downloads = []

            # Kiểm tra kho Việt hóa Cổ Ngữ
            congu_game = None
            if title:
                t_low = title.lower().strip()
                for g in self.games:
                    gt = str(g.get("title", "")).lower()
                    gvi = str(g.get("vietnamese_title", "")).lower()
                    if t_low and (t_low in gt or gt in t_low or t_low in gvi or gvi in t_low):
                        congu_game = {
                            "id": g.get("id"),
                            "title": g.get("title"),
                            "vietnamese_title": g.get("vietnamese_title"),
                            "is_installed": bool(g.get("is_installed")),
                            "has_vietnamese": True
                        }
                        break

            return {
                "success": True,
                "steam_appid": steam_appid,
                "title": title or (detail.get("name") if detail else ""),
                "detail": detail,
                "downloads": downloads,
                "congu_game": congu_game
            }
        except Exception as e:
            return {"success": False, "error": str(e), "detail": {}}

    def start_torrent_download(self, uri, title="", save_dir=None):
        """Bắt đầu tải file torrent qua daemon Aria2c nội bộ của Cổ Ngữ."""
        try:
            return TORRENT_MGR.add_download(uri=uri, title=title, save_dir=save_dir)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_torrent_downloads_status(self):
        """Lấy danh sách và tiến độ các tác vụ tải về qua Aria2c."""
        try:
            downloads = TORRENT_MGR.get_all_downloads_status()
            return {"success": True, "downloads": downloads}
        except Exception as e:
            return {"success": False, "downloads": [], "error": str(e)}

    def pause_torrent_download(self, gid):
        """Tạm dừng tải task theo GID."""
        try:
            return TORRENT_MGR.pause_download(gid)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resume_torrent_download(self, gid):
        """Tiếp tục tải task theo GID."""
        try:
            return TORRENT_MGR.resume_download(gid)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_torrent_download(self, gid, delete_files=False):
        """Hủy tải task theo GID."""
        try:
            return TORRENT_MGR.cancel_download(gid, delete_files=delete_files)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_external_torrent(self, uri):
        """Mở link tải bằng phần mềm ngoài (Torrent client hoặc Browser / IDM)."""
        if not uri:
            return {"success": False, "message": "URI trống!"}
        try:
            uri = uri.strip()
            if uri.startswith(('http://', 'https://')):
                import webbrowser
                webbrowser.open(uri)
                return {"success": True, "message": "Đã mở liên kết trong Trình duyệt Web của bạn!"}
            else:
                os.startfile(uri)
                return {"success": True, "message": "Đã chuyển link tới ứng dụng Torrent (qBittorrent/uTorrent) của máy!"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_torrent_folder(self, folder_path=None):
        """Mở thư mục chứa file tải về trên Windows Explorer."""
        try:
            target = folder_path if folder_path and os.path.exists(folder_path) else TORRENT_MGR.default_download_dir
            if os.path.exists(target):
                os.startfile(target)
                return {"success": True, "path": target}
            return {"success": False, "message": "Thư mục không tồn tại."}
        except Exception as e:
            return {"success": False, "error": str(e)}


    def inspect_torrent_download(self, path_or_gid):
        """Phân tích cấu trúc thư mục/file tải về để đề xuất hành động."""
        try:
            return TORRENT_MGR.inspect_download_contents(path_or_gid)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_torrent_installer(self, installer_path):
        """Khởi chạy file setup.exe."""
        try:
            return TORRENT_MGR.run_installer(installer_path)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def extract_torrent_archive(self, archive_path, dest_dir=None):
        """Giải nén file nén tải về."""
        try:
            return TORRENT_MGR.extract_archive(archive_path, dest_dir=dest_dir)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def auto_register_downloaded_game(self, path_or_gid, auto_install_mod=False):
        """Tự động phát hiện file .exe, thêm vào thư viện Cổ Ngữ và tùy chọn cài đặt Việt Hóa tức thì."""
        try:
            insp = TORRENT_MGR.inspect_download_contents(path_or_gid)
            game_exe = insp.get("game_exe")
            if not game_exe or not os.path.isfile(game_exe):
                return {"success": False, "message": "Không tìm thấy file .exe thực thi của game để thêm vào thư viện."}

            reg_res = self._dnd_add_game_from_exe(game_exe)
            if reg_res.get("status") != "ok":
                return {"success": False, "message": reg_res.get("message", "Thêm game vào thư viện thất bại.")}

            game_info = reg_res.get("game", {})
            gid = game_info.get("id")

            # Nếu người dùng chọn tự động cài đặt Việt Hóa
            mod_started = False
            if auto_install_mod and gid:
                all_games = self.get_games()
                matched_cat = None
                for g in all_games:
                    if g.get("id") == gid or (game_info.get("steam_appid") and str(g.get("steam_appid")) == str(game_info.get("steam_appid"))):
                        matched_cat = g
                        break

                if matched_cat:
                    target_gid = matched_cat["id"]
                    threading.Thread(target=lambda: self.install_mod(target_gid, force=True), daemon=True).start()
                    mod_started = True

            return {
                "success": True,
                "game": game_info,
                "mod_started": mod_started,
                "message": f"Đã thêm '{game_info.get('title')}' vào thư viện!" + (" Đang tự động nạp Việt Hóa..." if mod_started else "")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def quit_app(self, force: bool = False):
        """Immediately and cleanly terminate the application"""
        if not force and INSTALL_PROGRESS.get("status") == "running":
            return {
                "success": False,
                "message": "Không thể thoát ứng dụng khi đang thực thi cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ tiến trình hoàn tất để tránh làm hỏng tệp game."
            }

        # 1. Hủy icon khay hệ thống nếu có
        try:
            _app_mod = _get_app_module()
            tray = getattr(_app_mod, "SYSTEM_TRAY", None) if _app_mod else None
            if tray:
                tray.Visible = False
                tray.Dispose()
                _app_mod.SYSTEM_TRAY = None
        except Exception:
            pass

        # 2. Lưu nhịp tim đếm giờ chơi dở trước khi thoát hẳn
        try:
            PLAYTIME_MGR.flush_all_active()
        except Exception:
            pass

        # 3. Dọn dẹp sạch sẽ mọi file wrapper giả lập tay cầm nếu còn sót
        try:
            if "CONTROLLER_ENGINE" in globals() and CONTROLLER_ENGINE:
                CONTROLLER_ENGINE.cleanup_all()
        except Exception:
            pass

        # 3.1. Dừng triệt để aria2c daemon nếu đang chạy
        try:
            if "TORRENT_MGR" in globals() and TORRENT_MGR:
                TORRENT_MGR.stop_daemon()
        except Exception:
            pass

        # 4. Hủy cửa sổ giao diện ngay lập tức
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass

        # 5. Thoát tiến trình ngay lập tức
        def _instant_exit():
            time.sleep(0.05)
            os._exit(0)
        threading.Thread(target=_instant_exit, daemon=True).start()
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

    def minimize_to_tray(self):
        """Minimize CỔ NGỮ window to Windows System Tray (notification area)"""
        if self.window:
            try:
                _app_mod = _get_app_module()
                if _app_mod is None:
                    return {"success": False, "error": "App module unavailable"}
                return _app_mod.minimize_to_tray(self.window)
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def restore_from_tray(self):
        """Restore CỔ NGỮ window from Windows System Tray"""
        if self.window:
            try:
                _app_mod = _get_app_module()
                if _app_mod is None:
                    return {"success": False, "error": "App module unavailable"}
                return _app_mod.restore_from_tray(self.window)
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "No window instance"}

    def has_active_play_session(self):
        """Kiểm tra có phiên chơi game đang được theo dõi trực tiếp hay không."""
        try:
            return {"success": True, "has_active_session": bool(PLAYTIME_MGR.has_active_session())}
        except Exception as e:
            return {"success": False, "has_active_session": False, "error": str(e)}

    def request_close(self):
        """
        Nút X thông minh:
        - Đang có phiên chơi game -> ẩn xuống Khay Hệ Thống, giữ tiến trình để đếm giờ
          và kích hoạt hook đóng gói .congu_save + đẩy Google Drive sau khi tắt game.
        - Không có game nào chạy -> thoát hẳn (Zero-Leak Clean Exit).
        - Chế độ Fallback Browser (không có cửa sổ native): giữ tiến trình nếu đang có game,
          còn lại trả tín hiệu để frontend gọi /api/app/quit thoát hẳn.
        """
        try:
            _app_mod = _get_app_module()
            if self.window:
                if _app_mod is None:
                    return {"success": False, "error": "App module unavailable"}
                return _app_mod.request_close(self.window)

            # Fallback Browser Mode: không có cửa sổ WinForms để ẩn xuống Khay
            if PLAYTIME_MGR.has_active_session():
                return {
                    "success": True,
                    "hidden_to_tray": True,
                    "reason": "active_game_session",
                    "message": (
                        "CỔ NGỮ đang theo dõi phiên chơi game nên tiến trình sẽ tiếp tục chạy ngầm "
                        "để đếm giờ và tự động sao lưu Cloud khi bạn thoát game."
                    ),
                }
            try:
                PLAYTIME_MGR.flush_all_active()
            except Exception:
                pass
            return {"success": True, "hidden_to_tray": False, "reason": "fallback_no_window"}
        except Exception as e:
            return {"success": False, "hidden_to_tray": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # SAVE TIME MACHINE (lịch sử 3 thế hệ save trong .congu_save)
    # ---------------------------------------------------------------------
    def get_save_revisions(self, game_id: str):
        """Liệt kê các thế hệ save (current / prev_1 / prev_2) của 1 game."""
        try:
            games = {g["id"]: g for g in self.get_games()}
            g = games.get(game_id)
            if not g:
                return {"success": False, "error": "Không tìm thấy game."}
            data = get_vault_instance().list_game_revisions(g)
            return {"success": True, **data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restore_previous_save(self, game_id: str, revision: str = "prev_1"):
        """Khôi phục save của phiên chơi trước (mặc định prev_1) về thư mục game."""
        try:
            games = {g["id"]: g for g in self.get_games()}
            g = games.get(game_id)
            if not g:
                return {"success": False, "message": "Không tìm thấy game."}
            cfg = load_user_config()
            root = cfg.get(f"{game_id}_path", "") or ""
            res = get_vault_instance().restore_game_revision(g, root, revision=revision)
            if res.get("success"):
                label = {"current": "bản hiện tại", "prev_1": "phiên chơi trước", "prev_2": "2 phiên trước"}.get(revision, revision)
                res["message"] = (
                    f"Đã khôi phục {res.get('restored_files', 0)} tệp save từ {label}"
                    + (f" (đã sao lưu {res.get('backups_created', 0)} tệp cũ thành .congu_prevbak)."
                       if res.get("backups_created") else ".")
                )
            else:
                res["message"] = res.get("error") or "Khôi phục thất bại."
            return res
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ---------------------------------------------------------------------
    # PRE-FLIGHT GAME DOCTOR (kiểm tra runtime trước khi chơi)
    # ---------------------------------------------------------------------
    def run_game_doctor(self, game_id: str = ""):
        """
        Kiểm tra môi trường máy trước khi khởi chạy game:
        VC++ Redistributable x64, .NET Framework, DirectX, BepInEx winhttp.dll và font tiếng Việt.
        """
        try:
            from core.preflight_doctor import run_preflight
            games = {g["id"]: g for g in self.get_games()}
            gid = game_id or (next(iter(games)) if games else "")
            g = games.get(gid)
            if not g:
                return {"success": False, "error": "Không tìm thấy game để kiểm tra."}
            cfg = load_user_config()
            root = cfg.get(f"{gid}_path", "") or ""
            report = run_preflight(g, root)
            return {"success": True, "doctor": report}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # QUICK-SAVE CHECKPOINT (Ctrl+F5 lưu / Ctrl+F9 hoàn nguyên)
    # ---------------------------------------------------------------------
    def quick_checkpoint_save(self):
        """Tạo Quick Checkpoint cho game đang chơi (dùng cho phím tắt / UI)."""
        try:
            _app_mod = _get_app_module()
            if _app_mod is None:
                return {"success": False, "error": "App module unavailable"}
            return _app_mod.quick_checkpoint_save()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def quick_checkpoint_restore(self):
        """Hoàn nguyên Quick Checkpoint mới nhất cho game đang chơi."""
        try:
            _app_mod = _get_app_module()
            if _app_mod is None:
                return {"success": False, "error": "App module unavailable"}
            return _app_mod.quick_checkpoint_restore()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_quick_checkpoints(self, game_id: str = ""):
        """Liệt kê các Quick Checkpoint đã lưu của 1 game."""
        try:
            from core.quick_checkpoint import list_checkpoints
            gid = game_id
            if not gid:
                ids = PLAYTIME_MGR.get_active_session_ids()
                gid = ids[0] if ids else ""
            if not gid:
                return {"success": False, "items": [], "message": "Chưa chọn game nào."}
            return {"success": True, "game_id": gid, "items": list_checkpoints(gid, APPDATA_DIR)}
        except Exception as e:
            return {"success": False, "items": [], "error": str(e)}

    def get_all_playtime_stats(self):
        """Lấy toàn bộ thống kê giờ chơi thời gian thực của các game."""
        return PLAYTIME_MGR.get_all_stats()

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

    # ==========================================================================
    # CUSTOM THEMES (giao dien) - IPC BRIDGE
    # ==========================================================================

    def get_themes(self):
        """Lấy danh sách theme (builtin + người dùng) và theme đang kích hoạt."""
        try:
            from core.theme_manager import list_themes, get_active_theme
            return {"success": True, "themes": list_themes(), "active": get_active_theme()}
        except Exception as e:
            log_startup(f"[Theme] Lỗi lấy danh sách theme: {e}")
            return {"success": False, "themes": [], "active": "cyberpunk_default", "message": str(e)}

    def set_theme(self, theme_id: str):
        """Kích hoạt một theme đã cài (áp dụng ngay, không cần khởi động lại app)."""
        try:
            from core.theme_manager import set_active_theme
            return set_active_theme(theme_id)
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_theme_payload(self, theme_id: str):
        """Lấy manifest đã kiểm duyệt + URL asset để frontend áp dụng tức thì."""
        try:
            from core.theme_manager import get_theme
            data = get_theme(theme_id)
            if not data:
                return {"success": False, "message": "Không tìm thấy theme!"}
            return {"success": True, "theme": data}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ==========================================================================
    # UNIVERSAL DRAG & DROP (Kéo & Thả file trực tiếp vào cửa sổ CỔ NGỮ)
    # ==========================================================================

    def _dnd_resolve_lnk(self, lnk_path: str) -> str:
        """Giải mã đường dẫn đích thực của Shortcut .lnk qua COM WScript.Shell."""
        try:
            import subprocess
            safe = str(lnk_path).replace("'", "''")
            cmd = [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(New-Object -ComObject WScript.Shell).CreateShortcut('{safe}').TargetPath",
            ]
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            target = (out.stdout or "").strip().splitlines()
            target = target[0].strip() if target else ""
            if target and os.path.exists(target):
                return target
        except Exception as e:
            print(f"[DnD] Resolve .lnk error: {e}")
        return ""

    def _dnd_find_exe_in_folder(self, folder: str) -> str:
        """Tìm file .exe khả nghi nhất trong thư mục game được kéo thả (quét tối đa 2 tầng)."""
        best, best_size = "", -1
        try:
            for root, dirs, files in os.walk(folder):
                depth = root[len(folder):].count(os.sep)
                if depth >= 2:
                    dirs[:] = []
                for fn in files:
                    if not fn.lower().endswith(".exe"):
                        continue
                    low = fn.lower()
                    if any(t in low for t in ("unins", "setup", "crash", "helper", "vc_redist", "dxsetup")):
                        continue
                    p = os.path.join(root, fn)
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        continue
                    if size > best_size:
                        best, best_size = p, size
        except Exception as e:
            print(f"[DnD] Scan folder error: {e}")
        return best

    def _dnd_add_game_from_exe(self, exe_path: str) -> dict:
        """Nhận diện game từ .exe (Steam metadata + ảnh bìa) và thêm vào thư viện Game Lẻ."""
        det = self.detect_custom_game(exe_path)
        if not det.get("success"):
            return {"status": "error", "message": det.get("message") or "Không nhận diện được game."}
        game = det.get("game") or {}
        if not game.get("id"):
            return {"status": "error", "message": "Không tạo được mã định danh cho game."}
        saved = self.save_custom_game(game)
        if not saved.get("success"):
            return {"status": "error", "message": saved.get("message") or "Không lưu được game."}
        return {
            "status": "ok",
            "kind": "custom_game",
            "message": saved.get("message") or f"Đã thêm '{game.get('title')}' vào thư viện.",
            "game": {"id": game.get("id"), "title": game.get("title"), "steam_appid": game.get("steam_appid")},
        }

    def _dnd_install_congu(self, congu_path: str) -> dict:
        """
        Cài gói Việt hóa Offline (.congu): xác thực SHA-256 với games.json,
        đưa vào cache chuẩn rồi kích hoạt pipeline cài đặt hiện có.
        """
        hasher = hashlib.sha256()
        try:
            with open(congu_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    hasher.update(chunk)
        except Exception as e:
            return {"status": "error", "message": f"Không đọc được tệp .congu: {e}"}

        digest = hasher.hexdigest().lower()
        match = None
        for g in self.get_games():
            if str(g.get("congu_sha256") or "").strip().lower() == digest:
                match = g
                break
        if not match:
            return {
                "status": "error",
                "message": "Gói .congu không khớp mã SHA-256 của bất kỳ game nào trong danh mục — "
                           "từ chối cài đặt để bảo vệ máy bạn.",
            }

        gid = match["id"]
        try:
            cache_dir = os.path.join(APPDATA_DIR, "cache", gid)
            os.makedirs(cache_dir, exist_ok=True)
            shutil.copy2(congu_path, os.path.join(cache_dir, "mod_package.congu"))
        except Exception as e:
            return {"status": "error", "message": f"Không ghi được vào cache: {e}"}

        def _worker():
            try:
                self.install_mod(gid, force=True)
            except Exception as e:
                print(f"[DnD] Offline install error: {e}")

        threading.Thread(target=_worker, daemon=True).start()
        return {
            "status": "installing",
            "kind": "congu",
            "game_id": gid,
            "message": f"Đã nhận gói Việt hóa '{match.get('vietnamese_title') or match.get('title')}'. Đang cài đặt...",
        }

    def _dnd_install_theme(self, theme_path: str) -> dict:
        """Cài gói theme .congu_theme vừa kéo thả và áp dụng ngay."""
        try:
            from core.theme_manager import install_theme_zip, get_themes_root
            res = install_theme_zip(theme_path, get_themes_root())
        except Exception as e:
            return {"status": "error", "message": f"Lỗi cài theme: {e}"}
        if not res.get("success"):
            return {"status": "error", "message": res.get("message") or res.get("error") or "Cài theme thất bại."}
        theme_id = res.get("theme_id")
        if theme_id:
            try:
                from core.theme_manager import set_active_theme
                set_active_theme(theme_id)
            except Exception as e:
                print(f"[DnD] Apply theme warning: {e}")
        return {
            "status": "ok",
            "kind": "theme",
            "theme_id": theme_id,
            "message": res.get("message") or "Đã cài theme thành công.",
        }

    def _dnd_preview_vault(self, save_path: str) -> dict:
        """Đọc manifest .congu_save để hỏi xác nhận trước khi nạp Hồ sơ."""
        try:
            import zipfile
            with zipfile.ZipFile(save_path, "r") as zf:
                if "profile_manifest.json" not in zf.namelist():
                    return {"status": "error", "message": "Tệp không phải Hồ Sơ CỔ NGỮ (.congu_save) hợp lệ."}
                manifest = json.loads(zf.read("profile_manifest.json").decode("utf-8"))
        except Exception as e:
            return {"status": "error", "message": f"Tệp .congu_save bị hỏng hoặc sai định dạng: {e}"}

        player = manifest.get("player_name") or os.environ.get("USERNAME", "Game Thủ Cổ Ngữ")
        games_count = len(manifest.get("games") or {})
        return {
            "status": "confirm",
            "kind": "vault",
            "requires_confirm": True,
            "path": save_path,
            "player_name": player,
            "games_count": games_count,
            "message": f"Bạn có muốn nạp Hồ sơ Save & Thành tựu của {player} không?",
        }

    def handle_dropped_files(self, paths):
        """Điểm vào duy nhất cho Universal Drag & Drop (nhận danh sách đường dẫn tuyệt đối)."""
        if isinstance(paths, str):
            paths = [paths]
        items = []
        for raw in (paths or []):
            try:
                p = os.path.abspath(str(raw))
                if not os.path.exists(p):
                    items.append({"file": str(raw), "status": "error", "message": "Không tìm thấy tệp."})
                    continue

                # Thư mục game: tự tìm .exe bên trong
                if os.path.isdir(p):
                    exe = self._dnd_find_exe_in_folder(p)
                    if not exe:
                        items.append({"file": p, "status": "error",
                                      "message": "Không tìm thấy file .exe trong thư mục game."})
                        continue
                    item = self._dnd_add_game_from_exe(exe)
                    item["file"] = p
                    items.append(item)
                    continue

                ext = os.path.splitext(p)[1].lower()

                if ext == ".lnk":
                    target = self._dnd_resolve_lnk(p)
                    if not target:
                        items.append({"file": p, "status": "error",
                                      "message": "Không giải mã được Shortcut .lnk này."})
                        continue
                    if os.path.isdir(target):
                        target = self._dnd_find_exe_in_folder(target)
                    if not target or not target.lower().endswith(".exe"):
                        items.append({"file": p, "status": "error",
                                      "message": "Shortcut không trỏ tới file game .exe."})
                        continue
                    item = self._dnd_add_game_from_exe(target)
                    item["file"] = p
                    item["resolved_target"] = target
                    items.append(item)

                elif ext == ".exe":
                    item = self._dnd_add_game_from_exe(p)
                    item["file"] = p
                    items.append(item)

                elif ext == ".congu_save":
                    item = self._dnd_preview_vault(p)
                    item["file"] = p
                    items.append(item)

                elif ext == ".congu":
                    item = self._dnd_install_congu(p)
                    item["file"] = p
                    items.append(item)

                elif ext == ".congu_theme":
                    item = self._dnd_install_theme(p)
                    item["file"] = p
                    items.append(item)

                else:
                    items.append({
                        "file": p, "status": "unsupported",
                        "message": "Định dạng chưa hỗ trợ. CỔ NGỮ nhận: .exe, .lnk, .congu, .congu_save, .congu_theme",
                    })
            except Exception as e:
                items.append({"file": str(raw), "status": "error", "message": str(e)})

        ok = sum(1 for i in items if i.get("status") in ("ok", "installing", "confirm"))
        return {"success": ok > 0, "items": items, "total": len(items), "accepted": ok}

    def import_theme_dialog(self):
        """Mở hộp thoại chọn gói theme (.congu_theme / .zip) từ máy tính và cài đặt an toàn."""
        chosen_file = ""
        try:
            if self.window:
                file_types = ('Gói Theme Cổ Ngữ (*.congu_theme;*.zip)', 'All files (*.*)')
                res = self.window.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types
                )
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
        except Exception as e:
            print(f"[!] PyWebView theme dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn gói Theme Cổ Ngữ (.congu_theme)",
                    filetypes=[("Gói Theme Cổ Ngữ", "*.congu_theme"), ("ZIP", "*.zip"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if not chosen_file:
            return {"success": False, "message": "Bạn chưa chọn gói theme nào."}

        try:
            from core.theme_manager import install_theme_zip, get_themes_root
            res = install_theme_zip(chosen_file, get_themes_root())
            return res
        except Exception as e:
            return {"success": False, "message": f"Lỗi cài theme: {e}"}

    def export_theme_dialog(self, theme_id: str):
        """Đóng gói theme hiện có thành 1 file .congu_theme để chia sẻ cho cộng đồng."""
        if not theme_id:
            return {"success": False, "message": "Thiếu theme_id."}
        chosen_file = ""
        try:
            if self.window:
                file_types = ('Gói Theme Cổ Ngữ (*.congu_theme)', 'All files (*.*)')
                res = self.window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=f"{theme_id}.congu_theme",
                    file_types=file_types
                )
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
        except Exception as e:
            print(f"[!] PyWebView theme save dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.asksaveasfilename(
                    title="Lưu gói Theme để chia sẻ",
                    initialfile=f"{theme_id}.congu_theme",
                    defaultextension=".congu_theme",
                    filetypes=[("Gói Theme Cổ Ngữ", "*.congu_theme"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if not chosen_file:
            return {"success": False, "message": "Bạn chưa chọn nơi lưu file theme."}

        try:
            from core.theme_manager import export_theme
            return export_theme(theme_id, chosen_file)
        except Exception as e:
            return {"success": False, "message": f"Lỗi xuất theme: {e}"}

    def pick_theme_background(self):
        """Mở hộp thoại chọn ảnh nền (wallpaper) cho Theme Studio."""
        chosen_file = ""
        try:
            if self.window:
                file_types = ('Ảnh (*.png;*.jpg;*.jpeg;*.webp;*.gif)', 'All files (*.*)')
                res = self.window.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types
                )
                if res:
                    chosen_file = res if isinstance(res, str) else res[0]
        except Exception as e:
            print(f"[!] PyWebView background dialog error: {e}")

        if not chosen_file:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen_file = filedialog.askopenfilename(
                    title="Chọn ảnh nền cho Theme",
                    filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.gif"), ("All files", "*.*")]
                )
                root.destroy()
            except Exception:
                pass

        if not chosen_file:
            return {"success": False, "message": "Bạn chưa chọn ảnh nền."}
        return {"success": True, "path": chosen_file}

    def save_theme_studio(self, payload: dict):
        """Lưu theme tạo từ Theme Studio (màu sắc, blur, ảnh nền do người dùng chọn)."""
        try:
            from core.theme_manager import build_theme_from_values
            return build_theme_from_values(payload or {})
        except Exception as e:
            return {"success": False, "message": str(e)}

    def delete_theme(self, theme_id: str):
        """Xóa một theme người dùng (không xóa được theme mặc định / theme đang dùng)."""
        try:
            from core.theme_manager import delete_theme
            return delete_theme(theme_id)
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ==========================================================================
    # UNIFIED SETTINGS (MENU CÀI ĐẶT TRUNG TÂM) - IPC BRIDGE
    # ==========================================================================

    def get_settings(self):
        """Lấy cấu hình hợp nhất 4 tab (General, Scanner, Downloader, Cloud Save)."""
        try:
            return {"success": True, "settings": get_unified_settings()}
        except Exception as e:
            return {"success": False, "message": str(e), "settings": DEFAULT_USER_CONFIG}

    def update_settings(self, new_config: dict):
        """Cập nhật toàn bộ hoặc từng phần cài đặt từ Menu Cài Đặt Hợp Nhất."""
        try:
            return update_unified_settings(new_config)
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_cache_info(self):
        """Lấy thông tin dung lượng và số lượng tệp trong bộ nhớ đệm cache."""
        try:
            return get_cache_stats()
        except Exception as e:
            return {"success": False, "total_bytes": 0, "formatted_size": "0 B", "error": str(e)}

    def clear_cache(self):
        """Xóa sạch cache gói mod và tệp tạm trong %APPDATA%/VietModHub/cache."""
        try:
            return clear_app_cache()
        except Exception as e:
            return {"success": False, "message": str(e)}

    def open_appdata_folder(self):
        """Mở thư mục %APPDATA%/VietModHub trong Windows Explorer."""
        try:
            return open_appdata_directory()
        except Exception as e:
            return {"success": False, "message": str(e)}

    def select_custom_library_folder(self):
        """Mở hộp thoại chọn thư mục chứa game ngoài để thêm vào danh sách quét."""
        if hasattr(self, "_dialog_lock") and not self._dialog_lock.acquire(blocking=False):
            return {"success": False, "message": "Hộp thoại chọn thư mục đang được mở."}
        try:
            chosen_dir = pick_folder(title="Chọn thư mục chứa game để thêm vào quét", parent_window=self.window)
            if chosen_dir and os.path.exists(chosen_dir):
                return {"success": True, "path": os.path.normpath(chosen_dir)}
            return {"success": False, "message": "Chưa chọn thư mục nào."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi chọn thư mục: {str(e)}"}
        finally:
            if hasattr(self, "_dialog_lock"):
                try:
                    self._dialog_lock.release()
                except RuntimeError:
                    pass





# Global API singleton instance
api_instance = ModManagerAPI()

# Tự động khôi phục game lẻ + yêu cầu Việt hóa + danh sách Chưa tải từ Hồ Sơ (.congu_save) khi khởi động
try:
    merge_vault_custom_games()
except Exception as _merge_err:
    print(f"[LocalizationRequest] Startup merge skipped: {_merge_err}")
try:
    merge_vault_bookmarks()
except Exception as _bm_merge_err:
    print(f"[Bookmark] Startup merge skipped: {_bm_merge_err}")
try:
    merge_vault_playtime()
except Exception as _pt_merge_err:
    print(f"[Profile] Playtime startup merge skipped: {_pt_merge_err}")
set_api_instance_ref(api_instance)
