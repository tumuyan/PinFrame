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
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from core.transform import (apply_to_painter, base_size,  # noqa: E402
                            circumscribed_size, composite_origin, frame_aabb,
                            inscribed_size, normalize_aspect_ratio,
                            pixel_exact_factors, resolve_frame_geometry,
                            rotated_bitmap_size, scaled_size_floor)


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
# 按帧适配画布 —— rotated_bitmap_size / circumscribed_size / inscribed_size
# ---------------------------------------------------------------------------
def _pil_rotated_size(w, h, rotation):
    """用真实 PIL 量一遍导出位图尺寸；PIL 不可用时返回 None（跳过对照）。"""
    try:
        from PIL import Image
    except ImportError:                                   # noqa: BLE001
        return None
    # 与 Exporter.compose_frame 完全一致：PIL 的 rotate 正向为逆时针，故传负值
    return Image.new("RGBA", (w, h)).rotate(
        -rotation, resample=Image.Resampling.BICUBIC, expand=True).size


def _inside_rotated_rect(u, v, w, h, rotation):
    """内接矩形 u×v 的四角是否都落在「w×h 绕中心旋转 rotation 度」之内。

    判据：把角点逆旋转回未旋转的坐标系，再检查是否落在 [-w/2,w/2]×[-h/2,h/2]。
    """
    rad = math.radians(rotation)
    c, s = math.cos(rad), math.sin(rad)
    for x, y in ((u / 2, v / 2), (u / 2, -v / 2), (-u / 2, v / 2), (-u / 2, -v / 2)):
        xr = c * x + s * y
        yr = -s * x + c * y
        if abs(xr) > w / 2 + 1e-9 or abs(yr) > h / 2 + 1e-9:
            return False
    return True


def _x_factor(scale, aspect):
    """帧在 X 方向的实际倍率（与 resolve_frame_geometry 同一套约定）。"""
    return abs(scale)


def _y_factor(scale, aspect):
    """帧在 Y 方向的实际倍率。"""
    return abs(scale / normalize_aspect_ratio(aspect))


def test_pixel_exact_factors_x_mode():
    """除以 k_x 后 X 倍率必须恰好为 1，Y 倍率为 1/|aspect|。"""
    for scale in (2.0, 0.5, -2.0, 1.0, 3.7):
        for aspect in (1.0, 2.0, 0.5, -1.0, -2.0):
            kx, _ky = pixel_exact_factors(scale, aspect)
            new_scale = scale / kx
            assert abs(_x_factor(new_scale, aspect) - 1.0) < 1e-12, f"{scale}/{aspect}"
            assert abs(_y_factor(new_scale, aspect) - 1.0 / abs(aspect)) < 1e-12, \
                f"{scale}/{aspect}: Y 倍率应为 1/|aspect|"


def test_pixel_exact_factors_y_mode():
    """除以 k_y 后 Y 倍率必须恰好为 1，X 倍率为 |aspect|。"""
    for scale in (2.0, 0.5, -2.0, 1.0, 3.7):
        for aspect in (1.0, 2.0, 0.5, -1.0, -2.0):
            _kx, ky = pixel_exact_factors(scale, aspect)
            new_scale = scale / ky
            assert abs(_y_factor(new_scale, aspect) - 1.0) < 1e-12, f"{scale}/{aspect}"
            assert abs(_x_factor(new_scale, aspect) - abs(aspect)) < 1e-12, \
                f"{scale}/{aspect}: X 倍率应为 |aspect|"


def test_pixel_exact_two_modes_coincide_when_no_distortion():
    """无比例失真时 X / Y 两个解重合 —— 菜单此时不需要区分两者。

    工程允许失真（aspect_ratio ≠ ±1），两个方向的倍率可以不等，所以才有两种
    1:1；一旦没有失真，它们就是同一件事。
    """
    for scale in (1.0, 2.0, 0.5, -1.0, -3.0):
        for aspect in (1.0, -1.0):
            kx, ky = pixel_exact_factors(scale, aspect)
            assert abs(kx - ky) < 1e-12, f"{scale}/{aspect}: 无失真时两解应重合"
            new_scale = scale / kx
            assert abs(_x_factor(new_scale, aspect) - 1.0) < 1e-12
            assert abs(_y_factor(new_scale, aspect) - 1.0) < 1e-12


def test_pixel_exact_factors_preserve_mirror_state():
    """换算不得改变镜像：因子取绝对值，符号留在 scale / aspect_ratio 上。"""
    for scale, aspect in ((-2.0, 1.0), (2.0, -1.0), (-2.0, -1.0)):
        for k in pixel_exact_factors(scale, aspect):
            new_scale = scale / k
            assert (new_scale < 0) == (scale < 0), f"scale 符号被翻: {scale}"
            assert (aspect < 0) == (aspect < 0)
    # 显式确认：水平镜像（scale<0）换算后仍是水平镜像
    kx, _ = pixel_exact_factors(-2.0, 1.0)
    assert -2.0 / kx < 0


def test_pixel_exact_roundtrip_is_reversible():
    """整套换算必须可逆：除以 k 再乘回去，帧参数完全还原、画布只差 ≤1px。

    这正是"构图不变"的严格表述 —— 画布、scale、position 三者同比缩放，
    画面上任意一点的相对位置都不动。

    **画布无法严格可逆，是架构性的，不是 bug**：画布尺寸是整数，而 k 通常是
    无理的比例，取整必然丢失亚像素。误差上界是 `k/2` 源像素而非 1px —— 放大
    （k>1）时画布上那 1px 的取整误差在乘回去时被放大了 k 倍。它只影响"画布比
    帧多出来的那圈留白"，不影响帧本身的像素尺寸（那才是 1:1 的承诺所在）。
    scale 与 position 是 float，故严格可逆 —— 断言对它们不设容差。
    """
    random.seed(31337)
    for _ in range(200):
        scale = random.choice([1.0, 2.0, 0.5, 3.7]) * random.choice([1, -1])
        aspect = random.choice([1.0, 2.0, 0.5, 4.0]) * random.choice([1, -1])
        canvas_w, canvas_h = 512, 288
        pos_x, pos_y = 37.0, -19.0

        kx, ky = pixel_exact_factors(scale, aspect)
        for k in (kx, ky):
            new_scale = scale / k
            new_pos = (pos_x / k, pos_y / k)
            new_canvas = (round(canvas_w / k), round(canvas_h / k))

            assert new_scale * k == scale, "scale 必须严格可逆"
            assert (new_pos[0] * k, new_pos[1] * k) == (pos_x, pos_y), \
                "position 必须严格可逆"
            assert abs(new_canvas[0] * k - canvas_w) <= k / 2 + 1e-9, \
                f"画布误差应 ≤k/2，实得 {abs(new_canvas[0] * k - canvas_w)}"
            assert abs(new_canvas[1] * k - canvas_h) <= k / 2 + 1e-9


def test_pixel_exact_factor_zero_is_not_silently_patched():
    """scale == 0 的帧因子为 0，由调用方判断 —— 这里不兜底成 1.0。"""
    assert pixel_exact_factors(0.0, 1.0) == (0.0, 0.0)


def test_rotated_bitmap_size_matches_pil():
    """锁死与 PIL `rotate(expand=True)` 的逐像素一致。

    这是本组函数的**存在理由**：画布尺寸一旦小于 PIL 的实际输出，导出时那一圈
    像素就被 `alpha_composite` 静默裁掉（它不报错），用户只能在结果里发现。
    """
    random.seed(20260830)
    sizes = (1, 2, 3, 8, 9, 64, 65, 100, 101)
    angles = (0.0, 1.0, 15.0, 30.0, 45.0, 60.0, 89.0, 90.0, -90.0, 120.0,
              135.0, 180.0, -180.0, 200.0, 270.0, 271.5, 360.0, 450.0, -450.0,
              -33.3)
    cases = [(w, h, a) for w in sizes for h in sizes for a in angles]
    cases += [(random.randint(1, 300), random.randint(1, 300),
               random.uniform(-720, 720)) for _ in range(300)]

    checked = 0
    for w, h, a in cases:
        expected = _pil_rotated_size(w, h, a)
        if expected is None:
            return                                        # 无 PIL：跳过
        got = rotated_bitmap_size(w, h, a)
        assert got == expected, f"{w}x{h} @{a}: {got} != PIL {expected}"
        checked += 1
    assert checked > 0


def test_rotated_bitmap_size_special_angles_take_transpose_path():
    """0/90/180/270 必须走 PIL 的 transpose 捷径，尺寸恰为 (w,h)/(h,w)。

    通用公式在 90° 上会给出 (9,4) 而捷径给 (8,3) —— 差的那 1px 是白白多出来的
    透明边。既然 90° 是最常见的旋转，这条捷径必须复刻。
    """
    assert rotated_bitmap_size(3, 8, 0.0) == (3, 8)
    assert rotated_bitmap_size(3, 8, 360.0) == (3, 8)
    assert rotated_bitmap_size(3, 8, 180.0) == (3, 8)
    assert rotated_bitmap_size(3, 8, -180.0) == (3, 8)
    assert rotated_bitmap_size(3, 8, 90.0) == (8, 3)
    assert rotated_bitmap_size(3, 8, -90.0) == (8, 3)
    assert rotated_bitmap_size(3, 8, 270.0) == (8, 3)
    assert rotated_bitmap_size(3, 8, 450.0) == (8, 3)     # PIL 先取模，故也走捷径


def test_ceil_aabb_is_not_a_safe_canvas_size():
    """回归：`ceil(frame_aabb(...))` **不能**当画布尺寸，它经常偏小。

    这条测试锁的是"为什么这里不用现成的 frame_aabb"。56% 的用例上 ceil(AABB)
    小于 PIL 实际输出。差 1 的来源是先相减再取整 vs 先取整再相减。
    """
    random.seed(4242)
    cases = [(w, h, random.uniform(0.0001, 89.9999))
             for w in (3, 8, 9, 64, 65) for h in (3, 8, 9, 64, 65)
             for _ in range(4)]
    smaller = 0
    for w, h, a in cases:
        aabb_w = math.ceil(w * abs(math.cos(math.radians(a)))
                           + h * abs(math.sin(math.radians(a))))
        aabb_h = math.ceil(w * abs(math.sin(math.radians(a)))
                           + h * abs(math.cos(math.radians(a))))
        expected = _pil_rotated_size(w, h, a)
        if expected is None:
            return
        got = rotated_bitmap_size(w, h, a)
        assert got == expected
        if (aabb_w, aabb_h) != expected:
            smaller += 1
        # 我们给的尺寸永远不该小于 PIL 的实际输出（否则就是裁边）
        assert got[0] >= expected[0] and got[1] >= expected[1]
    assert smaller > 0, "若这条不再成立，说明 PIL 改了实现，可以换回 ceil(AABB)"


def test_rotated_bitmap_size_degenerate():
    assert rotated_bitmap_size(0, 8, 45.0) == (0, 0)
    assert rotated_bitmap_size(8, 0, 45.0) == (0, 0)


def test_circumscribed_size_includes_position():
    """外接矩形必须把 position 算进去，否则带偏移的帧照样出画布。"""
    # 无偏移、无旋转：恰好等于位图尺寸
    assert circumscribed_size(64, 32, 0.0) == (64, 32)
    # 有偏移：两侧各外扩 |offset|
    assert circumscribed_size(64, 32, 0.0, 10, 0) == (84, 32)
    assert circumscribed_size(64, 32, 0.0, -10, 0) == (84, 32)   # 方向无关
    assert circumscribed_size(64, 32, 0.0, 10, -5) == (84, 42)
    # 分数偏移向上取整，宁可多 1px 也不裁（64.5 -> 65、32.5 -> 33）
    assert circumscribed_size(64, 32, 0.0, 0.25, 0.25) == (65, 33)


def test_circumscribed_size_covers_rotated_bitmap():
    """不变量：外接尺寸恒不小于导出位图尺寸（position 只会让它变大）。"""
    random.seed(99)
    for _ in range(200):
        w = random.randint(1, 200)
        h = random.randint(1, 200)
        a = random.uniform(-360, 360)
        ox, oy = random.uniform(-50, 50), random.uniform(-50, 50)
        cw, ch = circumscribed_size(w, h, a, ox, oy)
        bw, bh = rotated_bitmap_size(w, h, a)
        assert cw >= bw and ch >= bh, f"{w}x{h}@{a} off=({ox},{oy})"


def test_circumscribed_size_degenerate():
    assert circumscribed_size(0, 8, 45.0, 3, 3) == (0, 0)


def test_inscribed_size_zero_rotation_is_identity():
    """rotation == 0 时结果必须恒等于原尺寸 —— 不能把没旋转的帧改小。"""
    for w, h in ((64, 32), (1, 1), (3, 8), (8, 3), (65, 65)):
        assert inscribed_size(w, h, 0.0) == (w, h), f"{w}x{h}"
    # 360 的整数倍同理
    assert inscribed_size(64, 32, 360.0) == (64, 32)
    assert inscribed_size(64, 32, -720.0) == (64, 32)


def test_inscribed_size_known_solutions():
    """与解析解对照。"""
    # 正方形转 45°：最大内接正方形边长 = 100/√2 ≈ 70.71 -> int 截断 70
    assert inscribed_size(100, 100, 45.0) == (70, 70)
    # 90°：8×3 转成 3×8，保 8:3 比例的最大内接是 3×1.125 -> (3, 1)
    assert inscribed_size(8, 3, 90.0) == (3, 1)
    # 180° 与不转等价
    assert inscribed_size(64, 32, 180.0) == (64, 32)


def test_inscribed_size_is_actually_inscribed():
    """不变量：算出的矩形四角必须真的落在旋转后的源矩形内。

    这是内接解唯一真正的正确性判据 —— 前面几条只对了几个解析值，这条覆盖了
    随机角度。注意用**未归约**的原始角度验证：归约依赖"θ 与 -θ、180°-θ 互为
    镜像、而内接矩形在镜像下不变"，这条测试顺带把那个论证也锁住了。
    """
    random.seed(1234)
    for _ in range(300):
        w = random.randint(1, 200)
        h = random.randint(1, 200)
        a = random.uniform(-720, 720)
        u, v = inscribed_size(w, h, a)
        assert _inside_rotated_rect(u, v, w, h, a), f"{w}x{h}@{a} -> {u}x{v}"


def test_inscribed_size_never_exceeds_circumscribed():
    """不变量：内接 ≤ 外接，且两者在 rotation == 0 时相等。"""
    random.seed(555)
    for _ in range(200):
        w = random.randint(1, 200)
        h = random.randint(1, 200)
        a = random.uniform(-360, 360)
        iw, ih = inscribed_size(w, h, a)
        cw, ch = circumscribed_size(w, h, a)
        assert iw <= cw and ih <= ch, f"{w}x{h}@{a}: inscribed {iw}x{ih} > {cw}x{ch}"


def test_inscribed_size_degenerate():
    assert inscribed_size(0, 8, 45.0) == (0, 0)
    assert inscribed_size(8, 0, 45.0) == (0, 0)


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
