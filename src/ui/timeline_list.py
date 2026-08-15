from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QAbstractItemView, QHeaderView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QItemSelectionModel, QModelIndex, QMimeData
from PyQt6.QtGui import QColor, QAction, QDrag, QPixmap
from i18n.manager import i18n
from ui.timeline_base_view import BaseTimelineView
from model.project_data import FrameData
from typing import List, Optional
import os

# Debug flag - set to False to disable debug output
DEBUG_LIST_VIEW = False


class TimelineListView(QTreeWidget, BaseTimelineView):
    """List view for timeline (original implementation)"""

    selection_changed = pyqtSignal(list)
    order_changed = pyqtSignal()
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

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setColumnCount(6)
        self.setHeaderLabels([
            i18n.t("col_index"),
            i18n.t("col_disabled"),
            i18n.t("col_filename"),
            i18n.t("col_scale"),
            i18n.t("col_position"),
            i18n.t("col_res_combined")
        ])

        header = self.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(0)

        # Column 0: Index
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 40)

        # Column 1: Disable icon
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 24)

        # Columns 3-5: Fixed/Interactive sizes
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 80)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(4, 100)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(5, 150)

        # Column 2: Filename - STRETCH
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)

        self.itemChanged.connect(self.on_item_changed)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self._selection_debounce_timer = QTimer(self)
        self._selection_debounce_timer.setSingleShot(True)
        self._selection_debounce_timer.setInterval(50)
        self._selection_debounce_timer.timeout.connect(self._emit_selection_changed)

        self._selection_blocked = False

        self.itemSelectionChanged.connect(self.on_selection_changed)

        self.reference_frame_data = None
        self.is_dark_theme = True
        self.setMinimumHeight(120)

    # BaseTimelineView abstract methods implementation
    def get_selected_indices(self) -> List[int]:
        """Get indices of selected items"""
        selected_items = self.selectedItems()
        return [self.indexOfTopLevelItem(item) for item in selected_items]

    def get_selected_items(self):
        """Get selected items"""
        return self.selectedItems()

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """Get frame data at specified index"""
        if 0 <= index < self.topLevelItemCount():
            item = self.topLevelItem(index)
            return item.data(0, Qt.ItemDataRole.UserRole)
        return None

    def add_frame_to_view(self, filename: str, frame_data: FrameData, index: int):
        """Add a frame to view at specified index"""
        self.add_frame(filename, frame_data, index=index)

    def remove_frame_from_view(self, index: int):
        """Remove frame from view at specified index"""
        if 0 <= index < self.topLevelItemCount():
            self.takeTopLevelItem(index)

    def update_frame_in_view(self, index: int, frame_data: FrameData, filename: str):
        """Update frame in view at specified index"""
        if 0 <= index < self.topLevelItemCount():
            item = self.topLevelItem(index)
            # Get original resolution from data
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.update_item_display(item, frame_data, w, h)

    def refresh_view(self):
        """Refresh the entire view"""
        self.refresh_current_items()

    def clear_view(self):
        """Clear all items from view"""
        self.clear()

    def get_item_count(self) -> int:
        """Get total number of items in view"""
        return self.topLevelItemCount()

    def block_selection_signals(self, block: bool):
        """Block or unblock selection change signals (auto-emit on unblock)"""
        self._selection_blocked = block
        if not block:
            self._emit_selection_changed()

    def block_selection_signals_internal(self, block: bool):
        """Block or unblock selection change signals AND Qt's itemSelectionChanged"""
        self._selection_blocked = block
        if block:
            try:
                self.itemSelectionChanged.disconnect(self.on_selection_changed)
            except TypeError:
                # Already disconnected or never connected
                pass
        else:
            self.itemSelectionChanged.connect(self.on_selection_changed)

    def select_all_optimized(self):
        """Select all items efficiently"""
        self._selection_blocked = True
        self.selectAll()
        self._selection_blocked = False
        self._emit_selection_changed()

    def _emit_selection_changed(self):
        """Emit selection changed signal"""
        if self._selection_blocked:
            return

        selected_items = self.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.selection_changed.emit(frames)

    def _apply_selection_from_set(self, selected_indices_set: set):
        """Apply selection from a set of indices (O(n) complexity)"""
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            should_select = i in selected_indices_set
            if item.isSelected() != should_select:
                item.setSelected(should_select)

    def set_theme_mode(self, is_dark: bool):
        """Set theme mode (dark/light)"""
        self.is_dark_theme = is_dark
        self.refresh_visuals()

    def set_visual_reference_frame(self, frame_data: Optional[FrameData]):
        """Set visual reference frame for highlighting"""
        self.reference_frame_data = frame_data

        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)

            is_ref = (data is frame_data)

            if is_ref:
                font = item.font(2)
                font.setBold(True)
                item.setFont(2, font)

                if hasattr(self, 'is_dark_theme') and not self.is_dark_theme:
                    color = QColor(200, 230, 200)
                    color.setAlpha(255)
                else:
                    color = QColor(30, 80, 40)
                    color.setAlpha(200)

                item.setBackground(2, color)
                if i18n.t("label_ref_prefix") not in item.text(2):
                    item.setText(2, f"{i18n.t('label_ref_prefix')}{item.text(2)}")
            else:
                font = item.font(2)
                font.setBold(False)
                item.setFont(2, font)
                item.setBackground(2, QColor(0, 0, 0, 0))
                item.setText(2, item.text(2).replace(i18n.t("label_ref_prefix"), ""))

    def refresh_visuals(self):
        """Refresh visual elements (reference highlighting, etc.)"""
        if self.reference_frame_data:
            self.set_visual_reference_frame(self.reference_frame_data)

    def on_selection_changed(self):
        """Handle selection change"""
        if self._selection_blocked:
            return

        self._selection_debounce_timer.start()

    def startDrag(self, supportedActions):
        selected_items = self.selectedItems()
        if not selected_items:
            return
        # 严格按当前行号升序排列被拖拽的项目，避免受用户选择顺序影响
        sorted_items = sorted(selected_items, key=lambda item: self.indexOfTopLevelItem(item))
        self._dragged_items = sorted_items

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData("application/x-pinframe-internal-reorder", b"reorder")
        drag.setMimeData(mime_data)

        # 简单的拖拽反馈图标
        pixmap = QPixmap(100, 24)
        pixmap.fill(QColor(60, 130, 220, 160))
        drag.setPixmap(pixmap)

        drag.exec(Qt.DropAction.MoveAction)
        self._dragged_items = []

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
            drop_item = self.itemAt(drop_pos)
            if drop_item:
                drop_index = self.indexOfTopLevelItem(drop_item)
                item_rect = self.visualItemRect(drop_item)
                if drop_pos.y() < item_rect.center().y():
                    self._drag_insert_position = (drop_index, True) # before
                else:
                    self._drag_insert_position = (drop_index, False) # after
            else:
                self._drag_insert_position = (self.topLevelItemCount(), False)
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
            item = self.itemAt(event.position().toPoint())
            drop_pos = self.dropIndicatorPosition()

            if item:
                index = self.indexOfTopLevelItem(item)
                if drop_pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
                    final_index = index
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.BelowItem:
                    final_index = index + 1
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.OnItem:
                    final_index = index + 1
                elif drop_pos == QAbstractItemView.DropIndicatorPosition.OnViewport:
                    final_index = -1

            event.accept()
            self.files_dropped.emit(links, final_index)
        elif event.mimeData().hasFormat("application/x-pinframe-internal-reorder"):
            # 内部重排：完全受控，保证原有先后顺序且拖拽后恢复高亮
            dragged_items = getattr(self, '_dragged_items', [])
            if not dragged_items:
                selected_items = self.selectedItems()
                if not selected_items:
                    self._drag_insert_position = None
                    event.ignore()
                    return
                dragged_items = sorted(selected_items, key=lambda item: self.indexOfTopLevelItem(item))

            selected_indices = [self.indexOfTopLevelItem(it) for it in dragged_items if self.indexOfTopLevelItem(it) >= 0]
            if not selected_indices:
                self._drag_insert_position = None
                event.ignore()
                return

            # 计算插入位置
            if getattr(self, '_drag_insert_position', None) is not None:
                index, before = self._drag_insert_position
                insert_index = index if before else index + 1
            else:
                item = self.itemAt(event.position().toPoint())
                drop_pos = self.dropIndicatorPosition()
                if item:
                    index = self.indexOfTopLevelItem(item)
                    if drop_pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
                        insert_index = index
                    else:
                        insert_index = index + 1
                else:
                    insert_index = self.topLevelItemCount()

            # 检查连续块放置在原位的情况
            is_contiguous = (selected_indices[-1] - selected_indices[0] + 1 == len(selected_indices))
            if is_contiguous:
                if insert_index == selected_indices[0] or insert_index == selected_indices[-1] + 1:
                    self._drag_insert_position = None
                    event.ignore()
                    return

            # 按照从前到后收集被拖拽项
            # 在排除被拖拽项后的剩余列表中的插入位置
            dragged_before_count = sum(1 for idx in selected_indices if idx < insert_index)
            remaining_count = self.topLevelItemCount() - len(selected_indices)
            target_pos = max(0, min(remaining_count, insert_index - dragged_before_count))

            # 严格按照行号降序 takeTopLevelItem
            taken_items = []
            for it in reversed(dragged_items):
                r = self.indexOfTopLevelItem(it)
                if r >= 0:
                    taken_items.append(self.takeTopLevelItem(r))
            taken_items.reverse()  # 恢复为升序

            # 在 target_pos 插入
            for i, it in enumerate(taken_items):
                self.insertTopLevelItem(target_pos + i, it)

            event.accept()

            # 恢复选中状态与 currentIndex / anchor
            self.block_selection_signals_internal(True)
            self.clearSelection()
            for it in taken_items:
                it.setSelected(True)
            if taken_items:
                last_item = taken_items[-1]
                last_idx = self.indexOfTopLevelItem(last_item)
                if last_idx >= 0 and self.selectionModel():
                    model_idx = self.model().index(last_idx, 0, QModelIndex())
                    if model_idx.isValid():
                        self.selectionModel().setCurrentIndex(model_idx, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.block_selection_signals_internal(False)

            self._drag_insert_position = None
            self.order_changed.emit()
        else:
            super().dropEvent(event)
            self.flatten_tree()
            self.order_changed.emit()

    def flatten_tree(self):
        root = self.invisibleRootItem()
        top_count = root.childCount()
        items_to_move = []

        for i in range(top_count):
            parent = root.child(i)
            if parent.childCount() > 0:
                children = parent.takeChildren()
                items_to_move.append((parent, children))

        for parent, children in items_to_move:
            parent_idx = self.indexOfTopLevelItem(parent)
            for offset, child in enumerate(children):
                self.insertTopLevelItem(parent_idx + 1 + offset, child)

    def show_context_menu(self, position):
        menu = QMenu()

        selected_items = self.selectedItems()
        has_selection = bool(selected_items)

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
        reverse_action.setEnabled(len(selected_items) > 1)

        int_action = QAction(i18n.t("action_integerize"), self)
        int_action.triggered.connect(self.integerize_offset_requested.emit)
        int_action.setEnabled(has_selection)

        smooth_action = QAction(i18n.t("action_smooth_params"), self)
        smooth_action.triggered.connect(self.smooth_params_requested.emit)
        smooth_action.setEnabled(len(selected_items) > 1)

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
        ref_action.setEnabled(len(selected_items) == 1)

        clear_ref_action = QAction(i18n.t("action_clear_reference"), self)
        clear_ref_action.triggered.connect(self.clear_reference_requested.emit)

        menu.addAction(ref_action)
        menu.addAction(clear_ref_action)
        menu.addSeparator()

        menu.addAction(dup_action)
        menu.addAction(dup_dialog_action)
        menu.addAction(rem_action)

        menu.exec(self.viewport().mapToGlobal(position))

    def on_item_changed(self, item, column):
        if column == 1:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            is_disabled = (item.checkState(1) == Qt.CheckState.Checked)
            if frame_data.is_disabled != is_disabled:
                frame_data.is_disabled = is_disabled
                self.disabled_state_changed.emit(frame_data, is_disabled)

    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0, index=None):
        # If index is specified, create item first, then insert it at position
        if index is not None:
            item = QTreeWidgetItem()
            self.insertTopLevelItem(index, item)
        else:
            item = QTreeWidgetItem(self)

        item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
        item.setData(3, Qt.ItemDataRole.UserRole, (orig_width, orig_height))

        # IMPORTANT: Set checkState BEFORE setting text to avoid triggering itemChanged signal
        # which would incorrectly reset is_disabled to False
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(1, Qt.CheckState.Checked if frame_data.is_disabled else Qt.CheckState.Unchecked)

        # Now set the text
        item.setText(0, str(self.indexOfTopLevelItem(item) + 1))
        item.setText(1, "")
        item.setText(2, filename)

        self.update_item_display(item, frame_data, orig_width, orig_height)

    def update_item_display(self, item, frame_data, orig_w, orig_h):
        fname = os.path.basename(frame_data.file_path)
        if frame_data.crop_rect:
            x, y, w, h = frame_data.crop_rect
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"
        item.setText(2, fname)

        item.setText(3, f"{frame_data.scale:.4f}")

        pos_str = f"({int(frame_data.position[0])}, {int(frame_data.position[1])})"
        item.setText(4, pos_str)

        if orig_w > 0:
            final_w = int(orig_w * frame_data.scale)
            final_h = int(orig_h * frame_data.scale)
            res_str = f"{orig_w}x{orig_h} -> {final_w}x{final_h}"

            if frame_data.target_resolution:
                tw, th = frame_data.target_resolution
                res_str += f" ({tw}x{th})"
        else:
            res_str = "?x?"

        item.setText(5, res_str)

    def refresh_ui_text(self):
        self.setHeaderLabels([
            i18n.t("col_index"),
            i18n.t("col_disabled"),
            i18n.t("col_filename"),
            i18n.t("col_scale"),
            i18n.t("col_position"),
            i18n.t("col_res_combined")
        ])
        self.refresh_current_items()

    def refresh_current_items(self):
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setText(0, str(i + 1))
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            if orig_res:
                w, h = orig_res
                self.update_item_display(item, frame_data, w, h)
            else:
                self.update_item_display(item, frame_data, 0, 0)
