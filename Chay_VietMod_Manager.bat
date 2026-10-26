@echo off
setlocal
chcp 65001 >nul
title CO NGU - Trinh Quan Ly Game Viet Hoa Pro
cd /d "%~dp0"

echo ========================================================
echo        // CO NGU v2.0 - KHO GAME VIET HOA
echo ========================================================
echo.

:: 1. Uu tien khoi dong tu ma nguon moi nhat neu may da co VirtualEnv Python
if exist "..\.venv\Scripts\python.exe" (
    if exist "app.py" (
        echo [*] Khoi dong CO NGU tu ma nguon cap nhat voi VirtualEnv...
        "..\.venv\Scripts\python.exe" "app.py"
        exit /b
    )
)
if exist ".venv\Scripts\python.exe" (
    if exist "app.py" (
        echo [*] Khoi dong CO NGU tu ma nguon cap nhat voi VirtualEnv...
        ".venv\Scripts\python.exe" "app.py"
        exit /b
    )
)

:: 2. Kiem tra xem co file thuc thi Portable san khong
if exist "VietModHub.exe" (
    echo [*] Dang khoi chay CO NGU Standalone...
    start "" "VietModHub.exe"
    exit /b
)

if exist "VietModHub_Portable\VietModHub.exe" (
    echo [*] Phat hien ban Standalone Portable! Dang khoi chay...
    cd "VietModHub_Portable"
    start "" "VietModHub.exe"
    exit /b
)

if exist "dist\VietModHub\VietModHub.exe" (
    echo [*] Phat hien ban build! Dang khoi chay...
    cd "dist\VietModHub"
    start "" "VietModHub.exe"
    exit /b
)

:: 2. Neu khong co file .exe (dang chay tu ma nguon GitHub), kiem tra Python
echo [*] Dang kiem tra moi truong Python runtime...

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [!] CANH BAO: Ban dang chay tu ma nguon GitHub ma may tinh chua cai Python!
    echo [!] Vui long cai dat Python 3.10 hoac 3.11 tu https://www.python.org/ (nho tich vao "Add Python to PATH")
    echo [!] Hoac tai ban CoNgu_v2.0_Portable.zip tu muc Releases tren GitHub:
    echo     https://github.com/tuan3991/CoNgu-VietModManager/releases
    echo.
    pause
    exit /b
)

:: Kiem tra va tu dong cai dat cac thu vien Python can thiet neu thieu
python -c "import bottle, webview, cryptography" >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [*] Phat hien thieu thu vien can thiet de khoi chay CO NGU.
    echo [*] Dang tu dong cai dat cac thu vien phu hop (bottle, pywebview, cryptography, pythonnet, Pillow)...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install bottle pywebview cryptography pythonnet Pillow
    echo [*] Cai dat thu vien hoan tat!
    echo.
)

if exist "..\.venv\Scripts\python.exe" (
    echo [*] Khoi dong voi VirtualEnv Python...
    "..\.venv\Scripts\python.exe" "app.py"
) else (
    echo [*] Khoi dong voi Python he thong...
    python "app.py"
)

if %errorlevel% neq 0 (
    echo.
    echo [!] Khoi dong that bai. Ma loi: %errorlevel%
    echo [!] Kiem tra file log tai: %%APPDATA%%\VietModHub\startup.log
    pause
)
