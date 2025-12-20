from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QHBoxLayout

class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Options")
        self.resize(300, 100)
        
        layout = QVBoxLayout(self)
        
        self.use_original_names = QCheckBox("Use Original Filenames")
        self.use_original_names.setChecked(True)
        self.use_original_names.setToolTip("If checked, exported files will keep their original filenames (with index if duplicate). Otherwise, they will be numbered sequentially.")
        layout.addWidget(self.use_original_names)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.ok_btn = QPushButton("Export")
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
