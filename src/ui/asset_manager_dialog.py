"""素材管理器对话框。

集中查看工程内所有被引用的素材图片：
- 展示文件名、路径、使用次数（有效帧/禁用帧）、创建时间、修改时间。
- 素材缺失（文件不存在）时红色标出，用于丢失检测。
- 默认按文件名排序，可点击表头任意排序。
- 勾选素材后可删除：仅移除帧引用（不删除磁盘文件），并弹出确认提示
  统计合计的有效帧引用 / 禁用帧引用。

术语说明：需求明确用"使用次数"替代"引用次数"。
"""
import os
import time
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QHeaderView, QMessageBox, QAbstractItemView,
                             QFileDialog, QMenu)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from core.image_cache import image_cache
from core import image_formats
from i18n.manager import i18n


class AssetManagerDialog(QDialog):
    def __init__(self, project, parent=None, on_delete=None, on_replace=None, on_edit=None):
        """on_delete: 回调，接收要移除的素材路径集合，由 MainWindow 实际执行删除。
        on_replace: 回调，接收 (old_path, new_path)，由 MainWindow 实际执行替换。
        on_edit: 回调，接收单个素材路径，由 MainWindow 调用外部图像编辑器处理。

        删除 / 替换都必须由 MainWindow 经 TimelineModel 唯一写路径执行（刷新时间轴/画布、
        记录历史、同步工程数据源），因此回调均为必需；对话框自身不提供绕过模型的回退。
        """
        super().__init__(parent)
        self.project = project
        self._on_delete = on_delete
        self._on_replace = on_replace
        self._on_edit = on_edit
        self._current_asset = None
        # 显式声明标准顶层窗口标志：带标题栏、可移动、可调整大小、可最大化/最小化
        # （QDialog 默认缺少 MinMax 标志，且部分环境下标题栏/拖拽行为异常）
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.WindowSystemMenuHint
                            | Qt.WindowType.WindowMinMaxButtonsHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(i18n.t("dlg_asset_manager_title"))
        self.setMinimumSize(900, 520)

        # 素材数据: path -> {path, filename, total, active, disabled,
        #                  active_indices, disabled_indices, mtime, ctime, missing}
        self.assets: List[dict] = []

        self.setup_ui()
        self.scan_assets()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "",  # checkbox
            i18n.t("col_asset_name"),
            i18n.t("col_asset_path"),
            i18n.t("col_asset_use_count"),
            i18n.t("col_asset_active_count"),
            i18n.t("col_asset_disabled_count"),
            i18n.t("col_asset_mtime"),
            i18n.t("col_asset_ctime"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # 路径列拉伸
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # 预览区（左侧预览图 + 右侧信息）
        preview_row = QHBoxLayout()
        self.preview = QLabel(i18n.t("lbl_asset_preview_hint"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.preview.setMinimumWidth(220)
        self.preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(self._show_preview_menu)
        preview_row.addWidget(self.preview, 1)

        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.info_label.setWordWrap(True)
        self.info_label.setMinimumWidth(360)
        preview_row.addWidget(self.info_label, 1)
        layout.addLayout(preview_row)

        # 底部按钮统一一排：左侧选择类，右侧操作类
        bottom_layout = QHBoxLayout()
        self.btn_select_all = QPushButton(i18n.t("btn_select_all"))
        self.btn_select_all.clicked.connect(self.select_all)
        bottom_layout.addWidget(self.btn_select_all)
        self.btn_select_not_enabled = QPushButton(i18n.t("btn_select_not_enabled"))
        self.btn_select_not_enabled.clicked.connect(self.select_not_enabled)
        bottom_layout.addWidget(self.btn_select_not_enabled)
        self.btn_select_none = QPushButton(i18n.t("btn_select_none"))
        self.btn_select_none.clicked.connect(self.select_none)
        bottom_layout.addWidget(self.btn_select_none)
        self.btn_select_invert = QPushButton(i18n.t("btn_select_invert"))
        self.btn_select_invert.clicked.connect(self.select_invert)
        bottom_layout.addWidget(self.btn_select_invert)
        bottom_layout.addStretch()

        # 操作当前选中素材
        self.replace_btn = QPushButton(i18n.t("btn_replace_asset"))
        self.replace_btn.setEnabled(False)
        self.replace_btn.clicked.connect(self._replace_asset)
        bottom_layout.addWidget(self.replace_btn)
        # 用外部图像编辑器打开预览的图片
        self.edit_btn = QPushButton(i18n.t("btn_edit_asset"))
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._edit_asset)
        bottom_layout.addWidget(self.edit_btn)
        # 操作勾选素材 / 对话框
        self.delete_btn = QPushButton(i18n.t("btn_delete_assets"))
        self.delete_btn.clicked.connect(self.delete_selected)
        bottom_layout.addWidget(self.delete_btn)
        self.close_btn = QPushButton(i18n.t("btn_close"))
        self.close_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(self.close_btn)
        layout.addLayout(bottom_layout)

    # ------------------------------------------------------------------
    # 素材扫描与统计
    # ------------------------------------------------------------------
    def scan_assets(self):
        """按 file_path 归一化路径归组遍历 project.frames 统计素材信息。"""
        # 归一化绝对路径
        def norm(path: str) -> str:
            p = os.path.abspath(path)
            return os.path.normpath(p).replace("\\", "/").lower()

        by_path: Dict[str, dict] = {}
        for idx, frame in enumerate(self.project.frames):
            key = norm(frame.file_path)
            entry = by_path.get(key)
            if entry is None:
                entry = {
                    "path": os.path.normpath(frame.file_path),
                    "filename": os.path.basename(frame.file_path),
                    "total": 0,
                    "active": 0,
                    "disabled": 0,
                    "active_indices": [],
                    "disabled_indices": [],
                    "mtime": None,
                    "ctime": None,
                    "missing": False,
                }
                by_path[key] = entry
            entry["total"] += 1
            if frame.is_disabled:
                entry["disabled"] += 1
                entry["disabled_indices"].append(idx)
            else:
                entry["active"] += 1
                entry["active_indices"].append(idx)

        # 补充文件元信息与缺失状态
        for entry in by_path.values():
            path = entry["path"]
            if os.path.exists(path):
                try:
                    st = os.stat(path)
                    entry["mtime"] = time.localtime(st.st_mtime)
                    entry["ctime"] = time.localtime(st.st_ctime)
                except OSError:
                    pass
            else:
                entry["missing"] = True

        self.assets = list(by_path.values())
        self.refresh_table()
        self.update_hint()

    def refresh_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        # 默认按文件名排序
        sorted_assets = sorted(self.assets, key=lambda a: a["filename"].lower())
        for asset in sorted_assets:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 列 0 勾选框：用 QTableWidgetItem.setCheckState 而非 cell widget，
            # 这样点击表头排序时勾选状态会随行一起移动，避免勾选与素材错配。
            check_item = QTableWidgetItem()
            check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # 默认全不选中
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(asset["filename"])
            name_item.setToolTip(asset["filename"])
            path_item = QTableWidgetItem(asset["path"])
            path_item.setToolTip(asset["path"])
            use_item = QTableWidgetItem(str(asset["total"]))
            use_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            active_item = QTableWidgetItem(str(asset["active"]))
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            disabled_item = QTableWidgetItem(str(asset["disabled"]))
            disabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mtime_item = QTableWidgetItem(_format_time(asset["mtime"]))
            ctime_item = QTableWidgetItem(_format_time(asset["ctime"]))

            if asset["missing"]:
                # 丢失检测：文件名红色加粗，其他列灰色
                name_item.setForeground(Qt.GlobalColor.red)
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                for it in (path_item, use_item, active_item, disabled_item, mtime_item, ctime_item):
                    it.setForeground(Qt.GlobalColor.gray)
                name_item.setToolTip(i18n.t("tip_asset_missing"))

            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, path_item)
            self.table.setItem(row, 3, use_item)
            self.table.setItem(row, 4, active_item)
            self.table.setItem(row, 5, disabled_item)
            self.table.setItem(row, 6, mtime_item)
            self.table.setItem(row, 7, ctime_item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def update_hint(self):
        missing_count = sum(1 for a in self.assets if a["missing"])
        if missing_count:
            self.hint_label.setText(
                i18n.t("lbl_asset_hint_missing").format(total=len(self.assets), missing=missing_count))
            self.hint_label.setStyleSheet("color: red;")
        else:
            self.hint_label.setText(i18n.t("lbl_asset_hint").format(total=len(self.assets)))
            self.hint_label.setStyleSheet("")

    # ------------------------------------------------------------------
    # 选中预览
    # ------------------------------------------------------------------
    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._current_asset = None
            self.replace_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            return
        row = rows[0].row()
        # 找到对应 asset（通过路径列）
        path_item = self.table.item(row, 2)
        if not path_item:
            self._current_asset = None
            self.replace_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            return
        path = path_item.text()
        for asset in self.assets:
            if os.path.normpath(asset["path"]) == os.path.normpath(path):
                self._current_asset = asset
                self.replace_btn.setEnabled(True)
                self.edit_btn.setEnabled(not asset["missing"])
                self._show_preview(asset)
                return
        self._current_asset = None
        self.replace_btn.setEnabled(False)
        self.edit_btn.setEnabled(False)

    def _show_preview(self, asset):
        img = None
        if not asset["missing"]:
            img = image_cache.get(asset["path"])
        if img and not img.isNull():
            from PyQt6.QtGui import QPixmap
            pix = QPixmap.fromImage(img).scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pix)
        else:
            self.preview.setText(i18n.t("lbl_asset_missing_preview"))

        missing = i18n.t("label_missing") if asset["missing"] else ""
        info = [
            i18n.t("lbl_asset_name").format(name=asset["filename"]),
            i18n.t("lbl_asset_path").format(path=asset["path"]),
            i18n.t("lbl_asset_missing_state").format(state=missing) if asset["missing"] else None,
            i18n.t("lbl_asset_mtime").format(t=_format_time(asset["mtime"])),
            i18n.t("lbl_asset_ctime").format(t=_format_time(asset["ctime"])),
            i18n.t("lbl_asset_active_frames").format(count=asset["active"]),
            i18n.t("lbl_asset_disabled_frames").format(count=asset["disabled"]),
        ]
        info = [x for x in info if x is not None]

        # 帧号展示：有效/禁用不同外观
        if asset["active_indices"]:
            info.append(i18n.t("lbl_asset_active_indices").format(
                idx=", ".join(str(i + 1) for i in asset["active_indices"])))
        if asset["disabled_indices"]:
            info.append(i18n.t("lbl_asset_disabled_indices").format(
                idx=", ".join(str(i + 1) for i in asset["disabled_indices"])))

        self.info_label.setText("\n".join(info))
        if asset["missing"]:
            self.info_label.setStyleSheet("color: red;")
        else:
            self.info_label.setStyleSheet("")

    # ------------------------------------------------------------------
    # 替换素材
    # ------------------------------------------------------------------
    def _show_preview_menu(self, pos):
        """预览区右键菜单。"""
        if not self._current_asset:
            return
        menu = QMenu(self)
        if self._on_edit and not self._current_asset["missing"]:
            edit_action = QAction(i18n.t("btn_edit_asset"), self)
            edit_action.triggered.connect(self._edit_asset)
            menu.addAction(edit_action)
        replace_action = QAction(i18n.t("btn_replace_asset"), self)
        replace_action.triggered.connect(self._replace_asset)
        menu.addAction(replace_action)
        menu.exec(self.preview.mapToGlobal(pos))

    def _edit_asset(self):
        """用外部图像编辑器处理当前预览的图片。"""
        if not self._current_asset or self._current_asset["missing"]:
            return
        if self._on_edit:
            self._on_edit(self._current_asset["path"])

    def _replace_asset(self):
        """替换当前选中素材：选择新图片，将所有引用该素材的帧改指向新文件。"""
        if not self._current_asset:
            return
        old_path = self._current_asset["path"]
        new_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dlg_replace_asset_title"), os.path.dirname(old_path),
            image_formats.filter_string(i18n.t("dlg_filter_images")))
        if not new_path:
            return

        # 新旧路径相同时无需替换
        if os.path.normpath(os.path.abspath(new_path)).lower() == \
                os.path.normpath(os.path.abspath(old_path)).lower():
            return

        # 校验新文件确实是可识别图像
        if not image_formats.is_supported(new_path):
            QMessageBox.warning(self, i18n.t("dlg_asset_manager_title"),
                                i18n.t("msg_unsupported_image"))
            return

        # on_replace 由 MainWindow 提供并走 TimelineModel 唯一写路径（替换、刷新时间轴/画布、
        # 历史记录与工程数据源同步）。不提供回退分支——直接改 project.frames 会绕过模型，
        # 即便 scan_assets() 刷新了本对话框表格/预览，主窗口时间轴与画布仍显示旧素材。
        self._on_replace(old_path, new_path)

        # 重新扫描（预览/列表刷新到新素材）
        self.scan_assets()
        self._select_asset_by_path(new_path)

    def _select_asset_by_path(self, path):
        """根据路径选中对应行（替换后定位到新素材）。"""
        target = os.path.normpath(os.path.abspath(path)).lower()
        for row in range(self.table.rowCount()):
            path_item = self.table.item(row, 2)
            if path_item and os.path.normpath(os.path.abspath(path_item.text())).lower() == target:
                self.table.selectRow(row)
                return

    # ------------------------------------------------------------------
    # 批量选择
    # ------------------------------------------------------------------
    def _row_asset(self, row):
        """根据行号返回对应的 asset dict（通过路径列匹配），找不到返回 None。"""
        path_item = self.table.item(row, 2)
        if path_item is None:
            return None
        norm = os.path.normpath(path_item.text())
        for asset in self.assets:
            if os.path.normpath(asset["path"]) == norm:
                return asset
        return None

    def select_all(self):
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item is not None:
                check_item.setCheckState(Qt.CheckState.Checked)

    def select_none(self):
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item is not None:
                check_item.setCheckState(Qt.CheckState.Unchecked)

    def select_invert(self):
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item is None:
                continue
            new_state = (Qt.CheckState.Unchecked if check_item.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
            check_item.setCheckState(new_state)

    def select_not_enabled(self):
        """选中未启用（未被任何有效帧使用）的素材：active == 0。"""
        for row in range(self.table.rowCount()):
            asset = self._row_asset(row)
            check_item = self.table.item(row, 0)
            if check_item is None:
                continue
            if asset is not None and asset["active"] == 0:
                check_item.setCheckState(Qt.CheckState.Checked)
            else:
                check_item.setCheckState(Qt.CheckState.Unchecked)

    # ------------------------------------------------------------------
    # 删除（仅移除引用）
    # ------------------------------------------------------------------
    def delete_selected(self):
        # 收集被勾选的素材
        selected_assets = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item is None or check_item.checkState() != Qt.CheckState.Checked:
                continue
            path_item = self.table.item(row, 2)
            if path_item:
                for asset in self.assets:
                    if os.path.normpath(asset["path"]) == os.path.normpath(path_item.text()):
                        selected_assets.append(asset)
                        break

        if not selected_assets:
            QMessageBox.information(self, i18n.t("dlg_asset_manager_title"),
                                    i18n.t("msg_no_asset_selected"))
            return

        # 收集要移除的帧（基于 project.frames 的索引，用于确认弹窗统计）
        total_active = sum(a["active"] for a in selected_assets)
        total_disabled = sum(a["disabled"] for a in selected_assets)
        total_assets = len(selected_assets)

        # 确认弹窗，统计有效/禁用帧引用
        msg = i18n.t("msg_asset_delete_confirm").format(
            count=total_assets, active=total_active, disabled=total_disabled)
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("dlg_asset_manager_title"))
        box.setText(msg)
        box.setIcon(QMessageBox.Icon.Question)
        yes_btn = box.addButton(i18n.t("btn_delete"), QMessageBox.ButtonRole.YesRole)
        no_btn = box.addButton(i18n.t("btn_cancel"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no_btn)
        box.exec()

        if box.clickedButton() != yes_btn:
            return

        # 收集要移除的素材路径（规范化），交由 MainWindow 移除所有引用这些素材的帧
        remove_paths = {os.path.normpath(os.path.abspath(a["path"])).lower() for a in selected_assets}

        # on_delete 由 MainWindow 提供并走 TimelineModel 唯一写路径（删除帧、刷新时间轴/画布、
        # 历史记录与工程数据源同步）。不提供回退分支——直接改 project.frames 会绕过模型，
        # 即便 scan_assets() 刷新了本对话框表格，主窗口时间轴与画布仍显示旧帧。
        self._on_delete(remove_paths)

        # 重新扫描
        self.scan_assets()


def _format_time(tm) -> str:
    """格式化时间；时间为 None 时返回空串。"""
    if not tm:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", tm)
