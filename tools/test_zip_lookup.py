#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test - Tra cứu thành viên ZIP (Điểm yếu #4)
=====================================================
4a. _find_zip_member: fallback theo basename chỉ hợp lệ khi tên đó là DUY NHẤT.
4b. _find_zip_folder_members: không được nhận nhầm TÊN TỆP thành TÊN THƯ MỤC
    (tránh sub_rel rỗng -> ghi đè lên chính thư mục đích).

Chạy: python tools/test_zip_lookup.py
"""
import io
import os
import sys
import zipfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import security

PASS, FAIL = [], []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
        print(f"[OK]   {label}")
    else:
        FAIL.append((label, detail))
        print(f"[FAIL] {label} {detail}")


def zip_from(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            zf.writestr(n, b"x")
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


def t_member_ambiguous():
    print("\n--- 4a. fallback basename mơ hồ ---")
    zf = zip_from(["Data/level0", "DLC/level0", "Data/other.dat"])
    got = security._find_zip_member(zf, "level0")
    check("2 tệp trùng tên ở thư mục khác -> từ chối fallback (None)", got is None, f"got={got}")
    got = security._find_zip_member(zf, "config.ini")
    check("tên không tồn tại -> None", got is None, f"got={got}")


def t_member_unique():
    print("\n--- 4a. fallback basename duy nhất vẫn hoạt động ---")
    zf = zip_from(["Mod_Files/SomeDir/unique.ini", "Mod_Files/other.dat"])
    got = security._find_zip_member(zf, "unique.ini")
    check("1 tệp duy nhất -> trả về đúng", got == "Mod_Files/SomeDir/unique.ini", f"got={got}")


def t_member_exact():
    print("\n--- 4a. exact / suffix match không bị ảnh hưởng ---")
    zf = zip_from(["Data/level0", "DLC/level0"])
    check("exact path khớp chính xác", security._find_zip_member(zf, "Data/level0") == "Data/level0")
    check("exact path (khác hoa thường)", security._find_zip_member(zf, "data/LEVEL0") == "Data/level0")
    check("suffix match", security._find_zip_member(zf, "DLC/level0") == "DLC/level0")

    zf2 = zip_from(["Mod_Files/data/config.ini", "data/config.ini"])
    got = security._find_zip_member(zf2, "data/config.ini")
    check("suffix trùng -> chọn tệp nông nhất, tất định",
          got == "data/config.ini", f"got={got}")


def t_folder_filename_confusion():
    print("\n--- 4b. tệp trùng tên thư mục không được coi là thư mục ---")
    zf = zip_from(["config/data", "config/readme.txt"])
    res = security._find_zip_folder_members(zf, "data")
    check("file 'config/data' KHÔNG bị nhận là thư mục 'data'", res == [], f"got={[(m.filename, s) for m, s in res]}")

    bad = [(m.filename, s) for m, s in res if s.strip() == ""]
    check("không có sub_rel rỗng", bad == [], f"bad={bad}")


def t_folder_normal():
    print("\n--- 4b. trường hợp thư mục bình thường ---")
    zf = zip_from([
        "BepInEx/plugins/A.dll",
        "BepInEx/plugins/sub/B.dll",
        "BepInEx/config/C.cfg",
        "Mod_Files/BepInEx/plugins/D.dll",
    ])
    res = dict((m.filename, s) for m, s in security._find_zip_folder_members(zf, "BepInEx/plugins"))
    check("khớp đúng thư mục lồng nhau",
          res == {
              "BepInEx/plugins/A.dll": "A.dll",
              "BepInEx/plugins/sub/B.dll": "sub/B.dll",
              "Mod_Files/BepInEx/plugins/D.dll": "D.dll",
          }, f"got={res}")

    res2 = dict((m.filename, s) for m, s in security._find_zip_folder_members(zf, "plugins"))
    check("khớp theo 1 thành phần thư mục",
          set(res2.keys()) == {"BepInEx/plugins/A.dll", "BepInEx/plugins/sub/B.dll",
                               "Mod_Files/BepInEx/plugins/D.dll"}, f"got={res2}")


def t_folder_multi_component_no_false_positive():
    print("\n--- 4b. 'BepInEx/plugins' không khớp nhầm 'Other/plugins' ---")
    zf = zip_from(["Other/plugins/X.dll", "BepInEx/plugins/Y.dll"])
    res = dict((m.filename, s) for m, s in security._find_zip_folder_members(zf, "BepInEx/plugins"))
    check("chỉ lấy đúng cây BepInEx/plugins", set(res.keys()) == {"BepInEx/plugins/Y.dll"}, f"got={res}")


def t_folder_invariant():
    print("\n--- 4b. bất biến: mọi sub_rel đều là đường dẫn tệp hợp lệ ---")
    names = [
        "config/data", "data/x.txt", "a/b/c/d.dat", "data", "data/",
        "x/data/y.bin", "Data/deep/z.bin", "other/data",
    ]
    violations = []
    for folder in ("data", "Data", "b/c", "a", "d"):
        zf = zip_from(names)
        for m, sub in security._find_zip_folder_members(zf, folder):
            if not sub.strip() or sub.startswith("/") or ".." in sub.split("/") or sub.endswith("/"):
                violations.append((folder, m.filename, sub))
    check("không có sub_rel rỗng/tuyệt đối/traversal", violations == [], f"violations={violations}")


def t_integration_no_crash():
    print("\n--- 4b. tích hợp: gói có tệp trùng tên thư mục không làm hỏng cài đặt ---")
    import tempfile
    import shutil
    import pack_security

    work = tempfile.mkdtemp(prefix="congu_zip4_")
    try:
        z = os.path.join(work, "payload.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Mod_Files/data/a.txt", b"AAA")
            zf.writestr("Mod_Files/other/config/data", b"STRAY-FILE-NAMED-DATA")

        cg = os.path.join(work, "m.congu")
        pack_security.encrypt_mod_package(z, cg, version=2)

        game = os.path.join(work, "Game")
        os.makedirs(game)
        with open(os.path.join(game, "TestGame.exe"), "wb") as f:
            f.write(b"MZ" + b"\x00" * 100)

        steps = [{"action": "copy_folder", "source": "data", "destination": "res"}]
        gd = {"id": "zip4", "executable_name": "TestGame.exe", "install_steps": steps}
        try:
            security.execute_secure_install(congu_path=cg, game_path=game, install_steps=steps,
                                            game_def=gd, auth_ticket=security.create_session_ticket())
            ok = True
            err = None
        except Exception as e:
            ok = False
            err = e
        check("install không crash", ok, f"{type(err).__name__}: {err}")
        check("chỉ cài tệp thuộc thư mục data thật",
              os.path.exists(os.path.join(game, "res", "a.txt")))
        check("không ghi đè lên chính thư mục đích res",
              os.path.isdir(os.path.join(game, "res")))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def t_ambiguous_integration():
    print("\n--- 4a. tích hợp: tên trần mơ hồ phải báo lỗi rõ, đường dẫn đầy đủ vẫn chạy ---")
    import tempfile
    import shutil
    import pack_security

    work = tempfile.mkdtemp(prefix="congu_zip4a_")
    try:
        z = os.path.join(work, "payload.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Data/level0", b"DATA-LEVEL0")
            zf.writestr("DLC/level0", b"DLC-LEVEL0")

        cg = os.path.join(work, "m.congu")
        pack_security.encrypt_mod_package(z, cg, version=2)

        def mk_game(tag):
            g = os.path.join(work, tag)
            os.makedirs(g)
            with open(os.path.join(g, "TestGame.exe"), "wb") as f:
                f.write(b"MZ" + b"\x00" * 100)
            return g

        g1 = mk_game("G1")
        steps = [{"action": "copy_file", "source": "level0", "destination": "dump.bin"}]
        gd = {"id": "amb", "executable_name": "TestGame.exe", "install_steps": steps}
        msg = ""
        try:
            security.execute_secure_install(congu_path=cg, game_path=g1, install_steps=steps,
                                            game_def=gd, auth_ticket=security.create_session_ticket())
            ok = False
        except Exception as e:
            ok = True
            msg = str(e)
        check("tên trần mơ hồ -> install bị từ chối", ok)
        check("thông báo nêu rõ MƠ HỒ + danh sách ứng viên",
              "MƠ HỒ" in msg and "DLC/level0" in msg, msg[:160])
        check("không ghi bừa file nào", not os.path.exists(os.path.join(g1, "dump.bin")))

        g2 = mk_game("G2")
        steps2 = [{"action": "copy_file", "source": "DLC/level0", "destination": "dump.bin"}]
        gd2 = {"id": "amb2", "executable_name": "TestGame.exe", "install_steps": steps2}
        security.execute_secure_install(congu_path=cg, game_path=g2, install_steps=steps2,
                                        game_def=gd2, auth_ticket=security.create_session_ticket())
        got = open(os.path.join(g2, "dump.bin"), "rb").read()
        check("đường dẫn đầy đủ -> lấy đúng DLC/level0", got == b"DLC-LEVEL0", f"got={got!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    print(f"security module: {security.__file__}")
    t_member_ambiguous()
    t_member_unique()
    t_member_exact()
    t_folder_filename_confusion()
    t_folder_normal()
    t_folder_multi_component_no_false_positive()
    t_folder_invariant()
    t_integration_no_crash()
    t_ambiguous_integration()

    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        for label, detail in FAIL:
            print(f"  - {label} {detail}")
        print("RESULT: FAILED")
        return 1
    print("RESULT: ZIP LOOKUP OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
