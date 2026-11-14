#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ghi SHA-256 ZIP Portable vào version.json trước khi tạo GitHub Release.

Chạy sau khi build ZIP, trước khi commit/push metadata:
    python tools/update_release_checksum.py path/to/CoNgu_vX.Y.Z_Portable.zip --version-file version.json

Mặc định chỉ in digest. Thêm --write để cập nhật atomically key
``portable_zip_sha256``. Tool từ chối ghi nếu URL metadata không kết thúc cùng
tên ZIP, tránh vô tình gắn hash artifact sai vào release.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_checksum(zip_path: str, version_file: str, write: bool = False) -> tuple[str, dict]:
    archive = Path(zip_path).resolve()
    metadata_path = Path(version_file).resolve()
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise ValueError(f"ZIP release không hợp lệ: {archive}")
    with metadata_path.open("r", encoding="utf-8") as source:
        metadata = json.load(source)
    if not isinstance(metadata, dict):
        raise ValueError("version.json phải là object JSON")
    release_url = str(metadata.get("portable_zip_url") or "").split("?", 1)[0].rstrip("/")
    if not release_url or os.path.basename(release_url) != archive.name:
        raise ValueError("Tên ZIP không khớp portable_zip_url trong version.json")
    digest = sha256_file(archive)
    if write:
        metadata["portable_zip_sha256"] = digest
        fd, temporary = tempfile.mkstemp(prefix=".version-", suffix=".json", dir=str(metadata_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                json.dump(metadata, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, metadata_path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    return digest, metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tính/gắn SHA-256 cho Portable ZIP release")
    parser.add_argument("zip_path")
    parser.add_argument("--version-file", default="version.json")
    parser.add_argument("--write", action="store_true", help="Ghi portable_zip_sha256 vào metadata")
    args = parser.parse_args(argv)
    try:
        digest, _ = update_checksum(args.zip_path, args.version_file, args.write)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
