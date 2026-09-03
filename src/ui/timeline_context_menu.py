"""时间轴右键菜单的**唯一构建处**。

此前 `TimelineListView.show_context_menu` 与 `TimelineGridWidget.show_context_menu`
是逐行复制的两份（除一行注释外完全相同）。那意味着每加一个菜单项要改两处，
漏改一处就表现为"列表视图有这个命令、网格视图没有" —— 而右键菜单是本项目
**完全没有自动化覆盖**的三项之一（`dev/run_all_checks.sh` 结尾明示），这类漏改
只能靠人眼发现。收敛成一份之后，两个视图的菜单结构不可能再漂移。

为什么不放在 `timeline.py`（`TimelineWidget`）里：菜单是**视图**的能力，由视图
在 `customContextMenuRequested` 时自己弹；`TimelineWidget` 是容器，它只负责把
视图的上行信号转发给 `MainWindow`（见 `_connect_view_signals`），不该反过来替视图
决定菜单长什么样。

本模块刻意**不含任何业务逻辑**：每个 QAction 只 `emit` 一个上行信号，真正的
执行体全在 `MainWindow`。视图因此不需要知道"复制属性"或"适配分辨率"是怎么
实现的，加命令时也不必碰视图的其它部分。
"""

import os

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from i18n.manager import i18n


def build_timeline_context_menu(parent, signals, selected_count, editors=None):
    """构建时间轴右键菜单；**不** exec，由调用方决定弹出位置。

    `parent` 是发起菜单的视图（同时作为各 QAction 的父对象，随视图一起销毁）。
    `signals` 是该视图持有的 `TimelineViewSignals` 实例 —— 由调用方传入而非从
    `parent` 上取，是为了让本函数不依赖视图的具体类型：列表视图与网格视图都
    把它暴露为 `self.signals`，直接传进来即可。
    `selected_count` 由调用方给出而非在这里查选择模型：视图自己有更直接的取法
    （`get_selected_indices()`），且本模块不必知道 `QItemSelectionModel`。
    `editors` 是外部图像编辑器列表，为空时隐藏对应的子菜单。

    菜单项按"影响范围递增"排列：先是与选中帧相关的，再是影响整个工程的
    （调整项目分辨率，收在同名子菜单里），最后是破坏性的（删除帧）。

    子菜单里可能挂着 `setVisible(False)` 的项（当前是「内接矩形」）：命令已接线
    但尚未对外暴露。本函数仍然照常构建并连接它们 —— 隐藏只是显示层的开关，
    不代表这条链路被废弃。
    """
    menu = QMenu()
    has_selection = selected_count > 0

    copy_action = QAction(i18n.t("action_copy_props"), parent)
    copy_action.triggered.connect(signals.copy_properties_requested.emit)
    copy_action.setEnabled(has_selection)

    paste_action = QAction(i18n.t("action_paste_props"), parent)
    paste_action.triggered.connect(signals.paste_properties_requested.emit)

    dup_action = QAction(i18n.t("action_dup_frame"), parent)
    dup_action.triggered.connect(signals.duplicate_requested.emit)
    dup_action.setEnabled(has_selection)

    dup_dialog_action = QAction(i18n.t("action_dup_frames_dialog"), parent)
    dup_dialog_action.triggered.connect(signals.duplicate_dialog_requested.emit)
    dup_dialog_action.setEnabled(has_selection)

    rem_action = QAction(i18n.t("action_rem_frame"), parent)
    rem_action.triggered.connect(signals.remove_requested.emit)
    rem_action.setEnabled(has_selection)

    disable_action = QAction(i18n.t("disable_frame_label", "Disable Frame(s)"), parent)
    disable_action.triggered.connect(lambda: signals.enable_requested.emit(False))
    disable_action.setEnabled(has_selection)

    enable_action = QAction(i18n.t("enable_frame_label", "Enable Frame(s)"), parent)
    enable_action.triggered.connect(lambda: signals.enable_requested.emit(True))
    enable_action.setEnabled(has_selection)

    reverse_action = QAction(i18n.t("action_reverse_order"), parent)
    reverse_action.triggered.connect(signals.reverse_order_requested.emit)
    reverse_action.setEnabled(selected_count > 1)

    int_action = QAction(i18n.t("action_integerize"), parent)
    int_action.triggered.connect(signals.integerize_offset_requested.emit)
    int_action.setEnabled(has_selection)

    smooth_action = QAction(i18n.t("action_smooth_params"), parent)
    smooth_action.triggered.connect(signals.smooth_params_requested.emit)
    smooth_action.setEnabled(selected_count > 1)

    menu.addAction(copy_action)
    menu.addAction(paste_action)
    menu.addSeparator()
    menu.addAction(int_action)
    menu.addAction(smooth_action)
    menu.addSeparator()
    menu.addAction(disable_action)
    menu.addAction(enable_action)
    menu.addAction(reverse_action)
    menu.addSeparator()

    ref_action = QAction(i18n.t("action_set_reference"), parent)
    ref_action.triggered.connect(signals.set_reference_requested.emit)
    ref_action.setEnabled(selected_count == 1)

    clear_ref_action = QAction(i18n.t("action_clear_reference"), parent)
    clear_ref_action.triggered.connect(signals.clear_reference_requested.emit)

    menu.addAction(ref_action)
    menu.addAction(clear_ref_action)
    menu.addSeparator()

    # ---- 调整项目分辨率（子菜单）----
    #
    # 为什么是子菜单而不是平铺：这四个命令改的是**整个工程**的分辨率（影响所有
    # 帧与三种导出模式），与菜单上其余"只作用于选中帧"的命令不是同一层级的东西。
    # 平铺会让主菜单一下多出 4 项，且其中"裁剪"那两项会静默切掉内容 —— 收进子
    # 菜单既压住了长度，也让"这是一组影响全局的命令"在结构上可见。
    #
    # 组内分两组，与菜单项上的括注对应：
    #   - "（缩放）"：画布 + 所有帧同除以一个因子，构图逐点不变，只有导出的
    #     像素数变了。X / Y 是两个不同的解，因为两个方向的倍率独立。
    #   - "（裁剪）"：只改画布尺寸、帧参数一个都不动，超出新画布的部分被切掉。
    #     两组命令的后果完全不同，括注就是为了让这个区别在一眼可见，避免点错。
    #
    # 这里**不显示算出来的分辨率**：多选时它只反映第一帧（或并集），显示一个
    # 数字反而会让人误以为所有帧都变成那个尺寸。
    #
    # 整组的可用性挂在子菜单上（`menuAction()`），而不是逐个 action —— 空选中时
    # 子菜单整体置灰，用户点不开、也不会看到一屏灰项。必须取 `menuAction()`：
    # `QMenu.setEnabled()` 作用的是那个弹出控件本身，管不到它在父菜单里的条目。
    # 组内 action 因此不再各设一次 `setEnabled` —— 四个命令本身对空选中都安全
    # （各自 `if not selected: return`，`dev/verify_fit_resolution.py` 有断言）。
    fit_width_action = QAction(i18n.t("action_fit_res_width_pixel"), parent)
    fit_width_action.setToolTip(i18n.t("action_fit_res_width_pixel_tip"))
    fit_width_action.triggered.connect(signals.fit_width_pixel_exact_requested.emit)

    fit_height_action = QAction(i18n.t("action_fit_res_height_pixel"), parent)
    fit_height_action.setToolTip(i18n.t("action_fit_res_height_pixel_tip"))
    fit_height_action.triggered.connect(signals.fit_height_pixel_exact_requested.emit)

    fit_circ_action = QAction(i18n.t("action_fit_res_circumscribed"), parent)
    fit_circ_action.setToolTip(i18n.t("action_fit_res_circumscribed_tip"))
    fit_circ_action.triggered.connect(signals.fit_circumscribed_requested.emit)

    fit_insc_action = QAction(i18n.t("action_fit_res_inscribed"), parent)
    fit_insc_action.setToolTip(i18n.t("action_fit_res_inscribed_tip"))
    fit_insc_action.triggered.connect(signals.fit_inscribed_requested.emit)

    fit_menu = menu.addMenu(i18n.t("menu_fit_resolution"))
    fit_menu.menuAction().setEnabled(has_selection)
    fit_menu.addAction(fit_width_action)
    fit_menu.addAction(fit_height_action)
    fit_menu.addSeparator()
    fit_menu.addAction(fit_circ_action)
    fit_menu.addAction(fit_insc_action)

    # 「内接矩形」暂时隐藏（`setVisible(False)`），不删除。
    #
    # 原因：`inscribed_size()` 固定的是**源图**宽高比，而源图旋转 90° 之后导出
    # 位图已经转置（`rotated_bitmap_size()` 走 PIL 的 transpose 捷径），两者的
    # 比例不再对应 —— 200×100 转 90° 会算出 (100, 50)，画布只剩内容的 1/4。
    # 90° 恰恰是精灵编辑里最常见的角度，且它**本来没有透明角**（内接本应等于
    # 外接），所以在修好之前不能暴露给用户。
    #
    # 命令、信号、几何函数与单测全部保留（详见 `dev/verify_fit_resolution.py`
    # 的说明），恢复时删掉下面这一行即可 —— 隐藏态下它仍是唯一覆盖这条链路的
    # 自动化。用 `setVisible(False)` 而不是不 `addAction`：前者明确表达"菜单上
    # 有这一项、暂时不显示"，后者看起来像漏接。
    fit_insc_action.setVisible(False)

    menu.addSeparator()

    menu.addAction(dup_action)
    menu.addAction(dup_dialog_action)
    menu.addAction(rem_action)

    # ---- 外部图像编辑器 ----
    if has_selection:
        menu.addSeparator()
        default_action = QAction(i18n.t("action_edit_default_editor"), parent)
        default_action.triggered.connect(signals.edit_default_editor_requested.emit)
        menu.addAction(default_action)
        if editors:
            editor_menu = menu.addMenu(i18n.t("menu_edit_external_editor"))
            for ed in editors:
                name = ed.get("name") or os.path.basename(ed.get("path") or "")
                act = editor_menu.addAction(name)
                act.triggered.connect(
                    lambda checked=False, ed=ed: signals.edit_in_editor_requested.emit(ed))
        else:
            default_action.setEnabled(False)

    return menu
