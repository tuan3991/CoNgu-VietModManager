# -*- coding: utf-8 -*-
"""
Test Unit: AccountManager (Đổi tài khoản & Kích dữ liệu cũ)
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.account_manager import AccountManager


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="congu_test_acc_")
        self.mock_config = {
            "profile": {
                "player_name": "Tài Khoản Gốc",
                "avatar_url": "preset:space_astro",
                "cover_url": "preset:synthwave",
                "bio": "Bio gốc"
            },
            "community_cloud": {
                "cloud_id": "goc_cloud",
                "is_logged_in": True,
                "password": "123"
            },
            "the_walking_dead_path": "C:\\Games\\TWD",
            "ror2_path": "C:\\Games\\ROR2",
            "favorite_games": ["twd", "ror2"],
            "scanner": {
                "auto_scan_on_startup": True,
                "custom_library_paths": ["D:\\SteamLibrary"]
            }
        }

        # Tạo file dữ liệu mẫu
        with open(os.path.join(self.test_dir, "custom_games.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": "custom_1", "title": "Game Ngoài 1"}], f)

        with open(os.path.join(self.test_dir, "playtime.json"), "w", encoding="utf-8") as f:
            json.dump({"custom_1": 3600}, f)

        with open(os.path.join(self.test_dir, "achievements_progress.json"), "w", encoding="utf-8") as f:
            json.dump({"custom_1": {"ach_1": True}}, f)

        with open(os.path.join(self.test_dir, "PlayerProfile.congu_save"), "w", encoding="utf-8") as f:
            f.write("mock_vault_content")

        self.mgr = AccountManager(
            appdata_dir=self.test_dir,
            config_getter=lambda: self.mock_config,
            config_saver=self._save_mock_config
        )

    def _save_mock_config(self, cfg):
        self.mock_config = cfg

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_initial_status(self):
        status = self.mgr.get_status()
        self.assertTrue(status["success"])
        self.assertEqual(status["total_accounts"], 1)
        active = status["active_account"]
        self.assertEqual(active["name"], "Tài Khoản Gốc")

    def test_02_create_blank_account_purges_all_old_data(self):
        """Kiểm tra: khi tạo tài khoản mới thì máy kích hết dữ liệu cũ ra và để lại app trống."""
        res = self.mgr.create_blank_account(name="Người Chơi Trống", account_type="offline")
        self.assertTrue(res["success"])
        self.assertEqual(res["active_account"]["name"], "Người Chơi Trống")

        # 1. custom_games.json phải bị làm rỗng
        with open(self.mgr.custom_games_file, "r", encoding="utf-8") as f:
            cg = json.load(f)
        self.assertEqual(cg, [], "custom_games.json phải là danh sách rỗng!")

        # 2. playtime.json phải bị làm rỗng
        with open(self.mgr.playtime_file, "r", encoding="utf-8") as f:
            pt = json.load(f)
        self.assertEqual(pt, {}, "playtime.json phải là dict rỗng!")

        # 3. achievements_progress.json phải bị làm rỗng
        with open(self.mgr.achievements_file, "r", encoding="utf-8") as f:
            ach = json.load(f)
        self.assertEqual(ach, {}, "achievements_progress.json phải là dict rỗng!")

        # 4. Save vault cũ phải bị xóa khỏi app
        self.assertFalse(os.path.exists(self.mgr.vault_file), "PlayerProfile.congu_save cũ phải bị xóa khỏi app!")

        # 5. Các game path cũ phải bị kích hết ra khỏi user_config
        self.assertNotIn("the_walking_dead_path", self.mock_config, "Đường dẫn game cũ phải bị xóa!")
        self.assertNotIn("ror2_path", self.mock_config, "Đường dẫn game cũ phải bị xóa!")
        self.assertEqual(self.mock_config.get("favorite_games"), [])
        self.assertFalse(self.mock_config.get("scanner", {}).get("auto_scan_on_startup"), "App trống phải tắt auto_scan_on_startup!")

        # 6. Đăng xuất Community Cloud
        self.assertFalse(self.mock_config.get("community_cloud", {}).get("is_logged_in"))

    def test_03_switch_account_roundtrip(self):
        """Kiểm tra: chuyển sang tài khoản mới rồi chuyển lại tài khoản cũ sẽ khôi phục nguyên vẹn."""
        idx = self.mgr._load_index()
        initial_id = idx["active_account_id"]

        # Tạo tài khoản mới (làm trống app)
        res_new = self.mgr.create_blank_account(name="Tài Khoản Thứ 2", account_type="offline")
        new_id = res_new["active_account"]["id"]

        # Thêm 1 game ngoài cho tài khoản 2
        with open(self.mgr.custom_games_file, "w", encoding="utf-8") as f:
            json.dump([{"id": "game_acc_2"}], f)

        # Chuyển lại về tài khoản ban đầu
        res_back = self.mgr.switch_to_account(initial_id)
        self.assertTrue(res_back["success"])

        # Kiểm tra dữ liệu của tài khoản 1 được khôi phục nguyên vẹn!
        with open(self.mgr.custom_games_file, "r", encoding="utf-8") as f:
            cg1 = json.load(f)
        self.assertEqual(len(cg1), 1)
        self.assertEqual(cg1[0]["id"], "custom_1", "Dữ liệu tài khoản 1 phải được khôi phục chính xác!")

        self.assertIn("the_walking_dead_path", self.mock_config, "Game path của tài khoản 1 phải được khôi phục!")

        # Chuyển lại sang tài khoản 2
        res_to_2 = self.mgr.switch_to_account(new_id)
        self.assertTrue(res_to_2["success"])
        with open(self.mgr.custom_games_file, "r", encoding="utf-8") as f:
            cg2 = json.load(f)
        self.assertEqual(cg2[0]["id"], "game_acc_2", "Dữ liệu tài khoản 2 phải độc lập hoàn toàn!")


if __name__ == "__main__":
    unittest.main()
