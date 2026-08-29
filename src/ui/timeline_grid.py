from PyQt6.QtWidgets import QListView, QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QPoint, QRectF, QItemSelectionModel, QModelIndex, QMimeData
from PyQt6.QtGui import QColor, QImage, QPixmap, QPainter, QBrush, QPen, QFont, QIcon, QAction, QDrag
from i18n.manager import i18n
from ui.timeline_grid_delegate import TimelineGridDelegate
from ui.timeline_item_model import COL_FILENAME, TimelineItemModel, ThumbnailRole
from model.project_data import FrameData
from typing import List, Optional
import os


class TimelineGridWidget(QListView):
    """时间轴的网格视图（缩略图形态）。

    已迁到 Qt model/view：与列表视图挂**同一个** `TimelineItemModel` 实例，因此两
    个视图天然共享 `QItemSelectionModel`（P1-3 最大的一条收益）。本视图**不持有
    帧数据或顺序** —— 那些都在 `TimelineModel` 里。

    缩略图仍由本视图计算与缓存（它是网格的展示形态：尺寸、背景模式都是网格的设置），
    通过 `TimelineItemModel.set_thumbnail_provider` 注入、经 `ThumbnailRole` 递给
    delegate。迁移前它是 `QListWidget`，帧数据挂在 `QListWidgetItem` 的 UserRole 上。
    """

    selection_changed = pyqtSignal(list)
    order_changed = pyqtSignal()
    # 顺序变更前发出（拖拽已算出目标位置、尚未调用 model.move_frames）。
    # 撤销快照必须在改模型之前捕获，否则快照到的就是新顺序。
    reorder_about_to_happen = pyqtSignal()
    files_dropped = pyqtSignal(list, int)
    copy_properties_requested = pyqtSignal()
    paste_properties_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    duplicate_dialog_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    disabled_state_changed = pyqtSignal(object, bool)
    enable_requested = pyqtSignal(bool)
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()
    smooth_params_requested = pyqtSignal()
    set_reference_requested = pyqtSignal()
    clear_reference_requested = pyqtSignal()
    edit_default_editor_requested = pyqtSignal()
    edit_in_editor_requested = pyqtSignal(object)  # 编辑器 dict（{name, path, default}）
    thumbnail_size_changed = pyqtSignal(int, int)  # width, height

    def __init__(self, parent=None):
        super().__init__(parent)

        # View mode settings
        self.thumbnail_width = 120
        self.thumbnail_height = 120
        self.show_multiline = False
        self.multiline_label_height = 36  # Custom height for multiline text area (default 36px)
        self.background_mode = "checkerboard"  # black, white, gray, checkerboard, green
        self._editors = []

        # 帧数据与顺序的唯一真源。由 TimelineWidget 注入（依赖注入，避免 ui 层之间
        # 互相硬引用）。视图不再拥有顺序，拖拽只算出"拖了哪几行、插到哪儿"。
        self._model = None

        # Widget settings
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Snap)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)  # Enable internal move for drag&drop
        self.setDropIndicatorShown(True)  # Show drop indicator during drag
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # 必须与列表视图一致：两者共享同一个 QItemSelectionModel，若这里是默认的
        # SelectItems，点击就只选中**自己那一列**（网格是文件名列 2），而列表按列 0
        # 去读 `selectedRows()` 就会认为"什么都没选" —— 表现为"点了帧，属性面板
        # 显示未选中、预览区没反应"。
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Set context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        # Selection debounce timer
        self._selection_debounce_timer = QTimer(self)
        self._selection_debounce_timer.setSingleShot(True)
        self._selection_debounce_timer.setInterval(50)
        self._selection_debounce_timer.timeout.connect(self._emit_selection_changed)

        self._selection_blocked = False

        self.is_dark_theme = True

        # Drag position tracking
        self._drag_insert_position = None  # (index, before) - where before is True if inserting before the item
        self._is_dragging = False
        self._dragged_rows = []  # 拖拽中的行号（selectionModel 在拖拽期间不可靠）

        # Set custom delegate for drawing frame numbers
        self.setItemDelegate(TimelineGridDelegate(self))

        # Thumbnail cache to avoid recreating the same thumbnail repeatedly
        self._thumbnail_cache = {}  # key: (file_path, crop_rect, ...), value: QPixmap

        # Set item size based on thumbnail dimensions
        self.update_item_size()
    
    def set_thumbnail_size(self, width, height):
        """Set thumbnail size"""
        self.thumbnail_width = width
        self.thumbnail_height = height
        self.update_item_size()
        self.refresh_all_items()
        self.thumbnail_size_changed.emit(width, height)
    
    def set_show_multiline(self, multiline):
        """Set whether to show multiline filename"""
        self.show_multiline = multiline
        # Update delegate's multiline setting
        delegate = self.itemDelegate()
        if hasattr(delegate, 'set_show_multiline'):
            delegate.set_show_multiline(multiline)
        self.update_item_size()
        self.refresh_all_items()

    def set_multiline_label_height(self, height: int):
        """Set the height of text area in multiline mode (in pixels)"""
        if self.multiline_label_height != height and height > 0:
            self.multiline_label_height = height
            self.update_item_size()
            self.refresh_all_items()

    def set_background_mode(self, mode):
        """Set background mode for thumbnails"""
        if self.background_mode != mode:
            self.background_mode = mode
            self._clear_thumbnail_cache()
            self.refresh_all_items()

    def _get_cache_key(self, image_path, frame_data, index):
        """Generate cache key for thumbnail"""
        crop_key = tuple(frame_data.crop_rect) if frame_data.crop_rect else None
        # Frame number (index) is no longer part of cache key since it's drawn by delegate
        return (image_path, crop_key, self.background_mode, self.thumbnail_width, self.thumbnail_height, frame_data.is_disabled)

    def _clear_thumbnail_cache(self):
        """Clear thumbnail cache"""
        self._thumbnail_cache.clear()

    def invalidate_thumbnail_cache_for_paths(self, paths):
        """失效指定源图路径对应的缩略图缓存，并让用到这批图的行重取。

        paths: 绝对路径列表。匹配缓存 key 中的源图路径（image_path）进行定向清除。

        **清除之后必须通知视图重取**（本方法负责，调用方不必再补一次刷新）：
        缩略图缓存是本视图自己维护的，model 的 `data()` 不知道缓存被动过，不通知
        的话视图会继续画缓存里那张已废弃的 QPixmap —— 表现为"外部编辑器改完图，
        时间轴毫无变化"，而数据层其实已经是新的。
        """
        if not paths:
            return
        path_set = {os.path.abspath(p) for p in paths}
        stale = [k for k in self._thumbnail_cache if k[0] in path_set]
        for k in stale:
            self._thumbnail_cache.pop(k, None)
        self._notify_rows_using_paths(path_set)

    def _notify_rows_using_paths(self, path_set):
        """只让 `file_path` 落在 `path_set` 里的行发 `dataChanged`。

        按行判断而非按"删了几条缓存"判断：一张源图常被几十帧共用（切片工程尤其），
        而缓存是按内容做 key 的 —— 删除条数既不等于行数，被删时也可能一个都不剩
        （行还没渲染过）。以行为准才不会漏通知。
        """
        model = self._get_model()
        item_model = self.model()
        if model is None or item_model is None:
            return
        rows = [r for r in range(item_model.rowCount())
                if (f := model.get_frame_at(r)) is not None
                and os.path.abspath(f.file_path) in path_set]
        if not rows:
            return

        col = self.modelColumn()
        start = prev = rows[0]
        for r in rows[1:] + [None]:  # 末尾哨兵：把最后一段冲出去
            if r is not None and r == prev + 1:
                prev = r
                continue
            item_model.dataChanged.emit(
                item_model.index(start, col), item_model.index(prev, col), [])
            if r is not None:
                start = prev = r

    def update_item_size(self):
        """Update grid item size based on thumbnail dimensions"""
        label_height = self.multiline_label_height if self.show_multiline else 20
        item_width = self.thumbnail_width + 8
        item_height = self.thumbnail_height + label_height + 8
        self.setIconSize(QSize(self.thumbnail_width, self.thumbnail_height))
        self.setGridSize(QSize(item_width, item_height))
        # Clear cache when size changes
        self._clear_thumbnail_cache()
    
    def set_theme_mode(self, is_dark):
        self.is_dark_theme = is_dark
        self.refresh_all_items()
    
    def set_visual_reference_frame(self, frame_data):
        """设置/清除参考帧高亮。

        参考帧状态**只存在一份**（在业务模型里，经共享的适配层 model 读写）：本方法
        把它写进去并触发刷新，delegate 再经 `ReferenceRole` 读回。本视图刻意不保留
        `reference_frame_data` 之类的镜像 —— 那会让"取消参考帧"时漏掉一处，高亮残留。
        """
        item_model = getattr(self, '_item_model', None)
        if item_model is not None:
            item_model.set_reference_frame(frame_data)
        else:
            self.refresh_all_items()  # 未绑定共享 model 时退化为自刷
    
    def refresh_visuals(self):
        item_model = getattr(self, '_item_model', None)
        if item_model is not None:
            item_model.set_reference_frame(item_model._business_reference_frame())
    
    def block_selection_signals(self, block: bool):
        """Block or unblock selection change signals (auto-emit on unblock)"""
        self._selection_blocked = block
        if not block:
            self._emit_selection_changed()

    def block_selection_signals_internal(self, block: bool):
        """Block or unblock selection change signals AND Qt's selectionChanged"""
        self._selection_blocked = block
        sel = self.selectionModel()
        if sel is None:
            return
        if block:
            try:
                sel.selectionChanged.disconnect(self.on_selection_changed)
            except TypeError:
                # Already disconnected or never connected
                pass
        else:
            sel.selectionChanged.connect(self.on_selection_changed)

    def select_all_optimized(self):
        """Select all items efficiently"""
        self._selection_blocked = True
        self.selectAll()
        self._selection_blocked = False
        self._emit_selection_changed()

    def get_selected_indices(self) -> List[int]:
        """Get indices of selected rows"""
        sel = self.selectionModel()
        if sel is None:
            return []
        return sorted({idx.row() for idx in sel.selectedIndexes()
                       if idx.column() == self.modelColumn()})

    def get_selected_frames(self) -> List[FrameData]:
        """选中行的帧数据（按行号升序）。"""
        model = self._get_model()
        if model is None:
            return []
        return [model.get_frame_at(i) for i in self.get_selected_indices()
                if model.get_frame_at(i) is not None]

    def bind_model(self, model):
        """注入帧数据与顺序的唯一真源，并挂上共享的 Qt 适配层（由 TimelineWidget 调用）。

        注入后视图不再拥有顺序 —— 拖拽只负责算出"拖了哪几行、插到哪儿"，顺序变更
        一律经 `model.move_frames`，视图随模型信号更新。
        """
        self._model = model
        # 与列表视图共用**同一个**适配层实例（由 TimelineWidget 创建），于是两个视图
        # 共享同一个 QItemSelectionModel —— 这才是 P1-3 想要的"选中只有一份"。
        self._item_model = getattr(self.parent(), 'item_model', None)
        if self._item_model is None:  # 单独构造本视图时的兜底
            self._item_model = TimelineItemModel(model, self)
        self.setModel(self._item_model)
        # 网格展示的是文件名那一列（决定悬浮提示等由 model 提供的角色）
        self.setModelColumn(COL_FILENAME)
        # 缩略图仍由本视图算（尺寸/背景模式都是网格的设置），注入给 model 转发
        self._item_model.set_thumbnail_provider(self.thumbnail_for_row)
        self.selectionModel().selectionChanged.connect(self.on_selection_changed)

    def adopt_shared_selection_model(self, selection_model):
        """改用共享的选择模型（由 TimelineWidget 调用）。

        **必须在 `setSelectionModel()` 之后重新连接信号** —— 换 selectionModel
        会丢弃旧模型上的所有连接，`bind_model` 里连上的那个随之失效：本视图从此
        不再发出 `selection_changed`，点击帧时下游（属性面板、预览区）收不到通知，
        表现为"点了没反应"。

        迁移前两个视图各有独立的 selectionModel、各自连接；共享之后这里的重连是必需的。
        """
        self.setSelectionModel(selection_model)
        try:
            selection_model.selectionChanged.disconnect(self.on_selection_changed)
        except (TypeError, RuntimeError):
            pass  # 未曾连接，或已被 disconnect
        selection_model.selectionChanged.connect(self.on_selection_changed)

    def thumbnail_for_row(self, row: int, frame_data: FrameData) -> Optional[QPixmap]:
        """`ThumbnailRole` 的提供者：把本视图的缩略图缓存交给 delegate。"""
        if frame_data is None:
            return None
        return self.create_thumbnail(frame_data.file_path, frame_data, row)

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

    def clear_view(self):
        """清空缩略图缓存；行由模型的 `clear()` 驱动移除。"""
        self._clear_thumbnail_cache()

    def get_item_count(self) -> int:
        """Get total number of rows in view"""
        return self.model().rowCount() if self.model() is not None else 0

    def _emit_selection_changed(self):
        if self._selection_blocked:
            return
        self.selection_changed.emit(self.get_selected_frames())

    def _apply_selection_from_set(self, selected_indices_set: set):
        """Apply selection from a set of row indices.

        只改动需要变更的行 —— 整表重设会打断用户按住 Ctrl 的连续多选
        （`selectionChanged` 每次都会触发防抖定时器 → 连锁刷新属性面板）。
        """
        sel = self.selectionModel()
        if sel is None:
            return
        current = set(self.get_selected_indices())
        if current == selected_indices_set:
            return
        col = self.modelColumn()
        # 必须带 `Rows`：本视图与列表视图共享同一个 QItemSelectionModel，但显示的是
        # **不同的列**（网格是文件名列、列表是序号列）。若只选中自己那一列，另一个
        # 视图按自己的列过滤 `selectedIndexes()` 就会什么都看不到 —— 选中在它眼里
        # 是空的。带上 Rows 让选中整行生效，两视图才能一致。
        was_blocked = self._selection_blocked
        self._selection_blocked = True
        for row in current - selected_indices_set:
            sel.select(self.model().index(row, col),
                       QItemSelectionModel.SelectionFlag.Deselect
                       | QItemSelectionModel.SelectionFlag.Rows)
        for row in selected_indices_set - current:
            sel.select(self.model().index(row, col),
                       QItemSelectionModel.SelectionFlag.Select
                       | QItemSelectionModel.SelectionFlag.Rows)
        self._selection_blocked = was_blocked
    
    def create_thumbnail(self, image_path, frame_data, index):
        """Create thumbnail with overlay information (with caching)"""
        cache_key = self._get_cache_key(image_path, frame_data, index)

        # Check cache first
        if cache_key in self._thumbnail_cache:
            return self._thumbnail_cache[cache_key]

        # Create base image with background
        img = QImage(self.thumbnail_width, self.thumbnail_height, QImage.Format.Format_ARGB32)
        # Fill with transparent for all modes first
        img.fill(QColor(0, 0, 0, 0))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw background (except for transparent mode)
        self.draw_background(painter, img.rect())

        # Load and draw image if exists
        if os.path.exists(image_path):
            loaded_img = QImage(image_path)

            if not loaded_img.isNull():
                # Apply crop_rect if exists (for sprite sheet virtual slicing)
                if frame_data.crop_rect:
                    crop_x, crop_y, crop_w, crop_h = frame_data.crop_rect
                    loaded_img = loaded_img.copy(crop_x, crop_y, crop_w, crop_h)

                # Scale keeping aspect ratio
                scaled_img = loaded_img.scaled(
                    self.thumbnail_width, self.thumbnail_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                # Center the image
                x = (self.thumbnail_width - scaled_img.width()) // 2
                y = (self.thumbnail_height - scaled_img.height()) // 2
                painter.drawImage(x, y, scaled_img)
        else:
            # Draw placeholder text
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "N/A")

        # Draw overlays (only disabled state, frame number is drawn by delegate)
        self.draw_overlays(painter, img.rect(), frame_data, index, draw_frame_number=False)

        painter.end()
        pixmap = QPixmap.fromImage(img)

        # Cache the result
        self._thumbnail_cache[cache_key] = pixmap

        return pixmap
    
    def draw_background(self, painter, rect):
        """Draw background for thumbnail"""
        if self.background_mode == "black":
            painter.fillRect(rect, QColor(0, 0, 0))
        elif self.background_mode == "white":
            painter.fillRect(rect, QColor(255, 255, 255))
        elif self.background_mode == "gray":
            painter.fillRect(rect, QColor(128, 128, 128))
        elif self.background_mode == "green":
            painter.fillRect(rect, QColor(0, 128, 0))
        elif self.background_mode == "checkerboard":
            checker_size = 8
            for y in range(0, rect.height(), checker_size):
                for x in range(0, rect.width(), checker_size):
                    if ((x // checker_size) + (y // checker_size)) % 2 == 0:
                        painter.fillRect(x, y, checker_size, checker_size, QColor(200, 200, 200))
                    else:
                        painter.fillRect(x, y, checker_size, checker_size, QColor(240, 240, 240))
        elif self.background_mode == "transparent":
            # Don't draw any background - keep it truly transparent
            pass
    
    def draw_overlays(self, painter, rect, frame_data, index, draw_frame_number=False):
        """Draw overlay information on thumbnail"""
        # Draw disabled overlay
        if frame_data.is_disabled:
            overlay_color = QColor(0, 0, 0, 120)
            painter.fillRect(rect, overlay_color)

        # Draw frame number (optional - frame numbers are now drawn by delegate by default)
        # This parameter is kept for compatibility and can be enabled if needed
        if draw_frame_number:
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))

            # Add semi-transparent background for text readability
            text_bg_rect = QRectF(rect.width() - 30, rect.height() - 25, 28, 20)
            painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(text_bg_rect, 3, 3)

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(text_bg_rect.toRect(), Qt.AlignmentFlag.AlignCenter, str(index + 1))
    
    def refresh_all_items(self):
        """让所有行重取缩略图与文本（model 的 `data()` 是现算的）。"""
        # Reset log flag for delegate to allow logging first frame info
        delegate = self.itemDelegate()
        if hasattr(delegate, 'reset_log_flag'):
            delegate.reset_log_flag()

        self._notify_rows_changed()

    def _notify_rows_changed(self, start: int = None, end: int = None):
        """通知视图重取指定范围的单元格数据（缩略图、文本、加粗都是现算的）。"""
        item_model = self.model()
        if item_model is None:
            return
        total = item_model.rowCount()
        if total == 0:
            return
        if start is None:
            start, end = 0, total - 1
        if end is None:
            end = start
        end = min(end, total - 1)
        if start > end:
            return
        col = self.modelColumn()
        item_model.dataChanged.emit(
            item_model.index(start, col), item_model.index(end, col), [])

    def refresh_item_numbers(self):
        """Refresh only the item numbers (index) without regenerating thumbnails"""
        # Frame numbers are now drawn by delegate, so we just need to trigger a repaint
        # No need to clear cache or recreate thumbnails
        self.viewport().update()
    
    def on_selection_changed(self):
        if self._selection_blocked:
            return
        self._selection_debounce_timer.start()
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            # Internal drag
            self._is_dragging = True
            event.acceptProposedAction()

    def _calc_insert_before(self, drop_pos, item_center) -> bool:
        """Determine if a drop at drop_pos should insert before the target item.

        In a grid (row-major layout) the Y coordinate only selects which row the
        pointer is over (handled implicitly by `indexAt`). Within that row the
        before/after decision depends solely on the X coordinate: left half of
        the cell => insert before, right half => insert after.
        """
        return drop_pos.x() < item_center.x()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            # Internal drag: calculate and show insert position
            drop_pos = event.position().toPoint()
            drop_index = self.indexAt(drop_pos).row()

            if drop_index >= 0:
                # Calculate if we're dropping before or after the target item
                item_rect = self.visualRect(self.model().index(drop_index, self.modelColumn()))
                item_center = item_rect.center()

                before = self._calc_insert_before(drop_pos, item_center)
                if before:
                    self._drag_insert_position = (drop_index, True)  # Insert before
                else:
                    self._drag_insert_position = (drop_index, False)  # Insert after
            else:
                # Drop at the end
                self._drag_insert_position = (self.get_item_count(), False)

            # Trigger repaint to show insert indicator
            self.viewport().update()
            # Don't call super() - let Qt handle it naturally
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._is_dragging = False
        self._drag_insert_position = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def paintEvent(self, event):
        # Draw the base list widget
        super().paintEvent(event)

        # Draw custom drag insert indicator
        if self._is_dragging and self._drag_insert_position:
            index, before = self._drag_insert_position

            # Calculate which item will have the inserted items before it
            # If before=True, insert before 'index'
            # If before=False, insert after 'index', which means before 'index+1'
            target_index = index if before else index + 1

            # Don't draw blue box if inserting at the end (after last item)
            if target_index < self.get_item_count():
                index = self.model().index(target_index, self.modelColumn())
                if index.isValid():
                    rect = self.visualRect(index)

                    # Draw insertion indicator on viewport
                    painter = QPainter(self.viewport())
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                    # Draw a blue rectangle around the target item
                    indicator_rect = rect.adjusted(-3, -3, 3, 3)

                    # Draw semi-transparent blue border
                    painter.setPen(QPen(QColor(0, 120, 215, 200), 4))
                    painter.drawRect(indicator_rect)

                    painter.end()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            links = []
            for url in event.mimeData().urls():
                links.append(url.toLocalFile())

            # Calculate insertion index
            drop_row = self.indexAt(event.position().toPoint()).row()
            final_index = drop_row + 1 if drop_row >= 0 else -1

            event.accept()
            self.files_dropped.emit(links, final_index)
        else:
            # 内部重排：完全受控，保证原有先后顺序且绝不丢帧
            selected_indices = sorted(getattr(self, '_dragged_rows', None)
                                      or self.get_selected_indices())
            if not selected_indices:
                self._clear_drag_state()
                event.ignore()
                return

            # Use the calculated insert position from dragMoveEvent
            if self._drag_insert_position:
                insert_index, before = self._drag_insert_position
                if not before:
                    insert_index += 1
            else:
                # Fallback: recalculate if position not tracked
                drop_pos = event.position().toPoint()
                drop_index = self.indexAt(drop_pos).row()
                if drop_index >= 0:
                    item_rect = self.visualRect(
                        self.model().index(drop_index, self.modelColumn()))
                    item_center = item_rect.center()
                    if self._calc_insert_before(drop_pos, item_center):
                        insert_index = drop_index
                    else:
                        insert_index = drop_index + 1
                else:
                    insert_index = self.get_item_count()

            # 顺序变更交给模型 —— 视图不再自己 takeItem/insertItem 搬 item。
            # 坐标系转换、原位判据、选中跟随都在 model.move_frames 内部（同列表视图，
            # 见那里的注释：视图自行搬 item 会让顺序有两个源）。
            model = self._get_model()
            if model is None:
                self._clear_drag_state()
                event.ignore()
                return

            # 快照必须在改模型之前捕获（MainWindow 连这个信号做撤销记录）
            self.reorder_about_to_happen.emit()
            if not model.move_frames(selected_indices, insert_index):
                self._clear_drag_state()
                event.ignore()
                return

            event.accept()
            self._clear_drag_state()
            self.order_changed.emit()

    def _clear_drag_state(self):
        """Clear drag state"""
        self._is_dragging = False
        self._drag_insert_position = None
        self._dragged_rows = []
        self.viewport().update()

    def startDrag(self, supportedActions):
        rows = self.get_selected_indices()
        if not rows:
            return
        # 拖拽期间 selectionModel 会被 Qt 改动，行号必须先存下来
        self._dragged_rows = rows
        self._is_dragging = True

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData("application/x-pinframe-internal-reorder", b"reorder")
        drag.setMimeData(mime_data)

        if rows:
            # 拖拽反馈图标：直接问 model 要缩略图，不再经过 item
            frame = self._get_model().get_frame_at(rows[0])
            pixmap = self.thumbnail_for_row(rows[0], frame)
            if pixmap is not None and not pixmap.isNull():
                drag.setPixmap(pixmap)

        # 执行拖拽（关键：不调用 super().startDrag，杜绝 Qt 内部二次删除导致帧消失）
        drag.exec(Qt.DropAction.MoveAction)
        self._clear_drag_state()
    
    def wheelEvent(self, event):
        """Handle mouse wheel for thumbnail size adjustment (with Ctrl key)"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Wheel: Adjust thumbnail size
            delta = event.angleDelta().y()
            if delta > 0:
                # Increase size
                new_width = min(500, self.thumbnail_width + 10)
                new_height = min(500, self.thumbnail_height + 10)
            else:
                # Decrease size
                new_width = max(50, self.thumbnail_width - 10)
                new_height = max(50, self.thumbnail_height - 10)
            
            self.set_thumbnail_size(new_width, new_height)
            event.accept()
        else:
            super().wheelEvent(event)
    
    def set_editors(self, editors):
        """外部图像编辑器列表，用于右键子菜单。"""
        self._editors = editors or []

    def show_context_menu(self, position):
        menu = QMenu()

        selected_count = len(self.get_selected_indices())
        has_selection = selected_count > 0

        copy_action = QAction(i18n.t("action_copy_props"), self)
        copy_action.triggered.connect(self.copy_properties_requested.emit)
        copy_action.setEnabled(has_selection)

        paste_action = QAction(i18n.t("action_paste_props"), self)
        paste_action.triggered.connect(self.paste_properties_requested.emit)

        dup_action = QAction(i18n.t("action_dup_frame"), self)
        dup_action.triggered.connect(self.duplicate_requested.emit)
        dup_action.setEnabled(has_selection)

        dup_dialog_action = QAction(i18n.t("action_dup_frames_dialog"), self)
        dup_dialog_action.triggered.connect(self.duplicate_dialog_requested.emit)
        dup_dialog_action.setEnabled(has_selection)

        rem_action = QAction(i18n.t("action_rem_frame"), self)
        rem_action.triggered.connect(self.remove_requested.emit)
        rem_action.setEnabled(has_selection)

        disable_action = QAction(i18n.t("disable_frame_label", "Disable Frame(s)"), self)
        disable_action.triggered.connect(lambda: self.enable_requested.emit(False))
        disable_action.setEnabled(has_selection)

        enable_action = QAction(i18n.t("enable_frame_label", "Enable Frame(s)"), self)
        enable_action.triggered.connect(lambda: self.enable_requested.emit(True))
        enable_action.setEnabled(has_selection)

        reverse_action = QAction(i18n.t("action_reverse_order"), self)
        reverse_action.triggered.connect(self.reverse_order_requested.emit)
        reverse_action.setEnabled(selected_count > 1)

        int_action = QAction(i18n.t("action_integerize"), self)
        int_action.triggered.connect(self.integerize_offset_requested.emit)
        int_action.setEnabled(has_selection)

        smooth_action = QAction(i18n.t("action_smooth_params"), self)
        smooth_action.triggered.connect(self.smooth_params_requested.emit)
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
        ref_action.triggered.connect(self.set_reference_requested.emit)
        ref_action.setEnabled(selected_count == 1)

        clear_ref_action = QAction(i18n.t("action_clear_reference"), self)
        clear_ref_action.triggered.connect(self.clear_reference_requested.emit)

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
            default_action.triggered.connect(self.edit_default_editor_requested.emit)
            menu.addAction(default_action)
            if self._editors:
                editor_menu = menu.addMenu(i18n.t("menu_edit_external_editor"))
                for ed in self._editors:
                    name = ed.get("name") or os.path.basename(ed.get("path") or "")
                    act = editor_menu.addAction(name)
                    act.triggered.connect(
                        lambda checked=False, ed=ed: self.edit_in_editor_requested.emit(ed))
            else:
                default_action.setEnabled(False)

        menu.exec(self.viewport().mapToGlobal(position))
    
    def refresh_ui_text(self):
        # Grid view doesn't have text labels to refresh
        pass

    def refresh_current_items(self):
        self.refresh_all_items()

    def update_item_display(self, index, frame_data=None):
        """让指定行重取缩略图与文本（model 的 `data()` 是现算的）。

        迁移前这里直接改 item 的 icon/text；现在只需发 `dataChanged`，delegate 会
        重新向 model 取数。缩略图缓存在本视图里、按内容而非位置做 key，因此无需
        在这里显式失效 —— 除非源图真的换了（那时走
        `invalidate_thumbnail_cache_for_paths`）。
        """
        self._notify_rows_changed(index, index)
