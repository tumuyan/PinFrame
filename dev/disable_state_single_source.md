# 禁用状态（is_disabled）单一数据源分析与方案

> 关联改动：`src/ui/timeline_list.py` 的禁用列自定义渲染（`_DisableColumnDelegate` + `mousePressEvent`）。
> 本文档聚焦 Code Review 发现 #6：**禁用状态存在多个存储位置，缺少单一数据源，存在不一致风险。**

---

## 1. 现状：禁用状态的三个存储位置

当前 `FrameData.is_disabled` 的“真值”被分散在三处维护：

| 位置 | 存储形式 | 写入方 | 读取方 |
| --- | --- | --- | --- |
| ① `FrameData.is_disabled` | Python 属性（模型真源） | `mousePressEvent`、`toggle_enable_disable`、`TimelineModel.enable_frames`、`on_frame_disabled_state_changed` 等 | grid 渲染、导出、list 自定义 delegate（间接）、`main_window` 播放/导出逻辑 |
| ② list item 的 `CheckStateRole` | `QTreeWidgetItem.setData(1, CheckStateRole, ...)` | `add_frame` 初始化、`mousePressEvent` 切换、`toggle_enable_disable` | `_DisableColumnDelegate.paint()`（读 `index.data(CheckStateRole)`） |
| ③ grid 直接读 ① | `frame_data.is_disabled` | ——（只读） | `timeline_grid.py`、`timeline_grid_delegate.py`、`TimelineModel` 内部 |

### 写入/读取路径梳理

- **用户点击 list 禁用列**（`timeline_list.py:552` `mousePressEvent`）：
  1. 改 ② `item.setData(1, CheckStateRole, new_state)`
  2. 改 ① `frame_data.is_disabled = is_disabled`
  3. 发射 `disabled_state_changed`
- **右键菜单 / 快捷键 启用·禁用**（`main_window.py` `toggle_enable_disable` ≈1985）：
  1. 改 ① `frame_data.is_disabled = is_disabled`
  2. 改 ② `item.setData(1, CheckStateRole, state)`（list）/ grid item 也写了但 grid 不读
  3. 调用 `_rebuild_timeline_before` 维护 undo
- **grid 视图**：完全不经过 ②，直接 `frame_data.is_disabled`（③）。
- **`TimelineModel`**：`enable_frames()`（306 行）直接改 ①，并通过 `data_changed` 通知视图刷新。

### 关键风险

1. **两处 UI 副本（②）与真源（①）可能失步**：
   - `toggle_enable_disable` 对 list 项写 ②、对 grid 项也写 ② 但 grid 从不读 ②——grid item 上的 `setData(CheckStateRole)` 是一句**无效写入**（死代码）。
   - 任何新增的“只改 ① 不刷新 ②”的代码路径都会让 list 禁用列显示与真实状态不一致。
2. **`CheckStateRole` 是 list item 的冗余副本**：
   - delegate 仅因“需要一个 Qt 角色来驱动绘制”才引入 ②；它与 ① 内容完全一致，却要双写、双维护。
3. **`TimelineModel` 已是事实上的模型层**，但视图仍各自持有 `CheckStateRole` 副本，未真正以 Model 为单一数据源。

### 本次改动是否恶化了问题

否。本次仅把 list 的禁用列渲染从 `ItemIsUserCheckable` 的默认对勾改为自定义 delegate + `CheckStateRole` 副本，并未改变“三处存储”的架构。但仍建议借机收敛，避免后续维护踩坑。

---

## 2. 三种可选方案

### 方案 0（最小改动，仅清无效写入）
- 删除 `toggle_enable_disable` 中对 grid item 的 `setData(CheckStateRole, ...)`（grid 不读，属死代码）。
- **不**改动 ② 的存在，不收敛数据源。
- 收益：少一处迷惑性死代码；风险：极低。
- 局限：① 与 ② 的双写耦合仍在。

### 方案 1（删除 list 的 CheckStateRole 副本）
- 删除 ②：`add_frame` / `mousePressEvent` / `toggle_enable_disable` 不再写 `CheckStateRole`。
- `_DisableColumnDelegate.paint()` 改为直接读 ①：从 `index.data(0, UserRole)` 取 `frame_data.is_disabled`。
- 收益：list 与 grid 统一以 ① 为唯一渲染来源；delegate 不再依赖 Qt 角色。
- 风险：中。需要保证 `index.data(0, UserRole)` 在 delegate 绘画时一定有效（当前 list item 已把 `frame_data` 存在 `UserRole`，成立）。

### 方案 2（推荐）：以 `TimelineModel` 为禁用状态的唯一数据源 ⭐
- **核心思想**：`TimelineModel` 已经是帧数据的模型层。`is_disabled` 作为 `FrameData` 的属性，本就归属于 Model。视图（list / grid）**只通过 Model 读写**，不再持有任何 UI 副本角色。
- 具体落地：
  1. **删除 ②**：list item 不再保存 `CheckStateRole`。
  2. **delegate 读取 Model**：`_DisableColumnDelegate.paint()` 通过 `index.data(0, UserRole).is_disabled` 决定绘制（空框 / 红 x）。
  3. **统一写入入口**：所有“切换/批量启用禁用”操作只改 `TimelineModel`：
     - 新增 `TimelineModel.set_frame_disabled(index, is_disabled)` 与现有 `enable_frames(indices, enabled)`，内部改 ① 并 `emit data_changed` / 新增 `frame_disabled_changed(index, is_disabled)` 信号。
     - `mousePressEvent`、`toggle_enable_disable`、`on_frame_disabled_state_changed` 均调用 Model 方法，而非直接改 `frame_data.is_disabled` 与 `item.setData`。
  4. **视图订阅 Model 信号刷新**：list / grid 监听 `data_changed` / `frame_disabled_changed`，对受影响行调用 `viewport().update()`，不再依赖 item 角色变化触发重绘。
  5. **grid 天然受益**：grid 已读 ①，无需改动即可与 list 同步。
- 收益：
  - 真正单一数据源（①），② 彻底消失，grid 无效写入（方案 0 的死代码）也一并消除。
  - 未来新增“批量反转禁用”“按条件禁用”等功能，只需走 Model 入口，UI 自动一致。
  - 与既有的 `data_changed` / `frames_*` 信号体系风格统一，降低认知负担。
- 风险：中高。需要：
  - 改造 `mousePressEvent` 与 `toggle_enable_disable` 的写入路径；
  - 保证 delegate 在 `data_changed` 后正确重绘；
  - 保证 undo/redo（`_rebuild_timeline_before`）仍基于 ① 正确工作（当前已基于 ①，无需大改）。
- 回归检验点：点击禁用列不选中行（保留现有行为）、右键启用/禁用、grid 与 list 显示一致、撤销重做后仍一致。

---

## 3. 结论与拟定执行方案

**拟定采用方案 2**：以 `TimelineModel` 为禁用状态的唯一数据源。

理由：
- ① 本就属于 Model（`FrameData` 是 Model 持有的数据对象）；
- ② 是历史遗留的 UI 副本，既冗余又需双写；
- 方案 2 一次性消除 ② 与 grid 无效写入，并从架构上杜绝“改了真源却忘了刷新 UI 副本”的回归风险；
- 改动面集中在 `timeline_list.py` 与 `timeline_model.py`，`main_window.py` 仅需把写入改调 Model 方法，影响可控。

### 实施步骤（待执行）

1. `timeline_model.py`：新增 `set_frame_disabled(index, is_disabled)` 与 `frame_disabled_changed(index, bool)` 信号；现有 `enable_frames` 改为经此信号通知。
2. `timeline_list.py`：
   - 删除 `add_frame` 中的 `CheckStateRole` 写入；
   - `_DisableColumnDelegate.paint()` 改为读 `frame_data.is_disabled`；
   - `mousePressEvent` 改为调用 `model.set_frame_disabled(...)` 并订阅 `frame_disabled_changed` 触发 `viewport().update()`；
   - 移除 `CheckStateRole` 相关注释。
3. `main_window.py`：
   - `toggle_enable_disable` 改为调用 Model 方法，删除对 list/grid item 的 `setData(CheckStateRole)`；
   - `on_frame_disabled_state_changed` 中如仍有 item 回写，一并删除。
4. 验证：用 `dev/screenshot.sh` 截图核对 list/grid 禁用列；运行 `test_full_slice.py`；手动验证点击不变更选中行、右键启用禁用、撤销重做。

> 注：方案 0 / 1 可作为方案 2 的增量子集——方案 2 完成后，方案 0 的死代码与方案 1 的“删除 ②”均自然达成。
