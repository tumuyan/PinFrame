from PyQt6.QtWidgets import QStackedWidget, QListWidgetItem, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from i18n.manager import i18n
from ui.timeline_grid import TimelineGridWidget
from ui.timeline_list import TimelineListView
from ui.timeline_base_view import BaseTimelineView, TimelineViewUtils
from ui.timeline_model import TimelineModel
from model.project_data import FrameData
from typing import List, Optional
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

        # Create data model
        self.model = TimelineModel()

        # Connect model signals to view updates
        self.model.frames_inserted.connect(self._on_frames_inserted)
        self.model.frames_removed.connect(self._on_frames_removed)
        self.model.frames_moved.connect(self._on_frames_moved)
        self.model.data_changed.connect(self._on_data_changed)
        self.model.selection_changed.connect(self._on_model_selection_changed)

        # Create list view (tree widget)
        self.list_view = TimelineListView(self)
        self.list_view.selection_changed.connect(self._on_view_selection_changed)
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
        self.grid_view = TimelineGridWidget(self)
        self.grid_view.selection_changed.connect(self._on_view_selection_changed)
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
            # Sync selection from model to list view
            selected_indices = self.model.get_selected_indices()
            # Block ALL Qt signals first
            self.list_view.blockSignals(True)
            self.grid_view.blockSignals(True)
            self.list_view.block_selection_signals_internal(True)
            self.grid_view.block_selection_signals_internal(True)
            self.list_view.clearSelection()
            for idx in selected_indices:
                if idx < self.list_view.topLevelItemCount():
                    item = self.list_view.topLevelItem(idx)
                    item.setSelected(True)
            self.list_view.blockSignals(False)
            self.grid_view.blockSignals(False)
            self.list_view.block_selection_signals_internal(False)
            self.grid_view.block_selection_signals_internal(False)
        elif mode == "grid":
            self.setCurrentWidget(self.grid_view)
            self.current_view_mode = "grid"
            # Refresh grid view with current data
            self.refresh_current_items()
            # Sync selection from model to grid view
            selected_indices = self.model.get_selected_indices()
            # Block ALL Qt signals first
            self.list_view.blockSignals(True)
            self.grid_view.blockSignals(True)
            self.list_view.block_selection_signals_internal(True)
            self.grid_view.block_selection_signals_internal(True)
            self.grid_view.clearSelection()
            for idx in selected_indices:
                if idx < self.grid_view.count():
                    item = self.grid_view.item(idx)
                    item.setSelected(True)
            self.list_view.blockSignals(False)
            self.grid_view.blockSignals(False)
            self.list_view.block_selection_signals_internal(False)
            self.grid_view.block_selection_signals_internal(False)

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
        """Get currently active timeline widget"""
        return self.currentWidget()

    # ========== Model signal handlers ==========
    def _on_frames_inserted(self, index: int, count: int):
        """Handle frame insertion from model"""
        # Get frame data from model
        for i in range(count):
            frame_data = self.model.get_frame_at(index + i)
            if frame_data:
                # Determine original resolution if available
                orig_w, orig_h = 0, 0
                if hasattr(frame_data, 'target_resolution') and frame_data.target_resolution:
                    orig_w, orig_h = frame_data.target_resolution

                # Add to both views
                filename = os.path.basename(frame_data.file_path)
                self.list_view.add_frame(filename, frame_data, orig_w, orig_h)
                self.grid_view.add_frame(filename, frame_data, index + i)

    def _on_frames_removed(self, index: int, count: int):
        """Handle frame removal from model"""
        # Remove from both views (remove from end first)
        for i in range(count):
            idx_to_remove = index + (count - 1 - i)
            if idx_to_remove < self.list_view.topLevelItemCount():
                self.list_view.takeTopLevelItem(idx_to_remove)
            if idx_to_remove < self.grid_view.count():
                self.grid_view.takeItem(idx_to_remove)

    def _on_frames_moved(self, from_index: int, to_index: int, count: int):
        """Handle frame movement from model"""
        # Rebuild both views
        # This is simpler than moving individual items
        total_frames = self.model.get_frame_count()

        # Rebuild list view
        self.list_view.clear()
        for i in range(total_frames):
            frame_data = self.model.get_frame_at(i)
            if frame_data:
                orig_w, orig_h = 0, 0
                if hasattr(frame_data, 'target_resolution') and frame_data.target_resolution:
                    orig_w, orig_h = frame_data.target_resolution
                filename = os.path.basename(frame_data.file_path)
                self.list_view.add_frame(filename, frame_data, orig_w, orig_h)

        # Rebuild grid view
        self.grid_view.clear()
        for i in range(total_frames):
            frame_data = self.model.get_frame_at(i)
            if frame_data:
                filename = os.path.basename(frame_data.file_path)
                self.grid_view.add_frame(filename, frame_data, i)

    def _on_data_changed(self, start_index: int, end_index: int):
        """Handle frame data change from model"""
        # Get selection before update
        selection_before = self.model.get_selected_indices()

        # Only update the currently active view
        if self.current_view_mode == "list":
            # Block ALL Qt signals to prevent itemSelectionChanged
            self.list_view.blockSignals(True)
            self.grid_view.blockSignals(True)

            for idx in range(start_index, end_index + 1):
                frame_data = self.model.get_frame_at(idx)
                if frame_data:
                    orig_w, orig_h = 0, 0
                    if hasattr(frame_data, 'target_resolution') and frame_data.target_resolution:
                        orig_w, orig_h = frame_data.target_resolution
                    filename = os.path.basename(frame_data.file_path)

                    # Update list view only
                    if idx < self.list_view.topLevelItemCount():
                        item = self.list_view.topLevelItem(idx)
                        self.list_view.update_item_display(item, frame_data, orig_w, orig_h)

            self.list_view.blockSignals(False)
            self.grid_view.blockSignals(False)
        else:
            # Grid mode - only update grid view
            # Block ALL Qt signals to prevent itemSelectionChanged
            self.list_view.blockSignals(True)
            self.grid_view.blockSignals(True)

            for idx in range(start_index, end_index + 1):
                frame_data = self.model.get_frame_at(idx)
                if frame_data:
                    filename = os.path.basename(frame_data.file_path)

                    # Update grid view only
                    if idx < self.grid_view.count():
                        self.grid_view.update_frame(idx, frame_data, filename)

            self.list_view.blockSignals(False)
            self.grid_view.blockSignals(False)

        # Check selection after update
        selection_after = self.model.get_selected_indices()

        if selection_before != selection_after:
            print(f"WARNING: Selection changed during update! Before: {selection_before}, After: {selection_after}")

    def _on_model_selection_changed(self):
        """Handle selection change from model"""
        # Get selected indices from model
        selected_indices = self.model.get_selected_indices()

        # Block signals and stop timers before updating
        if self.current_view_mode == "list":
            self.list_view._selection_debounce_timer.stop()
            self.list_view.blockSignals(True)
        else:
            self.grid_view._selection_debounce_timer.stop()
            self.grid_view.blockSignals(True)

        # Only update the currently active view
        if self.current_view_mode == "list":
            # Update list view only
            for idx in range(self.list_view.topLevelItemCount()):
                item = self.list_view.topLevelItem(idx)
                should_select = idx in selected_indices
                if item.isSelected() != should_select:
                    item.setSelected(should_select)
            self.list_view.blockSignals(False)
        else:
            # Grid mode - only update grid view
            for idx in range(self.grid_view.count()):
                item = self.grid_view.item(idx)
                should_select = idx in selected_indices
                if item.isSelected() != should_select:
                    item.setSelected(should_select)
            self.grid_view.blockSignals(False)

    # ========== Model access methods ==========
    def add_frame(self, filename: str, frame_data: FrameData, orig_width=0, orig_height=0):
        """Add frame through model"""
        self.model.add_frame(frame_data)

    def get_frame_at(self, index: int) -> Optional[FrameData]:
        """Get frame data from model"""
        return self.model.get_frame_at(index)

    def get_frame_count(self) -> int:
        """Get total frame count from model"""
        return self.model.get_frame_count()

    def get_all_frames(self) -> List[FrameData]:
        """Get all frames from model"""
        return self.model.get_all_frames()

    def remove_frame_at(self, index: int):
        """Remove frame at index through model"""
        self.model.remove_frame_at(index)

    def remove_frames_at(self, indices: List[int]):
        """Remove multiple frames at indices through model"""
        self.model.remove_frames_at(indices)

    def move_frame(self, from_index: int, to_index: int):
        """Move frame through model"""
        self.model.move_frame(from_index, to_index)

    def update_frame_data(self, index: int):
        """Notify model that frame data changed"""
        self.model.update_frame_data(index)

    def clear(self):
        """Clear all data"""
        self.model.clear()
        self.list_view.clear()
        self.grid_view.clear()

    def set_reference_frame(self, frame_data: Optional[FrameData]):
        """Set reference frame through model"""
        self.model.set_reference_frame(frame_data)

    def clear_reference_frame(self):
        """Clear reference frame through model"""
        self.model.clear_reference_frame()

    def get_reference_frame(self) -> Optional[FrameData]:
        """Get reference frame from model"""
        return self.model.get_reference_frame()

    def load_frames(self, frames: List[FrameData]):
        """Load frames into model and views"""
        self.model.clear()
        for frame_data in frames:
            orig_w, orig_h = 0, 0
            if hasattr(frame_data, 'target_resolution') and frame_data.target_resolution:
                orig_w, orig_h = frame_data.target_resolution
            filename = os.path.basename(frame_data.file_path)
            self.model.add_frame(frame_data)

    # ========== Unified interface methods (using model) ==========
    def get_selected_indices_from_current_view(self) -> List[int]:
        """Get selected indices from model"""
        return self.model.get_selected_indices()

    def get_selected_frames(self) -> List[FrameData]:
        """Get selected frame data from model"""
        return self.model.get_selected_frames()

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """Get frame data from model"""
        return self.model.get_frame_at(index)

    def extract_frame_data_from_item(self, item):
        """Extract frame data from an item (works for both QTreeWidgetItem and QListWidgetItem)"""
        return TimelineViewUtils.extract_frame_data_from_item(item)

    def add_frame_to_current_view(self, filename: str, frame_data, index: int):
        """Add frame to current view"""
        current = self.get_current_widget()
        if hasattr(current, 'add_frame_to_view'):
            current.add_frame_to_view(filename, frame_data, index)

    def remove_frame_from_current_view(self, index: int):
        """Remove frame from current view"""
        current = self.get_current_widget()
        if hasattr(current, 'remove_frame_from_view'):
            current.remove_frame_from_view(index)

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

    def update_item_display(self, item, frame_data, orig_w, orig_h):
        """Update display of a single item in current view"""
        if self.current_view_mode == "list":
            self.list_view.update_item_display(item, frame_data, orig_w, orig_h)
        else:
            self.grid_view.update_item_display(item, frame_data, orig_w, orig_h)

    def refresh_ui_text(self):
        self.list_view.refresh_ui_text()
        self.grid_view.refresh_ui_text()

    def refresh_current_items(self):
        """Refresh all items in current view"""
        if self.current_view_mode == "list":
            self.list_view.refresh_current_items()
        else:
            # Rebuild grid view from model
            self._rebuild_grid_view()

    def _rebuild_grid_view(self):
        """Rebuild grid view from model"""
        # Store selection before clearing
        selected_indices = self.model.get_selected_indices()

        self.grid_view.clear()
        total_frames = self.model.get_frame_count()

        for i in range(total_frames):
            frame_data = self.model.get_frame_at(i)
            if frame_data:
                filename = os.path.basename(frame_data.file_path)
                self.grid_view.add_frame(filename, frame_data, i)

        # Restore selection after rebuild (block signals to avoid triggering model update)
        if selected_indices:
            self.grid_view.blockSignals(True)
            self.grid_view.block_selection_signals_internal(True)
            for idx in selected_indices:
                if idx < self.grid_view.count():
                    item = self.grid_view.item(idx)
                    item.setSelected(True)
            self.grid_view.blockSignals(False)
            self.grid_view.block_selection_signals_internal(False)

    def refresh_all_grid_items(self):
        """Refresh all grid items (thumbnails and text)"""
        self.grid_view.refresh_all_items()

    def on_selection_changed(self):
        """Clear update flags after a delay to allow Qt to process pending events"""
        # Stop all timers one more time before unblocking
        self.list_view._selection_debounce_timer.stop()
        self.grid_view._selection_debounce_timer.stop()

        # Reset update count
        self._model_update_count = 0

        # Unblock signals FIRST, before clearing flags
        # This way, any selection changes triggered by unblocking will be caught by flags
        QTimer.singleShot(10, self._unblock_signals_while_flags_still_set)

    def _unblock_signals_while_flags_still_set(self):
        """Unblock signals while flags are still set to catch any immediate selection changes"""
        if self.current_view_mode == "list":
            if self.list_view.signalsBlocked():
                self.list_view.blockSignals(False)
        else:
            if self.grid_view.signalsBlocked():
                self.grid_view.blockSignals(False)

        # Now clear flags after a longer delay to ensure Qt has processed everything
        # 200ms delay gives Qt enough time to process all pending events
        QTimer.singleShot(200, self._clear_flags_after_unblock)

    def _clear_flags_after_unblock(self):
        """Clear flags a short time after unblocking signals"""
        # Store the expected selection before clearing flags
        expected_selection = self.model.get_selected_indices()

        # Clear flags
        self._updating_view_from_model = False
        self._view_update_in_progress = False

        # Schedule a check to restore selection if it was changed by Qt
        QTimer.singleShot(50, lambda: self._restore_selection_if_needed(expected_selection))

    def _restore_selection_if_needed(self, expected_selection):
        """Restore model selection if it was changed by Qt after unblock"""
        # Check if selection was changed by Qt after unblock
        current_selection = self.model.get_selected_indices()
        if current_selection != expected_selection:
            print(f"WARNING: Selection was changed by Qt after unblock: {expected_selection} -> {current_selection}, restoring...")
            # Restore the expected selection without triggering another model update
            self.model._selected_indices = expected_selection

    def _on_view_selection_changed(self, frames):
        """Handle selection change from views and update model"""
        # Check if selection actually changed to avoid unnecessary updates
        current_indices = self.model.get_selected_indices()
        new_indices = []
        if self.current_view_mode == "list":
            new_indices = self.list_view.get_selected_indices()
        else:
            new_indices = self.grid_view.get_selected_indices()

        if current_indices == new_indices:
            return  # No change, skip update

        self.model.set_selection(new_indices)

    def on_selection_changed(self):
        """Handle selection change from views and update model"""
        # This method is now called directly from _on_view_selection_changed
        # or can be called from other places if needed
        pass

    # ========== Property accessors for compatibility ==========
    @property
    def reference_frame_data(self):
        """Get reference frame from model"""
        return self.model.get_reference_frame()

    @reference_frame_data.setter
    def reference_frame_data(self, frame_data):
        """Set reference frame in model"""
        self.model.set_reference_frame(frame_data)

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
        """Remove frame at index using model"""
        self.model.remove_frame_at(index)

    def insertTopLevelItem(self, index, item):
        """This method is deprecated - use model.add_frame instead"""
        # Extract frame data from item and add to model
        frame_data = self.list_view._extract_frame_data_from_item(item)
        if frame_data:
            self.model.add_frame(frame_data, index)

    def count(self):
        """Get item count from model"""
        return self.model.get_frame_count()

    # Compatibility wrapper - delegates to views directly
    def _get_view_method(self, method_name, *args, **kwargs):
        """Helper to call methods on current view"""
        current = self.get_current_widget()
        if hasattr(current, method_name):
            method = getattr(current, method_name)
            return method(*args, **kwargs)
        return None
