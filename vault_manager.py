"""
CỔ NGỮ (VietModHub Pro) - Portable Save Vault Manager (.congu_save)
Cơ chế "Hồ Sơ Di Động Hợp Nhất" (Single-File Portable Vault):
Gom toàn bộ Save Game, Thành tựu (Achievements), Giờ chơi (Playtime)
và Hồ sơ cá nhân vào 1 tệp tin container duy nhất (*.congu_save).

Hỗ trợ:
1. Portable Path Macros ({DOCUMENTS}, {APPDATA}, {GAME_ROOT}...) giúp đem sang mọi PC khác nhau.
2. Ghi đè nguyên tử (Atomic Update) chống hỏng file khi mất điện.
3. Chống Zip-Slip & Path Traversal bảo mật tuyệt đối.
4. Tích hợp trực tiếp với Google Drive (Đồng bộ 1 file duy nhất siêu tốc).
"""

import io
import os
import json
import re
import time
import base64
import shutil
import zipfile
import hashlib
import tempfile
import threading
from datetime import datetime, timezone

VAULT_VERSION = "2.0"
VAULT_MAGIC_HEADER = "CONGU_SAVE_VAULT"

# Thư mục con trong save game chứa cache/tài nguyên khổng lồ - không bao giờ pack.
SKIP_SAVE_DIR_KEYWORDS = {"packedsongs", "shader", "webcache", "crashdumps", "gpu_cache"}
# File save thực tế không bao giờ là gói tài nguyên > 25MB.
MAX_PACKABLE_SAVE_FILE_BYTES = 25 * 1024 * 1024

# File tạm còn sót lại khi đóng gói vault bị gián đoạn (crash/mất điện).
STALE_TEMP_PATTERNS = ("*.congu_save_tmp", "congu-save-*.zip*")


def cleanup_stale_vault_temp(dirs=None, min_age_seconds: int = 600) -> dict:
    """
    Dọn các file tạm còn sót từ lần đóng gói vault/upload bị gián đoạn.

    Chỉ xóa file cũ hơn ``min_age_seconds`` để không đụng vào file tạm của
    tiến trình đang chạy. Trả về {"removed": int, "freed_bytes": int, "freed_mb": float}.
    """
    import glob
    removed = 0
    freed_bytes = 0
    now = time.time()
    seen = set()
    for directory in dirs or ():
        if not directory or not os.path.isdir(directory):
            continue
        for pattern in STALE_TEMP_PATTERNS:
            for path in glob.glob(os.path.join(directory, pattern)):
                try:
                    real = os.path.abspath(path)
                    if real in seen or not os.path.isfile(real):
                        continue
                    seen.add(real)
                    st = os.stat(real)
                    if now - st.st_mtime < max(0, min_age_seconds):
                        continue
                    os.remove(real)
                    removed += 1
                    freed_bytes += st.st_size
                except OSError:
                    continue
    return {
        "removed": removed,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 1),
    }


def _safe_restore_destination(base_dir: str, relative_path: str, label: str) -> str:
    """Trả về đường dẫn restore nằm dưới base, kể cả khi có symlink/junction.

    ``realpath`` phân giải các ancestor đang tồn tại nên một entry ZIP không thể
    lợi dụng junction/symlink để ghi ra ngoài thư mục save. So sánh normcase
    giữ hành vi chính xác trên Windows không phân biệt hoa/thường.
    """
    if not base_dir:
        raise ValueError(f"Thư mục đích restore không hợp lệ: {label}")
    rel = str(relative_path or "").replace("\\", "/")
    pieces = rel.split("/")
    if not rel or rel.startswith("/") or any(part in ("", ".", "..") or ":" in part for part in pieces):
        raise ValueError(f"Đường dẫn không an toàn trong file save: {label}")
    base_real = os.path.realpath(base_dir)
    destination = os.path.realpath(os.path.join(base_real, *pieces))
    try:
        common = os.path.commonpath([os.path.normcase(base_real), os.path.normcase(destination)])
    except ValueError as exc:
        raise ValueError(f"Đường dẫn không an toàn trong file save: {label}") from exc
    if common != os.path.normcase(base_real):
        raise ValueError(f"Đường dẫn không an toàn trong file save: {label}")
    return destination


class VaultRestoreRecoveryError(RuntimeError):
    """Rollback Vault thất bại; giữ thư mục staging để người dùng còn dữ liệu phục hồi."""


class ConguSaveVault:
    """
    Quản lý đóng gói & giải nén toàn bộ Save Game, Thành tựu, Giờ chơi
    vào 1 tệp tin duy nhất (.congu_save) có thể mang sang mọi PC.
    """
    def __init__(self, vault_file_path: str):
        self.vault_path = os.path.abspath(vault_file_path)
        self.lock = threading.RLock()
        self._ensure_vault_initialized()

    def _cover_thumb_from_game(self, game_config: dict, game_stat: dict) -> str:
        """
        Tạo thumbnail WebP nhẹ (~15-30KB) nhúng vào manifest để game Ghost vẫn có
        ảnh bìa khi sang PC mới chưa có mạng hoặc chưa cài game.
        """
        cover_path = str(game_config.get("cover_fs_path") or "").strip()
        if not cover_path or not os.path.isfile(cover_path):
            return game_stat.get("cover_thumb_b64", "") or ""
        try:
            src_key = hashlib.sha1(cover_path.encode("utf-8", "ignore")).hexdigest()[:16]
            src_mtime = int(os.path.getmtime(cover_path))
            if (game_stat.get("cover_thumb_b64")
                    and game_stat.get("cover_src_key") == src_key
                    and game_stat.get("cover_src_mtime") == src_mtime):
                return game_stat["cover_thumb_b64"]

            from PIL import Image
            with Image.open(cover_path) as img:
                img = img.convert("RGB")
                img.thumbnail((180, 270))
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=62, method=4)
                data = buf.getvalue()

            if len(data) > 90 * 1024:
                return game_stat.get("cover_thumb_b64", "") or ""

            game_stat["cover_src_key"] = src_key
            game_stat["cover_src_mtime"] = src_mtime
            game_stat["cover_thumb_b64"] = "data:image/webp;base64," + base64.b64encode(data).decode("ascii")
            return game_stat["cover_thumb_b64"]
        except Exception:
            return game_stat.get("cover_thumb_b64", "") or ""

    def _write_sync_marker(self, game_root: str):
        """Đánh dấu thư mục game đã đồng bộ với phiên bản vault hiện tại."""
        if not game_root or not os.path.isdir(game_root):
            return
        try:
            marker = {
                "vault_mtime": int(os.path.getmtime(self.vault_path)),
                "synced_at": int(time.time()),
            }
            with open(os.path.join(game_root, ".congu_restored.json"), "w", encoding="utf-8") as f:
                json.dump(marker, f)
        except OSError:
            pass

    # ==========================================
    # 1. CƠ CHẾ ÁNH XẠ ĐƯỜNG DẪN ĐA MÁY TÍNH (PORTABLE PATH MACROS)
    # ==========================================
    def get_path_macros(self, game_root: str = "") -> dict:
        """Lấy bảng ánh xạ các Macro tương đối theo người dùng Windows hiện tại."""
        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        public_dir = os.environ.get("PUBLIC", r"C:\Users\Public")

        # Tìm thư mục Steam Userdata phổ biến
        steam_userdata = ""
        for steam_candidate in [
            r"C:\Program Files (x86)\Steam\userdata",
            r"C:\Program Files\Steam\userdata",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Steam", "userdata")
        ]:
            if os.path.exists(steam_candidate):
                steam_userdata = steam_candidate
                break

        return {
            "{DOCUMENTS}": os.path.join(user_profile, "Documents"),
            "{APPDATA}": os.environ.get("APPDATA", os.path.join(user_profile, "AppData", "Roaming")),
            "{LOCALAPPDATA}": os.environ.get("LOCALAPPDATA", os.path.join(user_profile, "AppData", "Local")),
            "{LOCALAPPDATA_LOW}": os.path.join(user_profile, "AppData", "LocalLow"),
            "{USERPROFILE}": user_profile,
            "{SAVEDGAMES}": os.path.join(user_profile, "Saved Games"),
            "{PUBLIC_DOCS}": os.path.join(public_dir, "Documents"),
            "{GAME_ROOT}": game_root or "",
            "{STEAM_USERDATA}": steam_userdata
        }

    def resolve_macro_path(self, raw_path: str, game_root: str = "") -> str:
        """
        Dịch đường dẫn từ Macro hoặc biến môi trường sang đường dẫn thực tế trên PC này:
        - Hỗ trợ {DOCUMENTS}, {APPDATA}, {GAME_ROOT}...
        - Hỗ trợ %USERPROFILE%, %APPDATA%, <GameDir>, <SteamUserdata>...
        """
        if not raw_path:
            return ""

        resolved = raw_path

        # 1. Chuyển đổi các thẻ kiểu <GameDir> / <SteamUserdata> sang Macro
        if "<GameDir>" in resolved and game_root:
            resolved = resolved.replace("<GameDir>", game_root)
        if "%SAVEDGAMES%" in resolved:
            user_prof = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            resolved = resolved.replace("%SAVEDGAMES%", os.path.join(user_prof, "Saved Games"))

        # 2. Thay thế các Macro {DOCUMENTS}...
        macros = self.get_path_macros(game_root)
        for macro, real_dir in macros.items():
            if macro in resolved and real_dir:
                resolved = resolved.replace(macro, real_dir)

        # 3. Phân giải biến môi trường %VAR% của Windows
        resolved = os.path.expandvars(resolved)
        return os.path.normpath(resolved)

    def path_to_macro(self, real_path: str, game_root: str = "") -> str:
        """Chuyển đổi đường dẫn tuyệt đối dưới máy thành Macro độc lập với tên User Windows."""
        if not real_path:
            return ""
        norm_real = os.path.normcase(os.path.abspath(real_path))
        macros = self.get_path_macros(game_root)

        # Ưu tiên các macro dài hơn trước để khớp chính xác nhất
        sorted_macros = sorted(macros.items(), key=lambda x: len(x[1]), reverse=True)
        for macro, real_dir in sorted_macros:
            if not real_dir:
                continue
            norm_dir = os.path.normcase(os.path.abspath(real_dir))
            if norm_real.startswith(norm_dir):
                rel_part = os.path.relpath(real_path, real_dir).replace("\\", "/")
                return f"{macro}/{rel_part}"
        return real_path.replace("\\", "/")

    def macro_to_windows_hint(self, macro_path: str) -> str:
        """Đổi đường dẫn Macro sang dạng biến môi trường Windows để in trong hướng dẫn."""
        if not macro_path:
            return ""
        mapping = {
            "{DOCUMENTS}": "%USERPROFILE%\\Documents",
            "{PUBLIC_DOCS}": "%PUBLIC%\\Documents",
            "{LOCALAPPDATA_LOW}": "%USERPROFILE%\\AppData\\LocalLow",
            "{LOCALAPPDATA}": "%LOCALAPPDATA%",
            "{APPDATA}": "%APPDATA%",
            "{SAVEDGAMES}": "%USERPROFILE%\\Saved Games",
            "{STEAM_USERDATA}": "%ProgramFiles(x86)%\\Steam\\userdata",
            "{USERPROFILE}": "%USERPROFILE%",
            "{GAME_ROOT}": "<Thu muc cai game>",
        }
        text = str(macro_path).replace("\\", "/")
        for macro, win_path in mapping.items():
            if text.startswith(macro):
                return (win_path + text[len(macro):]).replace("/", "\\")
        return text.replace("/", "\\")

    # ==========================================
    # 2. KHỞI TẠO & ĐỌC THÔNG TIN MANIFEST CỦA KÉT
    # ==========================================
    def _ensure_vault_initialized(self):
        """Nếu file .congu_save chưa tồn tại, tạo mới với manifest chuẩn."""
        with self.lock:
            if not os.path.exists(self.vault_path):
                os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
                default_manifest = {
                    "vault_version": VAULT_VERSION,
                    "profile_version": "1.0",
                    "magic": VAULT_MAGIC_HEADER,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                    "player_name": os.environ.get("USERNAME", "Game Thủ CỔ NGỮ"),
                    "total_playtime_seconds": 0,
                    "total_achievements_count": 0,
                    "games": {}
                }
                with zipfile.ZipFile(self.vault_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("profile_manifest.json", json.dumps(default_manifest, indent=2, ensure_ascii=False))

    def read_manifest(self) -> dict:
        """Đọc thông tin tổng quan từ file .congu_save mà không cần giải nén."""
        with self.lock:
            if not os.path.exists(self.vault_path):
                self._ensure_vault_initialized()
            try:
                with zipfile.ZipFile(self.vault_path, "r") as zf:
                    if "profile_manifest.json" in zf.namelist():
                        data = json.loads(zf.read("profile_manifest.json").decode("utf-8"))
                        return data
            except Exception as e:
                print(f"[ConguSaveVault] Lỗi đọc manifest: {e}")
            return {
                "vault_version": VAULT_VERSION,
                "magic": VAULT_MAGIC_HEADER,
                "updated_at": int(time.time()),
                "player_name": os.environ.get("USERNAME", "Game Thủ CỔ NGỮ"),
                "games": {}
            }

    def update_manifest_only(self, new_manifest: dict) -> dict:
        """
        Ghi đè DUY NHẤT tệp profile_manifest.json bên trong .congu_save bằng cơ chế
        Atomic Update (tạo zip tạm -> os.replace), giữ nguyên 100% Save Game /
        Thành tựu / dữ liệu các game khác đang có trong Hồ Sơ.

        Dùng cho: player_id, localization_requests (Yêu cầu Việt hóa), custom_games...
        """
        with self.lock:
            if not isinstance(new_manifest, dict):
                return {"success": False, "error": "Manifest không hợp lệ (phải là dict)"}

            manifest = json.loads(json.dumps(new_manifest))  # Deep copy an toàn
            manifest["vault_version"] = manifest.get("vault_version") or VAULT_VERSION
            manifest["magic"] = manifest.get("magic") or VAULT_MAGIC_HEADER
            manifest["updated_at"] = int(time.time())
            manifest.setdefault("games", {})

            if not os.path.exists(self.vault_path):
                self._ensure_vault_initialized()

            vault_dir = os.path.dirname(self.vault_path) or "."
            os.makedirs(vault_dir, exist_ok=True)
            temp_fd, temp_zip_path = tempfile.mkstemp(suffix=".congu_save_tmp", dir=vault_dir)
            os.close(temp_fd)

            try:
                with zipfile.ZipFile(self.vault_path, "r") as old_zf, \
                     zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as new_zf:

                    # Giữ nguyên toàn bộ Save / Thành tựu, chỉ thay manifest
                    for item in old_zf.infolist():
                        if item.filename == "profile_manifest.json" or item.filename.endswith("/"):
                            continue
                        new_zf.writestr(item, old_zf.read(item.filename))

                    new_zf.writestr("profile_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

                os.replace(temp_zip_path, self.vault_path)
                return {"success": True, "updated_at": manifest["updated_at"], "vault_path": self.vault_path}
            except Exception as e:
                print(f"[ConguSaveVault] Lỗi cập nhật manifest: {e}")
                return {"success": False, "error": str(e)}
            finally:
                if os.path.exists(temp_zip_path):
                    try:
                        os.remove(temp_zip_path)
                    except OSError:
                        pass

    def get_vault_info(self) -> dict:
        """Lấy thông số chi tiết của file Vault hiện tại để hiển thị trên UI."""
        with self.lock:
            if not os.path.exists(self.vault_path):
                self._ensure_vault_initialized()

            sz = os.path.getsize(self.vault_path) if os.path.exists(self.vault_path) else 0
            mtime = os.path.getmtime(self.vault_path) if os.path.exists(self.vault_path) else 0
            manifest = self.read_manifest()

            # Tính tổng giờ chơi & thành tựu
            tot_playtime = 0
            tot_ach = 0
            games_info = {}
            for gid, gdata in manifest.get("games", {}).items():
                pts = gdata.get("playtime_seconds", 0)
                tot_playtime += pts
                achs = gdata.get("unlocked_achievements", [])
                tot_ach += len(achs)

                hrs = pts // 3600
                mins = (pts % 3600) // 60
                fmt_pt = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m" if mins > 0 else f"{pts}s"

                games_info[gid] = {
                    "title": gdata.get("title", gid),
                    "playtime_seconds": pts,
                    "formatted_playtime": fmt_pt,
                    "last_played": gdata.get("last_played"),
                    "achievements_count": len(achs),
                    "save_updated_at": gdata.get("save_updated_at", 0),
                    "save_size_bytes": gdata.get("save_size_bytes", 0),
                    "file_count": gdata.get("file_count", 0)
                }

            hrs = tot_playtime // 3600
            mins = (tot_playtime % 3600) // 60
            tot_playtime_str = f"{hrs} giờ {mins} phút" if hrs > 0 else f"{mins} phút"

            return {
                "vault_path": self.vault_path,
                "vault_filename": os.path.basename(self.vault_path),
                "vault_size_bytes": sz,
                "formatted_size": f"{sz / 1024:.1f} KB" if sz < 1048576 else f"{sz / 1048576:.2f} MB",
                "updated_at": int(mtime),
                "formatted_updated_at": datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M:%S") if mtime else "Chưa có",
                "player_name": manifest.get("player_name", "Game Thủ"),
                "total_games": len(manifest.get("games", {})),
                "total_playtime_str": tot_playtime_str,
                "total_achievements_count": tot_ach,
                "games": games_info
            }

    # ==========================================
    # 3. TRÍCH XUẤT CẤU HÌNH VỊ TRÍ SAVE & THÀNH TỰU TỪ GAME CONFIG
    # ==========================================
    def _extract_game_locations(self, game_config: dict, game_root: str = "") -> tuple:
        """
        Chuẩn hóa vị trí lưu save và thành tựu từ games.json:
        Tương thích cả 'vault_config' lẫn 'cloud_sync'/'achievement_sources'.
        """
        save_locs = []
        ach_locs = []
        exclude_patterns = []

        # 1. Từ vault_config nếu có
        if "vault_config" in game_config:
            vc = game_config["vault_config"]
            save_locs = vc.get("save_locations", [])
            ach_locs = vc.get("achievement_locations", [])
            exclude_patterns = vc.get("exclude_patterns", [])

        # 2. Tự động đối chiếu từ cloud_sync nếu chưa có vault_config
        if not save_locs and "cloud_sync" in game_config:
            cs = game_config["cloud_sync"]
            paths = cs.get("save_paths", [])
            for idx, p in enumerate(paths):
                save_locs.append({
                    "slot": f"slot_{idx+1}" if len(paths) > 1 else "main_saves",
                    "path": p
                })
            exclude_patterns = cs.get("exclude_patterns", ["*.bak", "*.tmp", "*.congu_bak"])
            ach_sources = cs.get("achievement_sources", [])
            for idx, a in enumerate(ach_sources):
                emu = "goldberg" if "goldberg" in a.lower() else ("codex" if "codex" in a.lower() else f"emu_{idx+1}")
                ach_locs.append({
                    "emu": emu,
                    "path": a
                })

                # 3. Smart Auto-Save Detector: Dò tìm mọi vị trí save thực tế (Steam Emu, Windows Saved Games, LocalLow, UE, Unity...)
        if not save_locs:
            try:
                from core.cloud_save.auto_save_detector import detect_game_save_locations
                detected = detect_game_save_locations(game_config, game_root)
                if detected:
                    save_locs.extend(detected)
                    if not exclude_patterns:
                        exclude_patterns = ["*.bak", "*.tmp", "*.congu_bak", "*.log", "CrashReport*"]
            except Exception as e:
                print(f"[ConguSaveVault] Auto-save detector error: {e}")

        return save_locs, ach_locs, exclude_patterns

    # ==========================================
    # 4. ĐÓNG GÓI NGUYÊN TỬ VÀO 1 FILE (.congu_save)
    # ==========================================
    def _compute_game_save_fingerprint(self, save_locs: list, game_root: str,
                                       exclude_patterns: list) -> str:
        """
        Fingerprint rẻ (relpath|size|mtime_ns) của đúng tập file sẽ được pack.

        Dùng để bỏ qua việc nén lại toàn bộ vault khi người dùng chỉ mở game
        rồi thoát mà không save gì. Chỉ đọc metadata, không đọc nội dung file.
        """
        hasher = hashlib.sha256()
        exclude_list = [str(p).lower() for p in (exclude_patterns or [])]
        for save_loc in save_locs or []:
            slot = save_loc.get("slot", "main_saves")
            real_path = self.resolve_macro_path(save_loc.get("path", ""), game_root)
            hasher.update(f"slot:{slot}\n".encode("utf-8"))
            if not real_path or not os.path.exists(real_path):
                hasher.update(b"<missing>\n")
                continue
            if os.path.isfile(real_path):
                try:
                    st = os.stat(real_path)
                    hasher.update(
                        f"F:{os.path.basename(real_path)}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8")
                    )
                except OSError:
                    hasher.update(b"<stat-error>\n")
                continue
            for root, dirs, files in os.walk(real_path):
                dirs[:] = [d for d in dirs if not any(k in d.lower() for k in SKIP_SAVE_DIR_KEYWORDS)]
                for f in sorted(files):
                    f_lower = f.lower()
                    if any(f_lower.endswith(ext.replace("*", "").lower()) for ext in exclude_list):
                        continue
                    full_p = os.path.join(root, f)
                    try:
                        st = os.stat(full_p)
                    except OSError:
                        continue
                    if st.st_size > MAX_PACKABLE_SAVE_FILE_BYTES:
                        continue
                    rel_p = os.path.relpath(full_p, real_path).replace("\\", "/")
                    hasher.update(f"D:{rel_p}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
        return hasher.hexdigest()

    def pack_game_to_vault(self, game_config: dict, game_root: str = "", added_playtime_sec: int = 0) -> dict:
        """
        Gom toàn bộ file save, thành tựu và cộng giờ chơi của game đưa vào file .congu_save.
        Sử dụng cơ chế Atomic Update (tạo zip tạm -> os.replace) để không bao giờ hỏng két.
        """
        with self.lock:
            game_id = game_config["id"]
            save_locs, ach_locs, exclude_patterns = self._extract_game_locations(game_config, game_root)
            manifest = self.read_manifest()

            game_stat = manifest["games"].get(game_id, {
                "title": game_config.get("vietnamese_title") or game_config.get("title", game_id),
                "playtime_seconds": 0,
                "last_played": None,
                "unlocked_achievements": [],
                "save_updated_at": 0,
                "save_size_bytes": 0,
                "file_count": 0
            })

            # 0. Metadata thư viện di động (Ghost Library + ảnh bìa nhúng)
            game_stat["title"] = game_config.get("vietnamese_title") or game_config.get("title") or game_stat.get("title", game_id)
            game_stat["steam_appid"] = str(game_config.get("steam_appid") or game_stat.get("steam_appid") or "")
            game_stat["cover_thumb_b64"] = self._cover_thumb_from_game(game_config, game_stat)
            if game_root:
                game_stat["last_installed_path"] = os.path.normpath(game_root).replace("\\", "/")
                game_stat["last_installed_at"] = int(time.time())

            vi_version = str(
                game_config.get("latest_version")
                or (game_config.get("translation_stats") or {}).get("version")
                or ""
            ).strip()
            vi_applied = bool(game_config.get("is_mod_installed"))
            vi_info = game_stat.get("vi_patch_info") if isinstance(game_stat.get("vi_patch_info"), dict) else {}
            vi_info.update({
                "applied": vi_applied,
                "version": vi_version or vi_info.get("version", ""),
                "patch_id": f"{game_id}_vi_{vi_version or 'unknown'}",
            })
            if vi_applied:
                vi_info["applied_at"] = int(time.time())
            game_stat["vi_patch_info"] = vi_info

            # 1. Cập nhật giờ chơi
            if added_playtime_sec > 0:
                game_stat["playtime_seconds"] = game_stat.get("playtime_seconds", 0) + added_playtime_sec
                game_stat["last_played"] = datetime.now(timezone.utc).isoformat()

            # 2. Quét thành tựu mở khóa
            unlocked_set = set(game_stat.get("unlocked_achievements", []))
            for ach_loc in ach_locs:
                real_ach_path = self.resolve_macro_path(ach_loc["path"], game_root)
                if os.path.exists(real_ach_path):
                    unlocked_set.update(self._parse_achievements_file(real_ach_path))
            game_stat["unlocked_achievements"] = sorted(list(unlocked_set))

            # 2.5. Bỏ qua viết lại vault nếu save + thành tựu không đổi
            # (mở game rồi thoát ngay). Đây là tối ưu lớn nhất: thay vì giải nén
            # + nén lại toàn bộ vault, chỉ đọc metadata và trả về ngay.
            try:
                save_fingerprint = self._compute_game_save_fingerprint(
                    save_locs, game_root, exclude_patterns
                )
            except Exception as e:
                save_fingerprint = ""
                print(f"[ConguSaveVault] Save fingerprint warning: {e}")

            if (
                save_fingerprint
                and not added_playtime_sec
                and game_stat.get("save_fingerprint") == save_fingerprint
                and set(game_stat.get("unlocked_achievements") or []) == unlocked_set
            ):
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "save_unchanged",
                    "game_id": game_id,
                    "files_packed": int(game_stat.get("file_count") or 0),
                    "total_bytes": int(game_stat.get("save_size_bytes") or 0),
                    "stat": game_stat,
                }

            # 3. Tạo file ZIP tạm cùng thư mục với Vault
            vault_dir = os.path.dirname(self.vault_path)
            temp_fd, temp_zip_path = tempfile.mkstemp(suffix=".congu_save_tmp", dir=vault_dir)
            os.close(temp_fd)

            try:
                prefix_to_replace = f"{game_id}/"
                total_bytes = 0
                files_packed = 0
                rotated_prev1_entries = 0

                with zipfile.ZipFile(self.vault_path, "r") as old_zf, \
                     zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as new_zf:

                    # ------------------------------------------------------------------
                    # TIME MACHINE: xoay vòng 3 thế hệ save của riêng game này
                    #   current  -> prev_1
                    #   prev_1   -> prev_2
                    #   prev_2   -> bỏ (thế hệ cũ nhất)
                    # Dữ liệu của các game khác được giữ nguyên tuyệt đối.
                    # ------------------------------------------------------------------
                    for item in old_zf.infolist():
                        name = item.filename
                        if name == "profile_manifest.json":
                            continue
                        if name.startswith(f"{game_id}/prev_2/"):
                            continue  # loại bỏ thế hệ cũ nhất
                        if name.startswith(f"{game_id}/prev_1/"):
                            new_zf.writestr(
                                f"{game_id}/prev_2/" + name[len(f"{game_id}/prev_1/"):],
                                old_zf.read(name),
                            )
                            continue
                        if name.startswith(f"{game_id}/saves/"):
                            new_zf.writestr(
                                f"{game_id}/prev_1/saves/" + name[len(f"{game_id}/saves/"):],
                                old_zf.read(name),
                            )
                            if not name.endswith("_meta.json"):
                                rotated_prev1_entries += 1
                            continue
                        if name.startswith(prefix_to_replace):
                            # achievements cũ của game này -> sẽ được ghi lại mới bên dưới
                            continue
                        # Dữ liệu của game khác
                        new_zf.writestr(item, old_zf.read(name))

                    # Đóng gói save game của game hiện tại
                    for save_loc in save_locs:
                        slot = save_loc.get("slot", "main_saves")
                        real_save_path = self.resolve_macro_path(save_loc["path"], game_root)
                        if not os.path.exists(real_save_path):
                            continue

                        # Lưu metadata đường dẫn gốc dạng macro
                        macro_path = self.path_to_macro(real_save_path, game_root)
                        meta_info = {
                            "macro_path": macro_path,
                            "original_type": "file" if os.path.isfile(real_save_path) else "directory",
                            "packed_at": int(time.time())
                        }
                        new_zf.writestr(f"{game_id}/saves/{slot}/_meta.json", json.dumps(meta_info, indent=2))

                        if os.path.isfile(real_save_path):
                            arcname = f"{game_id}/saves/{slot}/{os.path.basename(real_save_path)}"
                            new_zf.write(real_save_path, arcname)
                            total_bytes += os.path.getsize(real_save_path)
                            files_packed += 1
                        elif os.path.isdir(real_save_path):
                            # Bỏ qua các thư mục con chứa cache / gói tài nguyên / crash dump khổng lồ
                            skip_dir_keywords = SKIP_SAVE_DIR_KEYWORDS
                            for root, dirs, files in os.walk(real_save_path):
                                dirs[:] = [d for d in dirs if not any(k in d.lower() for k in skip_dir_keywords)]
                                for f in files:
                                    f_lower = f.lower()
                                    if any(f_lower.endswith(ext.replace("*", "").lower()) for ext in exclude_patterns):
                                        continue
                                    full_p = os.path.join(root, f)
                                    try:
                                        f_size = os.path.getsize(full_p)
                                    except Exception:
                                        continue
                                    # Bỏ qua tệp tin quá lớn (> 25MB) - file save thực tế không bao giờ là gói tài nguyên khổng lồ
                                    if f_size > MAX_PACKABLE_SAVE_FILE_BYTES:
                                        continue
                                    rel_p = os.path.relpath(full_p, real_save_path).replace("\\", "/")
                                    arcname = f"{game_id}/saves/{slot}/{rel_p}"
                                    new_zf.write(full_p, arcname)
                                    total_bytes += f_size
                                    files_packed += 1

                    # Đóng gói file gốc của Thành Tựu
                    for ach_loc in ach_locs:
                        emu_name = ach_loc.get("emu", "generic")
                        real_ach_path = self.resolve_macro_path(ach_loc["path"], game_root)
                        if os.path.isfile(real_ach_path):
                            arcname = f"{game_id}/achievements/{emu_name}/{os.path.basename(real_ach_path)}"
                            new_zf.write(real_ach_path, arcname)

                    if files_packed > 0:
                        game_stat["save_updated_at"] = int(time.time())
                        game_stat["save_size_bytes"] = total_bytes
                        game_stat["file_count"] = files_packed
                    game_stat["has_embedded_save"] = bool(int(game_stat.get("file_count") or 0) > 0)

                    # --- TIME MACHINE: ghi lại thông tin 3 thế hệ save vào manifest ---
                    try:
                        prev_revs = game_stat.get("revisions") or {}
                        prev1_info = prev_revs.get("current")
                        prev2_info = prev_revs.get("prev_1")
                        if prev1_info is None and rotated_prev1_entries > 0:
                            # Vault tạo trước khi có Time Machine: vẫn nhận diện được thế hệ trước
                            prev1_info = {
                                "packed_at": int(time.time()),
                                "files": rotated_prev1_entries,
                                "bytes": 0,
                            }
                        game_stat["revisions"] = {
                            "current": {
                                "packed_at": game_stat.get("save_updated_at", 0),
                                "files": game_stat.get("file_count", 0),
                                "bytes": game_stat.get("save_size_bytes", 0),
                            },
                            "prev_1": prev1_info,
                            "prev_2": prev2_info,
                        }
                    except Exception as e:
                        print(f"[Vault] Revisions metadata warning: {e}")

                    game_stat["save_fingerprint"] = save_fingerprint
                    manifest["games"][game_id] = game_stat
                    manifest["updated_at"] = int(time.time())
                    manifest.setdefault("profile_version", "1.0")
                    manifest["total_playtime_seconds"] = sum(g.get("playtime_seconds", 0) for g in manifest["games"].values())
                    manifest["total_achievements_count"] = sum(len(g.get("unlocked_achievements", [])) for g in manifest["games"].values())

                    new_zf.writestr("profile_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

                # Ghi đè nguyên tử
                os.replace(temp_zip_path, self.vault_path)
                self._write_sync_marker(game_root)
                return {
                    "success": True,
                    "game_id": game_id,
                    "files_packed": files_packed,
                    "total_bytes": total_bytes,
                    "stat": game_stat
                }
            finally:
                if os.path.exists(temp_zip_path):
                    try:
                        os.remove(temp_zip_path)
                    except OSError:
                        pass

    # ==========================================
    # 5. BUNG DỮ LIỆU (UNPACK) RA MÁY TÍNH
    # ==========================================
    def _apply_staged_restore_plan(self, plan: list, backup_suffix: str) -> tuple:
        """Áp dụng một batch restore đã stage với backup và rollback toàn bộ batch.

        Mỗi item gồm ``destination`` và ``staged``. File gốc được snapshot trong
        work dir trước *bất kỳ* lần ghi nào; nếu một lần replace lỗi, mọi file đã
        áp dụng trong batch được đưa về trạng thái trước giao dịch.
        """
        if not plan:
            return 0, 0

        work_dir = os.path.dirname(plan[0]["staged"])
        applied = []
        backups_created = 0
        preserve_work = False
        try:
            # A backup must never overwrite another destination in the same batch.
            # Resolve existing symlinks too: a backup alias can otherwise point at
            # a different save even though the lexical names are distinct.
            destinations = {os.path.normcase(os.path.realpath(item["destination"])) for item in plan}
            backup_paths = set()
            for item in plan:
                if item.get("backup_existing") and os.path.exists(item["destination"]):
                    backup_path = item["destination"] + backup_suffix
                    key = os.path.normcase(os.path.realpath(backup_path))
                    if key in destinations or key in backup_paths:
                        raise ValueError(f"Đường dẫn backup trùng file restore hoặc backup khác: {backup_path}")
                    backup_paths.add(key)
            # Chụp tất cả bản gốc trước khi ghi để lỗi backup không để lại batch nửa vời.
            for index, item in enumerate(plan):
                destination = item["destination"]
                item["old"] = None
                item["existed"] = os.path.exists(destination)
                if not item["existed"]:
                    continue
                item["old"] = os.path.join(work_dir, f"old-{index}")
                shutil.copy2(destination, item["old"])

            # Capture every original before creating any public backup.
            for item in plan:
                if item["existed"] and item.get("backup_existing"):
                    backup_path = item["destination"] + backup_suffix
                    fd, backup_tmp = tempfile.mkstemp(prefix=".congu-backup-", dir=os.path.dirname(backup_path) or ".")
                    os.close(fd)
                    try:
                        shutil.copy2(item["old"], backup_tmp)
                        os.replace(backup_tmp, backup_path)
                    finally:
                        if os.path.exists(backup_tmp):
                            os.remove(backup_tmp)
                    backups_created += 1

            for item in plan:
                destination = item["destination"]
                parent = os.path.dirname(destination) or "."
                os.makedirs(parent, exist_ok=True)
                fd, sibling = tempfile.mkstemp(prefix=".congu-restore-", dir=parent)
                try:
                    with os.fdopen(fd, "wb") as dst, open(item["staged"], "rb") as src:
                        shutil.copyfileobj(src, dst)
                    os.replace(sibling, destination)
                    applied.append(item)
                finally:
                    if os.path.exists(sibling):
                        os.remove(sibling)
            return len(applied), backups_created
        except Exception as error:
            failures = []
            for item in reversed(applied):
                try:
                    if item["existed"]:
                        destination = item["destination"]
                        fd, rollback_tmp = tempfile.mkstemp(prefix=".congu-rollback-", dir=os.path.dirname(destination) or ".")
                        os.close(fd)
                        try:
                            shutil.copy2(item["old"], rollback_tmp)
                            os.replace(rollback_tmp, destination)
                        finally:
                            if os.path.exists(rollback_tmp):
                                os.remove(rollback_tmp)
                    elif os.path.exists(item["destination"]):
                        os.remove(item["destination"])
                except Exception as rollback_error:
                    failures.append(f"{item['destination']}: {rollback_error}")
            if failures:
                preserve_work = True
                raise VaultRestoreRecoveryError(
                    f"Khôi phục Vault thất bại: {error}; rollback thất bại: "
                    f"{'; '.join(failures)}; dữ liệu phục hồi: {work_dir}"
                ) from error
            raise
        finally:
            if not preserve_work:
                shutil.rmtree(work_dir, ignore_errors=True)

    def _stage_vault_entries(self, zf, entries: list, plan: list, work_dir: str,
                             destination_for_entry, backup_existing: bool) -> None:
        """Đọc toàn bộ entry Vault ra staging trước khi sửa dữ liệu người dùng."""
        destinations = {os.path.normcase(item["destination"]) for item in plan}
        for entry in entries:
            destination = destination_for_entry(entry)
            key = os.path.normcase(destination)
            if key in destinations:
                raise ValueError(f"Tệp Vault trùng đích khôi phục: {entry}")
            destinations.add(key)
            staged = os.path.join(work_dir, f"new-{len(plan)}")
            with zf.open(entry) as src, open(staged, "wb") as dst:
                shutil.copyfileobj(src, dst)
            plan.append({"destination": destination, "staged": staged, "backup_existing": backup_existing})

    def unpack_game_from_vault(self, game_config: dict, game_root: str = "", backup_existing: bool = True) -> dict:
        """
        Đọc từ file .congu_save và bung Save Game + Thành tựu về đúng vị trí máy mới.
        Có cơ chế sao lưu an toàn (.congu_bak) nếu máy đã có sẵn file save cũ.
        """
        with self.lock:
            game_id = game_config["id"]
            save_locs, ach_locs, _ = self._extract_game_locations(game_config)
            if not os.path.exists(self.vault_path):
                return {"success": False, "error": "Tệp Vault không tồn tại"}

            plan = []
            save_entries = 0
            achievement_entries = 0
            work_dir = tempfile.mkdtemp(prefix="congu-vault-restore-")
            try:
                with zipfile.ZipFile(self.vault_path, "r") as zf:
                    all_names = zf.namelist()
                    for save_loc in save_locs:
                        slot = save_loc.get("slot", "main_saves")
                        target = self.resolve_macro_path(save_loc["path"], game_root)
                        if not target:
                            continue
                        prefix = f"{game_id}/saves/{slot}/"
                        entries = [name for name in all_names if name.startswith(prefix) and not name.endswith("/") and not name.endswith("_meta.json")]
                        meta_name = prefix + "_meta.json"
                        original_type = "directory"
                        if meta_name in all_names:
                            meta = json.loads(zf.read(meta_name).decode("utf-8"))
                            if not isinstance(meta, dict) or meta.get("original_type", "directory") not in ("file", "directory"):
                                raise ValueError(f"Metadata save không hợp lệ: {meta_name}")
                            original_type = meta.get("original_type", "directory")
                        elif os.path.isfile(target):
                            original_type = "file"
                        if original_type == "file" and entries:
                            if len(entries) != 1 or os.path.isdir(target):
                                raise ValueError(f"Slot file không hợp lệ hoặc chứa nhiều tệp: {prefix}")
                            _safe_restore_destination(os.path.dirname(os.path.abspath(target)), entries[0][len(prefix):], entries[0])
                            self._stage_vault_entries(zf, entries, plan, work_dir,
                                                      lambda _entry, dest=target: dest, backup_existing)
                            save_entries += len(entries)
                            continue

                        def save_destination(entry, base=target, entry_prefix=prefix):
                            return _safe_restore_destination(base, entry[len(entry_prefix):], entry)

                        self._stage_vault_entries(zf, entries, plan, work_dir, save_destination, backup_existing)
                        save_entries += len(entries)

                    for ach_loc in ach_locs:
                        emu_name = ach_loc.get("emu", "generic")
                        target = self.resolve_macro_path(ach_loc["path"], game_root)
                        if not target:
                            continue
                        prefix = f"{game_id}/achievements/{emu_name}/"
                        entries = [name for name in all_names if name.startswith(prefix) and not name.endswith("/")]
                        self._stage_vault_entries(zf, entries, plan, work_dir,
                                                   lambda _entry, dest=target: dest, backup_existing)
                        achievement_entries += len(entries)

                applied, backups = self._apply_staged_restore_plan(plan, ".congu_bak")
                if not plan:
                    shutil.rmtree(work_dir, ignore_errors=True)
            except VaultRestoreRecoveryError as e:
                # Helper đã giữ staging để còn dữ liệu phục hồi thủ công.
                return {"success": False, "error": f"Không thể khôi phục Vault: {e}"}
            except Exception as e:
                shutil.rmtree(work_dir, ignore_errors=True)
                return {"success": False, "error": f"Không thể khôi phục Vault: {e}"}

            if applied:
                self._write_sync_marker(game_root)
            return {
                "success": True,
                "game_id": game_id,
                "unpacked_saves": save_entries,
                "unpacked_achs": achievement_entries,
                "backups_created": backups
            }

    # ==========================================
    # 5.1. TIME MACHINE - LỊCH SỬ PHIÊN BẢN SAVE (current / prev_1 / prev_2)
    # ==========================================
    def list_game_revisions(self, game_config: dict) -> dict:
        """Liệt kê 3 thế hệ save đang lưu trong .congu_save cho 1 game."""
        game_id = (game_config or {}).get("id", "")
        manifest = self.read_manifest()
        gs = (manifest.get("games") or {}).get(game_id) or {}
        revs = gs.get("revisions") or {}

        labels = {
            "current": "Bản hiện tại (lần chơi gần nhất)",
            "prev_1": "Phiên chơi trước đó",
            "prev_2": "2 phiên chơi trước",
        }
        items = []
        for rev in ("current", "prev_1", "prev_2"):
            info = revs.get(rev)
            if rev != "current" and not info:
                continue
            info = info or {}
            ts = int(info.get("packed_at") or 0)
            try:
                ts_text = datetime.fromtimestamp(ts).strftime("%H:%M · %d/%m/%Y") if ts else "—"
            except Exception:
                ts_text = "—"
            items.append({
                "revision": rev,
                "label": labels[rev],
                "packed_at": ts,
                "packed_at_text": ts_text,
                "files": int(info.get("files") or 0),
                "bytes": int(info.get("bytes") or 0),
            })

        return {
            "game_id": game_id,
            "title": (game_config or {}).get("vietnamese_title") or (game_config or {}).get("title") or game_id,
            "revisions": items,
            "has_history": len(items) > 1,
        }

    def has_local_save_data(self, game_config: dict, game_root: str = "") -> bool:
        """Kiểm tra thư mục save của game trên máy đã có dữ liệu thật hay chưa."""
        try:
            save_locs, _ach_locs, _excl = self._extract_game_locations(game_config)
        except Exception:
            return False

        ignore_suffixes = (".congu_bak", ".congu_prevbak", ".congu_restored.json")
        for save_loc in save_locs:
            target = self.resolve_macro_path(save_loc.get("path", ""), game_root)
            if not target:
                continue
            try:
                if os.path.isfile(target):
                    if os.path.getsize(target) > 0:
                        return True
                    continue
                if os.path.isdir(target):
                    for _root, _dirs, files in os.walk(target):
                        for name in files:
                            if not name.endswith(ignore_suffixes):
                                return True
            except OSError:
                continue
        return False

    def restore_game_revision(self, game_config: dict, game_root: str = "",
                              revision: str = "prev_1", backup_existing: bool = True) -> dict:
        """
        Khôi phục 1 thế hệ save (current / prev_1 / prev_2) từ .congu_save về đúng thư mục máy.
        Dùng cho nút "Khôi phục Save của phiên chơi trước đó" khi save mới nhất bị hỏng.
        """
        with self.lock:
            game_id = (game_config or {}).get("id", "")
            if revision not in ("current", "prev_1", "prev_2"):
                return {"success": False, "error": f"Thế hệ save không hợp lệ: {revision}"}
            if not os.path.exists(self.vault_path):
                return {"success": False, "error": "Tệp Vault không tồn tại"}

            save_locs, _ach_locs, _excl = self._extract_game_locations(game_config)
            base_prefix = f"{game_id}/saves/" if revision == "current" else f"{game_id}/{revision}/saves/"

            plan = []
            used_slots = []
            work_dir = tempfile.mkdtemp(prefix="congu-vault-revision-")
            try:
                with zipfile.ZipFile(self.vault_path, "r") as zf:
                    all_names = zf.namelist()
                    for save_loc in save_locs:
                        slot = save_loc.get("slot", "main_saves")
                        prefix = f"{base_prefix}{slot}/"
                        entries = [n for n in all_names if n.startswith(prefix) and not n.endswith("/") and not n.endswith("_meta.json")]
                        if not entries:
                            continue
                        target = self.resolve_macro_path(save_loc.get("path", ""), game_root)
                        original_type = "directory"
                        meta_name = f"{base_prefix}{slot}/_meta.json"
                        if meta_name in all_names:
                            meta = json.loads(zf.read(meta_name).decode("utf-8"))
                            if not isinstance(meta, dict) or meta.get("original_type", "directory") not in ("file", "directory"):
                                raise ValueError(f"Metadata save không hợp lệ: {meta_name}")
                            original_type = meta.get("original_type", "directory")
                            # macro_path is historical archive data, not authority to
                            # redirect writes away from the configured local save slot.
                        elif target and os.path.isfile(target):
                            original_type = "file"
                        if not target:
                            continue
                        used_slots.append(slot)
                        if original_type == "file":
                            if len(entries) != 1 or os.path.isdir(target):
                                raise ValueError(f"Slot file không hợp lệ hoặc chứa nhiều tệp: {prefix}")
                            _safe_restore_destination(os.path.dirname(os.path.abspath(target)), entries[0][len(prefix):], entries[0])
                            self._stage_vault_entries(zf, entries, plan, work_dir,
                                                       lambda _entry, dest=target: dest, backup_existing)
                            continue

                        def revision_destination(entry, base=target, entry_prefix=prefix):
                            return _safe_restore_destination(base, entry[len(entry_prefix):], entry)

                        self._stage_vault_entries(zf, entries, plan, work_dir, revision_destination, backup_existing)

                if not plan:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    return {
                        "success": False,
                        "error": "Không tìm thấy dữ liệu save của thế hệ này trong .congu_save.",
                        "game_id": game_id,
                        "revision": revision,
                    }
                restored, backups = self._apply_staged_restore_plan(plan, ".congu_prevbak")
            except VaultRestoreRecoveryError as e:
                # Helper đã giữ staging để còn dữ liệu phục hồi thủ công.
                return {"success": False, "error": f"Không thể khôi phục revision: {e}", "game_id": game_id, "revision": revision}
            except Exception as e:
                shutil.rmtree(work_dir, ignore_errors=True)
                return {"success": False, "error": f"Không thể khôi phục revision: {e}", "game_id": game_id, "revision": revision}

            return {
                "success": True,
                "game_id": game_id,
                "revision": revision,
                "restored_files": restored,
                "backups_created": backups,
                "slots": used_slots,
            }

    def pack_all_installed_games(self, all_games: list, user_config: dict) -> dict:
        """Gom toàn bộ save của các game đã được tìm thấy trên máy tính này vào Vault."""
        results = {}
        for game in all_games:
            gid = game["id"]
            game_dir = user_config.get(f"{gid}_path")
            if game_dir and os.path.exists(game_dir):
                res = self.pack_game_to_vault(game, game_dir)
                results[gid] = res
        return results

    def unpack_all_installed_games(self, all_games: list, user_config: dict) -> dict:
        """Bung toàn bộ save của các game đã được tìm thấy trên máy tính này."""
        results = {}
        for game in all_games:
            gid = game["id"]
            game_dir = user_config.get(f"{gid}_path")
            if game_dir and os.path.exists(game_dir):
                res = self.unpack_game_from_vault(game, game_dir)
                results[gid] = res
        return results

    # ==========================================
    # 6. NHẬP / XUẤT FILE VAULT (.congu_save) CHO NGƯỜI CHÙNG
    # ==========================================
    def export_vault(self, target_filepath: str) -> dict:
        """Xuất file .congu_save ra USB hoặc thư mục bất kỳ."""
        with self.lock:
            if not os.path.exists(self.vault_path):
                self._ensure_vault_initialized()

            dest = os.path.abspath(target_filepath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(self.vault_path, dest)
            return {
                "success": True,
                "exported_to": dest,
                "size_bytes": os.path.getsize(dest)
            }

    def _vault_save_index(self) -> tuple:
        """Đọc chỉ mục save đã đóng gói trong .congu_save: (index, manifest).

        index dạng: {game_id: {slot: {"macro_path": str, "files": [rel, ...]}}}
        """
        index, manifest = {}, {}
        if not os.path.exists(self.vault_path):
            return index, manifest
        try:
            with zipfile.ZipFile(self.vault_path, "r") as zf:
                names = zf.namelist()
                if "profile_manifest.json" in names:
                    manifest = json.loads(zf.read("profile_manifest.json").decode("utf-8"))
                for name in names:
                    parts = name.split("/")
                    if len(parts) < 4 or parts[1] != "saves" or name.endswith("/"):
                        continue
                    gid, slot, rel = parts[0], parts[2], "/".join(parts[3:])
                    slot_data = index.setdefault(gid, {}).setdefault(slot, {"macro_path": "", "original_type": "directory", "files": []})
                    if rel == "_meta.json":
                        try:
                            meta = json.loads(zf.read(name).decode("utf-8"))
                            slot_data["macro_path"] = meta.get("macro_path", "")
                            slot_data["original_type"] = meta.get("original_type", "directory")
                        except Exception:
                            pass
                    else:
                        slot_data["files"].append(rel)
        except Exception as e:
            print(f"[ConguSaveVault] Không đọc được chỉ mục save trong két: {e}")
        return index, manifest

    @staticmethod
    def _append_readme_game(readme: list, game_entry: dict) -> None:
        """Ghi 1 khối hướng dẫn tiếng Việt cho từng game trong file HUONG_DAN_TU_KHOI_PHUC.txt."""
        readme.append(f"▶ Game: {game_entry['title']}  (ID: {game_entry['game_id']})")
        readme.append(f"  - Thư mục trong file nén : {game_entry['folder_in_zip']}/saves/")
        readme.append("  - Chép toàn bộ tệp vào thư mục sau trên máy tính:")
        for loc in game_entry.get("save_locations", []):
            hint = loc.get("windows_path") or loc.get("portable_path") or "(không xác định)"
            readme.append(f"      • {hint}")
            readme.append(f"        (slot '{loc.get('slot')}', {loc.get('files_count', 0)} tệp)")
        readme.append(f"  - Tổng cộng: {game_entry['files_count']} tệp · {game_entry['bytes']} bytes")
        readme.append("-" * 72)

    def export_standard_zip(self, target_filepath: str, all_games: list, user_config: dict) -> dict:
        """Xuất toàn bộ save game ra 1 file ZIP tiêu chuẩn (không mã hóa, không khóa).

        Gói gồm:
        - HUONG_DAN_TU_KHOI_PHUC.txt : hướng dẫn tiếng Việt cho người tự giải nén.
        - save_manifest.json         : dữ liệu để App CỔ NGỮ khôi phục 1-click.
        - <Tên game (id)>/saves/...  : save thật của từng game.

        Save được lấy từ đĩa nếu game đang cài trên máy; nếu không, lấy bản đã
        đóng gói sẵn trong .congu_save để không mất dữ liệu của máy khác.
        """
        with self.lock:
            dest = os.path.abspath(target_filepath)
            if not dest.lower().endswith(".zip"):
                dest += ".zip"
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            user_config = user_config if isinstance(user_config, dict) else {}

            vault_index, vault_manifest = self._vault_save_index()
            vault_games_meta = vault_manifest.get("games") or {}

            manifest = {
                "format": "congu_standard_save_zip",
                "format_version": "1.0",
                "app": "CỔ NGỮ (VietModHub Pro)",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "player_name": vault_manifest.get("player_name") or os.environ.get("USERNAME", "Game Thủ"),
                "games": []
            }
            readme = [
                "=" * 72,
                "   HƯỚNG DẪN TỰ KHÔI PHỤC SAVE GAME (KHÔNG CẦN DÙNG APP CỔ NGỮ)",
                "=" * 72,
                "Tệp này là gói sao lưu ZIP CHUẨN, không mã hóa, không đặt mật khẩu.",
                "Bạn có thể giải nén bằng Windows Explorer, WinRAR hoặc 7-Zip,",
                "sau đó chép save vào đúng thư mục của từng game như hướng dẫn dưới đây.",
                "",
                "Lưu ý an toàn:",
                "  - Nên THOÁT GAME trước khi chép save.",
                "  - Nên sao lưu thư mục save cũ trước khi ghi đè.",
                "  - Đường dẫn dùng biến môi trường Windows: %APPDATA%, %LOCALAPPDATA%...",
                "    Bạn có thể dán trực tiếp vào thanh địa chỉ của Windows Explorer.",
                "",
                "Nếu muốn khôi phục tự động 1-Click, hãy dùng chức năng",
                "\"NẠP TỪ ZIP CHUẨN\" trong App CỔ NGỮ (đọc tệp save_manifest.json).",
                "=" * 72,
                ""
            ]
            used_folder_names = set()
            completed = set()
            vzf = None

            def _alloc_folder(title: str, gid: str) -> str:
                base = re.sub(r'[<>:"/\\|?*]', "", f"{title} ({gid})").strip() or gid
                name, suffix = base, 2
                while name.lower() in used_folder_names:
                    name = f"{base} {suffix}"
                    suffix += 1
                used_folder_names.add(name.lower())
                return name

            try:
                if vault_index:
                    vzf = zipfile.ZipFile(self.vault_path, "r")
                with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

                    def _write_slot_files(loc_entry: dict, arc_prefix: str, disk_items: list, vault_items: list) -> None:
                        for abs_path, rel in disk_items:
                            zf.write(abs_path, arc_prefix + rel)
                            loc_entry["bytes"] += os.path.getsize(abs_path)
                            loc_entry["files_count"] += 1
                        for vault_name, rel in vault_items:
                            with vzf.open(vault_name) as src, zf.open(arc_prefix + rel, "w") as out:
                                shutil.copyfileobj(src, out)
                            loc_entry["bytes"] += vzf.getinfo(vault_name).file_size
                            loc_entry["files_count"] += 1

                    def _apply_slot(game_entry: dict, folder_name: str, slot: str,
                                    macro_path: str, disk_items: list, vault_items: list,
                                    is_file_target: bool = False) -> None:
                        if not disk_items and not vault_items:
                            return
                        slot_safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", slot).strip("._") or "main_saves"
                        loc_entry = {
                            "slot": slot,
                            "source": "disk" if disk_items else "vault",
                            "original_type": "file" if is_file_target else "directory",
                            "portable_path": macro_path,
                            "windows_path": self.macro_to_windows_hint(macro_path),
                            "files_count": 0,
                            "bytes": 0
                        }
                        _write_slot_files(loc_entry, f"{folder_name}/saves/{slot_safe}/", disk_items, vault_items)
                        game_entry["save_locations"].append(loc_entry)
                        game_entry["files_count"] += loc_entry["files_count"]
                        game_entry["bytes"] += loc_entry["bytes"]

                    def _new_game_entry(gid: str, title: str, folder_name: str) -> dict:
                        return {
                            "game_id": gid,
                            "title": title,
                            "folder_in_zip": folder_name,
                            "save_locations": [],
                            "files_count": 0,
                            "bytes": 0
                        }

                    # 1) Game trong danh mục hiện tại - ưu tiên save thật trên đĩa
                    for game in all_games or []:
                        gid = str(game.get("id") or game.get("game_id") or "unknown")
                        if not gid or gid in completed:
                            continue
                        title = str(game.get("vietnamese_title") or game.get("title") or gid)
                        game_dir = user_config.get(f"{gid}_path", "") or ""
                        save_locs, _, exclude_patterns = self._extract_game_locations(game)
                        folder_name = _alloc_folder(title, gid)
                        game_entry = _new_game_entry(gid, title, folder_name)

                        for save_loc in save_locs:
                            raw_path = save_loc.get("path", "")
                            slot = str(save_loc.get("slot", "main_saves"))
                            real_path = self.resolve_macro_path(raw_path, game_dir)
                            disk_items, macro_path = [], ""
                            is_file_target = False
                            if real_path and os.path.exists(real_path):
                                macro_path = self.path_to_macro(real_path, game_dir)
                                if os.path.isfile(real_path):
                                    is_file_target = True
                                    disk_items.append((real_path, os.path.basename(real_path)))
                                else:
                                    for root, _, names in os.walk(real_path):
                                        for name in names:
                                            if any(name.lower().endswith(str(p).replace("*", "").lower())
                                                   for p in exclude_patterns if p):
                                                continue
                                            full = os.path.join(root, name)
                                            disk_items.append((full, os.path.relpath(full, real_path).replace("\\", "/")))
                            if disk_items:
                                _apply_slot(game_entry, folder_name, slot, macro_path, disk_items, [], is_file_target)
                                continue

                            # Không có trên đĩa -> dùng bản đã đóng gói trong .congu_save
                            vault_slot = (vault_index.get(gid) or {}).get(slot) or {}
                            vault_files = vault_slot.get("files") or []
                            if vault_files and vzf:
                                v_macro = vault_slot.get("macro_path") or macro_path
                                vault_items = [(f"{gid}/saves/{slot}/{rel}", rel) for rel in vault_files]
                                _apply_slot(game_entry, folder_name, slot, v_macro, [], vault_items,
                                             vault_slot.get("original_type") == "file")

                        if game_entry["files_count"]:
                            completed.add(gid)
                            manifest["games"].append(game_entry)
                            self._append_readme_game(readme, game_entry)

                    # 2) Game chỉ còn trong .congu_save (đã gỡ khỏi máy / khỏi danh mục)
                    for gid, slots in vault_index.items():
                        if gid in completed:
                            continue
                        title = str((vault_games_meta.get(gid) or {}).get("title") or gid)
                        folder_name = _alloc_folder(title, gid)
                        game_entry = _new_game_entry(gid, title, folder_name)
                        for slot, slot_data in slots.items():
                            vault_files = slot_data.get("files") or []
                            if not vault_files or not vzf:
                                continue
                            vault_items = [(f"{gid}/saves/{slot}/{rel}", rel) for rel in vault_files]
                            _apply_slot(game_entry, folder_name, slot, slot_data.get("macro_path", ""), [], vault_items)
                        if game_entry["files_count"]:
                            completed.add(gid)
                            manifest["games"].append(game_entry)
                            self._append_readme_game(readme, game_entry)

                    manifest["games_count"] = len(manifest["games"])
                    manifest["files_count"] = sum(g["files_count"] for g in manifest["games"])
                    zf.writestr("save_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                    zf.writestr("HUONG_DAN_TU_KHOI_PHUC.txt", ("\ufeff" + "\n".join(readme) + "\n").encode("utf-8"))

                return {
                    "success": True,
                    "path": dest,
                    "exported_to": dest,
                    "games_count": manifest["games_count"],
                    "files_count": manifest["files_count"],
                    "size_bytes": os.path.getsize(dest)
                }
            except Exception as e:
                try:
                    if os.path.exists(dest):
                        os.remove(dest)
                except OSError:
                    pass
                return {"success": False, "error": f"Lỗi khi xuất ZIP chuẩn: {e}"}
            finally:
                if vzf is not None:
                    try:
                        vzf.close()
                    except Exception:
                        pass

    def import_standard_zip(self, source_filepath: str, all_games: list, user_config: dict, backup_existing: bool = True) -> dict:
        """Khôi phục save trực tiếp từ gói ZIP chuẩn (không cần nhập vào .congu_save).

        Đọc save_manifest.json bên trong gói, phân giải lại đường dẫn theo macro
        của PC hiện tại và chép save về đúng thư mục. Mọi tệp save cũ bị ghi đè
        đều được sao lưu thành *.congu_bak.
        """
        src = os.path.abspath(source_filepath)
        if not os.path.exists(src):
            return {"success": False, "error": f"Không tìm thấy file nguồn: {source_filepath}"}
        try:
            with zipfile.ZipFile(src, "r") as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if "save_manifest.json" not in names:
                    return {"success": False, "error": "ZIP không có save_manifest.json"}
                manifest = json.loads(zf.read("save_manifest.json").decode("utf-8"))
                if manifest.get("format") != "congu_standard_save_zip":
                    return {"success": False, "error": "Không đúng định dạng ZIP save chuẩn CỔ NGỮ"}

                # Stage toàn bộ ZIP trước khi ghi bất kỳ save nào. Một lỗi ở game
                # hoặc file sau phải rollback toàn bộ batch, không để restore nửa vời.
                results = {}
                plan = []
                games_by_id = {str(game.get("id") or game.get("game_id") or ""): game
                               for game in (all_games or []) if isinstance(game, dict)}
                work_dir = tempfile.mkdtemp(prefix="congu-standard-restore-")
                try:
                    for entry in manifest.get("games", []):
                        gid = str(entry.get("game_id", ""))
                        folder = str(entry.get("folder_in_zip", ""))
                        game_dir = (user_config or {}).get(f"{gid}_path", "") if isinstance(user_config, dict) else ""
                        count, warnings = 0, []
                        game = games_by_id.get(gid)
                        if not game:
                            raise ValueError(f"Không có cấu hình game đáng tin cậy cho ZIP: {gid}")
                        configured_locations, _, _ = self._extract_game_locations(game)
                        configured_slots = {}
                        for configured in configured_locations:
                            configured_slot = str(configured.get("slot", "main_saves"))
                            if configured_slot in configured_slots:
                                raise ValueError(f"Slot cấu hình trùng lặp: {gid}/{configured_slot}")
                            configured_slots[configured_slot] = configured

                        for loc in entry.get("save_locations", []):
                            slot = str(loc.get("slot", "main_saves"))
                            configured = configured_slots.get(slot)
                            if not configured:
                                raise ValueError(f"Không tìm thấy slot save trong cấu hình: {gid}/{slot}")
                            raw_target = configured.get("path", "")
                            target = self.resolve_macro_path(raw_target, game_dir)
                            if not target or "{" in target or "<" in target or not os.path.isabs(target):
                                raise ValueError(f"Không xác định được đường dẫn save hợp lệ: {gid}/{slot}")
                            is_file_target = os.path.isfile(target) or (not os.path.isdir(target) and loc.get("original_type") == "file")
                            slot_safe = re.sub(r'[^A-Za-z0-9_.-]+', "_", slot).strip("._") or "main_saves"
                            slot_prefix = f"{folder}/saves/{slot_safe}/"
                            entries = [name for name in names if name.startswith(slot_prefix)]
                            base_abs = os.path.realpath(os.path.dirname(target) if is_file_target else target)

                            if is_file_target:
                                # Một slot kiểu file chỉ được chứa đúng một file save.
                                if len(entries) > 1:
                                    raise ValueError(f"Slot file chứa nhiều tệp: {slot_prefix}")
                                destination_for_entry = lambda _name, dest=target: dest
                            else:
                                destination_for_entry = lambda name, base=base_abs, prefix=slot_prefix: _safe_restore_destination(base, name[len(prefix):], name)
                            self._stage_vault_entries(zf, entries, plan, work_dir, destination_for_entry, backup_existing)
                            count += len(entries)

                        results[gid] = {
                            "success": count > 0,
                            "unpacked_saves": count,
                            "backups_created": 0,
                            "warnings": warnings,
                            "error": "" if count else (warnings[0] if warnings else "Gói ZIP không có tệp save cho game này")
                        }

                    applied, backups = self._apply_staged_restore_plan(plan, ".congu_bak")
                    if not plan:
                        shutil.rmtree(work_dir, ignore_errors=True)
                    # Backup count thuộc transaction chung; tổng này được trả top-level.
                    total_files = sum(r["unpacked_saves"] for r in results.values())
                    return {
                        "success": True,
                        "games_count": len(results),
                        "total_files": total_files,
                        "backups_created": backups,
                        "results": results,
                        "manifest": manifest
                    }
                except VaultRestoreRecoveryError as e:
                    return {"success": False, "error": f"Khôi phục ZIP chuẩn chưa hoàn tất: {e}"}
                except Exception:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    raise
        except (zipfile.BadZipFile, json.JSONDecodeError, ValueError) as e:
            return {"success": False, "error": f"ZIP không hợp lệ hoặc không an toàn: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Lỗi khi khôi phục ZIP chuẩn: {e}"}

    def import_vault(self, source_filepath: str) -> dict:
        """
        Nạp file .congu_save từ USB/ổ cứng ngoài vào ứng dụng:
        1. Kiểm tra toàn vẹn định dạng và manifest.
        2. Tạo bản sao lưu dự phòng cho Vault hiện tại (.bak).
        3. Thay thế Vault hiện tại bằng Vault mới.
        """
        with self.lock:
            src = os.path.abspath(source_filepath)
            if not os.path.exists(src):
                return {"success": False, "error": f"Không tìm thấy file nguồn: {source_filepath}"}

            staged = None
            try:
                fd, staged = tempfile.mkstemp(prefix=".congu-vault-", dir=os.path.dirname(self.vault_path))
                with os.fdopen(fd, "wb") as dst, open(src, "rb") as source:
                    shutil.copyfileobj(source, dst)
                with zipfile.ZipFile(staged, "r") as zf:
                    if "profile_manifest.json" not in zf.namelist():
                        raise ValueError("thiếu profile_manifest.json")
                    manifest = json.loads(zf.read("profile_manifest.json").decode("utf-8"))
                    if not isinstance(manifest, dict) or not isinstance(manifest.get("games", {}), dict):
                        raise ValueError("manifest không hợp lệ")
                    bad_entry = zf.testzip()
                    if bad_entry:
                        raise ValueError(f"Tệp ZIP bị hỏng: {bad_entry}")
                if os.path.exists(self.vault_path):
                    fd, backup_tmp = tempfile.mkstemp(prefix=".congu-vault-backup-", dir=os.path.dirname(self.vault_path))
                    os.close(fd)
                    try:
                        shutil.copy2(self.vault_path, backup_tmp)
                        os.replace(backup_tmp, self.vault_path + ".congu_vault_bak")
                    finally:
                        if os.path.exists(backup_tmp):
                            os.remove(backup_tmp)
                os.replace(staged, self.vault_path)
                return {
                    "success": True,
                    "imported_games_count": len(manifest.get("games", {})),
                    "player_name": manifest.get("player_name"),
                    "manifest": manifest
                }
            except Exception as e:
                return {"success": False, "error": f"Không thể nhập Vault: {e}"}
            finally:
                if staged and os.path.exists(staged):
                    os.remove(staged)

    # ==========================================
    # 7. HỖ TRỢ ĐỌC THÀNH TỰU TỰ ĐỘNG
    # ==========================================
    def _parse_achievements_file(self, filepath: str) -> list:
        """Đọc danh sách ID thành tựu từ Goldberg JSON, TENOKE user_stats.ini, hoặc CODEX/RUNE/FLT INI."""
        unlocked = []
        try:
            if filepath.endswith(".json"):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for ach_id, info in data.items():
                            if isinstance(info, dict) and (info.get("earned") is True or info.get("unlocked") is True):
                                unlocked.append(ach_id)
                            elif isinstance(info, (int, float)) and info > 0:
                                unlocked.append(ach_id)
                            elif info is True:
                                unlocked.append(ach_id)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                aid = item.get("name") or item.get("id")
                                if aid and (item.get("earned") is True or item.get("unlocked") is True):
                                    unlocked.append(aid)
            elif filepath.endswith(".ini"):
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                # 1. Hỗ trợ Tenoke format: "ach_id" = {unlocked = true, ...}
                import re
                for match in re.finditer(r'"([^"]+)"\s*=\s*\{[^}]*unlocked\s*=\s*true', text, re.I):
                    unlocked.append(match.group(1))
                # 2. Hỗ trợ chuẩn INI thông thường (CODEX, RUNE, FLT, OnlineFix)
                lines = text.splitlines()
                current_section = None
                for line in lines:
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]"):
                        current_section = line[1:-1]
                    elif "=" in line and current_section and current_section != "SteamAchievements":
                        parts = line.split("=", 1)
                        k = parts[0].strip().lower()
                        v = parts[1].strip().lower()
                        if k in ("achieved", "unlocked", "state") and v in ("1", "true"):
                            unlocked.append(current_section)
        except Exception:
            pass
        return list(dict.fromkeys(unlocked))
