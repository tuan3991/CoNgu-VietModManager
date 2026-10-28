# -*- coding: utf-8 -*-
"""
Theme Manager - Safe Installer
==============================

Cài đặt gói theme cộng đồng ``.congu_theme`` (thực chất là file ZIP) với đầy đủ
lớp bảo vệ:

* Chống **Zip Slip / Path Traversal** cho từng member (absolute, ``..``, ổ đĩa
  ``C:``, UNC ``\\\\server``, symlink path, ADS ``file.txt:evil``).
* Whitelist phần mở rộng file — mọi file lạ (``.html``, ``.js``, ``.exe``,
  ``.bat``, ``.vbs``, ``.svg``, ``.php``, ``.py``...) bị bỏ qua kèm cảnh báo.
* Giới hạn 400 file, 80 MB tổng, 25 MB/file (kiểm tra cả khai báo lẫn lúc
  stream để chống zip bomb).
* Giải nén **file-by-file** bằng luồng nhị phân (không dùng ``extractall``),
  ghi vào thư mục tạm ``<themes_root>/.tmp_<random>`` rồi ``os.replace``.
* Sanitize toàn bộ ``.css`` sau khi giải nén (xem :func:`sanitize_css`).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from .manifest import (
    ManifestError,
    manifest_to_json,
    parse_manifest,
    validate_manifest,
)

# ---------------------------------------------------------------------------
# Giới hạn tài nguyên
# ---------------------------------------------------------------------------
MAX_FILES = 400
MAX_TOTAL_UNCOMPRESSED = 80 * 1024 * 1024       # 80 MB
MAX_SINGLE_FILE = 25 * 1024 * 1024              # 25 MB
MAX_MANIFEST_BYTES = 2 * 1024 * 1024            # 2 MB (manifest phải nhỏ)
CHUNK_SIZE = 64 * 1024

#: Chỉ các phần mở rộng này được phép ghi ra đĩa.
ALLOWED_EXTENSIONS = frozenset(
    {
        ".json", ".css",
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".woff", ".woff2", ".ttf", ".otf",
        ".mp3", ".ogg",
    }
)

#: ID của theme builtin — không bao giờ cho gói cộng đồng ghi đè/ẩn theme này.
RESERVED_THEME_IDS = frozenset({"cyberpunk_default"})

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_URL_RE = re.compile(
    r"""url\(\s*(?P<quote>['"]?)(?P<target>.*?)(?P=quote)\s*\)""",
    re.IGNORECASE | re.DOTALL,
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:")
_IMPORT_RE = re.compile(r"@import\b[^;{}]*(?:;|$)", re.IGNORECASE | re.MULTILINE)


class ThemeInstallError(Exception):
    """Lỗi trong quá trình cài đặt theme."""


# ---------------------------------------------------------------------------
# CSS sanitizer
# ---------------------------------------------------------------------------
def _clean_url(match: "re.Match[str]") -> str:
    """Giữ URL nội bộ/data URI, xóa URL trỏ ra ngoài hoặc có dấu hiệu traversal."""
    target = (match.group("target") or "").strip()
    lowered = target.lower()

    # data: URI được phép (nhúng ảnh/font trực tiếp).
    if lowered.startswith("data:"):
        return match.group(0)

    # URL rỗng coi như không hợp lệ.
    if not target:
        return ""

    # URL tuyệt đối có scheme (http:, https:, ftp:, file:, javascript:...) hoặc
    # protocol-relative //cdn... -> xóa.
    if lowered.startswith("//") or _SCHEME_RE.match(lowered):
        return ""

    normalized = target.replace("\\", "/")
    if normalized.startswith("/") or "\\" in target:
        return ""
    if any(part == ".." for part in normalized.split("/")):
        return ""

    # URL tương đối tới file cục bộ trong theme -> giữ nguyên.
    return match.group(0)


def sanitize_css(css_text: str) -> str:
    """
    Lọc CSS nguy hiểm trước khi phục vụ cho trình duyệt.

    * Xóa toàn bộ ``@import ...;``.
    * Xóa ``url(...)`` trỏ ra ngoài (``http(s)://``, ``//``, scheme lạ, đường dẫn
      tuyệt đối, ``..``); giữ ``url(data:...)`` và ``url("file-cuc-bo.png")``.
    * Xóa ``expression(``, ``javascript:``, ``-moz-binding``, ``behavior:``.
    """
    if css_text is None:
        return ""
    if isinstance(css_text, (bytes, bytearray)):
        css = bytes(css_text).decode("utf-8-sig", "replace")
    else:
        css = str(css_text)

    # 1) Xóa @import (kể cả @import url("..."); )
    css = _IMPORT_RE.sub("", css)

    # 2) Xóa URL trỏ ra ngoài.
    css = _URL_RE.sub(_clean_url, css)

    # 3) Xóa các construct thực thi / binding nguy hiểm.
    css = re.sub(r"expression\s*\(", "", css, flags=re.IGNORECASE)
    css = re.sub(r"javascript\s*:", "", css, flags=re.IGNORECASE)
    css = re.sub(r"-moz-binding", "", css, flags=re.IGNORECASE)
    css = re.sub(r"behavior\s*:", "", css, flags=re.IGNORECASE)

    # 4) Lớp bảo hiểm cuối: không bao giờ để @import sót lại.
    css = re.sub(r"@import", "", css, flags=re.IGNORECASE)

    return css


# ---------------------------------------------------------------------------
# Helpers đường dẫn
# ---------------------------------------------------------------------------
def _normalize_member_name(name: str) -> Optional[str]:
    """
    Chuẩn hóa tên member ZIP về dạng posix tương đối.

    Trả ``None`` nếu tên có dấu hiệu Zip Slip / không an toàn.
    """
    if not isinstance(name, str) or not name or "\x00" in name:
        return None

    raw = name.replace("\\", "/")

    # UNC hoặc absolute posix.
    if raw.startswith("//") or raw.startswith("/"):
        return None
    # Ổ đĩa Windows C:\...
    if _DRIVE_RE.match(raw):
        return None

    parts = raw.split("/")
    if any(part == ".." for part in parts):
        return None
    # Chặn Alternate Data Streams trên Windows (file.txt:evil).
    if any(":" in part for part in parts):
        return None

    normalized = posixpath.normpath(raw)
    if normalized in ("", ".", ".."):
        return None
    if normalized.startswith("../") or normalized.startswith("/"):
        return None
    return normalized


def _safe_join(root: str, relative: str) -> str:
    """Join + xác thực đường dẫn thật vẫn nằm trong ``root``."""
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, *relative.split("/")))
    try:
        common = os.path.commonpath([os.path.normcase(root_real),
                                     os.path.normcase(target)])
    except ValueError as exc:  # khác ổ đĩa
        raise ThemeInstallError(
            f"Đường dẫn '{relative}' nằm ngoài thư mục theme (cross-drive)."
        ) from exc
    if common != os.path.normcase(root_real) or target == root_real:
        raise ThemeInstallError(
            f"Đường dẫn '{relative}' nằm ngoài thư mục theme — từ chối cài đặt."
        )
    return target


MAX_THEME_ID_LEN = 40


def _unique_destination(themes_root: str, theme_id: str) -> Tuple[str, str]:
    """
    Tìm thư mục đích chưa tồn tại: ``<id>``, ``<id>_2``, ``<id>_3``...

    Theme builtin (``cyberpunk_default``) là reserved: gói cộng đồng trùng ID
    luôn được cài thành ``<id>_2`` để không che khuất theme mặc định.
    Giữ id cuối cùng vẫn hợp lệ (<= 40 ký tự).
    """
    counter = 2 if theme_id in RESERVED_THEME_IDS else 1
    suffix = f"_{counter}" if counter > 1 else ""
    while True:
        # Cắt bớt phần gốc để id sau khi thêm hậu tố vẫn <= 40 ký tự.
        base = theme_id[: MAX_THEME_ID_LEN - len(suffix)] if suffix else theme_id
        candidate_id = f"{base}{suffix}"
        destination = os.path.join(themes_root, candidate_id)
        if not os.path.exists(destination):
            return destination, candidate_id
        counter += 1
        suffix = f"_{counter}"
        if counter > 1000:
            raise ThemeInstallError(
                "Không thể tạo thư mục theme duy nhất (đã thử 1000 lần)."
            )


def _cleanup(path: Optional[str]) -> None:
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _failure(message: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "success": False,
        "theme_id": "",
        "name": "",
        "warnings": list(warnings or []),
        "message": message,
        "sanitized": False,
    }


# ---------------------------------------------------------------------------
# Cài đặt
# ---------------------------------------------------------------------------
def install_theme_zip(zip_path: str, themes_root: str) -> Dict[str, Any]:
    """
    Cài gói theme ``.congu_theme`` vào ``themes_root``.

    Returns:
        ``{"success": bool, "theme_id": str, "name": str,
        "warnings": list[str], "message": str, "sanitized": bool}``
    """
    warnings: List[str] = []

    if not isinstance(zip_path, str) or not zip_path.strip():
        return _failure("Thiếu đường dẫn file .congu_theme.")
    if not isinstance(themes_root, str) or not themes_root.strip():
        return _failure("Thiếu thư mục cài đặt theme.")

    source = os.path.abspath(os.path.expanduser(zip_path.strip()))
    root = os.path.abspath(os.path.expanduser(themes_root.strip()))

    if not os.path.isfile(source):
        return _failure(f"Không tìm thấy file theme: {source}")
    if os.path.exists(root) and not os.path.isdir(root):
        return _failure(f"Đường dẫn cài đặt không phải thư mục: {root}")

    try:
        os.makedirs(root, exist_ok=True)
    except OSError as exc:
        return _failure(f"Không thể tạo thư mục theme: {exc}")

    try:
        archive = zipfile.ZipFile(source, "r")
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return _failure(f"File .congu_theme không phải ZIP hợp lệ: {exc}")

    temp_dir: Optional[str] = None
    try:
        with archive:
            file_infos: List[Tuple[zipfile.ZipInfo, str]] = []

            # --- Bước 1: thẩm định tên toàn bộ member --------------------
            for info in archive.infolist():
                if info.is_dir() or info.filename.endswith(("/", "\\")):
                    continue
                relative = _normalize_member_name(info.filename)
                if relative is None:
                    return _failure(
                        "Phát hiện đường dẫn không an toàn trong gói theme "
                        f"(Zip Slip/Path Traversal): {info.filename!r}. "
                        "Đã hủy cài đặt."
                    )
                file_infos.append((info, relative))

            # --- Bước 2: tìm theme.json ở gốc hoặc đúng 1 thư mục con ---
            manifest_candidates: List[Tuple[zipfile.ZipInfo, str, str]] = []
            for info, relative in file_infos:
                if posixpath.basename(relative).lower() != "theme.json":
                    continue
                depth = relative.count("/")
                if depth > 1:
                    warnings.append(
                        f"Bỏ qua theme.json lồng quá sâu (chỉ hỗ trợ gốc hoặc 1 "
                        f"thư mục con): {relative}"
                    )
                    continue
                prefix = relative[: -len("theme.json")].rstrip("/")
                manifest_candidates.append((info, relative, prefix))

            if not manifest_candidates:
                return _failure(
                    "Không tìm thấy theme.json ở gốc gói hoặc trong một thư mục "
                    "con duy nhất.",
                    warnings,
                )

            prefixes = {prefix for _, _, prefix in manifest_candidates}
            if len(prefixes) > 1:
                return _failure(
                    "Gói theme chứa nhiều theme.json ở các thư mục gốc khác nhau "
                    "— không xác định được theme cần cài.",
                    warnings,
                )

            manifest_info, manifest_rel, prefix = manifest_candidates[0]

            # --- Bước 3: đọc & kiểm duyệt manifest ------------------------
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                return _failure("theme.json quá lớn (giới hạn 2 MB).", warnings)
            if manifest_info.flag_bits & 0x1:
                return _failure("Gói theme được mã hóa mật khẩu — từ chối cài đặt.")

            try:
                raw_manifest = archive.read(manifest_info)
                manifest = parse_manifest(raw_manifest)
            except (ManifestError, RuntimeError, zipfile.BadZipFile) as exc:
                return _failure(f"theme.json không hợp lệ: {exc}", warnings)

            ok, error_message = validate_manifest(manifest)
            if not ok:
                return _failure(f"theme.json không hợp lệ: {error_message}", warnings)
            warnings.extend(manifest.get("warnings", []))

            # --- Bước 4: lập kế hoạch giải nén (whitelist + giới hạn) -----
            plan: List[Tuple[zipfile.ZipInfo, str]] = []
            seen_targets: set[str] = set()
            total_declared = 0
            for info, relative in file_infos:
                if info.flag_bits & 0x1:
                    return _failure(
                        f"File '{relative}' trong gói được mã hóa — từ chối cài đặt.",
                        warnings,
                    )

                if prefix:
                    if relative == prefix:
                        continue
                    if not relative.startswith(prefix + "/"):
                        warnings.append(
                            f"Bỏ qua file nằm ngoài thư mục theme '{prefix}': "
                            f"{relative}"
                        )
                        continue
                    sub_path = relative[len(prefix) + 1:]
                else:
                    sub_path = relative

                if not sub_path:
                    continue

                extension = posixpath.splitext(sub_path)[1].lower()
                if extension not in ALLOWED_EXTENSIONS:
                    warnings.append(
                        f"Bỏ qua file không được phép (whitelist): {relative}"
                    )
                    continue

                if info.file_size > MAX_SINGLE_FILE:
                    return _failure(
                        f"File '{relative}' vượt quá 25 MB — đã hủy cài đặt.",
                        warnings,
                    )

                key = sub_path.lower()
                if key in seen_targets:
                    return _failure(
                        f"Gói theme chứa file trùng tên: {relative}", warnings
                    )
                seen_targets.add(key)

                total_declared += info.file_size
                if total_declared > MAX_TOTAL_UNCOMPRESSED:
                    return _failure(
                        "Tổng dung lượng giải nén vượt quá 80 MB — đã hủy cài đặt.",
                        warnings,
                    )

                plan.append((info, sub_path))

            if len(plan) > MAX_FILES:
                return _failure(
                    f"Gói theme có quá nhiều file ({len(plan)} > {MAX_FILES}) — "
                    "đã hủy cài đặt.",
                    warnings,
                )

            # --- Bước 5: giải nén file-by-file vào thư mục tạm -----------
            try:
                temp_dir = tempfile.mkdtemp(prefix=".tmp_", dir=root)
            except OSError as exc:
                return _failure(f"Không thể tạo thư mục tạm để cài theme: {exc}")

            total_written = 0
            try:
                for info, sub_path in plan:
                    # theme.json được ghi lại dưới dạng manifest đã chuẩn hóa.
                    if sub_path.lower() == "theme.json":
                        continue

                    target = _safe_join(temp_dir, sub_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)

                    written = 0
                    with archive.open(info, "r") as source_stream, open(
                        target, "wb"
                    ) as destination_stream:
                        while True:
                            chunk = source_stream.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            total_written += len(chunk)
                            if written > MAX_SINGLE_FILE:
                                raise ThemeInstallError(
                                    f"File '{sub_path}' vượt quá 25 MB khi giải nén."
                                )
                            if total_written > MAX_TOTAL_UNCOMPRESSED:
                                raise ThemeInstallError(
                                    "Tổng dung lượng giải nén vượt quá 80 MB."
                                )
                            destination_stream.write(chunk)

                # --- Bước 6: dọn assets trỏ tới file không tồn tại ----------
                assets = dict(manifest.get("assets") or {})
                for asset_key in ("background_image", "custom_css"):
                    relative_asset = assets.get(asset_key)
                    if not relative_asset:
                        continue
                    try:
                        asset_target = _safe_join(temp_dir, relative_asset)
                    except ThemeInstallError:
                        warnings.append(
                            f"Bỏ asset '{asset_key}' vì đường dẫn không an toàn."
                        )
                        assets.pop(asset_key, None)
                        continue
                    if not os.path.isfile(asset_target):
                        warnings.append(
                            f"Bỏ asset '{asset_key}': thiếu file '{relative_asset}'."
                        )
                        assets.pop(asset_key, None)
                manifest["assets"] = assets

                # --- Bước 7: sanitize toàn bộ CSS ---------------------------
                sanitized_any = False
                for directory, _dirs, filenames in os.walk(temp_dir):
                    for filename in filenames:
                        if not filename.lower().endswith(".css"):
                            continue
                        css_path = os.path.join(directory, filename)
                        try:
                            with open(css_path, "r", encoding="utf-8-sig",
                                      errors="replace") as handle:
                                original_css = handle.read()
                        except OSError as exc:
                            warnings.append(
                                f"Không đọc được CSS '{filename}': {exc}"
                            )
                            continue

                        clean_css = sanitize_css(original_css)
                        if clean_css != original_css:
                            sanitized_any = True
                            with open(css_path, "w", encoding="utf-8",
                                      newline="") as handle:
                                handle.write(clean_css)

                # --- Bước 8: chọn thư mục đích duy nhất --------------------
                theme_id = manifest["id"]
                destination, final_id = _unique_destination(root, theme_id)

                if final_id != theme_id:
                    manifest["id"] = final_id
                    warnings.append(
                        f"ID '{theme_id}' đã tồn tại — theme được cài với ID "
                        f"'{final_id}'."
                    )

                # Ghi manifest đã chuẩn hóa (bỏ warnings nội bộ).
                with open(os.path.join(temp_dir, "theme.json"), "w",
                          encoding="utf-8", newline="") as handle:
                    handle.write(manifest_to_json(manifest))

                # --- Bước 9: chuyển thư mục tạm sang đích ------------------
                try:
                    os.replace(temp_dir, destination)
                except OSError as exc:
                    raise ThemeInstallError(
                        f"Không thể hoàn tất cài theme: {exc}"
                    ) from exc
                temp_dir = None  # đã chuyển, không cleanup nữa.

                installed_name = manifest.get("name", "")
                if sanitized_any:
                    warnings.append(
                        "Đã tự động lọc CSS nguy hiểm (import/url ngoài/expression)."
                    )

                return {
                    "success": True,
                    "theme_id": final_id,
                    "name": installed_name,
                    "warnings": warnings,
                    "message": f"Đã cài theme '{installed_name}' thành công.",
                    "sanitized": sanitized_any,
                }

            except ThemeInstallError as exc:
                return _failure(str(exc), warnings)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                return _failure(f"Lỗi khi giải nén theme: {exc}", warnings)

    except ThemeInstallError as exc:
        return _failure(str(exc), warnings)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return _failure(f"Không thể đọc gói theme: {exc}", warnings)
    finally:
        _cleanup(temp_dir)


__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_FILES",
    "MAX_SINGLE_FILE",
    "MAX_TOTAL_UNCOMPRESSED",
    "ThemeInstallError",
    "install_theme_zip",
    "sanitize_css",
]
