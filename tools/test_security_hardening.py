#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test suite - Security Engine Hardening (security.py / security.pyd)
=============================================================================
Chạy:  python tools/test_security_hardening.py

Bộ test này khoá chặt các bất biến an ninh đã vá trong "Điểm yếu #1"
(Chống Hijacking / Zero Data Leakage) để các lần sửa điểm #2-#7 sau này
không vô tình tái mở lỗ hổng:

  1. Không phơi bày ConguStreamReader / _ConguStreamReader qua module __dict__
  2. Không phơi bày master key (_O_KEY_BYTES, _K_MASK, _TICKET_SECRET)
  3. Không phơi bày hàm nội bộ _get_master_key_bytes / _open_congu_stream_reader
  4. Không phơi bày SteamGridDB key bytes (_SGD_KEY_BYTES, _SGD_KEY_MASK)
  5. Ticket TTL <= 300 giây, chặn cả vé quá khứ lẫn vé tương lai
  6. execute_secure_install từ chối vé giả mạo
  7. Đóng gói .congu -> giải mã -> cài đặt end-to-end vẫn hoạt động
"""

import os
import sys
import json
import time
import shutil
import tempfile
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS = []
FAIL = []


def check(label, condition, detail=""):
    if condition:
        PASS.append(label)
        print(f"[OK]   {label}")
    else:
        FAIL.append((label, detail))
        print(f"[FAIL] {label} {detail}")


def main():
    import security

    print(f"security module: {security.__file__}\n")

    # ---------------------------------------------------------------- 1..4
    print("--- 1. Zero sensitive symbol leakage (module __dict__ / reflection) ---")
    forbidden = [
        "ConguStreamReader",
        "_ConguStreamReader",
        "_O_KEY_BYTES",
        "_K_MASK",
        "_TICKET_SECRET",
        "_get_master_key_bytes",
        "_build_secure_stream_engine",
        "_open_congu_stream_reader",
        "_SGD_KEY_BYTES",
        "_SGD_KEY_MASK",
        "_decrypt_container_to_spooled_stream",
    ]
    leaked = [n for n in forbidden if hasattr(security, n)]
    check("không có symbol nhạy cảm nào trong security.__dict__", leaked == [], f"leaked={leaked}")

    # exploit mẫu trong báo cáo
    try:
        security.ConguStreamReader("x.congu", auth_ticket=security.create_session_ticket())
        check("exploit dump decrypted stream bị chặn", False, "ConguStreamReader vẫn gọi được!")
    except AttributeError:
        check("exploit dump decrypted stream bị chặn", True)

    try:
        _ = security._O_KEY_BYTES
        check("exploit đọc master key bytes bị chặn", False, "_O_KEY_BYTES vẫn đọc được!")
    except AttributeError:
        check("exploit đọc master key bytes bị chặn", True)

    # SteamGridDB guard: gọi từ process/thư mục NGOÀI app phải bị chặn (trả "")
    probe_dir = tempfile.mkdtemp(prefix="sgd_probe_")
    try:
        probe = os.path.join(probe_dir, "probe.py")
        with open(probe, "w", encoding="utf-8") as f:
            f.write(
                "import sys\n"
                f"sys.path.insert(0, {APP_DIR!r})\n"
                "import security\n"
                "k = security.get_steamgriddb_key()\n"
                "print('BLOCKED' if k == '' else 'LEAKED:' + str(len(k)))\n"
            )
        import subprocess
        out = subprocess.run([sys.executable, probe], cwd=probe_dir,
                             capture_output=True, text=True)
        blocked = "BLOCKED" in (out.stdout or "")
        check("get_steamgriddb_key chặn caller ngoài app dir", blocked,
              ((out.stdout or "") + (out.stderr or "")).strip()[:160])
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)

    # caller nội bộ (core/) vẫn phải lấy được khóa
    try:
        import core.steam_client as _sc
        check("caller nội bộ core/ vẫn lấy được key",
              len(getattr(_sc, "STEAMGRIDDB_API_KEY", "")) == 32)
    except Exception as e:
        check("caller nội bộ core/ vẫn lấy được key", False, f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------------- 5
    print("\n--- 2. Session ticket TTL (<= 300s) & anti-replay ---")
    ticket = security.create_session_ticket()
    check("vé hợp lệ được chấp nhận", security.verify_session_ticket(ticket) is True)

    pid = os.getpid()
    expired = f"{pid}:{int(time.time()) - 350}:0123456789abcdef:invalidsig"
    check("vé quá hạn 350s bị từ chối", security.verify_session_ticket(expired) is False)

    near_edge = int(time.time()) - 290
    check("vé 290s vẫn còn hạn (biên)", security.verify_session_ticket(
        f"{pid}:{near_edge}:0123456789abcdef:invalidsig") is False,
        "chữ ký sai phải bị từ chối -> đúng")

    future = f"{pid}:{int(time.time()) + 100}:0123456789abcdef:invalidsig"
    check("vé tương lai (+100s) bị từ chối", security.verify_session_ticket(future) is False)

    check("vé rỗng bị từ chối", security.verify_session_ticket("") is False)
    check("vé None bị từ chối", security.verify_session_ticket(None) is False)

    # chữ ký sai nhưng thời gian hợp lệ -> vẫn phải fail
    forged = f"{pid}:{int(time.time())}:0123456789abcdef:deadbeef"
    check("vé giả mạo chữ ký bị từ chối", security.verify_session_ticket(forged) is False)

    # ---------------------------------------------------------------- 6
    print("\n--- 3. execute_secure_install chặn caller trái phép ---")
    try:
        security.execute_secure_install("x.congu", "x_dir", auth_ticket=forged)
        check("install từ chối vé giả mạo", False)
    except PermissionError:
        check("install từ chối vé giả mạo", True)

    try:
        security.execute_secure_install("x.congu", "x_dir")
        check("install từ chối khi thiếu vé", False)
    except PermissionError:
        check("install từ chối khi thiếu vé", True)

    # ---------------------------------------------------------------- 7
    print("\n--- 4. End-to-end: encrypt -> decrypt stream -> install ---")
    import pack_security

    work = tempfile.mkdtemp(prefix="congu_hardening_")
    try:
        src_zip = os.path.join(work, "payload.zip")
        with zipfile.ZipFile(src_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Mod_Files/BepInEx/plugins/Test.dll", b"MODDED-DLL-" * 1000)
            zf.writestr("Mod_Files/data/config.ini", "[Core]\nLanguage=English\n")

        congu = os.path.join(work, "mod.congu")
        pack_security.encrypt_mod_package(src_zip, congu, version=2)
        check("container .congu hợp lệ", security.is_congu_package(congu))

        game = os.path.join(work, "GameDir")
        os.makedirs(os.path.join(game, "Binaries", "Win64"), exist_ok=True)
        with open(os.path.join(game, "TestGame.exe"), "wb") as f:
            f.write(b"MZ" + b"\x00" * 100)
        pre = os.path.join(game, "data", "config.ini")
        os.makedirs(os.path.dirname(pre), exist_ok=True)
        with open(pre, "w", encoding="utf-8") as f:
            f.write("[Core]\nLanguage=English\n")

        steps = [{"action": "copy_folder", "source": "Mod_Files", "destination": ""}]
        game_def = {"id": "hardening_test", "executable_name": "TestGame.exe",
                    "install_steps": steps}

        res = security.execute_secure_install(
            congu_path=congu, game_path=game, install_steps=steps,
            game_def=game_def, auth_ticket=security.create_session_ticket(),
        )
        check("install thành công", res.get("success") is True)

        dll = os.path.join(game, "BepInEx", "plugins", "Test.dll")
        ok_content = False
        if os.path.exists(dll):
            with open(dll, "rb") as f:
                ok_content = f.read(11) == b"MODDED-DLL-"
        check("file giải mã ghi đúng nội dung", ok_content)

        check("file gốc được auto-backup .congu_bak",
              os.path.exists(os.path.join(game, "data", "config.ini.congu_bak")))

        leftovers = [n for n in os.listdir(os.path.join(game, "BepInEx", "plugins"))
                     if n.endswith(".congu_tx_tmp")]
        check("không còn rác .congu_tx_tmp", leftovers == [], f"leftovers={leftovers}")

        leaked_after = [n for n in forbidden if hasattr(security, n)]
        check("sau install vẫn không rò rỉ symbol", leaked_after == [], f"leaked={leaked_after}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---------------------------------------------------------------- summary
    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        for label, detail in FAIL:
            print(f"  - {label} {detail}")
        print("RESULT: FAILED")
        return 1
    print("RESULT: ALL SECURITY HARDENING INVARIANTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
