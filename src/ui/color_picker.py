from PyQt6.QtWidgets import (QHBoxLayout, QFrame, QPushButton, 
                             QComboBox, QColorDialog, QLabel)
from PyQt6.QtGui import QColor
from i18n.manager import i18n


class ColorPickerWidget(QHBoxLayout):
    """
    Reusable color picker widget with preset colors and custom color selection.
    
    Contains:
    - Dropdown with preset colors
    - Color swatch preview
    - RGB value display
    - Pick button for custom color selection
    """
    
    def __init__(self, parent=None, presets=None, show_alpha=False):
        """
        Initialize color picker widget.
        
        Args:
            parent: Parent widget
            presets: Dictionary of preset colors {key: (r, g, b, a)}
            show_alpha: Whether to show alpha channel in color dialog
        """
        super().__init__()
        self.parent = parent
        self.show_alpha = show_alpha
        
        # Default presets if none provided
        if presets is None:
            self.presets = {
                "white": (255, 255, 255, 255),
                "black": (0, 0, 0, 255),
                "red": (255, 0, 0, 255),
                "green": (0, 255, 0, 255),
                "blue": (0, 0, 255, 255),
            }
        else:
            self.presets = presets
        
        self._create_widgets()
        
    def _create_widgets(self):
        """Create all child widgets."""
        # Preset color dropdown
        self.color_combo = QComboBox()
        for key, rgba in self.presets.items():
            display_name = i18n.t(f"color_{key}", key.capitalize())
            self.color_combo.addItem(display_name, key)
        self.color_combo.addItem(i18n.t("color_custom", "Custom"), "custom")
        self.color_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.addWidget(self.color_combo)
        
        # Color swatch
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(24, 24)
        self.color_swatch.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.color_swatch.setAutoFillBackground(True)
        self.addWidget(self.color_swatch)
        
        # RGB info label
        self.color_info_label = QLabel()
        self.color_info_label.setStyleSheet("color: gray; font-size: 11px;")
        self.color_info_label.setMinimumWidth(80)
        self.addWidget(self.color_info_label)
        
        # Pick button (hidden by default, shown for custom colors)
        self.pick_btn = QPushButton(i18n.t("btn_pick", "Pick..."))
        self.pick_btn.clicked.connect(self._pick_color)
        self.pick_btn.setVisible(False)
        self.addWidget(self.pick_btn)
        
        # Set default color (first preset)
        first_key = list(self.presets.keys())[0]
        self.set_color(QColor(*self.presets[first_key]))
        
    def _on_combo_changed(self, index):
        """Handle combo box selection change."""
        data = self.color_combo.currentData()
        if data in self.presets:
            # Preset color
            self.pick_btn.setVisible(False)
            self.set_color(QColor(*self.presets[data]))
        else:
            # Custom color
            self.pick_btn.setVisible(True)
            self._update_info_label()
    
    def _update_info_label(self):
        """Update RGB info label text."""
        c = self.current_color
        if self.show_alpha:
            text = f"R:{c.red():>3} G:{c.green():>3} B:{c.blue():>3} A:{c.alpha():>3}"
        else:
            text = f"R:{c.red():>3} G:{c.green():>3} B:{c.blue():>3}"
        self.color_info_label.setText(text)
    
    def _pick_color(self):
        """Open color dialog to pick custom color."""
        title = i18n.t("dlg_pick_color", "Pick Color")
        options = QColorDialog.ColorDialogOption.ShowAlphaChannel if self.show_alpha else QColorDialog.ColorDialogOption(0)
        color = QColorDialog.getColor(self.current_color, self.parent, title, options)
        
        if color.isValid():
            self.set_color(color)
    
    def set_color(self, color: QColor):
        """
        Set the current color.
        
        Args:
            color: QColor to set
        """
        self.current_color = QColor(color)
        
        # Update swatch appearance
        r, g, b, a = self.current_color.red(), self.current_color.green(), self.current_color.blue(), self.current_color.alpha()
        rgba_str = f"rgba({r}, {g}, {b}, {a/255.0})"
        self.color_swatch.setStyleSheet(f"background-color: {rgba_str}; border: 1px solid #888; border-radius: 2px;")
        
        self._update_info_label()
    
    def get_color(self) -> QColor:
        """
        Get the current color.
        
        Returns:
            Current QColor
        """
        return QColor(self.current_color)
    
    def get_color_tuple(self) -> tuple:
        """
        Get the current color as a tuple.
        
        Returns:
            Tuple of (r, g, b, a)
        """
        c = self.current_color
        return (c.red(), c.green(), c.blue(), c.alpha())
    
    def set_color_from_tuple(self, color_tuple: tuple):
        """
        Set color from tuple.
        
        Args:
            color_tuple: Tuple of (r, g, b, a)
        """
        self.set_color(QColor(*color_tuple))
    
    def match_to_preset(self, color_tuple: tuple):
        """
        Try to match the given color to a preset and update the combo box.
        
        Args:
            color_tuple: Tuple of (r, g, b, a) to match
        """
        color_tuple = tuple(color_tuple)
        
        # Try to find matching preset
        for key, val in self.presets.items():
            if val == color_tuple:
                idx = self.color_combo.findData(key)
                if idx >= 0:
                    self.color_combo.setCurrentIndex(idx)
                    return
        
        # No match found, set to custom
        idx = self.color_combo.findData("custom")
        if idx >= 0:
            self.color_combo.setCurrentIndex(idx)
            self.set_color_from_tuple(color_tuple)
