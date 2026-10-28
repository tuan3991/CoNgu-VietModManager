# -*- coding: utf-8 -*-
"""
Core Package: theme_manager
===========================

Động cơ Theme (Theme Engine) phía backend cho Cổ Ngữ (VietModHub Pro).

Public API
----------
Manifest::

    parse_manifest(raw_json)            -> dict
    validate_manifest(data)            -> (ok: bool, error_message: str)
    normalize_manifest(data)           -> dict
    slugify(text)                      -> str

Installer::

    install_theme_zip(zip_path, themes_root) -> dict
    sanitize_css(css_text)                   -> str

Service::

    get_themes_root()                  -> str
    get_builtin_theme_dir()            -> str
    list_themes()                      -> list[dict]
    get_theme(theme_id)                -> dict | None
    get_active_theme()                 -> str
    set_active_theme(theme_id)         -> dict
    delete_theme(theme_id)             -> dict
    export_theme(theme_id, dest_path)  -> dict
    build_theme_from_values(payload)   -> dict
    resolve_asset_path(theme_id, rel)  -> str
    get_theme_css(theme_id)            -> str
"""

from .manifest import (
    CSS_EXTENSIONS,
    FORBIDDEN_VALUE_TOKENS,
    ID_RE,
    IMAGE_EXTENSIONS,
    MAX_META_LEN,
    MAX_NAME_LEN,
    MAX_VALUE_LEN,
    MAX_VARIABLES,
    ManifestError,
    SAFE_KEYWORDS,
    VAR_KEY_RE,
    is_safe_relative_asset_name,
    is_safe_variable_value,
    manifest_to_json,
    normalize_manifest,
    parse_manifest,
    slugify,
    strip_diacritics,
    validate_manifest,
)

from .installer import (
    ALLOWED_EXTENSIONS,
    MAX_FILES,
    MAX_SINGLE_FILE,
    MAX_TOTAL_UNCOMPRESSED,
    ThemeInstallError,
    install_theme_zip,
    sanitize_css,
)

from .service import (
    DEFAULT_THEME_ID,
    build_theme_from_values,
    delete_theme,
    export_theme,
    get_active_theme,
    get_builtin_theme_dir,
    get_theme,
    get_theme_css,
    get_themes_root,
    list_themes,
    resolve_asset_path,
    set_active_theme,
)

__all__ = [
    # manifest
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
    # installer
    "ALLOWED_EXTENSIONS",
    "MAX_FILES",
    "MAX_SINGLE_FILE",
    "MAX_TOTAL_UNCOMPRESSED",
    "ThemeInstallError",
    "install_theme_zip",
    "sanitize_css",
    # service
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
