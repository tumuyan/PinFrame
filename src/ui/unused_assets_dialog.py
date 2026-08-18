"""删除工程目录中未使用的素材对话框。

列出工程目录（含子目录）中未在工程中使用的图片文件：
- 以工程已识别的图像格式扫描工程目录。
- 排除工程内帧引用的图片。
- 排除工程导出的文件名（如 last_gif_export_path、last_export_path 等）。

列表仅显示文件名（文件已在工程目录下），并附带创建时间 / 修改时间栏位；
右侧显示当前点击行的素材预览图。
默认全部勾选，用户确认后物理删除勾选的图片文件。
"""
import os
import time
from typing import List

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QHeaderView, QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt

from core.image_cache import image_cache
from core import image_formats
from i18n.manager import i18n


class UnusedAssetsDialog(QDialog):
    def __init__(self, project, project_path, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_dir = os.path.dirname(project_path) if project_path else os.getcwd()
        # 与素材管理器一致：显式声明标准顶层窗口标志，确保标题栏/拖拽/调整大小正常
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.WindowSystemMenuHint
                            | Qt.WindowType.WindowMinMaxButtonsHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(i18n.t("dlg_delete_unused_title"))
        self.setMinimumSize(800, 480)

        self.unused_files: List[str] = []
        self.setup_ui()
        self.scan()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # 中部：左侧表格 + 右侧预览
        middle = QHBoxLayout()

        # 列表：勾选框 + 文件名 + 创建时间 + 修改时间
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "",
            i18n.t("col_asset_name"),
            i18n.t("col_asset_ctime"),
            i18n.t("col_asset_mtime"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 文件名列拉伸
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        middle.addWidget(self.table, 1)

        # 右侧预览区
        self.preview = QLabel(i18n.t("lbl_unused_preview_hint"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.preview.setMinimumWidth(200)
        self.preview.setMaximumWidth(240)
        middle.addWidget(self.preview, 0)

        layout.addLayout(middle, 1)

        # 所有按钮放同一排：左侧选择类，右侧操作类
        btn_layout = QHBoxLayout()
        self.select_all = QPushButton(i18n.t("btn_select_all"))
        self.select_all.clicked.connect(self.select_all_items)
        btn_layout.addWidget(self.select_all)
        self.select_none = QPushButton(i18n.t("btn_select_none"))
        self.select_none.clicked.connect(self.select_none_items)
        btn_layout.addWidget(self.select_none)
        self.select_invert = QPushButton(i18n.t("btn_select_invert"))
        self.select_invert.clicked.connect(self.select_invert_items)
        btn_layout.addWidget(self.select_invert)
        btn_layout.addStretch()
        self.delete_btn = QPushButton(i18n.t("btn_delete"))
        self.delete_btn.clicked.connect(self.delete_selected)
        btn_layout.addWidget(self.delete_btn)
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def scan(self):
        """扫描工程目录中未被工程引用的图片。"""
        if not os.path.isdir(self.project_dir):
            self.hint.setText(i18n.t("msg_no_project_dir"))
            self.delete_btn.setEnabled(False)
            return

        exts = image_formats.supported_extensions()

        # 1. 工程内引用的图片（归一化绝对路径集合，统一小写以兼容 Windows 大小写不敏感）
        used_paths = set()
        for frame in self.project.frames:
            p = os.path.normpath(os.path.abspath(frame.file_path)).lower()
            used_paths.add(p)

        # 2. 工程导出的文件路径集合（排除项）
        export_paths = set()
        for attr in ("last_export_path", "last_gif_export_path"):
            val = getattr(self.project, attr, "")
            if val:
                p = os.path.normpath(os.path.abspath(val)).lower()
                export_paths.add(p)

        # 3. 遍历工程目录（含子目录）
        unused = []
        for root, dirs, files in os.walk(self.project_dir):
            for name in files:
                _, ext = os.path.splitext(name)
                if ext.lower() not in exts:
                    continue
                full = os.path.normpath(os.path.abspath(os.path.join(root, name)))
                if full.lower() in used_paths:
                    continue
                if full.lower() in export_paths:
                    continue
                unused.append(full)

        self.unused_files = sorted(unused)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for f in self.unused_files:
            row = self.table.rowCount()
            self.table.insertRow(row)

            check_item = QTableWidgetItem()
            check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check_item.setCheckState(Qt.CheckState.Checked)  # 默认全部勾选
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(os.path.basename(f))
            name_item.setToolTip(f)  # 完整路径通过悬浮提示展示
            ctime_item = QTableWidgetItem(_file_time(f, "ctime"))
            mtime_item = QTableWidgetItem(_file_time(f, "mtime"))

            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, ctime_item)
            self.table.setItem(row, 3, mtime_item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.preview.setText(i18n.t("lbl_unused_preview_hint"))

        if self.unused_files:
            self.hint.setText(i18n.t("lbl_unused_hint").format(count=len(self.unused_files),
                                                                dir=self.project_dir))
            self.delete_btn.setEnabled(True)
        else:
            self.hint.setText(i18n.t("lbl_unused_none"))
            self.delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # 右侧预览
    # ------------------------------------------------------------------
    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.preview.setText(i18n.t("lbl_unused_preview_hint"))
            return
        row = rows[0].row()
        name_item = self.table.item(row, 1)
        if name_item is None:
            self.preview.setText(i18n.t("lbl_unused_preview_hint"))
            return
        path = name_item.toolTip()
        if not path or not os.path.exists(path):
            self.preview.setText(i18n.t("lbl_unused_preview_hint"))
            return
        img = image_cache.get(path)
        if img and not img.isNull():
            from PyQt6.QtGui import QPixmap
            pix = QPixmap.fromImage(img).scaled(
                220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pix)
        else:
            self.preview.setText(i18n.t("lbl_unused_preview_hint"))

    # ------------------------------------------------------------------
    # 批量选择
    # ------------------------------------------------------------------
    def select_all_items(self):
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)

    def select_none_items(self):
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)

    def select_invert_items(self):
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is None:
                continue
            new_state = (Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
            item.setCheckState(new_state)

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    def delete_selected(self):
        selected = []
        for i in range(self.table.rowCount()):
            check_item = self.table.item(i, 0)
            if check_item is not None and check_item.checkState() == Qt.CheckState.Checked:
                name_item = self.table.item(i, 1)
                if name_item is not None:
                    selected.append(name_item.toolTip())

        if not selected:
            QMessageBox.information(self, i18n.t("dlg_delete_unused_title"),
                                    i18n.t("msg_no_asset_selected"))
            return

        # 确认（此操作物理删除文件，不可撤销）
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("dlg_delete_unused_title"))
        box.setText(i18n.t("msg_delete_unused_confirm").format(count=len(selected)))
        box.setInformativeText(i18n.t("msg_delete_unused_warning"))
        box.setIcon(QMessageBox.Icon.Warning)
        yes_btn = box.addButton(i18n.t("btn_delete"), QMessageBox.ButtonRole.YesRole)
        no_btn = box.addButton(i18n.t("btn_cancel"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no_btn)
        box.exec()

        if box.clickedButton() != yes_btn:
            return

        failed = []
        deleted = 0
        for f in selected:
            try:
                os.remove(f)
                deleted += 1
            except OSError:
                failed.append(f)

        if failed:
            QMessageBox.warning(self, i18n.t("dlg_delete_unused_title"),
                                i18n.t("msg_delete_unused_partial_fail").format(
                                    deleted=deleted, failed=len(failed)))
        else:
            QMessageBox.information(self, i18n.t("dlg_delete_unused_title"),
                                    i18n.t("msg_delete_unused_done").format(count=deleted))

        self.scan()


def _file_time(path: str, kind: str) -> str:
    """返回文件的创建/修改时间字符串；读取失败返回空串。"""
    try:
        st = os.stat(path)
        tm = time.localtime(st.st_ctime if kind == "ctime" else st.st_mtime)
        return time.strftime("%Y-%m-%d %H:%M", tm)
    except OSError:
        return ""
