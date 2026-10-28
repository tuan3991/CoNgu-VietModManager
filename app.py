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

# Force bypass Windows system proxy/VPN for local loopback (fixes ERR_CONNECTION_REFUSED on 127.0.0.1)
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--no-proxy-server --proxy-bypass-list=<-loopback> --disable-features=msSmartScreenProtection"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

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
    sync_remote_catalog,
)
from core.cloud_save import PLAYTIME_MGR

from api import (
    ModManagerAPI,
    api_instance,
    server_app,
    configure_routes,
    create_http_server,
    log_startup,
)

SERVER_PORT = 0
HTTP_SERVER = None
SYSTEM_TRAY = None
SYSTEM_TRAY_BALLOON_SHOWN = False


def apply_titlebar_icon(window, ico_path):
    """Ensure the native Windows title bar and taskbar icon is set to the CỔ NGỮ icon"""
    time.sleep(0.3)
    if not ico_path or not os.path.exists(ico_path):
        return
    try:
        # 1. Direct WinForms Form Icon assignment
        if hasattr(window, 'native') and window.native:
            try:
                import clr
                clr.AddReference('System.Drawing')
                from System.Drawing import Icon
                window.native.Icon = Icon(ico_path)
            except Exception:
                pass

        # 2. Native Win32 WM_SETICON for Title Bar and Taskbar / Startbar
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        user32 = ctypes.windll.user32
        cx_small = user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
        cy_small = user32.GetSystemMetrics(50) or 16  # SM_CYSMICON
        cx_big = user32.GetSystemMetrics(11) or 32     # SM_CXICON
        cy_big = user32.GetSystemMetrics(12) or 32     # SM_CYICON

        hicon_small = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, cx_small, cy_small, LR_LOADFROMFILE)
        hicon_big = user32.LoadImageW(None, os.path.abspath(ico_path), IMAGE_ICON, cx_big, cy_big, LR_LOADFROMFILE)

        hwnd = None
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'Handle'):
            try:
                hwnd = window.native.Handle.ToInt64()
            except Exception:
                hwnd = None

        if not hwnd:
            title = "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro"
            hwnd = user32.FindWindowW(None, title)

        if hwnd:
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception as e:
        print(f"Error applying titlebar icon: {e}")


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
    global SYSTEM_TRAY
    if SYSTEM_TRAY is not None:
        return

    def _init():
        global SYSTEM_TRAY
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

    try:
        if hasattr(window, 'native') and window.native and hasattr(window.native, 'Invoke'):
            import clr
            from System import Action
            window.native.Invoke(Action(_init))
        else:
            _init()
    except Exception as e:
        log_startup(f"[SystemTray] Invoke error: {e}")


def minimize_to_tray(window):
    """Thu nhỏ cửa sổ xuống thanh Taskbar an toàn chuẩn Windows."""
    try:
        if window:
            window.minimize()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def restore_from_tray(window):
    """Khôi phục và hiển thị lại cửa sổ CỔ NGỮ lên trên cùng màn hình."""
    def _do_restore():
        try:
            if hasattr(window, 'native') and window.native:
                from System.Windows.Forms import FormWindowState
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
    global SYSTEM_TRAY
    try:
        if SYSTEM_TRAY:
            SYSTEM_TRAY.Visible = False
            SYSTEM_TRAY.Dispose()
            SYSTEM_TRAY = None
    except Exception:
        pass
    try:
        PLAYTIME_MGR.flush_all_active()
    except Exception:
        pass
    os._exit(0)


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
                "--no-proxy-server",
                "--proxy-bypass-list=<-loopback>",
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


def main():
    global SERVER_PORT, HTTP_SERVER

    # Gán AppID độc lập cho Windows Taskbar / Startbar
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("congu.vietmodhub.launcher.v2")
        except Exception:
            pass

    # 0. Single-Instance Protection: Mutex kiểm tra ứng dụng trùng lặp
    _app_mutex = None
    if sys.platform == "win32" and "--server" not in sys.argv and "--no-gui" not in sys.argv:
        try:
            ERROR_ALREADY_EXISTS = 183
            _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\CoNguVietModHubSingleInstance")
            last_err = ctypes.windll.kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                log_startup("[*] Phat hien Co Ngu da dang chay (Mutex ton tai). Dang danh thuc cua so...")
                hwnd = ctypes.windll.user32.FindWindowW(None, "CỔ NGỮ - Trình Quản Lý Game Việt Hóa Pro")
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                try:
                    import urllib.request
                    check_url = "http://127.0.0.1:49200/api/window/restore_tray"
                    req = urllib.request.Request(check_url, data=b"{}", headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        pass
                except Exception:
                    pass
                log_startup("[*] Da gui lenh danh thuc. Thoat tien trinh khoi tao thu hai.")
                sys.exit(0)
        except Exception as e:
            log_startup(f"[SingleInstance] Mutex check error: {e}")

    # 1. Khởi tạo cấu hình phiên & HTTP Server
    SESSION_AUTH_TOKEN = secrets.token_hex(16)
    configure_routes(api=api_instance, session_token=SESSION_AUTH_TOKEN)

    HTTP_SERVER = create_http_server(server_app)
    SERVER_PORT = HTTP_SERVER.server_address[1]
    log_startup(f"[*] Co Ngu Core Engine initialized on 127.0.0.1:{SERVER_PORT} (Token Protected)")

    t = threading.Thread(target=HTTP_SERVER.serve_forever, daemon=True)
    t.start()

    # 2. Kiểm tra Socket 127.0.0.1 đã sẵn sàng trước khi mở WebView
    if wait_for_local_server(SERVER_PORT, timeout_sec=5.0):
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
            easy_drag=True,
            background_color="#0b0f19"
        )
        api_instance.window = window

        def on_shown(w, ico):
            t_icon = threading.Thread(target=apply_titlebar_icon, args=(w, ico), daemon=True)
            t_icon.start()
            setup_system_tray(w, ico)

        def on_closed():
            global SYSTEM_TRAY
            try:
                if SYSTEM_TRAY:
                    SYSTEM_TRAY.Visible = False
                    SYSTEM_TRAY.Dispose()
                    SYSTEM_TRAY = None
            except Exception:
                pass
            if time.time() - webview_started_at > 3.0:
                user_closed_window["closed"] = True
                try:
                    PLAYTIME_MGR.flush_all_active()
                except Exception:
                    pass
                os._exit(0)

        window.events.closed += on_closed

        webview.start(
            func=on_shown,
            args=(window, icon_path),
            debug=False,
            icon=icon_path if icon_path else None
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
        while True:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
