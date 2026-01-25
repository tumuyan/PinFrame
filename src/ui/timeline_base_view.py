from typing import List, Optional
from model.project_data import FrameData


class BaseTimelineView:
    """
    抽象基类 - 定义时间轴视图的统一接口
    不继承ABC以避免与Qt的元类冲突
    使用NotImplementedError来强制子类实现抽象方法
    """

    # ========== 必须实现的抽象方法 ==========

    def get_selected_indices(self) -> List[int]:
        """获取选中项的索引列表"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_selected_indices()")

    def get_selected_items(self):
        """获取选中项列表（返回具体的item对象）"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_selected_items()")

    def get_frame_data_at_index(self, index: int) -> Optional[FrameData]:
        """获取指定索引的帧数据"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_frame_data_at_index()")

    def add_frame_to_view(self, filename: str, frame_data: FrameData, index: int):
        """向视图中添加帧"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement add_frame_to_view()")

    def remove_frame_from_view(self, index: int):
        """从视图中移除指定索引的帧"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement remove_frame_from_view()")

    def update_frame_in_view(self, index: int, frame_data: FrameData, filename: str):
        """更新视图中指定索引的帧"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement update_frame_in_view()")

    def refresh_view(self):
        """刷新整个视图"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement refresh_view()")

    def clear_view(self):
        """清空视图"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement clear_view()")

    def get_item_count(self) -> int:
        """获取视图中项的总数"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_item_count()")

    def block_selection_signals(self, block: bool):
        """阻塞或解除阻塞选择变化信号"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement block_selection_signals()")

    def select_all_optimized(self):
        """高效地选择所有项"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement select_all_optimized()")

    # ========== 可选的通用方法（子类可以重写）==========

    def set_theme_mode(self, is_dark: bool):
        """设置主题模式（亮/暗）"""
        # 默认实现：不做任何操作，子类可以重写
        pass

    def set_visual_reference_frame(self, frame_data: Optional[FrameData]):
        """设置视觉参考帧用于高亮显示"""
        # 默认实现：不做任何操作，子类可以重写
        pass

    def refresh_visuals(self):
        """刷新视觉元素（如参考帧高亮等）"""
        # 默认实现：不做任何操作，子类可以重写
        pass

    def on_selection_changed(self):
        """处理选择变化事件"""
        # 默认实现：不做任何操作，子类可以重写
        pass

    def get_selected_frame_data_list(self) -> List[FrameData]:
        """便利方法：获取选中的帧数据列表"""
        indices = self.get_selected_indices()
        frames = []
        for idx in indices:
            frame_data = self.get_frame_data_at_index(idx)
            if frame_data:
                frames.append(frame_data)
        return frames


class TimelineViewUtils:
    """
    工具类 - 提供静态方法供时间轴视图使用
    """

    @staticmethod
    def extract_frame_data_from_item(item) -> Optional[FrameData]:
        """
        从item中提取帧数据
        静态方法，可同时用于QTreeWidgetItem和QListWidgetItem
        """
        from PyQt6.QtCore import Qt
        if item is None:
            return None

        # 尝试常见的数据角色
        try:
            # 先尝试带列索引的（QTreeWidget常用）
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, FrameData):
                return data
        except (AttributeError, TypeError):
            pass

        try:
            # 再尝试不带列索引的（QListWidget常用）
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, FrameData):
                return data
        except (AttributeError, TypeError):
            pass

        return None
