# -*- coding: utf-8 -*-
"""
Core Cloud Save - Vault & Google Drive Sync
"""
import os
import sys
import time
from typing import Optional, Callable, Dict, Any, List, Tuple

from vault_manager import ConguSaveVault
from cloud_sync import CloudSyncManager, DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET
from .process_utils import (
    get_default_appdata_dir, _internal_log, _DEFAULT_APP_DIR,
    _CONFIG_GETTER, _CUSTOM_GAMES_GETTER, _GAMES_JSON_PATH_GETTER,
    _GAMES_GETTER, _CONTROLLER_ENGINE_REF, _LOG_STARTUP_FN,
    _CUSTOM_EXIT_HOOKS, _HOOK_LOCK
)
from .playtime import PlaytimeManager, PLAYTIME_MGR
from .achievements import AchievementManager, ACHIEVEMENT_MGR



# ==============================================================================
# HỒ SƠ DI ĐỘNG (ConguSaveVault) & POST-EXIT HOOKS
# ==============================================================================

SAVE_VAULT: Optional[ConguSaveVault] = None


def get_vault_instance(app_dir: str = "", appdata_dir: str = "") -> ConguSaveVault:
    """Lấy thể hiện quản lý Hồ Sơ Di Động Hợp Nhất (PlayerProfile.congu_save)."""
    global SAVE_VAULT
    app_d = app_dir or _DEFAULT_APP_DIR
    appdata_d = appdata_dir or get_default_appdata_dir()

    custom_path = None
    if _CONFIG_GETTER:
        try:
            cfg = _CONFIG_GETTER()
            custom_path = cfg.get("custom_vault_path")
        except Exception:
            pass

    if custom_path:
        target = os.path.abspath(custom_path)
    elif os.path.exists(os.path.join(app_d, "PlayerProfile.congu_save")):
        target = os.path.join(app_d, "PlayerProfile.congu_save")
    else:
        target = os.path.join(appdata_d, "PlayerProfile.congu_save")

    if SAVE_VAULT is None or SAVE_VAULT.vault_path != target:
        SAVE_VAULT = ConguSaveVault(target)
    return SAVE_VAULT


def handle_game_exit_hook(game_id: str, game_dir: str):
    """
    Điểm móc nối tự động sau khi thoát game (Post-Exit Hook):
    - Ghi log và đồng bộ trạng thái.
    - Sẵn sàng kích hoạt: Đồng bộ Cloud Save & Quét Thành Tựu mới mở khóa.
    - Tự động đóng gói Save + Thành tựu vào Hồ Sơ Di Động Hợp Nhất (PlayerProfile.congu_save).
    """
    _internal_log(f"[PlaytimeTracker] Kích hoạt Post-Exit Hook cho '{game_id}' tại '{game_dir}'")
    cfg = _CONFIG_GETTER() if _CONFIG_GETTER else {}
    cloud_cfg = cfg.get("cloud_save", {})
    auto_sync = cloud_cfg.get("auto_sync_on_exit", True)
    scan_ach = cloud_cfg.get("offline_achievements_scan", True)

    try:
        if ACHIEVEMENT_MGR and scan_ach:
            ACHIEVEMENT_MGR.check_game_live_achievements(game_id, game_dir)
    except Exception as e:
        print(f"[AchievementTracker] Post-exit scan error: {e}")

    try:
        if auto_sync:
            vault = get_vault_instance()
            games = _GAMES_GETTER() if _GAMES_GETTER else []
            g_cfg = next((g for g in games if g.get("id") == game_id), None)
            if g_cfg:
                vault.pack_game_to_vault(g_cfg, game_dir)
                _internal_log(f"[SaveVault] Đã tự động gom Save + Thành tựu của '{game_id}' vào Hồ Sơ Di Động (.congu_save)")
    except Exception as e:
        print(f"[SaveVault] Post-exit vault pack error: {e}")

    try:
        if CLOUD_SYNC_MGR and auto_sync:
            games = _GAMES_GETTER() if _GAMES_GETTER else []
            g_cfg = next((g for g in games if g.get("id") == game_id), None)
            if g_cfg:
                CLOUD_SYNC_MGR.post_session_sync(game_id, game_dir, g_cfg)
    except Exception as e:
        print(f"[CloudSync] Post-exit sync hook error: {e}")

    try:
        if _CONTROLLER_ENGINE_REF:
            _CONTROLLER_ENGINE_REF.handle_game_exit(game_id)
            _internal_log(f"[ControllerEngine] Đã dọn dẹp sạch sẽ wrapper và dừng mapper cho '{game_id}'")
    except Exception as e:
        print(f"[ControllerEngine] Post-exit cleanup error: {e}")

    # Chạy các custom exit hooks bổ sung nếu có
    with _HOOK_LOCK:
        for hook_fn in _CUSTOM_EXIT_HOOKS:
            try:
                hook_fn(game_id, game_dir)
            except Exception as e:
                print(f"[ExitHook] Custom hook error: {e}")


# ==============================================================================
# KHỞI TẠO CÁC SINGLETON MẶC ĐỊNH
# ==============================================================================

ACHIEVEMENT_MGR = AchievementManager()
PLAYTIME_MGR = PlaytimeManager(
    db_path=os.path.join(get_default_appdata_dir(), "playtime.json"),
    on_game_exit_callback=handle_game_exit_hook
)
CLOUD_SYNC_MGR = CloudSyncManager(get_default_appdata_dir())
