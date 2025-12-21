from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QHBoxLayout, QLabel, QSpinBox
from i18n.manager import i18n

class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_export_title"))
        self.resize(300, 100)
        
        layout = QVBoxLayout(self)
        
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
        self.resize(300, 150)
        
        layout = QVBoxLayout(self)
        
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
