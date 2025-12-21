from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSpinBox, QCheckBox, QPushButton, QGroupBox, QGridLayout)
from PyQt6.QtCore import Qt
from i18n.manager import i18n

class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_width=1920, current_height=1080):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_settings_title"))
        self.resize(300, 200)
        
        self.current_width = current_width
        self.current_height = current_height
        self.aspect_ratio = current_width / current_height if current_height > 0 else 1.0
        
        layout = QVBoxLayout(self)
        
        # Resolution Group
        res_group = QGroupBox(i18n.t("settings_target_res"))
        res_layout = QGridLayout(res_group)
        
        res_layout.addWidget(QLabel(i18n.t("settings_width")), 0, 0)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16384)
        self.width_spin.setValue(current_width)
        res_layout.addWidget(self.width_spin, 0, 1)
        
        res_layout.addWidget(QLabel(i18n.t("settings_height")), 1, 0)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 16384)
        self.height_spin.setValue(current_height)
        res_layout.addWidget(self.height_spin, 1, 1)
        
        layout.addWidget(res_group)
        
        # Options
        self.lock_ar_check = QCheckBox(i18n.t("settings_lock_ar"))
        self.lock_ar_check.setChecked(True)
        layout.addWidget(self.lock_ar_check)
        
        self.prop_rescale_check = QCheckBox(i18n.t("settings_rescale"))
        self.prop_rescale_check.setToolTip(i18n.t("settings_rescale_tip", "Scale and move frames to match the new resolution"))
        self.prop_rescale_check.setChecked(True)
        layout.addWidget(self.prop_rescale_check)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.ok_btn = QPushButton(i18n.t("btn_ok"))
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # Signals
        self.width_spin.valueChanged.connect(self.on_width_changed)
        self.height_spin.valueChanged.connect(self.on_height_changed)
        self.lock_ar_check.toggled.connect(self.on_lock_toggled)

        self.updating = False

    def on_width_changed(self, w):
        if self.updating or not self.lock_ar_check.isChecked():
            return
        
        self.updating = True
        new_h = int(w / self.aspect_ratio)
        self.height_spin.setValue(new_h)
        self.updating = False

    def on_height_changed(self, h):
        if self.updating or not self.lock_ar_check.isChecked():
            return
            
        self.updating = True
        new_w = int(h * self.aspect_ratio)
        self.width_spin.setValue(new_w)
        self.updating = False

    def on_lock_toggled(self, checked):
        if checked:
            w = self.width_spin.value()
            h = self.height_spin.value()
            if h > 0:
                self.aspect_ratio = w / h
