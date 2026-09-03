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
from typing import Optional, Tuple
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


def composite_origin(geo: FrameGeometry, canvas_w: int, canvas_h: int,
                     bitmap_w: int, bitmap_h: int) -> Tuple[int, int]:
    """变换后位图贴到画布时的左上角整数坐标。

    公式 `画布中心 - 位图宽/2 + 偏移` 本身是**精确正确**的：位图内容质心位于
    `(w-1)/2`，代入后质心恰好落在画布的像素索引中心 `(W-1)/2`。唯一的误差来自
    把结果取整为整数坐标——奇数宽度的位图理想落点必然是 X.5，用整数贴图无论如何
    取整都有 ±0.5px 偏差。**这是架构性限制，不是取整函数选得不对**：要真正消除
    它，必须改成用仿射矩阵直接把源图重采样到画布坐标系（见
    dev/export_pipeline_precision.md）。

    取整用 `math.floor` 而不是：
    - `int()`（原实现）：对负数向零取整、对正数向下取整，方向会在 0 处翻转。
      帧移出画布左/上边缘时（dest < 0）平移动画会出现 1px 顿跳。floor 对
      `dest >= 0` 与 `int()` 完全等价，所以这个修正不改变绝大多数导出结果。
    - `round()`（banker's rounding）：进位方向取决于相邻整数的奇偶，而位图宽度
      在缩放渐变中本身就在奇偶交替，两者干涉会把质心抖动从 0.5px 放大到 1.0px。
      实测确认，故不可用。
    """
    origin_x = math.floor((canvas_w / 2 + geo.offset_x) - bitmap_w / 2)
    origin_y = math.floor((canvas_h / 2 + geo.offset_y) - bitmap_h / 2)
    return origin_x, origin_y


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


# ---------------------------------------------------------------------------
# 「按帧适配画布」的尺寸解
#
# 供时间轴右键菜单的"按所选帧适配分辨率"使用。分两类：
#   - `pixel_exact_factors` 返回**可逆的缩放因子**，用于整套等比换算（1:1）；
#   - `circumscribed_size` / `inscribed_size` 返回**画布尺寸**，用于外接/内接。
#
# 后者以**缩放后的位图尺寸** `FrameData.effective_target_size()` 为输入（int，
# 与导出位图逐像素一致），而不是源图尺寸 —— 用户看到的是画面上的那个东西，
# 不是磁盘上那个。
# ---------------------------------------------------------------------------

def pixel_exact_factors(scale: float, aspect_ratio: float) -> Tuple[float, float]:
    """使该帧在 X / Y 方向达到 1:1 的缩放因子 (k_x, k_y)。

    帧的两个方向各有独立倍率：`scale` 作用于 X，`scale / aspect_ratio` 作用于 Y
    （与 `resolve_frame_geometry`、`effective_target_size()` 同一套约定）。因此
    **"1:1"有两个解**，只有 `|aspect_ratio| == 1` 时它们才重合：

        除以 k_x = |scale|          后：X 倍率 -> 1，          Y 倍率 -> 1/|aspect|
        除以 k_y = |scale / aspect| 后：X 倍率 -> |aspect|，   Y 倍率 -> 1

    这正是"X 点对点"与"Y 点对点"两个模式的由来 —— 工程允许比例失真，两个方向
    的倍率本就可以不相等，想让哪个方向回到原始像素就得按哪个来算。

    用法（构图完全不变的可逆换算）：画布尺寸、所有帧的 `scale` 与 `position`
    三者同除以因子 k。因为帧的像素尺寸与画布同比变化，画面构图逐点不变，
    只有导出的像素数变了；再除以 `1/k` 即可原样还原。

    取绝对值而不用原值，是为了**保住镜像**：`aspect_ratio` 与 `scale` 的负号是
    镜像状态的编码（见 `normalize_aspect_ratio` 的 docstring），除以一个正数不会
    动到符号，若除以带符号的因子则会把镜像一起翻掉。

    因子可能为 0（`scale == 0` 的帧），调用方须自行判断，除零是调用方的责任 ——
    这里不静默兜底成一个假的 1.0，那会把"这一帧被缩没了"变成"画布突然巨大"。
    """
    aspect = normalize_aspect_ratio(aspect_ratio)
    return abs(float(scale)), abs(float(scale) / aspect)

def rotated_bitmap_size(base_w: int, base_h: int, rotation: float) -> Tuple[int, int]:
    """(base_w × base_h) 的位图绕中心旋转后的**导出位图**尺寸。

    刻意**复刻 PIL `Image.rotate(..., expand=True)` 的输出尺寸**，而不是
    `ceil(frame_aabb(...))`。后者在实测的 1664 个组合里有 935 个（56%）**小于**
    PIL 的实际输出（最多小 1px）—— 拿它当画布就会静默裁掉一条边，而
    `alpha_composite` 对越界目标是 `crop + paste`、**不报错**，用户只能事后
    在导出结果里发现少了一圈像素。

    差异的来源不是"取整函数选错了"，而是**取整与相减的次序**：
    PIL 算的是 `ceil(max_corner) - floor(min_corner)`（先给端点取整数边界、再相减），
    而 `ceil(AABB)` 是先相减、再取整。区间 `[-0.026, 3.026]` 的整数包围是
    `[-1, 4]`（跨 5px），而 `ceil(3.052)` 只有 4 —— 只要旋转中心不落在整数
    格点上（宽或高为奇数时必然如此），两者就会差 1。

    此外 PIL 在进入通用公式之前先执行 `angle = angle % 360.0`，使 0 / 90 / 180 / 270
    走 transpose 捷径，输出恰为 `(w, h)` 或 `(h, w)`。**这条捷径与通用公式不等价**
    —— 3×8 转 90°：捷径给 `(8, 3)`，通用公式给 `(9, 4)` —— 所以必须一并复刻，
    否则 90° 这种最常见的情况会白白多出 1px 透明边。

    `rotation` 与 `FrameData.rotation` 同号（顺时针为正）；exporter 调 PIL 时传的是
    它的负值，本函数已在内部完成这一转换，调用方不必关心。
    """
    w, h = int(base_w), int(base_h)
    if w <= 0 or h <= 0:
        return 0, 0

    angle = (-float(rotation)) % 360.0          # 复刻 PIL 的取模
    if angle == 0.0 or angle == 180.0:
        return w, h
    if angle in (90.0, 270.0):
        return h, w

    rad = -math.radians(angle)
    a = round(math.cos(rad), 15)                # 复刻 PIL 的 15 位截断
    b = round(math.sin(rad), 15)
    # 四角相对中心的坐标是 (±w/2, ±h/2)，故 x/y 的最大绝对值即：
    half_w = abs(w / 2 * a) + abs(h / 2 * b)
    half_h = abs(w / 2 * b) + abs(h / 2 * a)
    # 必须"先取整端点、再相减"，与 PIL 一致
    return (math.ceil(w / 2 + half_w) - math.floor(w / 2 - half_w),
            math.ceil(h / 2 + half_h) - math.floor(h / 2 - half_h))


def circumscribed_size(base_w: int, base_h: int, rotation: float,
                       offset_x: float = 0.0,
                       offset_y: float = 0.0) -> Tuple[int, int]:
    """把一帧完整装下、且以**画布中心**为对称中心的最小画布尺寸。

    帧中心位于"画布中心 + (offset_x, offset_y)"，位图以帧中心为中心，故四角
    相对画布中心的最大距离是 `位图尺寸/2 + |offset|`，总跨度即
    `位图尺寸 + 2·|offset|`。

    与 `frame_aabb` 的区别正在 position：后者刻意不含它（服务于属性面板的 fit
    适配，那里帧总是居中），而这里**必须**含 —— 不然一个带偏移的帧即使画布
    等于它的包围盒，照样会超出画布被裁。

    多帧适配时对各帧取 `max`，即得所有帧的外接并集。
    """
    bw, bh = rotated_bitmap_size(base_w, base_h, rotation)
    if bw <= 0 or bh <= 0:
        return 0, 0
    return (math.ceil(bw + 2 * abs(float(offset_x))),
            math.ceil(bh + 2 * abs(float(offset_y))))


def inscribed_size(base_w: float, base_h: float, rotation: float) -> Tuple[int, int]:
    """(base_w × base_h) 矩形绕中心旋转后，保持**原宽高比**的最大内接轴对齐矩形。

    内接问题本身是欠定的：不限定长宽比时"最大"要在面积与边长之间取舍，且退化解
    （又细又长）没有意义。这里固定 `v/u = h/w`，即内接矩形与源图同比例 —— 好处是
    `rotation == 0` 时结果恒等于 `(base_w, base_h)`，不会把"没旋转"的帧莫名其妙
    改小；代价是不保证面积最大（若要最大面积需另解一个三分段优化，见
    `dev/known_issues.md`）。

    推导：两个矩形都中心对称且中心重合时，内接的充要条件是内接矩形的角点
    `(±u/2, ±v/2)` 全部落在旋转矩形内。把旋转角归约到 [0°, 90°]（θ 与 -θ 互为镜像、
    与 180°-θ 互为轴对称，对内接轴对齐矩形等价），记 `c = cos θ`、`s = sin θ`，
    展开四角后只剩两条紧约束：

        c·u + s·v ≤ w
        s·u + c·v ≤ h

    代入 `v = u·h/w` 即得下式。两约束分别来自"角顶到旋转后的横边"与"角顶到旋转
    后的纵边"，取 `min` 就是因为谁先碰边谁说话。
    """
    w, h = float(base_w), float(base_h)
    if w <= 0 or h <= 0:
        return 0, 0

    t = abs(float(rotation)) % 180.0
    if t > 90.0:
        t = 180.0 - t
    c = abs(math.cos(math.radians(t)))
    s = abs(math.sin(math.radians(t)))

    u = min((w * w) / (w * c + s * h),
            (h * w) / (s * w + c * h))
    # 与 scaled_size_floor 一致地用 int() 截断：属性面板显示的"目标分辨率"也用
    # int()，保持两者对得上。
    return int(u), int(u * h / w)
