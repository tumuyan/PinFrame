#!/bin/bash
# 流水线环境搭建（云原生构建 CI 用；幂等，可重复执行）。
#
# 用法：
#   bash dev/setup_ci.sh                  # 系统依赖 + venv + Python 依赖 + 像素基线
#   bash dev/setup_ci.sh --force-baseline # 强制重建像素基线
#   bash dev/setup_ci.sh --help
#
# 退出码：0 = 就绪；1 = 安装失败；2 = 参数错误或清单文件缺失。
#
# ---------------------------------------------------------------------------
# 与 dev/setup.sh 的分工
# ---------------------------------------------------------------------------
# 系统包清单只有一份：dev/qt_deps.txt，两份脚本都读它。业务侧的差异是：
#   - dev/setup.sh   面向云原生开发环境：装 python3 / pip 本体，输出给人看。
#   - dev/setup_ci.sh面向流水线：非交互（DEBIAN_FRONTEND=noninteractive）、
#                    幂等（venv 已存在就复用）、并在末尾生成像素基线。
#
# ---------------------------------------------------------------------------
# 为什么这个脚本要顺带生成像素基线（关键，别删这一段）
# ---------------------------------------------------------------------------
# dev/tmp_baseline/ 在 .gitignore 中，基线【不入库】。而 run_all_checks.sh 的第 4 项
# 是 `transform_baseline.py --compare`，它拿 dev/tmp_baseline/hashes.json 做比对；
# 该文件缺失时，run_all_checks.sh 会以退出码 2 直接报"前置依赖缺失"并拒绝开始
# （这是刻意的：--compare 在基线缺失时会静默写一条新基线然后返回 0，是假通过）。
# 所以全新容器里必须先有人生成一份基线，这件事只能由搭建脚本来做。
#
# 但必须清楚 CI 里这个比对的语义：
#   【它比的是同一容器内的两次渲染，验证的是渲染确定性】——没有随机源、没有未
#   初始化内存、没有与执行顺序相关的漂移。它【不是】"与团队基线一致"：基线不入库
#   正是因为 PIL / Qt 的版本差异会让跨机器比对先炸，那是纯粹的假阳性。
#   想验证"我这次改动是否改变了渲染"，只能在【同一台机器】上按
#   "改动前跑一次不带 --compare、改动后跑 --compare" 的流程做。
#
# ---------------------------------------------------------------------------
# 不需要 Xvfb / noVNC
# ---------------------------------------------------------------------------
# 所有测试脚本（transform_baseline / verify_* / smoke_*）都在开头
# `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`，用 offscreen 平台插件跑，
# 因此 CI 里不需要虚拟显示。xvfb / noVNC / 中文字体是【人工】用 noVNC 验收时才需要的，
# 装在 CI 里只会让每次 push 白白多下几百 MB。

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

FORCE_BASELINE=0
for arg in "$@"; do
    case "$arg" in
        --force-baseline) FORCE_BASELINE=1 ;;
        -h|--help)
            sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "未知参数: $arg（用 --help 查看用法）" >&2
            exit 2
            ;;
    esac
done

export DEBIAN_FRONTEND=noninteractive

# ---- 1. 系统依赖 ------------------------------------------------------------
DEPS_FILE="$REPO_ROOT/dev/qt_deps.txt"
if [ ! -f "$DEPS_FILE" ]; then
    echo "setup_ci: 缺少依赖清单 $DEPS_FILE" >&2
    exit 2
fi

PACKAGES=""
while read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    for pkg in $line; do
        PACKAGES="$PACKAGES $pkg"
    done
done < "$DEPS_FILE"

if [ -z "$PACKAGES" ]; then
    echo "setup_ci: $DEPS_FILE 解析后为空，拒绝继续（否则会静默跳过装依赖）。" >&2
    exit 2
fi

echo "setup_ci: 安装系统依赖"
apt-get update -qq
# 刻意不加 -qq：apt 的进度输出同时充当心跳，避免 Job 的"无输出超时"误杀。
apt-get install -y --no-install-recommends $PACKAGES
rm -rf /var/lib/apt/lists/*

# ---- 2. 虚拟环境 ------------------------------------------------------------
# 放在仓库根的 venv/ —— run_all_checks.sh 会自动优先用它（.gitignore 已忽略）。
PY="${PYTHON:-python3}"
if [ ! -x "$REPO_ROOT/venv/bin/python" ]; then
    echo "setup_ci: 创建 venv ($PY -m venv venv)"
    if ! "$PY" -m venv "$REPO_ROOT/venv" 2>/dev/null; then
        # 官方 python 镜像自带 venv；Debian 系的 distro python 需要单独装。
        echo "setup_ci: venv 模块不可用，补装 python3-venv / python3-pip"
        apt-get update -qq
        apt-get install -y --no-install-recommends python3-venv python3-pip
        rm -rf /var/lib/apt/lists/*
        "$PY" -m venv "$REPO_ROOT/venv"
    fi
else
    echo "setup_ci: 复用已存在的 venv"
fi

VENV_PY="$REPO_ROOT/venv/bin/python"
"$VENV_PY" -V

# ---- 3. Python 依赖 ---------------------------------------------------------
echo "setup_ci: 安装 requirements.txt"
"$VENV_PY" -m pip install --disable-pip-version-check -r "$REPO_ROOT/requirements.txt"

# ---- 4. 环境自检 ------------------------------------------------------------
# 这一步的价值：把"Qt 插件加载失败"这类只在运行时才暴露的问题，提前到搭建阶段报出来。
# 否则它会伪装成后面某个测试脚本的莫名 abort（Qt 把 paintEvent 内的异常升级为
# abort()，退出码 134，日志里没有 Python 回溯）。
echo "setup_ci: 自检 offscreen 平台可用"
"$VENV_PY" - <<'PY'
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PIL  # noqa: E402
from PyQt6.QtCore import qVersion  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
print(f"setup_ci: OK  Qt={qVersion()}  Pillow={PIL.__version__}")
PY

# ---- 5. 像素基线 ------------------------------------------------------------
BASELINE_JSON="$REPO_ROOT/dev/tmp_baseline/hashes.json"
if [ "$FORCE_BASELINE" -eq 1 ] || [ ! -f "$BASELINE_JSON" ]; then
    echo "setup_ci: 生成像素基线 dev/tmp_baseline/hashes.json"
    rm -rf "$REPO_ROOT/dev/tmp_baseline"
    "$VENV_PY" "$REPO_ROOT/dev/transform_baseline.py"
else
    echo "setup_ci: 已存在像素基线，跳过生成（要重建用 --force-baseline）"
fi

echo "setup_ci: 环境就绪。下一步：bash dev/run_all_checks.sh"
