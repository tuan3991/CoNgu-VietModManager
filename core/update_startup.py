# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def acknowledge_update_startup(version: str) -> bool:
    token = os.environ.get("CONGU_UPDATE_TOKEN", "")
    expected = os.environ.get("CONGU_UPDATE_VERSION", "")
    marker = os.environ.get("CONGU_UPDATE_MARKER", "")
    if not re.fullmatch(r"[0-9a-f]{64}", token) or version != expected or not os.path.isabs(marker):
        return False
    marker_path = Path(marker)
    payload = {"token": token, "version": version, "pid": os.getpid(),
               "executable": os.path.realpath(sys.executable)}
    fd, temporary = tempfile.mkstemp(prefix=".startup-", dir=str(marker_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, marker_path)
        for name in ("CONGU_UPDATE_TOKEN", "CONGU_UPDATE_VERSION", "CONGU_UPDATE_MARKER"):
            os.environ.pop(name, None)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return True


def build_startup_probe() -> str:
    return r'''param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$Marker,
    [Parameter(Mandatory=$true)][string]$Token,
    [Parameter(Mandatory=$true)][string]$Version,
    [int]$TimeoutSeconds = 30
)
$ErrorActionPreference = 'Stop'
$child = $null
try {
    Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    $env:CONGU_UPDATE_TOKEN = $Token
    $env:CONGU_UPDATE_VERSION = $Version
    $env:CONGU_UPDATE_MARKER = $Marker
    $child = Start-Process -FilePath $Executable -WorkingDirectory (Split-Path -Parent $Executable) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $child.Refresh()
        if ($child.HasExited) { exit 31 }
        if (Test-Path -LiteralPath $Marker) {
            try {
                $ack = Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json
                $samePath = [string]::Equals([IO.Path]::GetFullPath([string]$ack.executable), [IO.Path]::GetFullPath($Executable), [StringComparison]::OrdinalIgnoreCase)
                if ($ack.token -ceq $Token -and $ack.version -ceq $Version -and [int]$ack.pid -eq $child.Id -and $samePath) {
                    $child.Refresh()
                    if (-not $child.HasExited) { exit 0 }
                }
            } catch { }
        }
        Start-Sleep -Milliseconds 200
    }
    $child.Kill()
    $child.WaitForExit()
    exit 32
} catch {
    if ($null -ne $child) {
        try {
            $child.Refresh()
            if (-not $child.HasExited) {
                $child.Kill()
                $child.WaitForExit()
            }
        } catch { exit 34 }
    }
    exit 33
}
'''
