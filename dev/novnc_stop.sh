#!/bin/bash

# noVNC 停止脚本
# 用于清理所有相关进程

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== 停止 noVNC 环境 ===${NC}"

# 停止 websockify
if pgrep -f "websockify" > /dev/null; then
    echo "停止 websockify..."
    pkill -f "websockify"
    echo -e "${GREEN}websockify 已停止${NC}"
else
    echo "websockify 未运行"
fi

# 停止 x11vnc
if pgrep -x "x11vnc" > /dev/null; then
    echo "停止 x11vnc..."
    pkill -x "x11vnc"
    echo -e "${GREEN}x11vnc 已停止${NC}"
else
    echo "x11vnc 未运行"
fi

# 停止 Xvfb
if pgrep -x "Xvfb" > /dev/null; then
    echo "停止 Xvfb..."
    pkill -x "Xvfb"
    echo -e "${GREEN}Xvfb 已停止${NC}"
else
    echo "Xvfb 未运行"
fi

# 停止 PyQt6 应用
if pgrep -f "python.*main.py" > /dev/null; then
    echo "停止 PyQt6 应用..."
    pkill -f "python.*main.py"
    echo -e "${GREEN}PyQt6 应用已停止${NC}"
else
    echo "PyQt6 应用未运行"
fi

echo ""
echo -e "${GREEN}=== 停止完成 ===${NC}"
echo "所有进程已清理"
