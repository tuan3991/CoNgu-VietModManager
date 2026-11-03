# -*- coding: utf-8 -*-
"""
CỔ NGỮ - Troubleshooting Center & Audit History (P1-05)
======================================================
1. Hướng dẫn khắc phục sự cố theo kịch bản thường gặp:
   - Không hiện tiếng Việt
   - Game bị văng / crash khi mở
   - Game vừa cập nhật trên Steam/Epic
   - Gỡ sạch bản Việt hóa
   - Khôi phục file Save
2. Nhật ký thao tác (Audit Log) theo Job ID, bước thực hiện, kết quả xác minh.
3. Kiểm tra phạm vi bản sao lưu trước khi người dùng xác nhận khôi phục.
4. Xuất báo cáo hỗ trợ kỹ thuật (Support Report) tự động che mờ thông tin cá nhân/token.
   Tuyệt đối KHÔNG tự ý tải báo cáo lên mạng.
"""
import os
import re
import sys
import json
import time
import uuid
import platform
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import core.config_manager.paths as paths
from core.config_manager.paths import APPDATA_DIR, BACKUP_ROOT, CONFIG_JSON
from core.config_manager.user_settings import load_user_config

AUDIT_LOG_FILE = os.path.join(APPDATA_DIR, "operation_audit.json")
MAX_AUDIT_ENTRIES = 100


# =============================================================================
# 1. SCENARIO GUIDES (HƯỚNG DẪN THEO TÌNH HUỐNG)
# =============================================================================

SCENARIOS = {
    "not_showing_vietnamese": {
        "id": "not_showing_vietnamese",
        "title": "Game không hiện tiếng Việt (vẫn là tiếng Anh hoặc lỗi ô vuông)",
        "causes": [
            "Game chưa kích hoạt đúng ngôn ngữ trong phần Cài đặt của game.",
            "Thiếu font tiếng Việt hệ thống (Segoe UI / Tahoma) hoặc font game bị đè.",
            "File loader winhttp.dll bị Windows Defender chặn hoặc đổi tên thành .disabled."
        ],
        "solutions": [
            {
                "step": 1,
                "title": "Kiểm tra Cài Đặt Ngôn Ngữ trong Game",
                "detail": "Nhiều game (như Unity/Unreal) yêu cầu vào Menu Settings → Audio/Language và chọn tiếng Việt hoặc tiếng Anh (đã patch)."
            },
            {
                "step": 2,
                "title": "Kiểm tra Loader BepInEx / winhttp.dll",
                "detail": "Chạy 'Kiểm tra máy (Game Doctor)' để phát hiện file winhttp.dll có bị antivirus khóa hay không."
            },
            {
                "step": 3,
                "title": "Cài Lại 1-Click",
                "detail": "Bấm nút 'Cài Lại 1-Click' để Cổ Ngữ nạp lại toàn bộ font và file dịch chuẩn."
            }
        ]
    },
    "game_crash_on_launch": {
        "id": "game_crash_on_launch",
        "title": "Game bị văng (Crash) ngay khi bấm Chơi",
        "causes": [
            "Thiếu Visual C++ Redistributable 2015-2022 (x64) — nguyên nhân số 1.",
            "Thiếu DirectX 9/11 runtime tương thích.",
            "Xung đột với ứng dụng chèn đồ họa (ReShade, SpecialK, RivaTuner/MSI Afterburner)."
        ],
        "solutions": [
            {
                "step": 1,
                "title": "Cài đặt Visual C++ Redistributable (x64)",
                "detail": "Tải bản chính thức từ Microsoft và cài đặt, sau đó khởi động lại Cổ Ngữ.",
                "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            },
            {
                "step": 2,
                "title": "Tạm tắt Overlay & ReShade",
                "detail": "Nếu bạn có dùng ReShade (dxgi.dll) hoặc Discord/Steam Overlay, hãy thử tạm tắt để loại trừ xung đột hook."
            },
            {
                "step": 3,
                "title": "Khôi phục gốc về tiếng Anh",
                "detail": "Vào menu [...] → 'Khôi phục file gốc' để đưa game về trạng thái nguyên bản xác nhận game có chạy được không."
            }
        ]
    },
    "game_updated_steam_epic": {
        "id": "game_updated_steam_epic",
        "title": "Game vừa cập nhật trên Steam/Epic khiến bản dịch biến mất",
        "causes": [
            "Steam/Epic vừa tải bản vá mới và tự động ghi đè file ngôn ngữ.",
            "Bản sao lưu .congu_bak cũ vẫn an toàn tại chỗ."
        ],
        "solutions": [
            {
                "step": 1,
                "title": "Cài lại 1-Click tức thì",
                "detail": "Cổ Ngữ hỗ trợ cài lại 0 giây từ gói cache đã tải sẵn mà không cần tải lại."
            },
            {
                "step": 2,
                "title": "Kiểm tra tương thích",
                "detail": "Xem thông báo tương thích trên thẻ game xem bản vá mới của Steam có cần bản mod cập nhật không."
            }
        ]
    },
    "clean_uninstall": {
        "id": "clean_uninstall",
        "title": "Muốn gỡ sạch bản Việt hóa để chơi Online / Verify file Steam",
        "causes": [
            "Cần đưa game về trạng thái 100% nguyên bản nhà phát hành."
        ],
        "solutions": [
            {
                "step": 1,
                "title": "Bấm 'Gỡ Bản Việt Hóa'",
                "detail": "Cổ Ngữ sẽ tự động hoàn nguyên các file từ .congu_bak hoặc xóa tệp mod độc lập, trả lại game sạch 100%."
            },
            {
                "step": 2,
                "title": "Verify Integrity trên Steam (Nếu cần)",
                "detail": "Trên Steam: Chuột phải vào Game → Properties → Installed Files → Verify integrity of game files."
            }
        ]
    }
}


def get_troubleshooting_guides() -> List[dict]:
    """Trả về danh sách các hướng dẫn tình huống có sẵn."""
    return list(SCENARIOS.values())


def get_scenario_guide(scenario_id: str) -> Optional[dict]:
    """Lấy hướng dẫn chi tiết cho 1 kịch bản."""
    return SCENARIOS.get(scenario_id)


# =============================================================================
# 2. AUDIT LOGGING & JOB HISTORY
# =============================================================================

def record_audit_event(
    game_id: str,
    action: str,
    status: str,
    message: str = "",
    details: Optional[dict] = None
) -> dict:
    """
    Ghi nhận một sự kiện vận hành vào nhật ký audit (xoay vòng tối đa MAX_AUDIT_ENTRIES).
    
    action: 'install' | 'uninstall' | 'restore' | 'update_check' | 'preflight'
    status: 'success' | 'error' | 'warning' | 'rollback'
    """
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    entry = {
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
        "game_id": game_id,
        "action": action,
        "status": status,
        "message": message,
        "details": details or {}
    }

    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
        logs = []
        if os.path.exists(AUDIT_LOG_FILE):
            try:
                with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logs = data
            except Exception:
                logs = []

        logs.append(entry)
        # Giữ lại số lượng tối đa
        if len(logs) > MAX_AUDIT_ENTRIES:
            logs = logs[-MAX_AUDIT_ENTRIES:]

        # Ghi nguyên tử qua file tạm
        tmp_file = f"{AUDIT_LOG_FILE}.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, AUDIT_LOG_FILE)
    except Exception as e:
        print(f"[Troubleshooter] Lỗi ghi audit log: {e}")

    return entry


def get_recent_audit_logs(game_id: Optional[str] = None, limit: int = 50) -> List[dict]:
    """Lấy danh sách các sự kiện audit gần nhất, có thể lọc theo game_id."""
    if not os.path.exists(AUDIT_LOG_FILE):
        return []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            if game_id:
                data = [x for x in data if x.get("game_id") == game_id]
            data.reverse()
            return data[:limit]
    except Exception as e:
        print(f"[Troubleshooter] Lỗi đọc audit log: {e}")
        return []


# =============================================================================
# 3. BACKUP INSPECTION (XEM TRƯỚC PHẠM VI KHÔI PHỤC)
# =============================================================================

def inspect_game_backups(game_id: str, game_path: str = "") -> dict:
    """
    Kiểm tra và trả về phạm vi các bản sao lưu sẵn sàng khôi phục:
    - Backup Manifest từ AppData/backups/<game_id>
    - Các file .congu_bak tại chỗ trong thư mục game
    """
    files = []
    total_size = 0

    # 1. Manifest trong AppData
    manifest_path = os.path.join(BACKUP_ROOT, game_id, "backup_manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                mdata = json.load(f)
                for item in mdata.get("files", []):
                    rel = item.get("relative_in_game") or os.path.basename(item.get("target_file", ""))
                    sz = item.get("modded_size") or 0
                    files.append({
                        "source": "appdata_manifest",
                        "relative_path": rel,
                        "backup_path": item.get("backup_file", ""),
                        "original_sha256": item.get("original_sha256", ""),
                        "size_bytes": sz
                    })
                    total_size += sz
        except Exception as e:
            print(f"[Troubleshooter] Lỗi đọc backup manifest: {e}")

    # 2. Quét file .congu_bak tại chỗ trong thư mục game nếu có game_path
    if game_path and os.path.isdir(game_path):
        try:
            for root, _dirs, fnames in os.walk(game_path):
                for fn in fnames:
                    if fn.endswith(".congu_bak"):
                        full_p = os.path.join(root, fn)
                        orig_fn = fn[:-10]
                        rel_dir = os.path.relpath(root, game_path)
                        rel_orig = os.path.normpath(os.path.join(rel_dir, orig_fn)).replace("\\", "/")
                        try:
                            sz = os.path.getsize(full_p)
                        except OSError:
                            sz = 0
                        # Tránh trùng lặp
                        if not any(x["relative_path"] == rel_orig for x in files):
                            files.append({
                                "source": "inplace_bak",
                                "relative_path": rel_orig,
                                "backup_path": full_p,
                                "size_bytes": sz
                            })
                            total_size += sz
        except Exception as e:
            print(f"[Troubleshooter] Lỗi quét .congu_bak tại chỗ: {e}")

    return {
        "game_id": game_id,
        "has_backup": len(files) > 0,
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "files": files,
        "scope_summary": f"Sẵn sàng hoàn nguyên {len(files)} tệp tin ({round(total_size / (1024 * 1024), 2)} MB) về nguyên bản gốc."
    }


# =============================================================================
# 4. REDACTED SUPPORT REPORT (BÁO CÁO HỖ TRỢ ĐÃ CHE DỮ LIỆU NHẠY CẢM)
# =============================================================================

def redact_sensitive_info(text: str) -> str:
    """
    Tự động che giấu (redact) thông tin nhạy cảm trong chuỗi:
    - Tên người dùng Windows trong đường dẫn C:\\Users\\<username>
    - Token xác thực, session ticket
    - Mật khẩu, key
    """
    if not text or not isinstance(text, str):
        return ""

    # 1. Che tên người dùng Windows trong đường dẫn
    text = re.sub(r"([a-zA-Z]:[\\/]Users[\\/])([^\\/\"\'\s]+)", r"\1<USER>", text, flags=re.IGNORECASE)

    # 2. Che Token / Auth Header / API key
    text = re.sub(r"(token|auth|ticket|api_key|password)([:=\s\"']+)([a-zA-Z0-9_\-\.]{8,})", r"\1\2***REDACTED***", text, flags=re.IGNORECASE)

    # 3. Che Cloud ID bí mật (giữ 3 ký tự đầu và cuối)
    def _mask_id(m):
        prefix = m.group(1)
        sep = m.group(2)
        val = m.group(3)
        if len(val) > 6:
            masked = val[:3] + "***" + val[-2:]
        else:
            masked = "***"
        return f"{prefix}{sep}{masked}"
    text = re.sub(r"(cloud_id)([:=\s\"']+)([a-zA-Z0-9_\-]{4,})", _mask_id, text, flags=re.IGNORECASE)

    return text


def redact_object(obj: Any) -> Any:
    """Đệ quy che mờ các trường nhạy cảm trong đối tượng Python."""
    if isinstance(obj, str):
        return redact_sensitive_info(obj)
    elif isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            if str(k).lower() in ("password", "token", "auth_token", "ticket", "secret"):
                new_dict[k] = "***REDACTED***"
            else:
                new_dict[k] = redact_object(v)
        return new_dict
    elif isinstance(obj, list):
        return [redact_object(x) for x in obj]
    return obj


def generate_support_report(
    game_id: Optional[str] = None,
    include_recent_logs: bool = True
) -> dict:
    """
    Tổng hợp báo cáo kỹ thuật để người dùng gửi hỗ trợ.
    Toàn bộ dữ liệu nhạy cảm được che mờ. Không tự động upload.
    """
    cfg = load_user_config()
    os_info = f"{platform.system()} {platform.release()} ({platform.architecture()[0]})"
    py_info = f"Python {sys.version.split()[0]}"

    report_data = {
        "report_id": f"REP-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
        "generated_at": datetime.now().isoformat(),
        "environment": {
            "os": os_info,
            "python": py_info,
            "app_version": paths.CURRENT_VERSION,
        },
        "target_game": None,
        "recent_audit_events": []
    }

    if game_id:
        game_path = cfg.get(f"{game_id}_path", "")
        installed_mod = cfg.get("installed_mods", {}).get(game_id, {})
        backups = inspect_game_backups(game_id, game_path)

        report_data["target_game"] = {
            "game_id": game_id,
            "has_path": bool(game_path and os.path.exists(game_path)),
            "installed_mod_version": installed_mod.get("version"),
            "installed_at": installed_mod.get("installed_at"),
            "backups_available": backups.get("total_files", 0),
        }

    if include_recent_logs:
        recent = get_recent_audit_logs(game_id=game_id, limit=10)
        report_data["recent_audit_events"] = recent

    sanitized_data = redact_object(report_data)

    # Tạo phiên bản văn bản thân thiện dễ đọc
    lines = [
        f"=== CỔ NGỮ (VIETMODHUB) BÁO CÁO HỖ TRỢ KỸ THUẬT ===",
        f"Mã báo cáo: {sanitized_data.get('report_id')}",
        f"Thời gian: {sanitized_data.get('generated_at')}",
        f"Hệ điều hành: {sanitized_data['environment']['os']}",
        f"Phiên bản App: {sanitized_data['environment']['app_version']}",
    ]

    if sanitized_data.get("target_game"):
        tg = sanitized_data["target_game"]
        lines.append(f"\n[Thông Tin Game: {tg['game_id']}]")
        lines.append(f"- Đường dẫn: {'Đã nhận diện' if tg['has_path'] else 'Chưa chọn'}")
        lines.append(f"- Bản mod: {tg.get('installed_mod_version') or 'Chưa cài'}")
        lines.append(f"- Bản sao lưu gốc: {tg.get('backups_available')} tệp tin sẵn sàng")

    if sanitized_data.get("recent_audit_events"):
        lines.append("\n[Lịch Sử Thao Tác Gần Nhất]")
        for ev in sanitized_data["recent_audit_events"][:5]:
            lines.append(f"- [{ev.get('timestamp', '')[:19]}] {ev.get('action')} -> {ev.get('status')}: {ev.get('message')}")

    lines.append("\n* Lưu ý: Tên người dùng và token đã được tự động che giấu bảo mật.")
    text_report = "\n".join(lines)

    return {
        "success": True,
        "report_id": sanitized_data.get("report_id"),
        "report_text": text_report,
        "report_data": sanitized_data
    }
