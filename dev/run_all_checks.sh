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
# 3. 跑之前【强制】清空字节码缓存，并校验确实空了。切分支 / git checkout 后，
#    pyc 的 (mtime, size) 校验在秒级精度下可能碰撞，导致加载陈旧字节码 ——
#    症状极具迷惑性（inspect.getsource() 显示正确源码，行为却是旧的）。
#
#    为什么是"删 + 校验"而不是 PYTHONDONTWRITEBYTECODE=1：后者只禁【写】不禁
#    【读】，已存在的 pyc 照样被加载，对"陈旧字节码"这个问题几乎无收益；而且
#    compileall（第 2 项）会无视它照样落盘。真正管用的只有删。
#
#    为什么必须校验而不是 `|| true` 了事：删不掉是有可能的（Windows 上 pyc 被
#    占用时 rm 直接失败），而删不掉又静默继续 = 用旧字节码跑完整轮回归，全绿
#    但测的不是当前代码。所以清空后逐条确认残留为空，非空就 exit 2 中止，
#    绝不带病运行。
#
#    两处清理：开头一次；第 2 项 compileall 之后再一次（它会写满 src/ 与 dev/，
#    不清掉 3~11 项读的就是它刚生成的那批）。
#
# 4. 第 1 项（重复定义）是**纯标准库**的结构性检查，刻意放在最前：它只要 ~0.1s，
#    且能挡住"改了代码却没效果"这类最费解的问题 —— Python 对同名的后定义静默
#    覆盖先定义，前者从此是死代码。`MainWindow` 曾经躺着 5 份这样的死代码
#    （configure_reference_settings ×3、update_onion_state ×3）。
#
# 5. 第 12 项（ProjectData 持有契约）与第 1 项同族：纯标准库 AST、~0.1s、拦的也是
#    "跑了也测不到"的那类。它排在最末**仅仅是为了不给 2~11 项重新编号** ——
#    脚本里多处注释按序号指认检查项，重排的收益远小于改错一处引用带来的风险。
#    它守的是 P2-5 改道后的三条约定（project 只读 / clear 先于 adopt / 无跨层私有
#    访问），其中"次序"那条两种写法的**终态完全相同**，只有 AST 比行号能拦住。
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

# ---- 字节码缓存：强制清空 + 校验确实为空 -------------------------------------
# 只认 src/ 与 dev/：这两处是本仓库源码，也是唯一会被测试 import 的地方。
# 刻意在同一个表达式里同时匹配 __pycache__ 目录与游离的 .pyc 文件，删除与校验
# 复用同一套判据，避免"删的和查的不是一回事"。
list_bytecode() {
    find "$REPO_ROOT/src" "$REPO_ROOT/dev" \
        \( -name __pycache__ -type d -prune -o -name '*.pyc' \) -print 2>/dev/null
}

purge_bytecode() {
    find "$REPO_ROOT/src" "$REPO_ROOT/dev" \
        \( -name __pycache__ -type d -prune -o -name '*.pyc' \) \
        -exec rm -rf {} + 2>/dev/null

    local left
    left="$(list_bytecode)"
    if [ -n "$left" ]; then
        echo "run_all_checks: 字节码缓存未能清空，以下路径残留：" >&2
        echo "$left" | sed 's/^/        /' >&2
        echo "        继续跑下去会用旧字节码得到全绿的假结果，故中止。" >&2
        echo "        Windows 上通常是文件被占用（GUI / 上轮进程未退出），先关掉再重跑。" >&2
        return 1
    fi
    return 0
}

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
    "第 7/8/10 项（smoke_reorder.py、smoke_reference_frame.py、verify_undo_snapshot.py）\
 硬依赖它加载真实工程。\
 选它的理由：15 帧来自同一张源图但裁切互不相同，帧签名（crop_rect+scale+rotation+is_disabled）\
 全部唯一，105 种两两交换无一失明；旧的 test_long.json 有 1 组重复签名（第 4/15 帧），\
 已作为死文件删除（见 dev/code_review_p1_3.md）。另：dev/verify_selection_style.py
 刻意用运行时生成的短名图片，不依赖它"
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

# ---- 清 __pycache__（失败即中止，不静默继续）---------------------------------
if ! purge_bytecode; then
    exit 2
fi

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

if [ "$ABORTED" -eq 0 ]; then run_check "1/12 重复定义（结构性）"      "$PY" dev/check_no_duplicate_defs.py          || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "2/12 语法编译 main.py+src"    "$PY" -m compileall -q main.py src            || FAILED=1; fi

# compileall 刚把 pyc 写满了 src/ 与 dev/，3~11 项不清掉就会读这批而非源码。
# 同样失败即中止。根目录 __pycache__（compileall 为 main.py 生成的）刻意不动：
# 没有任何测试 import main 模块，且 find 到仓库根会一路扫进 venv/，得不偿失。
if ! purge_bytecode; then
    FAILED=1
    ABORTED=1
fi

if [ "$ABORTED" -eq 0 ]; then run_check "3/12 几何与模型单测"          "$PY" dev/test_transform.py                   || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "4/12 渲染像素哈希 --compare"   "$PY" dev/transform_baseline.py --compare     || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "5/12 双视图同步与拖拽"         "$PY" dev/verify_timeline_view_sync.py        || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "6/12 网格视图"                 "$PY" dev/verify_grid_view.py                 || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "7/12 MainWindow 接线：重排"    "$PY" dev/smoke_reorder.py                    || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "8/12 MainWindow 接线：参考帧"  "$PY" dev/smoke_reference_frame.py            || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "9/12 选中配色跨平台一致"       "$PY" dev/verify_selection_style.py           || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "10/12 撤销快照：增量与共享"    "$PY" dev/verify_undo_snapshot.py             || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "11/12 图片缓存与导出缓存"      "$PY" dev/verify_image_cache.py               || FAILED=1; fi
if [ "$ABORTED" -eq 0 ]; then run_check "12/12 ProjectData 持有契约"    "$PY" dev/verify_project_ownership.py         || FAILED=1; fi

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
    echo "  - 若第 1 项失败（重复定义）：Python 只保留最后一个定义，前面的永不执行。"
    echo "     删除被覆盖的那些；若两处都有用，说明其中一个该改名。"
    echo "     注意 src/ui/temp_prop.py 是 PropertyPanel 的旧副本（无人 import），"
    echo "     它作为死文件被单独排除，不在本项检查范围内。"
    echo "  - 若第 9 项失败（选中配色跨平台不一致）："
    echo "     选中色由 ui/timeline_selection_style.py 单一真源提供，QSS 与两个 delegate"
    echo "     都必须引用它。三个易踩的坑："
    echo "       (a) QSS 选择器要写 QTreeView/QListView —— 写 QTreeWidget 匹配不到"
    echo "           （Type Selector 只匹配该类及其子类，父子关系反过来不成立）；"
    echo "       (b) QSS 只认 /* */ 注释，写成 '# 注释' 会让 Qt 中断其后**整个**"
    echo "           样式表的解析，且只在 stderr 打一句警告，GUI 里完全看不见；"
    echo "       (c) 选中色必须不透明 —— 半透明会透出底层平台绘制的颜色，"
    echo "           而只看 RGB 三个分量区分不了 alpha=200 与 255。"
    echo "  - 若第 10 项失败（撤销快照）：这三项各对应一个独立的改动点，别混着查。"
    echo "      · '走了整体替换' → _apply_snapshot_inner 没走 apply_frames，"
    echo "        或它的行数判断失效；"
    echo "      · '快照被后续编辑污染' → apply_frames 漏了 clone()，模型与历史快照"
    echo "        共享了 FrameData（不报错，只在 redo 时偶尔取到错值，最难查）；"
    echo "      · '未变帧未共享' → _capture_snapshot 的 reuse_from 或"
    echo "        HistoryManager.push 的 before 复用被去掉（功能正常，只是退回"
    echo "        O(帧数×历史条数) 内存）。"
    # 反引号在双引号里会被 bash 当**命令替换**执行，ASCII 双引号则会提前闭合字符串
    # —— 两者都会让这段提示在真失败时输出残缺并往 stderr 喷 command not found。
    # 故提示文字一律不用反引号包裹标识符，且整段拆成单行 echo（与周围风格一致）。
    echo "  - 若第 12 项失败（ProjectData 持有契约）：6 条判据各自对应一个改动点。"
    echo "      · self.project = ... → project 是只读 property，替换工程对象必须走"
    echo "        _adopt_project()，它把【换对象】与【重新绑定 frames 数据源】绑成一步；"
    echo "      · 次序反了 → 必须先 timeline.clear() 再 _adopt_project()。绑定后"
    echo "        project.frames 就是 timeline 的实时内容，先绑定会让新工程短暂报告"
    echo "        【上一个工程】的帧。两种次序的终态相同，跑了看结果测不出来；"
    echo "      · 跨层私有访问 → 说明 TimelineWidget 的公开接口不够用，去补公开方法，"
    echo "        不要在 MainWindow 里伸手进别人的私有成员；"
    echo "      · 函数内 import → 一律提到模块顶部（P2-5 已清到 0，别再往回加）。"
    echo "  - 若第 11 项失败（缓存）：image_cache.py 与 exporter.py 的"
    echo "     SourceImageCache 都是「字节预算 + LRU」。退回按张数或 FIFO 功能完全正常，"
    echo "     只是内存/性能退化，肉眼几乎看不出来，所以只能靠这一项拦。"
    echo "     另：ImageCache.get() 的 crop_rect 是已删的死参数，加回来不会报错、"
    echo "     也不会有任何效果，只有这一项会红。"
    echo "  - 若第 4 项失败（MAIN_DIGEST 变化）而你【有意为之】地改了渲染："
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
