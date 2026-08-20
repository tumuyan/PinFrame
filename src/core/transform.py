"""帧变换的唯一几何来源（预览与导出共用）。

背景：同一套 `裁切 -> 镜像 -> 缩放 -> 旋转 -> 居中合成` 曾在 9 处各写一遍
(canvas 4 处、exporter 3 处、property_panel 2 处)，任何语义调整都要同步 9 遍，
是"预览所见 != 导出所得"的系统性来源。

本模块只收敛【几何语义】；【像素化方式】仍由各后端自行决定——canvas 走
QPainter 连续浮点变换，exporter 走 PIL 整数量化 (int() 截断 + expand=True)。
因此本次收敛不改变任何现有输出，两者之间既有的亚像素差异保持原样（若要消除，
属于独立议题，需同步调整 FrameData.effective_target_size 的取整策略，
否则属性面板显示的"目标分辨率"会与实际导出尺寸不一致）。

本模块刻意不导入 PyQt6：`apply_to_painter` 靠鸭子类型接受 QPainter 或
QTransform，使几何逻辑能在无 Qt、无 QApplication 的环境下被单元测试覆盖。
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import math


def normalize_aspect_ratio(aspect_ratio) -> float:
    """把无效的 aspect_ratio 归一为 1.0。

    仅 0 是无效值：它在数学上导致除零，且不表达任何镜像语义。
    **负值是有效的**——镜像状态就编码在 scale / aspect_ratio 的符号上
    (见 property_panel._mirror_axis: 水平镜像同时翻转两者的符号，垂直镜像
    只翻转 aspect_ratio; reset_mirror 还靠符号组合反推镜像轴)。把负值也归一
    会让水平镜像静默变成 180 度旋转、垂直镜像直接失效，故绝不可这么做。

    历史缺陷：归一之前，aspect_ratio == 0 会让 canvas 的 paintEvent 抛
    ZeroDivisionError，而 PyQt6 对虚函数内未捕获异常的处理是 abort 整个进程，
    即"工程里有一个 aspect_ratio 为 0 的帧 -> 打开即崩"。
    """
    try:
        value = float(aspect_ratio)
    except (TypeError, ValueError):
        return 1.0
    if value == 0.0 or value != value:  # 0 或 NaN
        return 1.0
    return value


@dataclass(frozen=True)
class FrameGeometry:
    """一帧的几何解析结果（与后端无关）。

    字段分两类：
    - 带符号的 scale_x / scale_y —— 供 QPainter / QTransform 直接使用
      (Qt 原生支持负缩放表示翻转)；
    - flip_h / flip_v + abs_scale_x / abs_scale_y —— 供 PIL 使用
      (先按正倍率 resize，再 transpose 翻转)。

    两者描述的是同一个变换，只是表达方式不同。

    offset_x / offset_y 是帧中心相对**画布中心**的偏移量。
    rotation 是帧自身的角度值 (与 FrameData.rotation 同号)；注意 PIL 的
    Image.rotate 正向为逆时针，故 PIL 调用方需传 `-rotation`。
    """

    crop_rect: Optional[Tuple[int, int, int, int]]
    scale_x: float
    scale_y: float
    rotation: float
    offset_x: float
    offset_y: float

    @property
    def flip_h(self) -> bool:
        return self.scale_x < 0

    @property
    def flip_v(self) -> bool:
        return self.scale_y < 0

    @property
    def abs_scale_x(self) -> float:
        return abs(self.scale_x)

    @property
    def abs_scale_y(self) -> float:
        return abs(self.scale_y)


def resolve_frame_geometry(frame, apply_position: bool = True) -> FrameGeometry:
    """把一个 FrameData 解析为后端无关的几何描述。

    frame 是鸭子类型的：只要求具备 scale / aspect_ratio / rotation /
    position / crop_rect 属性，因此本函数无需 import model。

    apply_position=False 用于属性面板的单帧预览——它把帧居中显示、刻意
    忽略帧在画布上的位置。多帧预览与画布、导出都需要 position。
    """
    aspect = normalize_aspect_ratio(frame.aspect_ratio)
    scale = float(frame.scale)
    if apply_position:
        offset_x = float(frame.position[0])
        offset_y = float(frame.position[1])
    else:
        offset_x = offset_y = 0.0
    return FrameGeometry(
        crop_rect=tuple(frame.crop_rect) if frame.crop_rect else None,
        scale_x=scale,
        scale_y=scale / aspect,
        rotation=float(frame.rotation),
        offset_x=offset_x,
        offset_y=offset_y,
    )


def apply_to_painter(target, geo: FrameGeometry) -> None:
    """把几何变换套用到 QPainter 或 QTransform 上（鸭子类型，无需 import Qt）。

    顺序必须是 平移 -> 旋转 -> 缩放：Qt 的变换是右乘复合，因此实际作用到
    图像坐标上的次序是 缩放(含镜像) -> 旋转 -> 平移，与 exporter 中
    `resize -> transpose -> rotate -> 定位` 的次序一致。改动此处等于同时改动
    预览与导出，务必配合 dev/transform_baseline.py 验证。
    """
    target.translate(geo.offset_x, geo.offset_y)
    target.rotate(geo.rotation)
    target.scale(geo.scale_x, geo.scale_y)


def base_size(geo: FrameGeometry, src_w: int, src_h: int) -> Tuple[int, int]:
    """变换前的基准尺寸：裁切尺寸优先，回退源图尺寸。"""
    if geo.crop_rect:
        return geo.crop_rect[2], geo.crop_rect[3]
    return src_w, src_h


def scaled_size_floor(geo: FrameGeometry, base_w: int, base_h: int) -> Tuple[int, int]:
    """缩放后的整数尺寸，使用 int() 截断。

    截断（而非四舍五入）是**刻意保持的现状**：FrameData.effective_target_size
    也用 int()，因此属性面板/时间轴显示的"目标分辨率"与 exporter 实际产出的
    尺寸目前是一致的。若改成 round()，两者会不一致，需一并调整。
    """
    return (int(base_w * geo.abs_scale_x), int(base_h * geo.abs_scale_y))


def centered_rect(base_w: float, base_h: float) -> Tuple[float, float, float, float]:
    """以原点为中心的绘制矩形 (left, top, w, h)。

    返回纯数值而不是 QRectF，以保持本模块不依赖 Qt；调用方自行构造 QRectF。
    """
    return (-base_w / 2.0, -base_h / 2.0, base_w, base_h)


def frame_corners(geo: FrameGeometry, base_w: float, base_h: float
                  ) -> List[Tuple[float, float]]:
    """变换后四角在世界坐标中的位置（含 position 偏移）。

    与 apply_to_painter 用同一套次序：先按 scale 拉伸、再旋转、最后平移。
    """
    hw = base_w / 2.0 * geo.scale_x
    hh = base_h / 2.0 * geo.scale_y
    rad = math.radians(geo.rotation)
    cos_t, sin_t = math.cos(rad), math.sin(rad)
    pts = []
    for sx, sy in ((-hw, -hh), (hw, -hh), (-hw, hh), (hw, hh)):
        rx = sx * cos_t - sy * sin_t
        ry = sx * sin_t + sy * cos_t
        pts.append((rx + geo.offset_x, ry + geo.offset_y))
    return pts


def frame_aabb(base_w: float, base_h: float, scale: float, aspect_ratio: float,
               rotation: float) -> Tuple[float, float]:
    """(base_w x base_h) 的矩形经 缩放 -> 旋转 后的轴对齐包围盒尺寸。

    以原点为中心、不含 position。镜像只是翻转矩形，对包围盒尺寸无影响，
    故这里用倍率的绝对值。供属性面板计算"预览适配缩放 (fit)"使用。
    """
    aspect = normalize_aspect_ratio(aspect_ratio)
    x_factor = abs(scale)
    y_factor = abs(scale / aspect)
    hw = base_w / 2.0 * x_factor
    hh = base_h / 2.0 * y_factor
    rad = math.radians(rotation)
    cos_t, sin_t = math.cos(rad), math.sin(rad)
    max_x = max_y = 0.0
    for sx, sy in ((hw, hh), (hw, -hh), (-hw, hh), (-hw, -hh)):
        rx = sx * cos_t - sy * sin_t
        ry = sx * sin_t + sy * cos_t
        max_x = max(max_x, abs(rx))
        max_y = max(max_y, abs(ry))
    return 2 * max_x, 2 * max_y
