from PyQt6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QHeaderView, QStackedWidget, QWidget)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QColor, QFont
from i18n.manager import i18n
from ui.timeline_grid import TimelineGridWidget
import os

class TimelineWidget(QStackedWidget):
    """Timeline widget that supports both list and grid views"""
    
    selection_changed = pyqtSignal(list) 
    order_changed = pyqtSignal()
    files_dropped = pyqtSignal(list, int)
    copy_properties_requested = pyqtSignal()
    paste_properties_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    disabled_state_changed = pyqtSignal(object, bool)
    enable_requested = pyqtSignal(bool)
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()
    set_reference_requested = pyqtSignal()
    clear_reference_requested = pyqtSignal()
    thumbnail_size_changed = pyqtSignal(int, int)  # width, height
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create list view (tree widget)
        self.list_view = TimelineListView()
        self.list_view.selection_changed.connect(self.selection_changed)
        self.list_view.order_changed.connect(self.order_changed)
        self.list_view.files_dropped.connect(self.files_dropped)
        self.list_view.copy_properties_requested.connect(self.copy_properties_requested)
        self.list_view.paste_properties_requested.connect(self.paste_properties_requested)
        self.list_view.duplicate_requested.connect(self.duplicate_requested)
        self.list_view.remove_requested.connect(self.remove_requested)
        self.list_view.disabled_state_changed.connect(self.disabled_state_changed)
        self.list_view.enable_requested.connect(self.enable_requested)
        self.list_view.reverse_order_requested.connect(self.reverse_order_requested)
        self.list_view.integerize_offset_requested.connect(self.integerize_offset_requested)
        self.list_view.set_reference_requested.connect(self.set_reference_requested)
        self.list_view.clear_reference_requested.connect(self.clear_reference_requested)
        
        # Create grid view
        self.grid_view = TimelineGridWidget()
        self.grid_view.selection_changed.connect(self.selection_changed)
        self.grid_view.order_changed.connect(self.order_changed)
        self.grid_view.files_dropped.connect(self.files_dropped)
        self.grid_view.copy_properties_requested.connect(self.copy_properties_requested)
        self.grid_view.paste_properties_requested.connect(self.paste_properties_requested)
        self.grid_view.duplicate_requested.connect(self.duplicate_requested)
        self.grid_view.remove_requested.connect(self.remove_requested)
        self.grid_view.disabled_state_changed.connect(self.disabled_state_changed)
        self.grid_view.enable_requested.connect(self.enable_requested)
        self.grid_view.reverse_order_requested.connect(self.reverse_order_requested)
        self.grid_view.integerize_offset_requested.connect(self.integerize_offset_requested)
        self.grid_view.set_reference_requested.connect(self.set_reference_requested)
        self.grid_view.clear_reference_requested.connect(self.clear_reference_requested)
        self.grid_view.thumbnail_size_changed.connect(self._on_grid_thumbnail_changed)
        
        # Add both views to stacked widget
        self.addWidget(self.list_view)
        self.addWidget(self.grid_view)
        
        # Default to list view
        self.current_view_mode = "list"  # "list" or "grid"
        
        # Grid settings
        self.grid_thumbnail_width = 120
        self.grid_thumbnail_height = 120
        self.grid_show_multiline = False
        self.grid_background_mode = "checkerboard"
        
        # Apply settings to grid view
        self.grid_view.set_thumbnail_size(self.grid_thumbnail_width, self.grid_thumbnail_height)
        self.grid_view.set_show_multiline(self.grid_show_multiline)
        self.grid_view.set_background_mode(self.grid_background_mode)
    
    def set_view_mode(self, mode):
        """Switch between list and grid view"""
        if mode == "list":
            self.setCurrentWidget(self.list_view)
            self.current_view_mode = "list"
        elif mode == "grid":
            self.setCurrentWidget(self.grid_view)
            self.current_view_mode = "grid"
            # Refresh grid view with current data
            self.refresh_current_items()
    
    def get_view_mode(self):
        """Return current view mode"""
        return self.current_view_mode
    
    def _on_grid_thumbnail_changed(self, width, height):
        """Handle grid thumbnail size change"""
        self.grid_thumbnail_width = width
        self.grid_thumbnail_height = height
        self.thumbnail_size_changed.emit(width, height)
    
    def update_grid_settings(self, width, height, multiline, background):
        """Update grid view settings"""
        self.grid_thumbnail_width = width
        self.grid_thumbnail_height = height
        self.grid_show_multiline = multiline
        self.grid_background_mode = background
        
        self.grid_view.set_thumbnail_size(width, height)
        self.grid_view.set_show_multiline(multiline)
        self.grid_view.set_background_mode(background)
    
    def get_current_widget(self):
        """Get the currently active timeline widget"""
        return self.currentWidget()
    
    # Forward methods to current view
    def block_selection_signals(self, block: bool):
        self.list_view.block_selection_signals(block)
        self.grid_view.block_selection_signals(block)
    
    def select_all_optimized(self):
        self.get_current_widget().select_all_optimized()
    
    def set_theme_mode(self, is_dark):
        self.list_view.set_theme_mode(is_dark)
        self.grid_view.set_theme_mode(is_dark)
    
    def set_visual_reference_frame(self, frame_data):
        self.list_view.set_visual_reference_frame(frame_data)
        self.grid_view.set_visual_reference_frame(frame_data)
    
    def refresh_visuals(self):
        self.list_view.refresh_visuals()
        self.grid_view.refresh_visuals()
    
    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0):
        index = self.list_view.topLevelItemCount()
        self.list_view.add_frame(filename, frame_data, orig_width, orig_height)
        self.grid_view.add_frame(filename, frame_data, index)
    
    def update_item_display(self, item, frame_data, orig_w, orig_h):
        if self.current_view_mode == "list":
            self.list_view.update_item_display(item, frame_data, orig_w, orig_h)
    
    def refresh_ui_text(self):
        self.list_view.refresh_ui_text()
        self.grid_view.refresh_ui_text()
    
    def refresh_current_items(self):
        """Refresh all items in current view"""
        if self.current_view_mode == "list":
            self.list_view.refresh_current_items()
        else:
            # Sync grid view from list view
            self.sync_grid_from_list()
            self.grid_view.refresh_current_items()
    
    def sync_grid_from_list(self):
        """Sync grid view with list view data"""
        root = self.list_view.invisibleRootItem()
        current_count = self.grid_view.count()

        # If grid has different number of items, rebuild it
        if current_count != root.childCount():
            self.grid_view.clear()
            for i in range(root.childCount()):
                item = root.child(i)
                frame_data = item.data(0, Qt.ItemDataRole.UserRole)
                orig_res = item.data(3, Qt.ItemDataRole.UserRole)
                if orig_res:
                    w, h = orig_res
                else:
                    w, h = 0, 0

                # Get filename from frame_data (without crop suffix)
                fname = os.path.basename(frame_data.file_path)

                self.grid_view.add_frame(fname, frame_data, i)
    
    def refresh_all_grid_items(self):
        """Refresh all grid items (thumbnails and text)"""
        self.grid_view.refresh_all_items()
    
    def on_selection_changed(self):
        if self.current_view_mode == "list":
            self.list_view.on_selection_changed()
        else:
            self.grid_view.on_selection_changed()
    
    # Property accessors for compatibility
    @property
    def reference_frame_data(self):
        return self.list_view.reference_frame_data
    
    @property
    def is_dark_theme(self):
        return self.list_view.is_dark_theme
    
    def setMinimumHeight(self, height):
        super().setMinimumHeight(height)
    
    def selectedItems(self):
        """Get selected items from current view"""
        return self.get_current_widget().selectedItems()
    
    def currentItem(self):
        """Get current item from current view"""
        return self.get_current_widget().currentItem()
    
    def setCurrentItem(self, item):
        """Set current item in current view"""
        # Find the corresponding item in the current view by index
        if isinstance(item, QTreeWidgetItem):  # QTreeWidgetItem from list view
            index = self.list_view.indexOfTopLevelItem(item)
            if self.current_view_mode == "list":
                self.list_view.setCurrentItem(item)
            elif index >= 0 and index < self.grid_view.count():
                self.grid_view.setCurrentItem(self.grid_view.item(index))
        elif isinstance(item, QListWidgetItem):  # QListWidgetItem from grid view
            index = self.grid_view.row(item)
            if self.current_view_mode == "grid":
                self.grid_view.setCurrentItem(item)
            elif index >= 0 and index < self.list_view.topLevelItemCount():
                self.list_view.setCurrentItem(self.list_view.topLevelItem(index))
        else:
            # Fallback: try to determine by view mode
            if self.current_view_mode == "list" and self.list_view.topLevelItemCount() > 0:
                self.list_view.setCurrentItem(self.list_view.topLevelItem(0))
            elif self.grid_view.count() > 0:
                self.grid_view.setCurrentItem(self.grid_view.item(0))
    
    def setCurrentIndex(self, index):
        """Set current index in current view"""
        self.get_current_widget().setCurrentIndex(index)
    
    def topLevelItem(self, index):
        """Get top level item from list view"""
        return self.list_view.topLevelItem(index)
    
    def topLevelItemCount(self):
        """Get top level item count from list view"""
        return self.list_view.topLevelItemCount()
    
    def indexOfTopLevelItem(self, item):
        """Get index of top level item from list view"""
        return self.list_view.indexOfTopLevelItem(item)
    
    def takeTopLevelItem(self, index):
        """Take top level item from list view"""
        return self.list_view.takeTopLevelItem(index)
    
    def insertTopLevelItem(self, index, item):
        """Insert top level item into list view"""
        self.list_view.insertTopLevelItem(index, item)
    
    def clear(self):
        """Clear all views"""
        self.list_view.clear()
        self.grid_view.clear()
    
    def count(self):
        """Get item count from current view"""
        return self.get_current_widget().count()


class TimelineListView(QTreeWidget):
    """List view for timeline (original implementation)"""
    
    selection_changed = pyqtSignal(list) 
    order_changed = pyqtSignal()
    files_dropped = pyqtSignal(list, int)
    copy_properties_requested = pyqtSignal()
    paste_properties_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    disabled_state_changed = pyqtSignal(object, bool)
    enable_requested = pyqtSignal(bool)
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()
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

    def block_selection_signals(self, block: bool):
        self._selection_blocked = block
        if not block:
            self._emit_selection_changed()

    def select_all_optimized(self):
        self._selection_blocked = True
        self.selectAll()
        self._selection_blocked = False
        self._emit_selection_changed()

    def _emit_selection_changed(self):
        if self._selection_blocked:
            return
        selected_items = self.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.selection_changed.emit(frames)

    def set_theme_mode(self, is_dark):
        self.is_dark_theme = is_dark
        self.refresh_visuals()

    def set_visual_reference_frame(self, frame_data):
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
        if self.reference_frame_data:
            self.set_visual_reference_frame(self.reference_frame_data)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragMoveEvent(event)

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
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
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

        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.addSeparator()
        menu.addAction(int_action)
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
        menu.addAction(rem_action)
        
        menu.exec(self.viewport().mapToGlobal(position))

    def on_item_changed(self, item, column):
        if column == 1:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            is_disabled = (item.checkState(1) == Qt.CheckState.Checked)
            if frame_data.is_disabled != is_disabled:
                frame_data.is_disabled = is_disabled
                self.disabled_state_changed.emit(frame_data, is_disabled)

    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0):
        item = QTreeWidgetItem(self)
        item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
        
        item.setData(3, Qt.ItemDataRole.UserRole, (orig_width, orig_height))
        
        item.setText(0, str(self.topLevelItemCount()))
        item.setText(1, "")
        item.setText(2, filename)
        
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(1, Qt.CheckState.Checked if frame_data.is_disabled else Qt.CheckState.Unchecked)
        
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

    def on_selection_changed(self):
        if self._selection_blocked:
            return
        self._selection_debounce_timer.start()
