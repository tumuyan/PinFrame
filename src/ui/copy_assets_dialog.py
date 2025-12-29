import os
import shutil
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QProgressBar, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from i18n.manager import i18n

class CopyWorker(QThread):
    progress = pyqtSignal(int, str) # current, total, current_file
    finished = pyqtSignal(bool, str) # success, error_msg

    def __init__(self, copy_tasks):
        super().__init__()
        self.copy_tasks = copy_tasks # List of (src, dest)

    def run(self):
        total = len(self.copy_tasks)
        try:
            for i, (src, dest) in enumerate(self.copy_tasks):
                self.progress.emit(i, src)
                
                # Create dest dir if needed (though it should be project root)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                
                if os.path.exists(src):
                    shutil.copy2(src, dest)
                else:
                    raise FileNotFoundError(f"Source file not found: {src}")
            
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))

class CopyAssetsDialog(QDialog):
    def __init__(self, project, project_path, parent=None):
        super().__init__(parent)
        self.project = project
        self.project_path = project_path
        self.project_dir = os.path.dirname(project_path)
        self.setWindowTitle(i18n.t("dlg_copy_assets_title"))
        self.setMinimumWidth(500)
        
        self.copy_tasks = [] # (src, dest)
        self.conflicts = [] # dest paths
        
        self.setup_ui()
        self.scan_assets()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.info_label = QLabel()
        layout.addWidget(self.info_label)

        self.conflict_label = QLabel()
        self.conflict_label.setStyleSheet("color: red; font-weight: bold;")
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setVisible(False)
        layout.addWidget(self.conflict_label)

        self.file_list = QListWidget()
        self.file_list.setVisible(False)
        layout.addWidget(self.file_list)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.copy_btn = QPushButton(i18n.t("btn_copy"))
        self.copy_btn.clicked.connect(self.start_copy)
        self.copy_btn.setEnabled(False)
        btn_layout.addWidget(self.copy_btn)
        
        self.cancel_btn = QPushButton(i18n.t("btn_cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

    def scan_assets(self):
        # 1. Identify all unique external files
        external_files = set()
        for frame in self.project.frames:
            fpath = os.path.abspath(frame.file_path)
            if not os.path.isabs(fpath):
                continue
                
            try:
                rel = os.path.relpath(fpath, self.project_dir)
                if rel.startswith('..'):
                    external_files.add(fpath)
            except ValueError:
                external_files.add(fpath)
        
        if not external_files:
            self.info_label.setText(i18n.t("lbl_no_external_files"))
            self.file_list.setVisible(False)
            self.copy_btn.setEnabled(False)
            return

        # 2. Check for conflicts and group
        self.copy_tasks = []
        self.conflicts = []
        ready_count = 0
        
        for src in sorted(list(external_files)):
            # Normalize for comparison
            src_norm = os.path.normpath(src)
            dest = os.path.abspath(os.path.join(self.project_dir, os.path.basename(src)))
            dest_norm = os.path.normpath(dest)
            
            self.copy_tasks.append((src, dest))
            
            if os.path.exists(dest) and src_norm.lower() != dest_norm.lower():
                self.conflicts.append(src)
                self.file_list.addItem(src)
            else:
                ready_count += 1
        
        # UI Updates
        total_count = len(external_files)
        info_text = f"{i18n.t('lbl_ready_to_copy').format(count=ready_count)} (Total: {total_count})"
        self.info_label.setText(info_text)
        
        if self.conflicts:
            self.conflict_label.setText(i18n.t("lbl_conflicts_found"))
            self.conflict_label.setVisible(True)
            self.file_list.setVisible(True)
        else:
            self.conflict_label.setVisible(False)
            self.file_list.setVisible(False)
            
        self.copy_btn.setEnabled(True)

    def start_copy(self):
        if self.conflicts:
            reply = QMessageBox.warning(
                self, 
                i18n.t("msg_overwrite_title"),
                i18n.t("msg_copy_overwrite_warn"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.copy_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.copy_tasks))
        self.progress_bar.setValue(0)
        
        self.worker = CopyWorker(self.copy_tasks)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, current, file_path):
        self.progress_bar.setValue(current)
        self.info_label.setText(i18n.t("msg_copying").format(file=os.path.basename(file_path)))

    def on_finished(self, success, error_msg):
        if success:
            # Update project indices in memory
            # Map src to dest, use normalized keys for lookup
            mapping = {os.path.normpath(src).lower(): dest for src, dest in self.copy_tasks}
            for frame in self.project.frames:
                norm_frame_path = os.path.normpath(frame.file_path).lower()
                if norm_frame_path in mapping:
                    frame.file_path = mapping[norm_frame_path]
            
            QMessageBox.information(self, i18n.t("dlg_copy_assets_title"), 
                                    i18n.t("msg_copy_success").format(count=len(self.copy_tasks)))
            self.accept()
        else:
            QMessageBox.critical(self, i18n.t("dlg_copy_assets_title"), 
                                 i18n.t("msg_copy_error").format(file="...", error=error_msg))
            self.copy_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
