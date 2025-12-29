from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QCheckBox, QPushButton, 
                             QHBoxLayout, QLabel, QSpinBox, QRadioButton, 
                             QButtonGroup, QLineEdit, QColorDialog, QFrame,
                             QComboBox)
from PyQt6.QtGui import QColor, QPalette
from i18n.manager import i18n

class CommonExportSettings(QVBoxLayout):
    def __init__(self, parent=None):
        super().__init__()
        self.parent_dlg = parent
        
        # Preset Color Mapping
        self.presets = {
            "trans": (0, 0, 0, 0),
            "white": (255, 255, 255, 255),
            "green": (0, 255, 0, 255),
            "red": (255, 0, 0, 255),
            "black": (0, 0, 0, 255)
        }
        
        # Range Selection
        self.range_group = QButtonGroup(parent)
        
        range_layout = QVBoxLayout()
        range_layout.addWidget(QLabel(i18n.t("export_range_title", "Export Range:")))
        
        self.range_all = QRadioButton(i18n.t("export_range_all", "All Frames"))
        self.range_selected = QRadioButton(i18n.t("export_range_selected", "Selected Frames"))
        self.range_custom = QRadioButton(i18n.t("export_range_custom", "Custom Range:"))
        
        self.range_group.addButton(self.range_all)
        self.range_group.addButton(self.range_selected)
        self.range_group.addButton(self.range_custom)
        
        range_layout.addWidget(self.range_all)
        range_layout.addWidget(self.range_selected)
        
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(self.range_custom)
        self.custom_range_edit = QLineEdit()
        self.custom_range_edit.setPlaceholderText("e.g. 1, 3, 5-10, 15-")
        self.custom_range_edit.setEnabled(False)
        custom_layout.addWidget(self.custom_range_edit)
        range_layout.addLayout(custom_layout)
        
        self.range_all.setChecked(True)
        self.range_custom.toggled.connect(self.custom_range_edit.setEnabled)
        
        self.addLayout(range_layout)
        self.addSpacing(10)
        
        # Background Color
        bg_main_layout = QVBoxLayout()
        bg_main_layout.addWidget(QLabel(i18n.t("export_bg_color", "Background Color:")))
        
        bg_layout = QHBoxLayout()
        
        self.color_combo = QComboBox()
        self.color_combo.addItem(i18n.t("export_color_trans"), "trans")
        self.color_combo.addItem(i18n.t("export_color_white"), "white")
        self.color_combo.addItem(i18n.t("export_color_green"), "green")
        self.color_combo.addItem(i18n.t("export_color_red"), "red")
        self.color_combo.addItem(i18n.t("export_color_black"), "black")
        self.color_combo.addItem(i18n.t("export_color_custom"), "custom")
        self.color_combo.currentIndexChanged.connect(self.on_combo_changed)
        bg_layout.addWidget(self.color_combo)
        
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(20, 20)
        self.color_swatch.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.color_swatch.setAutoFillBackground(True)
        bg_layout.addWidget(self.color_swatch)

        # Color Info Label
        self.color_info_label = QLabel()
        self.color_info_label.setStyleSheet("color: gray; font-size: 11px;")
        bg_layout.addWidget(self.color_info_label)
        
        self.color_btn = QPushButton(i18n.t("btn_pick", "Pick..."))
        self.color_btn.clicked.connect(self.pick_color)
        self.color_btn.setVisible(False)
        bg_layout.addWidget(self.color_btn)
        
        bg_layout.addStretch()
        bg_main_layout.addLayout(bg_layout)
        
        self.addLayout(bg_main_layout)
        self.addSpacing(10)
        
        self.set_swatch_color(QColor(0, 0, 0, 0))

    def on_combo_changed(self, index):
        data = self.color_combo.currentData()
        if data in self.presets:
            self.color_btn.setVisible(False)
            self.set_swatch_color(QColor(*self.presets[data]))
        else:
            self.color_btn.setVisible(True)
            self.update_info_label()

    def update_info_label(self):
        c = self.current_color
        text = i18n.t("label_color_info").format(r=c.red(), g=c.green(), b=c.blue(), a=c.alpha())
        self.color_info_label.setText(text)

    def set_swatch_color(self, color):
        self.current_color = color
        # Use stylesheet for reliability across themes
        r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
        rgba_str = f"rgba({r}, {g}, {b}, {a/255.0})"
        # If the swatch is too transparent, we might want to show something? 
        # But for now, just the color.
        self.color_swatch.setStyleSheet(f"background-color: {rgba_str}; border: 1px solid #888; border-radius: 2px;")
        self.update_info_label()

    def pick_color(self):
        color = QColorDialog.getColor(self.current_color, self.parent_dlg, i18n.t("dlg_pick_color", "Pick Background Color"), QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            self.set_swatch_color(color)

    def get_settings(self):
        mode = "all"
        if self.range_selected.isChecked(): mode = "selected"
        elif self.range_custom.isChecked(): mode = "custom"
        
        color = self.current_color
        return {
            "range_mode": mode,
            "custom_range": self.custom_range_edit.text(),
            "bg_color": (color.red(), color.green(), color.blue(), color.alpha())
        }

    def set_settings(self, mode, custom_range, bg_color_tuple):
        if mode == "selected": self.range_selected.setChecked(True)
        elif mode == "custom": self.range_custom.setChecked(True)
        else: self.range_all.setChecked(True)
        
        self.custom_range_edit.setText(custom_range)
        
        # Match color to preset or set custom
        found = False
        color_tuple = tuple(bg_color_tuple)
        for key, val in self.presets.items():
            if val == color_tuple:
                idx = self.color_combo.findData(key)
                if idx >= 0:
                    self.color_combo.setCurrentIndex(idx)
                    found = True
                    break
        
        if not found:
            idx = self.color_combo.findData("custom")
            self.color_combo.setCurrentIndex(idx)
            self.set_swatch_color(QColor(*bg_color_tuple))


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_export_title"))
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout(self)
        
        self.common = CommonExportSettings(self)
        layout.addLayout(self.common)
        
        self.use_original_names = QCheckBox(i18n.t("export_use_orig"))
        self.use_original_names.setChecked(True)
        self.use_original_names.setToolTip(i18n.t("export_use_orig_tip", "If checked, exported files will keep their original filenames (with index if duplicate). Otherwise, they will be numbered sequentially."))
        layout.addWidget(self.use_original_names)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.ok_btn = QPushButton(i18n.t("btn_export"))
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

class SpriteSheetExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("action_export_sheet"))
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout(self)
        
        self.common = CommonExportSettings(self)
        layout.addLayout(self.common)
        
        # Columns
        layout.addWidget(QLabel(i18n.t("sheet_cols")))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 100)
        self.cols_spin.setValue(4)
        layout.addWidget(self.cols_spin)
        
        # Padding
        layout.addWidget(QLabel(i18n.t("sheet_padding")))
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 1000)
        self.padding_spin.setValue(0)
        layout.addWidget(self.padding_spin)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.ok_btn = QPushButton(i18n.t("btn_export"))
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

