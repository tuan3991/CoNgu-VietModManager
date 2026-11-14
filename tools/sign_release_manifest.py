# -*- coding: utf-8 -*-
"""Ký manifest phát hành bằng Ed25519.

Ví dụ:
    python tools/sign_release_manifest.py version.json --key %USERPROFILE%\\.congu-release\\ed25519_private.pem

Khóa tư nhân phải nằm ngoài repository; tool từ chối ký nếu phát hiện khóa trong repo.
"""
import argparse
import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.update_manifest import canonical_manifest_payload
from cryptography.hazmat.primitives import serialization


def sign_manifest(manifest_path: str, key_path: str) -> str:
    manifest_file = Path(manifest_path).resolve()
    key_file = Path(key_path).resolve()
    if key_file == ROOT or ROOT in key_file.parents:
        raise SystemExit("Khóa ký phải nằm ngoài repository; đã từ chối.")
    if not manifest_file.is_file():
        raise SystemExit(f"Không tìm thấy manifest: {manifest_file}")
    if not key_file.is_file():
        raise SystemExit(f"Không tìm thấy khóa ký: {key_file}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    sha = str(manifest.get("portable_zip_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit("portable_zip_sha256 phải là SHA-256 64 ký tự trước khi ký.")
    if not str(manifest.get("portable_zip_url") or "").lower().endswith(".zip"):
        raise SystemExit("portable_zip_url phải trỏ tới gói .zip trước khi ký.")
    if not str(manifest.get("version") or "").strip():
        raise SystemExit("Manifest thiếu trường version.")

    private_key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    signature = private_key.sign(canonical_manifest_payload(manifest))
    manifest["manifest_signature"] = base64.b64encode(signature).decode("ascii")

    fd, temp_path = tempfile.mkstemp(prefix=".version-sign-", suffix=".json", dir=str(manifest_file.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(manifest, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(temp_path, manifest_file)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return manifest["manifest_signature"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ký manifest phát hành Cổ Ngữ bằng Ed25519.")
    parser.add_argument("manifest", help="Đường dẫn version.json cần ký")
    parser.add_argument("--key", required=True, help="Khóa tư nhân PEM nằm ngoài repository")
    args = parser.parse_args(argv)
    signature = sign_manifest(args.manifest, args.key)
    print(f"Đã ký {args.manifest}")
    print(f"manifest_signature: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
