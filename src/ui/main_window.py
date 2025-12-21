from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QDockWidget, QToolBar, QFileDialog, QSpinBox, 
                             QLabel, QPushButton, QInputDialog, QTreeWidgetItem, QMenu)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QImage, QActionGroup
from PyQt6.QtCore import Qt, QTimer, QSettings, QByteArray

from model.project_data import ProjectData, FrameData
from ui.canvas import CanvasWidget
from ui.timeline import TimelineWidget
from ui.property_panel import PropertyPanel
from ui.settings_dialog import SettingsDialog
from ui.export_dialog import ExportOptionsDialog
from i18n.manager import i18n
import os

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # State
        self.current_project_path = None
        self.is_dirty = False
        self.settings = QSettings("Yazii", "Image2Frame")
        self.current_theme = self.settings.value("theme", "dark")
        self.current_lang = self.settings.value("language", "zh_CN")
        i18n.load_language(self.current_lang)
        
        self.setWindowTitle(i18n.t("app_title") + " - " + i18n.t("new_project"))
        self.resize(1200, 800)
        
        # Data
        self.project = ProjectData()
        
        # Central Widget (Canvas)
        self.canvas = CanvasWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.transform_changed.connect(self.on_canvas_transform_changed)

        # Dock Widget (Timeline)
        self.timeline_dock = QDockWidget(i18n.t("dock_timeline"), self)
        self.timeline_dock.setObjectName("TimelineDock")
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
        self.timeline.reverse_order_requested.connect(self.reverse_selected_frames)
        self.timeline.integerize_offset_requested.connect(self.integerize_selection_offset)
        self.timeline_dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
        
        # Dock Widget (Property Panel)
        self.property_dock = QDockWidget(i18n.t("dock_properties"), self)
        self.property_dock.setObjectName("PropertyDock")
        self.property_panel = PropertyPanel()
        self.property_panel.frame_data_changed.connect(self.on_property_changed)
        
        # Init settings
        self.property_panel.set_project_info(self.project.width, self.project.height)
        
        self.property_dock.setWidget(self.property_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)

        # Connect relative move
        self.property_panel.relative_move_requested.connect(self.apply_relative_move)
        self.property_panel.repeat_requested.connect(self.repeat_last_move)
        self.property_panel.rev_repeat_requested.connect(self.reverse_repeat_last_move)
        
        self.last_relative_offset = (0.0, 0.0)

        # Menus & Toolbar
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        
        # Playback
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        self.is_playing = False
        self.playback_reverse = False
        self.playlist = []
        self.play_index = 0
        
        # Status Bar
        self.statusBar().showMessage(i18n.t("ready"))
        
        # Load persistent export settings if available
        # (Already loaded in ProjectData, but dialog defaults need setting)
        
        self.update_title()
        self.apply_theme(self.current_theme)
        
        # Restore window state
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
            
        # Restore repeat interval
        repeat_ms = int(self.settings.value("repeat_interval", 250))
        self.property_panel.set_repeat_interval(repeat_ms)
        self.set_repeat_action_checked(repeat_ms)

        # Restore background mode
        bg_mode = self.settings.value("background_mode", "checkerboard")
        self.update_background_mode(bg_mode)

    def set_repeat_action_checked(self, ms):
        if not hasattr(self, 'repeat_actions'):
            return
        for val, action in self.repeat_actions.items():
            if val == ms:
                action.setChecked(True)
                break

    def apply_theme(self, theme_name):
        self.current_theme = theme_name
        self.settings.setValue("theme", theme_name)
        
        # Update menu check state
        if hasattr(self, 'theme_dark_action'):
            self.theme_dark_action.setChecked(theme_name == "dark")
            self.theme_light_action.setChecked(theme_name == "light")
        if theme_name == "dark":
            qss = """
                QMainWindow, QDialog, QMessageBox {
                    background-color: #252526;
                    color: #CCCCCC;
                }
                QWidget {
                    background-color: #252526;
                    color: #CCCCCC;
                }
                QDockWidget {
                    background-color: #2D2D2D;
                    color: #CCCCCC;
                }
                QDockWidget::title {
                    background-color: #333333;
                    padding: 4px;
                    text-align: center;
                }
                QMenuBar {
                    background-color: #2D2D2D;
                    color: #CCCCCC;
                    border-bottom: 1px solid #333;
                }
                QMenuBar::item:selected {
                    background-color: #3E3E3E;
                }
                QMenu {
                    background-color: #2D2D2D;
                    color: #CCCCCC;
                    border: 1px solid #454545;
                }
                QMenu::item:selected {
                    background-color: #007ACC;
                    color: white;
                }
                QToolBar {
                    background-color: #2D2D2D;
                    border: none;
                    spacing: 5px;
                    padding: 3px;
                }
                QStatusBar {
                    background-color: #007ACC;
                    color: white;
                }
                QPushButton {
                    background-color: #3E3E42;
                    color: #CCCCCC;
                    border: 1px solid #454545;
                    padding: 4px 8px;
                    border-radius: 3px;
                    min-width: 60px;
                }
                QPushButton:hover {
                    background-color: #4E4E52;
                    border: 1px solid #007ACC;
                }
                QPushButton:pressed {
                    background-color: #2D2D30;
                }
                QPushButton#playBtn:checked {
                    background-color: #28a745;
                    color: white;
                    border: 1px solid #1e7e34;
                    font-weight: bold;
                }
                QPushButton#revPlayBtn:checked {
                    background-color: #17a2b8;
                    color: white;
                    border: 1px solid #117a8b;
                    font-weight: bold;
                }
                QSpinBox, QDoubleSpinBox {
                    color: #CCCCCC;
                }
                QLineEdit {
                    background-color: #333333;
                    color: #CCCCCC;
                    border: 1px solid #454545;
                    padding: 2px;
                    selection-background-color: #007ACC;
                }
                QHeaderView::section {
                    background-color: #333333;
                    color: #CCCCCC;
                    border: 1px solid #454545;
                    padding: 4px;
                }
                QTreeWidget {
                    background-color: #1E1E1E;
                    color: #CCCCCC;
                    border: none;
                }
                QTreeWidget::item:selected {
                    background-color: #094771;
                    color: white;
                }
                QGroupBox {
                    border: 1px solid #454545;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                    color: #007ACC;
                }
            """
        else:
            qss = """
                QMainWindow, QDialog, QMessageBox {
                    background-color: #F3F3F3;
                    color: #333333;
                }
                QWidget {
                    background-color: #F3F3F3;
                    color: #333333;
                }
                QDockWidget {
                    background-color: #E0E0E0;
                    color: #333333;
                }
                QDockWidget::title {
                    background-color: #D6D6D6;
                    padding: 4px;
                }
                QMenuBar {
                    background-color: #E0E0E0;
                    color: #333333;
                    border-bottom: 1px solid #CCCCCC;
                }
                QMenuBar::item:selected {
                    background-color: #D0D0D0;
                }
                QMenu {
                    background-color: white;
                    color: #333333;
                    border: 1px solid #CCCCCC;
                }
                QMenu::item:selected {
                    background-color: #007ACC;
                    color: white;
                }
                QToolBar {
                    background-color: #E0E0E0;
                    border: none;
                    padding: 3px;
                }
                QStatusBar {
                    background-color: #007ACC;
                    color: white;
                }
                QPushButton {
                    background-color: #FFFFFF;
                    color: #333333;
                    border: 1px solid #CCCCCC;
                    padding: 4px 8px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #F0F7FF;
                    border: 1px solid #007ACC;
                }
                QPushButton#playBtn:checked {
                    background-color: #4CAF50;
                    color: white;
                    border: 1px solid #388E3C;
                    font-weight: bold;
                }
                QPushButton#revPlayBtn:checked {
                    background-color: #03A9F4;
                    color: white;
                    border: 1px solid #0288D1;
                    font-weight: bold;
                }
                QSpinBox, QDoubleSpinBox {
                    color: #333333;
                }
                QLineEdit {
                    background-color: white;
                    color: #333333;
                    border: 1px solid #CCCCCC;
                    padding: 2px;
                }
                QHeaderView::section {
                    background-color: #EAEAEA;
                    color: #333333;
                    border: 1px solid #CCCCCC;
                    padding: 4px;
                }
                QTreeWidget {
                    background-color: white;
                    color: #333333;
                    border: 1px solid #EEEEEE;
                }
                QTreeWidget::item:selected {
                    background-color: #E5F3FF;
                    color: black;
                }
                QGroupBox {
                    border: 1px solid #CCCCCC;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                    color: #007ACC;
                }
            """
            
        QApplication.instance().setStyleSheet(qss)
        
        # Update specific widget styles that might need override
        self.canvas.update()
        self.property_panel.update_preview()

    def update_title(self):
        title = i18n.t("app_title") + " - "
        if self.current_project_path:
            title += os.path.basename(self.current_project_path)
        else:
            title += i18n.t("new_project")
            
        if self.is_dirty:
            title += i18n.t("dirty_suffix")
        self.setWindowTitle(title)

    def mark_dirty(self):
        if not self.is_dirty:
            self.is_dirty = True
            self.update_title()

    def create_actions(self):
        self.import_action = QAction(i18n.t("action_import"), self)
        self.import_action.triggered.connect(self.import_images)
        self.import_action.setShortcut(QKeySequence.StandardKey.Open)
        
        self.import_slice_action = QAction(i18n.t("action_import_slice"), self)
        self.import_slice_action.triggered.connect(self.import_sprite_sheet)
        self.import_slice_action.setShortcut("Ctrl+Shift+I")
        
        self.save_action = QAction(i18n.t("action_save"), self)
        self.save_action.triggered.connect(self.save_project)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)

        self.save_as_action = QAction(i18n.t("action_save_as"), self)
        self.save_as_action.triggered.connect(self.save_project_as)
        self.save_as_action.setShortcut("Ctrl+Shift+S")

        self.load_action = QAction(i18n.t("action_load"), self)
        self.load_action.triggered.connect(self.load_project)
        
        self.export_action = QAction(i18n.t("action_export"), self)
        self.export_action.triggered.connect(self.export_sequence)

        self.export_sheet_action = QAction(i18n.t("action_export_sheet"), self)
        self.export_sheet_action.triggered.connect(self.export_sprite_sheet)

        # Edit Actions
        self.copy_props_action = QAction(i18n.t("action_copy_props"), self)
        self.copy_props_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_props_action.triggered.connect(self.copy_frame_properties)
        
        self.paste_props_action = QAction(i18n.t("action_paste_props"), self)
        self.paste_props_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_props_action.triggered.connect(self.paste_frame_properties)
        
        self.dup_frame_action = QAction(i18n.t("action_dup_frame"), self)
        self.dup_frame_action.setShortcut("Ctrl+D")
        self.dup_frame_action.triggered.connect(self.duplicate_frame)
        
        self.rem_frame_action = QAction(i18n.t("action_rem_frame"), self)
        self.rem_frame_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.rem_frame_action.triggered.connect(self.remove_frame)

        self.reverse_order_action = QAction(i18n.t("action_reverse_order"), self)
        self.reverse_order_action.triggered.connect(self.reverse_selected_frames)

        # Background Actions
        self.bg_group = QActionGroup(self)
        self.bg_actions = {}
        for mode in ["checkerboard", "black", "white", "red", "green"]:
            action = QAction(i18n.t(f"bg_{mode}"), self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=mode: self.update_background_mode(m))
            self.bg_group.addAction(action)
            self.bg_actions[mode] = action
        self.bg_actions["checkerboard"].setChecked(True)
        
        self.settings_action = QAction(i18n.t("action_settings"), self)
        self.settings_action.triggered.connect(self.open_settings)

        # View Reset Shortcut (Global)
        self.reset_view_action = QAction(i18n.t("action_reset_view"), self)
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
        self.play_pause_action.triggered.connect(self.handle_space_shortcut)
        self.addAction(self.play_pause_action)

        self.reverse_play_action = QAction("Reverse Playback", self)
        self.reverse_play_action.setCheckable(True)
        self.reverse_play_action.triggered.connect(self.toggle_reverse_playback)
        self.addAction(self.reverse_play_action)

        self.theme_dark_action = QAction("Dark Theme", self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.setChecked(True)
        self.theme_dark_action.triggered.connect(lambda: self.apply_theme("dark"))

        self.theme_light_action = QAction("Light Theme", self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.triggered.connect(lambda: self.apply_theme("light"))
        
        # Ensure only one theme is checked
        self.theme_group = QActionGroup(self)
        self.theme_group.addAction(self.theme_dark_action)
        self.theme_group.addAction(self.theme_light_action)

        # Language Actions
        self.lang_zh_action = QAction("简体中文", self)
        self.lang_zh_action.setCheckable(True)
        self.lang_zh_action.triggered.connect(lambda: self.change_language("zh_CN"))
        
        self.lang_en_action = QAction("English", self)
        self.lang_en_action.setCheckable(True)
        self.lang_en_action.triggered.connect(lambda: self.change_language("en_US"))
        
        self.lang_group = QActionGroup(self)
        self.lang_group.addAction(self.lang_zh_action)
        self.lang_group.addAction(self.lang_en_action)
        if self.current_lang == "zh_CN":
            self.lang_zh_action.setChecked(True)
        else:
            self.lang_en_action.setChecked(True)

        # Layout Presets
        self.layout_std_action = QAction(i18n.t("preset_std"), self)
        self.layout_std_action.triggered.connect(lambda: self.apply_layout_preset("standard"))
        
        self.layout_side_action = QAction(i18n.t("preset_side"), self)
        self.layout_side_action.triggered.connect(lambda: self.apply_layout_preset("side"))
        
        self.layout_stack_ltp_action = QAction(i18n.t("preset_stack_ltp"), self)
        self.layout_stack_ltp_action.triggered.connect(lambda: self.apply_layout_preset("stack_ltp"))
        
        self.layout_stack_lpt_action = QAction(i18n.t("preset_stack_lpt"), self)
        self.layout_stack_lpt_action.triggered.connect(lambda: self.apply_layout_preset("stack_lpt"))
        
        self.layout_stack_rtp_action = QAction(i18n.t("preset_stack_rtp"), self)
        self.layout_stack_rtp_action.triggered.connect(lambda: self.apply_layout_preset("stack_rtp"))
        
        self.layout_stack_rpt_action = QAction(i18n.t("preset_stack_rpt"), self)
        self.layout_stack_rpt_action.triggered.connect(lambda: self.apply_layout_preset("stack_rpt"))

        # Auto-Repeat Settings
        self.repeat_group = QActionGroup(self)
        self.repeat_actions = {}
        
        intervals = [
            (i18n.t("lang_disabled"), 0),
            ("100ms", 100),
            (i18n.t("lang_250_default", "250ms (Default)"), 250),
            ("500ms", 500),
            ("1000ms", 1000)
        ]
        
        for name, ms in intervals:
            action = QAction(name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=ms: self.update_repeat_interval(m))
            self.repeat_group.addAction(action)
            self.repeat_actions[ms] = action
        


    def create_menus(self):
        menubar = self.menuBar()
        
        # File Menu
        file_menu = menubar.addMenu(i18n.t("menu_file"))
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.import_slice_action)
        file_menu.addSeparator()
        file_menu.addAction(self.load_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.export_sheet_action)
        
        # Edit Menu
        edit_menu = menubar.addMenu(i18n.t("menu_edit"))
        edit_menu.addAction(self.copy_props_action)
        edit_menu.addAction(self.paste_props_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.dup_frame_action)
        edit_menu.addAction(self.rem_frame_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.reverse_order_action)
        edit_menu.addSeparator()
        
        repeat_menu = edit_menu.addMenu(i18n.t("menu_repeat_delay"))
        for ms in [0, 100, 250, 500, 1000]:
            repeat_menu.addAction(self.repeat_actions[ms])
        
        # Layout Menu
        layout_menu = menubar.addMenu(i18n.t("menu_layout"))
        layout_menu.addAction(self.layout_std_action)
        layout_menu.addAction(self.layout_side_action)
        layout_menu.addSeparator()
        layout_menu.addAction(self.layout_stack_ltp_action)
        layout_menu.addAction(self.layout_stack_lpt_action)
        layout_menu.addSeparator()
        layout_menu.addAction(self.layout_stack_rtp_action)
        layout_menu.addAction(self.layout_stack_rpt_action)
        
        # Playback Menu
        play_menu = menubar.addMenu(i18n.t("menu_playback"))
        play_menu.addAction(self.play_pause_action)
        play_menu.addAction(self.reverse_play_action)
        
        # View Menu
        view_menu = menubar.addMenu(i18n.t("menu_view"))
        view_menu.addAction(self.reset_view_action)
        
        self.background_menu = view_menu.addMenu(i18n.t("menu_background"))
        for action in self.bg_actions.values():
            self.background_menu.addAction(action)
        
        view_menu.addSeparator()
        
        theme_menu = view_menu.addMenu(i18n.t("menu_theme"))
        theme_menu.addAction(self.theme_dark_action)
        theme_menu.addAction(self.theme_light_action)
        
        lang_menu = view_menu.addMenu("Language (语言)")
        lang_menu.addAction(self.lang_zh_action)
        lang_menu.addAction(self.lang_en_action)

    def create_toolbar(self):
        toolbar = QToolBar(i18n.t("toolbar_main"))
        toolbar.setObjectName("MainToolbar")
        self.addToolBar(toolbar)
        
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.save_action)
        toolbar.addAction(self.save_as_action)
        toolbar.addAction(self.load_action)
        toolbar.addSeparator()
        toolbar.addAction(self.settings_action)
        toolbar.addAction(self.export_action)
        
        toolbar.addSeparator()
        
        # FPS Control
        toolbar.addWidget(QLabel(i18n.t("label_fps")))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(self.project.fps)
        self.fps_spin.valueChanged.connect(self.update_fps)
        toolbar.addWidget(self.fps_spin)
        
        toolbar.addSeparator()
        
        # Play/Pause
        self.play_btn = QPushButton(i18n.t("btn_play"))
        self.play_btn.setObjectName("playBtn")
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self.toggle_play)
        toolbar.addWidget(self.play_btn)
        
        toolbar.addSeparator()
        self.rev_play_btn = QPushButton(i18n.t("btn_backward"))
        self.rev_play_btn.setObjectName("revPlayBtn")
        self.rev_play_btn.setCheckable(True)
        self.rev_play_btn.clicked.connect(lambda: self.toggle_reverse_playback())
        toolbar.addWidget(self.rev_play_btn)

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
        files, _ = QFileDialog.getOpenFileNames(self, i18n.t("dlg_import_title"), "", i18n.t("dlg_filter_images"))
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
                item.setText(1, name)
                
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
        self.statusBar().showMessage(i18n.t("msg_props_copied"), 3000)

    def paste_frame_properties(self):
        if not self.clipboard_frame_properties:
            self.statusBar().showMessage(i18n.t("msg_clipboard_empty"), 3000)
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
        self.statusBar().showMessage(i18n.t("msg_props_pasted").format(count=count), 3000)

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
        self.statusBar().showMessage(i18n.t("msg_frames_duplicated").format(count=added_count), 3000)

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
        self.statusBar().showMessage(i18n.t("msg_frames_removed").format(count=len(indices)), 3000)

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
        self.statusBar().showMessage(i18n.t("msg_frames_enabled_disabled").format(action=i18n.t("action_enabled") if enable else i18n.t("action_disabled"), count=len(selected)), 3000)

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

    def apply_relative_move(self, dx, dy, update_last=True):
        selected_items = self.timeline.selectedItems()
        if not selected_items:
            return
            
        for item in selected_items:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            frame_data.position = (frame_data.position[0] + dx, frame_data.position[1] + dy)
            
            # Update Timeline display
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.timeline.update_item_display(item, frame_data, w, h)
            
        if update_last:
            self.last_relative_offset = (dx, dy)
            self.property_panel.set_repeat_enabled(True)
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(i18n.t("msg_applied_rel_move").format(dx=dx, dy=dy), 2000)

    def repeat_last_move(self):
        dx, dy = self.last_relative_offset
        if dx == 0 and dy == 0:
            self.statusBar().showMessage(i18n.t("msg_no_prev_move"), 2000)
            return
        # Use update_last=False so we don't overwrite the manual move vector
        self.apply_relative_move(dx, dy, update_last=False)

    def reverse_repeat_last_move(self):
        dx, dy = self.last_relative_offset
        if dx == 0 and dy == 0:
            return
        # Use update_last=False
        self.apply_relative_move(-dx, -dy, update_last=False)

    def integerize_selection_offset(self):
        selected_items = self.timeline.selectedItems()
        if not selected_items:
            return
            
        for item in selected_items:
            frame_data = item.data(0, Qt.ItemDataRole.UserRole)
            x, y = frame_data.position
            frame_data.position = (float(round(x)), float(round(y)))
            
            # Update Timeline display
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.timeline.update_item_display(item, frame_data, w, h)
            
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(i18n.t("msg_integerized"), 2000)

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

    def reverse_selected_frames(self):
        selected = self.timeline.selectedItems()
        if len(selected) < 2:
            return
            
        # Get indices
        indices = []
        for item in selected:
            indices.append(self.timeline.indexOfTopLevelItem(item))
        
        indices.sort() # Ensure they are in order (e.g. [1, 3, 4, 10])
        
        # Get selected frames data
        selected_frames = [self.project.frames[idx] for idx in indices]
        
        # Reverse them
        selected_frames.reverse()
        
        # Put them back
        for i, idx in enumerate(indices):
            self.project.frames[idx] = selected_frames[i]
            
        # Refresh UI
        # We need to refresh the Timeline items to reflect the change
        # Easiest is to Clear and Reload, but we can also just update the data/text of existing items
        for i, idx in enumerate(indices):
            item = self.timeline.topLevelItem(idx)
            frame_data = self.project.frames[idx]
            
            # Update item data
            item.setData(0, Qt.ItemDataRole.UserRole, frame_data)
            
            # Update display (including name via update_item_display)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            self.timeline.update_item_display(item, frame_data, w, h)
            item.setCheckState(0, Qt.CheckState.Checked if frame_data.is_disabled else Qt.CheckState.Unchecked)
            
        self.mark_dirty()
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.statusBar().showMessage(f"Reversed {len(indices)} frames.", 3000)

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

    def stop_playback(self):
        self.is_playing = False
        self.timer.stop()
        self.play_btn.setText("Play")
        self.play_btn.setChecked(False)
        self.rev_play_btn.setText(i18n.t("btn_backward"))
        self.rev_play_btn.setChecked(False)
        self.reverse_play_action.setChecked(False)
        self.statusBar().showMessage(i18n.t("msg_playback_stopped"))
        
        # Restore selection
        selected_items = self.timeline.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.canvas.set_selected_frames(frames)

    def handle_space_shortcut(self):
        if self.is_playing:
            self.stop_playback()
        else:
            self.toggle_play()

    def toggle_play(self):
        # Forward Playback Toggle
        if self.is_playing and not self.playback_reverse:
            # Currently playing forward, so stop
            self.stop_playback()
        else:
            # Either paused or playing backward, switch to forward
            self.is_playing = True
            self.playback_reverse = False
            
            # Update UI
            self.play_btn.setText(i18n.t("btn_pause"))
            self.play_btn.setChecked(True)
            self.rev_play_btn.setText(i18n.t("btn_backward"))
            self.rev_play_btn.setChecked(False)
            self.reverse_play_action.setChecked(False)
            
            self.playlist = []
            self.play_index = 0
            self.update_playlist()
                
            if not self.playlist:
                self.is_playing = False
                self.play_btn.setText("Play")
                return

            self.timer.start(1000 // self.project.fps)

    def toggle_reverse_playback(self):
        # Backward Playback Toggle
        # This can be triggered by button click or action trigger
        if self.is_playing and self.playback_reverse:
            # Currently playing backward, so stop
            self.stop_playback()
        else:
            # Either paused or playing forward, switch to backward
            self.is_playing = True
            self.playback_reverse = True
            
            # Update UI
            self.play_btn.setText(i18n.t("btn_play"))
            self.play_btn.setChecked(False)
            self.rev_play_btn.setText(i18n.t("btn_pause"))
            self.rev_play_btn.setChecked(True)
            self.reverse_play_action.setChecked(True)
            
            self.playlist = []
            self.play_index = 0
            self.update_playlist()
                
            if not self.playlist:
                self.is_playing = False
                self.rev_play_btn.setText(i18n.t("btn_backward"))
                self.rev_play_btn.setChecked(False)
                self.reverse_play_action.setChecked(False)
                return

            self.timer.start(1000 // self.project.fps)

    def next_frame(self):
        if not self.project.frames or not hasattr(self, 'playlist') or not self.playlist:
            return
        
        # Advance
        item = self.playlist[self.play_index]
        frame_data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # Show on canvas directly (Override selection visualization)
        self.canvas.set_selected_frames([frame_data])
        
        # Update Status
        self.statusBar().showMessage(i18n.t("msg_playback_playing").format(
            index=self.play_index + 1, 
            total=len(self.playlist), 
            name=os.path.basename(frame_data.file_path),
            direction='[REV]' if self.playback_reverse else ''
        ))
        
        # Increment/Decrement index
        step = -1 if self.playback_reverse else 1
        self.play_index = (self.play_index + step) % len(self.playlist)

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
            if frame.crop_rect:
                w, h = frame.crop_rect[2], frame.crop_rect[3]
            elif os.path.exists(frame.file_path):
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
        
    def apply_layout_preset(self, preset):
        # Default area configuration for stacking
        # We need to unstack first? restoreState handles it.
        # But we can align docks manually.
        
        if preset == "standard":
            # Timeline Bottom, Property Right
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.timeline_dock.show()
            self.property_dock.show()
            
        elif preset == "side":
            # Timeline Left, Property Right
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.timeline_dock.show()
            self.property_dock.show()
            
        elif preset == "stack_ltp":
            # Stacked Left, Timeline on Top
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.property_dock)
            self.splitDockWidget(self.timeline_dock, self.property_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

        elif preset == "stack_lpt":
            # Stacked Left, Property on Top
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.property_dock)
            self.splitDockWidget(self.property_dock, self.timeline_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

        elif preset == "stack_rtp":
            # Stacked Right, Timeline on Top
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.splitDockWidget(self.timeline_dock, self.property_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

        elif preset == "stack_rpt":
            # Stacked Right, Property on Top
            self.timeline_dock.setFloating(False)
            self.property_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.splitDockWidget(self.property_dock, self.timeline_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.property_dock)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.timeline_dock)
            self.splitDockWidget(self.property_dock, self.timeline_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

        elif preset == "stack_rtp":
            # Stacked Right, Timeline on Top
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.splitDockWidget(self.timeline_dock, self.property_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

        elif preset == "stack_rpt":
            # Stacked Right, Property on Top
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.timeline_dock)
            self.splitDockWidget(self.property_dock, self.timeline_dock, Qt.Orientation.Vertical)
            self.timeline_dock.show()
            self.property_dock.show()

    def update_repeat_interval(self, ms):
        self.property_panel.set_repeat_interval(ms)
        self.settings.setValue("repeat_interval", ms)
        if ms > 0:
            self.statusBar().showMessage(i18n.t("msg_repeat_delay").format(ms=ms), 2000)
        else:
            self.statusBar().showMessage(i18n.t("msg_repeat_disabled"), 2000)

    def change_language(self, lang_code):
        if self.current_lang == lang_code:
            return
        
        self.current_lang = lang_code
        self.settings.setValue("language", lang_code)
        i18n.load_language(lang_code)
        
        # We need to re-create menus/toolbar or restart. 
        # Re-creating is cleaner but harder. Let's warn the user and restart or just re-init text.
        # Actually, for most strings, we can just call create_menus / create_actions again.
        # But we need to CLEAR existing ones first.
        
        # Simple approach for now: Ask for restart or just re-apply strings manually.
        # Since we have so many strings, let's try a "refresh_ui" method.
        # Language selection check states
        # We need to find the Language menu. It's under View menu or we can find by title.
        # But we just re-created the menu bar in refresh_ui_text, so the actions are new.
        # Let's move the check state logic INTO refresh_ui_text or after create_menus.
        
        self.refresh_ui_text()

    def refresh_ui_text(self):
        # Refresh Actions
        self.import_action.setText(i18n.t("action_import"))
        self.import_slice_action.setText(i18n.t("action_import_slice"))
        self.save_action.setText(i18n.t("action_save"))
        self.save_as_action.setText(i18n.t("action_save_as"))
        self.load_action.setText(i18n.t("action_load"))
        self.export_action.setText(i18n.t("action_export"))
        self.export_sheet_action.setText(i18n.t("action_export_sheet"))
        self.copy_props_action.setText(i18n.t("action_copy_props"))
        self.paste_props_action.setText(i18n.t("action_paste_props"))
        self.dup_frame_action.setText(i18n.t("action_dup_frame"))
        self.rem_frame_action.setText(i18n.t("action_rem_frame"))
        self.reverse_order_action.setText(i18n.t("action_reverse_order"))
        self.settings_action.setText(i18n.t("action_settings"))
        self.reset_view_action.setText(i18n.t("action_reset_view"))
        
        # Background Actions
        for mode, action in self.bg_actions.items():
            action.setText(i18n.t(f"bg_{mode}"))
        
        # Playback buttons (conditional)
        if self.is_playing:
            if self.playback_reverse:
                self.rev_play_btn.setText(i18n.t("btn_pause"))
                self.play_btn.setText(i18n.t("btn_play"))
            else:
                self.play_btn.setText(i18n.t("btn_pause"))
                self.rev_play_btn.setText(i18n.t("btn_backward"))
        else:
            self.play_btn.setText(i18n.t("btn_play"))
            self.rev_play_btn.setText(i18n.t("btn_backward"))
            
        # Layouts
        self.layout_std_action.setText(i18n.t("preset_std"))
        self.layout_side_action.setText(i18n.t("preset_side"))
        self.layout_stack_ltp_action.setText(i18n.t("preset_stack_ltp"))
        self.layout_stack_lpt_action.setText(i18n.t("preset_stack_lpt"))
        self.layout_stack_rtp_action.setText(i18n.t("preset_stack_rtp"))
        self.layout_stack_rpt_action.setText(i18n.t("preset_stack_rpt"))
        
        # Misc
        self.theme_dark_action.setText(i18n.t("theme_dark"))
        self.theme_light_action.setText(i18n.t("theme_light"))
        
        # Repeat Actions
        for ms, action in self.repeat_actions.items():
            if ms == 0:
                action.setText(i18n.t("lang_disabled"))
            elif ms == 250:
                action.setText(i18n.t("lang_250_default", "250ms (Default)"))
        
        # Update Docks
        self.timeline_dock.setWindowTitle(i18n.t("dock_timeline"))
        self.property_dock.setWindowTitle(i18n.t("dock_properties"))
        self.timeline.refresh_ui_text()
        self.property_panel.refresh_ui_text()
        
        menubar = self.menuBar()
        menubar.clear()
        self.create_menus()
        
        # After re-creating menus, sync the checked states
        self.lang_zh_action.setChecked(self.current_lang == "zh_CN")
        self.lang_en_action.setChecked(self.current_lang == "en_US")
        
        # Also sync theme actions if needed (theme is persistent too)
        self.theme_dark_action.setChecked(self.current_theme == "dark")
        self.theme_light_action.setChecked(self.current_theme == "light")
        
        # Sync background actions
        if hasattr(self, 'bg_actions'):
            bg_mode = self.settings.value("background_mode", "checkerboard")
            if bg_mode in self.bg_actions:
                self.bg_actions[bg_mode].setChecked(True)
        
        # Update Toolbar
        # Find which toolbar to update or just re-init text for existing ones?
        # Re-creating toolbar is messy. Let's just update the FPS label if we held a reference.
        # Wait, I didn't hold a reference to all labels.
        # Simple approach: Re-create toolbar.
        self.removeToolBar(self.findChild(QToolBar, "MainToolbar"))
        self.create_toolbar()

        # Update Sub-widgets
        self.property_panel.refresh_ui_text()
        self.timeline.setHeaderLabels([
            i18n.t("col_disabled"), 
            i18n.t("col_filename"), 
            i18n.t("col_scale"), 
            i18n.t("col_position"), 
            i18n.t("col_orig_res")
        ])
        
        # This is enough for now. A restart is always safer.
        self.update_title()
        self.statusBar().showMessage(i18n.t("ready"))

    def closeEvent(self, event):
        if self.check_unsaved_changes():
            # Save settings
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("windowState", self.saveState())
            self.settings.setValue("theme", self.current_theme)
            event.accept()
        else:
            event.ignore()

    def local_test(self):
        pass

    def update_background_mode(self, mode):
        self.canvas.set_background_mode(mode)
        self.settings.setValue("background_mode", mode)
        self.current_background_mode = mode
        
        # Sync menu check state
        if hasattr(self, 'bg_actions'):
            for action_mode, action in self.bg_actions.items():
                action.setChecked(action_mode == mode)

    def import_sprite_sheet(self):
        file, _ = QFileDialog.getOpenFileName(self, i18n.t("dlg_import_title"), "", i18n.t("dlg_filter_images"))
        if not file:
            return
            
        from ui.slice_dialog import SliceImportDialog
        dlg = SliceImportDialog(file, self)
        if not dlg.exec():
            return
            
        results = dlg.get_results()
        mode = results["mode"]
        crops = results["crops"]
        
        if mode == "virtual":
            # Virtual Slicing: Add FrameData with crop_rect
            for crop in crops:
                # Need original resolution for calculation
                # QImage is already loaded in dialog, but let's be efficient
                img = QImage(file)
                frame = FrameData(file_path=file, crop_rect=crop)
                self.project.frames.append(frame)
                self.timeline.add_frame(os.path.basename(file), frame, crop[2], crop[3])
                
        else:
            # Real Slicing: Save files to a subfolder
            base_dir = os.path.dirname(file)
            base_name = os.path.splitext(os.path.basename(file))[0]
            slice_dir = os.path.join(base_dir, f"{base_name}_slices")
            if not os.path.exists(slice_dir):
                os.makedirs(slice_dir)
                
            from PIL import Image
            src = Image.open(file).convert("RGBA")
            
            for i, crop in enumerate(crops):
                x, y, w, h = crop
                part = src.crop((x, y, x + w, y + h))
                out_path = os.path.join(slice_dir, f"{base_name}_{i:03d}.png")
                part.save(out_path)
                
                frame = FrameData(file_path=out_path)
                self.project.frames.append(frame)
                self.timeline.add_frame(os.path.basename(out_path), frame, w, h)
                
        self.mark_dirty()
        self.statusBar().showMessage(f"Imported {len(crops)} slices", 3000)

    def export_sprite_sheet(self):
        from ui.export_dialog import SpriteSheetExportDialog
        dlg = SpriteSheetExportDialog(self)
        dlg.cols_spin.setValue(self.project.export_sheet_cols)
        dlg.padding_spin.setValue(self.project.export_sheet_padding)
        
        if not dlg.exec():
            return
            
        self.project.export_sheet_cols = dlg.cols_spin.value()
        self.project.export_sheet_padding = dlg.padding_spin.value()
        self.mark_dirty()
        
        file, _ = QFileDialog.getSaveFileName(self, i18n.t("action_export_sheet"), "", "Image (*.png)")
        if not file:
            return
            
        from utils.exporter import Exporter
        try:
            Exporter.export_sprite_sheet(self.project, file)
            self.statusBar().showMessage(i18n.t("msg_export_complete"), 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Export Error: {str(e)}", 5000)


    def export_sequence(self):
        # Stop playback if running
        if self.is_playing:
            self.stop_playback()
        
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
        out_dir = QFileDialog.getExistingDirectory(self, i18n.t("dlg_save_title"), start_dir)
        if not out_dir:
            return
            
        self.project.last_export_path = out_dir
        self.mark_dirty() # Settings changed
        
        # Export Loop
        self.statusBar().showMessage(i18n.t("msg_exporting").format(index=0, total=len(self.project.frames)))
        try:
            for current, total in Exporter.export_iter(self.project, out_dir, use_orig_names):
                self.statusBar().showMessage(i18n.t("msg_exporting").format(index=current, total=total))
                QApplication.processEvents()
            self.statusBar().showMessage(i18n.t("msg_export_complete"), 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Export Error: {str(e)}", 5000)
