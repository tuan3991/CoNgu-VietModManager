# -*- coding: utf-8 -*-
"""
Native Dialogs Provider for VietModHub / Cổ Ngữ
------------------------------------------------
Provides foolproof, native Windows dialogs for picking folders,
opening files, and saving files.

Guarantees:
1. Exact dialog type (Folder vs File Open vs File Save).
2. Exactly ONE dialog is shown at a time.
3. If the user cancels or closes the dialog, returns None immediately
   without opening secondary fallback dialogs.
4. Fallback tiers (PowerShell STA -> Tkinter) are invoked ONLY if the
   primary tier fails to display due to an exception.
"""

import os
import sys
import base64
import logging
import subprocess
from typing import Optional, Sequence

logger = logging.getLogger("VietModHub.NativeDialogs")

try:
    import webview
    FOLDER_DIALOG = getattr(webview, "FOLDER_DIALOG", 20)
    OPEN_DIALOG = getattr(webview, "OPEN_DIALOG", 10)
    SAVE_DIALOG = getattr(webview, "SAVE_DIALOG", 30)
except Exception:
    FOLDER_DIALOG = 20
    OPEN_DIALOG = 10
    SAVE_DIALOG = 30


def _run_powershell_dialog(ps_script: str, timeout: int = 300) -> Optional[str]:
    """Execute a PowerShell script in an isolated STA process and return decoded string or None."""
    try:
        enc = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-EncodedCommand", enc],
            capture_output=True,
            text=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            timeout=timeout,
        )
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip() and not line.startswith("<")]
        if lines:
            b64_str = lines[-1]
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8")
                return decoded.strip() if decoded else None
            except Exception as e:
                logger.warning(f"Failed to decode base64 dialog output: {e}")
    except subprocess.TimeoutExpired:
        logger.warning("Native dialog timed out after 300s.")
    except Exception as e:
        logger.error(f"PowerShell dialog process error: {e}")
    return None


def pick_folder(
    title: str = "Chọn thư mục",
    initial_dir: str = "",
    parent_window=None
) -> Optional[str]:
    """
    Open native folder picker dialog.
    Guarantees that only ONE dialog is presented to the user.
    If the dialog opens and the user cancels, returns None immediately.
    Fallback to PowerShell is ONLY used if PyWebView cannot display a dialog.
    """
    # Tier 1: PyWebView Window (Native Windows Explorer Folder Picker)
    if parent_window is not None and hasattr(parent_window, "create_file_dialog"):
        try:
            res = parent_window.create_file_dialog(
                dialog_type=FOLDER_DIALOG,
                directory=initial_dir if (initial_dir and os.path.exists(initial_dir)) else "",
                allow_multiple=False,
            )
            # The dialog opened successfully and finished.
            if res is not None and len(res) > 0:
                p = res[0]
                if p and os.path.exists(p):
                    return os.path.normpath(p if os.path.isdir(p) else os.path.dirname(p))
            # res is None or empty tuple/list => User clicked Cancel in PyWebView dialog.
            # DO NOT fall through to Tier 2 or Tier 3! User explicitly cancelled.
            return None
        except Exception as e:
            logger.debug(f"PyWebView folder dialog exception (trying fallback): {e}")

    # Tier 2: PowerShell STA FolderBrowserDialog (Only if PyWebView failed or not available)
    try:
        safe_title = (title or "Chọn thư mục").replace('"', '`"').replace("'", "''")
        safe_init = (initial_dir or "").replace('"', '`"').replace("'", "''")

        ps_code = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{safe_title}'
$dialog.ShowNewFolderButton = $true
if ('{safe_init}' -ne '' -and (Test-Path '{safe_init}')) {{
    $dialog.SelectedPath = '{safe_init}'
}}
$topForm = New-Object System.Windows.Forms.Form
$topForm.TopMost = $true
$topForm.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$topForm.ShowInTaskbar = $false
$topForm.Opacity = 0
$topForm.Show()
$topForm.BringToFront()
$res = $dialog.ShowDialog($topForm)
$topForm.Dispose()
if ($res -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) {{
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath)
    [System.Convert]::ToBase64String($bytes)
}} else {{
    [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("__USER_CANCELLED__"))
}}
"""
        raw_out = _run_powershell_dialog(ps_code)
        if raw_out == "__USER_CANCELLED__":
            return None
        if raw_out and os.path.isdir(raw_out):
            return os.path.normpath(raw_out)
        if raw_out:
            return None
    except Exception as e:
        logger.debug(f"PowerShell folder dialog fallback error: {e}")

    # Tier 3: Tkinter fallback (Only if both PyWebView and PowerShell failed to execute)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        tk_path = filedialog.askdirectory(
            title=title,
            initialdir=initial_dir if (initial_dir and os.path.exists(initial_dir)) else None
        )
        root.destroy()
        if tk_path and os.path.isdir(tk_path):
            return os.path.normpath(tk_path)
    except Exception as e:
        logger.debug(f"Tkinter folder picker fallback error: {e}")

    return None


def pick_file(
    title: str = "Chọn tệp",
    file_types: Optional[Sequence[str]] = None,
    initial_dir: str = "",
    parent_window=None
) -> Optional[str]:
    """
    Open native file selection dialog.
    Guarantees ONLY ONE dialog is shown. If user cancels, returns None immediately.
    """
    # Tier 1: PyWebView Window
    if parent_window is not None and hasattr(parent_window, "create_file_dialog"):
        try:
            res = parent_window.create_file_dialog(
                dialog_type=OPEN_DIALOG,
                directory=initial_dir if (initial_dir and os.path.exists(initial_dir)) else "",
                allow_multiple=False,
                file_types=file_types or tuple(),
            )
            if res is not None and len(res) > 0:
                p = res[0]
                if p and os.path.isfile(p):
                    return os.path.normpath(p)
                if p and os.path.exists(p):
                    return os.path.normpath(p)
            return None
        except Exception as e:
            logger.debug(f"PyWebView file dialog exception: {e}")

    # Tier 2: PowerShell STA OpenFileDialog
    try:
        filter_parts = []
        if file_types:
            for ft in file_types:
                if not ft:
                    continue
                if "(" in ft and ")" in ft:
                    pattern = ft.split("(")[-1].split(")")[0].strip()
                    filter_parts.append(f"{ft}|{pattern}")
                elif ft.startswith("*.") or ";" in ft:
                    filter_parts.append(f"Tệp ({ft})|{ft}")
                else:
                    filter_parts.append(f"{ft} (*.*)|*.*")
        filter_parts.append("Tất cả tệp (*.*)|*.*")
        win_filter = "|".join(filter_parts).replace("'", "''")

        safe_title = (title or "Chọn tệp").replace('"', '`"').replace("'", "''")
        safe_init = (initial_dir or "").replace('"', '`"').replace("'", "''")

        ps_code = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '{safe_title}'
$dialog.Multiselect = $false
$dialog.Filter = '{win_filter}'
if ('{safe_init}' -ne '' -and (Test-Path '{safe_init}')) {{
    $dialog.InitialDirectory = '{safe_init}'
}}
$topForm = New-Object System.Windows.Forms.Form
$topForm.TopMost = $true
$topForm.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$topForm.ShowInTaskbar = $false
$topForm.Opacity = 0
$topForm.Show()
$topForm.BringToFront()
$res = $dialog.ShowDialog($topForm)
$topForm.Dispose()
if ($res -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.FileName) {{
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($dialog.FileName)
    [System.Convert]::ToBase64String($bytes)
}} else {{
    [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("__USER_CANCELLED__"))
}}
"""
        chosen = _run_powershell_dialog(ps_code)
        if chosen == "__USER_CANCELLED__":
            return None
        if chosen and os.path.isfile(chosen):
            return os.path.normpath(chosen)
        if chosen:
            return None
    except Exception as e:
        logger.debug(f"PowerShell file picker fallback error: {e}")

    # Tier 3: Tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        tk_path = filedialog.askopenfilename(
            title=title,
            initialdir=initial_dir if (initial_dir and os.path.exists(initial_dir)) else None
        )
        root.destroy()
        if tk_path and os.path.isfile(tk_path):
            return os.path.normpath(tk_path)
    except Exception as e:
        logger.debug(f"Tkinter file picker fallback error: {e}")

    return None


def save_file(
    title: str = "Lưu tệp",
    default_name: str = "",
    file_types: Optional[Sequence[str]] = None,
    parent_window=None
) -> Optional[str]:
    """
    Open native file save dialog.
    Guarantees ONLY ONE dialog is shown. If user cancels, returns None immediately.
    """
    # Tier 1: PyWebView Window
    if parent_window is not None and hasattr(parent_window, "create_file_dialog"):
        try:
            res = parent_window.create_file_dialog(
                dialog_type=SAVE_DIALOG,
                save_filename=default_name or "",
                file_types=file_types or tuple(),
            )
            if res is not None and len(res) > 0:
                p = res if isinstance(res, str) else res[0]
                return os.path.normpath(p)
            return None
        except Exception as e:
            logger.debug(f"PyWebView save dialog exception: {e}")

    # Tier 2: PowerShell STA SaveFileDialog
    try:
        filter_parts = []
        if file_types:
            for ft in file_types:
                if not ft:
                    continue
                if "(" in ft and ")" in ft:
                    pattern = ft.split("(")[-1].split(")")[0].strip()
                    filter_parts.append(f"{ft}|{pattern}")
                elif ft.startswith("*.") or ";" in ft:
                    filter_parts.append(f"Tệp ({ft})|{ft}")
                else:
                    filter_parts.append(f"{ft} (*.*)|*.*")
        filter_parts.append("Tất cả tệp (*.*)|*.*")
        win_filter = "|".join(filter_parts).replace("'", "''")

        safe_title = (title or "Lưu tệp").replace('"', '`"').replace("'", "''")
        safe_name = (default_name or "").replace('"', '`"').replace("'", "''")

        ps_code = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.Title = '{safe_title}'
$dialog.FileName = '{safe_name}'
$dialog.Filter = '{win_filter}'
$topForm = New-Object System.Windows.Forms.Form
$topForm.TopMost = $true
$topForm.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$topForm.ShowInTaskbar = $false
$topForm.Opacity = 0
$topForm.Show()
$topForm.BringToFront()
$res = $dialog.ShowDialog($topForm)
$topForm.Dispose()
if ($res -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.FileName) {{
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($dialog.FileName)
    [System.Convert]::ToBase64String($bytes)
}} else {{
    [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("__USER_CANCELLED__"))
}}
"""
        chosen = _run_powershell_dialog(ps_code)
        if chosen == "__USER_CANCELLED__":
            return None
        if chosen:
            return os.path.normpath(chosen)
    except Exception as e:
        logger.debug(f"PowerShell save dialog fallback error: {e}")

    # Tier 3: Tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        tk_path = filedialog.asksaveasfilename(
            title=title,
            initialfile=default_name or None
        )
        root.destroy()
        if tk_path:
            return os.path.normpath(tk_path)
    except Exception as e:
        logger.debug(f"Tkinter save file fallback error: {e}")

    return None
