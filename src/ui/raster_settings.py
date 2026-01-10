from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                              QDoubleSpinBox, QPushButton, QCheckBox, QColorDialog)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from i18n.manager import i18n

class RasterizationSettingsDialog(QDialog):
    def __init__(self, parent=None, enabled=False, grid_color=(0, 0, 0), scale_threshold=1.5):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_raster_settings"))
        self.setFixedSize(300, 200)
        
        layout = QVBoxLayout(self)
        
        # Enable Checkbox
        self.enable_check = QCheckBox(i18n.t("raster_enable"))
        self.enable_check.setChecked(enabled)
        layout.addWidget(self.enable_check)
        
        layout.addSpacing(10)
        
        # Grid Color
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel(i18n.t("raster_grid_color")))
        self.color_btn = QPushButton()
        self.grid_color = QColor(*grid_color)
        self._update_color_button()
        self.color_btn.clicked.connect(self._pick_color)
        color_layout.addWidget(self.color_btn)
        layout.addLayout(color_layout)
        
        # Scale Threshold
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel(i18n.t("raster_scale_threshold")))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(1.0, 10.0)
        self.threshold_spin.setSingleStep(0.1)
        self.threshold_spin.setValue(scale_threshold)
        threshold_layout.addWidget(self.threshold_spin)
        layout.addLayout(threshold_layout)
        
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
    
    def _update_color_button(self):
        self.color_btn.setStyleSheet(
            f"background-color: {self.grid_color.name()}; border: 1px solid #666;"
        )
    
    def _pick_color(self):
        color = QColorDialog.getColor(self.grid_color, self, i18n.t("dlg_pick_color", "Pick Color"))
        if color.isValid():
            self.grid_color = color
            self._update_color_button()
    
    def get_settings(self):
        return {
            "enabled": self.enable_check.isChecked(),
            "grid_color": (self.grid_color.red(), self.grid_color.green(), self.grid_color.blue()),
            "scale_threshold": self.threshold_spin.value()
        }
