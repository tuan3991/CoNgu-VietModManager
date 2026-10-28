# -*- coding: utf-8 -*-
"""
Core - Windows Platform Helpers
--------------------------------
Hang so dung chung cho moi lenh subprocess, tranh hien tuong "nhay cua so den"
(console flash) khi ung dung chay o che do GUI (PyInstaller --noconsole).
"""
import subprocess
import sys

# 0x08000000 tren Windows; 0 tren nen tang khac de subprocess khong bao loi.
WIN_NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                 if sys.platform.startswith("win") else 0)

# Co khoi chay tien trinh tach roi (dung cho game / script cap nhat)
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

__all__ = ["WIN_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"]
