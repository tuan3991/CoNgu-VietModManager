# -*- coding: utf-8 -*-
"""
Theme Manager - Service Layer
=============================

Điều phối toàn bộ vòng đời theme cho ứng dụng Cổ Ngữ:

* Liệt kê / đọc theme builtin + theme người dùng.
* Đọc & đổi theme đang kích hoạt (``active_theme`` trong ``user_config.json``).
* Xóa theme người dùng (không xóa builtin / theme đang dùng).
* Xuất / nhập gói theme cộng đồng ``.congu_theme``.
* Tạo hoặc cập nhật theme từ Theme Studio.
* Phục vụ file asset & CSS an toàn cho route Bottle.

Mọi thao tác với đường dẫn đều đi qua :func:`security.validate_safe_path` để
chống Path Traversal.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from security import PathTraversalError, validate_safe_path

from core.config_manager import (
    APPDATA_DIR,
    APP_DIR,
    load_user_config,
    save_user_config,
)

from .installer import (
    ALLOWED_EXTENSIONS,
    MAX_SINGLE_FILE,
    sanitize_css,
)
from .manifest import (
    ID_RE,
    ManifestError,
    manifest_to_json,
    normalize_manifest,
    parse_manifest,
    validate_manifest,
)

DEFAULT_THEME_ID = "cyberpunk_default"

#: Thư mục theme builtin (đi kèm ứng dụng).
_BUILTIN_THEME_NAME = DEFAULT_THEME_ID


def _log(message: str) -> None:
    """Log không được làm sập ứng dụng khi console Windows dùng cp1252."""
    try:
        print(message)
    except UnicodeEncodeError:
        try:
            sys.stdout.write(message.encode("ascii", "replace").decode("ascii") + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Đường dẫn gốc
# ---------------------------------------------------------------------------
def get_themes_root() -> str:
    """Trả ``%APPDATA%/VietModHub/themes`` và bảo đảm thư mục tồn tại."""
    root = os.path.join(APPDATA_DIR, "themes")
    os.makedirs(root, exist_ok=True)
    return root


def get_builtin_theme_dir() -> str:
    """Trả thư mục theme mặc định ``<APP_DIR>/static/themes/cyberpunk_default``."""
    return os.path.join(APP_DIR, "static", "themes", _BUILTIN_THEME_NAME)


# ---------------------------------------------------------------------------
# Helpers nội bộ
# ---------------------------------------------------------------------------
def _clean_theme_id(theme_id: Any) -> Optional[str]:
    if not isinstance(theme_id, str):
        return None
    value = theme_id.strip()
    if not ID_RE.fullmatch(value):
        return None
    return value


def _load_manifest_from_dir(dir_path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Đọc + kiểm duyệt ``theme.json`` trong một thư mục theme."""
    manifest_path = os.path.join(dir_path, "theme.json")
    try:
        with open(manifest_path, "rb") as handle:
            raw = handle.read()
        data = parse_manifest(raw)
        ok, error_message = validate_manifest(data)
        if not ok:
            return None, error_message
        return data, ""
    except (OSError, ManifestError) as exc:
        return None, str(exc)


def _iter_theme_dirs() -> List[Tuple[str, bool]]:
    """Trả danh sách ``(thư mục, là_builtin)``: builtin trước, user sau."""
    entries: List[Tuple[str, bool]] = []

    builtin = get_builtin_theme_dir()
    if os.path.isdir(builtin):
        entries.append((builtin, True))

    try:
        root = get_themes_root()
        names = sorted(os.listdir(root))
    except OSError:
        names = []

    for name in names:
        if name.startswith("."):
            continue
        directory = os.path.join(root, name)
        if not os.path.isdir(directory):
            continue
        if not os.path.isfile(os.path.join(directory, "theme.json")):
            continue
        entries.append((directory, False))

    return entries


def _scan_user_theme_by_manifest_id(theme_id: str) -> Optional[str]:
    """
    Fallback: tìm thư mục user theme có ``id`` trong manifest khớp (phòng khi
    thư mục bị đổi tên thủ công).
    """
    try:
        root = get_themes_root()
        names = os.listdir(root)
    except OSError:
        return None

    for name in names:
        if name.startswith("."):
            continue
        directory = os.path.join(root, name)
        if not os.path.isdir(directory):
            continue
        manifest_path = os.path.join(directory, "theme.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and str(data.get("id", "")).strip() == theme_id:
                safe = validate_safe_path(root, name)
                return safe
        except (OSError, ValueError, PathTraversalError, json.JSONDecodeError):
            continue
    return None


def _find_theme_dir(theme_id: Any) -> Optional[Tuple[str, bool]]:
    """Tìm thư mục theme theo id. Trả ``(thư mục, là_builtin)`` hoặc ``None``."""
    clean_id = _clean_theme_id(theme_id)
    if not clean_id:
        return None

    builtin = get_builtin_theme_dir()
    if clean_id == _BUILTIN_THEME_NAME and os.path.isdir(builtin):
        return os.path.realpath(builtin), True

    root = get_themes_root()
    candidate = os.path.join(root, clean_id)
    if os.path.isdir(candidate) and os.path.isfile(
        os.path.join(candidate, "theme.json")
    ):
        try:
            safe = validate_safe_path(root, clean_id)
        except (PathTraversalError, ValueError):
            return None
        return safe, False

    fallback = _scan_user_theme_by_manifest_id(clean_id)
    if fallback:
        return fallback, False
    return None


def _asset_exists(theme_dir: str, relative: str) -> bool:
    if not isinstance(relative, str) or not relative.strip():
        return False
    try:
        target = validate_safe_path(theme_dir, relative.strip())
    except (PathTraversalError, ValueError):
        return False
    return os.path.isfile(target)


def _build_preview_url(theme_id: str, background_rel: Optional[str]) -> Optional[str]:
    if not background_rel:
        return None
    encoded_id = quote(theme_id, safe="")
    encoded_path = quote(background_rel.replace("\\", "/"), safe="/")
    return f"/api/themes/{encoded_id}/assets/{encoded_path}"


def _theme_summary(
    theme_dir: str, builtin: bool, data: Dict[str, Any]
) -> Dict[str, Any]:
    theme_id = str(data.get("id", ""))
    assets = data.get("assets") or {}
    background_rel = assets.get("background_image")
    custom_css_rel = assets.get("custom_css")

    has_background = bool(background_rel) and _asset_exists(
        theme_dir, background_rel
    )
    has_custom_css = bool(custom_css_rel) and _asset_exists(
        theme_dir, custom_css_rel
    )
    if not has_custom_css:
        has_custom_css = os.path.isfile(os.path.join(theme_dir, "custom.css"))

    return {
        "id": theme_id,
        "name": data.get("name", ""),
        "author": data.get("author", ""),
        "version": data.get("version", ""),
        "description": data.get("description", ""),
        "builtin": bool(builtin),
        "has_custom_css": bool(has_custom_css),
        "has_background": bool(has_background),
        "preview_url": _build_preview_url(theme_id, background_rel),
        "warnings": list(data.get("warnings") or []),
    }


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


def _write_manifest_atomic(theme_dir: str, manifest: Dict[str, Any]) -> None:
    """Ghi ``theme.json`` qua file tạm cùng thư mục rồi ``os.replace``."""
    os.makedirs(theme_dir, exist_ok=True)
    target = os.path.join(theme_dir, "theme.json")
    temp_path = os.path.join(theme_dir, f".theme_{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(manifest_to_json(manifest))
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _failure(message: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "success": False,
        "theme_id": "",
        "name": "",
        "warnings": list(warnings or []),
        "message": message,
    }


# ---------------------------------------------------------------------------
# Danh sách & chi tiết theme
# ---------------------------------------------------------------------------
def list_themes() -> List[Dict[str, Any]]:
    """
    Liệt kê theme builtin + theme người dùng.

    Mỗi item gồm: ``id, name, author, version, description, builtin,
    has_custom_css, has_background, preview_url, warnings``.
    """
    themes: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for theme_dir, builtin in _iter_theme_dirs():
        data, error_message = _load_manifest_from_dir(theme_dir)
        if not data:
            # Theme hỏng bị bỏ qua; ưu tiên không làm sập toàn bộ danh sách.
            _log(f"[ThemeManager] Bỏ qua theme lỗi tại '{theme_dir}': {error_message}")
            continue

        theme_id = str(data.get("id", ""))
        if not theme_id or theme_id in seen:
            continue
        seen.add(theme_id)
        themes.append(_theme_summary(theme_dir, builtin, data))

    return themes


def get_theme(theme_id: str) -> Optional[Dict[str, Any]]:
    """Trả manifest đầy đủ (đã sanitize) của theme, hoặc ``None``."""
    found = _find_theme_dir(theme_id)
    if not found:
        return None

    theme_dir, builtin = found
    data, error_message = _load_manifest_from_dir(theme_dir)
    if not data:
        _log(f"[ThemeManager] Không đọc được theme '{theme_id}': {error_message}")
        return None

    summary = _theme_summary(theme_dir, builtin, data)
    return {
        "id": data.get("id", ""),
        "name": data.get("name", ""),
        "author": data.get("author", ""),
        "version": data.get("version", ""),
        "description": data.get("description", ""),
        "variables": dict(data.get("variables") or {}),
        "assets": dict(data.get("assets") or {}),
        "builtin": builtin,
        "has_custom_css": summary["has_custom_css"],
        "has_background": summary["has_background"],
        "preview_url": summary["preview_url"],
        "warnings": summary["warnings"],
    }


# ---------------------------------------------------------------------------
# Theme đang kích hoạt
# ---------------------------------------------------------------------------
def get_active_theme() -> str:
    """Đọc ``active_theme`` từ ``user_config.json``; fallback theme mặc định."""
    try:
        config = load_user_config()
        active = config.get("active_theme")
        if isinstance(active, str):
            clean = active.strip()
            if clean and _find_theme_dir(clean):
                return clean
    except Exception as exc:  # pragma: no cover - phòng lỗi I/O
        _log(f"[ThemeManager] Không đọc được active_theme: {exc}")
    return DEFAULT_THEME_ID


def set_active_theme(theme_id: str) -> Dict[str, Any]:
    """Đặt theme đang dùng. Trả ``{"success", "theme_id", "active_theme", "message"}``."""
    clean_id = _clean_theme_id(theme_id)
    if not clean_id or not _find_theme_dir(clean_id):
        return {
            "success": False,
            "theme_id": clean_id or "",
            "active_theme": get_active_theme(),
            "message": f"Không tìm thấy theme '{theme_id}'.",
        }

    try:
        config = load_user_config()
        config["active_theme"] = clean_id
        if not save_user_config(config):
            return {
                "success": False,
                "theme_id": clean_id,
                "active_theme": get_active_theme(),
                "message": "Không thể lưu cấu hình theme.",
            }
    except Exception as exc:
        return {
            "success": False,
            "theme_id": clean_id,
            "active_theme": get_active_theme(),
            "message": f"Lỗi khi lưu theme: {exc}",
        }

    return {
        "success": True,
        "theme_id": clean_id,
        "active_theme": clean_id,
        "message": f"Đã áp dụng theme '{clean_id}'.",
    }


# ---------------------------------------------------------------------------
# Xóa theme
# ---------------------------------------------------------------------------
def delete_theme(theme_id: str) -> Dict[str, Any]:
    """Xóa theme người dùng (từ chối builtin hoặc theme đang kích hoạt)."""
    clean_id = _clean_theme_id(theme_id)
    if not clean_id:
        return _failure("ID theme không hợp lệ.")

    found = _find_theme_dir(clean_id)
    if not found:
        return _failure(f"Không tìm thấy theme '{clean_id}'.")

    theme_dir, builtin = found
    if builtin:
        return _failure("Không thể xóa theme mặc định của ứng dụng.")

    if get_active_theme() == clean_id:
        return _failure(
            "Không thể xóa theme đang được sử dụng. Hãy chuyển sang theme khác trước."
        )

    root = get_themes_root()
    try:
        safe_dir = validate_safe_path(root, theme_dir)
    except (PathTraversalError, ValueError) as exc:
        return _failure(f"Đường dẫn theme không an toàn: {exc}")

    if os.path.normcase(os.path.realpath(safe_dir)) == os.path.normcase(
        os.path.realpath(root)
    ):
        return _failure("Không thể xóa thư mục gốc của theme.")

    try:
        shutil.rmtree(safe_dir)
    except OSError as exc:
        return _failure(f"Không thể xóa theme: {exc}")

    return {
        "success": True,
        "theme_id": clean_id,
        "message": f"Đã xóa theme '{clean_id}'.",
    }


# ---------------------------------------------------------------------------
# Xuất theme
# ---------------------------------------------------------------------------
def export_theme(theme_id: str, dest_zip_path: str) -> Dict[str, Any]:
    """
    Đóng gói theme thành file ``.congu_theme`` (ZIP) để chia sẻ cộng đồng.

    Gói gồm ``theme.json`` (đã chuẩn hóa) + toàn bộ file asset/CSS đi kèm.
    CSS được sanitize lại một lần nữa trước khi ghi vào ZIP.
    """
    clean_id = _clean_theme_id(theme_id)
    if not clean_id:
        return _failure("ID theme không hợp lệ.")

    found = _find_theme_dir(clean_id)
    if not found:
        return _failure(f"Không tìm thấy theme '{clean_id}'.")
    theme_dir, _builtin = found

    data, error_message = _load_manifest_from_dir(theme_dir)
    if not data:
        return _failure(f"Không đọc được theme.json: {error_message}")

    if not isinstance(dest_zip_path, str) or not dest_zip_path.strip():
        return _failure("Thiếu đường dẫn file ZIP cần xuất.")

    destination = os.path.abspath(os.path.expanduser(dest_zip_path.strip()))
    if os.path.isdir(destination):
        return _failure("Đường dẫn xuất phải là một file ZIP, không phải thư mục.")

    parent = os.path.dirname(destination)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return _failure(f"Không thể tạo thư mục chứa file xuất: {exc}")

    temp_zip = f"{destination}.{uuid.uuid4().hex}.part"
    exported_files = 0
    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("theme.json", manifest_to_json(data))
            exported_files += 1

            for directory, _dirs, filenames in os.walk(theme_dir):
                for filename in filenames:
                    absolute = os.path.join(directory, filename)
                    if not os.path.isfile(absolute):
                        continue
                    relative = os.path.relpath(absolute, theme_dir).replace(
                        os.sep, "/"
                    )
                    if relative == "theme.json":
                        continue
                    # Không đóng gói file tạm nội bộ.
                    if filename.startswith(".theme_") and filename.endswith(".tmp"):
                        continue

                    if filename.lower().endswith(".css"):
                        archive.writestr(relative, sanitize_css(_read_text(absolute)))
                    else:
                        archive.write(absolute, relative)
                    exported_files += 1

        os.replace(temp_zip, destination)
        temp_zip = ""

        return {
            "success": True,
            "theme_id": clean_id,
            "path": destination,
            "files": exported_files,
            "message": f"Đã xuất theme '{clean_id}' ra '{destination}'.",
        }
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return _failure(f"Không thể xuất theme: {exc}")
    finally:
        if temp_zip and os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Theme Studio
# ---------------------------------------------------------------------------
def build_theme_from_values(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tạo / cập nhật theme từ dữ liệu Theme Studio.

    Payload hỗ trợ::

        {
            "id": "my_theme",              # tùy chọn, tự sinh từ name nếu thiếu
            "name": "My Theme",
            "author": "...",               # tùy chọn
            "version": "1.0",              # tùy chọn
            "description": "...",          # tùy chọn
            "variables": {"--bg-primary": "#090d16", ...},
            "background_image_path": r"C:\\...\\bg.png"   # tùy chọn
        }

    Ảnh nền được copy vào thư mục theme và khai báo trong ``assets``.
    """
    if not isinstance(payload, dict):
        return _failure("Dữ liệu theme không hợp lệ (phải là object).")

    # Xác định theme hiện có (nếu đang cập nhật).
    requested_id = payload.get("id")
    existing_dir: Optional[str] = None
    if isinstance(requested_id, str) and requested_id.strip():
        found = _find_theme_dir(requested_id.strip())
        if found:
            if found[1]:
                return _failure(
                    "Không thể chỉnh sửa theme mặc định. Hãy tạo theme mới với ID khác."
                )
            existing_dir = found[0]

    old_data: Dict[str, Any] = {}
    if existing_dir:
        loaded, _error = _load_manifest_from_dir(existing_dir)
        if loaded:
            old_data = loaded

    name = payload.get("name", old_data.get("name", ""))
    if not isinstance(name, str):
        name = str(name) if name is not None else ""
    name = name.strip()
    if not name:
        return _failure("Tên theme không được để trống.")

    raw_manifest: Dict[str, Any] = {
        "id": requested_id if isinstance(requested_id, str) else "",
        "name": name,
        "author": payload.get("author", old_data.get("author", "")),
        "version": payload.get("version", old_data.get("version", "1.0")),
        "description": payload.get("description",
                                   old_data.get("description", "")),
        "variables": payload.get("variables", old_data.get("variables", {})),
        "assets": old_data.get("assets", {}),
    }

    try:
        manifest = normalize_manifest(raw_manifest)
    except ManifestError as exc:
        return _failure(f"Không thể tạo manifest: {exc}")

    ok, error_message = validate_manifest(manifest)
    if not ok:
        return _failure(f"Dữ liệu theme không hợp lệ: {error_message}")

    theme_id = str(manifest.get("id", ""))
    # Nếu id tự sinh trùng theme user đang có, chuyển sang chế độ cập nhật.
    if not existing_dir:
        found = _find_theme_dir(theme_id)
        if found:
            if found[1]:
                return _failure(
                    "ID theme trùng với theme mặc định. Vui lòng chọn ID khác."
                )
            existing_dir = found[0]
            loaded, _error = _load_manifest_from_dir(existing_dir)
            if loaded:
                # Giữ các trường cũ không được gửi lên.
                for key in ("author", "version", "description"):
                    if key not in payload:
                        manifest[key] = loaded.get(key, manifest.get(key, ""))
                if "variables" not in payload:
                    manifest["variables"] = loaded.get("variables", {})
                manifest["assets"] = loaded.get("assets", {})

    warnings: List[str] = list(manifest.get("warnings") or [])
    assets = dict(manifest.get("assets") or {})

    # Xử lý ảnh nền tùy chọn.
    background_source = payload.get(
        "background_image_path", payload.get("background_image")
    )
    new_background_rel: Optional[str] = None
    if background_source:
        if not isinstance(background_source, str) or not os.path.isfile(
            background_source
        ):
            return _failure("Không tìm thấy file ảnh nền đã chọn.")
        extension = os.path.splitext(background_source)[1].lower()
        if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return _failure(
                "Ảnh nền chỉ hỗ trợ .png/.jpg/.jpeg/.webp/.gif."
            )
        try:
            if os.path.getsize(background_source) > MAX_SINGLE_FILE:
                return _failure("Ảnh nền vượt quá 25 MB.")
        except OSError as exc:
            return _failure(f"Không đọc được ảnh nền: {exc}")
        new_background_rel = f"background{extension}"
        assets["background_image"] = new_background_rel

    manifest["assets"] = assets

    root = get_themes_root()
    try:
        target_dir = validate_safe_path(root, theme_id)
    except (PathTraversalError, ValueError) as exc:
        return _failure(f"ID theme không an toàn: {exc}")

    created_temp: Optional[str] = None
    try:
        if existing_dir:
            target_dir = existing_dir
            old_background = (
                (old_data.get("assets") or {}).get("background_image")
            )

            if new_background_rel:
                background_target = validate_safe_path(
                    target_dir, new_background_rel
                )
                shutil.copyfile(background_source, background_target)

            _write_manifest_atomic(target_dir, manifest)

            # Dọn ảnh nền cũ nếu đã thay bằng file khác.
            if (
                new_background_rel
                and old_background
                and old_background != new_background_rel
            ):
                try:
                    old_target = validate_safe_path(target_dir, old_background)
                    if os.path.isfile(old_target):
                        os.remove(old_target)
                except (OSError, PathTraversalError, ValueError):
                    pass

            message = f"Đã cập nhật theme '{theme_id}'."
        else:
            if os.path.exists(target_dir):
                return _failure(
                    f"Thư mục theme '{theme_id}' đã tồn tại nhưng không có "
                    "theme.json hợp lệ."
                )

            created_temp = tempfile.mkdtemp(prefix=".tmp_build_", dir=root)
            if new_background_rel:
                background_target = validate_safe_path(
                    created_temp, new_background_rel
                )
                shutil.copyfile(background_source, background_target)

            with open(
                os.path.join(created_temp, "theme.json"),
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write(manifest_to_json(manifest))

            os.replace(created_temp, target_dir)
            created_temp = None
            message = f"Đã tạo theme '{theme_id}'."

    except (OSError, PathTraversalError, ValueError) as exc:
        return _failure(f"Không thể lưu theme: {exc}", warnings)
    finally:
        if created_temp and os.path.isdir(created_temp):
            shutil.rmtree(created_temp, ignore_errors=True)

    return {
        "success": True,
        "theme_id": theme_id,
        "name": manifest.get("name", ""),
        "warnings": warnings,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Phục vụ asset / CSS cho route Bottle
# ---------------------------------------------------------------------------
def resolve_asset_path(theme_id: str, rel_path: str) -> str:
    """
    Trả đường dẫn tuyệt đối an toàn tới một asset trong theme.

    Raises:
        FileNotFoundError: theme/file không tồn tại.
        PathTraversalError: đường dẫn thoát ra ngoài thư mục theme.
        ValueError: định dạng file không được phép.
    """
    clean_id = _clean_theme_id(theme_id)
    if not clean_id:
        raise ValueError(f"ID theme không hợp lệ: {theme_id!r}")

    found = _find_theme_dir(clean_id)
    if not found:
        raise FileNotFoundError(f"Không tìm thấy theme '{clean_id}'.")

    theme_dir, _builtin = found

    if not isinstance(rel_path, str) or not rel_path.strip():
        raise PathTraversalError("Đường dẫn asset không được để trống.")
    relative = rel_path.strip().replace("\\", "/")
    if "\x00" in relative:
        raise PathTraversalError("Đường dẫn asset chứa ký tự không hợp lệ.")

    # Thẩm định đường dẫn TRƯỚC khi kiểm tra định dạng file để mọi hành vi
    # traversal đều bị chặn bằng PathTraversalError.
    safe_path = validate_safe_path(theme_dir, relative)

    extension = os.path.splitext(relative)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Định dạng file không được phép phục vụ: {extension or '(không có)'}"
        )

    if not os.path.isfile(safe_path):
        raise FileNotFoundError(f"Không tìm thấy asset '{relative}'.")
    return safe_path


def get_theme_css(theme_id: str) -> str:
    """
    Trả nội dung ``custom.css`` của theme đã sanitize (dùng cho route
    ``/api/themes/<id>/custom.css``). Trả chuỗi rỗng nếu theme không có CSS.
    """
    found = _find_theme_dir(theme_id)
    if not found:
        return ""

    theme_dir, _builtin = found
    data, _error = _load_manifest_from_dir(theme_dir)
    if not data:
        return ""

    candidates: List[str] = []
    asset_css = (data.get("assets") or {}).get("custom_css")
    if isinstance(asset_css, str) and asset_css.strip():
        candidates.append(asset_css.strip())
    candidates.append("custom.css")

    for relative in candidates:
        try:
            css_path = resolve_asset_path(theme_id, relative)
        except (FileNotFoundError, PathTraversalError, ValueError):
            continue
        try:
            return sanitize_css(_read_text(css_path))
        except OSError as exc:
            _log(f"[ThemeManager] Không đọc được CSS '{relative}': {exc}")

    return ""


__all__ = [
    "DEFAULT_THEME_ID",
    "get_themes_root",
    "get_builtin_theme_dir",
    "list_themes",
    "get_theme",
    "get_active_theme",
    "set_active_theme",
    "delete_theme",
    "export_theme",
    "build_theme_from_values",
    "resolve_asset_path",
    "get_theme_css",
]
