# Code Review — P1-3 时间轴 model/view 迁移

- **评审对象**：`git diff --cached`（18 个文件，+3405 / -1124）
- **评审日期**：2026-08-29
- **上下文**：`CNB_PULL_REQUEST_IID` 未设置 → 本地评审，未发送 PR 评论
- **结论**：🔴 critical 项**已修复并验证**（连同 🟠 参考帧双份状态一并收敛）
- **状态更新（2026-08-29）**：critical、参考帧、夹具盲区、缓存失效四条均已处理并验证
  （缓存失效改为定向 `dataChanged`，新增 2 条回归测试）。
  死夹具 `test_long.json` / `test_long_.json` 已删除。剩余 🔵 两条文档/死参数仍待办。

变更把时间轴从 item-based widget 迁到 Qt model/view：
`TimelineModel`（业务真源，一维帧列表）
→ `TimelineItemModel`（Qt 适配层，把语义化信号翻译成 `beginInsertRows`/`dataChanged`/`beginResetModel`）
→ `TimelineListView`（`QTreeView`）+ `TimelineGridWidget`（`QListView`），两者共享同一个
`QItemSelectionModel`。

---

## 评审过程中的一处自我纠错

⚠️ 本节记录评审者自己犯的错，因为它差点成为一条**错误的高优先级问题**。

初版评审曾报：

> ⚠️ warning — `dev/test_long.json` 的 16 帧全部指向 `sample_test_long_file_name.jpg`，
> 该图片不存在于仓库，测试实际跑的是"源图缺失的降级路径"。

**这个判断是错的。** `dev/sample_test_long_file_name.jpg` 确实存在且可正常解析
（134 KB，768×1376 RGB）。

错因：判断存在性时用了 `os.path.exists('sample_test_long_file_name.jpg')`，而
`ProjectData` 的**相对路径是按项目文件所在目录解析的**（此处应解析为
`dev/sample_test_long_file_name.jpg`），我却用 CWD（仓库根）去解析 —— 当然不存在。

**教训**：验证"文件是否存在"之前，必须先确认**路径的相对基准是什么**。
用错误的基准去判断，会得出与事实完全相反的结论。

不过顺着这条线索**发现了一个真实且更要紧的问题**（见下方 🟠 第 2 条）：
`test_long.json` 的第 4 与第 15 帧参数完全相同，导致顺序断言对这两帧的交换**完全失明**。

---

## 问题清单

### 🔴 critical — 两个自定义角色取了同一个值【已修复】

**位置**：`src/ui/timeline_item_model.py:56` 与 `:66`

```python
ReferenceRole = Qt.ItemDataRole.UserRole + 2   # 258
ThumbnailRole = Qt.ItemDataRole.UserRole + 2   # 258  ← 同一个值！
```

**修复过程还挖出了更深的问题（远比角色冲突本身严重）**：

排查时发现 `data()` **根本没有实现** `ReferenceRole` 分支 —— 注释声称"参考帧状态
只存在一份"，但网格 delegate 实际读的是视图自己的 `reference_frame_data`。顺着查
下去，参考帧被拆成了**三份**：

| 存哪儿 | 谁写它 | 谁读它 |
|---|---|---|
| `TimelineModel._reference_frame`（业务模型） | 加载工程、`MainWindow.set_reference_frame` | 撤销恢复、参考帧计算 |
| `TimelineItemModel._reference_frame`（适配层副本） | `set_visual_reference_frame` | 列表显示 |
| `GridWidget.reference_frame_data`（视图副本） | `set_visual_reference_frame` | 网格高亮 |

三份互不同步。**最要命的是第 1 条路径**：加载工程/撤销恢复只写业务模型，改不到
副本 —— 参考帧是本项目的特色功能，却会出现"工程里设了参考帧、界面不亮"。

**已做的修复**：

1. `ReferenceRole` 改为 `UserRole + 3`，并在 `data()` 中实现（返回 `frame is
   <业务模型的参考帧>`）；
2. 加断言 `assert len({FrameDataRole, ReferenceRole, ThumbnailRole}) == 3` ——
   新增角色若漏改偏移，import 阶段就炸，不会拖到运行时变成"高亮莫名失效"；
3. **删除适配层的副本**，`_business_reference_frame()` 直接问业务模型；
4. **删除网格/列表的 `reference_frame_data` 副本**（连同 delegate 里的回退路径）；
5. 参考帧真源收敛到 `TimelineModel`，三个视图/适配层都读它。

**新增 4 条回归测试**（`verify_grid_view.py`，13 → 16）：
`test_delegate_paints_reference_highlight`、
`test_reference_frame_lives_in_business_model_only`、
`test_reference_role_is_not_thumbnail_role`、以及改写后的
`test_reference_frame_highlight_toggles_off`。

#### 这一轮最重要的教训：新写的测试第一版是**假阳性**

`test_delegate_paints_reference_highlight` 最初用
`set_visual_reference_frame()` 制造"有参考帧"状态再比对渲染像素。破坏验证显示
**它抓不到失效**：设参考帧会顺带触发 `refresh_all_items()` 重算缩略图，像素差异
遍布整个单元格（实测 2265 个差异点、覆盖全部 148 行），与高亮本身无关 ——
哪怕高亮完全失效，测试照样通过。

改为**只变 `ReferenceRole` 这一个变量**（patch `data()` 让它在两次渲染间取
True/False，其余一概不动）后才真正有效：破坏时精确报
"ReferenceRole 由 False 变 True 后渲染完全没变"。

这与本文档前文「补网过程中的教训」第 1 条是同一类错误：**断言必须落在被测行为上，
而不是落在"看起来相关"的副作用上**。

### 🟠 warning — 测试夹具存在顺序断言盲区

**位置**：`dev/test_long.json`（第 4 帧与第 15 帧）

实测：16 帧中第 4 与第 15 帧的 `(crop_rect, scale, rotation, is_disabled)` **完全相同**
（`((256, 275, 256, 275), 1.0, 0.0, False)`）。

`dev/smoke_reorder.py` 用 `sig()`（即上述四元组）做顺序断言，于是：

```
dev/test_long.json : 16帧, 120 种两两交换, 断言失明的交换数 = 1  [(4, 15)]
dev/test_long2.json: 15帧, 105 种两两交换, 断言失明的交换数 = 0
```

即：交换第 4 与第 15 帧，`sig()` **完全不变**，撤销/拖拽的顺序断言会**假通过**。

这是本项目反复出现的一类问题（参见 `architecture_review.md`「补网过程中的教训」
第 2 条：**测试数据必须能分辨被测行为**）。

**修法**：测试改用 `dev/test_long2.json` —— 详见文末「test_long2.json 可行性评估」。
该切换**已完成并验证通过**。

---

### 🟠 warning — 参考帧仍是两份状态，且注释与实现不符【已随 🔴 一并修复】

**位置**：`src/ui/timeline_item_model.py:53-54`（注释）、`src/ui/timeline_grid.py:173-175`

`timeline_item_model.py:53-54` 声称：

> 参考帧状态只存在一份（本类的 `_reference_frame`），视图与 delegate 都不再存镜像

但实际是两份：

| 视图 | 读谁 |
|---|---|
| 列表 | `model._reference_frame`（经 `BackgroundRole` / `FontRole`） |
| 网格 | `widget.reference_frame_data`（网格自己的属性，`timeline_grid_delegate.py:56`、`:174-175`） |

`set_visual_reference_frame` 只设自己那份，**不碰共享 model**。当前仅靠
`TimelineWidget.set_visual_reference_frame` 同时调两者才碰巧一致；任何只调其一的
路径都会让两个视图的参考帧高亮不一致。

**修法**：让网格也以共享 model 为唯一真源：

```python
# timeline_grid.py
def set_visual_reference_frame(self, frame_data):
    self.reference_frame_data = frame_data
    if self._item_model is not None:
        self._item_model.set_reference_frame(frame_data)   # 收进共享 model
    self.refresh_all_items()
```

并把 `timeline_grid_delegate.py` 里的 `frame_data is widget.reference_frame_data`
改为读 `index.data(ReferenceRole)`（需与 🔴 第 1 条一并处理）。
同时修正 `timeline_item_model.py:53-54` 那两句已与实现不符的注释。

**已实际采用的做法**（比上面更彻底）：不保留任何视图/适配层副本，参考帧真源收敛到
`TimelineModel`；`_business_reference_frame()` 直接问它。详见 🔴 那一节。

---

### 🟠 warning — 缓存失效不触发重绘，与 docstring 承诺不符【已修复】

> **修复（2026-08-29）**：`invalidate_thumbnail_cache_for_paths` 末尾调
> `_notify_rows_using_paths()`，只向"用了这批源图"的行发 `dataChanged`（连续行合并成
> 段，避免一张图被几十帧共用时逐行发信号）。**按行判断而非按删了几条缓存判断** ——
> 缓存按内容做 key，删除条数既不等于行数，也可能一个都不剩（行还没渲染过）。
> 同时删掉 `_reload_edited_images` 里那句补刷新的 `refresh_all_items()`（正是它掩盖了
> 缺陷）。新增 2 条回归：`test_invalidate_for_paths_notifies_rows_using_those_paths`
> （通知精确到行 + 无关路径不通知）、`test_invalidate_for_paths_repaints_viewport`
> （视口确实重画）。

**位置**：`src/ui/timeline_grid.py:147-157`

`invalidate_thumbnail_cache_for_paths()` 只做 `_thumbnail_cache.pop(...)`，**既不发
`dataChanged` 也不 `viewport().update()`**。

而 `TimelineItemModel.set_thumbnail_provider` 的 docstring
（`timeline_item_model.py:103-104`）明确写着：

> 缓存失效也由网格发起（`invalidate_thumbnail_cache_for_paths` → `dataChanged`）

文档承诺的行为并未实现。后果：外部编辑器改图后，若调用方忘记再手动调一次
`refresh_all_items()`，界面会静默显示旧缩略图。

**修法**：让实现兑现文档承诺，在该函数末尾补一次刷新：

```python
def invalidate_thumbnail_cache_for_paths(self, paths):
    ...
    for k in stale:
        self._thumbnail_cache.pop(k, None)
    if stale:
        self.refresh_all_items()   # 让视图按新的 ThumbnailRole 重取
```

若出于性能考虑不想全量刷新，可定位到受影响的行只发 `dataChanged`，
但无论如何不应让 docstring 继续保持错误。

---

### 🔵 info — docstring 描述的"写串视图"风险已不存在

**位置**：`src/ui/timeline.py:438-444`

`_apply_selection_to_view` 的 docstring 警告：

> 本方法也被 `_rebuild_list_view`/`_rebuild_grid_view` 调用，而它们重建的是**非当前**
> 视图……重建 list 时就会把 selection 写进 grid

迁移后两个视图共享同一个 `QItemSelectionModel`，写任一视图等价于写同一份选中，
不存在"写串视图"；且 `rebuild_current_view`（`:380-382`）现在只重建**当前**视图。
这类过时注释会误导后来者去防御一个不存在的问题。

**修法**：更新 docstring，说明共享 selectionModel 之后 `mode` 仅用于决定
`currentIndex` 取哪一列（列表用列 0、网格用 `modelColumn()`）。

---

### 🔵 info — 死参数 `index`

**位置**：`src/ui/timeline_grid.py:310`

```python
cache_key = self._get_cache_key(image_path, frame_data, index)
```

`_get_cache_key`（`:137-141`）明确不含 index，`:140` 的注释也说明了原因。
留着它容易让后来者误以为 index 参与缓存，进而误判"重排会导致缩略图重算"
（P2-7 已把这列进待办，实际**不会**重算 —— 这是刻意设计）。

**修法**：移除该参数，同步更新 `create_thumbnail` 的签名与所有调用点，
让"重排不会导致缩略图重算"在签名上一眼可见。

---

## test_long2.json 可行性评估

**结论：✅ 可行，且明显优于 `test_long.json`。已完成切换并验证通过。**

### 对比

| 指标 | `test_long.json` | `test_long2.json` |
|---|---|---|
| 帧数 | 16 | 15 |
| 不同帧签名数 | **15 / 16**（有 1 组重复） | **15 / 15**（全部可区分） |
| 顺序断言盲区 | **1 种交换失明** | **0 种** |
| 含 `slice_pos` 的帧 | 0 | **15（全部）** |
| 禁用的帧 | 1 | 2 |
| 含 `crop_rect` 的帧 | 16 | 15 |
| 源图 | 同一张（存在且可解析） | 同一张（存在且可解析） |
| 本机绝对路径泄漏 | 无（均为空串） | 无（均为空串） |

### 优势

1. **消除顺序断言盲区** —— 见 🟠 第 2 条，这是最主要的理由。
2. **多覆盖一个显示路径** —— 15 帧全部含 `slice_pos`，覆盖
   `_filename()` 里 `[行,列]` 后缀的拼接；`test_long.json` 一帧都没有。
   切换后立刻暴露了 `smoke_reorder.py` 里一处脆弱断言
   （`row0_file.endswith(".jpg")` 没考虑后缀），已修正为按基名校验。
3. 禁用帧更多（2 vs 1），`aspect_ratio` 等字段完整。

### 已做的改动

| 文件 | 改动 |
|---|---|
| `dev/smoke_reorder.py:70` | 夹具改 `test_long2.json` |
| `dev/smoke_reorder.py:127-131` | 文件名断言改为按基名校验（兼容 `slice_pos` 后缀） |
| `dev/run_all_checks.sh:98` | `require_file` 改 `test_long2.json`，并注明选择理由 |

### 验证结果

```
1/6 语法编译 main.py+src      PASS
2/6 几何与模型单测             PASS  (37/37)
3/6 渲染像素哈希 --compare     PASS  (MAIN_DIGEST ba2304d808c6aef3 一致)
4/6 双视图同步与拖拽           PASS  (25/25)
5/6 网格视图                   PASS  (13/13)
6/6 MainWindow 接线冒烟        PASS
                               → 6/6 PASS
```

### 遗留建议

- `dev/test_long_.json`（4 帧）全仓库**无任何引用**，是死文件，建议删除。
- `dev/test_long.json` 切换后也无引用了，可一并删除；若想保留作为"大工程"
  夹具，建议先修掉第 4/15 帧重复签名的问题（否则它会一直是个断言陷阱）。

---

## 仍需手动验证（无任何自动化覆盖）

1. 时间轴右键菜单
2. 外部文件拖入时间轴
3. 播放时的选中跟随
