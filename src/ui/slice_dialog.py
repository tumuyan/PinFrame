from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSpinBox, 
                             QLabel, QPushButton, QRadioButton, QButtonGroup, 
                             QComboBox, QScrollArea, QFrame)
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage
from PyQt6.QtCore import Qt, QRect, QTimer
from i18n.manager import i18n
import os

class SlicePreviewLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = 1
        self.cols = 1
        self.pixmap_orig = None
        self.zoom = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, pixmap):
        self.pixmap_orig = pixmap
        self.update_preview()

    def set_grid(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.update_preview()

    def set_zoom(self, zoom):
        self.zoom = max(0.1, min(10.0, zoom))
        self.update_preview()

    def update_preview(self):
        if not self.pixmap_orig:
            return
        
        # Scale the original pixmap by zoom
        w = int(self.pixmap_orig.width() * self.zoom)
        h = int(self.pixmap_orig.height() * self.zoom)
        
        # Performance: Don't use pixmap.scaled for every grid update if possible, 
        # but for preview it's usually fine.
        preview = self.pixmap_orig.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        painter = QPainter(preview)
        painter.setPen(QPen(QColor(0, 255, 255, 180), 2))
        
        # Grid lines on the SCALED preview
        cell_w = preview.width() / self.cols
        cell_h = preview.height() / self.rows
        
        for i in range(1, self.cols):
            x = int(i * cell_w)
            painter.drawLine(x, 0, x, preview.height())
            
        for i in range(1, self.rows):
            y = int(i * cell_h)
            painter.drawLine(0, y, preview.width(), y)
            
        painter.end()
        self.setPixmap(preview)
        self.setFixedSize(preview.size()) # Ensure scroll area knows size

class SliceImportDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setWindowTitle(i18n.t("dlg_slice_title"))
        self.resize(800, 600)
        
        self.img = QImage(image_path)
        
        main_layout = QHBoxLayout(self)
        
        # Left side: Preview
        self.scroll_area = QScrollArea()
        self.preview_label = SlicePreviewLabel()
        self.preview_label.set_image(QPixmap.fromImage(self.img))
        self.scroll_area.setWidget(self.preview_label)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.scroll_area, 3)
        
        # Connect wheel event for zoom
        self.scroll_area.viewport().installEventFilter(self)
        
        # Right side: Controls
        ctrl_layout = QVBoxLayout()
        
        # Initial Zoom to Fit
        QTimer.singleShot(50, self.zoom_to_fit)
        
        # Grid settings
        grid_group = QVBoxLayout()
        grid_group.addWidget(QLabel(i18n.t("slice_cols")))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 100)
        self.cols_spin.setValue(1)
        self.cols_spin.valueChanged.connect(self.update_grid)
        grid_group.addWidget(self.cols_spin)
        
        grid_group.addWidget(QLabel(i18n.t("slice_rows")))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 100)
        self.rows_spin.setValue(1)
        self.rows_spin.valueChanged.connect(self.update_grid)
        grid_group.addWidget(self.rows_spin)
        ctrl_layout.addLayout(grid_group)
        
        ctrl_layout.addSpacing(20)
        
        # Mode settings
        mode_group = QVBoxLayout()
        mode_group.addWidget(QLabel(i18n.t("slice_mode")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(i18n.t("slice_mode_virtual"), "virtual")
        self.mode_combo.addItem(i18n.t("slice_mode_real"), "real")
        mode_group.addWidget(self.mode_combo)
        ctrl_layout.addLayout(mode_group)
        
        ctrl_layout.addSpacing(20)
        
        # Order settings
        order_group = QVBoxLayout()
        order_group.addWidget(QLabel(i18n.t("slice_order")))
        self.order_z_radio = QRadioButton(i18n.t("slice_order_z"))
        self.order_z_radio.setChecked(True)
        self.order_v_radio = QRadioButton(i18n.t("slice_order_v"))
        order_group.addWidget(self.order_z_radio)
        order_group.addWidget(self.order_v_radio)
        ctrl_layout.addLayout(order_group)
        
        ctrl_layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton(i18n.t("btn_ok", "OK"))
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton(i18n.t("btn_cancel", "Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        ctrl_layout.addLayout(btn_layout)
        
        main_layout.addLayout(ctrl_layout, 1)

    def zoom_to_fit(self):
        if self.img.isNull():
            return
        
        area_w = self.scroll_area.width() - 30
        area_h = self.scroll_area.height() - 30
        
        if area_w <= 0 or area_h <= 0:
            return
            
        fit_zoom = min(area_w / self.img.width(), area_h / self.img.height())
        self.preview_label.set_zoom(fit_zoom)

    def eventFilter(self, source, event):
        if source == self.scroll_area.viewport() and event.type() == event.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.preview_label.set_zoom(self.preview_label.zoom * 1.1)
                else:
                    self.preview_label.set_zoom(self.preview_label.zoom * 0.9)
                return True
        return super().eventFilter(source, event)

    def update_grid(self):
        self.preview_label.set_grid(self.rows_spin.value(), self.cols_spin.value())

    def get_results(self):
        rows = self.rows_spin.value()
        cols = self.cols_spin.value()
        mode = self.mode_combo.currentData()
        order = "Z" if self.order_z_radio.isChecked() else "V"
        
        w = self.img.width()
        h = self.img.height()
        cell_w = w // cols
        cell_h = h // rows
        
        crops = []
        if order == "Z":
            for r in range(rows):
                for c in range(cols):
                    crops.append((c * cell_w, r * cell_h, cell_w, cell_h))
        else:
            for c in range(cols):
                for r in range(rows):
                    crops.append((c * cell_w, r * cell_h, cell_w, cell_h))
                    
        return {
            "mode": mode,
            "crops": crops,
            "rows": rows,
            "cols": cols,
            "order": order
        }
