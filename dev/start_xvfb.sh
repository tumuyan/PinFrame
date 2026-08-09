#!/bin/bash
# 启动/复用 Xvfb 虚拟显示器（用于 noVNC / 无头 PyQt 运行）。
# 这是项目中"确保虚拟显示就绪"的唯一逻辑来源，被 run_gui.sh /
# novnc_start.sh / screenshot.sh 直接调用，避免各处重复实现。
# 打印的 xvfb-start: / xvfb-ready 标记供 VS Code tasks.json 的
# problemMatcher 识别。
# 用法: ./dev/start_xvfb.sh [DISPLAY_NUM]   默认 :99
set -e

DISPLAY_NUM="${1:-:99}"
SCREEN="1600x900x24"
LOCK_DIR="/tmp/xvfb-${DISPLAY_NUM#:}.lock"

# 原子加锁：同一 DISPLAY 只允许一个启动流程，彻底消除竞态下的重复拉起。
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  # 另一进程正在启动/已持有锁：等待其就绪即可，无需自己再拉 Xvfb
  for i in $(seq 1 50); do
    if xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
      echo "xvfb-start: Xvfb ${DISPLAY_NUM} already running (reused via lock)"
      echo "xvfb-ready"
      exit 0
    fi
    sleep 0.2
  done
  echo "xvfb-start: timed out waiting for locked Xvfb ${DISPLAY_NUM}" >&2
  exit 1
fi
# 脚本退出时释放锁（Xvfb 自身继续在后台运行）
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

# 若已有同号 Xvfb 在跑则直接复用（锁内判定，已无竞态）
if xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
  echo "xvfb-start: Xvfb ${DISPLAY_NUM} already running"
  echo "xvfb-ready"
  exit 0
fi

Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN}" >/dev/null 2>&1 &
XVFB_PID=$!

# 等待 X server 真正可连接
for i in $(seq 1 30); do
  if xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if ! xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
  echo "xvfb-start: failed to start Xvfb" >&2
  kill "${XVFB_PID}" 2>/dev/null || true
  exit 1
fi

echo "xvfb-start: Xvfb ${DISPLAY_NUM} ready (pid=${XVFB_PID})"
echo "xvfb-ready"
