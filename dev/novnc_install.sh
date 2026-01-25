#!/bin/bash

# noVNC 安装脚本
# 安装运行 noVNC 所需的所有依赖

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 安装 noVNC 依赖 ===${NC}"

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}请使用 sudo 运行此脚本${NC}"
    echo "命令: sudo ./novnc_install.sh"
    exit 1
fi

echo "更新包列表..."
apt update

echo ""
echo "安装 Xvfb (虚拟显示服务器)..."
apt install -y xvfb

echo "安装 x11vnc (VNC 服务器)..."
apt install -y x11vnc

echo "安装 websockify (WebSocket 代理)..."
apt install -y python3-websockify

echo "安装 noVNC (Web VNC 客户端)..."
apt install -y novnc

echo "安装 net-tools (用于端口检查)..."
apt install -y net-tools

echo ""
echo -e "${GREEN}=== 安装完成 ===${NC}"

# 验证安装
echo ""
echo "验证安装..."
command -v Xvfb >/dev/null 2>&1 && echo -e "${GREEN}✓ Xvfb${NC}" || echo -e "${RED}✗ Xvfb${NC}"
command -v x11vnc >/dev/null 2>&1 && echo -e "${GREEN}✓ x11vnc${NC}" || echo -e "${RED}✗ x11vnc${NC}"
command -v websockify >/dev/null 2>&1 && echo -e "${GREEN}✓ websockify${NC}" || echo -e "${RED}✗ websockify${NC}"
[ -d /usr/share/novnc ] && echo -e "${GREEN}✓ noVNC${NC}" || echo -e "${RED}✗ noVNC${NC}"

echo ""
echo "现在可以运行: ./novnc_start.sh"
