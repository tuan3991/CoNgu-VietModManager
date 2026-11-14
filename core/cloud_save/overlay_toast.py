# -*- coding: utf-8 -*-
"""
In-Game Steam-Style Achievement Overlay for VietModManager.
Displays a non-intrusive, top-most notification over full-screen & borderless games
when an achievement is unlocked during gameplay.
Uses Win32 WS_EX_NOACTIVATE to ensure 0 focus loss and 0 interruption for the player.
"""

import os
import sys
import time
import queue
import threading
import ctypes
from typing import Optional

_notification_queue = queue.Queue()
_overlay_thread_started = False
_thread_lock = threading.Lock()
_TING_WAV_CACHE: Optional[bytes] = None


def _build_crystal_ting_wav() -> bytes:
    """
    Tổng hợp âm thanh 'TING!' pha lê đa hài âm (44.1kHz Stereo 16-bit PCM).
    Gồm nốt chủ G6 (1568Hz), quãng năm D7 (2349Hz), quãng tám G7 (3136Hz),
    thân ấm G5 (784Hz) và hiệu ứng stereo shimmer nhẹ.
    """
    import io
    import math
    import struct
    import wave

    sample_rate = 44100
    duration = 1.25
    num_samples = int(sample_rate * duration)

    # Các thành phần hài âm (tần số Hz, biên độ, tốc độ tắt, độ trễ vào ms)
    partials = [
        (783.99, 0.20, 7.5, 0.0),    # G5: thân âm ấm, tắt nhanh
        (1567.98, 0.56, 3.2, 0.0),   # G6: âm chuông TING chủ đạo
        (2349.32, 0.28, 3.8, 0.0),   # D7: quãng 5 tạo độ vang sang trọng
        (3135.96, 0.34, 4.4, 0.008), # G7: quãng 8 sáng lấp lánh
        (4703.94, 0.10, 8.0, 0.014), # D8: ánh kim pha lê nhẹ lúc đầu
    ]

    attack_samples = int(0.0025 * sample_rate)  # 2.5ms fade-in chống click
    left_buf = [0.0] * num_samples
    right_buf = [0.0] * num_samples
    two_pi = 2.0 * math.pi

    for freq, amp, decay, delay_sec in partials:
        start_idx = int(delay_sec * sample_rate)
        # Detune rất nhẹ giữa trái/phải (+/- 1.2 Hz) cho hiệu ứng stereo shimmer
        omega_l = two_pi * (freq - 1.2) / sample_rate
        omega_r = two_pi * (freq + 1.2) / sample_rate
        for i in range(start_idx, num_samples):
            t = (i - start_idx) / sample_rate
            local_i = i - start_idx
            env = math.exp(-decay * t)
            if local_i < attack_samples:
                # Cosine attack mượt 0 -> 1
                env *= 0.5 * (1.0 - math.cos(math.pi * local_i / attack_samples))
            left_buf[i] += amp * env * math.sin(omega_l * local_i)
            right_buf[i] += amp * env * math.sin(omega_r * local_i)

    # Chuẩn hóa biên độ ở mức ~68% (-3.3 dBFS) để trong trẻo, không rè/chói
    peak = max(max(abs(x) for x in left_buf), max(abs(x) for x in right_buf), 1e-6)
    scale = (0.68 * 32767.0) / peak

    pcm_frames = bytearray(num_samples * 4)
    pack_into = struct.pack_into
    for i in range(num_samples):
        l_val = max(-32767, min(32767, int(left_buf[i] * scale)))
        r_val = max(-32767, min(32767, int(right_buf[i] * scale)))
        pack_into("<hh", pcm_frames, i * 4, l_val, r_val)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_frames)
    return buf.getvalue()


def _get_ting_wav_bytes() -> bytes:
    global _TING_WAV_CACHE
    if _TING_WAV_CACHE is None:
        _TING_WAV_CACHE = _build_crystal_ting_wav()
    return _TING_WAV_CACHE


def _is_achievement_sound_enabled() -> bool:
    try:
        from core.config_manager.user_settings import load_user_config
        cfg = load_user_config()
        return cfg.get("general", {}).get("achievement_sound", True) is not False
    except Exception:
        return True


def play_achievement_chime():
    """Phát âm thanh 'TING!' pha lê chất lượng cao khi mở khóa thành tựu."""
    if not _is_achievement_sound_enabled():
        return

    def _chime():
        try:
            import winsound
            wav_bytes = _get_ting_wav_bytes()
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    t = threading.Thread(target=_chime, daemon=True)
    t.start()


def show_in_game_achievement_notification(
    title: str,
    description: str = "",
    icon_path: str = "",
    game_title: str = ""
):
    """
    Đưa thành tựu vào hàng đợi hiển thị Overlay ngay trên màn hình game.
    """
    _ensure_worker_running()
    _notification_queue.put({
        "title": title or "Thành Tựu Mới!",
        "description": description or "Đã mở khóa trong quá trình chơi",
        "icon_path": icon_path or "",
        "game_title": game_title or ""
    })


def _ensure_worker_running():
    global _overlay_thread_started
    with _thread_lock:
        if not _overlay_thread_started:
            t = threading.Thread(target=_overlay_worker_loop, daemon=True)
            t.start()
            _overlay_thread_started = True


def _overlay_worker_loop():
    """Worker lấy từng thành tựu trong queue và hiển thị tuần tự (tránh đè lên nhau)."""
    while True:
        try:
            item = _notification_queue.get()
            if not item:
                continue

            # Phát âm thanh mở khóa thành tựu ngay lập tức
            play_achievement_chime()

            # Hiển thị cửa sổ overlay
            _display_single_notification(item)

            # Nghỉ ngắn giữa 2 thông báo liên tiếp
            time.sleep(0.3)
        except Exception as e:
            print(f"[AchievementOverlay] Worker error: {e}")
            time.sleep(1)


def _draw_trophy_icon(canvas, size=52):
    """Vẽ biểu tượng cúp vàng thành tựu sắc nét khi không có file ảnh PNG."""
    # Nền icon bo tròn nhẹ
    canvas.create_rectangle(2, 2, size - 2, size - 2, fill="#131D31", outline="#00F0FF", width=1)
    # Thân cúp vàng
    canvas.create_polygon(
        15, 14,
        37, 14,
        34, 28,
        28, 35,
        24, 35,
        18, 28,
        fill="#F59E0B", outline="#FBBF24", width=1
    )
    # Quai cúp trái
    canvas.create_arc(10, 15, 20, 27, start=90, extent=180, style="arc", outline="#FCD34D", width=2)
    # Quai cúp phải
    canvas.create_arc(32, 15, 42, 27, start=270, extent=180, style="arc", outline="#FCD34D", width=2)
    # Chân cúp & đế
    canvas.create_rectangle(24, 35, 28, 41, fill="#D97706", outline="")
    canvas.create_rectangle(17, 41, 35, 45, fill="#B45309", outline="#F59E0B", width=1)
    # Ngôi sao lấp lánh ở góc
    canvas.create_text(38, 12, text="✦", fill="#00F0FF", font=("Segoe UI", 10, "bold"))


def _display_single_notification(item: dict):
    """Khởi tạo và chạy cửa sổ Tkinter Topmost Overlay trong 5 giây."""
    try:
        import tkinter as tk
    except ImportError:
        return

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    # Kích thước chuẩn thông báo game: 360x86 px
    w = 370
    h = 86
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    # Vị trí góc dưới cùng bên phải (chuẩn Steam / Xbox)
    # Cách mép phải 24px, mép dưới 48px (trên thanh Taskbar hoặc viền game)
    x = sw - w - 24
    y = sh - h - 48

    root.geometry(f"{w}x{h}+{x}+{y}")
    root.configure(bg="#00F0FF")  # Viền ngoài Neon Cyan 1px

    # Áp dụng Win32 Styles chống cướp tiêu điểm phím/chuột của game
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        old_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            old_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        )
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception:
        pass

    # Frame nội dung bên trong màu tối cao cấp
    content = tk.Frame(root, bg="#0A0E1A", padx=10, pady=8)
    content.pack(fill="both", expand=True, padx=1, pady=1)

    # Cột trái: Icon
    icon_canvas = tk.Canvas(content, width=54, height=54, bg="#0A0E1A", highlightthickness=0)
    icon_canvas.pack(side="left", padx=(0, 10))

    img_ref = None
    icon_loaded = False
    icon_path = item.get("icon_path", "")

    if icon_path and os.path.isfile(icon_path):
        try:
            # Thử load bằng tk.PhotoImage (PNG)
            img = tk.PhotoImage(file=icon_path)
            # Resize nếu cần hoặc hiển thị trực tiếp
            icon_canvas.create_image(27, 27, image=img)
            img_ref = img
            icon_loaded = True
        except Exception:
            icon_loaded = False

    if not icon_loaded:
        _draw_trophy_icon(icon_canvas, size=54)

    # Cột phải: Thông tin thành tựu
    text_frame = tk.Frame(content, bg="#0A0E1A")
    text_frame.pack(side="left", fill="both", expand=True)

    header_text = "THÀNH TỰU MỞ KHÓA!"
    if item.get("game_title"):
        header_text = f"THÀNH TỰU • {item['game_title'].upper()}"

    lbl_header = tk.Label(
        text_frame,
        text=header_text,
        fg="#00F0FF",
        bg="#0A0E1A",
        font=("Segoe UI", 8, "bold"),
        anchor="w"
    )
    lbl_header.pack(fill="x")

    title_val = item.get("title", "Thành Tựu")
    if len(title_val) > 36:
        title_val = title_val[:33] + "..."

    lbl_title = tk.Label(
        text_frame,
        text=title_val,
        fg="#FFFFFF",
        bg="#0A0E1A",
        font=("Segoe UI", 10, "bold"),
        anchor="w"
    )
    lbl_title.pack(fill="x", pady=(1, 0))

    desc_val = item.get("description", "")
    if len(desc_val) > 52:
        desc_val = desc_val[:49] + "..."

    lbl_desc = tk.Label(
        text_frame,
        text=desc_val,
        fg="#94A3B8",
        bg="#0A0E1A",
        font=("Segoe UI", 8),
        anchor="w"
    )
    lbl_desc.pack(fill="x", pady=(1, 0))

    # Tự hủy sau 5.2 giây
    def _close():
        try:
            root.destroy()
        except Exception:
            pass

    root.after(5200, _close)

    try:
        root.mainloop()
    except Exception:
        pass
