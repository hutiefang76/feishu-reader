@echo off
chcp 65001 >nul 2>&1
REM 一键运行: 自动检查环境 → 激活虚拟环境 → 执行提取

if not exist ".venv" (
    echo [信息] 首次运行，初始化环境...
    call setup.bat
)

call .venv\Scripts\activate.bat
python extract_feishu.py %*
