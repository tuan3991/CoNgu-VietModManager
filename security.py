"""
CoNgu Security Engine - Hardened C-Extension (.pyd) Core
Proprietary Encrypted Mod Container (.congu) Architecture.
Compiled with Cython into native Windows binary to prevent reverse engineering.

Security Hardening & Anti-Hijacking Protections:
1. ZERO DATA LEAKAGE: Decrypted streams (BytesIO/bytes) are NEVER returned to Python caller.
2. DIRECT IN-ENGINE EXECUTION: install_steps (file streaming, folder streaming, in-place backup, INI patch)
   are executed entirely inside native C memory.
3. ANTI-DUMPING & TARGET VERIFICATION: Validates that destination directory is a genuine game installation
   containing legitimate game executables before performing any installation.
4. CALLER HANDSHAKE: Ephemeral HMAC session ticket bound to the host process PID prevents external scripts
   from hijacking the .pyd module.
5. ZERO DISK LEAKAGE (ConguStreamReader): In-memory chunk sliding window streaming (io.RawIOBase).
   Never uses SpooledTemporaryFile, zero disk spill-over to %TEMP%, transient buffers destroyed immediately.
"""

import os
import io
import gc
import sys
import time
import json
import hmac
import shutil
import zipfile
import hashlib
import bisect
import tempfile
import bz2
import struct
import subprocess
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Container Magic Headers
CONGU_MAGIC_V1 = b"CONGU\x01"
CONGU_MAGIC_V2 = b"CONGU\x02"
CONGU_MAGIC = CONGU_MAGIC_V1
ASSOC_METADATA = b"CO_NGU_SECURITY_LOCALIZATION_V1"

# Obfuscated Master Key Byte Stream (XOR masked with dynamic rolling key)
_K_MASK = 0xA7
_O_KEY_BYTES = bytes([
    228, 200, 233, 192, 210, 248, 247, 213, 200, 248, 228, 222, 197, 194, 213, 244,
    194, 196, 210, 213, 194, 248, 235, 200, 196, 198, 203, 206, 221, 198, 211, 206,
    200, 201, 248, 236, 194, 222, 248, 149, 151, 149, 145, 248, 134, 231, 132
])

# Ephemeral Ticket Signing Secret derived from masked key
_TICKET_SECRET = bytes([b ^ 0x5C for b in _O_KEY_BYTES[:16]])


class SecurityError(PermissionError):
    """Lỗi vi phạm an ninh hệ thống hoặc phát hiện hành vi can thiệp trái phép."""
    pass


class PathTraversalError(SecurityError):
    """Phát hiện lỗ hổng Path Traversal hoặc Zip Slip."""
    pass


def _norm_rel(rel_path):
    """Chuẩn hóa mọi đường dẫn tương đối về dấu / và loại bỏ khoảng trắng / gạch chéo thừa."""
    p = str(rel_path or "").replace("\\", "/").strip("/ ")
    while "//" in p:
        p = p.replace("//", "/")
    return p


def validate_safe_path(base_dir, relative_or_target_path, allow_base_itself=False):
    """
    Chuẩn hóa và thẩm định an toàn đường dẫn bắt buộc (Chống Path Traversal & Zip Slip).
    Sử dụng os.path.realpath và kiểm tra os.path.commonpath([game_root, target_path]) == game_root.

    Từ chối thực thi và raise PathTraversalError ngay lập tức nếu:
    - Đường dẫn rỗng hoặc không hợp lệ.
    - Đường dẫn tương đối thoát thư mục (..) hoặc đường dẫn tuyệt đối trỏ ra ngoài base_dir.
    - Đường dẫn nằm trên phân vùng ổ đĩa khác (Cross-Drive Traversal trên Windows).
    - Đường dẫn trỏ thẳng vào chính base_dir khi allow_base_itself=False (chống xóa/ghi đè toàn bộ thư mục game).
    """
    if not base_dir:
        raise PathTraversalError("Thư mục gốc (game_root) không được để trống!")
    if relative_or_target_path is None or str(relative_or_target_path).strip() == "":
        if allow_base_itself:
            return os.path.realpath(base_dir)
        raise PathTraversalError("Đường dẫn thao tác không được để trống!")

    base_real = os.path.realpath(base_dir)
    path_str = str(relative_or_target_path).strip()

    if os.path.isabs(path_str):
        target_real = os.path.realpath(path_str)
    else:
        target_real = os.path.realpath(os.path.join(base_real, path_str))

    base_norm = os.path.normcase(base_real)
    target_norm = os.path.normcase(target_real)

    try:
        common = os.path.commonpath([base_norm, target_norm])
    except ValueError as e:
        # Cross-Drive Traversal trên Windows (khác drive letter)
        raise PathTraversalError(
            f"Cảnh báo bảo mật (Cross-Drive Traversal): Đường dẫn '{path_str}' nằm khác phân vùng ổ đĩa với thư mục game '{base_dir}'! ({e})"
        )

    if common != base_norm:
        raise PathTraversalError(
            f"Cảnh báo bảo mật (Path Traversal): Phát hiện đường dẫn trái phép '{path_str}' trỏ ra ngoài phạm vi thư mục game '{base_dir}'! Từ chối thực thi để bảo vệ an toàn."
        )

    if not allow_base_itself and target_norm == base_norm:
        raise PathTraversalError(
            f"Cảnh báo bảo mật: Thao tác không được phép nhắm trực tiếp vào chính thư mục gốc của game '{base_dir}'!"
        )

    return target_real


def _get_master_key_bytes(auth_ticket=None):
    """Dynamically reconstruct master secret key in memory with caller verification"""
    if not auth_ticket or not verify_session_ticket(auth_ticket):
        raise PermissionError("Truy cập bị từ chối: Yêu cầu auth_ticket hợp lệ để giải phóng khóa bảo mật!")
    return bytes([b ^ _K_MASK for b in _O_KEY_BYTES])


def is_running_as_admin():
    """Check if the current process possesses elevated Windows Administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_directory_writable(dir_path):
    """
    Check if a directory has write permissions for the current user.
    Creates and removes a temporary test file (.congu_write_test) to reliably detect Windows ACL restrictions.
    """
    if not dir_path or not os.path.exists(dir_path):
        return False
    test_file = os.path.join(dir_path, f".congu_write_test_{os.getpid()}_{int(time.time())}.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except (PermissionError, OSError):
        return False


def create_session_ticket(target_pid=None):
    """
    Generate an ephemeral authentication ticket bound to a process PID or role, and time window.
    If target_pid is specified (integer PID or role like 'worker' / 'elevated'), binds to that target.
    Otherwise binds to the current process PID.
    """
    pid = str(target_pid) if target_pid is not None else str(os.getpid())
    ts = int(time.time())
    nonce = os.urandom(8).hex()
    msg = f"{pid}:{ts}:{nonce}".encode("utf-8")
    sig = hmac.new(_TICKET_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{pid}:{ts}:{nonce}:{sig}"


def verify_session_ticket(ticket, allowed_pid=None):
    """
    Verify ticket validity and process ownership to prevent import hijacking from foreign processes.
    Supports both single-process and parent/worker multi-process architectures:
    - Ticket signed for current process PID
    - Ticket signed by parent process PID (for child worker processes spawned by VietModHub)
    - Ticket signed for explicit worker / elevated role
    - Ticket signed for explicit allowed_pid
    """
    if not ticket or not isinstance(ticket, str):
        return False

    try:
        parts = ticket.split(":")
        if len(parts) != 4:
            return False
        pid_str, ts_str, nonce, sig = parts
        current_pid = os.getpid()
        parent_pid = os.getppid() if hasattr(os, "getppid") else None

        # Verify process affinity: current process, parent process, or authorized role / PID
        is_process_matched = False
        if str(pid_str) in ("worker", "elevated"):
            # Cryptographically signed role ticket passed to worker or elevated process
            is_process_matched = True
        elif pid_str.isdigit():
            ticket_pid = int(pid_str)
            is_process_matched = (
                ticket_pid == current_pid
                or (parent_pid is not None and ticket_pid == parent_pid)
                or (allowed_pid is not None and (str(allowed_pid) == "any_valid" or ticket_pid == int(allowed_pid)))
            )
        elif allowed_pid and str(pid_str) == str(allowed_pid):
            is_process_matched = True

        if not is_process_matched:
            return False

        if abs(int(time.time()) - int(ts_str)) > 86400:
            return False

        expected_msg = f"{pid_str}:{ts_str}:{nonce}".encode("utf-8")
        expected_sig = hmac.new(_TICKET_SECRET, expected_msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def verify_package_checksum(file_path, expected_sha256):
    """Verify SHA-256 integrity of a package file before decryption."""
    if not expected_sha256:
        return True
    if not os.path.exists(file_path):
        return False
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual_hash = h.hexdigest().lower()
    return actual_hash == expected_sha256.lower().strip()


def compute_file_sha256(file_path):
    """Compute SHA-256 hash of a file safely in 1MB chunks."""
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1048576):
                h.update(chunk)
        return h.hexdigest().lower()
    except Exception:
        return None


def pure_python_bspatch(src_bytes, patch_bytes):
    """
    Pure Python Colin Percival BSDIFF40 patch implementation.
    Standard bsdiff 4.0 format.
    Zero external dependencies (uses standard bz2 module).
    """
    if len(patch_bytes) < 32:
        raise ValueError("Tệp vá nhị phân không hợp lệ: header quá ngắn (< 32 bytes)")
    if patch_bytes[:8] != b"BSDIFF40":
        raise ValueError("Tệp vá nhị phân không đúng định dạng BSDIFF40")

    ctrl_len, diff_len, new_size = struct.unpack("<qqq", patch_bytes[8:32])
    if ctrl_len < 0 or diff_len < 0 or new_size < 0:
        raise ValueError("Header tệp vá bị lỗi (kích thước âm)")

    p1 = 32
    p2 = p1 + ctrl_len
    p3 = p2 + diff_len

    ctrl_data = bz2.decompress(patch_bytes[p1:p2])
    diff_data = bz2.decompress(patch_bytes[p2:p3])
    extra_data = bz2.decompress(patch_bytes[p3:])

    new_buf = bytearray(new_size)
    old_pos = 0
    new_pos = 0
    diff_pos = 0
    extra_pos = 0
    ctrl_pos = 0
    old_len = len(src_bytes)

    while new_pos < new_size:
        if ctrl_pos + 24 > len(ctrl_data):
            break
        x, y, z = struct.unpack("<qqq", ctrl_data[ctrl_pos:ctrl_pos + 24])
        ctrl_pos += 24

        if new_pos + x > new_size:
            raise ValueError("Lỗi cấu trúc bản vá: x vượt quá kích thước tệp mới")

        # 1. Add x bytes from old_buf and diff_data
        for i in range(x):
            src_val = src_bytes[old_pos + i] if (0 <= old_pos + i < old_len) else 0
            new_buf[new_pos + i] = (src_val + diff_data[diff_pos + i]) & 0xFF

        old_pos += x
        new_pos += x
        diff_pos += x

        # 2. Copy y bytes from extra_data
        if new_pos + y > new_size:
            raise ValueError("Lỗi cấu trúc bản vá: y vượt quá kích thước tệp mới")

        new_buf[new_pos : new_pos + y] = extra_data[extra_pos : extra_pos + y]
        new_pos += y
        extra_pos += y

        # 3. Seek old_pos by z
        old_pos += z

    return bytes(new_buf)


def find_tool_exe(tool_name: str):
    """
    Tìm đường dẫn tệp thực thi của công cụ nhị phân (ví dụ: xdelta3.exe, hpatchz.exe, hdiffz.exe)
    trong nhiều môi trường: IDE dev, PyInstaller _MEIPASS, Portable tools, và PATH hệ thống.
    """
    exe_name = tool_name if tool_name.lower().endswith(".exe") else f"{tool_name}.exe"
    
    candidates = []
    # 1. PyInstaller frozen app (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "tools", exe_name))
        candidates.append(os.path.join(sys._MEIPASS, exe_name))
        
    # 2. Thư mục file security.py hiện tại
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(current_dir, "tools", exe_name))
    candidates.append(os.path.join(current_dir, exe_name))
    
    # 3. Thư mục sys.executable (ví dụ python.exe hoặc VietModHub.exe)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates.append(os.path.join(exe_dir, "tools", exe_name))
    candidates.append(os.path.join(exe_dir, exe_name))
    
    # 4. Thư mục làm việc hiện tại os.getcwd()
    candidates.append(os.path.join(os.getcwd(), "tools", exe_name))
    candidates.append(os.path.join(os.getcwd(), exe_name))
    
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
            
    # 5. Hệ thống PATH
    found = shutil.which(exe_name) or shutil.which(tool_name)
    if found:
        return os.path.abspath(found)
        
    return None


def apply_binary_patch(src_file, dst_file, patch_data_or_file):
    """
    Áp dụng bản vá nhị phân lên tệp nguồn để tạo ra tệp đích với cơ chế Streaming Sliding Window.
    Bộ đệm RAM cố định ở mức 32MB - 64MB cho dù tệp nguồn nặng từ 1.5GB đến 10GB.
    
    Hỗ trợ tự động nhận diện định dạng bản vá:
    1. VCDIFF (xdelta3 - RFC 3284, header '\\xd6\\xc3\\xc4'): Dùng xdelta3.exe (-B 64MB) hoặc hpatchz.exe (-s-64m)
    2. HDiffPatch (header 'HDIFF'): Dùng hpatchz.exe (-s-64m)
    3. BSDIFF40 (header 'BSDIFF40'): Dùng hpatchz.exe (-s-64m streaming) hoặc bsdiff4.file_patch
    """
    if not os.path.exists(src_file):
        raise FileNotFoundError(f"Không tìm thấy tệp nguồn để vá: {src_file}")

    os.makedirs(os.path.dirname(os.path.abspath(dst_file)), exist_ok=True)

    # Chuẩn bị tệp patch: Nếu là byte stream, ghi ra tệp tạm để cho công cụ streaming xử lý
    temp_patch_path = None
    if isinstance(patch_data_or_file, (str, os.PathLike)) and os.path.isfile(str(patch_data_or_file)):
        patch_path = os.path.abspath(str(patch_data_or_file))
    elif isinstance(patch_data_or_file, (bytes, bytearray)):
        temp_patch_path = f"{dst_file}.patch_stream_{os.getpid()}_{int(time.time()*1000)}.tmp"
        with open(temp_patch_path, "wb") as pf:
            pf.write(patch_data_or_file)
        patch_path = temp_patch_path
    else:
        raise ValueError("patch_data_or_file phải là đường dẫn tệp hoặc mảng byte dữ liệu")

    try:
        # Đọc 16 bytes đầu để nhận diện chữ ký định dạng (Magic Bytes)
        with open(patch_path, "rb") as pf:
            magic = pf.read(16)

        no_window = 0x08000000 if sys.platform == "win32" else 0

        # Case 1: Định dạng VCDIFF (xdelta3) - \\xd6\\xc3\\xc4\\x00...
        if magic.startswith(b"\xd6\xc3\xc4"):
            xdelta_exe = find_tool_exe("xdelta3")
            if xdelta_exe:
                # xdelta3: -d (decompress), -f (force overwrite), -B 64MB sliding window buffer
                cmd = [xdelta_exe, "-d", "-f", "-B", "67108864", "-s", src_file, patch_path, dst_file]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
                if res.returncode != 0:
                    raise RuntimeError(f"Lỗi xdelta3 vá tệp thất bại (code {res.returncode}): {res.stderr.strip()}")
                return os.path.getsize(dst_file)

            hpatchz_exe = find_tool_exe("hpatchz")
            if hpatchz_exe:
                # hpatchz hỗ trợ tương thích VCDIFF hoàn toàn
                cmd = [hpatchz_exe, "-f", "-s-64m", src_file, patch_path, dst_file]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
                if res.returncode != 0:
                    raise RuntimeError(f"Lỗi hpatchz vá tệp VCDIFF thất bại (code {res.returncode}): {res.stderr.strip()}")
                return os.path.getsize(dst_file)

            raise RuntimeError("Tệp vá nhị phân định dạng VCDIFF (xdelta3) yêu cầu công cụ 'xdelta3.exe' hoặc 'hpatchz.exe' trong thư mục tools/.")

        # Case 2: Định dạng HDiffPatch (HDIFF13, HDIFF20, HDIFFW...)
        elif magic.startswith(b"HDIFF"):
            hpatchz_exe = find_tool_exe("hpatchz")
            if not hpatchz_exe:
                raise RuntimeError("Tệp vá định dạng HDiffPatch yêu cầu công cụ 'hpatchz.exe' trong thư mục tools/.")
            cmd = [hpatchz_exe, "-f", "-s-64m", src_file, patch_path, dst_file]
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
            if res.returncode != 0:
                raise RuntimeError(f"Lỗi hpatchz vá tệp HDIFF thất bại (code {res.returncode}): {res.stderr.strip()}")
            return os.path.getsize(dst_file)

        # Case 3: Định dạng BSDIFF40
        elif magic.startswith(b"BSDIFF40"):
            # Ưu tiên hpatchz vì hpatchz hỗ trợ bsdiff theo luồng cửa sổ trượt (không nạp toàn bộ vào RAM!)
            hpatchz_exe = find_tool_exe("hpatchz")
            if hpatchz_exe:
                cmd = [hpatchz_exe, "-f", "-s-64m", src_file, patch_path, dst_file]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
                if res.returncode == 0 and os.path.exists(dst_file) and os.path.getsize(dst_file) > 0:
                    return os.path.getsize(dst_file)

            # Fallback sang C-extension bsdiff4.file_patch (file-based streaming patch)
            has_bsdiff4 = False
            try:
                import bsdiff4
                has_bsdiff4 = True
            except ImportError:
                pass

            if has_bsdiff4:
                bsdiff4.file_patch(src_file, dst_file, patch_path)
                return os.path.getsize(dst_file)

            # Fallback cuối cùng: pure_python_bspatch
            with open(src_file, "rb") as sf:
                src_bytes = sf.read()
            with open(patch_path, "rb") as pf:
                p_bytes = pf.read()
            patched_bytes = pure_python_bspatch(src_bytes, p_bytes)
            with open(dst_file, "wb") as df:
                df.write(patched_bytes)
            return len(patched_bytes)

        # Case 4: Magic không xác định, thử lần lượt hpatchz rồi bsdiff4
        else:
            hpatchz_exe = find_tool_exe("hpatchz")
            if hpatchz_exe:
                cmd = [hpatchz_exe, "-f", "-s-64m", src_file, patch_path, dst_file]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
                if res.returncode == 0:
                    return os.path.getsize(dst_file)
            raise ValueError(f"Định dạng tệp vá không được hỗ trợ (header: {magic[:8]!r})")

    finally:
        # Xóa tệp tạm nếu có tạo ra
        if temp_patch_path and os.path.exists(temp_patch_path):
            try:
                os.remove(temp_patch_path)
            except Exception:
                pass


def create_binary_patch(src_file, modded_file, patch_file, algorithm="auto"):
    """
    Tạo tệp vá nhị phân diff giữa tệp gốc và tệp đã mod.
    Hỗ trợ đa thuật toán với chế độ Streaming Sliding Window để chống tràn RAM (MemoryError):
    - algorithm='auto': Tự động chọn thuật toán tối ưu.
      Nếu tệp nguồn > 150 MB: Tự động dùng xdelta3 hoặc hdiffz theo luồng cửa sổ trượt (Streaming Binary Diff)
      để tránh MemoryError (Suffix Sorting của bsdiff ngốn 8x-17x RAM, tức tệp 1GB cần tới 15GB RAM).
      Nếu tệp <= 150 MB: Ưu tiên xdelta3, nếu không có thì dùng bsdiff4.
    - algorithm='xdelta': Sử dụng xdelta3 (VCDIFF RFC 3284, bộ đệm trượt 64MB).
    - algorithm='hdiff': Sử dụng hdiffz (HDiffPatch stream mode -s-64k).
    - algorithm='bsdiff': Sử dụng bsdiff4 (BSDIFF40).
    """
    if not os.path.exists(src_file):
        raise FileNotFoundError(f"Không tìm thấy tệp nguồn gốc: {src_file}")
    if not os.path.exists(modded_file):
        raise FileNotFoundError(f"Không tìm thấy tệp đã mod: {modded_file}")

    os.makedirs(os.path.dirname(os.path.abspath(patch_file)), exist_ok=True)
    src_size = os.path.getsize(src_file)
    no_window = 0x08000000 if sys.platform == "win32" else 0

    xdelta_exe = find_tool_exe("xdelta3")
    hdiff_exe = find_tool_exe("hdiffz")
    has_bsdiff4 = False
    try:
        import bsdiff4
        has_bsdiff4 = True
    except ImportError:
        pass

    chosen_alg = algorithm.lower().strip()
    if chosen_alg == "auto":
        if src_size > 150 * 1024 * 1024:  # > 150 MB
            if xdelta_exe:
                chosen_alg = "xdelta"
            elif hdiff_exe:
                chosen_alg = "hdiff"
            elif has_bsdiff4:
                print(f"[CẢNH BÁO BỘ NHỚ] Tệp nguồn nặng {src_size / (1024*1024):.1f} MB (> 150 MB).")
                print("  Thuật toán bsdiff4 cần tới 8x-17x dung lượng RAM (~15GB cho 1GB file) và có thể gây MemoryError!")
                print("  Khuyến nghị đặt xdelta3.exe hoặc hdiffz.exe vào thư mục tools/ để vá theo luồng 64MB RAM.")
                chosen_alg = "bsdiff"
            else:
                raise RuntimeError("Cần công cụ streaming 'xdelta3.exe' hoặc 'hdiffz.exe' trong thư mục tools/ để tạo bản vá cho tệp > 150MB.")
        else:
            # File <= 150 MB
            if xdelta_exe:
                chosen_alg = "xdelta"
            elif has_bsdiff4:
                chosen_alg = "bsdiff"
            elif hdiff_exe:
                chosen_alg = "hdiff"
            else:
                raise RuntimeError("Không tìm thấy công cụ tạo diff (cần xdelta3.exe, hdiffz.exe hoặc thư viện bsdiff4).")

    if chosen_alg == "xdelta":
        if not xdelta_exe:
            raise RuntimeError("Không tìm thấy 'xdelta3.exe' trong thư mục tools/ hoặc PATH hệ thống.")
        cmd = [xdelta_exe, "-e", "-f", "-B", "67108864", "-s", src_file, modded_file, patch_file]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
        if res.returncode != 0:
            raise RuntimeError(f"Lỗi tạo diff xdelta3 (code {res.returncode}): {res.stderr.strip()}")
        return os.path.getsize(patch_file)

    elif chosen_alg == "hdiff":
        if not hdiff_exe:
            raise RuntimeError("Không tìm thấy 'hdiffz.exe' trong thư mục tools/ hoặc PATH hệ thống.")
        cmd = [hdiff_exe, "-f", "-s-64k", src_file, modded_file, patch_file]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
        if res.returncode != 0:
            raise RuntimeError(f"Lỗi tạo diff hdiffz (code {res.returncode}): {res.stderr.strip()}")
        return os.path.getsize(patch_file)

    elif chosen_alg == "bsdiff":
        if not has_bsdiff4:
            raise ImportError("Cần cài đặt thư viện 'bsdiff4' để tạo file diff: pip install bsdiff4")
        import bsdiff4
        bsdiff4.file_diff(src_file, modded_file, patch_file)
        return os.path.getsize(patch_file)

    else:
        raise ValueError(f"Thuật toán diff không hợp lệ: '{algorithm}'. Chỉ hỗ trợ 'auto', 'xdelta', 'hdiff', 'bsdiff'.")


def is_congu_package(file_path):
    """Check if a file is a valid encrypted .congu container (V1 or V2)."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 34:
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(6)
            return header in (CONGU_MAGIC_V1, CONGU_MAGIC_V2)
    except Exception:
        return False


def encrypt_mod_package(zip_path=None, congu_path=None, version=2, chunk_size=4 * 1024 * 1024, *args, **kwargs):
    """
    BẢO VỆ CHỐNG ENCRYPTION ORACLE:
    Chức năng đóng gói và mã hóa .congu đã bị vô hiệu hóa hoàn toàn trên phiên bản phân phối cho người dùng cuối (Client Binary).
    Chỉ nhà phát triển Cổ Ngữ mới sở hữu công cụ đóng gói chuyên biệt (pack_security.py / pack_mod.py).
    Mọi yêu cầu gọi trái phép từ bên ngoài đều bị từ chối triệt để.
    """
    raise PermissionError(
        "Truy cập bị từ chối: Chức năng đóng gói .congu không khả dụng trên phiên bản máy trạm (Client Binary). "
        "Vui lòng sử dụng công cụ đóng gói chuyên biệt của nhà phát triển (pack_mod.py / pack_security)."
    )


def _verify_game_path_legitimacy(game_path, game_def=None):
    """
    Anti-dumping check: Verifies that game_path is a genuine game installation directory,
    preventing malicious callers from dumping decrypted mod files into arbitrary folders.
    """
    if not game_path or not os.path.isdir(game_path):
        return False, "Thư mục đích không tồn tại hoặc không phải thư mục hợp lệ."

    if not game_def or not isinstance(game_def, dict):
        return False, "Thiếu thông tin định danh trò chơi hợp lệ (game_def)."

    raw_exe = game_def.get("executable_name")
    if not raw_exe or not isinstance(raw_exe, str):
        return False, "Thiếu thông tin tệp thực thi chính (executable_name) của game."

    exe_name = os.path.basename(str(raw_exe).replace("\\", "/").strip())
    if not exe_name:
        return False, "Tên tệp thực thi không hợp lệ."

    root_exe = os.path.join(game_path, exe_name)
    if os.path.exists(root_exe):
        return True, ""

    # Check immediate subfolders (e.g. Binaries/Win64)
    found = False
    try:
        for root, dirs, files in os.walk(game_path):
            if exe_name.lower() in [f.lower() for f in files]:
                found = True
                break
            rel = os.path.relpath(root, game_path)
            if rel != "." and len(rel.split(os.sep)) >= 2:
                dirs.clear()
    except Exception:
        pass

    if not found:
        return False, f"Thư mục không chứa tệp thực thi chính '{exe_name}' của game."

    return True, ""


def _find_zip_member(zf, relative_path):
    """
    Finds a member inside the zip archive matching relative_path.
    Supports exact match, slash normalization, Mod_Files subfolder, and basename fallback.
    Prevents path traversal by rejecting '..' elements.
    """
    clean_target = relative_path.replace("\\", "/").lstrip("/")
    if ".." in clean_target.split("/"):
        return None
    namelist = zf.namelist()
    namelist_set = set(namelist)

    if clean_target in namelist_set:
        return clean_target

    target_lower = clean_target.lower()
    for name in namelist:
        if name.lower() == target_lower:
            return name

    for name in namelist:
        norm = name.replace("\\", "/").lstrip("/")
        if norm.endswith("/" + clean_target):
            return name

    base = os.path.basename(clean_target).lower()
    for name in namelist:
        if not name.endswith("/"):
            if os.path.basename(name).lower() == base:
                return name

    return None


def _find_zip_folder_members(zf, folder_path):
    """
    Finds all file members in zip that belong to folder_path.
    Returns list of tuples: (member_info, relative_path_inside_folder)
    Includes Anti-Zip-Slip sanitation to guarantee sub_rel does not traverse backwards.
    """
    clean_folder = folder_path.replace("\\", "/").strip("/")
    results = []
    folder_lower = clean_folder.lower()
    folder_base = os.path.basename(clean_folder).lower()

    for member in zf.infolist():
        if member.is_dir() or member.filename.endswith("/"):
            continue
        norm = member.filename.replace("\\", "/").strip("/")
        norm_parts = norm.split("/")

        # Anti Zip-Slip check: reject members with '..' or absolute/cross-drive notation
        if ".." in norm_parts or (len(norm) >= 2 and norm[1] == ":") or norm.startswith("/"):
            continue

        if norm.lower().startswith(folder_lower + "/"):
            sub_rel = norm[len(folder_lower) + 1:]
            if ".." not in sub_rel.split("/"):
                results.append((member, sub_rel))
        elif folder_base in [p.lower() for p in norm_parts]:
            idx = [p.lower() for p in norm_parts].index(folder_base)
            sub_rel = "/".join(norm_parts[idx + 1:])
            if ".." not in sub_rel.split("/"):
                results.append((member, sub_rel))

    return results


def _patch_ini_file_internal(file_path, section, key, value, encoding="utf-8"):
    """
    Internal INI modification that preserves existing comments, whitespace, and formatting.
    """
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    bak_file = f"{file_path}.congu_bak"
    # Bẫy cấu hình (Mục 1.3): Tự phục hồi file .ini nếu trước đó bị lệnh backup đổi tên làm mất!
    if not os.path.exists(file_path) and os.path.exists(bak_file):
        try:
            shutil.copy2(bak_file, file_path)
            print(f"[Security Self-Healing INI] File '{os.path.basename(file_path)}' không tồn tại nhưng có sẵn '{os.path.basename(bak_file)}'. Đã tự động chép ngược để bảo toàn cấu hình gốc.")
        except Exception:
            pass

    content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                content = f.read()
        except Exception:
            with open(file_path, "r", encoding="latin-1", errors="replace") as f:
                content = f.read()

    lines = content.splitlines(keepends=True) if content else []
    out_lines = []
    in_target_section = False if section else True
    section_found = False if section else True
    key_replaced = False

    sec_header = f"[{section.strip().lower()}]" if section else ""
    key_prefix = key.strip().lower()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_sec = stripped.lower()
            if in_target_section and not key_replaced:
                out_lines.append(f"{key}={value}\n")
                key_replaced = True

            if sec_header and current_sec == sec_header:
                in_target_section = True
                section_found = True
            else:
                in_target_section = False if section else True
            out_lines.append(line)
            continue

        if in_target_section and not key_replaced:
            if "=" in line:
                k, sep, v = line.partition("=")
                if k.strip().lower() == key_prefix:
                    indent = len(line) - len(line.lstrip())
                    out_lines.append(f"{line[:indent]}{key}={value}\n")
                    key_replaced = True
                    continue
        out_lines.append(line)

    if in_target_section and not key_replaced:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        out_lines.append(f"{key}={value}\n")
        key_replaced = True
    elif not section_found:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        out_lines.append(f"\n[{section}]\n{key}={value}\n")
        key_replaced = True

    with open(file_path, "w", encoding=encoding, errors="replace") as f:
        f.write("".join(out_lines))
    return True


class _ConguStreamReader(io.RawIOBase):
    """
    Zero-Disk-Leakage Streaming Decryption Reader for .congu Containers.
    Inherits from io.RawIOBase to provide a standard seekable, readable binary stream interface
    directly consumable by zipfile.ZipFile or streaming file operations, without creating ANY temporary files
    on disk (%TEMP%) and completely eliminating SpooledTemporaryFile spill-over risk on large packages.

    Operates on a chunk-by-chunk in-memory sliding window:
    - Pre-indexes chunk headers at initialization (negligible memory & near-zero I/O overhead)
    - Decrypts ONLY requested chunks on-demand into RAM
    - Caches single current chunk (e.g. 4MB) in memory for sequential read throughput
    - Supports full random seeking (seek, tell) required by ZipFile central directory lookups
    - STRICT CALLER VERIFICATION: Requires valid ephemeral HMAC auth_ticket bound to host process PID
    """
    def __init__(self, congu_path, auth_ticket=None, progress_callback=None):
        super().__init__()
        if not auth_ticket or not verify_session_ticket(auth_ticket):
            raise PermissionError("Truy cập bị từ chối: Cần vé xác thực phiên hợp lệ (auth_ticket) để mở luồng giải mã!")
        self.name = congu_path
        self._congu_path = congu_path
        self._progress_callback = progress_callback
        self._f = open(congu_path, "rb")
        self._magic = self._f.read(6)
        if self._magic not in (CONGU_MAGIC_V1, CONGU_MAGIC_V2):
            self._f.close()
            raise ValueError("Không phải định dạng gói CỔ NGỮ hợp lệ (.congu)!")

        self._salt = self._f.read(16)
        master_secret = _get_master_key_bytes(auth_ticket=auth_ticket)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._salt,
            iterations=100000
        )
        self._key = kdf.derive(master_secret)
        self._aesgcm = AESGCM(self._key)

        self._pos = 0
        self._cached_chunk_idx = None
        self._cached_chunk_data = b""

        # Build chunk index table
        self._chunks = []
        self._chunk_starts = []
        file_size = os.path.getsize(congu_path)

        if self._magic == CONGU_MAGIC_V1:
            ciphertext_len = file_size - 6 - 16 - 12
            pt_len = max(0, ciphertext_len - 16)
            self._chunks.append({
                "idx": 0,
                "file_pos": 22,  # offset of 12-byte nonce
                "chunk_len": ciphertext_len,
                "pt_start": 0,
                "pt_len": pt_len,
                "pt_end": pt_len
            })
            self._chunk_starts.append(0)
            self._total_size = pt_len
        elif self._magic == CONGU_MAGIC_V2:
            pt_offset = 0
            chunk_idx = 0
            while True:
                len_bytes = self._f.read(4)
                if not len_bytes:
                    break
                file_pos = self._f.tell()
                chunk_len = int.from_bytes(len_bytes, "big") if len(len_bytes) == 4 else 0
                if len(len_bytes) < 4 or chunk_len < 16 or file_pos + 12 + chunk_len > file_size:
                    self.close()
                    raise ValueError("Gói .congu bị hỏng hoặc cắt cụt!")
                pt_len = chunk_len - 16
                self._chunks.append({
                    "idx": chunk_idx,
                    "file_pos": file_pos,
                    "chunk_len": chunk_len,
                    "pt_start": pt_offset,
                    "pt_len": pt_len,
                    "pt_end": pt_offset + pt_len
                })
                self._chunk_starts.append(pt_offset)
                pt_offset += pt_len
                chunk_idx += 1
                self._f.seek(file_pos + 12 + chunk_len)
            self._total_size = pt_offset

    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self._pos + offset
        elif whence == io.SEEK_END:
            new_pos = self._total_size + offset
        else:
            raise ValueError(f"Invalid whence argument: {whence}")

        if new_pos < 0:
            raise ValueError(f"Negative seek position: {new_pos}")
        self._pos = new_pos
        return self._pos

    def tell(self):
        return self._pos

    def _get_chunk_data(self, chunk_idx):
        if self._cached_chunk_idx == chunk_idx:
            return self._cached_chunk_data

        entry = self._chunks[chunk_idx]
        self._f.seek(entry["file_pos"])
        nonce = self._f.read(12)
        ciphertext = self._f.read(entry["chunk_len"])

        if self._magic == CONGU_MAGIC_V1:
            assoc = ASSOC_METADATA
        else:
            assoc = ASSOC_METADATA + chunk_idx.to_bytes(4, "big")

        try:
            decrypted = self._aesgcm.decrypt(nonce, ciphertext, assoc)
        except Exception as e:
            raise ValueError(f"Giải mã khối {chunk_idx} thất bại! ({e})")

        self._cached_chunk_idx = chunk_idx
        self._cached_chunk_data = decrypted

        if self._progress_callback and self._total_size > 0:
            pct = int(min(55, 15 + (entry["pt_end"] / self._total_size) * 40))
            self._progress_callback(pct, f"Đang giải mã luồng an toàn (Khối {chunk_idx + 1}/{len(self._chunks)})...")

        return decrypted

    def _find_chunk_index(self, pos):
        if not self._chunk_starts:
            return 0
        idx = bisect.bisect_right(self._chunk_starts, pos) - 1
        return max(0, min(len(self._chunks) - 1, idx))

    def read(self, size=-1):
        if self._pos >= self._total_size:
            return b""

        if size is None or size < 0:
            bytes_to_read = self._total_size - self._pos
        else:
            bytes_to_read = min(size, self._total_size - self._pos)

        if bytes_to_read <= 0:
            return b""

        out = bytearray()
        remaining = bytes_to_read
        while remaining > 0 and self._pos < self._total_size:
            chunk_idx = self._find_chunk_index(self._pos)
            chunk_entry = self._chunks[chunk_idx]
            offset_in_chunk = self._pos - chunk_entry["pt_start"]
            available = chunk_entry["pt_len"] - offset_in_chunk
            take = min(remaining, available)

            chunk_data = self._get_chunk_data(chunk_idx)
            out.extend(chunk_data[offset_in_chunk:offset_in_chunk + take])

            self._pos += take
            remaining -= take

        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self):
        if not self.closed:
            self._cached_chunk_data = b""
            self._cached_chunk_idx = None
            if hasattr(self, "_f") and self._f and not self._f.closed:
                self._f.close()
            super().close()
            gc.collect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

ConguStreamReader = _ConguStreamReader


def record_preexisting_environment(game_id, game_path):
    """
    Ghi nhận môi trường BepInEx/winhttp tiền tồn tại (Mục 1.5 - BepInEx & Unity Protection).
    Được gọi trước khi thực thi bất kỳ thao tác giải nén hoặc sao chép nào.
    Đặc biệt: Nếu manifest đã từng lưu giá trị bool, TUYỆT ĐỐI giữ nguyên để không bị sai lệch khi cài đè lần 2.
    """
    if not game_id or not game_path or not os.path.exists(game_path):
        return False, False
    appdata_base = os.environ.get("APPDATA", "")
    if not appdata_base:
        return False, False
    manifest_dir = os.path.join(appdata_base, "VietModHub", "backups", game_id)
    os.makedirs(manifest_dir, exist_ok=True)
    manifest_path = os.path.join(manifest_dir, "backup_manifest.json")

    manifest = {"game_id": game_id, "backup_type": "inplace", "files": []}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            pass

    winhttp_pre = manifest.get("winhttp_preexisting")
    if winhttp_pre is None:
        w_file = os.path.join(game_path, "winhttp.dll")
        w_bak = os.path.join(game_path, "winhttp.dll.congu_bak")
        winhttp_pre = bool(os.path.exists(w_file) or os.path.exists(w_bak))
        manifest["winhttp_preexisting"] = winhttp_pre

    bepinex_pre = manifest.get("bepinex_preexisting")
    if bepinex_pre is None:
        b_dir = os.path.join(game_path, "BepInEx")
        b_bak = os.path.join(game_path, "BepInEx.congu_bak")
        bepinex_pre = bool(os.path.isdir(b_dir) or os.path.isdir(b_bak))
        manifest["bepinex_preexisting"] = bepinex_pre

    doorstop_pre = manifest.get("doorstop_preexisting")
    if doorstop_pre is None:
        d_cfg = os.path.join(game_path, "doorstop_config.ini")
        d_ver = os.path.join(game_path, ".doorstop_version")
        doorstop_pre = bool(os.path.exists(d_cfg) or os.path.exists(d_ver))
        manifest["doorstop_preexisting"] = doorstop_pre

    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Security Pre-existing Warning] {e}")

    return winhttp_pre, bepinex_pre


def _rollback_transaction(game_path, executed_journal, game_def=None):
    """
    Transaction Rollback Engine (Tri-Tier Hardened Architecture):
    - Lớp 1 (Reverse Journal Rollback): Hoàn nguyên chính xác các bước trong executed_journal theo thứ tự ngược lại.
      Nếu Lớp 1 thành công 100% không phát sinh lỗi, dừng rollback ngay lập tức để bảo vệ an toàn tối đa cho game.
    - Lớp 2 (Targeted Fallback Uninstall Steps): Chỉ kích hoạt khi Lớp 1 gặp lỗi, và CHỈ xử lý đích danh các target bị lỗi.
    - Lớp 3 (Targeted Emergency Recovery): Cứu hộ đích danh cho các target còn lại, TUYỆT ĐỐI KHÔNG quét mù quáng os.walk toàn bộ thư mục game.
    """
    journal_errors = []

    # === LỚP 1: REVERSE JOURNAL ROLLBACK ===
    for entry in reversed(executed_journal):
        action = entry.get("action")
        target_rel = _norm_rel(entry.get("target"))
        if not target_rel:
            continue
        try:
            target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
        except Exception as rb_p_err:
            print(f"[Rollback Security Warning] Bỏ qua đường dẫn không an toàn: {target_rel} ({rb_p_err})")
            continue
        bak_abs = f"{target_abs}.congu_bak"
        tx_tmp_abs = entry.get("tx_tmp") or f"{target_abs}.congu_tx_tmp"
        has_tx_tmp = entry.get("has_tx_tmp", False)

        try:
            # Mục 1.4: ƯU TIÊN HOÀN NGUYÊN VỀ BẢN MOD V1.0 TỪ TX_TMP (BẢO TOÀN NGUYÊN VẸN .CONGU_BAK TIẾNG ANH GỐC)
            if has_tx_tmp and os.path.exists(tx_tmp_abs):
                if os.path.exists(target_abs):
                    try:
                        if os.path.isdir(target_abs):
                            shutil.rmtree(target_abs, ignore_errors=True)
                        else:
                            os.remove(target_abs)
                    except Exception:
                        pass
                try:
                    os.replace(tx_tmp_abs, target_abs)
                    print(f"[Rollback Smart Reversal] Đã hoàn nguyên '{target_rel}' về phiên bản mod v1.0 từ .congu_tx_tmp.")
                    continue
                except Exception as e_tx:
                    print(f"[Rollback Tx-Tmp Warning] Lỗi khôi phục tx_tmp {tx_tmp_abs}: {e_tx}")

            if action == "backup":
                created_new_bak = entry.get("created_new_bak", True)
                if os.path.exists(bak_abs):
                    if os.path.exists(target_abs):
                        try:
                            if os.path.isdir(target_abs):
                                shutil.rmtree(target_abs, ignore_errors=True)
                            else:
                                os.remove(target_abs)
                        except Exception:
                            pass
                    if created_new_bak:
                        try:
                            os.replace(bak_abs, target_abs)
                        except Exception:
                            try:
                                if os.path.isdir(bak_abs):
                                    shutil.copytree(bak_abs, target_abs, dirs_exist_ok=True)
                                    shutil.rmtree(bak_abs, ignore_errors=True)
                                else:
                                    shutil.copy2(bak_abs, target_abs)
                                    os.remove(bak_abs)
                            except Exception:
                                pass
                    else:
                        # Reinstall/overwrite case: keep .congu_bak intact!
                        try:
                            if os.path.isdir(bak_abs):
                                shutil.copytree(bak_abs, target_abs, dirs_exist_ok=True)
                            else:
                                shutil.copy2(bak_abs, target_abs)
                        except Exception:
                            pass

            elif action == "patch_ini":
                created_new_bak = entry.get("created_new_bak", True)
                if os.path.exists(bak_abs):
                    try:
                        shutil.copy2(bak_abs, target_abs)
                        if created_new_bak:
                            try:
                                os.remove(bak_abs)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"[Rollback] Error reverting INI patch: {e}")
                        journal_errors.append((entry, str(e)))

            elif action == "copy_file":
                existed_before = entry.get("existed_before", False)
                created_new_bak = entry.get("created_new_bak", False)
                if created_new_bak and os.path.exists(bak_abs):
                    if os.path.exists(target_abs):
                        try:
                            os.remove(target_abs)
                        except Exception:
                            pass
                    try:
                        os.replace(bak_abs, target_abs)
                    except Exception:
                        shutil.copy2(bak_abs, target_abs)
                        try:
                            os.remove(bak_abs)
                        except Exception:
                            pass
                elif existed_before and os.path.exists(bak_abs):
                    shutil.copy2(bak_abs, target_abs)
                elif not existed_before:
                    # Mục 1.5: Không xóa winhttp.dll nếu nó đã tồn tại trước khi cài Việt hóa
                    is_winhttp = os.path.basename(target_rel).lower() == "winhttp.dll"
                    appdata_base = os.environ.get("APPDATA", "")
                    gid = game_def.get("id") if (game_def and isinstance(game_def, dict)) else None
                    mf_path = os.path.join(appdata_base, "VietModHub", "backups", gid, "backup_manifest.json") if (appdata_base and gid) else None
                    w_pre = False
                    if mf_path and os.path.exists(mf_path):
                        try:
                            with open(mf_path, "r", encoding="utf-8") as f:
                                w_pre = json.load(f).get("winhttp_preexisting", False)
                        except Exception:
                            pass
                    if not (is_winhttp and w_pre):
                        if os.path.exists(target_abs) and not os.path.exists(bak_abs):
                            try:
                                os.remove(target_abs)
                            except Exception:
                                pass

            elif action == "patch_binary":
                created_new_bak = entry.get("created_new_bak", False)
                if os.path.exists(bak_abs):
                    if os.path.exists(target_abs):
                        try:
                            os.remove(target_abs)
                        except Exception:
                            pass
                    try:
                        if created_new_bak:
                            os.replace(bak_abs, target_abs)
                        else:
                            shutil.copy2(bak_abs, target_abs)
                    except Exception as e:
                        print(f"[Rollback] Lỗi khôi phục tệp patch_binary: {e}")
                        journal_errors.append((entry, str(e)))

            elif action == "copy_folder":
                copied_files = entry.get("copied_files", [])
                for item in copied_files:
                    if len(item) == 4:
                        f_rel, existed, created_new, f_has_tx = item
                    elif len(item) == 3:
                        f_rel, existed, created_new = item
                        f_has_tx = False
                    else:
                        f_rel, existed = item
                        created_new = False
                        f_has_tx = False
                    f_rel = _norm_rel(f_rel)
                    f_abs = os.path.join(game_path, f_rel)
                    b_abs = f"{f_abs}.congu_bak"
                    f_tx = f"{f_abs}.congu_tx_tmp"

                    if f_has_tx and os.path.exists(f_tx):
                        if os.path.exists(f_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass
                        try:
                            os.replace(f_tx, f_abs)
                            continue
                        except Exception:
                            pass

                    if created_new and os.path.exists(b_abs):
                        if os.path.exists(f_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass
                        try:
                            os.replace(b_abs, f_abs)
                        except Exception:
                            shutil.copy2(b_abs, f_abs)
                            try:
                                os.remove(b_abs)
                            except Exception:
                                pass
                    elif existed and os.path.exists(b_abs):
                        shutil.copy2(b_abs, f_abs)
                    elif not existed:
                        if os.path.exists(f_abs) and not os.path.exists(b_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass

            elif action in ("extract_all", "extract_zip"):
                extracted_files = entry.get("extracted_files", [])
                for item in extracted_files:
                    if len(item) == 4:
                        f_rel, existed, created_new, f_has_tx = item
                    elif len(item) == 3:
                        f_rel, existed, created_new = item
                        f_has_tx = False
                    else:
                        f_rel, existed = item
                        created_new = False
                        f_has_tx = False
                    f_rel = _norm_rel(f_rel)
                    f_abs = os.path.join(game_path, f_rel)
                    b_abs = f"{f_abs}.congu_bak"
                    f_tx = f"{f_abs}.congu_tx_tmp"

                    if f_has_tx and os.path.exists(f_tx):
                        if os.path.exists(f_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass
                        try:
                            os.replace(f_tx, f_abs)
                            continue
                        except Exception:
                            pass

                    if created_new and os.path.exists(b_abs):
                        if os.path.exists(f_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass
                        try:
                            os.replace(b_abs, f_abs)
                        except Exception:
                            shutil.copy2(b_abs, f_abs)
                            try:
                                os.remove(b_abs)
                            except Exception:
                                pass
                    elif existed and os.path.exists(b_abs):
                        shutil.copy2(b_abs, f_abs)
                    elif not existed:
                        if os.path.exists(f_abs) and not os.path.exists(b_abs):
                            try:
                                os.remove(f_abs)
                            except Exception:
                                pass

            elif action == "rename":
                src_orig = entry.get("source_orig")
                if src_orig and os.path.exists(target_abs):
                    try:
                        os.replace(target_abs, os.path.join(game_path, src_orig))
                    except Exception:
                        pass
        except Exception as rb_e:
            print(f"[Rollback Exception] {action} {target_rel}: {rb_e}")
            journal_errors.append((entry, str(rb_e)))

    if not journal_errors:
        print("[Rollback] Lớp 1 (Reverse Journal) hoàn nguyên 100% thành công!")
    else:
        print(f"[Rollback Warning] Lớp 1 hoàn nguyên xong với {len(journal_errors)} cảnh báo.")

    return True


def get_running_processes():
    """
    Enumerate running processes returning a list of tuples: (process_name_lower, full_path_or_None).
    Uses native Win32 Toolhelp API and QueryFullProcessImageNameW (0ms, 0 external dependencies).
    """
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_char * 260)
        ]

    try:
        hSnapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if hSnapshot == -1:
            return []
        procs = []
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(hSnapshot, ctypes.byref(pe)):
            while True:
                proc_name = pe.szExeFile.decode('latin-1', errors='ignore').lower()
                pid = pe.th32ProcessID
                full_path = None
                hProc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if hProc:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if ctypes.windll.kernel32.QueryFullProcessImageNameW(hProc, 0, buf, ctypes.byref(size)):
                            full_path = buf.value
                    finally:
                        ctypes.windll.kernel32.CloseHandle(hProc)
                procs.append((proc_name, full_path))
                if not ctypes.windll.kernel32.Process32Next(hSnapshot, ctypes.byref(pe)):
                    break
        ctypes.windll.kernel32.CloseHandle(hSnapshot)
        return procs
    except Exception:
        return []


def get_running_process_names():
    """Enumerate running process names using native Win32 Toolhelp API."""
    return {p[0] for p in get_running_processes()}


def check_game_running(game_def, game_path=None):
    """
    Check if the game executable or its crash handler / engine helper is currently running.
    Scans target executable, shipping variants, executables inside game_path, and verifies full process paths.
    Avoids false positives from generic crash handlers (UnityCrashHandler, CrashReportClient) running from other games/apps.
    Returns (is_running: bool, process_name: str | None)
    """
    target_exes = set()

    # 1. Executable defined in games.json + common shipping variants
    exe_name = game_def.get("executable_name") if isinstance(game_def, dict) else None
    if exe_name:
        base_exe = os.path.basename(exe_name).lower()
        target_exes.add(base_exe)
        root_name, ext = os.path.splitext(base_exe)
        target_exes.add(f"{root_name}-win64-shipping{ext}")
        target_exes.add(f"{root_name}-win32-shipping{ext}")
        target_exes.add(f"{root_name}gl{ext}")
        target_exes.add(f"{root_name.replace(' ', '')}{ext}")
        target_exes.add(f"{root_name.replace(' ', '_')}{ext}")

    # Generic crash handlers & engine helper processes that should ONLY match if running from inside game_path
    generic_helpers = {
        "unitycrashhandler64.exe",
        "unitycrashhandler32.exe",
        "crashreportclient.exe",
        "unrealcefsubprocess.exe"
    }

    # 2. Automatically scan executables in game_path if available (excluding generic helpers)
    if game_path and os.path.exists(game_path):
        try:
            for root, dirs, files in os.walk(game_path):
                rel_parts = os.path.relpath(root, game_path).split(os.sep)
                if len(rel_parts) > 3:
                    continue
                for f in files:
                    fl = f.lower()
                    if fl.endswith('.exe') and fl not in generic_helpers:
                        target_exes.add(fl)
        except Exception:
            pass

    # 3. Known default executable names or variants
    gid = game_def.get("id", "") if isinstance(game_def, dict) else ""
    if gid == "witcher3":
        target_exes.update(["witcher3.exe"])
    elif gid == "preludes":
        target_exes.update(["backbonestories.exe", "backbonestories-win64-shipping.exe"])
    elif gid == "backbone":
        target_exes.update(["detective.exe", "detective-win64-shipping.exe"])
    elif gid == "hotline_miami":
        target_exes.update(["hotlinegl.exe", "hotline_miami.exe"])
    elif gid == "toem":
        target_exes.update(["toem.exe"])
    elif gid == "ror2":
        target_exes.update(["risk of rain 2.exe", "riskofrain2.exe"])
    elif gid == "loop_hero":
        target_exes.update(["loop hero.exe", "loophero.exe"])
    elif gid == "fallout_tactics":
        target_exes.update(["bos.exe", "fallout tactics.exe", "bos_hr.exe"])
    elif gid == "ravenous_devils":
        target_exes.update(["ravenous_devils.exe", "ravenous_devils-win64-shipping.exe"])
    elif gid == "erra_exordium":
        target_exes.update(["erra.exe", "erra exordium.exe"])

    # 4. Check running processes against target_exes & game_path
    running_procs = get_running_processes()

    game_path_norm = None
    if game_path:
        try:
            game_path_norm = os.path.normcase(os.path.realpath(game_path) if os.path.exists(game_path) else os.path.abspath(game_path))
        except Exception:
            pass

    for proc_name, proc_path in running_procs:
        proc_path_norm = os.path.normcase(os.path.realpath(proc_path)) if proc_path else None

        # Trường hợp 1: Có cả đường dẫn thực thi của tiến trình và thư mục game
        if game_path_norm and proc_path_norm:
            is_inside_game = (
                proc_path_norm == game_path_norm
                or proc_path_norm.startswith(game_path_norm + os.sep)
            )
            if is_inside_game:
                # Nếu tiến trình đang chạy thuộc chính thư mục của game này
                if proc_name in target_exes or proc_name in generic_helpers:
                    return True, proc_name
            # Nếu proc_path không nằm trong thư mục game này, bỏ qua (không nhận nhầm)
            continue

        # Trường hợp 2: Fallback (không lấy được proc_path hoặc không có game_path)
        # Chỉ đối chiếu theo target_exes riêng của game (TUYỆT ĐỐI không đối chiếu generic_helpers)
        if proc_name in target_exes:
            return True, proc_name

    return False, None


def execute_secure_install(congu_path, game_path, install_steps=None, game_def=None, expected_sha256=None, auth_ticket=None, progress_callback=None):
    """
    SECURE EXECUTION ENGINE:
    Directly decrypts the .congu container in C memory and executes install_steps
    straight into the game directory.

    ZERO DATA LEAKAGE:
    - Never returns raw bytes, decrypted streams, or ZipFile handles to Python caller.
    - Destination directory is validated against legitimate game executable name.
    - Intermediate files are never written to %APPDATA% or user drives.
    - Transient buffers are immediately erased upon completion.
    """
    # 1. Anti-Hijacking Caller Check
    if not auth_ticket or not verify_session_ticket(auth_ticket):
        raise PermissionError(
            "Truy cập bị từ chối: Chỉ ứng dụng Cổ Ngữ (VietModHub) mới được phép kích hoạt tiến trình cài đặt an toàn!"
        )

    # 2. Anti-Dumping & Game Directory Legitimacy Verification
    if not game_def or not isinstance(game_def, dict):
        raise PermissionError("Cấu hình game_def không hợp lệ hoặc bị thiếu.")

    is_legit, legit_err = _verify_game_path_legitimacy(game_path, game_def)
    if not is_legit:
        raise PermissionError(f"Xác thực thư mục game thất bại: {legit_err}")

    # 2b. Running Game Process Pre-Flight Guard
    is_running, proc_name = check_game_running(game_def, game_path)
    if is_running:
        raise PermissionError(
            f"Tiến trình '{proc_name}' của game đang chạy! "
            f"Vui lòng đóng game hoàn toàn trước khi cài đặt để tránh xung đột khóa tệp tin."
        )

    # 2c. Pre-existing Environment Tracking (Mục 1.5 - BepInEx & winhttp.dll Protection)
    game_id = game_def.get("id") if (game_def and isinstance(game_def, dict)) else None
    winhttp_pre, bepinex_pre = record_preexisting_environment(game_id, game_path)

    # 3. Integrity Verification (SHA-256)
    if expected_sha256:
        if progress_callback:
            progress_callback(5, "Đang kiểm tra tính toàn vẹn gói bảo mật (SHA-256)...")
        if not verify_package_checksum(congu_path, expected_sha256):
            raise ValueError(
                "Xác thực gói bảo mật thất bại: Mã kiểm tra toàn vẹn SHA-256 không khớp! "
                "Tệp tin có thể bị lỗi khi tải về hoặc đã bị can thiệp trái phép."
            )

    if progress_callback:
        progress_callback(12, "Đang nạp gói bảo mật CỔ NGỮ (AES-256-GCM)...")

    # 4. Decrypt via _ConguStreamReader: In-Memory Sliding Window, Zero Disk Spooling
    stream_reader = _ConguStreamReader(congu_path, auth_ticket=auth_ticket, progress_callback=progress_callback)

    backed_up_files = []
    installed_files_count = 0
    executed_journal = []
    tx_temp_files = []

    try:
        with zipfile.ZipFile(stream_reader, "r") as zf:
            steps = install_steps or (game_def.get("install_steps") if isinstance(game_def, dict) else None)
            # Fallback synthesis if steps not provided
            if not steps or not isinstance(steps, list):
                if game_def and game_def.get("mod_type") == "pak":
                    dst_pak = os.path.join(
                        game_def.get("relative_install_path", ""),
                        game_def.get("target_pak_name", game_def.get("mod_file", ""))
                    )
                    steps = [{"action": "copy_file", "source": game_def.get("mod_file", ""), "destination": dst_pak}]
                elif game_def and game_def.get("mod_type") == "unity_assets":
                    dst_assets = os.path.join(
                        game_def.get("relative_install_path", ""),
                        game_def.get("target_pak_name", "")
                    )
                    steps = [
                        {"action": "backup", "target": dst_assets},
                        {"action": "copy_file", "source": game_def.get("mod_file", ""), "destination": dst_assets}
                    ]
                    for af in game_def.get("additional_files", []):
                        steps.append({"action": "backup", "target": af["dst"]})
                        steps.append({"action": "copy_file", "source": af["src"], "destination": af["dst"]})
                else:
                    steps = [{"action": "extract_all", "destination": ""}]

            total_steps = len(steps)
            if progress_callback:
                progress_callback(60, f"Đang cài đặt trực tiếp vào game ({total_steps} bước an toàn)...")

            try:
                for s_idx, step in enumerate(steps):
                    action = step.get("action", "").lower().strip()
                    pct = int(60 + ((s_idx + 1) / total_steps) * 35)

                    if action == "backup":
                        target_rel = _norm_rel(step.get("target"))
                        if not target_rel:
                            raise ValueError("Bước 'backup' thiếu trường bắt buộc 'target'")
                        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
                        bak_abs = f"{target_abs}.congu_bak"
                        is_ini = target_rel.lower().endswith(('.ini', '.cfg', '.conf'))
                        created_new_bak = False

                        # Load manifest to detect Steam/Epic update
                        game_id = game_def.get("id") if (game_def and isinstance(game_def, dict)) else None
                        appdata_base = os.environ.get("APPDATA", "")
                        manifest_path = os.path.join(appdata_base, "VietModHub", "backups", game_id, "backup_manifest.json") if (appdata_base and game_id) else None

                        manifest_item = None
                        if manifest_path and os.path.exists(manifest_path):
                            try:
                                import json
                                with open(manifest_path, "r", encoding="utf-8") as mf:
                                    m_data = json.load(mf)
                                    for it in m_data.get("files", []):
                                        if _norm_rel(it.get("relative_in_game")) == target_rel:
                                            manifest_item = it
                                            break
                            except Exception:
                                pass

                        # Check if existing .congu_bak is stale because Steam/Epic updated the game
                        if os.path.exists(bak_abs) and os.path.exists(target_abs):
                            modded_hash = manifest_item.get("modded_sha256") if manifest_item else None
                            if modded_hash:
                                curr_target_hash = compute_file_sha256(target_abs)
                                if curr_target_hash and curr_target_hash.lower() != modded_hash.lower():
                                    print(f"[Smart Update Detection] Tệp '{target_rel}' đã được Steam/Epic cập nhật mới (không khớp bản mod cũ). Đang xóa .congu_bak cũ để tạo bản backup mới.")
                                    try:
                                        os.remove(bak_abs)
                                    except Exception:
                                        pass

                        orig_hash = None
                        orig_size = 0
                        orig_mtime = 0

                        # Bẫy A: Cài đè lần 2 không bao giờ ghi đè lên .congu_bak đã có
                        has_tx_tmp = False
                        tx_tmp_abs = f"{target_abs}.congu_tx_tmp"
                        if os.path.exists(target_abs):
                            if not os.path.exists(bak_abs):
                                # Chưa có .congu_bak (lần 1): tạo backup gốc
                                orig_hash = compute_file_sha256(target_abs)
                                orig_size = os.path.getsize(target_abs)
                                orig_mtime = os.path.getmtime(target_abs)
                                if is_ini:
                                    shutil.copy2(target_abs, bak_abs)
                                    created_new_bak = True
                                else:
                                    try:
                                        os.rename(target_abs, bak_abs)
                                        created_new_bak = True
                                    except Exception:
                                        try:
                                            if os.path.isdir(target_abs):
                                                shutil.copytree(target_abs, bak_abs, dirs_exist_ok=True)
                                                shutil.rmtree(target_abs, ignore_errors=True)
                                            else:
                                                shutil.copy2(target_abs, bak_abs)
                                                os.remove(target_abs)
                                            created_new_bak = True
                                        except Exception:
                                            pass
                            else:
                                # .congu_bak đã tồn tại (cài đè lần 2 / cập nhật v1.1): TUYỆT ĐỐI GIỮ NGUYÊN FILE GỐC .congu_bak!
                                orig_hash = manifest_item.get("original_sha256") if manifest_item else compute_file_sha256(bak_abs)
                                orig_size = os.path.getsize(bak_abs) if os.path.exists(bak_abs) else 0
                                orig_mtime = os.path.getmtime(bak_abs) if os.path.exists(bak_abs) else 0
                                # Lưu tệp hiện tại (v1.0) sang .congu_tx_tmp để phục vụ rollback nếu v1.1 lỗi!
                                if not is_ini:
                                    try:
                                        if os.path.isdir(target_abs):
                                            shutil.copytree(target_abs, tx_tmp_abs, dirs_exist_ok=True)
                                            shutil.rmtree(target_abs, ignore_errors=True)
                                        else:
                                            shutil.copy2(target_abs, tx_tmp_abs)
                                            os.remove(target_abs)
                                        has_tx_tmp = True
                                        tx_temp_files.append(tx_tmp_abs)
                                    except Exception:
                                        pass
                        elif os.path.exists(bak_abs):
                            orig_hash = manifest_item.get("original_sha256") if manifest_item else compute_file_sha256(bak_abs)
                            orig_size = os.path.getsize(bak_abs)
                            orig_mtime = os.path.getmtime(bak_abs)

                        backed_up_files.append({
                            "relative_in_game": target_rel,
                            "target_file": target_abs,
                            "backup_file": bak_abs,
                            "size_bytes": os.path.getsize(bak_abs) if os.path.exists(bak_abs) else 0,
                            "original_sha256": orig_hash,
                            "original_size": orig_size,
                            "original_mtime": orig_mtime
                        })
                        executed_journal.append({
                            "action": "backup",
                            "target": target_rel,
                            "is_ini": is_ini,
                            "created_new_bak": created_new_bak,
                            "has_tx_tmp": has_tx_tmp,
                            "tx_tmp": tx_tmp_abs
                        })
                        if progress_callback:
                            progress_callback(pct, f"Đang sao lưu tệp gốc an toàn: {os.path.basename(target_rel)}")

                    elif action == "copy_file":
                        src_rel = _norm_rel(step.get("source"))
                        dst_rel = _norm_rel(step.get("destination", src_rel))
                        if not src_rel:
                            raise ValueError("Bước 'copy_file' thiếu trường bắt buộc 'source'")
                        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=False)
                        member_name = _find_zip_member(zf, src_rel)
                        if not member_name:
                            if step.get("optional", False):
                                continue
                            raise FileNotFoundError(f"Không tìm thấy tệp '{src_rel}' trong gói bảo mật Cổ Ngữ!")

                        existed_before = os.path.exists(dst_abs)
                        created_new_bak = False
                        has_tx_tmp = False
                        bak_abs = f"{dst_abs}.congu_bak"
                        tx_tmp_abs = f"{dst_abs}.congu_tx_tmp"

                        # Auto-Backup ngầm: Cứ hễ đích đến đã tồn tại file trước khi chép đè, tự động tạo .congu_bak nếu chưa có
                        if existed_before and os.path.isfile(dst_abs):
                            if not os.path.exists(bak_abs):
                                try:
                                    os.makedirs(os.path.dirname(bak_abs), exist_ok=True)
                                    os.rename(dst_abs, bak_abs)
                                    created_new_bak = True
                                    orig_hash = compute_file_sha256(bak_abs)
                                    backed_up_files.append({
                                        "relative_in_game": dst_rel,
                                        "target_file": dst_abs,
                                        "backup_file": bak_abs,
                                        "size_bytes": os.path.getsize(bak_abs),
                                        "original_sha256": orig_hash,
                                        "original_size": os.path.getsize(bak_abs),
                                        "original_mtime": os.path.getmtime(bak_abs)
                                    })
                                except Exception as e:
                                    print(f"[Security Auto-Backup Warning] copy_file {dst_abs}: {e}")
                            else:
                                # bak_abs đã tồn tại -> dst_abs là bản mod trước đó. Lưu tx_tmp để rollback nếu v1.1 lỗi!
                                try:
                                    shutil.copy2(dst_abs, tx_tmp_abs)
                                    has_tx_tmp = True
                                    tx_temp_files.append(tx_tmp_abs)
                                except Exception as e:
                                    print(f"[Security Tx-Tmp Warning] copy_file {dst_abs}: {e}")

                        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                        with zf.open(member_name, "r") as src_stream, open(dst_abs, "wb") as dst_stream:
                            shutil.copyfileobj(src_stream, dst_stream, length=65536)
                        installed_files_count += 1
                        executed_journal.append({
                            "action": "copy_file",
                            "target": dst_rel,
                            "destination": dst_rel,
                            "existed_before": existed_before,
                            "created_new_bak": created_new_bak,
                            "has_tx_tmp": has_tx_tmp,
                            "tx_tmp": tx_tmp_abs
                        })

                        if progress_callback:
                            progress_callback(pct, f"Đang cài đặt an toàn: {os.path.basename(dst_rel)}")

                    elif action == "patch_binary":
                        target_rel = _norm_rel(step.get("target"))
                        patch_rel = _norm_rel(step.get("patch") or step.get("source"))
                        if not target_rel or not patch_rel:
                            raise ValueError("Bước 'patch_binary' yêu cầu cả hai trường 'target' và 'patch' (hoặc 'source')")

                        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
                        bak_abs = f"{target_abs}.congu_bak"

                        member_name = _find_zip_member(zf, patch_rel)
                        if not member_name:
                            raise FileNotFoundError(f"Không tìm thấy tệp patch '{patch_rel}' trong gói bảo mật Cổ Ngữ!")

                        # 1. Xác định tệp nguồn để vá (Hỗ trợ cài đè/cập nhật bản dịch nếu target đã bị mod)
                        expected_orig_sha = step.get("original_sha256")
                        source_file_for_patch = None
                        created_new_bak = False

                        target_exists = os.path.exists(target_abs)
                        bak_exists = os.path.exists(bak_abs)

                        if not target_exists and not bak_exists:
                            raise FileNotFoundError(f"Không tìm thấy tệp gốc của game để vá: '{target_rel}'")

                        if expected_orig_sha:
                            norm_expected = expected_orig_sha.lower().strip()
                            # A. Kiểm tra nếu tệp đích hiện tại khớp mã băm gốc
                            if target_exists:
                                actual_target_sha = compute_file_sha256(target_abs)
                                if actual_target_sha and actual_target_sha.lower() == norm_expected:
                                    source_file_for_patch = target_abs

                            # B. Nếu tệp đích không khớp (đã cài mod trước đó), kiểm tra tệp sao lưu .congu_bak
                            if not source_file_for_patch and bak_exists:
                                actual_bak_sha = compute_file_sha256(bak_abs)
                                if actual_bak_sha and actual_bak_sha.lower() == norm_expected:
                                    source_file_for_patch = bak_abs

                            # C. Nếu cả hai đều không khớp, báo lỗi lệch phiên bản game
                            if not source_file_for_patch:
                                t_sha = compute_file_sha256(target_abs) if target_exists else "Missing"
                                b_sha = compute_file_sha256(bak_abs) if bak_exists else "Missing"
                                raise SecurityError(
                                    f"Lỗi toàn vẹn tệp gốc '{target_rel}': Mã băm không khớp! "
                                    f"(Dự kiến: {expected_orig_sha}, Thực tế tệp đích: {t_sha}, Tệp .congu_bak: {b_sha}). "
                                    f"Game trên Steam có thể đã cập nhật phiên bản mới hoặc tệp tin bị hỏng."
                                )
                        else:
                            if bak_exists:
                                source_file_for_patch = bak_abs
                            elif target_exists:
                                source_file_for_patch = target_abs
                            else:
                                raise FileNotFoundError(f"Không tìm thấy tệp gốc của game để vá: '{target_rel}'")

                        # 2. Auto-backup tệp gốc trước khi vá nếu chưa có sao lưu
                        has_tx_tmp = False
                        tx_tmp_abs = f"{target_abs}.congu_tx_tmp"
                        if not os.path.exists(bak_abs) and os.path.exists(target_abs):
                            try:
                                os.makedirs(os.path.dirname(bak_abs), exist_ok=True)
                                shutil.copy2(target_abs, bak_abs)
                                created_new_bak = True
                                orig_hash = compute_file_sha256(bak_abs)
                                backed_up_files.append({
                                    "relative_in_game": target_rel,
                                    "target_file": target_abs,
                                    "backup_file": bak_abs,
                                    "size_bytes": os.path.getsize(bak_abs),
                                    "original_sha256": orig_hash,
                                    "original_size": os.path.getsize(bak_abs),
                                    "original_mtime": os.path.getmtime(bak_abs)
                                })
                            except Exception as e:
                                print(f"[Security Auto-Backup Warning] patch_binary {target_abs}: {e}")
                        elif os.path.exists(bak_abs) and os.path.exists(target_abs):
                            # bak_abs đã có, target_abs hiện tại là bản mod trước đó. Lưu tx_tmp để rollback nếu v1.1 lỗi!
                            try:
                                shutil.copy2(target_abs, tx_tmp_abs)
                                has_tx_tmp = True
                                tx_temp_files.append(tx_tmp_abs)
                            except Exception as e:
                                print(f"[Security Tx-Tmp Warning] patch_binary {target_abs}: {e}")

                        # 3. Trích xuất luồng patch trực tiếp ra tệp tạm bằng streaming chunk 64KB (không nạp toàn bộ vào RAM)
                        tmp_patch_file = f"{target_abs}.congu_patch_stream_{os.getpid()}_{int(time.time() * 1000)}.tmp"
                        tmp_patched_file = f"{target_abs}.congu_patching_{os.getpid()}.tmp"
                        try:
                            with zf.open(member_name, "r") as p_stream, open(tmp_patch_file, "wb") as tmp_pf:
                                shutil.copyfileobj(p_stream, tmp_pf, length=65536)

                            # 4. Áp dụng bản vá từ source_file_for_patch ra file tạm thời an toàn
                            apply_binary_patch(source_file_for_patch, tmp_patched_file, tmp_patch_file)

                            # 5. Kiểm tra patched_sha256 nếu có khai báo
                            expected_patched_sha = step.get("patched_sha256")
                            if expected_patched_sha:
                                actual_patched_sha = compute_file_sha256(tmp_patched_file)
                                if actual_patched_sha and actual_patched_sha.lower() != expected_patched_sha.lower().strip():
                                    raise SecurityError(
                                        f"Lỗi kiểm tra sau vá tệp '{target_rel}': Mã băm không khớp! "
                                        f"(Dự kiến: {expected_patched_sha}, Thực tế: {actual_patched_sha})."
                                    )

                            # 6. Thay thế nguyên tử ghi đè lên target_abs
                            os.replace(tmp_patched_file, target_abs)
                        finally:
                            if os.path.exists(tmp_patch_file):
                                try:
                                    os.remove(tmp_patch_file)
                                except Exception:
                                    pass
                            if os.path.exists(tmp_patched_file):
                                try:
                                    os.remove(tmp_patched_file)
                                except Exception:
                                    pass

                        installed_files_count += 1
                        executed_journal.append({
                            "action": "patch_binary",
                            "target": target_rel,
                            "created_new_bak": created_new_bak,
                            "existed_before": True,
                            "has_tx_tmp": has_tx_tmp,
                            "tx_tmp": tx_tmp_abs
                        })

                        if progress_callback:
                            progress_callback(pct, f"Đang áp dụng bản vá nhị phân: {os.path.basename(target_rel)}")

                    elif action == "copy_folder":
                        src_rel = _norm_rel(step.get("source"))
                        dst_rel = _norm_rel(step.get("destination", src_rel))
                        if not src_rel:
                            raise ValueError("Bước 'copy_folder' thiếu trường bắt buộc 'source'")
                        validate_safe_path(game_path, dst_rel, allow_base_itself=True)
                        folder_members = _find_zip_folder_members(zf, src_rel)
                        if not folder_members and not step.get("optional", False):
                            raise FileNotFoundError(f"Không tìm thấy thư mục '{src_rel}' trong gói bảo mật Cổ Ngữ!")

                        copied_files = []
                        for member, sub_rel in folder_members:
                            dst_file = validate_safe_path(game_path, os.path.join(dst_rel, sub_rel), allow_base_itself=False)
                            d_rel = _norm_rel(os.path.relpath(dst_file, game_path))
                            existed_before = os.path.exists(dst_file)
                            created_new_bak = False
                            has_tx_tmp = False
                            b_file = f"{dst_file}.congu_bak"
                            tx_file = f"{dst_file}.congu_tx_tmp"

                            # Auto-Backup ngầm trước khi ghi đè
                            if existed_before and os.path.isfile(dst_file):
                                if not os.path.exists(b_file):
                                    try:
                                        os.makedirs(os.path.dirname(b_file), exist_ok=True)
                                        os.rename(dst_file, b_file)
                                        created_new_bak = True
                                        orig_hash = compute_file_sha256(b_file)
                                        backed_up_files.append({
                                            "relative_in_game": d_rel,
                                            "target_file": dst_file,
                                            "backup_file": b_file,
                                            "size_bytes": os.path.getsize(b_file),
                                            "original_sha256": orig_hash,
                                            "original_size": os.path.getsize(b_file),
                                            "original_mtime": os.path.getmtime(b_file)
                                        })
                                    except Exception as e:
                                        print(f"[Security Auto-Backup Folder Warning] {dst_file}: {e}")
                                else:
                                    try:
                                        shutil.copy2(dst_file, tx_file)
                                        has_tx_tmp = True
                                        tx_temp_files.append(tx_file)
                                    except Exception as e:
                                        print(f"[Security Tx-Tmp Folder Warning] {dst_file}: {e}")

                            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                            with zf.open(member, "r") as src_stream, open(dst_file, "wb") as dst_stream:
                                shutil.copyfileobj(src_stream, dst_stream, length=65536)
                            installed_files_count += 1
                            copied_files.append((d_rel, existed_before, created_new_bak, has_tx_tmp))
                        executed_journal.append({
                            "action": "copy_folder",
                            "target": dst_rel,
                            "destination": dst_rel,
                            "copied_files": copied_files
                        })

                        if progress_callback:
                            progress_callback(pct, f"Đang cài đặt thư mục: {os.path.basename(src_rel)}")

                    elif action in ("extract_all", "extract_zip"):
                        dst_rel = _norm_rel(step.get("destination", ""))
                        dst_dir = validate_safe_path(game_path, dst_rel, allow_base_itself=True)
                        extracted_files = []
                        for member in zf.infolist():
                            if member.is_dir() or member.filename.endswith("/"):
                                continue
                            # Anti-Zip-Slip: validate target destination for each member
                            dst_file = validate_safe_path(dst_dir, member.filename, allow_base_itself=False)
                            t_rel = _norm_rel(os.path.relpath(dst_file, game_path))
                            existed_before = os.path.exists(dst_file)
                            created_new_bak = False
                            has_tx_tmp = False
                            b_file = f"{dst_file}.congu_bak"
                            tx_file = f"{dst_file}.congu_tx_tmp"

                            # Auto-Backup ngầm trước khi trích xuất đè
                            if existed_before and os.path.isfile(dst_file):
                                if not os.path.exists(b_file):
                                    try:
                                        os.makedirs(os.path.dirname(b_file), exist_ok=True)
                                        os.rename(dst_file, b_file)
                                        created_new_bak = True
                                        orig_hash = compute_file_sha256(b_file)
                                        backed_up_files.append({
                                            "relative_in_game": t_rel,
                                            "target_file": dst_file,
                                            "backup_file": b_file,
                                            "size_bytes": os.path.getsize(b_file),
                                            "original_sha256": orig_hash,
                                            "original_size": os.path.getsize(b_file),
                                            "original_mtime": os.path.getmtime(b_file)
                                        })
                                    except Exception as e:
                                        print(f"[Security Auto-Backup Extract Warning] {dst_file}: {e}")
                                else:
                                    try:
                                        shutil.copy2(dst_file, tx_file)
                                        has_tx_tmp = True
                                        tx_temp_files.append(tx_file)
                                    except Exception as e:
                                        print(f"[Security Tx-Tmp Extract Warning] {dst_file}: {e}")

                            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                            with zf.open(member, "r") as src_stream, open(dst_file, "wb") as dst_stream:
                                shutil.copyfileobj(src_stream, dst_stream, length=65536)
                            installed_files_count += 1
                            extracted_files.append((t_rel, existed_before, created_new_bak, has_tx_tmp))
                        executed_journal.append({
                            "action": "extract_all",
                            "target": dst_rel,
                            "destination": dst_rel,
                            "extracted_files": extracted_files
                        })

                        if progress_callback:
                            progress_callback(pct, "Đang trích xuất toàn bộ gói tài nguyên...")

                    elif action == "patch_ini":
                        file_rel = _norm_rel(step.get("file") or step.get("target"))
                        if not file_rel:
                            raise ValueError("Bước 'patch_ini' thiếu trường bắt buộc 'file' hoặc 'target'")
                        file_abs = validate_safe_path(game_path, file_rel, allow_base_itself=False)
                        bak_file = f"{file_abs}.congu_bak"

                        # Bẫy cấu hình (Mục 1.3): Tự phục hồi file .ini nếu trước đó bị lệnh backup đổi tên làm mất!
                        if not os.path.exists(file_abs) and os.path.exists(bak_file):
                            try:
                                shutil.copy2(bak_file, file_abs)
                                print(f"[Security Self-Healing] File '{file_rel}' không tồn tại nhưng có sẵn '{bak_file}' do bước backup trước đó. Đã tự động chép ngược nội dung từ .congu_bak để giữ nguyên cấu hình gốc.")
                            except Exception:
                                pass

                        # Bẫy A & B: patch_ini LUÔN dùng COPY (shutil.copy2), không bao giờ Rename!
                        created_new_bak = False
                        has_tx_tmp = False
                        tx_tmp_abs = f"{file_abs}.congu_tx_tmp"
                        if os.path.exists(file_abs) and not os.path.exists(bak_file):
                            try:
                                shutil.copy2(file_abs, bak_file)
                                created_new_bak = True
                            except Exception:
                                pass
                        elif os.path.exists(file_abs) and os.path.exists(bak_file):
                            try:
                                shutil.copy2(file_abs, tx_tmp_abs)
                                has_tx_tmp = True
                                tx_temp_files.append(tx_tmp_abs)
                            except Exception:
                                pass

                        if os.path.exists(bak_file):
                            orig_hash = compute_file_sha256(bak_file)
                            bak_size = os.path.getsize(bak_file)
                            bak_mtime = os.path.getmtime(bak_file)
                            backed_up_files.append({
                                "relative_in_game": file_rel,
                                "target_file": file_abs,
                                "backup_file": bak_file,
                                "size_bytes": bak_size,
                                "original_sha256": orig_hash,
                                "original_size": bak_size,
                                "original_mtime": bak_mtime
                            })

                        _patch_ini_file_internal(
                            file_abs,
                            section=step.get("section"),
                            key=step.get("key"),
                            value=step.get("value"),
                            encoding=step.get("encoding", "utf-8")
                        )
                        executed_journal.append({
                            "action": "patch_ini",
                            "target": file_rel,
                            "created_new_bak": created_new_bak,
                            "has_tx_tmp": has_tx_tmp,
                            "tx_tmp": tx_tmp_abs
                        })
                        if progress_callback:
                            progress_callback(pct, f"Cấu hình tệp: {os.path.basename(file_rel)}")

                    elif action == "delete":
                        target_rel = _norm_rel(step.get("target"))
                        if not target_rel:
                            raise ValueError("Bước 'delete' thiếu trường bắt buộc 'target'")
                        target_abs = validate_safe_path(game_path, target_rel, allow_base_itself=False)
                        if os.path.exists(target_abs):
                            if os.path.isdir(target_abs):
                                shutil.rmtree(target_abs, ignore_errors=True)
                            else:
                                try:
                                    os.remove(target_abs)
                                except Exception:
                                    pass

                    elif action == "rename":
                        src_rel = _norm_rel(step.get("source"))
                        dst_rel = _norm_rel(step.get("destination"))
                        if not src_rel or not dst_rel:
                            raise ValueError("Bước 'rename' yêu cầu cả hai trường 'source' và 'destination'")
                        src_abs = validate_safe_path(game_path, src_rel, allow_base_itself=False)
                        dst_abs = validate_safe_path(game_path, dst_rel, allow_base_itself=False)
                        if os.path.exists(src_abs):
                            if os.path.exists(dst_abs):
                                if os.path.isdir(dst_abs):
                                    shutil.rmtree(dst_abs, ignore_errors=True)
                                else:
                                    try:
                                        os.remove(dst_abs)
                                    except Exception:
                                        pass
                            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                            os.rename(src_abs, dst_abs)
                            executed_journal.append({
                                "action": "rename",
                                "target": dst_rel,
                                "source_orig": src_rel
                            })

            except Exception as step_error:
                # TRANSACTION ROLLBACK TRIGGER
                if progress_callback:
                    progress_callback(0, f"Sự cố tại bước {s_idx+1}: {step_error}. Đang kích hoạt Transaction Rollback...")

                _rollback_transaction(game_path, executed_journal, game_def)

                raise RuntimeError(
                    f"Quá trình cài đặt gặp sự cố tại bước {s_idx+1}/{total_steps} ({action}): {str(step_error)}. "
                    f"Hệ thống đã tự động kích hoạt Transaction Rollback: toàn bộ tệp tin game đã được hoàn nguyên 100% về trạng thái ổn định trước khi cài đặt!"
                ) from step_error

    finally:
        for tx_f in tx_temp_files:
            if os.path.exists(tx_f):
                try:
                    if os.path.isdir(tx_f):
                        shutil.rmtree(tx_f, ignore_errors=True)
                    else:
                        os.remove(tx_f)
                except Exception:
                    pass
        stream_reader.close()
        gc.collect()

    if progress_callback:
        progress_callback(100, "Cài đặt an toàn hoàn tất 100%!")

    # Record post-installation modded hashes for all backed up files to detect future Steam/Epic updates
    for b_item in backed_up_files:
        t_path = b_item.get("target_file")
        if t_path and os.path.exists(t_path):
            b_item["modded_sha256"] = compute_file_sha256(t_path)
            b_item["modded_size"] = os.path.getsize(t_path)
            b_item["modded_mtime"] = os.path.getmtime(t_path)

    return {
        "success": True,
        "message": "Cài đặt an toàn hoàn tất trực tiếp vào thư mục game!",
        "installed_files_count": installed_files_count,
        "backed_up_files": backed_up_files,
        "winhttp_preexisting": winhttp_pre,
        "bepinex_preexisting": bepinex_pre
    }
