from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QImage, QTransform
from src.core.image_cache import image_cache
from PyQt6.QtGui import QImage, QPainter
import math

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
                                 # With multi-selection, we probably only really "edit" one active one or all?
                                 # User wants to move ALL selected.
        
        # We will maintain a list of (FrameData, QImage or None)
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
        self.background_mode = "checkerboard" # "checkerboard", "black", "white", "red", "green"
        
        # Reference Settings
        self.ref_opacity = 0.5
        self.ref_layer = "top" # "top", "bottom"
        self.ref_show_on_playback = False
        self.ref_show_on_playback = False
        self.is_playing = False # Needs to be updated by MainWindow
        self.custom_anchor_pos = QPointF(256, 256)
        self.is_dragging_anchor = False
        self.anchor_handle_radius = 6
        
        # Wheel Mode
        self.WHEEL_ZOOM = 0
        self.WHEEL_SCALE = 1
        self.wheel_mode = self.WHEEL_ZOOM
        
        # Rasterization Settings
        self.raster_enabled = False
        self.raster_grid_color = QColor(128, 128, 128)
        self.raster_scale_threshold = 5.0
        self.rasterization_show_grid = True
        
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
            # Fallback to reset if widget size is too small or invalid
            self.reset_view()
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

        # Check if rasterization post-processing is needed
        should_rasterize = (
            self.raster_enabled and
            self.view_scale > 1.0
        )

        if should_rasterize:
            # Apply rasterization post-processing
            # Step 1: Render to temporary buffer at project resolution
            buffer = self._render_to_buffer()

            # Step 2: Apply rasterization (shrink -> nearest upscale -> optional grid)
            processed = self._apply_rasterization(buffer)

            # Step 3: Fill editor background
            painter.fillRect(self.rect(), QColor(50, 50, 50))

            # Step 4: Draw processed image with view transform
            painter.translate(self.width() / 2, self.height() / 2)
            painter.translate(self.view_offset)
            # Scale -> processed image to screen size using nearest neighbor
            # The processed image is already scaled by _apply_rasterization
            # So we just draw it at 1.0 scale (already pixelated)
            scaled_width = int(self.project_width * self.view_scale)
            scaled_height = int(self.project_height * self.view_scale)
            painter.drawImage(QRectF(-scaled_width / 2, -scaled_height / 2,
                                   scaled_width, scaled_height), processed)

            # Step 5: Draw canvas border
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            scaled_width = int(self.project_width * self.view_scale)
            scaled_height = int(self.project_height * self.view_scale)
            painter.drawRect(QRectF(-scaled_width / 2, -scaled_height / 2,
                                   scaled_width, scaled_height))

            # Step 6: Draw UI elements (anchor, selection outlines) - these stay sharp
            self._draw_ui_elements(painter)
        else:
            # Normal rendering
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

    def _render_to_buffer(self):
        """Render canvas content to a QImage buffer at project resolution.
        Captures all content including frames positioned outside canvas area."""
        # Calculate bounding box of all frames to ensure everything is captured
        # This includes frames that may be positioned outside of canvas area
        if not self.selected_frames_data:
            # No frames selected, return empty buffer
            buffer = QImage(self.project_width, self.project_height, QImage.Format.Format_RGBA8888)
            buffer.fill(Qt.GlobalColor.transparent)
            return buffer
        
        min_x = min([frame.position[0] for frame in self.selected_frames_data] + [0], default=0)
        max_x = max([frame.position[0] for frame in self.selected_frames_data] + [self.project_width], default=self.project_width)
        min_y = min([frame.position[1] for frame in self.selected_frames_data] + [0], default=0)
        max_y = max([frame.position[1] for frame in self.selected_frames_data] + [self.project_height], default=self.project_height)
        
        # Add margin for transformed content (scaled/rotated frames)
        # Use a larger buffer to capture all content
        margin = 200
        content_width = max(max_x - min_x, self.project_width) + margin
        content_height = max(max_y - min_y, self.project_height) + margin
        content_x = (min_x + max_x) / 2
        content_y = (min_y + max_y) / 2

        # Create buffer at content size (larger than project to capture outside content)
        buffer = QImage(int(content_width), int(content_height), QImage.Format.Format_RGBA8888)
        buffer.fill(Qt.GlobalColor.transparent)

        painter = QPainter(buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # Disable AA for pixelated look
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # Translate to center of content area
        painter.translate(content_width / 2, content_height / 2)
        painter.translate(-content_x, -content_y)

        # Draw background (at project canvas position)
        output_rect = QRectF(-self.project_width / 2, -self.project_height / 2,
                             self.project_width, self.project_height)

        if self.background_mode == "checkerboard":
            self.draw_checkerboard_buffer(painter, output_rect)
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
        def draw_frame_buffer(frame_data, opacity=1.0, is_ref=False):
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

                if opacity < 1.0:
                    painter.setOpacity(opacity)

                if frame_data.crop_rect:
                    cx, cy, cw, ch = frame_data.crop_rect
                    source_rect = QRectF(cx, cy, cw, ch)
                    target_rect = QRectF(-cw/2, -ch/2, cw, ch)
                    painter.drawImage(target_rect, img, source_rect)
                else:
                    target_rect = QRectF(-w/2, -h/2, w, h)
                    painter.drawImage(target_rect, img)

                painter.restore()

        # Draw Reference Frame (Bottom)
        if self.reference_frame and self.ref_layer == "bottom":
            if not self.is_playing or self.ref_show_on_playback:
                draw_frame_buffer(self.reference_frame, self.ref_opacity, is_ref=True)

        # Draw Onion Skins
        for frame, opacity in self.onion_skin_frames:
            draw_frame_buffer(frame, opacity, is_ref=True)

        # Draw Selected Images (Active)
        for frame_data in self.selected_frames_data:
            draw_frame_buffer(frame_data)

        # Draw Reference Frame (Top)
        if self.reference_frame and self.ref_layer == "top":
            if not self.is_playing or self.ref_show_on_playback:
                draw_frame_buffer(self.reference_frame, self.ref_opacity, is_ref=True)

        painter.end()

        # Crop to project canvas area for scaling
        # We want to rasterize only the project canvas area
        project_area = QRectF(-self.project_width / 2, -self.project_height / 2,
                                 self.project_width, self.project_height)
        
        # Convert to content coordinates for cropping
        crop_left = int(project_area.left() - content_x + content_width / 2)
        crop_top = int(project_area.top() - content_y + content_height / 2)
        
        # Crop and return only the project canvas area
        cropped = buffer.copy(crop_left, crop_top, self.project_width, self.project_height)
        
        return cropped

    def draw_checkerboard_buffer(self, painter, rect):
        """Draw checkerboard pattern in buffer coordinates (no view transform)."""
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

    def _apply_rasterization(self, image):
        """Apply rasterization: shrink -> nearest upscale -> optional grid."""
        # Use to show_grid setting from rasterization config
        show_grid = (self.view_scale > self.raster_scale_threshold) and self.rasterization_show_grid

        # Create processed image at screen size using nearest neighbor
        target_width = int(self.project_width * self.view_scale)
        target_height = int(self.project_height * self.view_scale)

        # First, scale down to project resolution (if needed) - already at project res
        # Then scale up to screen size using nearest neighbor
        processed = image.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation  # Nearest neighbor
        )

        if show_grid:
            # Draw grid lines on scaled image
            painter = QPainter(processed)
            painter.setPen(QPen(self.raster_grid_color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Calculate pixel size in scaled image
            # Each original pixel is now 'view_scale' screen pixels
            pixel_size = self.view_scale

            # Draw vertical lines at pixel boundaries
            for x in range(0, target_width + 1, int(pixel_size)):
                painter.drawLine(x, 0, x, target_height)

            # Draw horizontal lines at pixel boundaries
            for y in range(0, target_height + 1, int(pixel_size)):
                painter.drawLine(0, y, target_width, y)

            painter.end()

        return processed

    def _draw_ui_elements(self, painter):
        """Draw UI elements (anchor, selection outlines) that should remain sharp."""
        # Apply view transform for UI elements
        painter.scale(self.view_scale, self.view_scale)

        # Draw Custom Anchor
        if self.show_custom_anchor:
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2 / self.view_scale))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            ax, ay = self.custom_anchor_pos.x(), self.custom_anchor_pos.y()
            r = self.anchor_handle_radius / self.view_scale

            # Crosshair
            painter.drawLine(QPointF(ax - r*2, ay), QPointF(ax + r*2, ay))
            painter.drawLine(QPointF(ax, ay - r*2), QPointF(ax, ay + r*2))

            # Circle
            painter.drawEllipse(self.custom_anchor_pos, r, r)

        # Draw selection outlines for active frames
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
                    target_rect = QRectF(-cw/2, -ch/2, cw, ch)
                else:
                    target_rect = QRectF(-w/2, -h/2, w, h)

                painter.setPen(QPen(Qt.GlobalColor.cyan, 2 / self.view_scale))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(target_rect)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = True
            self.last_mouse_pos = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            # Check for Anchor Hit FIRST if enabled
            if self.show_custom_anchor:
                # Map mouse pos to World Coords
                # View Transform: Translate(W/2, H/2) -> Translate(ViewOffset) -> Scale(ViewScale)
                # World Coords = (MousePos - W/2 - ViewOffset) / ViewScale
                
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
