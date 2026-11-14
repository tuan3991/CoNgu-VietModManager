#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chụp screenshot preview an toàn — KHÔNG đụng tới Chrome đang mở của bạn.

Ví dụ:
    python tools/preview_shot.py static/index.html -o preview.png --width 1440 --height 900
    python tools/preview_shot.py http://127.0.0.1:8000 -o preview.png

Nguyên tắc an toàn:
- Luôn chạy Chrome/Edge headless với `--user-data-dir` RIÊNG trong %TEMP%,
  nên không xung đột với profile Chrome người dùng đang mở.
- Tuyệt đối không kill toàn bộ `chrome.exe`. Nếu quá thời gian, chỉ kill đúng
  cây tiến trình do script này khởi tạo (theo PID).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _browser_candidates() -> list[Path]:
    """Danh sách trình duyệt Chromium ưu tiên: Chrome trước, Edge sau."""
    env = os.environ
    roots = [
        env.get("PROGRAMFILES"),
        env.get("PROGRAMFILES(X86)"),
        env.get("LOCALAPPDATA"),
    ]
    rels = [
        ("Google", "Chrome", "Application", "chrome.exe"),
        ("Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        for rel in rels:
            candidates.append(Path(root).joinpath(*rel))
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def find_browser() -> Path:
    for path in _browser_candidates():
        if path.is_file():
            return path
    raise SystemExit(
        "Không tìm thấy Chrome/Edge. Cài Chrome hoặc Edge rồi chạy lại."
    )


def target_to_url(target: str) -> str:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target):
        return target
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise SystemExit(f"Không tìm thấy file: {path}")
    return path.resolve().as_uri()


def _kill_own_tree(pid: int) -> None:
    """Chỉ kill tiến trình (và con) do chính script này tạo — không đụng Chrome khác."""
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chụp screenshot bằng Chrome/Edge headless với profile tạm an toàn."
    )
    parser.add_argument("target", help="Đường dẫn file .html hoặc URL http(s)://")
    parser.add_argument("-o", "--out", default="preview.png", help="File ảnh đầu ra")
    parser.add_argument("--width", type=int, default=1440, help="Chiều rộng viewport")
    parser.add_argument("--height", type=int, default=900, help="Chiều cao viewport")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Thời gian chờ tối đa (giây)"
    )
    args = parser.parse_args()

    browser = find_browser()
    url = target_to_url(args.target)
    out = Path(args.out).expanduser()
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    # Profile riêng cho mỗi lần chụp: đây là điểm quan trọng nhất để không
    # xung đột với Chrome đang mở của người dùng.
    profile_dir = Path(tempfile.mkdtemp(prefix="vmm-preview-"))

    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--disable-background-networking",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=2500",
        f"--user-data-dir={profile_dir}",
        f"--window-size={args.width},{args.height}",
        f"--screenshot={out}",
        url,
    ]

    started = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    timed_out = False
    try:
        try:
            proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_own_tree(proc.pid)
            proc.wait(timeout=10)

        # Chrome đôi khi thoát trước khi file được flush xong.
        for _ in range(50):
            if out.exists() and out.stat().st_size > 0:
                break
            time.sleep(0.1)
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)

    elapsed = time.time() - started
    if not out.exists() or out.stat().st_size == 0:
        reason = "quá thời gian" if timed_out else f"exit code {proc.returncode}"
        print(f"[X] Không tạo được ảnh ({reason}).", file=sys.stderr)
        return 2

    print(f"[OK] {out} ({out.stat().st_size:,} bytes, {elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
