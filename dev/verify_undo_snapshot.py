#!/usr/bin/env python3
"""P2-6 撤销快照的回归验证：增量恢复 + 快照之间的结构共享。

为什么单独一个文件
------------------
`smoke_reorder.py` 只覆盖"撤销能不能把状态还原对"，它**验证不了**本次改动修的
两件事，而且在两者被改坏时它照样全绿：

  1. **恢复是否增量** —— 撤销一次"把 scale 从 1.0 调成 1.1"只动了 1 帧，若实现
     又回到整体替换（`set_frames` → `beginResetModel`），状态依然是对的，冒烟看不
     出差别，但视图已经全量重取、滚动位置丢失、`QItemSelectionModel` 被清掉了。
  2. **快照之间是否共享未变帧** —— 若快照退化回"每条历史都全量深拷贝全部帧"，
     内存从 O(帧数 + 变更数) 退回 O(帧数 × 历史条数)，功能完全正常，看不出来。

本脚本因此断言的是**信号与对象身份**，而不是"撤销后值对不对"。

最要紧的一条是 `test_snapshot_not_polluted_by_later_edits`：共享帧对象这个做法
唯一的失败模式是"快照与模型共享了同一个 FrameData"，此后每次原地编辑都会写进
历史快照，撤销/重做恢复到的是被后续编辑改过的值 —— **不报错、不崩溃**，只能靠
这条断言拦住。

运行： ./venv/bin/python dev/verify_undo_snapshot.py
退出码非 0 表示有失败。
"""
import contextlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import (  # noqa: E402
    QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QEvent,
)
from PyQt6.QtGui import QDropEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

app = QApplication(sys.argv)

from model.project_data import FrameData  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.timeline_model import TimelineModel  # noqa: E402
from ui.timeline_item_model import FrameDataRole  # noqa: E402

PROJECT = os.path.join(REPO_ROOT, "dev", "test_long2.json")
SAMPLE_IMG = os.path.join(REPO_ROOT, "dev", "sample_test_long_file_name.png")

_WIN = None


def _win():
    """共享一个 MainWindow —— 构造一次要几百毫秒，且反复构造会留下多个窗口。"""
    global _WIN
    if _WIN is None:
        _WIN = MainWindow()
    return _WIN


def _reload():
    """重载工程并清空历史，保证每个用例从同一起点开始。

    不清历史的话用例之间会互相污染：上一个用例留下的快照会被下一个用例的
    `record_history` 当成"上一条记录的 after"去复用（`HistoryManager.push`），
    于是断言莫名其妙地失败 —— 看起来像撤销坏了，实际是测试自身的状态残留
    （P1-3 补网时踩过完全一样的问题）。
    """
    win = _win()
    win._load_from_path(PROJECT)
    win.history.clear()
    return win


def _edit_scale(win, index, value):
    """模拟一次真实属性编辑并落一条历史。

    刻意**不**直接调 `win.record_history(label)`：它在 `before == after` 时静默
    跳过，而缺省的 before 是调用那一刻抓的（帧已经改完了），于是等于没记 ——
    断言会被严重误导。必须走生产代码的模式：先抓 before，再改，再提交。
    """
    before = win._capture_snapshot()
    win.timeline.get_all_frames()[index].scale = value
    win.record_history("test_scale", before=before)


def _signals(model):
    """记录模型此后发出的变更通知。"""
    events = []

    def on_data(a, b):
        events.append(("data", a, b))

    def on_replaced():
        events.append(("replaced",))

    model.data_changed.connect(on_data)
    model.frames_replaced.connect(on_replaced)
    return events


def _internal_drop_event():
    """构造一次"内部重排"的 drop 事件（与 `smoke_reorder.py` 同一套手法）。"""
    mime = QMimeData()
    mime.setData("application/x-pinframe-internal-reorder", b"reorder")
    event = QDropEvent(QPointF(QPoint(0, 0)), Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QEvent.Type.Drop)
    event._keep_mime = mime  # QDropEvent 不接管 QMimeData 所有权
    return event


def _sig(win):
    """帧序列签名 —— 用来表达"顺序"。

    不能只取 crop_rect 的部分分量：前几帧的 (x, w) 可能相同，撞车之后
    before == after，"撤销还原了"与"重做回到了"会**同时成立**，两个断言一起
    变成假通过。必须取全字段。
    """
    return [tuple(f.crop_rect or ()) + (f.scale, f.rotation, f.is_disabled)
            for f in win.timeline.get_all_frames()]


def _select_rows_like_user(win, rows):
    """模拟用户点选若干行 —— **唯一**能触发 `MainWindow.on_selection_changed` 的路径。

    `win.timeline.model.set_selection(rows)` **不能用**：那是"模型 → 视图"方向，
    `TimelineWidget._on_model_selection_changed` 会 `blockSignals` 后写视图、刻意
    不回传 `selection_changed`（否则成环）。用它当"改了选中"的前置条件，
    `on_selection_changed` 根本不会被调用，断言随即**假通过**（实测踩到）。

    真实路径是：selectionModel 变化 → 视图 `on_selection_changed` → **50ms 防抖**
    → `_emit_selection_changed` → `MainWindow.on_selection_changed`。防抖是给
    属性面板用的（拖框选时别每帧重绘），故这里必须等过它。
    """
    view = win.timeline.list_view
    sel = view.selectionModel()
    wanted = set(rows)
    for row in set(view.get_selected_indices()) - wanted:
        sel.select(view._item_model.index(row, 0),
                   QItemSelectionModel.SelectionFlag.Deselect
                   | QItemSelectionModel.SelectionFlag.Rows)
    for row in wanted:
        sel.select(view._item_model.index(row, 0),
                   QItemSelectionModel.SelectionFlag.Select
                   | QItemSelectionModel.SelectionFlag.Rows)
    QTest.qWait(120)  # 过防抖（50ms）
    assert set(win.timeline.get_selected_indices_from_model()) == wanted, (
        "前置条件失败：选中没生效（模型 %s），后续断言会假通过"
        % win.timeline.get_selected_indices_from_model())


def _drag_row(win, from_row, insert_before):
    """把 from_row 拖到 insert_before 之前，返回 (拖前签名, 拖后签名)。"""
    view = win.timeline.list_view
    before = _sig(win)
    view._dragged_rows = [from_row]
    view._drag_insert_position = (insert_before, True)
    view.dropEvent(_internal_drop_event())
    after = _sig(win)
    assert after != before, (
        "前置条件失败：拖拽没有改变顺序，后续所有断言都会假通过"
        f"（from_row={from_row}, insert_before={insert_before}）")
    return before, after


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

def test_undo_property_change_is_incremental():
    """撤销一次单帧属性变更：只发 data_changed，不得触发整体替换。

    这是 P2-6 的核心收益。改坏（把 `_apply_snapshot_inner` 换回 `set_frames`）
    之后状态仍然正确，只有本条会红 —— 这也正是 `smoke_reorder.py` 盖不住的地方。
    """
    win = _reload()
    model = win.timeline.model
    item_model = win.timeline.list_view.model()

    resets = []
    item_model.modelReset.connect(lambda: resets.append(1))

    _edit_scale(win, 0, 1.5)
    assert win.history.count() == 1, f"前置条件失败：历史没记上，{win.history.count()} 条"

    events = _signals(model)
    win.undo_history()

    assert win.timeline.get_frame_at(0).scale == 1.0, "撤销后帧值未恢复"
    assert ("replaced",) not in events, \
        f"撤销单帧属性变更走了整体替换（frames_replaced），应走增量：{events}"
    assert resets == [], \
        "撤销触发了 beginResetModel —— 视图全量重取，选中与滚动位置都会丢"
    # 增量路径还必须**只**重绘变化的那一行，否则退化成另一种形式的全量刷新
    assert events == [("data", 0, 0)], \
        f"data_changed 的区间应恰好是第 0 行，实际 {events}"


def test_undo_row_count_change_falls_back_to_replace():
    """撤销一次加帧（行数会变）必须回落到整体替换 —— 增量只适用于行数不变。"""
    win = _reload()
    model = win.timeline.model
    n0 = win.timeline.get_frame_count()

    before = win._capture_snapshot()
    win.timeline.model.add_frame(FrameData(file_path=SAMPLE_IMG))
    win.record_history("test_add", before=before)
    assert win.timeline.get_frame_count() == n0 + 1, "前置条件失败：帧没加上"

    events = _signals(model)
    win.undo_history()

    assert win.timeline.get_frame_count() == n0, "撤销加帧后帧数未恢复"
    assert ("replaced",) in events, \
        f"行数变化的撤销应当走整体替换，实际 {events}"


def _pollution_tail(win, expected_scale, where):
    """污染检测的公共尾段：断言身份隔离，再"污染 → 重新应用"验证行为。

    前置：`win` 刚 undo 过一次，当前状态就是 `entries[0].after`，且 index=0
    （后续 `_edit_scale` 只删 `entries[1:]`，`entries[0]` 得以存活，redo 才够得着）。

    **为什么必须先跑到 index=0 再污染**：历史的线性语义是"撤销后产生新改动即丢弃
    redo 分支"（见 AGENTS.md）。若停在 index=-1 就编辑，`entries[0:]` 会被整个删掉，
    快照随之消失，"重新应用"根本无从谈起 —— 断言会退化成恒真。

    两段检查缺一不可：
      - 身份检查在**污染之前**就能抓到问题（值此刻还是对的）；
      - 行为检查证明它**真的**会造成用户可见的后果。
    """
    snapshot_frames = win.history.entries[0].after["frames"]

    # 1) 身份隔离：模型里的活帧不得是快照里的对象
    snap_ids = {id(f) for f in snapshot_frames}
    shared = sum(1 for f in win.timeline.get_all_frames() if id(f) in snap_ids)
    assert shared == 0, (
        f"[{where}] 撤销后模型与历史快照共享了 {shared} 个 FrameData 对象 —— "
        "此后每次原地编辑都会写进历史快照（apply_frames 漏了 clone）")

    # 2) 行为：污染之后让同一个快照再被应用一次，值必须还是当初记录的那个
    _edit_scale(win, 0, 9.0)
    win.undo_history()
    got = win.timeline.get_frame_at(0).scale
    assert got == expected_scale, (
        f"[{where}] 重新应用快照后应回到 {expected_scale}，实际 {got} —— "
        "历史快照被后续编辑污染了")


def test_snapshot_not_polluted__incremental_path():
    """增量路径（行数不变）：快照不得与模型共享帧对象。

    场景：记 H1(1.5) → 记 H2(2.5) → undo（应用 H1.after，此时模型帧正是那个对象）
    → 编辑成 9.0（污染 H1.after）→ undo（再次应用 H1.after）。
    """
    win = _reload()
    _edit_scale(win, 0, 1.5)
    _edit_scale(win, 0, 2.5)

    win.undo_history()
    assert win.timeline.get_frame_at(0).scale == 1.5, "前置条件失败：首次撤销没回到 1.5"
    assert win.history.index == 0, "前置条件失败：应停在 index=0"

    _pollution_tail(win, expected_scale=1.5, where="增量路径")


def test_snapshot_not_polluted__fallback_path():
    """回落路径（行数变化）：同样不得共享 —— 这是为一次真实漏网补的。

    `apply_frames` 落到 `set_frames` 上时，后者是"直接换列表、**不克隆**"，而调用方
    `_apply_snapshot_inner` 已把克隆的责任全交给了 `apply_frames` —— 于是整批帧与
    历史快照共享对象。实测 15/15 共享，且当时 10 个用例全绿：只有增量路径写了
    clone，也只有增量路径有检查。

    场景：加帧 → 再加帧 → undo（17 帧回退到 16 帧，**行数变化** → 回落路径，应用的
    是 `entries[0].after`）→ 编辑（污染它）→ undo（再次应用 `entries[0].after`）。
    """
    win = _reload()
    expected = win.timeline.get_frame_at(0).scale
    src = win.timeline.get_frame_at(0).file_path

    win.add_files([src])
    win.add_files([src])
    assert win.history.index == 1, "前置条件失败：两次加帧后应停在 index=1"

    win.undo_history()
    assert win.timeline.get_frame_count() == 16, \
        f"前置条件失败：撤销后应回到 16 帧，实际 {win.timeline.get_frame_count()}"
    assert win.history.index == 0, "前置条件失败：应停在 index=0"

    _pollution_tail(win, expected_scale=expected, where="回落路径")


def test_snapshots_share_unchanged_frames():
    """未变的帧必须在快照之间共享同一对象 —— 否则 P2-6 等于没修。

    三条断言分别钉住三个环节，任何一环退化回全量克隆都会让对应断言变红：
      - 同一条历史内 before/after 之间共享（省掉一半克隆）；
      - 变了的那一帧**不能**共享（它的旧值要被固化下来）；
      - 相邻两条历史之间复用（栈里不再存两份相同的状态）。
    """
    win = _reload()

    _edit_scale(win, 0, 1.5)
    _edit_scale(win, 0, 2.5)

    e0, e1 = win.history.entries[0], win.history.entries[1]

    assert e0.before["frames"][1] is e0.after["frames"][1], (
        "同一条历史里未变的帧被重复克隆了 —— 快照仍是 O(帧数) 而非 O(变更数)")

    assert e0.before["frames"][0] is not e0.after["frames"][0], (
        "变化的帧在 before/after 之间共享了对象，旧值会被新值覆盖（历史失真）")

    assert e1.before is e0.after, (
        "历史栈把同一个状态存了两份 —— before/after 未复用（HistoryManager.push）")


def test_undo_redo_add_frame():
    """加帧的撤销/重做往返。

    用 `add_files` 这个**真实动作**，不是手工 `record_history()` —— 后者在
    `before == after` 时静默跳过、根本不留历史，断言会被严重误导。
    """
    win = _reload()
    n0 = win.timeline.get_frame_count()
    base_sig = _sig(win)
    src = win.timeline.get_frame_at(0).file_path

    win.add_files([src], index=n0)
    assert win.timeline.get_frame_count() == n0 + 1, "前置条件失败：add_files 未加帧"
    added_sig = _sig(win)
    assert added_sig != base_sig, "前置条件失败：加帧后签名没变"

    win.undo_history()
    assert win.timeline.get_frame_count() == n0, \
        f"撤销加帧后帧数不对: {win.timeline.get_frame_count()} != {n0}"
    assert _sig(win) == base_sig, "撤销加帧后内容未还原"

    win.redo_history()
    assert win.timeline.get_frame_count() == n0 + 1, "重做加帧后帧数不对"
    assert _sig(win) == added_sig, "重做加帧后内容未回到加帧后的状态"
    assert win.timeline.get_frame_at(n0).file_path == src, \
        "重做后末尾不是当初加进来的那个文件"


def test_undo_redo_remove_frame():
    """删帧的撤销/重做往返 —— 被删的帧必须原样回来，不是只把行数补上。"""
    win = _reload()
    n0 = win.timeline.get_frame_count()
    base_sig = _sig(win)
    assert n0 > 2, f"夹具帧数太少: {n0}"

    win.timeline.model.set_selection([0])
    win.remove_frame()
    assert win.timeline.get_frame_count() == n0 - 1, "前置条件失败：remove_frame 未删帧"
    removed_sig = _sig(win)

    win.undo_history()
    assert win.timeline.get_frame_count() == n0, "撤销删帧后帧数未恢复"
    assert _sig(win) == base_sig, "撤销删帧后内容未还原（被删帧没原样回来）"

    win.redo_history()
    assert win.timeline.get_frame_count() == n0 - 1, "重做删帧后帧数不对"
    assert _sig(win) == removed_sig, "重做删帧后内容不对"


def test_undo_redo_reorder():
    """拖拽重排的撤销/重做往返。

    为什么这条必须单独在**本脚本**：`smoke_reorder.py` 覆盖的只是拖拽的 undo，
    而 P2-6 之后撤销重排走的是**增量路径**（帧对象被逐个 clone、发 `data_changed`）
    而不是整体替换。重排是唯一一个"映射变了但对象没变"的撤销场景，
    它与属性变更共用同一条 `apply_frames` 路径，但语义完全不同 ——
    属性变更是"内容变了、映射没变"（`data_changed` 的正统语义），
    重排是"映射变了"。

    结果之所以仍然正确，是因为 `data()` 每次都现算、视图不缓存帧对象。
    这条把"依赖视图不缓存"这个隐含前提钉住：将来若有人给视图加一层
    "行 → 帧对象"的缓存，本用例会第一个变红。
    """
    win = _reload()
    before, after = _drag_row(win, 0, 3)

    def assert_view_not_caching(where):
        """视图不得缓存帧对象：model 的 FrameDataRole 必须给出**当前**的帧。

        检查时机很讲究：必须在**顺序刚变过**之后查。若放在最后一次状态变化之后，
        缓存里存的恰好就是那一刻的帧，断言会假通过（实测：把这段放在 redo 之后，
        给 `data()` 加缓存的破坏根本抓不到 —— 因为缓存内容正好等于期望值）。
        """
        model = win.timeline.list_view.model()
        live = win.timeline.get_all_frames()
        for row in range(min(5, len(live))):
            got = model.index(row, 0).data(FrameDataRole)
            assert got is live[row], (
                f"{where}: 第 {row} 行返回的不是模型当前的帧对象 —— "
                "适配层缓存了帧，而撤销重排走的是 data_changed（只重绘、不重建）")

    assert_view_not_caching("拖后")

    events = _signals(win.timeline.model)
    win.undo_history()
    assert _sig(win) == before, "撤销重排后顺序未还原"
    assert events == [("data", 0, 2)], \
        f"撤销重排应走增量路径、只重绘受影响的行，实际 {events}"
    assert_view_not_caching("撤销后")

    win.redo_history()
    assert _sig(win) == after, "重做重排后顺序未回到拖后的状态"
    assert_view_not_caching("重做后")


def test_reference_frame_survives_undo():
    """撤销别的操作时，参考帧必须还在 —— 它不落历史，靠快照兜底还原。

    前提事实：**设置/清除参考帧不落历史**（`set_reference_frame_from_selection`
    没有 `record_history`，i18n 里也没有 `hist_*_reference` 这样的 label）。
    所以"撤销设置参考帧"这个操作本身不存在，用户问的这一项无从覆盖。

    但有一条真实风险必须测：参考帧是**帧对象引用**，而 `apply_frames` 克隆帧时
    会主动清掉指向旧对象的参考帧（见 `TimelineModel.apply_frames` 的副作用），
    再由 `_apply_snapshot_inner` 按"下标优先、路径兜底"恢复。二者是配套的 ——
    少了前者，参考帧会指向已经不在模型里的对象；少了后者，撤销就会莫名丢失参考帧。
    """
    win = _reload()

    # 设参考帧（确认它确实不落历史，否则本用例的前提就错了）
    win.timeline.model.set_selection([2])
    win.set_reference_frame_from_selection()
    assert win.reference_frame is not None, "前置条件失败：参考帧没设上"
    assert not win.history.can_undo, "参考帧设置不应落历史"

    ref_path = win.reference_frame.file_path
    ref_index = win.timeline.get_all_frames().index(win.reference_frame)

    # 改一个**别的**帧的属性并落历史，再撤销
    before = win._capture_snapshot()
    win.timeline.get_all_frames()[0].scale = 2.0
    win.record_history("test_scale", before=before)

    win.undo_history()
    live = win.timeline.get_all_frames()
    assert win.reference_frame is not None, "撤销别的操作之后，参考帧丢了"
    assert win.reference_frame.file_path == ref_path, "撤销后参考帧指向了别的文件"
    assert any(f is win.reference_frame for f in live), \
        "撤销后参考帧指向的对象已不在模型里（apply_frames 清掉了却没恢复）"
    assert live.index(win.reference_frame) == ref_index, \
        f"参考帧下标漂移: {live.index(win.reference_frame)} != {ref_index}"
    # 业务模型那份也必须同步（时间轴高亮读它）
    assert win.timeline.model.get_reference_frame() is win.reference_frame, \
        "参考帧的两份真源不同步（时间轴高亮会不亮）"


def test_history_cost_is_independent_of_frame_count():
    """记一条历史的克隆次数必须与**帧数无关**，只跟本次改了几帧有关。

    这是 P2-6 最核心的主张。它测的是 CPU 成本而非内存：`_capture_snapshot` 若退化回
    "无脑克隆全部帧"，功能一样正确、内存也只差一倍（靠 `HistoryManager.push` 的
    before 复用还能救回来），只有这里的计数会暴露 —— 500 帧的工程每改一帧就多克隆
    1000 个对象，拖滑块的手感差异就在这种地方。

    断言放在**稳定期**（第 2 条之后）：第 1 条没有基准可复用，必然是 O(帧数)，
    拿它断言会永远失败。
    """
    win = _reload()
    total = win.timeline.get_frame_count()
    assert total > 10, f"夹具帧数太少，测不出与帧数的关系：{total}"

    from model.project_data import FrameData as _FD
    original = _FD.clone
    calls = []

    def counting_clone(self):
        calls.append(1)
        return original(self)

    try:
        _FD.clone = counting_clone

        _edit_scale(win, 0, 1.5)          # 第 1 条：没有基准，必然全量
        first = len(calls)

        calls.clear()
        for v in (2.0, 2.5, 3.0):
            _edit_scale(win, 0, v)
        per_record = len(calls) / 3
    finally:
        _FD.clone = original

    assert first >= total, \
        f"第 1 条历史应当至少克隆每一帧（没有复用基准），实际 {first} < {total}"
    assert per_record <= 3, (
        f"稳定期每条历史克隆了 {per_record:.1f} 个对象 —— 应与帧数无关 "
        f"（本次只改 1 帧，期望 ≤3），说明快照退回成了全量深拷贝")


def test_apply_frames_contract():
    """模型层契约（不经过 MainWindow）：返回值、信号、以及"无变化则沉默"。

    返回值 `True/False` 表示走的是增量还是回落，调用方据此决定后续动作，
    所以它是契约的一部分，必须钉住。
    """
    def make(n, scale):
        return [FrameData(file_path=SAMPLE_IMG, scale=scale) for _ in range(n)]

    m = TimelineModel()
    m.set_frames(make(3, 1.0))

    events = _signals(m)
    target = make(3, 2.0)
    target[1].scale = 1.0  # 只有第 0、2 帧真的变了

    ok = m.apply_frames(target)
    assert ok is True, "行数相同应走增量路径"
    assert events == [("data", 0, 2)], \
        f"应合并成一条 data_changed 覆盖第 0~2 行（第 1 帧未变也落在区间内），实际 {events}"
    assert [f.scale for f in m.get_all_frames()] == [2.0, 1.0, 2.0], "帧值未按目标更新"
    # 替换进模型的必须是副本，不能与传入的列表共享对象
    assert m.get_frame_at(0) is not target[0], \
        "模型与传入的帧列表共享了对象，调用方的后续改动会直接改到模型里"

    # 无变化：一条通知都不该发（否则每次"撤销后又重做"都是一次白刷）。
    # 夹具必须与模型当前内容**逐字段相同**（第 1 帧仍是 1.0），否则就是有变化，
    # 断言会被自己的夹具误导。
    events.clear()
    unchanged = make(3, 2.0)
    unchanged[1].scale = 1.0
    assert m.apply_frames(unchanged) is True
    assert events == [], f"内容没有变化时不应发任何通知，实际 {events}"

    # 行数不同：回落整体替换
    events.clear()
    assert m.apply_frames(make(4, 2.0)) is False, "行数变化应回落并返回 False"
    assert events == [("replaced",)], f"回落时应只发 frames_replaced，实际 {events}"
    assert m.get_frame_count() == 4, "回落路径未更新行数"

    # 参考帧：不在新列表里时必须清空 —— 与 set_frames 保持一致。
    #
    # 这条**不是**在测某个必需的修复：唯一调用方 `_apply_snapshot_inner` 随后
    # 一定会按快照重设参考帧，所以少了这段清空，最终行为也一样（破坏性验证
    # 已确认：去掉它，10 个用例全绿）。
    #
    # 那为什么还钉它：这是**两条路径的一致性契约**。调用方现在是"先清空、后按
    # 下标/路径恢复"，依赖的是"apply_frames 与 set_frames 的副作用相同"。若有人
    # 以为这段清空是死代码而删掉，两条路径就分叉了 —— 将来任何**只走 apply_frames
    # 而不恢复参考帧**的新调用方（例如按行批量替换）会静默留下一个指向已移除对象的
    # 参考帧。钉住它，是为了让"两条路径行为一致"这件事有据可依。
    m2 = TimelineModel()
    m2.set_frames(make(3, 1.0))
    kept = m2.get_frame_at(1)
    m2.set_reference_frame(kept)

    # 整体替换成另一批对象 → 参考帧不在新列表中 → 必须清空
    m2.set_frames(make(3, 1.0))
    assert m2.get_reference_frame() is None, \
        "set_frames 未清空已失效的参考帧"

    # 增量替换同一行 → 同样必须清空
    m2.set_reference_frame(m2.get_frame_at(1))
    m2.apply_frames(make(3, 9.0))
    assert m2.get_reference_frame() is None, \
        "apply_frames 未清空已失效的参考帧 —— 与 set_frames 的副作用分叉了"


# ---------------------------------------------------------------------------
# 播放列表的鲜度（P2-6 实施记录里那条「未修的既有缺陷」）
# ---------------------------------------------------------------------------
#
# `MainWindow.playlist` 缓存的是**帧对象**，而模型在撤销 / 增删 / 换序时会把帧对象
# 换掉。此前没有任何一处通知它，于是播放中做这些操作时：
#   - 撤销 → 画面继续用旧对象，**看起来像撤销没生效**（不报错、不崩溃）；
#   - 删帧 → 已删的帧仍在播；
#   - 加帧 → 新帧永远轮不到。
#
# 修法是让模型的结构性变更信号在播放时重建 playlist。**五条信号各接一次，就必须
# 各测一遍** —— 与 `clone()` 分散在两条路径上那条教训同源：少接哪一条，对应的那条
# 路径就静默退回旧行为，而其余用例全绿。

@contextlib.contextmanager
def _playing(win):
    """进入即开始播放、退出必停。

    两端都不能省：

    - **进入前先 `stop_playback()`** —— `toggle_play` 是**切换**语义，若上一个用例
      残留 `is_playing=True`，再调它就成了「停止」，断言随即假通过（实测踩到）。
    - **退出必停** —— 留下的 `is_playing=True` 会让**后续**用例的每一次模型变更都
      去重建 playlist，是标准的用例间状态污染。而本文件其余 11 个用例全程在做撤销
      /重做，正好落在被污染的区间里。
    """
    win.stop_playback()
    win.toggle_play()
    assert win.is_playing, "前置条件失败：播放没能开始，后续断言会全部假通过"
    assert win.playlist, "前置条件失败：playlist 为空"
    try:
        yield win
    finally:
        win.stop_playback()


def _expected_playlist(win):
    """按模型**现算**的期望播放列表：未禁用的帧、按模型顺序。"""
    return [f for f in win.timeline.get_all_frames() if f and not f.is_disabled]


def _assert_playlist_fresh(win, what):
    """playlist 必须与模型同序且**同一批对象**。

    不能只比值：`FrameData` 是 dataclass，`==` 是值相等。撤销后的旧对象与模型里的
    新克隆**值可能仍然相同**（例如撤销后又重做、或改的值恰好一样），比值得不出结论。
    必须比身份 —— 这正是本组用例要钉的东西。
    """
    fresh = _expected_playlist(win)
    assert len(win.playlist) == len(fresh), (
        f"{what}：playlist 长度与模型不符（{len(win.playlist)} vs {len(fresh)}）")
    stale = [i for i, (p, m) in enumerate(zip(win.playlist, fresh)) if p is not m]
    assert not stale, (
        f"{what}：playlist 第 {stale} 项不是模型里的当前对象 —— "
        "画面会继续用已失效的旧帧")


def test_playlist_tracks_undo_during_playback():
    """播放中撤销：playlist 必须重建，不能继续用被 `apply_frames` 换掉的旧对象。

    这是 P2-6 记录里那条未修缺陷的主体。撤销的增量路径**刻意**把快照里的帧克隆进
    模型（不复用快照对象，否则后续原地编辑会写进历史），playlist 里缓存的对象就此
    失效 —— 用户撤销后画面继续按旧值播放，看起来像「撤销没生效」。
    """
    win = _reload()
    _edit_scale(win, 0, win.timeline.get_frame_at(0).scale + 0.5)
    with _playing(win):
        win.undo_history()
        _assert_playlist_fresh(win, "播放中撤销后")


def test_playlist_tracks_removed_frame_during_playback():
    """播放中删帧：已删的帧必须立刻从 playlist 消失（否则会继续播出来）。"""
    win = _reload()
    with _playing(win):
        victim = win.timeline.get_frame_at(1)
        win.timeline.model.set_selection([1])
        win.remove_frame()

        assert not any(f is victim for f in win.timeline.get_all_frames()), \
            "前置条件失败：帧没被删掉，后续断言会假通过"
        assert not any(f is victim for f in win.playlist), \
            "已删除的帧仍在 playlist 里 —— 播放会把它再放出来"
        _assert_playlist_fresh(win, "播放中删帧后")


def test_playlist_tracks_inserted_frame_during_playback():
    """播放中加帧：新帧必须进 playlist（否则永远轮不到它）。"""
    win = _reload()
    with _playing(win):
        win.add_files([SAMPLE_IMG])

        added = win.timeline.get_all_frames()[-1]
        assert any(f is added for f in win.playlist), \
            "新加的帧没进 playlist —— 播放永远不会轮到它"
        _assert_playlist_fresh(win, "播放中加帧后")


def test_playlist_tracks_reorder_during_playback():
    """播放中拖拽换序：播放顺序必须跟着模型走。"""
    win = _reload()
    with _playing(win):
        _drag_row(win, 0, 3)  # 内部已断言顺序确实变了
        _assert_playlist_fresh(win, "播放中拖拽换序后")


def test_playlist_tracks_undo_of_row_count_change_during_playback():
    """播放中撤销一次**增删帧**：走的是 `frames_replaced`，与撤销属性变更不是同一条信号。

    撤销属性变更时行数不变，`apply_frames` 走增量路径发 `data_changed`；而撤销加/删
    帧时行数变了，它回落到 `set_frames`，发的是 `frames_replaced`。两条信号各接一次，
    就必须各测一遍 —— 只测前者的话，把 `frames_replaced` 那条连接删掉所有用例照样全绿。
    """
    win = _reload()
    with _playing(win):
        n_before = win.timeline.get_frame_count()
        win.timeline.model.set_selection([1])
        win.remove_frame()
        assert win.timeline.get_frame_count() == n_before - 1, \
            "前置条件失败：帧没被删掉，后续断言会假通过"

        win.undo_history()
        assert win.timeline.get_frame_count() == n_before, \
            "前置条件失败：撤销没有把帧加回来，后续断言会假通过"
        _assert_playlist_fresh(win, "播放中撤销删帧后")


def test_playlist_tracks_disable_during_playback():
    """播放中禁用一帧：被禁的帧必须立刻从 playlist 消失。

    这条钉的是"**刻意不接** `frame_disabled_changed`"那个决断的另一半。不接的前提
    是禁用态的**每一条**写入路径都会自己调 `_refresh_playlist_if_playing()` —— 而
    那是分散的人工调用、不是信号驱动的：少一处，被禁用的帧就继续播，而上面五条
    用例一个都测不到（它们只走结构与内容变更）。

    故两条禁用写入路径**各测一遍**：
      - `toggle_enable_disable` —— 菜单/工具栏的"启用/禁用"；
      - `on_frame_disabled_state_changed` —— 右键菜单与视图勾选（`disabled_state_changed`）。
    第三条（`on_selection_changed`）不是禁用路径，由
    `test_playlist_follows_selection_change_during_playback` 覆盖。
    """
    # 路径一：toggle_enable_disable
    win = _reload()
    with _playing(win):
        win.timeline.model.set_selection([1])
        win.toggle_enable_disable(False)
        assert win.timeline.get_frame_at(1).is_disabled, \
            "前置条件失败：帧没被禁用，后续断言会假通过"

        assert not any(f.is_disabled for f in win.playlist), \
            "被禁用的帧仍在 playlist 里 —— 播放会跳过禁用逻辑把它放出来"
        _assert_playlist_fresh(win, "播放中禁用帧后（toggle_enable_disable）")

    # 路径二：视图勾选/右键菜单 —— 走真实的 `disabled_state_changed` 信号。
    # 该信号由视图在**改完 frame.is_disabled 之后**发出，故这里也要先改再发。
    win = _reload()
    with _playing(win):
        f = win.timeline.get_frame_at(1)
        f.is_disabled = True
        win.timeline.disabled_state_changed.emit(f, True)
        assert win.timeline.get_frame_at(1).is_disabled, \
            "前置条件失败：帧没被禁用，后续断言会假通过"

        assert not any(f.is_disabled for f in win.playlist), \
            "被禁用的帧仍在 playlist 里 —— 播放会跳过禁用逻辑把它放出来"
        _assert_playlist_fresh(win, "播放中禁用帧后（disabled_state_changed）")


def test_playlist_follows_selection_change_during_playback():
    """播放中改选中：playlist 必须跟着变成"只播选中的帧"。

    这是 `on_selection_changed` 里那处 `_refresh_playlist_if_playing()` —— 它既不
    是禁用路径也不是模型变更路径，是第三条独立的人工调用点。
    """
    win = _reload()
    with _playing(win):
        _select_rows_like_user(win, [2, 4])
        expected = [win.timeline.get_frame_at(2), win.timeline.get_frame_at(4)]
        assert len(win.playlist) == len(expected), (
            "播放中改了选中，playlist 却没有跟着变成“只播选中的帧”"
            "（%d vs %d）" % (len(win.playlist), len(expected)))
        # 仍比身份而非比值（理由同 `_assert_playlist_fresh`），但不能复用它 ——
        # 它算的是"播全部"，而这里走的是"只播选中"分支。
        stale = [i for i, (p, e) in enumerate(zip(win.playlist, expected)) if p is not e]
        assert not stale, \
            "播放中改选中后：playlist 第 %s 项不是模型里的当前对象" % stale


def test_playback_stops_when_playlist_empties():
    """播放中把帧删光：必须**当场**停下，不能留下僵尸播放态。

    刷新 playlist 之后不判空的话：`next_frame()` 在列表为空时静默 return，计时器
    继续空转、`is_playing` 一直是 True、按钮卡在"暂停"、状态栏停在最后一帧的文案 ——
    不报错、不崩溃，但界面看起来像卡死，只能靠用户再点一次按钮解开。

    断言必须写在 `_playing` 上下文**内部**：它的 `finally` 也会 `stop_playback()`，
    放到外面就是标准的假通过。
    """
    win = _reload()
    with _playing(win):
        win.timeline.model.set_selection(list(range(win.timeline.get_frame_count())))
        win.remove_frame()
        assert win.timeline.get_frame_count() == 0, \
            "前置条件失败：帧没被删光，后续断言会假通过"

        assert not win.is_playing, "帧全删光了却还在播放 —— 留下僵尸播放态"
        assert not win.timer.isActive(), "播放已停但计时器还在空转"
        assert win.playlist == [], "playlist 没有跟着清空"


def test_playlist_refresh_is_noop_when_not_playing():
    """不播放时模型变更不得动 playlist —— 这是 `_load_from_path` 的安全前提。

    载入工程会批量 emit 一次 `frames_removed`（clear）+ N 次 `frames_inserted`，
    这些信号现在都接到了 `_refresh_playlist_if_playing`。`_load_from_path` 里那条
    「`timeline.clear()` 期间安全」的论证正是建立在这个 `is_playing` 守卫上 ——
    守卫一去掉，载入就会一边灌帧一边重建 playlist，而且是在 `project.frames` 正
    处于半填充状态时。

    五条信号全部走**真实变更**，不用手工 `emit`：这两条结构性信号还有别的订阅者
    （适配层会在 `frames_inserted/removed` 里 `beginInsertRows/beginRemoveRows`），
    伪造 emit 等于往它灌一次**并不存在**的结构变更 —— 测的是守卫，却顺手破坏了
    模型与视图之间的契约（行数没变却通知增减行）。
    """
    win = _reload()
    sentinel = object()
    win.playlist = [sentinel]
    win.play_index = 7

    # 结构类：frames_removed → frames_inserted → frames_reordered
    win.timeline.model.set_selection([0])
    win.remove_frame()
    win.add_files([SAMPLE_IMG])
    _drag_row(win, 0, 3)
    # 内容类：撤销加帧/删帧走 frames_replaced（行数变），撤销属性走 data_changed
    win.undo_history()
    win.undo_history()
    _edit_scale(win, 0, win.timeline.get_frame_at(0).scale + 0.5)
    win.undo_history()

    assert win.playlist == [sentinel], "不播放时 playlist 被刷新了 —— 载入路径的安全前提没了"
    assert win.play_index == 7, "不播放时 play_index 被改了"


# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}")
            print(f"      {e}")
        except Exception as e:  # noqa: BLE001 - 用例里的任何异常都算失败
            failed += 1
            print(f"ERROR {name}")
            print(f"      {type(e).__name__}: {e}")
        else:
            print(f"PASS  {name}")

    print()
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
