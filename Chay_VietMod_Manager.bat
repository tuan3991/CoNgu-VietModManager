@echo off
chcp 65001 >nul
title CO NGU - Trinh Quan Ly Game Viet Hoa Pro
cd /d "%~dp0"

echo ========================================================
echo        // CO NGU v2.0 - KHO GAME VIET HOA
echo ========================================================
echo.

if exist "VietModHub_Portable\VietModHub.exe" (
    echo [✓] Phat hien ban Standalone Portable! Dang khoi chay...
    start "" "VietModHub_Portable\VietModHub.exe"
    exit /b
)

if exist "dist\VietModHub\VietModHub.exe" (
    echo [✓] Phat hien ban build! Dang khoi chay...
    start "" "dist\VietModHub\VietModHub.exe"
    exit /b
)

echo Dang khoi dong bang Python runtime...
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" "app.py"
) else (
    python "app.py"
)

pause
