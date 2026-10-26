#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub) - Developer Mod Packaging Security Engine (pack_security.py)
-------------------------------------------------------------------------
Module đóng gói bảo mật dành riêng cho nhà phát triển (Dev Environment).
Chịu trách nhiệm mã hóa container .congu V2 với chuẩn AES-256-GCM Streaming
và dẫn xuất khóa PBKDF2-HMAC-SHA256 (100,000 vòng lặp).

BẢO MẬT: Tệp tin này chỉ lưu hành nội bộ trên máy phát triển, TUYỆT ĐỐI KHÔNG
phân phối kèm theo bản phát hành người dùng cuối (Client Portable / Installer).
"""

import os
import sys
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CONGU_MAGIC_V1 = b"CONGU\x01"
CONGU_MAGIC_V2 = b"CONGU\x02"
ASSOC_METADATA = b"CO_NGU_SECURITY_LOCALIZATION_V1"

# Khóa gốc bảo mật tái tạo động trong RAM của môi trường đóng gói Dev
_K_MASK = 0xA7
_O_KEY_BYTES = bytes([
    228, 200, 233, 192, 210, 248, 247, 213, 200, 248, 228, 222, 197, 194, 213, 244,
    194, 196, 210, 213, 194, 248, 235, 200, 196, 198, 203, 206, 221, 198, 211, 206,
    200, 201, 248, 236, 194, 222, 248, 149, 151, 149, 145, 248, 134, 231, 132
])


def get_dev_master_key():
    """Tái tạo khóa chính từ mảng bytes đã che giấu bằng phép toán XOR."""
    return bytes([b ^ _K_MASK for b in _O_KEY_BYTES])


def encrypt_mod_package(zip_path, congu_path, version=2, chunk_size=4 * 1024 * 1024):
    """
    Mã hóa tệp nén mod chuẩn thành container .congu bảo mật.
    - version=1: Đóng gói đơn khối AES-256-GCM (tương thích ngược)
    - version=2: Đóng gói phân khối streaming AES-256-GCM (tối ưu cho mod nặng)
    """
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Tệp zip nguồn không tồn tại: {zip_path}")

    salt = os.urandom(16)
    master_secret = get_dev_master_key()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000
    )
    key = kdf.derive(master_secret)
    aesgcm = AESGCM(key)

    if version == 1:
        with open(zip_path, "rb") as f:
            data = f.read()
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, ASSOC_METADATA)
        with open(congu_path, "wb") as f:
            f.write(CONGU_MAGIC_V1 + salt + nonce + ciphertext)
    else:
        with open(zip_path, "rb") as f_in, open(congu_path, "wb") as f_out:
            f_out.write(CONGU_MAGIC_V2 + salt)
            chunk_idx = 0
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                nonce = os.urandom(12)
                assoc = ASSOC_METADATA + chunk_idx.to_bytes(4, "big")
                ciphertext = aesgcm.encrypt(nonce, chunk, assoc)
                f_out.write(len(ciphertext).to_bytes(4, "big"))
                f_out.write(nonce)
                f_out.write(ciphertext)
                chunk_idx += 1

    return os.path.getsize(congu_path)
