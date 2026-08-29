# 架构评审：现存问题与改进方向

> 评审日期：2026-08-20
> 评审基线：`main` @ `849bd23`（feat: 支持外部图像编辑器）
> 性质：**分析文档，未改动任何代码**。所有结论均附 `文件:行号` 证据，可按文末「复核方法」重新验证。

代码规模基线（`find src -name "*.py" | xargs wc -l`）：评审时（2026-08-20）全项目 15170 行，其中 `main_window.py` 4745 行、`property_panel.py` 1341 行、`temp_prop.py` 911 行、`canvas.py` 902 行。

> **2026-08-29 复核（基线 `1a12dff`）：** 全项目 **15537 行**，`main_window.py` **4579**、`property_panel.py` **1320**、`temp_prop.py` 911、`canvas.py` **890**。时间轴 7 文件 3412 行 → 8 文件 **3641 行**（P1-3 迁移后净增，见文末实施计划的口径说明）。

### 进度总览（2026-08-29 复核，基线 `1a12dff`）

| 项 | 状态 | 说明 |
|---|---|---|
| P0-1 变换语义收敛 | ✅ 已完成 | 2026-08-20；实为 9 份 → 1 份 |
| P0-2 `frames` 双源 | ✅ 已完成 | 2026-08-29，`2718d99` |
| P1-3 双视图迁 model/view | ✅ 三片全部完成 | 2026-08-29，`2764051` 起；**信号仍声明三遍，未消除** |
| P1-4 `BaseTimelineView` 空转 | ✅ 已解决 | 随 P1-3 第 3 片整个文件删除 |
| P2-5 `MainWindow` 拆分 | ❌ 未动 | 4579 行 / 157 方法；函数内 import 反增至 34 处 |
| P2-6 撤销快照 | ✅ 已完成 | 2026-08-29；走**结构共享**而非评审建议的「轻量补丁」，理由见实施记录 |
| P2-7 三层缓存 | ✅ 4 点全部完成 | 2026-08-30；字节预算 + LRU、删 `crop_rect` 死参数、导出期源图缓存（缩略图 key 去 index 已于 P1-3 完成）。**三层仍刻意不合并**，理由见实施记录 |
| P3-8 / 9 / 10 / 11 | ❌ 全部未动 | QSettings 6 处、`version.py` 未 gitignore、1195 行死代码、导出静默吞异常 |

回归基线：`bash dev/run_all_checks.sh --verbose` 实测 **9/9 PASS（约 5s）**。

> **2026-08-30 更新：** 新增第 11 项 `dev/verify_image_cache.py`（P2-7），现为
> **11/11 PASS（约 6s）**。

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
- [P2-6 实施记录](#p2-6-实施记录)
- [P2-7 实施记录](#p2-7-实施记录)
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
> 像素输出经哈希验证零变化（`MAIN_DIGEST` 前后一致，当时为 `9eb0372879f0aea1`）。
> 2026-08-29 复核：现行基线为 `ba2304d808c6aef3`（P0-1 之后另有渲染改动所致），
> `--compare` 与本机上次一致。
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

> **状态：已完成（2026-08-29，提交 `2718d99`）。** `ProjectData.frames` 改为绑定活跃数据源的属性，
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

### 实施结果（2026-08-29）

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

> **状态：已完成（2026-08-29，`2764051` 三片一次落地 + 至 `1a12dff` 的后续修复清理）。**
> 以下保留**原始分析**作为改动动机的记录 —— 但**正文里的 `文件:行号` 证据在迁移后
> 已全部失效**：`timeline_base_view.py` 整个文件已删、`extract_frame_data_from_item`
> 已不存在、两个视图已改为 `QTreeView` / `QListView`。**不要按这些旧行号去代码里找。**
>
> 2026-08-29 复核（基线 `1a12dff`）：
>
> | 结论 | 内容 |
> |---|---|
> | 已消除 | 视图持有帧数据副本；增删移改的手工镜像；`_view_in_sync_with_model`；顺序双源（视图→模型回写）；item 兼容外壳；P1-4 的抽象空转（`BaseTimelineView` 连带 `TimelineViewUtils` 已删） |
> | **未消除** | **信号仍声明三遍**（`pyqtSignal` 行数：`timeline.py` 20 / `timeline_list.py` 19 / `timeline_grid.py` 20，与评审时的 18 处同量级）。正文把这条列为根因，但三片都没动它 —— 迁移后这些是「视图 → MainWindow」的上行通知，与 `TimelineModel` 的下行通知不是一回事，属独立议题，未列入本次范围 |
> | 规模 | 时间轴 3412 行/7 文件 → **3641 行/8 文件**（新增 `timeline_item_model.py` 364 行）。行数净增，口径见实施计划 |
> | 回归 | `run_all_checks.sh` **9/9**；`verify_timeline_view_sync` **27/27**、`verify_grid_view` **20/20**、`test_transform` 37/37、`MAIN_DIGEST` 与上次一致 |
>
> 迁移过程中暴露并修掉的真实回归（多选拖拽失效、网格空白、点击网格属性面板无反应）
> 及完整破坏性验证记录，见文末 [P1-3 实施计划](#p1-3-实施计划)。

**这是时间轴全部复杂度的根因。**

> 以下「代价是可量化的」与「建议方向」两段描述的是**迁移前**的状态；行号指向
> `849bd23` / `2718d99` 时期的代码，现已不适用。

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

> **状态：已解决（2026-08-29）——`src/ui/timeline_base_view.py` 整个文件已删。**
> 它是随 P1-3 第 3 片一并清掉的（走的是本文「若走 P1-3 方案，这个基类基本可以整体
> 消失」那条路）。下表是删除前的调用点统计，保留作为动机记录。
>
> 一处例外：`get_frame_data_at_index` **没有删除**，而是从「两个视图各实现一份的抽象
> 方法」降级为各自（及 `TimelineWidget`）的**公开取数 API**，实现直接问模型、不经
> item。它现在是 3 处三行转发，语义上仍是重复，但属于对外接口而非抽象层空转。

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

> **2026-08-29 复核：未动，且两个症状都略微恶化。** 4579 行 / 157 个方法；
> 函数内 `import` **34 处**（评审时 32）；跨层私有访问**仍是那 2 处**，仅行号位移：
> `main_window.py:747` → `self.timeline._apply_selection_to_view(...)`、
> `main_window.py:3234` → `self.timeline.grid_view._clear_thumbnail_cache()`。

两个可观测症状：

- **32 处函数内 `import`**（现 34 处）—— 典型的规避循环依赖信号。例如 `EditorSettingsDialog` 在 `main_window.py:19` 顶部已导入，函数体内又导一遍。
- **2 处跨层访问私有成员**：
  - `main_window.py:724`（现 `:747`）→ `self.timeline._apply_selection_to_view(...)`
  - `main_window.py:3384`（现 `:3234`）→ `self.timeline.grid_view._clear_thumbnail_cache()`

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

> **状态：已完成（2026-08-29）。** 走的是**结构共享**而不是评审建议的「轻量补丁」，
> 理由与实测数据见文末 [P2-6 实施记录](#p2-6-实施记录)。要点：
> 恢复改为按帧增量（撤销一次 scale 只动 1 帧、只重绘 1 行）；快照之间按帧共享
> 对象，一条历史的增量成本从 O(帧数) 降到 O(变更帧数)。
> 2026-08-29 复核：未变动的另两条（P2-5 的拆分、P2-7 的缓存）与本项无关。

`_capture_snapshot()`（`main_window.py:654`，现 `:681`）深拷贝**所有**帧，上限 200 条（`history.py:45`）→ 500 帧的工程约 10 万个 `FrameData` 副本常驻内存。

更麻烦的是恢复路径：`_apply_snapshot_inner()`（`main_window.py:688`，现 `:715`）为了还原会 `timeline.clear()` + 逐帧 `add_frame` + `grid_view.refresh_all_items()`。
**此句已过时** —— 现为一次 `self.timeline.set_frames(...)`，也不再调 `refresh_all_items()`。

即：**撤销一次「把 scale 从 1.0 调成 1.1」，代价是整个时间轴视图重建 O(n)**。帧多时撤销会明显卡顿，且 item 对象全部重建（P1-3 的衍生代价在此再次显现）。

### 建议方向

区分两类操作：

- **结构性操作**（增删 / 排序 / 切片）：继续用全量快照；
- **纯属性变更**：走轻量补丁，记录 `(index, field, old, new)`，恢复时只 `replace_frame_at` + `data_changed`。

现有的合并窗口机制（`_open_history_merge_window`，600ms 单次定时器，label 变化即提交）可以直接复用，不需要重写。

---

## P2-6 实施记录

> 完成日期：2026-08-29。目标与本项评审建议的偏差都记在这里。

### 与建议方向的偏差：走结构共享，不走补丁

评审建议「纯属性变更记录 `(index, field, old, new)` 补丁」。**没有这么做**，原因是
它会把历史栈的语义从「存状态」改成「存变化」，代价超出收益：

`HistoryManager` 的状态模型是 `S0 → S1 → … → Sn`，`entries[k].before` 表示 `S(k-1)`。
撤销/重做沿着栈**单调**移动时，补丁是安全的（当前状态一定是 `S(k)`，反向应用补丁
即得 `S(k-1)`）。但历史菜单支持**跳到任意一条**（`jump_to`），那时当前状态未必是
目标的前一步 —— 补丁就必须从最近的一个完整状态**重放**过来，于是要给每条记录加
「基准 + 补丁链」，还要处理链上的结构操作。

更麻烦的是脆弱性：全量快照的「应用」是**绝对恢复**，当前状态与历史栈哪怕不同步
也能救回来；补丁的「应用」是**相对增量**，前提被打破就静默写到错误状态，不报错。
而这类不同步是存在的（`_history_suspend` 期间的 UI 刷新、不落历史的批量修改）。

最终选了**结构共享**：快照的形态完全不变（仍是完整状态，`undo`/`redo`/`jump_to`
一行没改），只是让快照之间**按帧共享对象** —— 未变的帧在所有快照里是同一个对象，
只有真变了的帧才克隆。内存从 O(帧数 × 历史条数) 降到 O(帧数 + 累计变更数)，
与补丁同量级，但不引入相对增量的那套前提。

### 改动的四处

**1. 恢复路径按帧增量（`TimelineModel.apply_frames`）。**
行数不变时逐帧比较，只替换真正不同的行，最后发**一条** `data_changed(最小行, 最大行)`；
行数变了（撤销加帧/删帧）才回落 `set_frames()`。

选 `data_changed` 而不是整体替换信号，语义是严丝合缝的：行数没变、「第 i 行是哪个
帧」也没变，只是内容变了 —— 正是 `data_changed` 的定义（同一条纪律在 P1-3 第 2 片
里已经用过一次）。

收益不只是少克隆：撤销不再 `beginResetModel`，于是**选中不被清空、滚动位置不丢、
网格布局不重算**；缩略图按内容缓存，属性变更不改 `file_path`/`crop_rect`，缓存命中，
一次解码都不做。

**2. 快照之间共享未变帧（`_capture_snapshot(reuse_from=...)`）。**
`record_history` 与合并窗口把 `before` 传给 `after` 当基准，值相同的帧直接复用基准
的对象、不重复克隆。

**3. 历史栈消除 before/after 双份（`HistoryManager.push`）。**
`entries[k].before` 就是 `entries[k-1].after`（状态模型保证），值相等时复用同一对象。
这一项单独就省掉一半。

**4. 默认复用基准（`_capture_snapshot` 省略 `reuse_from` 时取历史栈最新记录的 after）。**

前三条把**内存**降到了 O(帧数 + 累计变更数)，但 CPU 上每次记历史仍要克隆两次全表：
`record_history(before=X)` 的调用方是在操作前 `self._capture_snapshot()` 抓的，那时
没有基准。让省略参数时默认以 `entries[-1].after` 为基准，就补上了这一半 —— 实测
克隆次数从 1000/条 降到 1/条（见上表）。

基准过时**不会出错**：判据是"值相同才复用"，值不同就克隆，最坏退回全量。这也是敢
把它设成默认行为的原因。用户在历史中途（撤销过）时不给基准，避免白比一次。

第 2、3 项是互相成就的：因为第 2 项让相邻快照共享了未变帧的对象，第 3 项的
`before == entries[-1].after` 比较会大量命中 list 比较的**身份短路**，实际代价接近
O(1) —— 若没有第 2 项，这个 O(n) 比较会把省下的克隆又赔进去。

### 一个必须写下来的不变量

三条改动里只有一条有静默失败模式：**`apply_frames` 必须克隆它要替换的帧**。
若直接 `self._frames[i] = target[i]`，模型与历史快照就共享了同一个 `FrameData`，
此后每一次原地编辑都会写进历史快照 —— 撤销/重做恢复到的是「被后续编辑改过」的值，
**不报错、不崩溃**，只在 redo 时偶尔取到错值。

`dev/verify_undo_snapshot.py` 的两条 `test_snapshot_not_polluted__{incremental,fallback}_path`
分别钉住增量路径与回落路径 —— **两条路各测一遍是必需的**，`clone()` 只写在其中一条上
就会漏，而漏的那条在功能测试里完全看不出来。手法是让被污染的快照再被应用一次
（走 redo，它读的是 `after`）。破坏性验证确认：去掉任一条路径的 `clone()`，
对应用例立刻变红。

### 撤销/重做的覆盖边界（值得记住的一条事实）

**设置/清除参考帧不落历史。** `set_reference_frame_from_selection` 全文没有
`record_history`，i18n 里也没有 `hist_*_reference` 这样的 label —— 实测
`history.count()` 在设完参考帧后仍为 0、`can_undo` 为 False。

所以「撤销设置参考帧」这个操作**本身不存在**，无从覆盖。但参考帧会被快照**间接**
还原：快照存了 `reference_frame` 路径 + 下标，撤销任意其它操作时按它恢复。
`test_reference_frame_survives_undo` 覆盖的是这条路径。

分工上：`smoke_reorder.py`（P1-3 期）已有加帧 / 删帧 / 拖拽重排的**撤销**覆盖，
但**完全没有 redo**；`verify_undo_snapshot.py` 补的是 undo↔redo **往返**。
两者不重复，删任何一个都会留下缺口。

### 一个未修的既有缺陷（本项不改，记录在此）

`MainWindow.playlist` **缓存帧对象**（`self.playlist = [f for f in frames ...]`），
而 `update_playlist()` 只在"开始播放 / 禁用状态变化 / 播放中选中变化"时调用 ——
**模型数据变更不刷新它**。于是播放中撤销，playlist 里是已失效的旧对象。

这不是 P2-6 引入的：改动前撤销走整体替换，**全部**对象换新（实测 13/13 失效）；
改动后撤销单帧属性只让 **1** 个失效。亦即 P2-6 顺带把它变轻了，但没消除。

修法很直接（让 `frames_replaced` / `frames_reordered` / `data_changed` 在
`is_playing` 时刷新 playlist），但会改变播放中的既有行为，超出本项范围，故只记录。

### 实测数据（500 帧工程）

构造 500 帧、连续记录 20 条历史（每条只改 1 帧的 scale）：

| 指标 | 改动后 | 对照（全量深拷贝 + before/after 各一份） |
|---|---|---|
| `FrameData.clone()` 调用总数 | **520** | 20 × 2 × 500 = 20000 |
| 历史栈内不同的帧对象数 | **520**（≈ 帧数 + 变更数） | 20000 |
| 撤销一次单帧属性变更的克隆数 | **1** | 500 |
| 撤销一次通知覆盖的行数 | **1**（`data_changed(0,0)`） | 500（整体重建） |

第 1 条历史必然是 O(帧数)（没有基准可复用），之后每条只付变更帧的代价 ——
520 = 500 + 20，正是 "O(帧数 + 累计变更数)"。

### 破坏性验证（4 个破坏点，全部被捕获）

| 破坏（P2-6 机制本身） | 被哪个用例捕获 |
|---|---|
| 恢复改回 `set_frames()` | `test_undo_property_change_is_incremental`、两条 `test_snapshot_not_polluted__*`、`test_undo_redo_reorder` |
| **增量路径**不 clone | `test_snapshot_not_polluted__incremental_path`、`test_apply_frames_contract` |
| **回落路径**不 clone | `test_snapshot_not_polluted__fallback_path` |
| 快照退回全量克隆（去掉未变帧复用） | `test_history_cost_is_independent_of_frame_count`、`test_snapshots_share_unchanged_frames` |
| 历史栈 before/after 不去重 | `test_snapshots_share_unchanged_frames` |
| 禁用默认复用基准（退回全量克隆） | `test_history_cost_is_independent_of_frame_count` |

**「两条路径各测一遍」是后来补的，代价是一次真实漏网。** 最初只有一条污染检测，
且走的是增量路径；`clone()` 漏写在回落路径上时，11 个用例（当时 10 个）全绿、
15/15 帧与历史快照共享身份，直到 code review 才被发现。
`clone()` 分散在两条路径上，就只能测两条 —— 这是本项最贵的一条教训。

补 undo/redo 覆盖时又做了 6 个破坏，同样全部被捕获：
`redo` 返回错误快照（4 个用例变红）、撤销不恢复参考帧、`apply_frames` 不清空失效
参考帧、适配层缓存帧对象、`add_files` 不落历史、`remove_frame` 不落历史。

其中两个值得单独说，因为**第一次没被捕获**，是测试写错了而不是产品代码对：

- **「适配层缓存帧对象」最初抓不到**：我把检查放在了 redo 之后，而那一刻缓存里
  存的恰好就是期望值 —— 断言恒真。改到**每次顺序变化之后都查**才抓到。
  教训：验证「不缓存」这类性质，必须在**被缓存的值已经过时**的时刻去查。
- **「不清空失效参考帧」最初也抓不到**：因为唯一调用方随后一定会按快照重设参考帧。
  这段清空是**纯防御**，去掉它最终行为不变。所以不为它写行为断言，改为钉住
  「`apply_frames` 与 `set_frames` 副作用一致」这条契约 —— 否则两条路径分叉后，
  将来任何只走 `apply_frames` 的新调用方都会留下指向已移除对象的参考帧。

第一条同时被"污染"那条抓到，是合理的：旧代码 `set_frames([self._clone_frame(f) for f in frames])`
自己带克隆，所以只把调用换回 `set_frames` 而**不带**克隆，就正好复现了共享对象那
个失败模式 —— 说明这条不变量确实没有第二道防线。

### 刻意未做的部分

- **合并窗口本身的开合时机未动**。评审说「可以直接复用，不需要重写」，实测确实如此：
  `edit_started` / `drag_started` / `crop_drag_started` 三个信号已经在修改**之前**
  发出，是天然的"操作前"锚点。
- **没有做 COW（写时克隆）**。理论上还能再省一层：让快照完全不克隆、改在"帧即将被
  修改"时把模型里的对象换成副本。但那需要拦截全部 ~25 处就地改字段的地方
  （`property_panel` / `canvas` / `main_window` 批量操作），漏一处就是同样的静默污染，
  而收益只是把 O(变更数) 再降一个常数。风险与收益不匹配，不做 —— 记在这里以免
  后来者重走一遍。

---

## P2-7 实施记录

> 完成日期：2026-08-30。目标与本项评审建议的偏差都记在这里。

### 四处改动

**1. `core/image_cache.py`：上限改成字节预算，淘汰改成 LRU。**

`_max_size = 500`（张数）换成 `_max_bytes`（字节，默认 512 MiB），`dict` 换成
`OrderedDict`，命中时 `move_to_end` —— LRU 与 FIFO 的全部区别就在这一行。
字节数用 `QImage.sizeInBytes()`（回退 `bytesPerLine() * height()`），算的是
**解码后**的内存，与文件体积无关。

**2. 同文件：单张超过预算的图刻意保留。**

`_evict_to_fit` 淘汰时绝不淘汰"本次正要放进去的那张"。否则一张 4K 图放进即被踢，
每次访问都重新解码 —— **比不缓存更慢**，还多一次淘汰遍历。所以 `total_bytes`
允许超过预算，这是有意的，已写成单测（`test_oversized_image_is_kept_and_reused`）。

**3. 同文件：删除 `get()` 的 `crop_rect` 参数。**

全项目 17 个调用点没有一个传它，内部 key 也从不参与计算。

**4. `utils/exporter.py`：新增 `SourceImageCache` —— 导出期源图缓存。**

三种导出模式各开一个（`with` 块），经新增的可选参数 `source_cache` 传给唯一的
变换实现 `compose_frame`。缓存的是**解码后、未裁切**的 RGBA 原图：PIL 的
crop / resize / transpose / rotate 一律返回新对象，从不在原地修改，所以多帧共享
一张原图是安全的（这条前提由 `test_shared_source_image_is_not_mutated` 钉住）。

### 与建议方向的偏差

**评审说「在 `export_iter` 内加一个局部字典，几行代码」，做了三处偏离：**

- **加了字节上限（256 MiB）。** 评审没提，但**无限**缓存是有风险的：它把峰值内存
  从"1 张源图"变成"N 张"。精灵表工程（几百帧共用一张）赚，而"几百帧各用各的大图"
  的工程会**比不缓存更容易 OOM**。设了上限之后，最坏情况退化为"缓存没命中"，
  不会比改之前更差；不设上限则最坏情况是崩。
- **三种导出模式共用，不是只改 `export_iter`。** 三者都调 `compose_frame`，
  各加一个局部字典就是三份重复（正是 P0-1 那类毛病）。
- **生命周期用 `with` 收口，确保异常路径也 `close()`。** 注意这条的理由**不是**
  "修一个已存在的泄漏"，当初写下的那句理由已被实测推翻，见下。

**「三层缓存合并成一层」刻意没做。** 标题里的"互不知情"听上去像缺陷，但三层存的
**东西**与**生命周期**都不同，合并是错的：

| 层 | 存什么 | key | 生命周期 |
|---|---|---|---|
| `core.image_cache` | 解码后的 QImage（全尺寸） | 路径 | 进程级，手动失效 |
| 网格缩略图缓存 | 网格专属的 QPixmap（含背景棋盘、按缩略图尺寸缩放） | 内容 + **网格设置** | 视图私有，随设置清空 |
| `SourceImageCache` | PIL 原图（未裁切） | 路径 | **一次导出** |

缩略图那一层尤其不能合并：它的 key 里有"背景模式 + 缩略图尺寸"这两个**纯展示**
维度，塞进全局 `image_cache` 等于让画布与属性面板的全尺寸图也按缩略图尺寸分桶。

真正需要修的"不知情"是**失效时机**，而那已经是好的：外部编辑器改图后
`_reload_edited_images` 会逐个失效三层（`image_cache.remove` +
`clear_source_image_size_cache` + 缩略图定向失效 + 画布刷新）。

### 为什么必须写单测：改错了功能完全正常

这四处**没有一个**会让导出结果或界面行为发生变化，退化只体现在内存/CPU 上，
而且很隐蔽：

| 破坏 | 现象 |
|---|---|
| 上限退回按张数 | 500 张 4K 图照样吃满 32 GB（正是要修的东西） |
| 淘汰退回 FIFO | 只在"加载得早却一直被访问"的那张图上变慢，肉眼几乎看不出 |
| `crop_rect` 参数加回来 | 没人传它，代码照样跑 |
| 导出期缓存去掉 | 导出结果**逐字节相同**，只是同一张精灵表被解码几百遍 |

所以 `dev/verify_image_cache.py` 断言的是**预算、淘汰顺序、解码次数**这些看不见的
量。像素正确性交给 `transform_baseline.py`（导出路径改了缓存，它的哈希必须不变）。

### 破坏性验证（4 个破坏点，全部被捕获）

| 破坏 | 被哪个用例捕获 |
|---|---|
| 命中时不做 `move_to_end`（退回 FIFO） | `test_eviction_is_lru_not_fifo` |
| 淘汰条件改回 `len(self._cache) >= 500` | `test_eviction_is_driven_by_bytes_not_count` |
| `compose_frame` 不复用源图（每帧 `Image.open`） | `test_export_decodes_each_source_once` |
| 原地修改共享原图（`putpixel`） | `test_shared_source_image_is_not_mutated` |
| `get()` 返回即将被 `with` 关闭的中间对象 | `test_cached_images_survive_source_close`（另 3 条同时变红） |

最后一条是补的：`get()` 加了 `with` 之后引入了一个新的耦合点 —— 若返回的是那个
即将被关闭的中间对象，缓存里的图会在 `with` 退出的同一刻失效，而**首帧仍能正常
导出**，错误要等到第 2 帧才出现。故用例刻意用多帧的 GIF 而非 PNG 作夹具。

另有一条**防止假通过**的设计：`test_export_decodes_each_source_once` 开头先断言
"不开缓存时确实是每帧解码一次" —— 计数器若失灵，后面的"只解码 1 次"就是恒真的。

### 两条当初写错的理由（复核时由实测推翻，记在这里以免重犯）

code review 让"把投机性防御删掉"，逐条实测之后发现**两条当初的理由都是错的**，
其中一条是我自己写进注释的臆测：

**1. 「`convert()` 之后文件句柄仍挂在对象上」—— 错的。**

`Image.open()` 是懒加载，但 `convert()` 触发的 `load()` 在读完数据后就**自己关了**
文件。实测：`convert()` 之后 `im.fp` 变 `None`；不显式 close 循环 200 次，
`/proc/self/fd` 增量为 **0**。亦即 `Image.open(p).convert("RGBA")` 这条原写法
**根本没有泄漏句柄**，跟引用计数无关 —— 是 Pillow 主动关的。

那 `with` 与 `close()` 还有没有用？有，但性质从"修泄漏"降级为"**不依赖 Pillow
对具体格式的实现细节**"：单帧 PNG 会自己关，多帧格式（GIF / TIFF）未必。
所以 `with` 保留、注释改写，`close()` 也保留为防御。

**2. 「`_image_bytes` 需要回退分支」—— 也不需要。**

原本写了 `getattr(img,"sizeInBytes",None)` + `try/except (RuntimeError,TypeError)` +
`size <= 0` 回退到 `bytesPerLine()*height()`，三层防御。实测：`sizeInBytes()` 自
Qt 5.10 起存在、PyQt6 必然有；三处调用点都在 `isNull()` 之后或取自缓存，`img` 必然
非空；**空图调用它也返回 0**。三层分支全部不可达，已简化为一行。

教训：这两条都是"听起来应该防御一下"就写下的，没有任何一条来自实测。防御性代码
的代价不只是行数 —— 不可达的分支会让读者以为那些情况真的会发生。

### 刻意未做的部分

- **导出缓存没有跨导出复用。** 生命周期严格限定在一次导出内：跨次缓存会让
  "改了图再导出"拿到旧图，而它的失效时机比缩略图还难判（缩略图至少有
  `invalidate_thumbnail_cache_for_paths` 这个入口）。导出是一次性批处理，
  一次之内复用已经能覆盖精灵表这个主要场景。
- **没有做"预算自动调优"。** 512 MiB / 256 MiB 是拍的常量，够用且留了
  `set_budget()` 口子，但没有去做按可用内存自适应 —— 那属于 P3 级问题，
  且会引入"同一次运行里行为不一致"的调试困难。

---

## P2-7｜三层缓存互不知情，外加一个诱导误用的 API

```
image_cache (QImage, 按路径)  ←→  _thumbnail_cache (QPixmap, 按 path+crop+index)  ←→  exporter (无缓存)
```

> **状态：已完成（2026-08-30）。** 见文末 [P2-7 实施记录](#p2-7-实施记录)。
> 四点全部处理：字节预算 + LRU、删 `crop_rect` 死参数、导出期源图缓存；
> 第 3 点（缩略图 key 去 `index`）已于 P1-3 随迁移解决。**「三层缓存合并成一层」
> 刻意没做** —— 三层存的东西与生命周期都不同，理由在实施记录里。
> 以下保留原始分析，作为改动动机的记录。
>
> **2026-08-29 复核（当时）：4 点只做了 1 点。** 仅第 3 点随 P1-3 迁移顺带解决
> （缩略图 key 已不含行号，见 `timeline_grid.py:_get_cache_key`）。**第 1、2、4 点
> 原样存在**：`crop_rect` 死参数仍在 `image_cache.py:25`，`_max_size = 500` 按张数
> + FIFO 仍在，`exporter.py` 仍在 `compose_frame` 内每帧 `Image.open`（3 种导出
> 模式各调一次，尚无 PIL 层缓存）。

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

> **2026-08-29 复核：P3 四项全部未动**（`1a12dff`）。`QSettings` 仍 6 处、无
> `core/settings.py`；`version.py` 仍受版本控制且 `.gitignore` 未收录；
> `temp_prop.py`(911) 与 `assemble.py`(284) 仍在；`exporter.py` 三处
> `except Exception` 仍在，行号已漂到 `:164` / `:212` / `:248`。

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
| `dev/test_transform.py` | 25 个单测，锁定几何语义（顺序、符号、镜像编码、取整约定）—— **2026-08-29 已增至 37 个**（后续并入模型信号契约与帧克隆） |
| `dev/transform_baseline.py` | 7 条渲染路径的像素哈希回归；`--compare` 一眼看 MAIN_DIGEST（现行值 `ba2304d808c6aef3`） |

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

> **2026-08-29 后续（P2-6 收尾，见 [P2-6 实施记录](#p2-6-实施记录)）：** 撤销恢复
> 的默认入口改为 `apply_frames()` —— 行数不变时**逐帧比较后只替换不同的行**，发一条
> `data_changed`，`set_frames()` 退化为"行数变了才用"的回落路径。
>
> 上一段"不能用 `data_changed`"的论证在当时是对的，它的前提是"撤销恢复**连帧对象都
> 换了、行数也可能变**"。收尾时把这两种情形拆开了：行数变 → 仍走 `set_frames`（前提
> 成立）；行数不变 → 映射没变、只有内容变了，`data_changed` 正好合用。所以这不是推翻
> 前文的纪律，而是把纪律用在了它真正适用的那一半。

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

> 用例数为 2026-08-29 复核值（基线 `1a12dff`），与上文各片"净效果"里写作时的
> 数字不同 —— 那是分三片推进过程中逐步累加的快照。

| 资产 | 覆盖 | 与时间轴的关系 |
|---|---|---|
| `dev/test_transform.py` | **37 个单测**：几何语义、模型信号契约、帧克隆 | 不覆盖视图 |
| `dev/transform_baseline.py` | 渲染像素哈希（`MAIN_DIGEST` / `EDGE_DIGEST`） | 不覆盖视图 |
| `dev/verify_timeline_view_sync.py` | **27 个用例**：双视图同步、共享选中、模型顺序契约、真实 `QDropEvent` 拖拽路径、`set_frames` 整体替换 | 视图层主网 |
| `dev/verify_grid_view.py` | **20 个用例**：缩略图语义与缓存、序号、拖拽插入点、参考帧/禁用态渲染、列表列宽 | 网格视图专用网 |
| `dev/smoke_reorder.py` | 完整 `MainWindow` 链路：加载工程 → 拖拽 → 撤销（含加帧/删帧）→ 列映射/参考帧/禁用（断言式，无 `test_*` 命名） | 接线网 |
| `dev/smoke_reference_frame.py` | **9 个用例**：参考帧高亮、连设两次幂等、清除后还原 | 接线网 |
| `dev/verify_selection_style.py` | **9 个用例**：选中配色跨平台一致、对比度下限、单一来源 | 视觉样式网 |
| `dev/verify_undo_snapshot.py` | **11 个用例**：撤销走增量而非整体替换、行数变化回落、快照不被后续编辑污染（**增量/回落两条路径各一**）、未变帧共享、记历史的克隆成本与帧数无关、加帧/删帧/拖拽重排的撤销**重做**往返、参考帧在撤销后仍还原、`apply_frames` 契约 | 撤销快照网（P2-6） |

`dev/run_all_checks.sh` 把这批资产并为 **10 项**（含 `check_no_duplicate_defs` 与
语法编译），2026-08-29 实测 **10/10 PASS，约 5s**。

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

本文全部数字可用以下命令重新验证（repo 根目录，Git Bash）。

> **2026-08-29 注**：下列命令中标注 ⚠️ 的两条，其**预期输出已随 P1-3/P1-4 落地而
> 改变**（不是命令失效，而是"异常值"变成了"正常值"），已在注释里写明当前预期。
> 全量回归请直接跑 `bash dev/run_all_checks.sh --verbose`（9 项，约 5s）。

```bash
# 代码规模
find src -name "*.py" | xargs wc -l | sort -rn | head -20

# P0-1 变换块重复次数 / 三个导出方法
grep -c "Handle scale and aspect_ratio" src/utils/exporter.py
grep -n "    def " src/utils/exporter.py

# P1-3 信号三处声明
# ⚠️ 预期已变：迁移**没有**消除三处重复声明，当前约为 20 / 19 / 20（见 P1-3 状态块）
grep -c "pyqtSignal" src/ui/timeline.py src/ui/timeline_list.py src/ui/timeline_grid.py

# P1-4（⚠️ 已解决）：`timeline_base_view.py` 应不存在
ls src/ui/timeline_base_view.py 2>&1            # 期望：No such file or directory

# `get_frame_data_at_index` **未删除**，而是从抽象方法降级为各自的公开取数 API
#（实现改为直接问模型，不再经 item）—— 期望 3 处定义：timeline / list / grid
grep -rn "def get_frame_data_at_index" src/ui/ --include="*.py"

# `extract_frame_data_from_item` 应只剩注释里的历史提及（期望 1 处注释，0 处代码）
grep -rn "extract_frame_data_from_item" src/ --include="*.py"

# P2-5 MainWindow 规模与函数内 import
grep -c "    def " src/ui/main_window.py
grep -c "^        from \|^            from \|^        import " src/ui/main_window.py

# P2-7 全部四点（2026-08-30 已完成，以下为复核命令）
#  1) get() 签名只剩 (self, file_path)；crop_rect 只应出现在解释"为什么删掉"的
#     docstring 里，不得出现在 get() 的实现里
#  2) 上限是字节预算 + LRU：不应再有 _max_size / 按张数的判据，命中处应有 move_to_end
#  3) 缩略图 key 不含行号（P1-3 期已修）
#  4) 导出期源图缓存：三种导出模式都用 with SourceImageCache()
grep -n "def get" src/core/image_cache.py
grep -rn "crop_rect\|_max_size" src/core/image_cache.py
grep -n "_get_cache_key" -A 8 src/ui/timeline_grid.py
grep -n "SourceImageCache()" src/utils/exporter.py   # 应为 3 处

# 行为验证（改错了功能一样正常，只能靠这个）
python dev/verify_image_cache.py

# P3-8 QSettings 散落点
grep -rn "QSettings(" src/

# P3-9 version.py 是否受版本控制
git ls-files src/core/version.py && cat src/core/version.py

# P3-10 死代码是否真无引用（dev/ 里应只有 check_no_duplicate_defs.py 的排除项）
grep -rn "temp_prop\|assemble" src/ main.py PinFrame.spec dev/

# P3-11 吞异常与裸 print（--include 要加引号，zsh 下未 quote 的 glob 会报 no matches）
grep -rn "except:" src/ --include="*.py"
grep -rn "^\s*print(" src/ --include="*.py" | grep -v debug_config.py

# i18n 键一致性（应为双向空集）
python -c "import json;a=json.load(open('src/i18n/zh_CN.json',encoding='utf-8'));b=json.load(open('src/i18n/en_US.json',encoding='utf-8'));print(len(a),len(b),set(a)-set(b),set(b)-set(a))"
```
