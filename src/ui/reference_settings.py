from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSpinBox, QCheckBox, QPushButton, QComboBox, QGridLayout)
from PyQt6.QtCore import Qt
from i18n.manager import i18n

class ReferenceSettingsDialog(QDialog):
    def __init__(self, parent=None, opacity=0.5, layer="top", show_on_playback=False):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_ref_settings"))
        self.resize(300, 200)
        
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        
        # Opacity
        grid.addWidget(QLabel(i18n.t("ref_opacity")), 0, 0)
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.setValue(int(opacity * 100))
        grid.addWidget(self.opacity_spin, 0, 1)
        
        # Layer
        grid.addWidget(QLabel(i18n.t("ref_layer")), 1, 0)
        self.layer_combo = QComboBox()
        self.layer_combo.addItem(i18n.t("ref_layer_top"), "top")
        self.layer_combo.addItem(i18n.t("ref_layer_bottom"), "bottom")
        
        index = self.layer_combo.findData(layer)
        if index >= 0:
            self.layer_combo.setCurrentIndex(index)
        grid.addWidget(self.layer_combo, 1, 1)
        
        layout.addLayout(grid)
        
        # Playback
        self.playback_check = QCheckBox(i18n.t("ref_show_playback"))
        self.playback_check.setChecked(show_on_playback)
        layout.addWidget(self.playback_check)
        
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
        
    def get_settings(self):
        return {
            "opacity": self.opacity_spin.value() / 100.0,
            "layer": self.layer_combo.currentData(),
            "show_on_playback": self.playback_check.isChecked()
        }
