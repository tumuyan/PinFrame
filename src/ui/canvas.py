from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QImage, QTransform

class CanvasWidget(QWidget):
    # Signals to notify changes
    transform_changed = pyqtSignal(object) # data_changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # View Transform (Pan/Zoom)
        self.view_offset = QPointF(0, 0)
        self.view_scale = 1.0
        
        # Current Frame Data (Single or Multiple)
        self.current_frames = [] # List of (image, data) tuples or just data? 
                                 # We need images to draw. 
                                 # Let's verify how we pass data.
                                 # MainWindow passes Image + FrameData.
                                 # With multi-selection, we probably only really "edit" one active one or all?
                                 # User wants to move ALL selected.
        
        # We will maintain a list of (FrameData, QImage or None)
        # To avoid heavy IO, MainWindow should manage image caching/loading. 
        # For now, let's just stick to rendering "Current" (primary) + "Selected" (ghosts/outlines)?
        # Actually user said: "simultaneous preview and edit".
        # So we need to draw all selected images.
        
        self.selected_frames_data = [] # List of FrameData
        self.image_cache = {} # path -> QImage

        # Project Settings
        self.project_width = 512
        self.project_height = 512
        
        # Interaction state
        self.is_panning = False
        self.last_mouse_pos = QPointF()
        self.is_dragging_image = False
        
        self.checkerboard_color1 = QColor(200, 200, 200)
        self.checkerboard_color2 = QColor(160, 160, 160)
        self.show_checkerboard = True

    def toggle_background_mode(self):
        self.show_checkerboard = not self.show_checkerboard
        self.update()

    def set_project_settings(self, width, height):
        self.project_width = width
        self.project_height = height
        self.update()

    def set_selected_frames(self, frames_data):
        self.selected_frames_data = frames_data
        # Preload images for these frames
        for f in frames_data:
            if f.file_path not in self.image_cache:
                self.image_cache[f.file_path] = QImage(f.file_path)
        self.update()

    def reset_view(self):
        self.view_offset = QPointF(0, 0)
        self.view_scale = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Fill background (Editor background)
        painter.fillRect(self.rect(), QColor(50, 50, 50))

        # Apply View Transform
        painter.translate(self.width() / 2, self.height() / 2) # Center origin
        painter.translate(self.view_offset)
        painter.scale(self.view_scale, self.view_scale)

        # Draw Canvas Area (The Output Rectangle)
        output_rect = QRectF(-self.project_width / 2, -self.project_height / 2, 
                             self.project_width, self.project_height)
        
        if self.show_checkerboard:
            self.draw_checkerboard(painter, output_rect)
        else:
            painter.fillRect(output_rect, Qt.GlobalColor.black)
            
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawRect(output_rect)

        # Draw Selected Images
        # We should draw them in some order (preferably timeline order), but we only know selected ones here.
        # User didn't specify Z-order of selection. We'll just draw all selected.
        
        for frame_data in self.selected_frames_data:
            if frame_data.file_path in self.image_cache:
                img = self.image_cache[frame_data.file_path]
                
                painter.save()
                
                x, y = frame_data.position
                scale = frame_data.scale
                
                painter.translate(x, y)
                painter.scale(scale, scale)
                
                w = img.width()
                h = img.height()
                
                # If multiple are selected, maybe make them slightly transparent?
                # Or just draw normally.
                painter.drawImage(QRectF(-w/2, -h/2, w, h), img)
                
                # Draw selection outline
                painter.setPen(QPen(Qt.GlobalColor.cyan, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(-w/2, -h/2, w, h))
                
                painter.restore()

    def keyPressEvent(self, event):
        # View Controls
        if event.key() == Qt.Key.Key_0 and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.reset_view()
            return

        # Move Selection (Arrows)
        if self.selected_frames_data:
            step = 10 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            dx, dy = 0, 0
            
            if event.key() == Qt.Key.Key_Left: dx = -step
            elif event.key() == Qt.Key.Key_Right: dx = step
            elif event.key() == Qt.Key.Key_Up: dy = -step
            elif event.key() == Qt.Key.Key_Down: dy = step
            
            if dx != 0 or dy != 0:
                for f in self.selected_frames_data:
                    old_x, old_y = f.position
                    f.position = (old_x + dx, old_y + dy)
                self.transform_changed.emit(self.selected_frames_data[0]) # Emit primary or all?
                self.update()
                return

        # Scale Selection (Ctrl + +/- or similar)
        # Using Ctrl + = (Plus) and Ctrl + - (Minus)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scale_factor = 1.0
            if event.key() == Qt.Key.Key_Equal: # Plus
                scale_factor = 1.1
            elif event.key() == Qt.Key.Key_Minus:
                scale_factor = 0.9
            
            if scale_factor != 1.0 and self.selected_frames_data:
                for f in self.selected_frames_data:
                    f.scale *= scale_factor
                self.transform_changed.emit(self.selected_frames_data[0])
                self.update()
                return

        super().keyPressEvent(event)

    def draw_checkerboard(self, painter, rect):
        # Simple checkerboard pattern
        size = 20
        cols = int(rect.width() / size) + 1
        rows = int(rect.height() / size) + 1
        
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.topLeft())
        
        for r in range(rows):
            for c in range(cols):
                color = self.checkerboard_color1 if (r + c) % 2 == 0 else self.checkerboard_color2
                painter.fillRect(c * size, r * size, size, size, color)
        
        painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = True
            self.last_mouse_pos = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            if self.selected_frames_data:
                self.is_dragging_image = True
                self.last_mouse_pos = event.position()

    def mouseMoveEvent(self, event):
        delta = event.position() - self.last_mouse_pos
        self.last_mouse_pos = event.position()

        if self.is_panning:
            self.view_offset += delta
            self.update()
        
        elif self.is_dragging_image and self.selected_frames_data:
            world_delta = delta / self.view_scale
            
            for f in self.selected_frames_data:
                x, y = f.position
                f.position = (x + world_delta.x(), y + world_delta.y())
            
            self.transform_changed.emit(self.selected_frames_data[0])
            self.update()

    def mouseReleaseEvent(self, event):
        self.is_panning = False
        self.is_dragging_image = False

    def wheelEvent(self, event):
        # Alt + Scroll to scale image?
        if event.modifiers() & Qt.KeyboardModifier.AltModifier and self.selected_frames_data:
             zoom_in = event.angleDelta().y() > 0
             factor = 1.05 if zoom_in else 0.95
             for f in self.selected_frames_data:
                 f.scale *= factor
             self.transform_changed.emit(self.selected_frames_data[0])
             self.update()
        else:
            # Zoom View
            zoom_in = event.angleDelta().y() > 0
            factor = 1.1 if zoom_in else 0.9
            self.view_scale *= factor
            self.update()
