#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sinh lại whitelist SHA-256 cho các công cụ nhị phân trong security.py.

Dùng khi BẠN chủ động nâng cấp xdelta3.exe / hpatchz.exe / hdiffz.exe bằng bản
tải từ nguồn chính thức. Script in ra block _TOOL_SHA256 để dán vào security.py.

Chạy: python tools/gen_tool_hashes.py
"""
import os
import sys
import hashlib

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ("xdelta3.exe", "hpatchz.exe", "hdiffz.exe")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest().lower()


def main():
    search_dirs = [
        os.path.join(APP, "tools"),
        os.path.join(APP, "dist", "VietModHub", "_internal", "tools"),
        os.path.join(APP, "VietModHub_Portable", "_internal", "tools"),
    ]
    print("# ==== _TOOL_SHA256 (dan vao security.py) ====")
    print("_TOOL_SHA256 = {")
    missing = []
    for exe in TOOLS:
        found = None
        for d in search_dirs:
            p = os.path.join(d, exe)
            if os.path.isfile(p):
                found = p
                break
        if not found:
            missing.append(exe)
            continue
        digest = sha256(found)
        print(f'    "{exe}": frozenset({{')
        print(f'        "{digest}",')
        print('    }),')
        print(f"    # nguon: {os.path.relpath(found, APP)} | {os.path.getsize(found):,} bytes")
    print("}")

    if missing:
        print(f"\n[!] Khong tim thay: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Canh bao neu cac ban copy trong repo khong dong nhat
    print("\n# ==== Kiem tra dong nhat giua cac thu muc ====")
    for exe in TOOLS:
        hashes = {}
        for d in search_dirs:
            p = os.path.join(d, exe)
            if os.path.isfile(p):
                hashes[os.path.relpath(p, APP)] = sha256(p)
        uniq = set(hashes.values())
        status = "OK" if len(uniq) == 1 else "KHAC NHAU!"
        print(f"#   {exe}: {status} ({len(hashes)} ban copy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
