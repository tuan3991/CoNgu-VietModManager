import os
import sys
import subprocess
import shutil

# Console Windows mac dinh la cp1252 -> khong in duoc tieng Viet. Ep UTF-8 de log khong crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app_dir = os.path.dirname(os.path.abspath(__file__))
py_exe = r"C:\Users\tuan3\Documents\antigravity google\.venv\Scripts\python.exe"
sec_py = os.path.join(app_dir, "security.py")
sec_c = os.path.join(app_dir, "security.c")
sec_pyd = os.path.join(app_dir, "security.cp311-win_amd64.pyd")

print("====================================================================")
print("     COMPILING SECURITY.PY INTO NATIVE C-EXTENSION (.PYD)")
print("====================================================================")

# 1. Run Cython to convert security.py -> security.c
print("[1/3] Converting Python source to optimized C code via Cython...")
cython_cmd = [py_exe, "-m", "cython", "-3", "--module-name=security", sec_py, "-o", sec_c]
res = subprocess.run(cython_cmd, cwd=app_dir)
if res.returncode != 0:
    print("[!] Cython compilation failed!")
    sys.exit(1)
print(f"      Created C source: {sec_c} ({os.path.getsize(sec_c):,} bytes)")

# 2. Compile security.c to security.cp311-win_amd64.pyd with MinGW GCC
print("[2/3] Compiling C source to Native x86_64 Machine Code with MinGW GCC...")
# Python 3.11 include and lib paths
py_base = r"C:\Program Files\Python311"
py_inc = os.path.join(py_base, "include")
py_libs = os.path.join(py_base, "libs")

# Build ra tên tạm trước: nếu VietModHub đang chạy thì file .pyd thật đang bị khóa
# (Windows không cho ghi đè DLL/PDY đang được nạp), ta vẫn build xong rồi hoán đổi.
sec_pyd_build = sec_pyd + ".build"

gcc_cmd = [
    "gcc",
    "-shared",
    "-O3",                      # Maximum optimization
    "-DMS_WIN64",               # 64-bit Windows definition
    "-s",                       # Strip all symbol tables (Anti-Reverse Engineering)
    "-fvisibility=hidden",       # Hide internal symbols
    f"-I{py_inc}",
    sec_c,
    f"-L{py_libs}",
    "-lpython311",
    "-o", sec_pyd_build
]

print("      Running:", " ".join(gcc_cmd))
res = subprocess.run(gcc_cmd, cwd=app_dir)
if res.returncode != 0:
    print("[!] GCC compilation failed!")
    sys.exit(1)

# Hoán đổi bản build vào vị trí chính thức (chịu được trường hợp app đang chạy)
_swap_warned = False
try:
    os.replace(sec_pyd_build, sec_pyd)
except PermissionError:
    swapped = False
    for _attempt in range(4):
        backup_locked = f"{sec_pyd}.old{_attempt}"
        try:
            os.rename(sec_pyd, backup_locked)   # file dang duoc nap van cho phep rename
        except Exception:
            continue
        try:
            os.replace(sec_pyd_build, sec_pyd)
            swapped = True
            _swap_warned = True
            break
        except Exception:
            try:
                os.rename(backup_locked, sec_pyd)   # khoi phuc nguyen trang
            except Exception:
                pass
    if not swapped:
        print("[!] Khong the thay the security.pyd (dang bi khoa).")
        print("    Vui long DONG VietModHub roi chay lai script nay.")
        sys.exit(1)

if _swap_warned:
    print("      [!] VietModHub dang chay: da giu file cu thanh *.pyd.oldN.")
    print("      [!] Hay KHOI DONG LAI ung dung de nap engine bao mat moi.")

# Also create generic security.pyd (best-effort: co the bi khoa khi app dang chay)
generic_pyd = os.path.join(app_dir, "security.pyd")
try:
    shutil.copy2(sec_pyd, generic_pyd)
except Exception as alias_err:
    print(f"      [!] Bo qua ban alias security.pyd ({type(alias_err).__name__}); "
          f"module se duoc nap tu security.cp311-win_amd64.pyd.")

print(f"      [OK] Successfully built: {sec_pyd} ({os.path.getsize(sec_pyd):,} bytes)")

# 3. Clean up intermediate C file
try:
    if os.path.exists(sec_c):
        os.remove(sec_c)
        print("      [OK] Cleaned up intermediate C file.")
except Exception:
    pass

# 4. Verify import and functionality in Python
print("[3/3] Verifying native C-extension import & encryption engine...")
verify_code = """
import os
import sys
# Ensure current directory is first in path
sys.path.insert(0, r'%s')
import security
print('Imported module file:', security.__file__)
assert security.__file__.endswith('.pyd'), 'Must be loaded from .pyd binary!'

# 1. Verify authorized ticket generation and validation
import time
t = security.create_session_ticket()
assert security.verify_session_ticket(t) is True, 'Valid ticket must be verified!'

# 2. Verify ticket TTL expiration (> 300s) and future drift protection
expired_ticket = f"{os.getpid()}:{int(time.time()) - 350}:0123456789abcdef:invalidsig"
assert security.verify_session_ticket(expired_ticket) is False, 'Expired ticket must be rejected!'
future_ticket = f"{os.getpid()}:{int(time.time()) + 100}:0123456789abcdef:invalidsig"
assert security.verify_session_ticket(future_ticket) is False, 'Future ticket must be rejected!'

# 3. Verify zero public leakage of decryption classes, master keys, and secrets
assert not hasattr(security, 'ConguStreamReader'), 'Must not export ConguStreamReader!'
assert not hasattr(security, '_ConguStreamReader'), 'Must not export _ConguStreamReader!'
assert not hasattr(security, '_O_KEY_BYTES'), 'Must not export _O_KEY_BYTES!'
assert not hasattr(security, '_K_MASK'), 'Must not export _K_MASK!'
assert not hasattr(security, '_TICKET_SECRET'), 'Must not export _TICKET_SECRET!'
assert not hasattr(security, '_get_master_key_bytes'), 'Must not export _get_master_key_bytes!'
assert not hasattr(security, '_open_congu_stream_reader'), 'Must not export _open_congu_stream_reader!'
assert not hasattr(security, '_build_secure_stream_engine'), 'Must not export _build_secure_stream_engine!'

# 4. Verify deprecated leak wrapper is removed
assert not hasattr(security, '_decrypt_container_to_spooled_stream'), 'Must not leak _decrypt_container_to_spooled_stream!'

# 5. Verify CO_NGU_DEV_MODE and sys.frozen cannot bypass security verification
os.environ["CO_NGU_DEV_MODE"] = "1"
assert security.verify_session_ticket(None) is False, 'Must not bypass verify_session_ticket without ticket!'
assert security.verify_session_ticket('') is False, 'Must not bypass empty ticket!'

# 6. Verify _verify_game_path_legitimacy rejects missing game_def or invalid directory
ok, _ = security._verify_game_path_legitimacy(r'C:\fake_nonexistent_dir_congu', None)
assert ok is False, 'Must reject invalid directory or None game_def!'

# 7. Verify encrypt_mod_package raises PermissionError (Zero Encryption Oracle)
try:
    security.encrypt_mod_package()
    assert False, 'Should fail encrypt_mod_package on client binary!'
except PermissionError:
    pass

print('[OK] Native .pyd binary verification PASSED 100%%!')
""" % app_dir

res = subprocess.run([py_exe, "-c", verify_code], cwd=app_dir, capture_output=True, text=True)
print(res.stdout)
if res.returncode != 0:
    print("[!] Verification failed:", res.stderr)
    sys.exit(1)

print("====================================================================")
print("SECURITY ENGINE HARDENING COMPLETE! NO PYTHON BYTECODE LEAKS.")
print("====================================================================")
