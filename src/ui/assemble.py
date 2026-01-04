import os

# Top Part Construction
top_part = r"""import os
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
        
        # Custom Anchor Inputs
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
        
        # Grid for Move, Scale, Rotate
        op_grid = QGridLayout()
        
        # Row 0: Move
        # [Step] [Left] [Right] [Up] [Down]
        
        op_grid.addWidget(QLabel(i18n.t("prop_move_step") if i18n.has("prop_move_step") else "Step:"), 0, 0)
        
        self.step_move_spin = QDoubleSpinBox()
        self.step_move_spin.setRange(0, 9999)
        self.step_move_spin.setValue(10.0)
        op_grid.addWidget(self.step_move_spin, 0, 1)
        
        self.btn_move_left = QPushButton("←")
        self.btn_move_left.clicked.connect(lambda: self.apply_rel_move(-self.step_move_spin.value(), 0))
        op_grid.addWidget(self.btn_move_left, 0, 2)
        
        self.btn_move_right = QPushButton("→")
        self.btn_move_right.clicked.connect(lambda: self.apply_rel_move(self.step_move_spin.value(), 0))
        op_grid.addWidget(self.btn_move_right, 0, 3)
        
        self.btn_move_up = QPushButton("↑")
        self.btn_move_up.clicked.connect(lambda: self.apply_rel_move(0, -self.step_move_spin.value()))
        op_grid.addWidget(self.btn_move_up, 0, 4)
        
        self.btn_move_down = QPushButton("↓")
        self.btn_move_down.clicked.connect(lambda: self.apply_rel_move(0, self.step_move_spin.value()))
        op_grid.addWidget(self.btn_move_down, 0, 5)

        # Row 1: Scale
        op_grid.addWidget(QLabel(i18n.t("prop_scale_step")), 1, 0)
        self.step_scale_spin = QDoubleSpinBox()
        self.step_scale_spin.setRange(1.01, 10.0)
        self.step_scale_spin.setSingleStep(0.1)
        self.step_scale_spin.setValue(1.1)
        op_grid.addWidget(self.step_scale_spin, 1, 1)
        
        self.btn_scale_up = QPushButton(i18n.t("btn_scale_up"))
        self.btn_scale_up.clicked.connect(lambda: self.apply_rel_scale(self.step_scale_spin.value()))
        op_grid.addWidget(self.btn_scale_up, 1, 2, 1, 2)
        
        self.btn_scale_down = QPushButton(i18n.t("btn_scale_down"))
        self.btn_scale_down.clicked.connect(lambda: self.apply_rel_scale(1.0 / self.step_scale_spin.value()))
        op_grid.addWidget(self.btn_scale_down, 1, 4, 1, 2)
        
        # Row 2: Rotate
        op_grid.addWidget(QLabel(i18n.t("prop_rotate_step")), 2, 0)
        self.step_rotate_spin = QDoubleSpinBox()
        self.step_rotate_spin.setRange(1, 180)
        self.step_rotate_spin.setValue(15)
        op_grid.addWidget(self.step_rotate_spin, 2, 1)
        
        self.btn_rotate_ccw = QPushButton(i18n.t("btn_rotate_ccw"))
        self.btn_rotate_ccw.clicked.connect(lambda: self.apply_rel_rotate(-self.step_rotate_spin.value()))
        op_grid.addWidget(self.btn_rotate_ccw, 2, 2, 1, 2)
        
        self.btn_rotate_cw = QPushButton(i18n.t("btn_rotate_cw"))
        self.btn_rotate_cw.clicked.connect(lambda: self.apply_rel_rotate(self.step_rotate_spin.value()))
        op_grid.addWidget(self.btn_rotate_cw, 2, 4, 1, 2)
        
        rel_layout.addLayout(op_grid)
        layout.addWidget(self.rel_trans_group)
        
        # Alignment
"""

with open('a:/ProjectPython/Image2Frame/src/ui/temp_prop.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

align_idx = -1
for i, line in enumerate(lines):
    if '# Alignment' in line:
        align_idx = i
        break
    
if align_idx == -1:
    print("Error: Alignment not found")
    exit(1)
    
bottom = "".join(lines[align_idx+1:]) # +1 because Top Part includes # Alignment line?
# Wait, Top Part ends with `# Alignment`.
# But in my logic above, Top Part ends with `layout.addWidget(self.rel_trans_group)` ?
# No, let's look at the String.
# It ends with `layout.addWidget(self.rel_trans_group)`.
# Then `        # Alignment`.
# So Top Part DOES include `# Alignment` comment.
# So `bottom` should start AFTER `# Alignment`.
# But `view_file` had `self.align_group = ...` after `# Alignment`.
# So I need to skip `# Alignment` in `bottom`.

full = top_part + bottom

with open('a:/ProjectPython/Image2Frame/src/ui/property_panel.py', 'w', encoding='utf-8') as f:
    f.write(full)

print("Success")
