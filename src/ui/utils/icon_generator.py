from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPalette, QPen, QBrush, QPolygon, QPolygonF
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize

class IconGenerator:
    @staticmethod
    def play_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw right-pointing triangle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        
        points = [
            QPointF(size * 0.25, size * 0.2),
            QPointF(size * 0.25, size * 0.8),
            QPointF(size * 0.85, size * 0.5)
        ]
        painter.drawPolygon(QPolygonF(points))
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def reverse_play_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw left-pointing triangle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        
        points = [
            QPointF(size * 0.75, size * 0.2),
            QPointF(size * 0.75, size * 0.8),
            QPointF(size * 0.15, size * 0.5)
        ]
        painter.drawPolygon(QPolygonF(points))
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def pause_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        
        # Draw two vertical bars
        bar_width = size * 0.2
        bar_height = size * 0.6
        gap = size * 0.2
        
        # Left bar
        painter.drawRect(int((size - (2 * bar_width + gap)) / 2), int((size - bar_height) / 2), int(bar_width), int(bar_height))
        # Right bar
        painter.drawRect(int((size - (2 * bar_width + gap)) / 2 + bar_width + gap), int((size - bar_height) / 2), int(bar_width), int(bar_height))
        
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def onion_skin_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Darker base color for lower layers
        base_color = QColor(color)
        
        # Layer 1 (Back)
        painter.setPen(QPen(base_color.lighter(120), 1))
        painter.setBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 80))
        painter.drawRect(int(size * 0.2), int(size * 0.2), int(size * 0.5), int(size * 0.5))
        
        # Layer 2 (Middle)
        painter.setPen(QPen(base_color.lighter(140), 1))
        painter.setBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 140))
        painter.drawRect(int(size * 0.35), int(size * 0.35), int(size * 0.5), int(size * 0.5))
        
        # Layer 3 (Front - outline only or stronger fill)
        painter.setPen(QPen(base_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(int(size * 0.5), int(size * 0.5), int(size * 0.4), int(size * 0.4))
        
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def reference_frame_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # Frame
        painter.drawRect(int(size * 0.2), int(size * 0.2), int(size * 0.6), int(size * 0.6))
        
        # Pin icon at top right
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPoint(int(size * 0.8), int(size * 0.2)), int(size * 0.15), int(size * 0.15))
        
        painter.end()
        return QIcon(pixmap)
