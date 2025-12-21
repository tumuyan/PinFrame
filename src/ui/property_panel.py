import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QDoubleSpinBox, QGroupBox, QSpinBox, QPushButton, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor
from i18n.manager import i18n

class PropertyPanel(QWidget):
    # Signals
    frame_data_changed = pyqtSignal(object, object, object) # scale, x, y
    relative_move_requested = pyqtSignal(float, float) # dx, dy

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_frames = []
        self.project_width = 512 # Set externally
        self.project_height = 512
        
        self.repeat_timer = QTimer(self)
        self.repeat_timer.timeout.connect(self.on_repeat_timer_timeout)
        self.repeat_mode = None # "repeat" or "rev"
        self.repeat_interval = 250
        
        layout = QVBoxLayout(self)
        
        # Preview
        self.preview_label = QLabel("No Selection")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        layout.addWidget(self.preview_label)
        
        # Transform Controls
        self.transform_group = QGroupBox(i18n.t("prop_transform"))
        form = QVBoxLayout(self.transform_group)
        
        # Scale
        scale_layout = QHBoxLayout()
        self.label_scale = QLabel(i18n.t("prop_scale_label"))
        scale_layout.addWidget(self.label_scale)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(4)
        self.scale_spin.setRange(0.01, 100.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(1.0)
        self.scale_spin.valueChanged.connect(self.on_value_changed)
        scale_layout.addWidget(self.scale_spin)
        form.addLayout(scale_layout)
        
        # Position
        pos_layout = QHBoxLayout()
        self.label_x = QLabel("X:")
        pos_layout.addWidget(self.label_x)
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-9999, 9999)
        self.x_spin.valueChanged.connect(self.on_value_changed)
        pos_layout.addWidget(self.x_spin)
        
        self.label_y = QLabel("Y:")
        pos_layout.addWidget(self.label_y)
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-9999, 9999)
        self.y_spin.valueChanged.connect(self.on_value_changed)
        pos_layout.addWidget(self.y_spin)
        
        form.addLayout(pos_layout)
        layout.addWidget(self.transform_group)
        
        # Advanced Sizing
        self.size_group = QGroupBox(i18n.t("prop_size_resolution"))
        size_layout = QVBoxLayout(self.size_group)
        
        # Quick Size Buttons
        quick_layout = QHBoxLayout()
        self.btn_fit_w = QPushButton(i18n.t("btn_fit_width"))
        self.btn_fit_w.clicked.connect(lambda: self.fit_to_canvas("width"))
        quick_layout.addWidget(self.btn_fit_w)
        
        self.btn_fit_h = QPushButton(i18n.t("btn_fit_height"))
        self.btn_fit_h.clicked.connect(lambda: self.fit_to_canvas("height"))
        quick_layout.addWidget(self.btn_fit_h)
        size_layout.addLayout(quick_layout)
        
        # Target Resolution
        t_res_layout = QHBoxLayout()
        self.label_target_res = QLabel(i18n.t("prop_target_res"))
        t_res_layout.addWidget(self.label_target_res)
        self.t_w_spin = QSpinBox()
        self.t_w_spin.setRange(0, 9999)
        self.t_w_spin.setSpecialValueText(i18n.t("prop_res_none"))
        self.t_w_spin.valueChanged.connect(self.on_target_res_changed)
        
        self.t_h_spin = QSpinBox()
        self.t_h_spin.setRange(0, 9999)
        self.t_h_spin.setSpecialValueText(i18n.t("prop_res_none"))
        self.t_h_spin.valueChanged.connect(self.on_target_res_changed)
        
        t_res_layout.addWidget(self.t_w_spin)
        self.label_x_sep = QLabel("x")
        t_res_layout.addWidget(self.label_x_sep)
        t_res_layout.addWidget(self.t_h_spin)
        size_layout.addLayout(t_res_layout)
        
        layout.addWidget(self.size_group)
        
        # Relative Move
        self.rel_move_group = QGroupBox(i18n.t("prop_rel_move"))
        rel_layout = QVBoxLayout(self.rel_move_group)
        
        # dx/dy inputs
        d_input_layout = QHBoxLayout()
        self.label_dx = QLabel(i18n.t("prop_dx"))
        d_input_layout.addWidget(self.label_dx)
        self.dx_spin = QDoubleSpinBox()
        self.dx_spin.setRange(-9999, 9999)
        self.dx_spin.setDecimals(2)
        d_input_layout.addWidget(self.dx_spin)
        
        self.label_dy = QLabel(i18n.t("prop_dy"))
        d_input_layout.addWidget(self.label_dy)
        self.dy_spin = QDoubleSpinBox()
        self.dy_spin.setRange(-9999, 9999)
        self.dy_spin.setDecimals(2)
        d_input_layout.addWidget(self.dy_spin)
        rel_layout.addLayout(d_input_layout)
        
        # Move Buttons
        move_btn_layout = QHBoxLayout()
        self.btn_move_x = QPushButton(i18n.t("btn_move_x"))
        self.btn_move_x.clicked.connect(lambda: self.relative_move_requested.emit(self.dx_spin.value(), 0))
        move_btn_layout.addWidget(self.btn_move_x)
        
        self.btn_move_y = QPushButton(i18n.t("btn_move_y"))
        self.btn_move_y.clicked.connect(lambda: self.relative_move_requested.emit(0, self.dy_spin.value()))
        move_btn_layout.addWidget(self.btn_move_y)
        rel_layout.addLayout(move_btn_layout)
        
        # Repeat Buttons
        repeat_layout = QHBoxLayout()
        self.btn_repeat = QPushButton(i18n.t("btn_repeat"))
        self.btn_repeat.setEnabled(False)
        self.btn_repeat.pressed.connect(lambda: self.start_repeat("repeat"))
        self.btn_repeat.released.connect(self.stop_repeat)
        repeat_layout.addWidget(self.btn_repeat)
        
        self.btn_rev_repeat = QPushButton(i18n.t("btn_rev_repeat"))
        self.btn_rev_repeat.setEnabled(False)
        self.btn_rev_repeat.pressed.connect(lambda: self.start_repeat("rev"))
        self.btn_rev_repeat.released.connect(self.stop_repeat)
        repeat_layout.addWidget(self.btn_rev_repeat)
        rel_layout.addLayout(repeat_layout)
        
        layout.addWidget(self.rel_move_group)
        
        # Alignment
        self.align_group = QGroupBox(i18n.t("prop_alignment"))
        align_layout = QGridLayout(self.align_group)
        
        # 3x3 Grid
        positions = [
            ("align_tl", 0, 0), ("align_tc", 0, 1), ("align_tr", 0, 2),
            ("align_cl", 1, 0), ("align_cc", 1, 1), ("align_cr", 1, 2),
            ("align_bl", 2, 0), ("align_bc", 2, 1), ("align_br", 2, 2)
        ]
        
        self.align_btns = {}
        for key, r, c in positions:
            btn = QPushButton(i18n.t(key))
            self.align_btns[key] = btn
            btn.setFixedSize(30, 30)
            # Use small font
            f = btn.font()
            f.setPointSize(7)
            btn.setFont(f)
            # 0=Top/Left, 1=Center, 2=Bottom/Right
            # Mapping logic:
            # Row 0 -> Val 0 (Top), Row 1 -> Val 0.5 (Center), Row 2 -> Val 1.0 (Bottom)
            y_align = r * 0.5
            x_align = c * 0.5
            
            btn.clicked.connect(lambda _, x=x_align, y=y_align: self.quick_align(x, y))
            align_layout.addWidget(btn, r, c)
            
        layout.addWidget(self.align_group)

        layout.addStretch()
        
        self.updating_ui = False

    def refresh_ui_text(self):
        from src.i18n.manager import i18n
        
        # Groups
        self.transform_group.setTitle(i18n.t("prop_transform"))
        self.size_group.setTitle(i18n.t("prop_size_resolution"))
        self.rel_move_group.setTitle(i18n.t("prop_rel_move"))
        self.align_group.setTitle(i18n.t("prop_alignment"))
        
        # Labels
        self.label_scale.setText(i18n.t("prop_scale_label"))
        self.label_target_res.setText(i18n.t("prop_target_res"))
        self.label_dx.setText(i18n.t("prop_dx"))
        self.label_dy.setText(i18n.t("prop_dy"))
        
        # Special value text
        self.t_w_spin.setSpecialValueText(i18n.t("prop_res_none"))
        self.t_h_spin.setSpecialValueText(i18n.t("prop_res_none"))
        
        # Buttons
        self.btn_fit_w.setText(i18n.t("btn_fit_width"))
        self.btn_fit_h.setText(i18n.t("btn_fit_height"))
        self.btn_move_x.setText(i18n.t("btn_move_x"))
        self.btn_move_y.setText(i18n.t("btn_move_y"))
        self.btn_repeat.setText(i18n.t("btn_repeat"))
        self.btn_rev_repeat.setText(i18n.t("btn_rev_repeat"))
        
        # Alignment buttons
        for key, btn in self.align_btns.items():
            btn.setText(i18n.t(key))
            
        # Preview label if no selection
        if not self.selected_frames:
            self.preview_label.setText(i18n.t("ready")) # Or "No Selection" but ready is localized
            
        self.update_ui_from_selection()

    def set_project_info(self, w, h):
        self.project_width = w
        self.project_height = h

    def set_selection(self, frames):
        self.selected_frames = frames
        self.update_ui_from_selection()
        self.update_preview()

    def update_ui_from_selection(self):
        self.updating_ui = True
        if not self.selected_frames:
            self.setEnabled(False)
            self.preview_label.setText("No Selection")
            self.t_w_spin.setValue(0) # None
            self.t_h_spin.setValue(0)
        else:
            self.setEnabled(True)
            first = self.selected_frames[0]
            
            self.scale_spin.setValue(first.scale)
            self.x_spin.setValue(first.position[0])
            self.y_spin.setValue(first.position[1])
            
            if first.target_resolution:
                self.t_w_spin.setValue(first.target_resolution[0])
                self.t_h_spin.setValue(first.target_resolution[1])
            else:
                self.t_w_spin.setValue(0)
                self.t_h_spin.setValue(0)
            
        self.updating_ui = False

    def on_value_changed(self):
        if self.updating_ui or not self.selected_frames:
            return
            
        new_scale = self.scale_spin.value()
        new_x = self.x_spin.value()
        new_y = self.y_spin.value()
        
        for f in self.selected_frames:
            f.scale = new_scale
            f.position = (new_x, new_y)
            # Clear target res if manually scaled? 
            # Or recalculate? User requested "Target resolution sets scale".
            # If user changes scale manually, target res is likely invalid unless we update it.
            # But "Target Resolution" is a goal. If scale changes, target res changes.
            # We'll calculate it if original image is available. 
            # For now, if manual scale, we might want to unset target res or update it. 
            # Let's unset it to avoid confusion or forcing values.
            # Actually, user said: "保存时使用目标分辨率" (Use target resolution when saving). 
            # If scale is changed, target resolution might result in a scale that matches it.
            # Let's keep logic simple: manual scale invalidates fixed target res numbers unless they match.
            # We will just leave it.
            
        self.frame_data_changed.emit(new_scale, new_x, new_y)

    def on_target_res_changed(self):
        if self.updating_ui or not self.selected_frames:
            return
            
        w = self.t_w_spin.value()
        h = self.t_h_spin.value()
        
        if w <= 0 or h <= 0:
            for f in self.selected_frames:
                f.target_resolution = None
            return

        for f in self.selected_frames:
            f.target_resolution = (w, h)
            if os.path.exists(f.file_path):
                # Calculate scale to match this res
                # Assuming keeping aspect ratio? 
                # "Target resolution matches scale" -> implies we just stretch or fit?
                # Usually resizing to specific WxH implies exact match. 
                # But if we change scale, it's uniform. 
                # We can't have non-uniform scale in currently defined FrameData (single scale float).
                # So we must pick one dimension or use the one that fits?
                # Or maybe user meant "Resample to this WxH"?
                # If FrameData only has uniform 'scale', we can only support 'target width' OR 'target height' meaningfully 
                # unless source aspect ratio matches target aspect ratio.
                # Use Width as primarily driver if both set? Or just update scale based on Width.
                
                try:
                    img = QImage(f.file_path)
                    if not img.isNull() and img.width() > 0:
                        scale = w / img.width()
                        f.scale = scale
                except:
                    pass
        
        # Update UI scale spin
        if self.selected_frames:
            self.updating_ui = True
            self.scale_spin.setValue(self.selected_frames[0].scale)
            self.updating_ui = False
            
        self.frame_data_changed.emit(self.selected_frames[0].scale, 
                                     self.selected_frames[0].position[0], 
                                     self.selected_frames[0].position[1])

    def fit_to_canvas(self, mode):
        if not self.selected_frames:
            return
            
        for f in self.selected_frames:
            if os.path.exists(f.file_path):
                try:
                    img = QImage(f.file_path)
                    if not img.isNull():
                        if mode == "width" and img.width() > 0:
                            f.scale = self.project_width / img.width()
                        elif mode == "height" and img.height() > 0:
                            f.scale = self.project_height / img.height()
                except:
                    pass
        
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0) # dummy emit to force redraw

    def quick_align(self, align_x_factor, align_y_factor):
        # align_factor: 0.0 (Left/Top), 0.5 (Center), 1.0 (Right/Bottom)
        if not self.selected_frames:
            return
            
        # Canvas Rect is centered at (0,0) in our Coordinate System logic?
        # NO. We decided `position` is offset from Canvas Center (0,0)?
        # Let's check Canvas logic: 
        # painter.translate(x, y) ... painter.drawImage(-w/2, -h/2, ...)
        # Yes, (0,0) position means Image Center is at Canvas Center.
        
        # Wait, if Canvas Center is (0,0), then Top-Left of Canvas is (-W/2, -H/2).
        # Bottom-Right is (W/2, H/2).
        
        canvas_l = -self.project_width / 2
        canvas_t = -self.project_height / 2
        canvas_r = self.project_width / 2
        canvas_b = self.project_height / 2
        
        for f in self.selected_frames:
            if os.path.exists(f.file_path):
                img = QImage(f.file_path)
                # Scaled dimensions
                w = img.width() * f.scale
                h = img.height() * f.scale
                
                # Image bounds relative to its center are (-w/2, -h/2) to (w/2, h/2).
                
                # We want to align specific point of Image to specific point of Canvas.
                # "Anchor and Alignment". 
                # User said: "9 anchor points on image, 9 alignment points on canvas".
                # My UI simplified this to "TL, TC, TR..." buttons. 
                # Let's assume the button means "Align Image TL to Canvas TL", "Image Center to Canvas Center".
                # Standard alignment behavior.
                
                # Target Canvas X
                # if 0.0 (Left): t_x = canvas_l
                # if 0.5 (Center): t_x = 0
                # if 1.0 (Right): t_x = canvas_r
                
                if align_x_factor == 0.0: target_x = canvas_l
                elif align_x_factor == 0.5: target_x = 0
                else: target_x = canvas_r
                
                if align_y_factor == 0.0: target_y = canvas_t
                elif align_y_factor == 0.5: target_y = 0
                else: target_y = canvas_b
                
                # Image Offset needed so that its [Anchor] hits [Target].
                # If Image Anchor is Left (0.0), its x-coord relative to image center is -w/2.
                # If Image Anchor is Center (0.5), it is 0.
                # If Image Anchor is Right (1.0), it is w/2.
                
                # Pos = Target - AnchorOffset
                
                files_w_offset = (align_x_factor - 0.5) * w # -w/2, 0, w/2
                files_h_offset = (align_y_factor - 0.5) * h
                
                # Note: Y grows down in Qt. Top is negative relative to center? 
                # CanvasWidget logic:
                # painter.translate(self.width()/2, self.height()/2) -> Center is 0,0.
                # QRectF(-pw/2, -ph/2, ...) -> Top is -ph/2. Yes.
                # So logic holds.
                
                f.position = (target_x - files_w_offset, target_y - files_h_offset)

        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0)

    def update_preview(self):
        if not self.selected_frames:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No Selection")
            return
            
        w, h = 200, 200
        preview_img = QImage(w, h, QImage.Format.Format_ARGB32)
        preview_img.fill(Qt.GlobalColor.transparent)
        
        # Collect imagery and calculate bounding box
        valid_frames = [] # list of (QImage, FrameData)
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        for f in self.selected_frames:
            if f.file_path and os.path.exists(f.file_path):
                img = QImage(f.file_path)
                if not img.isNull():
                    valid_frames.append((img, f))
                    # Calculate corners
                    fw = img.width() * f.scale
                    fh = img.height() * f.scale
                    cx, cy = f.position
                    
                    min_x = min(min_x, cx - fw/2)
                    max_x = max(max_x, cx + fw/2)
                    min_y = min(min_y, cy - fh/2)
                    max_y = max(max_y, cy + fh/2)
        
        if not valid_frames:
            self.preview_label.setPixmap(QPixmap.fromImage(preview_img))
            return

        painter = QPainter(preview_img)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            
            # Target padding
            padding = 10
            target_area = 200 - 2 * padding
            
            if len(valid_frames) == 1:
                # Single selection: Fit image to 180x180 area
                img, f = valid_frames[0]
                src_w, src_h = img.width(), img.height()
                scale = min(target_area / src_w, target_area / src_h)
                
                final_w, final_h = int(src_w * scale), int(src_h * scale)
                dest_x, dest_y = (w - final_w) // 2, (h - final_h) // 2
                painter.drawImage(QRect(dest_x, dest_y, final_w, final_h), img)
            else:
                # Multiple selection: Fit bounding box to 180x180 area
                box_w = max_x - min_x
                box_h = max_y - min_y
                
                if box_w > 0 and box_h > 0:
                    scale = min(target_area / box_w, target_area / box_h)
                    
                    # Transformation to fit box
                    painter.translate(w/2, h/2) # Move to preview center
                    painter.scale(scale, scale)
                    painter.translate(-(min_x + max_x)/2, -(min_y + max_y)/2) # Center the box
                    
                    # Draw frames with opacity
                    for img, f in valid_frames:
                        painter.save()
                        painter.setOpacity(0.5)
                        painter.translate(f.position[0], f.position[1])
                        painter.scale(f.scale, f.scale)
                        painter.drawImage(int(-img.width()/2), int(-img.height()/2), img)
                        painter.restore()
        finally:
            painter.end()
        
        self.preview_label.setPixmap(QPixmap.fromImage(preview_img))
    def on_repeat_clicked(self):
        # Signaling 0,0 basically means "use whatever MainWindow has as last" 
        # But better to stay explicit. MainWindow will handle the actual "last" storage.
        # Actually, let's just emit a special value or let MainWindow handle it.
        # User said "repeat上次移动的操作".
        self.relative_move_requested.emit(99999, 99999) # Special value for repeat? 
        # No, better: connect to a slot in MainWindow that knows the last move.

    def on_rev_repeat_clicked(self):
        self.relative_move_requested.emit(-99999, -99999) # Special value for rev repeat?
        # Actually let's just add specific methods or more signals.

    # Better approach: specific signals for repeat/rev_repeat
    repeat_requested = pyqtSignal()
    rev_repeat_requested = pyqtSignal()

    # Re-doing the connections in __init__ would be better but let's just make these slots emit.
    def on_repeat_clicked(self):
        self.repeat_requested.emit()

    def set_repeat_enabled(self, enabled):
        self.btn_repeat.setEnabled(enabled)
        self.btn_rev_repeat.setEnabled(enabled)

    def set_repeat_interval(self, ms):
        """ ms <= 0 means disabled """
        self.repeat_interval = ms
        if ms <= 0:
            self.stop_repeat()

    def start_repeat(self, mode):
        if self.repeat_interval <= 0:
            # If auto-repeat is disabled, just trigger once immediately
            if mode == "repeat":
                self.repeat_requested.emit()
            else:
                self.rev_repeat_requested.emit()
            return

        self.repeat_mode = mode
        # Trigger immediately once
        if mode == "repeat":
            self.repeat_requested.emit()
        else:
            self.rev_repeat_requested.emit()
            
        # Start timer for auto-repeat
        self.repeat_timer.start(self.repeat_interval)

    def stop_repeat(self):
        self.repeat_timer.stop()
        self.repeat_mode = None

    def on_repeat_timer_timeout(self):
        if self.repeat_mode == "repeat":
            self.repeat_requested.emit()
        elif self.repeat_mode == "rev":
            self.rev_repeat_requested.emit()
