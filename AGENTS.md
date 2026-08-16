# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

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
  `python test_full_slice.py` (standalone, no test framework). Tests live as top-level scripts (e.g. `test_full_slice.py`); run them directly with the project root as CWD.

- **Linting:** No linter/CI configured. Use `python -m py_compile <file>` to sanity-check syntax.

## Architecture

PinFrame is a single-window PyQt6 app. `main.py` bootstraps `QApplication` + `MainWindow` (the central controller, ~3200 lines in `src/ui/main_window.py`). `src` is added to `sys.path` by `main.py`, so imports are relative to `src` (e.g. `from ui.main_window import MainWindow`, `from model.project_data import ...`, `from i18n.manager import i18n`).

### Data model (`src/model/project_data.py`)
Two dataclasses form the entire project state:
- `FrameData`: one sprite frame — `file_path`, `scale`, `position`, `rotation`, `aspect_ratio` (X/Y distortion, negative = mirror), `crop_rect`, `is_disabled`, and an ephemeral `target_resolution`. Supports `to_dict`/`from_dict` with project-relative path normalization (so projects stay portable when moved).
- `ProjectData`: the document — `fps`, `width`, `height`, `background_color`, `frames: List[FrameData]`, plus persisted export settings. `to_json`/`from_json` (file path drives relative-path resolution) are the save/load contract. **All persistence goes through these methods.**

### Core services (`src/core/`)
- `image_cache.py`: a global singleton `ImageCache` (`image_cache`) shared across all widgets, keyed by absolute file path (not crop rect), FIFO-capped at 500. Always read images from `image_cache.get(path)` rather than `QImage(path)` directly to avoid reloading.
- `version.py`: build-time generated; holds `VERSION`, `REPO_URL`, `BUILD_DATE`. Do not edit by hand.

### Rendering (`src/ui/canvas.py`, `src/utils/exporter.py`)
Two independent render paths must stay in sync when you change transform logic:
- **Interactive preview** (`CanvasWidget`): a `QWidget` that draws with `QPainter`, handling view pan/zoom (`view_offset`/`view_scale`), onion skins (`onion_skin_frames`), reference frame overlay, multi-selection drag, anchor handles (4 modes), rasterization grid, and wheel-mode toggle (zoom vs scale image). Emits `transform_changed`, `anchor_pos_changed`, `scale_change_requested`.
- **Export** (`Exporter` in `src/utils/exporter.py`): pure PIL (`'RGBA'` canvas, `alpha_composite`) implementing `export_iter` (PNG sequence, generator with progress), `export_sprite_sheet`, `export_gif`. It re-implements scale→crop→mirror→rotate→center-composite logic in Python. **If you change transform semantics in `FrameData`, mirror it here or exports will diverge from preview.** `parse_range_string` converts `"1,3,5-7,10-"` into 0-based indices.

### Timeline (`src/ui/timeline*.py`)
`TimelineWidget` (a `QStackedWidget`) holds two views — `TimelineListView` (tree) and `TimelineGridWidget` (thumbnails) — backed by a `TimelineModel` (frames insert/remove/move/selection signals). It exposes many `pyqtSignal`s (`selection_changed`, `order_changed`, `files_dropped`, `duplicate_requested`, `reverse_order_requested`, `set_reference_requested`, etc.) that `MainWindow` connects to actions. Views share `BaseTimelineView` + `TimelineViewUtils` + a delegate.

### Panels, dialogs, and settings (`src/ui/`)
- `PropertyPanel`: per-frame transform controls (scale, position, rotation, anchor mode, repeat-move timer). Emits `frame_data_changed`/`relative_move_requested`/`custom_anchor_changed`.
- `slice_dialog.py`: sprite-sheet slicing — rows/cols/grid preview that creates multiple `FrameData` sharing one source image with different `crop_rect`s.
- Settings dialogs: `settings_dialog`, `onion_settings`, `reference_settings`, `raster_settings`, `canvas_border_settings`, `duplicate_dialog`, `export_dialog`, `copy_assets_dialog`, `color_picker`, `assemble`. Each is a modal feeding `MainWindow` state.
- `MainWindow` owns the `ProjectData`, wires every signal, manages save/load (`_save_to_path`, `_load_from_path`, `check_unsaved_changes`), playback (`QTimer`-driven `toggle_play`/`next_frame`/`reverse`), and copy/paste of frame properties.

### i18n (`src/i18n/`)
Singleton `I18nManager` (`i18n`) loaded from `en_US.json` / `zh_CN.json`. Call `i18n.t("key")` for all user-visible strings; add new keys to both JSON files. Resource path resolution handles both dev and PyInstaller (`sys._MEIPASS`) bundles.

### Timeline internal drag-reorder contract (non-obvious, respect when editing)
`TimelineListView` and `TimelineGridWidget` fully take over internal reordering (they never let Qt delete/move items itself) to avoid frame loss. Invariants to preserve:
- **Insert before/after**: decided by `_calc_insert_before(drop_pos, item_center)` in `timeline_grid.py` (Grid is row-major — Y only picks the row via `itemAt`; X alone decides before/after). `dragMoveEvent` (preview) and `dropEvent` fallback (landing) must call the SAME method so the blue insert indicator matches the final drop. Never reintroduce separate `and`/`or` logic.
- **Item reuse**: both views `takeItem`/`takeTopLevelItem` then re-`insertItem` the *original* item objects (Grid copies from List's pattern). Do NOT rebuild `QListWidgetItem` (drops flags/sizeHint/custom roles and breaks external references).
- **State lifecycle**: `startDrag` sets `self._dragged_items`; `_clear_drag_state()` resets `_is_dragging`, `_drag_insert_position`, and `_dragged_items`. Selection is restored onto the re-inserted items after drop.
- **Selection source of truth**: read selected indices via `get_selected_indices_from_model()` (it reads the model, not the view) — the old `get_selected_indices_from_current_view` name was misleading and renamed.

### Conventions & gotchas
- Imports are `src`-relative (no `src.` prefix). Run anything with the repo root as CWD.
- Image loading = `image_cache.get(...)`. Image rendering transform logic exists in **two places** (canvas + exporter); keep them consistent.
- `src/core/version.py` is auto-generated — never commit hand edits.
- No automated test suite; verify via `test_full_slice.py` and `dev/screenshot.sh`.
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

