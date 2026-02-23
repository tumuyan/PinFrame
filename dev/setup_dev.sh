#!/bin/bash
# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 获取项目根目录（脚本所在目录的上一级）
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 在项目根目录执行 setup.sh（需要访问 requirements.txt）
"$SCRIPT_DIR/setup.sh"
"$SCRIPT_DIR/install_fonts.sh"
"$SCRIPT_DIR/novnc_install.sh"

echo "现在可以运行: source venv/bin/activate"
echo "现在可以运行: export DISPLAY=:99 && python main.py"
echo "启动后可以运行: pkill -f \"python.*main.py\""