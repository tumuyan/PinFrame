from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
from PyQt6.QtCore import Qt, QSize, QRectF, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon, QFontMetrics, QBrush
from typing import Optional
import logging
from ui.timeline_item_model import FrameDataRole, ReferenceRole, ThumbnailRole
from ui.timeline_selection_style import SELECTED_BG_QCOLOR, SELECTED_FG_QCOLOR
from utils.debug_config import grid_text_debug, grid_text_debug_lines

logger = logging.getLogger(__name__)


class TimelineGridDelegate(QStyledItemDelegate):
    """Custom delegate for timeline grid view that draws frame numbers and multiline text on items"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame_number_font = QFont("Arial", 10, QFont.Weight.Bold)
        self.show_multiline = False
        self._log_printed = False  # Flag to ensure only first frame logs

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint item with frame number overlay.

        数据全部**按 index 现取**（`FrameDataRole` / `ThumbnailRole`），视图侧不存
        任何副本 —— 迁移前是从 `widget.itemFromIndex(index)` 拿 `QListWidgetItem`
        再读它的 UserRole / text / font 的。
        """
        widget = option.widget
        if widget is None or not index.isValid():
            super().paint(painter, option, index)
            return

        frame_data = index.data(FrameDataRole)
        if frame_data is None:
            super().paint(painter, option, index)
            return

        # Save painter state
        painter.save()

        # 用改写过的 option 走 Qt 默认绘制：只让它画**背景/选中态 + 图标**，
        # 文本与配色完全交给本 delegate。
        #
        # 为什么要改写而不是直接 super().paint(painter, option, index)：
        #  - 本 model 被列表视图共享，它在文件名列返回了参考帧的绿色 BackgroundRole
        #    与加粗 FontRole；网格若照单全收，参考帧的**整个格子**都会变绿（原本
        #    只有底部文字条是绿的），外观就变了。
        #  - 缩略图走 ThumbnailRole（自定义角色），默认绘制不认识它，因此显式塞进
        #    option.icon 让它画在与以前完全相同的位置。
        paint_option = QStyleOptionViewItem(option)
        paint_option.text = ""                   # 文本由 _draw_custom_text 自行绘制
        paint_option.backgroundBrush = QBrush()  # 忽略 model 的参考帧底色

        # 参考帧加粗走 model 的 `ReferenceRole`，不读 `widget.reference_frame_data`
        # —— 那是视图自己复制的第二份状态，清理时会与 model 不同步（参考帧是本
        # 项目的特色功能，两个视图必须一致）。也不依赖 model 的 FontRole：那只在
        # 文件名列返回加粗，会让判定取决于"当前显示的是哪一列"。
        is_ref = bool(index.data(ReferenceRole))
        font = index.data(Qt.ItemDataRole.FontRole)
        paint_option.font = font if font is not None else QFont()
        paint_option.font.setBold(is_ref)
        super().paint(painter, paint_option, index)

        # Calculate icon position
        icon_size = widget.iconSize()
        icon_rect = QRectF(
            option.rect.x() + (option.rect.width() - icon_size.width()) // 2,
            option.rect.y(),
            icon_size.width(),
            icon_size.height()
        )

        # 缩略图**必须自己画**，不能塞进 `option.icon` 交给 super().paint()。
        #
        # `QStyledItemDelegate.paint()` 内部会先调 `initStyleOption()`，而那个函数按
        # model 的 **DecorationRole** 重新设置 `option.icon` 与 `HasDecoration` 标志。
        # 本 model 的 DecorationRole 恒为 None（缩略图走自定义 ThumbnailRole —— 两个
        # 视图共享同一个 model，用 DecorationRole 会让列表视图每格都冒出图标），于是
        # 塞进 option.icon 的缩略图被直接丢弃，表现为网格一片空白。
        # 实测：手动塞 option.icon → 红像素 0；自己 drawPixmap → 红像素 4800。
        # 用 `toRect()`：QPainter.drawPixmap 没有 (QRectF, QPixmap) 重载，只有
        # (QRect, QPixmap)。这里不缩放 —— 缩略图已按 iconSize 生成好。
        thumbnail = index.data(ThumbnailRole)
        if thumbnail is not None and not thumbnail.isNull():
            painter.drawPixmap(icon_rect.toRect(), thumbnail)

        # Draw frame number overlay
        frame_number = index.row() + 1
        self._draw_frame_number(painter, icon_rect, frame_number)

        # Draw disabled overlay if needed
        if frame_data.is_disabled:
            self._draw_disabled_overlay(painter, icon_rect)

        # Draw custom multiline text
        self._draw_custom_text(painter, option, frame_data, index)

        # Restore painter state
        painter.restore()

    @staticmethod
    def _display_text(frame_data) -> str:
        """网格里显示的文件名：基名 + 切片位置。

        刻意**不含**参考帧前缀 —— 那是列表视图的表示法（网格用底色与加粗体现）。
        """
        fname = frame_data.file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if frame_data.slice_pos:
            fname += f" [{frame_data.slice_pos[0]},{frame_data.slice_pos[1]}]"
        return fname

    def _draw_custom_text(self, painter: QPainter, option: QStyleOptionViewItem,
                          frame_data, index):
        """Draw the item text (filename) with smart truncation.

        文本直接由 frame_data 算出，不再读 `item.text()`：网格显示的是"文件名
        (+切片位置)"，**不带**参考帧前缀（那是列表视图的表示法，靠底色与加粗体现）。
        自己算也就不再依赖"当前显示的是 model 的哪一列"。
        """
        text = self._display_text(frame_data)
        if not text:
            return

        # 字体：model 在文件名列返回了参考帧的加粗 FontRole，这里以其为基准
        font = index.data(Qt.ItemDataRole.FontRole)
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
            lines = [
                f"[GridText Debug] First frame text info:",
                f"  - Original text: '{text}'",
                f"  - Text length: {len(text)} chars",
                f"  - Item rect: {option.rect.width()}x{option.rect.height()}",
                f"  - Icon size: {icon_size.width()}x{icon_size.height()}",
                f"  - Text rect: {text_rect.width():.1f}x{text_rect.height():.1f}",
                f"  - Font: {font.family()}, size: {font.pointSize()}pt",
                f"  - Font metrics height: {fm.height()}, ascent: {fm.ascent()}",
                f"  - Text width: {fm.horizontalAdvance(text)}",
                f"  - Multiline mode: {self.show_multiline}",
            ]
            if self.show_multiline:
                available_lines = int(text_rect.height()) // fm.height()
                lines.append(f"  - Available lines: {available_lines}")
            grid_text_debug_lines(lines)

        # Clear the default text drawn by super().paint()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(text_rect, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Get theme mode from widget
        is_dark_theme = True
        widget = option.widget
        if widget and hasattr(widget, 'is_dark_theme'):
            is_dark_theme = widget.is_dark_theme

        # Check if this is a reference frame —— 走 model 的 `ReferenceRole`（唯一真源），
        # 不再读 `widget.reference_frame_data`（那是视图复制的第二份状态，清理时会与
        # model 脱节，导致"参考帧没取消但高亮还在/高亮没了"）。
        is_ref = bool(index.data(ReferenceRole))

        # Get text color and background based on selection state and theme
        if option.state & QStyle.StateFlag.State_Selected:
            # 选中色取自 ui/timeline_selection_style.py（单一真源）：QSS 用它画本
            # 格图标区的选中背景，这里画下面那条文字区。两边必须同一个值。
            #
            # 必须**不透明**：这里紧接着上面一句 `CompositionMode_Source` 把 Qt
            # 刚画好的背景清空了，再叠半透明色就会透出控件自身的底色（网格是
            # viewport 背景，随主题而变），于是选中色随环境漂移。原来的
            # alpha=200/220 正是"同一帧上下两截不同色"的来源。
            #
            # 两个主题同一个值：本 delegate 的 `is_dark_theme` 只影响**未选中**
            # 的文字条底色，选中态是全局高亮，不该跟着主题换色。
            text_color = SELECTED_FG_QCOLOR
            bg_color = SELECTED_BG_QCOLOR
        elif is_ref:
            # Reference frame highlighting
            if is_dark_theme:
                bg_color = QColor(30, 80, 40, 200)
                text_color = QColor(200, 255, 200)
            else:
                bg_color = QColor(200, 230, 200, 255)
                text_color = QColor(30, 80, 40)
        else:
            # Normal state - adapt to theme
            if is_dark_theme:
                bg_color = QColor(40, 40, 40, 200)
                text_color = QColor(220, 220, 220)
            else:
                bg_color = QColor(250, 250, 250, 230)
                text_color = QColor(30, 30, 30)

        # Draw text background
        painter.fillRect(text_rect, bg_color)

        painter.setFont(font)
        painter.setPen(text_color)

        # Draw text based on mode
        if self.show_multiline:
            # Multiline mode: calculate available lines and truncate accordingly
            display_lines = self._get_multiline_display_text(text, font, text_rect, debug)

            # Log processed text for first frame
            if debug:
                lines = [f"  - Processed lines ({len(display_lines)}):"]
                for i, line in enumerate(display_lines):
                    line_width = QFontMetrics(font).horizontalAdvance(line)
                    lines.append(f"      [{i}] '{line}' (width: {line_width}, rect_width: {text_rect.width():.1f})")
                grid_text_debug_lines(lines)
                self._log_printed = True  # Mark as printed after all logs

            self._draw_multiline_truncated(painter, display_lines, text_rect, font)
        else:
            # Single line mode: simple smart truncation
            display_text = self._truncate_text_smartly(text, font, text_rect.width())

            # Log processed text for first frame
            if debug:
                display_width = QFontMetrics(font).horizontalAdvance(display_text)
                grid_text_debug(f"  - Processed text: '{display_text}' (width: {display_width}, rect_width: {text_rect.width():.1f})")
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
            grid_text_debug(f"  - [Algorithm] num_lines={num_lines}, line_height={line_height}, available_height={available_height}")

        # If text fits in a single line, return it
        if fm.horizontalAdvance(text) <= text_rect.width():
            if debug:
                grid_text_debug(f"  - [Algorithm] Text fits in single line, returning as-is")
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
                grid_text_debug_lines([
                    f"  - [Algorithm] main_text='{main_text}', slice_suffix='{slice_suffix}'",
                    f"  - [Algorithm] main_prefix='{main_prefix}', main_suffix='{main_suffix}'",
                    f"  - [Algorithm] slice_width={slice_width}, main_suffix_width={main_suffix_width}",
                ])

            # Try to fit as much as possible across multiple lines
            lines = []
            remaining_text = main_prefix

            for line_num in range(num_lines):
                # Check if this is the last line
                is_last_line = (line_num == num_lines - 1)

                if debug:
                    grid_text_debug(f"  - [Algorithm] Processing line {line_num}, is_last={is_last_line}, remaining='{remaining_text}'")

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
                            grid_text_debug(f"  - [Algorithm] No more remaining_text, done")
                        break

                    if fm.horizontalAdvance(remaining_text) <= text_rect.width():
                        # All remaining prefix fits, but we need to continue to next lines
                        # for main_suffix + slice_suffix
                        if debug:
                            grid_text_debug(f"  - [Algorithm] All remaining fits: '{remaining_text}'")
                        lines.append(remaining_text)
                        remaining_text = ""
                        # DON'T break here - continue to process remaining lines for suffix
                    else:
                        # Find the best split point
                        split_pos = self._find_best_split_point(fm, remaining_text, text_rect.width(), debug)
                        if debug:
                            grid_text_debug(f"  - [Algorithm] Split at pos {split_pos}: '{remaining_text[:split_pos]}'")
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
                grid_text_debug(f"    [SplitPoint] '{text}' fits (width={text_width}, max={max_width}), return {len(text)}")
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
                        grid_text_debug(f"    [SplitPoint] Split at word boundary: '{current_line}' (len={len(current_line)})")
                    return len(current_line)

            # All words fit
            if debug:
                grid_text_debug(f"    [SplitPoint] All words fit: '{current_line}' (len={len(current_line)})")
            return len(current_line)

        # No spaces, split character by character
        for i in range(len(text), 0, -1):
            if fm.horizontalAdvance(text[:i]) <= max_width:
                if debug:
                    grid_text_debug(f"    [SplitPoint] No spaces, char-by-char split at {i}: '{text[:i]}' (width={fm.horizontalAdvance(text[:i])})")
                return i

        # Nothing fits
        if debug:
            grid_text_debug(f"    [SplitPoint] WARNING: Nothing fits in max_width={max_width}, text_width={text_width}")
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
