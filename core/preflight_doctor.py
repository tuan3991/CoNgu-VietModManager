# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Pre-Flight Game Doctor (P1-02)
========================================================
Bác sĩ tiền trạm kiểm tra toàn diện TRƯỚC khi cài đặt hoặc khởi chạy game:
1. Tiến trình game đang chạy (Process check - WinError 32 prevention).
2. Quyền ghi thư mục game (Directory writable / Smart UAC elevation).
3. Dung lượng trống các ổ đĩa liên quan (Disk space check).
4. Runtime phù hợp với từng engine (VC++ 2015-2022 x64, .NET 4.8, DirectX 9/11).
5. Phát hiện xung đột loader / mod khác (BepInEx winhttp.dll, ReShade dxgi.dll).
6. Font tiếng Việt hệ thống và font override.
7. Kế hoạch thay đổi (Change Plan preview) & vị trí sao lưu dữ liệu.

Phân loại rõ ràng:
- Blocker: Lỗi chặn bắt buộc người dùng xử lý (tắt game, giải phóng ổ đĩa, chạy Admin).
- Warning: Cảnh báo lưu ý, không chặn thao tác cài đặt.
"""
import os
import re
import sys
import shutil
from typing import Dict, Any, List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet-framework/net48"
DX_URL = "https://www.microsoft.com/download/details.aspx?id=35"


def _reg_read_value(root, path: str, name: str):
    """Đọc 1 giá trị registry, trả None nếu không có."""
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _type = winreg.QueryValueEx(key, name)
            return value
    except Exception:
        return None


# =============================================================================
# 1. RUNTIME CHECKS
# =============================================================================

def _check_vc_runtime(game_config: Optional[dict] = None) -> dict:
    """Visual C++ Redistributable 2015-2022 (x64)."""
    if not IS_WINDOWS:
        return {"id": "vc_runtime", "label": "Visual C++ Redistributable (x64)",
                "status": "ok", "severity": "ok", "detail": "Không áp dụng trên hệ điều hành này."}

    import winreg
    key_path = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    installed = _reg_read_value(winreg.HKEY_LOCAL_MACHINE, key_path, "Installed")
    version = _reg_read_value(winreg.HKEY_LOCAL_MACHINE, key_path, "Version") or ""

    if installed not in (1, True):
        alt = _reg_read_value(winreg.HKEY_LOCAL_MACHINE,
                              r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                              "Installed")
        if alt in (1, True):
            installed = alt
            version = _reg_read_value(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                "Version",
            ) or version

    sys_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    has_dll = os.path.exists(os.path.join(sys_dir, "VCRUNTIME140.dll"))

    if installed in (1, True) or (version and has_dll):
        return {
            "id": "vc_runtime",
            "label": "Visual C++ Redistributable (x64)",
            "status": "ok",
            "severity": "ok",
            "detail": f"Đã cài{(' — phiên bản ' + str(version)) if version else ''}.",
        }

    return {
        "id": "vc_runtime",
        "label": "Visual C++ Redistributable (x64)",
        "status": "error",
        "severity": "blocker",
        "detail": "Chưa cài VC++ Redistributable x64. Game Unity/Unreal có thể văng ngay khi mở.",
        "hint": "Bấm 'Cài VC++' để tải bản chính thức từ Microsoft, cài xong khởi động lại CỔ NGỮ.",
        "fix_url": VC_REDIST_URL,
        "fix_label": "Cài VC++ Redist",
    }


def _check_dotnet(game_config: Optional[dict] = None) -> dict:
    """ .NET Framework 4.8 (Chỉ bắt buộc nếu game dùng BepInEx hoặc .NET loader). """
    label = ".NET Framework 4.8+"
    if not IS_WINDOWS:
        return {"id": "dotnet", "label": label, "status": "ok", "severity": "ok", "detail": "Không áp dụng."}

    # Kiểm tra xem game có thực sự cần BepInEx / .NET hay không
    g = game_config or {}
    blob = f"{g.get('engine', '')} {g.get('mod_type', '')} {str(g.get('install_steps', ''))}".lower()
    needs_dotnet = ("bepinex" in blob) or ("dotnet" in blob) or ("unity" in blob and "assembly" in blob)

    if not needs_dotnet and g:
        return {"id": "dotnet", "label": label, "status": "skip", "severity": "ok",
                "detail": "Game này không yêu cầu .NET Framework."}

    release = _reg_read_value(
        __import__("winreg").HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        "Release",
    )
    try:
        release = int(release)
    except Exception:
        release = 0

    if release >= 528040:      # 4.8 trở lên
        return {"id": "dotnet", "label": label, "status": "ok", "severity": "ok",
                "detail": f"Đã cài (Release {release})."}
    if release >= 394802:      # 4.6.2+
        return {"id": "dotnet", "label": label, "status": "warn", "severity": "warning",
                "detail": f"Đang có bản cũ hơn 4.8 (Release {release}). BepInEx có thể cần 4.8.",
                "fix_url": DOTNET_URL, "fix_label": "Tải .NET 4.8"}
    return {"id": "dotnet", "label": label, "status": "warn", "severity": "warning",
            "detail": "Không đọc được phiên bản .NET Framework 4.x. Nếu dùng BepInEx, hãy cài .NET 4.8.",
            "fix_url": DOTNET_URL, "fix_label": "Tải .NET 4.8"}


def _check_directx(game_config: Optional[dict] = None) -> dict:
    """DirectX runtime (D3D11/DXGI + DX9 cũ)."""
    if not IS_WINDOWS:
        return {"id": "directx", "label": "DirectX runtime", "status": "ok", "severity": "ok", "detail": "Không áp dụng."}

    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    d3d11 = os.path.exists(os.path.join(sysroot, "System32", "d3dcompiler_47.dll"))
    dx9 = os.path.exists(os.path.join(sysroot, "System32", "d3dx9_43.dll"))

    if d3d11 and dx9:
        return {"id": "directx", "label": "DirectX runtime", "status": "ok", "severity": "ok",
                "detail": "Đã có D3DCompiler 47 và DX9 runtime."}
    if d3d11 and not dx9:
        return {"id": "directx", "label": "DirectX runtime", "status": "warn", "severity": "warning",
                "detail": "Thiếu DX9 runtime (d3dx9_43.dll) — game cũ dùng DirectX 9 có thể không mở được.",
                "hint": "Cài 'DirectX End-User Runtime' từ Microsoft nếu game báo thiếu d3dx9_43.dll.",
                "fix_url": DX_URL, "fix_label": "Tải DirectX"}
    return {"id": "directx", "label": "DirectX runtime", "status": "error", "severity": "warning",
            "detail": "Không tìm thấy d3dcompiler_47.dll — DirectX runtime có thể đã hỏng hoặc bị gỡ.",
            "fix_url": DX_URL, "fix_label": "Tải DirectX"}


def _check_winhttp(game_config: dict, game_root: str) -> dict:
    """BepInEx/Doorstop loader (winhttp.dll) — kiểm tra trạng thái loader."""
    label = "BepInEx Loader (winhttp.dll)"

    blob = str(game_config or {}).lower()
    uses_bepinex = ("bepinex" in blob) or ("winhttp.dll" in blob)

    if not uses_bepinex:
        return {"id": "winhttp", "label": label, "status": "skip", "severity": "ok",
                "detail": "Game này không dùng BepInEx."}

    if not game_root or not os.path.isdir(game_root):
        return {"id": "winhttp", "label": label, "status": "skip", "severity": "ok",
                "detail": "Chưa xác định được thư mục game."}

    dll = os.path.join(game_root, "winhttp.dll")
    disabled = os.path.join(game_root, "winhttp.dll.disabled")

    if os.path.exists(disabled) and not os.path.exists(dll):
        return {"id": "winhttp", "label": label, "status": "error", "severity": "blocker",
                "detail": "winhttp.dll đang bị vô hiệu hoá (đã đổi tên thành winhttp.dll.disabled) nên BepInEx không nạp được bản Việt hóa.",
                "hint": "Đổi tên winhttp.dll.disabled trở lại thành winhttp.dll (nếu bạn không dùng mod gameplay khác)."}

    if os.path.exists(dll):
        try:
            size = os.path.getsize(dll)
        except OSError:
            size = 0
        if size < 1024:
            return {"id": "winhttp", "label": label, "status": "error", "severity": "blocker",
                    "detail": f"winhttp.dll chỉ còn {size} byte — nhiều khả năng bị antivirus thay bằng file rỗng.",
                    "hint": "Thêm thư mục game vào loại trừ của Windows Defender, rồi cài lại mod."}
        return {"id": "winhttp", "label": label, "status": "ok", "severity": "ok",
                "detail": f"winhttp.dll hợp lệ ({round(size / 1024)} KB)."}

    return {"id": "winhttp", "label": label, "status": "warn", "severity": "warning",
            "detail": "Game dùng BepInEx nhưng chưa thấy winhttp.dll trong thư mục game.",
            "hint": "Cài lại bản Việt hóa (CỔ NGỮ sẽ tự nạp winhttp.dll + thư mục BepInEx)."}


def _check_fonts(game_root: str) -> dict:
    """Font hệ thống hỗ trợ dấu tiếng Việt + font override trong thư mục game."""
    if not IS_WINDOWS:
        return {"id": "fonts", "label": "Font tiếng Việt", "status": "ok", "severity": "ok", "detail": "Không áp dụng."}

    fonts_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
    required = ["segoeui.ttf", "tahoma.ttf", "arial.ttf"]
    found = [f for f in required if os.path.exists(os.path.join(fonts_dir, f))]

    game_fonts = 0
    if game_root and os.path.isdir(game_root):
        for root, _dirs, files in os.walk(game_root):
            depth = root[len(game_root):].count(os.sep)
            if depth >= 2:
                continue
            game_fonts += sum(1 for f in files if f.lower().endswith((".ttf", ".otf")))
            if game_fonts > 0:
                break

    if not found:
        return {"id": "fonts", "label": "Font tiếng Việt", "status": "error", "severity": "warning",
                "detail": "Không tìm thấy font hệ thống cơ bản (Segoe UI/Tahoma/Arial) — chữ tiếng Việt có thể hiện sai dấu.",
                "hint": "Cài lại font Segoe UI trong Windows Settings → Optional features."}
    detail = f"Có {len(found)}/{len(required)} font hệ thống hỗ trợ tiếng Việt."
    if game_fonts:
        detail += f" Game có {game_fonts} font override."
    return {"id": "fonts", "label": "Font tiếng Việt", "status": "ok", "severity": "ok", "detail": detail}


# =============================================================================
# 2. PRE-INSTALL ENVIRONMENT CHECKS (P1-02)
# =============================================================================

def _check_game_process(game_config: dict, game_root: str) -> dict:
    """Kiểm tra tiến trình game có đang chạy không (chống WinError 32 khóa tệp)."""
    try:
        from core.installer_pipeline.process_checker import check_game_running
        is_running, proc_name = check_game_running(game_config or {}, game_root)
        if is_running:
            title = (game_config or {}).get("vietnamese_title") or "game"
            return {
                "id": "game_process",
                "label": "Tiến trình game đang chạy",
                "status": "error",
                "severity": "blocker",
                "detail": f"Phát hiện tiến trình '{proc_name}' của {title} đang chạy trong nền.",
                "hint": "Vui lòng thoát game hoàn toàn trước khi cài đặt hoặc khôi phục để tránh lỗi khóa tệp."
            }
    except Exception as e:
        print(f"[Preflight] Process check error: {e}")

    return {
        "id": "game_process",
        "label": "Tiến trình game đang chạy",
        "status": "ok",
        "severity": "ok",
        "detail": "Game hiện không chạy (an toàn để cài đặt / khôi phục)."
    }


def _check_write_permission(game_root: str) -> dict:
    """Kiểm tra quyền ghi vào thư mục cài đặt game (UAC / Program Files)."""
    label = "Quyền ghi thư mục game"
    if not game_root or not os.path.exists(game_root):
        return {"id": "write_permission", "label": label, "status": "skip", "severity": "ok",
                "detail": "Chưa chọn thư mục game."}

    try:
        import security
        if security.is_running_as_admin():
            return {"id": "write_permission", "label": label, "status": "ok", "severity": "ok",
                    "detail": "Ứng dụng đang chạy với quyền Administrator."}

        writable = security.check_directory_writable(game_root)
        if not writable:
            folder_name = os.path.basename(game_root)
            return {
                "id": "write_permission",
                "label": label,
                "status": "error",
                "severity": "blocker",
                "detail": f"Thư mục '{folder_name}' bị hạn chế quyền ghi bởi Windows (thường do nằm trong 'Program Files').",
                "hint": "Bấm 'Khởi động quyền Admin' trên menu CỔ NGỮ để cấp quyền ghi tệp."
            }
    except Exception as e:
        print(f"[Preflight] Write check error: {e}")

    return {"id": "write_permission", "label": label, "status": "ok", "severity": "ok",
            "detail": "Thư mục có đầy đủ quyền ghi tệp."}


def _parse_size_bytes(size_str: str) -> int:
    """Chuyển đổi chuỗi kích thước (ví dụ '~2.6 MB', '150 KB', '1.2 GB') sang số byte."""
    if not size_str or not isinstance(size_str, str):
        return 10 * 1024 * 1024  # Mặc định 10 MB
    m = re.search(r"([\d\.]+)\s*(gb|mb|kb|b)?", size_str.lower())
    if not m:
        return 10 * 1024 * 1024
    val = float(m.group(1))
    unit = m.group(2) or "mb"
    if unit == "gb":
        return int(val * 1024 * 1024 * 1024)
    elif unit == "mb":
        return int(val * 1024 * 1024)
    elif unit == "kb":
        return int(val * 1024)
    return int(val)


def _check_disk_space(game_config: dict, game_root: str) -> dict:
    """Kiểm tra dung lượng trống của ổ đĩa cài đặt game và ổ đĩa AppData."""
    label = "Dung lượng ổ đĩa"
    if not game_root or not os.path.exists(game_root):
        return {"id": "disk_space", "label": label, "status": "skip", "severity": "ok",
                "detail": "Chưa chọn thư mục game."}

    try:
        g = game_config or {}
        mod_size_str = g.get("mod_size") or g.get("translation_stats", {}).get("mod_size", "~15 MB")
        required_bytes = _parse_size_bytes(mod_size_str)
        # Cộng thêm buffer an toàn 150 MB cho việc tạo sao lưu .congu_bak và staging
        safety_buffer_bytes = 150 * 1024 * 1024
        total_needed_bytes = required_bytes + safety_buffer_bytes

        usage = shutil.disk_usage(game_root)
        free_bytes = usage.free

        free_mb = round(free_bytes / (1024 * 1024))
        needed_mb = round(total_needed_bytes / (1024 * 1024))

        if free_bytes < total_needed_bytes:
            drive_letter = os.path.splitdrive(os.path.abspath(game_root))[0] or game_root
            return {
                "id": "disk_space",
                "label": label,
                "status": "error",
                "severity": "blocker",
                "detail": f"Ổ đĩa {drive_letter} chỉ còn {free_mb} MB trống, không đủ {needed_mb} MB dung lượng cần thiết để giải nén và tạo bản sao lưu.",
                "hint": f"Hãy giải phóng ít nhất {needed_mb - free_mb + 50} MB trên ổ {drive_letter} rồi thử lại."
            }

        return {
            "id": "disk_space",
            "label": label,
            "status": "ok",
            "severity": "ok",
            "detail": f"Ổ đĩa còn {round(free_bytes / (1024**3), 1)} GB trống (đạt yêu cầu tối thiểu {needed_mb} MB)."
        }
    except Exception as e:
        print(f"[Preflight] Disk check error: {e}")
        return {"id": "disk_space", "label": label, "status": "ok", "severity": "ok", "detail": "Đã kiểm tra ổ đĩa."}


def _check_mod_conflicts(game_config: dict, game_root: str) -> dict:
    """Phát hiện xung đột với các loader hoặc injector bên thứ 3 (ReShade, SpecialK, injectors)."""
    label = "Xung đột mod / Injector khác"
    if not game_root or not os.path.isdir(game_root):
        return {"id": "mod_conflicts", "label": label, "status": "skip", "severity": "ok",
                "detail": "Chưa xác định được thư mục game."}

    conflict_indicators = [
        ("dxgi.dll", "ReShade / SpecialK (dxgi.dll)"),
        ("d3d11.dll", "DirectX 11 Injector / Mod Loader (d3d11.dll)"),
        ("winhttp.dll.disabled", "BepInEx loader đang bị đổi tên (.disabled)"),
    ]

    detected = []
    for fn, desc in conflict_indicators:
        fp = os.path.join(game_root, fn)
        if os.path.exists(fp):
            detected.append(desc)

    if detected:
        return {
            "id": "mod_conflicts",
            "label": label,
            "status": "warn",
            "severity": "warning",
            "detail": f"Phát hiện tệp có thể gây xung đột: {', '.join(detected)}.",
            "hint": "Nếu sau khi cài Việt hóa mà game bị văng hoặc chữ không hiện, hãy tạm thời đổi tên các file injector trên để kiểm tra."
        }

    return {
        "id": "mod_conflicts",
        "label": label,
        "status": "ok",
        "severity": "ok",
        "detail": "Không phát hiện xung đột loader hoặc file mod lạ."
    }


# =============================================================================
# 3. CHANGE PLAN PREVIEW (P1-02)
# =============================================================================

def generate_change_plan(game_config: dict, game_root: str) -> dict:
    """
    Sinh kế hoạch thay đổi (Change Plan preview) trước khi cài đặt:
    - Danh sách file sẽ ghi / thay thế
    - Danh sách file sẽ được sao lưu an toàn
    - Vị trí lưu trữ bản sao lưu
    - Đánh giá quyền quản trị
    """
    g = game_config or {}
    install_steps = g.get("install_steps") or []
    files_to_touch = []

    if install_steps and isinstance(install_steps, list):
        for step in install_steps:
            target = step.get("target") or step.get("dst") or ""
            action = step.get("action", "copy_file")
            if target and game_root:
                full_t = os.path.join(game_root, target.replace("/", os.sep))
                files_to_touch.append({
                    "relative_path": target,
                    "action": action,
                    "exists_already": os.path.exists(full_t)
                })
    else:
        # Legacy
        rel_p = g.get("relative_install_path", "")
        tpak = g.get("target_pak_name", "")
        if tpak and game_root:
            target_rel = os.path.join(rel_p, tpak) if rel_p else tpak
            full_t = os.path.join(game_root, target_rel.replace("/", os.sep))
            files_to_touch.append({
                "relative_path": target_rel,
                "action": "install_mod_pak",
                "exists_already": os.path.exists(full_t)
            })

    backup_files = [f["relative_path"] for f in files_to_touch if f["exists_already"]]

    return {
        "game_id": g.get("id", ""),
        "game_root": game_root,
        "files_to_modify": files_to_touch,
        "files_to_backup": backup_files,
        "backup_destination": f"Tại chỗ (.congu_bak) trong thư mục game & AppData/backups/{g.get('id', '')}",
        "steps_count": len(files_to_touch),
        "next_action": "Bấm 'Cài Việt Hóa' để bắt đầu giải nén và sao lưu tự động."
    }


# =============================================================================
# 4. RUN FULL PREFLIGHT
# =============================================================================

def run_preflight(game_config: dict, game_root: str = "", operation: str = "install") -> dict:
    """
    Chạy toàn bộ kiểm tra tiền trạm. Trả về báo cáo phân loại rõ Blocker và Warning.
    
    Parameters:
      operation: 'install' (trước khi cài mod) | 'launch' (trước khi mở game) | 'doctor' (tổng quát)
    """
    g = game_config or {}
    checks = []

    # 1. Các kiểm tra môi trường chạy máy
    checks.append(_check_game_process(g, game_root))
    checks.append(_check_write_permission(game_root))
    checks.append(_check_disk_space(g, game_root))
    checks.append(_check_vc_runtime(g))
    checks.append(_check_dotnet(g))
    checks.append(_check_directx(g))
    checks.append(_check_winhttp(g, game_root))
    checks.append(_check_fonts(game_root))
    checks.append(_check_mod_conflicts(g, game_root))

    # Tách lỗi chặn (blocker) và cảnh báo (warning)
    blockers = [c for c in checks if c.get("status") == "error" and c.get("severity") == "blocker"]
    other_errors = [c for c in checks if c.get("status") == "error" and c.get("severity") != "blocker"]
    warns = [c for c in checks if c.get("status") == "warn"] + other_errors

    blocker_msgs = [c.get("detail", "") for c in blockers if c.get("detail")]
    warning_msgs = [c.get("detail", "") for c in warns if c.get("detail")]

    is_blocked = len(blockers) > 0

    if is_blocked:
        severity = "error"
        summary = f"Phát hiện {len(blockers)} vấn đề chặn thao tác ({blockers[0].get('label', '')}). Cần xử lý trước khi tiếp tục."
    elif warns:
        severity = "warn"
        summary = f"Có {len(warns)} lưu ý nhỏ — bạn vẫn có thể cài đặt và chơi bình thường."
    else:
        severity = "ok"
        summary = "Môi trường hoàn hảo: tiến trình, ổ đĩa, quyền ghi và runtime đều sẵn sàng!"

    change_plan = generate_change_plan(g, game_root) if game_root else {}

    return {
        "ok": not is_blocked,
        "is_blocked": is_blocked,
        "severity": severity,
        "blockers": blocker_msgs,
        "warnings": warning_msgs,
        "checks": checks,
        "change_plan": change_plan,
        "summary": summary,
        "game_id": g.get("id", ""),
        "game_title": g.get("vietnamese_title") or g.get("title", ""),
    }
