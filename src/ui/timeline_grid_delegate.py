from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
from PyQt6.QtCore import Qt, QSize, QRectF, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon, QFontMetrics
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TimelineGridDelegate(QStyledItemDelegate):
    """Custom delegate for timeline grid view that draws frame numbers and multiline text on items"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_number_font = QFont("Arial", 10, QFont.Weight.Bold)
        self.show_multiline = False
        self._log_printed = False  # Flag to ensure only first frame logs

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint item with frame number overlay"""
        # Get widget and item first
        widget = option.widget
        if widget is None:
            super().paint(painter, option, index)
            return

        item = widget.itemFromIndex(index)
        if item is None:
            super().paint(painter, option, index)
            return

        # Get frame data from item
        frame_data = item.data(Qt.ItemDataRole.UserRole)
        if frame_data is None:
            super().paint(painter, option, index)
            return

        # Save painter state
        painter.save()

        # Draw background and icon using Qt's default implementation
        super().paint(painter, option, index)

        # Calculate icon position
        icon_size = widget.iconSize()
        icon_rect = QRectF(
            option.rect.x() + (option.rect.width() - icon_size.width()) // 2,
            option.rect.y(),
            icon_size.width(),
            icon_size.height()
        )

        # Draw frame number overlay
        frame_number = index.row() + 1
        self._draw_frame_number(painter, icon_rect, frame_number)

        # Draw disabled overlay if needed
        if frame_data.is_disabled:
            self._draw_disabled_overlay(painter, icon_rect)

        # Draw custom multiline text
        self._draw_custom_text(painter, option, item, index)

        # Restore painter state
        painter.restore()

    def _draw_custom_text(self, painter: QPainter, option: QStyleOptionViewItem, item, index):
        """Draw the item text (filename) with smart truncation"""
        text = item.text()
        if not text:
            return

        # Get font from item or use default
        font = item.font()
        if font is None:
            font = QFont()

        # Calculate text rectangle
        icon_size = option.widget.iconSize()
        text_top = option.rect.y() + icon_size.height() + 4
        text_height = option.rect.height() - icon_size.height() - 8
        text_rect = QRectF(
            option.rect.x() + 2,
            text_top,
            option.rect.width() - 4,
            text_height
        )

        # Log debug info for first frame only
        debug = index.row() == 0 and not self._log_printed
        if debug:
            fm = QFontMetrics(font)
            print(f"[GridText Debug] First frame text info:")
            print(f"  - Original text: '{text}'")
            print(f"  - Text length: {len(text)} chars")
            print(f"  - Item rect: {option.rect.width()}x{option.rect.height()}")
            print(f"  - Icon size: {icon_size.width()}x{icon_size.height()}")
            print(f"  - Text rect: {text_rect.width():.1f}x{text_rect.height():.1f}")
            print(f"  - Font: {font.family()}, size: {font.pointSize()}pt")
            print(f"  - Font metrics height: {fm.height()}, ascent: {fm.ascent()}")
            print(f"  - Text width: {fm.horizontalAdvance(text)}")
            print(f"  - Multiline mode: {self.show_multiline}")
            if self.show_multiline:
                available_lines = int(text_rect.height()) // fm.height()
                print(f"  - Available lines: {available_lines}")

        # Clear the default text drawn by super().paint()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(text_rect, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Get text color based on selection state
        if option.state & QStyle.StateFlag.State_Selected:
            text_color = QColor(255, 255, 255)
        else:
            text_color = option.palette.text().color()

        painter.setFont(font)
        painter.setPen(text_color)

        # Draw text based on mode
        if self.show_multiline:
            # Multiline mode: calculate available lines and truncate accordingly
            display_lines = self._get_multiline_display_text(text, font, text_rect, debug)

            # Log processed text for first frame
            if debug:
                print(f"  - Processed lines ({len(display_lines)}):")
                for i, line in enumerate(display_lines):
                    line_width = QFontMetrics(font).horizontalAdvance(line)
                    print(f"      [{i}] '{line}' (width: {line_width}, rect_width: {text_rect.width():.1f})")
                self._log_printed = True  # Mark as printed after all logs

            self._draw_multiline_truncated(painter, display_lines, text_rect, font)
        else:
            # Single line mode: simple smart truncation
            display_text = self._truncate_text_smartly(text, font, text_rect.width())

            # Log processed text for first frame
            if debug:
                display_width = QFontMetrics(font).horizontalAdvance(display_text)
                print(f"  - Processed text: '{display_text}' (width: {display_width}, rect_width: {text_rect.width():.1f})")
                self._log_printed = True  # Mark as printed after all logs

            painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, display_text)

    def _get_multiline_display_text(self, text: str, font: QFont, text_rect: QRectF, debug: bool = False) -> list:
        """Get display text lines for multiline mode based on available height"""
        import re

        fm = QFontMetrics(font)
        line_height = fm.height()
        available_height = int(text_rect.height())
        num_lines = available_height // line_height

        if debug:
            print(f"  - [Algorithm] num_lines={num_lines}, line_height={line_height}, available_height={available_height}")

        # If text fits in a single line, return it
        if fm.horizontalAdvance(text) <= text_rect.width():
            if debug:
                print(f"  - [Algorithm] Text fits in single line, returning as-is")
            return [text]

        # Check for virtual slice position suffix (e.g., " [1,1]")
        slice_match = re.search(r' \[\d+,\d+\]$', text)

        if slice_match:
            # Extract main filename and slice position
            # Slice position is NOT part of the 7 characters to keep
            main_text = text[:slice_match.start()]      # Filename only, without slice position
            slice_suffix = text[slice_match.start():]   # e.g., " [1,1]"

            # Keep last 7 characters of main_filename (excluding slice position)
            if len(main_text) >= 7:
                main_prefix = main_text[:-7]  # Part that can be split across lines
                main_suffix = main_text[-7:]     # Last 7 chars of filename, must be complete
            else:
                main_prefix = ""
                main_suffix = main_text

            # Calculate space needed for slice suffix and main suffix
            slice_width = fm.horizontalAdvance(slice_suffix)
            main_suffix_width = fm.horizontalAdvance(main_suffix)
            ellipsis_width = fm.horizontalAdvance("...")

            if debug:
                print(f"  - [Algorithm] main_text='{main_text}', slice_suffix='{slice_suffix}'")
                print(f"  - [Algorithm] main_prefix='{main_prefix}', main_suffix='{main_suffix}'")
                print(f"  - [Algorithm] slice_width={slice_width}, main_suffix_width={main_suffix_width}")

            # Try to fit as much as possible across multiple lines
            lines = []
            remaining_text = main_prefix

            for line_num in range(num_lines):
                # Check if this is the last line
                is_last_line = (line_num == num_lines - 1)

                if debug:
                    print(f"  - [Algorithm] Processing line {line_num}, is_last={is_last_line}, remaining='{remaining_text}'")

                if is_last_line:
                    # Last line must contain: remaining_text + main_suffix + slice_suffix
                    if len(remaining_text) == 0:
                        # No more prefix, just show suffix + slice
                        lines.append(main_suffix + slice_suffix)
                        break

                    # Check if everything fits
                    full_line = remaining_text + main_suffix + slice_suffix
                    if fm.horizontalAdvance(full_line) <= text_rect.width():
                        lines.append(full_line)
                        break

                    # Try to fit remaining_text + main_suffix + slice_suffix with truncation
                    # Space available for remaining_text
                    available_width = text_rect.width() - main_suffix_width - slice_width

                    if available_width <= 0:
                        # Not enough space, just show suffix + slice (maybe with ellipsis if needed)
                        if fm.horizontalAdvance(main_suffix + slice_suffix) <= text_rect.width():
                            lines.append(main_suffix + slice_suffix)
                        else:
                            # Still doesn't fit, truncate suffix with ellipsis
                            available_for_suffix = text_rect.width() - slice_width - ellipsis_width
                            suffix_split = self._find_best_split_point(fm, main_suffix, available_for_suffix, debug)
                            if suffix_split > 0:
                                lines.append(main_suffix[:suffix_split] + "..." + slice_suffix)
                            else:
                                lines.append("..." + slice_suffix)
                        break

                    # Try to fit as much of remaining_text as possible
                    best_split = self._find_best_split_point(fm, remaining_text, available_width, debug)

                    if best_split > 0:
                        # We can show some of the remaining_text
                        lines.append(remaining_text[:best_split] + main_suffix + slice_suffix)
                    else:
                        # Can't fit any of remaining_text, show suffix directly
                        if fm.horizontalAdvance(main_suffix + slice_suffix) <= text_rect.width():
                            lines.append(main_suffix + slice_suffix)
                        else:
                            # Truncate suffix with ellipsis
                            available_for_suffix = text_rect.width() - slice_width - ellipsis_width
                            suffix_split = self._find_best_split_point(fm, main_suffix, available_for_suffix, debug)
                            if suffix_split > 0:
                                lines.append(main_suffix[:suffix_split] + "..." + slice_suffix)
                            else:
                                lines.append("..." + slice_suffix)
                    break
                else:
                    # Not the last line: fit as much of main_prefix as possible
                    if len(remaining_text) == 0:
                        # No more prefix to display, we're done
                        if debug:
                            print(f"  - [Algorithm] No more remaining_text, done")
                        break

                    if fm.horizontalAdvance(remaining_text) <= text_rect.width():
                        # All remaining prefix fits, but we need to continue to next lines
                        # for main_suffix + slice_suffix
                        if debug:
                            print(f"  - [Algorithm] All remaining fits: '{remaining_text}'")
                        lines.append(remaining_text)
                        remaining_text = ""
                        # DON'T break here - continue to process remaining lines for suffix
                    else:
                        # Find the best split point
                        split_pos = self._find_best_split_point(fm, remaining_text, text_rect.width(), debug)
                        if debug:
                            print(f"  - [Algorithm] Split at pos {split_pos}: '{remaining_text[:split_pos]}'")
                        lines.append(remaining_text[:split_pos])
                        remaining_text = remaining_text[split_pos:]

            return lines
        else:
            # No slice suffix, try to fit across multiple lines
            lines = []
            remaining_text = text

            # Keep last 7 characters complete
            if len(text) >= 7:
                prefix = text[:-7]
                suffix = text[-7:]
            else:
                prefix = ""
                suffix = text

            suffix_width = fm.horizontalAdvance(suffix)

            for line_num in range(num_lines):
                # Check if this is the last line
                is_last_line = (line_num == num_lines - 1)

                if is_last_line:
                    # Last line must contain the suffix
                    if len(prefix) == 0:
                        # No more prefix, just show suffix
                        lines.append(suffix)
                        break

                    # Try to fit prefix + suffix
                    full_line = prefix + suffix
                    if fm.horizontalAdvance(full_line) <= text_rect.width():
                        lines.append(full_line)
                        break

                    # Need to truncate prefix to fit suffix
                    available_width = text_rect.width() - suffix_width

                    if available_width <= 0:
                        # Not enough space for suffix, use smart truncation
                        truncated_line = self._truncate_text_smartly(prefix + suffix, font, text_rect.width())
                        lines.append(truncated_line)
                        break

                    best_split = self._find_best_split_point(fm, prefix, available_width, debug)
                    if best_split > 0:
                        lines.append(prefix[:best_split] + suffix)
                    else:
                        # Can't fit prefix, use smart truncation on suffix
                        truncated_line = self._truncate_text_smartly(suffix, font, text_rect.width())
                        lines.append(truncated_line)
                    break
                else:
                    # Not the last line: fit as much of prefix as possible
                    if len(prefix) == 0:
                        break

                    if fm.horizontalAdvance(prefix) <= text_rect.width():
                        lines.append(prefix)
                        prefix = ""
                        # DON'T break here - continue to process remaining lines for suffix
                    else:
                        split_pos = self._find_best_split_point(fm, prefix, text_rect.width(), debug)
                        lines.append(prefix[:split_pos])
                        prefix = prefix[split_pos:]

            return lines

    def _find_best_split_point(self, fm: QFontMetrics, text: str, max_width: int, debug: bool = False) -> int:
        """Find the best position to split text (prefer word boundaries)"""
        if not text:
            return 0

        text_width = fm.horizontalAdvance(text)

        # If entire text fits, return its length
        if text_width <= max_width:
            if debug:
                print(f"    [SplitPoint] '{text}' fits (width={text_width}, max={max_width}), return {len(text)}")
            return len(text)

        # Try to split at spaces (word boundaries)
        words = text.split(' ')
        if len(words) > 1:
            # Build lines from words
            current_line = words[0]
            for i, word in enumerate(words[1:], 1):
                test_line = current_line + ' ' + word
                if fm.horizontalAdvance(test_line) <= max_width:
                    current_line = test_line
                else:
                    # This word doesn't fit, return the position before it
                    if debug:
                        print(f"    [SplitPoint] Split at word boundary: '{current_line}' (len={len(current_line)})")
                    return len(current_line)

            # All words fit
            if debug:
                print(f"    [SplitPoint] All words fit: '{current_line}' (len={len(current_line)})")
            return len(current_line)

        # No spaces, split character by character
        for i in range(len(text), 0, -1):
            if fm.horizontalAdvance(text[:i]) <= max_width:
                if debug:
                    print(f"    [SplitPoint] No spaces, char-by-char split at {i}: '{text[:i]}' (width={fm.horizontalAdvance(text[:i])})")
                return i

        # Nothing fits
        if debug:
            print(f"    [SplitPoint] WARNING: Nothing fits in max_width={max_width}, text_width={text_width}")
        return 0

        return 0

    def _draw_multiline_truncated(self, painter: QPainter, lines: list, text_rect: QRectF, font: QFont):
        """Draw multiline text with truncation"""
        fm = QFontMetrics(font)
        line_height = fm.height()

        # Calculate starting Y position (top aligned)
        y_pos = int(text_rect.top() + fm.ascent())

        for line in lines:
            # Check if we've exceeded the text area
            if y_pos > text_rect.bottom():
                break

            # Calculate x position for centered text
            x_pos = int(text_rect.center().x() - fm.horizontalAdvance(line) / 2)

            # Draw the line
            painter.drawText(x_pos, y_pos, line)

            # Move to next line
            y_pos += line_height

    def _truncate_text_smartly(self, text: str, font: QFont, max_width: int) -> str:
        """Truncate text intelligently: keep first part + ... + last 7 chars + slice position"""
        import re

        fm = QFontMetrics(font)
        full_width = fm.horizontalAdvance(text)

        # If text fits, return as is
        if full_width <= max_width:
            return text

        # Check for virtual slice position suffix (e.g., " [1,1]")
        slice_match = re.search(r' \[\d+,\d+\]$', text)

        if slice_match:
            # Extract main filename and slice position
            main_text = text[:slice_match.start()]
            slice_suffix = text[slice_match.start():]

            # Keep last 7 characters of main text
            if len(main_text) > 7:
                main_suffix = main_text[-7:]
            else:
                main_suffix = main_text

            # Build truncated text: prefix + ... + suffix + slice position
            # Start from half the length and reduce until it fits
            prefix_len = len(main_text) // 2
            while prefix_len > 0:
                truncated = main_text[:prefix_len] + "..." + main_suffix + slice_suffix
                if fm.horizontalAdvance(truncated) <= max_width:
                    return truncated
                prefix_len -= 1

            # If still too long, just show suffix + slice position
            return "..." + main_suffix + slice_suffix
        else:
            # No slice suffix, keep last 7 characters
            if len(text) > 7:
                text_suffix = text[-7:]
            else:
                text_suffix = text

            # Build truncated text: prefix + ... + suffix
            prefix_len = len(text) // 2
            while prefix_len > 0:
                truncated = text[:prefix_len] + "..." + text_suffix
                if fm.horizontalAdvance(truncated) <= max_width:
                    return truncated
                prefix_len -= 1

            # If still too long, just show suffix
            return "..." + text_suffix

    def _get_icon_rect(self, option: QStyleOptionViewItem) -> Optional[QRectF]:
        """Calculate the icon rectangle from the item option"""
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
        # Use the widget's grid size as size hint
        widget = option.widget
        if widget is not None:
            return widget.gridSize()
        return super().sizeHint(option, index)

    def set_show_multiline(self, multiline: bool):
        """Set whether to show multiline text"""
        self.show_multiline = multiline

    def reset_log_flag(self):
        """Reset log flag for new painting cycle"""
        self._log_printed = False
