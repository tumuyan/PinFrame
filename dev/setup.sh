#!/bin/bash
# PyQt6 的系统依赖清单在 dev/qt_deps.txt，与 dev/setup_ci.sh（流水线）共用同一份，
# 避免"本地能跑、CI 跑不了"的漂移。
DEPS_FILE="$(cd "$(dirname "$0")" && pwd)/qt_deps.txt"
PACKAGES=""
while read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    for pkg in $line; do
        PACKAGES="$PACKAGES $pkg"
    done
done < "$DEPS_FILE"

apt-get update
apt install -y python3 python3-venv pip
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

apt-get install -y $PACKAGES