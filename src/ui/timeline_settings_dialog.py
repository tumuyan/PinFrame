from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                              QSpinBox, QCheckBox, QPushButton, QGroupBox, QGridLayout, QComboBox)
from PyQt6.QtCore import Qt
from i18n.manager import i18n

class TimelineSettingsDialog(QDialog):
    def __init__(self, parent=None, grid_view_enabled=False, 
                 thumbnail_width=120, thumbnail_height=120, 
                 filename_line_mode="single"):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_timeline_settings_title", "Timeline Settings"))
        self.resize(350, 250)
        
        self.grid_view_enabled = grid_view_enabled
        self.thumbnail_width = thumbnail_width
        self.thumbnail_height = thumbnail_height
        self.filename_line_mode = filename_line_mode
        
        layout = QVBoxLayout(self)
        
        # Grid View Group
        grid_group = QGroupBox(i18n.t("timeline_settings_group_grid", "Grid View"))
        grid_layout = QGridLayout(grid_group)
        
        # Enable Grid View Checkbox
        self.grid_view_check = QCheckBox(i18n.t("timeline_settings_enable_grid", "Enable Grid View"))
        self.grid_view_check.setChecked(self.grid_view_enabled)
        grid_layout.addWidget(self.grid_view_check, 0, 0, 1, 2)
        
        # Thumbnail Width
        grid_layout.addWidget(QLabel(i18n.t("timeline_settings_thumb_width", "Thumbnail Width:")), 1, 0)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(40, 512)
        self.width_spin.setValue(self.thumbnail_width)
        self.width_spin.setSuffix(" px")
        grid_layout.addWidget(self.width_spin, 1, 1)
        
        # Thumbnail Height
        grid_layout.addWidget(QLabel(i18n.t("timeline_settings_thumb_height", "Thumbnail Height:")), 2, 0)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(40, 512)
        self.height_spin.setValue(self.thumbnail_height)
        self.height_spin.setSuffix(" px")
        grid_layout.addWidget(self.height_spin, 2, 1)
        
        layout.addWidget(grid_group)
        
        # Filename Display Group
        filename_group = QGroupBox(i18n.t("timeline_settings_group_filename", "Filename Display"))
        filename_layout = QVBoxLayout(filename_group)
        
        filename_layout.addWidget(QLabel(i18n.t("timeline_settings_filename_mode", "Filename Display Mode:")))
        
        self.filename_mode_combo = QComboBox()
        self.filename_mode_combo.addItem(i18n.t("timeline_settings_filename_single", "Single Line (Smart Ellipsis)"), "single")
        self.filename_mode_combo.addItem(i18n.t("timeline_settings_filename_multi", "Multi Line (Wrap)"), "multiple")
        
        # Set current mode
        index = self.filename_mode_combo.findData(self.filename_line_mode)
        if index >= 0:
            self.filename_mode_combo.setCurrentIndex(index)
        
        filename_layout.addWidget(self.filename_mode_combo)
        filename_layout.addWidget(
            QLabel(i18n.t("timeline_settings_filename_tip", 
                          "Single line mode will show frame number with ellipsis for long filenames.\n"
                          "Hover over filename to see full text."))
        )
        
        layout.addWidget(filename_group)
        
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
        
        # Connect grid view checkbox to enable/disable spin boxes
        self.grid_view_check.toggled.connect(self.on_grid_view_toggled)
        self.on_grid_view_toggled(self.grid_view_enabled)

    def on_grid_view_toggled(self, checked):
        """Enable or disable thumbnail size controls based on grid view checkbox"""
        self.width_spin.setEnabled(checked)
        self.height_spin.setEnabled(checked)

    def get_settings(self):
        """Return the current settings as a dictionary"""
        return {
            "grid_view_enabled": self.grid_view_check.isChecked(),
            "thumbnail_width": self.width_spin.value(),
            "thumbnail_height": self.height_spin.value(),
            "filename_line_mode": self.filename_mode_combo.currentData()
        }
