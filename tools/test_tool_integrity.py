#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test - Điểm yếu #5
=============================
5a. find_tool_exe chỉ trả về công cụ có SHA-256 khớp whitelist (chống Binary Planting).
5b. _safe_replace / _safe_rename retry khi file bị antivirus khóa tạm thời.
5c. execute_secure_install tự ghi backup_manifest.json (merge, không trùng, atomic).

Chạy: python tools/test_tool_integrity.py
"""
import os
import sys
import json
import time
import shutil
import zipfile
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import security
import pack_security

PASS, FAIL = [], []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
        print(f"[OK]   {label}")
    else:
        FAIL.append((label, detail))
        print(f"[FAIL] {label} {detail}")


# ---------------------------------------------------------------- 5a
def test_tool_whitelist():
    print("\n--- 5a. whitelist SHA-256 công cụ ---")
    real = security.find_tool_exe("xdelta3")
    check("tìm được xdelta3.exe thật (khớp hash)", bool(real), f"got={real}")
    if real:
        ok, digest = security._verify_tool_hash(real, "xdelta3.exe")
        check("_verify_tool_hash xác nhận đúng", ok and digest in security._TOOL_SHA256["xdelta3.exe"])

    tmp = tempfile.mkdtemp(prefix="plant_")
    old_cwd = os.getcwd()
    try:
        # 1. File giả trong cwd/tools
        os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)
        fake_tools = os.path.join(tmp, "tools", "xdelta3.exe")
        with open(fake_tools, "wb") as f:
            f.write(b"MZ-EVIL-PLANTED-BINARY" * 100)
        # 2. File giả ngay trong cwd
        fake_cwd = os.path.join(tmp, "xdelta3.exe")
        with open(fake_cwd, "wb") as f:
            f.write(b"MZ-EVIL-PLANTED-BINARY-2" * 100)

        ok1, h1 = security._verify_tool_hash(fake_tools, "xdelta3.exe")
        ok2, h2 = security._verify_tool_hash(fake_cwd, "xdelta3.exe")
        check("hash file giả trong cwd/tools bị từ chối", ok1 is False, f"hash={h1}")
        check("hash file giả ngay trong cwd bị từ chối", ok2 is False, f"hash={h2}")

        os.chdir(tmp)
        found = security.find_tool_exe("xdelta3")
        check("find_tool_exe KHÔNG trả về file giả (dù cwd đứng trước)",
              found != fake_cwd and found != fake_tools, f"got={found}")
        if found:
            okf, _ = security._verify_tool_hash(found, "xdelta3.exe")
            check("kết quả trả về luôn khớp whitelist", okf)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    # công cụ lạ không có trong whitelist -> luôn từ chối
    okx, _ = security._verify_tool_hash(__file__, "unknown.exe")
    check("công cụ không có trong whitelist bị từ chối", okx is False)


# ---------------------------------------------------------------- 5b
def test_safe_replace():
    print("\n--- 5b. _safe_replace / _safe_rename retry ---")
    tmp = tempfile.mkdtemp(prefix="sr_")
    try:
        src = os.path.join(tmp, "a.txt")
        dst = os.path.join(tmp, "b.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("hello")

        # Bình thường
        ok = security._safe_replace(src, dst)
        check("replace bình thường OK", ok is True and os.path.exists(dst) and not os.path.exists(src))

        # Giả lập antivirus khóa 2 lần đầu
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(s, d):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(13, "file bi khoa tam thoi (Defender)")
            return real_replace(s, d)

        src2 = os.path.join(tmp, "c.txt")
        dst2 = os.path.join(tmp, "d.txt")
        with open(src2, "w", encoding="utf-8") as f:
            f.write("world")
        os.replace = flaky
        try:
            t0 = time.perf_counter()
            ok2 = security._safe_replace(src2, dst2, retries=5, delay=0.05)
            elapsed = time.perf_counter() - t0
        finally:
            os.replace = real_replace
        check("retry thành công sau 2 lần bị khóa", ok2 is True and os.path.exists(dst2))
        check("đã thử đúng 3 lần", calls["n"] == 3, f"calls={calls['n']}")
        check("có chờ giữa các lần thử", elapsed >= 0.09, f"elapsed={elapsed:.3f}s")

        # FileNotFoundError không retry
        calls["n"] = 0
        src3 = os.path.join(tmp, "missing.txt")
        dst3 = os.path.join(tmp, "x.txt")
        try:
            security._safe_replace(src3, dst3, retries=5, delay=0.01)
            check("nguồn không tồn tại -> raise FileNotFoundError", False)
        except FileNotFoundError:
            check("nguồn không tồn tại -> raise FileNotFoundError", True)
        check("không retry vô nghĩa với FileNotFoundError", calls["n"] == 0, f"calls={calls['n']}")

        # _safe_rename
        src4 = os.path.join(tmp, "e.txt")
        dst4 = os.path.join(tmp, "f.txt")
        with open(src4, "w", encoding="utf-8") as f:
            f.write("ren")
        ok4 = security._safe_rename(src4, dst4)
        check("_safe_rename hoạt động", ok4 is True and os.path.exists(dst4) and not os.path.exists(src4))

        # hết lượt retry -> raise đúng lỗi cuối
        os.replace = lambda s, d: (_ for _ in ()).throw(PermissionError(13, "always locked"))
        try:
            src5 = os.path.join(tmp, "g.txt")
            with open(src5, "w", encoding="utf-8") as f:
                f.write("x")
            security._safe_replace(src5, os.path.join(tmp, "h.txt"), retries=3, delay=0.01)
            check("hết retry -> raise PermissionError", False)
        except PermissionError:
            check("hết retry -> raise PermissionError", True)
        finally:
            os.replace = real_replace
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 5c
def test_manifest_persist():
    print("\n--- 5c. tự ghi backup_manifest.json ---")
    tmp = tempfile.mkdtemp(prefix="mani_")
    old_appdata = os.environ.get("APPDATA")
    fake_appdata = os.path.join(tmp, "AppData")
    os.makedirs(fake_appdata, exist_ok=True)
    os.environ["APPDATA"] = fake_appdata
    try:
        z = os.path.join(tmp, "p.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Mod_Files/data/config.ini", "[Core]\nLanguage=Vietnamese\n")
        cg = os.path.join(tmp, "m.congu")
        pack_security.encrypt_mod_package(z, cg, version=2)

        game = os.path.join(tmp, "Game")
        os.makedirs(os.path.join(game, "data"), exist_ok=True)
        with open(os.path.join(game, "TestGame.exe"), "wb") as f:
            f.write(b"MZ" + b"\x00" * 100)
        pre = os.path.join(game, "data", "config.ini")
        with open(pre, "w", encoding="utf-8") as f:
            f.write("[Core]\nLanguage=English\n")

        steps = [{"action": "copy_folder", "source": "Mod_Files", "destination": ""}]
        gd = {"id": "mani_test", "executable_name": "TestGame.exe", "install_steps": steps}
        res = security.execute_secure_install(congu_path=cg, game_path=game, install_steps=steps,
                                              game_def=gd, auth_ticket=security.create_session_ticket())
        mpath = os.path.join(fake_appdata, "VietModHub", "backups", "mani_test", "backup_manifest.json")
        check("manifest được tạo ngay trong engine", os.path.exists(mpath))
        check("kết quả trả về manifest_saved=True", res.get("manifest_saved") is True)

        m = json.load(open(mpath, encoding="utf-8"))
        files = m.get("files") or []
        check("có bản ghi file đã backup", len(files) >= 1, f"files={len(files)}")
        entry = next((f for f in files if (f.get("relative_in_game") or "").endswith("config.ini")), None)
        check("entry có original_sha256", bool(entry and entry.get("original_sha256")))
        check("entry có modded_sha256 (không cần caller)", bool(entry and entry.get("modded_sha256")))
        check("giữ winhttp_preexisting trong manifest", "winhttp_preexisting" in m)

        # Cài lần 2 -> không nhân bản entry
        before = len(files)
        security.execute_secure_install(congu_path=cg, game_path=game, install_steps=steps,
                                        game_def=gd, auth_ticket=security.create_session_ticket())
        m2 = json.load(open(mpath, encoding="utf-8"))
        check("cài lại không tạo entry trùng", len(m2.get("files") or []) == before,
              f"{before} -> {len(m2.get('files') or [])}")

        # Không để lại file .tmp
        leftover = [n for n in os.listdir(os.path.dirname(mpath)) if n.endswith(".tmp")]
        check("không còn manifest .tmp", leftover == [], f"{leftover}")
    finally:
        if old_appdata is not None:
            os.environ["APPDATA"] = old_appdata
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print(f"security module: {security.__file__}")
    test_tool_whitelist()
    test_safe_replace()
    test_manifest_persist()

    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        for label, detail in FAIL:
            print(f"  - {label} {detail}")
        print("RESULT: FAILED")
        return 1
    print("RESULT: TOOL INTEGRITY / MANIFEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
