#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Đo I/O thực tế của patch_binary (Điểm yếu #2).

Cách đo: nạp security.py dưới dạng module thuần Python để có thể bọc
compute_file_sha256() và đếm số lượt đọc toàn bộ tệp (full-file read).
"""
import os
import sys
import json
import time
import shutil
import tempfile
import zipfile
import importlib.util

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Load security.py source (pure python) so we can instrument it
spec = importlib.util.spec_from_file_location("security", os.path.join(APP, "security.py"))
security = importlib.util.module_from_spec(spec)
sys.modules["security"] = security
spec.loader.exec_module(security)

import pack_security

READS = []          # list of (path, size)
_orig_sha = security.compute_file_sha256


def counting_sha(path):
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    # Bỏ qua file .exe công cụ: từ Điểm #5a find_tool_exe buộc phải băm
    # xdelta3/hpatchz/hdiffz để chống Binary Planting. Đó là chi phí một lần,
    # không phải I/O của tệp game đang được vá.
    if str(path).lower().endswith(".exe"):
        return _orig_sha(path)
    READS.append((os.path.basename(path), size))
    return _orig_sha(path)


security.compute_file_sha256 = counting_sha

work = tempfile.mkdtemp(prefix="congu_io_")
try:
    # ---- tệp "lớn" 12 MB (đại diện cho .pak 4GB, tỉ lệ I/O y hệt) ----
    SIZE = 12 * 1024 * 1024
    orig_bytes = bytes((i * 37 + 11) & 0xFF for i in range(SIZE))
    orig_bytes = (orig_bytes * ((SIZE // len(orig_bytes)) + 1))[:SIZE]
    modded_bytes = bytearray(orig_bytes)
    modded_bytes[0:1024] = b"VIET-HOA-PATCHED" * 64      # thay đổi đầu tệp
    modded_bytes[-1024:] = b"TAIL-MODIFIED!" * 64         # thay đổi cuối tệp
    modded_bytes = bytes(modded_bytes)

    game = os.path.join(work, "GameDir")
    os.makedirs(game, exist_ok=True)
    with open(os.path.join(game, "TestGame.exe"), "wb") as f:
        f.write(b"MZ" + b"\x00" * 100)

    target = os.path.join(game, "resources.assets")
    with open(target, "wb") as f:
        f.write(orig_bytes)
    orig_sha = _orig_sha(target)

    # ---- tạo patch thật bằng xdelta3 ----
    src_file = os.path.join(work, "orig.bin")
    mod_file = os.path.join(work, "mod.bin")
    patch_file = os.path.join(work, "resources.patch")
    with open(src_file, "wb") as f:
        f.write(orig_bytes)
    with open(mod_file, "wb") as f:
        f.write(modded_bytes)
    security.create_binary_patch(src_file, mod_file, patch_file, algorithm="xdelta")
    print(f"patch created: {os.path.getsize(patch_file):,} bytes (target {SIZE:,} bytes)")

    # ---- đóng gói .congu chứa patch ----
    src_zip = os.path.join(work, "payload.zip")
    with zipfile.ZipFile(src_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(patch_file, "patches/resources.patch")
    congu = os.path.join(work, "mod.congu")
    pack_security.encrypt_mod_package(src_zip, congu, version=2)

    steps = [{
        "action": "patch_binary",
        "target": "resources.assets",
        "patch": "patches/resources.patch",
        "original_sha256": orig_sha,
        "patched_sha256": _orig_sha(mod_file),
    }]
    game_def = {"id": "io_test", "executable_name": "TestGame.exe", "install_steps": steps}

    READS.clear()
    t0 = time.perf_counter()
    res = security.execute_secure_install(
        congu_path=congu, game_path=game, install_steps=steps,
        game_def=game_def, auth_ticket=security.create_session_ticket(),
    )
    elapsed = time.perf_counter() - t0

    # ---- kết quả ----
    with open(target, "rb") as f:
        final = f.read()
    ok_content = final == modded_bytes
    bak = target + ".congu_bak"
    ok_bak = os.path.exists(bak) and open(bak, "rb").read() == orig_bytes

    print("\n--- I/O REPORT (patch_binary) ---")
    total = 0
    for name, size in READS:
        total += size
        print(f"  full-file read: {name:<50} {size:>12,} bytes")
    print(f"  => số lượt đọc toàn tệp: {len(READS)} | tổng {total:,} bytes "
          f"({total / SIZE:.2f}x kích thước tệp)")

    entry = (res.get("backed_up_files") or [{}])[0]
    print(f"  modded_sha256 ghi nhận sẵn: {bool(entry.get('modded_sha256'))}")
    print(f"  original_sha256 khớp: {entry.get('original_sha256') == orig_sha}")

    print("\n--- ASSERTIONS ---")
    print(f"[{'OK' if ok_content else 'FAIL'}] tệp sau vá đúng nội dung mod")
    print(f"[{'OK' if ok_bak else 'FAIL'}] .congu_bak giữ nguyên bản gốc")
    print(f"[{'OK' if res.get('success') else 'FAIL'}] install success")
    print(f"[{'OK' if entry.get('modded_sha256') else 'FAIL'}] modded_sha256 có sẵn từ bước vá")
    expect_reads = 2  # hash kiểm tra phiên bản + hash sau vá
    print(f"[{'OK' if len(READS) <= expect_reads else 'FAIL'}] số lượt đọc <= {expect_reads} (thực tế {len(READS)})")
    print(f"  thời gian: {elapsed:.2f}s")
finally:
    shutil.rmtree(work, ignore_errors=True)
