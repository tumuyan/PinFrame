# AGENTS.md

This file provides guidance to CodeBuddy and other AI coding tools when working with code in this repository.

## Overview

PinFrame (定帧) is a PyQt6 desktop application for previewing, fine-tuning, and consolidating sprite sequences / sprite sheets, plus a general-purpose GIF tool. It is AI-driven developed. Projects are stored as JSON referencing external image files (lossless, no duplication). Entry point is `main.py`.

## Common Commands

- **Install dependencies (dev/headless):**
  `bash dev/setup.sh` (creates `venv`, installs `requirements.txt` + Qt system libs). For normal dev just `pip install -r requirements.txt` (PyQt6, Pillow; Python 3.11+).

- **Run the app:**
  `python main.py` (adds `src` to path internally). In headless/code-server environments use `bash dev/run_gui.sh` which starts Xvfb and `DISPLAY=:99`.

- **Build Windows executable (PyInstaller):**
  `pyinstaller PinFrame.spec` → output in `dist/PinFrame`. The spec auto-generates `src/core/version.py` from `git describe`/`git remote` at build time.

- **Screenshot for visual verification (headless):**
  `bash dev/screenshot.sh` launches the app under Xvfb and captures `dev/tmp_screenshot.png`.

- **Run a single test script:**
  `python dev/test_transform.py`（37 个 `core.transform` + 时间轴模型信号契约单测，纯 assert，无需 pytest）；
  `python dev/transform_baseline.py [--compare]`（所有渲染路径的像素哈希回归）。
  这是唯一的自动化测试；其余功能靠手动验证。

- **Linting:** No linter/CI configured. Use `python -m py_compile <file>` to sanity-check syntax.

## Architecture

PinFrame is a single-window PyQt6 app. `main.py` bootstraps `QApplication` + `MainWindow` (the central controller, ~3200 lines in `src/ui/main_window.py`). `src` is added to `sys.path` by `main.py`, so imports are relative to `src` (e.g. `from ui.main_window import MainWindow`, `from model.project_data import ...`, `from i18n.manager import i18n`).

### Data model (`src/model/project_data.py`)
Two dataclasses form the entire project state:
- `FrameData`: one sprite frame — `file_path`, `scale`, `position`, `rotation`, `aspect_ratio` (X/Y distortion, negative = mirror), `crop_rect`, `is_disabled`, and an ephemeral `target_resolution`. Supports `to_dict`/`from_dict` with project-relative path normalization (so projects stay portable when moved).
- `ProjectData`: the document — `fps`, `width`, `height`, `background_color`, `frames`, plus persisted export settings. `to_json`/`from_json` (file path drives relative-path resolution) are the save/load contract. **All persistence goes through these methods.**
- **`ProjectData.frames` 是绑定活跃数据源的属性，不是第二份副本。** `MainWindow` 调用 `project.bind_frames_provider(self.timeline.get_all_frames)`（在 `__init__`、`_reset_project_to_empty`，以及 `_load_from_path` 里 `from_json` 之后、先 `timeline.clear()`、再于填充循环之前绑定），之后读 `project.frames` 恒为 `TimelineModel` 的实时列表。**绑定后赋值会抛 `RuntimeError`**——旧的 `project.frames = self.timeline.get_all_frames()` 同步仪式已全部删除，不要再写回来。未绑定时（刚 `from_json`、或无 UI 脚本）回退到 `_static_frames`，载入流程正是靠这条路径填充帧。
  - 附带影响：`project.frames` 每次读取都返回**新列表**（`get_all_frames()` 是拷贝）。循环前先存到局部变量（`Exporter` 已这么做），且不要去改这个返回的列表；改它里面的 `FrameData` 对象**是有效的**，会作用到模型上。
- **`FrameData.clone()` 是唯一的帧复制实现。** 不要再手写字段列表复制帧——曾经有 4 份手写克隆，其中 3 份（`duplicate_frame` 与重复帧对话框的 ABAB / AABB 模式）漏拷 `aspect_ratio`，导致重复一个镜像帧时副本丢失镜像状态；第 4 份漏了 `target_resolution`。

### Core services (`src/core/`)
- `transform.py`: 帧变换几何的唯一来源（见上）。Qt-free，有单测覆盖。
- `image_cache.py`: a global singleton `ImageCache` (`image_cache`) shared across all widgets, keyed by absolute file path (the `crop_rect` argument is accepted but ignored — dead parameter), FIFO-capped at 500 *images* (not bytes). Always read images from `image_cache.get(path)` rather than `QImage(path)` directly to avoid reloading. **必须写成 `from core.image_cache import image_cache`**，不可写 `from src.core.image_cache import ...`：两种写法都能解析（仓库根在 `sys.path` 上），但会产生两个不同的模块对象、进而两个独立的单例——`canvas.py` 与 `property_panel.py` 曾经就是这样，导致内存翻倍且缓存失效被割裂。
- `version.py`: build-time generated; holds `VERSION`, `REPO_URL`, `BUILD_DATE`. Do not edit by hand.

### Rendering (`src/core/transform.py`, `src/ui/canvas.py`, `src/utils/exporter.py`)

`src/core/transform.py` 是**帧变换几何的唯一来源**，预览与导出共用。它刻意不 import PyQt6（`apply_to_painter` 用鸭子类型接受 `QPainter` / `QTransform`），因此几何逻辑无需 `QApplication` 即可单测。

- `resolve_frame_geometry(frame, apply_position=True)` → `FrameGeometry`（裁切、带符号的 `scale_x`/`scale_y`、`flip_h`/`flip_v`、旋转、中心偏移）。`apply_position=False` 供属性面板单帧预览使用——它把帧居中、刻意忽略画布位置。
- `apply_to_painter(target, geo)` 固定 **平移 → 旋转 → 缩放** 的次序。Qt 右乘复合，故图像实际经历 缩放(含镜像) → 旋转 → 平移，与 exporter 的 `resize → transpose → rotate → 定位` 一致。
- `frame_aabb` —— 缩放+旋转后的轴对齐包围盒（属性面板 fit 适配）。
- `scaled_size_floor` —— exporter 的 `int()` 截断，**刻意**与 `FrameData.effective_target_size()` 保持一致，使 UI 显示的"目标分辨率"等于导出实际像素尺寸。
- `composite_origin` —— 变换后位图贴到画布的整数左上角。用 `math.floor`，**不用** `int()`（它在 0 处翻转取整方向，帧移出左/上边缘时平移动画会顿跳 1px），**也不用** `round()`（banker's rounding 与位图宽度的奇偶交替相互干涉，实测把缩放渐变的质心抖动从 0.5px 放大到 1.0px）。

**几何共用，像素化不共用。** `CanvasWidget` 用连续浮点 `QPainter` 变换；`Exporter.compose_frame` 用 PIL 量化（`int()` 尺寸、`rotate(expand=True)`、LANCZOS/BICUBIC）。预览与导出**不可能**逐像素一致——重采样滤波器不同、导出两遍重采样而预览一遍、预览还叠了 `view_scale`。`dev/export_pipeline_precision.md` 记录了实测数据、为什么"让两者一致"是错的目标，以及真正值得修的部分（分数位置的阶梯抖动、缩放渐变的 ±0.5px 交替）该如何用单次仿射变换解决。

`Exporter` 只有一份变换实现（`compose_frame`），三种导出模式共用：`export_iter`（PNG 序列，带进度的 generator）、`export_sprite_sheet`、`export_gif`。`parse_range_string` 把 `"1,3,5-7,10-"` 转成 0 基下标。

**`aspect_ratio` 的符号是有语义的。** 它是 X/Y 失真系数，**负值编码镜像状态**——`property_panel._mirror_axis` 对水平镜像同时翻转 `scale` 与 `aspect_ratio` 的符号，垂直镜像只翻转 `aspect_ratio`，而 `reset_mirror` 靠符号**组合**反推镜像轴。只有 `0` 是无效值（除零且无语义）；`normalize_aspect_ratio()` 把它归一为 `1.0`，已应用于 `resolve_frame_geometry`、`frame_aabb`、`effective_target_size()`、`FrameData.from_dict`。**绝不可归一负值**——那会让水平镜像静默变成 180° 旋转、垂直镜像直接失效。

### 渲染改动的验证方式

任何触及变换语义的改动都必须过这两个工具（无需 pytest，只依赖 PyQt6 + Pillow）：

```powershell
python dev/test_transform.py                  # 37 个单测，快，解释"为什么"
python dev/transform_baseline.py              # 记录所有渲染路径的像素哈希
python dev/transform_baseline.py --compare    # 改动后：MAIN_DIGEST 必须不变
```

`transform_baseline.py` 用一个夹具工程（旋转、镜像、裁切、失真、奇偶源图尺寸）跑 PNG 序列/精灵表/GIF 导出、canvas 普通与栅格化两条路径、属性面板单选与多选预览，再对输出取哈希。其 `EDGE` 组把 `aspect_ratio == 0` **隔离到子进程**——归一之前该用例会 abort 整个进程（PyQt6 把 `paintEvent` 内未捕获异常升级为 `abort()`，实测退出码 `0xC0000409`）。

### Timeline — design (`src/ui/timeline*.py`)
The timeline is a **model/view system**: `TimelineModel` owns the frame list and is the sole authority over frame state; `TimelineWidget` (a `QStackedWidget`) hosts two read-only views — `TimelineListView` (tree) and `TimelineGridWidget` (thumbnails) — that share `BaseTimelineView` + `TimelineViewUtils` + a delegate. Every mutation broadcasts a `pyqtSignal` (`selection_changed`, `order_changed`, `files_dropped`, `duplicate_requested`, `reverse_order_requested`, `set_reference_requested`, ...) that `MainWindow` connects to actions.

**Design tenet — one fact, one truth, one write-path, read-only views.** Any per-frame state is *business data owned by the model*, never copied into a view's item roles. The model is the single write-path and broadcasts change via a signal; list & grid views are read-only consumers that render straight from the model and repaint on that signal. This keeps both views always consistent and makes any new batch/conditional operation just a loop over the model. Concretely, this philosophy shapes every sub-feature:

- **Selection source of truth** — selected indices are read from the model via `get_selected_indices_from_model()`, never from the view (the old `get_selected_indices_from_current_view` name was misleading and renamed).
- **Disabled state** — `FrameData.is_disabled` is the truth; the only write-path is `TimelineModel.set_frame_disabled(index, is_disabled)`, which broadcasts `frame_disabled_changed(index, bool)`; views repaint on that signal (`TimelineWidget._on_frame_disabled_changed` → per-row `viewport().update()`). Because rendering reads the truth, the list delegate fetches `frame_data` from column-0 `UserRole` (via `index.siblingAtColumn(0)`) and reads `.is_disabled` — no `CheckStateRole` copy is ever written.
- **Signal semantics — the model broadcasts frame-change signals with distinct meanings; views pick "repaint in place" vs "rebuild" accordingly. Never conflate them:**
  - `frames_inserted` / `frames_removed` / `frames_moved` — set add/remove, or a single-item move.
  - `data_changed(start, end)` — **content changed only; the index→item mapping is unchanged.** Views refresh text/thumbnail in place (and, for performance, only the *active* view — the inactive one is re-synced on `set_view_mode` switch). **Never use it to carry a reorder**: the view refreshes text by index and does not re-sort items, so after a reorder the UI keeps showing the *old* order while the model (save/export) is already correct. (`TimelineModel.reverse_frames` / `set_frames_order` must emit `frames_reordered`, not `data_changed`.)
  - `frames_reordered` — **a wholesale reorder** (reverse / drag-sort / `set_frames_order`): the index→item mapping is invalidated, so views must rebuild from the model. `_on_frames_reordered` rebuilds only the view that is actually out of sync (so the drag-origin view, already correct, isn't needlessly rebuilt — rebuilding it would also discard the item state it just arranged).
- **Internal drag-reorder** — the views take over reordering entirely (they never let Qt delete/move items, to avoid frame loss) and restore selection from the model afterwards. Invariants to preserve:
  - **Insert before/after**: decided by `_calc_insert_before(drop_pos, item_center)` in `timeline_grid.py` (Grid is row-major — Y only picks the row via `itemAt`; X alone decides before/after). `dragMoveEvent` (preview) and `dropEvent` fallback (landing) must call the SAME method so the blue insert indicator matches the final drop. Never reintroduce separate `and`/`or` logic.
  - **Item reuse**: both views `takeItem`/`takeTopLevelItem` then re-`insertItem` the *original* item objects (Grid copies from List's pattern). Do NOT rebuild `QListWidgetItem` (drops flags/sizeHint/custom roles and breaks external references).
  - **State lifecycle**: `startDrag` sets `self._dragged_items`; `_clear_drag_state()` resets `_is_dragging`, `_drag_insert_position`, and `_dragged_items`. Selection is restored onto the re-inserted items after drop.
  - **Rebuild restores selection on the correct view** — `_rebuild_list_view` / `_rebuild_grid_view` rebuild the *inactive* view; when restoring selection they must call `_apply_selection_to_view(indices, mode)` with an explicit `mode` (`"list"` / `"grid"`). Never rely on `current_view_mode` there — a rebuild of the list while in grid mode would write the selection into the grid, clobbering the just-dragged selection. (This was the root cause of "after a multi-select drag, the selected frames are no longer the dragged ones".)

### Panels, dialogs, and settings (`src/ui/`)
- `PropertyPanel`: per-frame transform controls (scale, position, rotation, anchor mode, repeat-move timer). Emits `frame_data_changed`/`relative_move_requested`/`custom_anchor_changed`.
- `slice_dialog.py`: sprite-sheet slicing — rows/cols/grid preview that creates multiple `FrameData` sharing one source image with different `crop_rect`s.
- Settings dialogs: `settings_dialog`, `onion_settings`, `reference_settings`, `raster_settings`, `canvas_border_settings`, `duplicate_dialog`, `export_dialog`, `copy_assets_dialog`, `color_picker`, `assemble`. Each is a modal feeding `MainWindow` state.
- `MainWindow` owns the `ProjectData`, wires every signal, manages save/load (`_save_to_path`, `_load_from_path`, `check_unsaved_changes`), playback (`QTimer`-driven `toggle_play`/`next_frame`/`reverse`), and copy/paste of frame properties.

### i18n (`src/i18n/`)
Singleton `I18nManager` (`i18n`) loaded from `en_US.json` / `zh_CN.json`. Call `i18n.t("key")` for all user-visible strings; add new keys to both JSON files. Resource path resolution handles both dev and PyInstaller (`sys._MEIPASS`) bundles.

### Conventions & gotchas
- Imports are `src`-relative (no `src.` prefix). Run anything with the repo root as CWD.
- **时间轴缩略图刻意不套用帧变换**：`TimelineGridWidget.create_thumbnail` 只做 `crop_rect` 裁切 + `KeepAspectRatio` 缩放，不含旋转/镜像/缩放/偏移。这是有意设计（缩略图展示素材本身的样子，而非合成后的帧），**不要**把它接到 `core/transform.py`。
- **`project.frames` 已是绑定活跃数据源的属性，恒为实时值**（见上方 Data model）。不要再写 `self.project.frames = self.timeline.get_all_frames()`——绑定后赋值会抛 `RuntimeError`。
- Image loading = `image_cache.get(...)`（注意用 `from core.image_cache import ...`，不要带 `src.` 前缀）。帧变换语义统一在 `core/transform.py`，canvas 与 exporter 共用；两者只在像素化方式上不同。
- `src/core/version.py` is auto-generated — never commit hand edits.
- `dev/test_transform.py` is the only automated test suite (37 pure-assert unit tests for `core.transform` + the timeline-model signal contract); everything else is verified via `dev/transform_baseline.py` (pixel regression), `dev/verify_timeline_view_sync.py` (offscreen Qt — timeline list/grid view sync + drag-selection; catches the "order/selection desync after switching views" regressions), and `dev/screenshot.sh` (manual visual check).
- `dev/` holds environment/screenshot/novnc helper scripts, not app code.

### Debug logging framework (use this instead of print)
`src/utils/debug_config.py` provides a categorized, opt-in logger. Enable the master switch + per-category checkboxes in the debug settings dialog (categories are dynamically read from `CATEGORY_KEYS`, so adding a key auto-adds a UI toggle). Import the per-category helper and call it:
- Helpers: `import_debug`, `export_debug`, `property_debug`, `canvas_debug`, `timeline_debug`, `grid_text_debug`, `layout_debug`, `layout_debug`.
- Default-enabled: `timeline`, `canvas`, `property`, `export`, `import`. `grid_text` and `layout` are OFF by default — add a new category to `CATEGORY_KEYS` + `CATEGORY_I18N_KEYS` + a `xxx_debug()` fn, and add the i18n key `debug_cat_<name>` to both `zh_CN.json`/`en_US.json`.

### Layout system (MainWindow dock/splitter) — non-obvious Qt pitfalls
`apply_layout_preset(preset)` in `main_window.py` switches between dock-based presets (`standard`/`side`/`stack_*`) and a custom non-dock `QSplitter` layout (`custom`). Presets persist via `settings` key `last_layout`; stacked ratio persists as `stack_split_sizes`; custom splitter sizes as `custom_layout_v_sizes`/`custom_layout_h_sizes`.
- **Do NOT split two independent docks in the same area.** `addDockWidget(area, dock)` IGNORES the `area` argument for a dock that has ever been docked before — the dock snaps back to the area it "remembers" (e.g. `timeline_dock` always returns to Bottom and fills the width). This is why stacked presets use a SINGLE `stack_dock` holding an internal `QSplitter` (timeline + property), not two docks split in one area.
- **`setSizes()` on a QSplitter must run AFTER the splitter is laid out** (`QTimer.singleShot(0, ...)` after `setCentralWidget`/`addDockWidget`). Calling it earlier lets Qt recompute from children `sizeHint` and collapse a pane to 0 (observed `[640,0]` / `[759,0]`).
- **Never persist a collapsed `[x, 0]` splitter size.** Filter saved ratios so both values are `> 0`, and delete the key if corrupted — otherwise the bad value is reused on every launch (it survives in QSettings).
- When moving a widget between a dock and a splitter, `setWidget(widget)` reparents it out of its current parent automatically; always `setWidget(None)` before re-homing.
- Cross-preset switching must fully `removeDockWidget` all docks (incl. `stack_dock`) before rebuilding, so stale split/area state doesn't carry over.
- Startup: skip `restoreState` for `custom` and `stack_*` presets (apply the preset directly); otherwise stale dock-area memories fight the rebuild.

## Documentation & file-location conventions

- **`doc/` is for end-user documentation** — written for **final users** of the shipped application. Explain features, UI operations, and workflows in plain user-facing language (e.g. `doc/使用说明.md`).
- **`dev/` is for developer-facing material** — scattered developer files (scripts AND docs): environment/screenshot/novnc helper scripts and developer notes (e.g. `dev/*.md`, `dev/*.sh`). Code architecture, internal APIs, signal contracts, and implementation details live here or in this `AGENTS.md`, never in `doc/`.
- Put user-facing guides in `doc/`, developer notes/scripts in `dev/`. Do not mix the two.
- In the user-facing usage guide, avoid duplicating `README.md` / `README_EN.md` (installation, running, packaging); focus on **how to use the app**, not how to build it.
- Keep each guide in the same language tone as the README it complements (Chinese guide pairs with `README.md`).

