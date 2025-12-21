from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QDockWidget, QToolBar, QFileDialog, QSpinBox, 
                             QLabel, QPushButton, QInputDialog, QTreeWidgetItem)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QImage
from PyQt6.QtCore import Qt, QTimer

from model.project_data import ProjectData, FrameData
from ui.canvas import CanvasWidget
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
        self.timeline.files_dropped.connect(self.add_files)
        self.timeline.copy_properties_requested.connect(self.copy_frame_properties)
        self.timeline.paste_properties_requested.connect(self.paste_frame_properties)
        self.timeline.duplicate_requested.connect(self.duplicate_frame)
        self.timeline.remove_requested.connect(self.remove_frame)
        self.timeline.disabled_state_changed.connect(self.on_frame_disabled_state_changed)
        self.timeline.enable_requested.connect(self.toggle_enable_disable)
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

        # Scale Hotkeys (Global)
        self.scale_up_action = QAction("Scale Up", self)
        self.scale_up_action.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        self.scale_up_action.triggered.connect(lambda: self.adjust_selection_scale(1.1))
        self.addAction(self.scale_up_action)

        self.scale_down_action = QAction("Scale Down", self)
        self.scale_down_action.setShortcut("Ctrl+-")
        self.scale_down_action.triggered.connect(lambda: self.adjust_selection_scale(0.9))
        self.addAction(self.scale_down_action)

        # Play/Pause Shortcut (Global Space)
        self.play_pause_action = QAction("Play/Pause", self)
        self.play_pause_action.setShortcut("Space")
        self.play_pause_action.triggered.connect(self.toggle_play)
        self.addAction(self.play_pause_action)

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
                self.canvas.update()
                self.property_panel.update_ui_from_selection()

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import Images", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not files:
            return
        self.add_files(files)

    def add_files(self, files, index=-1):
        if not files:
            return
            
        added_count = 0
        valid_extensions = {'.png', '.jpg', '.jpeg', '.bmp'}
        
        # Prepare list of items to insert
        new_items = []
        
        for f in files:
            _, ext = os.path.splitext(f)
            if ext.lower() not in valid_extensions:
                continue
                
            frame_data = FrameData(file_path=f)
            
            w, h = 0, 0
            try:
                from PIL import Image
                with Image.open(f) as img:
                    w, h = img.size
            except:
                pass
            
            new_items.append((os.path.basename(f), frame_data, w, h))
            added_count += 1
            
        if added_count == 0:
            return

        # Insert logic
        # index is user provided. If -1, append.
        # MainWindow needs to update Timeline AND Project Data.
        # Timeline usually manages its own view, but here we manually add.
        # Actually logic is split. Timeline `add_frame` appends.
        # We need an insertion method.
        
        if index == -1 or index >= len(self.project.frames):
            # Append
            for name, data, w, h in new_items:
                self.project.frames.append(data)
                self.timeline.add_frame(name, data, w, h)
        else:
            # Insert at Index
            # Timeline logic now provides the exact insertion index.
            # So we use it directly.
            
            target_idx = index
            
            # Slice insertion for project data
            frames_to_insert = [x[1] for x in new_items]
            self.project.frames[target_idx:target_idx] = frames_to_insert
            
            # Timeline insertion
            for i, (name, data, w, h) in enumerate(new_items):
                item = QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, data)
                item.setData(3, Qt.ItemDataRole.UserRole, (w, h))
                item.setText(0, name)
                
                # Checkbox flags
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Checked = Disabled, Unchecked = Enabled
                item.setCheckState(0, Qt.CheckState.Checked if data.is_disabled else Qt.CheckState.Unchecked)
                
                self.timeline.update_item_display(item, data, w, h)
                self.timeline.insertTopLevelItem(target_idx + i, item)
                
        self.mark_dirty()

    def copy_frame_properties(self):
        selected = self.timeline.selectedItems()
        if not selected:
            return
            
        # Copy from the first selected item (Primary)
        item = selected[0]
        frame_data = item.data(0, Qt.ItemDataRole.UserRole)
        
        self.clipboard_frame_properties = {
            "scale": frame_data.scale,
            "position": frame_data.position,
            "target_resolution": frame_data.target_resolution
        }
        self.statusBar().showMessage("Frame properties copied.", 3000)

    def paste_frame_properties(self):
        if not self.clipboard_frame_properties:
            self.statusBar().showMessage("Clipboard empty.", 3000)
            return
            
        selected = self.timeline.selectedItems()
        if not selected:
            return
            
        count = 0
        for item in selected:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            
            frame_data.scale = self.clipboard_frame_properties["scale"]
            frame_data.position = self.clipboard_frame_properties["position"]
            frame_data.target_resolution = self.clipboard_frame_properties["target_resolution"]
            
            # Update View
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.timeline.update_item_display(item, frame_data, w, h)
            count += 1
            
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(f"Properties pasted to {count} frames.", 3000)

    def duplicate_frame(self):
        selected = self.timeline.selectedItems()
        if not selected:
            return
            
        # We duplicate all selected
        # Insert them after the last selected item? Or after each?
        # Standard: Insert after the selection block.
        
        # Get indices
        indices = []
        for item in selected:
             indices.append(self.timeline.indexOfTopLevelItem(item))
        
        indices.sort(reverse=True) # Process from bottom up to avoid index shift issues if inserting logic is complex?
        # Actually simplest is to process bottom up, clone, and insert after.
        
        added_count = 0
        for idx in indices:
            # Get original data
            orig_data = self.project.frames[idx]
            
            # Clone data
            new_data = FrameData(
                file_path=orig_data.file_path,
                scale=orig_data.scale,
                position=orig_data.position,
                rotation=orig_data.rotation,
                target_resolution=orig_data.target_resolution,
                is_active=orig_data.is_active
            )
            
            # Insert into project
            insert_idx = idx + 1
            self.project.frames.insert(insert_idx, new_data)
            
            # Insert into Timeline
            # Need original dimensions
            # We can get them from the item
            item = self.timeline.topLevelItem(idx)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            
            new_item = QTreeWidgetItem()
            new_item.setData(0, Qt.ItemDataRole.UserRole, new_data)
            new_item.setData(3, Qt.ItemDataRole.UserRole, (w, h))
            new_item.setText(0, os.path.basename(new_data.file_path)) # Using same name
            new_item.setFlags(new_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            new_item.setCheckState(0, Qt.CheckState.Checked if new_data.is_active else Qt.CheckState.Unchecked)
            
            self.timeline.update_item_display(new_item, new_data, w, h)
            self.timeline.insertTopLevelItem(insert_idx, new_item)
            
            added_count += 1
            
        self.mark_dirty()
        self.statusBar().showMessage(f"Duplicated {added_count} frames.", 3000)

    def remove_frame(self):
        selected = self.timeline.selectedItems()
        if not selected:
            return
            
        # Multiple selection removal.
        # Need to remove from Project and Timeline.
        # Indices are safer.
        
        indices = []
        for item in selected:
            indices.append(self.timeline.indexOfTopLevelItem(item))
        
        indices.sort(reverse=True) # Remove from end first to keep indices valid
        
        for idx in indices:
            del self.project.frames[idx]
            self.timeline.takeTopLevelItem(idx)
            
        self.mark_dirty()
        self.canvas.set_selected_frames([])
        self.property_panel.set_selection([]) # Clear selection in property panel
        self.statusBar().showMessage(f"Removed {len(indices)} frames.", 3000)

    def on_frame_disabled_state_changed(self, frame_data, is_disabled):
        # Data already updated in Timeline logic
        self.mark_dirty()
        
        # If this frame is currently displayed in preview/canvas, update it.
        self.canvas.update() 
        
        # Update playlist if playing so that skip logic applies immediately
        if self.is_playing:
            self.update_playlist()

    def toggle_enable_disable(self, enable):
        selected = self.timeline.selectedItems()
        if not selected:
            return
            
        for item in selected:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            is_disabled = not enable
            if data.is_disabled != is_disabled:
                data.is_disabled = is_disabled
                # Update UI checkbox
                item.setCheckState(0, Qt.CheckState.Checked if is_disabled else Qt.CheckState.Unchecked)
        
        self.mark_dirty()
        self.canvas.update()
        if self.is_playing:
            self.update_playlist()
        self.statusBar().showMessage(f"{'Enabled' if enable else 'Disabled'} {len(selected)} frames.", 3000)

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

    def adjust_selection_scale(self, factor):
        selected_items = self.timeline.selectedItems()
        if not selected_items:
            return
            
        for item in selected_items:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            frame_data.scale *= factor
            
            # Update Timeline display
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.timeline.update_item_display(item, frame_data, w, h)
            
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
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
        target_items = []
        if len(selected_items) > 1:
            # Play selected only
            # Sort by visual order (index) to ensure correct sequence
            target_items = sorted(selected_items, key=lambda i: self.timeline.indexOfTopLevelItem(i))
        else:
            # Play all
            root = self.timeline.invisibleRootItem()
            target_items = [root.child(i) for i in range(root.childCount())]
            
        # Filter disabled
        self.playlist = []
        for item in target_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data.is_disabled:
                self.playlist.append(item)
            
        # Reset index if out of bounds or empty?
        if self.playlist:
            self.play_index = self.play_index % len(self.playlist)
        else:
            self.play_index = 0

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
