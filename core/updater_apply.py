# -*- coding: utf-8 -*-
"""Sinh script áp dụng cập nhật: sao lưu bản cũ, robocopy, rollback khi lỗi."""
import os
import re


def build_apply_script(src_dir: str, dst_dir: str, backup_dir: str, updater_pid: int,
                       watchdog_seconds: int = 30, *, startup_probe: str,
                       transaction_token: str, version: str, pending_update: str = None) -> str:
    """Trả về nội dung apply_update.bat.

    Thứ tự: chờ app thoát → sao lưu toàn bộ bản cũ → robocopy bản mới → kiểm EXE
    → chạy thử và chờ watchdog → nếu lỗi/không khởi động được thì phục hồi bản cũ.
    """
    paths = (src_dir, dst_dir, backup_dir)
    if not re.fullmatch(r"[0-9a-f]{64}", transaction_token) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
        raise ValueError("Phiên bản hoặc mã giao dịch cập nhật không hợp lệ")
    script_paths = (*paths, startup_probe) + ((pending_update,) if pending_update else ())
    for path in script_paths:
        if not os.path.isabs(path) or any(char in path for char in ('%', '!', '"', '\r', '\n', '\x00')):
            raise ValueError("Đường dẫn cập nhật không an toàn cho script Windows")
    resolved = [os.path.normcase(os.path.realpath(path)) for path in paths]
    for index, first in enumerate(resolved):
        for second in resolved[index + 1:]:
            try:
                common = os.path.commonpath([first, second])
            except ValueError:
                continue
            if common in (first, second):
                raise ValueError("Thư mục cập nhật, ứng dụng và backup không được chứa lẫn nhau")
    new_exe = os.path.join(dst_dir, "VietModHub.exe")
    backup_exe = os.path.join(backup_dir, "VietModHub.exe")
    verifier = startup_probe + ".verify.ps1"

    def verify_tree(source, destination, exact=False, paths_only=False):
        command = ('"%%SystemRoot%%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
                   '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%s" -Source "%s" -Destination "%s"')
        return (command % (verifier, source, destination) + (" -Exact" if exact else "")
                + (" -PathsOnly" if paths_only else ""))
    lines = [
        "@echo off",
        "setlocal EnableDelayedExpansion",
        "chcp 65001 >nul",
        "title CO NGU - Dang cap nhat...",
        "timeout /t 2 /nobreak >nul",
        ":waitloop",
        '"%%SystemRoot%%\\System32\\tasklist.exe" /FI "PID eq %d" 2>nul | "%%SystemRoot%%\\System32\\find.exe" "%d" >nul' % (updater_pid, updater_pid),
        "if not errorlevel 1 (",
        "    timeout /t 1 /nobreak >nul",
        "    goto waitloop",
        ")",
        'if not exist "%s" exit /b 23' % new_exe,
        verify_tree(src_dir, src_dir, paths_only=True),
        "if errorlevel 1 exit /b 26",
        verify_tree(dst_dir, dst_dir, paths_only=True),
        "if errorlevel 1 exit /b 26",
        'if exist "%s" (' % backup_dir,
        verify_tree(backup_dir, backup_dir, paths_only=True),
        "if errorlevel 1 exit /b 26",
        ")",
        "if exist \"%s\" (" % new_exe,
        '    robocopy "%s" "%s" /MIR /IS /IT /IM /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul' % (dst_dir, backup_dir),
        "    set BRC=!ERRORLEVEL!",
        "    if !BRC! GEQ 8 (",
        "        echo Khong the sao luu ban cu - robocopy exit !BRC!. Khong thay doi ung dung.",
        "        timeout /t 10 /nobreak >nul",
        "        exit /b 20",
        "    )",
        ")",
        verify_tree(dst_dir, backup_dir, exact=True),
        "if errorlevel 1 exit /b 24",
        'robocopy "%s" "%s" /E /IS /IT /IM /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul' % (src_dir, dst_dir),
        "set RC=!ERRORLEVEL!",
        "if !RC! GEQ 8 goto rollback",
        verify_tree(src_dir, dst_dir),
        "if errorlevel 1 goto rollback",
        "if not exist \"%s\" (" % new_exe,
        "    echo Khong tim thay VietModHub.exe sau khi cap nhat.",
        "    goto rollback",
        ")",
        ('"%%SystemRoot%%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass '
         '-File "%s" -Executable "%s" -Marker "%s" -Token "%s" -Version "%s" -TimeoutSeconds %d')
        % (startup_probe, new_exe, startup_probe + ".ready.json", transaction_token, version, int(watchdog_seconds)),
        "set START_RC=!ERRORLEVEL!",
        "if !START_RC! EQU 34 exit /b 34",
        "if !START_RC! NEQ 0 (",
        "    echo Ban moi khong khoi dong duoc - dang khoi phuc ban cu...",
        "    goto rollback",
        ")",
        "exit /b 0",
        "",
        ":rollback",
        "echo Cap nhat that bai - dang khoi phuc ban cu...",
        "if not exist \"%s\" (" % backup_exe,
        "    echo Khong co ban sao luu de khoi phuc. Ban cu nam tai \"%s\"." % backup_dir,
        "    timeout /t 20 /nobreak >nul",
        "    exit /b 21",
        ")",
        'robocopy "%s" "%s" /MIR /IS /IT /IM /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul' % (backup_dir, dst_dir),
        "set RRC=!ERRORLEVEL!",
        "if !RRC! GEQ 8 (",
        "    echo KHOI PHUC THAT BAI - robocopy exit !RRC!. Ban cu nam tai \"%s\"." % backup_dir,
        "    timeout /t 20 /nobreak >nul",
        "    exit /b 22",
        ")",
        verify_tree(backup_dir, dst_dir, exact=True),
        "if errorlevel 1 exit /b 25",
        "if exist \"%s\" start \"\" \"%s\"" % (new_exe, new_exe),
        "exit /b 1",
    ]
    phase_path = startup_probe + ".phase"
    journaled = []
    for line in lines:
        if line == ":rollback":
            journaled.extend([line, '> "%s" echo rolling_back' % phase_path])
            continue
        if line.lstrip().startswith('robocopy'):
            phase = "backing_up" if '"%s" "%s"' % (dst_dir, backup_dir) in line else "applying"
            if '"%s" "%s"' % (backup_dir, dst_dir) in line:
                phase = "rolling_back"
            journaled.append('> "%s" echo %s' % (phase_path, phase))
        if line in ("exit /b 0", "exit /b 1"):
            journaled.append('> "%s" echo %s' % (phase_path, "complete" if line.endswith("0") else "rolled_back"))
            if pending_update:
                journaled.append('del "%s"' % pending_update)
        if line.lstrip().startswith('robocopy'):
            line = line.replace(' >nul', ' /LOG+:"%s" >nul' % (startup_probe + '.robocopy.log'))
        journaled.append(line)
    return "\r\n".join(journaled) + "\r\n"


def build_copy_verifier() -> str:
    return r'''param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Destination,
    [switch]$Exact,
    [switch]$PathsOnly
)
$ErrorActionPreference = 'Stop'
function Read-Tree([string]$Root) {
    $base = Get-Item -LiteralPath $Root -Force
    if (-not $base.PSIsContainer -or ($base.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Unsafe root'
    }
    $prefix = $base.FullName.TrimEnd('\') + '\'
    $items = @{}
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($base.FullName)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($item in (Get-ChildItem -LiteralPath $directory -Force)) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected' }
            $relative = $item.FullName.Substring($prefix.Length)
            if ($item.PSIsContainer) {
                $items[$relative] = 'directory'
                $pending.Push($item.FullName)
            } elseif ($PathsOnly) {
                $items[$relative] = 'file'
            } else {
                $items[$relative] = 'file:' + $item.Length + ':' + (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
            }
        }
    }
    return ,$items
}
try {
    $expected = Read-Tree $Source
    if ($PathsOnly) { exit 0 }
    $actual = Read-Tree $Destination
    foreach ($name in $expected.Keys) {
        if (-not $actual.ContainsKey($name) -or $actual[$name] -cne $expected[$name]) { exit 41 }
    }
    if ($Exact -and $actual.Count -ne $expected.Count) { exit 42 }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 43
}
'''

