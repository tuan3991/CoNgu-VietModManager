import os
import sys
import json
import time
import uuid
import socket
import urllib.request
import urllib.parse
import subprocess
import threading
import re
import hashlib
from typing import List, Dict, Any, Optional

# Danh sách Public Trackers chất lượng cao và hoạt động ổn định nhất toàn cầu (cập nhật 2026)
BEST_PUBLIC_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
]


class TorrentDownloader:
    """
    Quản lý tiến trình tải Torrent / Magnet / Direct Link đa luồng qua aria2c.exe
    Tuân thủ nguyên tắc 'Zero-Leak Clean Exit': aria2c tự hủy tức thì khi app.py tắt.
    Tối ưu hóa tải Magnet nhanh, kết nối DHT/Trackers lập tức và phân giải metadata mượt mà.
    """

    def __init__(self, tools_dir: Optional[str] = None, appdata_dir: Optional[str] = None):
        # Hỗ trợ trường hợp gọi TorrentDownloader(appdata_dir)
        if tools_dir and not appdata_dir and ("VietModHub" in tools_dir or not os.path.exists(os.path.join(tools_dir, "aria2c.exe"))):
            if os.path.isdir(tools_dir) and not os.path.isfile(os.path.join(tools_dir, "aria2c.exe")):
                appdata_dir = tools_dir
                tools_dir = None

        if not tools_dir:
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            candidates = [
                os.path.join(cur_dir, "tools"),
                os.path.join(cur_dir, "_internal", "tools"),
                os.path.join(os.path.dirname(cur_dir), "_internal", "tools"),
                os.path.join(getattr(sys, "_MEIPASS", cur_dir), "tools"),
            ]
            for c in candidates:
                if os.path.isfile(os.path.join(c, "aria2c.exe")):
                    tools_dir = c
                    break
            if not tools_dir:
                tools_dir = os.path.join(cur_dir, "tools")

        self.tools_dir = os.path.abspath(tools_dir)
        self.aria2c_exe = os.path.join(self.tools_dir, "aria2c.exe")
        if not os.path.isfile(self.aria2c_exe):
            alt_exe = os.path.join(os.path.dirname(self.tools_dir), "_internal", "tools", "aria2c.exe")
            if os.path.isfile(alt_exe):
                self.aria2c_exe = alt_exe

        if not appdata_dir:
            appdata_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VietModHub")
        self.appdata_dir = os.path.abspath(appdata_dir)
        os.makedirs(self.appdata_dir, exist_ok=True)
        self.meta_file = os.path.join(self.appdata_dir, "active_downloads.json")

        # Thư mục tải về mặc định: Downloads/VietModHub_Games
        user_downloads = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Downloads", "VietModHub_Games")
        self.default_download_dir = user_downloads
        os.makedirs(self.default_download_dir, exist_ok=True)

        self.rpc_port = self._find_free_port(6800)
        self.rpc_secret = f"congu_{uuid.uuid4().hex[:12]}"
        self.rpc_url = f"http://127.0.0.1:{self.rpc_port}/jsonrpc"

        self.daemon_proc: Optional[subprocess.Popen] = None
        self.task_metadata = self._load_task_metadata()
        self.lock = threading.Lock()

    def _find_free_port(self, default_port: int = 6800) -> int:
        for port in range(default_port, default_port + 50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return default_port

    def _load_task_metadata(self) -> Dict[str, Any]:
        if os.path.isfile(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_task_metadata(self):
        try:
            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump(self.task_metadata, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ========================================================
    # 1. QUẢN LÝ TIẾN TRÌNH ARIA2C DAEMON
    # ========================================================
    def ensure_daemon_running(self) -> bool:
        """Khởi chạy aria2c daemon tối ưu hóa hiệu năng và kết nối Swarm nếu chưa chạy."""
        if not os.path.isfile(self.aria2c_exe):
            print(f"[TorrentDownloader Error] Không tìm thấy aria2c.exe tại: {self.aria2c_exe}")
            return False

        if self.daemon_proc and self.daemon_proc.poll() is None:
            return True

        dht_file = os.path.join(self.appdata_dir, "dht.dat")
        dht6_file = os.path.join(self.appdata_dir, "dht6.dat")

        # Cờ tối ưu hóa:
        # - --file-allocation=none: Ghi đĩa tức thì, KHÔNG preallocate file rỗng gây nghẽn đĩa 100% trên Windows
        # - --follow-torrent=mem: Giữ metadata trong RAM và tự động tải file data ngay
        # - --bt-max-peers=120: Tăng số lượng peers kết nối đồng thời
        # - --bt-tracker-connect-timeout=5: Timeout tracker nhanh để tìm seeder tốt nhất
        # - --stop-with-process: Windows tự hủy aria2c tức thì khi PID của app.py tắt (Zero Zombie)
        cmd = [
            self.aria2c_exe,
            "--enable-rpc=true",
            f"--rpc-listen-port={self.rpc_port}",
            f"--rpc-secret={self.rpc_secret}",
            "--rpc-allow-origin-all=true",
            f"--stop-with-process={os.getpid()}",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--file-allocation=none",
            "--follow-torrent=mem",
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            "--bt-enable-lpd=true",
            "--bt-max-peers=120",
            "--bt-tracker-connect-timeout=5",
            "--bt-tracker-timeout=5",
            f"--dht-file-path={dht_file}",
            f"--dht-file-path6={dht6_file}",
            "--dht-entry-point=router.bittorrent.com:6881",
            "--dht-entry-point=dht.transmissionbt.com:6881",
            "--dht-entry-point=router.utorrent.com:6881",
            "--listen-port=6881-6999",
            "--dht-listen-port=6881-6999",
            "--seed-time=0",
            f"--dir={self.default_download_dir}",
            "--check-certificate=false",
            "--quiet=true",
        ]

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self.daemon_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            time.sleep(0.3)
            return True
        except Exception as e:
            print(f"[TorrentDownloader Error] Khởi chạy aria2c thất bại: {e}")
            return False

    def stop_daemon(self):
        """Dừng tiến trình aria2c khi tắt ứng dụng."""
        if self.daemon_proc:
            try:
                self.daemon_proc.terminate()
                self.daemon_proc.wait(timeout=2)
            except Exception:
                try:
                    self.daemon_proc.kill()
                except Exception:
                    pass
            self.daemon_proc = None

    # ========================================================
    # 2. GIAO TIẾP JSON-RPC VỚI ARIA2C
    # ========================================================
    def _call_rpc(self, method: str, params: Optional[list] = None) -> Any:
        if not self.ensure_daemon_running():
            return None

        if params is None:
            params = []
        full_params = [f"token:{self.rpc_secret}"] + params
        payload = {
            "jsonrpc": "2.0",
            "id": f"congu_{int(time.time()*1000)}",
            "method": method,
            "params": full_params,
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.rpc_url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                if "error" in res_json:
                    err_info = res_json.get("error", {})
                    self._last_error = err_info.get("message", "Lỗi RPC không xác định")
                    return None
                return res_json.get("result")
        except Exception as e:
            self._last_error = str(e)
            return None

    # ========================================================
    # 3. CÁC HÀM ĐIỀU KHIỂN DOWNLOAD (PUBLIC API)
    # ========================================================
    def add_download(
        self,
        uri: str,
        game_id: str = "",
        game_title: str = "",
        release_title: str = "",
        repacker: str = "",
        custom_dir: str = "",
        title: str = "",
        save_dir: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Thêm một Magnet URI hoặc Direct Link vào hàng đợi tải của CỔ NGỮ.
        Tự động tiêm danh sách Public Trackers chất lượng cao để tăng tốc tìm Seeder/Peers tối đa.
        Tự động chuẩn hóa RFC-compliant SHA-1 hash cho btih.
        """
        if not uri:
            return {"success": False, "message": "Đường dẫn tải (URI) không được để trống!"}

        final_title = title or release_title or game_title or kwargs.get("name") or "Tệp Game Repack"
        final_dir = custom_dir or save_dir or kwargs.get("download_dir") or ""
        target_dir = os.path.abspath(final_dir) if final_dir else self.default_download_dir
        os.makedirs(target_dir, exist_ok=True)

        clean_uri = uri.strip()

        # Chuẩn hóa Magnet URI và Inject Trackers
        if clean_uri.startswith("magnet:?"):
            btih_match = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", clean_uri, re.IGNORECASE)
            if btih_match:
                raw_hash = btih_match.group(1)
                is_valid_hex40 = (len(raw_hash) == 40 and bool(re.match(r"^[0-9a-fA-F]{40}$", raw_hash)))
                is_valid_b32 = (len(raw_hash) == 32 and bool(re.match(r"^[2-7a-zA-Z]{32}$", raw_hash)))
                if not is_valid_hex40 and not is_valid_b32:
                    hex40 = hashlib.sha1(raw_hash.encode("utf-8")).hexdigest()
                    clean_uri = clean_uri.replace(f"xt=urn:btih:{raw_hash}", f"xt=urn:btih:{hex40}")

            # Luôn bổ sung các tracker uy tín nhất nếu magnet chưa có hoặc có ít tracker
            existing_trackers = set(re.findall(r"tr=([^&]+)", clean_uri))
            extra_trackers = []
            for tr in BEST_PUBLIC_TRACKERS:
                encoded_tr = urllib.parse.quote(tr, safe="")
                if encoded_tr not in existing_trackers and tr not in clean_uri:
                    extra_trackers.append(f"&tr={encoded_tr}")
            if extra_trackers:
                clean_uri += "".join(extra_trackers)

        options = {
            "dir": target_dir
        }

        self._last_error = ""
        gid = self._call_rpc("aria2.addUri", [[clean_uri], options])
        if not gid:
            err_msg = self._last_error or "Không thể kết nối với engine tải aria2c hoặc link magnet bị lỗi cấu trúc!"
            return {"success": False, "message": err_msg}

        with self.lock:
            self.task_metadata[gid] = {
                "gid": gid,
                "game_id": game_id,
                "title": final_title,
                "game_title": game_title or final_title,
                "release_title": release_title or final_title,
                "repacker": repacker,
                "uri": uri,
                "download_dir": target_dir,
                "started_at": int(time.time()),
                "status": "active"
            }
            self._save_task_metadata()

        return {
            "success": True,
            "gid": gid,
            "message": f"Đã bắt đầu tải '{final_title}'!",
            "download_dir": target_dir
        }

    def pause_download(self, gid: str) -> Dict[str, Any]:
        res = self._call_rpc("aria2.pause", [gid])
        return {"success": bool(res), "gid": gid}

    def resume_download(self, gid: str) -> Dict[str, Any]:
        res = self._call_rpc("aria2.unpause", [gid])
        return {"success": bool(res), "gid": gid}

    def cancel_download(self, gid: str, delete_files: bool = False) -> Dict[str, Any]:
        # Hủy task chính
        self._call_rpc("aria2.remove", [gid])
        self._call_rpc("aria2.removeDownloadResult", [gid])

        with self.lock:
            # Nếu task có task con sinh ra từ metadata, hủy luôn task con
            child_gids = [k for k, v in self.task_metadata.items() if v.get("parent_gid") == gid]
            for cg in child_gids:
                self._call_rpc("aria2.remove", [cg])
                self._call_rpc("aria2.removeDownloadResult", [cg])
                self.task_metadata.pop(cg, None)

            self.task_metadata.pop(gid, None)
            self._save_task_metadata()

        return {"success": True, "message": "Đã hủy tác vụ tải."}

    def get_all_downloads_status(self) -> List[Dict[str, Any]]:
        """
        Lấy danh sách và tiến độ realtime của toàn bộ tác vụ tải.
        Hỗ trợ tự động kế thừa metadata từ giai đoạn nạp torrent sang giai đoạn tải file data.
        Đảm bảo tương thích 100% với cả 2 bộ thuộc tính frontend (title, speed, bytes, peers).
        """
        keys = [
            "gid", "status", "totalLength", "completedLength",
            "downloadSpeed", "uploadSpeed", "numSeeders",
            "connections", "files", "errorMessage", "followedBy", "following"
        ]
        active = self._call_rpc("aria2.tellActive", [keys]) or []
        waiting = self._call_rpc("aria2.tellWaiting", [0, 50, keys]) or []
        stopped = self._call_rpc("aria2.tellStopped", [0, 50, keys]) or []

        all_tasks = active + waiting + stopped

        # 1. Tự động liên kết metadata giữa task tải metadata (cha) và task tải file thật (con)
        with self.lock:
            metadata_changed = False
            for item in all_tasks:
                gid = item.get("gid", "")
                following_gid = item.get("following")
                if following_gid and following_gid in self.task_metadata and gid not in self.task_metadata:
                    parent_meta = self.task_metadata[following_gid]
                    self.task_metadata[gid] = parent_meta.copy()
                    self.task_metadata[gid]["gid"] = gid
                    self.task_metadata[gid]["parent_gid"] = following_gid
                    metadata_changed = True
            if metadata_changed:
                self._save_task_metadata()

        # 2. Lọc bỏ các task metadata cha đã hoàn tất và đã sinh ra task con tải file
        parent_gids_with_children = set()
        for item in all_tasks:
            following = item.get("following")
            if following:
                parent_gids_with_children.add(following)

        results = []
        for item in all_tasks:
            gid = item.get("gid", "")
            raw_status = item.get("status", "unknown")
            followed_by = item.get("followedBy")

            # Bỏ qua task metadata cha nếu task con đã ra đời
            if gid in parent_gids_with_children or (followed_by and raw_status in ("complete", "removed")):
                continue

            meta = self.task_metadata.get(gid, {})

            tot = int(item.get("totalLength", 0))
            comp = int(item.get("completedLength", 0))
            spd = int(item.get("downloadSpeed", 0))
            connections = int(item.get("connections", 0))
            percent = round((comp / tot * 100), 1) if tot > 0 else 0.0

            # Xác định trạng thái người dùng dễ hiểu
            is_metadata_stage = (tot == 0 and raw_status in ("active", "waiting"))
            if is_metadata_stage:
                display_status = "metadata"
            elif raw_status == "active":
                display_status = "downloading"
            elif raw_status == "paused":
                display_status = "paused"
            elif raw_status == "complete":
                display_status = "complete"
            elif raw_status == "error":
                display_status = "error"
            else:
                display_status = raw_status

            # Tính thời gian còn lại (ETA)
            eta_seconds = int((tot - comp) / spd) if spd > 0 and tot > comp else 0
            if is_metadata_stage:
                eta_str = "Đang lấy metadata..."
            elif eta_seconds <= 0:
                eta_str = "Hoàn tất" if percent >= 100 else "Đang tính..."
            elif eta_seconds < 60:
                eta_str = f"{eta_seconds}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds // 60}m {eta_seconds % 60}s"
            else:
                eta_str = f"{eta_seconds // 3600}h {(eta_seconds % 3600) // 60}m"

            # Tên file hoặc folder thực tế tải về
            files = item.get("files", [])
            downloaded_path = ""
            if files and files[0].get("path"):
                downloaded_path = files[0].get("path")

            final_title = (
                meta.get("title")
                or meta.get("release_title")
                or meta.get("game_title")
                or (os.path.basename(downloaded_path) if downloaded_path and not downloaded_path.startswith("[METADATA]") else "")
                or "Tệp Game Repack"
            )

            # Cung cấp song song cả hai bộ tên thuộc tính để frontend luôn nhận đúng 100%
            results.append({
                "gid": gid,
                "title": final_title,
                "game_id": meta.get("game_id", ""),
                "game_title": final_title,
                "release_title": meta.get("release_title", final_title),
                "repacker": meta.get("repacker", ""),
                "status": display_status,
                "raw_status": raw_status,
                "is_metadata": is_metadata_stage,
                "total_bytes": tot,
                "completed_bytes": comp,
                "downloaded_bytes": comp,
                "total_formatted": self._format_bytes(tot),
                "completed_formatted": self._format_bytes(comp),
                "speed_bytes": spd,
                "download_speed": spd,
                "speed_formatted": self._format_speed(spd),
                "percent": percent,
                "num_seeders": int(item.get("numSeeders", 0)),
                "connections": connections,
                "peers": connections,
                "eta_str": eta_str,
                "eta_seconds": eta_seconds,
                "download_dir": meta.get("download_dir", self.default_download_dir),
                "save_dir": meta.get("download_dir", self.default_download_dir),
                "file_path": downloaded_path,
                "error": item.get("errorMessage", ""),
            })

        return results

    @staticmethod
    def _format_speed(spd: int) -> str:
        if spd >= 1024 * 1024:
            return f"{round(spd / (1024 * 1024), 2)} MB/s"
        elif spd >= 1024:
            return f"{round(spd / 1024, 1)} KB/s"
        return f"{spd} B/s"

    @staticmethod
    def _format_bytes(byte_count: int) -> str:
        if byte_count >= 1024 * 1024 * 1024:
            return f"{round(byte_count / (1024 * 1024 * 1024), 2)} GB"
        elif byte_count >= 1024 * 1024:
            return f"{round(byte_count / (1024 * 1024), 1)} MB"
        elif byte_count >= 1024:
            return f"{round(byte_count / 1024, 0)} KB"
        return f"{byte_count} B"

    # ========================================================
    # 4. MỞ BẰNG PHẦN MỀM NGOÀI (QBITTORRENT / UTORRENT)
    # ========================================================
    @staticmethod
    def open_external_torrent(uri: str) -> Dict[str, Any]:
        """Gọi ứng dụng Torrent mặc định trên máy người dùng (qBittorrent, uTorrent, IDM...)."""
        if not uri:
            return {"success": False, "message": "URI trống!"}
        try:
            os.startfile(uri)
            return {"success": True, "message": "Đã gửi link tới ứng dụng Torrent trên máy bạn!"}
        except Exception as e:
            return {"success": False, "message": f"Không thể mở ứng dụng torrent: {e}"}

    @staticmethod
    def open_download_folder(target_dir: str) -> Dict[str, Any]:
        """Mở thư mục chứa file đã tải trong Windows Explorer."""
        if not target_dir or not os.path.isdir(target_dir):
            return {"success": False, "message": "Thư mục không tồn tại!"}
        try:
            os.startfile(target_dir)
            return {"success": True, "message": "Đã mở thư mục tải về."}
        except Exception as e:
            return {"success": False, "message": f"Không thể mở thư mục: {e}"}


# Tương thích ngược với tên gọi cũ
TorrentDownloadManager = TorrentDownloader
