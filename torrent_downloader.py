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
import html
import base64
import ssl
import gzip
from typing import List, Dict, Any, Optional

# Danh sách Public Trackers chất lượng cao và hoạt động ổn định nhất toàn cầu (cập nhật 2026)
# Bổ sung cả giao thức HTTPS/HTTP trên cổng chuẩn 443/80 nhằm vượt tường lửa và chống bị ISP Việt Nam chặn UDP
BEST_PUBLIC_TRACKERS = [
    # Top Trackers uy tín và có lượng Seeder lớn nhất toàn cầu
    "http://tracker.opentrackr.org:1337/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "https://tr.ready4.icu:443/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "https://tracker.nanoha.org:443/announce",
    "https://tracker.gbitt.info:443/announce",
    "https://open.tracker.cl:443/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
    "udp://p4p.arenabg.com:1337/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://9.rarbg.to:2920/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://movies.zsw.ca:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
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

        self.torrents_dir = os.path.join(self.appdata_dir, "torrents")
        os.makedirs(self.torrents_dir, exist_ok=True)
        self._boosting_gids = set()

        self.daemon_proc: Optional[subprocess.Popen] = None
        self.task_metadata = self._load_task_metadata()
        self._inspection_cache: Dict[str, Any] = {}
        self.lock = threading.Lock()

    def _read_download_settings(self) -> tuple:
        """Lấy giới hạn băng thông và số tác vụ tải từ user_config.json."""
        try:
            config_path = os.path.join(self.appdata_dir, "user_config.json")
            with open(config_path, "r", encoding="utf-8") as handle:
                cfg = json.load(handle)
            settings = cfg.get("downloader", {})
            return (
                max(0, int(settings.get("max_download_limit_kb", 0) or 0)),
                max(1, min(10, int(settings.get("max_concurrent_downloads", 3) or 3)))
            )
        except Exception:
            return 0, 3

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
        # Kiểm tra dht.dat/dht6.dat nếu hỏng hoặc quá nhỏ (< 20 bytes) thì xóa để aria2c không văng lỗi deserializer
        for df in (dht_file, dht6_file):
            if os.path.isfile(df) and os.path.getsize(df) < 20:
                try:
                    os.remove(df)
                except Exception:
                    pass

        session_file = os.path.join(self.appdata_dir, "aria2.session")
        if not os.path.isfile(session_file):
            try:
                with open(session_file, "a", encoding="utf-8"):
                    pass
            except Exception:
                pass

        # Cờ tối ưu hóa:
        # - --file-allocation=none: Ghi đĩa tức thì, KHÔNG preallocate file rỗng gây nghẽn đĩa 100% trên Windows
        # - --allow-overwrite=true & --auto-file-renaming=false: Tránh lỗi errorCode=13 khi resume hoặc tải lại
        # - --disable-ipv6=true & --async-dns=false: Khắc phục triệt để lỗi c-ares IPv6 DNS timeouts trên mạng VN
        # - --follow-torrent=mem: Giữ metadata trong RAM và tự động tải file data ngay
        # - --bt-max-peers=200: Tăng số lượng peers kết nối đồng thời
        # - --bt-tracker-connect-timeout=10: Tối ưu thời gian bắt tay tracker quốc tế
        # - --bt-tracker: Tự động tiêm danh sách trackers mạnh nhất vào mọi tác vụ
        # - --bt-save-metadata: Lưu lại file torrent khi tải xong metadata
        # - --save-session & --input-file: Lưu và phục hồi tiến trình tải khi tắt mở lại app
        # - Giả lập qBittorrent: Tránh bị bóp/chặn bởi các swarm quốc tế
        # - --stop-with-process: Windows tự hủy aria2c tức thì khi PID của app.py tắt (Zero Zombie)
        cmd = [
            self.aria2c_exe,
            "--enable-rpc=true",
            f"--rpc-listen-port={self.rpc_port}",
            f"--rpc-secret={self.rpc_secret}",
            "--rpc-allow-origin-all=true",
            f"--stop-with-process={os.getpid()}",
            f"--input-file={session_file}",
            f"--save-session={session_file}",
            "--save-session-interval=30",
            "--peer-id-prefix=-qB4600-",
            "--user-agent=qBittorrent/4.6.0",
            "--peer-agent=qBittorrent/4.6.0",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--file-allocation=none",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--disable-ipv6=true",
            "--async-dns=false",
            "--follow-torrent=mem",
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            "--bt-enable-lpd=true",
            "--bt-max-peers=200",
            "--bt-tracker-connect-timeout=10",
            "--bt-tracker-timeout=10",
            "--bt-min-crypto-level=plain",
            "--bt-require-crypto=false",
            "--bt-save-metadata=true",
            "--bt-load-saved-metadata=true",
            f"--bt-tracker={','.join(BEST_PUBLIC_TRACKERS)}",
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

        # Đọc cấu hình Menu Cài Đặt để áp dụng ngay khi khởi động daemon
        limit_kb, max_concurrent = self._read_download_settings()
        if limit_kb > 0:
            cmd.append(f"--max-overall-download-limit={limit_kb}K")
        if max_concurrent > 0:
            cmd.append(f"--max-concurrent-downloads={max_concurrent}")

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
        """Dừng tiến trình aria2c khi tắt ứng dụng, lưu lại session."""
        if self.daemon_proc:
            try:
                self._call_rpc("aria2.saveSession")
            except Exception:
                pass
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
    # 2.5. PHÂN GIẢI METADATA TORRENT SIÊU TỐC QUA HTTPS CACHES
    # ========================================================
    def resolve_torrent_metadata(self, info_hash: str, timeout: float = 3.5) -> Optional[bytes]:
        """
        Tải file .torrent từ các kho HTTPS Cache toàn cầu (itorrents, torrage, btcache...).
        Bỏ qua hoàn toàn giai đoạn chờ DHT metadata của aria2c, nạp thẳng file data tải tức thì.
        """
        if not info_hash:
            return None

        # Chuẩn hóa SHA1 Hex40 từ Base32 nếu cần
        clean_hash = info_hash.strip().upper()
        if len(clean_hash) == 32:
            try:
                clean_hash = base64.b32decode(clean_hash).hex().upper()
            except Exception:
                pass

        if len(clean_hash) != 40 or not re.match(r"^[0-9A-F]{40}$", clean_hash):
            return None

        # 1. Kiểm tra cache local trên máy
        local_torrent_path = os.path.join(self.torrents_dir, f"{clean_hash}.torrent")
        if os.path.isfile(local_torrent_path) and os.path.getsize(local_torrent_path) > 100:
            try:
                with open(local_torrent_path, "rb") as f:
                    data = f.read()
                    if data[:2] == b"\x1f\x8b":
                        data = gzip.decompress(data)
                    if data.startswith(b"d") and b"info" in data:
                        return data
            except Exception:
                pass

        # 2. Truy vấn các HTTPS Cache mirrors (Không bị nhà mạng VN chặn UDP)
        cache_mirrors = [
            f"https://itorrents.org/torrent/{clean_hash}.torrent",
            f"http://itorrents.org/torrent/{clean_hash}.torrent",
            f"https://torrage.info/torrent.php?h={clean_hash}",
            f"https://btcache.me/torrent/{clean_hash}",
        ]

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/x-bittorrent, */*",
        }

        for url in cache_mirrors:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                    raw_data = resp.read()
                    if not raw_data or len(raw_data) < 50:
                        continue
                    # Giải nén nếu server trả về gzip
                    if raw_data[:2] == b"\x1f\x8b":
                        try:
                            raw_data = gzip.decompress(raw_data)
                        except Exception:
                            pass
                    # Bencoded dictionary bắt đầu bằng 'd' (d8:announce, d4:info, v.v.)
                    if raw_data.startswith(b"d") and b"info" in raw_data:
                        # Lưu vào local cache để dùng lại
                        try:
                            with open(local_torrent_path, "wb") as f:
                                f.write(raw_data)
                        except Exception:
                            pass
                        print(f"[TorrentDownloader] Phân giải thành công .torrent ({len(raw_data)} bytes) từ {url}")
                        return raw_data
            except Exception:
                continue

        return None

    def _background_metadata_booster(
        self,
        old_gid: str,
        info_hash: str,
        target_dir: str,
        title: str,
        game_id: str,
        repacker: str,
        raw_uri: str
    ):
        """
        Luồng nền ngầm phân giải metadata torrent qua HTTPS cache nếu aria2c bị nghẽn swarm DHT.
        Khi tìm thấy .torrent, tự động chuyển đổi sang task tải file thật mượt mà.
        """
        if not info_hash or len(info_hash) != 40:
            return

        for attempt in range(12):  # Thử trong tối đa 60 giây
            time.sleep(2 if attempt == 0 else 5)
            # Kiểm tra xem task cũ còn trong metadata và còn đang kẹt metadata không
            with self.lock:
                if old_gid not in self.task_metadata:
                    return
            status_obj = self._call_rpc("aria2.tellStatus", [old_gid, ["status", "totalLength", "followedBy"]])
            if not status_obj:
                return
            raw_st = status_obj.get("status")
            tot_len = int(status_obj.get("totalLength", 0))
            if raw_st not in ("active", "waiting"):
                return
            if tot_len > 0 or status_obj.get("followedBy"):
                # aria2c đã tự lấy được file data từ swarm
                return

            torrent_bytes = self.resolve_torrent_metadata(info_hash, timeout=4.0)
            if torrent_bytes:
                b64_str = base64.b64encode(torrent_bytes).decode("ascii")
                booster_opts = {
                    "dir": target_dir,
                    "file-allocation": "none",
                    "allow-overwrite": "true",
                    "auto-file-renaming": "false",
                    "seed-time": "0",
                    "bt-max-peers": "200",
                }
                new_gid = self._call_rpc("aria2.addTorrent", [b64_str, [], booster_opts])
                if new_gid:
                    print(f"[TorrentDownloader] Tự động hồi phục task kẹt {old_gid} -> {new_gid} thành công!")
                    with self.lock:
                        meta = self.task_metadata.pop(old_gid, {})
                        meta["gid"] = new_gid
                        meta["migrated_from"] = old_gid
                        meta["info_hash"] = info_hash
                        meta["title"] = title or meta.get("title", "")
                        meta["game_title"] = title or meta.get("game_title", "")
                        meta["release_title"] = title or meta.get("release_title", "")
                        meta["game_id"] = game_id or meta.get("game_id", "")
                        meta["repacker"] = repacker or meta.get("repacker", "")
                        meta["uri"] = raw_uri or meta.get("uri", "")
                        meta["download_dir"] = target_dir
                        meta["started_at"] = int(time.time())
                        meta["status"] = "active"
                        self.task_metadata[new_gid] = meta
                        self._save_task_metadata()

                    # Hủy task cũ bị nghẽn metadata
                    try:
                        self._call_rpc("aria2.forceRemove", [old_gid])
                    except Exception:
                        pass
                    try:
                        self._call_rpc("aria2.removeDownloadResult", [old_gid])
                    except Exception:
                        pass
                    return

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
        Tự động truy vấn HTTPS Cache để nạp file torrent ngay tức thì mà không cần chờ DHT.
        """
        if not uri:
            return {"success": False, "message": "Đường dẫn tải (URI) không được để trống!"}

        final_title = title or release_title or game_title or kwargs.get("name") or "Tệp Game Repack"
        final_dir = custom_dir or save_dir or kwargs.get("download_dir") or ""
        target_dir = os.path.abspath(final_dir) if final_dir else self.default_download_dir
        os.makedirs(target_dir, exist_ok=True)

        clean_uri = html.unescape(uri.strip()).replace("&#038;", "&").replace("&amp;", "&")
        info_hash = ""

        # Chuẩn hóa Magnet URI và Inject Trackers
        if clean_uri.startswith("magnet:?"):
            btih_match = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", clean_uri, re.IGNORECASE)
            if btih_match:
                raw_hash = btih_match.group(1).strip()
                if len(raw_hash) == 32:
                    try:
                        raw_bytes = base64.b32decode(raw_hash.upper())
                        info_hash = raw_bytes.hex().upper()
                    except Exception:
                        info_hash = raw_hash.upper()
                elif len(raw_hash) == 40 and bool(re.match(r"^[0-9a-fA-F]{40}$", raw_hash)):
                    info_hash = raw_hash.upper()
                else:
                    info_hash = hashlib.sha1(raw_hash.encode("utf-8")).hexdigest().upper()

                if raw_hash != info_hash:
                    clean_uri = clean_uri.replace(f"xt=urn:btih:{raw_hash}", f"xt=urn:btih:{info_hash}")

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
            "dir": target_dir,
            "file-allocation": "none",
            "allow-overwrite": "true",
            "auto-file-renaming": "false",
            "seed-time": "0",
            "bt-max-peers": "200",
            "bt-tracker-connect-timeout": "10",
            "bt-tracker-timeout": "10",
        }

        # BƯỚC ĐỘT PHÁ: Thử phân giải ngay file .torrent qua HTTPS Cache Mirrors
        # Giúp aria2c bỏ qua hoàn toàn DHT metadata handshake và tải thẳng file data
        gid = None
        torrent_bytes = None
        if info_hash:
            torrent_bytes = self.resolve_torrent_metadata(info_hash, timeout=3.0)

        if torrent_bytes:
            b64_str = base64.b64encode(torrent_bytes).decode("ascii")
            gid = self._call_rpc("aria2.addTorrent", [b64_str, [], options])
            if gid:
                print(f"[TorrentDownloader] Đã kích hoạt tải trực tiếp bằng .torrent cho '{final_title}' (GID: {gid})")

        # Nếu không lấy được .torrent ngay trong 3s, nạp magnet bình thường vào aria2c
        if not gid:
            self._last_error = ""
            gid = self._call_rpc("aria2.addUri", [[clean_uri], options])
            if not gid:
                err_msg = self._last_error or "Không thể kết nối với engine tải aria2c hoặc link magnet bị lỗi cấu trúc!"
                return {"success": False, "message": err_msg}

            # Kích hoạt luồng ngầm Metadata Booster để tự động lấy .torrent nếu aria2c bị nghẽn DHT
            if info_hash:
                t = threading.Thread(
                    target=self._background_metadata_booster,
                    args=(gid, info_hash, target_dir, final_title, game_id, repacker, uri),
                    daemon=True
                )
                t.start()

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
        # Hủy task triệt để bằng forceRemove + remove + removeDownloadResult
        try:
            self._call_rpc("aria2.forceRemove", [gid])
        except Exception:
            pass
        try:
            self._call_rpc("aria2.remove", [gid])
        except Exception:
            pass
        try:
            self._call_rpc("aria2.removeDownloadResult", [gid])
        except Exception:
            pass

        with self.lock:
            self._boosting_gids.discard(gid)
            # Nếu task có task con sinh ra từ metadata, hủy luôn task con
            child_gids = [k for k, v in self.task_metadata.items() if v.get("parent_gid") == gid]
            for cg in child_gids:
                self._boosting_gids.discard(cg)
                try:
                    self._call_rpc("aria2.forceRemove", [cg])
                except Exception:
                    pass
                try:
                    self._call_rpc("aria2.removeDownloadResult", [cg])
                except Exception:
                    pass
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

            # NẾU TASK KHÔNG CÒN TRONG task_metadata THÌ XÓA KẾT QUẢ VÀ BỎ QUA
            if gid not in self.task_metadata:
                try:
                    self._call_rpc("aria2.removeDownloadResult", [gid])
                except Exception:
                    pass
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
                # TỰ ĐỘNG CỨU TÁC VỤ KẸT METADATA:
                if gid not in self._boosting_gids:
                    task_uri = meta.get("uri", "")
                    h_match = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", task_uri, re.IGNORECASE)
                    if h_match:
                        h_val = h_match.group(1).strip()
                        if len(h_val) == 32:
                            try:
                                h_val = base64.b32decode(h_val.upper()).hex().upper()
                            except Exception:
                                pass
                        elif len(h_val) != 40:
                            h_val = hashlib.sha1(h_val.encode("utf-8")).hexdigest().upper()
                        else:
                            h_val = h_val.upper()

                        if len(h_val) == 40:
                            self._boosting_gids.add(gid)
                            t = threading.Thread(
                                target=self._background_metadata_booster,
                                args=(
                                    gid,
                                    h_val,
                                    meta.get("download_dir", self.default_download_dir),
                                    meta.get("title", ""),
                                    meta.get("game_id", ""),
                                    meta.get("repacker", ""),
                                    task_uri
                                ),
                                daemon=True
                            )
                            t.start()
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

            # Kiểm tra trạng thái kẹt/stalled (sau 45s mà 0 peers, 0 speed)
            started_at = int(meta.get("started_at", 0))
            is_stalled = False
            stalled_reason = ""
            if (raw_status in ("active", "waiting") or is_metadata_stage):
                if connections == 0 and spd == 0 and comp == 0:
                    if started_at > 0 and (time.time() - started_at) > 45:
                        is_stalled = True
                        stalled_reason = "Không có Seeder hoặc bị nhà mạng chặn kết nối. Hãy thử mở bằng qBittorrent hoặc tìm nguồn khác."

            # Nếu đã hoàn tất, tự động phân tích cấu trúc file/thư mục tải về
            inspection_info = None
            if display_status == "complete":
                if gid not in self._inspection_cache:
                    target_inspect = downloaded_path or meta.get("download_dir", self.default_download_dir)
                    self._inspection_cache[gid] = self.inspect_download_contents(target_inspect)
                inspection_info = self._inspection_cache.get(gid)

            # Cung cấp song song cả hai bộ tên thuộc tính để frontend luôn nhận đúng 100%
            results.append({
                "gid": gid,
                "title": final_title,
                "game_id": meta.get("game_id", ""),
                "game_title": final_title,
                "release_title": meta.get("release_title", final_title),
                "repacker": meta.get("repacker", ""),
                "uri": meta.get("uri", ""),
                "status": display_status,
                "raw_status": raw_status,
                "is_metadata": is_metadata_stage,
                "is_stalled": is_stalled,
                "stalled_reason": stalled_reason,
                "inspection": inspection_info,
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
    # 4. MỞ BẰNG PHẦN MỀM NGOÀI (QBITTORRENT / UTORRENT) & HẬU XỬ LÝ
    # ========================================================
    def inspect_download_contents(self, path_or_gid: str) -> Dict[str, Any]:
        """
        Kiểm tra nội dung file/thư mục tải về để đưa ra hành động cài đặt thông minh:
        - action_type: 'setup' | 'archive' | 'ready_to_play' | 'folder' | 'none'
        - setup_exe: Đường dẫn file setup.exe nếu có
        - game_exe: Đường dẫn file exe của game nếu có
        - archive_file: Đường dẫn file nén nếu có
        - target_dir: Thư mục chứa
        """
        target_path = ""
        if path_or_gid in self.task_metadata:
            meta = self.task_metadata[path_or_gid]
            target_path = meta.get("download_dir", "")
        elif os.path.exists(path_or_gid):
            target_path = path_or_gid

        if not target_path or not os.path.exists(target_path):
            return {
                "exists": False,
                "action_type": "none",
                "message": "Không tìm thấy đường dẫn tải về."
            }

        # Nếu là file đơn lẻ
        if os.path.isfile(target_path):
            low = target_path.lower()
            if low.endswith((".zip", ".7z", ".rar", ".iso", ".tar", ".gz")):
                return {
                    "exists": True,
                    "action_type": "archive",
                    "archive_file": target_path,
                    "target_dir": os.path.dirname(target_path),
                    "filename": os.path.basename(target_path),
                    "title": "Tệp nén game"
                }
            elif low.endswith(".exe"):
                fn = os.path.basename(low)
                if any(k in fn for k in ("setup", "install", "autorun")):
                    return {
                        "exists": True,
                        "action_type": "setup",
                        "setup_exe": target_path,
                        "target_dir": os.path.dirname(target_path),
                        "filename": os.path.basename(target_path),
                        "title": "Bộ cài đặt Game (Setup.exe)"
                    }
                else:
                    return {
                        "exists": True,
                        "action_type": "ready_to_play",
                        "game_exe": target_path,
                        "target_dir": os.path.dirname(target_path),
                        "filename": os.path.basename(target_path),
                        "title": "File thực thi Game"
                    }

        # Nếu là thư mục: Quét tìm các file bên trong (độ sâu 2)
        setup_exes = []
        game_exes = []
        archives = []

        try:
            for root, dirs, files in os.walk(target_path):
                rel = os.path.relpath(root, target_path)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
                if depth >= 2:
                    dirs[:] = []

                for f in files:
                    fp = os.path.join(root, f)
                    flow = f.lower()

                    if flow.endswith((".zip", ".7z", ".rar", ".iso")):
                        archives.append(fp)
                    elif flow.endswith(".exe"):
                        if any(k in flow for k in ("setup", "install", "gog_galaxy", "autorun")):
                            setup_exes.append(fp)
                        elif not any(k in flow for k in ("unins", "crash", "helper", "redist", "dxsetup", "vcredist", "dotnet", "patch")):
                            try:
                                sz = os.path.getsize(fp)
                            except OSError:
                                sz = 0
                            game_exes.append((fp, sz))
        except Exception as e:
            print(f"[TorrentDownloader] Lỗi quét thư mục: {e}")

        # Phân loại ưu tiên:
        if setup_exes:
            return {
                "exists": True,
                "action_type": "setup",
                "setup_exe": setup_exes[0],
                "target_dir": target_path,
                "filename": os.path.basename(setup_exes[0]),
                "title": "Bộ cài đặt Setup.exe"
            }

        if archives and not game_exes:
            return {
                "exists": True,
                "action_type": "archive",
                "archive_file": archives[0],
                "target_dir": target_path,
                "filename": os.path.basename(archives[0]),
                "title": "Tệp nén game"
            }

        if game_exes:
            game_exes.sort(key=lambda x: x[1], reverse=True)
            best_exe = game_exes[0][0]
            return {
                "exists": True,
                "action_type": "ready_to_play",
                "game_exe": best_exe,
                "target_dir": target_path,
                "filename": os.path.basename(best_exe),
                "title": "Game sẵn sàng chơi"
            }

        return {
            "exists": True,
            "action_type": "folder",
            "target_dir": target_path,
            "filename": os.path.basename(target_path),
            "title": "Thư mục tải về"
        }

    def extract_archive(self, archive_path: str, dest_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Giải nén file nén (.zip, .7z, .rar, .tar, .iso).
        Sử dụng zipfile cho file .zip, tar.exe của Windows cho tar/iso/zip,
        hoặc 7-Zip/WinRAR nếu có sẵn trên máy.
        """
        if not archive_path or not os.path.isfile(archive_path):
            return {"success": False, "message": "File nén không tồn tại."}

        target_dir = dest_dir or os.path.join(
            os.path.dirname(archive_path),
            os.path.splitext(os.path.basename(archive_path))[0]
        )
        os.makedirs(target_dir, exist_ok=True)

        low = archive_path.lower()
        if low.endswith(".zip"):
            try:
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(target_dir)
                return {"success": True, "dest_dir": target_dir, "message": "Đã giải nén thành công!"}
            except Exception:
                pass

        candidate_extractors = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
            r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
            r"C:\Windows\System32\tar.exe"
        ]

        for ext_tool in candidate_extractors:
            if os.path.isfile(ext_tool):
                try:
                    if "7z.exe" in ext_tool.lower():
                        cmd = [ext_tool, "x", archive_path, f"-o{target_dir}", "-y"]
                    elif "winrar.exe" in ext_tool.lower():
                        cmd = [ext_tool, "x", "-ibck", "-y", archive_path, target_dir]
                    elif "tar.exe" in ext_tool.lower() and not low.endswith((".rar", ".7z")):
                        cmd = [ext_tool, "-xf", archive_path, "-C", target_dir]
                    else:
                        continue

                    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
                    if proc.returncode == 0:
                        return {"success": True, "dest_dir": target_dir, "message": "Đã giải nén thành công!"}
                except Exception as e:
                    print(f"[TorrentDownloader] Giải nén bằng {ext_tool} lỗi: {e}")

        if low.endswith(".zip"):
            try:
                ps_cmd = f"Expand-Archive -LiteralPath '{archive_path}' -DestinationPath '{target_dir}' -Force"
                proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], timeout=180)
                if proc.returncode == 0:
                    return {"success": True, "dest_dir": target_dir, "message": "Đã giải nén xong!"}
            except Exception:
                pass

        return {
            "success": False,
            "message": "Không tìm thấy công cụ giải nén phù hợp (.7z/.rar cần có 7-Zip hoặc WinRAR trên máy)."
        }

    def run_installer(self, installer_path: str) -> Dict[str, Any]:
        """Khởi chạy file setup.exe không chặn tiến trình app."""
        if not installer_path or not os.path.isfile(installer_path):
            return {"success": False, "message": "File cài đặt không tồn tại."}
        try:
            cwd = os.path.dirname(installer_path)
            subprocess.Popen([installer_path], cwd=cwd, shell=True)
            return {"success": True, "message": "Đã khởi chạy bộ cài đặt Game!"}
        except Exception as e:
            return {"success": False, "message": f"Không thể chạy file cài đặt: {e}"}

    @staticmethod
    def open_external_torrent(uri: str) -> Dict[str, Any]:
        """Gọi ứng dụng Torrent hoặc Trình duyệt ngoài."""
        if not uri:
            return {"success": False, "message": "URI trống!"}
        try:
            uri = uri.strip()
            if uri.startswith(('http://', 'https://')):
                # Nếu là link trực tiếp file .torrent, tải về thư mục tạm và mở thẳng bằng phần mềm Torrent mặc định
                if uri.lower().endswith('.torrent') or '.torrent?' in uri.lower():
                    try:
                        import tempfile, urllib.request, urllib.parse
                        temp_dir = tempfile.gettempdir()
                        torrent_filename = os.path.basename(urllib.parse.urlparse(uri).path) or "download.torrent"
                        if not torrent_filename.endswith(".torrent"):
                            torrent_filename += ".torrent"
                        local_path = os.path.join(temp_dir, torrent_filename)
                        req = urllib.request.Request(uri, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as r, open(local_path, "wb") as f:
                            f.write(r.read())
                        os.startfile(local_path)
                        return {"success": True, "message": "Đã mở file torrent trong phần mềm tải torrent của máy!"}
                    except Exception as te:
                        print(f"[open_external_torrent] Download torrent file warning: {te}")
                import webbrowser
                webbrowser.open(uri)
                return {"success": True, "message": "Đã mở liên kết trong Trình duyệt Web của bạn!"}
            else:
                os.startfile(uri)
                return {"success": True, "message": "Đã gửi link tới ứng dụng Torrent trên máy bạn!"}
        except Exception as e:
            return {"success": False, "message": f"Không thể mở ứng dụng: {e}"}

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

    def set_speed_limit(self, limit_kb: int = 0) -> bool:
        """Đặt giới hạn tốc độ tải xuống tối đa (0 = Không giới hạn, >0 = KB/s)."""
        try:
            val = "0" if limit_kb <= 0 else f"{limit_kb}K"
            res = self._call_rpc("aria2.changeGlobalOption", [{"max-overall-download-limit": val}])
            return res == "OK"
        except Exception as e:
            print(f"[TorrentDownloader] Lỗi đặt giới hạn tốc độ: {e}")
            return False

    def set_max_concurrent(self, max_concurrent: int = 3) -> bool:
        """Đặt số lượng file tải đồng thời tối đa (1-10)."""
        try:
            val = str(max(1, min(10, max_concurrent)))
            res = self._call_rpc("aria2.changeGlobalOption", [{"max-concurrent-downloads": val}])
            return res == "OK"
        except Exception as e:
            print(f"[TorrentDownloader] Lỗi đặt số lượng tải đồng thời: {e}")
            return False


# Tương thích ngược với tên gọi cũ
TorrentDownloadManager = TorrentDownloader
