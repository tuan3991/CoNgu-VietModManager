#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: P1-02 Preflight Game Doctor
======================================
Kiểm chứng:
1. Kiểm tra dung lượng ổ đĩa (Disk space check): chặn khi thiếu dung lượng.
2. Kiểm tra quyền ghi thư mục game (Directory writable check): phát hiện UAC / Program Files.
3. Kiểm tra tiến trình game đang chạy (Process check): phát hiện và chặn khi game mở.
4. Lọc runtime theo engine game: Unreal không kiểm tra BepInEx/.NET không cần thiết.
5. Phát hiện xung đột loader / mod khác (BepInEx, ReShade, injector).
6. Tạo kế hoạch thay đổi (Change Plan preview) & vị trí sao lưu trước khi cài đặt.
7. Phân biệt rõ lỗi chặn (blocker) và cảnh báo (warning).
"""
import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.preflight_doctor as doctor


class TestPreflightDoctor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="congu-preflight-test-")
        self.fake_game_dir = os.path.join(self.temp_dir, "fake_game")
        os.makedirs(self.fake_game_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_disk_space_sufficient(self):
        # Giả lập ổ đĩa còn 10 GB trống
        fake_usage = MagicMock(total=100 * 1024**3, used=90 * 1024**3, free=10 * 1024**3)
        with patch("shutil.disk_usage", return_value=fake_usage):
            res = doctor._check_disk_space({"id": "game1", "mod_size": "~10 MB"}, self.fake_game_dir)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res.get("severity"), "ok")

    def test_disk_space_insufficient_blocks(self):
        # Giả lập ổ đĩa chỉ còn 10 MB trống, trong khi cần ít nhất 150 MB buffer
        fake_usage = MagicMock(total=100 * 1024**3, used=100 * 1024**3, free=10 * 1024**2)
        with patch("shutil.disk_usage", return_value=fake_usage):
            res = doctor._check_disk_space({"id": "game1", "mod_size": "~10 MB"}, self.fake_game_dir)
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("severity"), "blocker")
            self.assertIn("dung lượng", res["detail"].lower())

    def test_write_permission_writable(self):
        res = doctor._check_write_permission(self.fake_game_dir)
        self.assertEqual(res["status"], "ok")

    def test_write_permission_read_only_blocks(self):
        with patch("security.check_directory_writable", return_value=False), \
             patch("security.is_running_as_admin", return_value=False):
            res = doctor._check_write_permission(self.fake_game_dir)
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("severity"), "blocker")
            self.assertIn("Admin", res["hint"])

    def test_game_running_detection_blocks(self):
        game_cfg = {"id": "game1", "vietnamese_title": "Game Test", "executable_name": "Game.exe"}
        # Khi game đang chạy
        with patch("core.installer_pipeline.process_checker.check_game_running", return_value=(True, "Game.exe")):
            res = doctor._check_game_process(game_cfg, self.fake_game_dir)
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("severity"), "blocker")
            self.assertIn("Game.exe", res["detail"])

        # Khi game không chạy
        with patch("core.installer_pipeline.process_checker.check_game_running", return_value=(False, None)):
            res = doctor._check_game_process(game_cfg, self.fake_game_dir)
            self.assertEqual(res["status"], "ok")

    def test_engine_specific_runtime_filtering(self):
        # Game Unreal Engine thuần: không dùng BepInEx và không bắt buộc .NET
        unreal_cfg = {
            "id": "unreal_game",
            "engine": "Unreal Engine 5.1",
            "mod_type": "pak",
            "target_pak_name": "mod.pak"
        }
        winhttp_check = doctor._check_winhttp(unreal_cfg, self.fake_game_dir)
        self.assertEqual(winhttp_check["status"], "skip")

        # Game dùng BepInEx: yêu cầu winhttp.dll
        bepinex_cfg = {
            "id": "unity_bepinex",
            "engine": "Unity",
            "mod_type": "bepinex_language",
            "target_pak_name": "Translation.txt"
        }
        winhttp_check_bep = doctor._check_winhttp(bepinex_cfg, self.fake_game_dir)
        self.assertIn(winhttp_check_bep["status"], ("warn", "error", "ok"))

    def test_mod_conflicts_detection(self):
        # Giả lập có ReShade dxgi.dll trong thư mục game
        dxgi_file = os.path.join(self.fake_game_dir, "dxgi.dll")
        with open(dxgi_file, "w") as f:
            f.write("fake injector")

        game_cfg = {"id": "game1", "engine": "Unity"}
        res = doctor._check_mod_conflicts(game_cfg, self.fake_game_dir)
        self.assertEqual(res["status"], "warn")
        self.assertIn("ReShade", res["detail"])

    def test_change_plan_generation(self):
        # Tạo sẵn file gốc để xem có phát hiện cần backup không
        sub_dir = os.path.join(self.fake_game_dir, "Content", "Paks")
        os.makedirs(sub_dir, exist_ok=True)
        orig_file = os.path.join(sub_dir, "game_data.pak")
        with open(orig_file, "w") as f:
            f.write("original")

        game_cfg = {
            "id": "game1",
            "vietnamese_title": "Game Test",
            "relative_install_path": "Content/Paks",
            "target_pak_name": "game_data.pak",
            "install_steps": [
                {"action": "backup", "target": "Content/Paks/game_data.pak"},
                {"action": "copy_file", "source": "mod.pak", "target": "Content/Paks/game_data.pak"}
            ]
        }
        plan = doctor.generate_change_plan(game_cfg, self.fake_game_dir)
        self.assertEqual(plan["game_id"], "game1")
        self.assertIn(".congu_bak", plan["backup_destination"])
        self.assertTrue(len(plan["files_to_modify"]) >= 1)
        self.assertTrue(len(plan["files_to_backup"]) >= 1)

    def test_run_preflight_aggregate(self):
        game_cfg = {
            "id": "game1",
            "vietnamese_title": "Game Test",
            "engine": "Unreal Engine 4.27",
            "relative_install_path": "Paks",
            "target_pak_name": "mod.pak"
        }
        # Khi mọi thứ đều ổn
        with patch("core.installer_pipeline.process_checker.check_game_running", return_value=(False, None)), \
             patch("shutil.disk_usage", return_value=MagicMock(total=100*1024**3, used=50*1024**3, free=50*1024**3)), \
             patch("core.preflight_doctor._check_vc_runtime", return_value={"id": "vc_runtime", "status": "ok", "label": "VC++"}):
            rep = doctor.run_preflight(game_cfg, self.fake_game_dir, operation="install")
            self.assertTrue(rep["ok"])
            self.assertFalse(rep["is_blocked"])
            self.assertIn("change_plan", rep)

        # Khi có lỗi chặn (Game đang chạy)
        with patch("core.installer_pipeline.process_checker.check_game_running", return_value=(True, "Game.exe")):
            rep = doctor.run_preflight(game_cfg, self.fake_game_dir, operation="install")
            self.assertFalse(rep["ok"])
            self.assertTrue(rep["is_blocked"])
            self.assertEqual(rep["severity"], "error")
            self.assertTrue(len(rep["blockers"]) > 0)


if __name__ == "__main__":
    unittest.main()

