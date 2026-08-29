#!/usr/bin/env python3
"""参考帧生命周期 + 洋葱皮抑制 的 MainWindow 接线冒烟。

---------------------------------------------------------------------------
为什么单独一个文件（而不是塞进 smoke_reorder.py）
---------------------------------------------------------------------------
`smoke_reorder.py` 的主题是"拖拽重排 + 撤销"，参考帧塞进去会让它失去焦点。
而参考帧恰好是本项目**最容易被改坏**的一块，值得有自己的一张网：

  1. 它有**两份真源**：
       - `MainWindow.reference_frame`      —— 画布读它；
       - `TimelineModel._reference_frame`  —— 时间轴高亮读它（经 `ReferenceRole`）。
     两份之间没有信号连接（业务模型的 `reference_changed` 无人接收），全靠每个
     写入点**记得同时写两边**。漏一处就表现为"时间轴亮着但预览没有效果"，
     或反过来。所以本文件的每条断言都同时检查三处（MainWindow / canvas / 模型）。

  2. 它**不持久化**（工程 JSON 里没有这个字段），于是每次载入/新建都必须显式
     清除。清漏一份就是跨工程残留 —— 画布继续画上一个工程的帧对象。

  3. `MainWindow` 里曾经躺着 5 个重复定义（`configure_reference_settings` ×3、
     `update_onion_state` ×3），删掉之后这一片**零覆盖**。本文件补上。

---------------------------------------------------------------------------
一条必须记住的测试机制
---------------------------------------------------------------------------
视图 → 模型的选中回写走 50ms 防抖定时器（`_selection_debounce_timer`）。不推进
事件循环的话 `get_selected_frames()` 恒为空，于是"设置参考帧"会静默失败、而所有
断言看起来像是被测代码坏了。所以每个改动选中的地方后面都跟一次 `_select()`。

依赖：PyQt6；`dev/test_long2.json`（15 帧，来自同一张源图但裁切互不相同）。
运行： ./venv/bin/python dev/smoke_reference_frame.py
退出码非 0 表示有失败。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from i18n.manager import i18n  # noqa: E402
from ui.timeline_item_model import ReferenceRole  # noqa: E402

app = QApplication(sys.argv)

# 导入模块本身（而不只是类）是为了后面能替换 `ReferenceSettingsDialog`
import ui.main_window as main_window_mod  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

PROJECT = os.path.join(REPO_ROOT, "dev", "test_long2.json")

# 选中防抖是 50ms，给一倍余量
SETTLE_MS = 80

_win = None


def win():
    """共享一个 MainWindow —— 构造它要建画布/面板/菜单，不便宜。"""
    global _win
    if _win is None:
        _win = MainWindow()
    return _win


def reload_project():
    """重载工程，得到一个干净的起点（顺带覆盖"载入清参考帧"这个前提）。"""
    win()._load_from_path(PROJECT)
    return win()


def _select(row):
    """选中第 row 行并等模型收到。

    为什么必须等：`setCurrentRow` 只改 Qt 的 selectionModel，回写到业务模型要等
    防抖定时器。不等的话下面所有"选中 → 设置参考帧"的断言都会拿到空选中。
    """
    win().timeline.setCurrentRow(row)
    QTest.qWait(SETTLE_MS)


def _ref_highlighted(row):
    """第 row 行在时间轴上是否按参考帧高亮（走 model 的 ReferenceRole）。"""
    return bool(win().timeline.list_view.model().index(row, 2).data(ReferenceRole))


def _set_reference_at(row):
    """选中第 row 行并把它设为参考帧。

    为什么先强制归零：`set_reference_frame_from_selection` 是 **toggle** 语义
    （对同一帧再点一次 = 取消）。上一个用例若残留了参考帧，本函数会静默变成
    "取消"，后续断言拿到空状态 —— 症状像是被测代码坏了，其实是测试自身污染。
    破坏性验证时尤其明显：那时 `clear_reference_frame` 可能正是被改坏的对象。
    """
    w = win()
    _select(row)
    w.clear_reference_frame()
    # 双保险：上面那句在破坏验证下可能不起作用，直接写真源保证前置成立
    w.reference_frame = None
    w.timeline.model.set_reference_frame(None)
    w.set_reference_frame_from_selection()
    return w.timeline.get_frame_at(row)


def _assert_all_sources_are(frame, what):
    """参考帧的三处真源必须同时是 `frame`（None 表示同时清空）。"""
    w = win()
    assert w.reference_frame is frame, f"{what}: MainWindow.reference_frame 未同步"
    assert w.canvas.reference_frame is frame, f"{what}: canvas.reference_frame 未同步"
    assert w.timeline.model.get_reference_frame() is frame, \
        f"{what}: TimelineModel 未同步 —— 时间轴高亮会与预览分家"


# ---------------------------------------------------------------------------
# 参考帧：设置 / 清除
# ---------------------------------------------------------------------------
def test_set_reference_writes_all_three_sources():
    """设置参考帧必须同时写进三处真源。

    这是本文件最重要的一条：`MainWindow` 与业务模型之间**没有信号连接**，
    漏写任何一处都不会报错，只会静默地让高亮与预览分家。
    """
    w = reload_project()
    ref = _set_reference_at(2)

    _assert_all_sources_are(ref, "设置参考帧")
    assert _ref_highlighted(2), "第 2 行没有按参考帧高亮"
    assert not _ref_highlighted(0), "未设为参考帧的行不应高亮"
    assert w.set_ref_action.text() == i18n.t("action_cancel_reference"), \
        f"菜单文案应为'取消参考帧'，实际 {w.set_ref_action.text()!r}"


def test_clear_reference_clears_all_three_sources():
    """清除参考帧必须同时清掉三处 —— 残留比不生效更难查。"""
    w = reload_project()
    _set_reference_at(1)
    assert w.reference_frame is not None, "前置条件失败：参考帧没设上"

    w.clear_reference_frame()
    _assert_all_sources_are(None, "清除参考帧")
    assert not _ref_highlighted(1), "清除后高亮未消失（真源没清干净）"
    assert w.set_ref_action.text() == i18n.t("action_set_reference"), \
        f"菜单文案应回到'设置参考帧'，实际 {w.set_ref_action.text()!r}"


def test_set_reference_toggles_off_when_same_frame():
    """对同一帧再次"设置参考帧"应切换为取消（菜单项是一个开关）。

    刻意**不**用 `_set_reference_at` 做第二次调用 —— 它会先强制归零，那就测不到
    toggle 了。这里保持选中不动、直接再触发一次。
    """
    w = reload_project()
    _set_reference_at(2)
    assert w.reference_frame is not None, "前置条件失败：第一次没设上"

    _select(2)
    w.set_reference_frame_from_selection()
    _assert_all_sources_are(None, "再次设置同一帧")


# ---------------------------------------------------------------------------
# 参考帧不持久化：载入 / 新建必须清除
# ---------------------------------------------------------------------------
def test_load_project_clears_reference_and_selects_first():
    """载入工程：参考帧清除（两份真源）+ 默认选中第一帧。

    载入路径曾经把"选中第一帧"误写成"把第一帧设为参考帧"
    （`set_reference_frame` vs `setCurrentRow`）：它只写业务模型、不动画布，
    于是出现"工程里设了参考帧、预览却没有参考帧效果"。
    """
    w = reload_project()
    _set_reference_at(1)
    assert w.reference_frame is w.timeline.get_frame_at(1), "前置条件失败"
    assert w.canvas.reference_frame is w.reference_frame, "前置条件失败：画布没收到"

    w._load_from_path(PROJECT)

    _assert_all_sources_are(None, "载入工程")
    assert not _ref_highlighted(0), "载入后第一帧被误标成参考帧"

    # 载入后的选中由 Qt 的 selectionModel 经防抖回写模型，必须等一次
    QTest.qWait(SETTLE_MS)
    assert w.timeline.get_selected_indices_from_model() == [0], \
        f"载入后应默认选中第一帧，实际 {w.timeline.get_selected_indices_from_model()}"
    assert w.set_ref_action.text() == i18n.t("action_set_reference")


def test_new_project_clears_reference():
    """新建/关闭工程同样要清 —— `timeline.clear()` 管不到 MainWindow 那份。"""
    w = reload_project()
    _set_reference_at(1)
    assert w.reference_frame is not None, "前置条件失败"

    w._reset_project_to_empty()

    _assert_all_sources_are(None, "新建工程")
    assert w.timeline.get_frame_count() == 0


# ---------------------------------------------------------------------------
# 参考帧的联动清理
# ---------------------------------------------------------------------------
def test_deleting_the_reference_frame_clears_it():
    """删掉参考帧所在的帧，参考帧必须跟着清除。

    实现上这里有个坑：删除后帧已不在列表里、下标也已失效，所以它只能拿
    `before` 快照里的路径来判断 —— 断言写在这里，免得有人"简化"成按模型取值。
    """
    w = reload_project()
    ref = _set_reference_at(2)
    assert w.reference_frame is ref, "前置条件失败"
    # 保持选中第 2 行（remove_frame 按当前选中删）
    w.remove_frame()

    _assert_all_sources_are(None, "删除参考帧所在帧")


def test_onion_exclusive_mode_clears_reference():
    """洋葱皮与参考帧互斥时，打开洋葱皮应把参考帧清掉（三处都清）。"""
    w = reload_project()
    w.onion_ref_exclusive = True
    _set_reference_at(2)
    assert w.reference_frame is not None, "前置条件失败"

    try:
        w.toggle_onion_skin(True)
        _assert_all_sources_are(None, "互斥模式打开洋葱皮")
    finally:
        w.onion_ref_exclusive = False
        w.toggle_onion_skin(False)


# ---------------------------------------------------------------------------
# 洋葱皮抑制（顺带覆盖刚去重过的 update_onion_state）
# ---------------------------------------------------------------------------
def test_onion_skin_suppressed_while_playing():
    """播放时洋葱皮必须抑制：canvas 收空列表，且状态标记为 suppressed。"""
    w = reload_project()
    original_range = (w.onion_prev, w.onion_next)
    w.onion_prev, w.onion_next = 1, 0
    w.onion_ref_exclusive = False
    _select(3)

    try:
        w.toggle_onion_skin(True)
        assert len(w.canvas.onion_skin_frames) == 1, \
            f"未播放时应有 1 层洋葱皮，实际 {len(w.canvas.onion_skin_frames)}"

        w.is_playing = True
        w.update_onion_state()
        assert w.canvas.onion_skin_frames == [], "播放时 canvas 仍有洋葱皮"
        assert w.onion_suppressed is True, "播放时 onion_suppressed 未置位"
    finally:
        w.is_playing = False
        w.toggle_onion_skin(False)
        # 洋葱皮参数是共享实例上的持久状态，不还原则会污染后续用例
        w.onion_prev, w.onion_next = original_range


# ---------------------------------------------------------------------------
# 参考帧设置对话框（去重后锁住"设置确实生效"）
# ---------------------------------------------------------------------------
class _FakeRefDialog:
    """替身：不弹模态框，直接返回一组与被传入值不同的设置。

    替换 `ui.main_window.ReferenceSettingsDialog` 才能生效 —— 那边是
    `from ui.reference_settings import ReferenceSettingsDialog` 的模块级导入，
    改 `ui.reference_settings` 里的名字对已导入的引用无效。
    """

    last_init = None

    def __init__(self, parent=None, opacity=0.5, layer="top", show_on_playback=False):
        _FakeRefDialog.last_init = (opacity, layer, show_on_playback)
        self.parent = parent

    def exec(self):
        return int(QDialog.DialogCode.Accepted)

    def get_settings(self):
        return {"opacity": 0.25, "layer": "bottom", "show_on_playback": True}


_REF_SETTING_KEYS = ("ref_opacity", "ref_layer", "ref_show_on_playback")


def test_reference_settings_reach_canvas_and_settings():
    """参考帧设置必须落到画布三字段 + 持久化到 QSettings。

    `configure_reference_settings` 曾经在 MainWindow 里被定义了 3 份。删掉之后
    这一片没有覆盖，故补一条：既锁"设置真的生效"，也锁"它把当前值传给了对话框"。
    """
    w = reload_project()

    originals = {k: w.settings.value(k, None) for k in _REF_SETTING_KEYS}
    # 运行时状态也要还原：MainWindow 与 canvas 是**共享实例**（见 `win()`），
    # 只还原 QSettings 的话，下次跑这条用例时 canvas 已是被改过的值，
    # "设置没传到画布"这类破坏会**假通过**（破坏性验证实测踩到）。
    original_runtime = (
        w.ref_opacity, w.ref_layer, w.ref_show_on_playback,
        w.canvas.ref_opacity, w.canvas.ref_layer, w.canvas.ref_show_on_playback,
    )
    # 先把 MainWindow 与画布钉到**已知基线**（0.5 / top / False，与替身返回值
    # 三处全不同）。为什么必须钉：这两个对象的初值来自用户的 QSettings，是跨
    # 进程持久的真实偏好。若环境里残留 0.25，"设置没传到画布"会**假通过** ——
    # 破坏性验证实测踩到过：canvas 本来就是 0.25，断言看不出差别。
    for obj in (w, w.canvas):
        obj.ref_opacity = 0.5
        obj.ref_layer = "top"
        obj.ref_show_on_playback = False

    original_cls = main_window_mod.ReferenceSettingsDialog
    main_window_mod.ReferenceSettingsDialog = _FakeRefDialog
    try:
        w.configure_reference_settings()

        assert _FakeRefDialog.last_init is not None, "对话框没有被构造"
        assert w.ref_opacity == 0.25, f"ref_opacity 未生效: {w.ref_opacity}"
        assert w.canvas.ref_opacity == 0.25, \
            f"ref_opacity 没传到画布: {w.canvas.ref_opacity}"
        assert w.ref_layer == "bottom", f"ref_layer 未生效: {w.ref_layer}"
        assert w.canvas.ref_layer == "bottom", "ref_layer 没传到画布"
        assert w.ref_show_on_playback is True, "show_on_playback 未生效"
        assert w.canvas.ref_show_on_playback is True, "show_on_playback 没传到画布"

        # 持久化：改完要重开还在（参考帧的**显示参数**是全局偏好，与工程无关）
        assert abs(w.settings.value("ref_opacity", 0.5, type=float) - 0.25) < 1e-9, \
            f"ref_opacity 未持久化: {w.settings.value('ref_opacity')}"
        assert w.settings.value("ref_layer", "top", type=str) == "bottom", \
            "ref_layer 未持久化"
    finally:
        main_window_mod.ReferenceSettingsDialog = original_cls
        # 还原用户配置 —— 这些键是真实的全局偏好，测试不该留下痕迹
        for k, v in originals.items():
            if v is None:
                w.settings.remove(k)
            else:
                w.settings.setValue(k, v)
        (w.ref_opacity, w.ref_layer, w.ref_show_on_playback,
         w.canvas.ref_opacity, w.canvas.ref_layer, w.canvas.ref_show_on_playback) \
            = original_runtime


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
    sys.exit(_run_all())
