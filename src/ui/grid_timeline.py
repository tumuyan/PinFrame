from PyQt6.QtWidgets import (QWidget, QGridLayout, QLabel, QScrollArea, QFrame, 
                             QVBoxLayout, QHBoxLayout, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QImage
from PIL import Image
import os
from i18n.manager import i18n

class GridTimelineItem(QFrame):
    """单个网格项组件"""
    clicked = pyqtSignal(object)  # frame_data
    double_clicked = pyqtSignal(object)  # frame_data
    context_menu_requested = pyqtSignal(object, object)  # frame_data, position
    
    def __init__(self, frame_data, thumbnail_size=128, is_dark_theme=True, parent=None):
        super().__init__(parent)
        self.frame_data = frame_data
        self.thumbnail_size = thumbnail_size
        self.is_dark_theme = is_dark_theme
        self.is_selected = False
        
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(thumbnail_size + 20, thumbnail_size + 50)  # padding for labels
        
        self.setup_ui()
        self.update_display()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        
        # 缩略图标签
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                border: 1px solid #666;
                background-color: #333;
                border-radius: 4px;
            }
        """)
        
        # 文件名标签
        self.filename_label = QLabel()
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filename_label.setWordWrap(True)
        self.filename_label.setMaximumHeight(30)
        font = self.filename_label.font()
        font.setPointSize(9)
        self.filename_label.setFont(font)
        
        # 状态信息标签（帧号和禁用状态）
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.status_label.font()
        font.setPointSize(8)
        self.status_label.setFont(font)
        self.status_label.setStyleSheet("color: #888;")
        
        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.filename_label)
        layout.addWidget(self.status_label)
        
        # 连接信号
        self.mousePressEvent = self._mouse_press_event
        self.mouseDoubleClickEvent = self._mouse_double_click_event
        self.contextMenuEvent = self._context_menu_event
        
    def _mouse_press_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.frame_data)
        super().mousePressEvent(event)
        
    def _mouse_double_click_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.frame_data)
        super().mouseDoubleClickEvent(event)
        
    def _context_menu_event(self, event):
        self.context_menu_requested.emit(self.frame_data, event.globalPos())
        super().contextMenuEvent(event)
        
    def update_display(self):
        """更新显示内容"""
        # 加载缩略图
        self.load_thumbnail()
        
        # 更新文件名显示
        fname = os.path.basename(self.frame_data.file_path)
        if self.frame_data.crop_rect:
            x, y, w, h = self.frame_data.crop_rect
            col = x // w
            row = y // h
            fname += f" [{col},{row}]"
        self.filename_label.setText(fname)
        
        # 更新状态信息
        frame_index = getattr(self, '_frame_index', 0)
        status_text = f"#{frame_index + 1}"
        if self.frame_data.is_disabled:
            status_text += " 🚫"
        self.status_label.setText(status_text)
        
        # 更新选中状态
        self.update_selection_style()
        
    def load_thumbnail(self):
        """加载缩略图"""
        try:
            if os.path.exists(self.frame_data.file_path):
                with Image.open(self.frame_data.file_path) as img:
                    # 转换为RGBA格式
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    # 计算缩略图尺寸（保持宽高比）
                    img_w, img_h = img.size
                    if img_w > img_h:
                        new_w = self.thumbnail_size
                        new_h = int(img_h * self.thumbnail_size / img_w)
                    else:
                        new_h = self.thumbnail_size
                        new_w = int(img_w * self.thumbnail_size / img_h)
                    
                    # 缩放图片
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    # 转换为QPixmap - 使用更简单的方法
                    from PyQt6.QtGui import QPixmap
                    from PyQt6.QtCore import QBuffer, QByteArray
                    
                    # 将PIL图像转换为字节数据
                    byte_array = QByteArray()
                    buffer = QBuffer(byte_array)
                    buffer.open(QBuffer.OpenModeFlag.ReadWrite)
                    img.save(buffer, "PNG")
                    buffer.close()
                    
                    # 从字节数据创建QPixmap
                    pixmap = QPixmap()
                    pixmap.loadFromData(byte_array, "PNG")
                    
                    # 创建带背景的QPixmap
                    final_pixmap = QPixmap(self.thumbnail_size, self.thumbnail_size)
                    final_pixmap.fill(QColor(0, 0, 0, 0))  # 透明背景
                    
                    painter = QPainter(final_pixmap)
                    # 将原始缩放后的图片绘制到居中位置
                    scaled_pixmap = pixmap.scaled(new_w, new_h, 
                                               Qt.AspectRatioMode.KeepAspectRatio, 
                                               Qt.TransformationMode.SmoothTransformation)
                    x = (self.thumbnail_size - scaled_pixmap.width()) // 2
                    y = (self.thumbnail_size - scaled_pixmap.height()) // 2
                    painter.drawPixmap(x, y, scaled_pixmap)
                    painter.end()
                    
                    self.thumbnail_label.setPixmap(final_pixmap)
            else:
                # 文件不存在，显示占位符
                self.thumbnail_label.setStyleSheet("""
                    QLabel {
                        border: 1px solid #666;
                        background-color: #222;
                        border-radius: 4px;
                        color: #666;
                    }
                """)
                self.thumbnail_label.setText("文件\n不存在")
                
        except Exception as e:
            # 加载失败，显示错误占位符
            self.thumbnail_label.setStyleSheet("""
                QLabel {
                    border: 1px solid #666;
                    background-color: #222;
                    border-radius: 4px;
                    color: #666;
                }
            """)
            self.thumbnail_label.setText("加载\n失败")
            
    def set_frame_index(self, index):
        """设置帧索引"""
        self._frame_index = index
        self.update_display()
        
    def set_selected(self, selected):
        """设置选中状态"""
        self.is_selected = selected
        self.update_selection_style()
        
    def update_selection_style(self):
        """更新选中状态样式"""
        if self.is_dark_theme:
            if self.is_selected:
                self.setStyleSheet("""
                    QFrame {
                        border: 2px solid #007ACC;
                        background-color: #2D2D30;
                        border-radius: 4px;
                    }
                """)
            else:
                self.setStyleSheet("""
                    QFrame {
                        border: 1px solid #666;
                        background-color: #252526;
                        border-radius: 4px;
                    }
                    QFrame:hover {
                        border-color: #888;
                        background-color: #2D2D30;
                    }
                """)
        else:
            if self.is_selected:
                self.setStyleSheet("""
                    QFrame {
                        border: 2px solid #007ACC;
                        background-color: #E7F3FF;
                        border-radius: 4px;
                    }
                """)
            else:
                self.setStyleSheet("""
                    QFrame {
                        border: 1px solid #CCCCCC;
                        background-color: #F8F8F8;
                        border-radius: 4px;
                    }
                    QFrame:hover {
                        border-color: #888;
                        background-color: #F0F0F0;
                    }
                """)

class GridTimelineWidget(QWidget):
    """网格视图时间轴组件"""
    selection_changed = pyqtSignal(list)
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.selected_frames = []
        self.thumbnail_size = 128
        self.is_dark_theme = True
        self.reference_frame_data = None
        
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 网格容器
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(10)
        
        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area)
        
    def set_frames(self, frames):
        """设置帧数据"""
        self.frames = frames
        self.refresh_display()
        
    def set_thumbnail_size(self, size):
        """设置缩略图尺寸"""
        self.thumbnail_size = size
        self.refresh_display()
        
    def set_theme_mode(self, is_dark):
        """设置主题模式"""
        self.is_dark_theme = is_dark
        # 更新所有子项的主题
        for child in self.findChildren(GridTimelineItem):
            child.is_dark_theme = is_dark
            child.update_selection_style()
            
    def set_reference_frame(self, frame_data):
        """设置参考帧"""
        self.reference_frame_data = frame_data
        # 更新视觉样式
        for child in self.findChildren(GridTimelineItem):
            if child.frame_data is frame_data:
                # 设置参考帧样式（加粗边框）
                if hasattr(child, '_original_style'):
                    child.setStyleSheet(child._original_style + """
                        QFrame {
                            border: 3px solid #FFD700;
                        }
                    """)
            else:
                # 恢复普通样式
                child.update_selection_style()
                
    def refresh_display(self):
        """刷新显示"""
        # 清除现有网格项
        for i in reversed(range(self.grid_layout.count())):
            child = self.grid_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
                
        # 重新添加所有帧
        cols = max(1, (self.width() - 30) // (self.thumbnail_size + 30))  # 计算列数
        for i, frame_data in enumerate(self.frames):
            row = i // cols
            col = i % cols
            
            item = GridTimelineItem(frame_data, self.thumbnail_size, self.is_dark_theme)
            item.set_frame_index(i)
            item.set_selected(frame_data in self.selected_frames)
            item.clicked.connect(self.on_item_clicked)
            item.double_clicked.connect(self.on_item_double_clicked)
            item.context_menu_requested.connect(self.show_context_menu)
            
            self.grid_layout.addWidget(item, row, col)
            
    def on_item_clicked(self, frame_data):
        """处理项点击事件"""
        if frame_data in self.selected_frames:
            self.selected_frames.remove(frame_data)
        else:
            self.selected_frames.append(frame_data)
            
        # 更新选择状态
        for child in self.findChildren(GridTimelineItem):
            child.set_selected(child.frame_data in self.selected_frames)
            
        self.selection_changed.emit(self.selected_frames)
        
    def on_item_double_clicked(self, frame_data):
        """处理项双击事件"""
        # 双击事件可以用于设置参考帧或其他操作
        pass
        
    def show_context_menu(self, frame_data, position):
        """显示上下文菜单"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu()
        
        selected_items = self.selected_items()
        has_selection = bool(selected_items)
        
        # 复制属性
        copy_action = QAction(i18n.t("action_copy_props"), self)
        copy_action.triggered.connect(self.copy_properties_requested.emit)
        copy_action.setEnabled(has_selection)
        
        # 粘贴属性
        paste_action = QAction(i18n.t("action_paste_props"), self)
        paste_action.triggered.connect(self.paste_properties_requested.emit)
        
        # 重复帧
        dup_action = QAction(i18n.t("action_dup_frame"), self)
        dup_action.triggered.connect(self.duplicate_requested.emit)
        dup_action.setEnabled(has_selection)
        
        # 删除帧
        rem_action = QAction(i18n.t("action_rem_frame"), self)
        rem_action.triggered.connect(self.remove_requested.emit)
        rem_action.setEnabled(has_selection)
        
        # 禁用/启用
        disable_action = QAction(i18n.t("disable_frame_label", "Disable Frame(s)"), self)
        disable_action.triggered.connect(lambda: self.enable_requested.emit(False))
        disable_action.setEnabled(has_selection)
        
        enable_action = QAction(i18n.t("enable_frame_label", "Enable Frame(s)"), self)
        enable_action.triggered.connect(lambda: self.enable_requested.emit(True))
        enable_action.setEnabled(has_selection)
        
        # 反转顺序
        reverse_action = QAction(i18n.t("action_reverse_order"), self)
        reverse_action.triggered.connect(self.reverse_order_requested.emit)
        reverse_action.setEnabled(len(selected_items) > 1)
        
        # 整数化偏移
        int_action = QAction(i18n.t("action_integerize"), self)
        int_action.triggered.connect(self.integerize_offset_requested.emit)
        int_action.setEnabled(has_selection)
        
        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.addSeparator()
        menu.addAction(int_action)
        menu.addSeparator()
        menu.addAction(disable_action)
        menu.addAction(enable_action)
        menu.addAction(reverse_action)
        menu.addSeparator()
        
        # 参考帧操作
        ref_action = QAction(i18n.t("action_set_reference"), self)
        ref_action.triggered.connect(self.set_reference_requested.emit)
        ref_action.setEnabled(len(selected_items) == 1)
        
        clear_ref_action = QAction(i18n.t("action_clear_reference"), self)
        clear_ref_action.triggered.connect(self.clear_reference_requested.emit)
        
        menu.addAction(ref_action)
        menu.addAction(clear_ref_action)
        menu.addSeparator()
        
        menu.addAction(dup_action)
        menu.addAction(rem_action)
        
        menu.exec(position)
        
    def selected_items(self):
        """获取选中的项"""
        return self.selected_frames
        
    def clear_selection(self):
        """清除选择"""
        self.selected_frames.clear()
        for child in self.findChildren(GridTimelineItem):
            child.set_selected(False)
        self.selection_changed.emit(self.selected_frames)
        
    def select_all(self):
        """全选"""
        self.selected_frames = self.frames.copy()
        for child in self.findChildren(GridTimelineItem):
            child.set_selected(True)
        self.selection_changed.emit(self.selected_frames)
        
    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        # 延迟刷新以避免频繁重绘
        QTimer.singleShot(100, self.refresh_display)