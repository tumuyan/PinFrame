"""操作历史记录管理（撤销/重做）。

采用"状态快照 + 历史栈"的命令模式：
- 每条 HistoryEntry 保存一次编辑的"前/后"项目状态快照；
- 维护当前历史位置索引，支持撤销(undo)、重做(redo)以及直接跳转到任意历史状态；
- 撤销/重做/跳转统一通过 apply_snapshot 回调把快照应用回项目。

该模块与 UI 解耦，MainWindow 负责生成快照与应用快照。
"""
from typing import List, Optional


class HistoryEntry:
    """一条历史记录：操作名称 + 操作前后快照。"""

    __slots__ = ("label", "before", "after")

    def __init__(self, label: str, before, after):
        self.label = label
        self.before = before
        self.after = after

    def __repr__(self):
        return f"<HistoryEntry '{self.label}'>"


class HistoryManager:
    """轻量级操作历史管理器。

    状态模型：
        S0 = 初始状态（独立保存的 _initial_snapshot，栈裁剪后仍可还原）
        S1 = entries[0].after == entries[1].before
        ...
        Sn = entries[n-1].after

    当前位置 index:
        -1  -> 初始状态 S0
        k   -> 状态 entries[k].after

    说明：历史栈达到 max_entries 时会丢弃最旧的一条记录，但真正的初始状态
    S0 会被独立保存在 _initial_snapshot 中，因此撤销到 -1（或 jump_to(-1)）
    仍能还原到项目真正初始的状态，不受栈裁剪影响。
    """

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self._entries: List[HistoryEntry] = []
        self._index: int = -1
        # 独立保存的真正初始状态 S0（首次 push 时的 before），
        # 即使历史栈因容量限制被裁剪，撤销到 -1 仍可还原到最初状态。
        self._initial_snapshot = None

    # ---------- 只读属性 ----------

    @property
    def entries(self) -> List[HistoryEntry]:
        """返回全部历史记录（从旧到新）。"""
        return list(self._entries)

    @property
    def index(self) -> int:
        """当前所在历史位置索引，-1 表示初始状态。"""
        return self._index

    @property
    def can_undo(self) -> bool:
        return self._index >= 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._entries) - 1

    def count(self) -> int:
        return len(self._entries)

    # ---------- 核心操作 ----------

    def push(self, label: str, before, after, merge: bool = False) -> int:
        """记录一次编辑：before -> after。会丢弃当前之后的 redo 分支。

        merge=True 时，如果最近一条记录与本次 label 相同，则只更新其 after
        （例如连发“重复移动”时合并为一条历史，避免刷屏）。
        """
        # 丢弃 redo 分支
        del self._entries[self._index + 1:]
        # 尝试合并连续同标签操作
        if merge and self._entries and self._entries[-1].label == label:
            self._entries[-1].after = after
            self._index = len(self._entries) - 1
            return self._index
        if not self._entries:
            # 记录真正的初始状态，供撤销到 -1 时还原
            self._initial_snapshot = before
        self._entries.append(HistoryEntry(label, before, after))
        # 限制历史数量，丢弃最旧记录
        if len(self._entries) > self.max_entries:
            del self._entries[0]
        self._index = len(self._entries) - 1
        return self._index

    def undo(self) -> Optional[tuple]:
        """回退一步。返回 (label, snapshot) 表示应恢复到的新状态；不可撤销时返回 None。"""
        if not self.can_undo:
            return None
        self._index -= 1
        if self._index < 0:
            entry = self._entries[0]
            snapshot = self._initial_snapshot if self._initial_snapshot is not None else entry.before
            return entry.label, snapshot
        entry = self._entries[self._index]
        return entry.label, entry.after

    def redo(self) -> Optional[tuple]:
        """前进一步。返回 (label, snapshot)；不可重做时返回 None。"""
        if not self.can_redo:
            return None
        self._index += 1
        entry = self._entries[self._index]
        return entry.label, entry.after

    def jump_to(self, target_index: int) -> Optional[tuple]:
        """跳转到指定历史位置（-1 表示初始状态）。返回 (label, snapshot)。"""
        # 空栈守卫：历史为空时任何跳转（含 -1）都无意义，直接返回 None
        if not self._entries:
            return None
        if target_index < -1 or target_index >= len(self._entries):
            return None
        self._index = target_index
        if target_index < 0:
            entry = self._entries[0]
            snapshot = self._initial_snapshot if self._initial_snapshot is not None else entry.before
            return entry.label, snapshot
        entry = self._entries[target_index]
        return entry.label, entry.after

    def clear(self):
        """清空全部历史。"""
        self._entries.clear()
        self._index = -1
        self._initial_snapshot = None
