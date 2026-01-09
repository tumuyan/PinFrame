from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QImage, QTransform

class CanvasWidget(QWidget):
    # Signals to notify changes
    transform_changed = pyqtSignal(object) # data_changed
    anchor_pos_changed = pyqtSignal(float, float) # x, y
    scale_change_requested = pyqtSignal(float) # factor

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
        self.onion_skin_frames = [] # List of (FrameData, opacity)
        self.reference_frame = None # FrameData or None
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
        self.checkerboard_color1 = QColor(200, 200, 200)
        self.checkerboard_color2 = QColor(160, 160, 160)
        self.background_mode = "checkerboard" # "checkerboard", "black", "white", "red", "green"
        
        # Reference Settings
        self.ref_opacity = 0.5
        self.ref_layer = "top" # "top", "bottom"
        self.ref_show_on_playback = False
        self.ref_show_on_playback = False
        self.is_playing = False # Needs to be updated by MainWindow
        
        # Custom Anchor
        self.show_custom_anchor = False
        self.custom_anchor_pos = QPointF(256, 256)
        self.is_dragging_anchor = False
        self.anchor_handle_radius = 6
        
        # Wheel Mode
        self.WHEEL_ZOOM = 0
        self.WHEEL_SCALE = 1
        self.wheel_mode = self.WHEEL_ZOOM
        
    def set_wheel_mode(self, mode):
        self.wheel_mode = mode
        self.update()

    def set_background_mode(self, mode):
        self.background_mode = mode
        self.update()

    def set_project_settings(self, width, height):
        self.project_width = width
        self.project_height = height
        self.update()

    def set_show_custom_anchor(self, show):
        self.show_custom_anchor = show
        self.update()

    def set_custom_anchor_pos(self, pos):
        self.custom_anchor_pos = pos
        self.update()

    def set_selected_frames(self, frames_data):
        self.selected_frames_data = frames_data
        # Preload images for these frames
        for f in frames_data:
            if f.file_path not in self.image_cache:
                self.image_cache[f.file_path] = QImage(f.file_path)
        self.update()

    def set_onion_skins(self, skins):
        """Set onion skin frames. skins is a list of (FrameData, opacity)."""
        self.onion_skin_frames = skins
        for f, _ in skins:
            if f.file_path not in self.image_cache:
                self.image_cache[f.file_path] = QImage(f.file_path)
        self.update()

    def set_reference_frame(self, frame_data):
        """Set a single reference frame."""
        self.reference_frame = frame_data
        if frame_data and frame_data.file_path not in self.image_cache:
            self.image_cache[frame_data.file_path] = QImage(frame_data.file_path)
        self.update()

    def reset_view(self):
        self.view_offset = QPointF(0, 0)
        self.view_scale = 1.0
        self.update()

    def fit_to_view(self):
        if self.project_width <= 0 or self.project_height <= 0:
            return
            
        # Add some padding to ensure it's not sticking to edges
        padding = 40
        available_w = self.width() - padding
        available_h = self.height() - padding
        
        if available_w <= 0 or available_h <= 0:
            # Fallback to reset if widget size is too small or invalid
            self.reset_view()
            return
            
        scale_w = available_w / self.project_width
        scale_h = available_h / self.project_height
        
        # Use the smaller scale so that both dimensions are visible
        self.view_scale = min(scale_w, scale_h)
        self.view_offset = QPointF(0, 0)
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
        
        if self.background_mode == "checkerboard":
            self.draw_checkerboard(painter, output_rect)
        elif self.background_mode == "black":
            painter.fillRect(output_rect, Qt.GlobalColor.black)
        elif self.background_mode == "white":
            painter.fillRect(output_rect, Qt.GlobalColor.white)
        elif self.background_mode == "red":
            painter.fillRect(output_rect, Qt.GlobalColor.red)
        elif self.background_mode == "green":
            painter.fillRect(output_rect, Qt.GlobalColor.green)
            
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawRect(output_rect)

        # Draw Frame Helper
        def draw_frame(frame_data, opacity=1.0, is_ref=False):
            if frame_data.file_path in self.image_cache:
                img = self.image_cache[frame_data.file_path]
                
                painter.save()
                
                x, y = frame_data.position
                scale = frame_data.scale
                
                painter.translate(x, y)
                painter.rotate(frame_data.rotation)
                painter.scale(scale, scale / frame_data.aspect_ratio)
                
                w = img.width()
                h = img.height()
                
                # Setup transparency
                if opacity < 1.0:
                    painter.setOpacity(opacity)
                
                # Handle crop_rect
                if frame_data.crop_rect:
                    cx, cy, cw, ch = frame_data.crop_rect
                    source_rect = QRectF(cx, cy, cw, ch)
                    target_rect = QRectF(-cw/2, -ch/2, cw, ch)
                    painter.drawImage(target_rect, img, source_rect)
                else:
                    target_rect = QRectF(-w/2, -h/2, w, h)
                    painter.drawImage(target_rect, img)
                
                if not is_ref and opacity == 1.0: # Active Selection Outline
                    painter.setPen(QPen(Qt.GlobalColor.cyan, 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(target_rect)
                
                painter.restore()

        # 1. Draw Reference Frame (Bottom)
        if self.reference_frame and self.ref_layer == "bottom":
            if not self.is_playing or self.ref_show_on_playback:
                draw_frame(self.reference_frame, self.ref_opacity, is_ref=True) 

        # 2. Draw Onion Skins
        for frame, opacity in self.onion_skin_frames:
            draw_frame(frame, opacity, is_ref=True) # Treat as ref to avoid outlines

        # 3. Draw Selected Images (Active)
        for frame_data in self.selected_frames_data:
            draw_frame(frame_data)
            
        # 4. Draw Reference Frame (Top)
        if self.reference_frame and self.ref_layer == "top":
            if not self.is_playing or self.ref_show_on_playback:
                draw_frame(self.reference_frame, self.ref_opacity, is_ref=True)

        # 5. Draw Custom Anchor
        if self.show_custom_anchor:
            # Anchor is in Project Coordinates (0,0 is center)
            # We need to map it to View Coordinates to check for mouse hits easily if we did separate logic
            # But here we just draw it in the transformed painter context.
            
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            ax, ay = self.custom_anchor_pos.x(), self.custom_anchor_pos.y()
            r = self.anchor_handle_radius
            
            # Crosshair
            painter.drawLine(QPointF(ax - r*2, ay), QPointF(ax + r*2, ay))
            painter.drawLine(QPointF(ax, ay - r*2), QPointF(ax, ay + r*2))
            
            # Circle
            painter.drawEllipse(self.custom_anchor_pos, r, r)

    def refresh_resources(self):
        """Clear image cache and reload images for active frames."""
        self.image_cache.clear()
        
        # Reload selected frames
        self.set_selected_frames(self.selected_frames_data)
        
        # Reload onion skins
        frames_list = [f for f, _ in self.onion_skin_frames]
        for f in frames_list:
             if f.file_path not in self.image_cache:
                self.image_cache[f.file_path] = QImage(f.file_path)
        
        # Reload reference frame
        if self.reference_frame:
            if self.reference_frame.file_path not in self.image_cache:
                self.image_cache[self.reference_frame.file_path] = QImage(self.reference_frame.file_path)
                
        self.update()

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
            # Check for Anchor Hit FIRST if enabled
            if self.show_custom_anchor:
                # Map mouse pos to World Coords
                # View Transform: Translate(W/2, H/2) -> Translate(ViewOffset) -> Scale(ViewScale)
                # Reverse:
                center_offset = QPointF(self.width() / 2, self.height() / 2)
                local_pos = event.position() - center_offset - self.view_offset
                world_pos = local_pos / self.view_scale
                
                # Check distance
                dist = (world_pos - self.custom_anchor_pos).manhattanLength() # aprox
                if dist < self.anchor_handle_radius * 2 / self.view_scale + 5: # Tolerance
                    self.is_dragging_anchor = True
                    self.last_mouse_pos = event.position()
                    return

            if self.selected_frames_data:
                self.is_dragging_image = True
                self.last_mouse_pos = event.position()

    def mouseMoveEvent(self, event):
        delta = event.position() - self.last_mouse_pos
        self.last_mouse_pos = event.position()

        if self.is_panning:
            self.view_offset += delta
            self.update()
        
        elif self.is_dragging_anchor:
            world_delta = delta / self.view_scale
            self.custom_anchor_pos += world_delta
            self.anchor_pos_changed.emit(self.custom_anchor_pos.x(), self.custom_anchor_pos.y())
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
        self.is_dragging_anchor = False

    def wheelEvent(self, event):
        if self.wheel_mode == self.WHEEL_ZOOM:
            # Zoom View
            delta = event.angleDelta().y()
            if delta > 0:
                self.view_scale *= 1.1
            else:
                self.view_scale /= 1.1
            self.update()
        elif self.wheel_mode == self.WHEEL_SCALE:
            # Scale Image(s)
            if not self.selected_frames_data:
                return
                
            delta = event.angleDelta().y()
            factor = 1.05 if delta > 0 else 0.95
            
            # Emit signal for MainWindow to handle scaling
            self.scale_change_requested.emit(factor)
            # MainWindow will update the frame data and call set_selected_frames,
            # which will trigger an update()
