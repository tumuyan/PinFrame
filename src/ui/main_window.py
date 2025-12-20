from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QDockWidget, QToolBar, QFileDialog, QSpinBox, 
                             QLabel, QPushButton, QInputDialog)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QImage
from PyQt6.QtCore import Qt, QTimer

from model.project_data import ProjectData, FrameData
from ui.canvas import CanvasWidget
from ui.timeline import TimelineWidget
from ui.timeline import TimelineWidget
from ui.property_panel import PropertyPanel
from ui.settings_dialog import SettingsDialog
from ui.export_dialog import ExportOptionsDialog
import os

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # State
        self.current_project_path = None
        self.is_dirty = False
        
        self.setWindowTitle("Image2Frame - New Project")
        self.resize(1200, 800)
        
        # Data
        self.project = ProjectData()
        
        # Central Widget (Canvas)
        self.canvas = CanvasWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.transform_changed.connect(self.on_canvas_transform_changed)

        # Dock Widget (Timeline)
        self.timeline_dock = QDockWidget("Timeline", self)
        self.timeline = TimelineWidget()
        self.timeline.selection_changed.connect(self.on_selection_changed)
        self.timeline.order_changed.connect(self.on_order_changed)
        self.timeline_dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
        
        # Dock Widget (Property Panel)
        self.property_dock = QDockWidget("Properties", self)
        self.property_panel = PropertyPanel()
        self.property_panel.frame_data_changed.connect(self.on_property_changed)
        
        # Init settings
        self.property_panel.set_project_info(self.project.width, self.project.height)
        
        self.property_dock.setWidget(self.property_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)

        # Toolbar
        self.create_actions()
        self.create_toolbar()
        
        # Playback
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        self.is_playing = False
        
        # Status Bar
        self.statusBar().showMessage("Ready")
        
        # Load persistent export settings if available
        # (Already loaded in ProjectData, but dialog defaults need setting)
        
        self.update_title()

    def update_title(self):
        title = "Image2Frame - "
        if self.current_project_path:
            title += os.path.basename(self.current_project_path)
        else:
            title += "New Project"
            
        if self.is_dirty:
            title += " *"
        self.setWindowTitle(title)

    def mark_dirty(self):
        if not self.is_dirty:
            self.is_dirty = True
            self.update_title()

    def create_actions(self):
        self.import_action = QAction("Import Images", self)
        self.import_action.triggered.connect(self.import_images)
        self.import_action.setShortcut(QKeySequence.StandardKey.Open)
        
        self.save_action = QAction("Save Project", self)
        self.save_action.triggered.connect(self.save_project)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)

        self.save_as_action = QAction("Save Project As...", self)
        self.save_as_action.triggered.connect(self.save_project_as)
        self.save_as_action.setShortcut("Ctrl+Shift+S")

        self.load_action = QAction("Load Project", self)
        self.load_action.triggered.connect(self.load_project)
        
        self.export_action = QAction("Export Sequence", self)
        self.export_action.triggered.connect(self.export_sequence)

        self.bg_toggle_action = QAction("Toggle Background", self)
        self.bg_toggle_action.triggered.connect(self.toggle_background)
        
        self.settings_action = QAction("Project Settings", self)
        self.settings_action.triggered.connect(self.open_settings)

        # View Reset Shortcut (Global)
        self.reset_view_action = QAction("Reset View", self)
        self.reset_view_action.setShortcut("Ctrl+0")
        self.reset_view_action.triggered.connect(self.canvas.reset_view)
        self.addAction(self.reset_view_action)

    def create_toolbar(self):
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.save_action)
        toolbar.addAction(self.save_as_action)
        toolbar.addAction(self.load_action)
        toolbar.addSeparator()
        toolbar.addAction(self.settings_action)
        toolbar.addAction(self.export_action)
        
        toolbar.addSeparator()
        toolbar.addAction(self.bg_toggle_action)
        
        toolbar.addSeparator()
        
        # FPS Control
        toolbar.addWidget(QLabel(" FPS: "))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(self.project.fps)
        self.fps_spin.valueChanged.connect(self.update_fps)
        toolbar.addWidget(self.fps_spin)
        
        toolbar.addSeparator()
        
        # Play/Pause
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        toolbar.addWidget(self.play_btn)

    def open_settings(self):
        dlg = SettingsDialog(self, self.project.width, self.project.height)
        if dlg.exec():
            new_w = dlg.width_spin.value()
            new_h = dlg.height_spin.value()
            prop_rescale = dlg.prop_rescale_check.isChecked()
            
            if new_w != self.project.width or new_h != self.project.height:
                
                # Proportional Rescaling
                if prop_rescale:
                    # Calculate factors
                    ratio_w = new_w / self.project.width
                    ratio_h = new_h / self.project.height
                    
                    # Usually we want uniform scaling for the image scale itself.
                    # We use the width ratio generally as "scale" unless aspect ratio changes significantly?
                    # User request: "Default check proportional adjustment".
                    # Let's assume we scale images by ratio_w (or average).
                    # But if we stretch the canvas (100 -> 200 width, same height), 
                    # do we stretch images? Probably not.
                    # Usually "Proportional Scale" means scaling the entire composition.
                    # If I resize 1920x1080 -> 1280x720 (AR preserved), I expect everything to fit same way.
                    # So scale *= ratio_w (or ratio_h, they are same).
                    
                    # If AR changes, e.g. 100x100 -> 200x100.
                    # Item at 50,50 -> 100, 50? (Position x scaled, y same).
                    # Scale? If I used ratio_w (2.0), item gets 2x bigger.
                    # Does it fit? Yes relative to width.
                    # This seems correct for "responsive" resizing.
                    
                    scale_factor = ratio_w # Use Width as driver for element size?
                    # Or maybe min/max? Let's use Width as standard.
                    
                    for f in self.project.frames:
                        # Position: Coordinate space scaling
                        f.position = (f.position[0] * ratio_w, f.position[1] * ratio_h)
                        # Size: Element scaling
                        f.scale *= scale_factor
                
                self.project.width = new_w
                self.project.height = new_h
                self.canvas.set_project_settings(new_w, new_h)
                self.property_panel.set_project_info(new_w, new_h)
                self.mark_dirty()
                
                # Refresh UI
                if self.timeline.selectedItems():
                     self.canvas.update()
                     self.property_panel.update_ui_from_selection()

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import Images", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not files:
            return
            
        for f in files:
            frame_data = FrameData(file_path=f)
            self.project.frames.append(frame_data)
            
            w, h = 0, 0
            try:
                from PIL import Image
                with Image.open(f) as img:
                    w, h = img.size
            except:
                pass
            
            self.timeline.add_frame(os.path.basename(f), frame_data, w, h)
        
        if files:
            self.mark_dirty()

        # Select newly added
        # By default just select the last one if nothing selected?
        # Or let user decide.

    def on_selection_changed(self, frames):
        # 'frames' is a list of FrameData objects from Timeline
        self.canvas.set_selected_frames(frames)
        self.property_panel.set_selection(frames)
        
        # Update playlist if playing
        if self.is_playing:
            self.update_playlist()

    def on_canvas_transform_changed(self, primary_frame_data):
        # Update property panel ref
        self.property_panel.update_ui_from_selection()
        # Update Timeline texts
        self.timeline.refresh_current_items()
        self.mark_dirty()

    def on_property_changed(self, scale, x, y):
        self.canvas.update() # Redraw with new values
        self.timeline.refresh_current_items()
        self.mark_dirty()

    def on_order_changed(self):
        # Rebuild project frames list based on timeline order
        new_frames = []
        for i in range(self.timeline.topLevelItemCount()):
            item = self.timeline.topLevelItem(i)
            new_frames.append(item.data(0, Qt.ItemDataRole.UserRole))
        self.project.frames = new_frames
        self.mark_dirty()

    def update_fps(self, fps):
        if self.project.fps != fps:
            self.project.fps = fps
            if self.is_playing:
                self.timer.start(1000 // self.project.fps)
            self.mark_dirty()

    def update_playlist(self):
        # Build Playlist
        selected_items = self.timeline.selectedItems()
        if len(selected_items) > 1:
            # Play selected only
            # Sort by visual order (index) to ensure correct sequence
            self.playlist = sorted(selected_items, key=lambda i: self.timeline.indexOfTopLevelItem(i))
        else:
            # Play all
            root = self.timeline.invisibleRootItem()
            self.playlist = [root.child(i) for i in range(root.childCount())]
            
        # Reset index if out of bounds or empty?
        # If we are playing, and playlist length changes, index might be invalid.
        if self.playlist:
            self.play_index = self.play_index % len(self.playlist)

    def toggle_play(self):
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setText("Pause")
            
            self.playlist = []
            self.play_index = 0
            self.update_playlist()
                
            if not self.playlist:
                self.is_playing = False
                self.play_btn.setText("Play")
                return

            self.timer.start(1000 // self.project.fps)
        else:
            self.play_btn.setText("Play")
            self.timer.stop()
            self.statusBar().showMessage("Ready")
            
            # Restore selection
            selected_items = self.timeline.selectedItems()
            frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
            self.canvas.set_selected_frames(frames)

    def next_frame(self):
        if not self.project.frames or not hasattr(self, 'playlist') or not self.playlist:
            return
        
        # Advance
        item = self.playlist[self.play_index]
        frame_data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # Show on canvas directly (Override selection visualization)
        self.canvas.set_selected_frames([frame_data])
        
        # Update Status
        # Find index in full project frames if playing subset? 
        # Or just show "Playing Frame X/Y" of playlist?
        # Let's show "Playing: [Filename] (Frame X/Y)"
        current_idx = self.play_index + 1
        total = len(self.playlist)
        filename = os.path.basename(frame_data.file_path)
        self.statusBar().showMessage(f"Playing: {filename} ({current_idx}/{total})")
        
        self.play_index = (self.play_index + 1) % len(self.playlist)

    def save_project(self):
        if self.current_project_path:
            self._save_to_path(self.current_project_path)
        else:
            self.save_project_as()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "JSON (*.json)")
        if not path:
            return
        self._save_to_path(path)

    def _save_to_path(self, path):
        try:
            with open(path, 'w') as f:
                f.write(self.project.to_json())
            self.current_project_path = path
            self.is_dirty = False
            self.update_title()
            self.statusBar().showMessage(f"Project saved to {path}", 3000)
        except Exception as e:
            print(f"Error saving: {e}")
            self.statusBar().showMessage(f"Error saving: {e}", 5000)

    def load_project(self):
        if not self.check_unsaved_changes():
            return

        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "JSON (*.json)")
        if not path:
            return
            
        with open(path, 'r') as f:
            json_str = f.read()
            
        self.project = ProjectData.from_json(json_str)
        self.fps_spin.setValue(self.project.fps)
        self.canvas.set_project_settings(self.project.width, self.project.height)
        self.property_panel.set_project_info(self.project.width, self.project.height)
        
        self.timeline.clear()
        for frame in self.project.frames:
            w, h = 0, 0
            if os.path.exists(frame.file_path):
                 try:
                     from PIL import Image
                     with Image.open(frame.file_path) as img:
                         w, h = img.size
                 except: 
                     pass
            
            self.timeline.add_frame(os.path.basename(frame.file_path), frame, w, h)
            
        if self.project.frames:
             # Select first
             if self.timeline.topLevelItemCount() > 0:
                 self.timeline.setCurrentItem(self.timeline.topLevelItem(0))
                 
        self.current_project_path = path
        self.is_dirty = False
        self.update_title()
        self.statusBar().showMessage(f"Project loaded: {os.path.basename(path)}")
        
    def check_unsaved_changes(self):
        if self.is_dirty:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(self, "Unsaved Changes", 
                                        "You have unsaved changes. Do you want to save them?",
                                        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            
            if reply == QMessageBox.StandardButton.Save:
                self.save_project()
                return not self.is_dirty # If save failed/cancelled, return False
            elif reply == QMessageBox.StandardButton.Cancel:
                return False
            
        return True
        
    def closeEvent(self, event):
        if self.check_unsaved_changes():
            event.accept()
        else:
            event.ignore()

    def local_test(self):
        pass

    def toggle_background(self):
        self.canvas.toggle_background_mode()

    def export_sequence(self):
        # Stop playback if running
        if self.is_playing:
            self.toggle_play()
        
        # Options
        dlg = ExportOptionsDialog(self)
        # Load persistent options
        dlg.use_original_names.setChecked(self.project.export_use_orig_names)
        
        if not dlg.exec():
            return
            
        use_orig_names = dlg.use_original_names.isChecked()
        self.project.export_use_orig_names = use_orig_names # Default update
        
        # Directory
        from utils.exporter import Exporter 
        from PyQt6.QtWidgets import QApplication
        
        start_dir = self.project.last_export_path if self.project.last_export_path else ""
        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if not out_dir:
            return
            
        self.project.last_export_path = out_dir
        self.mark_dirty() # Settings changed
        
        # Export Loop
        self.statusBar().showMessage("Starting Export...")
        try:
            for current, total in Exporter.export_iter(self.project, out_dir, use_orig_names):
                self.statusBar().showMessage(f"Exporting: Frame {current}/{total}")
                QApplication.processEvents() # Keep UI responsive
            
            self.statusBar().showMessage("Export Complete!", 5000)
        except Exception as e:
            self.statusBar().showMessage(f"Export Error: {e}", 5000)
