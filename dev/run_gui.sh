#!/bin/bash
# 带虚拟显示运行 PyQt 应用（用于 code-server / 无头环境）。
# 内部确保 Xvfb 已就绪（用 setsid 脱离调用方进程树，避免被 VS Code 任务清理杀掉），
# 再 export DISPLAY 并 exec venv 的 python 运行目标脚本。
set -e

DISPLAY_NUM="${DISPLAY:-:99}"
export DISPLAY="${DISPLAY_NUM}"

# 复用统一的 Xvfb 就绪逻辑（dev/start_xvfb.sh 负责检测/拉起 :99，
# 并统一分辨率 1920x1080x24，避免各处重复实现与尺寸不一致）。
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"${SCRIPT_DIR}/start_xvfb.sh" "${DISPLAY_NUM}"

if ! xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
  echo "run_gui: failed to start Xvfb ${DISPLAY_NUM}" >&2
  exit 1
fi
echo "run_gui: DISPLAY=${DISPLAY_NUM} ready"

PY="${PYTHON:-${VIRTUAL_ENV:+${VIRTUAL_ENV}/bin/python}}"
if [ -z "${PY}" ] && [ -x "$(dirname "$0")/../venv/bin/python" ]; then
  PY="$(dirname "$0")/../venv/bin/python"
fi
PY="${PY:-python}"

# 用 setsid 把 python 放进独立会话/进程组，并 trap 退出信号，
# 保证 Ctrl+C（SIGINT）与 Tasks: Terminate Task（SIGTERM）都能可靠杀掉 python。
setsid "${PY}" "$@" &
PY_PID=$!
PY_PGID=$(ps -o pgid= -p "${PY_PID}" | tr -d ' ')

cleanup() {
    # 向整个进程组发送 TERM，再兜底 KILL
    if [ -n "${PY_PGID}" ]; then
        kill -TERM -"${PY_PGID}" 2>/dev/null || true
        sleep 0.5
        kill -KILL -"${PY_PGID}" 2>/dev/null || true
    fi
    echo "run_gui: terminated"
}
trap cleanup EXIT INT TERM

# 等待 python 结束，并把退出码透传
wait "${PY_PID}"
EXIT_CODE=$?
trap - EXIT INT TERM
cleanup
echo "run_gui: exited (code ${EXIT_CODE})"
exit "${EXIT_CODE}"
