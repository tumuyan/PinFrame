# project.frames 与 timeline 的同步规则

本文档说明 PinFrame 中 `ProjectData.frames` 与 `TimelineModel` 之间的关系，以及**为什么任何"工程级功能"在打开前必须先从 timeline 同步一次**。

## 1. 背景：两份数据，一个真源

PinFrame 遵循"**一份数据、一个真源、一个写入口、多视图只读**"的架构原则：

- **真源（source of truth）**：`TimelineModel`（timeline）持有帧列表的实时状态。
- **快照（stale snapshot）**：`ProjectData.frames` 是 `ProjectData`（文档对象）中的一个字段，**只在特定时机从 timeline 同步**，其余时间是一个"过期快照"。

用户的一切编辑操作（增 / 删 / 排序 / 复制 / 翻转 / 改帧属性 / 删除素材）**只改 timeline，并不会同步 `project.frames`**。

`project.frames` 仅在这些时机才从 timeline 同步：

- 保存 `_save_to_path`
- 导出（导出前显式 `self.project.frames = self.timeline.get_all_frames()`）
- 素材管理器删除引用后 `_remove_assets_refs`

## 2. 问题：未保存时"工程级功能"读到过期数据

任何**直接遍历 `project.frames`** 的功能，在用户尚未保存、仅做了内存编辑时，都会读到**过期**的帧列表。这会带来两类后果：

| 功能 | 入口 | 后果 |
|------|------|------|
| 素材管理器 | `scan_assets()` | 新增 / 删除帧后，素材列表与"使用次数"与实际不符 |
| **删除未使用素材** | `UnusedAssetsDialog.scan()` | **致命**：未保存时新增的帧，其素材会被误判为"未使用"而被**物理删除**（数据丢失） |
| 复制素材到工程目录 | `CopyAssetsDialog.scan_assets()` | 复制的素材集合不完整 / 过期 |

## 3. 规则：工程级入口先同步

**任何需要按当前工程帧状态计算的功能，在其入口处（打开对话框前）必须先执行一次：**

```python
self.project.frames = self.timeline.get_all_frames()
```

这正是导出与 `_remove_assets_refs` 已在用的既有模式，架构完全一致、零 UI 摩擦，永远反映真实（含未保存）状态，从根上消除误删风险。

当前已按此规则修复的三个入口（`src/ui/main_window.py`）：

- `copy_assets_to_local`
- `open_asset_manager`
- `delete_unused_assets`

## 4. 什么时候不需要同步

- 保存 / 导出：本身就会同步，不需要额外做。
- 只依赖 `timeline` 的功能（播放、画布渲染、时间轴视图）：本来就该读 timeline，不涉及 `project.frames`。

## 5. 经验要点

- 新增任何"遍历帧"的功能前，先判断它的数据来源：**该读 `timeline` 还是 `project.frames`？**
- 只要决定读 `project.frames`，就要在**入口**同步一次，别指望它是新鲜的。
- 删除磁盘文件这类不可逆操作，宁可多同步一次也不能让数据过期。
