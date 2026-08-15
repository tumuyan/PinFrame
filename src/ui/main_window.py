
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QDockWidget, QToolBar, QFileDialog, QSpinBox,
                             QLabel, QPushButton, QInputDialog, QTreeWidgetItem, QMenu, QStyle,
                             QMessageBox, QDialog)
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
from ui.canvas_border_settings import CanvasBorderSettingsDialog
from ui.utils.icon_generator import IconGenerator
from i18n.manager import i18n
from utils.debug_config import import_debug
from core.history import HistoryManager

class MainWindow(QMainWindow):
    def __init__(self):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)
        super().__init__()
        
        # State
        self.current_project_path = None
        self.is_dirty = False
        # 操作历史（撤销/重做）
        self.history = HistoryManager(max_entries=200)
        self._history_suspend = False
        # 连续操作（拖拽/连发/连续调节）合并窗口
        self._history_merging = False
        self._history_merge_timer = QTimer(self)
        self._history_merge_timer.setSingleShot(True)
        self._history_merge_timer.setInterval(600)
        self._history_merge_timer.timeout.connect(self._close_history_merge_window)
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
        self.resize(1440, 900)
        # 设置窗口为最大化状态
        # self.setWindowState(Qt.WindowState.WindowMaximized)
        
        # Data
        self.project = ProjectData()
        
        # Central Widget (Canvas)
        self.canvas = CanvasWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.transform_changed.connect(self.on_canvas_transform_changed)
        self.canvas.scale_change_requested.connect(self.on_canvas_scale_requested)
        self.canvas.drag_started.connect(lambda: self._open_history_merge_window(i18n.t("hist_edit_move")))

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
        self.timeline.duplicate_dialog_requested.connect(self.duplicate_frames_dialog)
        self.timeline.remove_requested.connect(self.remove_frame)
        self.timeline.disabled_state_changed.connect(self.on_frame_disabled_state_changed)
        self.timeline.enable_requested.connect(self.toggle_enable_disable)
        self.timeline.reverse_order_requested.connect(self.reverse_selected_frames)
        self.timeline.integerize_offset_requested.connect(self.integerize_selection_offset)
        self.timeline.smooth_params_requested.connect(self.smooth_params_dialog)
        self.timeline.set_reference_requested.connect(self.set_reference_frame_from_selection)
        self.timeline.clear_reference_requested.connect(self.clear_reference_frame)
        self.timeline.thumbnail_size_changed.connect(self.on_grid_thumbnail_size_changed)
        self.timeline_dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
        
        # Dock Widget (Property Panel)
        self.property_dock = QDockWidget(i18n.t("dock_properties"), self)
        self.property_dock.setObjectName("PropertyDock")
        self.property_panel = PropertyPanel()
        self.property_panel.frame_data_changed.connect(self.on_property_changed)
        self.property_panel.repeat_requested.connect(self.repeat_last_move)
        self.property_panel.rev_repeat_requested.connect(self.reverse_repeat_last_move)
        # edit_started 携带具体操作类型，映射为细化的历史记录描述
        self._edit_type_labels = {
            "move": "hist_edit_move",
            "rotate": "hist_edit_rotate",
            "scale": "hist_edit_scale",
            "mirror_h": "hist_edit_mirror_h",
            "mirror_v": "hist_edit_mirror_v",
            "target_size": "hist_edit_target_size",
            "aspect": "hist_edit_aspect",
            "fit_width": "hist_edit_fit_width",
            "fit_height": "hist_edit_fit_height",
            "align": "hist_edit_align",
        }
        self.property_panel.edit_started.connect(self._on_property_edit_started)
        
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

        # Canvas Border Settings
        border_inner_color_str = self.settings.value("canvas_border_inner_color", "255,255,255")
        try:
            self.canvas_border_inner_color = tuple(map(int, border_inner_color_str.split(',')))
        except:
            self.canvas_border_inner_color = (255, 255, 255)
        self.canvas_border_inner_width = self.settings.value("canvas_border_inner_width", 2, type=int)
        
        border_outer_color_str = self.settings.value("canvas_border_outer_color", "0,0,0")
        try:
            self.canvas_border_outer_color = tuple(map(int, border_outer_color_str.split(',')))
        except:
            self.canvas_border_outer_color = (0, 0, 0)
        self.canvas_border_outer_width = self.settings.value("canvas_border_outer_width", 1, type=int)

        # Load timeline view settings (before creating actions/menus)
        self.timeline_view_mode = self.settings.value("timeline_view_mode", "list")
        self.grid_thumb_width = self.settings.value("grid_thumb_width", 120, type=int)
        self.grid_thumb_height = self.settings.value("grid_thumb_height", 120, type=int)
        self.grid_show_multiline = self.settings.value("grid_show_multiline", False, type=bool)
        self.grid_multiline_label_height = self.settings.value("grid_multiline_label_height", 36, type=int)
        self.grid_background_mode = self.settings.value("grid_background_mode", "checkerboard")

        # Playback (must be initialized before create_menus to avoid AttributeError)
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        self.is_playing = False
        self.playback_reverse = False
        self.playlist = []
        self.play_index = 0

        # Onion Skin & Reference State (must be initialized before create_actions)
        self.onion_enabled = False
        self.onion_prev = self.settings.value("onion_prev", 1, type=int)
        self.onion_next = self.settings.value("onion_next", 0, type=int)
        self.onion_opacity_step = self.settings.value("onion_opacity_step", 0.2, type=float)
        self.onion_ref_exclusive = self.settings.value("onion_exclusive", False, type=bool)
        self.onion_suppressed = False

        # Reference Frame Settings (must be initialized before create_actions)
        self.reference_frame = None
        self.ref_opacity = self.settings.value("ref_opacity", 0.5, type=float)
        self.ref_layer = self.settings.value("ref_layer", "top", type=str)
        self.ref_show_on_playback = self.settings.value("ref_show_on_playback", False, type=bool)

        # Apply initial reference settings to canvas
        self.canvas.ref_opacity = self.ref_opacity
        self.canvas.ref_layer = self.ref_layer
        self.canvas.ref_show_on_playback = self.ref_show_on_playback
        
        # Apply initial border settings to canvas
        inner_color = QColor(*self.canvas_border_inner_color)
        outer_color = QColor(*self.canvas_border_outer_color)
        self.canvas.set_border_settings(
            inner_color,
            self.canvas_border_inner_width,
            outer_color,
            self.canvas_border_outer_width
        )

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

    def _set_dirty_state(self, dirty: bool):
        """按指定值设置未保存状态并刷新窗口标题。"""
        if bool(self.is_dirty) != bool(dirty):
            self.is_dirty = bool(dirty)
            self.update_title()

    # ------------------------------------------------------------------
    # 操作历史（撤销 / 重做 / 历史跳转）
    # ------------------------------------------------------------------

    @staticmethod
    def _clone_frame(f) -> FrameData:
        """深拷贝单帧数据（用于快照与还原，避免共享可变对象污染历史）。"""
        return FrameData(
            file_path=f.file_path,
            scale=f.scale,
            position=tuple(f.position),
            rotation=f.rotation,
            aspect_ratio=f.aspect_ratio,
            target_resolution=tuple(f.target_resolution) if f.target_resolution else None,
            is_disabled=f.is_disabled,
            crop_rect=tuple(f.crop_rect) if f.crop_rect else None,
        )

    def _capture_snapshot(self):
        """抓取当前项目状态的深拷贝快照（帧数据与画布设置）。"""
        live_frames = self.timeline.get_all_frames()
        # 记录参考帧在 frames 中的下标，供撤销/重做时按下标精确定位恢复
        ref_index = None
        if self.reference_frame is not None:
            for i, f in enumerate(live_frames):
                if f is self.reference_frame:
                    ref_index = i
                    break
        selected_indices = self.timeline.get_selected_indices_from_current_view()
        return {
            "fps": self.project.fps,
            "width": self.project.width,
            "height": self.project.height,
            "background_color": self.project.background_color,
            "is_dirty": self.is_dirty,
            "reference_frame": self.reference_frame.file_path if self.reference_frame else None,
            "reference_frame_index": ref_index,
            "selected_indices": list(selected_indices),
            "frames": [self._clone_frame(f) for f in live_frames],
        }

    def _apply_snapshot(self, snap):
        """将快照应用到当前项目（帧数据与画布设置），并刷新所有视图。"""
        # 应用快照期间挂起历史记录，避免 UI 刷新触发的信号污染历史
        self._history_suspend = True
        try:
            self._apply_snapshot_inner(snap)
        finally:
            self._history_suspend = False
            self._history_merge_timer.stop()
            self._history_merging = False

    def _apply_snapshot_inner(self, snap):
        """_apply_snapshot 的实际逻辑（供挂起/恢复包装）。"""
        self.project.fps = snap.get("fps", self.project.fps)
        self.project.width = snap.get("width", self.project.width)
        self.project.height = snap.get("height", self.project.height)
        self.project.background_color = snap.get("background_color", self.project.background_color)

        self.fps_spin.setValue(self.project.fps)
        self.canvas.set_project_settings(self.project.width, self.project.height)
        self.property_panel.set_project_info(self.project.width, self.project.height)

        frames = snap.get("frames", [])
        self.timeline.clear()
        # 克隆快照中的帧对象，避免后续编辑污染历史快照
        for frame in frames:
            new_frame = self._clone_frame(frame)
            # 尺寸仅供视图展示；add_frame 走模型插入，视图会在 _on_frames_inserted 中
            # 自行读取所需尺寸，这里传入的 orig_w/orig_h 会被丢弃，故不再做 QImageReader 读取。
            w, h = (new_frame.crop_rect[2], new_frame.crop_rect[3]) if new_frame.crop_rect else (0, 0)
            self.timeline.add_frame(os.path.basename(new_frame.file_path), new_frame, w, h)

        # 帧插入时缩略图已按 file_path/crop_rect 生成并写入缓存；此处仅刷新（复用缓存），
        # 不再 _clear_thumbnail_cache()，避免对无 crop_rect 的帧从磁盘重复加载原图。
        self.timeline.grid_view.refresh_all_items()

        # 参考帧与选中项恢复
        live_frames = self.timeline.get_all_frames()

        raw_selected_indices = snap.get("selected_indices", [])
        target_indices = [i for i in raw_selected_indices if 0 <= i < len(live_frames)]
        if not target_indices and live_frames:
            target_indices = [0]

        if target_indices:
            self.timeline.model.set_selection(target_indices)
            selected_frames = [live_frames[i] for i in target_indices]
            self.canvas.set_selected_frames(selected_frames)
            self.property_panel.set_selection(selected_frames)
            self.timeline._apply_selection_to_view(target_indices)
        else:
            self.timeline.model.clear_selection()
            self.canvas.set_selected_frames([])
            self.property_panel.set_selection([])

        ref_path = snap.get("reference_frame")
        # 优先按快照中记录的参考帧下标精确定位，避免同路径多帧被错误映射到第一个对象；
        # 下标失效时再按路径兜底匹配。
        new_ref = None
        if ref_path:
            ref_index = snap.get("reference_frame_index")
            if ref_index is not None and 0 <= ref_index < len(live_frames) \
                    and live_frames[ref_index].file_path == ref_path:
                new_ref = live_frames[ref_index]
            else:
                new_ref = next((f for f in live_frames if f.file_path == ref_path), None)
        if new_ref is not None:
            self.reference_frame = new_ref
            self.canvas.set_reference_frame(self.reference_frame)
            self.timeline.set_visual_reference_frame(self.reference_frame)
            if hasattr(self, 'set_ref_action'):
                self.set_ref_action.setText(i18n.t("action_cancel_reference"))
        else:
            self.reference_frame = None
            self.canvas.set_reference_frame(None)
            self.timeline.set_visual_reference_frame(None)
            if hasattr(self, 'set_ref_action'):
                self.set_ref_action.setText(i18n.t("action_set_reference"))

        # 恢复快照中记录的未保存状态，避免撤销回已保存状态后仍被标记为有未保存修改
        self._set_dirty_state(bool(snap.get("is_dirty", True)))

        self.canvas.update()
        self.update_onion_state()
        self.update_menu_state()

    # -- 连续操作合并窗口 ------------------------------------------------
    # 拖拽、连发移动、连续调节数值等会高频触发，开启合并窗口后，
    # 同一窗口内只保留一条历史记录（始终以窗口打开时的状态为 before），
    # 在最后一次事件后约 600ms 无新事件时由定时器自动提交。
    def _on_property_edit_started(self, edit_type):
        """属性面板开始一次编辑：把 edit_type 映射为细化的历史描述。"""
        label_key = self._edit_type_labels.get(edit_type, "hist_edit")
        self._open_history_merge_window(i18n.t(label_key))

    def _open_history_merge_window(self, label):
        """进入（或刷新）连续操作合并窗口，label 为操作名称。

        已处于合并窗口时：
        - 若操作类型与当前一致，仅刷新计时器（合并为一条历史，避免刷屏）；
        - 若操作类型发生变化，先提交当前记录，再以新类型开启新窗口，
          避免“移动+旋转”等不同操作被错误地合并为一条历史。
        """
        if self._history_suspend:
            return
        if self._history_merging:
            cur = getattr(self, '_history_merge_label', None)
            if cur != label:
                self._close_history_merge_window()
            else:
                self._history_merge_timer.start()
                return
        self._history_merging = True
        self._history_merge_before = self._capture_snapshot()
        self._history_merge_label = label
        self._history_merge_timer.start()

    def _close_history_merge_window(self):
        """立即关闭合并窗口并提交一条历史记录（由定时器或外部调用）。"""
        if not self._history_merging:
            return
        self._history_merge_timer.stop()
        self._history_merging = False
        label = getattr(self, '_history_merge_label', None)
        before = self._history_merge_before
        self._history_merge_before = None
        after = self._capture_snapshot()
        if label is None or before == after:
            return
        self.history.push(label, before, after)
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_recorded").format(label=label), 2000)

    def _flush_pending_history(self):
        """提交未完成的合并窗口（在其它非连续操作前调用，避免污染）。"""
        if self._history_merging:
            self._close_history_merge_window()

    def record_history(self, label, before=None, after=None):
        """记录一次完整的历史操作。before/after 缺省时自动抓取当前状态。"""
        if self._history_suspend:
            return
        self._flush_pending_history()
        if before is None:
            before = self._capture_snapshot()
        if after is None:
            after = self._capture_snapshot()
        # 跳过无实际变化的记录
        if before == after:
            return
        self.history.push(label, before, after)
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_recorded").format(label=label), 2000)

    def undo_history(self):
        self._flush_pending_history()
        result = self.history.undo()
        if result is None:
            self.statusBar().showMessage(i18n.t("msg_undo_empty"), 2000)
            return
        label, snapshot = result
        self._apply_snapshot(snapshot)
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_undone").format(label=label), 3000)

    def redo_history(self):
        self._flush_pending_history()
        result = self.history.redo()
        if result is None:
            self.statusBar().showMessage(i18n.t("msg_redo_empty"), 2000)
            return
        label, snapshot = result
        self._apply_snapshot(snapshot)
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_redone").format(label=label), 3000)

    def jump_history_to(self, index):
        self._flush_pending_history()
        result = self.history.jump_to(index)
        if result is None:
            return
        label, snapshot = result
        self._apply_snapshot(snapshot)
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_jumped").format(label=label), 3000)

    def clear_history(self):
        self._flush_pending_history()
        self.history.clear()
        self._refresh_history_menu()
        self.statusBar().showMessage(i18n.t("msg_history_cleared"), 2000)

    def _refresh_history_menu(self):
        """增量刷新历史菜单：仅增删/更新变化的历史记录子项，避免每次全量重建。

        撤销/重做已在编辑菜单中提供，这里只展示历史记录列表与「清空历史」。
        """
        if not hasattr(self, 'history_menu'):
            return

        self.undo_action.setEnabled(self.history.can_undo)
        self.redo_action.setEnabled(self.history.can_redo)

        # 首次调用时初始化持久化的菜单子项（条目 QAction、分隔符、空态提示、清空按钮）
        if not hasattr(self, '_history_entry_actions'):
            self._history_entry_actions = []
            self._history_clear_action = None
            self._history_separator_action = None
            self._history_empty_action = None

        entries = self.history.entries
        count = len(entries)
        index = self.history.index

        # ---- 1. 同步历史条目数量：移除多余项 ----
        while len(self._history_entry_actions) > count:
            action = self._history_entry_actions.pop()
            self.history_menu.removeAction(action)
            action.deleteLater()

        # ---- 2. 同步空态提示（空历史时显示） ----
        if count == 0:
            # 空态：仅保留「暂无历史」提示，隐藏底部分隔符与清空按钮
            if self._history_empty_action is None:
                self._history_empty_action = QAction(i18n.t("msg_history_empty"), self)
                self._history_empty_action.setEnabled(False)
                self.history_menu.addAction(self._history_empty_action)
            self._remove_history_menu_footer()
            return

        if self._history_empty_action is not None:
            self.history_menu.removeAction(self._history_empty_action)
            self._history_empty_action.deleteLater()
            self._history_empty_action = None

        # ---- 3. 增量更新/追加历史条目子项（从旧到新，最近的位于底部） ----
        for i, entry in enumerate(entries):
            if i < len(self._history_entry_actions):
                # 已有子项：仅更新文本与勾选/提示，不重建 QAction
                action = self._history_entry_actions[i]
                action.setText(entry.label)
            else:
                # 新增（纯追加）子项：新建并插入到分隔符/清空按钮之前，保持顺序
                action = QAction(entry.label, self)
                action.setCheckable(True)
                action.triggered.connect(lambda checked, idx=i: self.jump_history_to(idx))
                # 首次追加前先确保分隔符与「清空历史」已就位，以便插入其前
                self._ensure_history_menu_footer()
                if self._history_separator_action is not None:
                    self.history_menu.insertAction(self._history_separator_action, action)
                else:
                    self.history_menu.addAction(action)
                self._history_entry_actions.append(action)

            action.setChecked(i == index)
            action.setToolTip(i18n.t("msg_history_tooltip_done") if i <= index
                              else i18n.t("msg_history_tooltip_redoable"))

        # ---- 4. 确保分隔符与「清空历史」位于菜单底部 ----
        self._ensure_history_menu_footer()
        self._history_clear_action.setEnabled(count > 0)

    def _ensure_history_menu_footer(self):
        """确保历史菜单底部有分隔符与「清空历史」子项（幂等）。"""
        if self._history_clear_action is not None:
            return
        self._history_separator_action = self.history_menu.addSeparator()
        self._history_clear_action = QAction(i18n.t("action_history_clear"), self)
        self._history_clear_action.triggered.connect(self.clear_history)
        self.history_menu.addAction(self._history_clear_action)

    def _remove_history_menu_footer(self):
        """移除历史菜单底部的分隔符与「清空历史」子项（空态时调用，幂等）。"""
        if self._history_clear_action is None:
            return
        if self._history_separator_action is not None:
            self.history_menu.removeAction(self._history_separator_action)
            self._history_separator_action.deleteLater()
            self._history_separator_action = None
        self.history_menu.removeAction(self._history_clear_action)
        self._history_clear_action.deleteLater()
        self._history_clear_action = None

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

        self.new_action = QAction(i18n.t("action_new"), self)
        self.new_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.new_action.triggered.connect(self.new_project)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)

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

        self.reload_images_action = QAction(i18n.t("action_reload_images"), self)
        self.reload_images_action.triggered.connect(self.reload_image_resources)

        self.exit_action = QAction(i18n.t("action_exit"), self)
        self.exit_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        self.exit_action.triggered.connect(self.close)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)

        self.export_action = QAction(i18n.t("action_export"), self)
        self.export_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.export_action.triggered.connect(self.export_sequence)

        self.export_sheet_action = QAction(i18n.t("action_export_sheet"), self)
        self.export_sheet_action.triggered.connect(self.export_sprite_sheet)

        # Set labels for file/image related actions
        self.refresh_file_action_labels()

        # Edit Actions
        # 撤销 / 重做
        self.undo_action = QAction(i18n.t("action_undo"), self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo_history)
        self.undo_action.setEnabled(False)

        self.redo_action = QAction(i18n.t("action_redo"), self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo_history)
        self.redo_action.setEnabled(False)

        self.copy_props_action = QAction(i18n.t("action_copy_props"), self)
        self.copy_props_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_props_action.triggered.connect(self.copy_frame_properties)
        
        self.paste_props_action = QAction(i18n.t("action_paste_props"), self)
        self.paste_props_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_props_action.triggered.connect(self.paste_frame_properties)
        
        self.dup_frame_action = QAction(i18n.t("action_dup_frame"), self)
        self.dup_frame_action.setShortcut("Ctrl+D")
        self.dup_frame_action.triggered.connect(self.duplicate_frame)

        self.dup_frames_dialog_action = QAction(i18n.t("action_dup_frames_dialog"), self)
        self.dup_frames_dialog_action.setShortcut("Ctrl+Shift+D")
        self.dup_frames_dialog_action.triggered.connect(self.duplicate_frames_dialog)

        self.rem_frame_action = QAction(i18n.t("action_rem_frame"), self)
        self.rem_frame_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.rem_frame_action.triggered.connect(self.remove_frame)

        self.reverse_order_action = QAction(i18n.t("action_reverse_order"), self)
        self.reverse_order_action.triggered.connect(self.reverse_selected_frames)

        # Set labels for edit related actions
        self.refresh_edit_action_labels()

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
        
        self.canvas_settings_action = QAction(i18n.t("action_canvas_settings"), self)
        self.canvas_settings_action.triggered.connect(self.configure_canvas_border_settings)
        
        # Toolbar Onion Action (Separate for dynamic text)
        self.onion_toolbar_action = QAction(i18n.t("toolbar_onion_off"), self)
        onion_icon = QIcon()
        onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(150, 150, 150)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        onion_icon.addPixmap(IconGenerator.onion_skin_icon(QColor(0, 122, 204)).pixmap(32, 32), QIcon.Mode.Normal, QIcon.State.On)
        self.onion_toolbar_action.setIcon(onion_icon)
        self.onion_toolbar_action.setCheckable(True)
        self.onion_toolbar_action.triggered.connect(self.toggle_onion_skin)

        # Set labels for onion skin actions
        self.refresh_onion_action_labels()
        
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

        # Set labels for view related actions (after zoom/scale actions are created)
        self.refresh_view_action_labels()

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

        # Set labels for reference actions
        self.refresh_reference_action_labels()

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

        # Set labels for theme and playback actions
        self.refresh_theme_playback_action_labels()
        
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

        # Set labels for layout actions
        self.refresh_layout_action_labels()

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

        # Set labels for repeat actions
        self.refresh_repeat_action_labels()

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

        # Set labels for wheel mode actions
        self.refresh_wheel_mode_action_labels()

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

        # Set labels for rasterization actions
        self.refresh_rasterization_action_labels()

        # About Actions
        self.repo_action = QAction(i18n.t("action_repo"), self)
        self.repo_action.triggered.connect(self.open_repo_url)

        self.debug_control_action = QAction(i18n.t("action_debug_control"), self)
        self.debug_control_action.triggered.connect(self.show_debug_control_dialog)

        version_str = self.get_git_version()
        self.version_action = QAction(i18n.t("action_version").format(version=version_str), self)
        self.version_action.setEnabled(False)

        compile_date = self.get_build_date()
        self.build_date_action = QAction(i18n.t("action_build_date").format(date=compile_date), self)
        self.build_date_action.setEnabled(False)

        # Timeline View Actions
        self.timeline_view_group = QActionGroup(self)

        self.timeline_list_action = QAction(i18n.t("action_timeline_list"), self)
        self.timeline_list_action.setCheckable(True)
        self.timeline_list_action.setChecked(True)
        self.timeline_list_action.triggered.connect(lambda: self.set_timeline_view("list"))
        self.timeline_view_group.addAction(self.timeline_list_action)

        self.timeline_grid_action = QAction(i18n.t("action_timeline_grid"), self)
        self.timeline_grid_action.setCheckable(True)
        self.timeline_grid_action.triggered.connect(lambda: self.set_timeline_view("grid"))
        self.timeline_view_group.addAction(self.timeline_grid_action)

        self.timeline_grid_settings_action = QAction(i18n.t("action_timeline_grid_settings"), self)
        self.timeline_grid_settings_action.triggered.connect(self.open_timeline_grid_settings)

        # Set labels for timeline view actions
        self.refresh_timeline_view_action_labels()

        # Set labels for about actions
        self.refresh_about_action_labels()

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
        file_menu.addAction(self.new_action)
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
        file_menu.addAction(self.reload_images_action)

        file_menu.addSeparator()
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.export_sheet_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        # Image Menu
        image_menu = menubar.addMenu(i18n.t("menu_image"))
        image_menu.addAction(self.import_action)
        image_menu.addAction(self.import_slice_action)
        image_menu.addAction(self.import_gif_action)
        
        # Onion & Reference Submenu
        # View Menu

        
        # Edit Menu
        edit_menu = menubar.addMenu(i18n.t("menu_edit"))
        # 撤销 / 重做
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.copy_props_action)
        edit_menu.addAction(self.paste_props_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.dup_frame_action)
        edit_menu.addAction(self.dup_frames_dialog_action)
        edit_menu.addAction(self.rem_frame_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.reverse_order_action)
        edit_menu.addSeparator()
        
        repeat_menu = edit_menu.addMenu(i18n.t("menu_repeat_delay"))
        for ms in [0, 100, 250, 500, 1000]:
            repeat_menu.addAction(self.repeat_actions[ms])
        edit_menu.addSeparator()

        # 历史菜单组（撤销 / 重做 + 历史记录列表）
        self.history_menu = edit_menu.addMenu(i18n.t("menu_history"))
        self._refresh_history_menu()
        
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
        
        # Canvas Menu
        canvas_menu = menubar.addMenu(i18n.t("menu_canvas"))
        canvas_menu.addAction(self.zoom_in_action)
        canvas_menu.addAction(self.zoom_out_action)
        canvas_menu.addAction(self.zoom_fit_action)
        canvas_menu.addAction(self.reset_view_action)
        canvas_menu.addSeparator()
        
        # Wheel Mode Submenu
        wheel_menu = canvas_menu.addMenu(i18n.t("action_toggle_wheel_mode"))
        wheel_menu.addAction(self.action_wheel_zoom_view)
        wheel_menu.addAction(self.action_wheel_scale_image)
        canvas_menu.addSeparator()
        
        self.background_menu = canvas_menu.addMenu(i18n.t("menu_background"))
        for action in self.bg_actions.values():
            self.background_menu.addAction(action)
        canvas_menu.addSeparator()
        
        canvas_menu.addAction(self.canvas_settings_action)
        
        # View Menu
        view_menu = menubar.addMenu(i18n.t("menu_view"))
        
        # Onion Skin (Flattened)
        view_menu.addAction(self.onion_action)
        view_menu.addAction(self.onion_settings_action)
        view_menu.addSeparator()
        
        # Reference Frame (Flattened)
        view_menu.addAction(self.set_ref_action)
        view_menu.addAction(self.ref_settings_action)
        view_menu.addAction(self.clear_ref_action)
        view_menu.addSeparator()
        
        theme_menu = view_menu.addMenu(i18n.t("menu_theme"))
        theme_menu.addAction(self.theme_dark_action)
        theme_menu.addAction(self.theme_light_action)
        
        lang_menu = view_menu.addMenu(i18n.t("menu_lang"))
        lang_menu.addAction(self.lang_zh_action)
        lang_menu.addAction(self.lang_en_action)
        
        # Timeline View Menu
        timeline_view_menu = view_menu.addMenu(i18n.t("menu_timeline_view"))
        timeline_view_menu.addAction(self.timeline_list_action)
        timeline_view_menu.addAction(self.timeline_grid_action)
        timeline_view_menu.addSeparator()
        timeline_view_menu.addAction(self.timeline_grid_settings_action)

        # About Menu
        about_menu = menubar.addMenu(i18n.t("menu_about"))
        about_menu.addAction(self.repo_action)
        about_menu.addAction(self.version_action)
        about_menu.addAction(self.build_date_action)
        about_menu.addSeparator()
        about_menu.addAction(self.debug_control_action)

        # Apply saved timeline view settings
        self.timeline.update_grid_settings(
            self.grid_thumb_width,
            self.grid_thumb_height,
            self.grid_show_multiline,
            self.grid_multiline_label_height,
            self.grid_background_mode
        )
        
        if self.timeline_view_mode == "grid":
            self.timeline_grid_action.setChecked(True)
            self.timeline.set_view_mode("grid")
        else:
            self.timeline_list_action.setChecked(True)

    def open_repo_url(self):
        try:
            parsed_url = QUrl(BUILD_REPO_URL)
            QDesktopServices.openUrl(parsed_url)
        except Exception:
            # Fallback
            QDesktopServices.openUrl(QUrl("https://github.com/tumuyan/PinFrame"))

    def show_debug_control_dialog(self):
        """Show dialog to control debug output"""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QScrollArea,
                                      QWidget, QDialogButtonBox, QCheckBox)
        from PyQt6.QtCore import Qt
        from utils.debug_config import DebugConfig

        config = DebugConfig()

        dialog = QDialog(self)
        dialog.setWindowTitle(i18n.t("dlg_debug_control"))
        dialog.setMinimumWidth(400)
        dialog.setMinimumHeight(350)

        layout = QVBoxLayout(dialog)

        # Description
        desc_label = QLabel(i18n.t("debug_control_desc"))
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Master switch
        master_checkbox = QCheckBox(i18n.t("debug_master_switch", "Enable Debug Logging"))
        master_checkbox.setChecked(config.is_master_enabled())
        master_checkbox.setStyleSheet("font-weight: bold; padding: 5px 0;")
        layout.addWidget(master_checkbox)

        # Scroll area for checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Create checkboxes for each category
        checkboxes = {}
        categories = config.get_all_categories()
        for cat_key, cat_name in categories.items():
            cb = QCheckBox(cat_name)
            cb.setChecked(cat_key in config.get_enabled_categories())
            checkboxes[cat_key] = cb
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Function to update category checkboxes state based on master switch
        def update_category_states():
            master_on = master_checkbox.isChecked()
            for cb in checkboxes.values():
                cb.setEnabled(master_on)
                if master_on:
                    cb.setStyleSheet("")
                else:
                    cb.setStyleSheet("color: gray;")

        # Connect master checkbox
        master_checkbox.toggled.connect(update_category_states)
        # Initial state
        update_category_states()

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update config
            config.set_master_enabled(master_checkbox.isChecked())
            enabled = set()
            for cat_key, cb in checkboxes.items():
                if cb.isChecked():
                    enabled.add(cat_key)
            config.set_enabled_categories(enabled)
            self.statusBar().showMessage(i18n.t("msg_debug_settings_saved"), 2000)

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
        # 撤销 / 重做
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
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
                self._flush_pending_history()
                before = self._capture_snapshot()
                
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
                self.record_history(i18n.t("hist_canvas_resize"), before=before)
                
                # Refresh UI
                self.canvas.update()
                self.property_panel.update_ui_from_selection()

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, i18n.t("dlg_import_title"), "", i18n.t("dlg_filter_images"))
        if not files:
            return
        import_debug(f"[Import] Importing images: {len(files)} files selected")
        self.add_files(files)

    def add_files(self, files, index=-1):
        if not files:
            return
        
        import_debug(f"[Import] Adding files: count={len(files)}, index={index}")
            
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
            import_debug("[Import] No valid files to add")
            return

        import_debug(f"[Import] Successfully added {added_count} files")

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Insert logic - now uses TimelineModel
        # TimelineWidget handles both data and view updates
        if index == -1 or index >= self.timeline.get_frame_count():
            # Append all frames
            for name, data, w, h in new_items:
                self.timeline.add_frame(name, data, w, h)
        else:
            # Insert at specific index - insert in reverse order to maintain correct positions
            for i in range(len(new_items) - 1, -1, -1):
                name, data, w, h = new_items[i]
                self.timeline.add_frame(name, data, w, h)  # Model handles insertion at index

        self.mark_dirty()
        self.timeline.refresh_current_items()
        self.record_history(i18n.t("hist_add_frames"), before=before)

    def copy_frame_properties(self):
        # Use unified interface to get selected frames
        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames:
            return

        # Copy from the first selected frame (Primary)
        frame_data = selected_frames[0]
        if frame_data:
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

        # Use unified interface to get selected frames and indices
        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames:
            return

        selected_indices = self.timeline.get_selected_indices_from_current_view()

        self._flush_pending_history()
        before = self._capture_snapshot()
        count = 0
        for frame_data in selected_frames:
            frame_data.scale = self.clipboard_frame_properties["scale"]
            frame_data.position = self.clipboard_frame_properties["position"]
            frame_data.target_resolution = self.clipboard_frame_properties["target_resolution"]
            count += 1

        # Update view using indices
        for idx in selected_indices:
            self.timeline.update_frame_data(idx)

        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(i18n.t("msg_props_pasted").format(count=count), 3000)
        self.record_history(i18n.t("hist_paste_props"), before=before)

    def duplicate_frame(self):
        # Use unified interface to get selected indices
        indices = self.timeline.get_selected_indices_from_current_view()
        if not indices:
            return

        indices.sort()  # Sort in ascending order

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Find the insertion point (BEFORE the first selected item)
        insert_pos = indices[0]

        # Collect all duplicates first
        duplicates = []
        for idx in indices:
            # Get original data from timeline model
            orig_data = self.timeline.get_frame_at(idx)

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

            duplicates.append(new_data)

        # Insert all duplicates at once before the selection
        for i, new_data in enumerate(duplicates):
            filename = os.path.basename(new_data.file_path)
            # Use model directly to insert at specific position
            self.timeline.model.add_frame(new_data, insert_pos + i)

        # Calculate new indices for original frames (shifted right by number of duplicates)
        original_indices_after_dup = [idx + len(duplicates) for idx in indices]

        # Restore selection to original frames
        self.timeline.model.set_selection(original_indices_after_dup)

        self.mark_dirty()
        self.timeline.refresh_current_items()
        self.statusBar().showMessage(i18n.t("msg_frames_duplicated").format(count=len(duplicates)), 3000)
        self.record_history(i18n.t("hist_duplicate_frame"), before=before)

    def duplicate_frames_dialog(self):
        """Show dialog for advanced duplication with count and mode options"""
        from ui.duplicate_dialog import DuplicateFramesDialog

        # Use unified interface to get selected indices
        indices = self.timeline.get_selected_indices_from_current_view()
        if not indices:
            return

        indices.sort()  # Sort in ascending order

        # Show dialog
        dialog = DuplicateFramesDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.get_options()
        count = options['count']
        mode = options['mode']

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Find the insertion point (BEFORE the first selected item)
        insert_pos = indices[0]

        # Collect all duplicates based on mode
        frames_to_insert = []

        if mode == "ABAB":
            # ABAB mode: repeat the entire selected sequence
            # Example: selected A,B, count=3 -> A,B,A,B,A,B,A,B
            for repeat in range(count):
                for idx in indices:
                    # Get original data from timeline model
                    orig_data = self.timeline.get_frame_at(idx)

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

                    frames_to_insert.append(new_data)
        else:  # AABB mode
            # AABB mode: repeat each selected frame individually
            # Example: selected A,B, count=3 -> A,A,A,B,B,B
            for idx in indices:
                # Get original data from timeline model
                orig_data = self.timeline.get_frame_at(idx)

                # Repeat this frame 'count' times
                for repeat in range(count):
                    new_data = FrameData(
                        file_path=orig_data.file_path,
                        scale=orig_data.scale,
                        position=orig_data.position,
                        rotation=orig_data.rotation,
                        target_resolution=orig_data.target_resolution,
                        is_disabled=orig_data.is_disabled,
                        crop_rect=orig_data.crop_rect
                    )

                    frames_to_insert.append(new_data)

        # Insert all frames at once before the selection
        for i, frame_data in enumerate(frames_to_insert):
            filename = os.path.basename(frame_data.file_path)
            # Use model directly to insert at specific position
            self.timeline.model.add_frame(frame_data, insert_pos + i)

        # Calculate new indices for original frames (shifted right by number of inserted frames)
        original_indices_after_dup = [idx + len(frames_to_insert) for idx in indices]

        # Restore selection to original frames
        self.timeline.model.set_selection(original_indices_after_dup)

        self.mark_dirty()
        self.timeline.refresh_current_items()
        self.statusBar().showMessage(i18n.t("msg_frames_duplicated").format(count=len(frames_to_insert)), 3000)
        self.record_history(i18n.t("hist_duplicate_frame"), before=before)

    def remove_frame(self):
        # Use unified interface to get selected indices
        indices = self.timeline.get_selected_indices_from_current_view()
        if not indices:
            return

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Remove through timeline model
        self.timeline.remove_frames_at(indices)

        # 若被删帧恰为参考帧，清除参考帧
        if self.reference_frame is not None:
            # 从 before 快照中判断（此时帧已删除，indices 已失效，不能用模型取值）
            removed_paths = {before["frames"][i].file_path for i in indices if 0 <= i < len(before["frames"])}
            if self.reference_frame.file_path in removed_paths:
                self.reference_frame = None
                self.canvas.set_reference_frame(None)
                self.timeline.set_visual_reference_frame(None)
                self.set_ref_action.setText(i18n.t("action_set_reference"))

        self.mark_dirty()
        self.timeline.refresh_current_items() # Update numbers after removal
        self.canvas.set_selected_frames([])
        self.property_panel.set_selection([]) # Clear selection in property panel
        self.statusBar().showMessage(i18n.t("msg_frames_removed").format(count=len(indices)), 3000)
        self.record_history(i18n.t("hist_remove_frame"), before=before)

    def on_frame_disabled_state_changed(self, frame_data, is_disabled):
        # 注意：Timeline 已在发出信号前修改了 frame_data.is_disabled，
        # 因此这里先抓取"修改后"快照，再把该帧的状态回退以重建"修改前"快照。
        self._flush_pending_history()
        after = self._capture_snapshot()
        # 重建 before：仅将该帧的 is_disabled 反转回旧值
        before = dict(after)
        before["frames"] = []
        for f in self.timeline.get_all_frames():
            fb = FrameData(
                file_path=f.file_path,
                scale=f.scale,
                position=tuple(f.position),
                rotation=f.rotation,
                aspect_ratio=f.aspect_ratio,
                target_resolution=tuple(f.target_resolution) if f.target_resolution else None,
                is_disabled=f.is_disabled,
                crop_rect=tuple(f.crop_rect) if f.crop_rect else None,
            )
            if f is frame_data:
                fb.is_disabled = not is_disabled
            before["frames"].append(fb)
        self.mark_dirty()
        
        # If this frame is currently displayed in preview/canvas, update it.
        self.canvas.update() 
        
        # Update playlist if playing so that skip logic applies immediately
        if self.is_playing:
            self.update_playlist()
        self.record_history(i18n.t("hist_toggle_disable"), before=before, after=after)

    def toggle_enable_disable(self, enable):
        selected = self.timeline.selectedItems()
        if not selected:
            return

        is_disabled = not enable
        changed_frames = []
        for item in selected:
            # Use unified interface to extract frame data
            frame_data = self.timeline.extract_frame_data_from_item(item)
            if frame_data and frame_data.is_disabled != is_disabled:
                changed_frames.append((frame_data, frame_data.is_disabled))
                frame_data.is_disabled = is_disabled

                # Update UI checkbox in list view
                if hasattr(item, 'setCheckState') and hasattr(item, 'column'):
                    # QTreeWidgetItem needs column parameter
                    item.setCheckState(0, Qt.CheckState.Checked if is_disabled else Qt.CheckState.Unchecked)

        # Refresh current view to show/hide disabled overlay
        self._flush_pending_history()
        after = self._capture_snapshot()
        # 重建 before：将本次修改的帧回退为旧 is_disabled
        before = dict(after)
        before["frames"] = []
        for f in self.timeline.get_all_frames():
            fb = FrameData(
                file_path=f.file_path,
                scale=f.scale,
                position=tuple(f.position),
                rotation=f.rotation,
                aspect_ratio=f.aspect_ratio,
                target_resolution=tuple(f.target_resolution) if f.target_resolution else None,
                is_disabled=f.is_disabled,
                crop_rect=tuple(f.crop_rect) if f.crop_rect else None,
            )
            for cf, old_state in changed_frames:
                if f is cf:
                    fb.is_disabled = old_state
            before["frames"].append(fb)
        self.timeline.refresh_current_items()

        self.mark_dirty()
        self.canvas.update()
        if self.is_playing:
            self.update_playlist()
        self.statusBar().showMessage(i18n.t("msg_frames_enabled_disabled").format(action=i18n.t("action_enabled") if enable else i18n.t("action_disabled"), count=len(selected)), 3000)
        self.record_history(i18n.t("hist_toggle_disable"), before=before, after=after)

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

    def configure_canvas_border_settings(self):
        """Open canvas border settings dialog."""
        dlg = CanvasBorderSettingsDialog(self)
        
        # Set current settings
        dlg.set_settings({
            "inner_color": self.canvas_border_inner_color,
            "inner_width": self.canvas_border_inner_width,
            "outer_color": self.canvas_border_outer_color,
            "outer_width": self.canvas_border_outer_width,
        })
        
        if dlg.exec():
            settings = dlg.get_settings()
            self.canvas_border_inner_color = settings["inner_color"]
            self.canvas_border_inner_width = settings["inner_width"]
            self.canvas_border_outer_color = settings["outer_color"]
            self.canvas_border_outer_width = settings["outer_width"]

            # Save to global settings
            inner_color_str = ",".join(map(str, self.canvas_border_inner_color))
            self.settings.setValue("canvas_border_inner_color", inner_color_str)
            self.settings.setValue("canvas_border_inner_width", self.canvas_border_inner_width)
            
            outer_color_str = ",".join(map(str, self.canvas_border_outer_color))
            self.settings.setValue("canvas_border_outer_color", outer_color_str)
            self.settings.setValue("canvas_border_outer_width", self.canvas_border_outer_width)

            # Update canvas settings
            inner_color = QColor(*self.canvas_border_inner_color)
            outer_color = QColor(*self.canvas_border_outer_color)
            self.canvas.set_border_settings(
                inner_color,
                self.canvas_border_inner_width,
                outer_color,
                self.canvas_border_outer_width
            )

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
        selected_frames = self.timeline.get_selected_frames()
        if len(selected_frames) != 1:
            return

        frame_data = selected_frames[0]

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
        self.timeline.get_current_widget().viewport().update()
        
        self.update_onion_state()
        
    def clear_reference_frame(self, update=True):
        self.reference_frame = None
        if update:
            self.update_reference_view()
            self.timeline.get_current_widget().viewport().update()
            
        self.update_onion_state()

    def update_reference_view(self):
        self.canvas.set_reference_frame(self.reference_frame)
        self.timeline.set_visual_reference_frame(self.reference_frame)
        
    def calculate_onion_skins(self):
        onion_skins = []
        if self.onion_enabled and (self.onion_prev > 0 or self.onion_next > 0):
            # Find current frame index using unified interface
            selected_indices = self.timeline.get_selected_indices_from_current_view()
            if selected_indices:
                index = selected_indices[0]  # Use first selected frame

                # Get frame count from model
                frame_count = self.timeline.get_frame_count()

                # Previous Frames - use model to get data directly
                for i in range(1, self.onion_prev + 1):
                    target_idx = index - i
                    if target_idx >= 0:
                        data = self.timeline.get_frame_at(target_idx)
                        if data:
                            opacity = max(0.05, 1.0 - (i * self.onion_opacity_step))
                            onion_skins.append((data, opacity))

                # Next Frames - use model to get data directly
                for i in range(1, self.onion_next + 1):
                    target_idx = index + i
                    if target_idx < frame_count:
                        data = self.timeline.get_frame_at(target_idx)
                        if data:
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
        # 画布拖拽：合并窗口由 drag_started 打开，这里仅刷新计时器
        if self._history_merging:
            self._history_merge_timer.start()

    def on_property_changed(self, frame_data=None):
        self.canvas.update() # Redraw with new values
        self.timeline.refresh_current_items()
        self.mark_dirty()
        # 属性面板连续调节：合并窗口由 edit_started 打开，这里仅刷新计时器
        if self._history_merging:
            self._history_merge_timer.start()

    def apply_relative_move(self, dx, dy, update_last=True):
        # Use unified interface to get selected frames
        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames:
            return

        # 连续相对移动：合并窗口
        self._open_history_merge_window(i18n.t("hist_edit_move"))

        for frame_data in selected_frames:
            frame_data.position = (frame_data.position[0] + dx, frame_data.position[1] + dy)

        # Update timeline display
        selected_indices = self.timeline.get_selected_indices_from_current_view()
        for idx in selected_indices:
            self.timeline.update_frame_data(idx)

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
        # Use unified interface to get selected frames
        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames:
            return

        self._flush_pending_history()
        before = self._capture_snapshot()
        for frame_data in selected_frames:
            x, y = frame_data.position
            frame_data.position = (float(round(x)), float(round(y)))

        # Update timeline display
        selected_indices = self.timeline.get_selected_indices_from_current_view()
        for idx in selected_indices:
            self.timeline.update_frame_data(idx)

        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(i18n.t("msg_integerized"), 2000)
        self.record_history(i18n.t("hist_integerize"), before=before)

    def smooth_params_dialog(self):
        """Open dialog to smooth parameters between first and last selected frames"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QLabel, QDialogButtonBox, QCheckBox, QGroupBox

        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames or len(selected_frames) < 2:
            return

        # Get selected indices (sorted)
        selected_indices = sorted(self.timeline.get_selected_indices_from_current_view())
        first_frame = selected_frames[0]
        last_frame = selected_frames[-1]

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(i18n.t("dlg_smooth_params"))
        dialog.setMinimumWidth(350)

        layout = QVBoxLayout(dialog)

        # Mode selection
        mode_label = QLabel(i18n.t("smooth_mode_label"))
        layout.addWidget(mode_label)

        mode_combo = QComboBox()
        mode_combo.addItem(i18n.t("smooth_mode_linear"), "linear")
        mode_combo.addItem(i18n.t("smooth_mode_average"), "average")
        mode_combo.addItem(i18n.t("smooth_mode_ease_in"), "ease_in")
        mode_combo.addItem(i18n.t("smooth_mode_ease_out"), "ease_out")
        mode_combo.addItem(i18n.t("smooth_mode_ease_in_out"), "ease_in_out")
        layout.addWidget(mode_combo)

        # Parameter selection group
        params_group = QGroupBox(i18n.t("smooth_params_group"))
        params_layout = QVBoxLayout(params_group)

        # Checkboxes for each parameter
        scale_cb = QCheckBox(i18n.t("smooth_param_scale"))
        scale_cb.setChecked(True)
        params_layout.addWidget(scale_cb)

        pos_x_cb = QCheckBox(i18n.t("smooth_param_pos_x"))
        pos_x_cb.setChecked(True)
        params_layout.addWidget(pos_x_cb)

        pos_y_cb = QCheckBox(i18n.t("smooth_param_pos_y"))
        pos_y_cb.setChecked(True)
        params_layout.addWidget(pos_y_cb)

        rotation_cb = QCheckBox(i18n.t("smooth_param_rotation"))
        rotation_cb.setChecked(False)
        params_layout.addWidget(rotation_cb)

        layout.addWidget(params_group)

        # Rotation path selection (only enabled when rotation is checked)
        path_label = QLabel(i18n.t("smooth_path_label"))
        layout.addWidget(path_label)

        path_combo = QComboBox()
        path_combo.addItem(i18n.t("smooth_path_auto"), "auto")
        path_combo.addItem(i18n.t("smooth_path_shortest"), "shortest")
        path_combo.addItem(i18n.t("smooth_path_cw"), "cw")
        path_combo.addItem(i18n.t("smooth_path_ccw"), "ccw")
        layout.addWidget(path_combo)

        def _update_path_enabled():
            # Path only matters when rotation is checked AND mode is not "average"
            path_active = rotation_cb.isChecked() and mode_combo.currentData() != "average"
            path_label.setEnabled(path_active)
            path_combo.setEnabled(path_active)

        rotation_cb.toggled.connect(_update_path_enabled)
        mode_combo.currentIndexChanged.connect(_update_path_enabled)
        _update_path_enabled()

        # Info label
        info_label = QLabel(i18n.t("smooth_info").format(
            first=selected_indices[0] + 1,
            last=selected_indices[-1] + 1,
            count=len(selected_indices)
        ))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Get selected mode
        mode = mode_combo.currentData()

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Apply smoothing
        self._apply_param_smoothing(
            selected_frames,
            first_frame,
            last_frame,
            mode,
            scale_cb.isChecked(),
            pos_x_cb.isChecked(),
            pos_y_cb.isChecked(),
            rotation_cb.isChecked(),
            path_combo.currentData()
        )

        # Update timeline display
        for idx in selected_indices:
            self.timeline.update_frame_data(idx)

        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.statusBar().showMessage(i18n.t("msg_params_smoothed").format(count=len(selected_frames)), 2000)
        self.record_history(i18n.t("hist_smooth"), before=before)

    def _apply_param_smoothing(self, frames, first_frame, last_frame, mode,
                                smooth_scale, smooth_pos_x, smooth_pos_y, smooth_rotation,
                                rotation_path="auto"):
        """Apply parameter smoothing with the selected mode.

        rotation_path controls how rotation is interpolated when smooth_rotation is True
        (only relevant for interpolation modes; "average" always uses the shortest midpoint):
          - "auto":     with >2 keyframes, the average of the intermediate keyframes decides
                        whether interpolation should follow the clockwise or counterclockwise
                        direction relative to the first->last segment; if undecidable, falls
                        back to the shortest path. With exactly 2 frames it is effectively the
                        shortest path (no direction can be inferred).
          - "shortest": shortest rotation within [-180, 180].
          - "cw":       always rotate in the increasing-angle direction (+).
          - "ccw":      always rotate in the decreasing-angle direction (-).
        """
        if len(frames) < 2:
            return

        total = len(frames)

        # ----- Helpers -----
        def _normalize_signed(angle):
            """Wrap angle into (-180, 180]; the -180 boundary maps to +180,
            matching property_panel.normalize_rotation."""
            angle = angle % 360
            if angle > 180:
                angle -= 360
            return angle

        def _lerp_rotation(a, b, factor, path):
            """Interpolate from a to b by factor along the given path.

            The result is always normalized to (-180, 180], and the endpoint
            (factor == 1.0) keeps b's original stored value so the last keyframe
            is never rewritten to an equivalent-but-different value.
            """
            if factor >= 1.0:
                return b
            if path == "shortest":
                diff = _normalize_signed(b - a)
            elif path == "cw":
                diff = (b - a) % 360  # always increasing angle
            elif path == "ccw":
                diff = -((a - b) % 360)  # always decreasing angle
            else:  # "auto" -> already resolved to a concrete path
                diff = _normalize_signed(b - a)
            return _normalize_signed(a + diff * factor)

        def _infer_rotation_path():
            """Infer cw/ccw/shortest from intermediate keyframes (bnc rule #1)."""
            if total < 3:
                return "shortest"
            a = first_frame.rotation
            b = last_frame.rotation
            d_short = _normalize_signed(b - a)
            # Wrap-aware average of intermediate keyframes relative to the first
            # frame, so e.g. 170° & -10° are treated as 180° apart instead of
            # averaging the raw values into a misleading -10°.
            avg = sum(_normalize_signed(f.rotation - a) for f in frames[1:-1]) / (total - 2)
            d_avg = _normalize_signed(avg)
            # If intermediate average lies on the first->last shortest segment -> undecidable
            if d_short == 0:
                return "shortest"
            same_sign = (d_avg >= 0) == (d_short >= 0)
            if same_sign and abs(d_avg) <= abs(d_short) + 1e-9:
                return "shortest"
            # Otherwise follow the direction the intermediate frames lean toward
            if same_sign:
                # Beyond the segment end along the same direction -> extend that direction
                return "cw" if d_short >= 0 else "ccw"
            # Opposite side of the segment -> reverse direction
            return "ccw" if d_short >= 0 else "cw"

        # Resolve the concrete path once for the whole operation
        resolved_path = rotation_path
        if resolved_path == "auto":
            resolved_path = _infer_rotation_path()

        for i, frame in enumerate(frames):
            t = i / (total - 1)  # 0.0 to 1.0

            # Calculate interpolation factor based on mode
            if mode == "linear":
                factor = t
            elif mode == "average":
                factor = 0.5  # All frames use the average value
            elif mode == "ease_in":
                # Quadratic ease-in: slow start, fast end
                factor = t * t
            elif mode == "ease_out":
                # Quadratic ease-out: fast start, slow end
                factor = t * (2 - t)
            elif mode == "ease_in_out":
                # Smooth step (ease-in-out)
                factor = t * t * (3 - 2 * t)
            else:
                factor = t

            if mode == "average":
                # Average mode: mean of first & last (no path concept; use shortest midpoint
                # to avoid the ±180° wraparound pitfall, e.g. 170° & -170° -> 180° not 0°)
                if smooth_scale:
                    frame.scale = (first_frame.scale + last_frame.scale) / 2
                if smooth_pos_x:
                    x = (first_frame.position[0] + last_frame.position[0]) / 2
                    frame.position = (x, frame.position[1])
                if smooth_pos_y:
                    y = (first_frame.position[1] + last_frame.position[1]) / 2
                    frame.position = (frame.position[0], y)
                if smooth_rotation:
                    frame.rotation = _lerp_rotation(
                        first_frame.rotation, last_frame.rotation, 0.5, "shortest")
            else:
                # Interpolation modes: interpolate between first and last
                if smooth_scale:
                    frame.scale = first_frame.scale + (last_frame.scale - first_frame.scale) * factor
                if smooth_pos_x:
                    x = first_frame.position[0] + (last_frame.position[0] - first_frame.position[0]) * factor
                    frame.position = (x, frame.position[1])
                if smooth_pos_y:
                    y = first_frame.position[1] + (last_frame.position[1] - first_frame.position[1]) * factor
                    frame.position = (frame.position[0], y)
                if smooth_rotation:
                    frame.rotation = _lerp_rotation(
                        first_frame.rotation, last_frame.rotation, factor, resolved_path)

    def adjust_zoom(self, factor):
        self.canvas.view_scale *= factor
        self.canvas.update()
        
    def adjust_selection_scale(self, factor):
        # Use unified interface to get selected frames
        selected_frames = self.timeline.get_selected_frames()
        if not selected_frames:
            return

        self._flush_pending_history()
        before = self._capture_snapshot()
        for frame_data in selected_frames:
            frame_data.scale *= factor

        # Update timeline display
        selected_indices = self.timeline.get_selected_indices_from_current_view()
        for idx in selected_indices:
            self.timeline.update_frame_data(idx)

        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.mark_dirty()
        self.record_history(i18n.t("hist_scale"), before=before)

    def on_canvas_scale_requested(self, factor):
        # Use property panel to apply scale with proper anchor support
        self.property_panel.apply_rel_scale(factor)

    def on_order_changed(self):
        # 视图拖拽调整顺序后，模型并未自动同步；这里把视图顺序同步回模型，
        # 使保存、导出与撤销/重做都基于最新顺序。
        try:
            if self.timeline.get_view_mode() == "list":
                root = self.timeline.list_view.invisibleRootItem()
                view_order = [
                    root.child(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(root.childCount())
                ]
            else:
                view_order = [
                    self.timeline.grid_view.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.timeline.grid_view.count())
                ]
        except Exception:
            view_order = None

        if view_order is not None and view_order:
            model_frames = self.timeline.get_all_frames()
            if view_order != model_frames:
                self._flush_pending_history()
                before = self._capture_snapshot()
                # 仅当模型顺序真的发生了变更时才落历史，避免产生无效记录
                if self.timeline.model.set_frames_order(view_order):
                    self.record_history(i18n.t("hist_reorder"), before=before)

        # 同步拖拽后的选中项到 Model / Canvas / PropertyPanel
        if self.timeline.get_view_mode() == "list":
            current_selected_indices = self.timeline.list_view.get_selected_indices()
        else:
            current_selected_indices = self.timeline.grid_view.get_selected_indices()

        if current_selected_indices:
            self.timeline.model.set_selection(current_selected_indices)
            live_frames = self.timeline.get_all_frames()
            selected_frames = [live_frames[i] for i in current_selected_indices if 0 <= i < len(live_frames)]
            self.canvas.set_selected_frames(selected_frames)
            self.property_panel.set_selection(selected_frames)

        # Refresh current items for both list and grid view (to update numbers)
        if self.timeline.get_view_mode() == "list":
            self.timeline.refresh_current_items()
        else:
            # Grid view: only refresh item numbers, not full thumbnails
            self.timeline.grid_view.refresh_item_numbers()

        self.mark_dirty()

    def reverse_selected_frames(self):
        # Use unified interface to get selected indices
        indices = self.timeline.get_selected_indices_from_current_view()
        if len(indices) < 2:
            return

        self._flush_pending_history()
        before = self._capture_snapshot()
        # Reverse selected frames through model
        from ui.timeline_model import TimelineModel
        if isinstance(self.timeline.model, TimelineModel):
            self.timeline.model.reverse_frames(indices)
        else:
            # Fallback to manual reversal
            selected_frames = [self.timeline.get_frame_at(idx) for idx in indices]
            selected_frames.reverse()

            # Put them back by replacing in model
            for i, idx in enumerate(indices):
                frame_data = selected_frames[i]
                self.timeline.model.replace_frame_at(idx, frame_data)

        self.mark_dirty()
        self.timeline.refresh_current_items()
        self.canvas.update()
        self.property_panel.update_ui_from_selection()
        self.statusBar().showMessage(f"Reversed {len(indices)} frames.", 3000)
        self.record_history(i18n.t("hist_reverse_order"), before=before)

    def update_fps(self, fps):
        if self.project.fps != fps:
            self._flush_pending_history()
            before = self._capture_snapshot()
            self.project.fps = fps
            if self.is_playing:
                self.timer.start(1000 // self.project.fps)
            self.mark_dirty()
            self.record_history(i18n.t("hist_set_fps"), before=before)

    def update_playlist(self):
        # Build Playlist
        selected_items = self.timeline.selectedItems()
        target_items = []
        if len(selected_items) > 1:
            # Play selected only
            # Sort by visual order (index) to ensure correct sequence
            current_view = self.timeline.get_current_widget()
            if self.timeline.get_view_mode() == "list":
                # List view uses indexOfTopLevelItem
                target_items = sorted(selected_items, key=lambda i: self.timeline.indexOfTopLevelItem(i))
            else:
                # Grid view uses row
                target_items = sorted(selected_items, key=lambda i: current_view.row(i))
        else:
            # Play all
            current_view = self.timeline.get_current_widget()
            if self.timeline.get_view_mode() == "list":
                # List view - get all top level items
                root = self.timeline.list_view.invisibleRootItem()
                target_items = [root.child(i) for i in range(root.childCount())]
            else:
                # Grid view
                target_items = [current_view.item(i) for i in range(current_view.count())]

        # Filter disabled and store frame_data (not items) to avoid invalid references
        self.playlist = []
        for item in target_items:
            # Use unified interface to extract frame data
            data = self.timeline.extract_frame_data_from_item(item)
            if data and not data.is_disabled:
                self.playlist.append(data)

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

        # Restore selection using unified interface
        selected_frames = self.timeline.get_selected_frames()
        self.canvas.set_selected_frames(selected_frames)
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
        if self.timeline.get_frame_count() == 0 or not hasattr(self, 'playlist') or not self.playlist:
            return

        # Get frame_data directly from playlist (playlist now stores frame_data, not items)
        frame_data = self.playlist[self.play_index]

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
        # Automatically add .json extension if not present
        if not path.lower().endswith('.json'):
            path += '.json'
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
            # Sync frames from timeline model to project before saving
            self.project.frames = self.timeline.get_all_frames()

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
        import_debug(f"[Import] Loading project from: {path}")
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

            # Clear thumbnail cache after loading project and refresh grid view
            self.timeline.grid_view._clear_thumbnail_cache()
            self.timeline.grid_view.refresh_all_items()

            if self.project.frames:
                # Select first by default - use unified interface
                if self.timeline.get_frame_count() > 0:
                    # Select first frame
                    first_frame = self.timeline.get_frame_at(0)
                    if first_frame:
                        self.timeline.set_reference_frame(first_frame)
            self.is_dirty = False
            self.update_title()
            self.update_onion_state()
            self.update_menu_state()
            # 新工程载入后清空操作历史
            self._flush_pending_history()
            self.history.clear()
            self._refresh_history_menu()
            import_debug(f"[Import] Project loaded successfully: {len(self.project.frames)} frames")
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

        self._reset_project_to_empty()
        self.statusBar().showMessage(i18n.t("msg_project_closed"), 3000)

    def new_project(self):
        """Create a new empty project, prompting to save if there are unsaved changes."""
        if not self.check_unsaved_changes():
            return

        self._reset_project_to_empty()
        self.statusBar().showMessage(i18n.t("msg_project_new"), 3000)

    def _reset_project_to_empty(self):
        """Reset the current project to an empty state without any prompts."""
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

        # 新建空工程后清空操作历史
        self._flush_pending_history()
        self.history.clear()
        self._refresh_history_menu()

        # Update UI
        self.update_title()
        self.update_menu_state()

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

    def refresh_file_action_labels(self):
        self.import_action.setText(i18n.t("action_import"))
        self.import_slice_action.setText(i18n.t("action_import_slice"))
        self.import_gif_action.setText(i18n.t("action_import_gif"))
        self.save_action.setText(i18n.t("action_save"))
        self.save_as_action.setText(i18n.t("action_save_as"))
        self.load_action.setText(i18n.t("action_load"))
        self.action_open_dir.setText(i18n.t("action_open_dir"))
        self.close_action.setText(i18n.t("action_close"))
        self.reload_action.setText(i18n.t("action_reload"))
        self.copy_assets_action.setText(i18n.t("action_copy_assets"))
        self.reload_images_action.setText(i18n.t("action_reload_images"))
        self.exit_action.setText(i18n.t("action_exit"))
        self.export_action.setText(i18n.t("action_export"))
        self.export_sheet_action.setText(i18n.t("action_export_sheet"))

    def refresh_edit_action_labels(self):
        self.undo_action.setText(i18n.t("action_undo"))
        self.redo_action.setText(i18n.t("action_redo"))
        self.copy_props_action.setText(i18n.t("action_copy_props"))
        self.paste_props_action.setText(i18n.t("action_paste_props"))
        self.dup_frame_action.setText(i18n.t("action_dup_frame"))
        self.dup_frames_dialog_action.setText(i18n.t("action_dup_frames_dialog"))
        self.rem_frame_action.setText(i18n.t("action_rem_frame"))
        self.reverse_order_action.setText(i18n.t("action_reverse_order"))

    def refresh_view_action_labels(self):
        self.settings_action.setText(i18n.t("action_settings"))
        self.reset_view_action.setText(i18n.t("action_reset_view"))
        self.zoom_in_action.setText(i18n.t("action_zoom_in"))
        self.zoom_out_action.setText(i18n.t("action_zoom_out"))
        self.zoom_fit_action.setText(i18n.t("action_zoom_fit"))
        self.scale_up_action.setText(i18n.t("action_scale_up"))
        self.scale_down_action.setText(i18n.t("action_scale_down"))

        # Background Actions
        for mode, action in self.bg_actions.items():
            action.setText(i18n.t(f"bg_{mode}"))

    def refresh_onion_action_labels(self):
        self.onion_action.setText(i18n.t("action_onion_skin"))
        self.onion_settings_action.setText(i18n.t("action_onion_settings"))
        self.canvas_settings_action.setText(i18n.t("action_canvas_settings"))
        self.onion_toolbar_action.setText(i18n.t("toolbar_onion_off" if not self.onion_enabled else "toolbar_onion_on"))

    def refresh_reference_action_labels(self):
        self.set_ref_action.setText(i18n.t("action_set_reference"))
        self.set_ref_action.setToolTip(i18n.t("action_set_reference"))
        self.clear_ref_action.setText(i18n.t("action_cancel_reference"))
        self.ref_settings_action.setText(i18n.t("dlg_ref_settings"))

    def refresh_theme_playback_action_labels(self):
        self.theme_dark_action.setText(i18n.t("theme_dark"))
        self.theme_light_action.setText(i18n.t("theme_light"))

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

    def refresh_layout_action_labels(self):
        self.layout_std_action.setText(i18n.t("preset_std"))
        self.layout_side_action.setText(i18n.t("preset_side"))
        self.layout_stack_ltp_action.setText(i18n.t("preset_stack_ltp"))
        self.layout_stack_lpt_action.setText(i18n.t("preset_stack_lpt"))
        self.layout_stack_rtp_action.setText(i18n.t("preset_stack_rtp"))
        self.layout_stack_rpt_action.setText(i18n.t("preset_stack_rpt"))

    def refresh_repeat_action_labels(self):
        for ms, action in self.repeat_actions.items():
            if ms == 0:
                action.setText(i18n.t("lang_disabled"))
            elif ms == 250:
                action.setText(i18n.t("lang_250_default", "250ms (Default)"))

    def refresh_timeline_view_action_labels(self):
        self.timeline_list_action.setText(i18n.t("action_timeline_list"))
        self.timeline_grid_action.setText(i18n.t("action_timeline_grid"))
        self.timeline_grid_settings_action.setText(i18n.t("action_timeline_grid_settings"))

    def refresh_about_action_labels(self):
        self.repo_action.setText(i18n.t("action_repo"))
        self.debug_control_action.setText(i18n.t("action_debug_control"))
        version_str = self.get_git_version()
        self.version_action.setText(i18n.t("action_version").format(version=version_str))
        build_date = self.get_build_date()
        self.build_date_action.setText(i18n.t("action_build_date").format(date=build_date))

    def refresh_wheel_mode_action_labels(self):
        self.action_wheel_zoom_view.setText(i18n.t("action_wheel_zoom_view"))
        self.action_wheel_scale_image.setText(i18n.t("action_wheel_scale_image"))
        self.update_wheel_toggle_ui()

    def refresh_rasterization_action_labels(self):
        self.raster_toolbar_action.setText(i18n.t("toolbar_raster_off" if not self.raster_enabled else "toolbar_raster_on"))
        self.raster_settings_action.setText(i18n.t("btn_raster_settings"))

    def refresh_ui_text(self):
        # Refresh all action labels using grouped functions
        self.refresh_file_action_labels()
        self.refresh_edit_action_labels()
        self.refresh_view_action_labels()
        self.refresh_onion_action_labels()
        self.refresh_reference_action_labels()
        self.refresh_wheel_mode_action_labels()
        self.refresh_theme_playback_action_labels()
        self.refresh_layout_action_labels()
        self.refresh_repeat_action_labels()
        self.refresh_timeline_view_action_labels()
        self.refresh_rasterization_action_labels()
        self.refresh_about_action_labels()

        # Update Docks
        self.timeline_dock.setWindowTitle(i18n.t("dock_timeline"))
        self.property_dock.setWindowTitle(i18n.t("dock_properties"))

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

        # Sync timeline view actions
        if hasattr(self, 'timeline_view_group'):
            if self.timeline_view_mode == "grid":
                self.timeline_grid_action.setChecked(True)
            else:
                self.timeline_list_action.setChecked(True)

        # Update Toolbar
        self.create_toolbar()

        # Update Sub-widgets
        self.property_panel.refresh_ui_text()
        self.timeline.list_view.setHeaderLabels([
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
            # 提交未完成的连续操作历史
            self._flush_pending_history()
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
        
        import_debug(f"[Import] Importing sprite sheet: {file}")
            
        from ui.slice_dialog import SliceImportDialog
        dlg = SliceImportDialog(file, self)
        if not dlg.exec():
            return
            
        results = dlg.get_results()
        mode = results["mode"]
        crops = results["crops"]

        self._flush_pending_history()
        before = self._capture_snapshot()
        
        if mode == "virtual":
            # Virtual Slicing: Add FrameData with crop_rect
            # 只加载一次图片（用于验证）
            for crop in crops:
                frame = FrameData(file_path=file, crop_rect=crop)
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
                self.timeline.add_frame(os.path.basename(out_path), frame, w, h)

        self.mark_dirty()
        self.timeline.refresh_current_items()
        import_debug(f"[Import] Sprite sheet imported: {len(crops)} slices, mode={mode}")
        self.statusBar().showMessage(i18n.t("msg_imported_slices").format(count=len(crops)), 3000)
        self.record_history(i18n.t("hist_import_slice"), before=before)

    def import_gif(self):
        file, _ = QFileDialog.getOpenFileName(self, i18n.t("dlg_import_gif_title"), "", i18n.t("dlg_filter_gif"))
        if not file:
            return
        
        import_debug(f"[Import] Importing GIF: {file}")

        # 与 import_sprite_sheet 保持一致：抓取 before 快照前先提交挂起的合并窗口，
        # 避免把刚导入的 GIF 帧混入拖拽历史的 after，导致两条历史快照错位。
        self._flush_pending_history()
        before = self._capture_snapshot()
            
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

                # Add to project through timeline model
                f_data = FrameData(file_path=out_path)
                self.timeline.add_frame(os.path.basename(out_path), f_data, png_frame.width, png_frame.height)
                count += 1

            self.mark_dirty()
            self.timeline.refresh_current_items()
            import_debug(f"[Import] GIF imported: {count} frames extracted")
            self.statusBar().showMessage(i18n.t("msg_imported_gif").format(count=count), 3000)
            self.record_history(i18n.t("hist_import_gif"), before=before)
            
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
            # Use unified interface to get selected indices
            return sorted(self.timeline.get_selected_indices_from_current_view())
        elif range_mode == "custom":
            from utils.exporter import Exporter
            return Exporter.parse_range_string(custom_range, self.timeline.get_frame_count())
        else: # "all"
            # Return all non-disabled frames' indices
            return [i for i, f in enumerate(self.timeline.get_all_frames()) if not f.is_disabled]

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

        # Sync frames from timeline model to project so export works even when the
        # project has not been saved yet.
        self.project.frames = self.timeline.get_all_frames()

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

        # Sync frames from timeline model to project so export works even when the
        # project has not been saved yet.
        self.project.frames = self.timeline.get_all_frames()

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
            self._flush_pending_history()
            before = self._capture_snapshot()
            self.mark_dirty()
            self.timeline.refresh_current_items() # Filenames might have changed or just to be sure
            self.canvas.update()
            self.record_history(i18n.t("hist_copy_assets"), before=before)

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
    
    # --- Timeline View Methods ---
    
    def set_timeline_view(self, mode):
        """Switch between list and grid view"""
        # Save current selection before switching
        current_view = self.timeline.get_current_widget()
        selected_indices = []

        # Get selected indices using unified interface
        selected_indices = current_view.get_selected_indices()

        # Switch view
        self.timeline.set_view_mode(mode)

        # Restore selection
        if selected_indices:
            if mode == "grid":
                # Restore grid selection
                for idx in selected_indices:
                    if idx < self.timeline.grid_view.count():
                        self.timeline.grid_view.item(idx).setSelected(True)
            else:
                # Restore list selection
                for idx in selected_indices:
                    if idx < self.timeline.list_view.topLevelItemCount():
                        self.timeline.list_view.topLevelItem(idx).setSelected(True)

        # Save view mode preference
        self.settings.setValue("timeline_view_mode", mode)
    
    def open_timeline_grid_settings(self):
        """Open grid view settings dialog"""
        from ui.timeline_grid_settings import TimelineGridSettingsDialog

        dlg = TimelineGridSettingsDialog(
            self,
            self.timeline.grid_thumbnail_width,
            self.timeline.grid_thumbnail_height,
            self.timeline.grid_show_multiline,
            self.timeline.grid_multiline_label_height,
            self.timeline.grid_background_mode
        )

        if dlg.exec():
            settings = dlg.get_settings()

            # Apply settings
            self.timeline.update_grid_settings(
                settings['width'],
                settings['height'],
                settings['multiline'],
                settings['multiline_label_height'],
                settings['background']
            )

            # Save settings
            self.settings.setValue("grid_thumb_width", settings['width'])
            self.settings.setValue("grid_thumb_height", settings['height'])
            self.settings.setValue("grid_show_multiline", settings['multiline'])
            self.settings.setValue("grid_multiline_label_height", settings['multiline_label_height'])
            self.settings.setValue("grid_background_mode", settings['background'])

            # If currently in grid view, refresh
            if self.timeline.get_view_mode() == "grid":
                self.timeline.refresh_all_grid_items()
    
    def on_grid_thumbnail_size_changed(self, width, height):
        """Handle grid thumbnail size change"""
        self.grid_thumb_width = width
        self.grid_thumb_height = height
        self.settings.setValue("grid_thumb_width", width)
        self.settings.setValue("grid_thumb_height", height)
