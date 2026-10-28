# -*- coding: utf-8 -*-
"""
Core Cloud Save - Playtime Tracker
"""
import os
import sys
import time
import json
import threading
from typing import Dict, Any, Optional, Callable

from .process_utils import is_any_exe_running_in_folder, _internal_log, get_default_appdata_dir


class PlaytimeManager:
    """Bộ quản lý khởi chạy game và đếm giờ chơi chuẩn xác theo thời gian thực (Zero-Leak Clean Exit)."""

    def __init__(self, db_path: str = None, on_game_exit_callback=None, appdata_dir: str = None):
        self.appdata_dir = appdata_dir or get_default_appdata_dir()
        os.makedirs(self.appdata_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(self.appdata_dir, "playtime.json")
        self.lock = threading.RLock()
        self.active_games = {}  # {game_id: {"start_ts": float, "last_chk": float, "last_active": float, "game_dir": str}}
        self.on_game_exit_callback = on_game_exit_callback
        self.get_installed_paths = None
        self._data = self._load_db()

    def _load_db(self) -> dict:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[PlaytimeManager] Load DB error: {e}")
        return {}

    def _save_db(self, game_id: str = None, game_dir: str = None):
        with self.lock:
            try:
                tmp_path = self.db_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.db_path)
            except Exception as e:
                print(f"[PlaytimeManager] Save DB error: {e}")

            # Lưu đồng bộ 1 bản Portable ngay trong thư mục game (nếu có quyền ghi)
            if game_id:
                target_dir = game_dir
                if not target_dir or not os.path.isdir(target_dir):
                    try:
                        if _CONFIG_GETTER:
                            cfg = _CONFIG_GETTER()
                            target_dir = cfg.get(f"{game_id}_path")
                    except Exception:
                        pass
                if target_dir and os.path.isdir(target_dir):
                    try:
                        local_file = os.path.join(target_dir, ".congu_playtime.json")
                        with open(local_file, "w", encoding="utf-8") as lf:
                            json.dump(self._data.get(game_id, {}), lf, ensure_ascii=False, indent=2)
                    except OSError:
                        pass

    def is_game_running(self, game_id: str) -> bool:
        with self.lock:
            return game_id in self.active_games

    def get_game_stats(self, game_id: str, game_dir: str = None) -> dict:
        """Lấy thông tin giờ chơi đã định dạng đẹp để gửi lên Frontend (Hỗ trợ Live Playtime khi đang chơi)."""
        with self.lock:
            rec = self._data.get(game_id)
            if not game_dir:
                try:
                    if _CONFIG_GETTER:
                        cfg = _CONFIG_GETTER()
                        game_dir = cfg.get(f"{game_id}_path")
                except Exception:
                    pass

            # Khôi phục / đồng bộ hai chiều từ file portable trong thư mục game (Bảo toàn dữ liệu tuyệt đối)
            if game_dir and os.path.isdir(game_dir):
                local_file = os.path.join(game_dir, ".congu_playtime.json")
                if os.path.exists(local_file):
                    try:
                        with open(local_file, "r", encoding="utf-8") as lf:
                            local_rec = json.load(lf)
                            local_sec = int(local_rec.get("total_seconds", 0))
                            current_sec = int(rec.get("total_seconds", 0)) if rec else 0
                            if local_sec > current_sec:
                                rec = local_rec
                                self._data[game_id] = rec
                                self._save_db(game_id, game_dir)
                            elif current_sec > local_sec:
                                # Đồng bộ ngược vào file portable nếu máy có giờ chơi mới hơn
                                try:
                                    with open(local_file, "w", encoding="utf-8") as wlf:
                                        json.dump(rec, wlf, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                elif rec and int(rec.get("total_seconds", 0)) > 0:
                    try:
                        with open(local_file, "w", encoding="utf-8") as wlf:
                            json.dump(rec, wlf, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

            rec = rec or {"total_seconds": 0, "last_played_ts": None, "sessions_count": 0}
            total_sec = int(rec.get("total_seconds", 0))

            # Tự nhận diện cả khi người dùng mở game bằng Shortcut ngoài Desktop
            is_running = game_id in self.active_games
            if not is_running and game_dir and os.path.isdir(game_dir):
                if is_any_exe_running_in_folder(game_dir):
                    self.start_tracking(game_id, game_dir)
                    is_running = True

            # Tính Live Playtime trực tiếp nếu game đang chạy
            if is_running:
                active_info = self.active_games.get(game_id)
                if active_info:
                    start_session_ts = active_info.get("start_ts", time.time())
                    live_seconds = int(time.time() - active_info.get("last_chk", start_session_ts))
                    total_sec += max(0, live_seconds)

            # Định dạng chuỗi hiển thị thông minh giống Steam
            if total_sec == 0:
                formatted_time = "Chưa chơi"
            elif total_sec < 60:
                formatted_time = f"{total_sec} giây" if is_running else "< 1 phút"
            elif total_sec < 3600:
                formatted_time = f"{max(1, total_sec // 60)} phút"
            else:
                formatted_time = f"{round(total_sec / 3600, 1)} giờ"

            last_ts = rec.get("last_played_ts")
            if is_running:
                last_played_str = "Đang chơi"
            elif not last_ts:
                last_played_str = "Chưa từng mở"
            else:
                try:
                    diff_days = (datetime.now().date() - datetime.fromtimestamp(last_ts).date()).days
                    if diff_days == 0:
                        last_played_str = "Hôm nay"
                    elif diff_days == 1:
                        last_played_str = "Hôm qua"
                    else:
                        last_played_str = datetime.fromtimestamp(last_ts).strftime("%d/%m/%Y")
                except Exception:
                    last_played_str = "Vừa xong"

            return {
                "game_id": game_id,
                "is_running": is_running,
                "total_seconds": total_sec,
                "formatted_time": formatted_time,
                "last_played_str": last_played_str,
                "sessions_count": rec.get("sessions_count", 0)
            }

    def start_background_scanner(self, get_installed_paths_callback):
        """Khởi động luồng quét ngầm nhận diện game mở từ Shortcut Desktop / Steam."""
        if hasattr(self, '_scanner_running') and self._scanner_running:
            return
        self._scanner_running = True
        self.get_installed_paths = get_installed_paths_callback

        def _scan_loop():
            # Chờ 4s đầu để app khởi động mượt mà
            time.sleep(4)
            while self._scanner_running:
                try:
                    time.sleep(5)
                    if not self.get_installed_paths:
                        continue
                    installed_paths = self.get_installed_paths()
                    if not installed_paths:
                        continue
                    for gid, gpath in installed_paths.items():
                        if not gpath or not os.path.isdir(gpath):
                            continue
                        with self.lock:
                            is_active = gid in self.active_games
                        if not is_active:
                            if is_any_exe_running_in_folder(gpath):
                                _internal_log(f"[PlaytimeTracker] Tự động phát hiện game '{gid}' mở từ Shortcut Desktop/Steam tại '{gpath}'!")
                                self.start_tracking(gid, gpath)
                except Exception:
                    pass

        t = threading.Thread(target=_scan_loop, daemon=True)
        t.start()

    def start_tracking(self, game_id: str, game_dir: str):
        """Bắt đầu luồng theo dõi đếm giờ tự động (Daemon Watcher)."""
        with self.lock:
            if game_id in self.active_games:
                return
            now = time.time()
            self.active_games[game_id] = {
                "start_ts": now,
                "last_chk": now,
                "last_active": now,
                "game_dir": game_dir
            }
            rec = self._data.setdefault(game_id, {
                "total_seconds": 0, "last_played_ts": int(now), "sessions_count": 0, "daily_log": {}
            })
            rec["last_played_ts"] = int(now)
            rec["sessions_count"] = rec.get("sessions_count", 0) + 1
            self._save_db(game_id, game_dir)

        t = threading.Thread(
            target=self._monitor_loop,
            args=(game_id, game_dir),
            daemon=True
        )
        t.start()
        _internal_log(f"[PlaytimeTracker] Đã kích hoạt luồng theo dõi cho '{game_id}'")

    def _monitor_loop(self, game_id: str, game_dir: str):
        """Vòng lặp kiểm tra mỗi 3s và lưu checkpoint nhịp tim mỗi 60s."""
        time.sleep(3)
        start_ts = time.time()
        last_checkpoint = start_ts
        last_active = start_ts
        session_saved_sec = 0
        unseen_streak = 0

        try:
            while True:
                time.sleep(3)
                now = time.time()

                if is_any_exe_running_in_folder(game_dir):
                    unseen_streak = 0
                    last_active = now

                    # Quét phát hiện thành tựu thời gian thực (Cơ chế Hydra Launcher / Achievement Watcher)
                    try:
                        if ACHIEVEMENT_MGR:
                            ACHIEVEMENT_MGR.check_game_live_achievements(game_id, game_dir)
                    except Exception:
                        pass

                    elapsed_delta = int(now - last_checkpoint)
                    # Lưu nhịp tim mỗi 60 giây chống mất dữ liệu khi mất điện hoặc crash
                    if elapsed_delta >= 60:
                        self._add_seconds(game_id, game_dir, elapsed_delta)
                        session_saved_sec += elapsed_delta
                        last_checkpoint = now
                        with self.lock:
                            if game_id in self.active_games:
                                self.active_games[game_id]["last_chk"] = now
                                self.active_games[game_id]["last_active"] = now
                else:
                    # Chờ xác nhận 2 nhịp liên tiếp (~6s) phòng lúc Launcher đang chuyển sang Shipping.exe
                    unseen_streak += 1
                    if unseen_streak >= 2:
                        session_elapsed = int(max(0, last_active - start_ts))
                        remaining_delta = max(0, session_elapsed - session_saved_sec)
                        if remaining_delta > 0:
                            self._add_seconds(game_id, game_dir, remaining_delta)
                        break
        except Exception as e:
            print(f"[PlaytimeTracker] Monitor loop error: {e}")
        finally:
            with self.lock:
                self.active_games.pop(game_id, None)

        _internal_log(f"[PlaytimeTracker] Phiên chơi của '{game_id}' đã kết thúc.")
        if self.on_game_exit_callback:
            try:
                self.on_game_exit_callback(game_id, game_dir)
            except Exception as e:
                print(f"[PlaytimeTracker] Post-exit hook error: {e}")

    def _add_seconds(self, game_id: str, game_dir: str, seconds: int):
        if seconds <= 0:
            return
        with self.lock:
            today_key = datetime.now().strftime("%Y-%m-%d")
            now_ts = int(time.time())
            rec = self._data.setdefault(game_id, {
                "total_seconds": 0, "last_played_ts": now_ts, "sessions_count": 1, "daily_log": {}
            })
            rec["total_seconds"] = int(rec.get("total_seconds", 0)) + seconds
            rec["last_played_ts"] = now_ts
            daily = rec.setdefault("daily_log", {})
            daily[today_key] = int(daily.get(today_key, 0)) + seconds
            self._save_db(game_id, game_dir)

    def flush_all_active(self):
        """Lưu nốt số giây đang chơi dở trước khi CỔ NGỮ đóng hẳn (Zero-Leak Clean Exit)."""
        with self.lock:
            now = time.time()
            for gid, info in list(self.active_games.items()):
                last_chk = info.get("last_chk", info.get("start_ts", now))
                delta = int(now - last_chk)
                if delta > 0:
                    gdir = info.get("game_dir")
                    self._add_seconds(gid, gdir, delta)
                    info["last_chk"] = now

    def get_all_stats(self) -> dict:
        """Trả về toàn bộ thống kê giờ chơi và trạng thái đang chạy cho tất cả game."""
        with self.lock:
            result = {}
            for gid, rec in self._data.items():
                is_running = gid in self.active_games
                total_sec = int(rec.get("total_seconds", 0))
                if is_running:
                    active_info = self.active_games.get(gid)
                    if active_info:
                        start_session_ts = active_info.get("start_ts", time.time())
                        live_seconds = int(time.time() - active_info.get("last_chk", start_session_ts))
                        total_sec += max(0, live_seconds)

                if total_sec == 0:
                    formatted_time = "Chưa chơi"
                elif total_sec < 60:
                    formatted_time = f"{total_sec} giây" if is_running else "< 1 phút"
                elif total_sec < 3600:
                    formatted_time = f"{max(1, total_sec // 60)} phút"
                else:
                    formatted_time = f"{round(total_sec / 3600, 1)} giờ"

                result[gid] = {
                    "game_id": gid,
                    "is_running": is_running,
                    "total_seconds": total_sec,
                    "formatted_time": formatted_time,
                    "last_played_str": "Đang chơi" if is_running else (rec.get("last_played_str") or "Gần đây"),
                    "sessions_count": rec.get("sessions_count", 0)
                }
            return result


# ==============================================================================
# QUẢN LÝ THÀNH TỰU (AchievementManager)
# ==============================================================================



PLAYTIME_MGR = PlaytimeManager()
