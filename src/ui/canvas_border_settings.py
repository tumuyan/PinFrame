from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSpinBox, QPushButton)
from PyQt6.QtGui import QColor
from i18n.manager import i18n
from .color_picker import ColorPickerWidget


class CanvasBorderSettingsDialog(QDialog):
    """
    Dialog for configuring canvas border settings.
    
    Provides options for:
    - Inner border color and width
    - Outer border color and width
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_canvas_border_settings", "Canvas Border Settings"))
        self.setMinimumWidth(400)
        
        # Preset colors for borders
        border_presets = {
            "white": (255, 255, 255, 255),
            "black": (0, 0, 0, 255),
            "gray": (128, 128, 128, 255),
            "red": (255, 0, 0, 255),
            "green": (0, 255, 0, 255),
            "blue": (0, 0, 255, 255),
            "yellow": (255, 255, 0, 255),
        }
        
        layout = QVBoxLayout(self)
        
        # Inner Border Section
        inner_group = self._create_border_section(
            "canvas_inner_border", "Inner Border", border_presets
        )
        layout.addLayout(inner_group)
        
        layout.addSpacing(15)
        
        # Outer Border Section
        outer_group = self._create_border_section(
            "canvas_outer_border", "Outer Border", border_presets
        )
        layout.addLayout(outer_group)
        
        layout.addSpacing(20)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.ok_btn = QPushButton(i18n.t("btn_ok", "OK"))
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel", "Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # Set default values
        self._set_defaults()
    
    def _create_border_section(self, prefix, title, presets):
        """
        Create a border settings section.
        
        Args:
            prefix: i18n key prefix for this section
            title: Section title
            presets: Color presets dictionary
            
        Returns:
            QVBoxLayout containing the section widgets
        """
        section = QVBoxLayout()
        
        # Section title
        title_label = QLabel(i18n.t(prefix, title))
        title_label.setStyleSheet("font-weight: bold;")
        section.addWidget(title_label)
        
        # Color picker row
        color_layout = QHBoxLayout()
        color_label = QLabel(i18n.t(f"{prefix}_color", "Color:"))
        color_layout.addWidget(color_label)
        
        color_picker = ColorPickerWidget(self, presets, show_alpha=False)
        color_layout.addLayout(color_picker)
        color_layout.addStretch()
        section.addLayout(color_layout)
        
        # Width spinbox row
        width_layout = QHBoxLayout()
        width_label = QLabel(i18n.t(f"{prefix}_width", "Width:"))
        width_layout.addWidget(width_label)
        
        width_spin = QSpinBox()
        width_spin.setRange(0, 20)
        width_spin.setSuffix(" px")
        width_layout.addWidget(width_spin)
        width_layout.addStretch()
        section.addLayout(width_layout)
        
        # Store references
        setattr(self, f"{prefix}_picker", color_picker)
        setattr(self, f"{prefix}_spin", width_spin)
        
        return section
    
    def _set_defaults(self):
        """Set default values."""
        # Default: Inner border white, width 2
        self.canvas_inner_border_picker.set_color(QColor(255, 255, 255))
        self.canvas_inner_border_spin.setValue(2)
        
        # Default: Outer border black, width 1
        self.canvas_outer_border_picker.set_color(QColor(0, 0, 0))
        self.canvas_outer_border_spin.setValue(1)
    
    def get_settings(self):
        """
        Get current border settings.
        
        Returns:
            Dictionary with border settings
        """
        inner_color = self.canvas_inner_border_picker.get_color_tuple()
        outer_color = self.canvas_outer_border_picker.get_color_tuple()
        
        return {
            "inner_color": inner_color,
            "inner_width": self.canvas_inner_border_spin.value(),
            "outer_color": outer_color,
            "outer_width": self.canvas_outer_border_spin.value(),
        }
    
    def set_settings(self, settings: dict):
        """
        Set border settings from dictionary.
        
        Args:
            settings: Dictionary with border settings
        """
        if "inner_color" in settings:
            self.canvas_inner_border_picker.set_color_from_tuple(settings["inner_color"])
        
        if "inner_width" in settings:
            self.canvas_inner_border_spin.setValue(settings["inner_width"])
        
        if "outer_color" in settings:
            self.canvas_outer_border_picker.set_color_from_tuple(settings["outer_color"])
        
        if "outer_width" in settings:
            self.canvas_outer_border_spin.setValue(settings["outer_width"])
    
    def match_to_presets(self, inner_color_tuple: tuple, outer_color_tuple: tuple):
        """
        Try to match the given colors to presets.
        
        Args:
            inner_color_tuple: Tuple of (r, g, b) for inner border
            outer_color_tuple: Tuple of (r, g, b) for outer border
        """
        if inner_color_tuple:
            self.canvas_inner_border_picker.match_to_preset(tuple(inner_color_tuple) + (255,))
        if outer_color_tuple:
            self.canvas_outer_border_picker.match_to_preset(tuple(outer_color_tuple) + (255,))
