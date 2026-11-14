# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - System Booster
=========================================
Giải phóng RAM (Trim Working Set) cho chính tiến trình CỔ NGỮ và toàn bộ cây tiến trình con
(bao gồm các tiến trình WebView2 `msedgewebview2.exe` vốn ngốn 150-280 MB RAM).

Cơ chế: gọi Win32 `psapi.EmptyWorkingSet()` cho từng PID (fallback `SetProcessWorkingSetSize(-1,-1)`),
buộc Windows đẩy các page ít dùng ra pagefile/standby list -> Working Set tụt mạnh về ~8-15 MB.
Hoàn toàn không can thiệp vào tiến trình game của người dùng.
"""

import os
import sys
import time
import ctypes
from typing import Dict, List, Tuple

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_SET_QUOTA = 0x0100

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    _kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
    _kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]

    _psapi.EmptyWorkingSet.restype = wintypes.BOOL
    _psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    _psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]

    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


def _list_processes() -> List[Tuple[int, int, str]]:
    """Trả về danh sách (pid, ppid, exe_name) từ Toolhelp32 snapshot."""
    if not IS_WINDOWS:
        return []
    result: List[Tuple[int, int, str]] = []
    h_snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not h_snap or h_snap == _INVALID_HANDLE_VALUE:
        return result
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if _kernel32.Process32FirstW(h_snap, ctypes.byref(entry)):
            while True:
                result.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
                if not _kernel32.Process32NextW(h_snap, ctypes.byref(entry)):
                    break
    finally:
        _kernel32.CloseHandle(h_snap)
    return result


def get_process_tree(root_pid: int = None) -> List[Tuple[int, str]]:
    """Liệt kê PID của tiến trình gốc và toàn bộ tiến trình con/cháu (BFS)."""
    if not IS_WINDOWS:
        return []
    root_pid = int(root_pid or os.getpid())
    procs = _list_processes()
    children: Dict[int, List[Tuple[int, str]]] = {}
    for pid, ppid, exe in procs:
        children.setdefault(ppid, []).append((pid, exe))

    ordered: List[Tuple[int, str]] = [(root_pid, "self")]
    seen = {root_pid}
    queue = [root_pid]
    while queue:
        parent = queue.pop(0)
        for pid, exe in children.get(parent, []):
            if pid in seen:
                continue
            seen.add(pid)
            ordered.append((pid, exe))
            queue.append(pid)
    return ordered


def get_working_set_bytes(pid: int) -> int:
    """Working Set hiện tại của 1 tiến trình (byte). Trả 0 nếu không đọc được."""
    if not IS_WINDOWS:
        return 0
    access = PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
    h_proc = _kernel32.OpenProcess(access, False, int(pid))
    if not h_proc:
        return 0
    try:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        if _psapi.GetProcessMemoryInfo(h_proc, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
    finally:
        _kernel32.CloseHandle(h_proc)
    return 0


def trim_process_working_set(pid: int) -> bool:
    """
    Giải phóng Working Set của 1 tiến trình.
    Ưu tiên EmptyWorkingSet, fallback SetProcessWorkingSetSize(h, -1, -1).
    """
    if not IS_WINDOWS:
        return False
    h_proc = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, int(pid))
    if not h_proc:
        return False
    try:
        if _psapi.EmptyWorkingSet(h_proc):
            return True
        # -1, -1 = yêu cầu Windows trim toàn bộ working set hiện có
        return bool(_kernel32.SetProcessWorkingSetSize(h_proc, ctypes.c_size_t(-1), ctypes.c_size_t(-1)))
    except Exception:
        return False
    finally:
        _kernel32.CloseHandle(h_proc)


def boost_memory(include_children: bool = True, settle_sec: float = 0.35) -> Dict:
    """
    Trim Working Set cho CỔ NGỮ + cây tiến trình con (WebView2).
    Trả về dict thống kê: số tiến trình, RAM trước/sau, RAM giải phóng (MB).
    """
    if not IS_WINDOWS:
        return {"success": False, "error": "Chi ho tro Windows", "freed_mb": 0.0}

    targets = get_process_tree() if include_children else [(os.getpid(), "self")]
    before = 0
    trimmed = 0
    detail = []
    for pid, exe in targets:
        ws = get_working_set_bytes(pid)
        before += ws
        # Bỏ qua tiến trình hệ thống không có quyền truy cập
        if trim_process_working_set(pid):
            trimmed += 1
            detail.append({"pid": pid, "exe": exe, "mb": round(ws / (1024 * 1024), 1)})

    if settle_sec:
        time.sleep(settle_sec)

    after = sum(get_working_set_bytes(pid) for pid, _ in targets)
    freed_mb = max(0.0, (before - after) / (1024 * 1024))
    return {
        "success": True,
        "processes": len(targets),
        "trimmed": trimmed,
        "before_mb": round(before / (1024 * 1024), 1),
        "after_mb": round(after / (1024 * 1024), 1),
        "freed_mb": round(freed_mb, 1),
        "detail": detail,
    }


def format_mb(value: float) -> str:
    return f"{value:.1f} MB".replace(".", ",") if isinstance(value, float) else f"{value} MB"
