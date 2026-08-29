"""时间轴"选中"配色的**单一真源**。

---------------------------------------------------------------------------
为什么必须有这个文件
---------------------------------------------------------------------------
同一个"选中色"同时被三种**互不相干**的机制使用：

  - `main_window.py` 的 **QSS 字符串** —— 控制列表视图的普通列、网格的图标区；
  - `timeline_grid_delegate.py` 的 **QColor** —— 控制网格底部文字条（它先用
    `CompositionMode_Source` 把 Qt 刚画好的背景清空，再自己填一遍）；
  - `timeline_list.py` 的 `_DisableColumnDelegate` —— 控制"禁用"列（它同样会用
    `palette.base()` 铺满整格，把选中背景整块盖掉）。

三处各写一份就必然不一致。历史上正是如此：QSS 写 `#094872`、delegate 写
`#0078D7`，效果就是"同一个选中帧，上半截和下半截两个颜色"。

---------------------------------------------------------------------------
为什么两个主题共用同一个色
---------------------------------------------------------------------------
选中态是**高亮**，在暗底和亮底上都要突出。这个蓝在 `#1E1E1E` 暗底上对比度
3.71、在白底上 4.50（WCAG 相对亮度公式），两侧都够。存两份常量只会多一处
需要同步的地方，没有收益。

---------------------------------------------------------------------------
两个硬约束（违反就是 bug）
---------------------------------------------------------------------------
1. **必须不透明（alpha = 255）**。
   半透明会让**底下平台画好的选中色**透出来，混成第三种颜色 —— 那正是本次
   要消灭的"选中色随平台而变"。网格 delegate 原本用 alpha 200/220，必须改掉。

2. **不能依赖 `option.palette`**。
   调色板的值由平台样式（Fusion / Windows / macOS）决定，用户还能在系统设置里
   改强调色。曾经"禁用"列用 `palette.base()` 铺底，Windows 下就在整行选中色里
   切出一个异色缺口 —— 用户看到的就是"多选时看不清哪帧被选中"。

改动这里请跑：`dev/verify_selection_style.py`（会切 Fusion / Windows 双样式
验证像素一致且对比度达标）。
"""

from PyQt6.QtGui import QColor

#: 选中行背景（QSS 与 delegate 共用；十六进制串给 QSS，QColor 给 delegate）
SELECTED_BG = "#0078D7"
#: 选中行前景
SELECTED_FG = "#FFFFFF"

# 只读使用，不要在绘制里就地修改它。
SELECTED_BG_QCOLOR = QColor(SELECTED_BG)
SELECTED_FG_QCOLOR = QColor(SELECTED_FG)

#: QSS 占位符 —— 在 `main_window.apply_theme()` 里被替换为上面的常量。
#:
#: 为什么用占位符而不是 f-string：QSS 通篇是 `{` `}`，整段改成 f-string 要把
#: 每一个花括号转义成 `{{` `}}`，几百处手工转义必然出错，且出错后 QSS 静默失效
#: （Qt 只打一句警告）。占位符只动那一行，代价最小。
PLACEHOLDER_BG = "@SELECTED_BG@"
PLACEHOLDER_FG = "@SELECTED_FG@"


def apply_to_qss(qss: str) -> str:
    """把占位符替换成真正的颜色值。"""
    return qss.replace(PLACEHOLDER_BG, SELECTED_BG).replace(PLACEHOLDER_FG, SELECTED_FG)
