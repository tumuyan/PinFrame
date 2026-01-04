import os
import math
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QDoubleSpinBox, QGroupBox, QSpinBox, QPushButton, 
                             QGridLayout, QCheckBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QTransform
from i18n.manager import i18n

class PropertyPanel(QWidget):
    # Signals
    frame_data_changed = pyqtSignal(object, object, object) # scale, x, y
    relative_move_requested = pyqtSignal(float, float) # dx, dy
    # New signals for anchor sync
    custom_anchor_changed = pyqtSignal(float, float) # x, y
    show_anchor_changed = pyqtSignal(bool)

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
        self.preview_label = QLabel(i18n.t("msg_no_selection"))
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        layout.addWidget(self.preview_label)
        
        # Rotation spinbox needs to be added to transform_group or we refactor it completely.
        
        # 1. Transform Group (Scale, Rotate, Position)
        self.transform_group = QGroupBox(i18n.t("prop_transform"))
        form = QGridLayout(self.transform_group)
        
        # Scale
        self.label_scale = QLabel(i18n.t("prop_scale_label"))
        form.addWidget(self.label_scale, 0, 0)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(4)
        self.scale_spin.setRange(0.01, 100.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(1.0)
        self.scale_spin.valueChanged.connect(self.on_value_changed)
        form.addWidget(self.scale_spin, 0, 1)
        
        # Rotation
        self.label_rotation = QLabel(i18n.t("prop_rotation_label"))
        form.addWidget(self.label_rotation, 1, 0)
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-3600, 3600)
        self.rotation_spin.setSingleStep(15)
        self.rotation_spin.setSuffix("°")
        self.rotation_spin.valueChanged.connect(self.on_value_changed)
        form.addWidget(self.rotation_spin, 1, 1)
        
        # Position X
        self.label_x = QLabel("X:")
        form.addWidget(self.label_x, 2, 0)
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-9999, 9999)
        self.x_spin.valueChanged.connect(self.on_value_changed)
        form.addWidget(self.x_spin, 2, 1)
        
        # Position Y
        self.label_y = QLabel("Y:")
        form.addWidget(self.label_y, 3, 0)
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-9999, 9999)
        self.y_spin.valueChanged.connect(self.on_value_changed)
        form.addWidget(self.y_spin, 3, 1)
        
        layout.addWidget(self.transform_group)
        
        # 1.5 Mirror Group
        self.mirror_group = QGroupBox(i18n.t("prop_mirror"))
        mirror_layout = QHBoxLayout(self.mirror_group)
        
        self.btn_flip_h = QPushButton(i18n.t("prop_mirror_h"))
        self.btn_flip_h.clicked.connect(lambda: self.apply_mirror("h"))
        mirror_layout.addWidget(self.btn_flip_h)
        
        self.btn_flip_v = QPushButton(i18n.t("prop_mirror_v"))
        self.btn_flip_v.clicked.connect(lambda: self.apply_mirror("v"))
        mirror_layout.addWidget(self.btn_flip_v)
        
        layout.addWidget(self.mirror_group)
        
        # Advanced Sizing (Existing)
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
        self.t_w_spin.valueChanged.connect(self.on_t_w_changed)
        
        self.t_h_spin = QSpinBox()
        self.t_h_spin.setRange(0, 9999)
        self.t_h_spin.setSpecialValueText(i18n.t("prop_res_none"))
        self.t_h_spin.valueChanged.connect(self.on_t_h_changed)
        
        t_res_layout.addWidget(self.t_w_spin)
        self.label_x_sep = QLabel("x")
        t_res_layout.addWidget(self.label_x_sep)
        t_res_layout.addWidget(self.t_h_spin)
        
        # AR Lock
        self.t_res_lock = QCheckBox(i18n.t("prop_res_lock"))
        self.t_res_lock.setChecked(True)
        t_res_layout.addWidget(self.t_res_lock)
        
        # Reset AR Button
        self.btn_reset_ar = QPushButton(i18n.t("prop_res_reset"))
        self.btn_reset_ar.clicked.connect(self.reset_aspect_ratio)
        t_res_layout.addWidget(self.btn_reset_ar)
        
        size_layout.addLayout(t_res_layout)
        
        layout.addWidget(self.size_group)
        
        # 2. Anchor (Moved out)
        self.anchor_group = QGroupBox(i18n.t("prop_anchor"))
        anchor_layout = QHBoxLayout(self.anchor_group)
        self.anchor_bg = QButtonGroup(self)
        
        self.rb_anchor_canvas = QRadioButton(i18n.t("prop_anchor_canvas"))
        self.rb_anchor_image = QRadioButton(i18n.t("prop_anchor_image"))
        self.rb_anchor_custom = QRadioButton(i18n.t("prop_anchor_custom"))
        
        self.anchor_bg.addButton(self.rb_anchor_canvas, 0)
        self.anchor_bg.addButton(self.rb_anchor_image, 1)
        self.anchor_bg.addButton(self.rb_anchor_custom, 2)
        self.rb_anchor_canvas.setChecked(True) # Default
        
        self.anchor_bg.idToggled.connect(self.on_anchor_mode_changed)
        
        anchor_layout.addWidget(self.rb_anchor_canvas)
        anchor_layout.addWidget(self.rb_anchor_image)
        anchor_layout.addWidget(self.rb_anchor_custom)
        layout.addWidget(self.anchor_group)
        
        # Custom Anchor Inputs (Hidden/Shown based on selection? Or just disabled)
        # Putting inside separate widget for cleaner layout.
        self.custom_anchor_widget = QWidget()
        ca_layout = QHBoxLayout(self.custom_anchor_widget)
        ca_layout.setContentsMargins(10, 0, 10, 5)
        ca_layout.addWidget(QLabel("Anchor X:"))
        self.ca_x_spin = QDoubleSpinBox()
        self.ca_x_spin.setRange(-9999, 9999)
        self.ca_x_spin.valueChanged.connect(self.on_custom_anchor_ui_changed)
        ca_layout.addWidget(self.ca_x_spin)
        ca_layout.addWidget(QLabel("Anchor Y:"))
        self.ca_y_spin = QDoubleSpinBox()
        self.ca_y_spin.setRange(-9999, 9999)
        self.ca_y_spin.valueChanged.connect(self.on_custom_anchor_ui_changed)
        ca_layout.addWidget(self.ca_y_spin)
        self.custom_anchor_widget.setEnabled(False) 
        layout.addWidget(self.custom_anchor_widget)

        # 3. Relative Transform
        self.rel_trans_group = QGroupBox(i18n.t("prop_rel_trans"))
        rel_layout = QVBoxLayout(self.rel_trans_group)
        

        

        
        # REPLACED GRID
        op_grid = QGridLayout()
        
        # Row 0: Move
        # [Step] [X-] [X+] [Y-] [Y+]
        op_grid.addWidget(QLabel(i18n.t("prop_dx")), 0, 0)
        self.dx_spin = QDoubleSpinBox()
        self.dx_spin.setRange(-9999, 9999)
        self.dx_spin.setValue(10.0)
        op_grid.addWidget(self.dx_spin, 0, 1)
        
        self.btn_move_left = QPushButton("X-")
        self.btn_move_left.clicked.connect(lambda: self.apply_rel_move(-self.dx_spin.value(), 0))
        op_grid.addWidget(self.btn_move_left, 0, 2)
        
        self.btn_move_right = QPushButton("X+")
        self.btn_move_right.clicked.connect(lambda: self.apply_rel_move(self.dx_spin.value(), 0))
        op_grid.addWidget(self.btn_move_right, 0, 3)
        
        # Combine Y onto existing lines or new line? Let's use 2nd line for Y to save width?
        # Or combine dx/dy into one 'step' spinbox for simplification?
        # User requested: "移动× 移动Y 重复... 改为 x- x+ y- y+, 增加数值缩放系数..."
        # Let's keep one step value for move X and one for Y? Or shared?
        # "增加数值缩放系数... 增加数值旋转系数..." implies separate steps.
        # Let's use separate X/Y steps or shared? Shared 'Move Step' is cleaner. 
        # But previously we had dx and dy. I'll keep dx and dy logic but maybe simplify UI.
        # Let's put Y on same row if possible, or new row.
        
        op_grid.addWidget(QLabel(i18n.t("prop_dy")), 1, 0)
        self.dy_spin = QDoubleSpinBox()
        self.dy_spin.setRange(-9999, 9999)
        self.dy_spin.setValue(10.0)
        op_grid.addWidget(self.dy_spin, 1, 1)
        
        self.btn_move_up = QPushButton("Y-")
        self.btn_move_up.clicked.connect(lambda: self.apply_rel_move(0, -self.dy_spin.value()))
        op_grid.addWidget(self.btn_move_up, 1, 2)
        
        self.btn_move_down = QPushButton("Y+")
        self.btn_move_down.clicked.connect(lambda: self.apply_rel_move(0, self.dy_spin.value()))
        op_grid.addWidget(self.btn_move_down, 1, 3)

        # Row 2: Scale
        op_grid.addWidget(QLabel(i18n.t("prop_scale_step")), 2, 0)
        self.step_scale_spin = QDoubleSpinBox()
        self.step_scale_spin.setRange(1.01, 10.0)
        self.step_scale_spin.setSingleStep(0.1)
        self.step_scale_spin.setValue(1.1)
        op_grid.addWidget(self.step_scale_spin, 2, 1)
        
        self.btn_scale_up = QPushButton(i18n.t("btn_scale_up"))
        self.btn_scale_up.clicked.connect(lambda: self.apply_rel_scale(self.step_scale_spin.value()))
        op_grid.addWidget(self.btn_scale_up, 2, 2)
        
        self.btn_scale_down = QPushButton(i18n.t("btn_scale_down"))
        self.btn_scale_down.clicked.connect(lambda: self.apply_rel_scale(1.0 / self.step_scale_spin.value()))
        op_grid.addWidget(self.btn_scale_down, 2, 3)
        
        # Row 3: Rotate
        op_grid.addWidget(QLabel(i18n.t("prop_rotate_step")), 3, 0)
        self.step_rotate_spin = QDoubleSpinBox()
        self.step_rotate_spin.setRange(1, 180)
        self.step_rotate_spin.setValue(15)
        op_grid.addWidget(self.step_rotate_spin, 3, 1)
        
        self.btn_rotate_ccw = QPushButton(i18n.t("btn_rotate_ccw"))
        self.btn_rotate_ccw.clicked.connect(lambda: self.apply_rel_rotate(-self.step_rotate_spin.value()))
        op_grid.addWidget(self.btn_rotate_ccw, 3, 2)
        
        self.btn_rotate_cw = QPushButton(i18n.t("btn_rotate_cw"))
        self.btn_rotate_cw.clicked.connect(lambda: self.apply_rel_rotate(self.step_rotate_spin.value()))
        op_grid.addWidget(self.btn_rotate_cw, 3, 3)
        
        rel_layout.addLayout(op_grid)
        layout.addWidget(self.rel_trans_group)
        
        # Alignment
        self.align_group = QGroupBox(i18n.t("prop_alignment"))
        align_layout = QGridLayout(self.align_group)
        
        # 3x3 Grid
        positions = [
            ("⇖", 0, 0), ("⇑", 0, 1), ("⇗", 0, 2),
            ("⇐", 1, 0), ("⏺", 1, 1), ("⇒", 1, 2),
            ("⇙", 2, 0), ("⇓", 2, 1), ("⇘", 2, 2)
        ]
        
        self.align_btns = {}
        for symbol, r, c in positions:
            btn = QPushButton(symbol)
            self.align_btns[f"align_{r}_{c}"] = btn
            btn.setFixedSize(32, 32)
            # Use larger font for symbols
            f = btn.font()
            f.setPointSize(12)
            f.setBold(True)
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
        self.mirror_group.setTitle(i18n.t("prop_mirror"))
        self.size_group.setTitle(i18n.t("prop_size_resolution"))
        self.rel_trans_group.setTitle(i18n.t("prop_rel_trans"))
        self.align_group.setTitle(i18n.t("prop_alignment"))
        
        # Labels
        self.label_scale.setText(i18n.t("prop_scale_label"))
        self.label_rotation.setText(i18n.t("prop_rotation_label"))
        self.label_target_res.setText(i18n.t("prop_target_res"))
        self.t_res_lock.setText(i18n.t("prop_res_lock"))
        self.btn_reset_ar.setText(i18n.t("prop_res_reset"))
        
        # Buttons
        self.btn_flip_h.setText(i18n.t("prop_mirror_h"))
        self.btn_flip_v.setText(i18n.t("prop_mirror_v"))
        
        self.btn_fit_w.setText(i18n.t("btn_fit_width"))
        self.btn_fit_h.setText(i18n.t("btn_fit_height"))
        
        self.btn_scale_up.setText(i18n.t("btn_scale_up"))
        self.btn_scale_down.setText(i18n.t("btn_scale_down"))
        self.btn_rotate_cw.setText(i18n.t("btn_rotate_cw"))
        self.btn_rotate_ccw.setText(i18n.t("btn_rotate_ccw"))
        
        # Anchor
        self.rb_anchor_canvas.setText(i18n.t("prop_anchor_canvas"))
        self.rb_anchor_image.setText(i18n.t("prop_anchor_image"))
        self.rb_anchor_custom.setText(i18n.t("prop_anchor_custom"))
        
        # Special value text
        self.t_w_spin.setSpecialValueText(i18n.t("prop_res_none"))
        self.t_h_spin.setSpecialValueText(i18n.t("prop_res_none"))
            
        # Preview label if no selection
        if not self.selected_frames:
            self.preview_label.setText(i18n.t("msg_no_selection"))
            
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
            self.preview_label.setText(i18n.t("msg_no_selection"))
            self.t_w_spin.setValue(0) # None
            self.t_h_spin.setValue(0)
        else:
            self.setEnabled(True)
            first = self.selected_frames[0]
            
            self.scale_spin.setValue(first.scale)
            self.x_spin.setValue(first.position[0])
            self.y_spin.setValue(first.position[1])
            self.rotation_spin.setValue(first.rotation)
            
            # Calculate target resolution from scale and aspect_ratio
            if os.path.exists(first.file_path):
                img = QImage(first.file_path)
                if not img.isNull():
                    orig_w = first.crop_rect[2] if first.crop_rect else img.width()
                    orig_h = first.crop_rect[3] if first.crop_rect else img.height()
                    if orig_w > 0 and orig_h > 0:
                        self.t_w_spin.setValue(int(abs(orig_w * first.scale)))
                        self.t_h_spin.setValue(int(abs(orig_h * (first.scale / first.aspect_ratio))))
                    else:
                        self.t_w_spin.setValue(0)
                        self.t_h_spin.setValue(0)
                else:
                    self.t_w_spin.setValue(0)
                    self.t_h_spin.setValue(0)
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
        new_rot = self.rotation_spin.value()
        
        for f in self.selected_frames:
            f.scale = new_scale
            f.position = (new_x, new_y)
            f.rotation = new_rot
            
        self.refresh_t_res_ui() # Updates T-Res UI as well
            
        self.frame_data_changed.emit(new_scale, new_x, new_y)

    def on_anchor_mode_changed(self, id):
        is_custom = (id == 2)
        self.custom_anchor_widget.setEnabled(is_custom)
        self.show_anchor_changed.emit(is_custom)

    def on_custom_anchor_ui_changed(self):
        if self.updating_ui: return
        x = self.ca_x_spin.value()
        y = self.ca_y_spin.value()
        self.custom_anchor_changed.emit(x, y)

    def set_custom_anchor_pos(self, x, y):
        # Called by MainWindow when Canvas updates anchor
        self.updating_ui = True
        self.ca_x_spin.setValue(x)
        self.ca_y_spin.setValue(y)
        self.updating_ui = False

    def get_anchor_pos(self, f):
        # Returns global anchor pos for the frame operation
        mode = self.anchor_bg.checkedId()
        if mode == 0: # Canvas Center
            return QPointF(0, 0)
        elif mode == 1: # Image Center
            return QPointF(f.position[0], f.position[1])
        else: # Custom
            return QPointF(self.ca_x_spin.value(), self.ca_y_spin.value())

    def apply_mirror(self, axis):
        if not self.selected_frames: return
        
        center_mode = self.anchor_bg.checkedId()
        
        for f in self.selected_frames:
            # 1. Logic for flipping scale/AR
            # Flip H: scale *= -1
            # Flip V: aspect_ratio *= -1
            
            if axis == "h":
                f.scale *= -1
                f.aspect_ratio *= -1
            else:
                f.aspect_ratio *= -1
            
            # 2. Logic for position mirror around Anchor
            # If Image Center, position doesn't change relative to itself? 
            # Wait. If I flip an image horizontally around its center, it stays in place.
            # If I flip around Canvas Center (0,0), and image is at (100,0), it should go to (-100, 0).
            
            anchor = self.get_anchor_pos(f)
            
            # Vector from anchor to images pos
            vx = f.position[0] - anchor.x()
            vy = f.position[1] - anchor.y()
            
            if axis == "h":
                # Reflect X
                vx = -vx
            else:
                # Reflect Y
                vy = -vy
                
            f.position = (anchor.x() + vx, anchor.y() + vy)
            
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0)

    def apply_rel_move(self, dx, dy):
        if not self.selected_frames: return
        for f in self.selected_frames:
            f.position = (f.position[0] + dx, f.position[1] + dy)
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0)

    def apply_rel_scale(self, factor):
        if not self.selected_frames: return
        
        for f in self.selected_frames:
            # Scale Factor applies to Frame.scale
            # And also scales distance from Anchor
            
            anchor = self.get_anchor_pos(f)
            
            # Update Scale
            f.scale *= factor
            
            # Update Position relative to anchor
            # P_new = Anchor + (P_old - Anchor) * factor
            vx = f.position[0] - anchor.x()
            vy = f.position[1] - anchor.y()
            
            f.position = (anchor.x() + vx * factor, anchor.y() + vy * factor)
            
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0)

    def apply_rel_rotate(self, angle_deg):
        if not self.selected_frames: return
        
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        
        for f in self.selected_frames:
            f.rotation += angle_deg
            
            anchor = self.get_anchor_pos(f)
            
            # Rotate position around anchor
            # P_new = Anchor + Rotate(P_old - Anchor)
            vx = f.position[0] - anchor.x()
            vy = f.position[1] - anchor.y()
            
            # Rotate vector (vx, vy)
            rx = vx * cos_a - vy * sin_a
            ry = vx * sin_a + vy * cos_a
            
            f.position = (anchor.x() + rx, anchor.y() + ry)
            
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0,0,0)

    def on_t_w_changed(self):
        if self.updating_ui or not self.selected_frames:
            return
            
        w = self.t_w_spin.value()
        if w <= 0: return

        for f in self.selected_frames:
            if not os.path.exists(f.file_path): continue
            img = QImage(f.file_path)
            if img.isNull(): continue
            
            orig_w = f.crop_rect[2] if f.crop_rect else img.width()
            orig_h = f.crop_rect[3] if f.crop_rect else img.height()
            if orig_w <= 0 or orig_h <= 0: continue
            
            s_sign = 1 if f.scale >= 0 else -1
            if self.t_res_lock.isChecked():
                if abs(f.aspect_ratio - 1.0) < 0.001:
                    # 锁定 + 比例为1
                    f.scale = (w / orig_w) * s_sign
                    f.aspect_ratio = 1.0
                else:
                    # 锁定 + 比例不为1
                    f.scale = (w / orig_w) * s_sign
            else:
                # 不锁定
                current_h = int(orig_h * (f.scale / f.aspect_ratio))
                f.scale = (w / orig_w) * s_sign
                if current_h > 0:
                    f.aspect_ratio = (orig_h * f.scale) / current_h
            
        self.refresh_t_res_ui()

    def on_t_h_changed(self):
        if self.updating_ui or not self.selected_frames:
            return
            
        h = self.t_h_spin.value()
        if h <= 0: return

        for f in self.selected_frames:
            if not os.path.exists(f.file_path): continue
            img = QImage(f.file_path)
            if img.isNull(): continue
            
            orig_w = f.crop_rect[2] if f.crop_rect else img.width()
            orig_h = f.crop_rect[3] if f.crop_rect else img.height()
            if orig_w <= 0 or orig_h <= 0: continue
            
            s_sign = 1 if f.scale >= 0 else -1
            if self.t_res_lock.isChecked():
                if abs(f.aspect_ratio - 1.0) < 0.001:
                    f.scale = (h / orig_h) * s_sign
                    f.aspect_ratio = 1.0
                else:
                    f.scale = (h * f.aspect_ratio) / orig_h
            else:
                if h > 0:
                    f.aspect_ratio = (orig_h * f.scale) / h

        self.refresh_t_res_ui()

    def refresh_t_res_ui(self):
        """Update scale spin and canvas after any target res change."""
        if not self.selected_frames: return
        
        self.updating_ui = True
        self.scale_spin.setValue(self.selected_frames[0].scale)
        
        # Update H spin if W changed (locked) or vice versa
        first = self.selected_frames[0]
        if os.path.exists(first.file_path):
            img = QImage(first.file_path)
            if not img.isNull():
                orig_w = first.crop_rect[2] if first.crop_rect else img.width()
                orig_h = first.crop_rect[3] if first.crop_rect else img.height()
                if orig_w > 0 and orig_h > 0:
                    self.t_w_spin.setValue(int(abs(orig_w * first.scale)))
                    self.t_h_spin.setValue(int(abs(orig_h * (first.scale / first.aspect_ratio))))
        
        self.updating_ui = False
        
        self.frame_data_changed.emit(self.selected_frames[0].scale, 
                                     self.selected_frames[0].position[0], 
                                     self.selected_frames[0].position[1])

    def reset_aspect_ratio(self):
        """Reset aspect_ratio to 1.0 for all selected frames."""
        if not self.selected_frames:
            return
        
        for f in self.selected_frames:
            f.aspect_ratio = 1.0
        
        self.update_ui_from_selection()
        self.frame_data_changed.emit(0, 0, 0)

    def fit_to_canvas(self, mode):
        if not self.selected_frames:
            return
            
        for f in self.selected_frames:
            if os.path.exists(f.file_path):
                try:
                    img = QImage(f.file_path)
                    if not img.isNull():
                        # Use sliced dimensions if available
                        cur_w = f.crop_rect[2] if f.crop_rect else img.width()
                        cur_h = f.crop_rect[3] if f.crop_rect else img.height()
                        
                        if mode == "width" and cur_w > 0:
                            f.scale = self.project_width / cur_w
                        elif mode == "height" and cur_h > 0:
                            f.scale = self.project_height / cur_h
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
                # Scaled dimensions (sliced or full)
                if f.crop_rect:
                    _, _, cw, ch = f.crop_rect
                    w = cw * f.scale
                    h = ch * f.scale
                else:
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
            self.preview_label.setText(i18n.t("msg_no_selection"))
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
                
                if f.crop_rect:
                    cx, cy, cw, ch = f.crop_rect
                    src_w, src_h = cw, ch
                    scale = min(target_area / src_w, target_area / src_h)
                    final_w, final_h = int(src_w * scale), int(src_h * scale)
                    dest_x, dest_y = (w - final_w) // 2, (h - final_h) // 2
                    painter.drawImage(QRect(dest_x, dest_y, final_w, final_h), img, QRect(cx, cy, cw, ch))
                else:
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
                        
                        if f.crop_rect:
                            cx, cy, cw, ch = f.crop_rect
                            painter.drawImage(QRect(int(-cw/2), int(-ch/2), int(cw), int(ch)), img, QRect(cx, cy, cw, ch))
                        else:
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
