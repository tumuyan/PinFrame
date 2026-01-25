#!/bin/bash

# 中文字体安装脚本
# 用于安装支持中文显示的字体，解决 PyQt6 应用中文显示为空心方块的问题

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 安装中文字体 ===${NC}"

# 检查是否以 root 权限运行
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}注意: 建议使用 root 权限运行此脚本${NC}"
    echo "如果安装失败，请尝试: sudo $0"
fi

# 更新包管理器
echo "更新包管理器..."
apt-get update -qq

# 安装中文字体
echo "安装中文字体包..."
apt-get install -y \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fontconfig

# 刷新字体缓存
echo "刷新字体缓存..."
fc-cache -fv > /dev/null 2>&1

# 验证字体是否安装成功
echo -e "${GREEN}=== 验证字体安装 ===${NC}"

# 检查已安装的中文字体
CHINESE_FONTS=$(fc-list :lang=zh-cn | head -5)

if [ -n "$CHINESE_FONTS" ]; then
    echo -e "${GREEN}中文字体安装成功！${NC}"
    echo ""
    echo "已安装的中文字体包括:"
    fc-list :lang=zh-cn 2>/dev/null | sed 's/\/.*\///g' | sed 's/:[^:]*$//' | sort | uniq
    echo ""
    echo "请重启应用程序以使字体生效。"
else
    echo -e "${RED}警告: 未检测到中文字体，可能安装失败${NC}"
    echo "请检查错误信息并重试"
    exit 1
fi

echo -e "${GREEN}=== 安装完成 ===${NC}"
