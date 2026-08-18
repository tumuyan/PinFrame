"""可识别的图像格式管理模块。

集中管理应用可导入/识别的图像文件后缀（扩展名）。
默认支持现有的格式：.png .jpg .jpeg .bmp .gif。
用户可在"图像 → 图像格式设置"中自定义（持久化到 QSettings）。

所有需要判断"是否为可识别的图像文件"的入口都应调用本模块，
避免硬编码后缀集合导致导入与预览不一致。
"""
import os

from PyQt6.QtCore import QSettings

# 默认支持的图像格式（统一小写、带点前缀，供比较时统一大小写）
_DEFAULT_FORMATS = [".png", ".jpg", ".jpeg", ".bmp", ".gif"]

# QSettings 键名
_SETTINGS_KEY = "recognized_image_formats"

# 模块级缓存：避免 _load() 每次调用都重复读磁盘；在 save/reset 时失效
_cached_formats = None


def _load() -> list:
    """从 QSettings 读取用户自定义的格式列表；为空时返回默认列表。

    结果带模块级缓存，避免批量场景（如遍历调用 is_supported）重复 I/O。
    缓存仅在 save_formats / reset_to_default 时失效。
    """
    global _cached_formats
    if _cached_formats is not None:
        return _cached_formats
    settings = QSettings("tumuyan", "PinFrame")
    raw = settings.value(_SETTINGS_KEY, None)
    if not raw:
        _cached_formats = list(_DEFAULT_FORMATS)
        return _cached_formats
    # 归一化：统一小写、确保带点前缀、去掉空项
    normalized = []
    for item in raw:
        if not item:
            continue
        ext = item.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in normalized:
            normalized.append(ext)
    _cached_formats = normalized or list(_DEFAULT_FORMATS)
    return _cached_formats


def save_formats(formats: list) -> None:
    """保存用户自定义的格式列表到 QSettings。"""
    global _cached_formats
    settings = QSettings("tumuyan", "PinFrame")
    settings.setValue(_SETTINGS_KEY, [f.lower().strip() for f in formats])
    _cached_formats = None  # 使缓存失效，下次读取重新加载


def reset_to_default() -> None:
    """恢复默认格式（从 QSettings 中删除自定义项）。"""
    global _cached_formats
    settings = QSettings("tumuyan", "PinFrame")
    settings.remove(_SETTINGS_KEY)
    _cached_formats = None  # 使缓存失效，下次读取重新加载


def supported_formats() -> list:
    """返回归一化后的受支持格式列表（带点、小写）。"""
    # 返回副本，避免调用方修改污染内部缓存
    return list(_load())


def supported_extensions() -> set:
    """返回受支持格式的后缀集合（带点、小写），便于快速判断。"""
    return set(_load())


def is_supported(path: str) -> bool:
    """判断给定文件路径（或后缀）是否为受支持的图像格式。"""
    if not path:
        return False
    _, ext = os.path.splitext(path)
    return ext.lower() in supported_extensions()


def filter_string(label: str) -> str:
    """生成 QFileDialog 使用的过滤字符串。

    label 为可读描述（如 i18n.t('dlg_filter_images')），返回
    "描述 (*.png *.jpg ...)" 形式。
    """
    exts = supported_formats()
    if not exts:
        return label
    pattern = " ".join("*%s" % e for e in exts)
    return "%s (%s)" % (label, pattern)
