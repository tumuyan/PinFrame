#!/usr/bin/env python3
"""时间轴双视图同步 + 拖拽选中 的回归验证（需要显示环境，用 offscreen 平台）。

锁定两次回归的根因：

  1. 在列表视图反转 / 拖拽排序后切到网格视图，顺序错乱。
     根因：整体换序本应走 `frames_reordered`（视图按模型重建），却曾经发
     `data_changed`（视图按索引原地刷新文本、不重排 item），导致界面显示旧顺序。

  2. 多选拖拽后切视图，选中项不是被拖拽的帧。
     根因：`_rebuild_list_view` / `_rebuild_grid_view` 在恢复选中时调用
     `_apply_selection_to_view(indices)` 却**没有显式指定目标视图**，于是依赖
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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from model.project_data import FrameData  # noqa: E402
from ui.timeline import TimelineWidget  # noqa: E402

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
    return [tw.list_view.get_frame_data_at_index(i).file_path
            for i in range(tw.list_view.topLevelItemCount())]


def _grid_order(tw):
    return [tw.grid_view.get_frame_data_at_index(i).file_path
            for i in range(tw.grid_view.count())]


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
    assert tw._view_in_sync_with_model("grid"), "切到 grid 后 _view_in_sync_with_model 报不一致"


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
    assert tw._view_in_sync_with_model("grid"), "切到 grid 后仍不一致"


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
