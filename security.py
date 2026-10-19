"""
CoNgu Security Engine - Proprietary Encrypted Mod Container (.congu)
Uses military-grade AES-256-GCM authenticated encryption with PBKDF2-HMAC-SHA256 key derivation.
Protects translation assets, fonts, scripts, and localization packages from unauthorized extraction.
"""

import os
import io
import zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Proprietary Container Magic Header (v1)
CONGU_MAGIC = b"CONGU\x01"
ASSOC_METADATA = b"CO_NGU_SECURITY_LOCALIZATION_V1"

def _get_master_key_bytes():
    """
    Dynamically reconstruct the master secret key in memory.
    Protects against simple string extraction or static file scanners.
    """
    p1 = bytes([67, 111, 78, 103, 117, 95, 80, 114, 111])  # 'CoNgu_Pro'
    p2 = bytes([95, 67, 121, 98, 101, 114, 83, 101, 99])  # '_CyberSec'
    p3 = bytes([117, 114, 101, 95, 76, 111, 99, 97, 108]) # 'ure_Local'
    p4 = bytes([105, 122, 97, 116, 105, 111, 110, 95])    # 'ization_'
    p5 = bytes([75, 101, 121, 95, 50, 48, 50, 54, 95, 33, 64, 35]) # 'Key_2026_!@#'
    return p1 + p2 + p3 + p4 + p5

def encrypt_mod_package(zip_path, congu_path):
    """
    Encrypt a standard mod zip file into a secure .congu container.
    """
    with open(zip_path, "rb") as f:
        data = f.read()

    salt = os.urandom(16)
    nonce = os.urandom(12)
    master_secret = _get_master_key_bytes()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000
    )
    key = kdf.derive(master_secret)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, ASSOC_METADATA)

    with open(congu_path, "wb") as f:
        f.write(CONGU_MAGIC + salt + nonce + ciphertext)

    return os.path.getsize(congu_path)

def is_congu_package(file_path):
    """
    Check if a file is a valid encrypted .congu container.
    """
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 34:
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(6)
            return header == CONGU_MAGIC
    except Exception:
        return False

def extract_congu_package(congu_path, target_extract_dir, progress_callback=None):
    """
    Decrypts a .congu package in-memory and extracts contents directly into target_extract_dir.
    No unencrypted intermediate zip file is ever written to disk.
    """
    if progress_callback:
        progress_callback(10, "Đang nạp gói bảo mật CỔ NGỮ (AES-256)...")

    with open(congu_path, "rb") as f:
        magic = f.read(6)
        if magic != CONGU_MAGIC:
            raise ValueError("Không phải định dạng gói CỔ NGỮ hợp lệ (.congu)!")
        salt = f.read(16)
        nonce = f.read(12)
        ciphertext = f.read()

    if progress_callback:
        progress_callback(30, "Đang xác thực chữ ký & giải mã dữ liệu an toàn...")

    master_secret = _get_master_key_bytes()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000
    )
    key = kdf.derive(master_secret)
    aesgcm = AESGCM(key)

    try:
        decrypted_zip_data = aesgcm.decrypt(nonce, ciphertext, ASSOC_METADATA)
    except Exception as e:
        raise ValueError(f"Giải mã thất bại: Khóa bảo mật không khớp hoặc file bị can thiệp! ({e})")

    if progress_callback:
        progress_callback(70, "Đang giải nén các tài nguyên Việt hóa vào thư mục tạm...")

    os.makedirs(target_extract_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(decrypted_zip_data), "r") as zf:
        zf.extractall(target_extract_dir)

    # Immediately release decrypted memory
    del decrypted_zip_data

    if progress_callback:
        progress_callback(100, "Giải mã và chuẩn bị mod hoàn tất an toàn!")

    return True
