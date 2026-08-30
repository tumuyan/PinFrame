"""时间轴「上行动作」信号的**唯一声明处**。

`TimelineWidget`、列表视图、网格视图三者共用 `TimelineViewSignals` 的实例，
因此这套信号只声明一遍（此前是三处各抄一遍，加一个右键菜单项要改三个文件）。

为什么是「持有一个 QObject 实例」而不是基类 / mixin
------------------------------------------------

评审（`dev/architecture_review.md` P1-3）把根因归结为「`BaseTimelineView` 不是
QObject，无法声明信号」，最直觉的修法自然是造一个声明信号的**基类**让两个视图
继承，让声明只剩一份。这条路在 PyQt6 里走不通，有两个独立的障碍：

1. **QObject 不能多继承。** 两个视图已经是 `QTreeView` / `QListView`。若本类
   继承 `QObject`，`class TimelineListView(TimelineViewSignals, QTreeView)` 就是
   两个 QObject 派生类并列，PyQt6 直接拒绝（instance lay-out conflict）。
2. **不继承 QObject 的 mixin 里，信号不会被激活。** `pyqtSignal` 是靠 pyqt 的元类
   在**类字典**里扫描并绑定的，它只认 QObject 派生类、且不回溯基类字典。把
   `pyqtSignal()` 写进一个普通 mixin 再混进 QObject 子类，访问到的是**未绑定**的
   `pyqtSignal` 对象 —— 不报错，但 `emit` 不了，症状是"菜单点了没反应"。

所以只能退一步：本类是 QObject，由使用者各自持有**一个实例**并暴露为
`self.signals`。代价是调用点多一层 `.signals.`；换来的是声明从三份降到一份。

不要试图用字符串/枚举来合并成一个 `action_requested(name)` 信号：那只是把
"三份声明"换成"三份字符串字面量"，拼错不报错，比现在更糟。
"""

from PyQt6.QtCore import QObject, pyqtSignal


class TimelineViewSignals(QObject):
    """列表视图 / 网格视图 → `TimelineWidget` 的上行通知，`TimelineWidget` 再转发给 `MainWindow`。

    每个持有者只 emit 与自己相关的那几个：`thumbnail_size_changed` 只有网格视图会
    发（列表视图没有缩略图尺寸这个概念），这是刻意的 —— 声明是三者共用的契约，
    发不发取决于具体视图的能力。

    `reorder_about_to_happen` 的时机有讲究：它必须在**改模型之前**发出（拖拽已算
    出目标位置、尚未调 `model.move_frames`），撤销快照才能抓到旧顺序。
    """

    selection_changed = pyqtSignal(list)
    order_changed = pyqtSignal()
    # 顺序变更前发出（拖拽已算出目标位置、尚未调用 model.move_frames）。
    # 撤销快照必须在改模型之前捕获，否则快照到的就是新顺序。
    reorder_about_to_happen = pyqtSignal()
    files_dropped = pyqtSignal(list, int)
    copy_properties_requested = pyqtSignal()
    paste_properties_requested = pyqtSignal()
    duplicate_requested = pyqtSignal()
    duplicate_dialog_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    disabled_state_changed = pyqtSignal(object, bool)
    enable_requested = pyqtSignal(bool)
    reverse_order_requested = pyqtSignal()
    integerize_offset_requested = pyqtSignal()
    smooth_params_requested = pyqtSignal()
    set_reference_requested = pyqtSignal()
    clear_reference_requested = pyqtSignal()
    edit_default_editor_requested = pyqtSignal()
    edit_in_editor_requested = pyqtSignal(object)  # 编辑器 dict（{name, path, default}）
    thumbnail_size_changed = pyqtSignal(int, int)  # width, height
