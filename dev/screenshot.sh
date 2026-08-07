# 1. 复用统一的 Xvfb 就绪逻辑（不自行拉起、也不 killall，避免与
#    noVNC / 运行中的显示冲突；分辨率统一为 1920x1080x24）。
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"${SCRIPT_DIR}/start_xvfb.sh" :99
export DISPLAY=:99

# 2. 运行你的 Python GUI 程序 (后台运行)
"${SCRIPT_DIR}/../venv/bin/python" main.py &

# 3. 等待几秒让界面加载
sleep 5

# 4. 截图
scrot dev/tmp_screenshot.png

# 5. 只清理本次启动的 python 进程（不动 Xvfb / noVNC）
pkill -f "python main.py"