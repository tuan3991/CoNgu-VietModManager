#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: P1-05 Troubleshooting Center & Audit Logs
=====================================================
Kiểm chứng:
1. Danh sách kịch bản hướng dẫn sửa lỗi (Scenarios).
2. Ghi và truy xuất Audit Log theo Job ID (không mất dữ liệu, tự xoay vòng).
3. Đọc và tính toán phạm vi bản sao lưu (Backup Inspection) trước khi restore.
4. Thuật toán tự động che mờ thông tin cá nhân (Redaction) trong Support Report.
5. Tạo báo cáo hỗ trợ kỹ thuật không rò rỉ token / username / mật khẩu.
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

import core.troubleshooter as tb
import core.config_manager.paths as paths_mod


class TestTroubleshooter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="congu-troubleshoot-test-")
        self.appdata_dir = os.path.join(self.temp_dir, "appdata")
        os.makedirs(self.appdata_dir, exist_ok=True)

        self._orig_audit_file = tb.AUDIT_LOG_FILE
        self._orig_backup_root = tb.BACKUP_ROOT

        tb.AUDIT_LOG_FILE = os.path.join(self.appdata_dir, "operation_audit.json")
        tb.BACKUP_ROOT = os.path.join(self.appdata_dir, "backups")
        os.makedirs(tb.BACKUP_ROOT, exist_ok=True)

    def tearDown(self):
        tb.AUDIT_LOG_FILE = self._orig_audit_file
        tb.BACKUP_ROOT = self._orig_backup_root
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenarios_available(self):
        guides = tb.get_troubleshooting_guides()
        self.assertTrue(len(guides) >= 4)
        for g in guides:
            self.assertIn("id", g)
            self.assertIn("title", g)
            self.assertIn("causes", g)
            self.assertIn("solutions", g)
            self.assertTrue(len(g["solutions"]) >= 1)

    def test_audit_logging_and_rotation(self):
        # Ghi 1 sự kiện
        entry = tb.record_audit_event("game1", "install", "success", "Cài đặt thành công", {"ver": "v1.0"})
        self.assertIn("job_id", entry)
        self.assertEqual(entry["game_id"], "game1")
        self.assertEqual(entry["status"], "success")

        # Đọc lại
        logs = tb.get_recent_audit_logs("game1")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "install")

        # Ghi vượt quá giới hạn xoay vòng
        orig_max = tb.MAX_AUDIT_ENTRIES
        tb.MAX_AUDIT_ENTRIES = 5
        try:
            for i in range(10):
                tb.record_audit_event("game1", f"action_{i}", "success", f"Msg {i}")
            logs_after = tb.get_recent_audit_logs("game1", limit=100)
            self.assertLessEqual(len(logs_after), 5)
        finally:
            tb.MAX_AUDIT_ENTRIES = orig_max

    def test_backup_inspection(self):
        game_id = "test_game"
        game_backup_dir = os.path.join(tb.BACKUP_ROOT, game_id)
        os.makedirs(game_backup_dir, exist_ok=True)

        manifest = {
            "game_id": game_id,
            "files": [
                {"relative_in_game": "Data/pak0.pak", "modded_size": 1024 * 1024, "original_sha256": "12345"},
                {"relative_in_game": "Data/pak1.pak", "modded_size": 2048 * 1024, "original_sha256": "67890"}
            ]
        }
        with open(os.path.join(game_backup_dir, "backup_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Tạo thêm file .congu_bak trong game dir giả
        fake_game_dir = os.path.join(self.temp_dir, "game_root")
        os.makedirs(os.path.join(fake_game_dir, "Data"), exist_ok=True)
        bak_file = os.path.join(fake_game_dir, "Data", "config.ini.congu_bak")
        with open(bak_file, "w") as f:
            f.write("abc")

        res = tb.inspect_game_backups(game_id, fake_game_dir)
        self.assertTrue(res["has_backup"])
        self.assertEqual(res["total_files"], 3)  # 2 từ manifest + 1 từ .congu_bak
        self.assertTrue(res["total_size_bytes"] > 0)
        self.assertIn("hoàn nguyên", res["scope_summary"].lower())

    def test_redaction_privacy_protection(self):
        raw_text = (
            "User home is C:\\Users\\tuan3991\\AppData\\Local and "
            "Auth header is token: abcdef1234567890xyz. "
            "Cloud ID is cloud_id: secret_user_9988."
        )
        redacted = tb.redact_sensitive_info(raw_text)
        self.assertNotIn("tuan3991", redacted)
        self.assertIn("C:\\Users\\<USER>\\AppData", redacted)
        self.assertNotIn("abcdef1234567890xyz", redacted)
        self.assertIn("***REDACTED***", redacted)
        self.assertNotIn("secret_user_9988", redacted)

    def test_generate_support_report_anonymity(self):
        # Ghi 1 log có chứa token giả lập
        tb.record_audit_event("game1", "install", "error", "Lỗi token: secret_api_key_12345")
        rep = tb.generate_support_report("game1")
        self.assertTrue(rep["success"])
        self.assertIn("report_text", rep)
        self.assertNotIn("secret_api_key_12345", rep["report_text"])
        self.assertIn("CỔ NGỮ", rep["report_text"])


if __name__ == "__main__":
    unittest.main()

