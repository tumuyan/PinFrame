#!/bin/bash
#切换工作路径到当前脚本所在目录
cd "$(dirname "$0")"

./setup.sh
./install_fonts.sh
./novnc_install.sh

echo "现在可以运行: source venv/bin/activate"
echo "现在可以运行: export DISPLAY=:99 && python main.py"
echo "启动后可以运行: pkill -f \"python.*main.py\""