from PyQt6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QHeaderView, QWidget, QVBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QColor, QFont
from i18n.manager import i18n
from model.project_data import TimelineViewMode
import os

class TimelineWidget(QWidget):
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
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()
    set_reference_requested = pyqtSignal()
    clear_reference_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.current_view_mode = TimelineViewMode.LIST
        self.thumbnail_size = 128
        self.is_dark_theme = True
        self.reference_frame_data = None
        
        self.setup_ui()
        self.setup_connections()
        
        self.setMinimumHeight(120)

    def setup_ui(self):
        """设置UI布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 列表视图组件
        self.list_view = QTreeWidget()
        self.setup_list_view()
        
        # 网格视图组件（延迟导入避免循环依赖）
        self.grid_view = None
        
        # 初始显示列表视图
        layout.addWidget(self.list_view)
        
    def setup_list_view(self):
        """设置列表视图"""
        self.list_view.setColumnCount(6)
        self.list_view.setHeaderLabels([
            i18n.t("col_index"),
            i18n.t("col_disabled"), 
            i18n.t("col_filename"), 
            i18n.t("col_scale"), 
            i18n.t("col_position"), 
            i18n.t("col_res_combined")
        ])
        
        header = self.list_view.header()
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
        
        self.list_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.list_view.setAcceptDrops(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_view.setRootIsDecorated(False)
        self.list_view.setUniformRowHeights(True)
        
        # Block internal signals during setup if needed, but here simple connect is fine
        self.list_view.itemChanged.connect(self.on_item_changed)
        
        # Enable Context Menu
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        
        # 防抖定时器：避免快速连续的选择变化触发过多更新
        self._selection_debounce_timer = QTimer(self)
        self._selection_debounce_timer.setSingleShot(True)
        self._selection_debounce_timer.setInterval(50)  # 50ms 防抖延迟
        self._selection_debounce_timer.timeout.connect(self._emit_selection_changed)
        
        # 信号阻塞标志：用于批量操作时阻塞选择信号
        self._selection_blocked = False
        
        self.list_view.itemSelectionChanged.connect(self.on_selection_changed)

    def setup_connections(self):
        """设置信号连接"""
        # 连接列表视图信号
        self.list_view.dropEvent = self.dropEvent
        self.list_view.dragEnterEvent = self.dragEnterEvent
        self.list_view.dragMoveEvent = self.dragMoveEvent

    def get_list_widget(self):
        """获取列表视图组件（用于兼容性）"""
        return self.list_view
        
    def get_grid_widget(self):
        """获取网格视图组件"""
        if self.grid_view is None:
            from ui.grid_timeline import GridTimelineWidget
            self.grid_view = GridTimelineWidget()
            # 连接网格视图信号
            self.grid_view.selection_changed.connect(self._on_grid_selection_changed)
            self.grid_view.copy_properties_requested.connect(self.copy_properties_requested.emit)
            self.grid_view.paste_properties_requested.connect(self.paste_properties_requested.emit)
            self.grid_view.duplicate_requested.connect(self.duplicate_requested.emit)
            self.grid_view.remove_requested.connect(self.remove_requested.emit)
            self.grid_view.disabled_state_changed.connect(self.disabled_state_changed.emit)
            self.grid_view.enable_requested.connect(self.enable_requested.emit)
            self.grid_view.reverse_order_requested.connect(self.reverse_order_requested.emit)
            self.grid_view.integerize_offset_requested.connect(self.integerize_offset_requested.emit)
            self.grid_view.set_reference_requested.connect(self.set_reference_requested.emit)
            self.grid_view.clear_reference_requested.connect(self.clear_reference_requested.emit)
        return self.grid_view

    def switch_view_mode(self, view_mode):
        """切换视图模式"""
        if self.current_view_mode == view_mode:
            return
            
        self.current_view_mode = view_mode
        layout = self.layout()
        
        # 移除当前视图
        if self.current_view_mode == TimelineViewMode.LIST:
            # 切换到列表视图
            if self.grid_view:
                layout.removeWidget(self.grid_view)
                self.grid_view.hide()
            if self.list_view:
                layout.addWidget(self.list_view)
                self.list_view.show()
        else:
            # 切换到网格视图
            layout.removeWidget(self.list_view)
            self.list_view.hide()
            grid_widget = self.get_grid_widget()
            layout.addWidget(grid_widget)
            grid_widget.show()
            
            # 更新网格视图数据
            grid_widget.set_frames(self.frames)
            grid_widget.set_thumbnail_size(self.thumbnail_size)
            grid_widget.set_theme_mode(self.is_dark_theme)
            if self.reference_frame_data:
                grid_widget.set_reference_frame(self.reference_frame_data)

    def set_view_mode(self, view_mode):
        """设置视图模式（别名方法）"""
        self.switch_view_mode(view_mode)
        
    def set_thumbnail_size(self, size):
        """设置缩略图尺寸"""
        self.thumbnail_size = size
        if self.grid_view:
            self.grid_view.set_thumbnail_size(size)

    def block_selection_signals(self, block: bool):
        """
        阻塞或恢复选择信号
        用于批量选择操作（如全选）时阻止频繁的信号触发
        """
        self._selection_blocked = block
        if not block:
            # 解除阻塞时，立即触发一次选择变化
            self._emit_selection_changed()

    def select_all_optimized(self):
        """
        优化的全选方法：阻塞信号后批量选择，最后只触发一次更新
        """
        self._selection_blocked = True
        if self.current_view_mode == TimelineViewMode.LIST:
            self.list_view.selectAll()
        else:
            if self.grid_view:
                self.grid_view.select_all()
        self._selection_blocked = False
        self._emit_selection_changed()

    def _emit_selection_changed(self):
        """实际发射选择变化信号"""
        if self._selection_blocked:
            return
        selected_frames = self.get_selected_frames()
        self.selection_changed.emit(selected_frames)
        
    def get_selected_frames(self):
        """获取选中的帧"""
        if self.current_view_mode == TimelineViewMode.LIST:
            selected_items = self.list_view.selectedItems()
            frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
            return frames
        else:
            if self.grid_view:
                return self.grid_view.selected_items()
            return []

    def _on_grid_selection_changed(self, selected_frames):
        """网格视图选择变化处理"""
        if self._selection_blocked:
            return
        self.selection_changed.emit(selected_frames)

    def set_theme_mode(self, is_dark):
        self.is_dark_theme = is_dark
        if self.grid_view:
            self.grid_view.set_theme_mode(is_dark)
        self.refresh_visuals()

    def set_visual_reference_frame(self, frame_data):
        self.reference_frame_data = frame_data
        
        if self.current_view_mode == TimelineViewMode.LIST:
            # 列表视图的参考帧处理
            root = self.list_view.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                data = item.data(0, Qt.ItemDataRole.UserRole)
                
                # Simple reference check
                is_ref = (data is frame_data)
                
                # Update visual style (e.g. Background or Font)
                if is_ref:
                    # Set background or font
                    font = item.font(2)
                    font.setBold(True)
                    item.setFont(2, font)
                    
                    # Optimized Colors for Light/Dark themes
                    if hasattr(self, 'is_dark_theme') and not self.is_dark_theme:
                        # Light Theme: Light Green background
                        color = QColor(200, 230, 200)
                        color.setAlpha(255)
                    else:
                        # Dark Theme (Default): Dark Green background
                        color = QColor(30, 80, 40) 
                        color.setAlpha(200)
                    
                    item.setBackground(2, color) 
                    if i18n.t("label_ref_prefix") not in item.text(2):
                        item.setText(2, f"{i18n.t('label_ref_prefix')}{item.text(2)}")
                else:
                    font = item.font(2)
                    font.setBold(False)
                    item.setFont(2, font)
                    item.setBackground(2, QColor(0, 0, 0, 0)) # Transparent
                    item.setText(2, item.text(2).replace(i18n.t("label_ref_prefix"), ""))
        else:
            # 网格视图的参考帧处理
            if self.grid_view:
                self.grid_view.set_reference_frame(frame_data)

    def refresh_visuals(self):
        """Force refresh of visual elements (e.g. after theme change)."""
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
            # Prevent dropping ON item (nesting) for internal moves
            # Only allow Above or Below
            target = self.list_view.itemAt(event.position().toPoint())
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
            item = self.list_view.itemAt(event.position().toPoint())
            drop_pos = self.list_view.dropIndicatorPosition()
            
            if item:
                index = self.list_view.indexOfTopLevelItem(item)
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
            drop_pos = self.list_view.dropIndicatorPosition()
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
            root = self.list_view.invisibleRootItem()
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
        root = self.list_view.invisibleRootItem()
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
            parent_idx = self.list_view.indexOfTopLevelItem(parent)
            # Insert children after parent
            for offset, child in enumerate(children):
                self.list_view.insertTopLevelItem(parent_idx + 1 + offset, child)

    def show_context_menu(self, position):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu()
        
        # Actions
        selected_items = self.list_view.selectedItems()
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
        menu.addAction(reverse_action)
        menu.addSeparator()
        
        # Reference Frame Actions
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
        
        menu.exec(self.list_view.viewport().mapToGlobal(position))

    def on_item_changed(self, item, column):
        if column == 1:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            # Checked means DISABLED
            is_disabled = (item.checkState(1) == Qt.CheckState.Checked)
            if frame_data.is_disabled != is_disabled:
                frame_data.is_disabled = is_disabled
                self.disabled_state_changed.emit(frame_data, is_disabled)

    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0):
        self.frames.append(frame_data)
        
        # 添加到当前视图
        if self.current_view_mode == TimelineViewMode.LIST:
            self._add_frame_to_list_view(filename, frame_data, orig_width, orig_height)
        else:
            # 网格视图会自动从frames列表获取数据
            if self.grid_view:
                self.grid_view.set_frames(self.frames)

    def _add_frame_to_list_view(self, filename, frame_data, orig_width, orig_height):
        """添加帧到列表视图"""
        item = QTreeWidgetItem(self.list_view)
        item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
        
        # Store original resolution for calculation
        item.setData(3, Qt.ItemDataRole.UserRole, (orig_width, orig_height))
        
        item.setText(0, str(self.list_view.topLevelItemCount())) # Initial Index
        item.setText(1, "") # Just the checkbox
        item.setText(2, filename)
        
        # Checkbox
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        # Checked = Disabled, Unchecked = Enabled
        item.setCheckState(1, Qt.CheckState.Checked if frame_data.is_disabled else Qt.CheckState.Unchecked)
        
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
        item.setText(2, fname)
        
        # Scale
        item.setText(3, f"{frame_data.scale:.4f}")
        
        # Position
        pos_str = f"({int(frame_data.position[0])}, {int(frame_data.position[1])})"
        item.setText(4, pos_str)
        
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
        
        item.setText(5, res_str)

    def refresh_ui_text(self):
        if self.current_view_mode == TimelineViewMode.LIST:
            self.list_view.setHeaderLabels([
                i18n.t("col_index"),
                i18n.t("col_disabled"), 
                i18n.t("col_filename"), 
                i18n.t("col_scale"), 
                i18n.t("col_position"), 
                i18n.t("col_res_combined")
            ])
        self.refresh_current_items()

    def refresh_current_items(self):
        # Actually standard iteration
        if self.current_view_mode == TimelineViewMode.LIST:
            root = self.list_view.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                item.setText(0, str(i + 1)) # Update index
                frame_data = item.data(0, Qt.ItemDataRole.UserRole)
                orig_res = item.data(3, Qt.ItemDataRole.UserRole)
                if orig_res:
                    w, h = orig_res
                    self.update_item_display(item, frame_data, w, h)
                else:
                    self.update_item_display(item, frame_data, 0, 0)

    def on_selection_changed(self):
        """选择变化时启动防抖定时器，避免频繁触发"""
        if self._selection_blocked:
            return
        # 重启防抖定时器
        self._selection_debounce_timer.start()

    def clear_all_frames(self):
        """清除所有帧"""
        self.frames.clear()
        if self.current_view_mode == TimelineViewMode.LIST:
            self.list_view.clear()
        else:
            if self.grid_view:
                self.grid_view.set_frames(self.frames)

    def clear(self):
        """向后兼容方法 - 清除所有帧"""
        self.clear_all_frames()

    def remove_frame_at_index(self, index):
        """移除指定索引的帧"""
        if 0 <= index < len(self.frames):
            self.frames.pop(index)
            if self.current_view_mode == TimelineViewMode.LIST:
                # 从列表视图中移除
                if index < self.list_view.topLevelItemCount():
                    item = self.list_view.takeTopLevelItem(index)
                    if item:
                        item.setParent(None)
            else:
                if self.grid_view:
                    self.grid_view.set_frames(self.frames)
            self.refresh_current_items()

    def topLevelItemCount(self):
        """向后兼容方法 - 获取顶级项目数量"""
        if self.current_view_mode == TimelineViewMode.LIST:
            return self.list_view.topLevelItemCount()
        else:
            return len(self.frames)

    def topLevelItem(self, index):
        """向后兼容方法 - 获取指定索引的顶级项目"""
        if self.current_view_mode == TimelineViewMode.LIST:
            return self.list_view.topLevelItem(index)
        else:
            # 网格模式下，返回一个虚拟项目以保持兼容性
            if 0 <= index < len(self.frames):
                # 创建一个虚拟的QTreeWidgetItem用于兼容性
                item = QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, self.frames[index])
                return item
            return None

    def setCurrentItem(self, item):
        """向后兼容方法 - 设置当前项目"""
        if self.current_view_mode == TimelineViewMode.LIST:
            self.list_view.setCurrentItem(item)
        # 网格模式下暂时不实现选择保持

    def move_frame(self, from_index, to_index):
        """移动帧的位置"""
        if (0 <= from_index < len(self.frames) and 
            0 <= to_index < len(self.frames) and 
            from_index != to_index):
            frame = self.frames.pop(from_index)
            self.frames.insert(to_index, frame)
            
            if self.current_view_mode == TimelineViewMode.LIST:
                # 在列表视图中移动
                item = self.list_view.takeTopLevelItem(from_index)
                if item:
                    self.list_view.insertTopLevelItem(to_index, item)
            else:
                if self.grid_view:
                    self.grid_view.set_frames(self.frames)
                    
            self.refresh_current_items()
            self.order_changed.emit()