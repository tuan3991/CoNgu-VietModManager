# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - HTTP REST API Routes & Multi-Threaded WSGI Server
----------------------------------------------------------------------------
Cung cấp các endpoint HTTP (/api/...) và máy chủ ThreadingWSGIServer phục vụ giao diện Single-Page UI.
"""

import os
import sys
import json
import time
import socketserver
import urllib.parse
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer
from bottle import Bottle, static_file, request, response, abort

from core.config_manager import (
    APP_DIR,
    STATIC_DIR,
    APPDATA_DIR,
    COVERS_DIR,
    load_user_config,
    save_user_config,
    get_repo_dir,
    get_active_games_json_path,
    get_games,
    load_covers_cache,
    save_covers_cache,
    get_favorite_games,
    toggle_favorite,
    get_bookmarked_games,
    toggle_bookmark,
    get_unified_settings,
    update_unified_settings,
    get_cache_stats,
    clear_app_cache,
    open_appdata_directory,
)

from core.platform_win import WIN_NO_WINDOW

from core.installer_pipeline import (
    INSTALL_PROGRESS,
    check_game_running,
)

from core.steam_client import (
    steam_direct_request,
    search_steam_online,
)

from core.cloud_save import (
    PLAYTIME_MGR,
    CLOUD_SYNC_MGR,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    get_vault_instance,
)

from api.ipc_bridge import (
    ModManagerAPI,
    api_instance,
    fetch_game_metadata_and_avatar,
    make_vertical_poster,
    get_steam_games,
    COMMUNITY_CLOUD_MGR,
    CONTROLLER_ENGINE,
    LOCALIZATION_REQ_MGR,
    merge_vault_custom_games,
    merge_vault_bookmarks,
    merge_vault_playtime,
    sync_bookmarks_to_vault,
    log_startup,
)

server_app = Bottle()
SESSION_AUTH_TOKEN = ""

# Trạng thái Heartbeat của giao diện khi chạy ở chế độ Fallback Browser (Edge/Chrome App Mode).
# Frontend gửi POST /api/heartbeat mỗi 5 giây; watchdog trong app.py sẽ tự thoát tiến trình
# nếu quá 15 giây không nhận được ping (người dùng đã đóng cửa sổ trình duyệt) và không có
# phiên chơi game nào đang hoạt động -> bảo toàn triết lý "Tắt là tắt hẳn" (Zero-Leak Clean Exit).
HEARTBEAT_STATE = {"last": 0.0, "hits": 0}


def mark_ui_heartbeat() -> float:
    """Ghi nhận thời điểm cuối cùng giao diện còn sống (thread-safe nhờ GIL cho dict đơn giản)."""
    now = time.time()
    HEARTBEAT_STATE["last"] = now
    HEARTBEAT_STATE["hits"] = int(HEARTBEAT_STATE.get("hits", 0)) + 1
    return now


def get_ui_heartbeat_age() -> float:
    """Số giây kể từ heartbeat gần nhất (inf nếu chưa từng nhận)."""
    last = float(HEARTBEAT_STATE.get("last", 0.0) or 0.0)
    if last <= 0:
        return float("inf")
    return max(0.0, time.time() - last)


def configure_routes(api: ModManagerAPI = None, session_token: str = ""):
    """Cập nhật api_instance và SESSION_AUTH_TOKEN cho các endpoint."""
    global api_instance, SESSION_AUTH_TOKEN
    if api is not None:
        api_instance = api
    if session_token:
        SESSION_AUTH_TOKEN = session_token


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """
    Multi-Threaded WSGI Server (Mục 1.4):
    Kế thừa socketserver.ThreadingMixIn để xử lý mỗi HTTP request trên một luồng riêng biệt (daemon_threads = True).
    Loại bỏ hoàn toàn nguy cơ nghẽn luồng UI (Single-Threaded bottleneck của wsgiref mặc định)
    khi Frontend vừa tải/cài đặt mod vừa polling /api/progress hoặc tải hình ảnh tĩnh.
    """
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # Bỏ qua các ngoại lệ socket connection reset vô hại khi client hủy request sớm
        pass


class SafeNullWriter:
    def write(self, *args, **kwargs):
        pass
    def flush(self):
        pass

class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress WSGI HTTP request logs

    def get_stderr(self):
        if sys.stderr is not None:
            return sys.stderr
        return SafeNullWriter()


def _is_loopback_origin(origin: str) -> bool:
    """Chấp nhận origin loopback của server hiện tại, từ chối website ngoài."""
    if not origin:
        return True  # pywebview/native IPC và một số fallback request không đặt Origin.
    try:
        parsed = urllib.parse.urlparse(origin)
        return parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


def _is_loopback_host(host: str) -> bool:
    """Chặn DNS-rebinding: Host header phải trỏ loopback (hoặc vắng với client native)."""
    if not host:
        return True
    try:
        parsed = urllib.parse.urlparse("//" + host)
        return parsed.hostname in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


@server_app.hook("before_request")
def verify_session_token():
    """
    CSRF & Localhost Access Protection:
    Blocks unauthorized external websites, browser tabs, or malicious local processes
    from calling /api/ endpoints. Only requests bearing the valid per-session Auth-Token are permitted.
    """
    if request.path.startswith("/api/covers/") or request.path.startswith("/api/game/poster_preview"):
        return
    if request.path.startswith("/api/discovery/clip"):
        # Thẻ <video> phát micro-trailer không gửi được header token; tham số chỉ nhận appid dạng số
        # nên vẫn an toàn tuyệt đối (không thể path traversal, chỉ phục vụ file trong discovery_trailers).
        return
    if request.path.startswith("/api/themes/") and not request.path.rstrip("/").endswith("/api/themes"):
        # custom.css & ảnh nền theme được nạp qua <link>/<img> nên trình duyệt không gửi được header token.
        # An toàn vẫn bảo đảm: chỉ phục vụ file trong thư mục theme + validate_safe_path chống traversal.
        return
    if request.path.startswith("/api/heartbeat"):
        # Ping nhịp sống của giao diện: chỉ cập nhật 1 timestamp, không đọc/ghi dữ liệu người dùng
        # nên an toàn khi miễn token (watchdog Fallback Browser cần ping cả khi chưa kịp đọc token).
        return
    if request.path.startswith("/api/"):
        if not _is_loopback_host(request.headers.get("Host", "")):
            abort(403, "Forbidden: Invalid Host header")
        # Chỉ nhận token qua header: query string dễ lọt vào lịch sử, proxy và log.
        token = request.headers.get("X-App-Auth-Token")
        if not SESSION_AUTH_TOKEN or token != SESSION_AUTH_TOKEN:
            abort(403, "Forbidden: Unauthorized local API access")
        # Chỉ chặn Origin lạ cho request có thể đổi trạng thái. Origin trống vẫn hợp lệ
        # cho native WebView; server chỉ bind 127.0.0.1.
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _is_loopback_origin(request.headers.get("Origin", "")):
            abort(403, "Forbidden: Unauthorized request origin")

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

@server_app.route("/favicon.ico")
@server_app.route("/app_icon.ico")
def serve_app_icon():
    return static_file("app_icon.ico", root=STATIC_DIR)

@server_app.route("/static/<filepath:path>")
def serve_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@server_app.route("/css/<filepath:path>")
def serve_css(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "css"))

@server_app.route("/js/<filepath:path>")
def serve_js(filepath):
    return static_file(filepath, root=os.path.join(STATIC_DIR, "js"))

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

@server_app.route("/api/game/steam_install", method="POST")
def api_game_steam_install():
    """Mở Steam để cài game Ghost Library theo AppID."""
    data = request.json or {}
    res = api_instance.install_game_from_steam(data.get("appid"))
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/game/remap", method="POST")
def api_game_remap():
    data = request.json or {}
    game_id = data.get("game_id", "")
    target_appid = str(data.get("steam_appid", "")).strip()
    target_title = data.get("title", "").strip()
    avatar_url = data.get("avatar_url", "").strip()

    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu game_id"})

    res = api_instance.apply_selected_avatar(game_id, {
        "steam_appid": target_appid if target_appid.isdigit() else "",
        "title": target_title,
        "source": data.get("source", ""),
        "avatar_url": avatar_url or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{target_appid}/library_600x900.jpg" if target_appid.isdigit() else ""),
        "header_url": data.get("header_url") or (f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{target_appid}/header.jpg" if target_appid.isdigit() else "")
    })
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/game/poster_preview", method="GET")
def api_game_poster_preview():
    """Proxy chuyển đổi mọi ảnh banner ngang thành Poster dọc 600x900 Glassmorphism không bị cắt chữ."""
    img_url = (request.query.get("url") or "").strip()
    if not img_url:
        abort(404)
    raw = steam_direct_request(img_url, timeout=4.0)
    if not raw or len(raw) < 500:
        abort(404)
    formatted = make_vertical_poster(raw)
    response.content_type = "image/jpeg"
    response.set_header("Cache-Control", "public, max-age=86400")
    return formatted

@server_app.route("/api/games", method="GET")
def api_get_games():
    response.content_type = "application/json"
    return json.dumps(api_instance.get_games(), ensure_ascii=False)

@server_app.route("/api/favorite/toggle", method="POST")
def api_toggle_favorite():
    data = request.json or {}
    game_id = data.get("game_id") or ""
    res = toggle_favorite(game_id)
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/favorites", method="GET")
def api_get_favorites():
    response.content_type = "application/json"
    return json.dumps({"success": True, "favorites": get_favorite_games()}, ensure_ascii=False)


@server_app.route("/api/bookmark/toggle", method="POST")
def api_toggle_bookmark():
    """Bật/tắt "Thêm vào Thư viện" và đồng bộ ngay vào Hồ Sơ .congu_save."""
    data = request.json or {}
    payload = data.get("game") if isinstance(data.get("game"), dict) else data
    res = toggle_bookmark(payload)
    if res.get("success"):
        res["vault_synced"] = sync_bookmarks_to_vault()
    else:
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/bookmarks", method="GET")
def api_get_bookmarks():
    response.content_type = "application/json"
    return json.dumps({"success": True, "bookmarks": get_bookmarked_games()}, ensure_ascii=False)


# ==============================================================================
# CUSTOM THEMES (Giao diện người dùng) REST API
# ==============================================================================

@server_app.route("/api/themes", method="GET")
def api_get_themes():
    """Danh sách theme (builtin + người dùng) kèm theme đang dùng."""
    response.content_type = "application/json"
    return json.dumps(api_instance.get_themes(), ensure_ascii=False)

@server_app.route("/api/themes/active", method="POST")
def api_set_active_theme():
    """Kích hoạt theme theo id, áp dụng ngay không cần khởi động lại app."""
    data = request.json or {}
    theme_id = (data.get("theme_id") or "").strip()
    res = api_instance.set_theme(theme_id)
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/detail", method=["GET", "POST"])
def api_get_theme_detail():
    """Lấy manifest + thông tin assets của một theme để frontend áp dụng tức thì."""
    if request.method == "POST":
        data = request.json or {}
    else:
        data = {"theme_id": request.query.get("theme_id") or request.query.get("id") or ""}
    theme_id = (data.get("theme_id") or "").strip()
    res = api_instance.get_theme_payload(theme_id)
    if not res.get("success"):
        response.status = 404
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/import", method="POST")
def api_import_theme():
    """Mở hộp thoại chọn gói .congu_theme và cài đặt an toàn."""
    res = api_instance.import_theme_dialog()
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/export", method="POST")
def api_export_theme():
    """Đóng gói theme hiện tại thành file .congu_theme để chia sẻ."""
    data = request.json or {}
    theme_id = (data.get("theme_id") or "").strip()
    res = api_instance.export_theme_dialog(theme_id)
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/studio", method="POST")
def api_theme_studio():
    """Lưu theme do người dùng tự chỉnh (màu sắc, blur, ảnh nền)."""
    data = request.json or {}
    res = api_instance.save_theme_studio(data)
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/pick_background", method="POST")
def api_theme_pick_background():
    """Mở hộp thoại chọn ảnh nền wallpaper cho Theme Studio."""
    res = api_instance.pick_theme_background()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/delete", method="POST")
def api_delete_theme():
    """Xóa theme người dùng (không xóa theme mặc định hoặc theme đang dùng)."""
    data = request.json or {}
    theme_id = (data.get("theme_id") or "").strip()
    res = api_instance.delete_theme(theme_id)
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/themes/<theme_id>/custom.css", method="GET")
def api_theme_custom_css(theme_id):
    """Phục vụ custom.css của theme (đã lọc @import / url ngoài)."""
    try:
        from core.theme_manager import get_theme_css
        css = get_theme_css(theme_id)
    except Exception:
        abort(404)
    if not css:
        abort(404)
    response.content_type = "text/css; charset=utf-8"
    response.set_header("Cache-Control", "no-cache")
    return css

@server_app.route("/api/themes/<theme_id>/assets/<filepath:path>", method="GET")
def api_theme_asset(theme_id, filepath):
    """Phục vụ ảnh nền / font của theme với kiểm tra chống Path Traversal."""
    try:
        from core.theme_manager import resolve_asset_path
        abs_path = resolve_asset_path(theme_id, filepath)
    except Exception:
        abort(404)
    response.set_header("Cache-Control", "public, max-age=3600")
    return static_file(os.path.basename(abs_path), root=os.path.dirname(abs_path))


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
    force = bool(data.get("force", False))
    res = api_instance.launch_game(game_id, force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/game/doctor", method=["GET", "POST"])
def api_game_doctor():
    """Pre-Flight Game Doctor: kiểm tra runtime / DirectX / BepInEx / font trước khi chơi."""
    data = request.json or {}
    game_id = data.get("game_id") or request.query.get("game_id")
    res = api_instance.run_game_doctor(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/playtime/<game_id>", method="GET")
def api_get_playtime(game_id):
    res = api_instance.get_playtime_stats(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/playtime/stats", method=["GET", "POST"])
def api_get_all_playtime():
    data = request.json or {}
    game_id = data.get("game_id") or request.query.get("game_id")
    if game_id:
        res = api_instance.get_playtime_stats(game_id)
    else:
        res = PLAYTIME_MGR.get_all_stats()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/achievements/poll_new", method=["GET", "POST"])
def api_poll_new_achievements():
    res = api_instance.poll_new_achievements()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/achievements/<game_id_or_appid>", method=["GET", "POST"])
def api_get_achievements(game_id_or_appid):
    game_dir = request.query.get("game_dir", "") or (request.json.get("game_dir", "") if request.json else "")
    res = api_instance.get_game_achievements(game_id_or_appid, game_dir)
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

@server_app.route("/api/open_save_folder", method="POST")
def api_open_save_folder():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.open_save_folder(game_id)
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

@server_app.route("/api/check_compatibility", method="POST")
def api_check_compatibility():
    data = request.json or {}
    game_id = data.get("game_id")
    res = api_instance.check_compatibility(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/troubleshoot/guides", method="GET")
def api_troubleshoot_guides():
    res = api_instance.get_troubleshooting_guides()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/troubleshoot/inspect_backups", method="POST")
def api_troubleshoot_inspect_backups():
    data = request.json or {}
    game_id = data.get("game_id", "")
    res = api_instance.inspect_game_backups(game_id)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/troubleshoot/audit_logs", method="POST")
def api_troubleshoot_audit_logs():
    data = request.json or {}
    game_id = data.get("game_id", "")
    limit = data.get("limit", 50)
    res = api_instance.get_recent_audit_logs(game_id, limit)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/troubleshoot/support_report", method="POST")
def api_troubleshoot_support_report():
    data = request.json or {}
    game_id = data.get("game_id", "")
    res = api_instance.generate_support_report(game_id)
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


# ========================================================
# Google Drive Cloud Save & Ecosystem REST API Endpoints
# ========================================================

@server_app.route("/api/cloud/status", method="GET")
def api_cloud_status():
    """Lấy trạng thái kết nối tài khoản Google Drive cá nhân."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        return json.dumps({"connected": False})
    return json.dumps(CLOUD_SYNC_MGR.get_connection_info(), ensure_ascii=False)

@server_app.route("/api/cloud/login", method="POST")
def api_cloud_login():
    """Khởi chạy luồng xác thực Google OAuth2 PKCE Desktop Flow."""
    data = request.json or {}
    cfg = load_user_config()
    client_id = data.get("client_id") or cfg.get("google_client_id", "") or DEFAULT_CLIENT_ID
    client_secret = data.get("client_secret") or cfg.get("google_client_secret", "") or DEFAULT_CLIENT_SECRET

    if not client_id:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "error": "Chưa có Google Client ID. Vui lòng nhập Client ID của bạn bên dưới (hoặc chờ quản trị viên cấp Client ID mặc định)."
        }, ensure_ascii=False)

    # Tự động lưu Client ID vào cấu hình nếu người dùng nhập riêng
    if data.get("client_id"):
        cfg["google_client_id"] = data["client_id"].strip()
        if data.get("client_secret"):
            cfg["google_client_secret"] = data["client_secret"].strip()
        save_user_config(cfg)

    response.content_type = "application/json"
    res = CLOUD_SYNC_MGR.start_oauth_flow(client_id, client_secret)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/logout", method="POST")
def api_cloud_logout():
    """Đăng xuất tài khoản Google Drive."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR:
        return json.dumps(CLOUD_SYNC_MGR.logout(), ensure_ascii=False)
    return json.dumps({"success": True})

@server_app.route("/api/cloud/config", method=["GET", "POST"])
def api_cloud_config():
    """Đọc hoặc lưu Client ID / Secret của Google Cloud Console."""
    response.content_type = "application/json"
    cfg = load_user_config()
    if request.method == "POST":
        data = request.json or {}
        cid = data.get("client_id", "").strip()
        csec = data.get("client_secret", "").strip()
        if cid:
            cfg["google_client_id"] = cid
        if csec:
            cfg["google_client_secret"] = csec
        save_user_config(cfg)
        return json.dumps({"success": True, "message": "Đã lưu cấu hình Google OAuth thành công!"})
    else:
        cid = cfg.get("google_client_id", "") or DEFAULT_CLIENT_ID
        csec = cfg.get("google_client_secret", "") or DEFAULT_CLIENT_SECRET
        masked_sec = (csec[:4] + "********" + csec[-4:]) if len(csec) > 8 else ("********" if csec else "")
        return json.dumps({
            "client_id": cid,
            "has_secret": bool(csec),
            "masked_secret": masked_sec,
            "is_default": not bool(cfg.get("google_client_id")) and bool(DEFAULT_CLIENT_ID)
        })

@server_app.route("/api/cloud/save/status", method="POST")
def api_cloud_save_status():
    """Kiểm tra trạng thái đồng bộ 3 chiều (Local vs Cloud vs Last Sync) của một game."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.check_game_sync_status(game_config, game_dir)
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/save/sync", method="POST")
def api_cloud_save_sync():
    """Thực thi đồng bộ Save Game (Upload, Download hoặc Resolve Conflict)."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    action = data.get("action")  # "upload", "download", hoặc None (auto)
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.sync_game_save(game_config, game_dir, force_action=action)
    if not res.get("success") and res.get("action") != "conflict":
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/cloud/save/backups/<game_id>", method="GET")
def api_cloud_save_backups(game_id):
    """Liệt kê danh sách các bản backup cục bộ (tối đa 3 slots)."""
    response.content_type = "application/json"
    backups = CLOUD_SYNC_MGR.list_local_backups(game_id)
    return json.dumps({"game_id": game_id, "backups": backups}, ensure_ascii=False)

@server_app.route("/api/cloud/save/restore_backup", method="POST")
def api_cloud_save_restore_backup():
    """Khôi phục lại bản backup cục bộ đã lưu."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    backup_filename = data.get("backup_filename")
    if not game_id or not backup_filename:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu tham số game_id hoặc backup_filename"})

    games = get_games()
    game_config = next((g for g in games if g["id"] == game_id), None)
    if not game_config:
        response.status = 404
        return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})

    cfg = load_user_config()
    game_dir = cfg.get(f"{game_id}_path")

    res = CLOUD_SYNC_MGR.restore_local_backup(game_id, backup_filename, game_config, game_dir)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# HỒ SƠ GAME THỦ (PROFILE, HUY HIỆU, TOP GAME)
# ==============================================================================

@server_app.route("/api/profile/overview", method="GET")
def api_profile_overview():
    """Tổng hợp Hồ Sơ: level/XP, huy hiệu nền tảng, top game, hoạt động gần đây."""
    response.content_type = "application/json"
    return json.dumps(api_instance.get_profile_overview(), ensure_ascii=False)


# ==============================================================================
# HỒ SƠ DI ĐỘNG HỢP NHẤT (PORTABLE SAVE VAULT - .congu_save) API
# ==============================================================================

@server_app.route("/api/vault/status", method="GET")
def api_vault_status():
    """Lấy thông tin tổng quan của Hồ Sơ Di Động Hợp Nhất (.congu_save)."""
    response.content_type = "application/json"
    vault = get_vault_instance()
    info = vault.get_vault_info()
    cloud_info = {}
    if "CLOUD_SYNC_MGR" in globals() and CLOUD_SYNC_MGR and CLOUD_SYNC_MGR.is_connected():
        cloud_info = CLOUD_SYNC_MGR.get_vault_cloud_info(os.path.basename(vault.vault_path))
    info["cloud"] = cloud_info
    return json.dumps(info, ensure_ascii=False)

@server_app.route("/api/vault/pack", method="POST")
def api_vault_pack():
    """Gom Save Game, Thành tựu & Giờ chơi vào Hồ Sơ Di Động."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    vault = get_vault_instance()
    games = get_games()
    cfg = load_user_config()

    if game_id:
        game_config = next((g for g in games if g["id"] == game_id), None)
        if not game_config:
            response.status = 404
            return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})
        game_dir = cfg.get(f"{game_id}_path", "")
        res = vault.pack_game_to_vault(game_config, game_dir)
        return json.dumps({"success": True, "game_stat": res, "message": f"Đã đóng gói {game_config.get('title', game_id)} vào Hồ Sơ!"}, ensure_ascii=False)
    else:
        # Đóng gói toàn bộ game tìm thấy
        results = {}
        count = 0
        for g in games:
            gid = g["id"]
            gdir = cfg.get(f"{gid}_path", "")
            if gdir and os.path.exists(gdir):
                stat = vault.pack_game_to_vault(g, gdir)
                results[gid] = stat
                count += 1
        return json.dumps({"success": True, "count": count, "games": results, "message": f"Đã đóng gói {count} tựa game vào Hồ Sơ!"}, ensure_ascii=False)

@server_app.route("/api/vault/unpack", method="POST")
def api_vault_unpack():
    """Bung Save Game & Thành tựu từ Hồ Sơ Di Động ra máy tính."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id")
    backup_existing = data.get("backup_existing", True)
    vault = get_vault_instance()
    games = get_games()
    cfg = load_user_config()

    if game_id:
        game_config = next((g for g in games if g["id"] == game_id), None)
        if not game_config:
            response.status = 404
            return json.dumps({"success": False, "error": f"Không tìm thấy game '{game_id}'"})
        game_dir = cfg.get(f"{game_id}_path", "")
        res = vault.unpack_game_from_vault(game_config, game_dir, backup_existing=backup_existing)
        return json.dumps(res, ensure_ascii=False)
    else:
        # Bung toàn bộ game đã cài
        res = vault.unpack_all_installed_games(games, cfg)
        return json.dumps({"success": True, "results": res, "message": f"Đã bung Save cho {len(res)} game vào máy!"}, ensure_ascii=False)

@server_app.route("/api/vault/export", method="POST")
def api_vault_export():
    """Xuất file .congu_save ra USB hoặc thư mục được chọn."""
    response.content_type = "application/json"
    data = request.json or {}
    target_path = data.get("target_path")
    if not target_path:
        target_path = api_instance.export_vault_dialog()
        if not target_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy xuất file"})

    vault = get_vault_instance()
    res = vault.export_vault(target_path)
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/export_standard_zip", method="POST")
def api_vault_export_standard_zip():
    """Xuất save thành ZIP chuẩn mở được bằng Explorer/WinRAR/7-Zip."""
    response.content_type = "application/json"
    data = request.json or {}
    target_path = data.get("target_path")
    if not target_path:
        target_path = api_instance.export_standard_zip_dialog()
        if not target_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy xuất ZIP"})
    vault = get_vault_instance()
    res = vault.export_standard_zip(target_path, get_games(), load_user_config())
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/import_standard_zip", method="POST")
def api_vault_import_standard_zip():
    """Khôi phục trực tiếp từ ZIP chuẩn theo save_manifest.json."""
    response.content_type = "application/json"
    data = request.json or {}
    source_path = data.get("source_path")
    if not source_path:
        source_path = api_instance.select_standard_zip_dialog()
        if not source_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy chọn ZIP"})
    vault = get_vault_instance()
    res = vault.import_standard_zip(source_path, get_games(), load_user_config(), backup_existing=data.get("backup_existing", True))
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/vault/revisions", method=["GET", "POST"])
def api_vault_revisions():
    """Time Machine: liệt kê 3 thế hệ save (current / prev_1 / prev_2) của 1 game."""
    data = request.json or {}
    game_id = data.get("game_id") or request.query.get("game_id")
    response.content_type = "application/json"
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"}, ensure_ascii=False)
    res = api_instance.get_save_revisions(game_id)
    if not res.get("success"):
        response.status = 404
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/vault/restore_revision", method="POST")
def api_vault_restore_revision():
    """Time Machine: khôi phục save của phiên chơi trước (prev_1 / prev_2 / current)."""
    data = request.json or {}
    game_id = data.get("game_id")
    revision = data.get("revision") or "prev_1"
    response.content_type = "application/json"
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "error": "Thiếu game_id"}, ensure_ascii=False)
    res = api_instance.restore_previous_save(game_id, revision=revision)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/vault/import", method="POST")
def api_vault_import():
    """Nạp file .congu_save từ USB hoặc file được chọn vào hệ thống."""
    response.content_type = "application/json"
    data = request.json or {}
    source_path = data.get("source_path")
    auto_unpack = data.get("auto_unpack", True)
    if not source_path:
        source_path = api_instance.select_vault_file_dialog()
        if not source_path:
            return json.dumps({"success": False, "cancelled": True, "message": "Người dùng đã hủy chọn file"})

    vault = get_vault_instance()
    res = vault.import_vault(source_path)
    if res.get("success") and auto_unpack:
        # Khôi phục danh sách game lẻ + yêu cầu Việt hóa đi kèm Hồ Sơ sang PC này
        try:
            res["restored_custom_games"] = merge_vault_custom_games()
        except Exception as e:
            print(f"[VaultImport] merge custom games warning: {e}")
        try:
            res["restored_bookmarks"] = merge_vault_bookmarks()
        except Exception as e:
            print(f"[VaultImport] merge bookmarks warning: {e}")
        try:
            res["restored_playtime_games"] = merge_vault_playtime()
        except Exception as e:
            print(f"[VaultImport] merge playtime warning: {e}")
        games = get_games()
        cfg = load_user_config()
        unpack_res = vault.unpack_all_installed_games(games, cfg)
        res["auto_unpack_results"] = unpack_res
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/open_folder", method="POST")
def api_vault_open_folder():
    """Mở thư mục chứa file PlayerProfile.congu_save trên Windows Explorer."""
    response.content_type = "application/json"
    vault = get_vault_instance()
    folder = os.path.dirname(vault.vault_path)
    try:
        if os.path.exists(vault.vault_path):
            subprocess.Popen(f'explorer /select,"{vault.vault_path}"', creationflags=WIN_NO_WINDOW)
        else:
            os.startfile(folder)
        return json.dumps({"success": True, "folder": folder})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@server_app.route("/api/vault/cloud/upload", method="POST")
def api_vault_cloud_upload():
    """Tải file PlayerProfile.congu_save lên Google Drive (Zero-Bloat, siêu tốc)."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        response.status = 400
        return json.dumps({"success": False, "error": "Chưa khởi tạo CloudSyncManager"})

    vault = get_vault_instance()
    res = CLOUD_SYNC_MGR.sync_vault_to_drive(vault.vault_path)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/vault/cloud/download", method="POST")
def api_vault_cloud_download():
    """Tải file PlayerProfile.congu_save từ Google Drive về máy và nạp vào hệ thống."""
    response.content_type = "application/json"
    if "CLOUD_SYNC_MGR" not in globals() or not CLOUD_SYNC_MGR:
        response.status = 400
        return json.dumps({"success": False, "error": "Chưa khởi tạo CloudSyncManager"})

    data = request.json or {}
    auto_unpack = data.get("auto_unpack", True)
    vault = get_vault_instance()
    res = CLOUD_SYNC_MGR.download_vault_from_drive(vault.vault_path)
    if res.get("success"):
        merge_vault_custom_games()
        merge_vault_bookmarks()
        merge_vault_playtime()
    if res.get("success") and auto_unpack:
        games = get_games()
        cfg = load_user_config()
        unpack_res = vault.unpack_all_installed_games(games, cfg)
        res["auto_unpack_results"] = unpack_res
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# ĐÁM MÂY CỔ NGỮ (COMMUNITY CLOUD HUB - GOOGLE APPS SCRIPT) API
# ==============================================================================

@server_app.route("/api/community_cloud/status", method="GET")
def api_community_cloud_status():
    """Lấy trạng thái tài khoản Đám Mây Cổ Ngữ (Cloud ID, Last Sync, Server Configured)."""
    response.content_type = "application/json"
    if "COMMUNITY_CLOUD_MGR" not in globals() or not COMMUNITY_CLOUD_MGR:
        return json.dumps({"is_logged_in": False, "is_server_configured": False, "cloud_id": ""})
    return json.dumps(COMMUNITY_CLOUD_MGR.get_status(), ensure_ascii=False)

@server_app.route("/api/community_cloud/register", method="POST")
def api_community_cloud_register():
    """Đăng ký Mã Cloud ID và Mật khẩu tự chọn."""
    response.content_type = "application/json"
    data = request.json or {}
    cloud_id = data.get("cloud_id", "")
    password = data.get("password", "")
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.register(cloud_id, password, server_url=server_url)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/login", method="POST")
def api_community_cloud_login():
    """Đăng nhập bằng Mã Cloud ID và Mật khẩu trên máy khác."""
    response.content_type = "application/json"
    data = request.json or {}
    cloud_id = data.get("cloud_id", "")
    password = data.get("password", "")
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.login(cloud_id, password, server_url=server_url)
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/logout", method="POST")
def api_community_cloud_logout():
    """Đăng xuất tài khoản Đám Mây Cổ Ngữ khỏi máy này."""
    response.content_type = "application/json"
    res = COMMUNITY_CLOUD_MGR.logout()
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/upload", method="POST")
def api_community_cloud_upload():
    """Đóng gói toàn bộ save và đẩy lên Mây tập trung."""
    response.content_type = "application/json"
    res = COMMUNITY_CLOUD_MGR.upload_save()
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/download", method="POST")
def api_community_cloud_download():
    """Kéo save từ Mây về máy và tự động bung vào các game đã cài."""
    response.content_type = "application/json"
    data = request.json or {}
    auto_unpack = data.get("auto_unpack", True)
    res = COMMUNITY_CLOUD_MGR.download_save(auto_unpack=auto_unpack)
    if res.get("success"):
        # Hồ Sơ vừa được thay bằng bản trên Mây -> đồng bộ lại game lẻ, Chưa tải, giờ chơi
        try:
            merge_vault_custom_games()
            merge_vault_bookmarks()
            merge_vault_playtime()
        except Exception as e:
            print(f"[CommunityCloud] Post-download merge warning: {e}")
    else:
        response.status = 400
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/community_cloud/config", method="POST")
def api_community_cloud_config():
    """Lưu URL Web App máy chủ của Admin."""
    response.content_type = "application/json"
    data = request.json or {}
    server_url = data.get("server_url", "")
    res = COMMUNITY_CLOUD_MGR.set_server_url(server_url)
    return json.dumps(res, ensure_ascii=False)


# =========================================================================
# GAMEPAD EMULATION & STEAM INPUT FOR OFFLINE GAMES (CẤP ĐỘ 3)
# =========================================================================
@server_app.route("/api/gamepad/controllers", method="GET")
def api_gamepad_controllers():
    """Liệt kê tất cả các tay cầm đang kết nối (PlayStation, Xbox, Switch, DirectInput)."""
    response.content_type = "application/json"
    try:
        controllers = CONTROLLER_ENGINE.detect_controllers()
        return json.dumps({"success": True, "controllers": controllers}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "controllers": []}, ensure_ascii=False)


@server_app.route("/api/gamepad/config/<game_id>", method="GET")
def api_gamepad_get_config(game_id):
    """Lấy cấu hình giả lập tay cầm cho game (từ Hồ Sơ .congu_save)."""
    response.content_type = "application/json"
    try:
        cfg = CONTROLLER_ENGINE.get_game_gamepad_config(game_id)
        return json.dumps({"success": True, "config": cfg}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@server_app.route("/api/gamepad/config", method="POST")
def api_gamepad_save_config():
    """Lưu cấu hình giả lập tay cầm cho game vào thẳng Hồ Sơ .congu_save."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    config = data.get("config", {})
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    try:
        ok = CONTROLLER_ENGINE.save_game_gamepad_config(game_id, config)
        return json.dumps({
            "success": ok,
            "message": "Đã lưu cấu hình tay cầm vào Hồ Sơ .congu_save!" if ok else "Không thể lưu cấu hình."
        }, ensure_ascii=False)
    except Exception as e:
        response.status = 500
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@server_app.route("/api/gamepad/test_vibration", method="POST")
def api_gamepad_test_vibration():
    """Rung thử nghiệm tay cầm để người dùng kiểm tra phản hồi xúc giác."""
    response.content_type = "application/json"
    data = request.json or {}
    ctrl_idx = int(data.get("controller_index", 0))
    duration = float(data.get("duration_sec", 0.5))
    try:
        ok = CONTROLLER_ENGINE.test_vibration(ctrl_idx, duration)
        return json.dumps({
            "success": ok,
            "message": "Đã kích hoạt rung tay cầm!" if ok else "Tay cầm không hỗ trợ rung XInput hoặc chưa kết nối."
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# =========================================================================
# NON-STEAM & CUSTOM GAMES AUTO-DISCOVERY PIPELINE (THÊM GAME NGOÀI)
# =========================================================================
@server_app.route("/api/custom_games/browse_exe", method="POST")
def api_custom_games_browse_exe():
    """Mở hộp thoại chọn file .exe của game ngoài."""
    response.content_type = "application/json"
    res = api_instance.browse_custom_game_exe()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/detect", method="POST")
def api_custom_games_detect():
    """Tự động phân tích và nhận diện game ngoài qua 4 phễu thông minh."""
    response.content_type = "application/json"
    data = request.json or {}
    exe_path = data.get("exe_path", "")
    if not exe_path:
        response.status = 400
        return json.dumps({"success": False, "message": "Đường dẫn file .exe không được để trống!"}, ensure_ascii=False)
    res = api_instance.detect_custom_game(exe_path)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/save", method="POST")
def api_custom_games_save():
    """Lưu game ngoài vào danh sách thư viện CỔ NGỮ."""
    response.content_type = "application/json"
    data = request.json or {}
    game_data = data.get("game_data", {})
    if not game_data:
        response.status = 400
        return json.dumps({"success": False, "message": "Dữ liệu game không được để trống!"}, ensure_ascii=False)
    res = api_instance.save_custom_game(game_data)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/delete", method="POST")
def api_custom_games_delete():
    """Xóa game ngoài khỏi thư viện."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.delete_custom_game(game_id)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/custom_games/set_appid", method="POST")
def api_custom_games_set_appid():
    """Cập nhật Steam AppID cho game tự thêm và tải schema thành tựu."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    steam_appid = str(data.get("steam_appid", "")).strip()
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.set_custom_game_appid(game_id, steam_appid)
    return json.dumps(res, ensure_ascii=False)


# =========================================================================
# YÊU CẦU VIỆT HÓA CHO GAME LẺ (LOCALIZATION REQUESTS -> FILE .CONGU_SAVE)
# =========================================================================
@server_app.route("/api/localization/inspect", method="POST")
def api_localization_inspect():
    """Quét nhanh Engine & cấu trúc file ngôn ngữ của game ngoài (Engine Telemetry)."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.inspect_custom_game_engine(game_id)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/localization/request", method="POST")
def api_localization_request():
    """Gửi yêu cầu Việt hóa cho game lẻ và lưu vĩnh viễn vào .congu_save."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    user_note = data.get("user_note", "")
    if not game_id:
        response.status = 400
        return json.dumps({"success": False, "message": "game_id không được để trống!"}, ensure_ascii=False)
    res = api_instance.request_custom_game_localization(game_id, user_note)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/localization/my_requests", method="GET")
def api_localization_my_requests():
    """Danh sách yêu cầu Việt hóa của tôi (đọc từ Hồ Sơ .congu_save + trạng thái máy chủ)."""
    response.content_type = "application/json"
    res = api_instance.get_my_localization_requests()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/localization/sync", method="POST")
def api_localization_sync():
    """Đồng bộ trạng thái yêu cầu & phát hiện game đã có bản Việt Hóa chính thức ('Tin vui!')."""
    response.content_type = "application/json"
    res = api_instance.sync_localization_requests()
    return json.dumps(res, ensure_ascii=False)


# =========================================================================
# HYDRA REPACK SOURCES & TORRENT DOWNLOAD ENGINE REST APIS
# =========================================================================
@server_app.route("/api/hydra/sources", method="GET")
def api_hydra_sources():
    """Lấy danh sách các nguồn Hydra và thống kê cache."""
    response.content_type = "application/json"
    res = api_instance.get_hydra_sources()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/add", method="POST")
def api_hydra_sources_add():
    """Thêm nguồn Hydra mới."""
    response.content_type = "application/json"
    data = request.json or {}
    urls = data.get("urls") or data.get("url")
    if not urls:
        response.status = 400
        return json.dumps({"success": False, "message": "URL nguồn không được để trống!"}, ensure_ascii=False)
    res = api_instance.add_hydra_sources(urls)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/remove", method="POST")
def api_hydra_sources_remove():
    """Xóa một nguồn Hydra."""
    response.content_type = "application/json"
    data = request.json or {}
    url = data.get("url", "")
    if not url:
        response.status = 400
        return json.dumps({"success": False, "message": "URL nguồn không được để trống!"}, ensure_ascii=False)
    res = api_instance.remove_hydra_source(url)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/sync", method="POST")
def api_hydra_sources_sync():
    """Đồng bộ các nguồn Hydra."""
    response.content_type = "application/json"
    data = request.json or {}
    force = bool(data.get("force", False))
    res = api_instance.sync_hydra_sources(force=force)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/sources/import_local", method="POST")
def api_hydra_sources_import_local():
    """Mở hộp thoại chọn file .json từ máy tính và nạp vào cache."""
    response.content_type = "application/json"
    res = api_instance.browse_and_import_hydra_json()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/catalogue/search", method=["GET", "POST"])
def api_hydra_catalogue_search():
    """Tìm kiếm danh mục game và link tải theo từng nguồn Repack."""
    response.content_type = "application/json"
    if request.method == "POST":
        data = request.json or {}
    else:
        data = dict(request.query)
    query = data.get("query", "").strip()
    limit = int(data.get("limit", 50))
    res = api_instance.search_catalogue_games(query=query, limit=limit)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/hydra/search", method="POST")
def api_hydra_search():
    """Tìm kiếm link tải game theo game_id hoặc tên game."""
    response.content_type = "application/json"
    data = request.json or {}
    game_id = data.get("game_id", "")
    query_title = data.get("title", "")
    steam_appid = str(data.get("steam_appid", "")).strip()
    res = api_instance.search_game_downloads(game_id=game_id, query_title=query_title, steam_appid=steam_appid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/start", method="POST")
def api_torrent_start():
    """Bắt đầu tải file qua aria2c."""
    response.content_type = "application/json"
    data = request.json or {}
    uri = data.get("uri", "")
    title = data.get("title", "")
    save_dir = data.get("save_dir", None)
    if not uri:
        response.status = 400
        return json.dumps({"success": False, "message": "URI tải về không được để trống!"}, ensure_ascii=False)
    res = api_instance.start_torrent_download(uri=uri, title=title, save_dir=save_dir)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/status", method="GET")
def api_torrent_status():
    """Lấy trạng thái tất cả các download."""
    response.content_type = "application/json"
    res = api_instance.get_torrent_downloads_status()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/pause", method="POST")
def api_torrent_pause():
    """Tạm dừng một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.pause_torrent_download(gid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/resume", method="POST")
def api_torrent_resume():
    """Tiếp tục một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.resume_torrent_download(gid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/cancel", method="POST")
def api_torrent_cancel():
    """Hủy một tác vụ tải."""
    response.content_type = "application/json"
    data = request.json or {}
    gid = data.get("gid", "")
    delete_files = bool(data.get("delete_files", False))
    if not gid:
        response.status = 400
        return json.dumps({"success": False, "message": "GID không được để trống!"}, ensure_ascii=False)
    res = api_instance.cancel_torrent_download(gid, delete_files=delete_files)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/open_external", method="POST")
def api_torrent_open_external():
    """Mở link qua ứng dụng Torrent bên ngoài."""
    response.content_type = "application/json"
    data = request.json or {}
    uri = data.get("uri", "")
    if not uri:
        response.status = 400
        return json.dumps({"success": False, "message": "URI không được để trống!"}, ensure_ascii=False)
    res = api_instance.open_external_torrent(uri)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/torrent/open_folder", method="POST")
def api_torrent_open_folder():
    """Mở thư mục chứa file tải về."""
    response.content_type = "application/json"
    data = request.json or {}
    folder_path = data.get("folder_path", None)
    res = api_instance.open_torrent_folder(folder_path)
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# DISCOVERY HUB (TAB KHÁM PHÁ) REST APIS
# Ghép 3 nguồn: Steam Trending + Nguồn tải Hydra (.json) + Kho Việt hóa (games.json)
# ==============================================================================

@server_app.route("/api/discovery/feed", method=["GET", "POST"])
def api_discovery_feed():
    """Feed tổng hợp cho tab Khám Phá (cache 6 tiếng, mở tab tức thì)."""
    response.content_type = "application/json"
    force = False
    if request.method == "POST":
        data = request.json or {}
        force = bool(data.get("force_refresh") or data.get("refresh"))
    else:
        force = str(request.query.get("refresh") or "").lower() in ("1", "true", "yes")
    res = api_instance.get_discovery_feed(force_refresh=force)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/discovery/trailer", method=["GET", "POST"])
def api_discovery_trailer():
    """Thông tin micro-trailer + link clip MP4 cục bộ để phát preview khi rê chuột lên Poster."""
    response.content_type = "application/json"
    appid = ""
    seconds = 12
    if request.method == "POST":
        data = request.json or {}
        appid = str(data.get("steam_appid") or data.get("appid") or "").strip()
        seconds = data.get("seconds") or 12
    else:
        appid = str(request.query.get("steam_appid") or request.query.get("appid") or "").strip()
        seconds = request.query.get("seconds") or 12
    try:
        seconds = int(seconds)
    except Exception:
        seconds = 12
    res = api_instance.get_discovery_trailer(appid, seconds)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/discovery/clip", method="GET")
def api_discovery_clip():
    """
    Phục vụ file micro-trailer MP4 cục bộ (đã cắt 12-20s đầu) với hỗ trợ HTTP Range.
    Được whitelist khỏi kiểm tra token vì thẻ <video> của trình duyệt không gửi được header,
    và tham số chỉ nhận Steam AppID dạng số nên không thể path traversal.
    """
    appid = str(request.query.get("appid") or request.query.get("steam_appid") or "").strip()
    try:
        seconds = int(request.query.get("seconds") or 12)
    except Exception:
        seconds = 12
    res = api_instance.get_discovery_clip(appid, seconds)
    if not res.get("success"):
        abort(404, res.get("message") or "Không có trailer cho tựa game này")
    response.set_header("Cache-Control", "public, max-age=604800")
    return static_file(res["file"], root=os.path.dirname(res["path"]))


@server_app.route("/api/discovery/pc_check", method=["GET", "POST"])
def api_discovery_pc_check():
    """Đánh giá tương thích cấu hình máy với game (RAM/CPU/GPU vs pc_requirements)."""
    response.content_type = "application/json"
    appid = ""
    if request.method == "POST":
        data = request.json or {}
        appid = str(data.get("steam_appid") or data.get("appid") or "").strip()
    else:
        appid = str(request.query.get("steam_appid") or request.query.get("appid") or "").strip()
    res = api_instance.check_pc_compatibility(appid)
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/discovery/watchlist", method=["GET", "POST"])
def api_discovery_watchlist():
    """Đọc hoặc cập nhật danh sách game đang Theo dõi bản tải / Việt hóa."""
    response.content_type = "application/json"
    if request.method == "POST":
        data = request.json or {}
        res = api_instance.update_discovery_watchlist(
            action=str(data.get("action") or "add"),
            title=str(data.get("title") or ""),
            steam_appid=str(data.get("steam_appid") or ""),
            poster_url=str(data.get("poster_url") or ""),
        )
        if not res.get("success"):
            response.status = 400
        return json.dumps(res, ensure_ascii=False)
    res = api_instance.get_discovery_watchlist()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/discovery/request_vietnamese", method="POST")
def api_discovery_request_vietnamese():
    """Nút 'Yêu cầu Việt hóa' cho game hot chưa có tiếng Việt."""
    response.content_type = "application/json"
    data = request.json or {}
    title = str(data.get("title") or data.get("game_name") or "").strip()
    if not title:
        response.status = 400
        return json.dumps({"success": False, "message": "Thiếu tên game cần Việt hóa!"}, ensure_ascii=False)
    res = api_instance.request_vietnamese_localization(
        title=title,
        steam_appid=str(data.get("steam_appid") or ""),
        note=str(data.get("note") or ""),
    )
    if not res.get("success"):
        response.status = 400
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/app/quit", method="POST")
def api_app_quit():
    """Immediately and completely shut down the application and all background processes"""
    data = request.json or {}
    force = bool(data.get("force", False))
    if not force and INSTALL_PROGRESS.get("status") == "running":
        response.status = 409  # Conflict
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "message": "Không thể thoát ứng dụng khi đang thực thi cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ hoàn tất."
        }, ensure_ascii=False)

    res = api_instance.quit_app(force=force)
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/minimize", method="POST")
def api_window_minimize():
    """Minimize the desktop window to taskbar"""
    res = api_instance.minimize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/heartbeat", method=["GET", "POST"])
def api_heartbeat():
    """
    Nhịp sống của giao diện (gọi mỗi 5 giây từ frontend).
    Watchdog ở chế độ Fallback Browser dùng endpoint này để phát hiện cửa sổ Edge/Chrome
    đã bị người dùng đóng -> tự thoát tiến trình (Zero-Leak Clean Exit).
    """
    mark_ui_heartbeat()
    if (request.method == "POST" and SESSION_AUTH_TOKEN
            and request.headers.get("X-App-Auth-Token") == SESSION_AUTH_TOKEN
            and _is_loopback_host(request.headers.get("Host", ""))
            and _is_loopback_origin(request.headers.get("Origin", ""))):
        try:
            from core.config_manager import CURRENT_VERSION
            from core.update_startup import acknowledge_update_startup
            acknowledge_update_startup(CURRENT_VERSION)
        except OSError as error:
            print(f"[Updater] Startup acknowledgement failed: {error}")
    response.content_type = "application/json"
    return json.dumps({"success": True, "server_time": time.time()}, ensure_ascii=False)


@server_app.route("/api/window/minimize_tray", method="POST")
def api_window_minimize_tray():
    """Minimize the desktop window to system tray"""
    res = api_instance.minimize_to_tray()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/restore_tray", method="POST")
def api_window_restore_tray():
    """Restore the desktop window from system tray"""
    if not api_instance.window:
        response.status = 404
        return json.dumps({"success": False, "error": "No window instance"})
    res = api_instance.restore_from_tray()
    response.content_type = "application/json"
    if not res.get("success"):
        response.status = 500
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/close", method="POST")
def api_window_close():
    """
    Nút X thông minh: ẩn xuống Khay Hệ Thống nếu đang theo dõi phiên chơi game,
    ngược lại thoát hẳn ứng dụng (Zero-Leak Clean Exit).
    Hoạt động cả ở chế độ Fallback Browser (khi api_instance.window là None).
    """
    res = api_instance.request_close()
    response.content_type = "application/json"
    if not res.get("success"):
        response.status = 500
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/window/maximize", method="POST")
def api_window_maximize():
    """Toggle maximize / restore the desktop window"""
    res = api_instance.maximize_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag", method="POST")
def api_window_drag():
    """Trigger ultra-smooth native Windows OS window dragging on titlebar mouse down"""
    res = api_instance.drag_window()
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)

@server_app.route("/api/window/drag_stop", method="POST")
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

@server_app.route("/api/app/update", method="POST")
def api_app_update():
    """Tự động tải và cài bản cập nhật mới nhất (In-App Self-Updater), sau đó tự khởi động lại."""
    res = api_instance.apply_app_update()
    if not res.get("success"):
        response.status = 400
    response.content_type = "application/json"
    return json.dumps(res, ensure_ascii=False)


# ==============================================================================
# MENU CÀI ĐẶT TRUNG TÂM (UNIFIED SETTINGS) REST ROUTES
# ==============================================================================

@server_app.route("/api/settings", method=["GET", "POST"])
def api_unified_settings():
    """Đọc hoặc ghi cấu hình hợp nhất 4 tab (General, Scanner, Downloader, Cloud Save)."""
    response.content_type = "application/json"
    if request.method == "POST":
        data = request.json or {}
        res = api_instance.update_settings(data)
        if not res.get("success"):
            response.status = 400
        return json.dumps(res, ensure_ascii=False)
    else:
        res = api_instance.get_settings()
        return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/cache/info", method="GET")
def api_cache_info():
    """Lấy dung lượng bộ nhớ đệm cache."""
    response.content_type = "application/json"
    res = api_instance.get_cache_info()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/cache/clear", method="POST")
def api_cache_clear():
    """Dọn dẹp sạch cache và file tạm."""
    response.content_type = "application/json"
    res = api_instance.clear_cache()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/settings/open_appdata", method="POST")
def api_settings_open_appdata():
    """Mở thư mục APPDATA."""
    response.content_type = "application/json"
    res = api_instance.open_appdata_folder()
    return json.dumps(res, ensure_ascii=False)


@server_app.route("/api/settings/browse_folder", method="POST")
def api_settings_browse_folder():
    """Chọn thư mục quét bổ sung."""
    response.content_type = "application/json"
    res = api_instance.select_custom_library_folder()
    return json.dumps(res, ensure_ascii=False)



def create_http_server(app=None, port_list=None):
    """
    Khởi tạo máy chủ HTTP đa luồng trên 127.0.0.1.
    Thử các cổng cố định 49200-49205 trước, nếu bận thì dùng cổng động (0).
    """
    target_app = app or server_app
    ports = port_list or [49200, 49201, 49202, 49203, 0]
    for try_port in ports:
        try:
            srv = make_server(
                "127.0.0.1",
                try_port,
                target_app,
                server_class=ThreadingWSGIServer,
                handler_class=QuietWSGIRequestHandler
            )
            return srv
        except OSError as e:
            log_startup(f"[!] Cong {try_port} dang ban ({e}), thu cong tiep theo...")
            continue
    return make_server("127.0.0.1", 0, target_app, server_class=ThreadingWSGIServer, handler_class=QuietWSGIRequestHandler)
