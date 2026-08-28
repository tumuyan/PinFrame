# 架构评审：现存问题与改进方向

> 评审日期：2026-08-20
> 评审基线：`main` @ `849bd23`（feat: 支持外部图像编辑器）
> 性质：**分析文档，未改动任何代码**。所有结论均附 `文件:行号` 证据，可按文末「复核方法」重新验证。

代码规模基线（`find src -name "*.py" | xargs wc -l`）：全项目 15170 行，其中 `main_window.py` 4745 行、`property_panel.py` 1341 行、`temp_prop.py` 911 行、`canvas.py` 902 行。

---

## 目录

- [0. 现有设计中做对的部分](#0-现有设计中做对的部分)
- [P0-1 变换语义有 4 份实现，且零测试保护](#p0-1变换语义有-4-份实现且零测试保护)
- [P0-2 文档状态有两个源：ProjectData.frames vs TimelineModel._frames](#p0-2文档状态有两个源projectdataframes-vs-timelinemodel_frames)
- [P1-3 TimelineModel 不是 QAbstractItemModel，两个视图是 item-based widget](#p1-3timelinemodel-不是-qabstractitemmodel两个视图是-item-based-widget)
- [P1-4 BaseTimelineView 这个「统一接口」事实上是空转](#p1-4basetimelineview-这个统一接口事实上是空转)
- [P2-5 MainWindow 上帝对象](#p2-5mainwindow-上帝对象)
- [P2-6 撤销快照是全量深拷贝 + 全量视图重建](#p2-6撤销快照是全量深拷贝--全量视图重建)
- [P2-7 三层缓存互不知情，外加一个诱导误用的 API](#p2-7三层缓存互不知情外加一个诱导误用的-api)
- [P3 其余问题](#p3其余问题)
- [最小起步建议](#最小起步建议)
- [P0-1 实施记录](#p0-1-实施记录)
- [复核方法](#复核方法)

---

## 0. 现有设计中做对的部分

作为评判基准，以下几处是正确的，重构时**不要破坏**：

- **`TimelineModel` 的「单一写入口」纪律**。`set_frame_disabled()` 作为禁用状态唯一写路径、拒绝往视图写 `CheckStateRole` 副本（`timeline_model.py:307`），这个信条是对的，问题只在于它靠约定而非框架维持（见 P1-3）。
- **`effective_target_size()` 收敛为唯一算法**（`project_data.py:103`），属性面板与时间轴共用，没有各算一遍。
- **i18n 无债**：`zh_CN.json` 与 `en_US.json` 各 479 键，双向差集为空。
- **`exporter.py` 是 Qt-free 的**（仅依赖 PIL + ProjectData + debug_config）——这意味着全项目风险最高的那段逻辑，**今天就能在无显示环境下写单元测试**。
- 关键不变量被写进了 `dev/*.md` 与 `AGENTS.md`，而不是只存在于作者记忆中。

下述问题按「改动杠杆 ÷ 风险」排序。

---

## P0-1｜变换语义有 4 份实现，且零测试保护

> **状态：已完成（2026-08-20）。** 实际是 **9 份**而非 4 份，详见文末
> [P0-1 实施记录](#p0-1-实施记录)。变换语义已收敛到 `src/core/transform.py`，
> 像素输出经哈希验证零变化（`MAIN_DIGEST = 9eb0372879f0aea1` 前后一致）。
> 以下保留原始分析，作为改动动机的记录。

**这是目前最高的风险点**，不是「代码重复」这类审美问题。

同一套 crop → 翻转 → 缩放 → 旋转 → 居中合成，实现了 4 遍：

| 位置 | 实现方式 |
|---|---|
| `canvas.py:285` `draw_frame_normal` | QPainter / QTransform，连续变换 |
| `exporter.py:93`（`export_iter`） | PIL，整数量化 |
| `exporter.py:188`（`export_sprite_sheet`） | PIL，**与上逐行重复** |
| `exporter.py:253`（`export_gif`） | PIL，**与上逐行重复** |

`exporter.py` 内部那段 `# Handle scale and aspect_ratio` 注释出现 **3 次**，三个导出方法各抄一份。因此「改了 `FrameData` 的变换语义要记得同步 exporter」实际上是「要记得同步 4 处」。

### 预览与导出之间已存在结构性差异

不只是理论风险：

- 导出走 `int(src_img.width * abs(scale_x))` —— **截断（floor）而非四舍五入**；
- 旋转用 PIL `rotate(-rotation, expand=True)`，随后按**扩展后位图的中心**计算 `dest_x/dest_y`；
- 而 canvas 是 `translate → rotate → scale` 的连续仿射变换，不做任何量化与位图扩展。

旋转角非 90° 倍数时，两条路径的中心点会差到亚像素乃至 1px 量级。

方向与顺序经核对是一致的（PIL 的 `-rotation` 对应 Qt 的顺时针正向；翻转都发生在旋转之前），所以这不是「错」，但它是「预览所见 ≠ 导出所得」的系统性来源。

> 说明：**未实测具体像素差**，该结论由代码路径推导得出。若要确认，可对同一帧设 `rotation=17°` 分别截图与导出后做像素 diff。

### 建议方向

抽 `src/core/transform.py`，一个纯函数：

```python
def resolve_frame_geometry(frame: FrameData, canvas_w: int, canvas_h: int) -> FrameGeometry:
    """返回 crop 区域、翻转标志、目标宽高、旋转角、目标左上角坐标。"""
```

- canvas 用它构造 `QTransform`；
- exporter 用它驱动 PIL；
- `exporter.py` 中三份变换块合并为一个 `_compose_frame(canvas, frame, project)`。

**这一步的真正价值**：它是整个项目唯一能立刻被单测覆盖的核心逻辑（纯数据进、纯数据出，不需要 `QApplication`）。项目目前零测试，从这里开始比从任何 UI 处开始都划算。

---

## P0-2｜文档状态有两个源：`ProjectData.frames` vs `TimelineModel._frames`

> **状态：已完成（2026-08-21）。** `ProjectData.frames` 改为绑定活跃数据源的属性，
> 8 处手工同步全部删除，绑定后赋值直接抛 `RuntimeError`。设计与使用须知见
> `dev/project_frames_sync.md`（该文档已按新设计改写），回归测试见
> `dev/test_transform.py` 的 5 项 `test_frames_*` / `test_to_json_*`。
> 以下保留原始分析。

该问题已记录在 `AGENTS.md` 与 `dev/project_frames_sync.md`，包括「可能让删除未使用素材误判在用素材并物理删除（数据丢失）」。

**本评审要补充的是：现有缓解手段处在错误的层次。**

现状是靠约定 —— 「每个扫描帧的功能都必须在入口先 `self.project.frames = self.timeline.get_all_frames()`」。这把一个结构问题降级成了一条注释纪律，而它的失败模式是**静默删除用户文件**。新增任何一个遍历帧的功能，都要重新踩一次这个坑。

### 建议方向（从小到大）

1. **最小改动**：把 `ProjectData.frames` 改成 `property`，getter 委托到 model，消灭可写的第二份状态；
2. **更彻底**：`ProjectData` 降级为纯序列化 DTO（只管 JSON 编解码），帧列表由 `TimelineModel` 独占持有，`to_json(frames=...)` 显式传入。

目标是让「忘记同步」**在类型层面不可能发生**，而不是在文档层面被警告。

### 实施结果（2026-08-21）

走了方案 1，但用**依赖注入**而非直接引用解决了层次问题：`ProjectData`（`model/` 层）
不能依赖 `TimelineModel`（`ui/` 层），否则造成 model → ui 反向依赖；改为由 MainWindow
注入一个 `get_all_frames` 回调（`bind_frames_provider`），方向就正了，同时
`to_json` / `from_json` 的持久化契约完全不变。

删掉的 8 处同步仪式：`_save_to_path`、精灵表导出、GIF 导出、`copy_assets_to_local`、
`open_asset_manager`、`_remove_assets_refs`、`_replace_asset`、`delete_unused_assets`。

顺带修好一个当时未被发现的同类缺陷：改画布尺寸时重算所有帧位置的循环
（`main_window.py` 约 1770 行）也读 `project.frames`，此前**上次同步之后新增的帧不会
被重算**；现在自动正确。

一个需要注意的附带影响：`project.frames` 每次读取都返回新列表（`get_all_frames()` 是
拷贝），因此在推导式里反复读会退化成 O(n²)。`Exporter` 的三个导出方法已改为先取一次
快照到局部变量。

---

## P1-3｜`TimelineModel` 不是 `QAbstractItemModel`，两个视图是 item-based widget

**这是时间轴全部复杂度的根因。**

`TimelineModel` 是普通 `QObject`（`timeline_model.py:6`）；两个视图是 `QTreeWidget` / `QListWidget`（`timeline_list.py:84`、`timeline_grid.py:11`）—— 便利控件，天然把数据存在 item 里（`UserRole` 存 `FrameData` 引用、text 存文件名）。因此「视图只读、模型唯一」这个正确的信条，**只能靠人工维持，框架完全不提供帮助**。

代价是可量化的：

- **18 个信号声明了 3 遍**（`timeline.py:16-33`、`timeline_list.py:87-103`、`timeline_grid.py:14-30`），外加 `_connect_view_signals`（`timeline.py:77`）中 17 行手工 connect。加一个右键菜单项要改 3～4 个文件。
  - 根因：`BaseTimelineView` 不是 `QObject`，无法声明信号，所以只能在两个具体视图里各写一份。
- **增删移改都要手工镜像到两个视图**。`timeline.py:163` `_on_frames_inserted` 循环调用两个 `add_frame`，且签名不一致 —— list 用 `index=` 关键字、grid 用位置参数。
- `_block_all_signals` / `_unblock_all_signals` / `_apply_selection_to_view` / `refresh_current_items` / `refresh_all_items` 这一整套同步样板。
- `dev/` 中那一整页拖拽重排不变量（「必须复用原 item 对象」、「`dragMoveEvent` 与 `dropEvent` 必须调同一个 `_calc_insert_before`」）**全部是这个技术选择的衍生成本** —— 因为要绕开 Qt 自带的 item 删除/移动行为以避免丢帧。
- `TimelineViewUtils.extract_frame_data_from_item`（`timeline_base_view.py:97`）需用 try/except 依次探测两种 `data()` 签名，因为 `QTreeWidgetItem.data(col, role)` 与 `QListWidgetItem.data(role)` 不兼容。

### 建议方向

迁移到 `QAbstractListModel` + `QTreeView` / `QListView`，两个视图共享同一个 `QItemSelectionModel`。收益是把已经写对的设计信条从「约定」升级为「框架强制」：

- 选中同步免费（同一个 selection model）；
- 增删移用 `beginInsertRows` / `moveRows`，视图自动跟随；
- 视图零数据副本，delegate 直接 `index.data(role)`；
- 内部拖拽重排退化为 `moveRows`，那一整页不变量文档可以删除。

**工作量最大，收益也最大。建议排在 P0-1 建立起测试之后再动** —— 否则没有任何回归网。

---

## P1-4｜`BaseTimelineView` 这个「统一接口」事实上是空转

11 个抽象方法，两个视图都老实实现了，但调用点情况是：

| 抽象方法 | 全项目调用点 |
|---|---|
| `update_frame_in_view` / `refresh_view` / `clear_view` / `get_item_count` | **0** |
| `add_frame_to_view` / `remove_frame_from_view` / `get_frame_data_at_index` / `select_all_optimized` | 各 1 |

真正被 `timeline.py` 调用的是视图各自的具体方法（`add_frame`、`refresh_current_items`、`refresh_all_items`）。

即：存在**两套并行 API** —— 声明的抽象层（无约束力，但要在两个视图里各维护一份实现）+ 实际在用的具体层。这是最坏的组合：**有维护成本，无抽象收益**。

### 建议方向

要么删掉未使用的抽象方法、让接口只保留真实契约；要么把调用点统一到抽象方法名上。

若走 P1-3 的 `QAbstractItemModel` 方案，这个基类基本可以整体消失。

---

## P2-5｜MainWindow 上帝对象

4745 行 / 160 个方法，同时承担：文档所有权、菜单与 QAction、存取盘、播放定时器、撤销快照、布局预设、属性剪贴板、外部编辑器调用、素材扫描。

两个可观测症状：

- **32 处函数内 `import`** —— 典型的规避循环依赖信号。例如 `EditorSettingsDialog` 在 `main_window.py:19` 顶部已导入，`1726` 行又在函数体内导一遍。
- **2 处跨层访问私有成员**：
  - `main_window.py:724` → `self.timeline._apply_selection_to_view(...)`
  - `main_window.py:3384` → `self.timeline.grid_view._clear_thumbnail_cache()`

  说明 `TimelineWidget` 的公开接口不够用，而非 MainWindow 写得随意。

### 建议方向

不必大重构，按「能否脱离 `QMainWindow` 独立测试」切几块出去：

| 拆出模块 | 职责 | 备注 |
|---|---|---|
| `ProjectIO` | 存取盘、相对路径规整 | 与 `ProjectData` 天然配对 |
| `PlaybackController` | QTimer、播放范围、倒放 | 纯状态机 |
| `LayoutManager` | 布局预设 + QSettings 校验 | 顺带解决 P3 的 key 校验分散 |
| `HistoryCoordinator` | `_capture_snapshot` / `_apply_snapshot` / 合并窗口 | 目前已自成一体，切出几乎无摩擦 |

---

## P2-6｜撤销快照是全量深拷贝 + 全量视图重建

`_capture_snapshot()`（`main_window.py:654`）深拷贝**所有**帧，上限 200 条（`history.py:45`）→ 500 帧的工程约 10 万个 `FrameData` 副本常驻内存。

更麻烦的是恢复路径：`_apply_snapshot_inner()`（`main_window.py:688`）为了还原会 `timeline.clear()` + 逐帧 `add_frame` + `grid_view.refresh_all_items()`。

即：**撤销一次「把 scale 从 1.0 调成 1.1」，代价是整个时间轴视图重建 O(n)**。帧多时撤销会明显卡顿，且 item 对象全部重建（P1-3 的衍生代价在此再次显现）。

### 建议方向

区分两类操作：

- **结构性操作**（增删 / 排序 / 切片）：继续用全量快照；
- **纯属性变更**：走轻量补丁，记录 `(index, field, old, new)`，恢复时只 `replace_frame_at` + `data_changed`。

现有的合并窗口机制（`_open_history_merge_window`，600ms 单次定时器，label 变化即提交）可以直接复用，不需要重写。

---

## P2-7｜三层缓存互不知情，外加一个诱导误用的 API

```
image_cache (QImage, 按路径)  ←→  _thumbnail_cache (QPixmap, 按 path+crop+index)  ←→  exporter (无缓存)
```

四个具体问题：

1. **`image_cache` 的上限是「张数」而非「字节」**（`image_cache.py:22`，`_max_size = 500`）。500 张 4096×4096 RGBA ≈ 32 GB —— 处理大精灵表的工程可以直接把内存打满。淘汰策略是 FIFO 而非 LRU（`image_cache.py:81`），正在反复访问的图可能先被踢出。
2. **`ImageCache.get(path, crop_rect=None)` 的 `crop_rect` 是死参数**：内部 cache key 只用 path（`image_cache.py:40`），全项目 17 个调用点**没有一个**传它。这个签名唯一的作用是诱导下一个人以为传了就会按裁切区缓存。应当删除。
3. **`_thumbnail_cache` 的 key 含 `index`**（`timeline_grid.py:82`）。移动一帧会白白失效其缩略图，重复帧各存一份。key 中的 index 看不出必要性。
4. **exporter 完全绕过缓存**：`Image.open` 出现 3 次，每帧一次。导出一个 100 帧共享同一张精灵表的工程 = 解码同一文件 100 次。

### 建议方向

- 缓存上限改为**字节预算 + LRU**；
- 删除 `get()` 的 `crop_rect` 参数；
- 缩略图 key 去掉 `index`；
- **第 4 点投入产出比最高**：在 `export_iter` 内加一个导出期生命周期的 `{path: PIL.Image}` 局部字典，几行代码，精灵表工程立竿见影。

---

## P3｜其余问题

成本低，建议顺手清掉。

### P3-8 配置持久化三套机制并存

| 机制 | 位置 |
|---|---|
| `QSettings("tumuyan","PinFrame")` 各自 new，共 6 处 | `image_formats.py` ×3、`editor_settings_dialog.py` ×2、`main_window.py` ×1 |
| 自写 JSON | `debug_config.py` → `~/.pinframe/debug_config.json` |
| 存进工程文件 | `ProjectData` 的导出设置字段 |

key 名是散落的字符串字面量，无默认值注册表、无迁移机制。

**建议**：加 `core/settings.py` 集中 key 常量 + 默认值 + 校验。附带好处是布局预设那几个「易损坏、需防御性过滤 `[x, 0]`」的 key（`custom_layout_v_sizes` 等）可以在一处校验，而不是散落在 `main_window` 里做防御。

### P3-9 `version.py` 被提交进仓库，但构建时会被改写

`git ls-files src/core/version.py` 确认它在版本控制内，内容为：

```python
VERSION = "v0.4.1-6-gce17dec"
BUILD_DATE = "2026-01-14T18:53+00:00"
```

与当前 HEAD（`849bd23`）不一致。而 `PinFrame.spec:24-28` 在每次构建时重写该文件。

后果：

1. 每次 `pyinstaller PinFrame.spec` 都会污染工作区（文件被改写并显示为 modified）；
2. 开发态运行时显示的是过期版本号。

**建议**：`.gitignore` 掉 `src/core/version.py`，改为缺失时回退到运行时 `git describe` 或 `"dev"`。文档中「自动生成，永不手改」那句话才能真正成立。

### P3-10 约 1200 行死代码（占全项目 8%）

| 文件 | 行数 | 状态 |
|---|---|---|
| `src/ui/temp_prop.py` | 911 | 无任何 import 引用 |
| `src/ui/assemble.py` | 284 | 无任何 import 引用；内含写死的 `a:/ProjectPython/Image2Frame/...` 绝对路径 |

二者是早期项目路径（`Image2Frame`）遗留的代码生成脚手架。

**真正的风险不是体积** —— 而是 `temp_prop.py` 中有一个**同名 `PropertyPanel` 类**，搜索或 AI 辅助改代码时极易改错文件（本次评审即先撞上了它）。真正在用的是 `src/ui/property_panel.py`。

**建议**：直接删除（git 保有历史）。

### P3-11 导出失败被静默吞掉

`exporter.py:144 / 219 / 282`（三个导出方法各一处）：单帧异常被 `except Exception` 捕获后仅 `print`，导出流程照常「成功」结束。用户得到一个少了若干帧的序列，且不会收到任何提示。

`export_iter` 已经是 generator，顺手 yield 出错误、结束时汇总提示即可。

其他：全项目 5 处裸 `except:`（`main_window.py:169 / 177 / 184 / 2690`，`temp_prop.py:684`）；10 处裸 `print` 未走 debug 框架（`exporter.py` 4、`i18n/manager.py` 2、`main_window.py` 1、`timeline.py` 1）。

---

## 最小起步建议

若只做三件事：

1. **抽 `core/transform.py` 纯函数，并给 exporter 补第一批单测**（P0-1）。唯一能立刻上测试的地方，守住的是最高风险（预览/导出分叉），顺手把 exporter 里 3 份重复合成 1 份。
2. **消灭 `ProjectData.frames` 双源**（P0-2）。这是唯一一个失败模式为**删除用户文件**的问题。
3. **`.gitignore` 掉 `version.py` + 删掉 `temp_prop.py` / `assemble.py`**（P3-9、P3-10）。十分钟，立刻降噪。

`QAbstractItemModel` 迁移（P1-3）收益最大，但**建议放在第 1 步有了测试之后**再动 —— 它会同时化解 P1-4、大幅简化 P2-6，以及删掉 `dev/` 里那整页拖拽不变量文档。

---

## P0-1 实施记录

> 完成日期：2026-08-20。以下是评审结论落地时的实际发现与偏差，供后续几项参考。

### 与原始分析的偏差

**实际是 9 份实现，不是 4 份。** 原分析漏掉了 canvas 内部的另外 3 处与
property_panel 的 2 处：

| 位置 | 用途 | 除零保护 |
|---|---|---|
| `canvas.py:292` | 正常预览绘制 | ✗ |
| `canvas.py:420` | 栅格化 bbox（`QTransform.map` 四角） | ✗ |
| `canvas.py:459` | 栅格化缓冲区绘制 | ✗ |
| `canvas.py:643` | 选中轮廓绘制 | ✗ |
| `exporter.py:93 / 188 / 253` | 三种导出模式 | ✗ |
| `property_panel.py:1239 / 1265` | 单选 / 多选预览 | **✓** |
| `project_data.py:120` | `effective_target_size()` | ✗ |

`property_panel.py:1242` 原本还留着作者自己写的注释 `# matches canvas` —— 这份重复
是被意识到但未被消除的。三份 exporter 变换块经逐行 diff（忽略空白与注释）确认**完全
等价**，因此三合一是纯重构。

### `aspect_ratio == 0` 的真实后果比预计严重

原分析以为是"渲染不一致"，实测是**进程崩溃**：

| 路径 | 归一前 | 归一后 |
|---|---|---|
| canvas | **进程 abort**（`0xC0000409`） | 正常渲染 |
| PNG 序列导出 | 静默产出 **0 个文件**，流程报告成功 | 正常产出 |
| 精灵表导出 | 产出文件但该格**空白** | 正常合成 |
| 属性面板 | `ZeroDivisionError` | 正常显示 |

canvas 崩溃的机制：`paintEvent` 抛 `ZeroDivisionError`，而 PyQt6 把虚函数内未捕获
异常升级为 `abort()`。因为每次重绘都会触发，**一个手改过的工程 JSON 只要写了
`aspect_ratio: 0`，打开即崩**。

属性面板那处值得注意：它自己的变换有 `aspect != 0` 保护，却仍然崩——根源是
`project_data.py` 的 `effective_target_size()` 无保护，显示目标分辨率时先撞上它。
所以修复点不止共享函数一处，`from_dict` / `effective_target_size` / `frame_aabb`
都要覆盖。

### 关键决策：只归一 0，负值必须保留

一度考虑过"`aspect_ratio <= 0` 一律按 1 计算"，**这会破坏镜像功能**。镜像状态正是
编码在符号上（`property_panel._mirror_axis`）：

| 状态 | scale | aspect | `scale_y = scale/aspect` | 实际效果 | 若把 ≤0 归一为 1 |
|---|---|---|---|---|---|
| 正常 | 1 | 1 | 1 | 无翻转 | 无翻转 ✓ |
| **V 镜像** | 1 | −1 | −1 | 垂直翻转 | **镜像消失** ✗ |
| **H 镜像** | −1 | −1 | +1 | 仅水平翻转 | **水平+垂直 = 180° 旋转** ✗ |
| H+V | −1 | +1 | −1 | 水平+垂直 | 不变 ✓ |

H 镜像那行最危险：不是失效，而是**静默变成 180° 旋转**，已存工程一打开就错。此外
`reset_mirror` 靠符号**组合**反推镜像轴，抹掉符号连复位按钮也会失效。

最终规则：**仅 `0`（及 NaN / 非数）归一为 `1.0`，负值原样保留。** 已由
`dev/test_transform.py::test_normalize_preserves_negative` 等 6 个镜像语义测试钉住。

### 顺带修掉的缺陷：`image_cache` 有两个实例

`canvas.py` 与 `property_panel.py` 写的是 `from src.core.image_cache import ...`，
其余模块写 `from core.image_cache import ...`。两种写法都能解析（仓库根在 `sys.path`
上），但产生两个不同的模块对象，实测 `a is b` 为 `False`、往一个存图另一个 `size`
仍为 0。后果：

- 内存翻倍（两个实例各自上限 500 张），每张图被解码两次；
- `main_window._reload_edited_images` 里的 `image_cache.remove(p)` 清的是实例 A，
  而 canvas / property_panel 读的是实例 B，"定向失效"形同虚设。

注意：外部编辑器改图后画布**仍能刷新**，因为 `canvas.refresh_resources()` 对实例 B
做的是 `clear()` 全量清空，碰巧掩盖了这个问题。已统一为无前缀写法。

### 收尾清理（第二轮）

首轮收敛完成后复查，又发现三项残留，均已处理：

**1. 我在首轮引入的死 API。** `core/transform.py` 里的 `centered_rect` 与
`frame_corners` 生产代码零调用——正是本文 P1-4 批评的"有成本无收益的抽象层"，而且
`CLAUDE.md` / `AGENTS.md` 里还错误地声称 `frame_corners` 供 canvas 栅格化缓冲区使用。
已删除函数、对应的 3 个测试，并修正两份文档。教训：**收敛时只创建有真实调用点的
函数**，"以后可能有用"就是 P1-4 的成因。

**2. `FrameData` 克隆有 4 份手写实现，其中 3 份漏字段（真 bug）。**

| 位置 | 缺失字段 | 用户可见后果 |
|---|---|---|
| `main_window.duplicate_frame` | `aspect_ratio` | 重复镜像帧 → 副本丢失镜像 |
| 重复帧对话框 ABAB 模式 | `aspect_ratio` | 同上 |
| 重复帧对话框 AABB 模式 | `aspect_ratio` | 同上 |
| `timeline_model.duplicate_frames` | `target_resolution` | 影响较小（该字段是 ephemeral） |

漏 `aspect_ratio` 的后果与"把负值归一"同类：垂直镜像帧的副本**镜像直接消失**；水平
镜像帧的副本因 `scale` 仍为负而 `scale_y` 由 +1 翻成 −1，**变成 180° 旋转**。

已新增 `FrameData.clone()` 作为唯一克隆实现，5 处调用点全部改为调用它
（`main_window._clone_frame` 退化为薄封装以保留既有调用点）。新增 3 个测试，其中
`test_clone_copies_every_field` 用 `dataclasses.fields()` 遍历，将来给 `FrameData`
加字段而忘记更新 clone 时会直接失败。

**3. `property_panel.py` 的两处 `scale / aspect_ratio` 除法——已加除零保护，但
刻意不做收敛。**

一度想把它们并入 `effective_target_size()`，核查后发现**不能**：

- `on_t_w_changed` 那处**刻意不取绝对值**，`current_h` 的符号被 `> 0` 当作判据——
  垂直镜像帧 (scale>0, aspect<0) 会得到负值从而跳过 `aspect_ratio` 重算，避免改写掉
  镜像状态。若换用带 `abs()` 的 `effective_target_size()`，**垂直镜像会在用户改目标
  宽度时被静默清除**。
- `on_crop_changed` 那处用的是**旧**裁切尺寸反算（`crop_rect` 正要被改写），而
  `effective_target_size()` 读的是当前 `crop_rect`，语义上无法替代。

所以只加了 `normalize_aspect_ratio()` 防除零（对所有合法输入行为不变），并把"为什么
不能收敛"写进代码注释。**这是"记录下来的重复"，不是"消除了的重复"**——如实标注。

### 导出取整：从"方案 B"到实测收窄

原本计划把 `dest` 的 `int()` 换成 `round()`。实测数据推翻了这个方案：
`round()`（banker's rounding）的进位方向取决于相邻整数的奇偶，而位图宽度在缩放渐变
中本身就在奇偶交替，两者干涉把质心抖动**从 0.5px 放大到 1.0px**。

同时确认：居中公式 `画布中心 − 位图宽/2 + 偏移` **本身是精确正确的**，奇数宽度位图的
±0.5px 偏差是"整数贴图无法表达半像素落点"的架构限制，任何取整函数都修不掉。

最终只做了唯一站得住的部分：`int()` → `math.floor()`，收进
`core.transform.composite_origin()`。对 `dest >= 0` 输出完全不变，只修 `int()` 在 0 处
翻转取整方向导致的顿跳（帧移出画布左/上边缘时）。配 4 个测试，其中
`test_composite_origin_is_translation_consistent` 遍历 position −60..+60 断言落点步长
恒为 1。

完整的实测数据、为什么"消除预览/导出亚像素差异"是错的目标、以及真正的解法（单次
仿射变换）见 **`dev/export_pipeline_precision.md`**。

### 有意未做的部分

- **尺寸的 `int()` 截断与 `expand=True` 旋转保持原样**。改动会改变导出产物，且必须
  同步调整 `effective_target_size()`，否则属性面板显示的"目标分辨率"会与实际导出
  尺寸不符。`test_scaled_size_matches_effective_target_size` 把这个不变量钉住了——
  将来若单方面改取整，该测试会先失败。这属于 `export_pipeline_precision.md` 的范围。
- **时间轴缩略图未纳入统一**。`create_thumbnail` 只做裁切 + `KeepAspectRatio` 缩放，
  故意不含旋转/镜像/偏移（缩略图展示素材本身，而非合成后的帧）。若接进共享函数，
  缩略图会开始跟着旋转——属功能退化。

### 留下的验证资产

| 文件 | 作用 |
|---|---|
| `dev/test_transform.py` | 25 个单测，锁定几何语义（顺序、符号、镜像编码、取整约定） |
| `dev/transform_baseline.py` | 7 条渲染路径的像素哈希回归；`--compare` 一眼看 MAIN_DIGEST |

两者分工：单测跑得快、解释"为什么"；基线证明"没变"。基线的 `EDGE` 组把
`aspect_ratio == 0` 隔离到子进程，否则 abort 会把整个基线带走。

### 后续几项的顺序建议不变

P0-1 的测试资产现在可以为 P1-3（`QAbstractItemModel` 迁移）提供部分回归网，但基线只
覆盖渲染输出、不覆盖时间轴交互，动 P1-3 前仍需补交互层的验证手段。

---

## 复核方法

本文全部数字可用以下命令重新验证（repo 根目录，Git Bash）：

```bash
# 代码规模
find src -name "*.py" | xargs wc -l | sort -rn | head -20

# P0-1 变换块重复次数 / 三个导出方法
grep -c "Handle scale and aspect_ratio" src/utils/exporter.py
grep -n "    def " src/utils/exporter.py

# P1-3 信号三处声明
grep -c "pyqtSignal" src/ui/timeline.py src/ui/timeline_list.py src/ui/timeline_grid.py

# P1-4 抽象方法的实现数与调用点数
for m in add_frame_to_view remove_frame_from_view update_frame_in_view \
         refresh_view clear_view get_item_count select_all_optimized \
         block_selection_signals get_frame_data_at_index; do
  printf "%-28s def:%s call:%s\n" "$m" \
    "$(grep -rl "def $m" src/ui/timeline_list.py src/ui/timeline_grid.py | wc -l)" \
    "$(grep -rn "\.$m(" src/ | wc -l)"
done

# P2-5 MainWindow 规模与函数内 import
grep -c "    def " src/ui/main_window.py
grep -c "^        from \|^            from \|^        import " src/ui/main_window.py

# P2-7 crop_rect 死参数（应为 0 个调用点传参）
grep -rn "image_cache.get(" src/

# P3-8 QSettings 散落点
grep -rn "QSettings(" src/

# P3-9 version.py 是否受版本控制
git ls-files src/core/version.py && cat src/core/version.py

# P3-10 死代码是否真无引用
grep -rn "temp_prop\|assemble" src/ main.py PinFrame.spec

# P3-11 吞异常与裸 print
grep -rn "except:" src/ --include=*.py
grep -rn "^\s*print(" src/ --include=*.py | grep -v debug_config.py

# i18n 键一致性（应为双向空集）
python -c "import json;a=json.load(open('src/i18n/zh_CN.json',encoding='utf-8'));b=json.load(open('src/i18n/en_US.json',encoding='utf-8'));print(len(a),len(b),set(a)-set(b),set(b)-set(a))"
```
