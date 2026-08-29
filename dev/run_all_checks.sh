#!/bin/bash
# 全量回归：把本仓库所有自动化验证跑一遍。
#
# 用法：
#   bash dev/run_all_checks.sh              # 跑完所有项，末尾汇总
#   bash dev/run_all_checks.sh --verbose    # 实时回显每个脚本的完整输出
#   bash dev/run_all_checks.sh --fail-fast  # 第一项失败即停
#   bash dev/run_all_checks.sh --help
#
# 退出码：0 = 全部通过；1 = 有失败项；2 = 参数错误或前置依赖缺失。
#
# ---------------------------------------------------------------------------
# 为什么需要这个脚本（而不是手敲六行命令）
# ---------------------------------------------------------------------------
# 1. 退出码判定用 `-ne 0`，不是 `-eq 1`。Qt 会把 paintEvent 内未捕获的异常升级
#    为 abort()，进程退出码是 134（Linux）/ 0xC0000409（Windows）这类，只判 1
#    会把崩溃漏成通过 —— 这正是 transform_baseline.py 要把 aspect_ratio == 0
#    隔离到子进程的原因。
#
# 2. 第 3 项（像素基线）有一条静默的假通过路径：transform_baseline.py 的 --compare
#    只在 prev 非空时才比对。若 dev/tmp_baseline/hashes.json 缺失，它会跳过比对、
#    落盘一条新基线、然后【返回 0】。所以脚本必须前置校验该文件存在且含
#    main_digest，并在跑完后校验它没被改写，否则基线会被刷新成"当前（可能已坏的）
#    结果"，此后比对将永远通过。
#
# 3. 跑之前清 __pycache__。切分支 / git checkout 后，pyc 的 (mtime, size) 校验
#    在秒级精度下可能碰撞，导致加载陈旧字节码 —— 症状极具迷惑性
#    （inspect.getsource() 显示正确源码，行为却是旧的）。
#
# ---------------------------------------------------------------------------
# 关于第 3 项的基线语义（重要）
# ---------------------------------------------------------------------------
# dev/tmp_baseline/ 在 .gitignore 中，基线【不入库】。因此 --compare 比的是
# "与本机上一次运行"，不是"与团队基线"。正确用法是：改动前跑一次不带 --compare
# 的存基线，改动后 --compare 看 main_digest 是否变化。
# 新 clone 的环境里必然缺基线，脚本会明确报出并告诉你怎么生成，而不是假装通过。
#
# ---------------------------------------------------------------------------
# 覆盖缺口（脚本全绿 != 一切正常）
# ---------------------------------------------------------------------------
# 右键菜单、外部文件拖入、播放跟随 这三项没有任何自动化覆盖，只能手动验证。
# 脚本结束时会把这份清单打出来，别因为跑绿了就跳过。

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---- 参数 ------------------------------------------------------------------
FAIL_FAST=0
VERBOSE=0
for arg in "$@"; do
    case "$arg" in
        --fail-fast) FAIL_FAST=1 ;;
        --verbose|-v) VERBOSE=1 ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "未知参数: $arg（用 --help 查看用法）" >&2
            exit 2
            ;;
    esac
done

# ---- 解释器选择 -------------------------------------------------------------
# 优先级：已激活的虚拟环境（$VIRTUAL_ENV 由 activate 脚本导出，是真实存在的标准
# 变量）> 仓库默认 venv/ > PATH 里的 python3。
#
# 刻意【不】支持 $PYTHON 覆盖：dev/run_gui.sh 里有这个口子，但全仓库没有任何地方
# 给它赋值或记录它，是无人知晓的死约定，不复制。
PY="${VIRTUAL_ENV:+${VIRTUAL_ENV}/bin/python}"
if [ -z "$PY" ] && [ -x "$REPO_ROOT/venv/bin/python" ]; then
    PY="$REPO_ROOT/venv/bin/python"
fi
PY="${PY:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "run_all_checks: 找不到可用的 Python 解释器: $PY" >&2
    echo "  请先 bash dev/setup.sh，或激活你的虚拟环境后重试。" >&2
    exit 2
fi

echo "使用解释器: $PY  ($("$PY" -V 2>&1))"
echo "仓库根目录: $REPO_ROOT"

# ---- 前置依赖校验 -----------------------------------------------------------
# 这些文件缺失会让某个脚本以莫名其妙的 assert 失败，不如在这里一次性说清楚。
MISSING=0
require_file() {
    if [ ! -f "$1" ]; then
        echo "  缺失: $1"
        echo "        $2"
        MISSING=1
    fi
}
require_file "$REPO_ROOT/dev/test_long2.json" \
    "第 6 项（smoke_reorder.py）硬依赖它加载真实工程。\
 用它而不是 test_long.json：后者的第 4 与第 15 帧参数完全相同，\
 顺序断言对这两帧的交换完全失明（见 dev/code_review_p1_3.md）"
require_file "$REPO_ROOT/dev/tmp_baseline/hashes.json" \
    "第 3 项需要它做比对；缺失时该脚本会静默新建基线并返回 0（假通过）。先跑一次 'python dev/transform_baseline.py' 生成"

if [ "$MISSING" -ne 0 ]; then
    echo ""
    echo "run_all_checks: 前置依赖缺失，未开始检查。" >&2
    exit 2
fi

# 基线的 main_digest 必须存在，否则 --compare 拿到的是残缺数据
if ! "$PY" -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('main_digest') else 1)" \
        "$REPO_ROOT/dev/tmp_baseline/hashes.json"; then
    echo "run_all_checks: dev/tmp_baseline/hashes.json 中缺少 main_digest，基线不完整。" >&2
    echo "  先跑一次 'python dev/transform_baseline.py' 重新生成。" >&2
    exit 2
fi

# ---- 清 __pycache__ ---------------------------------------------------------
find "$REPO_ROOT/src" "$REPO_ROOT/dev" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ---- 检查项执行框架 ---------------------------------------------------------
BASELINE_JSON="$REPO_ROOT/dev/tmp_baseline/hashes.json"
LOGDIR="$(mktemp -d)"
trap 'rm -rf "$LOGDIR"' EXIT

RESULTS_NAME=()
RESULTS_RC=()
RESULTS_DUR=()
CHECK_INDEX=0

run_check() {
    local name="$1"
    shift
    local log="$LOGDIR/$CHECK_INDEX.log"
    CHECK_INDEX=$((CHECK_INDEX + 1))

    local start end rc
    start=$(date +%s)

    if [ "$VERBOSE" -eq 1 ]; then
        "$@"
        rc=$?
    else
        "$@" >"$log" 2>&1
        rc=$?
    fi

    end=$(date +%s)
    RESULTS_NAME+=("$name")
    RESULTS_RC+=("$rc")
    RESULTS_DUR+=("$((end - start))")

    if [ "$rc" -eq 0 ]; then
        printf '  [PASS] %s (%ss)\n' "$name" "$((end - start))"
    else
        printf '  [FAIL] %s (%ss, exit=%s)\n' "$name" "$((end - start))" "$rc"
        if [ "$VERBOSE" -ne 1 ] && [ -s "$log" ]; then
            echo "        ---- $name 输出 ----"
            sed 's/^/        /' "$log"
            echo "        --------------------------"
        fi
        # "请求中止"用变量传出，【不】占用返回值 —— 返回值必须始终是真实退出码，
        # 否则调用处的 `|| FAILED=1` 会在非 fail-fast 模式下永不触发。
        if [ "$FAIL_FAST" -eq 1 ]; then
            ABORTED=1
        fi
    fi

    return "$rc"
}

# ---- 开始 -------------------------------------------------------------------
TOTAL_START=$(date +%s)
BASELINE_BEFORE="$("$PY" -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$BASELINE_JSON")"

echo ""
echo "============================================================"
echo " 全量回归"
echo "============================================================"

FAILED=0
ABORTED=0

if [ "$ABORTED" -eq 0 ]; then run_check "1/6 语法编译 main.py+src"    "$PY" -m compileall -q main.py src            || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "2/6 几何与模型单测"           "$PY" dev/test_transform.py                   || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "3/6 渲染像素哈希 --compare"   "$PY" dev/transform_baseline.py --compare     || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "4/6 双视图同步与拖拽"         "$PY" dev/verify_timeline_view_sync.py        || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "5/6 网格视图"                 "$PY" dev/verify_grid_view.py                 || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "6/6 MainWindow 接线冒烟"      "$PY" dev/smoke_reorder.py                    || FAILED=1; fi

# ---- 基线未改写校验 ---------------------------------------------------------
BASELINE_AFTER="$("$PY" -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$BASELINE_JSON")"
BASELINE_TAMPERED=0
if [ "$BASELINE_BEFORE" != "$BASELINE_AFTER" ]; then
    BASELINE_TAMPERED=1
    FAILED=1
fi

# ---- 汇总 -------------------------------------------------------------------
TOTAL_END=$(date +%s)
TOTAL_DUR=$((TOTAL_END - TOTAL_START))

echo ""
echo "============================================================"
echo " 汇总"
echo "============================================================"
i=0
while [ "$i" -lt "${#RESULTS_NAME[@]}" ]; do
    if [ "${RESULTS_RC[$i]}" -eq 0 ]; then
        printf '  PASS  %s (%ss)\n' "${RESULTS_NAME[$i]}" "${RESULTS_DUR[$i]}"
    else
        printf '  FAIL  %s (%ss)\n' "${RESULTS_NAME[$i]}" "${RESULTS_DUR[$i]}"
    fi
    i=$((i + 1))
done

if [ "$BASELINE_TAMPERED" -ne 0 ]; then
    echo ""
    echo "  !! 严重：dev/tmp_baseline/hashes.json 在运行期间被改写。"
    echo "     基线一旦被刷新成当前结果，之后的 --compare 将永远通过（比对失去意义）。"
    echo "     请检查 transform_baseline.py 为何写入了基线（正常情况下 --compare 不落盘）。"
fi

echo ""
echo "  共 ${#RESULTS_NAME[@]} 项，耗时 ${TOTAL_DUR}s"

if [ "$FAILED" -ne 0 ]; then
    echo "  结果：FAIL"

    # 失败时给出针对性的排查提示
    echo ""
    echo "排查提示："
    echo "  - 若第 3 项失败（MAIN_DIGEST 变化）而你【有意为之】地改了渲染："
    echo "      确认差异符合预期后，跑 'python dev/transform_baseline.py' 刷新基线。"
    echo "  - 若某项的失败是异常而非断言（exit=134 之类）："
    echo "      Qt 在 paintEvent 中的未捕获异常会升级为 abort，需看完整输出定位，"
    echo "      用 --verbose 重跑那一项。"
    echo "  - 若失败来得莫名其妙：先 'find src dev -name __pycache__ -type d -exec rm -rf {} +'"
    echo "      再重跑（本脚本已在开头做过一次，但失败的脚本可能又生成了陈旧的 pyc）。"
else
    echo "  结果：PASS"
fi

# 无论如何都要提醒手动验证缺口
echo ""
echo "============================================================"
echo " 仍需手动验证（无任何自动化覆盖，脚本全绿不代表这几项正常）"
echo "============================================================"
echo "  1. 时间轴右键菜单"
echo "  2. 外部文件拖入时间轴"
echo "  3. 播放时的选中跟随"

if [ "$FAILED" -ne 0 ]; then
    exit 1
fi
exit 0
