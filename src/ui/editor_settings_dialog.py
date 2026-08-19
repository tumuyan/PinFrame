import os

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QListWidget, QListWidgetItem,
                             QLineEdit, QFileDialog, QInputDialog)
from PyQt6.QtCore import Qt, QSettings
from i18n.manager import i18n


def load_image_editors():
    """从 QSettings 读取外部图像编辑器配置。

    该配置是全局生效的（与具体工程无关），因此存于 QSettings 而非工程文件。
    返回编辑器列表，每一项为 dict：{name, path, default}
    default 为 True 的项表示用户指定的默认编辑器（至多一个）。
    """
    settings = QSettings("tumuyan", "PinFrame")
    raw = settings.value("image_editors", [], type=list)
    editors = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                editors.append({
                    "name": str(item.get("name", "")),
                    "path": str(item.get("path", "")),
                    "default": bool(item.get("default", False)),
                })
    return editors


def save_image_editors(editors):
    """将编辑器列表写入 QSettings。"""
    settings = QSettings("tumuyan", "PinFrame")
    settings.setValue("image_editors", editors)


class EditorSettingsDialog(QDialog):
    """外部图像编辑器设置对话框（全局设置，非工程设置）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dialog_editor_settings_title"))
        self.resize(460, 520)

        layout = QVBoxLayout(self)

        editor_group = QGroupBox(i18n.t("settings_image_editors"))
        editor_layout = QVBoxLayout(editor_group)

        hint = QLabel(i18n.t("settings_image_editors_hint"))
        hint.setWordWrap(True)
        editor_layout.addWidget(hint)

        self.editor_list = QListWidget()
        self.editor_list.setMinimumHeight(220)
        editor_layout.addWidget(self.editor_list)

        btn_row = QHBoxLayout()
        self.btn_add_editor = QPushButton(i18n.t("btn_add_editor"))
        self.btn_add_editor.clicked.connect(self._add_editor)
        btn_row.addWidget(self.btn_add_editor)

        self.btn_edit_editor = QPushButton(i18n.t("btn_edit_editor"))
        self.btn_edit_editor.clicked.connect(self._edit_editor)
        btn_row.addWidget(self.btn_edit_editor)

        self.btn_remove_editor = QPushButton(i18n.t("btn_remove_editor"))
        self.btn_remove_editor.clicked.connect(self._remove_editor)
        btn_row.addWidget(self.btn_remove_editor)

        self.btn_set_default_editor = QPushButton(i18n.t("btn_set_default_editor"))
        self.btn_set_default_editor.clicked.connect(self._set_default_editor)
        btn_row.addWidget(self.btn_set_default_editor)

        self.btn_move_up = QPushButton(i18n.t("btn_move_up"))
        self.btn_move_up.clicked.connect(lambda: self._move_editor(-1))
        btn_row.addWidget(self.btn_move_up)

        self.btn_move_down = QPushButton(i18n.t("btn_move_down"))
        self.btn_move_down.clicked.connect(lambda: self._move_editor(1))
        btn_row.addWidget(self.btn_move_down)

        editor_layout.addLayout(btn_row)
        layout.addWidget(editor_group)

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

        self._editors = load_image_editors()
        self._refresh_editor_list()

    # ------------------------------------------------------------------
    # 编辑器列表
    # ------------------------------------------------------------------
    def _refresh_editor_list(self):
        self.editor_list.clear()
        for ed in self._editors:
            prefix = "★ " if ed.get("default") else ""
            name = ed.get("name", "") or "(未命名)"
            path = ed.get("path", "")
            label = f"{prefix}{name}\n{path}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ed)
            if not path or not name:
                item.setToolTip(i18n.t("tip_editor_incomplete"))
            self.editor_list.addItem(item)

    def _selected_editor_index(self):
        row = self.editor_list.currentRow()
        if row < 0:
            return None
        return row

    def _add_editor(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dlg_choose_editor"), "",
            i18n.t("dlg_filter_executable", "All Files (*)"))
        if not path:
            return
        name, ok = QInputDialog.getText(
            self, i18n.t("dlg_editor_name_title"),
            i18n.t("dlg_editor_name_prompt"), QLineEdit.EchoMode.Normal,
            os.path.splitext(os.path.basename(path))[0])
        if not ok:
            return
        if not name.strip():
            name = os.path.splitext(os.path.basename(path))[0]
        # 若当前没有任何编辑器，第一个自动设为默认
        is_default = not self._editors
        self._editors.append({"name": name.strip(), "path": path, "default": is_default})
        self._refresh_editor_list()
        self.editor_list.setCurrentRow(len(self._editors) - 1)

    def _edit_editor(self):
        row = self._selected_editor_index()
        if row is None:
            return
        ed = self._editors[row]
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dlg_choose_editor"), ed.get("path", ""),
            i18n.t("dlg_filter_executable", "All Files (*)"))
        if not path:
            return
        name, ok = QInputDialog.getText(
            self, i18n.t("dlg_editor_name_title"),
            i18n.t("dlg_editor_name_prompt"), QLineEdit.EchoMode.Normal,
            ed.get("name", ""))
        if not ok:
            return
        ed["path"] = path
        if name.strip():
            ed["name"] = name.strip()
        self._refresh_editor_list()
        self.editor_list.setCurrentRow(row)

    def _remove_editor(self):
        row = self._selected_editor_index()
        if row is None:
            return
        was_default = self._editors[row].get("default", False)
        del self._editors[row]
        if was_default and self._editors:
            self._editors[0]["default"] = True
        self._refresh_editor_list()

    def _set_default_editor(self):
        row = self._selected_editor_index()
        if row is None:
            return
        for ed in self._editors:
            ed["default"] = False
        self._editors[row]["default"] = True
        self._refresh_editor_list()
        self.editor_list.setCurrentRow(row)

    def _move_editor(self, delta):
        row = self._selected_editor_index()
        if row is None:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= len(self._editors):
            return
        self._editors[row], self._editors[new_row] = self._editors[new_row], self._editors[row]
        self._refresh_editor_list()
        self.editor_list.setCurrentRow(new_row)

    def get_editors(self):
        """返回编辑后的编辑器列表，供 MainWindow 保存。"""
        return self._editors
