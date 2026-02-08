#!/usr/bin/env bash
# ============================================================
# Feishu Reader — Environment Setup (macOS / Linux)
# 飞书文档提取工具 — 环境初始化
#
# Auto-detects and installs: Python 3.8+, Chrome, pip deps
# Uses virtual environment (.venv) — won't pollute system Python
# Supports China mirror fallback for pip and Chrome
# ============================================================
set -euo pipefail

VENV_DIR=".venv"
MIN_PY_MAJOR=3
MIN_PY_MINOR=8
CDN_BASE="http://dl.hutiefang.com"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }
ask()   { echo -e "${YELLOW}[?]${NC} $*"; }

echo "============================================================"
echo "  Feishu Reader — Setup / 飞书文档提取工具 — 环境初始化"
echo "  System / 系统: $(uname -s) $(uname -m)"
echo "============================================================"
echo ""

# ============================================================
# 1. Python
# ============================================================
echo "[1/3] Checking Python / 检查 Python..."

find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge "$MIN_PY_MAJOR" ] && [ "$minor" -ge "$MIN_PY_MINOR" ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_CMD=$(find_python || echo "")

if [ -z "$PYTHON_CMD" ]; then
    warn "Python >=${MIN_PY_MAJOR}.${MIN_PY_MINOR} not found / 未找到合适的 Python"
    ask "Install Python automatically? / 自动安装 Python？(y/n)"
    read -r answer
    if [[ "$answer" =~ ^[Yy] ]]; then
        if [ "$(uname -s)" = "Darwin" ]; then
            if command -v brew &>/dev/null; then
                echo "  Installing via brew... / 通过 brew 安装..."
                brew install python@3.12 || brew install python3
            else
                warn "Homebrew not found. Downloading Python installer..."
                warn "未找到 Homebrew，下载 Python 安装包..."
                PKG_URL="https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg"
                PKG_PATH="/tmp/python3.pkg"
                curl -fSL --connect-timeout 30 -o "$PKG_PATH" "$PKG_URL" 2>/dev/null || \
                    curl -fSL --connect-timeout 30 -o "$PKG_PATH" "https://registry.npmmirror.com/-/binary/python/3.12.8/python-3.12.8-macos11.pkg" 2>/dev/null
                if [ -f "$PKG_PATH" ]; then
                    sudo installer -pkg "$PKG_PATH" -target /
                    rm -f "$PKG_PATH"
                else
                    err "Download failed / 下载失败"
                    echo "  Manual install / 手动安装: https://www.python.org/downloads/"
                    exit 1
                fi
            fi
        else
            # Linux
            if command -v apt-get &>/dev/null; then
                sudo apt-get update -qq
                sudo apt-get install -y python3 python3-venv python3-pip
            elif command -v yum &>/dev/null; then
                sudo yum install -y python3 python3-pip
            elif command -v dnf &>/dev/null; then
                sudo dnf install -y python3 python3-pip
            else
                err "Cannot auto-install Python on this system"
                echo "  Please install Python 3.8+ manually"
                exit 1
            fi
        fi
        PYTHON_CMD=$(find_python || echo "")
        if [ -z "$PYTHON_CMD" ]; then
            err "Python installation failed / Python 安装失败"
            exit 1
        fi
    else
        echo "  Please install Python 3.8+ manually / 请手动安装 Python 3.8+"
        echo "  https://www.python.org/downloads/"
        exit 1
    fi
fi

PY_VER=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
info "Python $PY_VER ($PYTHON_CMD)"

# Ensure venv module
if ! "$PYTHON_CMD" -c "import venv" &>/dev/null; then
    warn "venv module missing, installing... / venv 模块缺失，安装中..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y python3-venv
    fi
fi

# ============================================================
# 2. Chrome
# ============================================================
echo ""
echo "[2/3] Checking Chrome / 检查 Chrome..."

find_chrome() {
    if [ "$(uname -s)" = "Darwin" ]; then
        for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
            [ -f "$c" ] && echo "$c" && return 0
        done
    else
        for c in google-chrome google-chrome-stable chromium-browser chromium; do
            command -v "$c" &>/dev/null && echo "$c" && return 0
        done
    fi
    return 1
}

CHROME_PATH=$(find_chrome || echo "")

if [ -n "$CHROME_PATH" ]; then
    info "Chrome: $CHROME_PATH"
else
    warn "Chrome not found / 未找到 Chrome"
    ask "Install Chrome automatically? / 自动安装 Chrome？(y/n)"
    read -r answer
    if [[ "$answer" =~ ^[Yy] ]]; then
        if [ "$(uname -s)" = "Darwin" ]; then
            if command -v brew &>/dev/null; then
                brew install --cask google-chrome 2>/dev/null && info "Chrome installed via brew" || {
                    warn "brew failed, downloading dmg... / brew 失败，下载 dmg..."
                    DMG="/tmp/chrome.dmg"
                    curl -fSL --connect-timeout 30 -o "$DMG" "https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg"
                    hdiutil attach "$DMG" -quiet
                    cp -R "/Volumes/Google Chrome/Google Chrome.app" /Applications/ 2>/dev/null || \
                        sudo cp -R "/Volumes/Google Chrome/Google Chrome.app" /Applications/
                    hdiutil detach "/Volumes/Google Chrome" -quiet 2>/dev/null || true
                    rm -f "$DMG"
                    info "Chrome installed / Chrome 已安装"
                }
            else
                DMG="/tmp/chrome.dmg"
                curl -fSL --connect-timeout 30 -o "$DMG" "https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg"
                hdiutil attach "$DMG" -quiet
                cp -R "/Volumes/Google Chrome/Google Chrome.app" /Applications/ 2>/dev/null || \
                    sudo cp -R "/Volumes/Google Chrome/Google Chrome.app" /Applications/
                hdiutil detach "/Volumes/Google Chrome" -quiet 2>/dev/null || true
                rm -f "$DMG"
                info "Chrome installed / Chrome 已安装"
            fi
        else
            if command -v apt-get &>/dev/null; then
                DEB="/tmp/chrome.deb"
                curl -fSL --connect-timeout 15 -o "$DEB" "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" 2>/dev/null || \
                    curl -fSL --connect-timeout 15 -o "$DEB" "${CDN_BASE}/google-chrome-stable_current_amd64.deb" 2>/dev/null || true
                if [ -f "$DEB" ] && [ -s "$DEB" ]; then
                    sudo apt-get install -y "$DEB" 2>/dev/null || { sudo dpkg -i "$DEB"; sudo apt-get install -f -y; }
                    rm -f "$DEB"
                else
                    warn "Chrome download failed, trying chromium... / Chrome 下载失败，尝试 chromium..."
                    sudo apt-get update -qq && sudo apt-get install -y chromium-browser 2>/dev/null || \
                        sudo apt-get install -y chromium 2>/dev/null || \
                        sudo snap install chromium 2>/dev/null || true
                fi
            elif command -v yum &>/dev/null || command -v dnf &>/dev/null; then
                RPM="/tmp/chrome.rpm"
                curl -fSL --connect-timeout 15 -o "$RPM" "https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm" 2>/dev/null || \
                    curl -fSL --connect-timeout 15 -o "$RPM" "${CDN_BASE}/google-chrome-stable_current_x86_64.rpm" 2>/dev/null || true
                if [ -f "$RPM" ] && [ -s "$RPM" ]; then
                    sudo yum localinstall -y "$RPM" 2>/dev/null || sudo dnf install -y "$RPM"
                    rm -f "$RPM"
                else
                    warn "Chrome download failed, trying chromium... / Chrome 下载失败，尝试 chromium..."
                    sudo dnf install -y chromium 2>/dev/null || sudo yum install -y chromium 2>/dev/null || true
                fi
            else
                err "Cannot auto-install Chrome on this system"
                echo "  https://www.google.com/chrome/"
                exit 1
            fi
            CHROME_PATH=$(find_chrome || echo "")
            [ -n "$CHROME_PATH" ] && info "Chrome installed / Chrome 已安装"
        fi
        CHROME_PATH=$(find_chrome || echo "")
        [ -z "$CHROME_PATH" ] && { err "Chrome install failed / Chrome 安装失败"; exit 1; }
    else
        echo "  Please install Chrome manually / 请手动安装 Chrome"
        echo "  https://www.google.com/chrome/"
        exit 1
    fi
fi

# ============================================================
# 3. Virtual environment + dependencies
# ============================================================
echo ""
echo "[3/3] Setting up virtual environment / 配置虚拟环境..."

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    info "Virtual environment created / 虚拟环境已创建: $VENV_DIR"
else
    info "Virtual environment exists / 虚拟环境已存在: $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

pip_install() {
    local args="$*"
    if pip install --timeout 15 $args -q 2>/dev/null; then return 0; fi
    warn "PyPI timeout, trying China mirrors... / 官方源超时，尝试国内镜像..."
    if pip install --timeout 15 -i "https://pypi.tuna.tsinghua.edu.cn/simple" --trusted-host "pypi.tuna.tsinghua.edu.cn" $args -q 2>/dev/null; then
        info "Installed via Tsinghua mirror / 清华镜像安装成功"; return 0
    fi
    if pip install --timeout 15 -i "https://mirrors.aliyun.com/pypi/simple" --trusted-host "mirrors.aliyun.com" $args -q 2>/dev/null; then
        info "Installed via Aliyun mirror / 阿里云镜像安装成功"; return 0
    fi
    err "All sources failed / 所有源均失败"
    return 1
}

pip_install --upgrade pip
if ! pip_install -r requirements.txt; then
    warn "Trying CDN fallback for websocket-client... / 尝试 CDN 兜底..."
    WHL="/tmp/websocket_client.whl"
    if curl -fSL --connect-timeout 15 -o "$WHL" "${CDN_BASE}/websocket_client-1.9.0-py3-none-any.whl" 2>/dev/null && [ -s "$WHL" ]; then
        pip install "$WHL" -q && info "Installed via CDN / CDN 安装成功" || { err "CDN install failed"; exit 1; }
        rm -f "$WHL"
    else
        err "CDN download failed / CDN 下载失败"; exit 1
    fi
fi

# Verify
"$PYTHON_CMD" -c "import websocket; print(f'[OK] websocket-client {websocket.__version__}')" || { err "Dependency check failed"; exit 1; }

echo ""
echo "============================================================"
info "✅ Setup complete / 环境初始化完成"
echo ""
echo "Usage / 使用方法:"
echo "  .venv/bin/python3 feishu_skill.py status              # Check env / 环境检查"
echo "  .venv/bin/python3 extract_feishu.py login              # Login / 登录"
echo "  .venv/bin/python3 feishu_skill.py extract '<URL>'      # Extract / 提取"
echo "============================================================"
