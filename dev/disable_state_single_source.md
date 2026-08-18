# 禁用状态（is_disabled）的单一数据源设计

本文档说明 PinFrame 时间轴中**帧禁用状态**的设计思路与最终架构，回答两个问题：
**为什么**把禁用状态收敛到单一数据源，以及**最终的设计是什么样的**。

---

## 1. 设计思路：为什么要单一数据源

### 1.1 问题的本质

一帧的“是否禁用”是一个**业务数据**，它归属 `FrameData`（模型层），被多处消费：

- **时间轴视图**：list 视图的禁用列、grid 视图的缩略图角标，都需要展示它；
- **导出逻辑**：导出时跳过被禁用的帧；
- **播放逻辑**：播放/序时是否包含被禁用帧。

当同一个“事实”被分散存储在多处、并由多个入口写入时，**这些副本之间必然存在失步风险**：改了一处，另一处还留着旧值，界面显示与真实状态不一致。历史上，list item 的 `CheckStateRole` 就是这样一个冗余副本——它与 `FrameData.is_disabled` 内容完全一致，却要双写、双维护，任何新增的“只改真源不刷新副本”的路径都会悄悄埋下 bug。

### 1.2 设计原则

本项目遵循一条通用的架构原则：**一份数据、一个真源、一个写入口、多视图只读**。

- **真源（source of truth）只有一个**：`FrameData.is_disabled`。
- **写入只有一个入口**：`TimelineModel.set_frame_disabled()`。
- **视图不持有状态副本**：list / grid 都从真源读取渲染，绝不把状态写进 UI item 的角色（role）里当副本。
- **模型通过信号广播变化**：视图订阅模型信号来触发重绘，而不是自己感知。

这条原则让“改了状态”与“界面更新”解耦：只要写入走统一入口，模型信号就会驱动所有视图自动一致，从架构上杜绝“改真源忘了刷 UI”这类回归。

---

## 2. 设计：单一数据源如何落地

### 2.1 角色划分

| 角色 | 承担者 | 职责 |
| --- | --- | --- |
| 状态真源 | `FrameData.is_disabled` | 唯一保存“是否禁用”的地方 |
| 写入口 | `TimelineModel.set_frame_disabled(index, is_disabled)` | 唯一允许修改真源的代码路径；写完后广播 `frame_disabled_changed` |
| 状态广播 | `TimelineModel.frame_disabled_changed(index, bool)` | 通知所有视图“某行的禁用状态变了” |
| 视图订阅 | `TimelineWidget._on_frame_disabled_changed` | 收到广播后对受影响行 `viewport().update()`，触发重绘 |
| list 渲染 | `_DisableColumnDelegate.paint()` | 从 column-0 的 `UserRole` 取回 `frame_data`，读 `is_disabled` 画空框或红 x |
| grid 渲染 | grid delegate | 同样直接读真源，天然与 list 一致 |

### 2.2 数据流

```
用户操作（点击禁用列 / 右键 / 快捷键）
        │
        ▼
TimelineModel.set_frame_disabled(index, is_disabled)   ← 唯一写入口
        │  修改 FrameData.is_disabled（真源）
        │  emit frame_disabled_changed(index, is_disabled)
        ▼
TimelineWidget._on_frame_disabled_changed(index)
        │  viewport().update()
        ▼
list  delegate / grid  delegate 重新读取真源 → 界面一致更新
```

### 2.3 关键设计决策与理由

1. **list 禁用列用自定义 delegate 而非 Qt 的 `CheckStateRole` 勾选框**
   - 目的：禁用列要画成“空框 / 红 x”而不是系统对勾，交互上“点击切换禁用但不选中行”。
   - 关键点：**渲染来源仍是真源**。delegate 通过 `index.siblingAtColumn(0)` 定位到 column 0，从那里的 `UserRole` 取出 `frame_data`，再读 `.is_disabled`。这样 list 与 grid 渲染同一份数据，永远一致。

2. **写入统一走 `set_frame_disabled`，视图不改真源**
   - 视图（`mousePressEvent`、`toggle_enable_disable`）都不直接写 `frame_data.is_disabled`，而是调用模型方法。模型是数据的所有者，写入口收拢到一处后，未来“批量禁用”“条件禁用”等新功能只需循环调用这一入口，UI 自动同步。

3. **`set_frame_disabled` 只 emit `frame_disabled_changed`，不 emit 通用 `data_changed`**
   - 禁用列由 delegate **直接读真源**渲染，并不依赖 `data_changed` 带来的整行文本重刷。单独广播 `frame_disabled_changed` 只重绘受影响行，避免无谓刷新。
   - 这体现了“**信号按需、最小重绘**”的更新哲学：什么变了就通知什么，能局部刷新就不整行刷新。

4. **不设 `enable_frames` 这类“伪批量”接口**
   - 批量场景本质就是对多帧重复执行同一状态变更，循环调用 `set_frame_disabled` 即可表达，无需引入语义含混（`not enabled`）且无人调用的专用方法，避免接口冗余。

### 2.4 设计带来的收益

- **一致性是结构保证的**，不是靠“记得同步”维持的：只要写入口唯一，多视图必然一致。
- **易扩展**：新增“批量反转”“按条件禁用”等，只扩展模型方法，不动视图。
- **易理解**：新维护者只需记住“写走模型、读走真源、订阅信号”，无需在多个 UI 角色里排查状态藏在哪。

---

## 3. 维护时如何保持这个设计

在时间轴相关功能中：

- **要读**禁用状态 → 从 `frame_data.is_disabled`（真源）读，或在 delegate 里经 column-0 `UserRole` 取出 `frame_data` 再读。
- **要改**禁用状态 → 调 `TimelineModel.set_frame_disabled(...)`，并依赖 `frame_disabled_changed` 驱动刷新。
- **不要**在 list / grid 的 item 上写 `CheckStateRole` 或任何“状态副本”角色——那会重新引入第二数据源。
- **不要**在视图层直接改 `frame_data.is_disabled` 绕过模型——会绕过信号广播，导致视图不刷新。

只要遵循“写走模型、读走真源、订阅信号”，单一数据源就不会被破坏。
