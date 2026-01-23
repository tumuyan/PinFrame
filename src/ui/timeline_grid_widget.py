from PyQt6.QtWidgets import (QWidget, QGridLayout, QLabel, QCheckBox, QFrame,
                              QScrollArea, QVBoxLayout, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QImage
from i18n.manager import i18n
import os
import re

class TimelineGridItem(QWidget):
    """单个网格项，包含缩略图、帧号、禁用标记和文件名"""
    clicked = pyqtSignal(object)  # frame_data
    checkbox_toggled = pyqtSignal(object, bool)  # frame_data, is_disabled
    
    def __init__(self, frame_data, index, image_cache, parent=None):
        super().__init__(parent)
        self.frame_data = frame_data
        self.index = index
        self.image_cache = image_cache
        self.pixmap = None
        
        # 设置默认大小
        self.setFixedSize(120, 150)  # 默认 120x120 缩略图 + 30px 文件名区域
        
        # 加载缩略图
        self.load_thumbnail()
        
        # 启用鼠标追踪以支持悬停
        self.setMouseTracking(True)
        
        # 悬停状态
        self._is_hovered = False
        
        # 文件名显示模式
        self._filename_line_mode = "single"  # "single" 或 "multiple"

        # 设置 tooltip
        self.update_tooltip()

    def update_tooltip(self):
        """更新 tooltip 显示完整文件名"""
        filename = os.path.basename(self.frame_data.file_path)

        # 如果有切割信息，添加到文件名
        if self.frame_data.crop_rect:
            x, y, w, h = self.frame_data.crop_rect
            col = x // w
            row = y // h
            filename += f" [{col},{row}]"

        # 设置 tooltip
        self.setToolTip(filename)

        
    def load_thumbnail(self):
        """从缓存加载缩略图"""
        try:
            qimage = self.image_cache.get(self.frame_data.file_path)
            if qimage:
                self.pixmap = QPixmap.fromImage(qimage)
        except Exception as e:
            self.pixmap = None
    
    def set_thumbnail_size(self, width, height):
        """设置缩略图大小"""
        # 总高度 = 缩略图高度 + 文件名区域高度
        filename_height = 30
        self.setFixedSize(width, height + filename_height)
        self.update()
    
    def set_filename_line_mode(self, mode):
        """设置文件名显示模式"""
        self._filename_line_mode = mode
        self.update()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.frame_data)
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)
    
    def get_elided_filename(self, painter, max_width):
        """获取省略后的文件名，优先保留序号"""
        filename = os.path.basename(self.frame_data.file_path)
        
        # 如果有切割信息，添加到文件名
        if self.frame_data.crop_rect:
            x, y, w, h = self.frame_data.crop_rect
            col = x // w
            row = y // h
            filename += f" [{col},{row}]"
        
        # 使用 QFontMetrics 测量文本宽度
        font = painter.font()
        font_metrics = QApplication.fontMetrics()
        
        if font_metrics.horizontalAdvance(filename) <= max_width:
            return filename
        
        # 尝试识别序号模式（如 image_001.jpg）
        # 正则匹配：文件名末尾的数字 + 扩展名
        name_without_ext = os.path.splitext(filename)[0]
        ext = os.path.splitext(filename)[1]
        
        # 查找文件名中的数字序列
        # 常见模式：image_001.jpg, sprite_002.png, frame.003.gif
        number_match = re.search(r'(\d+)(\.\w+)?$', filename)
        if number_match:
            # 找到序号
            number_part = number_match.group(1)
            # 尝试省略中间部分，保留前缀和序号
            prefix = filename[:number_match.start()]
            suffix = filename[number_match.start():]
            
            # 尝试省略前缀
            if len(prefix) > 10:
                # 省略前缀中间部分
                max_prefix_len = 8
                ellipsis = "..."
                prefix = prefix[:max_prefix_len]
                truncated = prefix + ellipsis + suffix
                
                if font_metrics.horizontalAdvance(truncated) <= max_width:
                    return truncated
            
            # 如果还不够，从后向前省略
            available_width = max_width - font_metrics.horizontalAdvance(suffix)
            if available_width > 20:
                prefix_elided = font_metrics.elidedText(prefix, Qt.TextElideMode.ElideLeft, int(available_width))
                return prefix_elided + suffix
        
        # 如果没有找到序号模式，使用标准省略
        return font_metrics.elidedText(filename, Qt.TextElideMode.ElideMiddle, int(max_width))
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 获取尺寸
        thumb_width = self.width()
        thumb_height = self.height() - 30  # 留出 30px 给文件名
        
        # 绘制背景
        bg_color = QColor(60, 60, 60) if self._is_hovered else QColor(45, 45, 45)
        painter.fillRect(0, 0, thumb_width, thumb_height, bg_color)
        
        # 绘制缩略图
        if self.pixmap:
            # 保持宽高比缩放
            scaled_pixmap = self.pixmap.scaled(
                thumb_width, thumb_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # 居中显示
            x = (thumb_width - scaled_pixmap.width()) // 2
            y = (thumb_height - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)
        else:
            # 如果没有图片，显示占位符
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(QRect(0, 0, thumb_width, thumb_height),
                           Qt.AlignmentFlag.AlignCenter,
                           i18n.t("msg_no_image"))
        
        # 绘制帧号（右上角）
        self.draw_frame_number(painter, thumb_width, thumb_height)
        
        # 绘制禁用标记（左上角）
        self.draw_disabled_marker(painter, thumb_width, thumb_height)
        
        # 绘制文件名
        self.draw_filename(painter, thumb_width, thumb_height)
        
        painter.end()
    
    def draw_frame_number(self, painter, width, height):
        """绘制帧号（右上角叠加）"""
        text = str(self.index)
        
        # 设置字体
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        
        # 计算文本大小
        font_metrics = painter.fontMetrics()
        text_width = font_metrics.horizontalAdvance(text)
        text_height = font_metrics.height()
        
        # 绘制半透明背景
        padding = 4
        bg_rect = QRect(
            width - text_width - padding * 2 - 4,
            4,
            text_width + padding * 2,
            text_height - 2
        )
        
        bg_color = QColor(0, 122, 204, 200)  # 蓝色半透明背景
        painter.fillRect(bg_rect, bg_color)
        
        # 绘制文本
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, text)
    
    def draw_disabled_marker(self, painter, width, height):
        """绘制禁用标记（左上角叠加）"""
        if not self.frame_data.is_disabled:
            return
        
        marker_size = 20
        
        # 绘制半透明红色背景
        bg_rect = QRect(4, 4, marker_size, marker_size)
        bg_color = QColor(255, 59, 48, 200)  # 红色半透明背景
        painter.fillRect(bg_rect, bg_color)
        
        # 绘制叉号
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        padding = 5
        painter.drawLine(bg_rect.left() + padding, bg_rect.top() + padding,
                        bg_rect.right() - padding, bg_rect.bottom() - padding)
        painter.drawLine(bg_rect.right() - padding, bg_rect.top() + padding,
                        bg_rect.left() + padding, bg_rect.bottom() - padding)
    
    def draw_filename(self, painter, width, height):
        """绘制文件名"""
        filename = os.path.basename(self.frame_data.file_path)
        
        # 如果有切割信息，添加到文件名
        if self.frame_data.crop_rect:
            x, y, w, h = self.frame_data.crop_rect
            col = x // w
            row = y // h
            filename += f" [{col},{row}]"
        
        # 设置字体
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        
        # 文件名区域
        filename_rect = QRect(0, height, width, 30)
        
        if self._filename_line_mode == "single":
            # 单行模式：使用智能省略
            elided_text = self.get_elided_filename(painter, width - 4)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(filename_rect.adjusted(2, 0, -2, 0), 
                           Qt.AlignmentFlag.AlignVCenter, elided_text)
        else:
            # 多行模式：自动换行
            painter.setPen(QColor(200, 200, 200))
            flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
            painter.drawText(filename_rect.adjusted(2, 2, -2, -2), flags, filename)


class TimelineGridWidget(QScrollArea):
    """网格视图容器"""
    selection_changed = pyqtSignal(list)
    item_double_clicked = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建容器部件
        self.container = QWidget()
        self.container_layout = QGridLayout(self.container)
        self.container_layout.setSpacing(8)
        self.container_layout.setContentsMargins(8, 8, 8, 8)
        
        self.setWidget(self.container)
        
        # 存储所有网格项
        self.grid_items = []
        
        # 配置
        self.thumbnail_width = 120
        self.thumbnail_height = 120
        self.filename_line_mode = "single"
        self.columns = 4  # 默认 4 列
        
        # 图片缓存
        self.image_cache = None
        
        # 选中的项
        self.selected_items = set()
    
    def set_image_cache(self, cache):
        """设置图片缓存"""
        self.image_cache = cache
    
    def set_thumbnail_size(self, width, height):
        """设置缩略图大小"""
        self.thumbnail_width = width
        self.thumbnail_height = height
        
        # 更新所有现有项
        for item in self.grid_items:
            item.set_thumbnail_size(width, height)
        
        # 重新计算列数
        self.recalculate_columns()
    
    def set_filename_line_mode(self, mode):
        """设置文件名显示模式"""
        self.filename_line_mode = mode
        for item in self.grid_items:
            item.set_filename_line_mode(mode)
    
    def set_columns(self, cols):
        """设置列数"""
        self.columns = cols
        self.rebuild_layout()
    
    def recalculate_columns(self):
        """根据宽度自动计算列数"""
        container_width = self.width() - 40  # 减去滚动条和边距
        if container_width > 0:
            new_cols = max(1, container_width // (self.thumbnail_width + 8))
            if new_cols != self.columns:
                self.columns = new_cols
                self.rebuild_layout()
    
    def resizeEvent(self, event):
        """窗口大小改变时重新计算列数"""
        super().resizeEvent(event)
        self.recalculate_columns()
    
    def clear(self):
        """清空网格"""
        for item in self.grid_items:
            item.deleteLater()
        self.grid_items.clear()
        self.selected_items.clear()
    
    def add_frame(self, frame_data, index):
        """添加一个帧到网格"""
        item = TimelineGridItem(frame_data, index, self.image_cache)
        item.set_thumbnail_size(self.thumbnail_width, self.thumbnail_height)
        item.set_filename_line_mode(self.filename_line_mode)
        item.clicked.connect(self.on_item_clicked)
        
        self.grid_items.append(item)
        self.rebuild_layout()
    
    def rebuild_layout(self):
        """重建网格布局"""
        # 清除现有布局
        for i in range(self.container_layout.count()):
            self.container_layout.itemAt(i).widget().setParent(None)
        
        # 重新添加所有项
        for i, item in enumerate(self.grid_items):
            row = i // self.columns
            col = i % self.columns
            self.container_layout.addWidget(item, row, col)
    
    def on_item_clicked(self, frame_data):
        """处理项点击事件"""
        # 如果是 Ctrl 键按下，多选
        modifiers = QApplication.keyboardModifiers()
        
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # 切换选择状态
            if frame_data in self.selected_items:
                self.selected_items.remove(frame_data)
            else:
                self.selected_items.add(frame_data)
        elif modifiers == Qt.KeyboardModifier.ShiftModifier:
            # Shift 键：范围选择
            if self.grid_items:
                # 找到点击的项的索引
                clicked_index = -1
                for i, item in enumerate(self.grid_items):
                    if item.frame_data == frame_data:
                        clicked_index = i
                        break
                
                if clicked_index >= 0 and self.selected_items:
                    # 找到最后一个选中项的索引
                    last_index = -1
                    for i, item in enumerate(self.grid_items):
                        if item.frame_data in self.selected_items:
                            last_index = i
                    
                    if last_index >= 0:
                        # 选择两个索引之间的所有项
                        start = min(clicked_index, last_index)
                        end = max(clicked_index, last_index)
                        for i in range(start, end + 1):
                            self.selected_items.add(self.grid_items[i].frame_data)
        else:
            # 单选
            self.selected_items.clear()
            self.selected_items.add(frame_data)
        
        self.selection_changed.emit(list(self.selected_items))
    
    def get_selected_frames(self):
        """获取选中的帧"""
        return list(self.selected_items)
    
    def select_all(self):
        """全选"""
        self.selected_items.clear()
        for item in self.grid_items:
            self.selected_items.add(item.frame_data)
        self.selection_changed.emit(list(self.selected_items))
    
    def clear_selection(self):
        """清除选择"""
        self.selected_items.clear()
        self.selection_changed.emit([])
    
    def update_visuals(self):
        """更新视觉效果（主题切换等）"""
        for item in self.grid_items:
            item.update()
