#!/usr/bin/env python3
"""core.transform 的单元测试（本仓库第一批单测）。

为什么能有单测：core.transform 刻意不 import PyQt6，几何逻辑是纯函数，
不需要 QApplication、不需要显示环境。

运行方式（两种都可以）：
    python dev/test_transform.py      # 无需任何额外依赖
    pytest dev/test_transform.py      # 若已安装 pytest

与 dev/transform_baseline.py 的分工：
    本文件锁定【几何语义】（顺序、符号、镜像编码、取整约定）；
    baseline 锁定【最终像素】。前者跑得快、说明"为什么"，后者证明"没变"。
"""
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from core.transform import (apply_to_painter, base_size, centered_rect,  # noqa: E402
                            frame_aabb, frame_corners,
                            normalize_aspect_ratio, resolve_frame_geometry,
                            scaled_size_floor)


class FakeFrame:
    """鸭子类型的帧对象：core.transform 只读这几个属性，无需 import model。"""

    def __init__(self, scale=1.0, aspect_ratio=1.0, rotation=0.0,
                 position=(0, 0), crop_rect=None):
        self.scale = scale
        self.aspect_ratio = aspect_ratio
        self.rotation = rotation
        self.position = position
        self.crop_rect = crop_rect


class RecordingTarget:
    """记录 translate/rotate/scale 调用顺序的假 QPainter。"""

    def __init__(self):
        self.calls = []

    def translate(self, x, y):
        self.calls.append(("translate", x, y))

    def rotate(self, a):
        self.calls.append(("rotate", a))

    def scale(self, sx, sy):
        self.calls.append(("scale", sx, sy))


# ---------------------------------------------------------------------------
# normalize_aspect_ratio —— 只有 0 无效，负值是镜像编码
# ---------------------------------------------------------------------------
def test_normalize_only_zero_is_invalid():
    assert normalize_aspect_ratio(0) == 1.0
    assert normalize_aspect_ratio(0.0) == 1.0
    assert normalize_aspect_ratio(1.0) == 1.0
    assert normalize_aspect_ratio(1.6) == 1.6


def test_normalize_preserves_negative():
    """负值必须原样保留：镜像状态就编码在符号上。

    若把负值也归一为 1.0，垂直镜像会失效、水平镜像会静默变成 180 度旋转，
    且 property_panel.reset_mirror 靠符号组合反推镜像轴的逻辑会一并失效。
    """
    assert normalize_aspect_ratio(-1.0) == -1.0
    assert normalize_aspect_ratio(-2.5) == -2.5


def test_normalize_handles_garbage():
    assert normalize_aspect_ratio(float("nan")) == 1.0
    assert normalize_aspect_ratio(None) == 1.0
    assert normalize_aspect_ratio("abc") == 1.0


# ---------------------------------------------------------------------------
# 镜像语义回归 —— 按 property_panel._mirror_axis 的真实编码构造
# ---------------------------------------------------------------------------
def test_mirror_encoding_none():
    geo = resolve_frame_geometry(FakeFrame(scale=1.0, aspect_ratio=1.0))
    assert (geo.flip_h, geo.flip_v) == (False, False)


def test_mirror_encoding_horizontal():
    """H 镜像：_mirror_axis 同时翻转 scale 与 aspect_ratio 的符号。

    scale_y = -1 / -1 = +1，因此只有水平方向翻转。
    """
    geo = resolve_frame_geometry(FakeFrame(scale=-1.0, aspect_ratio=-1.0))
    assert (geo.flip_h, geo.flip_v) == (True, False)
    assert geo.abs_scale_x == 1.0 and geo.abs_scale_y == 1.0


def test_mirror_encoding_vertical():
    """V 镜像：只翻转 aspect_ratio，scale_y = 1 / -1 = -1。"""
    geo = resolve_frame_geometry(FakeFrame(scale=1.0, aspect_ratio=-1.0))
    assert (geo.flip_h, geo.flip_v) == (False, True)


def test_mirror_encoding_both():
    """H+V：两次镜像后 scale<0 而 aspect>=0（见 reset_mirror 的符号表）。"""
    geo = resolve_frame_geometry(FakeFrame(scale=-1.0, aspect_ratio=1.0))
    assert (geo.flip_h, geo.flip_v) == (True, True)


def test_mirror_is_involutive():
    """镜像两次回到原状：符号翻转两次即恒等。"""
    f = FakeFrame(scale=1.3, aspect_ratio=2.0)
    for _ in range(2):
        f.scale *= -1
        f.aspect_ratio *= -1
    geo = resolve_frame_geometry(f)
    assert (geo.flip_h, geo.flip_v) == (False, False)
    assert math.isclose(geo.scale_x, 1.3)
    assert math.isclose(geo.scale_y, 1.3 / 2.0)


def test_zero_aspect_renders_as_unity():
    """aspect_ratio == 0 归一为 1.0：等价于无失真，而不是崩溃或零高度。

    归一之前，canvas 的 paintEvent 会抛 ZeroDivisionError，而 PyQt6 对虚函数内
    未捕获异常的处理是 abort 整个进程（实测退出码 0xC0000409）。
    """
    zero = resolve_frame_geometry(FakeFrame(scale=2.0, aspect_ratio=0.0))
    unity = resolve_frame_geometry(FakeFrame(scale=2.0, aspect_ratio=1.0))
    assert zero == unity


# ---------------------------------------------------------------------------
# position 开关 —— 单帧预览刻意忽略偏移
# ---------------------------------------------------------------------------
def test_position_applied_by_default():
    geo = resolve_frame_geometry(FakeFrame(position=(37, -23)))
    assert (geo.offset_x, geo.offset_y) == (37.0, -23.0)


def test_position_can_be_suppressed():
    geo = resolve_frame_geometry(FakeFrame(position=(37, -23)),
                                 apply_position=False)
    assert (geo.offset_x, geo.offset_y) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 变换顺序 —— 改这个顺序等于同时改预览与导出
# ---------------------------------------------------------------------------
def test_painter_call_order_is_translate_rotate_scale():
    geo = resolve_frame_geometry(
        FakeFrame(scale=1.5, aspect_ratio=2.0, rotation=17.0, position=(5, 7)))
    t = RecordingTarget()
    apply_to_painter(t, geo)
    assert [c[0] for c in t.calls] == ["translate", "rotate", "scale"]
    assert t.calls[0] == ("translate", 5.0, 7.0)
    assert t.calls[1] == ("rotate", 17.0)
    assert t.calls[2] == ("scale", 1.5, 0.75)


# ---------------------------------------------------------------------------
# 基准尺寸与取整
# ---------------------------------------------------------------------------
def test_base_size_prefers_crop_rect():
    geo = resolve_frame_geometry(FakeFrame(crop_rect=(10, 20, 64, 32)))
    assert base_size(geo, 128, 64) == (64, 32)


def test_base_size_falls_back_to_source():
    geo = resolve_frame_geometry(FakeFrame())
    assert base_size(geo, 128, 64) == (128, 64)


def test_scaled_size_truncates_not_rounds():
    """int() 截断是刻意保持的现状（见下一个测试说明原因）。"""
    geo = resolve_frame_geometry(FakeFrame(scale=1.9))
    # 64 * 1.9 = 121.6 -> 截断得 121；若改成 round() 会得到 122
    assert scaled_size_floor(geo, 64, 64) == (121, 121)


def test_scaled_size_uses_magnitude_for_mirror():
    """镜像不该让尺寸变负。"""
    geo = resolve_frame_geometry(FakeFrame(scale=-2.0, aspect_ratio=-1.0))
    assert scaled_size_floor(geo, 10, 20) == (20, 40)


def test_scaled_size_matches_effective_target_size():
    """不变量：导出实际尺寸 == 属性面板/时间轴显示的"目标分辨率"。

    FrameData.effective_target_size 与 exporter 目前都用 int() 截断，所以两者
    一致。若哪天把 exporter 改成 round()（阶段 2 的候选改动），必须同步改
    effective_target_size，否则 UI 显示的数字会与导出产物不符——本测试会先失败。
    """
    from model.project_data import FrameData

    for scale, aspect in ((1.0, 1.0), (1.7, 1.0), (0.85, 1.6),
                          (1.33, -1.0), (-1.3, -1.0), (2.5, 3.7)):
        # 用 crop_rect 提供基准尺寸，避免依赖真实图片文件
        fd = FrameData("nonexistent.png", scale=scale, aspect_ratio=aspect,
                       crop_rect=(0, 0, 63, 41))
        geo = resolve_frame_geometry(fd)
        assert scaled_size_floor(geo, 63, 41) == fd.effective_target_size(), (
            f"scale={scale} aspect={aspect}")


# ---------------------------------------------------------------------------
# 几何辅助
# ---------------------------------------------------------------------------
def test_centered_rect():
    assert centered_rect(64, 40) == (-32.0, -20.0, 64, 40)


def test_aabb_no_rotation():
    assert frame_aabb(64, 40, 1.0, 1.0, 0.0) == (64.0, 40.0)


def test_aabb_quarter_turn_swaps_extents():
    w, h = frame_aabb(64, 40, 1.0, 1.0, 90.0)
    assert math.isclose(w, 40.0, abs_tol=1e-9)
    assert math.isclose(h, 64.0, abs_tol=1e-9)


def test_aabb_45_degrees_known_value():
    w, h = frame_aabb(10, 10, 1.0, 1.0, 45.0)
    expected = 10 * math.sqrt(2)
    assert math.isclose(w, expected, rel_tol=1e-9)
    assert math.isclose(h, expected, rel_tol=1e-9)


def test_aabb_ignores_mirror_sign():
    """镜像只是翻转矩形，不改变包围盒尺寸。"""
    plain = frame_aabb(64, 40, 1.0, 1.0, 33.0)
    mirrored_v = frame_aabb(64, 40, 1.0, -1.0, 33.0)
    mirrored_h = frame_aabb(64, 40, -1.0, -1.0, 33.0)
    assert math.isclose(plain[0], mirrored_v[0]) and math.isclose(plain[1], mirrored_v[1])
    assert math.isclose(plain[0], mirrored_h[0]) and math.isclose(plain[1], mirrored_h[1])


def test_aabb_zero_aspect_treated_as_unity():
    assert frame_aabb(64, 40, 1.0, 0.0, 0.0) == frame_aabb(64, 40, 1.0, 1.0, 0.0)


def test_frame_corners_include_position():
    geo = resolve_frame_geometry(FakeFrame(position=(100, 50)))
    pts = frame_corners(geo, 10, 10)
    assert len(pts) == 4
    cx = sum(p[0] for p in pts) / 4
    cy = sum(p[1] for p in pts) / 4
    assert math.isclose(cx, 100.0, abs_tol=1e-9)
    assert math.isclose(cy, 50.0, abs_tol=1e-9)


def test_frame_corners_consistent_with_aabb():
    """四角求出的包围盒应与 frame_aabb 一致（两者是同一变换的两种算法）。"""
    f = FakeFrame(scale=1.4, aspect_ratio=1.7, rotation=23.0)
    geo = resolve_frame_geometry(f, apply_position=False)
    pts = frame_corners(geo, 64, 40)
    width = max(p[0] for p in pts) - min(p[0] for p in pts)
    height = max(p[1] for p in pts) - min(p[1] for p in pts)
    aabb_w, aabb_h = frame_aabb(64, 40, f.scale, f.aspect_ratio, f.rotation)
    assert math.isclose(width, aabb_w, rel_tol=1e-9)
    assert math.isclose(height, aabb_h, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 独立运行入口（无 pytest 也能跑）
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
    print(f"core.transform: {passed}/{len(tests)} 通过")
    for name, err in failed:
        print(f"  FAIL {name}\n       {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
