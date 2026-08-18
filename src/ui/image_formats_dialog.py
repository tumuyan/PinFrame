"""图像格式设置对话框。

让用户自定义应用可识别的图像文件后缀（扩展名）。
设置持久化到 QSettings，影响文件导入过滤与 add_files 的合法性判断。
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QLineEdit, QPushButton,
                             QMessageBox, QListWidgetItem)
from PyQt6.QtCore import Qt

from core import image_formats
from i18n.manager import i18n


class ImageFormatsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_image_formats_title"))
        self.setMinimumWidth(380)
        self.setup_ui()
        self.load_formats()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t("lbl_image_formats_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.format_list = QListWidget()
        layout.addWidget(self.format_list)

        entry_layout = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(i18n.t("lbl_image_format_placeholder"))
        entry_layout.addWidget(self.entry)

        add_btn = QPushButton(i18n.t("btn_add"))
        add_btn.clicked.connect(self.add_format)
        entry_layout.addWidget(add_btn)
        layout.addLayout(entry_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.reset_btn = QPushButton(i18n.t("btn_reset_default"))
        self.reset_btn.clicked.connect(self.reset_to_default)
        btn_layout.addWidget(self.reset_btn)

        ok_btn = QPushButton(i18n.t("btn_ok"))
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(i18n.t("btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def load_formats(self):
        self.format_list.clear()
        for fmt in image_formats.supported_formats():
            self.format_list.addItem(fmt)

    def add_format(self):
        text = self.entry.text().strip()
        if not text:
            return
        ext = text.lower()
        if not ext.startswith("."):
            ext = "." + ext
        if not self._is_valid(ext):
            QMessageBox.warning(self, i18n.t("dlg_image_formats_title"),
                                i18n.t("msg_invalid_image_format").format(ext=ext))
            return
        # 避免重复
        for i in range(self.format_list.count()):
            if self.format_list.item(i).text() == ext:
                self.entry.clear()
                return
        self.format_list.addItem(ext)
        self.entry.clear()

    def _is_valid(self, ext: str) -> bool:
        """校验后缀格式：仅允许字母/数字，长度 1-10 位。

        图像格式后缀可能含数字（如 jp2、j2k），因此用 isalnum() 允许字母/数字，
        与提示文案"仅允许字母/数字"保持一致；长度放宽到 10 以兼容较长后缀（如 jpeg2000）。
        """
        body = ext[1:] if ext.startswith(".") else ext
        if not body:
            return False
        return all(c.isalnum() for c in body) and len(body) <= 10

    def reset_to_default(self):
        # 先真正持久化重置存储（删除 QSettings 自定义项、失效缓存），
        # 再刷新 UI 列表，避免只改列表框而未重置存储的功能性 bug。
        image_formats.reset_to_default()
        self.format_list.clear()
        for fmt in image_formats.supported_formats():
            self.format_list.addItem(fmt)

    def accept(self):
        formats = []
        for i in range(self.format_list.count()):
            item = self.format_list.item(i)
            text = item.text().strip().lower()
            if text and text not in formats:
                formats.append(text)
        image_formats.save_formats(formats)
        super().accept()

    def keyPressEvent(self, event):
        # 删除选中项
        if event.key() == Qt.Key.Key_Delete:
            for item in self.format_list.selectedItems():
                row = self.format_list.row(item)
                self.format_list.takeItem(row)
            event.accept()
            return
        super().keyPressEvent(event)
