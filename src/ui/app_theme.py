"""应用程序主题样式表（QSS）的**数据模块**。

本文件只装两个字符串常量与一个取值函数 —— 从 `main_window.apply_theme()` 里搬过来
的，除**去掉了外层那级缩进**（原 QSS 是方法体内的三引号字符串）外逐字一致：搬运是
用脚本按行提取的，不是手工重录。把 QSS 留在
`apply_theme` 里，`main_window.py` 就凭空多出近 300 行**纯字面量**：它既没有控制
流、也不参与任何计算，却让那个文件的行数指标看起来像"上帝对象"，从而误导后来者
去拆其实并不复杂的方法 —— 搬运当时 `apply_theme` 有 331 行、其中 87% 是 QSS 字面
量（现已落在本文件，那里只剩 26 行控制流），拆类是错的工具。

留在 `main_window.py` 里的只有取用与刷新那一小段控制流。

---------------------------------------------------------------------------
改这里要遵守的两条硬约束
---------------------------------------------------------------------------
1. **选中色必须用占位符**，不能直接写颜色值。
   同一个"选中色"被三种互不相干的机制使用（本文件的 QSS、网格 delegate 的
   QColor、列表"禁用"列 delegate），三处各写一份必然不一致 —— 历史上正是如此：
   QSS 写 `#094872`、delegate 写 `#0078D7`，效果是"同一个选中帧上下两截两种颜色"。
   唯一真源是 `ui.timeline_selection_style`，本模块通过 `apply_to_qss()` 取用。

2. **QSS 只认 `/* */` 注释**，`#` 在那里是 ID 选择器（如 `QPushButton#playBtn`）。
   写成 `# 注释` 会让 Qt 解析失败并**中断整个样式表的后续解析**，后面所有规则
   静默失效（Qt 只在 stderr 打一句 "Could not parse stylesheet"，GUI 程序里根本
   看不见）。这个坑踩过。所以下面两个字符串里**一行注释都不能有**，说明一律写在
   字符串外面。

改动这里请跑：`dev/verify_selection_style.py`（切 Fusion / Windows 双样式验证
像素一致且对比度达标）。
"""

from ui.timeline_selection_style import apply_to_qss

# 时间轴视图那两条规则的说明（**刻意写在字符串外面**，理由见模块 docstring）：
#
# 选择器必须是 `QTreeView, QListView`：QSS 的 Type Selector 只匹配"该类及其子类"，
# 而这两个视图的基类正是 QTreeView/QListView。写 `QTreeWidget` 匹配的是它的
# **子类**，反过来不成立，规则一次都不会生效 —— 选中色于是全交给平台调色板，
# Windows 上取决于用户自定义的系统强调色，表现为"多选时看不清哪帧被选中"。
#
# `@SELECTED_BG@` / `@SELECTED_FG@` 是占位符，由下面的 `stylesheet_for()` 经
# `apply_to_qss()` 换成 `ui.timeline_selection_style.py` 的真值。网格底部文字条由
# delegate 自绘，两边必须同一个值，否则一个选中帧会被切成两种颜色。
#
# 为什么用占位符而不是 f-string：QSS 通篇是 `{` `}`，整段改成 f-string 要把每一个
# 花括号转义成 `{{` `}}`，几百处手工转义必然出错，且出错后 QSS 静默失效。占位符
# 只动那两行，代价最小。

DARK_QSS = """
QMainWindow, QDialog, QMessageBox {
    background-color: #252526;
    color: #CCCCCC;
}
QWidget {
    background-color: #252526;
    color: #CCCCCC;
}
QMainWindow::separator {
    background-color: #333333;
    width: 4px;
    height: 4px;
}
QMainWindow::separator:hover {
    background-color: #007ACC;
}
QDockWidget {
    background-color: #2D2D2D;
    color: #CCCCCC;
}
QDockWidget::title {
    background-color: #333333;
    padding: 4px;
    text-align: center;
}
QMenuBar {
    background-color: #2D2D2D;
    color: #CCCCCC;
    border-bottom: 1px solid #333;
}
QMenuBar::item:selected {
    background-color: #3E3E3E;
}
QMenu {
    background-color: #2D2D2D;
    color: #CCCCCC;
    border: 1px solid #454545;
}
QMenu::item:selected {
    background-color: #007ACC;
    color: white;
}
QToolBar {
    background-color: #2D2D2D;
    border: none;
    spacing: 5px;
    padding: 3px;
}
QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 3px;
}
QToolButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
}
QStatusBar {
    background-color: #007ACC;
    color: white;
}
QPushButton {
    background-color: #3E3E42;
    color: #CCCCCC;
    border: 1px solid #454545;
    padding: 4px 8px;
    border-radius: 3px;
    min-width: 60px;
}
QRadioButton, QCheckBox {
    spacing: 8px;
    color: #CCCCCC;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #454545;
    border-radius: 9px;
    background-color: #333333;
}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background-color: #007ACC;
    border: 3px solid #454545;
    width: 12px;
    height: 12px;
}
QPushButton:hover {
    background-color: #4E4E52;
    border: 1px solid #007ACC;
}
QPushButton:pressed {
    background-color: #2D2D30;
}
QPushButton#playBtn:checked {
    background-color: #28a745;
    color: white;
    border: 1px solid #1e7e34;
    font-weight: bold;
}
QPushButton#revPlayBtn:checked {
    background-color: #17a2b8;
    color: white;
    border: 1px solid #117a8b;
    font-weight: bold;
}
QSpinBox, QDoubleSpinBox {
    color: #CCCCCC;
}
QLineEdit {
    background-color: #333333;
    color: #CCCCCC;
    border: 1px solid #454545;
    padding: 2px;
    selection-background-color: #007ACC;
}
QHeaderView::section {
    background-color: #333333;
    color: #CCCCCC;
    border: 1px solid #454545;
    padding: 4px;
}
QTreeView, QListView {
    background-color: #1E1E1E;
    color: #CCCCCC;
    border: none;
}
QTreeView::item:selected, QListView::item:selected {
    background-color: @SELECTED_BG@;
    color: @SELECTED_FG@;
}
QGroupBox {
    border: 1px solid #454545;
    margin-top: 10px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px 0 3px;
    color: #007ACC;
}"""

# 亮色主题。时间轴两条规则与暗色主题同源，说明见上面的注释块。
#
# 选中色与暗色主题**同一个值**（理由见 ui/timeline_selection_style.py）：原先这里
# 是 `#E5F3FF` 淡蓝底 + 黑字，在白底上对比度仅约 1.1，多选时几乎看不出哪些行被
# 选中，故改成实色底 + 白字（4.50）。
LIGHT_QSS = """
QMainWindow, QDialog, QMessageBox {
    background-color: #F3F3F3;
    color: #333333;
}
QWidget {
    background-color: #F3F3F3;
    color: #333333;
}
QMainWindow::separator {
    background-color: #CCCCCC;
    width: 4px;
    height: 4px;
}
QMainWindow::separator:hover {
    background-color: #007ACC;
}
QDockWidget {
    background-color: #E0E0E0;
    color: #333333;
}
QDockWidget::title {
    background-color: #D6D6D6;
    padding: 4px;
}
QMenuBar {
    background-color: #E0E0E0;
    color: #333333;
    border-bottom: 1px solid #CCCCCC;
}
QMenuBar::item:selected {
    background-color: #D0D0D0;
}
QMenu {
    background-color: white;
    color: #333333;
    border: 1px solid #CCCCCC;
}
QMenu::item:selected {
    background-color: #007ACC;
    color: white;
}
QToolBar {
    background-color: #E0E0E0;
    border: none;
    padding: 3px;
}
QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 3px;
}
QToolButton:hover {
    background-color: rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(0, 0, 0, 0.1);
}
QStatusBar {
    background-color: #007ACC;
    color: white;
}
QPushButton {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #CCCCCC;
    padding: 4px 8px;
    border-radius: 3px;
}
QRadioButton, QCheckBox {
    spacing: 8px;
    color: #333333;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #CCCCCC;
    border-radius: 9px;
    background-color: #FFFFFF;
}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background-color: #007ACC;
    border: 3px solid #CCCCCC;
    width: 12px;
    height: 12px;
}
QPushButton:hover {
    background-color: #F0F7FF;
    border: 1px solid #007ACC;
}
QPushButton#playBtn:checked {
    background-color: #4CAF50;
    color: white;
    border: 1px solid #388E3C;
    font-weight: bold;
}
QPushButton#revPlayBtn:checked {
    background-color: #03A9F4;
    color: white;
    border: 1px solid #0288D1;
    font-weight: bold;
}
QSpinBox, QDoubleSpinBox {
    color: #333333;
}
QLineEdit {
    background-color: white;
    color: #333333;
    border: 1px solid #CCCCCC;
    padding: 2px;
}
QHeaderView::section {
    background-color: #EAEAEA;
    color: #333333;
    border: 1px solid #CCCCCC;
    padding: 4px;
}
QTreeView, QListView {
    background-color: white;
    color: #333333;
    border: 1px solid #EEEEEE;
}
QTreeView::item:selected, QListView::item:selected {
    background-color: @SELECTED_BG@;
    color: @SELECTED_FG@;
}
QGroupBox {
    border: 1px solid #CCCCCC;
    margin-top: 10px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px 0 3px;
    color: #007ACC;
}"""


def stylesheet_for(theme_name: str) -> str:
    """返回指定主题的**完整**样式表（占位符已替换成真值）。

    判据是 `== "dark"`，其余一律按亮色处理 —— 与搬运前 `apply_theme` 的
    `if / else` 语义完全一致，不要"顺手"改成 `!= "light"` 之类的等价写法：
    两个分支不对称（dark 是显式分支），将来加第三个主题时这个差别会咬人。
    """
    qss = DARK_QSS if theme_name == "dark" else LIGHT_QSS
    # 不做这步，QSS 里会留着字面的 `@SELECTED_BG@`，Qt 解析失败后**静默丢弃整条
    # 规则** —— 选中色又悄悄退回平台调色板，正是历史上要修的现象，且极难察觉。
    return apply_to_qss(qss)
