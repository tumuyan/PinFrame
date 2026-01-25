from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon
from typing import Optional


class TimelineGridDelegate(QStyledItemDelegate):
    """Custom delegate for timeline grid view that draws frame numbers on items"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_number_font = QFont("Arial", 10, QFont.Weight.Bold)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint the item with frame number overlay"""
        # Call parent implementation to draw the base item (icon and text)
        super().paint(painter, option, index)

        # Draw frame number overlay on the icon
        widget = option.widget
        if widget is None:
            return

        # For QListWidget, use widget.itemFromIndex() instead of model.itemFromIndex()
        item = widget.itemFromIndex(index)
        if item is None:
            return

        # Get frame data from item
        frame_data = item.data(Qt.ItemDataRole.UserRole)
        if frame_data is None:
            return

        # Get the icon rectangle (should be at the top of the item)
        icon_rect = self._get_icon_rect(option)

        if icon_rect is None or icon_rect.isEmpty():
            return

        # Draw frame number
        frame_number = index.row() + 1
        self._draw_frame_number(painter, icon_rect, frame_number)

        # Draw disabled overlay if needed
        if frame_data.is_disabled:
            self._draw_disabled_overlay(painter, icon_rect)

    def _get_icon_rect(self, option: QStyleOptionViewItem) -> Optional[QRectF]:
        """Calculate the icon rectangle from the item option"""
        # In IconMode, the icon is typically centered and sized according to iconSize
        # The rect we need is where the icon is drawn, excluding the text area at the bottom

        # For IconMode, the icon occupies the top portion of the item rect
        # We can estimate this based on the option.rect and the widget's iconSize
        widget = option.widget
        if widget is None:
            return None

        icon_size = widget.iconSize()
        if icon_size.isEmpty():
            return None

        # Calculate icon position (centered horizontally, at the top vertically)
        x = option.rect.x() + (option.rect.width() - icon_size.width()) // 2
        y = option.rect.y()

        return QRectF(x, y, icon_size.width(), icon_size.height())

    def _draw_frame_number(self, painter: QPainter, icon_rect: QRectF, frame_number: int):
        """Draw frame number on the icon"""
        # Save painter state
        painter.save()

        # Set up text
        text = str(frame_number)

        # Add semi-transparent background for text readability
        text_bg_rect = QRectF(
            icon_rect.right() - 32,
            icon_rect.bottom() - 25,
            30,
            20
        )
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(text_bg_rect, 3, 3)

        # Draw text
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.frame_number_font)
        painter.drawText(text_bg_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)

        # Restore painter state
        painter.restore()

    def _draw_disabled_overlay(self, painter: QPainter, icon_rect: QRectF):
        """Draw semi-transparent overlay for disabled items"""
        painter.save()
        painter.fillRect(icon_rect, QColor(0, 0, 0, 120))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        """Return the size hint for the item"""
        # Let the widget handle sizing
        return super().sizeHint(option, index)
