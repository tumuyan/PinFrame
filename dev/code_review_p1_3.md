# Code Review — P1-3 时间轴 model/view 迁移

- **评审对象**：`git diff --cached`（评审当时的暂存快照）
- **评审日期**：2026-08-29
- **上下文**：`CNB_PULL_REQUEST_IID` 未设置 → 本地评审，未发送 PR 评论
- **结论**：🔴 critical 项**已修复并验证**（连同 🟠 参考帧双份状态一并收敛）
- **状态更新（2026-08-29）**：critical、参考帧、夹具盲区、缓存失效四条均已处理并验证
  （缓存失效改为定向 `dataChanged`，新增 2 条回归测试）。
  死夹具 `test_long.json` / `test_long_.json` 已删除。剩余 🔵 两条文档/死参数仍待办。
- **行号校准（2026-08-29 复核）**：全文行号已按 HEAD `6b83466` 重校，对照表见文末
  「行号与进度校准」。引用行号的评审文档必然漂移，**用前先校**。
- **复核结论**：4 条已修复项复核全部属实，全量回归 9/9 PASS；🔵 两条确认仍待办，
  其中死参数一条复核时新发现连带死代码（见该节）。
- **进度（同日推进）**：🔵 两条均已修复并验证（9/9 PASS，`MAIN_DIGEST` 不变），
  问题清单 6 条全部关闭。

> **评审对象已入库**：当时的 `--cached` 快照对应提交 `2764051`
> （19 文件 +3196/-1139）。原记的「18 文件 +3405/-1124」是暂存快照与最终提交之间的
> 中间态，现已不可复现，**以 `2764051` 为准**。四条修复随后分 4 个提交落地：
> `4a686cb`（参考帧收敛到业务模型）→ `558ce0e`（跨工程残留 + 缓存失效通知）→
> `4ab91eb`（选中配色统一）→ `6b83466`（网格文件名重复绘制）。

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

**位置**：`src/ui/timeline_item_model.py:49`、`:59`、`:71`（校准后）

```python
FrameDataRole = Qt.ItemDataRole.UserRole + 1   # 257  ← :49
ThumbnailRole = Qt.ItemDataRole.UserRole + 2   # 258  ← :59
ReferenceRole = Qt.ItemDataRole.UserRole + 3   # 259  ← :71
assert len({FrameDataRole, ReferenceRole, ThumbnailRole}) == 3, ...   # ← :76
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

1. `ReferenceRole` 改为 `UserRole + 3`（`timeline_item_model.py:71`），并在 `data()`
   中实现（`:193-196`，返回 `frame is <业务模型的参考帧>`）；
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

**位置**：`src/ui/timeline_item_model.py:63-66`（注释，校准后）、
`src/ui/timeline_grid.py:211-222`、同族 `src/ui/timeline_list.py:325-332`

`timeline_item_model.py:63-66` 声称：

> 参考帧状态只存在一份（本类的 `_reference_frame`），视图与 delegate 都不再存镜像

但实际是两份：

| 视图 | 读谁 |
|---|---|
| 列表 | `model._reference_frame`（经 `BackgroundRole` / `FontRole`） |
| 网格 | `widget.reference_frame_data`（网格自己的属性，`timeline_grid_delegate.py:62`、`:181`） |

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
同时修正 `timeline_item_model.py:63-66` 那几句已与实现不符的注释。

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

**位置**：`src/ui/timeline_grid.py:151-167`（校准后；修复新增的
`_notify_rows_using_paths` 在 `:169` 起）

`invalidate_thumbnail_cache_for_paths()` 只做 `_thumbnail_cache.pop(...)`，**既不发
`dataChanged` 也不 `viewport().update()`**。

而 `TimelineItemModel.set_thumbnail_provider` 的 docstring
（`timeline_item_model.py:114`，校准后）明确写着：

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

**位置**：`src/ui/timeline.py:451-475`（校准后，原记 `:438-444`）
**状态**：✅ 已修复（2026-08-29），全量回归 9/9 PASS

`_apply_selection_to_view` 的 docstring 曾警告：

> 本方法也被 `_rebuild_list_view`/`_rebuild_grid_view` 调用，而它们重建的是**非当前**
> 视图……重建 list 时就会把 selection 写进 grid

迁移后两个视图共享同一个 `QItemSelectionModel`，写任一视图等价于写同一份选中，
不存在"写串视图"；且 `rebuild_current_view`（`:390-395`，校准后）现在只重建
**当前**视图。这类过时注释会误导后来者去防御一个不存在的问题。

**修法**：更新 docstring，说明共享 selectionModel 之后 `mode` 仅用于决定
`currentIndex` 取哪一列（列表用列 0、网格用 `modelColumn()`）。

**实际做法**：删掉那段"写串视图"警告并改写为 10 行。第一版写成了 24 行，其中 11 行
是"引用旧警告原文 + 论证其两条前提为何不成立 + 别再写回来"—— 那是给已删除的代码
写墓志铭，讲的全是过去而非当前代码。已按"描述当前行为、不记录变更历史"精简掉，
只留两条正面陈述：共享 selectionModel 使选中只有一份；`mode` 只决定列，其中
`currentIndex` 是锚点。

删掉旧警告不需要留"别写回来"的元注释：新 docstring 正面说明了"选中只有一份、
`mode` 只决定列"，与旧警告**直接矛盾**，谁想补回去都会立刻撞上。

精简后的 docstring 讲清三件事：

1. 两视图共享 selectionModel，选中只有一份 —— 这是理解"为什么 `mode` 不区分写哪个
   视图"的前提；
2. `mode` 现在只决定**列**：调哪个视图的 `_apply_selection_from_set`（两者构造
   `QModelIndex` 用的列不同：列表固定列 0、网格用 `modelColumn()`）；
3. `currentIndex` 落在哪一列。

第 3 点里加了一条原文没提的信息：`currentIndex` **是 Shift/Ctrl 连续多选的锚点**
（也决定键盘导航从哪一列起步），必须与用户正在看的视图一致 —— 这正是 `mode` 参数
至今仍需存在的真正理由。旧注释把 `mode` 的存在归因于一个已消失的风险，等于让这个
参数看起来是纯历史包袱，容易被人顺手删掉。

---

### 🔵 info — 死参数 `index`

**位置**（改动前）：`src/ui/timeline_grid.py:375`（`cache_key = ...` 那行，
原记 `:310`，漂移 +65 行）

```python
# :381  定义：def create_thumbnail(self, image_path, frame_data, index):
# :387  传参：cache_key = self._get_cache_key(image_path, frame_data, index)
# :322  唯一调用点：return self.create_thumbnail(frame_data.file_path, frame_data, row)
```

**状态**：✅ 已修复（2026-08-29），全量回归 9/9 PASS，`MAIN_DIGEST` 不变

`_get_cache_key`（`:141-145`）明确不含 index，`:144` 的注释也说明了原因。
留着它容易让后来者误以为 index 参与缓存，进而误判"重排会导致缩略图重算"
（P2-7 已把这列进待办，实际**不会**重算 —— 这是刻意设计）。

**修法**：移除该参数，同步更新 `create_thumbnail` 的签名与所有调用点，
让"重排不会导致缩略图重算"在签名上一眼可见。

**连带死代码**（复核时新发现，原文未记）：`create_thumbnail` 把 `index` 继续传给
`draw_overlays(..., index, draw_frame_number=False)`（`:418`），而 `draw_overlays`
（`:450-470`）里 `index` **只在 `draw_frame_number=True` 分支被用**（`:470`），
全仓库唯一调用点传的正是 `False`；帧号实际由 delegate 自己的
`_draw_frame_number`（`timeline_grid_delegate.py:584`）绘制。
即 `draw_overlays` 的 `index` 参数与整个 `draw_frame_number` 分支**都是死的**。
只改签名会留下"参数还在但永远走不到"的半吊子状态，应与本条一并清掉。

**实际做法**：一行 `index` 牵出整条链，比原文记的更深。完整改动 8 处：

| 位置 | 改动 |
|---|---|
| `timeline_grid.py:2-3` | 删 `QRectF` / `QBrush` / `QFont` —— **只**被死分支用到（AST 核验） |
| `timeline_grid.py:141-149` | `_get_cache_key` 删 `index`，注释扩为解释"刻意不含行号" |
| `timeline_grid.py:315-323` | `thumbnail_for_row(row, frame)` → `thumbnail_for_frame(frame)` |
| `timeline_grid.py:293` | 注入点同步改名 |
| `timeline_grid.py:381-387` | `create_thumbnail` 删 `index` |
| `timeline_grid.py:421` | `draw_overlays` 调用删 `index` 与 `draw_frame_number` |
| `timeline_grid.py:453-465` | `draw_overlays` 删 `index` 参数与整个帧号分支 |
| `timeline_item_model.py:103/204` | provider 契约 `provider(row, frame)` → `provider(frame)` |

`thumbnail_for_row` **必须一起改名**：去掉 `row` 参数却留着 "for_row" 的名字，等于
留一个与实现相反的说法 —— 名字本身也是一种需要维护的状态。

**验证**：

1. 全量回归 **9/9 PASS**。
2. `MAIN_DIGEST` = `ba2304d808c6aef3` 与改动前一致（基线文件 mtime 18:33 早于改动
   23:06，是真比对而非"缺失时静默建基线"的假通过）—— 逐像素不变，证明删掉的确实是
   从未执行的死分支。
3. **破坏验证**：临时把 `row` 塞回缓存 key（经 model 反查行号模拟该回归），
   `test_reorder_keeps_thumbnails_cached` 立刻失败并报出预期消息
   "移动的那帧缩略图被重算了（本应命中缓存）"，另有 3 条相关用例一并失败。
   这一步是必需的：参数从签名里消失后，该守卫是否还咬得住**不能靠推断** ——
   已实测它仍然有效，不是空断言。
4. 未新增测试：`test_reorder_keeps_thumbnails_cached` 已守住这条性质，而断言
   `inspect.signature` 属低价值脆断言。
5. **运行时直验**（针对 `startDrag` 那处改动）：`test_grid_multi_select_drag_starts_drag`
   虽用真实鼠标手势驱动到了 `startDrag`，但它只断言 `_dragged_rows`，**不覆盖
   `drag.setPixmap` 那一段** —— 报不出"缩略图取不到"这类错误。故另做了直接调用：
   构造真实网格 + 夹具源图，调 `thumbnail_for_frame` 得到 120×120 非空 `QPixmap`，
   并复跑 `startDrag` 里取图那两行；同时确认缓存 key 为 6 元素、首元素非行号。
   `thumbnail_for_frame` 在 `drag.exec()` **之前**调用，所以 stub 掉 `exec` 不会
   跳过它 —— 但测试不断言它，照样是盲区。

**顺带清理的存量未使用 import**（原记"与本条无关、不扩大 diff"，后按用户要求一并
清掉）：`QPoint` / `QModelIndex` / `QIcon` / `ThumbnailRole`。

它们是**改动前就存在**的存量问题（AST 对比 HEAD 核验：本次新引入 0 处），与本条死
参数无关。清掉前先排除了两类风险：

- **再导出**：全仓库只有 `timeline.py:4` 一句 `from ui.timeline_grid import
  TimelineGridWidget`，没有 `import *`，删哪个符号都不会连带断掉别人的导入。
- **动态引用**：逐个正则整词核验（`\bQPoint\b` 这类写法不会误伤 `QPointF`），
  四个名字除 import 行外**零出现**，不存在 `getattr` / 字符串取符号的漏检。

`ThumbnailRole` 特殊一点：它有 3 处出现，另 2 处在 docstring 的**行文**里（`:20`、
`:314`）。删 import 后这两处会指向一个本模块里不存在的裸名，故改为带限定的
`TimelineItemModel.ThumbnailRole`（该类确实在本模块导入，读起来仍是可解析的真实
符号），而不是留一个悬空引用。

清理后 AST 复查：**未使用 import 归零**。

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

| 文件 | 改动 | 校准后位置 |
|---|---|---|
| `dev/smoke_reorder.py` | 夹具改 `test_long2.json` | `:72`（原记 `:70`） |
| `dev/smoke_reorder.py` | 文件名断言改为按基名校验（兼容 `slice_pos` 后缀） | `:166-179`（原记 `:127-131`） |
| `dev/run_all_checks.sh` | `require_file` 改 `test_long2.json`，并注明选择理由 | `:141-146`（原记 `:98`，漂移 +43 行） |

### 验证结果

**原文记录（6 项时期，已过期）**：

```
1/6 语法编译 main.py+src      PASS
2/6 几何与模型单测             PASS  (37/37)
3/6 渲染像素哈希 --compare     PASS  (MAIN_DIGEST ba2304d808c6aef3 一致)
4/6 双视图同步与拖拽           PASS  (25/25)
5/6 网格视图                   PASS  (13/13)
6/6 MainWindow 接线冒烟        PASS
                               → 6/6 PASS
```

**2026-08-29 复核（HEAD `6b83466`，回归项已扩到 9 项）**：

```
1/9 重复定义（结构性）      PASS      6/9 网格视图                  PASS
2/9 语法编译 main.py+src    PASS      7/9 MainWindow 接线：重排     PASS
3/9 几何与模型单测          PASS  (37/37)   8/9 MainWindow 接线：参考帧  PASS
4/9 渲染像素哈希 --compare  PASS      9/9 选中配色跨平台一致        PASS
5/9 双视图同步与拖拽        PASS  (27/27)  → 9/9 PASS，5s
```

用例条数变化（原文数字已落后）：网格视图 **13 → 20**（评审新增 4 条 + 后续
`6b83466` 新增 1 条 + 其他）；双视图同步 **25 → 27**。几何单测 37/37 未变。

### 遗留建议

- ✅ `dev/test_long_.json`（4 帧）已删除。
- ✅ `dev/test_long.json` 已删除（`git ls-files` 确认仅剩 `test_long2.json`；
  旧文件只存在于 `.Trash-0/files/`，不入库）。

---

## 行号与进度校准（2026-08-29 复核，HEAD `6b83466`）

评审文档一旦写了行号就开始漂移。本节是**复核时的实测值**与原文记值的对照，
后续使用本文请以此为准。

| 引用对象 | 原文记值 | 校准后 | 漂移 |
|---|---|---|---|
| 三角色定义 | `timeline_item_model.py:56` / `:66` | `:49` / `:59` / `:71` | 结构性变化 |
| 角色唯一性断言 | 未记 | `:76-77` | 新增 |
| `ReferenceRole` 数据分支 | 未记 | `:193-196` | 新增 |
| 参考帧注释 | `timeline_item_model.py:53-54` | `:63-66` | +10 |
| 网格 `set_visual_reference_frame` | `timeline_grid.py:173-175` | `:211-222` | +38 |
| （同族）列表版 | 未记 | `timeline_list.py:325-332` | 新增 |
| delegate 读参考帧 | `timeline_grid_delegate.py:56` / `:174-175` | `:62` / `:181` | +6 / +7 |
| `invalidate_thumbnail_cache_for_paths` | `timeline_grid.py:147-157` | `:151-167` | +4 |
| `_notify_rows_using_paths`（修复新增） | 未记 | `timeline_grid.py:169` 起 | 新增 |
| `set_thumbnail_provider` docstring | `timeline_item_model.py:103-104` | `:114` | +10 |
| `_apply_selection_to_view` docstring | `timeline.py:438-444` | `:451-475`（已改写） | +13 |
| `rebuild_current_view` | `timeline.py:380-382` | `:390-395` | +10 |
| 死参数 `index` 传参行 | `timeline_grid.py:310` | `:387`（已删该参数） | 已修复 |
| `_get_cache_key` | `timeline_grid.py:137-141`（注释 `:140`） | `:141-149` | +4 |
| `create_thumbnail` 定义 | 未记 | `timeline_grid.py:381` | 已修复 |
| 唯一调用点 | 未记 | `timeline_grid.py:322` | 已修复 |
| smoke_reorder 夹具路径 | `dev/smoke_reorder.py:70` | `:72` | +2 |
| smoke_reorder 文件名断言 | `dev/smoke_reorder.py:127-131` | `:166-179` | +39 |
| run_all_checks `require_file` | `dev/run_all_checks.sh:98` | `:141-146` | +43 |

**进度**

| 项 | 原文状态 | 复核状态 |
|---|---|---|
| 🔴 角色取值冲突 | 已修复 | ✅ 已验证（`assert` 在 import 期生效） |
| 🟠 夹具顺序断言盲区 | 已完成切换 | ✅ 已验证（`git ls-files` 仅剩 `test_long2.json`） |
| 🟠 参考帧双份状态 | 已随 🔴 修复 | ✅ 已验证（三处副本全无，20 条网格用例含 4 条专项） |
| 🟠 缓存失效不重绘 | 已修复 | ✅ 已验证（定向 `dataChanged` + 2 条回归） |
| 🔵 过时 docstring | 待办 | ✅ **已修复**（`timeline.py:451-461`，9/9 PASS） |
| 🔵 死参数 `index` | 待办 | ✅ **已修复**（8 处，含连带死分支；9/9 PASS、`MAIN_DIGEST` 不变） |
| 全量回归 | 6/6 | ✅ **9/9 PASS**（6s） |

→ **本文 6 条问题清单现已全部关闭。** 剩余只有文末「仍需手动验证」那 3 项
（右键菜单 / 外部文件拖入 / 播放时选中跟随），它们从无任何自动化覆盖，与本次评审
的问题清单无关。

---

## 仍需手动验证（无任何自动化覆盖）

1. 时间轴右键菜单
2. 外部文件拖入时间轴
3. 播放时的选中跟随
