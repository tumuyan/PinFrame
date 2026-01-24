#!/bin/bash

# noVNC 启动脚本
# 用于在无桌面环境的Linux系统上运行PyQt6 GUI程序

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 启动 noVNC 环境 ===${NC}"

# 检查是否已经在运行
if pgrep -x "Xvfb" > /dev/null; then
    echo -e "${YELLOW}Xvfb 已经在运行${NC}"
else
    # 启动 Xvfb 虚拟显示器
    # 分辨率 1440x900，颜色深度 24
    echo "启动 Xvfb 虚拟显示器 (1440x900)..."
    Xvfb :99 -screen 0 1440x900x24 -ac +extension GLX +render -noreset &

    # 等待 Xvfb 启动
    sleep 2

    if ! pgrep -x "Xvfb" > /dev/null; then
        echo -e "${RED}Xvfb 启动失败！${NC}"
        exit 1
    fi
    echo -e "${GREEN}Xvfb 启动成功${NC}"
fi

# 设置 DISPLAY 环境变量
export DISPLAY=:99
echo "DISPLAY 环境变量设置为: $DISPLAY"

# 启动 x11vnc
if pgrep -x "x11vnc" > /dev/null; then
    echo -e "${YELLOW}x11vnc 已经在运行${NC}"
else
    echo "启动 x11vnc 服务器..."
    x11vnc -display :99 -forever -shared -nopw -nowf -nowcr -noxdamage -rfbport 5900 -timeout 900 &

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
    websockify --web=/usr/share/novnc 6080 localhost:5900 &

    sleep 1

    if ! pgrep -f "websockify" > /dev/null; then
        echo -e "${RED}websockify 启动失败！${NC}"
        exit 1
    fi
    echo -e "${GREEN}websockify 启动成功 (端口 6080)${NC}"
fi

# 启动 PyQt6 应用
if pgrep -f "python.*main.py" > /dev/null; then
    echo -e "${YELLOW}PyQt6 应用已经在运行${NC}"
else
    echo "启动 PyQt6 应用..."
    cd /workspace
    python main.py &
    echo -e "${GREEN}PyQt6 应用启动成功${NC}"
fi

echo ""
echo -e "${GREEN}=== 启动完成 ===${NC}"
echo "noVNC 访问地址: http://localhost:6080/vnc.html"
echo "如果需要从外部访问，请使用: http://<服务器IP>:6080/vnc.html"
echo ""
echo "如需查看进程状态，运行: ps aux | grep -E 'Xvfb|x11vnc|websockify'"
echo "如需停止服务，运行: ./novnc_stop.sh"
