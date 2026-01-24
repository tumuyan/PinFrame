from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, 
                             QComboBox, QRadioButton, QButtonGroup, QWidget, QFrame)
from PyQt6.QtCore import Qt
from i18n.manager import i18n

class TimelineGridSettingsDialog(QDialog):
    """Settings dialog for timeline grid view"""
    
    def __init__(self, parent=None, current_width=120, current_height=120, 
                 current_multiline=False, current_background="checkerboard"):
        super().__init__(parent)
        
        self.current_width = current_width
        self.current_height = current_height
        self.current_multiline = current_multiline
        self.current_background = current_background
        
        self.result_width = current_width
        self.result_height = current_height
        self.result_multiline = current_multiline
        self.result_background = current_background
        
        self.setWindowTitle(i18n.t("dialog_timeline_grid_settings", "Grid View Settings"))
        self.setMinimumWidth(350)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Thumbnail Size Section
        size_group = self.create_size_section()
        layout.addWidget(size_group)
        
        # Filename Display Section
        filename_group = self.create_filename_section()
        layout.addWidget(filename_group)
        
        # Background Section
        background_group = self.create_background_section()
        layout.addWidget(background_group)
        
        # Buttons
        from PyQt6.QtWidgets import QDialogButtonBox
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def create_size_section(self):
        """Create thumbnail size settings section"""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout()
        
        title = QLabel(i18n.t("grid_settings_thumbnail_size", "Thumbnail Size"))
        title.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(title)
        
        # Width
        width_layout = QHBoxLayout()
        width_label = QLabel(i18n.t("grid_settings_width", "Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(50, 500)
        self.width_spin.setValue(self.current_width)
        self.width_spin.setSuffix(" px")
        width_layout.addWidget(width_label)
        width_layout.addWidget(self.width_spin)
        width_layout.addStretch()
        layout.addLayout(width_layout)
        
        # Height
        height_layout = QHBoxLayout()
        height_label = QLabel(i18n.t("grid_settings_height", "Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(50, 500)
        self.height_spin.setValue(self.current_height)
        self.height_spin.setSuffix(" px")
        height_layout.addWidget(height_label)
        height_layout.addWidget(self.height_spin)
        height_layout.addStretch()
        layout.addLayout(height_layout)
        
        frame.setLayout(layout)
        return frame
    
    def create_filename_section(self):
        """Create filename display settings section"""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout()
        
        title = QLabel(i18n.t("grid_settings_filename", "Filename Display"))
        title.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(title)
        
        # Single/Multi line radio buttons
        self.line_group = QButtonGroup()
        
        single_radio = QRadioButton(i18n.t("grid_settings_single_line", "Single Line"))
        single_radio.setChecked(not self.current_multiline)
        self.line_group.addButton(single_radio, 0)
        
        multi_radio = QRadioButton(i18n.t("grid_settings_multi_line", "Multi Line"))
        multi_radio.setChecked(self.current_multiline)
        self.line_group.addButton(multi_radio, 1)
        
        layout.addWidget(single_radio)
        layout.addWidget(multi_radio)
        
        # Hint text
        hint = QLabel(i18n.t("grid_settings_filename_hint", 
            "Single line: Shows truncated filename with ellipsis. Hover for full name."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(hint)
        
        frame.setLayout(layout)
        return frame
    
    def create_background_section(self):
        """Create background settings section"""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout()

        title = QLabel(i18n.t("grid_settings_background", "Preview Background"))
        title.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(title)

        # Background mode combo
        self.bg_combo = QComboBox()
        self.bg_combo.addItem(i18n.t("bg_checkerboard"), "checkerboard")
        self.bg_combo.addItem(i18n.t("bg_black"), "black")
        self.bg_combo.addItem(i18n.t("bg_white"), "white")
        self.bg_combo.addItem(i18n.t("grid_settings_gray", "Gray"), "gray")
        self.bg_combo.addItem(i18n.t("bg_green"), "green")
        self.bg_combo.addItem(i18n.t("bg_transparent", "Transparent"), "transparent")

        # Set current selection
        index = self.bg_combo.findData(self.current_background)
        if index >= 0:
            self.bg_combo.setCurrentIndex(index)

        layout.addWidget(self.bg_combo)

        frame.setLayout(layout)
        return frame
    
    def get_settings(self):
        """Get the settings from dialog"""
        self.result_width = self.width_spin.value()
        self.result_height = self.height_spin.value()
        self.result_multiline = (self.line_group.checkedId() == 1)
        self.result_background = self.bg_combo.currentData()
        
        return {
            'width': self.result_width,
            'height': self.result_height,
            'multiline': self.result_multiline,
            'background': self.result_background
        }
