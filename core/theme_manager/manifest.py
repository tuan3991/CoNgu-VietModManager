# -*- coding: utf-8 -*-
"""
Theme Manager - Manifest Parser & Validator
===========================================

Chịu trách nhiệm đọc, chuẩn hóa và kiểm duyệt tệp ``theme.json`` của một theme
cộng đồng. Toàn bộ dữ liệu đi ra khỏi module này đều đã được lọc:

* ``id`` / ``name`` bắt buộc, ``id`` chống path traversal bằng regex.
* ``variables`` chỉ giữ các CSS custom property an toàn (không ``url()``,
  ``expression()``, ``javascript:``, dấu ngoặc nhọn, dấu chấm phẩy...).
* ``assets`` chỉ nhận tên file tương đối (không phải URL), đúng định dạng.

Triết lý: các biến CSS không hợp lệ bị **bỏ kèm cảnh báo** thay vì làm hỏng
toàn bộ theme; riêng ``id`` / ``name`` sai thì theme bị coi là không hợp lệ.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Giới hạn (hard limits)
# ---------------------------------------------------------------------------
MAX_ID_LEN = 40
MAX_NAME_LEN = 80
MAX_META_LEN = 120
MAX_VARIABLES = 80
MAX_VALUE_LEN = 120

#: ID theme: chữ thường, số, ``_`` hoặc ``-``; bắt đầu bằng chữ/số.
#: Phần ``{1,39}`` phía sau bảo đảm tổng độ dài 2..40 ký tự và chặn các id
#: nguy hiểm kiểu ``..``, ``/``, ``\``, ``C:``.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,39}$")

#: Tên CSS custom property, ví dụ ``--bg-primary``.
VAR_KEY_RE = re.compile(r"^--[a-z0-9\-]{1,50}$")

_HEX_COLOR_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)
_COLOR_FUNC_RE = re.compile(
    r"^(?:rgb|rgba|hsl|hsla)\(\s*[0-9.,%\s]+\)$", re.IGNORECASE
)
_DIMENSION_RE = re.compile(
    r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem|em|vh|vw|ms|s|%)$", re.IGNORECASE
)

SAFE_KEYWORDS = frozenset(
    {"none", "transparent", "inherit", "initial", "auto", "normal"}
)

#: Bất kỳ chuỗi nào chứa các token này đều bị từ chối (so khớp lowercase).
FORBIDDEN_VALUE_TOKENS = (
    "url",
    "expression",
    "javascript",
    "@import",
    "\\",
    "{",
    "}",
    ";",
    "<",
    ">",
)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
CSS_EXTENSIONS = frozenset({".css"})

ASSET_KEYS = ("background_image", "custom_css", "background_opacity")


class ManifestError(ValueError):
    """Lỗi không thể đọc / chuẩn hóa ``theme.json``."""


# ---------------------------------------------------------------------------
# Chuỗi & slug
# ---------------------------------------------------------------------------
def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt (bao gồm ``đ``/``Đ``) khỏi một chuỗi."""
    if text is None:
        return ""
    value = str(text).replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def slugify(value: Any, fallback_prefix: str = "theme") -> str:
    """Tạo slug id hợp lệ từ tên theme (đã bỏ dấu, lowercase, tối đa 40 ký tự)."""
    raw = "" if value is None else str(value)
    ascii_text = strip_diacritics(raw).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    slug = slug[:MAX_ID_LEN].strip("_")

    if len(slug) < 2:
        digest = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:8]
        prefix = re.sub(r"[^a-z0-9]+", "", fallback_prefix.lower()) or "theme"
        slug = f"{prefix}_{digest}"[:MAX_ID_LEN]

    if not slug or not slug[0].isalnum():
        slug = f"theme_{slug}"[:MAX_ID_LEN]

    return slug


# ---------------------------------------------------------------------------
# Kiểm tra giá trị an toàn
# ---------------------------------------------------------------------------
def is_safe_variable_value(value: str) -> bool:
    """Trả ``True`` nếu value là một giá trị CSS an toàn theo whitelist."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value or len(value) > MAX_VALUE_LEN:
        return False

    lowered = value.lower()
    for token in FORBIDDEN_VALUE_TOKENS:
        if token in lowered:
            return False

    if lowered in SAFE_KEYWORDS:
        return True
    if _HEX_COLOR_RE.match(value):
        return True
    if _COLOR_FUNC_RE.match(value):
        return True
    if _DIMENSION_RE.match(value):
        return True
    return False


def is_safe_relative_asset_name(value: Any) -> bool:
    """Kiểm tra một tên file tương đối (không URL, không thoát thư mục)."""
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw or len(raw) > 255:
        return False

    path = raw.replace("\\", "/")
    if path.startswith("/") or path.startswith("//"):
        return False
    if re.match(r"^[A-Za-z]:", path):
        return False
    if "://" in path:
        return False

    parts = [part for part in path.split("/") if part not in ("", ".")]
    if not parts:
        return False
    for part in parts:
        if part == ".." or ":" in part:
            return False
    return True


def _safe_asset_with_ext(value: Any, allowed_exts: frozenset) -> bool:
    if not is_safe_relative_asset_name(value):
        return False
    lower = value.strip().lower()
    return any(lower.endswith(ext) for ext in allowed_exts)


def _coerce_opacity(value: Any) -> float | None:
    """Chuẩn hóa ``background_opacity`` về float trong [0, 1]."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


# ---------------------------------------------------------------------------
# Chuẩn hóa từng phần
# ---------------------------------------------------------------------------
def _clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return fallback
    return value.strip()


def _normalize_id(raw_id: Any, name: str) -> str:
    if raw_id is None:
        return slugify(name)
    text = str(raw_id).strip()
    if not text:
        return slugify(name)
    return text


def _normalize_variables(
    raw_variables: Any, warnings: List[str]
) -> Dict[str, str]:
    if raw_variables is None:
        return {}
    if not isinstance(raw_variables, dict):
        warnings.append("Trường 'variables' phải là object JSON — đã bỏ qua.")
        return {}

    variables: Dict[str, str] = {}
    for key, raw_value in raw_variables.items():
        if len(variables) >= MAX_VARIABLES:
            warnings.append(
                f"Chỉ giữ tối đa {MAX_VARIABLES} biến CSS; đã bỏ các biến còn lại."
            )
            break

        if not isinstance(key, str) or not VAR_KEY_RE.fullmatch(key):
            warnings.append(f"Bỏ biến CSS có tên không hợp lệ: {key!r}")
            continue

        if isinstance(raw_value, bool) or not isinstance(
            raw_value, (str, int, float)
        ):
            warnings.append(f"Bỏ biến '{key}': giá trị phải là chuỗi.")
            continue

        value = str(raw_value).strip()
        if len(value) > MAX_VALUE_LEN:
            warnings.append(
                f"Bỏ biến '{key}': giá trị vượt quá {MAX_VALUE_LEN} ký tự."
            )
            continue

        if not is_safe_variable_value(value):
            warnings.append(f"Bỏ biến '{key}': giá trị không an toàn ({value[:60]!r}).")
            continue

        variables[key] = value

    return variables


def _normalize_assets(raw_assets: Any, warnings: List[str]) -> Dict[str, Any]:
    if raw_assets is None:
        return {}
    if not isinstance(raw_assets, dict):
        warnings.append("Trường 'assets' phải là object JSON — đã bỏ qua.")
        return {}

    assets: Dict[str, Any] = {}

    background = raw_assets.get("background_image")
    if background is not None:
        if _safe_asset_with_ext(background, IMAGE_EXTENSIONS):
            assets["background_image"] = background.strip().replace("\\", "/")
        else:
            warnings.append(
                "Bỏ 'background_image': phải là tên file tương đối có đuôi "
                ".png/.jpg/.jpeg/.webp/.gif."
            )

    custom_css = raw_assets.get("custom_css")
    if custom_css is not None:
        if _safe_asset_with_ext(custom_css, CSS_EXTENSIONS):
            assets["custom_css"] = custom_css.strip().replace("\\", "/")
        else:
            warnings.append(
                "Bỏ 'custom_css': phải là tên file tương đối có đuôi .css."
            )

    opacity = raw_assets.get("background_opacity")
    if opacity is not None:
        normalized_opacity = _coerce_opacity(opacity)
        if normalized_opacity is None:
            warnings.append(
                "Bỏ 'background_opacity': phải là số thực trong khoảng 0..1."
            )
        else:
            assets["background_opacity"] = normalized_opacity

    for key in raw_assets:
        if key not in ASSET_KEYS:
            warnings.append(f"Bỏ asset không được hỗ trợ: {key!r}")

    return assets


# ---------------------------------------------------------------------------
# API public
# ---------------------------------------------------------------------------
def normalize_manifest(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chuẩn hóa một manifest thô thành dict đầy đủ khóa.

    Không raise với lỗi ngữ nghĩa (id/name sai...) — phần đó do
    :func:`validate_manifest` đảm nhiệm. Chỉ raise :class:`ManifestError` nếu
    đầu vào không phải object JSON.
    """
    if not isinstance(data, dict):
        raise ManifestError("theme.json phải là một JSON object (dictionary).")

    warnings: List[str] = []
    name = _clean_text(data.get("name"))
    theme_id = _normalize_id(data.get("id"), name)

    normalized: Dict[str, Any] = {
        "id": theme_id,
        "name": name,
        "author": _clean_text(data.get("author")),
        "version": _clean_text(data.get("version")),
        "description": _clean_text(data.get("description")),
        "variables": _normalize_variables(data.get("variables"), warnings),
        "assets": _normalize_assets(data.get("assets"), warnings),
        "warnings": warnings,
    }
    return normalized


def parse_manifest(raw_json: str | bytes) -> Dict[str, Any]:
    """
    Parse ``theme.json`` thô (str/bytes) và trả manifest đã chuẩn hóa.

    Raises:
        ManifestError: JSON không hợp lệ hoặc không phải object.
    """
    if raw_json is None:
        raise ManifestError("theme.json rỗng.")
    if isinstance(raw_json, (bytes, bytearray)):
        try:
            text = bytes(raw_json).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ManifestError(f"theme.json không phải UTF-8 hợp lệ: {exc}") from exc
    elif isinstance(raw_json, str):
        text = raw_json.lstrip("\ufeff")
    else:
        raise ManifestError("Dữ liệu theme.json phải là str hoặc bytes.")

    text = text.strip()
    if not text:
        raise ManifestError("theme.json rỗng.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"theme.json không phải JSON hợp lệ: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestError("theme.json phải là một JSON object (dictionary).")

    return normalize_manifest(data)


def validate_manifest(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Kiểm duyệt manifest.

    Returns:
        ``(ok, error_message)`` — ``error_message`` rỗng khi ``ok`` là True.
    """
    if not isinstance(data, dict):
        return False, "theme.json phải là một JSON object (dictionary)."

    try:
        normalized = normalize_manifest(data)
    except ManifestError as exc:
        return False, str(exc)

    theme_id = normalized.get("id", "")
    if not theme_id:
        return False, "Thiếu 'id' và không thể sinh id từ 'name'."
    if not ID_RE.fullmatch(theme_id):
        return (
            False,
            "ID theme không hợp lệ: chỉ cho phép chữ thường a-z, số 0-9, '_' "
            "hoặc '-', bắt đầu bằng chữ/số, độ dài 2-40 ký tự.",
        )

    name = normalized.get("name", "")
    if not name:
        return False, "Thiếu trường bắt buộc 'name' (tên theme)."
    if len(name) > MAX_NAME_LEN:
        return False, f"Tên theme vượt quá {MAX_NAME_LEN} ký tự."

    for field in ("author", "version", "description"):
        value = normalized.get(field, "")
        if len(value) > MAX_META_LEN:
            return False, f"Trường '{field}' vượt quá {MAX_META_LEN} ký tự."

    return True, ""


def manifest_to_json(data: Dict[str, Any], include_warnings: bool = False) -> str:
    """Serialize manifest sạch (bỏ khóa ``warnings``) để ghi ra đĩa/zip."""
    payload = {
        key: data[key]
        for key in ("id", "name", "author", "version", "description",
                    "variables", "assets")
        if key in data
    }
    if include_warnings and data.get("warnings"):
        payload["warnings"] = list(data["warnings"])
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "ManifestError",
    "ID_RE",
    "VAR_KEY_RE",
    "SAFE_KEYWORDS",
    "FORBIDDEN_VALUE_TOKENS",
    "IMAGE_EXTENSIONS",
    "CSS_EXTENSIONS",
    "MAX_VARIABLES",
    "MAX_VALUE_LEN",
    "MAX_NAME_LEN",
    "MAX_META_LEN",
    "strip_diacritics",
    "slugify",
    "is_safe_variable_value",
    "is_safe_relative_asset_name",
    "normalize_manifest",
    "parse_manifest",
    "validate_manifest",
    "manifest_to_json",
]
