"""时间轴的 Qt 模型/视图适配层（P1-3 第 2 片）。

职责边界
--------
`TimelineModel`（`timeline_model.py`）是**业务真源**：帧数据、顺序、选中、历史。
它刻意不是 `QAbstractItemModel` —— 它是一个一维帧列表，而"8 列"只是列表视图的
一种展示形态，把列定义塞进业务模型会让导出、存档、`ProjectData` 这些无关方
被迫理解表格坐标。

本模块是**薄的 Qt 适配层**：把 `TimelineModel` 的一维帧列表暴露成
`QAbstractTableModel`，并把它那些语义化的信号翻译成 Qt 的结构变更通知。

这样做换来三件事：
  1. **视图零数据副本** —— 单元格文本由 `data()` 现算，不再有 `QTreeWidgetItem`
     把 `FrameData` 挂在 `UserRole` 上。帧数据与顺序都只有一个源。
  2. **增删移改由框架驱动** —— `beginInsertRows`/`dataChanged` 让视图自动跟随，
     不再有 `_on_frames_inserted` 那种手工往两个视图各加一遍的镜像逻辑。
  3. **选中可以共享** —— 两个视图挂同一个 model 后即可共享 `QItemSelectionModel`。

命名说明：当前只有列表视图用它。网格视图迁到 `QListView` 后会共用同一个实例
（用 `setModelColumn` 取列 0），届时"切换视图选中不串"由框架保证。
"""
from typing import Optional

from PyQt6.QtCore import (
    QAbstractTableModel, QModelIndex, Qt, QSize,
)
from PyQt6.QtGui import QColor, QFont

from i18n.manager import i18n
from model.project_data import FrameData

# 列定义（顺序即显示顺序，与 TimelineListView 的表头一致）
COL_INDEX = 0
COL_DISABLED = 1
COL_FILENAME = 2
COL_SCALE = 3
COL_POSITION = 4
COL_CROP_ORIGIN = 5
COL_CROP_RES = 6
COL_SCALED_RES = 7
COLUMN_COUNT = 8

# 任意列都能取到该行的 FrameData。
# 原先用 `index.siblingAtColumn(0).data(UserRole)`：禁用列的 delegate 绘制的是
# 列 1，而 frame_data 只挂在列 0 上，必须绕一次 sibling —— 忘了就永远读不到，
# 禁用勾选不显示（这个坑真实发生过，见 _DisableColumnDelegate 的注释）。
# 让每一列都直接回答自己那一行的帧，就没有"挂在哪一列"这回事了。
FrameDataRole = Qt.ItemDataRole.UserRole + 1

# 缩略图。**刻意用自定义角色而不是 DecorationRole** —— 本 model 由列表视图与网格
# 视图**共享同一个实例**（这是两个视图能共享 QItemSelectionModel 的前提）。
# DecorationRole 会被 Qt 的默认 delegate 直接画出来，列表视图的每一格就会冒出一个
# 缩略图图标；自定义角色则只有主动去读它的网格 delegate 才会拿到，列表侧完全无感。
#
# 缩略图不进业务模型（TimelineModel）的理由同列定义：它是**网格视图的展示形态**
# （尺寸、背景模式都由网格设置决定），塞进业务模型会污染导出与存档。这里由网格把
# 自己的 `create_thumbnail` 注入进来（依赖注入，同 `bind_frames_provider`）。
ThumbnailRole = Qt.ItemDataRole.UserRole + 2

# 该行是否为参考帧（返回 bool）。网格 delegate 用它决定高亮（加粗 + 绿底文字条）。
#
# 参考帧状态**只存在一份**，在业务模型 `TimelineModel._reference_frame` 里 —— 本
# 适配层刻意**不存**副本：若自己存一份，加载工程时走的
# `MainWindow -> timeline.set_reference_frame -> TimelineModel` 那条路径设置的参考帧
# 就不会反映到显示上（显示读的是副本），表现为"工程里设了参考帧，界面却不亮"。
#
# ⚠️ 取值必须唯一 —— 曾经它与 ThumbnailRole 同为 `UserRole + 2`，于是按本角色
# 取数拿到的是缩略图 QPixmap 而不是布尔。参考帧是本项目的特色功能，这种静默错乱
# （高亮失效，甚至画图时崩溃）比直接报错更难查，故用断言钉死。
ReferenceRole = Qt.ItemDataRole.UserRole + 3

# 三个自定义角色必须互不相同：取值相同会让语义完全不同的两个角色互相覆盖。
# 新增角色时若漏改偏移，这条断言会在 import 阶段就炸掉，而不是等到运行时出现
# "参考帧高亮莫名失效"这类难以定位的症状。
assert len({FrameDataRole, ReferenceRole, ThumbnailRole}) == 3, \
    "自定义 ItemDataRole 取值冲突：两个角色取了同一个值，语义会互相覆盖"

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class TimelineItemModel(QAbstractTableModel):
    """把 `TimelineModel` 的帧列表暴露成 Qt 表格模型。

    本类**不持有**任何帧数据 —— 每次 `data()` 都回头问 `TimelineModel`。
    这是刻意的：缓存一份就等于重新引入第二份状态。
    """

    def __init__(self, frames_model=None, parent=None):
        super().__init__(parent)
        # 刻意不在这里给 `_frames` 赋值 —— 交给 `bind()`。
        #
        # 曾经这里写成 `self._frames = frames_model` 再调 `self.bind(...)`，而 bind()
        # 开头有"已绑定则直接返回"的防重入判断 —— 于是构造时传入 model 的那个实例
        # **永远不会真正接线**（`_connect_frames_model()` 一次都没被调用）。
        # 后果：模型的所有变化（增删帧、换序、改属性、撤销恢复）都不会通知到视图，
        # 视图只在被显式 refresh 或发生 Resize/Show 时才"碰巧"重新取数 —— 表现为
        # "加载完工程后时间轴是空的，拖一下面板或改一下缩略图尺寸才出来"。
        self._frames = None
        self._is_dark_theme = True
        # 缩略图提供者，由网格视图注入：`provider(frame_data) -> QPixmap`。
        # 未注入时缩略图角色返回 None（列表视图不需要它）。
        self._thumbnail_provider = None
        if frames_model is not None:
            self.bind(frames_model)

    def set_thumbnail_provider(self, provider):
        """注入缩略图提供者（由网格视图调用）。

        缩略图是网格视图的展示形态（尺寸、背景模式都是网格的设置），因此由网格自己
        算、自己缓存；本 model 只负责在 `ThumbnailRole` 上把它递给网格的 delegate。
        缓存失效也由网格发起（`invalidate_thumbnail_cache_for_paths` → `dataChanged`）。

        签名刻意**不含行号**：缩略图只由内容决定，与帧处在哪一行无关（含行号会让
        重排触发全量重算）。
        """
        self._thumbnail_provider = provider

    # ---------- 接线 ----------

    def bind(self, frames_model):
        """绑定业务真源。

        允许构造时不绑定：视图的创建早于 `TimelineWidget` 拥有 model 的时刻。
        绑定是**一次性**的 —— 本类的生命周期与视图一致，中途换 model 没有意义，
        且重复连接会让信号回调调用两次。
        """
        if self._frames is not None:
            return
        self._frames = frames_model
        self._connect_frames_model()

    def _connect_frames_model(self):
        m = self._frames
        m.frames_inserted.connect(self._on_frames_inserted)
        m.frames_removed.connect(self._on_frames_removed)
        m.frames_reordered.connect(self._on_wholesale_change)
        m.frames_replaced.connect(self._on_wholesale_change)
        m.data_changed.connect(self._on_data_changed)
        m.frame_disabled_changed.connect(self._on_frame_disabled_changed)

    def _on_frames_inserted(self, index: int, count: int):
        self.beginInsertRows(QModelIndex(), index, index + count - 1)
        self.endInsertRows()

    def _on_frames_removed(self, index: int, count: int):
        self.beginRemoveRows(QModelIndex(), index, index + count - 1)
        self.endRemoveRows()

    def _on_wholesale_change(self, *_args):
        """行到帧的映射整体失效（单个移动 / 整体换序 / 换成另一批对象），只能全量重取。

        两种情形对视图的处理完全相同，都是 `beginResetModel`：
          - `frames_reordered()` — 换序（同一批对象，行数不变）
          - `frames_replaced()` — 换成另一批对象（撤销恢复），行数也可能变

        两者都是无参信号，用 *_args 一并接住。
        """
        self.beginResetModel()
        self.endResetModel()

    def _on_data_changed(self, start: int, end: int):
        top_left = self.index(start, 0)
        bottom_right = self.index(end, COLUMN_COUNT - 1)
        self.dataChanged.emit(top_left, bottom_right, [])

    def _on_frame_disabled_changed(self, index: int, _is_disabled: bool):
        # 禁用状态只影响列 1 的绘制，但该行选中时的配色也跟着变，整行刷新最稳
        top_left = self.index(index, 0)
        bottom_right = self.index(index, COLUMN_COUNT - 1)
        self.dataChanged.emit(top_left, bottom_right, [])

    # ---------- QAbstractItemModel 必需实现 ----------

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self._frames.get_frame_count()

    def columnCount(self, parent=QModelIndex()) -> int:
        return COLUMN_COUNT

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        frame = self._frames.get_frame_at(row)
        if frame is None:
            return None

        if role == FrameDataRole:
            return frame

        if role == ReferenceRole:
            # 参考帧是"本行是否高亮"的依据，与列无关（网格只显示文件名列，但整格
            # 都要高亮）。返回 bool 而非帧对象 —— delegate 要的是判断结果。
            return frame is self._business_reference_frame()

        if role == ThumbnailRole:
            if self._thumbnail_provider is None:
                return None
            return self._thumbnail_provider(frame)

        if role == Qt.ItemDataRole.ToolTipRole:
            # 给文件名列一个悬浮提示（长文件名会被截断，列表与网格都是）。
            # 只在文件名列返回，避免整行每格都弹同一个提示。
            return self._filename(frame) if col == COL_FILENAME else None

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(frame, row, col)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SCALE, COL_POSITION, COL_CROP_ORIGIN,
                       COL_CROP_RES, COL_SCALED_RES):
                return int(_RIGHT)
            if col == COL_INDEX:
                return int(_CENTER)
            return int(_LEFT)

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(frame, col)

        if role == Qt.ItemDataRole.FontRole:
            return self._font(frame, col)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            keys = ("col_index", "col_disabled_header", "col_filename", "col_scale",
                    "col_position", "col_crop_origin", "col_crop_res", "col_scaled_res")
            if 0 <= section < len(keys):
                return i18n.t(keys[section])
            return None
        if role == Qt.ItemDataRole.ToolTipRole and section == COL_SCALED_RES:
            # 与属性面板"目标分辨率"同源（含比例失真）
            return i18n.t("col_scaled_res_tip")
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        # `ItemIsDragEnabled` **必须给出**。
        #
        # 光有 `view.setDragEnabled(True)` 是不够的：`QAbstractItemView` 的
        # `mouseMoveEvent` 决定启动拖拽时，还要再查一次 model 的 flags —— 缺了这个
        # 位，view 就进入 `DragSelectingState`，把手势解释成**扩展选区**，表现为
        # "多选后拖不动，一拖选区反而乱变"。
        #
        # 迁移前 `QTreeWidget` 用的是它内建的 model，`flags()` 默认带这个位，所以
        # 从没暴露过。换成适配层后 flags 由我们自己写 —— 漏了它就翻车。
        #
        # 刻意**不给** `ItemIsUserCheckable`：Qt 自带的复选框指示器会画一个我们不
        # 想要的 'v'，禁用列完全由 `_DisableColumnDelegate` 自己画。
        return (Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled)

    # ---------- 单元格内容 ----------

    def _display(self, frame: FrameData, row: int, col: int):
        if col == COL_INDEX:
            return str(row + 1)
        if col == COL_DISABLED:
            return ""  # 由 delegate 绘制，不给文本
        if col == COL_FILENAME:
            return self._filename(frame)
        if col == COL_SCALE:
            return f"{frame.scale:.4f}"
        if col == COL_POSITION:
            px, py = frame.position
            return f"{int(px):>4d} , {int(py):>4d}"
        if col == COL_CROP_ORIGIN:
            if not frame.crop_rect:
                return ""
            cx, cy = frame.crop_rect[0], frame.crop_rect[1]
            return f"{cx:>4d} , {cy:>4d}"
        if col == COL_CROP_RES:
            # 裁切过显示裁切尺寸，否则显示源图尺寸（零解码，结果带缓存）
            if frame.crop_rect:
                cw, ch = frame.crop_rect[2], frame.crop_rect[3]
                return f"{cw} x {ch}"
            sw, sh = frame.base_size()
            return f"({sw} x {sh})" if sw > 0 else "(? x ?)"
        if col == COL_SCALED_RES:
            # 与属性面板"目标分辨率"共用 FrameData.effective_target_size() 唯一算法
            tw, th = frame.effective_target_size()
            return f"{tw} x {th}" if tw > 0 else "? x ?"
        return None

    def _filename(self, frame: FrameData) -> str:
        fname = frame.file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if frame.slice_pos:
            fname += f" [{frame.slice_pos[0]},{frame.slice_pos[1]}]"
        if self._is_reference(frame):
            fname = f"{i18n.t('label_ref_prefix')}{fname}"
        return fname

    def _business_reference_frame(self) -> Optional[FrameData]:
        """业务模型里的参考帧（唯一真源）。

        本适配层不存副本 —— 存了就会与业务模型脱节：加载工程、
        `MainWindow.set_reference_frame` 等都只改业务模型，改不到副本，
        于是"设了参考帧但高亮不亮"。
        """
        if self._frames is None:
            return None
        return self._frames.get_reference_frame()

    def _is_reference(self, frame: FrameData) -> bool:
        return frame is self._business_reference_frame()

    def _background(self, frame: FrameData, col: int):
        # 参考帧高亮只着文件名列（与迁移前的 item.setBackground(2, ...) 一致）
        if col == COL_FILENAME and self._is_reference(frame):
            if self._is_dark_theme:
                color = QColor(30, 80, 40)
                color.setAlpha(200)
            else:
                color = QColor(200, 230, 200)
                color.setAlpha(255)
            return color
        return None

    def _font(self, frame: FrameData, col: int):
        if col == COL_FILENAME and self._is_reference(frame):
            font = QFont()
            font.setBold(True)
            return font
        return None

    # ---------- 供视图调用 ----------

    def set_reference_frame(self, frame: Optional[FrameData]):
        """设置参考帧并刷新。

        迁移前是在 item 上改 font/background，并往文件名字符串里增删"参考"前缀
        （`text.replace(prefix, "")`）—— 若文件名本身含该前缀会被误删。现在前缀
        由 `_filename()` 现算，天然幂等。
        """
        if self._frames is not None:
            # 转发到业务模型（唯一真源）。它不发信号，故下面补发 dataChanged。
            self._frames.set_reference_frame(frame)
        if self.rowCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, COLUMN_COUNT - 1), [])

    def set_theme_mode(self, is_dark: bool):
        self._is_dark_theme = is_dark
        if self._business_reference_frame() is not None and self.rowCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, COLUMN_COUNT - 1), [])

    def frame_at_row(self, row: int) -> Optional[FrameData]:
        return self._frames.get_frame_at(row)

    def sizeHint(self, index):  # noqa: N802 - Qt 命名
        return QSize()
