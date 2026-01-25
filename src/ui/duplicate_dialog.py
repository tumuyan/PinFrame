from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
                             QComboBox, QDialogButtonBox)
from PyQt6.QtCore import Qt
from i18n.manager import i18n


class DuplicateFramesDialog(QDialog):
    """Dialog for duplicating frames with custom options"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_duplicate_frames"))
        self.setModal(True)
        self.result_count = 1
        self.result_mode = "ABAB"  # Default mode

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Repeat count
        count_layout = QHBoxLayout()
        count_label = QLabel(i18n.t("dup_repeat_count"))
        count_label.setMinimumWidth(120)
        self.count_spinbox = QSpinBox()
        self.count_spinbox.setRange(1, 99)
        self.count_spinbox.setValue(3)
        self.count_spinbox.setMinimumWidth(150)
        count_layout.addWidget(count_label)
        count_layout.addWidget(self.count_spinbox, 1)
        count_layout.addStretch()
        layout.addLayout(count_layout)

        # Duplicate mode
        mode_layout = QHBoxLayout()
        mode_label = QLabel(i18n.t("dup_repeat_mode"))
        mode_label.setMinimumWidth(120)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(i18n.t("dup_mode_abab"), "ABAB")
        self.mode_combo.addItem(i18n.t("dup_mode_aabb"), "AABB")
        self.mode_combo.setMinimumWidth(150)
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo, 1)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Preview text
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.preview_label)

        # Update preview when options change
        self.count_spinbox.valueChanged.connect(self._update_preview)
        self.mode_combo.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _update_preview(self):
        """Update preview text based on current selection"""
        count = self.count_spinbox.value()
        mode = self.mode_combo.currentData()

        if mode == "ABAB":
            example = i18n.t("dup_example_abab").format(count=count)
        else:  # AABB
            example = i18n.t("dup_example_aabb").format(count=count)

        self.preview_label.setText(example)

    def accept(self):
        """Accept dialog and store results"""
        self.result_count = self.count_spinbox.value()
        self.result_mode = self.mode_combo.currentData()
        super().accept()

    def get_options(self):
        """Return the dialog options"""
        return {
            'count': self.result_count,
            'mode': self.result_mode
        }
