#!/usr/bin/env python3
"""网格视图（`TimelineGridWidget`）的回归验证 —— 第 2 片-b 的前置。

为什么单独一个文件：网格视图是时间轴里**唯一零自动化覆盖**的部分。列表视图迁移时
有 `verify_timeline_view_sync.py` 兜底，网格没有 —— 它迁到 `QListView` 时若没有这层网，
缩略图缓存、序号、拖拽插入点这些只能靠肉眼。

本脚本钉住的是**迁移时必须保持不变的行为**，而不是当前的实现细节：
  - 缩略图：按 `crop_rect` 裁切 + `KeepAspectRatio`，**不含**帧变换（旋转/镜像/缩放/偏移）；
  - 缩略图缓存：命中/失效的边界（key **不含** index，重排不重算 —— 刻意设计，
    见 `test_reorder_keeps_thumbnails_cached`）；
  - 序号：由 delegate 按 row 绘制，随位置变化；
  - 拖拽插入点：`_calc_insert_before` 的"网格按行主序"规则；
  - 参考帧高亮、禁用态。

与 `verify_timeline_view_sync.py` 的分工：那边管"两个视图如何与模型保持一致"，
这边管"网格视图自身渲染与交互的既有行为"。

运行： ./venv/bin/python dev/verify_grid_view.py
退出码非 0 表示有失败。
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QEvent  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from model.project_data import FrameData  # noqa: E402
from ui.timeline_item_model import (  # noqa: E402
    FrameDataRole, ReferenceRole, ThumbnailRole)
from ui.timeline import TimelineWidget  # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="pinframe_grid_")
app = QApplication(sys.argv)


def _make_png(name, size=(64, 64)):
    """生成一张**有空间变化**的图（四象限不同色 + 棋盘底纹）。

    为什么不能用纯色图：缩略图的裁切/缩放是对像素做重采样，纯色图裁任何区域、
    缩放到任何尺寸，结果像素都完全一样 —— 于是"缩略图没变"这类断言会**假通过**
    （测试通过是因为看不出差别，而不是因为行为正确）。要让断言真正有效，
    源图必须在空间上有可分辨的结构。
    """
    from PIL import Image
    path = os.path.join(_TMPDIR, name)
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    px = img.load()
    w, h = size
    for y in range(h):
        for x in range(w):
            # 四象限异色 + 棋盘底纹，保证任意子区域都彼此不同
            checker = 40 if ((x // 8) + (y // 8)) % 2 == 0 else 0
            left, top = x < w // 2, y < h // 2
            r = 200 if left else 40
            g = 180 if top else 60
            b = 90
            px[x, y] = (r - checker, g - checker, b + checker, 255)
    img.save(path)
    return path


def _crop_for(i):
    """第 i 帧的裁切区 —— 刻意让**任意两帧**裁出的像素都不同。

    为什么需要它：`test_reorder_keeps_thumbnails_cached` 是按位置比对的
    （"帧 A 从 row0 移到 row2"）。`_frames()` 以前造的是"同一张图案的 n 个文件"且
    不带裁切，四行缩略图哈希实测完全相同（`bf5c87d6ccf07fea` ×4），于是那个位置比对
    是空转的 —— 怎么换序都成立，测试通过是因为看不出差别，而不是行为正确。

    取法与真实工程保持一致：**同一张源图 + 每帧不同裁切**（`test_long2.json` 正是这个
    形态：15 帧共用一张 png，裁切互不相同）。起点按四象限轮转（跨象限色块必不同），
    尺寸随轮次递减（轮转回同一象限时也不会裁出同一块）。
    """
    x, y = [(0, 0), (32, 0), (0, 32), (32, 32)][i % 4]
    size = max(8, 32 - 4 * (i // 4))  # 源图 64×64，起点最大 32 → 永不出界
    return (x, y, size, size)


def _frames(n):
    return [FrameData(file_path=_make_png(f"f{i}.png"), crop_rect=_crop_for(i))
            for i in range(n)]


def _grid(tw):
    return tw.grid_view


def _fill(tw, n=5):
    for f in _frames(n):
        tw.model.add_frame(f)


def _font_bold(view, row):
    """第 row 行最终会被画出来的字体是否加粗 —— 走 delegate 的实际取数路径。

    delegate 的做法：以 model 的 FontRole 为基准，再用 `ReferenceRole` 覆写 bold。
    这里复刻同一套逻辑，因此断言的是渲染结果而非中间状态。

    注意不要退化回 `frame is view.reference_frame_data`：那是视图的镜像，已经被
    删除了；保留它的话，测试会在"镜像与 model 不同步"时依然通过 —— 正是本次要
    消灭的那类假通过。
    """
    index = view.model().index(row, view.modelColumn())
    font = index.data(Qt.ItemDataRole.FontRole)
    bold = font.bold() if font is not None else False
    if index.data(ReferenceRole):
        bold = True
    return bold


def _thumb_sig(view, row):
    """第 row 行缩略图的稳定签名：用像素哈希，能同时反映内容与尺寸。

    经 model 的 `ThumbnailRole` 取 —— 与 delegate 的取数路径完全一致，因此断言的
    就是**真正会被画出来的那张图**，而不是某个可能与渲染脱节的副本。
    """
    pix = view.model().index(row, view.modelColumn()).data(ThumbnailRole)
    assert pix is not None, f"row {row} 取不到缩略图"
    img = pix.toImage()
    buf = bytearray()
    for y in range(img.height()):
        for x in range(img.width()):
            buf.extend(img.pixelColor(x, y).getRgb())
    import hashlib
    return hashlib.sha1(bytes(buf)).hexdigest()[:16]


def _rewrite_source_image(path):
    """把磁盘上的源图整张换成另一种图案（不只是改个颜色，避免与裁切/缩放撞上）。"""
    from PIL import Image
    img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    px = img.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = (x * 4 % 256, y * 4 % 256, 128, 255)
    img.save(path)


def count_paint_events(widget, sink):
    """把 widget 此后收到的 Paint 事件记进 `sink`（列表），用来断言"有没有重画"。

    ⚠️ 返回值必须留住引用：事件过滤器是 QObject，被 GC 掉之后事件就再也收不到了，
    于是"一次都没重画"和"过滤器没了"长得一模一样。
    """
    from PyQt6.QtCore import QObject, QEvent

    class _Counter(QObject):
        def eventFilter(self, _obj, event):
            if event.type() == QEvent.Type.Paint:
                sink.append(event.type())
            return False

    counter = _Counter(widget)
    widget.installEventFilter(counter)
    return counter


# ---------------------------------------------------------------------------
# 夹具自身的有效性（先证明"看得见差别"，否则下面的断言都可能失明）
# ---------------------------------------------------------------------------
def test_fixture_frames_have_distinct_thumbnails():
    """夹具的 n 帧必须有**互不相同**的缩略图。

    这条钉的是本文件曾真实存在过的盲区：`_frames()` 造的帧不带裁切，四行缩略图哈希
    实测完全相同，于是所有按**位置/顺序**的比对（如
    `test_reorder_keeps_thumbnails_cached` 里的 `after[2] == before[0]`）无论怎么换序
    都成立 —— 典型的"测试数据无法分辨被测行为"。

    因此把夹具改成"同一张源图 + 每帧不同裁切"，并由本用例守住这个前提：
    哪天夹具退化回不可分辨，这里先红。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 5)
    view = _grid(tw)
    view.refresh_all_items()

    sigs = [_thumb_sig(view, r) for r in range(tw.model.get_frame_count())]
    assert len(sigs) == 5, f"夹具帧数不对: {len(sigs)}"
    assert len(set(sigs)) == len(sigs), \
        f"夹具缩略图有重复，位置/顺序断言会失明: {sigs}"


# ---------------------------------------------------------------------------
# 缩略图语义
# ---------------------------------------------------------------------------
def test_thumbnail_ignores_frame_transform():
    """缩略图刻意不套用帧变换：改 scale/rotation/镜像不应改变缩略图像素。

    这是有意设计（缩略图展示素材本身，而非合成后的帧）。若哪天把它接到
    core/transform.py，缩略图会开始跟着旋转 —— 属功能退化，这个测试会先失败。

    **必须先使缓存失效再刷新**：缓存 key 是
    `(image_path, crop_key, background_mode, w, h, is_disabled)`，**不含**帧变换字段
    （这正是"缩略图不受帧变换影响"的保证，也让改变换时无需重算缩略图）。
    若直接改 rotation 再刷新，缓存会命中、缩略图压根不重算 —— 于是哪怕有人真的给
    `create_thumbnail` 加了旋转，这个测试也照样绿。**实测过**：加旋转后 12/12 全过。

    换句话说：这条性质由**缓存 key** 保证；要验到 `create_thumbnail` 自身的行为，
    测试必须绕过缓存。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)
    before = _thumb_sig(view, 0)

    frame = tw.model.get_frame_at(0)
    frame.scale = 3.0
    frame.rotation = 45.0
    frame.aspect_ratio = -1.0  # 水平镜像
    frame.position = (50, -20)
    view._clear_thumbnail_cache()  # 强制 create_thumbnail 真正重算
    view.refresh_all_items()

    assert _thumb_sig(view, 0) == before, "缩略图跟着帧变换变了（应只反映素材本身）"


def test_thumbnail_reflects_crop_rect():
    """缩略图只做 crop_rect 裁切 —— 改裁切区，缩略图必须变。

    上一条证明"不该变的不变"，这条证明"该变的确实变了"，避免上一条因为
    "缩略图根本没刷新"而假通过。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)
    before = _thumb_sig(view, 0)

    frame = tw.model.get_frame_at(0)
    frame.crop_rect = (2, 2, 4, 4)
    tw.model.data_changed.emit(0, 0)

    assert _thumb_sig(view, 0) != before, "改 crop_rect 后缩略图未更新"


def test_thumbnail_follows_source_image_change():
    """换掉磁盘上的源图后，缩略图必须重算 —— 需要显式失效缓存。

    这是 P2-7 那类"缓存互不知情"缺陷的探测点：源图尺寸有缓存、缩略图有缓存、
    图内容有 image_cache，三者失效时机必须对齐。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)
    before = _thumb_sig(view, 0)

    path = tw.model.get_frame_at(0).file_path
    _rewrite_source_image(path)
    view.invalidate_thumbnail_cache_for_paths([path])
    view.refresh_all_items()

    assert _thumb_sig(view, 0) != before, "换了源图但缩略图未重算"


def test_invalidate_for_paths_notifies_rows_using_those_paths():
    """`invalidate_thumbnail_cache_for_paths` 必须同时做两件事：丢缓存 **且** 通知视图。

    只做前者（本文件曾经的实现）会这样：源图已经换掉、缓存也清了，但视图仍握着那张
    废弃的 QPixmap —— 缩略图缓存是**本视图私有的**，model 的 `data()` 无从知晓它被
    动过，不通知就没人去重取。表现为"外部编辑器改完图，时间轴毫无变化"。
    `TimelineItemModel.set_thumbnail_provider` 的 docstring 承诺的正是
    "缓存失效也由网格发起（→ `dataChanged`）"。

    ⚠️ 这里断言信号是因为**像素这条路在无头环境下根本走不通**：
    `viewport().grab()` 会**强制**重绘（`QWidget::render()` 直接给 widget 发
    PaintEvent），于是无论有没有通知，抓到的都是最新图 —— 用它断言必然假通过
    （第一版这条就是比像素写的，修复前也照样 PASS）。真正落到"视口确实重画了"的
    断言在下面 `test_invalidate_for_paths_repaints_viewport`（数 Paint 事件）。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)
    view.refresh_all_items()
    before = _thumb_sig(view, 0)

    seen = []
    tw.item_model.dataChanged.connect(lambda a, b, _roles: seen.append((a.row(), b.row())))

    # 与这批路径无关的行不该被通知（定向失效的意义就在于不惊动整表）
    view.invalidate_thumbnail_cache_for_paths([os.path.join(_TMPDIR, "unrelated.png")])
    assert seen == [], f"无关路径也触发了通知: {seen}"

    path = tw.model.get_frame_at(0).file_path
    _rewrite_source_image(path)
    view.invalidate_thumbnail_cache_for_paths([path])

    assert seen == [(0, 0)], f"未精确通知受影响的行（期望只通知 row0）: {seen}"
    # 另一半：缓存确实被丢掉 —— 否则重取到的还是旧图，通知了也白通知
    assert _thumb_sig(view, 0) != before, "缓存没被丢掉，重取到的仍是旧缩略图"


def test_invalidate_for_paths_repaints_viewport():
    """失效之后视口必须**真的重画** —— 只丢缓存不发通知的话，屏幕一直是旧图。

    这条是上一条的落地点：上一条钉的是"发了 dataChanged"，这条钉的是"视图因此重画了"
    （中间还隔着 Qt 的 update 调度与 widget 可见性，并非发了就一定会画）。实测：
    修复前 Paint=0，修复后 Paint=1。

    ⚠️ 两个必备前提，缺一个这条就失明（都实测过）：
      - **必须 `tw.show()` 而不是 `view.show()`**：父窗口不可见时子 widget 的
        `isVisible()` 为 False，`QWidget::update()` 直接空转 —— 那时新旧实现都数到
        0 个 Paint，测试照样通过；
      - **必须在装过滤器之前把首绘跑完**：否则数到的是"终于画完了"，与被测行为无关。

    ⚠️ 也不能改成比像素：`viewport().grab()` 会强制重绘，任何实现都能拿到最新图。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)
    view.resize(400, 300)
    tw.resize(500, 400)
    tw.show()  # 顶层窗口必须可见，否则 update() 空转
    for _ in range(5):
        app.processEvents()  # 跑完首绘，避免把它数进下面的计数

    paints = []
    counter = count_paint_events(view.viewport(), paints)  # noqa: F841 必须留住引用

    path = tw.model.get_frame_at(0).file_path
    _rewrite_source_image(path)
    view.invalidate_thumbnail_cache_for_paths([path])  # 只有这一句，刻意不补刷新
    app.processEvents()
    app.processEvents()

    assert paints, (
        "缓存失效后视口一次都没重画：界面会一直显示旧缩略图（外部编辑器改完图可见）")


# ---------------------------------------------------------------------------
# 缩略图缓存
# ---------------------------------------------------------------------------
def test_thumbnail_cache_reused_on_refresh():
    """内容未变时，`refresh_all_items()` 必须命中缓存，**不读磁盘**。

    验证方式刻意不依赖内部实现：命中缓存时把**源文件从磁盘移走**，缩略图仍应
    照原样渲染出来（因为根本不需要读文件）。若哪天缓存失效了，就会走
    `os.path.exists(image_path)` 的失败分支 → 画出占位符 → 缩略图内容变化 → 测试失败。

    （曾经这里 mock `image_cache.get` 来计解码次数，但 `create_thumbnail` 实际用的是
    `QImage(image_path)` —— 它绕过全局图缓存，mock 打空了却照样绿：破坏缓存命中后
    11 个测试仍全过。教训：**断言要落在可观测行为上，不要落在你以为的实现上**。）
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)
    view.refresh_all_items()
    before = _thumb_sig(view, 0)

    path = tw.model.get_frame_at(0).file_path
    hidden = path + ".hidden"
    os.rename(path, hidden)
    try:
        view.refresh_all_items()
        after = _thumb_sig(view, 0)
    finally:
        os.rename(hidden, path)

    assert after == before, "缓存未命中：refresh 时重新读了磁盘（源图已移走，内容却变了）"


def test_thumbnail_rereads_disk_after_cache_invalidation():
    """上一条的对照组：缓存失效后**确实**要重新读盘。

    没有这条的话，上一条可能因为"缩略图压根没刷新"而假通过 —— 移走文件也不会
    影响一张永远不重画的旧图。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)
    view.refresh_all_items()
    before = _thumb_sig(view, 0)

    path = tw.model.get_frame_at(0).file_path
    hidden = path + ".hidden"
    view.invalidate_thumbnail_cache_for_paths([path])  # 显式失效
    os.rename(path, hidden)
    try:
        view.refresh_all_items()
        after = _thumb_sig(view, 0)
    finally:
        os.rename(hidden, path)

    assert after != before, "缓存已失效却仍不读磁盘，说明缩略图根本没刷新"


def test_reorder_keeps_thumbnails_cached():
    """重排**不重算**缩略图 —— 换序只改变"哪张图在第几行"，不该触发解码。

    迁移前这条断言的是"item 对象被复用"（那时缩略图挂在 item 上，重建 item 就等于
    全部重算）。迁到 model/view 后缩略图缓存在网格视图里、按内容做 key，行序变化
    根本不影响缓存 —— 因此断言改为落在真正要保护的东西上：**不重新读盘**。

    手法同缓存测试：换序时把源文件移走，若缩略图重算了就会画出占位符。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 4)
    view = _grid(tw)
    view.refresh_all_items()

    paths = [f.file_path for f in tw.model.get_all_frames()]
    before = [_thumb_sig(view, r) for r in range(len(paths))]
    # 前置：下面按**位置**比对，若各行缩略图本就相同，比对是空转的 —— 先自证可分辨
    assert len(set(before)) == len(before), \
        f"夹具失明：各行缩略图相同，位置比对无意义 {before}"

    hidden = [p + ".hidden" for p in paths]
    for p, h in zip(paths, hidden):
        os.rename(p, h)
    try:
        assert tw.model.move_frames([0], 3) is True
        view.refresh_all_items()
        after = [_thumb_sig(view, r) for r in range(len(paths))]
    finally:
        for p, h in zip(paths, hidden):
            os.rename(h, p)

    # 帧 A 从 row0 移到 row2：把它按新位置对齐后逐帧比对
    assert after[2] == before[0], "移动的那帧缩略图被重算了（本应命中缓存）"
    assert after[0] == before[1], "其余帧的缩略图被重算了"


# ---------------------------------------------------------------------------
# 序号（delegate 按 row 绘制）
# ---------------------------------------------------------------------------
def test_item_numbers_follow_row_position():
    """序号由 delegate 按 row 现算 —— 换序后必须跟着变，无需重建缩略图。

    与列表视图不同：网格没有"序号"这一列，数字是画在缩略图角上的，
    因此 `refresh_item_numbers()` 只需触发重绘。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)
    assert tw.model.move_frames([0], 3) is True

    # 直接验证 row→帧 的映射：delegate 用 index.row()+1 画数字
    for row in range(view.get_item_count()):
        assert view.get_frame_data_at_index(row) is tw.model.get_frame_at(row), \
            f"row {row} 与模型不一致，序号会画错"


# ---------------------------------------------------------------------------
# 拖拽插入点（网格按行主序）
# ---------------------------------------------------------------------------
def test_calc_insert_before_uses_x_only():
    """网格是行主序：Y 只决定落在哪一行，X 单独决定前/后。

    这是真实的业务规则，不是 item-based 的衍生成本 —— 迁到 QListView 后要保留。
    """
    view = _grid(TimelineWidget())
    center = QPoint(100, 50)
    assert view._calc_insert_before(QPoint(90, 0), center) is True, "X 在中心左侧应为 before"
    assert view._calc_insert_before(QPoint(110, 0), center) is False, "X 在中心右侧应为 after"
    # Y 再怎么变都不影响结论
    assert view._calc_insert_before(QPoint(90, 9999), center) is True
    assert view._calc_insert_before(QPoint(110, -9999), center) is False


def test_grid_drop_uses_drag_insert_position():
    """dropEvent 与 dragMoveEvent 必须用同一个插入点。

    两者分叉的话蓝色插入指示器的位置会和最终落点不一致 —— 这是 `AGENTS.md` 里
    记过的不变量。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 5)
    view = _grid(tw)
    b = [f.file_path for f in tw.model.get_all_frames()]

    view._is_dragging = True
    view._dragged_rows = [0]
    view._drag_insert_position = (3, True)  # 插到原 index 3 之前

    mime = QMimeData()
    mime.setData("application/x-pinframe-internal-reorder", b"reorder")
    event = QDropEvent(QPointF(QPoint(0, 0)), Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QEvent.Type.Drop)
    event._keep_mime = mime  # QDropEvent 不接管 QMimeData 所有权
    view.dropEvent(event)

    after = [f.file_path for f in tw.model.get_all_frames()]
    assert after == b[1:3] + [b[0]] + b[3:], f"落点与指示器不一致: {after}"


# ---------------------------------------------------------------------------
# 参考帧与禁用态
# ---------------------------------------------------------------------------
def test_reference_frame_highlight_toggles_off():
    """参考帧高亮必须能被设置与清除（加粗 + 绿底文字条）。

    加粗由 delegate 依据 model 的 `ReferenceRole` 判定，因此这里断言的是
    delegate 真正会读到的那个角色，而不是视图里的镜像。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)

    ref = tw.model.get_frame_at(1)
    view.set_visual_reference_frame(ref)
    assert _font_bold(view, 1), "参考帧未加粗"
    assert not _font_bold(view, 2), "非参考帧不该加粗"

    view.set_visual_reference_frame(None)
    assert not _font_bold(view, 1), "清除参考帧后高亮残留"


def test_reference_frame_lives_in_business_model_only():
    """参考帧状态必须只存在**业务模型**里，显示层不得保留镜像。

    这条盯的是真实故障：显示层若各自存一份，加载工程/撤销恢复时走的
    `MainWindow -> timeline.set_reference_frame -> TimelineModel` 那条路径
    就改不到镜像，表现为"工程里设了参考帧，界面却不亮"。

    断言方式：绕过视图的 set_visual_reference_frame，**直接**写业务模型，
    显示必须立刻跟上（说明显示读的就是业务模型，没有第二份）。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)

    ref = tw.model.get_frame_at(1)
    tw.model.set_reference_frame(ref)   # 只写业务模型，不碰任何视图
    tw.item_model.dataChanged.emit(
        tw.item_model.index(0, 0),
        tw.item_model.index(2, tw.item_model.columnCount() - 1), [])

    assert _font_bold(view, 1), "只改业务模型后，网格高亮没跟上（显示层存了镜像）"
    assert view.model().index(1, view.modelColumn()).data(ReferenceRole) is True

    tw.model.clear_reference_frame()
    tw.item_model.dataChanged.emit(
        tw.item_model.index(0, 0),
        tw.item_model.index(2, tw.item_model.columnCount() - 1), [])
    assert not _font_bold(view, 1), "业务模型清了参考帧，网格高亮仍在"


def test_delegate_paints_reference_highlight():
    """delegate 必须真的读 model 的 `ReferenceRole` 来画参考帧高亮。

    为什么需要这条，以及为什么必须**只变 ReferenceRole 这一个变量**：
    其余参考帧用例断言的是 model 的 `ReferenceRole` 返回什么，中间隔着一层
    delegate。于是有人把 delegate 改回去读视图的镜像属性（`widget.reference_frame_data`，
    该属性已删除 → 恒 None → 参考帧**永不显示**），15 个用例照样全绿。

    第一版这条测试用 `set_visual_reference_frame()` 制造"有参考帧"状态再比对渲染结果，
    但那是**假阳性**：设参考帧会顺带触发 `refresh_all_items()` 重算缩略图，像素差异
    遍布整个单元格（实测 2265 个差异点、覆盖全部 148 行），与高亮本身无关 ——
    哪怕高亮完全失效，测试照样通过。

    因此这里直接 patch `data()`，让 ReferenceRole 在两次渲染间取 True/False，
    **其余一切不变**（不刷新、不重算缩略图）。这样差异就只可能来自 delegate 的
    高亮绘制。
    """
    from PyQt6.QtGui import QImage as _QImage
    from PyQt6.QtWidgets import QStyleOptionViewItem
    from PyQt6.QtGui import QPainter
    from ui.timeline_grid_delegate import TimelineGridDelegate
    from ui.timeline_item_model import TimelineItemModel as _M

    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)
    view.resize(400, 300)
    view.show()
    app.processEvents()

    delegate = view.itemDelegate()
    assert isinstance(delegate, TimelineGridDelegate), type(delegate)

    class _Harness:
        """让 ReferenceRole 返回可控值，其余角色照常。"""
        is_ref = False

        def __enter__(self):
            self._orig = _M.data

            def patched(self_, index, role=Qt.ItemDataRole.DisplayRole):
                if role == ReferenceRole:
                    return _harness.is_ref
                return self._orig(self_, index, role)

            _M.data = patched
            return self

        def __exit__(self, *exc):
            _M.data = self._orig
            return False

    def render_row(row):
        idx = view.model().index(row, view.modelColumn())
        rect = view.visualRect(idx)
        assert rect.width() > 0, f"row{row} 未排版: {rect}"
        img = _QImage(rect.width(), rect.height(), _QImage.Format.Format_ARGB32)
        img.fill(0)
        opt = QStyleOptionViewItem()
        opt.rect = rect.translated(-rect.topLeft())
        opt.widget = view
        opt.state |= view.style().StateFlag.State_Enabled
        p = QPainter(img)
        delegate.paint(p, opt, idx)
        p.end()
        return img

    def digest(img):
        buf = bytearray()
        for y in range(0, img.height(), 2):
            for x in range(0, img.width(), 2):
                buf.extend(img.pixelColor(x, y).getRgb())
        import hashlib
        return hashlib.sha1(bytes(buf)).hexdigest()

    _harness = _Harness()
    with _harness:
        _harness.is_ref = False
        plain = render_row(1)
        _harness.is_ref = True
        highlighted = render_row(1)

    assert digest(plain) != digest(highlighted), (
        "ReferenceRole 由 False 变 True 后渲染完全没变 —— delegate 没有读它。"
        "（可能改回了视图的镜像属性，而那个属性已删除 → 参考帧永不显示）")


def test_reference_role_is_not_thumbnail_role():
    """`ReferenceRole` 与 `ThumbnailRole` 不得取同一个值。

    曾经两者同为 `UserRole + 2`，于是按参考帧取数拿到的是缩略图 QPixmap 而非
    布尔 —— 参考帧是本项目的特色功能，这种静默错乱（高亮失效，甚至画图时崩溃）
    比直接报错难查得多，故单独钉住。
    """
    assert ReferenceRole != ThumbnailRole, "角色取值冲突：参考帧会拿到缩略图"
    assert ReferenceRole != FrameDataRole

    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 2)
    view = _grid(tw)
    tw.model.set_reference_frame(tw.model.get_frame_at(0))
    tw.item_model.dataChanged.emit(
        tw.item_model.index(0, 0),
        tw.item_model.index(1, tw.item_model.columnCount() - 1), [])

    idx = view.model().index(0, view.modelColumn())
    v = idx.data(ReferenceRole)
    assert isinstance(v, bool), f"ReferenceRole 应返回 bool，实际 {type(v).__name__}"


def test_disabled_state_read_from_model():
    """禁用态读的是 `FrameData.is_disabled`（模型真源），视图不存副本。"""
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 3)
    view = _grid(tw)

    assert view.get_frame_data_at_index(1) is tw.model.get_frame_at(1), \
        "视图持有的不是模型里的帧对象（说明存了副本）"
    tw.model.set_frame_disabled(1, True)
    assert view.get_frame_data_at_index(1).is_disabled is True

    tw.model.set_frame_disabled(1, False)
    assert view.get_frame_data_at_index(1).is_disabled is False


def test_disabled_state_changes_thumbnail_pixels():
    """禁用态必须在**渲染**上体现（缩略图压暗），而不只是数据上。

    上一条是弱断言：它读 `item.data(UserRole).is_disabled`，而那正是 `FrameData`
    对象本身 —— 只要视图持有同一个对象引用，无论有没有真正重绘它都成立
    （破坏性验证时确实构造不出让它失败的情形）。

    这条落在像素上：禁用时 `draw_overlays` 会盖一层半透明黑，缩略图整体变暗。
    """
    tw = TimelineWidget()
    tw.set_view_mode("grid")
    _fill(tw, 1)
    view = _grid(tw)

    enabled_sig = _thumb_sig(view, 0)
    tw.model.set_frame_disabled(0, True)
    view.refresh_all_items()
    disabled_sig = _thumb_sig(view, 0)
    assert disabled_sig != enabled_sig, "禁用后缩略图没有变化（遮罩没画上）"

    tw.model.set_frame_disabled(0, False)
    view.refresh_all_items()
    assert _thumb_sig(view, 0) == enabled_sig, "取消禁用后未恢复"


# ---------------------------------------------------------------------------
# 列表视图列宽（迁移引入的回归，钉在此处）
# ---------------------------------------------------------------------------
def test_list_column_widths_not_uniform():
    """列表视图的 8 列必须是预设宽度，不能退化成等宽。

    迁移到 `QTreeView` 时踩过：`QHeaderView` 在 `setModel()` 时按新模型的列数
    重建 section 状态，之前设的 resizeMode / 列宽**全部作废**，表现为 8 列等宽
    100px。因此 `_setup_columns()` 必须在 `setModel()` 之后调用。
    """
    tw = TimelineWidget()
    _fill(tw, 3)
    widths = [tw.list_view.columnWidth(c) for c in range(8)]

    assert len(set(widths)) > 1, f"8 列等宽，列宽设置被 setModel 冲掉了: {widths}"
    assert widths[0] == 40, f"列0(序号) 应为 40: {widths[0]}"
    assert widths[1] == 24, f"列1(禁用) 应为 24: {widths[1]}"
    assert widths[3] == 80, f"列3(缩放) 应为 80: {widths[3]}"
    assert widths[7] == 130, f"列7(分辨率) 应为 130: {widths[7]}"

    header = tw.list_view.header()
    from PyQt6.QtWidgets import QHeaderView
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Fixed, "禁用列应为 Fixed"
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch, "文件名列应为 Stretch"


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
