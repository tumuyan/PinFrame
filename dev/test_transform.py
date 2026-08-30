#!/usr/bin/env python3
"""核心不变量单元测试（本仓库唯一的自动化测试）。

覆盖范围（已超出文件名的字面含义，暂未拆分）：
  - `core.transform`：变换几何、镜像编码、取整约定
  - `FrameData.clone()`：帧复制不得漏字段
  - `ProjectData.frames`：单一真相，绑定后恒为实时值

为什么能有单测：`core.transform` 刻意不 import PyQt6，几何逻辑是纯函数；
`project_data` 只需 PyQt6 已安装，不需要 QApplication 或显示环境。

运行方式（两种都可以）：
    python dev/test_transform.py      # 无需任何额外依赖
    pytest dev/test_transform.py      # 若已安装 pytest

与 dev/transform_baseline.py 的分工：
    本文件锁定【语义与不变量】；baseline 锁定【最终像素】。
    前者跑得快、说明"为什么"，后者证明"没变"。
"""
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from core.transform import (apply_to_painter, base_size,  # noqa: E402
                            composite_origin, frame_aabb,
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


# ---------------------------------------------------------------------------
# composite_origin —— 贴图落点的取整约定
# ---------------------------------------------------------------------------
def test_composite_origin_centers_content():
    """居中公式精确：内容质心应落在画布的像素索引中心 (W-1)/2。

    位图内容质心位于 (w-1)/2，故 origin + (w-1)/2 == (W-1)/2 当 origin 无需取整时。
    """
    geo = resolve_frame_geometry(FakeFrame())
    # 偶数宽度：理想落点是整数，取整无损
    ox, _ = composite_origin(geo, 200, 150, 64, 64)
    assert ox == 68
    assert ox + (64 - 1) / 2 == (200 - 1) / 2      # 99.5，精确命中


def test_composite_origin_odd_width_is_half_pixel_limited():
    """奇数宽度位图的理想落点是 X.5，整数贴图必然有 0.5px 偏差——架构性限制。"""
    geo = resolve_frame_geometry(FakeFrame())
    ox, _ = composite_origin(geo, 200, 150, 63, 63)
    assert ox == 68                                # floor(68.5)
    assert ox + (63 - 1) / 2 == 99.0               # 理想 99.5，差 -0.5px


def test_composite_origin_uses_floor_not_truncation():
    """负坐标必须向下取整，不能向零取整。

    回归：原实现用 `int()`，对负数向零取整而对正数向下取整，方向在 0 处翻转。
    帧移出画布左/上边缘时（origin < 0）平移动画会出现 1px 顿跳。
    """
    # 位图比画布宽，且往左偏移 -> origin 为负的 X.5
    geo = resolve_frame_geometry(FakeFrame(position=(-10, 0)))
    ox, _ = composite_origin(geo, 100, 100, 163, 10)
    ideal = (100 / 2 - 10) - 163 / 2               # = -41.5
    assert ideal == -41.5
    assert ox == -42, "必须是 floor(-41.5) = -42，而非 int(-41.5) = -41"


def test_composite_origin_is_translation_consistent():
    """整体平移整数像素时，落点必须整数同步移动（无方向翻转导致的顿跳）。"""
    prev = None
    for pos in range(-60, 61, 1):
        geo = resolve_frame_geometry(FakeFrame(position=(pos, 0)))
        ox, _ = composite_origin(geo, 100, 100, 63, 63)
        if prev is not None:
            assert ox - prev == 1, f"position={pos} 处步长为 {ox - prev}，应恒为 1"
        prev = ox


def test_composite_origin_applies_offset():
    geo = resolve_frame_geometry(FakeFrame(position=(10, -6)))
    ox, oy = composite_origin(geo, 200, 150, 64, 40)
    assert (ox, oy) == (78, 49)


# ---------------------------------------------------------------------------
# FrameData.clone() —— 克隆必须带上全部字段
# ---------------------------------------------------------------------------
def test_clone_copies_every_field():
    """回归：main_window 的三处手写克隆曾漏 aspect_ratio，timeline_model 漏
    target_resolution。任何字段漏拷都会被这个测试抓到。"""
    from dataclasses import fields

    from model.project_data import FrameData

    src = FrameData("a.png", scale=-1.3, position=(37, -23), rotation=-25.0,
                    aspect_ratio=-1.0, target_resolution=(120, 80),
                    is_disabled=True, crop_rect=(1, 2, 63, 41),
                    slice_pos=(2, 3))
    dup = src.clone()
    for f in fields(FrameData):
        assert getattr(dup, f.name) == getattr(src, f.name), f.name


def test_clone_preserves_mirror_state():
    """重复一个镜像帧后，副本的镜像状态必须一致。

    漏拷 aspect_ratio 时：垂直镜像直接消失；水平镜像因 scale 仍为负而变成
    180 度旋转（scale_y 由 +1 翻成 -1）。
    """
    from model.project_data import FrameData

    for scale, aspect in ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0)):
        src = FrameData("a.png", scale=scale, aspect_ratio=aspect)
        a = resolve_frame_geometry(src)
        b = resolve_frame_geometry(src.clone())
        assert (a.flip_h, a.flip_v) == (b.flip_h, b.flip_v), f"{scale}/{aspect}"


def test_clone_does_not_share_mutable_fields():
    """副本的字段改写不得影响原帧。"""
    from model.project_data import FrameData

    src = FrameData("a.png", position=(1, 2), crop_rect=(0, 0, 8, 8),
                    slice_pos=(1, 1), target_resolution=(4, 4))
    dup = src.clone()
    dup.position = (9, 9)
    dup.crop_rect = (1, 1, 2, 2)
    dup.scale = 5.0
    assert src.position == (1, 2)
    assert src.crop_rect == (0, 0, 8, 8)
    assert src.scale == 1.0


# ---------------------------------------------------------------------------
# ProjectData.frames —— 单一真相
# ---------------------------------------------------------------------------
def test_frames_unbound_uses_static_list():
    """未绑定 provider 时（from_json 载入阶段、无 UI 脚本）走后备列表。"""
    from model.project_data import FrameData, ProjectData

    p = ProjectData()
    assert p.frames == []
    p.frames = [FrameData("a.png"), FrameData("b.png")]
    assert [f.file_path for f in p.frames] == ["a.png", "b.png"]


def test_frames_bound_reads_live_source():
    """绑定后读 frames 恒为活跃数据源的实时内容——无需任何手工同步。

    `frames` 曾是普通字段、只在保存/导出时手工同步一次，于是"删除未使用素材"可能
    把未保存新增的在用素材判为未使用并物理删除。现设计见
    `dev/project_frames_sync.md`。
    """
    from model.project_data import FrameData, ProjectData

    live = [FrameData("a.png")]
    p = ProjectData()
    p.bind_frames_provider(lambda: list(live))

    assert [f.file_path for f in p.frames] == ["a.png"]
    live.append(FrameData("new.png"))          # 模拟用户新增一帧、尚未保存
    assert [f.file_path for f in p.frames] == ["a.png", "new.png"], \
        "绑定后必须看到实时新增的帧，否则就退回了 frames 双源的数据丢失风险"


def test_frames_getter_never_exposes_internal_list():
    """两种模式都必须返回新列表，语义对称。

    若未绑定时返回内部列表本身，`project.frames.append(x)` 会在未绑定模式
    （脚本/测试）下生效、在绑定模式（应用内）下静默失效——那种不对称会让
    "在测试里能过、在应用里失效"的代码溜过去。
    """
    from model.project_data import FrameData, ProjectData

    unbound = ProjectData()
    unbound.frames = [FrameData("a.png")]
    unbound.frames.append(FrameData("ghost.png"))       # 应当无效
    assert [f.file_path for f in unbound.frames] == ["a.png"]

    bound = ProjectData()
    bound.bind_frames_provider(lambda: [FrameData("a.png")])
    bound.frames.append(FrameData("ghost.png"))         # 同样无效
    assert [f.file_path for f in bound.frames] == ["a.png"]


def test_frames_assignment_after_binding_is_rejected():
    """绑定后再赋值是设计错误，必须报错而不是静默失败。"""
    from model.project_data import FrameData, ProjectData

    p = ProjectData()
    p.bind_frames_provider(lambda: [FrameData("live.png")])
    try:
        p.frames = [FrameData("stale.png")]
    except RuntimeError:
        pass
    else:
        raise AssertionError("绑定后赋值 frames 应抛 RuntimeError")
    assert [f.file_path for f in p.frames] == ["live.png"]


def test_to_json_serializes_live_frames():
    """保存路径不再需要"存盘前先同步"——to_json 直接读到实时帧。"""
    import json

    from model.project_data import FrameData, ProjectData

    live = [FrameData("a.png")]
    p = ProjectData()
    p.bind_frames_provider(lambda: list(live))
    live.append(FrameData("b.png"))            # 同步仪式已删除，这里刻意不做任何同步

    data = json.loads(p.to_json())
    assert [f["file_path"] for f in data["frames"]] == ["a.png", "b.png"]


def test_from_json_roundtrip_still_works():
    """载入阶段 provider 未绑定，from_json 必须能正常写入帧。"""
    import json

    from model.project_data import FrameData, ProjectData

    src = ProjectData(fps=12, width=200, height=150)
    src.frames = [FrameData("a.png", scale=1.5, aspect_ratio=-1.0),
                  FrameData("b.png", crop_rect=(0, 0, 8, 8))]
    restored = ProjectData.from_json(src.to_json())
    assert len(restored.frames) == 2
    assert restored.frames[0].aspect_ratio == -1.0      # 镜像状态往返保持
    assert restored.frames[1].crop_rect == (0, 0, 8, 8)


# ---------------------------------------------------------------------------
# TimelineModel —— 顺序变更必须发 frames_reordered
# ---------------------------------------------------------------------------
def test_reorder_emits_frames_reordered_not_data_changed():
    """顺序整体变化必须走 frames_reordered，不能用 data_changed。

    data_changed 的契约是"内容变了、位置没变"，视图收到后按索引原地刷新文本，
    **不会重排 item**。用它承载顺序变更的结果是：模型顺序是对的（保存/导出也
    是对的），但界面仍显示旧顺序——而且因为 `_on_data_changed` 只更新当前活动
    视图，两个视图还会各显示各的。
    """
    from model.project_data import FrameData
    from ui.timeline_model import TimelineModel

    def _record(model, action):
        """返回 (reordered 次数, data_changed 次数)。"""
        seen = {"reordered": 0, "data_changed": 0}
        model.frames_reordered.connect(lambda: seen.__setitem__("reordered", seen["reordered"] + 1))
        model.data_changed.connect(lambda *_: seen.__setitem__("data_changed", seen["data_changed"] + 1))
        action()
        return seen["reordered"], seen["data_changed"]

    def _filled(n=4):
        m = TimelineModel()
        for i in range(n):
            m.add_frame(FrameData(f"f{i}.png"))
        return m

    # 全量反转
    m = _filled()
    reordered, data_changed = _record(m, lambda: m.reverse_frames(None))
    assert (reordered, data_changed) == (1, 0), f"全量反转: {(reordered, data_changed)}"
    assert [f.file_path for f in m.get_all_frames()] == ["f3.png", "f2.png", "f1.png", "f0.png"]

    # 子集反转
    m = _filled()
    reordered, data_changed = _record(m, lambda: m.reverse_frames([1, 2]))
    assert (reordered, data_changed) == (1, 0), f"子集反转: {(reordered, data_changed)}"
    assert [f.file_path for f in m.get_all_frames()] == ["f0.png", "f2.png", "f1.png", "f3.png"]

    # 拖拽排序后的整体换序
    m = _filled()
    order = m.get_all_frames()
    order[0], order[3] = order[3], order[0]
    reordered, data_changed = _record(m, lambda: m.set_frames_order(order))
    assert (reordered, data_changed) == (1, 0), f"整体换序: {(reordered, data_changed)}"

    # 顺序没变时不该发信号（否则每次拖拽都会无谓重建两个视图）
    m = _filled()
    reordered, data_changed = _record(m, lambda: m.set_frames_order(m.get_all_frames()))
    assert (reordered, data_changed) == (0, 0), f"顺序未变: {(reordered, data_changed)}"

    # 反向确认：改帧内容仍然只发 data_changed
    m = _filled()
    reordered, data_changed = _record(m, lambda: m.update_frame_data(2))
    assert (reordered, data_changed) == (0, 1), f"内容变更: {(reordered, data_changed)}"


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
