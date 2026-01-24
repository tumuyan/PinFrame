# 1. 启动 Xvfb 并指定显示端口（例如 :99）
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99

# 2. 运行你的 Python GUI 程序 (后台运行)
python main.py &

# 3. 等待几秒让界面加载
sleep 5

# 4. 截图
scrot dev/tmp_screenshot.png

# 5. 杀掉进程 (可选)
pkill -f "python main.py"
killall Xvfb