#!/bin/bash

# noVNC 启动脚本
# 用于在无桌面环境的Linux系统上运行PyQt6 GUI程序

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "novnc-start: starting"
echo -e "${GREEN}=== 启动 noVNC 环境 ===${NC}"

# 复用统一的 Xvfb 就绪逻辑（dev/start_xvfb.sh 负责检测/拉起 :99，
# 分辨率统一为 1920x1080x24，避免与各脚本重复实现且尺寸不一致）。
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"${SCRIPT_DIR}/start_xvfb.sh" :99

# 设置 DISPLAY 环境变量
export DISPLAY=:99
echo "DISPLAY 环境变量设置为: $DISPLAY"

# 刷新字体缓存 (确保新安装的中文字体生效)
echo "刷新字体缓存..."
fc-cache -fv > /dev/null 2>&1

# 启动 x11vnc
if pgrep -x "x11vnc" > /dev/null; then
    echo -e "${YELLOW}x11vnc 已经在运行${NC}"
else
    echo "启动 x11vnc 服务器..."
    # setsid 脱离调用方进程树，避免被 VS Code 任务结束时的进程清理杀掉
    setsid x11vnc -display :99 -forever -shared -nopw -nowf -nowcr -noxdamage -rfbport 5900 -timeout 900 >/dev/null 2>&1 < /dev/null &

    # 等待 x11vnc 启动并监听端口
    sleep 3

    if ! pgrep -x "x11vnc" > /dev/null; then
        echo -e "${RED}x11vnc 启动失败！${NC}"
        exit 1
    fi

    # 检查端口是否监听
    if ! netstat -tln 2>/dev/null | grep -q ':5900' && ! ss -tln 2>/dev/null | grep -q ':5900'; then
        echo -e "${RED}x11vnc 端口 5900 未监听！${NC}"
        exit 1
    fi
    echo -e "${GREEN}x11vnc 启动成功 (端口 5900)${NC}"
fi

# 启动 websockify (连接 noVNC 和 x11vnc)
if pgrep -f "websockify" > /dev/null; then
    echo -e "${YELLOW}websockify 已经在运行${NC}"
else
    echo "启动 websockify..."
    # setsid 脱离调用方进程树
    setsid websockify --web=/usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 < /dev/null &

    sleep 1

    if ! pgrep -f "websockify" > /dev/null; then
        echo -e "${RED}websockify 启动失败！${NC}"
        exit 1
    fi
    echo -e "${GREEN}websockify 启动成功 (端口 6080)${NC}"
fi

# 打印就绪标记，供 VS Code tasks.json 的 problemMatcher 识别
echo "novnc-start: ready"

# 以前台阻塞方式保持任务存活（等待终止信号），
# 使 VS Code 的 background 任务不会立即结束、也不会清理掉 noVNC 进程。
echo "noVNC 运行中，按任务停止按钮可结束（停止 noVNC 任务会一并清理进程）。"
wait

# 启动 PyQt6 应用
# if pgrep -f "python.*main.py" > /dev/null; then
#     echo -e "${YELLOW}PyQt6 应用已经在运行${NC}"
# else
#     echo "启动 PyQt6 应用..."
#     cd /workspace
#     python main.py &
#     echo -e "${GREEN}PyQt6 应用启动成功${NC}"
# fi

echo ""
echo -e "${GREEN}=== 启动完成 ===${NC}"
echo "noVNC 访问地址: http://localhost:6080/vnc.html"
echo "如果需要从外部访问，请使用: http://<服务器IP>:6080/vnc.html"
echo ""
echo "如需查看进程状态，运行: ps aux | grep -E 'Xvfb|x11vnc|websockify'"
echo "如需停止服务，运行: ./novnc_stop.sh"
