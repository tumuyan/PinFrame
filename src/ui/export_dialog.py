from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QCheckBox, QPushButton, 
                             QHBoxLayout, QLabel, QSpinBox, QRadioButton, 
                             QButtonGroup, QLineEdit)
from PyQt6.QtGui import QColor, QPalette
from i18n.manager import i18n
from .color_picker import ColorPickerWidget

class CommonExportSettings(QVBoxLayout):
    def __init__(self, parent=None):
        super().__init__()
        self.parent_dlg = parent
        
        # Preset Color Mapping for background
        bg_presets = {
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
        
        # Use ColorPickerWidget
        self.color_picker = ColorPickerWidget(parent, bg_presets, show_alpha=True)
        bg_layout.addLayout(self.color_picker)
        bg_layout.addStretch()
        bg_main_layout.addLayout(bg_layout)
        
        self.addLayout(bg_main_layout)
        self.addSpacing(10)

    def get_settings(self):
        mode = "all"
        if self.range_selected.isChecked(): mode = "selected"
        elif self.range_custom.isChecked(): mode = "custom"
        
        color = self.color_picker.get_color_tuple()
        return {
            "range_mode": mode,
            "custom_range": self.custom_range_edit.text(),
            "bg_color": color
        }

    def set_settings(self, mode, custom_range, bg_color_tuple):
        if mode == "selected": self.range_selected.setChecked(True)
        elif mode == "custom": self.range_custom.setChecked(True)
        else: self.range_all.setChecked(True)
        
        self.custom_range_edit.setText(custom_range)
        
        # Use ColorPickerWidget to set color
        self.color_picker.match_to_preset(bg_color_tuple)


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_export_title"))
        self.setMinimumWidth(350)
        
        self.export_type = None  # "sequence" or "gif"
        
        layout = QVBoxLayout(self)
        
        self.common = CommonExportSettings(self)
        layout.addLayout(self.common)
        
        self.use_original_names = QCheckBox(i18n.t("export_use_orig"))
        self.use_original_names.setChecked(True)
        self.use_original_names.setToolTip(i18n.t("export_use_orig_tip", "If checked, exported files will keep their original filenames (with index if duplicate). Otherwise, they will be numbered sequentially."))
        layout.addWidget(self.use_original_names)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.seq_btn = QPushButton(i18n.t("btn_export_sequence"))
        self.seq_btn.clicked.connect(lambda: self.on_export_clicked("sequence"))
        btn_layout.addWidget(self.seq_btn)
        
        self.gif_btn = QPushButton(i18n.t("btn_export_gif"))
        self.gif_btn.clicked.connect(lambda: self.on_export_clicked("gif"))
        btn_layout.addWidget(self.gif_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

    def on_export_clicked(self, export_type):
        self.export_type = export_type
        self.accept()

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

