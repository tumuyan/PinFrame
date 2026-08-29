#!/usr/bin/env python3
"""时间轴"选中"配色的跨平台一致性检查。

---------------------------------------------------------------------------
它锁住的是什么
---------------------------------------------------------------------------
选中色曾经**完全由平台决定**，在 Windows 上表现为"多选时看不清哪帧被选中"。
根因有两层，本脚本两层都覆盖：

  1. QSS 规则的选择器写的是 `QTreeWidget`，而时间轴两个视图的基类是 `QTreeView`
     / `QListView`。QSS 的 Type Selector 只匹配"该类及其子类"，`QTreeWidget` 是
     `QTreeView` 的**子类**，反过来不成立 —— 规则一次都没生效过，选中色于是
     退回平台调色板（Windows 上就是用户可自定义的系统强调色）。

  2. `timeline_list.py` 的"禁用"列用 `option.palette.base()` 铺满整格，既盖掉了
     选中背景、又引入了一个平台相关的值，在整行选中色里切出异色缺口。

  3. 网格选中色是**拼接**的：图标区走 `super().paint()`（受 QSS 控制），底部文字
     条由 delegate 先 `CompositionMode_Source` 清空再自绘。两边必须同一个值，
     否则同一帧上下两截不同色。

---------------------------------------------------------------------------
怎么测的（关键：不需要 Windows 机器）
---------------------------------------------------------------------------
用 `QStyleFactory` 在本机切 **Fusion / Windows** 两种样式跑同一套断言。这能覆盖
"样式相关"的差异（Qt 自带的 Windows 样式的行为在 Linux 上也能复现）。

**测不到**的部分要心里有数：真实 Windows 上还叠加了系统主题/高对比度/用户自定
义强调色。所以断言写成"选中色必须等于我们指定的 `SELECTED_BG`" —— 只要颜色由
**我们**给死，就与平台无关，这才是对的方向；若是"允许它等于某个平台值"，那这个
测试就失去意义了。

断言三件事：
  A. 选中行的背景 == `SELECTED_BG`（QSS 与自绘两处都必须）；
  B. 切换到另一种 Qt 样式后，像素**完全不变**（哈希相等）；
  C. 选中色与未选中底色/文字色的对比度达标（否则"能分辨"就没有量化依据）。

依赖：PyQt6（offscreen）。
运行： ./venv/bin/python dev/verify_selection_style.py
退出码非 0 表示有失败。
"""
import ast
import os
import sys
import hashlib
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from PyQt6.QtWidgets import QApplication, QStyleFactory  # noqa: E402
from PyQt6.QtCore import Qt, QItemSelectionModel, QRect, QPoint  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402

app = QApplication(sys.argv)

import tempfile  # noqa: E402

_TMP_DIR = tempfile.mkdtemp(prefix="pinframe_sel_")

# 刻意用一个**短文件名**的测试图。
#
# 网格底部那条文字区是 delegate 自绘的，文件名 `AlignHCenter` 居中。若用仓库里
# 的 `sample_test_long_file_name.png`，截断后文字仍会占满整条，任何采样点都落在
# 笔画上，测到的是白字与蓝底的抗锯齿混合色（实测 (120,165,227)、(155,186,233)
# 这类值），而不是背景色。短名让背景成为该区域的主体，众数才是真正的底色。
_TEST_PNG = os.path.join(_TMP_DIR, "f.png")
_img = QImage(64, 64, QImage.Format.Format_RGB32)
_img.fill(QColor(200, 60, 60))
assert _img.save(_TEST_PNG), f"测试图片生成失败: {_TEST_PNG}"

from model.project_data import FrameData  # noqa: E402
from ui.timeline import TimelineWidget  # noqa: E402
from ui.timeline_selection_style import (  # noqa: E402
    SELECTED_BG, SELECTED_FG, PLACEHOLDER_BG, PLACEHOLDER_FG,
)

_PNG = _TEST_PNG

# 对比度下限（WCAG 1.4.11 非文本对比要求 3:1）
MIN_CONTRAST = 3.0


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _rel_luminance(rgb):
    """WCAG 相对亮度。"""
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    l1, l2 = sorted((_rel_luminance(a), _rel_luminance(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _row_bg(view, row):
    """第 row 行的背景色众数（整行采样取最多者，避开文字笔画）。

    返回 `((r,g,b), alpha)`。alpha 要一并返回：`QImage` 不做预乘，只看 RGB 三个
    分量无法区分 alpha=200 与 alpha=255（两者 `getRgb()[:3]` 相同），而半透明
    正是"选中色随平台漂移"的成因，必须能被测出来。
    """
    rect = view.visualRect(view.model().index(row, 0))
    img = view.viewport().grab().toImage()
    y = rect.top() + rect.height() // 2
    colors = []
    x = rect.left() + 5
    while x < min(rect.right() - 5, img.width() - 5):
        c = img.pixelColor(x, y)
        if c.isValid():
            colors.append(((c.red(), c.green(), c.blue()), c.alpha()))
        x += 4
    return Counter(colors).most_common(1)[0][0] if colors else (None, None)


def _viewport_hash(view, max_h=None):
    """视图可见区域的像素签名 —— 用来判断"换平台样式后渲染是否变了"。

    `max_h` 用于把两个视图裁到**同样的高度**再比。为什么需要它：视口高度会随
    平台样式变化（行高、滚动条厚度不同），实测同样 6 行数据在 Fusion 下是
    288px、Windows 下是 284px。那多出来的几像素是"多显示了一行的一部分"，
    属于无害的平台差异；不裁剪的话哈希必然不同，这条断言就永远失败，反而掩盖
    了真正要抓的"同一个位置画出了不同颜色"。

    验证时用两者高度的较小值，比对共同可见区域内**逐像素**是否一致。
    """
    img = view.viewport().grab().toImage()
    h = img.height() if max_h is None else min(img.height(), max_h)
    buf = bytearray()
    for y in range(0, h, 3):
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            # 取 **RGBA 四个分量**：只取 RGB 的话 alpha 差异会被完全忽略，
            # 而"某处画成了半透明"正是要抓的东西（它会让底层平台色透出来）。
            # 这里把 alpha 纳入签名，那条用例才能覆盖到它。
            buf.extend(c.getRgb())
    return hashlib.sha1(bytes(buf)).hexdigest()


def _grid_item_rect(view, row):
    """用 `indexAt` 反查网格里第 row 项的几何。

    为什么不用 `visualRect()`：`QListView` 在 IconMode + `uniformItemSizes` 下，
    布局走"批量布局"路径，未完成前 `visualRect()` 会返回一个**空的 QRect**（宽高
    都是 0）。offscreen 下无论 `doItemsLayout()` / `scheduleDelayedItemsLayout()` /
    `reset()` / 显式 resize 都触发不了它，而内容其实是画出来的。

    `indexAt()` 走的是另一套逻辑，不依赖那次批量布局，因此可靠。用它扫出一个
    属于该项的点集，取其外接矩形即可（步长带来几像素误差，对本用例无影响）。
    """
    vp = view.viewport()
    W, H = max(1, vp.width()), max(1, vp.height())

    # 只比 `row()`：QModelIndex 的相等比较还包含 column，而 `indexAt()` 返回的
    # 列取决于视图的 modelColumn，未必是 0 —— 比整个 index 会一个点都匹配不上。
    def at(x, y):
        return view.indexAt(QPoint(x, y)).row() == row

    pts = [(x, y) for y in range(0, H, 6) for x in range(0, W, 6) if at(x, y)]
    if not pts:
        return None
    xs, ys = zip(*pts)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    # 边界精细化：粗扫步长 6 会带来 ±6px 误差，而缩略图左右只留 4px 空隙 ——
    # 差几像素就会采到缩略图上（棋盘格），测的就不是背景色了。从粗扫结果出发
    # 逐像素向外推，得到精确外接矩形。
    ym = (y0 + y1) // 2
    while x0 > 0 and at(x0 - 1, ym):
        x0 -= 1
    while x1 < W - 1 and at(x1 + 1, ym):
        x1 += 1
    xm = (x0 + x1) // 2
    while y0 > 0 and at(xm, y0 - 1):
        y0 -= 1
    while y1 < H - 1 and at(xm, y1 + 1):
        y1 += 1
    return QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _select_rows(view, rows, clear_focus=True):
    """真实多选路径：直接操作 Qt 的 selectionModel（等价于 Ctrl+点击）。

    不能用 `TimelineModel.set_selection()` —— 那只改业务模型的影子列表，根本不碰
    Qt 的选中，走它会得到假结果。

    `clear_focus` 说明：Qt 会给**当前项**（current）额外画焦点装饰，实测它的背景
    会被叠亮一档（(0,120,215) → (16,130,220)）。那是正常的 UI 行为，但它会让
    "选中行颜色一致"这条断言在各行之间失败。

    而且**用户抱怨的正是非焦点场景**：焦点在画布/属性面板上时，时间轴没有焦点，
    此时所有选中行必须仍然清晰可辨。所以这里刻意清除焦点后再断言。
    """
    sm = view.selectionModel()
    sm.clearSelection()
    for r in rows:
        sm.select(view.model().index(r, 0),
                  QItemSelectionModel.SelectionFlag.Select
                  | QItemSelectionModel.SelectionFlag.Rows)
    if clear_focus:
        view.clearFocus()
    app.processEvents()
    return sm


_main_win = None


def _ensure_theme(theme="dark"):
    """让 App 的主题 QSS 生效，返回（并缓存）一个 MainWindow。

    为什么必须构造 MainWindow：QSS 是在 `MainWindow.apply_theme()` 里写出来的，
    没有别的入口。但 `QApplication.setStyleSheet()` 是**全局**的，所以只要这里
    应用过一次，后续新建的独立 `TimelineWidget` 同样受它控制 —— 于是各用例可以
    用轻量的独立 TimelineWidget，而不必每次都扛一个 MainWindow。

    另一个理由：MainWindow 里的时间轴嵌在 dock 中，脱离主窗口布局时
    `visualRect()` 会返回 0x0，采不到像素。独立 TimelineWidget 没有这问题。
    """
    global _main_win
    if _main_win is None:
        from ui.main_window import MainWindow
        _main_win = MainWindow()
    _main_win.apply_theme(theme)
    return _main_win


def _build(style_name, theme="dark"):
    """在指定 Qt 样式下搭一个多选了 3 行的时间轴。

    顺序有讲究：先 `setStyle()` 再 `apply_theme()` —— 切换 Qt 样式会重置部分
    样式状态，QSS 必须在之后重新应用才能盖住新样式的调色板。
    """
    app.setStyle(QStyleFactory.create(style_name))
    _ensure_theme(theme)

    tw = TimelineWidget()
    for _ in range(6):
        tw.model.add_frame(FrameData(file_path=_PNG))
    tw.resize(760, 320)
    tw.show()
    app.processEvents()
    return tw


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
def test_qss_placeholders_are_substituted():
    """QSS 里不能残留占位符。

    Qt 解析 `@SELECTED_BG@` 失败后会**静默丢弃整条规则**（只在 stderr 打一句
    "Could not parse stylesheet"），选中色随即退回平台调色板 —— 现象和没改一样，
    而且极难察觉。所以直接检查真正生效的那份 QSS。
    """
    _ensure_theme("dark")
    qss = QApplication.instance().styleSheet()
    assert qss, "apply_theme() 没有设置任何样式表"
    assert PLACEHOLDER_BG not in qss, \
        f"生效的 QSS 里仍残留占位符 {PLACEHOLDER_BG}（apply_to_qss 没被调用？）"
    assert PLACEHOLDER_FG not in qss, \
        f"生效的 QSS 里仍残留占位符 {PLACEHOLDER_FG}"
    assert SELECTED_BG in qss, \
        f"生效的 QSS 里没有真正的选中色 {SELECTED_BG}"


def test_qss_has_no_hash_line_comments():
    """样式表里不能有"行首 # "式的注释 —— 它会让整个样式表静默失效。

    QSS **只认 `/* */` 注释**。`#` 在那里是 ID 选择器（如 `QPushButton#playBtn`），
    所以写成 `# 这是一句说明` 会让 Qt 解析失败，并**中断其后所有规则的解析**。
    后果极具迷惑性：规则明明写在字符串里，却一条都不生效，而 Qt 只在 stderr 打
    一句 "Could not parse stylesheet" —— GUI 程序里根本看不见。

    这个坑在本次修改中真实踩到：给时间轴规则加的说明文字用 `#` 开头，导致后面
    全部规则失效，现象与"QSS 没改"一模一样。

    判据：`#` 出现在行首（前面只有空白）且后面**跟着空格或中文** → 注释；
    `#playBtn` 这种紧跟标识符的是合法 ID 选择器，放行。
    """
    _ensure_theme("dark")
    qss = QApplication.instance().styleSheet()

    bad = []
    for lineno, line in enumerate(qss.split("\n"), 1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        rest = stripped[1:]
        # ID 选择器：`#name` 紧跟标识符、且不含空格
        if rest and not rest[0].isspace():
            continue
        bad.append((lineno, stripped[:60]))

    assert not bad, (
        "样式表里有 `#` 式的行注释，会让 Qt 中断解析其后所有规则（应改用 "
        f"/* */ 或写到 qss 字符串外面的 Python 注释）：{bad}")


def test_qss_targets_the_actual_view_classes():
    """选择器必须落在 QTreeView/QListView 上，不能是 QTreeWidget。

    这是本次 bug 的根因：`QTreeWidget` 规则匹配不到 `QTreeView` 实例。断言写成
    "必须出现 QTreeView/QListView 的 ::item:selected 规则"，直接钉住。
    """
    _ensure_theme("dark")
    qss = QApplication.instance().styleSheet()

    assert "QTreeWidget" not in qss, \
        "QSS 里仍有 QTreeWidget 规则 —— 仓库中已无 QTreeWidget 实例（P1-3 已迁到 " \
        "QTreeView/QListView），这类规则永远匹配不到，是死代码"
    for cls in ("QTreeView", "QListView"):
        assert f"{cls}::item:selected" in qss, \
            f"缺少 {cls}::item:selected 规则 —— 该视图的选中色会退回平台调色板"


def test_list_selected_color_is_ours_in_both_styles():
    """列表：两种 Qt 样式下，选中行都必须是 SELECTED_BG。"""
    expected = _hex_to_rgb(SELECTED_BG)
    for style in ("Fusion", "Windows"):
        tw = _build(style)
        view = tw.list_view
        _select_rows(view, [0, 1, 2])

        for r in (0, 1, 2):
            got, alpha = _row_bg(view, r)
            assert got == expected, \
                f"[style={style}] 列表第 {r} 行（已选中）背景应为 {expected}，" \
                f"实际 {got} —— 选中色又被平台调色板接管了"
            # 同上：半透明必须被抓出来（只看 RGB 抓不到，见网格用例的说明）
            assert alpha == 255, \
                f"[style={style}] 列表第 {r} 行选中背景是半透明的（alpha={alpha}）" \
                f"—— 会透出底层平台绘制的颜色"

        unsel, _ = _row_bg(view, 3)
        assert unsel != expected, \
            f"[style={style}] 未选中行也变成了选中色，无法区分"
        assert _contrast(expected, unsel) >= MIN_CONTRAST, \
            f"[style={style}] 选中色与未选中底色的对比度 " \
            f"{_contrast(expected, unsel):.2f} 低于 {MIN_CONTRAST}，多选看不清"


def test_disable_column_has_no_gap_when_selected():
    """"禁用"列不能把整行选中色切出异色缺口。

    该列由 `_DisableColumnDelegate` 自绘，曾经无条件铺 `option.palette.base()` ——
    既盖掉选中背景，又引入平台相关的值。这里逐列采样：选中行的**每一列**背景都
    必须一致。
    """
    tw = _build("Windows")   # 用 Windows 样式：它最容易暴露 base 色问题
    view = tw.list_view
    _select_rows(view, [1])

    view.resize(760, 320)
    app.processEvents()
    img = view.viewport().grab().toImage()
    model = view.model()

    per_col = {}
    for col in range(model.columnCount()):
        if view.isColumnHidden(col) or view.columnWidth(col) <= 0:
            continue
        rect = view.visualRect(model.index(1, col))
        y = rect.center().y()
        colors = []
        x = rect.left() + 3
        while x < min(rect.right() - 3, img.width() - 3):
            c = img.pixelColor(x, y)
            if c.isValid():
                colors.append((c.red(), c.green(), c.blue()))
            x += 3
        if colors:
            per_col[col] = Counter(colors).most_common(1)[0][0]

    assert per_col, "没有采到任何列的像素，检查视口尺寸"
    distinct = set(per_col.values())
    assert len(distinct) == 1, \
        f"选中行各列背景不一致 {per_col} —— 存在异色缺口，多选时看不清选中范围"
    assert per_col[max(per_col)] == _hex_to_rgb(SELECTED_BG), \
        f"选中行某列背景不是 {SELECTED_BG}：{per_col}"


def test_grid_selected_color_is_ours_in_both_styles():
    """网格：图标区（QSS 画）与文字条（delegate 自绘）必须是同一个色。

    两者机制完全不同：图标区走 `super().paint()` 受 QSS 控制，文字条被
    `CompositionMode_Source` 清空后由 delegate 填。任一边漂移，同一帧就上下两截
    不同色。
    """
    expected = _hex_to_rgb(SELECTED_BG)
    for style in ("Fusion", "Windows"):
        tw = _build(style)
        tw.set_view_mode("grid")
        app.processEvents()
        view = tw.grid_view
        _select_rows(view, [1])

        rect = _grid_item_rect(view, 1)
        assert rect is not None and rect.width() > 0 and rect.height() > 0, \
            f"[style={style}] 定位不到网格里第 1 项的几何，采不到像素"
        img = view.viewport().grab().toImage()
        icon_h = view.iconSize().height()

        # 采样点必须**避开缩略图本身** —— 缩略图是不透明的图片内容，画在选中背景
        # 之上，采到它测的就不是选中色了。
        #
        # 网格布局（gridSize 128x148、iconSize 120x120）：缩略图水平居中、贴顶。
        #   - 图标区留白：最左侧那几列（缩略图左右各留 (128-120)/2 = 4px）；
        #   - 文字条：icon 高度以下，由 delegate 自绘。
        # 文字条那条也是**避开文字**：文件名是 `AlignHCenter` 居中的，采正中间会
        # 落在笔画上，测到的是白字与蓝底的混合色（实测 (120,165,227) 这种）。
        icon_y = rect.top() + min(10, max(1, icon_h // 8))
        text_y = rect.top() + icon_h + max(2, (rect.height() - icon_h) // 2)

        for label, x, y in (
            ("图标区(QSS)", rect.left() + 2, icon_y),
            ("文字条(delegate)", rect.left() + 4, text_y),
        ):
            c = img.pixelColor(x, y)
            got = c.getRgb()[:3]
            assert got == expected, \
                f"[style={style}] 网格第 1 行{label}应为 {expected}，实际 {got} " \
                f"—— 两个区域由不同机制绘制，色值必须取自同一真源"
            # 必须**不透明**。只看 RGB 是抓不到半透明的：QImage 不做预乘，
            # `getRgb()[:3]` 对 alpha=200 和 alpha=255 返回同样的三个分量。
            # 而半透明正是本次要消灭的东西 —— 它会让底下平台画好的选中色透出来，
            # 混成第三种颜色（"选中色随平台而变"）。所以这里单独查 alpha。
            assert c.alpha() == 255, \
                f"[style={style}] 网格第 1 行{label}是半透明的（alpha={c.alpha()}）" \
                f"—— 会透出底层由平台绘制的颜色，选中色将随平台漂移"


def test_rendering_is_identical_across_qt_styles():
    """换 Qt 样式后，两个视图的渲染必须**逐像素相同**。

    这是"与平台无关"的最终判据。若某天有人把某处改回 `option.palette.*` 或让
    QSS 规则失效，这条会立刻报红。

    **能力边界（破坏性验证实测）**：它抓不到"某处画成了半透明"。原因是
    offscreen 下两种 Qt 样式的底层色都由我们的 QSS 统一成了 `#1E1E1E`，半透明
    混上去的结果自然相同；真实 Windows 上底层可能不同，那才是半透明真正出事的
    地方，而这里构造不出来。

    所以半透明由 `alpha == 255` 那几条断言单独把关（见网格/列表用例），这条
    只负责"平台相关绘制"。两条是互补关系，缺一不可 —— 这说明"跨样式像素一致"
    是**必要但不充分**条件，真正的保障是"颜色由我们写死"（不透明 + 具体 RGB）。
    """
    for mode in ("list", "grid"):
        views, keep_alive = {}, []
        for style in ("Fusion", "Windows"):
            tw = _build(style)
            tw.set_view_mode(mode)
            app.processEvents()
            view = tw.list_view if mode == "list" else tw.grid_view
            _select_rows(view, [0, 1, 2])
            views[style] = view
            # 必须保住 `tw` 的引用：`TimelineWidget` 没有 parent，若它在本轮循环
            # 结束后被回收，其下的 view 会一并销毁，下一轮拿到的就是悬垂指针
            # （RuntimeError: wrapped C/C++ object has been deleted）。
            keep_alive.append(tw)

        # 裁到共同高度：视口高度随平台样式变化（行高/滚动条），见 _viewport_hash
        common_h = min(v.viewport().height() for v in views.values())
        sigs = {s: _viewport_hash(v, common_h) for s, v in views.items()}

        assert sigs["Fusion"] == sigs["Windows"], \
            f"{mode} 视图在 Fusion / Windows 两种 Qt 样式下渲染不同 " \
            f"({sigs['Fusion']} vs {sigs['Windows']}) —— 出现了平台相关的绘制"


def test_selected_colors_meet_contrast_floor():
    """选中配色本身要达标：底色 vs 选中色、选中色 vs 选中文字色。"""
    bg = _hex_to_rgb(SELECTED_BG)
    fg = _hex_to_rgb(SELECTED_FG)

    c_fg = _contrast(bg, fg)
    assert c_fg >= MIN_CONTRAST, \
        f"选中文字 {SELECTED_FG} 在选中底色 {SELECTED_BG} 上对比度 {c_fg:.2f} " \
        f"低于 {MIN_CONTRAST}"

    # 两个主题的行底色（与 main_window.py 的 QSS 保持一致）
    for theme, row_bg_hex in (("暗色", "#1E1E1E"), ("亮色", "#FFFFFF")):
        c = _contrast(bg, _hex_to_rgb(row_bg_hex))
        assert c >= MIN_CONTRAST, \
            f"{theme}主题：选中色 {SELECTED_BG} 与行底色 {row_bg_hex} 对比度 " \
            f"{c:.2f} 低于 {MIN_CONTRAST}"


def test_single_source_of_truth():
    """QSS 与 delegate 必须引用同一份常量，不得各自硬编码。"""
    main_src = open(os.path.join(REPO_ROOT, "src/ui/main_window.py"),
                    encoding="utf-8").read()
    for path in ("src/ui/timeline_grid_delegate.py", "src/ui/timeline_list.py"):
        src = open(os.path.join(REPO_ROOT, path), encoding="utf-8").read()
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    node.module.endswith("timeline_selection_style"):
                imported.update(a.name for a in node.names)
        assert imported, \
            f"{path} 没有从 ui.timeline_selection_style 导入选中色 —— " \
            f"硬编码会让选中色出现第二份真源"
        # 不得再出现形如 QColor(0, 120, 215, ...) 的旧写法
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QColor":
                args = [a.value for a in node.args
                        if isinstance(a, ast.Constant)]
                if args[:3] == [0, 120, 215]:
                    raise AssertionError(
                        f"{path} 仍有硬编码的 QColor(0, 120, 215, ...) "
                        f"（第 {node.lineno} 行）—— 应改用 SELECTED_BG_QCOLOR")

    assert "timeline_selection_style" in main_src, \
        "main_window.py 没有引用 ui.timeline_selection_style"


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
