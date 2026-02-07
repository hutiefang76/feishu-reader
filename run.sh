#!/usr/bin/env bash
# 一键运行: 自动检查环境 → 激活虚拟环境 → 执行提取
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 检查虚拟环境
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "[信息] 首次运行，初始化环境..."
    bash "$SCRIPT_DIR/setup.sh"
fi

# 激活虚拟环境
source "$SCRIPT_DIR/.venv/bin/activate"

# 传递所有参数给 extract_feishu.py
python "$SCRIPT_DIR/extract_feishu.py" "$@"
