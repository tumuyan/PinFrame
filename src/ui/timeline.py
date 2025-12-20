from PyQt6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QHeaderView)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont

class TimelineWidget(QTreeWidget):
    selection_changed = pyqtSignal(list) 
    order_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHeaderLabels(["Filename", "Scale", "Position", "Orig. Res"])
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        
        # Style
        self.setStyleSheet("""
            QTreeWidget { background-color: #333; color: white; border: none; }
            QHeaderView::section { background-color: #444; color: white; padding: 4px; border: 1px solid #555; }
            QTreeWidget::item:selected { background-color: #555; }
        """)
        
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.itemSelectionChanged.connect(self.on_selection_changed)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.order_changed.emit()

    def add_frame(self, filename, frame_data, orig_width=0, orig_height=0):
        item = QTreeWidgetItem(self)
        item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
        
        # Store original resolution for calculation
        item.setData(3, Qt.ItemDataRole.UserRole, (orig_width, orig_height))
        
        item.setText(0, filename)
        self.update_item_display(item, frame_data, orig_width, orig_height)

    def update_item_display(self, item, frame_data, orig_w, orig_h):
        # Scale
        item.setText(1, f"{frame_data.scale:.2f}")
        
        # Position
        pos_str = f"({int(frame_data.position[0])}, {int(frame_data.position[1])})"
        item.setText(2, pos_str)
        
        # Orig Res and Calculated Res
        if orig_w > 0:
            final_w = int(orig_w * frame_data.scale)
            final_h = int(orig_h * frame_data.scale)
            res_str = f"{orig_w}x{orig_h} -> {final_w}x{final_h}"
        else:
            res_str = "?x?"
        
        item.setText(3, res_str)

    def refresh_current_items(self):
        items = self.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive)
        # Actually standard iteration
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            if orig_res:
                w, h = orig_res
                self.update_item_display(item, frame_data, w, h)
            else:
                self.update_item_display(item, frame_data, 0, 0)

    def on_selection_changed(self):
        selected_items = self.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.selection_changed.emit(frames)
