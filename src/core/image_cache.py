"""
全局图片缓存模块
提供统一的图片缓存管理，避免重复加载同一图片
"""

from collections import OrderedDict

from PyQt6.QtGui import QImage
from typing import Optional
import os

# 默认字节预算：512 MiB。
#
# 为什么按字节而不是按张数（见 dev/architecture_review.md 的 P2-7）：张数上限对
# 内存毫无约束 —— 500 张 4096×4096 RGBA ≈ 32 GB，而 500 张 64×64 图标只有 8 MB，
# 两者占用的资源差三个数量级却同样"命中上限"。字节预算才是真正的约束量。
DEFAULT_MAX_BYTES = 512 * 1024 * 1024


def _image_bytes(img: QImage) -> int:
    """一张 QImage 的像素内存（字节）。

    算的是**解码后**的内存，与文件体积无关 —— 一张压缩率极高的 PNG 展开后可能是
    文件大小的几十倍；`sizeInBytes()` 已计入每行的对齐填充。

    不做回退：`sizeInBytes()` 自 Qt 5.10 起存在，PyQt6 必然有；调用点也都在
    `isNull()` 之后（或取自缓存），`img` 必然非空（空图调用它也返回 0，实测）。
    """
    return img.sizeInBytes()


class ImageCache:
    """
    单例图片缓存类
    所有组件共享同一个缓存实例，避免重复加载图片

    两个刻意的设计（P2-7）：

    - **上限是字节预算，不是张数**（`_max_bytes`）。张数上限挡不住"500 张 4K 图
      吃满 32 GB"，而它同时又会过早淘汰 500 张小图标。
    - **淘汰是 LRU，不是 FIFO**。FIFO 只看插入顺序，于是"工程一打开就预加载、之后
      每帧都在用"的那张图，会先于"加载进来后再没碰过"的图被踢掉 —— 而缓存的意义
      恰恰在于保住反复访问的那几张。

    缓存按**路径**索引，与裁切无关：`crop_rect` 曾经是 `get()` 的一个参数，但内部
    从不参与 key 计算，全项目也没有一个调用点传它 —— 它唯一的作用是诱导下一个人
    以为传了就能按裁切区缓存。已删除。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = OrderedDict()
            cls._instance._total_bytes = 0
            cls._instance._max_bytes = DEFAULT_MAX_BYTES
        return cls._instance

    def get(self, file_path: str) -> Optional[QImage]:
        """
        获取图片，如果缓存中存在则直接返回，否则加载并缓存

        Args:
            file_path: 图片文件路径

        Returns:
            QImage 对象或 None（如果加载失败）
        """
        if not file_path or not os.path.exists(file_path):
            return None

        # 生成缓存键（完整路径）
        cache_key = file_path

        cached = self._cache.get(cache_key)
        if cached is not None:
            # 命中即升为最近使用 —— LRU 与 FIFO 的全部区别就在这一行
            self._cache.move_to_end(cache_key)
            return cached

        # 加载图片
        img = QImage(file_path)
        if img.isNull():
            return None

        size = _image_bytes(img)
        self._evict_to_fit(size)

        self._cache[cache_key] = img
        self._total_bytes += size
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
        self._total_bytes = 0

    def remove(self, file_path: str) -> None:
        """从缓存中移除指定图片"""
        img = self._cache.pop(file_path, None)
        if img is not None:
            self._total_bytes -= _image_bytes(img)

    def set_budget(self, max_bytes: int) -> None:
        """设置字节预算并立即淘汰到预算之内。

        存在的意义是**可测**：512 MiB 的预算装不进单测，而预算逻辑正是本类最容易
        写错的地方（张数 / 字节、FIFO / LRU 各错一次就都白改）。
        """
        self._max_bytes = max(0, int(max_bytes))
        self._evict_to_fit(0)

    def _evict_to_fit(self, incoming_bytes: int) -> None:
        """淘汰最久未使用的条目，直到能再放下 `incoming_bytes`。

        刻意**不会**淘汰本次正要放进去的那张：它此刻还不在缓存里，即使单张就超过
        预算也照留 —— 否则大图会被"放进即踢"，每次访问都重新解码，比不缓存更慢
        （那时 `total_bytes` 允许超过预算，这是有意的）。
        """
        while self._cache and self._total_bytes + incoming_bytes > self._max_bytes:
            self._drop_lru()

    def _drop_lru(self) -> None:
        """移除最久未使用的缓存项"""
        if not self._cache:
            return
        _, img = self._cache.popitem(last=False)  # OrderedDict 头部即 LRU
        self._total_bytes -= _image_bytes(img)

    @property
    def size(self) -> int:
        """返回当前缓存数量"""
        return len(self._cache)

    @property
    def total_bytes(self) -> int:
        """返回当前缓存占用的像素内存（字节）"""
        return self._total_bytes

    @property
    def max_bytes(self) -> int:
        """返回当前字节预算"""
        return self._max_bytes


# 全局缓存实例
image_cache = ImageCache()
