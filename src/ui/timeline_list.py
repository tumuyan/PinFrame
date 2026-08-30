from PyQt6.QtWidgets import (
    QTreeView, QAbstractItemView, QHeaderView, QMenu,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
from PyQt6.QtCore import Qt, QTimer, QItemSelectionModel, QModelIndex, QMimeData, QRect
from PyQt6.QtGui import QColor, QAction, QDrag, QPixmap, QPainter, QPen
from i18n.manager import i18n
from ui.timeline_item_model import (
    TimelineItemModel, FrameDataRole, COL_DISABLED, COL_FILENAME, COLUMN_COUNT,
)
from ui.timeline_selection_style import SELECTED_BG_QCOLOR
from ui.timeline_view_signals import TimelineViewSignals
from model.project_data import FrameData
from typing import List, Optional
import os

# Debug flag - set to False to disable debug output
DEBUG_LIST_VIEW = False


class _DisableColumnDelegate(QStyledItemDelegate):
    """Paints column 1 of every row using only our custom indicator.

    Why a delegate instead of paintEvent overlay:
      - The column-1 cell is set empty (no text, no role data other than
        CheckStateRole), so QTreeWidget has no native decoration to draw.
      - The delegate's paint() is invoked for every column (including 1),
        guaranteeing we always own the visuals.
      - We force-enable ItemIsUserCheckable from outside? No - by giving the
        item *no* data role of CheckStateRole when not needed, plus no
        ItemIsUserCheckable flag, Qt's QStyle draws nothing for the cell.
        We draw the box / x ourselves.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Only paint column 1 (disable indicator); other columns delegate normally.
        if index.column() != COL_DISABLED:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        # 每一列都能直接取到本行的 FrameData（FrameDataRole），不必再绕
        # siblingAtColumn(0) —— 当初 frame_data 只挂在列 0 上，忘了绕一次
        # 就永远读到空值、禁用勾选不显示。
        frame_data = index.data(FrameDataRole)
        is_disabled = bool(getattr(frame_data, 'is_disabled', False)) if frame_data else False
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Erase any Qt-drawn remnants inside the cell (focus rectangles, default
        # checkbox indicators, etc.). We don't know what was drawn before us,
        # so we paint the background over the whole cell first.
        #
        # 选中时必须铺**选中色**，不能铺 `palette.base()`：base 是本列自己的底色，
        # 用它会在整行选中色里切出一个异色缺口 —— 而"这一行到底选没选中"靠的正是
        # 整行颜色的连续性，缺一格就非常显眼。更要命的是 `palette.base()` 是
        # **平台相关**的值（Fusion / Windows / macOS 各不相同，Windows 上还跟着
        # 用户的系统主题走），这是"Windows 下多选看不清"最直接的来源。
        #
        # 颜色取自 ui/timeline_selection_style.py（单一真源），与 QSS 和网格
        # delegate 共用，三者任一不同都会把选中帧切成几段不同颜色。
        if is_selected:
            painter.fillRect(rect, SELECTED_BG_QCOLOR)
        else:
            painter.fillRect(rect, option.palette.base())

        # Compute a square indicator area, centred both horizontally and
        # vertically in the cell. Using min(width, height) keeps the indicator
        # a perfect square regardless of the column's actual aspect ratio,
        # which avoids the 'squashed x' rendering when column width differs
        # from row height.
        side = max(8, min(rect.width(), rect.height()) - 6)
        cx = rect.left() + rect.width() // 2
        cy = rect.top() + rect.height() // 2
        box = QRect(cx - side // 2, cy - side // 2, side, side)

        # Inset further so the 1-px stroke doesn't get clipped at the edges.
        pad = 3
        inner = QRect(box.left() + pad, box.top() + pad,
                      box.width() - 2 * pad, box.height() - 2 * pad)

        if is_disabled:
            x_color = QColor(230, 80, 80) if is_selected else QColor(200, 60, 60)
            painter.setPen(QPen(x_color, 1.8))
            painter.drawLine(inner.left(), inner.top(),
                             inner.right(), inner.bottom())
            painter.drawLine(inner.right(), inner.top(),
                             inner.left(), inner.bottom())
        else:
            box_color = QColor(180, 180, 180) if is_selected else QColor(150, 150, 150)
            painter.setPen(QPen(box_color, 1))
            painter.drawRect(inner)
        painter.restore()


class TimelineListView(QTreeView):
    """时间轴的列表视图（表格形态，8 列）。

    已迁到 Qt model/view：挂 `TimelineItemModel`，单元格内容由 model 的 `data()`
    现算，本视图**不持有任何帧数据或顺序** —— 那些都在 `TimelineModel` 里。
    迁移前它是 `QTreeWidget`，帧数据挂在 `QTreeWidgetItem` 的 `UserRole` 上。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 上行动作通知（右键菜单 / 拖拽 / 选中）。声明在 `ui.timeline_view_signals`
        # —— 列表视图、网格视图与 `TimelineWidget` 共用同一份，只声明一遍。
        self.signals = TimelineViewSignals(self)

        self._editors = []
        # 帧数据与顺序的唯一真源（TimelineModel）。由 TimelineWidget 注入
        # （依赖注入，避免 ui 层之间互相硬引用）。视图不再拥有顺序，
        # 拖拽只算出"拖了哪几行、插到哪儿"。
        self._model = None
        # Qt 适配层，包装 _model 供本视图消费
        self._item_model = TimelineItemModel(None, self)

        header = self.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(0)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self._selection_debounce_timer = QTimer(self)
        self._selection_debounce_timer.setSingleShot(True)
        self._selection_debounce_timer.setInterval(50)
        self._selection_debounce_timer.timeout.connect(self._emit_selection_changed)

        self._selection_blocked = False

        self.is_dark_theme = True
        self.setMinimumHeight(120)

        self._dragged_rows = []  # 拖拽中的行号（selectionModel 在拖拽期间不可靠）

        # Disable-column rendering (column 1):
        #   - state is read directly from frame_data.is_disabled (model 真源，
        #     经 FrameDataRole 现取)，视图侧不存任何 CheckStateRole 副本，
        #   - model 的 flags() 刻意不给 ItemIsUserCheckable（Qt 自带的复选框
        #     指示器会画一个我们不想要的 'v'），
        #   - column 1 的视觉完全归 _DisableColumnDelegate：启用画空心方框，
        #     禁用画红叉，
        #   - clicks on column 1 are intercepted in mousePressEvent() to toggle
        #     the state via TimelineModel.set_frame_disabled() and emit
        #     disabled_state_changed (for undo history).
        self.setItemDelegateForColumn(COL_DISABLED, _DisableColumnDelegate(self))

    def get_selected_indices(self) -> List[int]:
        """Get indices of selected rows"""
        return sorted({idx.row() for idx in self.selectionModel().selectedRows()}
                      if self.selectionModel() else [])

    def get_selected_frames(self) -> List[FrameData]:
        """选中行的帧数据（按行号升序）。"""
        model = self._get_model()
        if model is None:
            return []
        return [model.get_frame_at(i) for i in self.get_selected_indices()
                if model.get_frame_at(i) is not None]

    def bind_model(self, model):
        """注入帧数据与顺序的唯一真源（由 TimelineWidget 调用）。

        注入后视图不再拥有顺序 —— 拖拽只负责算出"拖了哪几行、插到哪儿"，
        顺序变更一律经 `model.move_frames`，视图随模型信号更新。
        """
        self._model = model
        # 与网格视图共用**同一个**适配层实例（由 TimelineWidget 创建），于是两个视图
        # 共享同一个 QItemSelectionModel —— 这才是 P1-3 想要的"选中只有一份"。
        shared = getattr(self.parent(), 'item_model', None)
        if shared is not None and shared is not self._item_model:
            self._item_model = shared
        self._item_model.bind(model)
        self.setModel(self._item_model)
        # 必须在 setModel 之后：QHeaderView 会在 setModel 时按新模型的列数重建
        # section 状态，之前设的 resizeMode / 列宽全部作废（表现为 8 列等宽 100px）。
        self._setup_columns()
        self.selectionModel().selectionChanged.connect(self.on_selection_changed)

    def _setup_columns(self):
        """列宽与缩放策略。

        只能在 `setModel()` **之后**调用 —— 见 `bind_model` 里的注释。
        """
        header = self.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(0)

        # Column 0: Index
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 40)

        # Column 1: Disable icon
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 24)

        # Columns 3-7: Fixed/Interactive sizes
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 80)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(4, 110)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(5, 120)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(6, 130)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(7, 130)

        # Column 2: Filename - STRETCH
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def _get_model(self):
        """取模型真源；未显式注入时回退到 parent（TimelineWidget.model）。"""
        if self._model is not None:
            return self._model
        return getattr(self.parent(), 'model', None)

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """Get frame data at specified index"""
        model = self._get_model()
        return model.get_frame_at(index) if model is not None else None

    # 增删帧不需要视图做任何事 —— 模型发出的 frames_inserted / frames_removed
    # 会由适配层翻译成 beginInsertRows / beginRemoveRows，视图自动跟随。
    # 迁移前这里有 add_frame_to_view / remove_frame_from_view / update_frame_in_view
    # 三个方法，迁到 model/view 后全部退化为空，已删除。

    def get_item_count(self) -> int:
        """Get total number of rows in view"""
        return self._item_model.rowCount()

    def block_selection_signals(self, block: bool):
        """Block or unblock selection change signals (auto-emit on unblock)"""
        self._selection_blocked = block
        if not block:
            self._emit_selection_changed()

    def block_selection_signals_internal(self, block: bool):
        """Block or unblock selection change signals AND Qt's selectionChanged"""
        self._selection_blocked = block
        sel_model = self.selectionModel()
        if sel_model is None:
            return
        if block:
            try:
                sel_model.selectionChanged.disconnect(self.on_selection_changed)
            except TypeError:
                # Already disconnected or never connected
                pass
        else:
            sel_model.selectionChanged.connect(self.on_selection_changed)

    def select_all_optimized(self):
        """Select all rows efficiently"""
        self._selection_blocked = True
        self.selectAll()
        self._selection_blocked = False
        self._emit_selection_changed()

    def _emit_selection_changed(self):
        """Emit selection changed signal"""
        if self._selection_blocked:
            return
        self.signals.selection_changed.emit(self.get_selected_frames())

    def _apply_selection_from_set(self, selected_indices_set: set):
        """Apply selection from a set of indices.

        只改动需要变更的行 —— 整表重设会打断用户按住 Ctrl 的连续多选
        （`selectionChanged` 每次都会触发防抖定时器 → 连锁刷新属性面板）。
        """
        sel_model = self.selectionModel()
        if sel_model is None:
            return
        current = set(self.get_selected_indices())
        if current == selected_indices_set:
            return
        was_blocked = self._selection_blocked
        self._selection_blocked = True
        for row in current - selected_indices_set:
            sel_model.select(self._item_model.index(row, 0),
                             QItemSelectionModel.SelectionFlag.Deselect
                             | QItemSelectionModel.SelectionFlag.Rows)
        for row in selected_indices_set - current:
            sel_model.select(self._item_model.index(row, 0),
                             QItemSelectionModel.SelectionFlag.Select
                             | QItemSelectionModel.SelectionFlag.Rows)
        self._selection_blocked = was_blocked

    def set_theme_mode(self, is_dark: bool):
        """Set theme mode (dark/light)"""
        self.is_dark_theme = is_dark
        self._item_model.set_theme_mode(is_dark)

    def set_visual_reference_frame(self, frame_data: Optional[FrameData]):
        """设置/清除参考帧高亮。

        参考帧状态**只存在一份**（在业务模型里，经共享的适配层 model 读写）：本方法
        把它写进去并触发刷新，delegate 再经 `ReferenceRole` 读回。本视图刻意不保留
        `reference_frame_data` 之类的镜像 —— 那会让"取消参考帧"时漏掉一处，高亮残留。
        """
        self._item_model.set_reference_frame(frame_data)

    def refresh_visuals(self):
        """Refresh visual elements (reference highlighting, etc.)

        高亮状态在 model 里，重建视图不会丢，因此这里只需按当前值重设一次。
        """
        self._item_model.set_reference_frame(
            self._item_model._business_reference_frame())

    def on_selection_changed(self):
        """Handle selection change"""
        if self._selection_blocked:
            return

        self._selection_debounce_timer.start()

    def startDrag(self, supportedActions):
        rows = self.get_selected_indices()
        if not rows:
            return
        # 拖拽期间 selectionModel 会被 Qt 改动，行号必须先存下来
        self._dragged_rows = rows

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData("application/x-pinframe-internal-reorder", b"reorder")
        drag.setMimeData(mime_data)

        # 简单的拖拽反馈图标
        pixmap = QPixmap(100, 24)
        pixmap.fill(QColor(60, 130, 220, 160))
        drag.setPixmap(pixmap)

        drag.exec(Qt.DropAction.MoveAction)
        self._dragged_rows = []

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        elif event.mimeData().hasFormat("application/x-pinframe-internal-reorder"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        elif event.mimeData().hasFormat("application/x-pinframe-internal-reorder"):
            drop_pos = event.position().toPoint()
            drop_row = self.indexAt(drop_pos).row()
            if drop_row >= 0:
                rect = self.visualRect(self._item_model.index(drop_row, 0))
                # 落在行的上半 → 插到它前面；下半 → 插到它后面
                before = drop_pos.y() < rect.center().y()
                self._drag_insert_position = (drop_row, before)
            else:
                self._drag_insert_position = (self._item_model.rowCount(), False)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._drag_insert_position = None
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            links = []
            for url in event.mimeData().urls():
                links.append(url.toLocalFile())

            final_index = -1
            drop_row = self.indexAt(event.position().toPoint()).row()
            drop_pos = self.dropIndicatorPosition()

            if drop_row >= 0:
                if drop_pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
                    final_index = drop_row
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.BelowItem:
                    final_index = drop_row + 1
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.OnItem:
                    final_index = drop_row + 1
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.OnViewport:
                    final_index = -1

            event.accept()
            self.signals.files_dropped.emit(links, final_index)
        elif event.mimeData().hasFormat("application/x-pinframe-internal-reorder"):
            # 内部重排：完全受控，保证原有先后顺序
            selected_indices = sorted(getattr(self, '_dragged_rows', None) or self.get_selected_indices())
            if not selected_indices:
                self._drag_insert_position = None
                event.ignore()
                return

            # 计算插入位置
            if getattr(self, '_drag_insert_position', None) is not None:
                index, before = self._drag_insert_position
                insert_index = index if before else index + 1
            else:
                drop_row = self.indexAt(event.position().toPoint()).row()
                drop_pos = self.dropIndicatorPosition()
                if drop_row >= 0:
                    if drop_pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
                        insert_index = drop_row
                    else:
                        insert_index = drop_row + 1
                else:
                    insert_index = self._item_model.rowCount()

            # 顺序变更交给模型 —— 视图不再自己 takeTopLevelItem/insertTopLevelItem 搬 item。
            #
            # 曾经视图直接改 item 顺序、模型毫不知情，之后再由 MainWindow.on_order_changed
            # 把视图顺序**回写**给模型，等于顺序有两个源：这正是"切视图后顺序错乱"以及
            # 需要 _view_in_sync_with_model 兜底的根因。
            #
            # 坐标系转换（insert_index → 移除被拖项之后的下标）、原位判据、选中跟随
            # 全部在 model.move_frames 内部；成功时它发 frames_reordered，视图按模型重建。
            self._drag_insert_position = None
            model = self._get_model()
            if model is None:
                event.ignore()
                return

            # 快照必须在改模型之前捕获（MainWindow 连这个信号做撤销记录）
            self.signals.reorder_about_to_happen.emit()
            if not model.move_frames(selected_indices, insert_index):
                event.ignore()
                return

            event.accept()
            self.signals.order_changed.emit()
        else:
            super().dropEvent(event)
            self.signals.order_changed.emit()

    def show_context_menu(self, position):
        menu = QMenu()

        # 扁平列表（rootIsDecorated=False、且 model 无层级），不存在"折叠的子项"
        selected_count = len(self.get_selected_indices())
        has_selection = selected_count > 0

        copy_action = QAction(i18n.t("action_copy_props"), self)
        copy_action.triggered.connect(self.signals.copy_properties_requested.emit)
        copy_action.setEnabled(has_selection)

        paste_action = QAction(i18n.t("action_paste_props"), self)
        paste_action.triggered.connect(self.signals.paste_properties_requested.emit)

        dup_action = QAction(i18n.t("action_dup_frame"), self)
        dup_action.triggered.connect(self.signals.duplicate_requested.emit)
        dup_action.setEnabled(has_selection)

        dup_dialog_action = QAction(i18n.t("action_dup_frames_dialog"), self)
        dup_dialog_action.triggered.connect(self.signals.duplicate_dialog_requested.emit)
        dup_dialog_action.setEnabled(has_selection)

        rem_action = QAction(i18n.t("action_rem_frame"), self)
        rem_action.triggered.connect(self.signals.remove_requested.emit)
        rem_action.setEnabled(has_selection)

        disable_action = QAction(i18n.t("disable_frame_label", "Disable Frame(s)"), self)
        disable_action.triggered.connect(lambda: self.signals.enable_requested.emit(False))
        disable_action.setEnabled(has_selection)

        enable_action = QAction(i18n.t("enable_frame_label", "Enable Frame(s)"), self)
        enable_action.triggered.connect(lambda: self.signals.enable_requested.emit(True))
        enable_action.setEnabled(has_selection)

        reverse_action = QAction(i18n.t("action_reverse_order"), self)
        reverse_action.triggered.connect(self.signals.reverse_order_requested.emit)
        reverse_action.setEnabled(selected_count > 1)

        int_action = QAction(i18n.t("action_integerize"), self)
        int_action.triggered.connect(self.signals.integerize_offset_requested.emit)
        int_action.setEnabled(has_selection)

        smooth_action = QAction(i18n.t("action_smooth_params"), self)
        smooth_action.triggered.connect(self.signals.smooth_params_requested.emit)
        smooth_action.setEnabled(selected_count > 1)

        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.addSeparator()
        menu.addAction(int_action)
        menu.addAction(smooth_action)
        menu.addSeparator()
        menu.addAction(disable_action)
        menu.addAction(enable_action)
        menu.addAction(reverse_action)
        menu.addSeparator()

        ref_action = QAction(i18n.t("action_set_reference"), self)
        ref_action.triggered.connect(self.signals.set_reference_requested.emit)
        ref_action.setEnabled(selected_count == 1)

        clear_ref_action = QAction(i18n.t("action_clear_reference"), self)
        clear_ref_action.triggered.connect(self.signals.clear_reference_requested.emit)

        menu.addAction(ref_action)
        menu.addAction(clear_ref_action)
        menu.addSeparator()

        menu.addAction(dup_action)
        menu.addAction(dup_dialog_action)
        menu.addAction(rem_action)

        # ---- 外部图像编辑器 ----
        if has_selection:
            menu.addSeparator()
            default_action = QAction(i18n.t("action_edit_default_editor"), self)
            default_action.triggered.connect(self.signals.edit_default_editor_requested.emit)
            menu.addAction(default_action)
            if self._editors:
                editor_menu = menu.addMenu(i18n.t("menu_edit_external_editor"))
                for ed in self._editors:
                    name = ed.get("name") or os.path.basename(ed.get("path") or "")
                    act = editor_menu.addAction(name)
                    act.triggered.connect(
                        lambda checked=False, ed=ed: self.signals.edit_in_editor_requested.emit(ed))
            else:
                default_action.setEnabled(False)

        menu.exec(self.viewport().mapToGlobal(position))

    def set_editors(self, editors):
        """外部图像编辑器列表，用于右键子菜单。"""
        self._editors = editors or []

    def mousePressEvent(self, event):
        """Intercept clicks on the disable column (column 1) to toggle state.

        We don't use Qt's ItemIsUserCheckable because its built-in checkbox
        indicator draws an unwanted 'v' tick. Instead, the user clicks on
        column 1 of any row, and we toggle the frame's disabled state through
        the TimelineModel (single source of truth). The model emits
        frame_disabled_changed / data_changed which trigger a repaint; we only
        re-emit disabled_state_changed so MainWindow can record undo history.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index.isValid():
                x_start = self.columnViewportPosition(COL_DISABLED)
                w = self.columnWidth(COL_DISABLED)
                if x_start <= pos.x() < x_start + w:
                    frame_data = index.data(FrameDataRole)
                    if frame_data:
                        idx = index.row()
                        model = self._get_model()
                        new_is_disabled = not frame_data.is_disabled
                        if model is not None and model.set_frame_disabled(idx, new_is_disabled):
                            # Model 已改真源并触发 dataChanged，视图自动重绘；
                            # 仅转发信号供 MainWindow 记录 undo。
                            self.signals.disabled_state_changed.emit(frame_data, new_is_disabled)
                        event.accept()
                        return
        super().mousePressEvent(event)

    def refresh_ui_text(self):
        """语言切换：表头文案由 model 的 headerData() 现取，只需让表头重画。"""
        self._item_model.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)

    def refresh_current_items(self):
        """强制重绘可见单元格。

        内容由 model 现算，平时靠 `dataChanged` 驱动；这里补的是"非活动视图"那一半
        —— `_on_data_changed` 出于性能刻意跳过它，切过来时它的缓存渲染还是旧的。

        迁移前这里要遍历所有 item 重算 8 列文本（含读源图尺寸的磁盘 I/O）；现在
        model 只服务可见行，且源图尺寸带缓存。
        """
        self.viewport().update()
