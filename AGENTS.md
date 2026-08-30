# AGENTS.md

This file provides guidance to CodeBuddy and other AI coding tools when working with code in this repository.

## Overview

PinFrame (定帧) is a PyQt6 desktop application for previewing, fine-tuning, and consolidating sprite sequences / sprite sheets, plus a general-purpose GIF tool. It is AI-driven developed. Projects are stored as JSON referencing external image files (lossless, no duplication). Entry point is `main.py`.

**配套文档：** `dev/known_issues.md` 记"哪些不做、为什么不做、还剩什么"（不做清单与判据、已知残留、后续独立议题、无自动化覆盖项、写测试与复核命令的陷阱）。本文件记"是什么、怎么用"，那文件记"为什么不做" —— 提议一个重构前先翻它，很可能那条路已经走过并给出了不做的判据。

## Common Commands

- **Install dependencies (dev/headless):**
  `bash dev/setup.sh` (creates `venv`, installs `requirements.txt` + Qt system libs). For normal dev just `pip install -r requirements.txt` (PyQt6, Pillow; Python 3.11+).

- **Run the app:**
  `python main.py` (adds `src` to path internally). In headless/code-server environments use `bash dev/run_gui.sh` which starts Xvfb and `DISPLAY=:99`.

- **Build Windows executable (PyInstaller):**
  `pyinstaller PinFrame.spec` → output in `dist/PinFrame`. The spec auto-generates `src/core/version.py` from `git describe`/`git remote` at build time. 该文件**不入库**（`.gitignore`），故构建后再也不会污染工作区；开发态没有它，`main_window` 容错回落。

- **Screenshot for visual verification (headless):**
  `bash dev/screenshot.sh` launches the app under Xvfb and captures `dev/tmp_screenshot.png`.

- **Run all automated checks (全量回归):**
  `bash dev/run_all_checks.sh`（退出码 0=全过 / 1=有失败 / 2=前置依赖缺失）。
  依次跑 13 项：`check_no_duplicate_defs.py` → 语法编译 → `test_transform.py` →
  `transform_baseline.py --compare` → `verify_timeline_view_sync.py` →
  `verify_grid_view.py` → `smoke_reorder.py` → `smoke_reference_frame.py` →
  `verify_selection_style.py` → `verify_undo_snapshot.py` → `verify_image_cache.py`
  → `verify_project_ownership.py` → `verify_export_errors.py`。
  `--verbose` 实时回显完整输出，`--fail-fast` 首败即停。
  **改动触及共享层（`core/transform.py`、`timeline_model.py`、`timeline_item_model.py`、
  `project_data.py`）或打包发布前，必须跑全量**；只动某个对话框/i18n 键时可只跑定向项。

- **Run a single test script:**
  `python dev/test_transform.py`（37 个 `core.transform` + 时间轴模型信号契约单测，纯 assert，无需 pytest）；
  `python dev/transform_baseline.py [--compare]`（所有渲染路径的像素哈希回归）。
  **脚本全绿 ≠ 全覆盖**：右键菜单、外部文件拖入、播放时的选中跟随这三项没有任何
  自动化覆盖，只能手动验证。

- **像素基线的正确用法（`transform_baseline.py`）:**
  `dev/tmp_baseline/` 在 `.gitignore` 中，**基线不入库**。所以 `--compare` 比的是
  "与本机上一次运行"，不是"与团队基线"。流程：改动**前**跑一次不带 `--compare` 的
  存基线，改动**后** `--compare` 看 `MAIN_DIGEST` 是否变化。
  陷阱：若 `dev/tmp_baseline/hashes.json` 缺失，`--compare` 会**跳过比对、静默建一条
  新基线并返回 0（假通过）**。`dev/run_all_checks.sh` 会前置校验它存在且含
  `main_digest`，并在跑完后校验它未被改写。

- **CI（云原生构建流水线，`.cnb.yml`）:** 任何分支的 `push` 都触发「自动测试」流水线：
  `dev/setup_ci.sh`（装环境）→ `dev/run_all_checks.sh --verbose`（全量回归），跑在
  `python:3.12-slim` 容器里。本地复现：`bash dev/setup_ci.sh && bash dev/run_all_checks.sh --verbose`。
  **系统依赖清单只有一份：`dev/qt_deps.txt`**，`dev/setup.sh`（云原生开发环境）与
  `dev/setup_ci.sh` 都读它 —— 别在任一处内联写包名，否则会漂移出"本地能跑、CI 跑不了"
  （`python:3.12-slim` 缺 `libdbus-1-3`，`import PyQt6` 直接 `ImportError`，实测踩过）。
  CI 里不需要 Xvfb / noVNC / 中文字体：所有测试脚本都设了 `QT_QPA_PLATFORM=offscreen`；
  noVNC 那套是给人工作验收用的。CI 的像素基线由 `setup_ci.sh` 当场生成，所以那里的
  `--compare` 验证的是**渲染确定性**（同容器两次渲染一致），**不是**"与团队基线一致"。

- **Linting:** No linter configured. Use `python -m py_compile <file>` to sanity-check syntax.
  但**重复定义**有结构性检查：`dev/check_no_duplicate_defs.py`（AST 扫描 `main.py` +
  `src/**` + `dev/*`，约 0.1s，纯标准库）。Python 对同名的后定义**静默覆盖**先定义、
  不报任何错，前者从此是死代码 —— 症状是"改了这段代码却没效果"，而
  `inspect.getsource()` 显示的正是你改的那份，极具迷惑性。`MainWindow` 真实踩过：
  `configure_reference_settings` 定义 3 份、`update_onion_state` 定义 3 份。
  判据：重名且**至少一个定义不带装饰器**才报错 —— 全都带装饰器视为有意的重载
  （`@property` + setter、`@pyqtSlot` 重载、`typing.overload`），必须放行否则误报淹没。
  **例外集合应当恒为空**（曾装过 `src/ui/temp_prop.py`，那个死文件已删除）；
  想加豁免前先问"能不能直接删掉那个文件"。

- **做破坏性验证前必须清字节码缓存:**
  ```sh
  find src dev \( -name __pycache__ -type d -prune -o -name '*.pyc' \) -exec rm -rf {} +
  ```
  pyc 校验用 `(mtime, size)`，秒级精度下切分支/快速往返会碰撞，导致加载**陈旧字节码**
  —— 症状极具迷惑性（`inspect.getsource()` 显示正确源码，行为却是旧的）。
  两个表达式都要有：`__pycache__` 只覆盖常规目录，游离的 `.pyc`（例如被
  `python -m compileall` 平铺生成、或 `__pycache__` 不可写时的遗留）只有第二条能抓到。

  **删不掉必须停手，不能静默继续。** 占用时 `rm` 会失败（Windows 上常见），
  而删不掉又继续跑 = 用旧字节码跑完整轮回归，**全绿但测的不是当前代码** ——
  这正是最难查的一类假通过。`run_all_checks.sh` 已代劳：开头一次、第 2 项
  `compileall` 之后再一次（它会写满 `src/` 与 `dev/`），两次都是**强制清空后校验
  残留为空**，非空则 `exit 2` 中止并列出残留路径。

  不要改用 `PYTHONDONTWRITEBYTECODE=1` 来替代：它只禁【写】不禁【读】，已存在的
  pyc 照样被加载，且 `compileall` 会无视它照样落盘。

## Architecture

PinFrame is a single-window PyQt6 app. `main.py` bootstraps `QApplication` + `MainWindow` (the central controller, ~4580 lines in `src/ui/main_window.py`). `src` is added to `sys.path` by `main.py`, so imports are relative to `src` (e.g. `from ui.main_window import MainWindow`, `from model.project_data import ...`, `from i18n.manager import i18n`).

### Data model (`src/model/project_data.py`)
Two dataclasses form the entire project state:
- `FrameData`: one sprite frame — `file_path`, `scale`, `position`, `rotation`, `aspect_ratio` (X/Y distortion, negative = mirror), `crop_rect`, `is_disabled`, and an ephemeral `target_resolution`. Supports `to_dict`/`from_dict` with project-relative path normalization (so projects stay portable when moved).
- `ProjectData`: the document — `fps`, `width`, `height`, `background_color`, `frames`, plus persisted export settings. `to_json`/`from_json` (file path drives relative-path resolution) are the save/load contract. **All persistence goes through these methods.**
- **`ProjectData.frames` 是绑定活跃数据源的属性，不是第二份副本。** `MainWindow._adopt_project(project)` 调用 `project.bind_frames_provider(self.timeline.get_all_frames)`——这是**绑定发生的唯一地点**：`MainWindow.project` 是只读属性，替换工程对象的唯一途径是 `_adopt_project()`，它把"换对象"与"重新绑定"强制做成一步，二者不可能只发生其一。调用时机：`__init__`（timeline 就位后，以 `self._adopt_project(self._project)` 补绑定）、`_load_from_path` 与 `_reset_project_to_empty`（都必须**先 `timeline.clear()` 再 adopt**）。之后读 `project.frames` 恒为 `TimelineModel` 的实时列表。**绑定后赋值会抛 `RuntimeError`**——旧的 `project.frames = self.timeline.get_all_frames()` 同步仪式已全部删除，不要再写回来。未绑定时（刚 `from_json`、或无 UI 脚本）回退到 `_static_frames`，载入流程正是靠这条路径填充帧。
  - 注意"先 `timeline.clear()`、再 `_adopt_project`"这个次序：`clear()` 之前 timeline 里还是**上一个工程**的帧，提前绑定会让新工程对象短暂地报告旧工程的帧。两种次序的**终态相同**，只有 `dev/verify_project_ownership.py` 的 AST 检查拦得住。
  - 载入路径里推 UI 设置（`fps_spin.setValue` 等）要放在 adopt **之后**：`setValue` 会同步触发 `update_fps`，其守卫 `self.project.fps != fps` 只有在 `self.project` 已是新工程时才为 False。
  - 附带影响：`project.frames` 每次读取都返回**新列表**（`get_all_frames()` 是拷贝）。循环前先存到局部变量（`Exporter` 已这么做），且不要去改这个返回的列表；改它里面的 `FrameData` 对象**是有效的**，会作用到模型上。
- **`FrameData.clone()` 是唯一的帧复制实现。** 不要再手写字段列表复制帧——曾经有 4 份手写克隆，其中 3 份（`duplicate_frame` 与重复帧对话框的 ABAB / AABB 模式）漏拷 `aspect_ratio`，导致重复一个镜像帧时副本丢失镜像状态；第 4 份漏了 `target_resolution`。

### Core services (`src/core/`)
- `transform.py`: 帧变换几何的唯一来源（见上）。Qt-free，有单测覆盖。
- `image_cache.py`: a global singleton `ImageCache` (`image_cache`) shared across all widgets, keyed by absolute file path. Always read images from `image_cache.get(path)` rather than `QImage(path)` directly to avoid reloading. **必须写成 `from core.image_cache import image_cache`**，不可写 `from src.core.image_cache import ...`：两种写法都能解析（仓库根在 `sys.path` 上），但会产生两个不同的模块对象、进而两个独立的单例。
  - **淘汰判据必须是字节，不是张数；顺序必须是 LRU，不是 FIFO。** 上限是字节预算（`_max_bytes`，默认 512 MiB，经 `set_budget()` 调整），命中时 `move_to_end` 续命。张数上限对内存毫无约束（500 张 4K 图 ≈ 32 GB），FIFO 会先踢掉反复访问的那张。
  - **单张超过预算的图要保留，不要"放进即踢"。** `_evict_to_fit` 淘汰时绝不淘汰本次正要放入的那张，否则大图每次访问都重新解码，比不缓存更慢。故 `total_bytes` 允许超过预算。
  - **`get()` 只收 `file_path`**，不要加回 `crop_rect` 之类的参数——缓存 key 只用路径，加了也不参与计算，只会诱导下一个人以为传了就按裁切区分桶。
  - **预算没有设置项，也没有环境变量。** 改默认值的唯一方式是改 `DEFAULT_MAX_BYTES`；运行时改是 `image_cache.set_budget(n)`（目前只有单测用，生产代码零调用）。**不要为此新增 UI 项**：预算调小只是命中率下降、多解码几次，不会出错，而调大才是真风险（OOM），一个"调错了会崩"的旋钮比不给更糟。真需要在某台低内存机器上压一压，改常量重打包即可。
- `history.py`: **线性历史栈**，撤销/重做的唯一真源。改动前必读：
  - **状态模型 `S0 → S1 → … → Sn`。** `entries[k].before` 是 `S(k-1)`、`after` 是 `Sk`，首尾相接成链；`_index` 指向当前状态（`k` = `Sk`，`-1` = 真正的初始 `S0`，由 `_initial_snapshot` 独立保存，栈被裁剪也还原得了）。
  - **撤销/重做可重复任意次。** `undo()` / `redo()` 只移动 `_index` 并返回相邻快照，**不删改任何条目**，故可一路撤到 `-1` 再一路重做回来。
  - **但撤销后一旦有新操作，重做分支即永久丢弃。** `push()` 第一步就是 `del self._entries[self._index + 1:]`。
  - **这是刻意的线性语义，不是缺陷，不要"修"成分支树**（与 Photoshop / Office 一致）。
  - 推论：`jump_to` 直接应用目标条目的 `after`、**不重放**中间步骤，因此快照必须是**完整状态**而非增量补丁。
- `version.py`: **不入库**（见 `.gitignore`），打包时由 `PinFrame.spec` 生成；holds `VERSION`, `REPO_URL`, `BUILD_DATE`。`main_window.py` 的导入是**容错**的：缺该文件不报错，版本回落运行时 `git describe`、URL 回落内置 `DEFAULT_REPO_URL`。不要手工创建或编辑它。

### Rendering (`src/core/transform.py`, `src/ui/canvas.py`, `src/utils/exporter.py`)

`src/core/transform.py` 是**帧变换几何的唯一来源**，预览与导出共用。它刻意不 import PyQt6（`apply_to_painter` 用鸭子类型接受 `QPainter` / `QTransform`），因此几何逻辑无需 `QApplication` 即可单测。

- `resolve_frame_geometry(frame, apply_position=True)` → `FrameGeometry`（裁切、带符号的 `scale_x`/`scale_y`、`flip_h`/`flip_v`、旋转、中心偏移）。`apply_position=False` 供属性面板单帧预览使用——它把帧居中、刻意忽略画布位置。
- `apply_to_painter(target, geo)` 固定 **平移 → 旋转 → 缩放** 的次序。Qt 右乘复合，故图像实际经历 缩放(含镜像) → 旋转 → 平移，与 exporter 的 `resize → transpose → rotate → 定位` 一致。
- `frame_aabb` —— 缩放+旋转后的轴对齐包围盒（属性面板 fit 适配）。
- `scaled_size_floor` —— exporter 的 `int()` 截断，**刻意**与 `FrameData.effective_target_size()` 保持一致，使 UI 显示的"目标分辨率"等于导出实际像素尺寸。
- `composite_origin` —— 变换后位图贴到画布的整数左上角。用 `math.floor`，**不用** `int()`（它在 0 处翻转取整方向，帧移出左/上边缘时平移动画会顿跳 1px），**也不用** `round()`（banker's rounding 与位图宽度的奇偶交替相互干涉，实测把缩放渐变的质心抖动从 0.5px 放大到 1.0px）。

**几何共用，像素化不共用。** `CanvasWidget` 用连续浮点 `QPainter` 变换；`Exporter.compose_frame` 用 PIL 量化（`int()` 尺寸、`rotate(expand=True)`、LANCZOS/BICUBIC）。预览与导出**不可能**逐像素一致——重采样滤波器不同、导出两遍重采样而预览一遍、预览还叠了 `view_scale`。`dev/export_pipeline_precision.md` 记录了实测数据、为什么"让两者一致"是错的目标，以及真正值得修的部分（分数位置的阶梯抖动、缩放渐变的 ±0.5px 交替）该如何用单次仿射变换解决。

`Exporter` 只有一份变换实现（`compose_frame`），三种导出模式共用：`export_iter`（PNG 序列，带进度的 generator）、`export_sprite_sheet`、`export_gif`。`parse_range_string` 把 `"1,3,5-7,10-"` 转成 0 基下标。

**三层缓存刻意不合并**（理由与三层对照表见 `dev/known_issues.md`）：`core.image_cache`（解码后的 QImage，进程级）、网格缩略图缓存（QPixmap，key 含"背景模式 + 缩略图尺寸"这类**纯展示**维度，视图私有）、`SourceImageCache`（`utils/exporter.py`，PIL 原图）。把缩略图那层塞进全局 `image_cache` 是错的——那等于让画布与属性面板的全尺寸图也按缩略图尺寸分桶。

**导出路径：`SourceImageCache` 的生命周期是一次导出。** 三种导出模式各开一个 `with SourceImageCache()`，经 `compose_frame` 的可选参数 `source_cache` 注入。
- **不要跨导出复用**：跨次缓存会让"改了图再导出"拿到旧图，而它的失效时机比缩略图还难判。
- **上限必须设（默认 256 MiB）**，不要做成无限：无上限会把峰值内存从 1 张变成 N 张，几百帧各用各的大图时**比不缓存更容易 OOM**。
- 缓存**未裁切**的原图：安全前提是 PIL 的 crop / resize / transpose / rotate 一律返回新对象、从不在原地修改。改用任何原地 API 都会让多帧互相污染且不报错。

**导出失败必须被看见。** `compose_frame` 返回 `False` 表示"源文件缺失或缩放后尺寸退化为 0"——它**不抛异常**，所以"看有没有报错"发现不了。三个导出方法都不许忽略这个返回值，必须经 `_compose_into_canvas()` 记进 `errors`：
- **`errors` 是可选出参**（`Optional[List[ExportError]] = None`），不传则行为与加该参数前完全一致 —— `transform_baseline.py` 与 `verify_image_cache.py` 都还在不传参地调用，别把它改成必填。
- **缺帧不产出的具体形态，两种产物刻意相反**：PNG 序列**不写**该文件（写空图会让用户以为素材本来就是空的）；精灵表**留空但占位**（否则后续帧整体错位）；GIF **不 append**（补空白帧会同时改变动画时长与节奏）。
- **整批失败（一帧都没渲染出来）必须抛 `ExportFailedError`** —— 只有 GIF 会这样。静默返回会让调用方接着弹"导出完成"而磁盘上没有产物。
- `ExportError.frame_index` 是**工程内 0 基下标**，不是导出批次序号（导出可以只导选中范围，批次序号对不上时间轴）。UI 里显示时才 +1。
- 单帧失败**不**中断整批：缺 3 帧但其余 97 帧导出来是有价值的。由 `MainWindow._report_export_errors()` 在最后汇总弹一次 `QMessageBox`（部分成功也要提示）。

**`aspect_ratio` 的符号是有语义的。** 它是 X/Y 失真系数，**负值编码镜像状态**——`property_panel._mirror_axis` 对水平镜像同时翻转 `scale` 与 `aspect_ratio` 的符号，垂直镜像只翻转 `aspect_ratio`，而 `reset_mirror` 靠符号**组合**反推镜像轴。只有 `0` 是无效值（除零且无语义）；`normalize_aspect_ratio()` 把它归一为 `1.0`，已应用于 `resolve_frame_geometry`、`frame_aabb`、`effective_target_size()`、`FrameData.from_dict`。**绝不可归一负值**——那会让水平镜像静默变成 180° 旋转、垂直镜像直接失效。

### 渲染改动的验证方式

任何触及变换语义的改动都必须过这两个工具（无需 pytest，只依赖 PyQt6 + Pillow）：

```powershell
python dev/test_transform.py                  # 37 个单测，快，解释"为什么"
python dev/transform_baseline.py              # 记录所有渲染路径的像素哈希（改动前跑）
python dev/transform_baseline.py --compare    # 改动后：MAIN_DIGEST 必须不变
```

基线存在 `dev/tmp_baseline/`（**`.gitignore` 中，不入库**），故 `--compare` 比的是"与本机上一次运行"。若 `hashes.json` 缺失，它会**跳过比对、静默建新基线并返回 0** —— 假通过。

`transform_baseline.py` 用一个夹具工程（旋转、镜像、裁切、失真、奇偶源图尺寸）跑 PNG 序列/精灵表/GIF 导出、canvas 普通与栅格化两条路径、属性面板单选与多选预览，再对输出取哈希。其 `EDGE` 组把 `aspect_ratio == 0` **隔离到子进程**——归一之前该用例会 abort 整个进程（PyQt6 把 `paintEvent` 内未捕获异常升级为 `abort()`，实测退出码 `0xC0000409`）。

### Timeline — design (`src/ui/timeline*.py`)
The timeline is a **model/view system**: `TimelineModel` owns the frame list and is the sole authority over frame state; `TimelineWidget` (a `QStackedWidget`) hosts two read-only views — `TimelineListView` (`QTreeView`) and `TimelineGridWidget` (`QListView`). Every mutation broadcasts a `pyqtSignal` (`selection_changed`, `order_changed`, `files_dropped`, `duplicate_requested`, `reverse_order_requested`, `set_reference_requested`, ...) that `MainWindow` connects to actions. **These uplink signals are declared exactly once** — in `ui/timeline_view_signals.py` (`TimelineViewSignals`); `TimelineWidget`, the list view and the grid view each hold *one instance* exposed as `self.signals`, so `MainWindow` connects to `timeline.signals.<name>`. `TimelineWidget._connect_view_signals` forwards each view's signals up to its own — it is an explicit per-signal list on purpose (see its docstring); adding a signal there is a **second place to edit**, and missing it fails silently, so `dev/verify_timeline_view_sync.py` checks the forwarding list stays complete.

**两个视图挂同一个 `TimelineItemModel` 实例**（`ui/timeline_item_model.py`），
并**共享同一个 `QItemSelectionModel`**。两者都**不持有帧数据或顺序** —— 内容由
model 的 `data()` 现算，帧经 `FrameDataRole`（任意列都能取到本行的 `FrameData`）
交给 delegate。

`TimelineModel` **刻意不是** `QAbstractItemModel`：它是一维帧列表，"8 列"与"缩略图"
都只是某种视图的展示形态，把列定义 / 缩略图塞进业务模型会污染导出与存档。适配层
负责把 `TimelineModel` 的语义化信号翻译成 `beginInsertRows` / `dataChanged` /
`beginResetModel`。

两个必须记住的 Qt 事实（都踩过）：
- **`setModel()` 同一个实例并不会共享选中** —— `QAbstractItemView.setModel()`
  会给每个视图各建一个新的 `QItemSelectionModel`。必须显式
  `grid_view.setSelectionModel(list_view.selectionModel())`。
- **选中必须整行生效**（`SelectionFlag.Rows`）。两个视图显示不同列（列表是序号
  列 0、网格是文件名列 2），只选中某一列的话，另一个视图按自己的 modelColumn
  过滤 `selectedIndexes()` 就什么都看不到。

外部代码请直接问模型，或按行操作（`TimelineWidget.setCurrentRow`）。

**Design tenet — one fact, one truth, one write-path, read-only views.** Any per-frame state is *business data owned by the model*, never copied into the view. The model is the single write-path and broadcasts change via a signal; list & grid views are read-only consumers that render straight from the model and repaint on that signal. This keeps both views always consistent and makes any new batch/conditional operation just a loop over the model. Concretely, this philosophy shapes every sub-feature:

- **Selection source of truth** — selected indices are read from the model via `get_selected_indices_from_model()`, never from the view (the old `get_selected_indices_from_current_view` name was misleading and renamed).
- **Disabled state** — `FrameData.is_disabled` is the truth; the only write-path is `TimelineModel.set_frame_disabled(index, is_disabled)`, which broadcasts `frame_disabled_changed(index, bool)`; the adapter model turns that into `dataChanged` for the affected row, and both views repaint automatically (`TimelineWidget._on_frame_disabled_changed` is now a no-op). Because rendering reads the truth, the list delegate fetches `frame_data` via `FrameDataRole` from **its own** index — **not** `index.siblingAtColumn(0).data(UserRole)`; that form was only needed while frames hung off column 0's `UserRole`, and forgetting the sibling hop silently made the disable marker never draw. No `CheckStateRole` copy is ever written.
- **Signal semantics — the model broadcasts frame-change signals with distinct meanings; the adapter model translates each into the matching Qt notification. Never conflate them:**
  - `frames_inserted` / `frames_removed` — set add/remove.
  - **`TimelineModel.clear()` 必须发 `frames_removed(0, 旧行数)`，且先发信号再清数据。** 信号处理器会同步读 `rowCount()`（Qt 适配层的 `beginRemoveRows` 就是），那时若 `_frames` 已空，Qt 断言"要删的行数超过实际行数"并 abort 进程。视图迁到 model/view 后，发信号是视图跟着清空的**唯一**途径（`QTreeView` 没有 `clear()`）。
  - `data_changed(start, end)` — **content changed only; the row→frame mapping is unchanged.** Views repaint those rows (and, for performance, only the *active* view — the inactive one is refreshed on `set_view_mode` switch). **Never use it to carry a reorder**: the view repaints by index and does not re-fetch a new order. (`reverse_frames` / `set_frames_order` must emit `frames_reordered`.)
  - **`frames_reordered()`** — 换序（同一批对象，行数不变）：reverse / drag-sort / `set_frames_order`。
  - **`frames_replaced()`** — 换成**另一批对象**（行数可变的整体替换），行数也可变。`data_changed` 不能用于此：它的语义是"内容变了、映射没变"，而这里连对象都换了、行数也可能变。
    两者对视图的处理相同，都是 `beginResetModel` → 视图全量重取。
  - **`set_frames()` 只发一条信号。** 撤销恢复曾经是 `clear()` + 逐帧 `add_frame()`，即 1 次移除 + N 次插入共 **N+1 条**，每条都让视图做一次布局调整。
  - **撤销恢复默认走 `apply_frames()`，不是 `set_frames()`。** 它先比行数：行数相同就
    逐帧比较、只替换真正不同的行，末尾发**一条** `data_changed(最小行, 最大行)`；
    行数不同（撤销加帧/删帧）才回落 `set_frames()`。于是"撤销一次 scale"只重绘那一行，
    选中不被清空、滚动位置不丢、缩略图按内容缓存全部命中。
    **两条路径都必须 `clone()`，一处都不能少** —— 增量路径克隆变化的那几帧，回落路径
    整体克隆（因为 `set_frames` 是"直接换列表、不克隆"）。漏掉任意一条，模型就会与
    历史快照共享 `FrameData`，此后每次原地编辑都写进历史快照，撤销恢复到的是被后续
    编辑改过的值：**不报错、不崩溃**，只在 redo 时偶尔取到错值。
    实测踩过：只有增量路径写了 clone，10 个用例全绿、15/15 帧共享身份。
    `dev/verify_undo_snapshot.py` 的两条 `test_snapshot_not_polluted__*` 分别钉住这两条路。
- **顺序只存在一份：模型。** `TimelineModel.move_frames(indices, insert_index)` 是顺序的唯一写入入口（坐标系、原位判据、选中跟随都在里面，最后发 `frames_reordered`）。**视图不再拥有顺序**：`dropEvent` 只算出"拖了哪几行、插到哪儿"然后交给模型。曾经视图自己改顺序、再由 `MainWindow.on_order_changed` 回写模型 —— 那等于顺序有两个源，是"切视图后顺序错乱"的根因，已被删除。
  - **撤销快照必须在改模型之前捕获**。顺序改为当场生效后，等到 `order_changed` 时模型已是新顺序，那时再 `_capture_snapshot()` 快照到的就是结果而非前态，撤销会变成空操作。为此视图在调 `move_frames` 前发 `reorder_about_to_happen`，`MainWindow` 连它捕获快照，`on_order_changed` 再落历史。
  - **Insert before/after**: decided by `_calc_insert_before(drop_pos, item_center)` in `timeline_grid.py` (Grid is row-major — Y only picks the row via `indexAt`; X alone decides before/after). `dragMoveEvent` (preview) and `dropEvent` fallback (landing) must call the SAME method so the blue insert indicator matches the final drop. Never reintroduce separate `and`/`or` logic.
  - **State lifecycle**: `startDrag` records the dragged **row numbers** (`self._dragged_rows`) — the `selectionModel` gets mutated by Qt during a drag, so rows must be captured up front; `_clear_drag_state()` resets `_is_dragging`, `_drag_insert_position`, and `_dragged_rows`. Selection follows the model (`move_frames` sets it), so nothing needs restoring by hand after drop.
  - **`_calc_insert_before` / 插入指示器是业务规则，别删。** "Y 只决定落在哪一行、X 单独决定前/后"是网格按行主序排布的真实语义，不是 item-based 的衍生成本。
  - **换序之后必须恢复选中**：`beginResetModel` 会清掉 `QItemSelectionModel`，而业务模型的选中不受影响，两者就此不同步。`TimelineWidget._restore_selection_from_model()` 干这件事 —— 两个视图共享同一个 selectionModel，因此只需恢复一次。

### Panels, dialogs, and settings (`src/ui/`)
- `PropertyPanel`: per-frame transform controls (scale, position, rotation, anchor mode, repeat-move timer). Emits `frame_data_changed`/`relative_move_requested`/`custom_anchor_changed`.
- `slice_dialog.py`: sprite-sheet slicing — rows/cols/grid preview that creates multiple `FrameData` sharing one source image with different `crop_rect`s.
- Settings dialogs: `settings_dialog`, `onion_settings`, `reference_settings`, `raster_settings`, `canvas_border_settings`, `duplicate_dialog`, `export_dialog`, `copy_assets_dialog`, `color_picker`. Each is a modal feeding `MainWindow` state.
- `MainWindow` owns the `ProjectData`, wires every signal, manages save/load (`_save_to_path`, `_load_from_path`, `check_unsaved_changes`), playback (`QTimer`-driven `toggle_play`/`next_frame`/`reverse`), and copy/paste of frame properties.

### i18n (`src/i18n/`)
Singleton `I18nManager` (`i18n`) loaded from `en_US.json` / `zh_CN.json`. Call `i18n.t("key")` for all user-visible strings; add new keys to both JSON files. Resource path resolution handles both dev and PyInstaller (`sys._MEIPASS`) bundles.

### Conventions & gotchas
- Imports are `src`-relative (no `src.` prefix). Run anything with the repo root as CWD.
- **时间轴缩略图刻意不套用帧变换**：`TimelineGridWidget.create_thumbnail` 只做 `crop_rect` 裁切 + `KeepAspectRatio` 缩放，不含旋转/镜像/缩放/偏移。这是有意设计（缩略图展示素材本身的样子，而非合成后的帧），**不要**把它接到 `core/transform.py`。
- **参考帧（`FrameData` 高亮）的真源只有一份：`TimelineModel._reference_frame`。** 加载工程、撤销恢复都只写它；适配层（`TimelineItemModel`）与两个视图**都不得**保留副本 —— 存了就会出现"工程里设了参考帧、界面却不亮"（副本没被改到）。delegate 一律经 `ReferenceRole` 读取。
- **自定义 `ItemDataRole` 的取值必须互不相同**，文件里有 `assert len({FrameDataRole, ReferenceRole, ThumbnailRole}) == 3` 兜底。新增角色时改偏移即可；若忘了，该断言会在 import 阶段炸掉，而不是等到运行时变成"参考帧高亮莫名失效”这种难查的症状。
- **两个视图共享 selectionModel 时，两者的 `SelectionBehavior` 必须一致（都用 `SelectRows`）。** 它们显示的是**不同的列**（列表是序号列 0、网格是文件名列 2）。若只有一方是 `SelectItems`，点击就只选中自己那一列，另一方按自己的列去读 `selectedRows()` 就认为"什么都没选" —— 两个视图对"选中了什么"看法完全相反。表现为"点了帧，属性面板显示未选中"。
- **换 `selectionModel` 会丢弃旧模型上的所有连接。** 用 `setSelectionModel(shared)` 共享选中之后，必须**重新**连接 `selectionChanged` —— 之前在 `bind_model` 里连上的那个已经失效了。见 `TimelineGridWidget.adopt_shared_selection_model()`。
- **`TimelineItemModel.__init__` 不要给 `_frames` 赋值，交给 `bind()`。** 曾经写成先赋值再调 `bind()`，而 `bind()` 开头有"已绑定则直接返回"的防重入判断 —— 于是构造时传入 model 的实例**永远不接线**（`_connect_frames_model()` 一次都没被调用）。症状极具迷惑性：`rowCount()` 实时查模型所以"行数"永远对，但所有模型信号都不转发给视图，视图只在显式 refresh 或 Resize/Show 时才"碰巧"刷新（表现为"加载工程后时间轴空白，拖一下面板才出来"）。这类故障**测不出来**——除非断言信号被转发，或断言 `visualRect(row0)` 在无任何 resize 的情况下有效。
- **`TimelineItemModel.flags()` 必须给出 `ItemIsDragEnabled`。** `view.setDragEnabled(True)` 并不足以启动拖拽 —— `QAbstractItemView.mouseMoveEvent` 还会再查一次 **model 的 flags**，缺这个位 view 就进入 `DragSelectingState`，把手势当成**扩展选区**（表现为"多选后拖不动，一拖选区反而乱变"）。迁移前 `QTreeWidget` 的内建 model 默认带这个位，所以从未暴露。刻意**不给** `ItemIsUserCheckable`（Qt 自带的复选框指示器会画一个我们不想要的 'v'）。
- **判断"顺序是否变化"必须按对象身份，不能用 `==`。** `FrameData` 是 dataclass，`==` 是值相等；工程里完全相同的帧很常见（复制帧、同一张源图切出的相同区域），此时任意排列都"相等"，会被误判成无变化而静默忽略。顺序的语义是"**哪个帧对象**在哪个位置"。
- **`source_image_size()`（`model/project_data.py`）有路径缓存，改磁盘上的源图后必须失效。** 它每次调用都是真实的文件 I/O（`QImageReader` 开文件读头），而时间轴的分辨率列在**每次重绘**都会调它。缓存加在 I/O 边界，因此 `base_size()` 与 `effective_target_size()` 都自动受益。失效时机：外部编辑器改图（`_reload_edited_images`）、替换素材（`_replace_asset`）—— 两处均已调 `clear_source_image_size_cache()`。**新增任何"换掉源文件"的路径都要补上这一句**，它不与 `image_cache` 的失效联动。
- **`project.frames` 已是绑定活跃数据源的属性，恒为实时值**（见上方 Data model）。不要再写 `self.project.frames = self.timeline.get_all_frames()`——绑定后赋值会抛 `RuntimeError`。
- Image loading = `image_cache.get(...)`（注意用 `from core.image_cache import ...`，不要带 `src.` 前缀）。帧变换语义统一在 `core/transform.py`，canvas 与 exporter 共用；两者只在像素化方式上不同。
- **`src/core/version.py` 不入库**，只在打包时由 `PinFrame.spec` 生成 —— never commit it，也别手工创建。开发态**没有这个文件是正常的**：`main_window.py` 用 `try/except ImportError` 容错导入，版本回落运行时 `git describe`。**容错逻辑必须留在入库文件里**（就是 `main_window.py`），写进那个被 ignore 的 `version.py` 会让全新克隆直接 `ImportError`。另：`REPO_URL` **不可置空** —— `QDesktopServices.openUrl(QUrl(""))` 不抛异常，只是什么都不做，"打开仓库"菜单会静默失效，故它有内置兜底 `DEFAULT_REPO_URL`。
- 自动化验证的统一入口是 `bash dev/run_all_checks.sh`（项数与耗时见 Common Commands，
  此处不复制数字，避免两处同时漂移）。
  各脚本分工：`dev/check_no_duplicate_defs.py` 是重复定义的结构性检查（AST，纯标准库），
  `dev/test_transform.py` 是纯 assert 单测（37 个，`core.transform` 几何语义 + 时间轴模型信号契约），
  `dev/transform_baseline.py` 是像素哈希回归，`dev/verify_timeline_view_sync.py` 是时间轴列表/网格视图同步 + 拖拽 + 模型 `move_frames` 顺序契约（含真实 `QDropEvent` 路径，offscreen Qt），
  `dev/verify_grid_view.py` 是网格视图专用（缩略图语义与缓存、序号、插入点、参考帧/禁用态渲染），
  `dev/smoke_reorder.py` 是完整 `MainWindow` 接线链路（加载工程 → 拖拽重排 → 撤销），
  `dev/smoke_reference_frame.py` 是参考帧生命周期 + 洋葱皮抑制的 `MainWindow` 接线（见下条），
  `dev/verify_selection_style.py` 是时间轴选中配色的跨平台一致性（见下条），
  `dev/verify_undo_snapshot.py` 是撤销快照（恢复走增量而非整体替换、快照之间按帧
  共享对象、历史快照不被后续编辑污染 —— 增量/回落两条路径各测一遍），
  `dev/verify_image_cache.py` 是缓存（`image_cache` 的字节预算 + LRU、导出期源图每张只解码一次、共享原图不被污染），
  `dev/verify_project_ownership.py` 是 `ProjectData` 持有契约的结构性检查（AST，纯标准库：
  `project` 只读且无 setter、无 `self.project =` 赋值点、`bind_frames_provider` 唯一且只在
  `_adopt_project` 内、`timeline.clear()` 行号必须早于 `_adopt_project()`、`main_window.py`
  无函数内 import、无跨层私有访问），
  `dev/screenshot.sh` 是人工目视检查。
  **另有三个缺口无任何自动化覆盖**：右键菜单、外部文件拖入、播放时的选中跟随。

- **参考帧有**两份真源**，之间没有信号连接，每个写入点都必须记得同时写**：
  `MainWindow.reference_frame`（画布读它）与 `TimelineModel._reference_frame`
  （时间轴高亮读它，经 `ReferenceRole`）。业务模型的 `reference_changed` 信号
  **无人 connect**，所以"写一处"不会自动同步另一处 —— 漏写的表现是"时间轴亮着
  但预览没有参考帧"，或反过来。`dev/smoke_reference_frame.py` 的每条断言都同时
  检查三处（MainWindow / canvas / 模型）来钉住这一点。
  另外参考帧**不持久化**（`ProjectData.to_json` 里没有这个字段），所以载入工程与
  新建/关闭工程都必须**显式清除两份**（`timeline.clear()` 只清得掉模型那份）。
  写入点清单：设置/取消、删除参考帧所在帧、互斥模式下开洋葱皮、素材移除/替换、
  撤销恢复 —— 新增任何一条都要同时写三处并补进该脚本。

- **时间轴"选中"配色的单一真源是 `src/ui/timeline_selection_style.py`。**
  它同时被三种**互不相干**的机制使用，任一处不引用它就会把同一个选中帧切成
  几种颜色：
    - `main_window.py` 的 **QSS 字符串**（控制列表普通列、网格图标区）；
    - `timeline_grid_delegate.py`（网格底部文字条：它先用 `CompositionMode_Source`
      把 Qt 刚画好的背景清空，再自己填一遍）；
    - `timeline_list.py` 的 `_DisableColumnDelegate`（"禁用"列：它会铺满整格，
      把选中背景整块盖掉）。
  三个必须记住的约束（违反就是 bug，且都真实踩过）：
    - **QSS 选择器要写 `QTreeView, QListView`**。两个视图是 `QTreeView` /
      `QListView`。QSS 的 Type
      Selector 只匹配"该类及其子类"，写 `QTreeWidget` 匹配的是它的**子类**，
      反过来不成立 —— 规则一次都不会生效，选中色随即退回平台调色板（Windows 上
      就是用户可自定义的系统强调色）。这正是"多选看不清哪帧被选中"的根因。
    - **QSS 只认 `/* */` 注释**。`#` 在那里是 ID 选择器，写成 `# 说明` 会让 Qt
      解析失败并**中断其后整个样式表**的解析，所有规则静默失效，而 Qt 只在
      stderr 打一句 "Could not parse stylesheet"，GUI 程序里根本看不见。
      所以关于 QSS 的说明一律写在 qss 字符串**外面**的 Python 注释里。
    - **选中色必须不透明**（alpha=255）。半透明会让底下平台画好的选中色透出来，
      混成第三种颜色。注意 `QImage` 不做预乘，只看 `getRgb()[:3]` **区分不了**
      alpha=200 与 255，检查时必须单独查 `alpha()`。
  另外 **QSS 里那两个颜色是占位符 `@SELECTED_BG@`/`@SELECTED_FG@`**，由
  `apply_to_qss()` 在 `ui/app_theme.py::stylesheet_for()` 里替换（`apply_theme()`
  只负责取用返回值，不参与替换）。不做这步，Qt 解析失败后静默丢弃整条
  规则，选中色又悄悄退回平台值。用占位符而不是 f-string，是因为 QSS 通篇是
  `{}`，整段改 f-string 要转义几百处花括号，必然出错。
- **写 Qt 事件测试时，`QMimeData` 必须挂在 event 上保持引用**（`event._keep_mime = mime`）。`QDropEvent` 只持有裸指针、不接管所有权，局部变量被 GC 后 `mimeData()` 就是悬空指针 → 进程直接 abort，且没有 Python traceback。
- **做破坏性验证（改坏代码、确认测试变红）前，必须先清 `__pycache__`**：`find src -name __pycache__ -type d -exec rm -rf {} +`。用 `cp` 还原源文件后 Python 可能仍加载**被破坏时编译的旧字节码** —— `cp` 只更新 mtime，而 pyc 校验用 `(mtime, size)`，秒级精度下快速往返会碰撞。症状极具迷惑性：`inspect.getsource()` 显示正确源码，函数内打印的比较结果是 `False`，实际却返回 `True`。此外破坏脚本要**先断言目标字符串存在再改**，否则 `str.replace` 静默无操作会让"测试没红"被误读成"测试无效"。
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

