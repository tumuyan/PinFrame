#!/usr/bin/env python3
"""P1-3 第 1 片冒烟：整个 MainWindow 链路下拖拽重排 + 撤销是否还成立。

只覆盖"接线"，不替代 dev/verify_timeline_view_sync.py 的契约测试：
  - MainWindow 能加载真实工程；
  - 载入后参考帧被清除、第一帧被选中（参考帧有两份真源，只清一份的残留最难查）；
  - 视图拖拽 → model.move_frames → 视图重排；
  - 撤销快照是在改模型**之前**捕获的（这是本片最容易错的接线：
    顺序改为当场生效后，等到 order_changed 再捕获快照就是新顺序，撤销变空操作）。

运行： ./venv/bin/python dev/smoke_reorder.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QEvent  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402
from i18n.manager import i18n  # noqa: E402
from ui.timeline_item_model import FrameDataRole, ReferenceRole  # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow  # noqa: E402


def internal_drop_event():
    mime = QMimeData()
    mime.setData("application/x-pinframe-internal-reorder", b"reorder")
    event = QDropEvent(QPointF(QPoint(0, 0)), Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QEvent.Type.Drop)
    event._keep_mime = mime  # QDropEvent 不接管 QMimeData 所有权
    return event


def sig(win):
    """帧的稳定签名，用来表达"顺序"。

    不能用文件名：夹具的 15 帧共用同一张源图（只有裁切不同），按名字比任何顺序都相等，
    断言会假通过。
    也不能用对象身份：撤销是全量深拷贝快照（P2-6），恢复后帧对象全是新的 —— 用它
    比较会让"顺序没变"也被判成失败。
    """
    # crop_rect 可能为 None（新加的帧没裁切），不能直接 tuple(None)
    return [tuple(f.crop_rect or ()) + (f.scale, f.rotation, f.is_disabled)
            for f in win.timeline.get_all_frames()]


def show(seq, n=5):
    return " ".join(str(s[0]) for s in seq[:n]) + (" ..." if len(seq) > n else "")


def first_diff(a, b):
    """首个不同之处的描述 —— 长列表直接比较失败时看不出原因，必须给出定位。"""
    if len(a) != len(b):
        return f"长度不同: {len(a)} vs {len(b)}"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"第 {i} 项: {x} != {y}"
    return "无差异"


def main():
    win = MainWindow()
    project = os.path.join(REPO_ROOT, "dev", "test_long2.json")
    win._load_from_path(project)

    total = win.timeline.get_frame_count()
    print(f"loaded: {total} frames")
    assert total > 3, f"工程帧数太少，无法验证拖拽: {total}"

    # ---- 载入后：参考帧必须清除，第一帧必须选中 ----
    # 参考帧**不持久化**（ProjectData.to_json 里没有这个字段），但它有两份真源：
    #   MainWindow.reference_frame —— 画布读它；
    #   TimelineModel._reference_frame —— 时间轴高亮读它。
    # 载入时 `timeline.clear()` 只会清掉后者。不清前者，画布就会继续画**上一个
    # 工程**的帧对象——那个对象已经不在帧列表里，症状是"参考帧凭空出现且无法取消"。
    # 所以这里先**故意设一个**参考帧，再重载工程，验证两份都被清掉。
    # 视图 → 模型的选中回写走 50ms 防抖定时器（`_selection_debounce_timer`），
    # 不推进事件循环的话 `get_selected_frames()` 恒为空，下面的设置会静默失败。
    win.timeline.setCurrentRow(1)
    QTest.qWait(80)
    win.set_reference_frame_from_selection()
    assert win.reference_frame is win.timeline.get_frame_at(1), \
        "前置条件失败：设置参考帧没落到 MainWindow 那份"
    assert win.canvas.reference_frame is win.reference_frame, \
        "前置条件失败：设置参考帧没落到画布"

    win._load_from_path(project)

    assert win.reference_frame is None, "载入后 MainWindow 那份参考帧未清除"
    assert win.canvas.reference_frame is None, \
        "载入后画布仍在画上一个工程的参考帧（跨工程残留）"
    assert win.timeline.model.get_reference_frame() is None, \
        "载入后业务模型那份参考帧未清除"
    # 时间轴高亮走 ReferenceRole 读业务模型，第一帧不能被误标成参考帧
    assert win.timeline.list_view.model().index(0, 2).data(ReferenceRole) is False, \
        "载入后第一帧被误标成参考帧"
    QTest.qWait(80)  # 同上：等选中防抖回写
    assert win.timeline.get_selected_indices_from_model() == [0], \
        f"载入后应默认选中第一帧，实际 {win.timeline.get_selected_indices_from_model()}"
    assert win.set_ref_action.text() == i18n.t("action_set_reference"), \
        f"载入后菜单文案应回到'设置参考帧'，实际 {win.set_ref_action.text()!r}"
    print("载入后：参考帧已清除（两份真源）、第一帧已选中")

    def _sig_of(frame):
        return tuple(frame.crop_rect) + (frame.scale, frame.rotation, frame.is_disabled)

    before = sig(win)
    print("before:", show(before))

    # 把第 0 帧拖到"原第 3 帧之前"
    view = win.timeline.list_view
    view._dragged_rows = [0]
    view._drag_insert_position = (3, True)
    view.dropEvent(internal_drop_event())

    after = sig(win)
    expected = before[1:3] + [before[0]] + before[3:]
    print("after :", show(after))
    assert after == expected, f"顺序不对\n  期望 {show(expected, 8)}\n  实际 {show(after, 8)}"

    # 视图必须跟着模型
    view_order = [_sig_of(view.get_frame_data_at_index(i))
                  for i in range(view.get_item_count())]
    assert view_order == after, "视图顺序与模型不一致"

    # 撤销：快照必须捕获到的是拖拽**前**的顺序
    assert win.history.can_undo, "拖拽没有留下撤销记录"
    win.undo_history()
    restored = sig(win)
    print("undone:", show(restored))
    assert restored == before, f"撤销未还原到拖拽前\n  期望 {show(before, 8)}\n  实际 {show(restored, 8)}"

    # 反证：快照确实来自 reorder_about_to_happen（改模型**之前**）。
    # 把它换成 no-op 后拖拽就不再产生撤销记录 —— 说明 on_order_changed 自己
    # 当场捕获快照是抓不到前态的（那时模型已经是新顺序），这个信号不是多余接线。
    original_capture = win._capture_reorder_snapshot
    win._capture_reorder_snapshot = lambda: None
    depth_before = win.history.count()
    view._dragged_rows = [0]
    view._drag_insert_position = (2, True)
    view.dropEvent(internal_drop_event())
    win._capture_reorder_snapshot = original_capture
    assert win.history.count() == depth_before, (
        "去掉 reorder_about_to_happen 后仍产生了撤销记录 —— "
        "说明快照不是来自该信号，接线可能有问题")
    print("反证通过：撤销快照确实捕获于改模型之前")

    # ---- 列表视图迁移到 model/view 之后的专属路径 ----
    list_view = win.timeline.list_view
    item_model = list_view.model()

    # 8 列数据映射：列 0 序号、列 2 文件名、列 6/7 分辨率必须都能取到
    assert item_model.columnCount() == 8, item_model.columnCount()
    # 断言"显示的 == 源图基名（+ 可选的切片后缀）"，从帧的 file_path **推导**
    # 期望值，不硬编码任何具体文件名或扩展名。
    #
    # 为什么必须推导：素材文件名是夹具的任意属性，不是被测行为。这里曾两度因为
    # 写死素材名而假失败 —— 一次是切片帧的 `[行,列]` 后缀，一次是素材从 .jpg
    # 换成 .png。被测行为是"文件名列展示源图基名"，与它叫什么无关。
    row0_frame = win.timeline.get_frame_at(0)
    expected_base = os.path.basename(row0_frame.file_path)
    row0_file = item_model.index(0, 2).data(Qt.ItemDataRole.DisplayRole)
    assert row0_file, "列2 文件名为空"
    assert row0_file.split(" [")[0] == expected_base, \
        f"列2 文件名异常: 显示 {row0_file!r}，源图基名 {expected_base!r}"
    # 切片帧应带 `[行,列]` 后缀（test_long2.json 全部含 slice_pos）
    if row0_frame.slice_pos:
        assert row0_file.endswith(
            f" [{row0_frame.slice_pos[0]},{row0_frame.slice_pos[1]}]"), \
            f"切片后缀缺失: {row0_file!r}"
    assert item_model.index(0, 0).data(Qt.ItemDataRole.DisplayRole) == "1"
    assert "x" in (item_model.index(0, 7).data(Qt.ItemDataRole.DisplayRole) or ""), \
        f"列7 缩放后分辨率异常: {item_model.index(0, 7).data(Qt.ItemDataRole.DisplayRole)}"
    # 表头文案（i18n）
    for col in range(8):
        assert item_model.headerData(col, Qt.Orientation.Horizontal), f"列{col} 无表头"

    # 帧属性改了，单元格必须跟着变（data() 现算，不缓存）
    scale_before = item_model.index(0, 3).data(Qt.ItemDataRole.DisplayRole)
    win.timeline.get_frame_at(0).scale = 2.0
    win.timeline.model.data_changed.emit(0, 0)
    scale_after = item_model.index(0, 3).data(Qt.ItemDataRole.DisplayRole)
    assert scale_after == "2.0000" and scale_after != scale_before, \
        f"改 scale 后单元格未更新: {scale_before} -> {scale_after}"

    # 禁用切换：点列 1 应改模型真源，且 delegate 能经 FrameDataRole 读到
    frame0 = win.timeline.get_frame_at(0)
    was_disabled = frame0.is_disabled
    idx_col1 = item_model.index(0, 1)
    assert idx_col1.data(FrameDataRole) is frame0, "FrameDataRole 取不到帧"
    win.timeline.model.set_frame_disabled(0, not was_disabled)
    assert frame0.is_disabled is not was_disabled
    win.timeline.model.set_frame_disabled(0, was_disabled)  # 还原

    # 参考帧高亮：背景由 model 提供，且前缀幂等（不会重复叠加）
    ref_frame = win.timeline.get_frame_at(2)
    list_view.set_visual_reference_frame(ref_frame)
    fname_cell = item_model.index(2, 2).data(Qt.ItemDataRole.DisplayRole)
    prefix = i18n.t("label_ref_prefix")
    assert fname_cell.count(prefix) == 1, f"参考帧前缀重复叠加: {fname_cell}"
    assert item_model.index(2, 2).data(Qt.ItemDataRole.BackgroundRole) is not None
    assert item_model.index(0, 2).data(Qt.ItemDataRole.BackgroundRole) is None
    # 再设一次同一个参考帧，前缀仍只出现一次（迁移前用字符串 replace 会误删同名文件）
    list_view.set_visual_reference_frame(ref_frame)
    assert item_model.index(2, 2).data(Qt.ItemDataRole.DisplayRole).count(prefix) == 1
    list_view.set_visual_reference_frame(None)

    print("列映射 / 属性刷新 / 禁用切换 / 参考帧高亮 均正常")

    # ---- 撤销恢复（P2-6：整体替换，一条信号）----
    # 覆盖"行数变化"的撤销：加帧后撤销（行数变少）、删帧后撤销（行数变多）。
    # 只测拖拽重排的撤销是不够的 —— 那条路径行数不变，走不到 set_frames 里
    # "行数可变"的分支（而这正是它与 set_frames_order 的关键区别）。
    # 必须先清历史栈：上一节的"反证"拖拽**刻意不记录历史**（它就是要证明撤销快照
    # 来自 `reorder_about_to_happen`），于是模型状态与历史栈已经不同步了。带着这个
    # 不同步往下走，undo 恢复到的是上一节遗留的快照，断言会被严重误导 ——
    # 看起来像撤销坏了，实际是测试自身的状态污染。
    win.history.clear()

    # 刻意用 `add_files` / `remove_frame` 这两个**真实动作**，而不是手工
    # `record_history()` —— 后者在 before==after 时会静默跳过、根本不留历史。
    base_count = win.timeline.get_frame_count()
    base_sig = sig(win)

    src = win.timeline.get_frame_at(0).file_path
    win.add_files([src], index=base_count)  # 末尾加一帧
    assert win.timeline.get_frame_count() == base_count + 1, "add_files 未加上帧"
    assert win.history.can_undo, "add_files 没有留下撤销记录"

    # 撤销期间应只发一条结构变更信号（整体替换），而不是 clear()+逐帧 add 的 N+1 条
    seen = []
    win.timeline.model.frames_replaced.connect(lambda: seen.append("replaced"))
    win.timeline.model.frames_removed.connect(lambda *_: seen.append("removed"))
    win.timeline.model.frames_inserted.connect(lambda *_: seen.append("inserted"))
    win.undo_history()
    assert win.timeline.get_frame_count() == base_count, \
        f"撤销加帧后行数未恢复: {win.timeline.get_frame_count()} != {base_count}"
    assert sig(win) == base_sig, "撤销加帧后内容未恢复: " + first_diff(sig(win), base_sig)
    assert seen == ["replaced"], f"撤销恢复应只发一条 frames_replaced，实际: {seen}"

    # 删帧后撤销（行数变多）
    win.timeline.model.set_selection([0])
    win.remove_frame()
    assert win.timeline.get_frame_count() == base_count - 1, "remove_frame 未删掉帧"
    win.undo_history()
    assert win.timeline.get_frame_count() == base_count, \
        f"撤销删帧后行数未恢复: {win.timeline.get_frame_count()} != {base_count}"
    assert sig(win) == base_sig, "撤销删帧后内容未恢复"

    print("撤销恢复（加帧/删帧，行数可变）正常")

    print("\nOK: 拖拽重排与撤销在完整 MainWindow 链路下均正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
