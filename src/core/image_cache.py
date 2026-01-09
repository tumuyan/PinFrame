"""
全局图片缓存模块
提供统一的图片缓存管理，避免重复加载同一图片
"""

from PyQt6.QtGui import QImage
from typing import Optional
import os


class ImageCache:
    """
    单例图片缓存类
    所有组件共享同一个缓存实例，避免重复加载图片
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._max_size = 500  # 最大缓存数量
        return cls._instance
    
    def get(self, file_path: str, crop_rect: Optional[tuple] = None) -> Optional[QImage]:
        """
        获取图片，如果缓存中存在则直接返回，否则加载并缓存
        
        Args:
            file_path: 图片文件路径
            crop_rect: 可选的裁剪区域 (x, y, w, h)
            
        Returns:
            QImage 对象或 None（如果加载失败）
        """
        if not file_path or not os.path.exists(file_path):
            return None
            
        # 生成缓存键（完整路径，不考虑裁剪）
        cache_key = file_path
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 加载图片
        img = QImage(file_path)
        if img.isNull():
            return None
            
        # 检查缓存大小，必要时清理
        if len(self._cache) >= self._max_size:
            self._evict_oldest()
            
        self._cache[cache_key] = img
        return img
    
    def preload(self, file_paths: list) -> None:
        """
        预加载多个图片到缓存
        
        Args:
            file_paths: 图片路径列表
        """
        for path in file_paths:
            if path and path not in self._cache:
                self.get(path)
    
    def contains(self, file_path: str) -> bool:
        """检查缓存中是否存在指定图片"""
        return file_path in self._cache
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
    
    def remove(self, file_path: str) -> None:
        """从缓存中移除指定图片"""
        if file_path in self._cache:
            del self._cache[file_path]
    
    def _evict_oldest(self) -> None:
        """移除最早添加的缓存项（简单的 FIFO 策略）"""
        if self._cache:
            # Python 3.7+ dict 保持插入顺序
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
    
    @property
    def size(self) -> int:
        """返回当前缓存数量"""
        return len(self._cache)


# 全局缓存实例
image_cache = ImageCache()
