#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test - An toàn dữ liệu khi Rollback cho action `delete` và `rename`
(Điểm yếu #3).

Bất biến được khoá:
  A. delete + lỗi bước sau  -> tệp/thư mục bị xóa phải được phục hồi NGUYÊN VẸN
  B. delete thành công       -> tệp thực sự bị xóa, không còn rác .congu_tx_tmp
  C. rename (dst đã tồn tại) + lỗi bước sau
                             -> src quay về chỗ cũ VÀ dst nguyên bản được phục hồi
  D. rename thành công       -> dst mang nội dung của src, bản dst cũ bị xóa (commit)
  E. rename (dst chưa tồn tại) + lỗi -> src phục hồi, dst không tồn tại

Chạy: python tools/test_rollback_safety.py
"""
import os
import sys
import zipfile
import tempfile
import shutil

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


def make_game(root):
    game = os.path.join(root, "Game")
    os.makedirs(game, exist_ok=True)
    with open(os.path.join(game, "TestGame.exe"), "wb") as f:
        f.write(b"MZ" + b"\x00" * 100)
    return game


def make_container(root):
    """Tạo .congu tối thiểu (có 1 member giả) để zipfile mở được."""
    z = os.path.join(root, "payload.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dummy.txt", b"dummy payload")
    cg = os.path.join(root, "mod.congu")
    pack_security.encrypt_mod_package(z, cg, version=2)
    return cg


def run_install(cg, game, steps, expect_ok=True):
    gd = {"id": "rb_safety", "executable_name": "TestGame.exe", "install_steps": steps}
    try:
        security.execute_secure_install(
            congu_path=cg, game_path=game, install_steps=steps, game_def=gd,
            auth_ticket=security.create_session_ticket(),
        )
        return True, None
    except Exception as e:
        return False, e


def leftovers(dir_path):
    out = []
    for root, _dirs, files in os.walk(dir_path):
        for f in files:
            if f.endswith((".congu_tx_tmp", ".tmp")) or ".congu_del_" in f or ".congu_rename_" in f:
                out.append(os.path.relpath(os.path.join(root, f), dir_path))
        for d in _dirs:
            if d.endswith((".congu_tx_tmp", ".tmp")):
                out.append(os.path.relpath(os.path.join(root, d), dir_path))
    return sorted(out)


FAIL_STEP = {"action": "copy_file", "source": "khong_ton_tai.bin", "destination": "zz.bin"}


def case_a(root):
    print("\n--- A. delete + lỗi bước sau => phải phục hồi nguyên vẹn ---")
    game = make_game(root)
    cg = make_container(root)
    f = os.path.join(game, "old_mod.dll")
    payload = b"ORIGINAL-MOD-BYTES" * 500
    with open(f, "wb") as fh:
        fh.write(payload)

    ok, err = run_install(cg, game, [{"action": "delete", "target": "old_mod.dll"}, FAIL_STEP])
    check("install báo lỗi và kích hoạt rollback", ok is False)
    restored = os.path.exists(f) and open(f, "rb").read() == payload
    check("tệp bị delete được phục hồi nguyên vẹn", restored)
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def case_a_dir(root):
    print("\n--- A2. delete THƯ MỤC + lỗi bước sau => phục hồi cả cây ---")
    game = make_game(root)
    cg = make_container(root)
    d = os.path.join(game, "OldFolder", "sub")
    os.makedirs(d)
    with open(os.path.join(d, "a.bin"), "wb") as fh:
        fh.write(b"AAA" * 100)
    with open(os.path.join(game, "OldFolder", "b.txt"), "w", encoding="utf-8") as fh:
        fh.write("hello")

    ok, _ = run_install(cg, game, [{"action": "delete", "target": "OldFolder"}, FAIL_STEP])
    check("install báo lỗi", ok is False)
    ok_tree = (os.path.exists(os.path.join(game, "OldFolder", "sub", "a.bin"))
               and open(os.path.join(game, "OldFolder", "sub", "a.bin"), "rb").read() == b"AAA" * 100
               and open(os.path.join(game, "OldFolder", "b.txt"), encoding="utf-8").read() == "hello")
    check("thư mục bị delete được phục hồi đầy đủ", ok_tree)
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def case_b(root):
    print("\n--- B. delete thành công => xóa thật (commit) ---")
    game = make_game(root)
    cg = make_container(root)
    f = os.path.join(game, "to_remove.dll")
    with open(f, "wb") as fh:
        fh.write(b"bye" * 100)

    ok, err = run_install(cg, game, [{"action": "delete", "target": "to_remove.dll"}])
    check("install thành công", ok is True, str(err))
    check("tệp thực sự đã bị xóa", not os.path.exists(f))
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def case_c(root):
    print("\n--- C. rename (dst đã tồn tại) + lỗi => phục hồi CẢ src và dst ---")
    game = make_game(root)
    cg = make_container(root)
    src = os.path.join(game, "src.dat")
    dst = os.path.join(game, "dst.dat")
    src_bytes = b"SRC-CONTENT" * 300
    dst_bytes = b"DST-ORIGINAL" * 300
    with open(src, "wb") as fh:
        fh.write(src_bytes)
    with open(dst, "wb") as fh:
        fh.write(dst_bytes)

    ok, _ = run_install(cg, game, [
        {"action": "rename", "source": "src.dat", "destination": "dst.dat"},
        FAIL_STEP,
    ])
    check("install báo lỗi", ok is False)
    check("src.dat được phục hồi nguyên vẹn",
          os.path.exists(src) and open(src, "rb").read() == src_bytes)
    check("dst.dat NGUYÊN BẢN được phục hồi (không mất vĩnh viễn)",
          os.path.exists(dst) and open(dst, "rb").read() == dst_bytes)
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def case_d(root):
    print("\n--- D. rename thành công => dst = nội dung src, bản dst cũ bị xóa ---")
    game = make_game(root)
    cg = make_container(root)
    src = os.path.join(game, "src.dat")
    dst = os.path.join(game, "dst.dat")
    src_bytes = b"SRC-CONTENT" * 300
    with open(src, "wb") as fh:
        fh.write(src_bytes)
    with open(dst, "wb") as fh:
        fh.write(b"DST-ORIGINAL" * 300)

    ok, err = run_install(cg, game, [
        {"action": "rename", "source": "src.dat", "destination": "dst.dat"},
    ])
    check("install thành công", ok is True, str(err))
    check("dst.dat mang nội dung của src", open(dst, "rb").read() == src_bytes)
    check("src.dat không còn", not os.path.exists(src))
    check("không còn rác tạm (bản dst cũ đã bị dọn)", leftovers(game) == [], str(leftovers(game)))


def case_e(root):
    print("\n--- E. rename (dst chưa tồn tại) + lỗi => src phục hồi, dst không có ---")
    game = make_game(root)
    cg = make_container(root)
    src = os.path.join(game, "src2.dat")
    dst = os.path.join(game, "dst2.dat")
    src_bytes = b"SRC2" * 200
    with open(src, "wb") as fh:
        fh.write(src_bytes)

    ok, _ = run_install(cg, game, [
        {"action": "rename", "source": "src2.dat", "destination": "dst2.dat"},
        FAIL_STEP,
    ])
    check("install báo lỗi", ok is False)
    check("src2.dat được phục hồi",
          os.path.exists(src) and open(src, "rb").read() == src_bytes)
    check("dst2.dat không tồn tại sau rollback", not os.path.exists(dst))
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def case_f(root):
    print("\n--- F. delete + rename kết hợp, lỗi cuối => hoàn nguyên toàn bộ ---")
    game = make_game(root)
    cg = make_container(root)
    d = os.path.join(game, "del.dll")
    s = os.path.join(game, "a.dat")
    t = os.path.join(game, "b.dat")
    with open(d, "wb") as fh:
        fh.write(b"DEL-ME" * 100)
    with open(s, "wb") as fh:
        fh.write(b"A-DATA" * 100)
    with open(t, "wb") as fh:
        fh.write(b"B-ORIGINAL" * 100)

    ok, _ = run_install(cg, game, [
        {"action": "delete", "target": "del.dll"},
        {"action": "rename", "source": "a.dat", "destination": "b.dat"},
        FAIL_STEP,
    ])
    check("install báo lỗi", ok is False)
    check("del.dll phục hồi", os.path.exists(d) and open(d, "rb").read() == b"DEL-ME" * 100)
    check("a.dat phục hồi", os.path.exists(s) and open(s, "rb").read() == b"A-DATA" * 100)
    check("b.dat nguyên bản phục hồi", os.path.exists(t) and open(t, "rb").read() == b"B-ORIGINAL" * 100)
    check("không còn rác tạm", leftovers(game) == [], str(leftovers(game)))


def main():
    print(f"security module: {security.__file__}")
    root = tempfile.mkdtemp(prefix="congu_rb3_")
    try:
        for i, fn in enumerate((case_a, case_a_dir, case_b, case_c, case_d, case_e, case_f)):
            sub = os.path.join(root, f"c{i}")
            os.makedirs(sub, exist_ok=True)
            fn(sub)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        for label, detail in FAIL:
            print(f"  - {label} {detail}")
        print("RESULT: FAILED")
        return 1
    print("RESULT: ROLLBACK SAFETY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
