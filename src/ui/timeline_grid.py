from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QPoint, QRectF
from PyQt6.QtGui import QColor, QImage, QPixmap, QPainter, QBrush, QPen, QFont, QIcon, QAction
from i18n.manager import i18n
from ui.timeline_base_view import BaseTimelineView
from model.project_data import FrameData
from typing import List, Optional
import os

class TimelineGridWidget(QListWidget, BaseTimelineView):
    """Grid view for timeline with thumbnail display"""

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
        
        # View mode settings
        self.thumbnail_width = 120
        self.thumbnail_height = 120
        self.show_multiline = False
        self.background_mode = "checkerboard"  # black, white, gray, checkerboard, green
        
        # Widget settings
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)  # Enable internal move for drag&drop
        self.setDropIndicatorShown(True)  # Show drop indicator during drag
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        self.itemSelectionChanged.connect(self.on_selection_changed)

        self.reference_frame_data = None
        self.is_dark_theme = True

        # Drag position tracking
        self._drag_insert_position = None  # (index, before) - where before is True if inserting before the item
        self._is_dragging = False

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
        self.update_item_size()
        self.refresh_all_items()
    
    def set_background_mode(self, mode):
        """Set background mode for thumbnails"""
        self.background_mode = mode
        self.refresh_all_items()
    
    def update_item_size(self):
        """Update grid item size based on thumbnail dimensions"""
        label_height = 40 if self.show_multiline else 20
        item_width = self.thumbnail_width + 8
        item_height = self.thumbnail_height + label_height + 8
        self.setIconSize(QSize(self.thumbnail_width, self.thumbnail_height))
        self.setGridSize(QSize(item_width, item_height))
    
    def set_theme_mode(self, is_dark):
        self.is_dark_theme = is_dark
        self.refresh_all_items()
    
    def set_visual_reference_frame(self, frame_data):
        self.reference_frame_data = frame_data
        self.refresh_all_items()
    
    def refresh_visuals(self):
        if self.reference_frame_data:
            self.set_visual_reference_frame(self.reference_frame_data)
    
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

    # BaseTimelineView abstract methods implementation
    def get_selected_indices(self) -> List[int]:
        """Get indices of selected items"""
        selected_items = self.selectedItems()
        return [self.row(item) for item in selected_items]

    def get_selected_items(self):
        """Get selected items"""
        return self.selectedItems()

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """Get frame data at specified index"""
        if 0 <= index < self.count():
            item = self.item(index)
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def add_frame_to_view(self, filename: str, frame_data: FrameData, index: int):
        """Add a frame to the view at specified index"""
        self.add_frame(filename, frame_data, index)

    def remove_frame_from_view(self, index: int):
        """Remove frame from view at specified index"""
        if 0 <= index < self.count():
            self.takeItem(index)

    def update_frame_in_view(self, index: int, frame_data: FrameData, filename: str):
        """Update frame in view at specified index"""
        self.update_frame(index, frame_data, filename)

    def refresh_view(self):
        """Refresh the entire view"""
        self.refresh_all_items()

    def clear_view(self):
        """Clear all items from view"""
        self.clear()

    def get_item_count(self) -> int:
        """Get total number of items in view"""
        return self.count()

    def _emit_selection_changed(self):
        if self._selection_blocked:
            return

        selected_items = self.selectedItems()
        frames = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        self.selection_changed.emit(frames)
    
    def create_thumbnail(self, image_path, frame_data, index):
        """Create thumbnail with overlay information"""
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

        # Draw overlays
        self.draw_overlays(painter, img.rect(), frame_data, index)

        painter.end()
        return QPixmap.fromImage(img)
    
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
    
    def draw_overlays(self, painter, rect, frame_data, index):
        """Draw overlay information on thumbnail"""
        # Draw disabled overlay
        if frame_data.is_disabled:
            overlay_color = QColor(0, 0, 0, 120)
            painter.fillRect(rect, overlay_color)

            # Draw disabled icon/text
            painter.setPen(QColor(255, 100, 100))
            painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "🚫")

        # Draw frame number
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))

        # Add semi-transparent background for text readability
        text_bg_rect = QRectF(rect.width() - 30, rect.height() - 25, 28, 20)
        painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(text_bg_rect, 3, 3)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(text_bg_rect.toRect(), Qt.AlignmentFlag.AlignCenter, str(index + 1))
    
    def add_frame(self, filename, frame_data, index):
        """Add a frame to the grid"""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, frame_data)
        
        # Create thumbnail
        thumbnail = self.create_thumbnail(frame_data.file_path, frame_data, index)
        item.setIcon(QIcon(thumbnail))
        
        # Set tooltip and display text
        fname = os.path.basename(filename)
        if frame_data.crop_rect:
            x, y, w, h = frame_data.crop_rect
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"
        
        item.setText(fname)
        item.setToolTip(fname)
        
        # Reference frame highlighting
        is_ref = (frame_data is self.reference_frame_data)
        if is_ref:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        
        self.addItem(item)
    
    def update_frame(self, index, frame_data, filename):
        """Update frame at index"""
        if index < 0 or index >= self.count():
            return

        item = self.item(index)
        item.setData(Qt.ItemDataRole.UserRole, frame_data)

        # Recreate thumbnail
        thumbnail = self.create_thumbnail(frame_data.file_path, frame_data, index)
        item.setIcon(QIcon(thumbnail))

        # Update text
        fname = os.path.basename(filename)
        if frame_data.crop_rect:
            x, y, w, h = frame_data.crop_rect
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"

        item.setText(fname)
        item.setToolTip(fname)
    
    def refresh_all_items(self):
        """Refresh all items (thumbnails and text)"""
        for i in range(self.count()):
            item = self.item(i)
            frame_data = item.data(Qt.ItemDataRole.UserRole)

            # Recreate thumbnail
            thumbnail = self.create_thumbnail(frame_data.file_path, frame_data, i)
            item.setIcon(QIcon(thumbnail))

            # Update reference highlighting
            is_ref = (frame_data is self.reference_frame_data)
            font = item.font()
            font.setBold(is_ref)
            item.setFont(font)

    def refresh_item_numbers(self):
        """Refresh only the item numbers (index) without regenerating thumbnails"""
        for i in range(self.count()):
            item = self.item(i)
            frame_data = item.data(Qt.ItemDataRole.UserRole)

            # Recreate thumbnail with updated index
            thumbnail = self.create_thumbnail(frame_data.file_path, frame_data, i)
            item.setIcon(QIcon(thumbnail))
    
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

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            # Internal drag: calculate and show insert position
            drop_pos = event.position().toPoint()
            drop_item = self.itemAt(drop_pos)

            if drop_item:
                drop_index = self.row(drop_item)
                # Calculate if we're dropping before or after the target item
                item_rect = self.visualItemRect(drop_item)
                item_center = item_rect.center()

                # Determine if drop is before or after based on position
                if drop_pos.x() < item_center.x() and drop_pos.y() < item_center.y():
                    self._drag_insert_position = (drop_index, True)  # Insert before
                else:
                    self._drag_insert_position = (drop_index, False)  # Insert after
            else:
                # Drop at the end
                self._drag_insert_position = (self.count(), False)

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
            if target_index < self.count():
                item = self.item(target_index)
                if item:
                    rect = self.visualItemRect(item)

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
            item = self.itemAt(event.position().toPoint())
            if item:
                final_index = self.row(item) + 1
            else:
                final_index = -1

            event.accept()
            self.files_dropped.emit(links, final_index)
        else:
            # Internal drag: manually handle reordering for IconMode
            # Get selected items (being dragged)
            selected_items = self.selectedItems()

            if not selected_items:
                super().dropEvent(event)
                self._clear_drag_state()
                return

            # Use the calculated insert position from dragMoveEvent
            if self._drag_insert_position:
                insert_index, before = self._drag_insert_position
                if not before:
                    insert_index += 1
            else:
                # Fallback: recalculate if position not tracked
                drop_pos = event.position().toPoint()
                drop_item = self.itemAt(drop_pos)
                if drop_item:
                    drop_index = self.row(drop_item)
                    item_rect = self.visualItemRect(drop_item)
                    item_center = item_rect.center()
                    if drop_pos.x() < item_center.x() or drop_pos.y() < item_center.y():
                        insert_index = drop_index
                    else:
                        insert_index = drop_index + 1
                else:
                    insert_index = self.count()

            # Get selected indices before any modifications
            selected_indices = sorted([self.row(item) for item in selected_items])

            # Don't process if drop position is the same
            if insert_index == selected_indices[0]:
                self._clear_drag_state()
                event.ignore()
                return

            # Collect the dragged items' data
            dragged_items_data = []
            for item in selected_items:
                dragged_items_data.append({
                    'data': item.data(Qt.ItemDataRole.UserRole),
                    'text': item.text(),
                    'icon': item.icon(),
                    'tooltip': item.toolTip(),
                    'font': item.font(),
                    'selected': item.isSelected()
                })

            # Remove items from current positions (in reverse order to maintain indices)
            for item in reversed(selected_items):
                self.takeItem(self.row(item))

            # Calculate adjusted insert index after removal
            # If dragged items were before the insert position, their removal shifts the insert index
            dragged_before_count = sum(1 for idx in selected_indices if idx < insert_index)
            adjusted_insert_index = insert_index - dragged_before_count

            # Insert items at new position
            for i, item_data in enumerate(dragged_items_data):
                new_item = QListWidgetItem(item_data['text'])
                new_item.setData(Qt.ItemDataRole.UserRole, item_data['data'])
                new_item.setIcon(item_data['icon'])
                new_item.setToolTip(item_data['tooltip'])
                new_item.setFont(item_data['font'])
                new_item.setSelected(item_data['selected'])
                self.insertItem(adjusted_insert_index + i, new_item)

            event.accept()

            # Clear drag state
            self._clear_drag_state()

            # Update item numbers after drag is complete
            self.refresh_item_numbers()
            self.order_changed.emit()

    def _clear_drag_state(self):
        """Clear drag state"""
        self._is_dragging = False
        self._drag_insert_position = None
        self.viewport().update()

    def startDrag(self, supportedActions):
        # Override to ensure proper drag behavior
        super().startDrag(supportedActions)
    
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
    
    def refresh_ui_text(self):
        # Grid view doesn't have text labels to refresh
        pass

    def refresh_current_items(self):
        self.refresh_all_items()

    def update_item_display(self, item, frame_data, _orig_w, _orig_h):
        """Update display of a single item (refreshes thumbnail and text)"""
        if item is None:
            return

        index = self.row(item)
        thumbnail = self.create_thumbnail(frame_data.file_path, frame_data, index)
        item.setIcon(QIcon(thumbnail))

        fname = os.path.basename(frame_data.file_path)
        if frame_data.crop_rect:
            x, y, w, h = frame_data.crop_rect
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"

        item.setText(fname)
        item.setToolTip(fname)
