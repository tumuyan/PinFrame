from PyQt6.QtCore import QObject, pyqtSignal
from model.project_data import FrameData
from typing import List, Optional


class TimelineModel(QObject):
    """Timeline data model - manages frame data independently from UI views"""

    # Signals
    data_changed = pyqtSignal(int, int)  # start_index, end_index
    frames_inserted = pyqtSignal(int, int)  # index, count
    frames_removed = pyqtSignal(int, int)  # index, count
    frames_moved = pyqtSignal(int, int, int)  # from_index, to_index, count
    selection_changed = pyqtSignal()
    reference_changed = pyqtSignal(object)  # frame_data or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: List[FrameData] = []
        self._reference_frame: Optional[FrameData] = None
        self._selected_indices: List[int] = []

    # Frame data management
    def get_frame_count(self) -> int:
        """Get total number of frames"""
        return len(self._frames)

    def get_frame_at(self, index: int) -> Optional[FrameData]:
        """Get frame data at specified index"""
        if 0 <= index < len(self._frames):
            return self._frames[index]
        return None

    def get_all_frames(self) -> List[FrameData]:
        """Get all frames"""
        return self._frames.copy()

    def add_frame(self, frame_data: FrameData, index: Optional[int] = None) -> int:
        """
        Add a frame to the model
        Returns the actual index where frame was added
        """
        if index is None:
            index = len(self._frames)
        elif index < 0:
            index = 0
        elif index > len(self._frames):
            index = len(self._frames)

        self._frames.insert(index, frame_data)
        self.frames_inserted.emit(index, 1)
        return index

    def remove_frame_at(self, index: int) -> Optional[FrameData]:
        """Remove frame at specified index, returns the removed frame"""
        if 0 <= index < len(self._frames):
            frame = self._frames.pop(index)
            self.frames_removed.emit(index, 1)

            # Update selection
            if self._selected_indices:
                new_selection = []
                for idx in self._selected_indices:
                    if idx == index:
                        # Removed item, skip it
                        continue
                    elif idx > index:
                        # Shift down
                        new_selection.append(idx - 1)
                    else:
                        # Keep as is
                        new_selection.append(idx)
                self._selected_indices = new_selection
                self.selection_changed.emit()

            return frame
        return None

    def remove_frames_at(self, indices: List[int]) -> List[FrameData]:
        """Remove multiple frames at specified indices, returns list of removed frames"""
        if not indices:
            return []

        # Sort indices in descending order for safe removal
        sorted_indices = sorted(indices, reverse=True)
        removed = []

        for index in sorted_indices:
            frame = self.remove_frame_at(index)
            if frame:
                removed.append(frame)

        return removed

    def move_frame(self, from_index: int, to_index: int) -> bool:
        """Move frame from one index to another"""
        if not self._is_valid_index(from_index) or not self._is_valid_index(to_index):
            return False

        if from_index == to_index:
            return False

        frame = self._frames.pop(from_index)
        self._frames.insert(to_index, frame)
        self.frames_moved.emit(from_index, to_index, 1)

        # Update selection
        self._update_selection_after_move(from_index, to_index)
        return True

    def replace_frame_at(self, index: int, frame_data: FrameData) -> bool:
        """Replace frame data at specified index"""
        if 0 <= index < len(self._frames):
            self._frames[index] = frame_data
            self.data_changed.emit(index, index)

            # Update reference if needed
            if self._reference_frame and self._reference_frame is not frame_data:
                # Check if we need to update reference
                pass

            return True
        return False

    def update_frame_data(self, index: int):
        """Notify that frame data at index has changed"""
        if 0 <= index < len(self._frames):
            self.data_changed.emit(index, index)

    def clear(self):
        """Clear all frames"""
        self._frames.clear()
        self._selected_indices.clear()
        self._reference_frame = None

    # Selection management
    def get_selected_indices(self) -> List[int]:
        """Get list of selected indices"""
        return self._selected_indices.copy()

    def get_selected_frames(self) -> List[FrameData]:
        """Get list of selected frame data"""
        return [self._frames[i] for i in self._selected_indices if 0 <= i < len(self._frames)]

    def set_selection(self, indices: List[int]):
        """Set selection by indices"""
        # Filter invalid indices
        valid_indices = [i for i in indices if 0 <= i < len(self._frames)]
        self._selected_indices = sorted(list(set(valid_indices)))  # Remove duplicates and sort
        self.selection_changed.emit()

    def select_all(self):
        """Select all frames"""
        self._selected_indices = list(range(len(self._frames)))
        self.selection_changed.emit()

    def clear_selection(self):
        """Clear selection"""
        self._selected_indices.clear()
        self.selection_changed.emit()

    def toggle_selection(self, index: int) -> bool:
        """Toggle selection at index, returns True if selected, False if deselected"""
        if not self._is_valid_index(index):
            return False

        if index in self._selected_indices:
            self._selected_indices.remove(index)
            self.selection_changed.emit()
            return False
        else:
            self._selected_indices.append(index)
            self._selected_indices.sort()
            self.selection_changed.emit()
            return True

    # Reference frame management
    def get_reference_frame(self) -> Optional[FrameData]:
        """Get current reference frame"""
        return self._reference_frame

    def set_reference_frame(self, frame_data: Optional[FrameData]):
        """Set reference frame (or None to clear)"""
        self._reference_frame = frame_data
        self.reference_changed.emit(frame_data)

    def clear_reference_frame(self):
        """Clear reference frame"""
        self.set_reference_frame(None)

    def get_reference_index(self) -> Optional[int]:
        """Get index of reference frame"""
        if self._reference_frame:
            try:
                return self._frames.index(self._reference_frame)
            except ValueError:
                return None
        return None

    # Utility methods
    def _is_valid_index(self, index: int) -> bool:
        """Check if index is valid"""
        return 0 <= index < len(self._frames)

    def _update_selection_after_move(self, from_index: int, to_index: int):
        """Update selection after moving a frame"""
        new_selection = []
        for idx in self._selected_indices:
            if idx == from_index:
                # Moved item
                new_selection.append(to_index)
            elif from_index < idx <= to_index:
                # Items between from and to shift left
                new_selection.append(idx - 1)
            elif to_index <= idx < from_index:
                # Items between to and from shift right
                new_selection.append(idx + 1)
            else:
                # No change
                new_selection.append(idx)

        self._selected_indices = sorted(list(set(new_selection)))
        self.selection_changed.emit()

    # Batch operations
    def reverse_frames(self, indices: Optional[List[int]] = None):
        """
        Reverse order of specified frames or all frames
        If indices provided, reverse order of those frames only
        """
        if indices:
            # Reverse specific subset
            valid_indices = [i for i in indices if self._is_valid_index(i)]
            if len(valid_indices) < 2:
                return

            frames_to_reverse = [self._frames[i] for i in valid_indices]
            frames_to_reverse.reverse()

            for idx, frame_data in zip(valid_indices, frames_to_reverse):
                self._frames[idx] = frame_data

            min_idx = min(valid_indices)
            max_idx = max(valid_indices)
            self.data_changed.emit(min_idx, max_idx)
        else:
            # Reverse all
            self._frames.reverse()

            # Update selection indices
            if self._selected_indices:
                total = len(self._frames)
                new_selection = [total - 1 - idx for idx in self._selected_indices]
                self._selected_indices = sorted(new_selection)
                self.selection_changed.emit()

            self.data_changed.emit(0, len(self._frames) - 1)

    def duplicate_frames(self, indices: List[int], insert_position: Optional[int] = None) -> List[int]:
        """
        Duplicate frames at specified indices
        Returns list of new indices where duplicates were inserted
        """
        if not indices:
            return []

        # Sort indices
        sorted_indices = sorted([i for i in indices if self._is_valid_index(i)])
        if not sorted_indices:
            return []

        # Determine insertion position
        if insert_position is None:
            insert_position = max(sorted_indices) + 1

        # Duplicate frames (batch operation - emit single signal at the end)
        new_indices = []
        duplicates = []
        for idx in sorted_indices:
            original = self._frames[idx]
            duplicate = FrameData(
                file_path=original.file_path,
                scale=original.scale,
                position=original.position,
                rotation=original.rotation,
                aspect_ratio=original.aspect_ratio,
                is_disabled=original.is_disabled,
                crop_rect=original.crop_rect if original.crop_rect else None
            )
            duplicates.append(duplicate)

        # Insert all duplicates at once and emit a single signal
        if duplicates:
            for duplicate in duplicates:
                self._frames.insert(insert_position, duplicate)
                new_indices.append(insert_position)
                insert_position += 1

            # Emit a single frames_inserted signal for all duplicates
            if new_indices:
                self.frames_inserted.emit(new_indices[0], len(new_indices))

        return new_indices

    def enable_frames(self, indices: List[int], enabled: bool):
        """Enable or disable frames at specified indices"""
        for idx in indices:
            if self._is_valid_index(idx):
                self._frames[idx].is_disabled = not enabled

        if indices:
            min_idx = min(i for i in indices if self._is_valid_index(i))
            max_idx = max(i for i in indices if self._is_valid_index(i))
            self.data_changed.emit(min_idx, max_idx)

    def find_frame_index(self, frame_data: FrameData) -> Optional[int]:
        """Find index of a frame data object"""
        try:
            return self._frames.index(frame_data)
        except ValueError:
            return None

    def set_frames_order(self, frames: List[FrameData]) -> bool:
        """用给定的帧顺序整体替换模型中的帧列表（用于视图拖拽排序后同步）。

        注意：传入的列表应包含当前模型中的全部帧对象（同一批对象、仅顺序不同）。
        返回是否真的发生了顺序变更（长度不符或顺序未变时返回 False）。
        """
        if len(frames) != len(self._frames):
            return False
        if frames == self._frames:
            return False
        self._frames = list(frames)
        self.data_changed.emit(0, max(0, len(self._frames) - 1))
        return True
