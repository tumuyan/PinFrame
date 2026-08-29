from PyQt6.QtCore import QObject, pyqtSignal
from model.project_data import FrameData
from typing import List, Optional


class TimelineModel(QObject):
    """Timeline data model - manages frame data independently from UI views"""

    # Signals
    data_changed = pyqtSignal(int, int)  # start_index, end_index
    frame_disabled_changed = pyqtSignal(int, bool)  # index, is_disabled
    frames_inserted = pyqtSignal(int, int)  # index, count
    frames_removed = pyqtSignal(int, int)  # index, count
    # 顺序整体变化（反转 / 拖拽排序 / set_frames_order），无参数。
    # 曾经还有个 `frames_moved(from, to, count)` 表示"单个移动"，但唯一的发射方
    # `move_frame()`（单数）随第 3 片删除了 —— 所有换序都走 `move_frames()`，它发的是
    # 本信号。留着一个没人发的信号只会误导后来者。
    frames_reordered = pyqtSignal()
    frames_replaced = pyqtSignal()  # 帧列表被**整体替换成另一批对象**（撤销恢复），无参数
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

    def move_frames(self, indices: List[int], insert_index: int) -> bool:
        """把 indices 处的帧整体移动到 insert_index 之前 —— **顺序的唯一写入入口**。

        坐标系与视图 dropEvent 一致：`insert_index` 取 0..len(frames)，表示"移动前"
        列表中这些帧应插入到的位置（插到第 insert_index 个元素之前）。

        为什么放在模型里：视图曾经自己 `takeItem`/`insertItem` 搬 item，模型毫不知情，
        之后再由 `MainWindow.on_order_changed` 把视图顺序**回写**给模型。那等于顺序有
        两个源，是 `TimelineWidget._view_in_sync_with_model` 与"切视图后顺序错乱"那类
        缺陷的根因。拖拽现在只负责算出 `(被拖行号, 插入点)`，顺序变更一律走这里。

        返回是否真的发生了顺序变更（无效下标 / 原位放置 / 结果相同均返回 False）。
        """
        valid = sorted({i for i in indices if self._is_valid_index(i)})
        if not valid:
            return False

        total = len(self._frames)
        insert_index = max(0, min(total, insert_index))

        # 连续块放在自己原位的两种情形（紧邻其上 / 紧邻其下）视为无变更
        is_contiguous = (valid[-1] - valid[0] + 1 == len(valid))
        if is_contiguous and (insert_index == valid[0] or insert_index == valid[-1] + 1):
            return False

        moved_set = set(valid)
        dragged = [self._frames[i] for i in valid]
        remaining = [f for i, f in enumerate(self._frames) if i not in moved_set]

        # 转换到"移除被拖项之后"的坐标系
        dragged_before_count = sum(1 for i in valid if i < insert_index)
        target = max(0, min(len(remaining), insert_index - dragged_before_count))

        new_frames = remaining[:target] + dragged + remaining[target:]

        # 顺序是否变化，必须按**对象身份**比较，不能用 `==`。
        #
        # `FrameData` 是 dataclass，`==` 是自动生成的值相等。工程里完全相同的帧
        # 并不罕见 —— 复制帧、同一张源图切出的相同区域、批量粘贴的属性。此时任意
        # 排列在 `==` 下都"相等"，于是拖到非相邻位置会被误判成无变化而静默忽略：
        # 用户拖了，什么也没发生，也没有任何提示。
        #
        # 顺序的语义是"**哪个帧对象**在哪个位置"，不是"哪个值在哪个位置"。
        if len(new_frames) == len(self._frames) and all(
                a is b for a, b in zip(new_frames, self._frames)):
            return False

        self._frames = new_frames

        # 被拖的帧在新列表中是连续块，占据 [target, target + len(dragged))
        self._selected_indices = list(range(target, target + len(dragged)))

        # 整体换序：索引到 item 的映射失效，视图必须按模型重建。
        # 不能用 data_changed —— 它只按索引原地刷新文本、不重排 item（同 reverse_frames）。
        self.frames_reordered.emit()
        self.selection_changed.emit()
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
        """Clear all frames.

        必须**先发信号再清数据**：`frames_removed` 的处理器（含 Qt 适配层的
        `beginRemoveRows`）会同步读 `rowCount()`，若此时 `_frames` 已空，
        Qt 会断言"要删的行数超过了实际行数"并 abort。

        曾经这里不发信号，靠调用方手工 `view.clear()` 清视图 —— 那是典型的
        "模型改了但视图得自己知道"，列表视图迁到 model/view 后就崩了。
        """
        count = len(self._frames)
        if count:
            self.frames_removed.emit(0, count)
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
        else:
            # Reverse all
            self._frames.reverse()

            # Update selection indices
            if self._selected_indices:
                total = len(self._frames)
                new_selection = [total - 1 - idx for idx in self._selected_indices]
                self._selected_indices = sorted(new_selection)
                self.selection_changed.emit()

        # 顺序整体变了 → 索引到 item 的映射不再成立，发 frames_reordered 让视图按
        # 模型重建。**不能用 data_changed**：它的语义是"内容变了、位置没变"，视图
        # 收到后只按索引原地刷新文本，不会重排 item，于是顺序变更在 UI 上完全不生效
        # （模型是对的、保存导出也是对的，只有界面显示旧顺序）。
        self.frames_reordered.emit()

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
            # 克隆逻辑统一在 FrameData.clone()（此前这里漏了 target_resolution）
            duplicates.append(original.clone())

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

    def set_frame_disabled(self, index: int, is_disabled: bool):
        """
        设置单帧禁用状态（禁用状态的唯一写入入口）。

        仅修改帧数据本身并通过 frame_disabled_changed 通知视图刷新，
        视图不再持有任何 UI 副本角色（如 CheckStateRole），避免多源不一致。
        返回是否真的发生了变更（状态未变时返回 False，不触发信号）。
        """
        if not self._is_valid_index(index):
            return False
        frame = self._frames[index]
        if frame.is_disabled == is_disabled:
            return False
        frame.is_disabled = is_disabled
        # 禁用列由 _DisableColumnDelegate 直接读 frame_data.is_disabled，
        # 只需 frame_disabled_changed 触发受影响行重绘即可，无需再 emit data_changed
        # （data_changed 会额外触发整行文本重刷，属冗余）。
        self.frame_disabled_changed.emit(index, is_disabled)
        return True

    def find_frame_index(self, frame_data: FrameData) -> Optional[int]:
        """Find index of a frame data object"""
        try:
            return self._frames.index(frame_data)
        except ValueError:
            return None

    def set_frames(self, frames: List[FrameData]) -> None:
        """整体替换帧列表 —— **只发一条**信号，而不是逐帧通知。

        用于撤销恢复这类"整个文档换成另一批帧对象"的场景。曾经那里是
        `clear()` + 逐帧 `add_frame()`，即 1 次移除 + N 次插入共 **N+1 条**结构变更
        通知，每条都会让视图做一次布局调整；换成整体替换后只有一条。

        为什么不能复用 `data_changed`：它的语义是"内容变了、索引映射没变"，而这里
        连帧对象都换了，**行数也可能变**。

        副作用（刻意）：选中下标越界的丢弃、不在新列表里的参考帧清空。调用方随后会
        按快照恢复这两者（见 `MainWindow._apply_snapshot_inner`）。
        """
        self._frames = list(frames)
        total = len(self._frames)
        if self._selected_indices:
            self._selected_indices = [i for i in self._selected_indices if i < total]
        if self._reference_frame is not None and not any(
                f is self._reference_frame for f in self._frames):
            self._reference_frame = None
        self.frames_replaced.emit()

    def apply_frames(self, frames: List[FrameData]) -> bool:
        """按内容更新模型，尽量走**增量**而非整体替换 —— 撤销恢复的专用入口。

        背景：`set_frames()` 是整体替换，适配层收到 `frames_replaced` 后
        `beginResetModel`，视图全量重取、滚动位置丢失、`QItemSelectionModel`
        被清空（于是每次撤销都要再恢复一次选中）。而撤销一次"把 scale 从 1.0
        调成 1.1"实际只动了 1 帧 —— 为 1 帧重建整个时间轴是纯浪费。

        行数相同时改为逐帧替换，最后发**一条** `data_changed(最小行, 最大行)`：
        选中与滚动位置都保住（这才是相对整体替换的主要收益）。行数不同才回落到
        `set_frames()`（撤销加帧/删帧时行数确实会变）。

        区间取"最小行~最大行"的**闭包**，非连续变更时中间未变的行也落在区间内 ——
        例如只改第 0 行与第 999 行，发出的是 `data_changed(0, 999)`。
        这是有意的权衡，不要为了"精确"把区间拆成多段：实测 Qt 视图只绘制**视口内**
        的项（1000 帧工程、800x600 视口下，区间从 1 行放大到 1000 行，
        `delegate.paint` 都是 22 次），多覆盖的部分不产生实际绘制开销；
        而拆成多段意味着发多条通知，复杂度不划算。

        这里用 `data_changed` 而非整体替换信号，语义是对的：行数不变、
        "第 i 行是哪个帧"也没变，只是**内容**变了 —— 正是 `data_changed` 的定义。

        返回是否走了增量路径（False 表示回落到整体替换）。
        """
        target = list(frames)
        if len(target) != len(self._frames):
            # 回落路径**同样必须克隆**：`set_frames` 是直接换列表、不克隆的，而
            # 调用方（`_apply_snapshot_inner`）已把克隆的责任全交给本方法。
            # 漏了这里，模型就会与历史快照共享同一批 FrameData，此后每次原地
            # 编辑都会写进历史快照 —— 不报错、不崩溃，只是撤销恢复到的是被后续
            # 编辑改过的值。增量路径与回落路径都必须守住这一点。
            self.set_frames([f.clone() for f in target])
            return False

        # 先挑出真正不同的行：一次撤销常常什么都没变（例如撤销后又重做），
        # 那时一条通知都不该发。
        # `is not` 短路掉"同一对象"，`!=` 是 FrameData 的值比较。
        changed = [i for i, (cur, new) in enumerate(zip(self._frames, target))
                   if cur is not new and cur != new]
        if not changed:
            return True

        # 克隆后再放进模型：快照里的帧对象必须只属于快照。
        # 若这里直接存 `target[i]`，模型与历史快照就共享了同一对象，之后的每一次
        # 原地编辑都会**改到历史快照里去**，撤销恢复到的是"被后续编辑改过"的值
        # （静默错误，且不报错）。只克隆变化的那几帧，未变的帧保持原对象不动。
        for i in changed:
            self._frames[i] = target[i].clone()

        # 与 set_frames 的副作用保持一致：参考帧若指向被换掉的旧对象则清空。
        # 调用方随后会按快照重新设置参考帧（见 `_apply_snapshot_inner`）。
        if self._reference_frame is not None and not any(
                f is self._reference_frame for f in self._frames):
            self._reference_frame = None

        # changed 由 enumerate 生成，天然升序，故首/末即最小/最大行。
        self.data_changed.emit(changed[0], changed[-1])
        return True

    def set_frames_order(self, frames: List[FrameData]) -> bool:
        """用给定的帧顺序整体替换模型中的帧列表。

        注意：传入的列表应包含当前模型中的全部帧对象（同一批对象、仅顺序不同）。
        返回是否真的发生了顺序变更（长度不符或顺序未变时返回 False）。

        **当前无生产调用点**，只被 `dev/test_transform.py`（锁定 `frames_reordered`
        的信号契约）与 `dev/verify_timeline_view_sync.py` 使用。它曾经是"视图拖拽后
        把顺序回写模型"的入口，那条回写路径已随第 1 片删除。

        注意与 `set_frames()` 的区别：本方法要求**同一批对象**且**行数不变**
        （纯换序，发 `frames_reordered`）；`set_frames()` 是换成另一批对象、行数可变
        （发 `frames_replaced`）。撤销恢复用的是后者。
        """
        if len(frames) != len(self._frames):
            return False
        # 身份比较，不能用 `==` —— 理由同 move_frames：FrameData 是 dataclass，
        # 值相等会让完全相同的帧（复制帧、同图同裁切）无论怎么重排都判为"无变化"。
        if all(a is b for a, b in zip(frames, self._frames)):
            return False
        self._frames = list(frames)
        # 同 reverse_frames：整体换序后索引映射失效，必须让视图按模型重建，
        # 发 data_changed 只会原地刷新文本、不会重排 item。
        self.frames_reordered.emit()
        return True
