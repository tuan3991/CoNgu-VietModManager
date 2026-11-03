#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: P1-01 & P1-04 Mod Compatibility & Update Checker
============================================================
Kiểm chứng:
1. Thuật toán so khớp phiên bản Mod (Semver, prefix, suffix, date-based).
2. Lưu & truy xuất biên nhận cài đặt mod (Receipts) trong User Config.
3. Cơ chế kiểm tra cập nhật mod thực chất (check_updates) với đầy đủ các trạng thái:
   - not_installed (chưa cài)
   - up_to_date (đã ở bản mới nhất)
   - update_available (có bản mới hơn)
   - unknown_version (mod cũ chưa có biên nhận)
   - catalog_error / offline (mất kết nối hoặc thiếu danh mục)
4. Đánh giá tương thích bản mod (P1-01):
   - Đã xác nhận tương thích (confirmed_compatible)
   - Chưa kiểm thử (untested)
   - Không tương thích (incompatible)
   - Cảnh báo Anti-Cheat / Online
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.config_manager.paths as paths_mod
import core.config_manager.user_settings as settings_mod
from core.mod_compatibility import (
    parse_version_tuple,
    compare_mod_versions,
    assess_mod_compatibility,
    get_catalog_latest_mod_version,
    check_mod_update_status,
    COMPATIBILITY_STATUS_CONFIRMED,
    COMPATIBILITY_STATUS_UNTESTED,
    COMPATIBILITY_STATUS_INCOMPATIBLE,
    COMPATIBILITY_STATUS_MISSING,
)


class TestModUpdateChecker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="congu-mod-update-test-")
        self.appdata_dir = os.path.join(self.temp_dir, "appdata")
        os.makedirs(self.appdata_dir, exist_ok=True)

        self._orig_appdata = paths_mod.APPDATA_DIR
        self._orig_config_json = paths_mod.CONFIG_JSON
        paths_mod.APPDATA_DIR = self.appdata_dir
        paths_mod.CONFIG_JSON = os.path.join(self.appdata_dir, "user_config.json")
        settings_mod.CONFIG_JSON = paths_mod.CONFIG_JSON

    def tearDown(self):
        paths_mod.APPDATA_DIR = self._orig_appdata
        paths_mod.CONFIG_JSON = self._orig_config_json
        settings_mod.CONFIG_JSON = self._orig_config_json
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. VERSION COMPARISON ENGINE
    # -------------------------------------------------------------------------
    def test_version_parsing(self):
        self.assertEqual(parse_version_tuple("v1.0.0")[0], (1, 0, 0))
        self.assertEqual(parse_version_tuple("V2.1.3")[0], (2, 1, 3))
        self.assertEqual(parse_version_tuple("1.2.0 (Bản Chuẩn UE5)")[0], (1, 2, 0))
        self.assertIn("ue5", parse_version_tuple("1.2.0 (Bản Chuẩn UE5)")[1])
        self.assertEqual(parse_version_tuple("2026.11.03")[0], (2026, 11, 3))

    def test_version_comparison_logic(self):
        # Cùng phiên bản
        self.assertEqual(compare_mod_versions("v1.0.0", "v1.0.0"), 0)
        self.assertEqual(compare_mod_versions("1.2.0", "v1.2.0"), 0)

        # Có bản mới hơn trong catalog (v1 < v2 -> -1)
        self.assertEqual(compare_mod_versions("v1.0.0", "v1.0.1"), -1)
        self.assertEqual(compare_mod_versions("v1.0.0", "v1.2.0"), -1)
        self.assertEqual(compare_mod_versions("v1.9.9", "v2.0.0"), -1)
        self.assertEqual(compare_mod_versions("2026.10.30", "2026.11.01"), -1)

        # Bản hiện tại mới hơn catalog (v1 > v2 -> 1)
        self.assertEqual(compare_mod_versions("v1.1.0", "v1.0.9"), 1)
        self.assertEqual(compare_mod_versions("v2.0.0", "v1.9.9"), 1)

    # -------------------------------------------------------------------------
    # 2. INSTALLED MOD RECEIPTS
    # -------------------------------------------------------------------------
    def test_receipt_lifecycle(self):
        game_id = "test_game"
        # Ban đầu chưa có receipt
        receipt = settings_mod.get_installed_mod_receipt(game_id)
        self.assertEqual(receipt, {})

        # Ghi nhận cài đặt thành công
        ok = settings_mod.record_installed_mod_receipt(
            game_id,
            version="v1.2.0",
            sha256="abcdef123456",
            metadata={"game_path": r"C:\Games\TestGame", "mod_type": "pak"}
        )
        self.assertTrue(ok)

        # Kiểm tra đọc lại
        saved = settings_mod.get_installed_mod_receipt(game_id)
        self.assertEqual(saved.get("version"), "v1.2.0")
        self.assertEqual(saved.get("sha256"), "abcdef123456")
        self.assertEqual(saved.get("status"), "installed")
        self.assertEqual(saved.get("mod_type"), "pak")

        # Gỡ cài đặt
        removed = settings_mod.remove_installed_mod_receipt(game_id)
        self.assertTrue(removed)
        after_remove = settings_mod.get_installed_mod_receipt(game_id)
        self.assertEqual(after_remove.get("status"), "uninstalled")

    # -------------------------------------------------------------------------
    # 3. MOD UPDATE CHECKER (P1-04)
    # -------------------------------------------------------------------------
    def test_update_checker_not_installed(self):
        catalog_game = {
            "id": "game1",
            "versions": [{"version": "v1.0.0", "is_latest": True, "changelog": "Init"}]
        }
        res = check_mod_update_status(
            game_id="game1",
            catalog_game=catalog_game,
            installed_receipt=None,
            is_mod_installed_on_disk=False
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["has_update"])
        self.assertEqual(res["status"], "not_installed")

    def test_update_checker_up_to_date(self):
        catalog_game = {
            "id": "game1",
            "versions": [
                {"version": "v1.2.0", "is_latest": True, "changelog": "Update font"},
                {"version": "v1.0.0", "is_latest": False, "changelog": "Init"}
            ]
        }
        receipt = {"version": "v1.2.0", "status": "installed"}
        res = check_mod_update_status(
            game_id="game1",
            catalog_game=catalog_game,
            installed_receipt=receipt,
            is_mod_installed_on_disk=True
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["has_update"])
        self.assertEqual(res["status"], "up_to_date")
        self.assertEqual(res["installed_version"], "v1.2.0")

    def test_update_checker_update_available(self):
        catalog_game = {
            "id": "game1",
            "versions": [
                {"version": "v1.3.0", "is_latest": True, "changelog": "Sửa lỗi chính tả"},
                {"version": "v1.2.0", "is_latest": False, "changelog": "Init"}
            ]
        }
        receipt = {"version": "v1.2.0", "status": "installed"}
        res = check_mod_update_status(
            game_id="game1",
            catalog_game=catalog_game,
            installed_receipt=receipt,
            is_mod_installed_on_disk=True
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["has_update"])
        self.assertEqual(res["status"], "update_available")
        self.assertEqual(res["installed_version"], "v1.2.0")
        self.assertEqual(res["latest_version"], "v1.3.0")
        self.assertEqual(res["changelog"], "Sửa lỗi chính tả")

    def test_update_checker_legacy_untracked_version(self):
        # Có file mod trên đĩa nhưng không có receipt
        catalog_game = {
            "id": "game1",
            "versions": [{"version": "v2.0.0", "is_latest": True, "changelog": "Bản mới"}]
        }
        res = check_mod_update_status(
            game_id="game1",
            catalog_game=catalog_game,
            installed_receipt=None,
            is_mod_installed_on_disk=True
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["has_update"])
        self.assertEqual(res["status"], "unknown_version")
        self.assertEqual(res["latest_version"], "v2.0.0")

    def test_update_checker_catalog_missing(self):
        res = check_mod_update_status(
            game_id="game1",
            catalog_game=None,
            installed_receipt=None,
            is_mod_installed_on_disk=False
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "catalog_error")
        self.assertFalse(res["has_update"])

    # -------------------------------------------------------------------------
    # 4. COMPATIBILITY METADATA ASSESSMENT (P1-01)
    # -------------------------------------------------------------------------
    def test_compatibility_game_missing(self):
        game_cfg = {"id": "game1", "title": "Game 1"}
        rep = assess_mod_compatibility(game_cfg, installed_game_info={"game_path": ""})
        self.assertEqual(rep["status"], COMPATIBILITY_STATUS_MISSING)
        self.assertFalse(rep["is_compatible"])

    def test_compatibility_confirmed(self):
        fake_game_path = os.path.join(self.temp_dir, "fake_game")
        os.makedirs(fake_game_path, exist_ok=True)

        game_cfg = {
            "id": "game1",
            "title": "Game 1",
            "supported_platforms": ["steam"],
            "tested_game_versions": ["1.2.3456", "build_9999"],
        }
        installed = {
            "game_path": fake_game_path,
            "platform": "steam",
            "game_version": "1.2.3456",
        }
        rep = assess_mod_compatibility(game_cfg, installed)
        self.assertEqual(rep["status"], COMPATIBILITY_STATUS_CONFIRMED)
        self.assertTrue(rep["is_compatible"])

    def test_compatibility_incompatible_version(self):
        fake_game_path = os.path.join(self.temp_dir, "fake_game")
        os.makedirs(fake_game_path, exist_ok=True)

        game_cfg = {
            "id": "game1",
            "title": "Game 1",
            "tested_game_versions": ["1.0.0"],
            "incompatible_game_versions": ["1.1.0_broken"],
        }
        installed = {
            "game_path": fake_game_path,
            "game_version": "1.1.0_broken",
        }
        rep = assess_mod_compatibility(game_cfg, installed)
        self.assertEqual(rep["status"], COMPATIBILITY_STATUS_INCOMPATIBLE)
        self.assertFalse(rep["is_compatible"])
        self.assertTrue(len(rep["reasons"]) > 0)

    def test_compatibility_untested_version(self):
        fake_game_path = os.path.join(self.temp_dir, "fake_game")
        os.makedirs(fake_game_path, exist_ok=True)

        game_cfg = {
            "id": "game1",
            "title": "Game 1",
            "tested_game_versions": ["1.0.0"],
        }
        installed = {
            "game_path": fake_game_path,
            "game_version": "2.0.0_future",
        }
        rep = assess_mod_compatibility(game_cfg, installed)
        self.assertEqual(rep["status"], COMPATIBILITY_STATUS_UNTESTED)
        self.assertTrue(rep["is_compatible"])  # Untested is still allowed with warning

    def test_compatibility_anti_cheat_warning(self):
        fake_game_path = os.path.join(self.temp_dir, "fake_game")
        os.makedirs(fake_game_path, exist_ok=True)

        game_cfg = {
            "id": "game1",
            "title": "Online Game",
            "anti_cheat": {
                "has_anti_cheat": True,
                "system": "EasyAntiCheat",
                "warning": "Không dùng khi chơi Multiplayer trực tuyến!"
            }
        }
        installed = {"game_path": fake_game_path}
        rep = assess_mod_compatibility(game_cfg, installed)
        self.assertIsNotNone(rep["anti_cheat_warning"])
        self.assertIn("EasyAntiCheat", rep["anti_cheat_warning"])

    def test_api_check_updates_and_compatibility_integration(self):
        from api.ipc_bridge import ModManagerAPI
        import core.config_manager.catalog as catalog_mod
        orig_games_json = paths_mod.GAMES_JSON
        orig_cache_json = paths_mod.CACHE_GAMES_JSON
        orig_cat_games = catalog_mod.GAMES_JSON
        orig_cat_cache = catalog_mod.CACHE_GAMES_JSON

        fake_games_json = os.path.join(self.temp_dir, "fake_games.json")
        fake_cache_json = os.path.join(self.temp_dir, "fake_cache_games.json")

        paths_mod.GAMES_JSON = fake_games_json
        paths_mod.CACHE_GAMES_JSON = fake_cache_json
        catalog_mod.GAMES_JSON = fake_games_json
        catalog_mod.CACHE_GAMES_JSON = fake_cache_json

        try:
            fake_catalog = [
                {
                    "id": "game_alpha",
                    "title": "Alpha Game",
                    "vietnamese_title": "Game Alpha Tiếng Việt",
                    "versions": [
                        {"version": "v1.5.0", "is_latest": True, "changelog": "Cập nhật chương 2"},
                        {"version": "v1.0.0", "is_latest": False, "changelog": "Phát hành"}
                    ],
                    "tested_game_versions": ["1.0.0", "1.5.0"],
                    "supported_platforms": ["steam"]
                }
            ]
            with open(fake_games_json, "w", encoding="utf-8") as f:
                json.dump(fake_catalog, f)

            api = ModManagerAPI()

            # 1. Chưa cài đặt
            res_not_installed = api.check_updates("game_alpha")
            self.assertTrue(res_not_installed["success"])
            self.assertFalse(res_not_installed["has_update"])
            self.assertEqual(res_not_installed["status"], "not_installed")

            # 2. Cài đặt v1.0.0 -> check_updates thấy có bản mới v1.5.0
            settings_mod.record_installed_mod_receipt("game_alpha", version="v1.0.0")
            res_has_update = api.check_updates("game_alpha")
            self.assertTrue(res_has_update["success"])
            self.assertTrue(res_has_update["has_update"])
            self.assertEqual(res_has_update["status"], "update_available")
            self.assertEqual(res_has_update["latest_version"], "v1.5.0")
            self.assertEqual(res_has_update["installed_version"], "v1.0.0")

            # 3. Cập nhật lên v1.5.0 -> check_updates báo up_to_date
            settings_mod.record_installed_mod_receipt("game_alpha", version="v1.5.0")
            res_up_to_date = api.check_updates("game_alpha")
            self.assertTrue(res_up_to_date["success"])
            self.assertFalse(res_up_to_date["has_update"])
            self.assertEqual(res_up_to_date["status"], "up_to_date")

            # 4. Gỡ cài đặt -> quay về not_installed
            settings_mod.remove_installed_mod_receipt("game_alpha")
            res_after_uninstall = api.check_updates("game_alpha")
            self.assertEqual(res_after_uninstall["status"], "not_installed")

            # 5. Check compatibility
            res_compat = api.check_compatibility("game_alpha")
            self.assertTrue(res_compat["success"])
            self.assertIn("compatibility", res_compat)
            self.assertIn("status", res_compat["compatibility"])

            # 6. Game không tồn tại trong danh mục
            res_unknown = api.check_updates("non_existent_game")
            self.assertFalse(res_unknown["success"])
            self.assertEqual(res_unknown["status"], "game_not_found")
        finally:
            paths_mod.GAMES_JSON = orig_games_json
            paths_mod.CACHE_GAMES_JSON = orig_cache_json
            catalog_mod.GAMES_JSON = orig_cat_games
            catalog_mod.CACHE_GAMES_JSON = orig_cat_cache


if __name__ == "__main__":
    unittest.main()

