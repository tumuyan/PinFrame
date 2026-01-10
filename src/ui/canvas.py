from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QImage, QTransform
from src.core.image_cache import image_cache

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
        # 使用全局共享缓存 image_cache，不再维护本地缓存

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
        
        # Rasterization Settings
        self.rasterization_enabled = False
        self.rasterization_grid_color = QColor(0, 0, 0)
        self.rasterization_scale_threshold = 2.0
        
    def set_wheel_mode(self, mode):
        self.wheel_mode = mode
        self.update()

    def set_background_mode(self, mode):
        self.background_mode = mode
        self.update()
    
    def set_rasterization_settings(self, enabled, grid_color, scale_threshold):
        self.rasterization_enabled = enabled
        self.rasterization_grid_color = grid_color
        self.rasterization_scale_threshold = scale_threshold
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
        # 使用全局缓存预加载图片
        paths = [f.file_path for f in frames_data if f.file_path]
        image_cache.preload(paths)
        self.update()

    def set_onion_skins(self, skins):
        """Set onion skin frames. skins is a list of (FrameData, opacity)."""
        self.onion_skin_frames = skins
        paths = [f.file_path for f, _ in skins if f.file_path]
        image_cache.preload(paths)
        self.update()

    def set_reference_frame(self, frame_data):
        """Set a single reference frame."""
        self.reference_frame = frame_data
        if frame_data and frame_data.file_path:
            image_cache.get(frame_data.file_path)
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
        
        # Fill background (Editor background)
        painter.fillRect(self.rect(), QColor(50, 50, 50))
        
        # Check if we need rasterization
        use_rasterization = self.rasterization_enabled and self.view_scale > 1.0
        
        if use_rasterization:
            # Render to offscreen buffer first
            self._paint_with_rasterization(painter)
        else:
            # Normal rendering path
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            
            # Apply View Transform
            painter.translate(self.width() / 2, self.height() / 2) # Center origin
            painter.translate(self.view_offset)
            painter.scale(self.view_scale, self.view_scale)
            
            self._paint_content(painter)
            self._paint_overlays(painter)
    
    def _paint_content(self, painter):
        """Paint the main content (canvas background and frames)"""
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

        # Draw frames
        self._draw_frames(painter, draw_outlines=True)
    
    def _draw_frames(self, painter, draw_outlines=True):
        """Draw all frames (reference, onion, selected)"""
        # Draw Frame Helper
        def draw_frame(frame_data, opacity=1.0, is_ref=False):
            img = image_cache.get(frame_data.file_path)
            if img:
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
                
                if draw_outlines and not is_ref and opacity == 1.0: # Active Selection Outline
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
    
    def _paint_overlays(self, painter):
        """Paint overlays (anchor, selection outlines) on top of content"""
        # Draw Custom Anchor
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
    
    def _paint_with_rasterization(self, painter):
        """Paint with rasterization (pixelated) effect"""
        output_w = int(self.project_width)
        output_h = int(self.project_height)
        
        # Create temporary buffer at project resolution
        buffer = QImage(output_w, output_h, QImage.Format.Format_ARGB32_Premultiplied)
        buffer.fill(Qt.GlobalColor.transparent)
        
        buffer_painter = QPainter(buffer)
        buffer_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        buffer_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Draw background
        buffer_rect = QRectF(0, 0, output_w, output_h)
        if self.background_mode == "checkerboard":
            self.draw_checkerboard_to_painter(buffer_painter, buffer_rect)
        elif self.background_mode == "black":
            buffer_painter.fillRect(buffer_rect, Qt.GlobalColor.black)
        elif self.background_mode == "white":
            buffer_painter.fillRect(buffer_rect, Qt.GlobalColor.white)
        elif self.background_mode == "red":
            buffer_painter.fillRect(buffer_rect, Qt.GlobalColor.red)
        elif self.background_mode == "green":
            buffer_painter.fillRect(buffer_rect, Qt.GlobalColor.green)
        
        # Transform for drawing frames (center origin)
        buffer_painter.translate(output_w / 2, output_h / 2)
        
        # Draw frames to buffer (without outlines in buffer)
        self._draw_frames(buffer_painter, draw_outlines=False)
        
        buffer_painter.end()
        
        # Now draw the buffer back to the main painter using nearest-neighbor
        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.translate(self.view_offset)
        painter.scale(self.view_scale, self.view_scale)
        
        # Disable smooth transform for pixelated effect
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        
        # Draw the buffer with nearest-neighbor sampling
        target_rect = QRectF(-self.project_width / 2, -self.project_height / 2,
                             self.project_width, self.project_height)
        painter.drawImage(target_rect, buffer)
        
        # Draw white border
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawRect(target_rect)
        
        # Draw grid lines if scale is above threshold
        if self.view_scale > self.rasterization_scale_threshold:
            self._draw_pixel_grid(painter, output_w, output_h)
        
        # Draw selection outlines (on top, crisp)
        for frame_data in self.selected_frames_data:
            img = image_cache.get(frame_data.file_path)
            if img:
                painter.save()
                x, y = frame_data.position
                scale = frame_data.scale
                painter.translate(x, y)
                painter.rotate(frame_data.rotation)
                painter.scale(scale, scale / frame_data.aspect_ratio)
                w = img.width()
                h = img.height()
                if frame_data.crop_rect:
                    cx, cy, cw, ch = frame_data.crop_rect
                    target_rect_outline = QRectF(-cw/2, -ch/2, cw, ch)
                else:
                    target_rect_outline = QRectF(-w/2, -h/2, w, h)
                painter.setPen(QPen(Qt.GlobalColor.cyan, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(target_rect_outline)
                painter.restore()
        
        # Draw anchor (on top, crisp)
        if self.show_custom_anchor:
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            ax, ay = self.custom_anchor_pos.x(), self.custom_anchor_pos.y()
            r = self.anchor_handle_radius
            
            # Crosshair
            painter.drawLine(QPointF(ax - r*2, ay), QPointF(ax + r*2, ay))
            painter.drawLine(QPointF(ax, ay - r*2), QPointF(ax, ay + r*2))
            
            # Circle
            painter.drawEllipse(self.custom_anchor_pos, r, r)
        
        painter.restore()

    def refresh_resources(self):
        """Clear image cache and reload images for active frames."""
        image_cache.clear()
        
        # 重新加载所有活动帧的图片
        paths = [f.file_path for f in self.selected_frames_data if f.file_path]
        paths += [f.file_path for f, _ in self.onion_skin_frames if f.file_path]
        if self.reference_frame and self.reference_frame.file_path:
            paths.append(self.reference_frame.file_path)
        
        image_cache.preload(paths)
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
    
    def draw_checkerboard_to_painter(self, painter, rect):
        # Draw checkerboard without clipping (for buffer rendering)
        size = 20
        cols = int(rect.width() / size) + 1
        rows = int(rect.height() / size) + 1
        
        painter.save()
        
        for r in range(rows):
            for c in range(cols):
                color = self.checkerboard_color1 if (r + c) % 2 == 0 else self.checkerboard_color2
                painter.fillRect(int(c * size), int(r * size), size, size, color)
        
        painter.restore()
    
    def _draw_pixel_grid(self, painter, width, height):
        """Draw pixel grid lines over the rasterized content."""
        painter.save()
        painter.setPen(QPen(self.rasterization_grid_color, 1 / self.view_scale))
        
        # Draw vertical lines
        for x in range(int(-width / 2), int(width / 2) + 1):
            painter.drawLine(QPointF(x, -height / 2), QPointF(x, height / 2))
        
        # Draw horizontal lines
        for y in range(int(-height / 2), int(height / 2) + 1):
            painter.drawLine(QPointF(-width / 2, y), QPointF(width / 2, y))
        
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
