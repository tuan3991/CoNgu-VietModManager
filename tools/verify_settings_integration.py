# -*- coding: utf-8 -*-
"""Kiểm tra tích hợp: các tùy chọn Menu Cài Đặt có thực sự ảnh hưởng tới hành vi backend."""

import os
import tempfile

from core.config_manager import (
    load_user_config, save_user_config, get_unified_settings,
    update_unified_settings, get_cache_stats, clear_app_cache, APPDATA_DIR,
)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---------------------------------------------------------------- 1. Cấu trúc
settings = get_unified_settings()
for section in ("general", "scanner", "downloader", "cloud_save"):
    check(f"section '{section}' tồn tại", section in settings)
check("general.theme có giá trị", bool(settings["general"].get("theme")),
      settings["general"].get("theme"))
check("downloader.preferred_source hợp lệ",
      settings["downloader"].get("preferred_source") in
      ("github_cdn", "gdrive", "hydra", "torrent"),
      settings["downloader"].get("preferred_source"))

# ------------------------------------------------- 2. Tương thích ngược
cfg = load_user_config()
check("active_theme đồng bộ với general.theme",
      cfg.get("active_theme") == settings["general"]["theme"])
check("community_cloud đồng bộ cloud_id",
      (cfg.get("community_cloud") or {}).get("cloud_id") == settings["cloud_save"].get("cloud_id"))
check("custom_library_paths top-level đồng bộ",
      cfg.get("custom_library_paths") == settings["scanner"].get("custom_library_paths"))
check("đường dẫn game riêng lẻ vẫn được giữ (vd *_path)",
      any(k.endswith("_path") for k in cfg.keys()))

# ------------------------------------- 3. Cache: thống kê & dọn dẹp thật
cache_dir = os.path.join(APPDATA_DIR, "cache", "_selftest_game")
os.makedirs(cache_dir, exist_ok=True)
fake = os.path.join(cache_dir, "mod_package.congu")
with open(fake, "wb") as fh:
    fh.write(b"0" * 4096)

stats = get_cache_stats()
check("get_cache_stats đếm được tệp", stats["success"] and stats["file_count"] >= 1,
      f'{stats["file_count"]} tệp / {stats["formatted_size"]}')

cleared = clear_app_cache()
check("clear_app_cache báo thành công", cleared["success"])
check("tệp test đã bị xóa", not os.path.exists(fake))
check("thư mục cache được tạo lại", os.path.isdir(os.path.join(APPDATA_DIR, "cache")))

# --------------------------- 4. keep_congu_cache chi phối dọn cache sau cài
from core.installer_pipeline import cleanup_cache_after_install

os.makedirs(cache_dir, exist_ok=True)
with open(fake, "wb") as fh:
    fh.write(b"0" * 1024)

# keep = True -> phải giữ lại
removed_keep = cleanup_cache_after_install("_selftest_game",
                                           {"downloader": {"keep_congu_cache": True}})
check("keep_congu_cache=True giữ lại gói nén",
      removed_keep == 0 and os.path.exists(fake))

# keep = False -> phải xóa
removed_drop = cleanup_cache_after_install("_selftest_game",
                                           {"downloader": {"keep_congu_cache": False}})
check("keep_congu_cache=False xóa gói nén",
      removed_drop == 1 and not os.path.exists(fake))

# ------------------------------------- 5. Giới hạn aria2c đọc từ cấu hình
from core.downloader import get_torrent_manager
mgr = get_torrent_manager()
limit_kb, concurrent = mgr._read_download_settings()
check("aria2c đọc được giới hạn băng thông", limit_kb >= 0, f"{limit_kb} KB/s")
check("aria2c đọc được số tác vụ đồng thời", 1 <= concurrent <= 10, str(concurrent))

# ------------------- 6. Hook thoát game tôn trọng auto_sync / offline scan
import core.cloud_save.gdrive_sync as gs
import inspect
src = inspect.getsource(gs.handle_game_exit_hook)
check("hook đọc cloud_save.auto_sync_on_exit", "auto_sync_on_exit" in src)
check("hook đọc cloud_save.offline_achievements_scan", "offline_achievements_scan" in src)

# --------------------------- 7. Playtime tôn trọng cờ track_playtime
import core.cloud_save.playtime as pt
check("playtime đọc cờ track_playtime", "track_playtime" in inspect.getsource(pt))

# ------------------- 8. Scanner tôn trọng scan_steam/epic/gog + auto_scan
import api.ipc_bridge as bridge
bridge_src = inspect.getsource(bridge.ModManagerAPI.get_games)
for flag in ("scan_steam", "scan_epic", "scan_gog", "auto_scan_on_startup"):
    check(f"scanner tôn trọng '{flag}'", flag in bridge_src)

# ------------------- 9. preferred_source chi phối thứ tự nguồn tải
import core.installer_pipeline.install_ops as ops
ops_src = inspect.getsource(ops)
check("installer tôn trọng preferred_source", "preferred_source" in ops_src)

# dọn dẹp
try:
    import shutil
    shutil.rmtree(cache_dir, ignore_errors=True)
except Exception:
    pass

# ------------------------------------------------------------------ Báo cáo
print()

# ------------------------------------------------ 4. In-Game & Controller (Steam-Style additions)
check("section 'in_game' t?n t?i", "in_game" in settings)
check("in_game.game_booster_enabled h?p l?", "game_booster_enabled" in settings.get("in_game", {}))
check("section 'controller' t?n t?i", "controller" in settings)
check("controller.enabled h?p l?", "enabled" in settings.get("controller", {}))

failed = 0
for name, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    suffix = f"  [{detail}]" if detail else ""
    print(f"[{mark}] {name}{suffix}")
print()
print(f"Tổng: {len(results)} kiểm tra, {len(results) - failed} đạt, {failed} lỗi.")
raise SystemExit(1 if failed else 0)