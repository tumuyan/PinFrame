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
- [P1-3 实施计划](#p1-3-实施计划)
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

> **状态：未实现，且未过时（复核日期 2026-08-29，基线 `main` @ `2718d99`）。**
> 原文事实逐条复核**全部成立**，仅行号位移（`TimelineModel` 现 `timeline_model.py:5`、
> `_connect_view_signals` 现 `timeline.py:78`、`_on_frames_inserted` 现 `timeline.py:200`
> 且签名不一致一字未改、`extract_frame_data_from_item` 仍 `timeline_base_view.py:97`）。
>
> **成本比评审时更高**，新增两处衍生债务：`_view_in_sync_with_model`
> （`timeline.py:108-136`，存在的前提就是"视图持有数据副本会变陈旧"）与
> `timeline_grid_delegate.py`（570 行，`:34`/`:124` 走 `item.data()`）。时间轴已达
> **3412 行 / 7 文件**。另有两处迁移阻力需单独计价：列表 `setColumnCount(8)`
> （`timeline_list.py:109`）意味着要做多列 model，外部文件拖入（`mimeData().hasUrls()`
> 分支）在两视图各 3 处需统一进 model 的 `dropMimeData`。
>
> **前置条件部分满足**：`dev/verify_timeline_view_sync.py` 提供 4 个 offscreen 交互
> 回归测试。但它们断言的是"视图与模型一致"——迁移后该性质由框架保证、恒真，
> 因此迁移时需**改写**（转去断言 model 与 `QItemSelectionModel` 契约）而非直接复用。
> 实施顺序见文末 [P1-3 实施计划](#p1-3-实施计划)。

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

## P1-3 实施计划

> 起始日期：2026-08-29，基线 `main` @ `2718d99`。本节记录分三片推进的**计划与每片的
> 实际偏差**（沿用 P0-1 实施记录的写法，做完一片补一片）。

一次性替换 3412 行风险过高，改为三片推进。但**不能停在第 1 片** —— 半途停下会同时
承担旧成本与新成本，正是 P1-4 批评的"有维护成本、无抽象收益"。

### 第 1 片：模型成为顺序的唯一权威（原方案已废弃）

> **原方案（"视图零数据副本"）已废弃，原因记录在此以免重犯。**
>
> 原计划让所有取数点绕开 item、按 index 直接问模型，并让 item 的 `UserRole` 只挂索引。
> **这行不通**：item 的 `UserRole` 挂的是 `FrameData` **引用**而非副本，它承载的语义是
> **"第 i 行是哪个帧"，即视图自己的排列顺序**。而顺序是视图的**合法状态** —— 内部拖拽
> 直接对 item 做 `takeTopLevelItem`/`insertTopLevelItem`（`timeline_list.py:450-455`），
> 模型并不知情，之后由 `main_window.on_order_changed`（`main_window.py:3030-3043`）把视图
> 顺序**回写**给模型。若让 `get_frame_data_at_index()` 改走模型，读到的将永远是模型顺序，
> 视图→模型的回写恒为空操作，**拖拽排序直接失效**。
>
> 教训：真正该消灭的不是"item 持有帧引用"，而是**"视图拥有 index→frame 映射"这件事
> 本身**。这只有第 2 片能做到。

修订后的第 1 片 —— 不动取数方式，改为把**顺序**的权威从视图搬到模型：

- 视图的拖拽/重排不再直接搬 item，而是调 `model.move_frames(...)`；模型改完发
  `frames_reordered`，视图按模型重建。**视图从此不再拥有顺序。**
- 于是可删 `_view_in_sync_with_model`（`timeline.py:108-136`）—— 它防御的"视图可能陈旧"
  这一前提不复存在；
- 于是可删 `main_window.on_order_changed` 里的视图→模型回写（`main_window.py:3030-3052`）；
- 顺手统一 `add_frame` 签名（list 用 `index=` 关键字、grid 用位置参数，`timeline.py:209-210`）。

**代价**：拖拽后视图全量重建（缩略图重算）。可接受 —— 切换视图时本就要重建。
**风险**：这段逻辑在 `AGENTS.md` 里记了一整页不变量，而 `verify_timeline_view_sync.py`
只覆盖 `set_frames_order` 的**结果**、不覆盖真实拖拽路径。**因此先补测试再改。**

#### 第 1 片实施结果（2026-08-29，已完成）

实际改动与计划有三处偏差，都值得记下来。

**1. 撤销快照的时序 —— 计划时完全没预见到。**

顺序改为"拖拽当场生效"后，`MainWindow.on_order_changed` 再调 `_capture_snapshot()`
抓到的是**新**顺序，撤销静默变成空操作（不报错、不崩溃，就是没效果）。为此新增
`reorder_about_to_happen` 信号：视图在调 `move_frames` **之前**发出，MainWindow 连它
捕获快照，`on_order_changed` 再落历史。

`dev/smoke_reorder.py` 里留了一条反证：把该信号的处理器换成 no-op 后，拖拽就不再产生
任何撤销记录 —— 以此证明这条接线不是多余的。

教训：**任何"状态改为当场生效"的改动，都要回头检查撤销快照是在哪个时刻抓的。**
原来的回写式流程碰巧是对的（回写发生在 `on_order_changed` 里、那时模型还没变），
改成直接生效就把这个前提悄悄拆掉了。这类失效没有报错，只能靠断言防。

**2. 视图不重建，改为按模型重排 item。**

计划写的是"视图按模型重建"。实测发现 `grid.clear()` 会连带清空缩略图缓存
（`timeline_grid.py` 覆写了 `clear()`），重建要为每一帧重新解码一次源图 —— 拖一次就
全量重算一遍。因此新增 `sync_order_from_model()`：take 出来、按模型顺序插回，**复用
原 item 对象**。顺带把 `AGENTS.md` 里"必须复用原 item 对象"那条不变量收拢到了一处。
`_rebuild_*_view` 保留，作为 item 数与模型不符时的兜底。

**3. `set_frames_order` 退化为仅测试使用。**

生产代码里它唯一的调用点就是被删掉的那处回写。它现在是 `move_frames` 的特例（整体
替换），保留只因 `dev/test_transform.py` 用它锁 `frames_reordered` 的信号契约。
第 2 片收尾时应评估是否一并删除（连同依赖它的 2 个测试一起改）。

#### 净效果

- 删约 130 行（两处"搬 item"、视图→模型回写、`_view_in_sync_with_model`、拖拽后的
  选中恢复样板），增约 120 行（`move_frames`、`sync_order_from_model` × 2、信号接线）。
- **行数几乎没减，但顺序从两个源变成一个源。** 行数不是本片的指标，不变量的持有者才是。
- 新增 10 个测试（6 个模型层 + 4 个走真实 `QDropEvent` 的拖拽路径）+ 1 个冒烟脚本。
  拖拽路径此前**完全没有**自动化覆盖 —— 这是本片最实在的收获。
- 回归：`verify_timeline_view_sync.py` 14/14、`test_transform.py` 37/37、
  `transform_baseline.py --compare` 的 MAIN_DIGEST 前后一致。

### 第 2 片-a：列表视图迁到 model/view（2026-08-29，已完成）

**关键设计决定：`TimelineModel` 不改成 `QAbstractItemModel`，改为加一层 Qt 适配层。**

原计划把 `TimelineModel` 本身改成 `QAbstractItemModel`。实际动手后否掉了：
它是一个**一维帧列表**，而"8 列"只是列表视图的一种展示形态。把列定义塞进业务
模型，会让导出、存档、`ProjectData` 这些与表格无关的使用方被迫理解表格坐标。

改为新增 `ui/timeline_item_model.py` 的 `TimelineItemModel(QAbstractTableModel)`：
每行回头问 `TimelineModel`，把它的语义化信号翻译成 `beginInsertRows` / `dataChanged` /
`beginResetModel`。本类**不持有任何帧数据**（缓存一份就等于重新引入第二份状态）。

**两个计划时没预见到的问题：**

**1. `data()` 的高频调用暴露了一个既有的 I/O 热点。**

`source_image_size()` 每次都 `QImageReader(file_path)` + `os.path.exists()` —— 是真实的
**文件 I/O**。item-based 时每帧只在刷新时算一次并缓存到 item；迁到 model/view 后
`data()` 在**每次重绘**（含滚动）都被调用，一屏重绘就是几十次 open/read/close。

修法是把缓存加在 **I/O 边界**（`source_image_size` 本身）而不是调用方，这样
`base_size()` 与 `effective_target_size()` 都自动受益，且不破坏"目标分辨率只有一个
算法来源"这条不变量。失效时机：外部编辑器改图、替换素材（两处均已接上
`clear_source_image_size_cache`）。

**这条不是迁移引入的缺陷，是迁移**暴露**的既有缺陷** —— 大工程下刷新一次时间轴
本来就要做 500 次这样的 I/O，只是不频繁所以没被察觉。**

**2. `TimelineModel.clear()` 不发信号 —— 模型信号契约的缺口。**

原流程靠调用方手工 `view.clear()` 清视图。列表视图变成 `QTreeView` 后没有 `clear()`
方法，直接 `AttributeError`。修法是让 `clear()` 发 `frames_removed(0, count)`，
且**必须先发信号再清数据**：信号处理器同步读 `rowCount()`，若那时 `_frames` 已空，
Qt 会断言"要删的行数超过实际行数"并 abort。

**顺带修掉的一个既有缺陷**：参考帧高亮原先是 `item.setText(2, prefix + text)` 加
`text.replace(prefix, "")` 复原 —— 若文件名本身含该前缀字符串，**会被误删**。现在
前缀由 `data()` 现算，天然幂等。冒烟里加了"连设两次同一个参考帧，前缀只出现一次"
的断言。

#### 净效果

- 列表视图删约 220 行（`add_frame` 的 8 列文本填充、`update_item_display`、
  `sync_order_from_model`、`flatten_tree`、item 兼容外壳），新增适配层约 230 行。
- `TimelineWidget` 里"事件 → 手工镜像到两个视图"的逻辑**对列表视图全部消失**
  （`_on_frames_inserted/removed/moved/data_changed/frame_disabled_changed`）。
- 外部调用点（播放列表、多选判断、切换视图恢复选中）改为直接问模型，不再绕 item。
  `update_playlist` 从 27 行（按视图类型分叉 + item 排序 + 掏 UserRole）降到 12 行。
- 回归：`verify_timeline_view_sync.py` **15/15**（新增 `test_clear_notifies_views`）、
  `test_transform.py` 37/37、`transform_baseline.py --compare` MAIN_DIGEST 前后一致、
  `smoke_reorder.py` 全链路通过（新增 8 列映射 / 属性刷新 / 禁用切换 / 参考帧高亮断言）。
- 真实 GUI 冒烟：offscreen 下渲染两种视图各抓一张位图，8 列内容与禁用图标均正常。

### 第 2 片-b：网格视图迁到 model/view（2026-08-29，已完成）

网格视图已迁到 `QListView`，与列表视图挂**同一个** `TimelineItemModel` 实例，因此
两个视图共享同一个 `QItemSelectionModel` —— **选中只有一份**，P1-3 最大的一条收益
在此兑现。

**实施时偏离原计划的两处：**

1. **缩略图走自定义 `ThumbnailRole`，不走 `DecorationRole`。** 原计划用
   `DecorationRole`，但本 model 由两个视图共享，而 `DecorationRole` 会被 Qt 的默认
   delegate 直接画出来 —— 列表视图每一格都会冒出一个缩略图图标。自定义角色只有主动
   去读它的网格 delegate 才拿得到，列表侧完全无感。

2. **缩略图留在网格视图里算，不进业务模型。** 它是网格的**展示形态**（尺寸、背景
   模式都是网格的设置），塞进 `TimelineModel` 会污染导出与存档 —— 与"列定义不进
   业务模型"是同一个理由。改为由网格注入 `thumbnail_for_row` 给适配层，经
   `ThumbnailRole` 递给 delegate。

#### 一个反直觉的 Qt 陷阱（差点让"共享选中"名存实亡）

**两个视图 `setModel()` 同一个 model 实例，并不会共享选中。**
`QAbstractItemView.setModel()` 会给每个视图**各建一个新的** `QItemSelectionModel`，
必须显式 `grid_view.setSelectionModel(list_view.selectionModel())`。

我一开始就漏了这句 —— 视觉上两个视图看起来都正常，但选中仍是两份，切换视图靠的还
是旧的同步仪式。这条由 `test_both_views_share_selection_model` 直接断言对象同一性
来守住。

**配套的第二层坑**：即便共享了 selectionModel，**若选中只落在某一列上，另一个视图
仍看不到**。两个视图显示的是不同的列（列表是序号列 0、网格是文件名列 2），
`get_selected_indices()` 按自己的 modelColumn 过滤 `selectedIndexes()`，于是"只选中
第 0 列"在网格眼里是空的。选中必须整行生效（`SelectionFlag.Rows`）。
这条由 `test_selection_visible_from_both_views` 守住。

#### 净效果

- 网格视图删约 300 行（`add_frame` 的缩略图/文本填充、`update_frame`、
  `sync_order_from_model`、`update_item_display` 的 item 级改写）。
- `TimelineWidget` 里"事件 → 手工镜像到两个视图"的逻辑**全部消失**；
  `_on_frames_reordered` 从 20 行降到 2 行（只剩"reset 会清 selectionModel，故恢复
  选中"）；`set_view_mode` 不再需要任何选中同步。
- 删掉最后的 item 兼容外壳 `extract_frame_data_from_item`（曾是唯一还依赖
  `QTreeWidgetItem` / `QListWidgetItem` 的地方）。
- 顺带修掉：`TimelineWidget.update_item_display` 是死代码，且其 list 分支指向一个
  迁移中已删除的方法 —— 一旦有人调用就会 `AttributeError`。
- 网格的 `_calc_insert_before` / 插入指示器等拖拽细节**保留** —— 那是"网格按行主序
  排布"的真实业务规则，不是 item-based 的衍生成本。
- 回归：`verify_timeline_view_sync.py` **20/20**（新增共享选中 2 条）、
  `verify_grid_view.py` **13/13**、`test_transform.py` 37/37、
  `transform_baseline.py --compare` MAIN_DIGEST 一致、`smoke_reorder.py` 通过。
- 真实 GUI：两种视图各抓一张位图，缩略图、序号、选中高亮均正常。

#### 破坏性验证记录（第 2 片-b）

| 破坏 | 被哪个用例捕获 |
|---|---|
| 去掉显式 `setSelectionModel(share)` | `test_both_views_share_selection_model`、`test_selection_visible_from_both_views`、`test_rebuild_selection_list_active` |
| 选中不带 `Rows`（只选自己那列） | `test_selection_visible_from_both_views` |
| 不注入缩略图 provider | `verify_grid_view` 的 7 个缩略图用例 |
| 缩略图忽略 `crop_rect` | `test_thumbnail_reflects_crop_rect` |
| 缩略图套用 `rotation` | `test_thumbnail_ignores_frame_transform` |
| 清除参考帧时不还原 | `test_reference_frame_highlight_toggles_off` |

### 第 3 片：收尾（2026-08-29，已完成）

**1. 删 `BaseTimelineView`（P1-4 一并解决）** —— `src/ui/timeline_base_view.py` 整个文件删除。

它剩下的东西只有两类：11 个抽象方法在两个视图里都退化成了空实现或三行转发，以及一个
0 调用点的便利方法 `get_selected_frame_data_list`。同文件的
`TimelineViewUtils.extract_frame_data_from_item`（双签名 try/except 探测）也随之删除 ——
两个视图都已没有 item 对象。连带删掉因它而存在的 `TimelineWidget` 兼容外壳。

**顺带清掉的一批死代码**（都是"迁移后退化为空、但没人删"）：两视图的
`add_frame_to_view` / `remove_frame_from_view` / `update_frame_in_view` / `refresh_view` /
`get_selected_items` / `sync_order_from_model`；`TimelineWidget` 的 `move_frame` /
`move_frames` / `load_frames` / `add_frame_to_current_view` / `remove_frame_from_current_view`；
`TimelineModel.move_frame`（单数）与它的辅助方法 `_update_selection_after_move`。

**还删掉一个没人发的信号**：`frames_moved(from, to, count)` 的唯一发射方就是上面那个
`move_frame`（单数）。留着它只会误导后来者 —— 所有换序现在都走 `move_frames()`，
发的是 `frames_reordered`。

**2. P2-6 撤销恢复：整体替换，一条信号。**

原计划写的是"退化为 `data_changed`"，实际**没有**用 `data_changed` —— 它的语义是
"内容变了、行到帧的映射没变"，而撤销恢复连帧对象都换了、**行数也可能变**（撤销加帧 /
删帧）。硬套 `data_changed` 就是又一次语义错配。

改为新增 `frames_replaced` 信号 + `TimelineModel.set_frames()`：替换整个列表，只发一条。
`_apply_snapshot_inner` 从 `clear()` + N 次 `add_frame()`（1 次移除 + N 次插入共 **N+1 条**，
每条都让视图做一次布局调整）改成一次 `set_frames()`。实测一个 16 帧工程：17 条 → 1 条。
`grid_view.refresh_all_items()` 也不再需要 —— 整体替换本就让视图全量重取。

**3. 删拖拽不变量文档 —— 只删过时的，保留业务规则。**

`AGENTS.md` 那一页里，真正该删的是 item 时代的实现约束（`takeItem` 搬 item 的顺序、
"rebuild 必须显式传 mode 否则会写串视图"等）。但 `_calc_insert_before` 的"Y 只选行、
X 决定前后"是网格按行主序排布的**真实业务语义**，不是衍生成本 —— 保留，并加注释说明
别删。新增了两条迁移后的新事实：`beginResetModel` 会清掉 `QItemSelectionModel`、
故换序后必须恢复选中；`set_frames` 只发一条信号。

#### 破坏性验证（第 3 片）

| 破坏 | 被哪个用例捕获 |
|---|---|
| `set_frames` 改回 `clear()`+逐帧 add | `test_set_frames_emits_single_signal` |
| `set_frames` 不收敛越界选中 | `test_set_frames_drops_stale_selection_and_reference` |
| `set_frames` 不清理失效参考帧 | `test_set_frames_drops_stale_selection_and_reference` |
| 撤销恢复改回旧写法 | `dev/smoke_reorder.py`（新增的撤销恢复段，实测 17 条 vs 1 条） |

最后一条**一开始没被捕获** —— 当时 `smoke_reorder.py` 只测了拖拽重排的撤销，那条路径
行数不变，走不到 `set_frames` 里"行数可变"的分支。补了 `add_files` / `remove_frame`
两个真实动作的撤销覆盖之后才抓到。

#### 补测试时踩到的两个坑（值得记）

- **手工 `record_history()` 不会留下历史**：它在 `before == after` 时静默跳过，随后的
  `undo` 撤掉的是**上一条**历史，断言会被严重误导。要测撤销就得用真实动作
  （`add_files` / `remove_frame`）。
- **"刻意不记录历史"的测试会污染后续测试**：冒烟里那段"反证"拖拽故意不落历史，于是
  模型状态与历史栈就此不同步；后面再做撤销，恢复的是上一节遗留的快照。看起来像撤销
  坏了，实际是测试自身的状态污染 —— 必须在段前 `history.clear()`。

### 回归网现状与缺口

| 资产 | 覆盖 | 与时间轴的关系 |
|---|---|---|
| `dev/test_transform.py` | 37 个单测：几何语义、模型信号契约、帧克隆 | 不覆盖视图 |
| `dev/transform_baseline.py` | 渲染像素哈希 | 不覆盖视图 |
| `dev/verify_timeline_view_sync.py` | 23 个用例：双视图同步、共享选中、模型顺序契约、真实 `QDropEvent` 拖拽路径、`set_frames` 整体替换 | 视图层主网 |
| `dev/smoke_reorder.py` | 完整 `MainWindow` 链路：加载工程 → 拖拽 → 撤销（含加帧/删帧）→ 列映射/参考帧/禁用 | 接线网 |
| `dev/verify_grid_view.py` | 13 个用例：缩略图语义与缓存、序号、拖拽插入点、参考帧/禁用态渲染、列表列宽 | 网格视图专用网 |

缺口：右键菜单、外部文件拖入、播放跟随仍是纯手工验证。

### 补网过程中的教训（比新增的用例本身更值钱）

为网格视图补网时，写出来的**前 7 个断言里至少有 4 个是假通过**。是靠破坏性验证
（故意改坏产品代码，看测试是否变红）才逐个暴露出来的。四条反复出现的教训：

**1. 断言要落在可观测行为上，不要落在你以为的实现上。**

为了验证"缩略图命中缓存时不重算"，我 mock 了 `image_cache.get` 来计解码次数。
但 `create_thumbnail` 实际用的是 `QImage(image_path)` —— 它**绕过全局图缓存**，
于是 mock 打空了、测试却照样绿：破坏缓存后 11 个测试全过。

改法：不依赖内部实现 —— 命中缓存时把**源文件从磁盘移走**，缩略图仍应照原样渲染
（因为根本不需要读文件）。缓存一失效就会走 `os.path.exists` 失败分支、画出占位符，
内容随之变化。同时补一个对照组（显式失效缓存后**必须**重新读盘），否则上一条可能
因为"缩略图压根没刷新"而假通过。

**2. 测试数据必须能分辨被测行为。**

最初用 8×8 纯色图做缩略图夹具。纯色图裁任何区域、缩放到任何尺寸，结果像素都完全
一样 —— 于是三个缩略图断言全是假通过。改用四象限异色 + 棋盘底纹后才有分辨力。

**3. 被测性质若由缓存保证，测试必须先绕过缓存。**

"缩略图不套用帧变换"这条性质，实际是由**缓存 key 不含帧变换字段**保证的。直接改
`rotation` 再刷新，缓存命中、缩略图根本没重算 —— 哪怕真的给 `create_thumbnail` 加了
旋转，测试也照样绿（实测：加旋转后 12/12 全过）。必须先 `_clear_thumbnail_cache()`
才能真正验到 `create_thumbnail` 自己的行为。

**4. 破坏性验证自身也需要验证。**

两次"没被捕获"查下来都是我的破坏点没生效：一次把代码插进了 `if crop_rect:` 分支内
（测试帧没有 `crop_rect`，根本没走到）；一次替换目标字符串不存在，`str.replace` 静默
无操作。**破坏脚本必须先断言目标字符串确实存在再改**，否则"测试没红"会被误读成
"测试无效"，方向正好相反。

**5. `__pycache__` 会让破坏性验证的结果彻底失真。**

用 `cp` 还原源文件后，Python 可能仍加载**被破坏时编译的旧字节码**：`cp` 只更新 mtime，
而 pyc 校验用的是 `(mtime, size)`，秒级精度下快速往返会碰撞。症状极具迷惑性 ——
`inspect.getsource()` 显示的是正确源码，函数内部打印参数、比较结果是 `False`，
实际却返回 `True`。

**做破坏性验证前必须先 `find src -name __pycache__ -type d -exec rm -rf {} +`。**

**2026-08-29 回归：网格视图点击帧后属性面板显示未选中、预览区无反应**

根因两处叠加，且**第一处才是决定性的**：

**根因 1（决定性）：网格少了 `setSelectionBehavior(SelectRows)`。**

两个视图共享同一个 `QItemSelectionModel`，但显示的是**不同的列**（列表是序号列 0、
网格是文件名列 2）。列表设了 `SelectRows`，网格没设、用的是默认的 `SelectItems` ——
于是点击网格只选中**那一列**，`selectedIndexes` 里只有列 2；而列表按列 0 去读
`selectedRows()` 就认为"什么都没选"。两个视图对"选中了什么"看法完全相反。

**根因 2（次要）：网格的 `selectionChanged` 连在了 `setSelectionModel()` 之前。**

换 selectionModel 会**丢弃旧模型上的所有连接**，于是网格从此不再发通知；只有列表
在发，而它算出的是空 —— 空 frames 一路传到属性面板与预览区，表现为"点了没反应"。
（`model` 那边反而是对的，因为 `_on_view_selection_changed` 用的是当前视图的选中，
所以看起来"选中生效了"，只是下游没收到通知 —— 非常容易误判。）

修法：补 `SelectRows`；并把共享 selectionModel 的动作收进
`TimelineGridWidget.adopt_shared_selection_model()`，在 `setSelectionModel()` **之后**
重连信号。

**关于根因 2 的诚实说明**：破坏验证显示，**单独撤掉重连并不会让测试变红** —— 因为
列表的连接已经能覆盖共享 selectionModel 上的所有变化。所以根因 2 属于**健壮性改进**
而非必需修复：它让网格不必依赖"列表存在且已连接"这个隐式前提。实测两个视图都连接
时 `selection_changed` 仍只触发一次（第二次被 `_on_view_selection_changed` 的
"选中未变则短路"吸收），无重复通知、无副作用。

**为什么又是 25 个测试全绿**：所有选中用例都用 `_apply_selection_to_view` 或
`model.set_selection`，**绕过了真实鼠标路径**。这与此前拖拽那次（`test_*_drag_starts_drag`
补的就是 `startDrag` 这一环）是同一类盲区：**用高层 API 驱动测试，就测不到"用户
实际操作的那条路径"**。已补 `test_click_grid_row_notifies_downstream` 与
`test_both_views_agree_on_clicked_row`。

### 迁移引入的回归（用户报告）

**2026-08-29 回归：列表视图多选拖拽失效**

列表视图迁移后多选拖拽失效 —— 拖不动，手势被当成**扩展选区**。查下来是**两个**
独立缺陷，且第二个只有在修完第一个之后才暴露：

**回归 1：`TimelineItemModel.flags()` 漏了 `ItemIsDragEnabled`。**

`view.setDragEnabled(True)` **并不足以**启动拖拽：`QAbstractItemView.mouseMoveEvent`
还会再查一次 **model 的 flags**。缺这个位，view 就进入 `DragSelectingState`，把手势
解释成扩展选区。迁移前 `QTreeWidget` 用内建 model，`flags()` 默认带这个位，所以从未
暴露；换成适配层后 flags 由我们自己写 —— 漏了就翻车。

**回归 2：`move_frames` 用 `==` 判"顺序有无变化"，应为对象身份比较。**

`FrameData` 是 dataclass，`==` 是自动生成的值相等。工程里完全相同的帧很常见（复制帧、
同一张源图切出的相同区域），此时任意排列在 `==` 下都相等 → 拖到非相邻位置被判成
"无变化"而静默忽略。**用户拖了，什么也没发生，没有任何提示。**

**2026-08-29 回归：网格视图加载工程后一片空白**

根因不是列表视图的 delegate 缩略图问题（已单独修），也不是网格布局没触发 ——
`QListView` 在 IconMode 下会自动处理布局。**真正的根因是 `TimelineItemModel.__init__`
里一个低级的顺序错误**：先给 `self._frames = frames_model` 再调 `self.bind(frames_model)`，
而 `bind()` 开头有"已绑定则直接返回"的防重入判断 —— 构造时传入 model 的那个实例
**永远不会真正接线**（`_connect_frames_model()` 一次都没被调用）。

后果非常隐蔽：
- `rowCount()` 实时查模型，所以"有几行"永远对；
- 但所有模型信号（增删帧、换序、属性改、撤销恢复）都没转发给 Qt 视图；
- 视图只在**显式 refresh** 或 **Resize/Show** 事件时才"碰巧"重新取数 —— 也就是
  "拖一下面板、改一下缩略图尺寸、或切一下视图"才会刷新。

这正是为什么 23 个测试全绿：测试套件要么显式调了 `set_view_mode`/refresh，要么
跑在 headless 环境下尺寸事件被触发，稀里糊涂就过了。

已补两条直接定位的测试：
- `test_adapter_model_is_wired_to_frames_model`：断言 `model.add_frame` 会触发
  `item_model.rowsInserted`（不依赖任何视觉状态）；
- `test_views_follow_model_without_manual_refresh`：视图已就绪后再加帧，断言
  `visualRect(row0)` 真实有效，中间没有任何 resize/show/refresh 兜底。

两个缺陷均做了破坏性验证（分别恢复 `_frames` 提前赋值、把身份比较改回 `==`），
新测试均精确变红。

### 破坏性验证记录（13 个用例，8 个有效破坏全部被捕获）

| 破坏 | 被哪个用例捕获 |
|---|---|
| 缩略图缓存永不命中 | `test_thumbnail_cache_reused_on_refresh` |
| 缩略图套用 `rotation` | `test_thumbnail_ignores_frame_transform` |
| 缩略图忽略 `crop_rect` | `test_thumbnail_reflects_crop_rect` |
| 插入点判据改为只看 Y | `test_calc_insert_before_uses_x_only` |
| 列宽设到 `setModel()` 之前 | `test_list_column_widths_not_uniform` |
| 清除参考帧时不还原加粗 | `test_reference_frame_highlight_toggles_off` |
| 重排时重建 item 而非复用 | `test_reorder_preserves_thumbnail_objects` |
| 禁用遮罩不画 | `test_disabled_state_changes_thumbnail_pixels` |

另有 1 个用例（`test_disabled_state_read_from_model`）被确认是**弱断言**：它读的是
`item.data(UserRole).is_disabled`，而那正是 `FrameData` 对象本身，只要视图持有同一个
引用就恒真，与是否重绘无关。保留它是因为"视图持有模型对象而非副本"本身值得钉住，
但真正的渲染验证由 `test_disabled_state_changes_thumbnail_pixels` 承担。

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
