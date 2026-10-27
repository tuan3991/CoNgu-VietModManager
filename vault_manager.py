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

import os
import json
import time
import shutil
import zipfile
import hashlib
import tempfile
import threading
from datetime import datetime, timezone

VAULT_VERSION = "2.0"
VAULT_MAGIC_HEADER = "CONGU_SAVE_VAULT"


class ConguSaveVault:
    """
    Quản lý đóng gói & giải nén toàn bộ Save Game, Thành tựu, Giờ chơi
    vào 1 tệp tin duy nhất (.congu_save) có thể mang sang mọi PC.
    """
    def __init__(self, vault_file_path: str):
        self.vault_path = os.path.abspath(vault_file_path)
        self.lock = threading.RLock()
        self._ensure_vault_initialized()

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
    def _extract_game_locations(self, game_config: dict) -> tuple:
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

        return save_locs, ach_locs, exclude_patterns

    # ==========================================
    # 4. ĐÓNG GÓI NGUYÊN TỬ VÀO 1 FILE (.congu_save)
    # ==========================================
    def pack_game_to_vault(self, game_config: dict, game_root: str = "", added_playtime_sec: int = 0) -> dict:
        """
        Gom toàn bộ file save, thành tựu và cộng giờ chơi của game đưa vào file .congu_save.
        Sử dụng cơ chế Atomic Update (tạo zip tạm -> os.replace) để không bao giờ hỏng két.
        """
        with self.lock:
            game_id = game_config["id"]
            save_locs, ach_locs, exclude_patterns = self._extract_game_locations(game_config)
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

            # 3. Tạo file ZIP tạm cùng thư mục với Vault
            vault_dir = os.path.dirname(self.vault_path)
            temp_fd, temp_zip_path = tempfile.mkstemp(suffix=".congu_save_tmp", dir=vault_dir)
            os.close(temp_fd)

            try:
                prefix_to_replace = f"{game_id}/"
                total_bytes = 0
                files_packed = 0

                with zipfile.ZipFile(self.vault_path, "r") as old_zf, \
                     zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as new_zf:

                    # Giữ nguyên toàn bộ dữ liệu của các game khác đã có trong file Vault
                    for item in old_zf.infolist():
                        if item.filename != "profile_manifest.json" and not item.filename.startswith(prefix_to_replace):
                            new_zf.writestr(item, old_zf.read(item.filename))

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
                            for root, _, files in os.walk(real_save_path):
                                for f in files:
                                    if any(f.endswith(ext.replace("*", "")) for ext in exclude_patterns):
                                        continue
                                    full_p = os.path.join(root, f)
                                    rel_p = os.path.relpath(full_p, real_save_path).replace("\\", "/")
                                    arcname = f"{game_id}/saves/{slot}/{rel_p}"
                                    new_zf.write(full_p, arcname)
                                    total_bytes += os.path.getsize(full_p)
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

                    manifest["games"][game_id] = game_stat
                    manifest["updated_at"] = int(time.time())
                    manifest["total_playtime_seconds"] = sum(g.get("playtime_seconds", 0) for g in manifest["games"].values())
                    manifest["total_achievements_count"] = sum(len(g.get("unlocked_achievements", [])) for g in manifest["games"].values())

                    new_zf.writestr("profile_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

                # Ghi đè nguyên tử
                os.replace(temp_zip_path, self.vault_path)
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

            unpacked_saves = 0
            unpacked_achs = 0
            created_backups = []

            with zipfile.ZipFile(self.vault_path, "r") as zf:
                all_names = zf.namelist()

                # 1. Bung Save Game
                for save_loc in save_locs:
                    slot = save_loc.get("slot", "main_saves")
                    target_real_path = self.resolve_macro_path(save_loc["path"], game_root)
                    if not target_real_path:
                        continue

                    prefix = f"{game_id}/saves/{slot}/"
                    matched_entries = [name for name in all_names if name.startswith(prefix) and not name.endswith("/") and not name.endswith("_meta.json")]
                    if not matched_entries:
                        continue

                    # Tạo thư mục đích
                    os.makedirs(target_real_path, exist_ok=True)

                    for entry in matched_entries:
                        rel_inside_slot = entry[len(prefix):]
                        dest_file = os.path.normpath(os.path.join(target_real_path, rel_inside_slot))

                        # Chống Zip Slip
                        if not os.path.normcase(dest_file).startswith(os.path.normcase(target_real_path)):
                            raise ValueError(f"Phát hiện đường dẫn không an toàn trong file save: {entry}")

                        # Sao lưu tệp cũ nếu đã có sẵn
                        if backup_existing and os.path.exists(dest_file):
                            bak_path = dest_file + ".congu_bak"
                            try:
                                shutil.copy2(dest_file, bak_path)
                                created_backups.append(bak_path)
                            except Exception:
                                pass

                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        with zf.open(entry) as src, open(dest_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        unpacked_saves += 1

                # 2. Bung Thành Tựu SteamEmu
                for ach_loc in ach_locs:
                    emu_name = ach_loc.get("emu", "generic")
                    target_ach_file = self.resolve_macro_path(ach_loc["path"], game_root)
                    if not target_ach_file:
                        continue

                    prefix = f"{game_id}/achievements/{emu_name}/"
                    for entry in all_names:
                        if entry.startswith(prefix) and not entry.endswith("/"):
                            # Sao lưu tệp thành tựu cũ nếu có
                            if backup_existing and os.path.exists(target_ach_file):
                                bak_p = target_ach_file + ".congu_bak"
                                try:
                                    shutil.copy2(target_ach_file, bak_p)
                                    created_backups.append(bak_p)
                                except Exception:
                                    pass

                            os.makedirs(os.path.dirname(target_ach_file), exist_ok=True)
                            with zf.open(entry) as src, open(target_ach_file, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            unpacked_achs += 1

            return {
                "success": True,
                "game_id": game_id,
                "unpacked_saves": unpacked_saves,
                "unpacked_achs": unpacked_achs,
                "backups_created": len(created_backups)
            }

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

            # Kiểm tra xem có đúng định dạng ZIP và có manifest không
            try:
                with zipfile.ZipFile(src, "r") as zf:
                    if "profile_manifest.json" not in zf.namelist():
                        return {"success": False, "error": "Tệp không phải là Hồ Sơ CỔ NGỮ (.congu_save) hợp lệ (thiếu profile_manifest.json)"}
                    manifest = json.loads(zf.read("profile_manifest.json").decode("utf-8"))
            except Exception as e:
                return {"success": False, "error": f"Tệp bị hỏng hoặc không đúng định dạng: {e}"}

            # Sao lưu Vault cũ nếu có
            if os.path.exists(self.vault_path):
                bak = self.vault_path + ".congu_vault_bak"
                try:
                    shutil.copy2(self.vault_path, bak)
                except Exception:
                    pass

            shutil.copy2(src, self.vault_path)
            return {
                "success": True,
                "imported_games_count": len(manifest.get("games", {})),
                "player_name": manifest.get("player_name"),
                "manifest": manifest
            }

    # ==========================================
    # 7. HỖ TRỢ ĐỌC THÀNH TỰU TỰ ĐỘNG
    # ==========================================
    def _parse_achievements_file(self, filepath: str) -> list:
        """Đọc danh sách ID thành tựu từ Goldberg JSON hoặc CODEX/RUNE INI."""
        unlocked = []
        try:
            if filepath.endswith(".json"):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for ach_id, info in data.items():
                            if isinstance(info, dict) and info.get("earned", False):
                                unlocked.append(ach_id)
            elif filepath.endswith(".ini"):
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    current_section = None
                    for line in f:
                        line = line.strip()
                        if line.startswith("[") and line.endswith("]"):
                            current_section = line[1:-1]
                        elif "=" in line and current_section and current_section != "SteamAchievements":
                            k, v = [x.strip().lower() for x in line.split("=", 1)]
                            if k in ("achieved", "unlocked") and v in ("1", "true"):
                                unlocked.append(current_section)
        except Exception:
            pass
        return unlocked
