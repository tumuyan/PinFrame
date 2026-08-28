# project.frames 的单一真相设计

本文档说明 `ProjectData.frames` 与 `TimelineModel` 的关系。

> **2026-08-21 起设计已改变。** 原先的规则是"任何工程级功能在入口手工同步一次"，
> 现已被属性委托取代，**那条规则不再适用，且已被代码主动拒绝**（绑定后赋值抛
> `RuntimeError`）。第 1–2 节保留下来记录为什么要改，第 3 节起是当前设计。

## 1. 曾经的设计：两份数据，靠纪律维系

`TimelineModel` 持有帧列表的实时状态；`ProjectData.frames` 曾是一个普通字段，
**只在保存 / 导出 / 素材管理器删除引用后**才从 timeline 同步一次，其余时间是过期快照。

用户的一切编辑（增 / 删 / 排序 / 复制 / 翻转 / 改属性）只改 timeline，不碰
`project.frames`。于是任何直接遍历 `project.frames` 的功能，在用户尚未保存时都会读到
过期列表。

## 2. 后果：一次数据丢失风险

| 功能 | 入口 | 后果 |
|------|------|------|
| 素材管理器 | `scan_assets()` | 素材列表与"使用次数"与实际不符 |
| **删除未使用素材** | `UnusedAssetsDialog.scan()` | **致命**：未保存时新增的帧，其素材被误判为"未使用"而**物理删除**（数据丢失） |
| 复制素材到工程目录 | `CopyAssetsDialog.scan_assets()` | 复制的素材集合不完整 |

当时的对策是在每个入口补一行 `self.project.frames = self.timeline.get_all_frames()`。
问题在于**这是纪律而不是结构**：新增任何遍历帧的功能都要重新记得补这一行，而遗漏的
失败模式是静默删除用户文件。架构评审把它列为 P0-2。

顺带一个当时没被发现的同类问题：改画布尺寸时重算所有帧位置的循环
（`main_window` 的 project settings 处理）也读 `project.frames`，因此**上次同步之后
新增的帧不会被重算**。

## 3. 当前设计：属性委托到活跃数据源

`ProjectData.frames` 现在是一个属性：

```python
project.bind_frames_provider(self.timeline.get_all_frames)   # MainWindow 注入
```

- **绑定后**：读 `project.frames` 恒为 `TimelineModel` 的实时列表。
- **未绑定时**：回退到 `_static_frames`。这条路径专供两种场景——`from_json` 载入阶段
  （此时 timeline 还没填充），以及无 UI 的脚本 / 导出场景。
- **绑定后赋值会抛 `RuntimeError`**。写进去的东西永远不会被读到，那只能是旧同步模式
  留下的肌肉记忆，所以直接报错而不是静默失败。

绑定发生在三处（`src/ui/main_window.py`）：

| 位置 | 时机 |
|---|---|
| `__init__` | `self.timeline = TimelineWidget()` 之后立刻绑定 |
| `_reset_project_to_empty` | 新建工程会造一个新的 `ProjectData`，必须重新绑定 |
| `_load_from_path` | `from_json` 之后**立刻**绑定 |

`_load_from_path` 的顺序有讲究：

```python
self.project = ProjectData.from_json(json_str, path)
loaded_frames = self.project.frames        # 先取出载入的静态列表
self.project.bind_frames_provider(...)     # 再绑定
...
for frame in loaded_frames:                # 用局部变量驱动填充
    self.timeline.add_frame(...)
```

必须先取出再绑定：绑定后 `project.frames` 就是 timeline 的实时内容，用它驱动填充循环
会边遍历边追加（死循环），而且那一刻 timeline 里还是上一个工程的内容。

## 4. 使用须知

- **不要**再写 `project.frames = ...`。帧的增删改一律走 `TimelineModel`。
- `project.frames` 每次读取都返回**新列表**（`get_all_frames()` 是拷贝）。循环前先存
  到局部变量——`Exporter` 的三个导出方法都这么做，否则推导式里反复读取会退化成 O(n²)。
- 不要修改返回的那个列表（改了也不会生效）。但**修改列表里的 `FrameData` 对象是有效的**，
  会作用到模型上——改画布尺寸时重算帧位置就依赖这一点。
- 保存 / 导出 / 素材类对话框都不再需要任何同步动作。

## 5. 为什么不用更彻底的方案

评审里提过"把 `ProjectData` 降级为纯序列化 DTO、帧列表由 `TimelineModel` 独占持有"。
没走这条路的原因：`to_json` / `from_json` 是既定的持久化契约（`ProjectData` 是
`model/` 层，而 `TimelineModel` 在 `ui/` 层），让 `ProjectData` 直接依赖 `TimelineModel`
会造成 model → ui 的反向依赖。依赖注入一个 provider 回调把这个方向掰正了，同时保住了
持久化契约不变。

## 6. 回归测试

`dev/test_transform.py` 中的这几项锁定本设计：

| 测试 | 锁定的性质 |
|---|---|
| `test_frames_unbound_uses_static_list` | 未绑定时走后备列表（载入路径可用） |
| `test_frames_bound_reads_live_source` | 绑定后能看到实时新增的帧（P0-2 的核心） |
| `test_frames_assignment_after_binding_is_rejected` | 绑定后赋值必须报错 |
| `test_to_json_serializes_live_frames` | 存盘不再需要"先同步" |
| `test_from_json_roundtrip_still_works` | 载入阶段仍能正常写入帧 |
