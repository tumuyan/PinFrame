from PyQt6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QHeaderView)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont
from i18n.manager import i18n
import os

class TimelineWidget(QTreeWidget):
    selection_changed = pyqtSignal(list) 
    order_changed = pyqtSignal()
    files_dropped = pyqtSignal(list, int) # list of files, insertion index
    copy_properties_requested = pyqtSignal()
    paste_properties_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    disabled_state_changed = pyqtSignal(object, bool) # frame_data, is_disabled
    enable_requested = pyqtSignal(bool) # True for Enable, False for Disable
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHeaderLabels([
            i18n.t("col_disabled"), 
            i18n.t("col_filename"), 
            i18n.t("col_scale"), 
            i18n.t("col_position"), 
            i18n.t("col_res_combined")
        ])
        
        header = self.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(0)
        
        # Column 0: Disable icon
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 24) # Slightly smaller
        
        # Columns 2-4: Fixed/Interactive sizes
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 80)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 100)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(4, 150)
        
        # Column 1: Filename - STRETCH
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        
        # Block internal signals during setup if needed, but here simple connect is fine
        self.itemChanged.connect(self.on_item_changed)
        
        # Enable Context Menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        self.itemSelectionChanged.connect(self.on_selection_changed)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            # Prevent dropping ON item (nesting) for internal moves
            # Only allow Above or Below
            target = self.itemAt(event.position().toPoint())
            if target:
                # Force drop indicator
                # We can't easily force QTreeWidget's internal logic for indicator via just event accept.
                # However, dropping "On" item is usually handled by `dropEvent` logic or `dragMoveEvent` flags.
                # QTreeWidget tries to reparent if you drop on item.
                # We can try to modify the drop action or ignore 'On' pos.
                pass
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            links = []
            for url in event.mimeData().urls():
                links.append(url.toLocalFile())
            
            # Calculate Insertion Index
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
            # Internal Drop
            # We must prevent nesting.
            # Check drop position
            drop_pos = self.dropIndicatorPosition()
            if drop_pos == QAbstractItemView.DropIndicatorPosition.OnItem:
                # If user tries to drop "On" item, redirect to "Below" or "Above"
                # Or just let super handle it but we ensure flatten?
                # QTreeWidget dropEvent "OnItem" makes it a child.
                # We can inhibit this by calling super() but then reparenting back? 
                # Or easier: setRootIsDecorated(False) is already set, but that just hides expanders, doesn't prevent structure.
                # Actually, standard fix for QTreeWidget flat list behavior:
                pass

            super().dropEvent(event)
            
            # Post-Drop cleanup: Ensure no items are children
            root = self.invisibleRootItem()
            # If any top level item has children, move them out.
            # Iterating while modifying is tricky.
            # But simpler: The moved items are now children of 'target'.
            # We can detect this.
            
            # Better approach: 
            # Re-emit order changed and let MainWindow sync?
            # MainWindow syncs based on `files` list from `order_changed` assuming flat list?
            # If QTreeWidget nests them, `topLevelItemCount` decreases.
            # We need to flatten.
            
            # Flatten Logic
            self.flatten_tree()
            self.order_changed.emit()

    def flatten_tree(self):
        root = self.invisibleRootItem()
        top_count = root.childCount()
        items_to_move = [] # list of (item, index_to_insert_at)
        
        # Check all top level items for children
        for i in range(top_count):
            parent = root.child(i)
            if parent.childCount() > 0:
                # Found nested items
                children = parent.takeChildren()
                # We want to insert them after the parent
                items_to_move.append((parent, children))
        
        # Re-insert children at top level
        # Process in reverse to maintain index logic? 
        # Actually easier: Just collect ALL items in generic order and rebuild tree?
        # No, that loses selection state potentially.
        
        for parent, children in items_to_move:
            parent_idx = self.indexOfTopLevelItem(parent)
            # Insert children after parent
            for offset, child in enumerate(children):
                self.insertTopLevelItem(parent_idx + 1 + offset, child)

    def show_context_menu(self, position):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu()
        
        # Actions
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

        # Disable/Enable actions
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
        menu.addAction(dup_action)
        menu.addAction(rem_action)
        
        menu.exec(self.viewport().mapToGlobal(position))

    def on_item_changed(self, item, column):
        if column == 0:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            # Checked means DISABLED
            is_disabled = (item.checkState(0) == Qt.CheckState.Checked)
            if frame_data.is_disabled != is_disabled:
                frame_data.is_disabled = is_disabled
                self.disabled_state_changed.emit(frame_data, is_disabled)


    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0):
        item = QTreeWidgetItem(self)
        item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
        
        # Store original resolution for calculation
        item.setData(3, Qt.ItemDataRole.UserRole, (orig_width, orig_height))
        
        item.setText(0, "") # Just the checkbox
        item.setText(1, filename)
        
        # Checkbox
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        # Checked = Disabled, Unchecked = Enabled
        item.setCheckState(0, Qt.CheckState.Checked if frame_data.is_disabled else Qt.CheckState.Unchecked)
        
        self.update_item_display(item, frame_data, orig_width, orig_height)

    def update_item_display(self, item, frame_data, orig_w, orig_h):
        # Filename
        fname = os.path.basename(frame_data.file_path)
        if frame_data.crop_rect:
            x, y, w, h = frame_data.crop_rect
            # Attempt to calculate col/row. 
            # We need the full resolution of the source image to be accurate if it's not a simple grid,
            # but usually it is. 
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"
        item.setText(1, fname)
        
        # Scale
        item.setText(2, f"{frame_data.scale:.4f}")
        
        # Position
        pos_str = f"({int(frame_data.position[0])}, {int(frame_data.position[1])})"
        item.setText(3, pos_str)
        
        # Orig Res and Calculated Res
        if orig_w > 0:
            final_w = int(orig_w * frame_data.scale)
            final_h = int(orig_h * frame_data.scale)
            res_str = f"{orig_w}x{orig_h} -> {final_w}x{final_h}"
            
            if frame_data.target_resolution:
                tw, th = frame_data.target_resolution
                res_str += f" ({tw}x{th})"
        else:
            res_str = "?x?"
        
        item.setText(4, res_str)

    def refresh_ui_text(self):
        self.setHeaderLabels([
            i18n.t("col_disabled"), 
            i18n.t("col_filename"), 
            i18n.t("col_scale"), 
            i18n.t("col_position"), 
            i18n.t("col_res_combined")
        ])
        self.refresh_current_items()

    def refresh_current_items(self):
        items = self.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive)
        # Actually standard iteration
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            if orig_res:
                w, h = orig_res
                self.update_item_display(item, frame_data, w, h)
            else:
                self.update_item_display(item, frame_data, 0, 0)

    def on_selection_changed(self):
        selected_items = self.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.selection_changed.emit(frames)
