from PyQt6.QtWidgets import QStackedWidget
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QItemSelectionModel, QModelIndex
from i18n.manager import i18n
from ui.timeline_grid import TimelineGridWidget
from ui.timeline_list import TimelineListView
from ui.timeline_model import TimelineModel
from ui.timeline_item_model import TimelineItemModel
from model.project_data import FrameData
from utils.debug_config import timeline_debug
from typing import List, Optional
import os

class TimelineWidget(QStackedWidget):
    """Timeline widget that supports both list and grid views"""

    selection_changed = pyqtSignal(list)
    order_changed = pyqtSignal()
    # 顺序变更**前**发出，供 MainWindow 捕获撤销快照。
    # 顺序现在在信号发出时还没变，等 order_changed 再捕获快照就已经是新的了。
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

        # Create data model
        self.model = TimelineModel()

        # Qt 适配层 —— **两个视图共用同一个实例**。
        # 这是它们能共享 QItemSelectionModel 的前提（P1-3 的核心收益）：
        # 选中因此只有一份，切换视图不再需要任何同步仪式。
        self.item_model = TimelineItemModel(self.model, self)

        # Connect model signals to view updates
        self.model.frames_inserted.connect(self._on_frames_inserted)
        self.model.frames_removed.connect(self._on_frames_removed)
        self.model.frames_reordered.connect(self._on_frames_reordered)
        self.model.data_changed.connect(self._on_data_changed)
        self.model.frame_disabled_changed.connect(self._on_frame_disabled_changed)
        self.model.selection_changed.connect(self._on_model_selection_changed)

        # Create list view (tree widget)
        self.list_view = TimelineListView(self)
        self.list_view.bind_model(self.model)  # 帧数据与顺序的真源
        self._connect_view_signals(self.list_view)

        # Create grid view
        self.grid_view = TimelineGridWidget(self)
        self.grid_view.bind_model(self.model)
        # **选中只有一份** —— 让网格沿用列表的选择模型。
        #
        # 注意：光是两个视图 `setModel()` 同一个实例，Qt 并不会共享选中 ——
        # `QAbstractItemView.setModel()` 会给每个视图各建一个新的
        # QItemSelectionModel。必须显式 `setSelectionModel()` 才是"选中只有一份"。
        #
        # 顺序有讲究：列表先构造并已绑定模型，它的 selectionModel 此时才有效。
        # 用 `adopt_shared_selection_model` 而不是直接 `setSelectionModel`：换
        # selectionModel 会丢弃旧模型上的连接，必须在之后重连本视图的信号，
        # 否则点击网格里的帧不会通知到属性面板与预览区。
        self.grid_view.adopt_shared_selection_model(self.list_view.selectionModel())
        self._connect_view_signals(self.grid_view, is_grid=True)

        # Add both views to stacked widget
        self.addWidget(self.list_view)
        self.addWidget(self.grid_view)

        # Default to list view
        self.current_view_mode = "list"  # "list" or "grid"

        # Grid settings
        self.grid_thumbnail_width = 120
        self.grid_thumbnail_height = 120
        self.grid_show_multiline = False
        self.grid_multiline_label_height = 36
        self.grid_background_mode = "checkerboard"

        # Apply settings to grid view
        self.grid_view.set_thumbnail_size(self.grid_thumbnail_width, self.grid_thumbnail_height)
        self.grid_view.set_show_multiline(self.grid_show_multiline)
        self.grid_view.set_multiline_label_height(self.grid_multiline_label_height)
        self.grid_view.set_background_mode(self.grid_background_mode)

    def _connect_view_signals(self, view, is_grid=False):
        """Connect common signals from a view to this widget"""
        view.selection_changed.connect(self._on_view_selection_changed)
        view.selection_changed.connect(self.selection_changed)
        view.order_changed.connect(self.order_changed)
        view.reorder_about_to_happen.connect(self.reorder_about_to_happen)
        view.files_dropped.connect(self.files_dropped)
        view.copy_properties_requested.connect(self.copy_properties_requested)
        view.paste_properties_requested.connect(self.paste_properties_requested)
        view.duplicate_requested.connect(self.duplicate_requested)
        view.duplicate_dialog_requested.connect(self.duplicate_dialog_requested)
        view.remove_requested.connect(self.remove_requested)
        view.disabled_state_changed.connect(self.disabled_state_changed)
        view.enable_requested.connect(self.enable_requested)
        view.reverse_order_requested.connect(self.reverse_order_requested)
        view.integerize_offset_requested.connect(self.integerize_offset_requested)
        view.smooth_params_requested.connect(self.smooth_params_requested)
        view.set_reference_requested.connect(self.set_reference_requested)
        view.clear_reference_requested.connect(self.clear_reference_requested)
        view.edit_default_editor_requested.connect(self.edit_default_editor_requested)
        view.edit_in_editor_requested.connect(self.edit_in_editor_requested)

        # Grid-specific signal
        if is_grid:
            view.thumbnail_size_changed.connect(self._on_grid_thumbnail_changed)

    def set_editors(self, editors):
        """把外部图像编辑器列表推送给两个视图，用于构建右键子菜单。"""
        self.list_view.set_editors(editors)
        self.grid_view.set_editors(editors)

    def set_view_mode(self, mode):
        """Switch between list and grid view"""
        timeline_debug(f"[Timeline] Switching view mode to: {mode}")
        # 选定的视图只需重绘**内容** —— `_on_data_changed` 出于性能刻意跳过非活动
        # 视图，它的文本/缩略图可能已陈旧。顺序恒等于模型，无需处理。
        #
        # **选中不需要同步**：两个视图挂同一个适配层 model，共享同一个
        # QItemSelectionModel —— 选中只有一份，切换视图时自动带过去。迁移前这里要
        # 手工 `clearSelection()` + 按模型重设，还因此出过"重建非当前视图时把选中
        # 写串了"的缺陷。
        if mode == "list":
            self.setCurrentWidget(self.list_view)
            self.current_view_mode = "list"
            self.list_view.refresh_current_items()
        elif mode == "grid":
            self.setCurrentWidget(self.grid_view)
            self.current_view_mode = "grid"
            self.grid_view.refresh_current_items()

    def get_view_mode(self):
        """Return current view mode"""
        return self.current_view_mode

    def _on_grid_thumbnail_changed(self, width, height):
        """Handle grid thumbnail size change"""
        self.grid_thumbnail_width = width
        self.grid_thumbnail_height = height
        self.thumbnail_size_changed.emit(width, height)

    def update_grid_settings(self, width, height, multiline, multiline_label_height, background):
        """Update grid view settings"""
        self.grid_thumbnail_width = width
        self.grid_thumbnail_height = height
        self.grid_show_multiline = multiline
        self.grid_multiline_label_height = multiline_label_height
        self.grid_background_mode = background

        self.grid_view.set_thumbnail_size(width, height)
        self.grid_view.set_show_multiline(multiline)
        self.grid_view.set_multiline_label_height(multiline_label_height)
        self.grid_view.set_background_mode(background)

    def get_current_widget(self):
        """Get currently active timeline widget"""
        return self.currentWidget()

    # ========== Model signal handlers ==========
    def _on_frames_inserted(self, index: int, count: int):
        """Handle frame insertion from model"""
        timeline_debug(f"[Timeline] Frames inserted at index {index}, count: {count}")
        # Get frame data from model
        for i in range(count):
            frame_data = self.model.get_frame_at(index + i)
            if frame_data:
                # 两个视图都是 Qt model/view：适配层已把 frames_inserted 翻译成
                # beginInsertRows，视图自动跟随。这里不再需要任何手工镜像。
                filename = os.path.basename(frame_data.file_path)

    def _on_frames_removed(self, index: int, count: int):
        """Handle frame removal from model"""
        timeline_debug(f"[Timeline] Frames removed at index {index}, count: {count}")
        # 两个视图都由适配层 model 的 frames_removed → beginRemoveRows 自动跟随

    def _on_frames_reordered(self):
        """Handle wholesale reordering (reverse / drag-drop sort / set_frames_order).

        The frame objects themselves are unchanged — what changed is the index→item
        mapping, so this cannot be handled by refreshing item text in place.

        The order now lives **only** in the model (drag-drop calls
        `model.move_frames` instead of shuffling items). Both views are Qt
        model/view, so the adapter model's `beginResetModel` already makes them
        re-fetch everything by row — there is nothing to re-sort here.

        What remains: `beginResetModel` **clears the QItemSelectionModel**, so the
        selection has to be re-applied from the model afterwards.
        """
        timeline_debug("[Timeline] Frames reordered")
        self._restore_selection_from_model()

    def _on_data_changed(self, start_index: int, end_index: int):
        """Handle frame data change from model

        性能约定：**只更新当前活动视图**。另一个视图不可见，为它重建缩略图是白花的
        磁盘 I/O，而属性面板拖滑块时本信号会以每帧一次的频率触发。

        代价是非活动视图会停留在上一次同步时的状态（**帧属性**变了它不知道），因此
        `set_view_mode` 切换过去时要重绘一次内容。**顺序**不会陈旧 —— 顺序只能由模型
        改（拖拽走 `model.move_frames` → `frames_reordered`），视图不持有顺序。

        **不要**为了让本方法"看起来更正确"而改成同时更新两个视图。
        """
        timeline_debug(f"[Timeline] Data changed from index {start_index} to {end_index}")
        # Get selection before update
        selection_before = self.model.get_selected_indices()

        # 顺序无需校验：顺序只能由模型改（拖拽走 model.move_frames → frames_reordered），
        # 本信号的语义就是"内容变了、位置没变"，因此下面的原地刷新是安全的。
        # （曾经这里要靠 _view_in_sync_with_model 兜底，因为视图会自己搬 item。）

        # 两个视图都是 Qt model/view：适配层已把 dataChanged 转发给视图，
        # 单元格文本与缩略图都是现算的，无需任何手工刷新。

        # Check selection after update
        selection_after = self.model.get_selected_indices()

        if selection_before != selection_after:
            print(f"WARNING: Selection changed during update! Before: {selection_before}, After: {selection_after}")

    def _on_frame_disabled_changed(self, index: int, is_disabled: bool):
        """Handle frame disabled state change from model.

        两个视图都是 Qt model/view，适配层已对受影响的行发 `dataChanged`，
        视图自动重绘，无需处理。
        """

    def _on_model_selection_changed(self):
        """Handle selection change from model"""
        # Get selected indices from model
        selected_indices = set(self.model.get_selected_indices())

        # Block signals and stop timers before updating
        if self.current_view_mode == "list":
            self.list_view._selection_debounce_timer.stop()
            self.list_view.blockSignals(True)
        else:
            self.grid_view._selection_debounce_timer.stop()
            self.grid_view.blockSignals(True)

        # Only update the currently active view
        self._apply_selection_to_view(selected_indices)

        # Unblock signals
        if self.current_view_mode == "list":
            self.list_view.blockSignals(False)
        else:
            self.grid_view.blockSignals(False)

    # ========== Model access methods ==========
    def add_frame(self, filename: str, frame_data: FrameData, index: Optional[int] = None):
        """Add frame through model"""
        self.model.add_frame(frame_data, index)

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

    # `move_frame` / `move_frames` 转发已删除 —— 视图直接调 `model.move_frames()`
    # （顺序的唯一入口），不需要经过本类再绕一层。

    def set_frames(self, frames: List[FrameData]):
        """整体替换帧列表（撤销恢复）—— 只发一条信号，不逐帧通知。

        见 `TimelineModel.set_frames` 的说明：曾经这里是 `clear()` + 逐帧
        `add_frame()`，共 N+1 条结构变更通知。
        """
        self.model.set_frames(frames)

    def update_frame_data(self, index: int):
        """Notify model that frame data changed"""
        self.model.update_frame_data(index)

    def clear(self):
        """Clear all data"""
        self.model.clear()  # 发 frames_removed → 适配层清行 → 两视图自动跟随
        # 只需清缩略图缓存 —— 那属于网格视图（列表视图没有缩略图）。
        # 迁移前两视图各有一个 clear_view()，列表那个迁到 model/view 后退化为空，已删。
        self.grid_view.clear_view()

    def set_reference_frame(self, frame_data: Optional[FrameData]):
        """Set reference frame through model"""
        self.model.set_reference_frame(frame_data)

    def clear_reference_frame(self):
        """Clear reference frame through model"""
        self.model.clear_reference_frame()

    def get_reference_frame(self) -> Optional[FrameData]:
        """Get reference frame from model"""
        return self.model.get_reference_frame()

    # ========== Unified interface methods (using model) ==========
    def get_selected_indices_from_model(self) -> List[int]:
        """Get selected indices from the model (source of truth for selection)"""
        return self.model.get_selected_indices()

    def get_selected_frames(self) -> List[FrameData]:
        """Get selected frame data from model"""
        return self.model.get_selected_frames()

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """Get frame data from model"""
        return self.model.get_frame_at(index)

    # `extract_frame_data_from_item` 已删除 —— 两个视图都不再有 item 对象，
    # 它成了唯一还依赖 `QTreeWidgetItem` / `QListWidgetItem` 的死代码。
    # 需要帧数据请直接用 `get_frame_data_at_index()` 或 `get_selected_frames()`。

    # `add_frame_to_current_view` / `remove_frame_from_current_view` 已删除 ——
    # 它们转发到视图的 add_frame_to_view/remove_frame_from_view，而那两个方法在
    # 两视图迁到 model/view 后已退化为空（视图由模型信号自动跟随），整条链是空的。

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

    # `update_item_display` 已删除 —— 死代码，且 list 分支指向了一个已被删掉的方法。

    def refresh_ui_text(self):
        self.list_view.refresh_ui_text()
        self.grid_view.refresh_ui_text()

    def refresh_current_items(self):
        """Refresh all items in current view in-place (without clearing/rebuilding)"""
        if self.current_view_mode == "list":
            self.list_view.refresh_current_items()
        else:
            self.grid_view.refresh_current_items()

    def rebuild_current_view(self):
        """Full rebuild of current view from model (only when structure/order requires)"""
        if self.current_view_mode == "list":
            self._rebuild_list_view()
        else:
            self._rebuild_grid_view()

    def _restore_selection_from_model(self):
        """按模型恢复选中 —— model reset 之后的唯一必要动作。

        两个视图共享同一个 `QItemSelectionModel`（挂同一个适配层 model），因此选中
        **只有一份**，恢复一次即可，不存在"两个视图各自记一份"的问题。

        为什么必须显式恢复：`beginResetModel`/`endResetModel` 会清掉
        `QItemSelectionModel`，而业务模型 `TimelineModel` 的选中仍然存在（它是
        model 之外的一份状态，reset 影响不到它）。不恢复的话，反转/拖拽之后界面上
        就什么都不选中了。
        """
        selected_indices = set(self.model.get_selected_indices())
        self._block_all_signals()
        self._apply_selection_to_view(selected_indices, self.current_view_mode)
        self._unblock_all_signals()

    def _rebuild_list_view(self):
        """列表视图：model reset 之后只需恢复选中。

        内容是 model 的 `data()` 现算的，不存在"重建"这回事。但
        `beginResetModel`/`endResetModel` 会清掉 selectionModel，所以选中必须重设。
        """
        selected_indices = set(self.model.get_selected_indices())
        if selected_indices:
            self.list_view.blockSignals(True)
            self._apply_selection_to_view(selected_indices, "list")
            self.list_view.blockSignals(False)

    def _rebuild_grid_view(self):
        """网格视图：model reset 之后只需恢复选中（同列表视图）。

        内容由 model 的 `data()` 现算，缩略图缓存在网格视图里、与行序无关，
        都不需要"重建"。
        """
        self._restore_selection_from_model()

    def refresh_all_grid_items(self):
        """Refresh all grid items (thumbnails and text)"""
        self.grid_view.refresh_all_items()

    def _block_all_signals(self):
        """Block all signals from both views"""
        self.list_view.blockSignals(True)
        self.grid_view.blockSignals(True)
        self.list_view.block_selection_signals_internal(True)
        self.grid_view.block_selection_signals_internal(True)

    def _unblock_all_signals(self):
        """Unblock all signals from both views"""
        self.list_view.blockSignals(False)
        self.grid_view.blockSignals(False)
        self.list_view.block_selection_signals_internal(False)
        self.grid_view.block_selection_signals_internal(False)

    def _apply_selection_to_view(self, selected_indices, mode=None):
        """Apply selection indices to a view and sync currentIndex/anchor

        mode: 目标视图。**必须显式指定**——本方法也被 `_rebuild_list_view` /
        `_rebuild_grid_view` 调用，而它们重建的是**非当前**视图。若这里默许读
        `current_view_mode`，重建 list 时就会把 selection 写进 grid（反之亦然），
        于是"重建一个视图"顺手覆盖了另一个视图刚排好的选中状态。
        """
        selected_set = selected_indices if isinstance(selected_indices, set) else set(selected_indices)
        mode = mode or self.current_view_mode

        if mode == "list":
            # Apply selection to list items
            self.list_view._apply_selection_from_set(selected_set)

            # Sync currentIndex & anchor for Shift/Ctrl range selection
            if selected_set:
                target_idx = max(selected_set)
                if 0 <= target_idx < self.list_view.model().rowCount():
                    model_idx = self.list_view.model().index(target_idx, 0, QModelIndex())
                    if model_idx.isValid() and self.list_view.selectionModel():
                        self.list_view.selectionModel().setCurrentIndex(
                            model_idx, QItemSelectionModel.SelectionFlag.NoUpdate
                        )
            else:
                if self.list_view.selectionModel():
                    self.list_view.selectionModel().clearCurrentIndex()
        else:
            # Grid view
            self.grid_view._apply_selection_from_set(selected_set)

            # Sync currentIndex & anchor for Shift/Ctrl range selection
            if selected_set:
                target_idx = max(selected_set)
                if 0 <= target_idx < self.grid_view.model().rowCount():
                    model_idx = self.grid_view.model().index(
                        target_idx, self.grid_view.modelColumn(), QModelIndex())
                    if model_idx.isValid() and self.grid_view.selectionModel():
                        self.grid_view.selectionModel().setCurrentIndex(
                            model_idx, QItemSelectionModel.SelectionFlag.NoUpdate
                        )
            else:
                if self.grid_view.selectionModel():
                    self.grid_view.selectionModel().clearCurrentIndex()

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

    def setCurrentRow(self, row: int):
        """Set the current row in both views (used to follow playback)."""
        if row < 0:
            return
        for view in (self.list_view, self.grid_view):
            if row >= view.model().rowCount():
                continue
            index = view.model().index(row, 0)
            if not index.isValid():
                continue
            view.setCurrentIndex(index)
            sel = view.selectionModel()
            if sel is not None:
                sel.select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                           | QItemSelectionModel.SelectionFlag.Rows)

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
