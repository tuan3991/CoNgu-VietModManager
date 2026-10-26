import os
import sys
import subprocess
import shutil

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
    "-o", sec_pyd
]

print("      Running:", " ".join(gcc_cmd))
res = subprocess.run(gcc_cmd, cwd=app_dir)
if res.returncode != 0:
    print("[!] GCC compilation failed!")
    sys.exit(1)

# Also create generic security.pyd
generic_pyd = os.path.join(app_dir, "security.pyd")
shutil.copy2(sec_pyd, generic_pyd)

print(f"      [OK] Successfully built: {sec_pyd} ({os.path.getsize(sec_pyd):,} bytes)")

# 3. Clean up intermediate C file
if os.path.exists(sec_c):
    os.remove(sec_c)
    print("      [OK] Cleaned up intermediate C file.")

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

# 1. Verify authorized caller with ticket
t = security.create_session_ticket()
k = security._get_master_key_bytes(auth_ticket=t)
assert k == b'CoNgu_Pro_CyberSecure_Localization_Key_2026_!@#', 'Key mismatch!'

# 2. Verify unauthorized caller without ticket raises PermissionError
try:
    security._get_master_key_bytes()
    assert False, 'Should fail without ticket!'
except PermissionError:
    pass

try:
    security.ConguStreamReader('dummy.congu')
    assert False, 'Should fail without ticket!'
except PermissionError:
    pass

# 3. Verify deprecated leak wrapper is removed
assert not hasattr(security, '_decrypt_container_to_spooled_stream'), 'Must not leak _decrypt_container_to_spooled_stream!'

# 4. Verify CO_NGU_DEV_MODE and sys.frozen cannot bypass security verification
os.environ["CO_NGU_DEV_MODE"] = "1"
assert security.verify_session_ticket(None) is False, 'Must not bypass verify_session_ticket without ticket!'
assert security.verify_session_ticket('') is False, 'Must not bypass empty ticket!'

# 5. Verify _verify_game_path_legitimacy rejects missing game_def or invalid directory
ok, _ = security._verify_game_path_legitimacy(r'C:\fake_nonexistent_dir_congu', None)
assert ok is False, 'Must reject invalid directory or None game_def!'

# 6. Verify encrypt_mod_package raises PermissionError (Zero Encryption Oracle)
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
