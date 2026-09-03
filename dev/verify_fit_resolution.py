#!/usr/bin/env python3
"""验证「按所选帧适配项目分辨率」四个命令（接线 + 几何不变量）。

右键菜单本身**没有自动化覆盖**（`dev/run_all_checks.sh` 结尾明示），所以本脚本
不假装点了菜单 —— 它验证两件确实能自动化、且最容易静默出错的事：

  1. **接线**：四个新信号从视图 → `TimelineWidget` → `MainWindow` 完整转发，
     emit 之后确实执行到了命令方法。漏改 `_connect_view_signals` 里的一行是
     **静默失败**（菜单点了没反应，且不报任何错），这里把它变成断言。
  2. **几何不变量**：命令执行后，菜单承诺的语义真的成立 ——
     - 宽度/高度点对点：目标方向的倍率恰好为 1.0，且构图逐点不变；
     - 外接矩形：所有选中帧的导出内容一个像素都没被裁掉（用 PIL 实际合成比对）；
     - 内接矩形：画布的角落在旋转后的倾斜矩形之内（透明角确实被去掉）。

  3. 本脚本**只**验证上述两件事，不假装点了菜单 —— 菜单结构（分组、可见性）
     仍需人工确认。

**「内接矩形」当前在菜单里是隐藏的**（`timeline_context_menu.py` 里
`fit_insc_action.setVisible(False)`），但命令、信号、几何函数与本脚本里的用例
全部保留。因此下面对 `fit_inscribed_requested` 的断言在隐藏态下是**这条链路唯一
的自动化覆盖** —— 别因为"菜单上看不到"就把它们删掉。恢复显示时只需删掉那一行
`setVisible`，这里无需改动。

运行：
    venv/bin/python dev/verify_fit_resolution.py
退出码非 0 表示有失败。
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

app = QApplication(sys.argv)

from PIL import Image  # noqa: E402

from core.transform import (inscribed_size, pixel_exact_factors,  # noqa: E402
                            rotated_bitmap_size)
from model.project_data import FrameData, ProjectData  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from utils.exporter import Exporter  # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="pinframe_fit_res_")

_FIT_SIGNALS = ("fit_width_pixel_exact_requested",
                "fit_height_pixel_exact_requested",
                "fit_circumscribed_requested",
                "fit_inscribed_requested")


def _make_png(name, size):
    """造一张有实际内容的图（全不透明），这样"被裁掉多少像素"是可数的。"""
    path = os.path.join(_TMPDIR, name)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)
    return path


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _opaque_count(canvas_w, canvas_h, frame):
    """把一帧合成到 canvas_w×canvas_h 上，返回不透明像素数。"""
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if not Exporter.compose_frame(canvas, frame, canvas_w, canvas_h):
        return None
    return sum(1 for px in canvas.getdata() if px[3] > 0)


def _unclipped_count(frame):
    """把同一帧合成到一张超大画布上，作为"一个像素都没被裁"的基准。"""
    big = 4096
    return _opaque_count(big, big, frame)


def _composition(win, frame):
    """帧相对画布的构图（归一化尺寸与归一化中心偏移）。

    点对点命令承诺"构图不变"。

    注意它只在**画布取整误差**的范围内成立：画布尺寸是整数而缩放因子通常是
    无理数（1024/3 = 341.33 → 341），故这些比值有 ~1/canvas 量级的偏差。
    真正的构图破坏（例如忘了同步除 position）会让它差整整一个 k 倍，
    1% 的容差足以把两者区分开。
    """
    tw, th = frame.effective_target_size()
    return (tw / win.project.width,
            th / win.project.height,
            frame.position[0] / win.project.width,
            frame.position[1] / win.project.height)


def _select(win, indices):
    win.timeline.model.set_selection(list(indices))
    QTest.qWait(80)          # 视图 → 模型的选中回写走 50ms 防抖定时器


# ---------------------------------------------------------------------------
# 1. 接线
# ---------------------------------------------------------------------------
def test_signals_are_forwarded():
    """四个信号必须能从两个视图冒到 `TimelineWidget`。

    漏改 `timeline.py:_connect_view_signals` 里的一行，症状是"菜单点了没反应"
    —— 不抛异常、不报错，只有人工点菜单才能发现。这里把它变成断言。
    """
    win = MainWindow()
    for view_name in ("list_view", "grid_view"):
        view = getattr(win.timeline, view_name)
        for name in _FIT_SIGNALS:
            src = getattr(view.signals, name)
            dst = getattr(win.timeline.signals, name)
            got = []
            dst.connect(lambda *a, _g=got: _g.append(True))
            src.emit()
            assert got, f"{view_name}: 信号 {name} 未转发到 TimelineWidget"
    print("  接线：四个信号在两个视图上均完整转发")


def test_signals_reach_main_window_commands():
    """emit 之后必须真的执行到 MainWindow 的命令方法（不只是转发到中途）。

    用一个"不该改变任何东西"的场景：没有选中帧时，四个命令都必须提前返回，
    画布尺寸不变。若接线断在这里，测试会因画布被改而失败。
    """
    win = MainWindow()
    win.timeline.model.set_selection([])
    QTest.qWait(80)
    before = (win.project.width, win.project.height)
    for name in _FIT_SIGNALS:
        getattr(win.timeline.signals, name).emit()
    assert (win.project.width, win.project.height) == before, \
        "无选中时命令不应改动画布（若接线断裂，这里可能反而'通过'）"
    print("  接线：四个命令均可达 MainWindow（空选中下按预期提前返回）")


# ---------------------------------------------------------------------------
# 2. 几何不变量
# ---------------------------------------------------------------------------
def _build_win(frames, canvas=(1024, 768)):
    """用给定帧造一个工程并载入。"""
    project = ProjectData(width=canvas[0], height=canvas[1])
    project.frames = frames
    path = os.path.join(_TMPDIR, "proj.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(project.to_json(path))
    win = MainWindow()
    win._load_from_path(path)
    return win


def test_pixel_exact_makes_target_axis_one():
    """命令执行后，目标方向的倍率必须恰好为 1.0，且构图不变。"""
    src = _make_png("a.png", (80, 40))

    # aspect=2：X 倍率 3.0、Y 倍率 1.5（两个解不同，正是要区分两种模式的原因）
    frames = [FrameData(file_path=src, scale=3.0, aspect_ratio=2.0,
                        position=(100, -50)),
              FrameData(file_path=src, scale=3.0, aspect_ratio=2.0)]

    for use_width, sig_name in ((True, "fit_width_pixel_exact_requested"),
                                (False, "fit_height_pixel_exact_requested")):
        win = _build_win([f.clone() for f in frames])
        _select(win, [0, 1])
        before = [_composition(win, f) for f in win.project.frames]

        getattr(win.timeline.signals, sig_name).emit()

        for f in win.project.frames:
            kx, ky = pixel_exact_factors(3.0, 2.0)
            axis = abs(f.scale) if use_width else abs(f.scale / 2.0)
            assert abs(axis - 1.0) < 1e-9, \
                f"{sig_name}: 目标方向倍率应为 1.0，实际 {axis}"

        # 构图不变（容差 1%，见 _composition 的说明：画布取整会带来 ~1/canvas
        # 量级的偏差，而真正的构图破坏会差整整 k 倍）
        after = [_composition(win, f) for f in win.project.frames]
        for i, (b, a) in enumerate(zip(before, after)):
            for j, (bval, aval) in enumerate(zip(b, a)):
                assert abs(bval - aval) <= abs(bval) * 0.01 + 1e-9, \
                    f"{sig_name}: 第 {i} 帧构图第 {j} 项变了 {bval} -> {aval}"

        # 画布确实变了（否则这个测试可能因为空操作而"通过"）
        assert (win.project.width, win.project.height) != (1024, 768), \
            f"{sig_name}: 画布尺寸未变化，命令可能是空操作"
        print(f"  {'宽度' if use_width else '高度'}点对点：倍率=1.0，构图逐点不变，"
              f"画布 {win.project.width}×{win.project.height}")


def test_pixel_exact_two_axes_differ():
    """X / Y 两个点对点解必须给出不同的画布（否则等于没实现第二种模式）。"""
    src = _make_png("b.png", (80, 40))
    results = []
    for sig_name in ("fit_width_pixel_exact_requested",
                     "fit_height_pixel_exact_requested"):
        win = _build_win([FrameData(file_path=src, scale=3.0, aspect_ratio=2.0)])
        _select(win, [0])
        getattr(win.timeline.signals, sig_name).emit()
        results.append((win.project.width, win.project.height))

    assert results[0] != results[1], \
        f"有比例失真时两种模式应给出不同画布，实际都是 {results[0]}"
    print(f"  两种点对点解不同：宽度→{results[0]}，高度→{results[1]}")


def test_circumscribed_crops_nothing():
    """外接矩形之后，选中帧一个像素都不能被裁掉（用 PIL 实际合成比对）。"""
    src = _make_png("c.png", (60, 30))
    frames = [
        # 旋转 + 缩放：正是 ceil(AABB) 会裁边的场景
        FrameData(file_path=src, scale=2.0, rotation=37.0),
        FrameData(file_path=src, scale=1.5, rotation=-64.0, aspect_ratio=1.7),
        FrameData(file_path=src, scale=1.0, rotation=90.0, position=(40, -25)),
    ]
    win = _build_win(frames)
    _select(win, [0, 1, 2])

    win.timeline.signals.fit_circumscribed_requested.emit()

    for i, frame in enumerate(win.project.frames):
        ref = _unclipped_count(frame)
        got = _opaque_count(win.project.width, win.project.height, frame)
        assert got == ref, \
            f"第 {i} 帧被裁掉了 {ref - got} 个像素：" \
            f"外接矩形承诺不裁内容（画布 {win.project.width}×{win.project.height}）"
    print(f"  外接矩形：3 帧均无像素被裁，画布 {win.project.width}×{win.project.height}")


def test_inscribed_removes_transparent_corners():
    """内接矩形之后画布必须严格小于外接矩形（透明角确实被去掉）。"""
    src = _make_png("d.png", (80, 60))
    frames = [FrameData(file_path=src, scale=1.0, rotation=30.0)]

    win_c = _build_win([f.clone() for f in frames])
    _select(win_c, [0])
    win_c.timeline.signals.fit_circumscribed_requested.emit()
    circ = (win_c.project.width, win_c.project.height)

    win_i = _build_win([f.clone() for f in frames])
    _select(win_i, [0])
    win_i.timeline.signals.fit_inscribed_requested.emit()
    insc = (win_i.project.width, win_i.project.height)

    assert insc[0] < circ[0] and insc[1] < circ[1], \
        f"内接应严格小于外接：内接 {insc} vs 外接 {circ}"
    print(f"  内接矩形：{insc} 严格小于外接 {circ}（透明角已去掉）")


def test_inscribed_uses_first_selected_frame():
    """多选时内接只用第一帧（时间轴上最靠前的选中帧），与点击顺序无关。

    `_selected_indices` 恒为升序，故"第一帧"是确定的 —— 这里锁住这个语义。
    """
    big = _make_png("e_big.png", (200, 100))
    small = _make_png("e_small.png", (40, 20))
    frames = [FrameData(file_path=big, scale=1.0, rotation=25.0),
              FrameData(file_path=small, scale=1.0, rotation=25.0)]

    win = _build_win(frames)
    _select(win, [1, 0])            # 刻意乱序设置选中
    assert win.timeline.get_selected_indices_from_model() == [0, 1], \
        "选中索引应恒为升序，否则'第一帧'的语义不确定"

    win.timeline.signals.fit_inscribed_requested.emit()
    expected = inscribed_size(200, 100, 25.0)     # 第一帧是大图
    assert (win.project.width, win.project.height) == expected, \
        f"内接应按第一帧（大图）计算，期望 {expected}，实际 " \
        f"{(win.project.width, win.project.height)}"
    print(f"  内接矩形：多选时取第一帧 {expected}")


def test_commands_are_undoable():
    """四个命令都必须可撤销：撤销后画布与帧参数完全还原。"""
    src = _make_png("f.png", (80, 40))
    spec = dict(scale=2.5, aspect_ratio=1.6, rotation=20.0, position=(30, -15))

    for sig_name in _FIT_SIGNALS:
        win = _build_win([FrameData(file_path=src, **spec)])
        _select(win, [0])
        before_canvas = (win.project.width, win.project.height)
        before = [(f.scale, f.rotation, tuple(f.position))
                  for f in win.project.frames]

        getattr(win.timeline.signals, sig_name).emit()
        assert (win.project.width, win.project.height) != before_canvas, \
            f"{sig_name}: 画布未变，撤销测试无意义"

        win.undo_history()

        assert (win.project.width, win.project.height) == before_canvas, \
            f"{sig_name}: 撤销后画布未还原 " \
            f"{(win.project.width, win.project.height)} != {before_canvas}"
        after = [(f.scale, f.rotation, tuple(f.position))
                 for f in win.project.frames]
        assert after == before, f"{sig_name}: 撤销后帧参数未还原 {after} != {before}"

        # 画布与属性面板必须同步（不同步的症状是"数据对了、画面还是旧的"）
        assert win.canvas.project_width == before_canvas[0], \
            f"{sig_name}: 撤销后画布控件未同步"
    print("  撤销：四个命令均完整还原（画布 + 帧参数 + 画布控件）")


def test_zero_scale_is_rejected_not_silently_applied():
    """缩放为 0 的帧必须被拒绝，不能把画布算成天文数字。"""
    src = _make_png("g.png", (80, 40))
    win = _build_win([FrameData(file_path=src, scale=0.0)])
    _select(win, [0])
    before = (win.project.width, win.project.height)
    for name in ("fit_width_pixel_exact_requested",
                 "fit_height_pixel_exact_requested"):
        getattr(win.timeline.signals, name).emit()
    assert (win.project.width, win.project.height) == before, \
        "缩放为 0 时应拒绝执行，画布不变"
    print("  缩放为 0：已拒绝执行（画布不变）")


def test_missing_source_is_skipped():
    """源图缺失的帧被跳过而不是让外接矩形算成 0×0。"""
    good = _make_png("h.png", (60, 30))
    frames = [FrameData(file_path=os.path.join(_TMPDIR, "nope.png")),
              FrameData(file_path=good, scale=1.0)]
    win = _build_win(frames)
    _select(win, [0, 1])
    before = (win.project.width, win.project.height)
    win.timeline.signals.fit_circumscribed_requested.emit()
    assert win.project.width > 0 and win.project.height > 0, \
        "存在缺帧时仍应按其余帧算出画布"
    assert (win.project.width, win.project.height) != before
    print(f"  缺帧：已跳过，按其余帧算出 {win.project.width}×{win.project.height}")


# ---------------------------------------------------------------------------
def _run_all():
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            failed.append((name, f"AssertionError: {e}"))
        except Exception as e:                        # noqa: BLE001
            failed.append((name, f"{type(e).__name__}: {e}"))
    print(f"\n适配分辨率: {passed}/{len(tests)} 通过")
    for name, err in failed:
        print(f"  FAIL {name}\n       {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(_run_all())
    finally:
        shutil.rmtree(_TMPDIR, ignore_errors=True)
