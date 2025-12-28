from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSpinBox, QDoubleSpinBox, QPushButton, QCheckBox)
from PyQt6.QtCore import Qt
from i18n.manager import i18n

class OnionSettingsDialog(QDialog):
    def __init__(self, parent=None, prev_frames=1, next_frames=0, opacity_step=0.2, exclusive=False):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_onion_skin"))
        self.setFixedSize(300, 300)
        
        layout = QVBoxLayout(self)
        
        # Exclusive Checkbox
        self.exclusive_check = QCheckBox(i18n.t("onion_ref_exclusive"))
        self.exclusive_check.setChecked(exclusive)
        layout.addWidget(self.exclusive_check)
        
        layout.addSpacing(10)
        
        # Previous Frames
        prev_layout = QHBoxLayout()
        prev_layout.addWidget(QLabel(i18n.t("onion_prev")))
        self.prev_spin = QSpinBox()
        self.prev_spin.setRange(0, 10)
        self.prev_spin.setValue(prev_frames)
        prev_layout.addWidget(self.prev_spin)
        layout.addLayout(prev_layout)
        
        # Next Frames
        next_layout = QHBoxLayout()
        next_layout.addWidget(QLabel(i18n.t("onion_next")))
        self.next_spin = QSpinBox()
        self.next_spin.setRange(0, 10)
        self.next_spin.setValue(next_frames)
        next_layout.addWidget(self.next_spin)
        layout.addLayout(next_layout)
        
        # Opacity Step
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel(i18n.t("onion_opacity_step")))
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.05, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(opacity_step)
        opacity_layout.addWidget(self.opacity_spin)
        layout.addLayout(opacity_layout)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton(i18n.t("btn_ok", "OK"))
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton(i18n.t("btn_cancel", "Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_settings(self):
        return {
            "exclusive": self.exclusive_check.isChecked(),
            "prev": self.prev_spin.value(),
            "next": self.next_spin.value(),
            "opacity": self.opacity_spin.value()
        }
