#!/usr/bin/env python3
"""时间轴双视图同步 + 拖拽选中 的回归验证（需要显示环境，用 offscreen 平台）。

锁定两次回归的根因：

  1. 在列表视图反转 / 拖拽排序后切到网格视图，顺序错乱。
     根因：整体换序本应走 `frames_reordered`（视图按模型重建），却曾经发
     `data_changed`（视图按索引原地刷新文本、不重排 item），导致界面显示旧顺序。

  2. 多选拖拽后切视图，选中项不是被拖拽的帧。
     根因：`_rebuild_list_view` / `_rebuild_grid_view` 在恢复选中时调用
     `apply_selection_to_view(indices)` 却**没有显式指定目标视图**，于是依赖
     `current_view_mode`——重建 list 时把选中写进了 grid（反之亦然），污染刚拖好的选中。

与 dev/test_transform.py 的分工：
  test_transform.py 的 test_reorder_emits_frames_reordered_not_data_changed 锁住
  **模型信号契约**（顺序变更发 frames_reordered 而非 data_changed）；本脚本锁住
  **视图层实际表现**（重建后两视图顺序一致、选中不串视图）。

依赖：PyQt6 + Pillow（仅为缩略图造一张真实的小 PNG，避免 image_cache 加载缺失文件）。
运行：
    python dev/verify_timeline_view_sync.py
退出码非 0 表示有失败。
"""
import os
import sys
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QEvent, QMetaMethod  # noqa: E402
from PyQt6.QtGui import QDropEvent, QDrag  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from model.project_data import FrameData  # noqa: E402
from ui.timeline import TimelineWidget  # noqa: E402
from ui.timeline_view_signals import TimelineViewSignals  # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="pinframe_view_sync_")
app = QApplication(sys.argv)


def _make_png(name):
    from PIL import Image
    path = os.path.join(_TMPDIR, name)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(path)
    return path


def _frames(n):
    return [FrameData(file_path=_make_png(f"f{i}.png")) for i in range(n)]


def _list_order(tw):
    """列表视图当前呈现的行序（走 model/view，不碰 item）。"""
    return [tw.list_view.get_frame_data_at_index(i).file_path
            for i in range(tw.list_view.get_item_count())]


def _grid_order(tw):
    return [tw.grid_view.get_frame_data_at_index(i).file_path
            for i in range(tw.grid_view.get_item_count())]


def _model_order(tw):
    return [tw.model.get_frame_at(i).file_path for i in range(tw.model.get_frame_count())]


def _fill(tw, n=5):
    for f in _frames(n):
        tw.model.add_frame(f)


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
def test_reverse_sync_both_views():
    """列表视图当前时全量反转，两个视图都应按模型重建为同一顺序。"""
    tw = TimelineWidget()
    _fill(tw)
    tw.model.reverse_frames(None)
    assert _list_order(tw) == _model_order(tw), f"list 反转后未同步: {_list_order(tw)}"
    assert _grid_order(tw) == _model_order(tw), f"grid 反转后未同步: {_grid_order(tw)}"
    # 切到 grid 后，grid 必须仍与模型一致（不能再回到旧顺序）
    tw.set_view_mode("grid")
    assert _grid_order(tw) == _model_order(tw), "切到 grid 后顺序错乱"


def test_drag_order_sync_inactive_view():
    """当前列表视图下拖拽换序，非当前网格视图必须按模型重建为同一顺序。

    对应原始 bug：list 里操作时间轴后切到 grid，数据不一致。
    """
    tw = TimelineWidget()
    _fill(tw)
    order = tw.model.get_all_frames()
    order[0], order[4] = order[4], order[0]  # 模拟拖拽排序的结果
    tw.model.set_frames_order(order)  # 发 frames_reordered → 重建非当前 grid
    assert _grid_order(tw) == _model_order(tw), f"拖拽换序后非当前 grid 未同步: {_grid_order(tw)}"
    tw.set_view_mode("grid")
    assert _grid_order(tw) == _model_order(tw), "切到 grid 后仍不一致"


def test_rebuild_selection_grid_active():
    """当前为网格视图时重建列表视图：选中必须落到 list 上，不污染 grid。"""
    tw = TimelineWidget()
    _fill(tw)
    tw.set_view_mode("grid")  # 当前视图 = grid
    tw.model.set_selection([1, 3])  # 真实选中：grid 视图选中 {1,3}（并同步到模型）
    tw.list_view.clearSelection()  # 让 list 偏离模型选中，制造'重建应修正'的前提
    tw._rebuild_list_view()
    assert set(tw.list_view.get_selected_indices()) == {1, 3}, \
        f"rebuild list 未把选中应用到 list: {tw.list_view.get_selected_indices()}"
    assert set(tw.grid_view.get_selected_indices()) == {1, 3}, \
        f"rebuild list 污染了 grid 选中: {tw.grid_view.get_selected_indices()}"


def test_rebuild_selection_list_active():
    """当前为列表视图时重建网格视图：选中必须落到 grid 上，不污染 list。"""
    tw = TimelineWidget()
    _fill(tw)  # 当前视图默认 = list
    tw.model.set_selection([0, 2])  # 真实选中：list 视图选中 {0,2}（并同步到模型）
    tw.grid_view.clearSelection()
    tw._rebuild_grid_view()
    assert set(tw.grid_view.get_selected_indices()) == {0, 2}, \
        f"rebuild grid 未把选中应用到 grid: {tw.grid_view.get_selected_indices()}"
    assert set(tw.list_view.get_selected_indices()) == {0, 2}, \
        f"rebuild grid 污染了 list 选中: {tw.list_view.get_selected_indices()}"


# ---------------------------------------------------------------------------
# P1-3 第 1 片：模型成为顺序的唯一权威（TimelineModel.move_frames）
# ---------------------------------------------------------------------------
def _names(frames):
    return [f.file_path.rsplit(os.sep, 1)[-1] for f in frames]


def test_clear_notifies_views():
    """model.clear() 必须让两个视图都变空。

    clear() 曾经不发明信号，靠调用方手工 `view.clear()` 清视图 —— 列表视图
    迁到 model/view 后这行直接崩（QTreeView 没有 clear()）。信号必须先于清数据
    发出，否则适配层的 beginRemoveRows 读到的 rowCount 已是 0，Qt 会 abort。
    """
    tw = TimelineWidget()
    _fill(tw)
    assert tw.model.get_frame_count() == 5
    tw.model.clear()
    assert tw.model.get_frame_count() == 0
    assert tw.list_view.get_item_count() == 0, f"list 未清空: {tw.list_view.get_item_count()}"
    assert tw.grid_view.get_item_count() == 0, f"grid 未清空: {tw.grid_view.get_item_count()}"

    # 清完还能继续加帧，且视图跟随
    tw.model.add_frame(_frames(1)[0])
    assert tw.list_view.get_item_count() == 1
    assert tw.grid_view.get_item_count() == 1


def test_move_frames_single_forward():
    """move_frames 的坐标系：insert_index 取"移动前"列表中插入到的位置。"""
    tw = TimelineWidget()
    _fill(tw)
    b = _names(tw.model.get_all_frames())
    assert tw.model.move_frames([0], 3) is True
    after = _names(tw.model.get_all_frames())
    assert after == [b[1], b[2], b[0], b[3], b[4]], after


def test_move_frames_multi_block_backward():
    """多选块整体前移，块内相对顺序保持。"""
    tw = TimelineWidget()
    _fill(tw)
    b = _names(tw.model.get_all_frames())
    assert tw.model.move_frames([3, 4], 1) is True
    after = _names(tw.model.get_all_frames())
    assert after == [b[0], b[3], b[4], b[1], b[2]], after


def test_move_frames_identical_frames():
    """完全相同的帧也必须能重排（顺序按**对象身份**判定，不按 `==`）。

    `FrameData` 是 dataclass，`==` 是自动生成的值相等。工程里完全相同的帧很常见
    —— 复制帧、同一张源图切出的相同区域。曾经 `move_frames` 用
    `new_frames == self._frames` 判有无变化，于是这些帧无论拖到哪儿都相等，
    被判成无变化而静默忽略：用户拖了，什么也没发生，也没有任何提示。

    夹具刻意让所有帧共用同一张源图且参数完全一致（因此两两 `==` 相等），
    只有按身份比较才能看出顺序确实变了。
    """
    tw = TimelineWidget()
    path = _make_png("same.png")
    tw.model.add_frame(FrameData(file_path=path))
    for _ in range(5):
        tw.model.add_frame(tw.model.get_frame_at(0).clone())

    # 前置断言：这些帧在值上确实无法区分，只有身份能区分
    frames = tw.model.get_all_frames()
    assert frames[0] == frames[3], "夹具失效：这些帧应当在值上相等"
    assert frames[0] is not frames[3], "clone() 应当产生新对象"

    assert tw.model.move_frames([0], 3) is True, "相同的帧被误判为无变化"
    order = tw.model.get_all_frames()
    assert order[2] is frames[0], "第 0 帧没有移动到第 2 位"


def test_move_frames_in_place_is_noop():
    """连续块放在自己原位（紧邻其上 / 紧邻其下）必须返回 False 且不动数据。

    视图 dropEvent 曾用这段判据决定 event.ignore()，判据必须留在模型里。
    """
    tw = TimelineWidget()
    _fill(tw)
    b = _names(tw.model.get_all_frames())
    assert tw.model.move_frames([1, 2], 1) is False
    assert tw.model.move_frames([1, 2], 3) is False
    assert _names(tw.model.get_all_frames()) == b


def test_move_frames_carries_selection():
    """被拖的帧在新列表中是连续块，选中必须跟到新位置（跟帧，不跟下标）。"""
    tw = TimelineWidget()
    _fill(tw)
    tw.model.set_selection([0])
    dragged = tw.model.get_frame_at(0)
    assert tw.model.move_frames([0], 3) is True
    assert tw.model.get_selected_indices() == [2], tw.model.get_selected_indices()
    assert tw.model.get_selected_frames() == [dragged]


def test_move_frames_emits_frames_reordered_not_data_changed():
    """整体换序必须发 frames_reordered。

    发 data_changed 的话视图只按索引原地刷新文本、不重排 item —— 模型与导出是对的，
    界面却显示旧顺序，且没有任何报错。
    """
    tw = TimelineWidget()
    _fill(tw)
    seen = []
    tw.model.frames_reordered.connect(lambda: seen.append("reordered"))
    tw.model.data_changed.connect(lambda *_: seen.append("data_changed"))
    tw.model.move_frames([0], 3)
    assert seen == ["reordered"], seen


def test_move_frames_keeps_both_views_in_model_order():
    """顺序变更后两个视图都必须等于模型顺序（这是本片的核心不变量）。"""
    tw = TimelineWidget()
    _fill(tw)
    tw.model.move_frames([0], 3)
    assert _list_order(tw) == _model_order(tw), f"list 未跟随: {_list_order(tw)}"
    assert _grid_order(tw) == _model_order(tw), f"grid 未跟随: {_grid_order(tw)}"


# ---------------------------------------------------------------------------
# 拖拽路径（构造真实的 QDropEvent 走视图 dropEvent，而不是绕过去直接调模型）
# ---------------------------------------------------------------------------
def _internal_drop_event(pos):
    """构造一个内部重排的 QDropEvent（不含 urls，避免走"外部文件拖入"分支）。

    QMimeData 必须挂在 event 上保持引用：QDropEvent 只持有裸指针，不接管所有权，
    局部变量被 GC 后 dropEvent 里再访问 mimeData() 就是悬空指针 → 进程 abort。
    """
    mime = QMimeData()
    mime.setData("application/x-pinframe-internal-reorder", b"reorder")
    event = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QEvent.Type.Drop)
    event._keep_mime = mime
    return event


def test_list_drop_reorders_through_model():
    """列表视图拖拽后，**模型**顺序必须已变，且两视图都等于模型。

    改动前视图自己 takeItem/insertItem 搬 item、模型毫不知情，顺序要等
    MainWindow.on_order_changed 回写 —— 于是这里是"视图与模型不一致"，
    也是切视图后顺序错乱的根源。
    """
    tw = TimelineWidget()
    _fill(tw)
    b = _names(tw.model.get_all_frames())
    view = tw.list_view
    view._dragged_rows = [0]
    view._drag_insert_position = (3, True)  # 插到原 index 3 之前
    view.dropEvent(_internal_drop_event(QPoint(0, 0)))

    assert _names(tw.model.get_all_frames()) == [b[1], b[2], b[0], b[3], b[4]], \
        f"模型顺序未变更: {_names(tw.model.get_all_frames())}"
    assert _list_order(tw) == _model_order(tw), f"list 与模型不一致: {_list_order(tw)}"
    assert _grid_order(tw) == _model_order(tw), f"grid 与模型不一致: {_grid_order(tw)}"


def test_grid_drop_reorders_through_model():
    tw = TimelineWidget()
    _fill(tw)
    tw.set_view_mode("grid")
    b = _names(tw.model.get_all_frames())
    view = tw.grid_view
    view._is_dragging = True
    view._dragged_rows = [0]
    view._drag_insert_position = (3, True)
    view.dropEvent(_internal_drop_event(QPoint(0, 0)))

    assert _names(tw.model.get_all_frames()) == [b[1], b[2], b[0], b[3], b[4]], \
        f"模型顺序未变更: {_names(tw.model.get_all_frames())}"
    assert _grid_order(tw) == _model_order(tw), f"grid 与模型不一致: {_grid_order(tw)}"
    assert _list_order(tw) == _model_order(tw), f"list 与模型不一致: {_list_order(tw)}"


def test_drop_leaves_selection_on_dragged_frames():
    """多选拖拽后，选中的必须还是被拖走的那几帧（跟帧，不跟下标）。"""
    tw = TimelineWidget()
    _fill(tw)
    dragged = [tw.model.get_frame_at(3), tw.model.get_frame_at(4)]
    view = tw.list_view
    view._dragged_rows = [3, 4]
    view._drag_insert_position = (1, True)
    view.dropEvent(_internal_drop_event(QPoint(0, 0)))

    assert tw.model.get_selected_frames() == dragged, \
        f"选中不是被拖的帧: {_names(tw.model.get_selected_frames())}"
    assert tw.model.get_selected_indices() == [1, 2], tw.model.get_selected_indices()


def test_drop_in_place_changes_nothing():
    """连续块放回原位：顺序与选中都不变。"""
    tw = TimelineWidget()
    _fill(tw)
    b = _names(tw.model.get_all_frames())
    tw.model.set_selection([1, 2])
    view = tw.list_view
    view._dragged_rows = [1, 2]
    view._drag_insert_position = (1, True)
    view.dropEvent(_internal_drop_event(QPoint(0, 0)))

    assert _names(tw.model.get_all_frames()) == b
    assert tw.model.get_selected_indices() == [1, 2]


# ---------------------------------------------------------------------------
# 真实鼠标点击（其余选中用例都绕过了这一环）
# ---------------------------------------------------------------------------
def _click_row(view, row, column):
    """在该行该列的单元格中心做一次真实的鼠标点击。"""
    r = view.visualRect(view.model().index(row, column))
    assert r.isValid() and r.width() > 0, f"row{row} 没有排版，无法点击"
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, r.center(), 5)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, r.center(), 5)
    for _ in range(12):  # 等防抖定时器（50ms）触发
        app.processEvents()
        QTest.qWait(10)


def test_click_grid_row_notifies_downstream():
    """鼠标点击网格里的帧，必须向业务层发出**非空**的选中通知。

    为什么单独加这条：其余选中用例都用 `apply_selection_to_view` 或
    `model.set_selection`，**绕过了真实鼠标路径**。于是 25 个用例全绿，却没人发现
    "点了帧，属性面板显示未选中、预览区没反应"。

    根因是两处叠加，都被这条测试盯住：
      1. 网格没设 `SelectRows`：点击只选中**自己那一列**（文件名列 2），而列表按列 0
         读 `selectedRows()` 就认为"什么都没选" —— 两视图对"选中了什么"看法不同。
      2. 网格的 `selectionChanged` 连在 `setSelectionModel()` **之前**：换
         selectionModel 会丢弃旧模型上的连接，网格从此不再发通知；只有列表在发，
         而它算出的是空 —— 空 frames 一路传到属性面板与预览区。

    断言落在发出的 frames 上（而不是"看起来选没选中"），因为它就是被传下去的载荷。
    """
    tw = TimelineWidget()
    _fill(tw)
    tw.set_view_mode("grid")
    tw.resize(600, 400)
    tw.show()
    app.processEvents()

    got = []
    tw.signals.selection_changed.connect(lambda frames: got.append(list(frames)))

    _click_row(tw.grid_view, 2, tw.grid_view.modelColumn())

    assert got, "点击网格后没有发出任何 selection_changed"
    assert len(got[-1]) == 1, f"发出的选中帧数不对（曾为空）: {len(got[-1])}"
    assert got[-1][0] is tw.model.get_frame_at(2), "选中的不是被点击的那一帧"
    assert tw.model.get_selected_indices() == [2]


def test_both_views_agree_on_clicked_row():
    """点击之后两个视图必须对"选中了哪几行"看法一致。

    上一条盯着"通知是否非空"，这条盯着"两视图是否一致" —— 那是第 1 处根因
    （缺少 `SelectRows`）的直接症状：网格看到 [2]、列表看到 []。
    """
    tw = TimelineWidget()
    _fill(tw)
    tw.resize(600, 400)
    tw.show()
    app.processEvents()

    # 网格里点
    tw.set_view_mode("grid")
    app.processEvents()
    _click_row(tw.grid_view, 2, tw.grid_view.modelColumn())
    assert tw.grid_view.get_selected_indices() == [2]
    assert tw.list_view.get_selected_indices() == [2], (
        "列表看不到网格点选的行 —— 选中不是整行，或两视图列不一致: "
        f"{tw.list_view.get_selected_indices()}")

    # 列表里点（反向同样要成立）
    tw.set_view_mode("list")
    app.processEvents()
    _click_row(tw.list_view, 1, 0)
    assert tw.list_view.get_selected_indices() == [1]
    assert tw.grid_view.get_selected_indices() == [1], (
        f"网格看不到列表点选的行: {tw.grid_view.get_selected_indices()}")


# ---------------------------------------------------------------------------
# 上行动作信号：声明只有一份，但**转发清单**是第二处必须同步改的地方
# ---------------------------------------------------------------------------
# 按 QMetaObject 里的参数类型造 emit 用的占位值。类型名来自 C++ 侧的
# 归一化签名（`pyqtSignal(list)` → `QVariantList`，`pyqtSignal(object)` →
# `PyQt_PyObject`），与 Python 注解不是一回事。
_DUMMY_BY_TYPE = {
    "QVariantList": [],
    "PyQt_PyObject": None,
    "bool": False,
    "int": 0,
    "double": 0.0,
    "QString": "",
}


def _declared_view_signals():
    """枚举 `TimelineViewSignals` 上声明的全部信号 → {名字: emit 用的占位参数}。"""
    out = {}
    meta = TimelineViewSignals.staticMetaObject
    for i in range(meta.methodOffset(), meta.methodCount()):
        m = meta.method(i)
        if m.methodType() != QMetaMethod.MethodType.Signal:
            continue
        name = m.name().data().decode()
        args = []
        for t in m.parameterTypes():
            tname = t.data().decode()
            assert tname in _DUMMY_BY_TYPE, (
                f"信号 {name} 的参数类型 {tname} 没有占位值 —— 补进 _DUMMY_BY_TYPE，"
                f"否则这条测试会用一个错误的实参去 emit 它")
            args.append(_DUMMY_BY_TYPE[tname])
        out[name] = args
    return out


def test_every_view_signal_reaches_timeline_widget():
    """视图 `signals` 上的每一条信号，都必须真的冒到 `TimelineWidget.signals`。

    为什么加这条：声明已经收敛到 `ui/timeline_view_signals.py` 一份了（此前是三个
    文件各抄一遍，加一个右键菜单项要改三个文件），但 `TimelineWidget.
    _connect_view_signals` 里的**转发清单**是第二个必须同步改动的地方 —— 新加一个
    信号却忘了在那儿加一行，Python 不报错、也没有任何测试变红，表现只是"右键菜单
    这一项点了没反应"。这和"用字符串/枚举合并信号"是同一类失败模式，只是位置从
    声明处搬到了转发处。

    断言落在**行为**上而不是比对名字：真的从视图 emit 一次，看 `TimelineWidget`
    那侧收不收得到。名字比对挡不住"连了但连错对象"这种情况。

    唯一例外 `thumbnail_size_changed`：它不直连，而是接到
    `_on_grid_thumbnail_changed`（先把尺寸记进 `grid_thumbnail_width/height` 再
    re-emit），且只有网格视图会连 —— 列表视图没有缩略图尺寸这个概念。它是刻意的
    特例，故被显式豁免；**不要**往这个集合里加第二个名字。
    """
    tw = TimelineWidget()
    _fill(tw)

    declared = _declared_view_signals()
    assert declared, "从 TimelineViewSignals 上枚举不到任何信号 —— 检查方式本身失效了"

    only_grid = {"thumbnail_size_changed"}

    for name, args in sorted(declared.items()):
        sources = {"grid": tw.grid_view}
        if name not in only_grid:
            sources["list"] = tw.list_view

        for who, view in sources.items():
            got = []
            dst = getattr(tw.signals, name)

            def _recv(*_a, _got=got):
                _got.append(True)

            dst.connect(_recv)
            try:
                getattr(view.signals, name).emit(*args)
            finally:
                dst.disconnect(_recv)

            assert got, (
                f"{who} 视图的 {name} 没有转发到 TimelineWidget —— "
                f"`_connect_view_signals` 里漏了一行？")


# ---------------------------------------------------------------------------
# 适配层必须真的接在业务模型上（否则视图收不到任何变更通知）
# ---------------------------------------------------------------------------
def test_adapter_model_is_wired_to_frames_model():
    """适配层必须真的把业务模型的信号转发成 Qt 的结构变更通知。

    曾经 `TimelineItemModel.__init__` 先给 `_frames` 赋值再调 `bind()`，而 `bind()`
    开头有"已绑定则直接返回"的防重入判断 —— 构造时传入 model 的那个实例**永远不会
    接线**（`_connect_frames_model()` 一次都没被调用）。

    后果很隐蔽：`rowCount()` 是实时查模型的，所以"有多少行"始终是对的；但只要没有
    Resize/Show 或显式 refresh，视图就不会重新取数 —— 表现为"加载完工程后时间轴是
    空的，拖一下面板或改一下缩略图尺寸才出来"。

    这条直接断言信号被转发，而不是靠"界面看起来对不对" —— 后者在有 Resize 兜底时
    根本测不出来（本套件此前 23 个用例就是这么全绿的）。
    """
    tw = TimelineWidget()
    seen = []
    tw.item_model.rowsInserted.connect(lambda *_: seen.append("inserted"))
    tw.model.add_frame(_frames(1)[0])
    assert seen == ["inserted"], f"适配层没有转发新增: {seen}"

    tw.item_model.dataChanged.connect(lambda *_: seen.append("changed"))
    tw.model.data_changed.emit(0, 0)
    assert "changed" in seen, f"适配层没有转发内容变更: {seen}"


def test_views_follow_model_without_manual_refresh():
    """模型变了，视图必须跟着变 —— 中间不能有 resize/show/refresh 兜底。

    这条盯的是真实故障：加载工程时视图已就绪，帧是后加进去的。若适配层没接线，
    视图就停在旧状态，只在被 Resize 时才碰巧刷出来。
    """
    tw = TimelineWidget()
    tw.resize(600, 400)
    tw.show()
    app.processEvents()

    # 视图就绪之后才加帧（"加载工程"的真实时序）
    for f in _frames(4):
        tw.model.add_frame(f)
    app.processEvents()

    assert tw.list_view.get_item_count() == 4
    assert tw.grid_view.get_item_count() == 4

    # 并且真的排好了版（visualRect 有效 = 会被画出来）
    idx = tw.list_view.model().index(0, 0)
    assert tw.list_view.visualRect(idx).isValid(), "列表视图没有为新增的行排版"
    grect = tw.grid_view.visualRect(
        tw.grid_view.model().index(0, tw.grid_view.modelColumn()))
    assert grect.isValid() and grect.width() > 0 and grect.height() > 0, \
        f"网格视图没有为新增的行排版: {grect}"


# ---------------------------------------------------------------------------
# P1-3 第 3 片：set_frames（撤销恢复走这条路）
# ---------------------------------------------------------------------------
def test_set_frames_emits_single_signal():
    """`set_frames` 只发**一条**信号，而不是 clear() + 逐帧 add_frame 的 N+1 条。

    撤销恢复曾经是 `clear()` + N 次 `add_frame()`，即 1 次移除 + N 次插入，每条都会
    让视图做一次布局调整。换成整体替换后只有一条 `frames_replaced`。
    """
    tw = TimelineWidget()
    _fill(tw)
    seen = []
    tw.model.frames_replaced.connect(lambda: seen.append("replaced"))
    tw.model.frames_removed.connect(lambda *_: seen.append("removed"))
    tw.model.frames_inserted.connect(lambda *_: seen.append("inserted"))
    tw.model.data_changed.connect(lambda *_: seen.append("data_changed"))

    tw.model.set_frames(_frames(4))
    assert seen == ["replaced"], f"应当只有一条 frames_replaced，实际: {seen}"


def test_set_frames_updates_both_views():
    """整体替换后两个视图的行数都要跟着变（行数可变，是它与 set_frames_order 的关键区别）。"""
    tw = TimelineWidget()
    _fill(tw, 3)
    tw.model.set_frames(_frames(6))
    assert tw.model.get_frame_count() == 6
    assert tw.list_view.get_item_count() == 6, f"list 未跟随: {tw.list_view.get_item_count()}"
    assert tw.grid_view.get_item_count() == 6, f"grid 未跟随: {tw.grid_view.get_item_count()}"
    for i in range(6):
        assert tw.list_view.get_frame_data_at_index(i) is tw.model.get_frame_at(i)

    tw.model.set_frames(_frames(2))  # 变少也要跟随
    assert tw.list_view.get_item_count() == 2
    assert tw.grid_view.get_item_count() == 2


def test_set_frames_drops_stale_selection_and_reference():
    """替换后越界的选中下标要丢弃、不在新列表里的参考帧要清空。

    撤销恢复随后会按快照重设这两者，但模型不能先留下一个越界的中间态 ——
    那会让"选中 [4]"指向一个不存在的行。
    """
    tw = TimelineWidget()
    _fill(tw, 5)
    ref = tw.model.get_frame_at(4)
    tw.model.set_reference_frame(ref)
    tw.model.set_selection([2, 4])

    tw.model.set_frames(_frames(3))  # 5 → 3 帧，下标 4 与参考帧都失效
    assert tw.model.get_selected_indices() == [2], tw.model.get_selected_indices()
    assert tw.model.get_reference_frame() is None


# ---------------------------------------------------------------------------
# P1-3 第 2 片-b：两个视图共享同一个 QItemSelectionModel
# ---------------------------------------------------------------------------
def test_both_views_share_selection_model():
    """两个视图必须共享**同一个** `QItemSelectionModel` —— 选中只有一份。

    这是 P1-3 最大的一条收益，但也是最容易"以为做到了其实没有"的一条：
    **两个视图 `setModel()` 同一个 model 实例，并不会共享选中** —— Qt 的
    `QAbstractItemView.setModel()` 会给每个视图各建一个新的 QItemSelectionModel。
    必须显式 `grid_view.setSelectionModel(list_view.selectionModel())`。

    不共享的话选中就有两份源，于是"在一个视图里选、切到另一个视图看"需要同步仪式，
    而这套仪式正是迁移前一连串缺陷的来源。
    """
    tw = TimelineWidget()
    _fill(tw)
    assert tw.list_view.selectionModel() is tw.grid_view.selectionModel(), \
        "两个视图没有共享 QItemSelectionModel —— 选中又变成两份了"


def test_selection_visible_from_both_views():
    """在列表里选中，网格必须也能看到那几行（反之亦然）。

    与上一条的分工：那条断言**机制**（同一个 selectionModel 对象），这条断言
    **效果**（用户真的看得到）。机制对了效果未必对 —— 例如若选中只落在某一列上，
    另一个视图按自己的 modelColumn 过滤就会什么都看不到。

    两个视图显示的是**不同的列**（列表是序号列 0、网格是文件名列 2），这正是这条
    测试要盯住的点：选中必须整行生效（`SelectionFlag.Rows`）。
    """
    tw = TimelineWidget()
    _fill(tw)

    tw.model.set_selection([0, 2])
    tw.apply_selection_to_view({0, 2}, "list")
    assert tw.grid_view.get_selected_indices() == [0, 2], \
        f"网格看不到列表里选中的行（列不一致导致）: {tw.grid_view.get_selected_indices()}"

    # 在网格里改选，列表也必须跟着变
    tw.apply_selection_to_view({1, 3}, "grid")
    assert tw.list_view.get_selected_indices() == [1, 3], \
        f"列表看不到网格里选中的行: {tw.list_view.get_selected_indices()}"


# ---------------------------------------------------------------------------
# 从鼠标手势到 startDrag（其余拖拽用例都绕过了这一环）
# ---------------------------------------------------------------------------
def test_multi_select_drag_starts_drag():
    """多选后按住已选中行拖动，必须**启动拖拽**，而不是扩展选区。

    为什么单独加这条：其余拖拽用例都是直接构造 `QDropEvent` 再调 `dropEvent`，
    **绕过了 startDrag**。所以 `flags()` 漏掉 `ItemIsDragEnabled` 那次回归，
    15 个测试全绿，只有人手工拖才发现拖不动。

    根因记录：`view.setDragEnabled(True)` 并不足以让 Qt 启动拖拽 ——
    `QAbstractItemView.mouseMoveEvent` 还要再查一次 **model 的 flags** 里有没有
    `ItemIsDragEnabled`。缺了这个位，view 进入 `DragSelectingState`，把手势解释成
    扩展选区（表现为"拖不动、一拖选区反而乱变"）。迁移前 `QTreeWidget` 用内建 model，
    flags 默认就带这个位，所以从未暴露。

    验证手法：stub `QDrag.exec`（避免进入嵌套事件循环），在它被调用的那一刻读取
    `_dragged_rows` —— 那是 `startDrag` 设置、且会在 `exec()` 返回后被清空的字段。
    """
    tw = TimelineWidget()
    _fill(tw)
    tw.resize(600, 400)
    tw.show()
    app.processEvents()

    tw.model.set_selection([0, 1])
    tw.apply_selection_to_view([0, 1], "list")
    app.processEvents()

    view = tw.list_view
    captured = {}
    orig_exec = QDrag.exec

    def spy_exec(drag, *args, **kwargs):
        v = drag.parent()
        captured['rows'] = list(getattr(v, '_dragged_rows', []))
        captured['selection'] = sorted(
            {i.row() for i in v.selectionModel().selectedRows()})
        return Qt.DropAction.MoveAction

    QDrag.exec = spy_exec
    try:
        r0 = view.visualRect(view.model().index(0, 0)).center()
        r3 = view.visualRect(view.model().index(3, 0)).center()
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, r0, 5)
        for i in range(1, 6):
            p = QPoint(r0.x(), r0.y() + (r3.y() - r0.y()) * i // 5)
            QTest.mouseMove(view.viewport(), p, 5)
            app.processEvents()
    finally:
        QDrag.exec = orig_exec

    assert captured, (
        "拖拽没有启动（startDrag 未被调用）。典型的成因是 model 的 flags() 少了 "
        "ItemIsDragEnabled —— Qt 会把手势当成扩展选区，而不是拖放")
    assert captured['rows'] == [0, 1], f"拖的不是被选中的行: {captured['rows']}"
    assert captured['selection'] == [0, 1], (
        "拖拽期间选区被改乱了（这正是“拖不动反而变选区”的现象）: "
        f"{captured['selection']}")


def test_grid_multi_select_drag_starts_drag():
    """网格视图同样必须能从鼠标手势启动拖拽（拖拽不能只有列表能用）。"""
    tw = TimelineWidget()
    _fill(tw)
    tw.set_view_mode("grid")
    tw.resize(600, 400)
    tw.show()
    app.processEvents()

    tw.model.set_selection([0, 1])
    tw.apply_selection_to_view([0, 1], "grid")
    app.processEvents()

    view = tw.grid_view
    captured = {}
    orig_exec = QDrag.exec

    def spy_exec(drag, *args, **kwargs):
        v = drag.parent()
        captured['rows'] = list(getattr(v, '_dragged_rows', []))
        return Qt.DropAction.MoveAction

    QDrag.exec = spy_exec
    try:
        r0 = view.visualRect(view.model().index(0, view.modelColumn())).center()
        r3 = view.visualRect(view.model().index(3, view.modelColumn())).center()
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, r0, 5)
        for i in range(1, 6):
            p = QPoint(r0.x() + (r3.x() - r0.x()) * i // 5, r0.y())
            QTest.mouseMove(view.viewport(), p, 5)
            app.processEvents()
    finally:
        QDrag.exec = orig_exec

    assert captured, "网格视图的多选拖拽没有启动（startDrag 未被调用）"
    assert captured['rows'] == [0, 1], f"拖的不是被选中的行: {captured['rows']}"


# ---------------------------------------------------------------------------
# 运行入口
# ---------------------------------------------------------------------------
def _run_all():
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {name}: {e}")
            failed.append(name)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        rc = _run_all()
    finally:
        shutil.rmtree(_TMPDIR, ignore_errors=True)
    sys.exit(rc)
