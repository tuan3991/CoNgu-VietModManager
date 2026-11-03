# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Main Application Entry Point
-------------------------------------------------------
Khởi tạo PyWebView Desktop Window, Server Bottle đa luồng và liên kết các module:
- core/: Config, Scanner, Downloader, Installer Pipeline, Backup & Rollback, Cloud Save
- api/: Native IPC Bridge (ModManagerAPI) & HTTP REST Routes
- static/: Frontend Single-Page App (HTML, TailwindCSS, Lucide, JS)
"""

import os
import sys
import time
import secrets
import threading
import webview
import ctypes
from datetime import datetime

# Loopback (127.0.0.1/localhost) của WebView2 PHẢI đi thẳng, nhưng KHÔNG được đụng tới proxy/VPN
# của người dùng cho traffic Internet (Steam CDN, GitHub, Google Drive...).
#
# LƯU Ý KỸ THUẬT (theo Chromium net/docs/proxy.md):
#   - Chromium ĐÃ có "implicit bypass rules" cho localhost, *.localhost, [::1], 127.0.0.1/8
#     -> request tới loopback mặc định KHÔNG bao giờ đi qua proxy.
#   - Tuyệt đối KHÔNG dùng `--no-proxy-server`: cờ này vô hiệu hoá toàn bộ proxy/VPN của người dùng
#     bên trong WebView2, làm hỏng việc tải ảnh bìa Steam CDN / GitHub trên máy cần WARP/Proxy.
#   - Tuyệt đối KHÔNG dùng `--proxy-bypass-list=<-loopback>`: token `<-loopback>` là quy tắc TRỪ
#     (subtract) implicit rules, tức nó ÉP 127.0.0.1 đi QUA proxy -> chính là nguyên nhân
#     ERR_CONNECTION_REFUSED. Ở đây dùng danh sách bypass dương (positive) tường minh thay thế.
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--proxy-bypass-list=127.0.0.1;localhost;[::1] "
    "--disable-features=msSmartScreenProtection,msEdgeStartupBoost,RendererCodeIntegrity "
    "--disable-backgrounding-occluded-windows "
    "--disable-renderer-backgrounding "
    "--disable-background-timer-throttling"
)
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

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

from core.config_manager import (
    APP_DIR,
    STATIC_DIR,
    APPDATA_DIR,
    load_user_config,
    sync_remote_catalog,
)
from core.cloud_save import PLAYTIME_MGR, register_exit_hook
from core.system_booster import boost_memory
from core.installer_pipeline import get_pending_transaction, recover_pending_transaction

from api import (
    ModManagerAPI,
    api_instance,
    server_app,
    configure_routes,
    create_http_server,
    log_startup,
)
from api.routes import get_ui_heartbeat_age

SERVER_PORT = 0
HTTP_SERVER = None
SYSTEM_TRAY = None
SYSTEM_TRAY_INIT_PENDING = False
SYSTEM_TRAY_BALLOON_SHOWN = {}  # {once_key: True} - chống spam Balloon thông báo Khay Hệ Thống
_TITLEBAR_ICON_REF = None  # Giữ tham chiếu System.Drawing.Icon để GC không DestroyIcon
APP_MUTEX = None
WAKEUP_EVENT = None
APP_MUTEX_NAME = "Local\\CoNguVietModHubSingleInstance"
WAKEUP_EVENT_NAME = "Local\\CoNguVietModHubWakeupEvent"

# --- Fallback Browser (Edge/Chrome App Mode) Heartbeat Watchdog ---
FALLBACK_HEARTBEAT_TIMEOUT = 15.0    # Quá 15s không nhận ping -> coi như cửa sổ trình duyệt đã đóng
FALLBACK_BROWSER_START_GRACE = 30.0  # Thời gian ân hạn cho lần load trang đầu tiên
FALLBACK_WATCHDOG_TICK = 2.0         # Chu kỳ kiểm tra của watchdog


def apply_titlebar_icon(window, ico_path):
    """Gán icon title bar/taskbar trên đúng UI thread, không chặn WebView2."""
    if not ico_path or not os.path.exists(ico_path):
        return

    def _set_icon():
        global _TITLEBAR_ICON_REF
        try:
            native = getattr(window, "native", None)
            if native is not None:
                try:
                    import clr
                    clr.AddReference("System.Drawing")
                    from System.Drawing import Icon as WinIcon
                    icon = WinIcon(ico_path)
                    native.Icon = icon
                    # Giữ tham chiếu để GC không DestroyIcon khi icon còn đang dùng
                    _TITLEBAR_ICON_REF = icon
                except Exception:
                    pass

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x00000010
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            user32 = ctypes.windll.user32
            user32.GetSystemMetrics.restype = ctypes.c_int
            user32.LoadImageW.restype = ctypes.c_void_p
            user32.LoadImageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.PostMessageW.restype = ctypes.c_bool
            user32.PostMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            user32.FindWindowW.restype = ctypes.c_void_p
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]

            cx_small = user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
            cy_small = user32.GetSystemMetrics(50) or 16  # SM_CYSMICON
            cx_big = user32.GetSystemMetrics(11) or 32     # SM_CXICON
            cy_big = user32.GetSystemMetrics(12) or 32     # SM_CYICON

            hicon_small = user32.LoadImageW(
                None, os.path.abspath(ico_path), IMAGE_ICON, cx_small, cy_small, LR_LOADFROMFILE
            )
            hicon_big = user32.LoadImageW(
                None, os.path.abspath(ico_path), IMAGE_ICON, cx_big, cy_big, LR_LOADFROMFILE
            )

            hwnd = None
            if native is not None and hasattr(native, "Handle"):
                try:
                    hwnd = native.Handle.ToInt64()
                except Exception:
                    hwnd = None

            if not hwnd:
                hwnd = user32.FindWindowW(None, "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro")

            if hwnd:
                # PostMessageW (bất đồng bộ) thay vì SendMessageW để không bao giờ
                # khóa chéo luồng với message pump của WebView2.
                if hicon_small:
                    user32.PostMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                if hicon_big:
                    user32.PostMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        except Exception as e:
            log_startup(f"[TitlebarIcon] Loi gan icon: {e}")

    try:
        native = getattr(window, "native", None)
        if native is not None and hasattr(native, "BeginInvoke"):
            import clr
            from System import Action
            native.BeginInvoke(Action(_set_icon))
        else:
            _set_icon()
    except Exception as e:
        log_startup(f"[TitlebarIcon] Khong dispatch duoc len UI thread: {e}")


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


def setup_system_tray(window, ico_path=None):
    """Thiết lập Khay Hệ Thống (System Tray) chuẩn Windows qua Windows Forms (gắn trực tiếp vào UI thread)."""
    global SYSTEM_TRAY, SYSTEM_TRAY_INIT_PENDING
    if SYSTEM_TRAY is not None or SYSTEM_TRAY_INIT_PENDING:
        return
    SYSTEM_TRAY_INIT_PENDING = True

    def _init():
        global SYSTEM_TRAY, SYSTEM_TRAY_INIT_PENDING
        try:
            import clr
            clr.AddReference('System.Windows.Forms')
            clr.AddReference('System.Drawing')
            from System.Windows.Forms import (
                NotifyIcon, ContextMenuStrip, ToolStripMenuItem,
                ToolStripSeparator, MouseButtons
            )
            from System.Drawing import Icon, SystemIcons

            tray = NotifyIcon()
            if ico_path and os.path.exists(ico_path):
                try:
                    tray.Icon = Icon(ico_path)
                except Exception:
                    tray.Icon = SystemIcons.Application
            else:
                tray.Icon = SystemIcons.Application

            tray.Text = "CỔ NGỮ - Quản Lý Game Việt Hóa Pro"[:63]

            menu = ContextMenuStrip()
            item_open = ToolStripMenuItem("🎮 Mở CỔ NGỮ")
            item_min = ToolStripMenuItem("⏬ Thu nhỏ xuống Taskbar")
            item_exit = ToolStripMenuItem("❌ Thoát hoàn toàn")

            def _on_open_click(sender, args):
                restore_from_tray(window)

            def _on_min_click(sender, args):
                if window:
                    try:
                        restore_from_tray(window)
                        window.minimize()
                    except Exception:
                        pass

            def _on_exit_click(sender, args):
                quit_from_tray()

            item_open.Click += _on_open_click
            item_min.Click += _on_min_click
            item_exit.Click += _on_exit_click

            menu.Items.Add(item_open)
            menu.Items.Add(item_min)
            menu.Items.Add(ToolStripSeparator())
            menu.Items.Add(item_exit)

            tray.ContextMenuStrip = menu

            def _on_tray_mouse_click(sender, e):
                if hasattr(e, 'Button') and e.Button == MouseButtons.Left:
                    restore_from_tray(window)

            def _on_tray_double_click(sender, e):
                restore_from_tray(window)

            tray.MouseClick += _on_tray_mouse_click
            tray.DoubleClick += _on_tray_double_click
            tray.Visible = True

            SYSTEM_TRAY = tray
            log_startup("[SystemTray] Đã khởi tạo biểu tượng Khay Hệ Thống Windows thành công trên UI Thread!")
        except Exception as e:
            log_startup(f"[SystemTray] Không thể khởi tạo System Tray: {e}")
        finally:
            SYSTEM_TRAY_INIT_PENDING = False

    try:
        native = getattr(window, "native", None)
        if native is not None and hasattr(native, "BeginInvoke"):
            import clr
            from System import Action
            native.BeginInvoke(Action(_init))
        elif native is not None and hasattr(native, "Invoke"):
            import clr
            from System import Action
            native.Invoke(Action(_init))
        else:
            _init()
    except Exception as e:
        SYSTEM_TRAY_INIT_PENDING = False
        log_startup(f"[SystemTray] Dispatch error: {e}")


# =============================================================================
# UNIVERSAL DRAG & DROP - Kéo & thả .exe / .lnk / .congu / .congu_save / .congu_theme
# =============================================================================
_DND_STATE = {"handler": None, "registered": False}


def _push_dnd_result(payload: dict, window) -> bool:
    """Đẩy kết quả xử lý kéo-thả lên giao diện (window.handleDroppedFilesResult)."""
    if not window:
        return False
    try:
        import json as _json
        script = (
            "(function(){try{"
            "if(typeof window.handleDroppedFilesResult==='function'){"
            f"window.handleDroppedFilesResult({_json.dumps(payload, ensure_ascii=False)});return true;}}"
            "catch(e){console.warn('[DnD] UI error',e);}return false;})()"
        )
        return bool(window.evaluate_js(script))
    except Exception as e:
        log_startup(f"[DnD] Khong day duoc ket qua len UI: {e}")
        return False


def setup_drag_and_drop(window) -> bool:
    """
    Đăng ký Universal Drag & Drop qua DOM API của pywebview.
    Trên WebView2 (EdgeChromium), pywebview dùng `postMessageWithAdditionalObjects('FilesDropped')`
    để lấy ĐƯỜNG DẪN TUYỆT ĐỐI thật của tệp (khóa `pywebviewFullPath`) — điều mà HTML5 File API
    thông thường không thể cung cấp.
    """
    if not window:
        return False

    def _on_drop(event):
        try:
            files = ((event or {}).get("dataTransfer") or {}).get("files") or []
            paths = []
            for f in files:
                if isinstance(f, dict):
                    fp = f.get("pywebviewFullPath")
                    if fp:
                        paths.append(fp)
            if not paths:
                log_startup("[DnD] Drop event khong kem duong dan tep (che do Fallback Browser?).")
                return
            log_startup(f"[DnD] Nhan {len(paths)} tep keo-tha: {paths}")
            res = api_instance.handle_dropped_files(paths)
            _push_dnd_result(res, window)
        except Exception as e:
            log_startup(f"[DnD] Drop handler error: {e}")

    # Gỡ handler cũ (nếu trang vừa reload) trước khi gắn lại để tránh xử lý trùng
    prev = _DND_STATE.get("handler")
    if prev is not None:
        try:
            window.dom.document.events.drop -= prev
        except Exception:
            pass

    try:
        window.dom.document.events.drop += _on_drop
        _DND_STATE["handler"] = _on_drop
        _DND_STATE["registered"] = True
        log_startup("[DnD] Da dang ky Universal Drag & Drop tren cua so chinh.")
        return True
    except Exception as e:
        log_startup(f"[DnD] Khong dang ky duoc Drag & Drop: {e}")
        return False


def show_tray_balloon(title: str, message: str, timeout_ms: int = 4000, once_key: str = None, icon: str = "Info"):
    """
    Hiển thị thông báo Balloon từ biểu tượng Khay Hệ Thống (NotifyIcon).
    once_key: nếu truyền vào, mỗi nội dung chỉ hiển thị đúng 1 lần trong suốt vòng đời ứng dụng
    (điều khiển bằng dict SYSTEM_TRAY_BALLOON_SHOWN đã khai báo ở đầu module).
    """
    global SYSTEM_TRAY_BALLOON_SHOWN
    if once_key and SYSTEM_TRAY_BALLOON_SHOWN.get(once_key):
        return False
    if not SYSTEM_TRAY:
        return False
    try:
        # ToolTipIcon.None == 0: dùng int thuần để pythonnet tự ép kiểu enum,
        # vẫn hoạt động kể cả khi chưa import được namespace System.Windows.Forms.
        tip_icon = 0
        try:
            from System.Windows.Forms import ToolTipIcon
            tip_icon = {
                "Info": ToolTipIcon.Info,
                "Warning": ToolTipIcon.Warning,
                "Error": ToolTipIcon.Error,
                "None": getattr(ToolTipIcon, "None", 0),
            }.get(icon, ToolTipIcon.Info)
        except Exception:
            tip_icon = 0
        SYSTEM_TRAY.ShowBalloonTip(timeout_ms, title, message, tip_icon)
        if once_key:
            SYSTEM_TRAY_BALLOON_SHOWN[once_key] = True
        return True
    except Exception as e:
        # Thử overload tối giản (một số bản WinForms chỉ nhận timeout)
        try:
            SYSTEM_TRAY.ShowBalloonTip(timeout_ms)
            if once_key:
                SYSTEM_TRAY_BALLOON_SHOWN[once_key] = True
            return True
        except Exception:
            log_startup(f"[SystemTray] Balloon error: {e}")
            return False


def has_active_play_session() -> bool:
    """Có phiên chơi game nào đang được theo dõi (đếm giờ + hook Cloud Save) hay không."""
    try:
        return bool(PLAYTIME_MGR.has_active_session())
    except Exception:
        return False


def hide_window_to_tray(window, notify: bool = True) -> bool:
    """
    Ẩn cửa sổ khỏi Taskbar và đưa xuống Khay Hệ Thống (System Tray).
    Khác hoàn toàn với window.minimize() (chỉ thu nhỏ xuống Taskbar).
    """
    if not window:
        return False
    hidden = {"ok": False}

    def _do_hide():
        try:
            if hasattr(window, 'native') and window.native:
                window.native.ShowInTaskbar = False
                window.native.Visible = False
            else:
                window.hide()
            hidden["ok"] = True
        except Exception as e:
            log_startup(f"[SystemTray] Hide error: {e}")

    try:
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'BeginInvoke'):
            import clr
            from System import Action
            window.native.BeginInvoke(Action(_do_hide))
            hidden["ok"] = True
        elif hasattr(window, 'native') and window.native and hasattr(window.native, 'Invoke'):
            import clr
            from System import Action
            window.native.Invoke(Action(_do_hide))
        else:
            threading.Thread(target=_do_hide, daemon=True).start()
            hidden["ok"] = True
    except Exception as e:
        log_startup(f"[SystemTray] Hide dispatch error: {e}")

    if notify and hidden["ok"]:
        show_tray_balloon(
            "CỔ NGỮ đang chạy thu nhỏ",
            "CỔ NGỮ thu nhỏ để đếm giờ chơi & tự động đóng gói .congu_save, "
            "sao lưu Cloud ngay khi bạn thoát game. Nháy đúp biểu tượng để mở lại.",
            once_key="hide_to_tray_hint",
        )
    return hidden["ok"]


def minimize_to_tray(window, notify: bool = True):
    """Đưa cửa sổ xuống Khay Hệ Thống (System Tray)."""
    try:
        if not window:
            return {"success": False, "error": "No window instance"}
        ok = hide_window_to_tray(window, notify=notify)
        return {"success": bool(ok)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def request_close(window):
    """
    Xử lý thông minh khi người dùng bấm nút X (hoặc Alt+F4):
    - Nếu đang có phiên chơi game hoạt động: ẩn xuống System Tray, GIỮ NGUYÊN tiến trình
      để luồng đếm giờ + hook đóng gói .congu_save và đẩy lên Google Drive vẫn chạy sau khi tắt game.
    - Nếu không có game nào chạy: thoát hẳn theo triết lý "Tắt là tắt hẳn" (Zero-Leak Clean Exit).
    """
    if has_active_play_session():
        ok = hide_window_to_tray(window, notify=True)
        if not ok:
            # Không ẩn được cửa sổ (hiếm gặp) -> trả tín hiệu để frontend đi theo đường thoát hẳn
            return {"success": False, "hidden_to_tray": False, "reason": "hide_failed"}
        return {
            "success": True,
            "hidden_to_tray": True,
            "reason": "active_game_session",
            "message": (
                "CỔ NGỮ đang theo dõi phiên chơi game nên được thu nhỏ xuống Khay Hệ Thống "
                "để đếm giờ và tự động sao lưu Cloud khi bạn thoát game."
            ),
        }
    try:
        PLAYTIME_MGR.flush_all_active()
    except Exception:
        pass
    quit_from_tray()
    return {"success": True, "hidden_to_tray": False, "reason": "clean_exit"}


# =============================================================================
# GAME BOOSTER - Thu nhỏ xuống Khay + Giải phóng RAM (Trim Working Set) khi chơi game
# =============================================================================
BOOSTER_STATE = {
    "active": False,
    "game_id": None,
    "game_name": "",
    "started_at": 0.0,
    "hidden": False,
    "trim": None,
}
_BOOSTER_HOOK = {"registered": False}


def _push_session_summary(payload: dict, window) -> bool:
    """Gọi hàm JS showSessionSummary(payload) trong giao diện để hiện bảng tổng kết phiên chơi."""
    if not window:
        return False
    try:
        import json as _json
        js_payload = _json.dumps(payload, ensure_ascii=False)
        script = (
            "(function(){try{"
            "if (typeof window.showSessionSummary === 'function'){"
            f"window.showSessionSummary({js_payload});return true;}}"
            "catch(e){console.warn('[Booster] showSessionSummary error',e);}return false;})()"
        )
        return bool(window.evaluate_js(script))
    except Exception as e:
        log_startup(f"[GameBooster] Khong day duoc bang tong ket len UI: {e}")
        return False


def _booster_on_game_exit(game_id: str, game_dir: str):
    """
    Post-Exit Hook (chạy SAU khi Vault đã đóng gói .congu_save và Cloud Sync đã kích hoạt):
    - Khôi phục cửa sổ CỔ NGỮ từ System Tray.
    - Hiển thị bảng tổng kết phiên chơi + trạng thái đẩy save lên Google Drive.
    """
    if not BOOSTER_STATE.get("active") or BOOSTER_STATE.get("game_id") != game_id:
        return  # Phiên chơi không do Game Booster khởi tạo

    duration_sec = max(0, int(time.time() - float(BOOSTER_STATE.get("started_at") or time.time())))
    trim = BOOSTER_STATE.get("trim") or {}
    hidden = bool(BOOSTER_STATE.get("hidden"))
    game_name = BOOSTER_STATE.get("game_name") or game_id

    # Reset sớm để tránh hook chạy lặp
    BOOSTER_STATE.update({"active": False, "game_id": None, "trim": None, "hidden": False})

    cloud_msg = "Đã đóng gói .congu_save"
    try:
        cfg = load_user_config()
        cloud_cfg = cfg.get("cloud_save", {}) or {}
        if not cloud_cfg.get("auto_sync_on_exit", True):
            cloud_msg = "Đã đóng gói .congu_save (tự động sync đang tắt)"
        else:
            try:
                from core.cloud_save import CLOUD_SYNC_MGR
                if CLOUD_SYNC_MGR and CLOUD_SYNC_MGR.is_connected():
                    cloud_msg = "Đang tải save lên Google Drive..."
                else:
                    cloud_msg = "Đã đóng gói .congu_save (chưa kết nối Google Drive)"
            except Exception:
                cloud_msg = "Đã đóng gói .congu_save"
    except Exception:
        pass

    total_played = ""
    try:
        total_played = PLAYTIME_MGR.get_game_stats(game_id, game_dir).get("formatted_time", "")
    except Exception:
        pass

    def _deliver():
        # Chờ Cloud Sync kịp khởi động & cửa sổ kịp render lại
        time.sleep(1.0)
        w = getattr(api_instance, "window", None)
        if w and hidden:
            restore_from_tray(w)
            time.sleep(0.4)
        _push_session_summary({
            "game_id": game_id,
            "game_name": game_name,
            "duration_sec": duration_sec,
            "duration_text": _format_duration(duration_sec),
            "total_played": total_played,
            "cloud_status": cloud_msg,
            "freed_mb": trim.get("freed_mb", 0),
            "trimmed_processes": trim.get("trimmed", 0),
        }, w)

    threading.Thread(target=_deliver, daemon=True).start()


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} giờ {m} phút"
    if m:
        return f"{m} phút {s} giây"
    return f"{s} giây"


def _register_booster_exit_hook():
    if _BOOSTER_HOOK["registered"]:
        return
    try:
        register_exit_hook(_booster_on_game_exit)
        _BOOSTER_HOOK["registered"] = True
        log_startup("[GameBooster] Da dang ky Post-Exit Hook (khoi phuc cua so + tong ket phien choi).")
    except Exception as e:
        log_startup(f"[GameBooster] Khong dang ky duoc Post-Exit Hook: {e}")


def enter_game_booster_mode(window, game_id: str, game_name: str = ""):
    """
    Kích hoạt Game Booster ngay sau khi game khởi chạy thành công:
    1. Ẩn cửa sổ CỔ NGỮ xuống Khay Hệ Thống (nhường GPU/foreground cho game).
    2. Trim Working Set của CỔ NGỮ + toàn bộ tiến trình WebView2 con (~200 MB -> ~10 MB).
    3. Đăng ký Post-Exit Hook để tự bật lại cửa sổ + hiện bảng tổng kết khi thoát game.
    """
    BOOSTER_STATE.update({
        "active": True,
        "game_id": game_id,
        "game_name": game_name or game_id,
        "started_at": time.time(),
        "hidden": False,
        "trim": None,
    })
    _register_booster_exit_hook()

    hidden = False
    try:
        if window:
            hidden = hide_window_to_tray(window, notify=False)
    except Exception as e:
        log_startup(f"[GameBooster] An cua so that bai: {e}")
    BOOSTER_STATE["hidden"] = hidden

    def _trim_worker():
        # Chờ UI chuyển hẳn sang background (Chromium throttle) rồi mới trim -> hiệu quả cao nhất
        time.sleep(1.2)
        try:
            res = boost_memory()
            BOOSTER_STATE["trim"] = res
            log_startup(
                f"[GameBooster] Da giai phong {res.get('freed_mb', 0)} MB RAM "
                f"({res.get('before_mb', 0)} MB -> {res.get('after_mb', 0)} MB, "
                f"{res.get('trimmed', 0)}/{res.get('processes', 0)} tien trinh)."
            )
            if hidden:
                show_tray_balloon(
                    "🎮 Game Booster đang bật",
                    f"Đã thu nhỏ CỔ NGỮ và giải phóng {res.get('freed_mb', 0)} MB RAM cho game. "
                    f"Cửa sổ sẽ tự mở lại khi bạn thoát game.",
                    timeout_ms=4000,
                )
        except Exception as e:
            log_startup(f"[GameBooster] Trim RAM error: {e}")

    threading.Thread(target=_trim_worker, daemon=True).start()
    return {"success": True, "hidden_to_tray": hidden, "trim_pending": True}


# =============================================================================
# QUICK-SAVE CHECKPOINT - Phím tắt toàn cục Ctrl+F5 (lưu) / Ctrl+F9 (hoàn nguyên)
# Chỉ đăng ký khi thật sự có phiên chơi game đang chạy (không chiếm phím của app khác).
# =============================================================================
_HOTKEY = {
    "thread": None,
    "save_id": 0xB511,
    "restore_id": 0xB512,
    "active": False,
}


def _play_ping(ok: bool = True) -> None:
    """Tiếng 'Tinh!' nhẹ báo hiệu đã lưu / hoàn nguyên checkpoint (không chặn luồng)."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        if ok:
            winsound.Beep(1250, 70)
            winsound.Beep(1700, 90)
        else:
            winsound.Beep(520, 160)
    except Exception:
        pass


def _push_toast(message: str, kind: str = "info") -> bool:
    """Hiển thị toast trong giao diện (nếu đang mở)."""
    w = getattr(api_instance, "window", None)
    if not w:
        return False
    try:
        import json as _json
        script = (
            "(function(){try{"
            "if(typeof window.showToast==='function'){"
            f"window.showToast({_json.dumps(message, ensure_ascii=False)},{_json.dumps(kind)});return true;}}"
            "catch(e){}return false;})()"
        )
        return bool(w.evaluate_js(script))
    except Exception:
        return False


def _get_active_game_context():
    """Lấy (game_config, game_root) của phiên chơi đang hoạt động (nếu có)."""
    try:
        ids = PLAYTIME_MGR.get_active_session_ids()
    except Exception:
        ids = []
    if not ids:
        return None, ""
    game_id = ids[0]
    game_root = ""
    try:
        cfg = load_user_config()
        game_root = cfg.get(f"{game_id}_path", "") or ""
    except Exception:
        pass
    game = None
    try:
        for g in api_instance.get_games():
            if g.get("id") == game_id:
                game = g
                break
    except Exception:
        pass
    if game is None:
        game = {"id": game_id, "title": game_id, "vietnamese_title": game_id}
    return game, game_root


def quick_checkpoint_save():
    """Ctrl+F5: nén nóng save hiện tại thành 1 Quick Checkpoint."""
    game, game_root = _get_active_game_context()
    if not game:
        _play_ping(False)
        _push_toast("Chưa có game nào đang chạy — Quick Checkpoint chỉ hoạt động trong lúc chơi.", "error")
        return {"success": False, "error": "no_active_game"}

    try:
        from core.quick_checkpoint import save_checkpoint
        from core.cloud_save import get_vault_instance
        res = save_checkpoint(get_vault_instance(), game, game_root, APPDATA_DIR)
    except Exception as e:
        res = {"success": False, "error": str(e)}

    if res.get("success"):
        _play_ping(True)
        msg = (
            f"💾 Quick Checkpoint: {res.get('files', 0)} tệp · "
            f"{round(res.get('size_bytes', 0) / 1024, 1)} KB · {res.get('duration_ms', 0)} ms"
        )
        log_startup(f"[QuickSave] {msg}")
        _push_toast(msg, "success")
        # Cửa sổ có thể đang ẩn xuống Khay (Game Booster) -> báo thêm bằng Balloon
        show_tray_balloon("💾 Quick Checkpoint", msg, timeout_ms=2500)
    else:
        _play_ping(False)
        log_startup(f"[QuickSave] That bai: {res.get('error')}")
        _push_toast(f"Quick Checkpoint thất bại: {res.get('error')}", "error")
    return res


def quick_checkpoint_restore():
    """Ctrl+F9: hoàn nguyên Quick Checkpoint mới nhất về đúng thư mục save."""
    game, game_root = _get_active_game_context()
    if not game:
        _play_ping(False)
        _push_toast("Chưa có game nào đang chạy — hãy mở game rồi thoát ra menu chính trước khi hoàn nguyên.", "error")
        return {"success": False, "error": "no_active_game"}

    try:
        from core.quick_checkpoint import restore_checkpoint
        from core.cloud_save import get_vault_instance
        res = restore_checkpoint(get_vault_instance(), game, game_root, APPDATA_DIR)
    except Exception as e:
        res = {"success": False, "error": str(e)}

    if res.get("success"):
        _play_ping(True)
        msg = (
            f"⏪ Đã hoàn nguyên {res.get('restored_files', 0)} tệp save "
            f"(checkpoint {res.get('created_at_text', '')}) · {res.get('duration_ms', 0)} ms"
        )
        log_startup(f"[QuickSave] {msg}")
        _push_toast(msg, "success")
        # Cửa sổ có thể đang ẩn xuống Khay (Game Booster) -> báo thêm bằng Balloon
        show_tray_balloon("⏪ Hoàn nguyên Save", msg, timeout_ms=2500)
    else:
        _play_ping(False)
        log_startup(f"[QuickSave] Restore that bai: {res.get('error')}")
        _push_toast(f"Hoàn nguyên thất bại: {res.get('error')}", "error")
    return res


def start_quick_checkpoint_hotkeys():
    """
    Khởi động luồng Win32 message-pump đăng ký hotkey.
    RegisterHotKey + GetMessageW BẮT BUỘC chạy trên cùng một thread.
    """
    if sys.platform != "win32":
        return False
    th = _HOTKEY.get("thread")
    if th is not None and th.is_alive():
        return True
    t = threading.Thread(target=_hotkey_loop, name="QuickCheckpointHotkeys", daemon=True)
    _HOTKEY["thread"] = t
    t.start()
    return True


def _hotkey_loop():
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    WM_TIMER = 0x0113
    VK_F5 = 0x74
    VK_F9 = 0x78
    POLL_MS = 3000
    save_id = _HOTKEY["save_id"]
    restore_id = _HOTKEY["restore_id"]

    try:
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
    except Exception:
        pass

    # Timer định kỳ để kiểm tra phiên chơi (WM_TIMER phát về đúng thread này)
    user32.SetTimer(None, 1, POLL_MS, None)
    log_startup("[QuickSave] Hotkey listener san sang (Ctrl+F5 luu / Ctrl+F9 hoan nguyen khi co game chay).")

    msg = wintypes.MSG()
    while True:
        try:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break

            if msg.message == WM_TIMER:
                want = has_active_play_session()
                if want and not _HOTKEY["active"]:
                    ok_save = user32.RegisterHotKey(None, save_id, MOD_CONTROL | MOD_NOREPEAT, VK_F5)
                    ok_restore = user32.RegisterHotKey(None, restore_id, MOD_CONTROL | MOD_NOREPEAT, VK_F9)
                    _HOTKEY["active"] = bool(ok_save) or bool(ok_restore)
                    if _HOTKEY["active"]:
                        log_startup("[QuickSave] Da dang ky Ctrl+F5 / Ctrl+F9 (dang co game chay).")
                    else:
                        log_startup("[QuickSave] Khong dang ky duoc hotkey (co the bi app khac chiem).")
                elif not want and _HOTKEY["active"]:
                    try:
                        user32.UnregisterHotKey(None, save_id)
                        user32.UnregisterHotKey(None, restore_id)
                    except Exception:
                        pass
                    _HOTKEY["active"] = False
                    log_startup("[QuickSave] Da nha phim tat (khong con game nao chay).")

            elif msg.message == WM_HOTKEY:
                hid = int(msg.wParam)
                if hid == save_id:
                    threading.Thread(target=quick_checkpoint_save, daemon=True).start()
                elif hid == restore_id:
                    threading.Thread(target=quick_checkpoint_restore, daemon=True).start()
        except Exception as e:
            log_startup(f"[QuickSave] Hotkey loop error: {e}")
            time.sleep(1.0)


def restore_from_tray(window):
    """Khôi phục và hiển thị lại cửa sổ CỔ NGỮ lên trên cùng màn hình."""
    def _do_restore():
        try:
            if hasattr(window, 'native') and window.native:
                from System.Windows.Forms import FormWindowState
                window.native.ShowInTaskbar = True
                window.native.Visible = True
                window.native.Show()
                window.native.WindowState = FormWindowState.Normal
                window.native.BringToFront()
                window.native.Activate()
                hwnd = window.native.Handle.ToInt64()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            else:
                window.show()
                window.restore()
        except Exception as e:
            log_startup(f"[SystemTray] Restore error: {e}")

    try:
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'BeginInvoke'):
            import clr
            from System import Action
            window.native.BeginInvoke(Action(_do_restore))
        elif hasattr(window, 'native') and window.native and hasattr(window.native, 'Invoke'):
            import clr
            from System import Action
            window.native.Invoke(Action(_do_restore))
        else:
            threading.Thread(target=_do_restore, daemon=True).start()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def quit_from_tray():
    """Thoát hoàn toàn ứng dụng từ khay hệ thống (Zero-Leak Clean Exit)."""
    global SYSTEM_TRAY, APP_MUTEX, WAKEUP_EVENT
    try:
        if SYSTEM_TRAY:
            SYSTEM_TRAY.Visible = False
            SYSTEM_TRAY.Dispose()
            SYSTEM_TRAY = None
    except Exception:
        pass
    try:
        if WAKEUP_EVENT and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(WAKEUP_EVENT)
            WAKEUP_EVENT = None
    except Exception:
        pass
    try:
        if APP_MUTEX and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(APP_MUTEX)
            APP_MUTEX = None
    except Exception:
        pass
    try:
        PLAYTIME_MGR.flush_all_active()
    except Exception:
        pass
    os._exit(0)


def start_wakeup_listener(wakeup_event, window_getter):
    """
    Single-Instance Wakeup Listener:
    Lắng nghe tín hiệu Windows Named Event từ tiến trình thứ hai để khôi phục
    và đưa cửa sổ CỔ NGỮ lên trên cùng màn hình ngay lập tức (0ms, độc lập cổng mạng & token).
    """
    if not wakeup_event or sys.platform != "win32":
        return

    def _listener():
        INFINITE = 0xFFFFFFFF
        WAIT_OBJECT_0 = 0
        while True:
            try:
                res = ctypes.windll.kernel32.WaitForSingleObject(wakeup_event, INFINITE)
                if res == WAIT_OBJECT_0:
                    log_startup("[Wakeup] Nhan tin hieu danh thuc tu tien trinh thu hai qua Named Event.")
                    w = window_getter()
                    if w:
                        restore_from_tray(w)
                    else:
                        title = "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro"
                        hwnd = ctypes.windll.user32.FindWindowW(None, title)
                        if hwnd:
                            ctypes.windll.user32.ShowWindow(hwnd, 9)
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception as e:
                log_startup(f"[Wakeup] Listener exception: {e}")
            time.sleep(0.05)

    t_wakeup = threading.Thread(target=_listener, daemon=True)
    t_wakeup.start()


def wait_for_local_server(port: int, timeout_sec: float = 5.0) -> bool:
    """Kiểm tra trực tiếp qua Raw Socket xem 127.0.0.1:port đã thực sự mở cổng lắng nghe chưa."""
    import socket
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def launch_app_window_fallback(url):
    """
    Fallback Desktop Window Mode:
    Khởi chạy Edge/Chrome ở chế độ App Mode với thư mục profile riêng biệt.
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
            app_data_edge = os.path.join(APPDATA_DIR, "congu_edge_profile")
            os.makedirs(app_data_edge, exist_ok=True)
            cmd = [
                exe,
                f"--app={url}",
                f"--user-data-dir={app_data_edge}",
                "--window-size=1340,900",
                "--no-first-run",
                "--no-default-browser-check",
                # Giữ nguyên proxy/VPN của người dùng cho traffic Internet,
                # chỉ bypass tường minh cho loopback (KHÔNG dùng --no-proxy-server).
                "--proxy-bypass-list=127.0.0.1;localhost;[::1]",
                "--disable-features=msEdgeStartupBoost,msSmartScreenProtection",
                "--disable-background-mode",
                "--disable-extensions",
                "--new-window"
            ]
            try:
                log_startup(f"Khoi chay cua so Standalone qua: {exe}")
                t0 = time.time()
                proc = subprocess.Popen(cmd)
                proc.wait()
                elapsed = time.time() - t0
                if elapsed > 8.0:
                    log_startup(f"Cua so ung dung da dong sau {elapsed:.1f}s. Thoat tien trinh.")
                    try:
                        PLAYTIME_MGR.flush_all_active()
                    except Exception:
                        pass
                    os._exit(0)
                else:
                    log_startup(
                        f"Trinh duyet handoff nhanh ({elapsed:.1f}s). "
                        f"Duy tri may chu 127.0.0.1 de phuc vu giao dien!"
                    )
                    return True
            except Exception as e:
                log_startup(f"[!] Loi khoi chay trinh duyet {exe}: {e}")

    log_startup("Khong tim thay Edge/Chrome doc lap. Dang mo tren trinh duyet mac dinh...")
    import webbrowser
    webbrowser.open(url)
    return True


def run_fallback_browser_watchdog():
    """
    Watchdog cho chế độ Fallback Browser (Edge/Chrome App Mode).

    Vì sao cần: nếu máy đã có Edge/Chrome chạy ngầm, tiến trình được spawn sẽ handoff sang
    instance có sẵn và `proc.wait()` trả về trong < 1 giây, nên không thể dùng thời gian sống
    của tiến trình con để biết cửa sổ còn mở hay không.

    Cơ chế: giao diện gửi POST /api/heartbeat mỗi 5 giây. Nếu quá FALLBACK_HEARTBEAT_TIMEOUT (15s)
    không nhận được ping VÀ không có phiên chơi game nào đang hoạt động trong PLAYTIME_MGR,
    tiến trình tự gọi os._exit(0) -> đúng triết lý "Tắt là tắt hẳn" (Zero-Leak Clean Exit).

    Nếu vẫn còn game đang chơi (người dùng đóng cửa sổ để chơi full-screen), watchdog tiếp tục
    giữ tiến trình sống để đếm giờ và chạy hook đóng gói .congu_save + Cloud Save sau khi tắt game;
    khi phiên chơi kết thúc và heartbeat vẫn thiếu, tiến trình sẽ tự thoát ở nhịp kiểm tra kế tiếp.
    """
    started_at = time.time()
    # Reset mốc heartbeat để không bị dính dữ liệu cũ của phiên trước
    try:
        from api.routes import HEARTBEAT_STATE
        HEARTBEAT_STATE["last"] = 0.0
    except Exception:
        pass

    log_startup(
        f"[Fallback] Watchdog Heartbeat bat dau (timeout {FALLBACK_HEARTBEAT_TIMEOUT:.0f}s, "
        f"an han khoi dong {FALLBACK_BROWSER_START_GRACE:.0f}s)."
    )

    warned = {"lost": False, "holding": False}

    while True:
        try:
            time.sleep(FALLBACK_WATCHDOG_TICK)
            age = get_ui_heartbeat_age()

            # Giai đoạn ân hạn: trang chưa kịp load / chưa ping lần nào
            if age == float("inf") and (time.time() - started_at) < FALLBACK_BROWSER_START_GRACE:
                continue

            heartbeat_alive = age != float("inf") and age <= FALLBACK_HEARTBEAT_TIMEOUT
            if heartbeat_alive:
                warned["lost"] = False
                warned["holding"] = False
                continue  # Cửa sổ trình duyệt vẫn đang sống

            if not warned["lost"]:
                warned["lost"] = True
                if age == float("inf"):
                    log_startup(
                        "[Fallback] Khong nhan duoc Heartbeat nao sau thoi gian an han -> "
                        "cua so trinh duyet khong mo duoc."
                    )
                else:
                    log_startup(
                        f"[Fallback] Mat Heartbeat {age:.0f}s (> {FALLBACK_HEARTBEAT_TIMEOUT:.0f}s)."
                    )

            # Mất heartbeat: chỉ thoát khi không còn phiên chơi game nào cần bảo toàn
            if has_active_play_session():
                if not warned["holding"]:
                    warned["holding"] = True
                    log_startup(
                        "[Fallback] Cua so da dong nhung van co game dang choi -> "
                        "giu tien trinh de dem gio & Cloud Save."
                    )
                continue

            log_startup("[Fallback] Cua so trinh duyet da dong va khong con game dang chay -> Thoat tien trinh.")
            try:
                PLAYTIME_MGR.flush_all_active()
            except Exception:
                pass
            try:
                if SYSTEM_TRAY:
                    SYSTEM_TRAY.Visible = False
                    SYSTEM_TRAY.Dispose()
            except Exception:
                pass
            os._exit(0)
        except Exception as e:
            log_startup(f"[Fallback] Watchdog error: {e}")
            time.sleep(1.0)


def main():
    global SERVER_PORT, HTTP_SERVER, APP_MUTEX, WAKEUP_EVENT

    # Gán AppID độc lập cho Windows Taskbar / Startbar
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("congu.vietmodhub.launcher.v2")
        except Exception:
            pass

    # 0. Single-Instance Protection: Mutex kiểm tra ứng dụng trùng lặp & Windows Named Event Wakeup
    if sys.platform == "win32" and "--server" not in sys.argv and "--no-gui" not in sys.argv:
        try:
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateEventW.restype = wintypes.HANDLE
            kernel32.OpenEventW.restype = wintypes.HANDLE
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.SetEvent.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

            ERROR_ALREADY_EXISTS = 183
            APP_MUTEX = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                log_startup("[*] Phat hien Co Ngu da dang chay (Mutex ton tai). Dang danh thuc cua so...")
                try:
                    # Cho phép tiến trình chính giành quyền chiếm Active Foreground Window
                    ctypes.windll.user32.AllowSetForegroundWindow(-1)
                except Exception:
                    pass

                # 1. Kích hoạt Windows Named Event để đánh thức tiến trình chính (0ms, độc lập cổng mạng & token)
                EVENT_MODIFY_STATE = 0x0002
                h_event = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, WAKEUP_EVENT_NAME)
                if h_event:
                    kernel32.SetEvent(h_event)
                    kernel32.CloseHandle(h_event)
                    log_startup("[*] Da gui tin hieu SetEvent toi Named Event thanh cong.")
                else:
                    # 2. Fallback HWND nếu Named Event chưa kịp khởi tạo
                    hwnd = ctypes.windll.user32.FindWindowW(None, "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro")
                    if hwnd:
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)

                log_startup("[*] Da gui lenh danh thuc. Thoat tien trinh khoi tao thu hai.")
                sys.exit(0)
            else:
                # Tiến trình chính: Khởi tạo Auto-Reset Named Event và bắt đầu luồng lắng nghe đánh thức
                WAKEUP_EVENT = kernel32.CreateEventW(None, False, False, WAKEUP_EVENT_NAME)
                start_wakeup_listener(WAKEUP_EVENT, lambda: getattr(api_instance, "window", None))
        except Exception as e:
            log_startup(f"[SingleInstance] Mutex/Event check error: {e}")

    # 1. Phát hiện transaction install bị gián đoạn ở lần chạy trước.
    # Chỉ cảnh báo; journal hiện chưa đủ thông tin để tự rollback an toàn.
    try:
        recovery_cfg = load_user_config()
        for key, game_path in recovery_cfg.items():
            if not key.endswith("_path") or not game_path or not os.path.isdir(game_path):
                continue
            game_id = key[:-5]
            if get_pending_transaction(game_id):
                recovery = recover_pending_transaction(game_id, game_path)
                if recovery.get("success"):
                    log_startup(f"[Recovery] Da xu ly transaction gian doan cua {game_id}.")
                else:
                    log_startup(f"[Recovery Warning] {game_id}: {recovery.get('message', 'khong the khoi phuc tu dong')}")
    except Exception as recovery_error:
        log_startup(f"[Recovery Warning] Kiem tra transaction gian doan that bai: {recovery_error}")

    # 2. Khởi tạo cấu hình phiên & HTTP Server
    SESSION_AUTH_TOKEN = secrets.token_hex(16)
    configure_routes(api=api_instance, session_token=SESSION_AUTH_TOKEN)

    HTTP_SERVER = create_http_server(server_app)
    SERVER_PORT = HTTP_SERVER.server_address[1]
    log_startup(f"[*] Co Ngu Core Engine initialized on 127.0.0.1:{SERVER_PORT} (Token Protected)")

    t = threading.Thread(target=HTTP_SERVER.serve_forever, daemon=True)
    t.start()

    # 2. Kiểm tra Socket 127.0.0.1 đã sẵn sàng trước khi mở WebView
    server_ready = wait_for_local_server(SERVER_PORT, timeout_sec=5.0)
    if server_ready:
        log_startup(f"[OK] May chu HTTP tren 127.0.0.1:{SERVER_PORT} da san sang lang nghe.")
    else:
        log_startup(f"[!] Canh bao: Socket 127.0.0.1:{SERVER_PORT} phan hoi cham.")

    # 3. Đồng bộ danh mục ngầm
    def _bg_cloud_sync():
        time.sleep(2.5)
        sync_remote_catalog(force=False)
    threading.Thread(target=_bg_cloud_sync, daemon=True).start()

    url = f"http://127.0.0.1:{SERVER_PORT}"
    icon_path = get_app_icon_path()

    if "--server" in sys.argv or "--no-gui" in sys.argv:
        log_startup(f"[*] Che do Server Headless kich hoat tren {url}. Dang phuc vu yeu cau...")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        return

    # 3.5. Quick-Save Checkpoint hotkeys (Ctrl+F5 / Ctrl+F9) - chỉ kích hoạt khi có game chạy
    start_quick_checkpoint_hotkeys()

    # 4. Khởi chạy giao diện PyWebView Native Desktop
    user_closed_window = {"closed": False}
    webview_started_at = time.time()

    try:
        window = webview.create_window(
            title="CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro",
            url=url,
            js_api=api_instance,
            width=1340,
            height=900,
            min_size=(1020, 680),
            frameless=True,
            # easy_drag=False: Không biến toàn bộ diện tích cửa sổ thành vùng kéo.
            # Việc di chuyển cửa sổ do hệ thống native drag riêng (ui_render.js -> drag_window,
            # tracking SetWindowPos 200 Hz) đảm nhiệm, chỉ kích hoạt từ thanh tiêu đề <header>.
            # Nhờ đó thanh trượt (Theme Builder), bôi đen văn bản và kéo thả file không bị kẹt.
            easy_drag=False,
            background_color="#0b0f19"
        )
        # pywebview inject JS API bằng cách duyệt đệ quy mọi attribute của js_api.
        # Window.native là WinForms Form khổng lồ; nếu để pywebview introspect nó,
        # quá trình inject có thể treo và sự kiện loaded không bao giờ bắn.
        # Đánh dấu _serializable=False để pywebview bỏ qua đúng attribute này.
        window._serializable = False
        api_instance.window = window

        def on_loaded():
            """Chỉ chạm vào DOM/native sau khi WebView2 đã nạp xong index.html."""
            log_startup("[WebView2] loaded -> gan icon/tray/DnD.")
            apply_titlebar_icon(window, icon_path)
            setup_system_tray(window, icon_path)
            setup_drag_and_drop(window)
            if server_ready:
                try:
                    from core.config_manager import CURRENT_VERSION
                    from core.update_startup import acknowledge_update_startup
                    acknowledge_update_startup(CURRENT_VERSION)
                except Exception as error:
                    log_startup(f"[Updater] Startup acknowledgement failed: {error}")

        def on_shown(w, ico):
            log_startup("[WebView2] on_shown -> bat dau watchdog render.")

            # Watchdog chống màn hình đen: nếu WebView2 không hoàn tất load trong 2.5s,
            # tự reload tối đa 3 lần thay vì bắt người dùng tắt/mở lại app.
            def _webview_render_watchdog():
                for attempt in range(1, 4):
                    if w.events.loaded.wait(2.5):
                        log_startup("[WebView2 Watchdog] Trang da load xong.")
                        return
                    log_startup(
                        f"[WebView2 Watchdog] Chua load sau {attempt * 2.5:.1f}s "
                        f"-> tu dong reload (lan {attempt})..."
                    )
                    try:
                        w.load_url(url)
                    except Exception as ex:
                        log_startup(f"[WebView2 Watchdog] Reload error: {ex}")
                        return
                log_startup("[WebView2 Watchdog] Da reload 3 lan nhung trang van chua load.")

            threading.Thread(target=_webview_render_watchdog, daemon=True).start()

        def on_closed():
            global SYSTEM_TRAY, APP_MUTEX, WAKEUP_EVENT
            try:
                if SYSTEM_TRAY:
                    SYSTEM_TRAY.Visible = False
                    SYSTEM_TRAY.Dispose()
                    SYSTEM_TRAY = None
            except Exception:
                pass
            try:
                if WAKEUP_EVENT and sys.platform == "win32":
                    ctypes.windll.kernel32.CloseHandle(WAKEUP_EVENT)
                    WAKEUP_EVENT = None
            except Exception:
                pass
            try:
                if APP_MUTEX and sys.platform == "win32":
                    ctypes.windll.kernel32.CloseHandle(APP_MUTEX)
                    APP_MUTEX = None
            except Exception:
                pass
            if time.time() - webview_started_at > 3.0:
                user_closed_window["closed"] = True
                try:
                    PLAYTIME_MGR.flush_all_active()
                except Exception:
                    pass
                os._exit(0)

        def on_closing():
            """
            Chặn thao tác đóng cửa sổ (nút X hệ thống / Alt+F4) khi CỔ NGỮ đang theo dõi
            một phiên chơi game: thu nhỏ xuống Khay Hệ Thống thay vì để os._exit(0) cắt đứt
            luồng đếm giờ và hook đóng gói .congu_save + đẩy Google Drive sau khi tắt game.
            """
            if has_active_play_session():
                log_startup(
                    "[Close] Phat hien phien choi game dang hoat dong -> thu nho xuong Khay He Thong "
                    "de bao toan luong dem gio & hook Cloud Save."
                )
                threading.Thread(
                    target=lambda: hide_window_to_tray(window, notify=True),
                    daemon=True
                ).start()
                return False  # Hủy thao tác đóng cửa sổ
            return True

        window.events.closed += on_closed
        if hasattr(window.events, "closing"):
            window.events.closing += on_closing
        if hasattr(window.events, "loaded"):
            # on_loaded gắn icon/tray/DnD sau khi DOM sẵn sàng; tự gắn lại mỗi lần reload.
            window.events.loaded += on_loaded

        webview_storage = os.path.join(APPDATA_DIR, "webview2_profile")
        os.makedirs(webview_storage, exist_ok=True)
        webview.start(
            func=on_shown,
            args=(window, icon_path),
            debug=False,
            icon=icon_path if icon_path else None,
            private_mode=False,
            storage_path=webview_storage,
        )

        if time.time() - webview_started_at < 3.0 and not user_closed_window["closed"]:
            raise RuntimeError("WebView2 exited prematurely (< 3s) on target PC")

        try:
            PLAYTIME_MGR.flush_all_active()
        except Exception:
            pass
        os._exit(0)

    except Exception as e:
        log_startup(f"[!] PyWebView fallback triggered ({e}). Launching Standalone Desktop Window mode...")
        launch_app_window_fallback(url)
        # Giữ tiến trình sống song song với cửa sổ Edge/Chrome và tự thoát khi cửa sổ đó bị đóng
        # (Zero-Leak Clean Exit), trừ khi vẫn còn phiên chơi game cần đếm giờ / Cloud Save.
        run_fallback_browser_watchdog()


if __name__ == "__main__":
    main()
