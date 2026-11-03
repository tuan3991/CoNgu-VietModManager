# -*- coding: utf-8 -*-
"""
CỔ NGỮ - Mod Compatibility & Update System (P1-01 & P1-04)
=========================================================
Quản lý metadata tương thích (Game build, platform, Anti-Cheat, DLC)
và cơ chế kiểm tra cập nhật bản mod thực chất (Version comparison & Receipts).
"""
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


# =============================================================================
# 1. VERSION COMPARISON ENGINE
# =============================================================================

def parse_version_tuple(ver_str: str) -> Tuple[Tuple[int, ...], str]:
    """
    Tách chuỗi phiên bản thành tuple số nguyên để so sánh thứ bậc (Semantic Versioning)
    kèm phần đuôi phụ (suffix).
    
    Ví dụ:
      'v1.2.3' -> ((1, 2, 3), '')
      'v1.0.0 (Bản Chuẩn UE5)' -> ((1, 0, 0), 'bản chuẩn ue5')
      '2.1-hotfix' -> ((2, 1), 'hotfix')
      '2026.11.01' -> ((2026, 11, 1), '')
    """
    if not ver_str or not isinstance(ver_str, str):
        return ((0,), "")

    s = ver_str.strip()
    # Bỏ tiền tố v hoặc V nếu có
    if s.lower().startswith("v") and len(s) > 1 and s[1].isdigit():
        s = s[1:].strip()

    # Tìm phần số ở đầu (dạng 1.2.3...)
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", s)
    if m:
        num_part, rest = m.group(1), m.group(2).strip()
        nums = tuple(int(x) for x in num_part.split("."))
        return (nums, rest.lower())

    # Fallback: tìm toàn bộ số trong chuỗi
    all_nums = re.findall(r"\d+", s)
    if all_nums:
        return (tuple(int(x) for x in all_nums), s.lower())

    return ((0,), s.lower())


def compare_mod_versions(v1: str, v2: str) -> int:
    """
    So sánh hai chuỗi phiên bản:
      Trả về -1 nếu v1 < v2  (có bản cập nhật mới)
      Trả về  0 nếu v1 == v2 (bằng nhau / đã ở bản mới nhất)
      Trả về  1 nếu v1 > v2  (bản hiện tại mới hơn catalog)
    """
    t1, s1 = parse_version_tuple(v1)
    t2, s2 = parse_version_tuple(v2)

    # Đưa hai tuple về cùng độ dài bằng cách đệm số 0
    max_len = max(len(t1), len(t2))
    padded_t1 = t1 + (0,) * (max_len - len(t1))
    padded_t2 = t2 + (0,) * (max_len - len(t2))

    if padded_t1 < padded_t2:
        return -1
    elif padded_t1 > padded_t2:
        return 1

    # Nếu phần số bằng nhau, so sánh chuỗi phụ
    if s1 == s2:
        return 0
    # Chuỗi không có hậu tố thường được coi là bản release chuẩn (mới hơn pre-release/hotfix)
    if not s1 and s2:
        return 1
    if s1 and not s2:
        return -1
    return -1 if s1 < s2 else (1 if s1 > s2 else 0)


# =============================================================================
# 2. COMPATIBILITY METADATA & VALIDATION (P1-01)
# =============================================================================

COMPATIBILITY_STATUS_CONFIRMED = "confirmed_compatible"
COMPATIBILITY_STATUS_UNTESTED = "untested"
COMPATIBILITY_STATUS_INCOMPATIBLE = "incompatible"
COMPATIBILITY_STATUS_MISSING = "game_missing"


def assess_mod_compatibility(
    game_config: dict,
    installed_game_info: Optional[dict] = None
) -> dict:
    """
    Đánh giá độ tương thích giữa bản mod và game cài trên máy người dùng (P1-01).
    Không suy đoán tương thích chỉ từ việc tồn tại thư mục game.

    Trả về:
    {
      "status": "confirmed_compatible" | "untested" | "incompatible" | "game_missing",
      "status_label": "Đã xác nhận tương thích" | "Chưa kiểm thử" | "Không tương thích",
      "is_compatible": bool,
      "reasons": list[str],
      "warnings": list[str],
      "anti_cheat_warning": Optional[str],
      "supported_platforms": list[str],
      "tested_game_versions": list[str],
      "tested_date": str,
      "translator_team": str
    }
    """
    g = game_config or {}
    installed = installed_game_info or {}

    game_path = installed.get("game_path") or ""
    if not game_path or not os.path.exists(game_path):
        return {
            "status": COMPATIBILITY_STATUS_MISSING,
            "status_label": "Chưa chọn thư mục game",
            "is_compatible": False,
            "reasons": ["Chưa xác định được thư mục game trên máy."],
            "warnings": [],
            "anti_cheat_warning": None,
            "supported_platforms": g.get("supported_platforms", ["steam", "epic", "gog", "standalone"]),
            "tested_game_versions": g.get("tested_game_versions", []),
            "tested_date": g.get("translation_stats", {}).get("last_updated", ""),
            "translator_team": g.get("translation_stats", {}).get("author", "Antigravity Localization Team")
        }

    reasons = []
    warnings = []
    anti_cheat_warning = None

    # 1. Cảnh báo Anti-Cheat / Online
    anti_cheat_info = g.get("anti_cheat")
    if isinstance(anti_cheat_info, dict) and anti_cheat_info.get("has_anti_cheat"):
        ac_name = anti_cheat_info.get("system", "Hệ thống bảo vệ bản quyền/Anti-Cheat")
        raw_msg = anti_cheat_info.get(
            "warning",
            f"Game sử dụng {ac_name}. Khuyến cáo chỉ chơi ở chế độ Offline/Singleplayer để tránh bị khóa tài khoản."
        )
        if ac_name and ac_name.lower() not in raw_msg.lower():
            ac_msg = f"[{ac_name}] {raw_msg}"
        else:
            ac_msg = raw_msg
        anti_cheat_warning = ac_msg
        warnings.append(ac_msg)
    elif g.get("has_anti_cheat"):
        anti_cheat_warning = "Game có tích hợp hệ thống Anti-Cheat. Cần chú ý khi chơi trực tuyến."
        warnings.append(anti_cheat_warning)

    # 2. Kiểm tra Nền tảng (Platform: Steam, Epic, GOG, GamePass, Standalone)
    supported_platforms = g.get("supported_platforms")
    if not supported_platforms:
        # Mặc định hỗ trợ Steam nếu có steam_appid
        supported_platforms = ["steam"] if g.get("steam_appid") else ["standalone"]
    
    current_platform = (installed.get("platform") or "").lower()
    platform_matched = True
    if current_platform and supported_platforms:
        norm_supported = [p.lower() for p in supported_platforms]
        if "any" not in norm_supported and current_platform not in norm_supported:
            platform_matched = False
            warnings.append(
                f"Nền tảng '{current_platform.upper()}' chưa nằm trong danh sách hỗ trợ chính thức ({', '.join(supported_platforms)})."
            )

    # 3. Kiểm tra Game Build / Version
    tested_versions = g.get("tested_game_versions") or []
    incompatible_versions = g.get("incompatible_game_versions") or []
    current_game_version = str(installed.get("game_version") or installed.get("build_id") or "").strip()

    status = COMPATIBILITY_STATUS_UNTESTED
    status_label = "Chưa kiểm thử bản game này"

    if current_game_version and incompatible_versions and current_game_version in incompatible_versions:
        status = COMPATIBILITY_STATUS_INCOMPATIBLE
        status_label = "Không tương thích"
        reasons.append(
            f"Phiên bản game hiện tại ({current_game_version}) đã được xác nhận không tương thích với bản mod này (có thể gây văng game)."
        )
    elif current_game_version and tested_versions and current_game_version in tested_versions:
        status = COMPATIBILITY_STATUS_CONFIRMED
        status_label = "Đã xác nhận tương thích"
        reasons.append(
            f"Phiên bản game ({current_game_version}) hoàn toàn khớp với danh sách kiểm thử chính thức."
        )
    elif not current_game_version:
        status = COMPATIBILITY_STATUS_UNTESTED
        status_label = "Chưa kiểm chứng phiên bản game"
        reasons.append(
            "Chưa xác định được Build ID hoặc Version cụ thể của file game. Hãy kiểm tra trước khi cài đặt."
        )
    else:
        status = COMPATIBILITY_STATUS_UNTESTED
        status_label = "Phiên bản chưa kiểm thử"
        reasons.append(
            f"Bản game hiện tại ({current_game_version}) chưa có trong dữ liệu kiểm thử. Bản dịch có thể vẫn hoạt động nếu nhà phát triển không thay đổi cấu trúc file."
        )

    if not platform_matched and status == COMPATIBILITY_STATUS_CONFIRMED:
        status = COMPATIBILITY_STATUS_UNTESTED
        status_label = "Khác nền tảng đã kiểm thử"

    return {
        "status": status,
        "status_label": status_label,
        "is_compatible": status in (COMPATIBILITY_STATUS_CONFIRMED, COMPATIBILITY_STATUS_UNTESTED),
        "reasons": reasons,
        "warnings": warnings,
        "anti_cheat_warning": anti_cheat_warning,
        "supported_platforms": supported_platforms,
        "tested_game_versions": tested_versions,
        "tested_date": g.get("translation_stats", {}).get("last_updated", ""),
        "translator_team": g.get("translation_stats", {}).get("author", "Antigravity Localization Team")
    }


# =============================================================================
# 3. MOD UPDATE CHECKER (P1-04)
# =============================================================================

def get_catalog_latest_mod_version(game_config: dict) -> Tuple[str, str, List[dict]]:
    """
    Lấy thông tin phiên bản mới nhất từ catalog (games.json):
    Trả về (latest_version_str, changelog, versions_list).
    """
    if not game_config or not isinstance(game_config, dict):
        return ("", "", [])

    versions = game_config.get("versions") or []
    if isinstance(versions, list) and len(versions) > 0:
        # Ưu tiên mục có is_latest = True hoặc mục đầu tiên
        latest_entry = next((v for v in versions if v.get("is_latest")), versions[0])
        latest_ver = str(latest_entry.get("version") or "").strip()
        changelog = str(latest_entry.get("changelog") or "").strip()
        return (latest_ver, changelog, versions)

    # Fallback vào translation_stats
    stats = game_config.get("translation_stats") or {}
    ver = str(stats.get("version") or "").strip()
    return (ver or "v1.0.0", "Bản phát hành chuẩn", [])


def check_mod_update_status(
    game_id: str,
    catalog_game: Optional[dict],
    installed_receipt: Optional[dict],
    is_mod_installed_on_disk: bool = False
) -> dict:
    """
    Đánh giá trạng thái cập nhật bản mod một cách thực chất (P1-04):
    
    Phân biệt rõ:
      1. `not_installed`: Game chưa cài bản mod
      2. `up_to_date`: Đang ở bản mới nhất
      3. `update_available`: Có bản mới hơn trong catalog
      4. `unknown_version`: Bản mod đã có file nhưng chưa có biên nhận ghi phiên bản (cài từ trước)
      5. `offline` / `catalog_error`: Không có dữ liệu catalog hoặc mất kết nối
    """
    if not catalog_game or not isinstance(catalog_game, dict):
        return {
            "success": False,
            "game_id": game_id,
            "has_update": False,
            "status": "catalog_error",
            "message": "Không tìm thấy thông tin game trong danh mục máy chủ."
        }

    latest_ver, changelog, versions = get_catalog_latest_mod_version(catalog_game)
    if not latest_ver:
        return {
            "success": False,
            "game_id": game_id,
            "has_update": False,
            "status": "catalog_error",
            "message": "Danh mục game thiếu thông tin phiên bản mod."
        }

    # Kiểm tra xem mod đã cài hay chưa
    has_receipt = bool(installed_receipt and installed_receipt.get("status") == "installed")
    installed_ver = str(installed_receipt.get("version") or "").strip() if has_receipt else ""

    if not has_receipt and not is_mod_installed_on_disk:
        return {
            "success": True,
            "game_id": game_id,
            "has_update": False,
            "status": "not_installed",
            "installed_version": None,
            "latest_version": latest_ver,
            "message": "Bản Việt hóa hiện chưa được cài đặt."
        }

    # Trường hợp file mod có trên ổ đĩa nhưng thiếu biên nhận phiên bản (untracked legacy install)
    if not installed_ver and is_mod_installed_on_disk:
        return {
            "success": True,
            "game_id": game_id,
            "has_update": True,
            "status": "unknown_version",
            "installed_version": "Chưa rõ phiên bản (Legacy)",
            "latest_version": latest_ver,
            "changelog": changelog,
            "versions": versions,
            "message": f"Phát hiện bản Việt hóa cũ chưa định danh. Khuyến nghị cập nhật lên {latest_ver}."
        }

    # So sánh phiên bản
    cmp_res = compare_mod_versions(installed_ver, latest_ver)

    if cmp_res < 0:
        return {
            "success": True,
            "game_id": game_id,
            "has_update": True,
            "status": "update_available",
            "installed_version": installed_ver,
            "latest_version": latest_ver,
            "changelog": changelog,
            "versions": versions,
            "message": f"Có bản cập nhật mới ({latest_ver}) thay cho bản hiện tại ({installed_ver})."
        }
    elif cmp_res == 0:
        return {
            "success": True,
            "game_id": game_id,
            "has_update": False,
            "status": "up_to_date",
            "installed_version": installed_ver,
            "latest_version": latest_ver,
            "changelog": changelog,
            "versions": versions,
            "message": f"Bản Việt hóa đang ở phiên bản mới nhất ({installed_ver})."
        }
    else:
        # installed_ver > latest_ver (Bản dev hoặc test nội bộ)
        return {
            "success": True,
            "game_id": game_id,
            "has_update": False,
            "status": "up_to_date",
            "installed_version": installed_ver,
            "latest_version": latest_ver,
            "changelog": changelog,
            "versions": versions,
            "message": f"Bản Việt hóa hiện tại ({installed_ver}) mới hơn bản trên catalog ({latest_ver})."
        }

