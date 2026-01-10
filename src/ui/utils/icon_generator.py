from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPalette, QPen, QBrush, QPolygon, QPolygonF
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize, QRect

class IconGenerator:
    PEN_WIDTH = 2
    BORDER_WIDTH = 1

    @staticmethod
    def play_icon(color: QColor, size: int = 32) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw right-pointing triangle with black stroke
        painter.setPen(QPen(Qt.GlobalColor.black, IconGenerator.BORDER_WIDTH))
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
        
        # Draw left-pointing triangle with black stroke
        painter.setPen(QPen(Qt.GlobalColor.black, IconGenerator.BORDER_WIDTH))
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
        painter.setPen(QPen(base_color, IconGenerator.PEN_WIDTH))
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
        
        pen = QPen(color, IconGenerator.PEN_WIDTH)
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

    @staticmethod
    def create_pixmap(name: str, color: QColor, size: int = 32) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(color, IconGenerator.PEN_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        if name == "arrow_expand":
            # Zoom Icon (Magnifying Glass)
            # Circle
            cx, cy = int(size*0.45), int(size*0.45)
            r = int(size*0.25)
            painter.drawEllipse(QPoint(cx, cy), r, r)
            # Handle
            painter.drawLine(int(size*0.65), int(size*0.65), int(size*0.85), int(size*0.85))
            
        elif name == "image":
            # Image Icon (Scale)
            # Rect
            rect = QRect(int(size*0.15), int(size*0.25), int(size*0.7), int(size*0.5))
            painter.drawRect(rect)
            # Mountain/Sun hints
            painter.drawLine(int(size*0.15), int(size*0.65), int(size*0.35), int(size*0.4))
            painter.drawLine(int(size*0.35), int(size*0.4), int(size*0.55), int(size*0.65))
            # Small sun
            painter.drawEllipse(QPoint(int(size*0.7), int(size*0.35)), 2, 2)
        
        painter.end()
        return pixmap

    @staticmethod
    def rasterization_icon(color: QColor, size: int = 32) -> QIcon:
        """Create a pixel grid icon representing rasterization."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # No anti-aliasing for pixelated look
        
        # Draw pixel grid
        grid_size = 4  # 4x4 grid
        cell_size = size // grid_size
        
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # Draw grid lines
        for i in range(grid_size + 1):
            pos = i * cell_size
            painter.drawLine(pos, 0, pos, size)  # Vertical lines
            painter.drawLine(0, pos, size, pos)  # Horizontal lines
        
        # Fill alternating cells to show pixelated effect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 100))
        
        for row in range(grid_size):
            for col in range(grid_size):
                if (row + col) % 2 == 0:
                    painter.drawRect(col * cell_size, row * cell_size, cell_size, cell_size)
        
        painter.end()
        return QIcon(pixmap)
