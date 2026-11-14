# -*- coding: utf-8 -*-
"""Xác minh manifest phát hành có chữ ký Ed25519.

Khóa công khai tin cậy nằm trong mã nguồn; khóa tư nhân chỉ tồn tại ngoài
repository và được dùng bởi `tools/sign_release_manifest.py` khi phát hành.
"""
import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

RELEASE_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAzVRp+Hrqlne2SwSbWVrsuvbZ6MU+8fsenyemkS+J6Uo=
-----END PUBLIC KEY-----
"""

SIGNED_FIELDS = ("version", "portable_zip_url", "portable_zip_sha256")


def canonical_manifest_payload(manifest: dict) -> bytes:
    """Payload cố định để ký và xác minh: đúng 3 trường phát hành, khóa sắp xếp."""
    fields = {
        "version": str(manifest.get("version") or ""),
        "portable_zip_url": str(manifest.get("portable_zip_url") or ""),
        "portable_zip_sha256": str(manifest.get("portable_zip_sha256") or "").lower(),
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_manifest_signature(manifest: dict, public_key_pem: bytes = None) -> tuple:
    """Trả về (hợp_lệ, lý_do). Thiếu chữ ký hoặc sai chữ ký đều bị coi là không hợp lệ."""
    signature_text = str(manifest.get("manifest_signature") or "").strip()
    if not signature_text:
        return False, "Manifest phát hành thiếu chữ ký số"
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except Exception:
        return False, "Chữ ký manifest không đúng định dạng base64"
    try:
        public_key = load_pem_public_key(public_key_pem or RELEASE_PUBLIC_KEY_PEM)
        public_key.verify(signature, canonical_manifest_payload(manifest))
        return True, ""
    except InvalidSignature:
        return False, "Chữ ký manifest không hợp lệ"
    except Exception as exc:
        return False, f"Không thể xác minh chữ ký manifest: {exc}"
