@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
REM ============================================================
REM Feishu Reader — Environment Setup (Windows)
REM Auto-detects: Python 3.8+, Chrome, pip deps
REM Uses .venv — won't pollute system Python
REM ============================================================

set VENV_DIR=.venv

echo ============================================================
echo   Feishu Reader — Setup / 环境初始化 (Windows)
echo ============================================================
echo.

REM === 1. Python ===
echo [1/3] Checking Python / 检查 Python...
set PYTHON_CMD=

where python >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PY_VER=%%v
    for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
        if %%a geq 3 if %%b geq 8 (
            set PYTHON_CMD=python
            echo [OK] Python !PY_VER!
            goto :python_ok
        )
    )
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    echo [OK] Found python3
    goto :python_ok
)

echo [!] Python 3.8+ not found / 未找到 Python 3.8+
echo.
set /p INSTALL_PY="Install Python automatically? / 自动安装？(y/n): "
if /i "!INSTALL_PY!" neq "y" (
    echo   Please install Python 3.8+: https://www.python.org/downloads/
    exit /b 1
)

REM Try winget first
where winget >nul 2>&1
if %errorlevel% equ 0 (
    echo   Installing via winget...
    winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Python installed via winget
        set PYTHON_CMD=python
        goto :python_ok
    )
)

REM Try choco
where choco >nul 2>&1
if %errorlevel% equ 0 (
    echo   Installing via choco...
    choco install python312 -y --no-progress 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Python installed via choco
        set PYTHON_CMD=python
        goto :python_ok
    )
)

echo [ERROR] Auto-install failed. Please install manually:
echo   https://www.python.org/downloads/
exit /b 1

:python_ok

REM === 2. Chrome ===
echo.
echo [2/3] Checking Chrome / 检查 Chrome...
set CHROME_FOUND=0
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1

if %CHROME_FOUND% equ 1 (
    echo [OK] Chrome found
    goto :chrome_ok
)

echo [!] Chrome not found / 未找到 Chrome
set /p INSTALL_CH="Install Chrome automatically? / 自动安装？(y/n): "
if /i "!INSTALL_CH!" neq "y" (
    echo   Please install Chrome: https://www.google.com/chrome/
    exit /b 1
)

where winget >nul 2>&1
if %errorlevel% equ 0 (
    echo   Installing via winget...
    winget install --id Google.Chrome -e --silent --accept-source-agreements --accept-package-agreements 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Chrome installed via winget
        goto :chrome_ok
    )
)

where choco >nul 2>&1
if %errorlevel% equ 0 (
    echo   Installing via choco...
    choco install googlechrome -y --no-progress 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Chrome installed via choco
        goto :chrome_ok
    )
)

echo [ERROR] Auto-install failed. Please install manually:
echo   https://www.google.com/chrome/
exit /b 1

:chrome_ok

REM === 3. Virtual environment + deps ===
echo.
echo [3/3] Setting up virtual environment / 配置虚拟环境...

if not exist "%VENV_DIR%" (
    %PYTHON_CMD% -m venv %VENV_DIR%
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)
call %VENV_DIR%\Scripts\activate.bat

echo   Installing dependencies / 安装依赖...
call :pip_install "-r requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Dependency install failed / 依赖安装失败
    exit /b 1
)

echo.
echo ============================================================
echo [OK] Setup complete / 环境初始化完成
echo.
echo Usage / 使用方法:
echo   .venv\Scripts\python.exe feishu_skill.py status
echo   .venv\Scripts\python.exe extract_feishu.py login
echo   .venv\Scripts\python.exe feishu_skill.py extract "URL"
echo ============================================================
endlocal
exit /b 0

:pip_install
set "PKG=%~1"
pip install --timeout 15 %PKG% -q 2>nul
if %errorlevel% equ 0 exit /b 0
echo [!] PyPI timeout, trying mirrors... / 尝试镜像...
pip install --timeout 15 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn %PKG% -q 2>nul
if %errorlevel% equ 0 ( echo [OK] Tsinghua mirror & exit /b 0 )
pip install --timeout 15 -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com %PKG% -q 2>nul
if %errorlevel% equ 0 ( echo [OK] Aliyun mirror & exit /b 0 )
echo [ERROR] All sources failed
exit /b 1
