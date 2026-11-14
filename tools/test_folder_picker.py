# -*- coding: utf-8 -*-
import sys
import os
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from api.ipc_bridge import ModManagerAPI

class TestFolderPicker(unittest.TestCase):
    def setUp(self):
        self.api = ModManagerAPI()

    def test_select_vault_dialog_method_exists(self):
        self.assertTrue(hasattr(self.api, "select_vault_file_dialog"), "select_vault_file_dialog must exist on ModManagerAPI")

    def test_select_folder_cancelled(self):
        with patch("api.ipc_bridge.pick_folder", return_value=None):
            res = self.api.select_folder("the_genesis_order")
            self.assertFalse(res["success"])
            self.assertIn("Không có thư mục nào được chọn", res["message"])

    def test_select_folder_valid(self):
        dummy_dir = os.path.abspath("test_dummy_dir_picker")
        os.makedirs(dummy_dir, exist_ok=True)
        dummy_exe = os.path.join(dummy_dir, "The Genesis Order.exe")
        with open(dummy_exe, "w") as f:
            f.write("exe")

        try:
            with patch("api.ipc_bridge.pick_folder", return_value=dummy_dir):
                res = self.api.select_folder("the_genesis_order")
                self.assertTrue(res["success"])
                self.assertEqual(os.path.normpath(res["path"]), os.path.normpath(dummy_dir))
        finally:
            if os.path.exists(dummy_exe):
                os.remove(dummy_exe)
            if os.path.exists(dummy_dir):
                os.rmdir(dummy_dir)

if __name__ == "__main__":
    unittest.main()
