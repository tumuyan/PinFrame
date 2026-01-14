
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QDockWidget, QToolBar, QFileDialog, QSpinBox, 
                             QLabel, QPushButton, QInputDialog, QTreeWidgetItem, QMenu, QStyle,
                             QMessageBox)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QImage, QActionGroup, QImageReader, QDesktopServices, QColor
from PyQt6.QtCore import Qt, QTimer, QSettings, QByteArray, QUrl, QDateTime, QLocale
import subprocess
import sys
import os

from core.version import VERSION as BUILD_VERSION, BUILD_DATE, REPO_URL as BUILD_REPO_URL
from model.project_data import ProjectData, FrameData
from ui.canvas import CanvasWidget
from ui.timeline import TimelineWidget
from ui.property_panel import PropertyPanel
from ui.settings_dialog import SettingsDialog
from ui.export_dialog import ExportOptionsDialog
from ui.onion_settings import OnionSettingsDialog
from ui.reference_settings import ReferenceSettingsDialog
from ui.raster_settings import RasterizationSettingsDialog
from ui.utils.icon_generator import IconGenerator
from i18n.manager import i18n

class MainWindow(QMainWindow):
    def __init__(self):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)
        super().__init__()
        
        # State
        self.current_project_path = None
        self.is_dirty = False
        self.settings = QSettings("tumuyan", "PinFrame")
        self.current_theme = self.settings.value("theme", "dark")
        self.current_lang = self.settings.value("language", "zh_CN")
        i18n.load_language(self.current_lang)
        self.recent_projects = self.settings.value("recent_projects", [], type=list)
        
        # Set Window Icon
        import sys
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(sys._MEIPASS, "src", "resources", "icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icon.ico")
        
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.setWindowTitle(i18n.t("app_title") + " - " + i18n.t("new_project"))
        self.resize(1200, 800)
        
        # Data
        self.project = ProjectData()
        
        # Central Widget (Canvas)
        self.canvas = CanvasWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.transform_changed.connect(self.on_canvas_transform_changed)
        self.canvas.scale_change_requested.connect(self.on_canvas_scale_requested)

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
        self.timeline.set_reference_requested.connect(self.set_reference_frame_from_selection)
        self.timeline.clear_reference_requested.connect(self.clear_reference_frame)
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

        # Connect Anchor Sync
        self.property_panel.custom_anchor_changed.connect(self.canvas.set_custom_anchor_pos)
        self.property_panel.show_anchor_changed.connect(self.canvas.set_show_custom_anchor)
        self.canvas.anchor_pos_changed.connect(self.property_panel.set_custom_anchor_pos)
        
        self.last_relative_offset = (0.0, 0.0)

        # Rasterization Settings (Global)
        self.raster_enabled = self.settings.value("raster_enabled", False, type=bool)
        self.raster_show_grid = self.settings.value("raster_show_grid", True, type=bool)
        grid_color_str = self.settings.value("raster_grid_color", "128,128,128")
        try:
            self.raster_grid_color = tuple(map(int, grid_color_str.split(',')))
        except:
            self.raster_grid_color = (128, 128, 128)
        self.raster_scale_threshold = float(self.settings.value("raster_scale_threshold", 5.0))

        # Menus & Toolbar
        self.create_actions()
        self.create_menus()
        self.create_toolbar()
        
        # Apply initial raster settings to canvas
        grid_color = QColor(*self.raster_grid_color)
        self.canvas.set_rasterization_settings(
            self.raster_enabled,
            grid_color,
            self.raster_scale_threshold,
            self.raster_show_grid
        )
        self.update_rasterization_ui()
        
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
        self.update_menu_state()
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

        # Recent Projects
        self.recent_projects = self.settings.value("recent_projects", [], type=list)

        # Onion Skin & Reference State
        self.onion_enabled = False
        self.onion_prev = self.settings.value("onion_prev", 1, type=int)
        self.onion_next = self.settings.value("onion_next", 0, type=int)
        self.onion_opacity_step = self.settings.value("onion_opacity_step", 0.2, type=float)
        self.onion_ref_exclusive = self.settings.value("onion_exclusive", False, type=bool)
        self.onion_ref_exclusive = self.settings.value("onion_exclusive", False, type=bool)
        self.onion_suppressed = False # New suppression state
        
        # Reference Frame Settings
        self.reference_frame = None # FrameData
        self.ref_opacity = self.settings.value("ref_opacity", 0.5, type=float)
        self.ref_layer = self.settings.value("ref_layer", "top", type=str)
        self.ref_show_on_playback = self.settings.value("ref_show_on_playback", False, type=bool)
        
        # Apply initial reference settings to canvas
        self.canvas.ref_opacity = self.ref_opacity
        self.canvas.ref_layer = self.ref_layer
        self.canvas.ref_show_on_playback = self.ref_show_on_playback

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
                QMainWindow::separator {
                    background-color: #333333;
                    width: 4px;
                    height: 4px;
                }
                QMainWindow::separator:hover {
                    background-color: #007ACC;
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
                QToolButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 3px;
                    padding: 3px;
                }
                QToolButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                    border: 1px solid rgba(255, 255, 255, 0.2);
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
                QRadioButton, QCheckBox {
                    spacing: 8px;
                    color: #CCCCCC;
                }
                QRadioButton::indicator, QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #454545;
                    border-radius: 9px;
                    background-color: #333333;
                }
                QRadioButton::indicator:checked, QCheckBox::indicator:checked {
                    background-color: #007ACC;
                    border: 3px solid #454545;
                    width: 12px;
                    height: 12px;
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
                QMainWindow::separator {
                    background-color: #CCCCCC;
                    width: 4px;
                    height: 4px;
                }
                QMainWindow::separator:hover {
                    background-color: #007ACC;
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
                QToolButton {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 3px;
                    padding: 3px;
                }
                QToolButton:hover {
                    background-color: rgba(0, 0, 0, 0.05);
                    border: 1px solid rgba(0, 0, 0, 0.1);
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
                QRadioButton, QCheckBox {
                    spacing: 8px;
                    color: #333333;
                }
                QRadioButton::indicator, QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #CCCCCC;
                    border-radius: 9px;
                    background-color: #FFFFFF;
                }
                QRadioButton::indicator:checked, QCheckBox::indicator:checked {
                    background-color: #007ACC;
                    border: 3px solid #CCCCCC;
                    width: 12px;
                    height: 12px;
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
        
        # Refresh visuals (specifically for Reference Frame highlight)
        if hasattr(self, 'timeline'):
            self.timeline.set_theme_mode(theme_name == "dark")
            if hasattr(self, 'reference_frame'):
                 self.timeline.set_visual_reference_frame(self.reference_frame)
        
        # Update specific widget styles that might need override
        self.canvas.update()
        self.timeline.update()
        self.property_panel.update()
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
        style = self.style()
        
        self.import_action = QAction(i18n.t("action_import"), self)
        self.import_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.import_action.triggered.connect(self.import_images)
        self.import_action.setShortcut(QKeySequence.StandardKey.Open)
        
        self.import_slice_action = QAction(i18n.t("action_import_slice"), self)
        self.import_slice_action.triggered.connect(self.import_sprite_sheet)
        self.import_slice_action.setShortcut("Ctrl+Shift+I")

        self.import_gif_action = QAction(i18n.t("action_import_gif"), self)
        self.import_gif_action.triggered.connect(self.import_gif)
        self.import_gif_action.setShortcut("Ctrl+G")
        
        self.save_action = QAction(i18n.t("action_save"), self)
        self.save_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_action.triggered.connect(self.save_project)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)

        self.save_as_action = QAction(i18n.t("action_save_as"), self)
        self.save_as_action.triggered.connect(self.save_project_as)
        self.save_as_action.setShortcut("Ctrl+Shift+S")

        self.load_action = QAction(i18n.t("action_load"), self)
        self.load_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.load_action.triggered.connect(self.load_project)
        
        self.action_open_dir = QAction(i18n.t("action_open_dir"), self)
        self.action_open_dir.triggered.connect(self.open_project_directory)
        
        self.close_action = QAction(i18n.t("action_close"), self)
        self.close_action.triggered.connect(self.close_project)
        self.close_action.setShortcut("Ctrl+W")
        
        self.reload_action = QAction(i18n.t("action_reload"), self)
        self.reload_action.triggered.connect(self.reload_project)
        self.reload_action.setShortcut("Ctrl+R")

        self.copy_assets_action = QAction(i18n.t("action_copy_assets"), self)
        self.copy_assets_action.triggered.connect(self.copy_assets_to_local)

        
        self.export_action = QAction(i18n.t("action_export"), self)
        self.export_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
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
        self.settings_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.settings_action.triggered.connect(self.open_settings)

        # View Reset Shortcut (Global)
        self.reset_view_action = QAction(i18n.t("action_reset_view"), self)
        self.reset_view_action.setShortcut("Ctrl+1")
        self.reset_view_action.triggered.connect(self.canvas.reset_view)
        
        # Onion Skin Actions
        self.onion_action = QAction(i18n.t("action_onion_skin"), self)
        self.onion_action.setCheckable(True)
        self.onion_action.setShortcut("O")
        self.onion_action.triggered.connect(self.toggle_onion_skin)
        
        self.onion_settings_action = QAction(i18n.t("action_onion_settings"), self)
        self.onion_settings_action.triggered.connect(self.configure_onion_settings)
        
        # Toolbar Onion Action (Separate for dynamic text)
        self.onion_toolbar_action = QAction(i18n.t("toolbar_onion_off"), self)
        onion_icon = QIcon()
        onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        self.onion_toolbar_action.setIcon(onion_icon)
        self.onion_toolbar_action.setCheckable(True)
        self.onion_toolbar_action.triggered.connect(self.toggle_onion_skin)
        
        self.addAction(self.reset_view_action)

        # Scale Hotkeys (Global)
        # Zoom Actions
        self.zoom_in_action = QAction(i18n.t("action_zoom_in"), self)
        self.zoom_in_action.setShortcut("Ctrl++")
        self.zoom_in_action.triggered.connect(lambda: self.adjust_zoom(1.1))
        
        self.zoom_out_action = QAction(i18n.t("action_zoom_out"), self)
        self.zoom_out_action.setShortcut("Ctrl+-")
        self.zoom_out_action.triggered.connect(lambda: self.adjust_zoom(0.9))
        
        self.zoom_fit_action = QAction(i18n.t("action_zoom_fit"), self)
        self.zoom_fit_action.setShortcut("Ctrl+0")
        self.zoom_fit_action.triggered.connect(self.canvas.fit_to_view)

        # Scale Actions (Selection)
        self.scale_up_action = QAction(i18n.t("action_scale_up"), self)
        self.scale_up_action.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        self.scale_up_action.triggered.connect(lambda: self.adjust_selection_scale(1.1))
        self.addAction(self.scale_up_action)

        self.scale_down_action = QAction(i18n.t("action_scale_down"), self)
        self.scale_down_action.setShortcut("Ctrl+-")
        self.scale_down_action.triggered.connect(lambda: self.adjust_selection_scale(0.9))
        self.addAction(self.scale_down_action)
        
        # Reference Settings Action
        self.ref_settings_action = QAction(i18n.t("dlg_ref_settings"), self)
        self.ref_settings_action.triggered.connect(self.configure_reference_settings)
        
        # Set Reference Action
        self.set_ref_action = QAction(i18n.t("action_set_reference"), self)
        self.set_ref_action.setIcon(IconGenerator.reference_frame_icon(QColor(0, 122, 204)))
        self.set_ref_action.setToolTip(i18n.t("action_set_reference"))
        self.set_ref_action.triggered.connect(self.set_reference_frame_from_selection)
        
        # Clear Reference Action
        self.clear_ref_action = QAction(i18n.t("action_cancel_reference"), self)
        self.clear_ref_action.triggered.connect(self.clear_reference_frame)

        # Play/Pause Shortcut (Global Space)
        self.play_pause_action = QAction(i18n.t("action_play_pause"), self)
        self.play_pause_action.setShortcut("Space")
        self.play_pause_action.triggered.connect(self.handle_space_shortcut)
        self.addAction(self.play_pause_action)
        
        # Play Action for Toolbar
        self.play_action = QAction(i18n.t("btn_play"), self)
        self.play_action.setCheckable(True)
        play_icon = QIcon()
        play_icon.addPixmap(IconGenerator.play_icon(QColor(200, 200, 200)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        play_icon.addPixmap(IconGenerator.pause_icon(QColor(255, 69, 58)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On) # Red for pause/stop
        self.play_action.setIcon(play_icon)
        self.play_action.toggled.connect(self.toggle_play)

        # Reverse Play Action for Toolbar
        self.rev_play_action = QAction(i18n.t("btn_backward"), self)
        self.rev_play_action.setCheckable(True)
        rev_icon = QIcon()
        rev_icon.addPixmap(IconGenerator.reverse_play_icon(QColor(200, 200, 200)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        rev_icon.addPixmap(IconGenerator.pause_icon(QColor(255, 69, 58)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        self.rev_play_action.setIcon(rev_icon)
        self.rev_play_action.toggled.connect(lambda checked: self.toggle_reverse_playback(checked))

        self.theme_dark_action = QAction(i18n.t("theme_dark"), self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.setChecked(True)
        self.theme_dark_action.triggered.connect(lambda: self.apply_theme("dark"))

        self.theme_light_action = QAction(i18n.t("theme_light"), self)
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
            
        # Wheel Mode Actions
        self.wheel_mode_group = QActionGroup(self)
        
        self.action_wheel_zoom_view = QAction(i18n.t("action_wheel_zoom_view"), self)
        self.action_wheel_zoom_view.setCheckable(True)
        self.action_wheel_zoom_view.triggered.connect(lambda: self.set_wheel_mode_actual(self.canvas.WHEEL_ZOOM))
        self.wheel_mode_group.addAction(self.action_wheel_zoom_view)
        
        self.action_wheel_scale_image = QAction(i18n.t("action_wheel_scale_image"), self)
        self.action_wheel_scale_image.setCheckable(True)
        self.action_wheel_scale_image.triggered.connect(lambda: self.set_wheel_mode_actual(self.canvas.WHEEL_SCALE))
        self.wheel_mode_group.addAction(self.action_wheel_scale_image)

        # Master toggle for toolbar
        self.action_toggle_wheel_mode = QAction("", self) # Text set dynamically
        self.action_toggle_wheel_mode.setCheckable(True)
        self.action_toggle_wheel_mode.triggered.connect(self.toggle_wheel_mode)

        # Initial State
        self.action_wheel_zoom_view.setChecked(True)
        self.update_wheel_toggle_ui()

        # Rasterization Preview Actions
        self.raster_toolbar_action = QAction(i18n.t("toolbar_raster_off"))
        raster_icon = QIcon()
        raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        self.raster_toolbar_action.setIcon(raster_icon)
        self.raster_toolbar_action.setCheckable(True)
        self.raster_toolbar_action.triggered.connect(self.toggle_rasterization)

        self.raster_settings_action = QAction(i18n.t("btn_raster_settings"))
        settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.raster_settings_action.setIcon(settings_icon)
        self.raster_settings_action.triggered.connect(self.configure_rasterization_settings)

        # About Actions
        self.repo_action = QAction(i18n.t("action_repo"), self)
        self.repo_action.triggered.connect(self.open_repo_url)
        
        version_str = self.get_git_version()
        self.version_action = QAction(i18n.t("action_version").format(version=version_str), self)
        self.version_action.setEnabled(False)
        
        compile_date = self.get_build_date()
        self.build_date_action = QAction(i18n.t("action_build_date").format(date=compile_date), self)
        self.build_date_action.setEnabled(False)

    def update_wheel_toggle_ui(self):
        # Sync the master toggle in toolbar based on current canvas mode
        mode = self.canvas.wheel_mode
        if mode == self.canvas.WHEEL_SCALE:
            self.action_toggle_wheel_mode.setText(i18n.t("action_wheel_scale_image"))
            self.action_toggle_wheel_mode.setChecked(True)
            self.action_wheel_scale_image.setChecked(True)
        else:
            self.action_toggle_wheel_mode.setText(i18n.t("action_wheel_zoom_view"))
            self.action_toggle_wheel_mode.setChecked(False)
            self.action_wheel_zoom_view.setChecked(True)
        
        # Icon sync
        wheel_icon = QIcon()
        wheel_icon.addPixmap(IconGenerator.create_pixmap("arrow_expand", QColor(200, 200, 200), 32), QIcon.Mode.Normal, QIcon.State.Off)
        wheel_icon.addPixmap(IconGenerator.create_pixmap("image", QColor(255, 204, 0), 32), QIcon.Mode.Normal, QIcon.State.On)
        self.action_toggle_wheel_mode.setIcon(wheel_icon)
        


    def create_menus(self):
        menubar = self.menuBar()
        
        # File Menu
        file_menu = menubar.addMenu(i18n.t("menu_file"))
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.import_slice_action)
        file_menu.addAction(self.import_gif_action)
        file_menu.addSeparator()
        file_menu.addAction(self.load_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)
        file_menu.addAction(self.reload_action)
        
        self.recent_menu = file_menu.addMenu(i18n.t("menu_recent_projects"))
        self.update_recent_projects_menu()
        
        file_menu.addAction(self.copy_assets_action)
        file_menu.addSeparator()
        file_menu.addAction(self.action_open_dir)
        file_menu.addSeparator()
        
        self.reload_images_action = QAction(i18n.t("action_reload_images"), self)
        self.reload_images_action.triggered.connect(self.reload_image_resources)
        file_menu.addAction(self.reload_images_action)
        
        file_menu.addSeparator()
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.export_sheet_action)
        
        # Onion & Reference Submenu
        # View Menu

        
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
        play_menu.addAction(self.rev_play_action)
        
        # View Menu
        view_menu = menubar.addMenu(i18n.t("menu_view"))
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_fit_action)
        view_menu.addAction(self.reset_view_action)
        view_menu.addSeparator()
        
        # Onion Skin (Flattened)
        view_menu.addAction(self.onion_action)
        view_menu.addAction(self.onion_settings_action)
        view_menu.addSeparator()
        
        # Reference Frame (Flattened)
        view_menu.addAction(self.set_ref_action)
        view_menu.addAction(self.ref_settings_action)
        view_menu.addAction(self.clear_ref_action)
        
        view_menu.addSeparator()
        
        # Wheel Mode Submenu
        wheel_menu = view_menu.addMenu(i18n.t("action_toggle_wheel_mode"))
        wheel_menu.addAction(self.action_wheel_zoom_view)
        wheel_menu.addAction(self.action_wheel_scale_image)
        
        view_menu.addSeparator()
        
        self.background_menu = view_menu.addMenu(i18n.t("menu_background"))
        for action in self.bg_actions.values():
            self.background_menu.addAction(action)
        
        view_menu.addSeparator()
        
        theme_menu = view_menu.addMenu(i18n.t("menu_theme"))
        theme_menu.addAction(self.theme_dark_action)
        theme_menu.addAction(self.theme_light_action)
        
        lang_menu = view_menu.addMenu(i18n.t("menu_lang"))
        lang_menu.addAction(self.lang_zh_action)
        lang_menu.addAction(self.lang_en_action)

        # About Menu
        about_menu = menubar.addMenu(i18n.t("menu_about"))
        about_menu.addAction(self.repo_action)
        about_menu.addAction(self.version_action)
        about_menu.addAction(self.build_date_action)

    def open_repo_url(self):
        try:
            parsed_url = QUrl(BUILD_REPO_URL)
            QDesktopServices.openUrl(parsed_url)
        except Exception:
            # Fallback
            QDesktopServices.openUrl(QUrl("https://github.com/tumuyan/PinFrame"))

    def get_git_version(self):
        self._git_available = False
        try:
            version = subprocess.check_output(
                ['git', 'describe', '--tags', '--long'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            self._git_available = True
            return version
        except Exception:
            return BUILD_VERSION

    def get_build_date(self):
        if getattr(self, '_git_available', False):
            dt = QDateTime.currentDateTime()
        else:
            try:
                dt = QDateTime.fromString(BUILD_DATE, Qt.DateFormat.ISODate)
                if not dt.isValid():
                    dt = QDateTime.currentDateTime()
                else:
                    dt = dt.toLocalTime()
            except Exception:
                dt = QDateTime.currentDateTime()
        return QLocale.system().toString(dt, QLocale.FormatType.LongFormat)

    def create_toolbar(self):
        # Remove and delete existing toolbar(s) to avoid duplication on language change
        for old_toolbar in self.findChildren(QToolBar, "MainToolbar"):
            self.removeToolBar(old_toolbar)
            old_toolbar.deleteLater()
            old_toolbar.setObjectName("DeletedToolbar") # Prevent re-finding in same loop
            
        toolbar = QToolBar(i18n.t("toolbar_main"))
        toolbar.setObjectName("MainToolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.save_action)
        # toolbar.addAction(self.save_as_action) # Removed as per Cycle 33
        toolbar.addAction(self.load_action)
        toolbar.addSeparator()
        toolbar.addAction(self.action_toggle_wheel_mode)
        toolbar.addSeparator()
        toolbar.addAction(self.settings_action)
        toolbar.addAction(self.export_action)
        
        toolbar.addSeparator()
        
        toolbar.addAction(self.onion_toolbar_action)

        # Add "Set Reference" action (from selection)
        # Add "Set Reference" action (from selection)
        # Action already defined in create_actions
        toolbar.addAction(self.set_ref_action)

        # Rasterization Preview
        toolbar.addAction(self.raster_toolbar_action)
        toolbar.addAction(self.raster_settings_action)

        toolbar.addSeparator()
        
        # FPS Control
        fps_label = QLabel(i18n.t("label_fps"))
        fps_label.setStyleSheet("background: transparent;")
        toolbar.addWidget(fps_label)
        
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(self.project.fps)
        self.fps_spin.valueChanged.connect(self.update_fps)
        self.fps_spin.setStyleSheet("background: transparent;")
        toolbar.addWidget(self.fps_spin)
        
        toolbar.addSeparator()
        
        # Play/Pause
        toolbar.addAction(self.play_action)
        
        toolbar.addSeparator()
        toolbar.addAction(self.rev_play_action)

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
                item.setText(0, "") # Updated by refresh
                item.setText(2, name)
                
                # Checkbox flags
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Checked = Disabled, Unchecked = Enabled
                item.setCheckState(1, Qt.CheckState.Checked if data.is_disabled else Qt.CheckState.Unchecked)
                
                self.timeline.update_item_display(item, data, w, h)
                self.timeline.insertTopLevelItem(target_idx + i, item)
                
        self.mark_dirty()
        self.timeline.refresh_current_items()

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
            
        # Get indices of all selected items
        indices = []
        for item in selected:
             indices.append(self.timeline.indexOfTopLevelItem(item))
        
        indices.sort()  # Sort in ascending order
        
        # Find the insertion point (after the last selected item)
        insert_pos = indices[-1] + 1
        
        # Collect all duplicates first
        duplicates = []
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
                is_disabled=orig_data.is_disabled,
                crop_rect=orig_data.crop_rect
            )
            
            # Get original dimensions from timeline item
            item = self.timeline.topLevelItem(idx)
            orig_res = item.data(3, Qt.ItemDataRole.UserRole)
            w, h = orig_res if orig_res else (0, 0)
            
            duplicates.append((new_data, w, h))
        
        # Insert all duplicates at the end of selection
        for i, (new_data, w, h) in enumerate(duplicates):
            # Insert into project
            self.project.frames.insert(insert_pos + i, new_data)
            
            # Create timeline item
            new_item = QTreeWidgetItem()
            new_item.setData(0, Qt.ItemDataRole.UserRole, new_data)
            new_item.setData(3, Qt.ItemDataRole.UserRole, (w, h))
            new_item.setText(0, "") # Will be updated by refresh_current_items
            new_item.setText(2, os.path.basename(new_data.file_path))
            new_item.setFlags(new_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            new_item.setCheckState(1, Qt.CheckState.Checked if new_data.is_disabled else Qt.CheckState.Unchecked)
            
            self.timeline.update_item_display(new_item, new_data, w, h)
            self.timeline.insertTopLevelItem(insert_pos + i, new_item)
            
        self.mark_dirty()
        self.timeline.refresh_current_items()
        self.statusBar().showMessage(i18n.t("msg_frames_duplicated").format(count=len(duplicates)), 3000)

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
        self.timeline.refresh_current_items() # Update numbers after removal
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

        if self.is_playing:
            self.update_playlist()
        self.statusBar().showMessage(i18n.t("msg_frames_enabled_disabled").format(action=i18n.t("action_enabled") if enable else i18n.t("action_disabled"), count=len(selected)), 3000)

    # --- Onion Skin & Reference Logic ---
        
    def configure_reference_settings(self):
        dlg = ReferenceSettingsDialog(self, self.ref_opacity, self.ref_layer, self.ref_show_on_playback)
        if dlg.exec():
            settings = dlg.get_settings()
            self.ref_opacity = settings["opacity"]
            self.ref_layer = settings["layer"]
            self.ref_show_on_playback = settings["show_on_playback"]
            
            # Save settings
            self.settings.setValue("ref_opacity", self.ref_opacity)
            self.settings.setValue("ref_layer", self.ref_layer)
            self.settings.setValue("ref_show_on_playback", self.ref_show_on_playback)
            
            # Apply to canvas
            self.canvas.ref_opacity = self.ref_opacity
            self.canvas.ref_layer = self.ref_layer
            self.canvas.ref_show_on_playback = self.ref_show_on_playback
            self.canvas.update()
            
            self.update_onion_state()

    def update_onion_state(self):
        """
        Centralized logic for Onion Skin visibility.
        Handles Enable/Disable, Suppression (Multi-select/Playback), and Mutual Exclusion.
        """
        # 1. Determine Suppression State
        # Suppress if: Multiple items selected OR Playing (forward or reverse)
        is_multi_select = len(self.timeline.selectedItems()) > 1
        is_playing = self.is_playing
        
        should_suppress = is_multi_select or is_playing
        
        if self.onion_enabled:
            if should_suppress:
                if not self.onion_suppressed:
                    self.onion_suppressed = True
                    # Visual Feedback: Yellow/Warning Icon
                    onion_icon = QIcon()
                    onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(255, 204, 0)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On) # Yellow for suppressed
                    self.onion_toolbar_action.setIcon(onion_icon)
                    self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on") + " (Suppressed)")
                    
                    # Canvas: Hide onion skin
                    self.canvas.set_onion_skins([])
            else:
                if self.onion_suppressed:
                    self.onion_suppressed = False
                    # Normal ON Icon
                    onion_icon = QIcon()
                    onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
                    onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
                    self.onion_toolbar_action.setIcon(onion_icon)
                    self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on"))

                # Check Mutual Exclusion (only when not suppressed and enabled)
                if self.onion_ref_exclusive and self.reference_frame:
                    if not self.onion_suppressed: # Only turn off if we would otherwise be showing it
                         self.toggle_onion_skin(False)
                         return

                # Calculate and set onion skins
                self.calculate_onion_skins()
        else:
            self.onion_suppressed = False
            # Normal OFF Icon behavior
            onion_icon = QIcon()
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
            self.onion_toolbar_action.setIcon(onion_icon)
            self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_off"))
            self.canvas.set_onion_skins([])
        
    def toggle_onion_skin(self, checked):
        # Update both actions
        self.onion_action.setChecked(checked)
        self.onion_toolbar_action.setChecked(checked)
        
        # Update Toolbar Text
        if checked:
            self.onion_toolbar_action.setText(i18n.t("toolbar_onion_on")) 
        else:
            self.onion_toolbar_action.setText(i18n.t("toolbar_onion_off"))
            
        # Behavior Change: If turning ON and Exclusive Mode + Reference Frame exists,
        # we should CLEAR the reference frame to allow Onion Skin to show.
        if checked:
            if self.onion_ref_exclusive and self.reference_frame:
                self.clear_reference_frame(update=True)
            
        self.onion_enabled = checked
        self.update_onion_state()
        
    def configure_reference_settings(self):
        dlg = ReferenceSettingsDialog(self, self.ref_opacity, self.ref_layer, self.ref_show_on_playback)
        if dlg.exec():
            settings = dlg.get_settings()
            self.ref_opacity = settings["opacity"]
            self.ref_layer = settings["layer"]
            self.ref_show_on_playback = settings["show_on_playback"]
            
            # Save settings
            self.settings.setValue("ref_opacity", self.ref_opacity)
            self.settings.setValue("ref_layer", self.ref_layer)
            self.settings.setValue("ref_show_on_playback", self.ref_show_on_playback)
            
            # Apply to canvas
            self.canvas.ref_opacity = self.ref_opacity
            self.canvas.ref_layer = self.ref_layer
            self.canvas.ref_show_on_playback = self.ref_show_on_playback
            self.canvas.update()
            
            self.update_onion_state()

    def update_onion_state(self):
        """
        Centralized logic for Onion Skin visibility.
        Handles Enable/Disable, Suppression (Multi-select/Playback), and Mutual Exclusion.
        """
        # 1. Determine Suppression State
        # Suppress if: Multiple items selected OR Playing (forward or reverse)
        is_multi_select = len(self.timeline.selectedItems()) > 1
        is_playing = self.is_playing
        
        should_suppress = is_multi_select or is_playing
        
        if self.onion_enabled:
            if should_suppress:
                self.onion_suppressed = True
                # Visual Feedback: Yellow/Warning Icon
                onion_icon = QIcon()
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(255, 204, 0)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On) # Yellow for suppressed
                self.onion_toolbar_action.setIcon(onion_icon)
                self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on") + " (Suppressed)")
                
                # Canvas: Hide onion skin
                self.canvas.set_onion_skins([])
            else:
                self.onion_suppressed = False
                # Normal ON Icon
                onion_icon = QIcon()
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
                self.onion_toolbar_action.setIcon(onion_icon)
                self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on"))
                
                # Check Mutual Exclusion (only when not suppressed and enabled)
                if self.onion_ref_exclusive and self.reference_frame:
                    if not self.onion_suppressed: # Only turn off if we would otherwise be showing it
                         self.toggle_onion_skin(False)
                         return

                # Calculate and set onion skins
                self.calculate_onion_skins()
        else:
            self.onion_suppressed = False
            # Normal OFF Icon behavior
            onion_icon = QIcon()
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
            self.onion_toolbar_action.setIcon(onion_icon)
            self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_off"))
            self.canvas.set_onion_skins([])

    def configure_reference_settings(self):
        dlg = ReferenceSettingsDialog(self, self.ref_opacity, self.ref_layer, self.ref_show_on_playback)
        if dlg.exec():
            settings = dlg.get_settings()
            self.ref_opacity = settings["opacity"]
            self.ref_layer = settings["layer"]
            self.ref_show_on_playback = settings["show_on_playback"]

            # Save settings
            self.settings.setValue("ref_opacity", self.ref_opacity)
            self.settings.setValue("ref_layer", self.ref_layer)
            self.settings.setValue("ref_show_on_playback", self.ref_show_on_playback)

            # Apply to canvas
            self.canvas.ref_opacity = self.ref_opacity
            self.canvas.ref_layer = self.ref_layer
            self.canvas.ref_show_on_playback = self.ref_show_on_playback
            self.canvas.update()

            self.update_onion_state()


    def configure_rasterization_settings(self):
        """Open rasterization settings dialog."""
        dlg = RasterizationSettingsDialog(
            self,
            self.raster_enabled,
            self.raster_grid_color,
            self.raster_scale_threshold,
            self.raster_show_grid
        )
        if dlg.exec():
            settings = dlg.get_settings()
            self.raster_enabled = settings["enabled"]
            self.raster_grid_color = settings["grid_color"]
            self.raster_scale_threshold = settings["scale_threshold"]
            self.raster_show_grid = settings["show_grid"]

            # Save to global settings
            self.settings.setValue("raster_enabled", self.raster_enabled)
            self.settings.setValue("raster_show_grid", self.raster_show_grid)
            grid_color_str = ",".join(map(str, self.raster_grid_color))
            self.settings.setValue("raster_grid_color", grid_color_str)
            self.settings.setValue("raster_scale_threshold", self.raster_scale_threshold)

            # Update canvas settings
            grid_color = QColor(*self.raster_grid_color)
            self.canvas.set_rasterization_settings(
                self.raster_enabled,
                grid_color,
                self.raster_scale_threshold,
                self.raster_show_grid
            )

            # Update UI
            self.update_rasterization_ui()

    def toggle_rasterization(self, checked):
        """Toggle rasterization preview."""
        self.raster_enabled = checked
        self.settings.setValue("raster_enabled", self.raster_enabled)
        
        grid_color = QColor(*self.raster_grid_color)
        self.canvas.set_rasterization_settings(
            self.raster_enabled,
            grid_color,
            self.raster_scale_threshold,
            self.raster_show_grid
        )
        self.update_rasterization_ui()

    def update_rasterization_ui(self):
        """Update rasterization button state."""
        enabled = self.raster_enabled

        # Update button text
        if enabled:
            self.raster_toolbar_action.setText(i18n.t("toolbar_raster_on"))
        else:
            self.raster_toolbar_action.setText(i18n.t("toolbar_raster_off"))

        # Update button checked state
        self.raster_toolbar_action.setChecked(enabled)

        # Update icon colors
        raster_icon = QIcon()
        if enabled:
            raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
            raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        else:
            raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
            raster_icon.addPixmap(IconGenerator.rasterization_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        self.raster_toolbar_action.setIcon(raster_icon)


    def update_onion_state(self):
        """
        Centralized logic for Onion Skin visibility.
        Handles Enable/Disable, Suppression (Multi-select/Playback), and Mutual Exclusion.
        """
        # 1. Determine Suppression State
        # Suppress if: Multiple items selected OR Playing (forward or reverse)
        is_multi_select = len(self.timeline.selectedItems()) > 1
        is_playing = self.is_playing
        
        should_suppress = is_multi_select or is_playing
        
        if self.onion_enabled:
            if should_suppress:
                self.onion_suppressed = True
                # Visual Feedback: Yellow/Warning Icon
                onion_icon = QIcon()
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(255, 204, 0)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On) # Yellow for suppressed
                self.onion_toolbar_action.setIcon(onion_icon)
                self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on") + " (Suppressed)")
                
                # Canvas: Hide onion skin
                self.canvas.set_onion_skins([])
            else:
                self.onion_suppressed = False
                # Normal ON Icon
                onion_icon = QIcon()
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
                onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
                self.onion_toolbar_action.setIcon(onion_icon)
                self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_on"))
                
                # Check Mutual Exclusion (only when not suppressed and enabled)
                if self.onion_ref_exclusive and self.reference_frame:
                    # If exclusive and reference set, we shouldn't have enabled onion?
                    # But if we just came out of suppression, maybe we need to check.
                    # Logic says: "If exclusive mode enabled... and reference frame set... normally close onion skin switch."
                    # So if we are here, we should turn it off.
                    self.toggle_onion_skin(False)
                    return

                # Calculate and set onion skins
                self.calculate_onion_skins()
        else:
            self.onion_suppressed = False
            # Normal OFF Icon behavior (already handled by toggle_onion_skin setting checked state)
            # Just ensure icon is correct (standard dual state handles off)
            onion_icon = QIcon()
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
            onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
            self.onion_toolbar_action.setIcon(onion_icon)
            self.onion_toolbar_action.setToolTip(i18n.t("toolbar_onion_off"))
            self.canvas.set_onion_skins([])

    def toggle_wheel_mode(self, checked):
        # Toggled from toolbar
        mode = self.canvas.WHEEL_SCALE if checked else self.canvas.WHEEL_ZOOM
        self.set_wheel_mode_actual(mode)

    def set_wheel_mode_actual(self, mode):
        self.canvas.set_wheel_mode(mode)
        self.update_wheel_toggle_ui()
    

        
    def configure_onion_settings(self):
        dlg = OnionSettingsDialog(self, self.onion_prev, self.onion_next, self.onion_opacity_step, self.onion_ref_exclusive)
        if dlg.exec():
            settings = dlg.get_settings()
            # onion_enabled is NOT updated here anymore
            self.onion_prev = settings["prev"]
            self.onion_next = settings["next"]
            self.onion_opacity_step = settings["opacity"]
            self.onion_ref_exclusive = settings["exclusive"]
            
            # Sync action state and text (Just re-apply current state to update visuals if options changed)
            self.toggle_onion_skin(self.onion_enabled)
            
            if self.onion_enabled and self.onion_ref_exclusive:
                 self.clear_reference_frame(update=False)

            self.update_onion_state()

    def set_reference_frame_from_selection(self):
        selected = self.timeline.selectedItems()
        if len(selected) != 1:
            return
            
        frame_data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        
        # Toggle / Cancel if already Ref
        if self.reference_frame and frame_data == self.reference_frame:
             self.clear_reference_frame()
             self.set_ref_action.setText(i18n.t("action_set_reference"))
             return
             
        # print(f"[DEBUG] Setting reference frame: {frame_data.file_path}")
        
        self.reference_frame = frame_data
        
        if self.onion_ref_exclusive:
            # print("[DEBUG] Exclusive mode: Disabling onion skin")
            # Reuse toggle to update text/state
            self.toggle_onion_skin(False)
        
        # Update Action Text
        self.set_ref_action.setText(i18n.t("action_cancel_reference"))
        
        # update UI indication
        self.update_reference_view()
        self.timeline.viewport().update()
        
        self.update_onion_state()
        
    def clear_reference_frame(self, update=True):
        self.reference_frame = None
        if update:
            self.update_reference_view()
            self.timeline.viewport().update()
            
        self.update_onion_state()

    def update_reference_view(self):
        self.canvas.set_reference_frame(self.reference_frame)
        self.timeline.set_visual_reference_frame(self.reference_frame)
        
    def calculate_onion_skins(self):
        onion_skins = []
        if self.onion_enabled and (self.onion_prev > 0 or self.onion_next > 0):
            # Find current frame index
            current_item = self.timeline.currentItem()
            if current_item:
                index = self.timeline.indexOfTopLevelItem(current_item)
                
                # Previous Frames
                for i in range(1, self.onion_prev + 1):
                    target_idx = index - i
                    if target_idx >= 0:
                        item = self.timeline.topLevelItem(target_idx)
                        data = item.data(0, Qt.ItemDataRole.UserRole)
                        opacity = max(0.05, 1.0 - (i * self.onion_opacity_step))
                        onion_skins.append((data, opacity))
                
                # Next Frames
                for i in range(1, self.onion_next + 1):
                    target_idx = index + i
                    if target_idx < self.timeline.topLevelItemCount():
                        item = self.timeline.topLevelItem(target_idx)
                        data = item.data(0, Qt.ItemDataRole.UserRole)
                        opacity = max(0.05, 1.0 - (i * self.onion_opacity_step))
                        onion_skins.append((data, opacity))

        self.canvas.set_onion_skins(onion_skins)

    def on_selection_changed(self, frames):
        # 'frames' is a list of FrameData objects from Timeline
        self.canvas.set_selected_frames(frames)
        self.property_panel.set_selection(frames)
        
        # Update Reference Action Text
        if len(frames) == 1 and self.reference_frame and frames[0] == self.reference_frame:
             self.set_ref_action.setText(i18n.t("action_cancel_reference"))
        else:
             self.set_ref_action.setText(i18n.t("action_set_reference"))
        

        
        self.update_onion_state() # Update Onion (auto-suppress logic handled here)
        
        # Update playlist if playing
        if self.is_playing:
            self.update_playlist()
        
        # Show offset information for multi-frame selection when not playing
        if not self.is_playing and len(frames) >= 2:
            self.show_frame_offset_info(frames)
    
    def show_frame_offset_info(self, frames):
        """Calculate and display offset information between first and last selected frames."""
        first_frame = frames[0]
        last_frame = frames[-1]
        
        # Get dimensions for both frames
        first_w, first_h = self.get_frame_dimensions(first_frame)
        last_w, last_h = self.get_frame_dimensions(last_frame)
        
        if first_w == 0 or last_w == 0:
            return
        
        # Calculate scaled dimensions
        first_scaled_w = first_w * first_frame.scale
        first_scaled_h = first_h * first_frame.scale
        last_scaled_w = last_w * last_frame.scale
        last_scaled_h = last_h * last_frame.scale
        
        # Center positions
        first_center_x = first_frame.position[0]
        first_center_y = first_frame.position[1]
        last_center_x = last_frame.position[0]
        last_center_y = last_frame.position[1]
        
        # Center offset
        center_dx = last_center_x - first_center_x
        center_dy = last_center_y - first_center_y
        
        # Edge positions
        first_left = first_center_x - first_scaled_w / 2
        first_right = first_center_x + first_scaled_w / 2
        first_top = first_center_y - first_scaled_h / 2
        first_bottom = first_center_y + first_scaled_h / 2
        
        last_left = last_center_x - last_scaled_w / 2
        last_right = last_center_x + last_scaled_w / 2
        last_top = last_center_y - last_scaled_h / 2
        last_bottom = last_center_y + last_scaled_h / 2
        
        # Edge offsets
        left_offset = last_left - first_left
        right_offset = last_right - first_right
        top_offset = last_top - first_top
        bottom_offset = last_bottom - first_bottom
        
        # Format message
        msg = i18n.t("msg_multi_frame_offset").format(
            count=len(frames),
            center_dx=int(center_dx),
            center_dy=int(center_dy),
            left=int(left_offset),
            right=int(right_offset),
            top=int(top_offset),
            bottom=int(bottom_offset)
        )
        
        self.statusBar().showMessage(msg)
    
    def get_frame_dimensions(self, frame):
        """Get the original dimensions of a frame, respecting crop_rect if present."""
        if frame.crop_rect:
            return frame.crop_rect[2], frame.crop_rect[3]
        
        # Try to get from file
        if os.path.exists(frame.file_path):
            try:
                from PIL import Image
                with Image.open(frame.file_path) as img:
                    return img.size
            except:
                pass
        
        return 0, 0

    def on_canvas_transform_changed(self, primary_frame_data):
        # Update property panel ref
        self.property_panel.update_ui_from_selection()
        # Update Timeline texts
        self.timeline.refresh_current_items()
        self.mark_dirty()

    def on_property_changed(self, frame_data=None):
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

    def adjust_zoom(self, factor):
        self.canvas.view_scale *= factor
        self.canvas.update()
        
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

    def on_canvas_scale_requested(self, factor):
        # Use property panel to apply scale with proper anchor support
        self.property_panel.apply_rel_scale(factor)

    def on_order_changed(self):
        # Rebuild project frames list based on timeline order
        new_frames = []
        for i in range(self.timeline.topLevelItemCount()):
            item = self.timeline.topLevelItem(i)
            new_frames.append(item.data(0, Qt.ItemDataRole.UserRole))
        self.project.frames = new_frames
        self.timeline.refresh_current_items() # Update numbers after drag&drop
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
        
        from PyQt6.QtCore import QSignalBlocker
        with QSignalBlocker(self.play_action), QSignalBlocker(self.rev_play_action):
            self.play_action.setText(i18n.t("btn_play"))
            self.play_action.setChecked(False)
            self.rev_play_action.setText(i18n.t("btn_backward"))
            self.rev_play_action.setChecked(False)
            
        self.statusBar().showMessage(i18n.t("msg_playback_stopped"))
        
        # Restore selection
        selected_items = self.timeline.selectedItems()
        frames = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        self.canvas.set_selected_frames(frames)
        self.update_onion_state()

    def handle_space_shortcut(self):
        if self.is_playing:
            self.stop_playback()
        else:
            self.toggle_play()

    def toggle_play(self, checked=False):
        # Forward Playback Toggle
        if self.is_playing and not self.playback_reverse:
            # Currently playing forward, so stop
            self.stop_playback()
        else:
            # Either paused or playing backward, switch to forward
            self.is_playing = True
            self.playback_reverse = False
            
            # Update UI
            # Update UI
            from PyQt6.QtCore import QSignalBlocker
            with QSignalBlocker(self.play_action), QSignalBlocker(self.rev_play_action):
                self.play_action.setText(i18n.t("btn_pause"))
                self.play_action.setChecked(True)
                self.rev_play_action.setText(i18n.t("btn_backward"))
                self.rev_play_action.setChecked(False)
            
            self.playlist = []
            self.play_index = 0
            self.update_playlist()
                
            if not self.playlist:
                self.is_playing = False
                with QSignalBlocker(self.play_action):
                    self.play_action.setText(i18n.t("btn_play"))
                    self.play_action.setChecked(False)
                return

            self.timer.start(1000 // self.project.fps)
            self.update_onion_state()

    def toggle_reverse_playback(self, checked=False):
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
            # Update UI
            from PyQt6.QtCore import QSignalBlocker
            with QSignalBlocker(self.play_action), QSignalBlocker(self.rev_play_action):
                self.play_action.setText(i18n.t("btn_play"))
                self.play_action.setChecked(False)
                self.rev_play_action.setText(i18n.t("btn_pause"))
                self.rev_play_action.setChecked(True)
            
            self.playlist = []
            self.play_index = 0
            self.update_playlist()
                
            if not self.playlist:
                self.is_playing = False
                with QSignalBlocker(self.rev_play_action):
                    self.rev_play_action.setText(i18n.t("btn_backward"))
                    self.rev_play_action.setChecked(False)
                return

            self.timer.start(1000 // self.project.fps)
            self.update_onion_state()

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
        path, _ = QFileDialog.getSaveFileName(self, i18n.t("dlg_save_title"), "", i18n.t("dlg_filter_json"))
        if not path:
            return
        self._save_to_path(path)

    def save_settings(self):
        self.settings.setValue("recent_projects", self.recent_projects)
        self.settings.setValue("theme", self.current_theme)
        self.settings.setValue("language", self.current_lang)
        self.settings.setValue("background_mode", self.current_background_mode)
        self.settings.setValue("onion_prev", self.onion_prev)
        self.settings.setValue("onion_next", self.onion_next)
        self.settings.setValue("onion_opacity_step", self.onion_opacity_step)
        self.settings.setValue("onion_exclusive", self.onion_ref_exclusive)
        self.settings.setValue("ref_opacity", self.ref_opacity)
        self.settings.setValue("ref_layer", self.ref_layer)
        self.settings.setValue("ref_show_on_playback", self.ref_show_on_playback)
        self.settings.setValue("repeat_interval", self.property_panel.repeat_interval)

    def _save_to_path(self, path):
        try:
            with open(path, 'w') as f:
                f.write(self.project.to_json(path))
            self.current_project_path = path
            self.add_recent_project(path)
            self.is_dirty = False
            self.update_title()
            self.update_menu_state()
            self.statusBar().showMessage(i18n.t("msg_project_saved").format(path=path), 3000)
        except Exception as e:
            print(f"Error saving: {e}")
            self.statusBar().showMessage(f"Error saving: {e}", 5000)

    def load_project(self):
        if not self.check_unsaved_changes():
            return

        path, _ = QFileDialog.getOpenFileName(self, i18n.t("dlg_load_title"), "", i18n.t("dlg_filter_json"))
        if not path:
            return
            
        self._load_from_path(path)

    def _load_from_path(self, path):
        try:
            with open(path, 'r') as f:
                json_str = f.read()
                
            self.project = ProjectData.from_json(json_str, path)
            self.current_project_path = path
            self.add_recent_project(path)
            
            # Update UI
            self.fps_spin.setValue(self.project.fps)
            self.canvas.set_project_settings(self.project.width, self.project.height)
            self.property_panel.set_project_info(self.project.width, self.project.height)

            # Rasterization settings are now global, don't load from project

            self.timeline.clear()
            for frame in self.project.frames:
                w, h = 0, 0
                if frame.crop_rect:
                    w, h = frame.crop_rect[2], frame.crop_rect[3]
                elif os.path.exists(frame.file_path):
                    # Optimized: Read only metadata/size
                    reader = QImageReader(frame.file_path)
                    if reader.canRead():
                        size = reader.size()
                        w, h = size.width(), size.height()
                
                self.timeline.add_frame(os.path.basename(frame.file_path), frame, w, h)
                
            if self.project.frames:
                # Select first by default
                if self.timeline.topLevelItemCount() > 0:
                    self.timeline.setCurrentItem(self.timeline.topLevelItem(0))
                    
            self.is_dirty = False
            self.update_title()
            self.update_onion_state()
            self.update_menu_state()
            self.statusBar().showMessage(i18n.t("msg_project_loaded").format(path=path), 3000)
        except Exception as e:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(i18n.t("dlg_load_title"))
            msg_box.setText(f"{i18n.t('msg_load_error')}: {str(e)}")
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.addButton(i18n.t("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()
        
    def check_unsaved_changes(self):
        if self.is_dirty:
            from PyQt6.QtWidgets import QMessageBox
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(i18n.t("dlg_unsaved_title"))
            msg_box.setText(i18n.t("msg_unsaved_changes"))
            msg_box.setIcon(QMessageBox.Icon.Question)
            
            save_btn = msg_box.addButton(i18n.t("btn_save"), QMessageBox.ButtonRole.AcceptRole)
            discard_btn = msg_box.addButton(i18n.t("btn_discard"), QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton(i18n.t("btn_cancel"), QMessageBox.ButtonRole.RejectRole)
            
            msg_box.setDefaultButton(save_btn)
            msg_box.exec()
            
            clicked_btn = msg_box.clickedButton()
            
            if clicked_btn == save_btn:
                self.save_project()
                return not self.is_dirty # If save failed/cancelled, return False
            elif clicked_btn == cancel_btn:
                return False
            
        return True
    
    def close_project(self):
        """Close current project and reset to empty state."""
        if not self.check_unsaved_changes():
            return
        
        # Reset project to empty state
        self.project = ProjectData()
        self.fps_spin.setValue(self.project.fps)
        self.canvas.set_project_settings(self.project.width, self.project.height)
        self.property_panel.set_project_info(self.project.width, self.project.height)

        # Apply rasterization settings (Keep global settings)
        grid_color = QColor(*self.raster_grid_color)
        self.canvas.set_rasterization_settings(
            self.raster_enabled,
            grid_color,
            self.raster_scale_threshold,
            self.raster_show_grid
        )
        self.update_rasterization_ui()

        # Clear timeline
        self.timeline.clear()
        
        # Clear canvas selection
        self.canvas.set_selected_frames([])
        
        # Reset project path and dirty flag
        self.current_project_path = None
        self.is_dirty = False
        
        # Update UI
        self.update_title()
        self.update_menu_state()
        self.statusBar().showMessage(i18n.t("msg_project_closed"), 3000)

    def update_menu_state(self):
        """Enable/Disable menu items based on project state."""
        has_project = self.current_project_path is not None
        self.action_open_dir.setEnabled(has_project)
        self.copy_assets_action.setEnabled(has_project)
        self.save_action.setEnabled(has_project)
        self.reload_action.setEnabled(has_project)
        # self.action_export.setEnabled(has_project) # Maybe?

    
    def reload_project(self):
        """Reload current project from disk."""
        if not self.current_project_path:
            self.statusBar().showMessage(i18n.t("msg_no_project_reload"), 3000)
            return
        
        if self.is_dirty:
            if not self.check_unsaved_changes():
                return
        
        try:
            self._load_from_path(self.current_project_path)
            self.statusBar().showMessage(i18n.t("msg_project_reloaded").format(name=os.path.basename(self.current_project_path)), 3000)
        except Exception as e:
            self.statusBar().showMessage(i18n.t("msg_load_error").format(error=str(e)), 5000)

    def open_project_directory(self):
        folder_path = ""
        if self.current_project_path:
            folder_path = os.path.dirname(self.current_project_path)
        else:
            folder_path = os.getcwd()
            
        if folder_path and os.path.isdir(folder_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    def reload_image_resources(self):
        """Force reload of all image resources in the canvas."""
        self.canvas.refresh_resources()
        self.statusBar().showMessage(i18n.t("action_reload_images"), 3000) # Reusing label for status for now or simple msg
        
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
        self.import_gif_action.setText(i18n.t("action_import_gif"))
        self.save_action.setText(i18n.t("action_save"))
        self.save_as_action.setText(i18n.t("action_save_as"))
        self.load_action.setText(i18n.t("action_load"))
        self.close_action.setText(i18n.t("action_close"))
        self.reload_action.setText(i18n.t("action_reload"))
        self.export_action.setText(i18n.t("action_export"))
        self.export_sheet_action.setText(i18n.t("action_export_sheet"))
        self.copy_props_action.setText(i18n.t("action_copy_props"))
        self.paste_props_action.setText(i18n.t("action_paste_props"))
        self.dup_frame_action.setText(i18n.t("action_dup_frame"))
        self.rem_frame_action.setText(i18n.t("action_rem_frame"))
        self.reverse_order_action.setText(i18n.t("action_reverse_order"))
        self.settings_action.setText(i18n.t("action_settings"))
        self.reset_view_action.setText(i18n.t("action_reset_view"))
        self.zoom_in_action.setText(i18n.t("action_zoom_in"))
        self.zoom_out_action.setText(i18n.t("action_zoom_out"))
        self.zoom_fit_action.setText(i18n.t("action_zoom_fit"))
        self.scale_up_action.setText(i18n.t("action_scale_up"))
        self.scale_down_action.setText(i18n.t("action_scale_down"))
        
        # Wheel Mode
        self.action_wheel_zoom_view.setText(i18n.t("action_wheel_zoom_view"))
        self.action_wheel_scale_image.setText(i18n.t("action_wheel_scale_image"))
        self.update_wheel_toggle_ui()
        
        # Background Actions
        for mode, action in self.bg_actions.items():
            action.setText(i18n.t(f"bg_{mode}"))
        
        # Playback buttons (conditional)
        if self.is_playing:
            if self.playback_reverse:
                self.rev_play_action.setText(i18n.t("btn_pause"))
                self.play_action.setText(i18n.t("btn_play"))
            else:
                self.play_action.setText(i18n.t("btn_pause"))
                self.rev_play_action.setText(i18n.t("btn_backward"))
        else:
            self.play_action.setText(i18n.t("btn_play"))
            self.rev_play_action.setText(i18n.t("btn_backward"))
            
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

        # About
        self.repo_action.setText(i18n.t("action_repo"))
        version_str = self.get_git_version()
        self.version_action.setText(i18n.t("action_version").format(version=version_str))
        build_date = self.get_build_date()
        self.build_date_action.setText(i18n.t("action_build_date").format(date=build_date))
        
        # Repeat Actions
        for ms, action in self.repeat_actions.items():
            if ms == 0:
                action.setText(i18n.t("lang_disabled"))
            elif ms == 250:
                action.setText(i18n.t("lang_250_default", "250ms (Default)"))
        
        # Update Docks
        self.timeline_dock.setWindowTitle(i18n.t("dock_timeline"))
        self.property_dock.setWindowTitle(i18n.t("dock_properties"))
        # Assuming t_state and p_state are defined elsewhere or this is a partial snippet
        # self.timeline.restoreState(QByteArray.fromHex(t_state.encode()))
        # self.property_panel.restoreState(QByteArray.fromHex(p_state.encode()))
        
        self.update_menu_state()

        
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
        self.create_toolbar()

        # Update Sub-widgets
        self.property_panel.refresh_ui_text()
        self.timeline.setHeaderLabels([
            i18n.t("col_index"),
            i18n.t("col_disabled"), 
            i18n.t("col_filename"), 
            i18n.t("col_scale"), 
            i18n.t("col_position"), 
            i18n.t("col_res_combined")
        ])
        self.timeline.refresh_current_items()
        
        # This is enough for now. A restart is always safer.
        self.update_title()
        self.statusBar().showMessage(i18n.t("ready"))

    def closeEvent(self, event):
        if self.check_unsaved_changes():
            # Save settings
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("windowState", self.saveState())
            self.settings.setValue("recent_projects", self.recent_projects)
            self.settings.setValue("theme", self.current_theme)
            self.settings.setValue("onion_exclusive", self.onion_ref_exclusive)
            self.settings.setValue("onion_prev", self.onion_prev)
            self.settings.setValue("onion_next", self.onion_next)
            self.settings.setValue("onion_opacity_step", self.onion_opacity_step)
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
        file, _ = QFileDialog.getOpenFileName(self, i18n.t("dlg_import_slice_title"), "", i18n.t("dlg_filter_images"))
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
            # 只加载一次图片（用于验证）
            for crop in crops:
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
        self.timeline.refresh_current_items()
        self.statusBar().showMessage(i18n.t("msg_imported_slices").format(count=len(crops)), 3000)

    def import_gif(self):
        file, _ = QFileDialog.getOpenFileName(self, i18n.t("dlg_import_gif_title"), "", i18n.t("dlg_filter_gif"))
        if not file:
            return
            
        try:
            from PIL import Image, ImageSequence
            gif = Image.open(file)
            
            base_dir = os.path.dirname(file)
            base_name = os.path.splitext(os.path.basename(file))[0]
            frames_dir = os.path.join(base_dir, f"{base_name}_gif_frames")
            if not os.path.exists(frames_dir):
                os.makedirs(frames_dir)
                
            count = 0
            for i, frame in enumerate(ImageSequence.Iterator(gif)):
                # Convert to RGBA to ensure PNG compatibility and transparency
                png_frame = frame.convert("RGBA")
                out_path = os.path.join(frames_dir, f"{base_name}_{i:03d}.png")
                png_frame.save(out_path)
                
                # Add to project
                f_data = FrameData(file_path=out_path)
                self.project.frames.append(f_data)
                self.timeline.add_frame(os.path.basename(out_path), f_data, png_frame.width, png_frame.height)
                count += 1
                
            self.mark_dirty()
            self.timeline.refresh_current_items()
            self.statusBar().showMessage(i18n.t("msg_imported_gif").format(count=count), 3000)
            
        except Exception as e:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(i18n.t("dlg_load_error"))
            msg_box.setText(f"Error importing GIF: {str(e)}")
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.addButton(i18n.t("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()

    def _get_export_indices(self, range_mode, custom_range):
        """Helper to get list of indices based on mode."""
        if range_mode == "selected":
            selected = self.timeline.selectedItems()
            indices = []
            for item in selected:
                indices.append(self.timeline.indexOfTopLevelItem(item))
            return sorted(indices)
        elif range_mode == "custom":
            from utils.exporter import Exporter
            return Exporter.parse_range_string(custom_range, len(self.project.frames))
        else: # "all"
            # Return all non-disabled frames' indices
            return [i for i, f in enumerate(self.project.frames) if not f.is_disabled]

    def export_sprite_sheet(self):
        from ui.export_dialog import SpriteSheetExportDialog
        dlg = SpriteSheetExportDialog(self)
        dlg.cols_spin.setValue(self.project.export_sheet_cols)
        dlg.padding_spin.setValue(self.project.export_sheet_padding)
        dlg.common.set_settings(self.project.export_range_mode, self.project.export_custom_range, self.project.export_bg_color)
        
        if not dlg.exec():
            return
            
        settings = dlg.common.get_settings()
        self.project.export_sheet_cols = dlg.cols_spin.value()
        self.project.export_sheet_padding = dlg.padding_spin.value()
        self.project.export_range_mode = settings["range_mode"]
        self.project.export_custom_range = settings["custom_range"]
        self.project.export_bg_color = settings["bg_color"]
        self.mark_dirty()
        
        file, _ = QFileDialog.getSaveFileName(self, i18n.t("action_export_sheet"), "", i18n.t("dlg_filter_images"))
        if not file:
            return
            
        indices = self._get_export_indices(settings["range_mode"], settings["custom_range"])
        if not indices:
            self.statusBar().showMessage(i18n.t("msg_no_frames_to_export", "No frames to export"), 3000)
            return

        from utils.exporter import Exporter
        try:
            Exporter.export_sprite_sheet(self.project, file, frame_indices=indices, bg_color=self.project.export_bg_color)
            self.statusBar().showMessage(i18n.t("msg_export_complete"), 3000)
        except Exception as e:
            self.statusBar().showMessage(f"{i18n.t('msg_save_error').format(error=str(e))}", 5000)


    def export_sequence(self):
        # Stop playback if running
        if self.is_playing:
            self.stop_playback()
        
        # Options
        from ui.export_dialog import ExportOptionsDialog
        dlg = ExportOptionsDialog(self)
        # Load persistent options
        dlg.use_original_names.setChecked(self.project.export_use_orig_names)
        dlg.common.set_settings(self.project.export_range_mode, self.project.export_custom_range, self.project.export_bg_color)
        
        if not dlg.exec():
            return
            
        settings = dlg.common.get_settings()
        use_orig_names = dlg.use_original_names.isChecked()
        export_type = dlg.export_type  # "sequence" or "gif"
        
        # Save settings back to project
        self.project.export_use_orig_names = use_orig_names
        self.project.export_range_mode = settings["range_mode"]
        self.project.export_custom_range = settings["custom_range"]
        self.project.export_bg_color = settings["bg_color"]
        self.mark_dirty() 

        indices = self._get_export_indices(settings["range_mode"], settings["custom_range"])
        if not indices:
             self.statusBar().showMessage(i18n.t("msg_no_frames_to_export"), 3000)
             return

        from utils.exporter import Exporter 
        from PyQt6.QtWidgets import QApplication

        if export_type == "sequence":
            start_dir = self.project.last_export_path if self.project.last_export_path else ""
            out_dir = QFileDialog.getExistingDirectory(self, i18n.t("dlg_save_title"), start_dir)
            if not out_dir:
                return
                
            self.project.last_export_path = out_dir
            
            # Export Loop
            total = len(indices)
            try:
                for current, total_cnt in Exporter.export_iter(self.project, out_dir, use_orig_names, 
                                                            frame_indices=indices, bg_color=self.project.export_bg_color):
                    self.statusBar().showMessage(i18n.t("msg_exporting").format(index=current, total=total_cnt))
                    QApplication.processEvents()
                self.statusBar().showMessage(i18n.t("msg_export_complete"), 3000)
            except Exception as e:
                self.statusBar().showMessage(f"Export Error: {str(e)}", 5000)

        elif export_type == "gif":
            # Determine default filename and directory
            default_dir = ""
            default_filename = ""
            
            if self.project.last_gif_export_path:
                default_dir = os.path.dirname(self.project.last_gif_export_path)
                default_filename = os.path.basename(self.project.last_gif_export_path)
            elif self.current_project_path:
                default_dir = os.path.dirname(self.current_project_path)
                default_filename = os.path.splitext(os.path.basename(self.current_project_path))[0] + ".gif"
            else:
                default_filename = "animation.gif"

            out_path, _ = QFileDialog.getSaveFileName(
                self, 
                i18n.t("dlg_export_gif_save_title"), 
                os.path.join(default_dir, default_filename),
                i18n.t("dlg_filter_gif")
            )
            
            if not out_path:
                return
                
            self.project.last_gif_export_path = out_path
            
            self.statusBar().showMessage(i18n.t("msg_exporting").format(index="...", total="..."))
            try:
                Exporter.export_gif(self.project, out_path, frame_indices=indices, bg_color=self.project.export_bg_color)
                self.statusBar().showMessage(i18n.t("msg_export_complete"), 3000)
            except Exception as e:
                self.statusBar().showMessage(f"GIF Export Error: {str(e)}", 5000)
    def copy_assets_to_local(self):
        if not self.current_project_path:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(i18n.t("action_copy_assets"))
            msg_box.setText(i18n.t("msg_save_project_first"))
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.addButton(i18n.t("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()
            return
            
        from ui.copy_assets_dialog import CopyAssetsDialog
        dlg = CopyAssetsDialog(self.project, self.current_project_path, self)
        if dlg.exec():
            self.mark_dirty()
            self.timeline.refresh_current_items() # Filenames might have changed or just to be sure
            self.canvas.update()

    def add_recent_project(self, path):
        path = os.path.abspath(path)
        if path in self.recent_projects:
            self.recent_projects.remove(path)
        self.recent_projects.insert(0, path)
        self.recent_projects = self.recent_projects[:10] # Limit to 10
        self.save_settings()
        self.update_recent_projects_menu()

    def update_recent_projects_menu(self):
        if not hasattr(self, 'recent_menu'):
            return
            
        self.recent_menu.clear()
        
        if not self.recent_projects:
            action = QAction(i18n.t("msg_no_selection"), self) # Use a generic "None" or similar
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return

        for path in self.recent_projects:
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self.load_recent_project(p))
            self.recent_menu.addAction(action)
            
        self.recent_menu.addSeparator()
        clear_action = QAction(i18n.t("action_clear_recent"), self)
        clear_action.triggered.connect(self.clear_recent_projects)
        self.recent_menu.addAction(clear_action)

    def load_recent_project(self, path):
        if not os.path.exists(path):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(i18n.t("dlg_load_title"))
            msg_box.setText(i18n.t("msg_recent_file_not_found").format(path=path))
            msg_box.setIcon(QMessageBox.Icon.Question)
            
            yes_btn = msg_box.addButton(i18n.t("btn_yes"), QMessageBox.ButtonRole.YesRole)
            no_btn = msg_box.addButton(i18n.t("btn_no"), QMessageBox.ButtonRole.NoRole)
            
            msg_box.setDefaultButton(no_btn)
            msg_box.exec()
            
            if msg_box.clickedButton() == yes_btn:
                if path in self.recent_projects:
                    self.recent_projects.remove(path)
                    self.save_settings()
                    self.update_recent_projects_menu()
            return

        if not self.check_unsaved_changes():
            return

        self._load_from_path(path)

    def clear_recent_projects(self):
        self.recent_projects = []
        self.save_settings()
        self.update_recent_projects_menu()
