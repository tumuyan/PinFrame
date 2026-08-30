"""应用级 `QSettings` 的单一来源（P3-8）。

原来 `QSettings("tumuyan", "PinFrame")` 在 6 处各自 new（`image_formats.py` 3、
`editor_settings_dialog.py` 2、`main_window.py` 1），org/app 名是复制粘贴的字面量。

收拢的价值**不是**"少几个对象" —— QSettings 对同一 (org, app) 本来就共享底层
存储，构造多少次行为都一样。真正的价值是：

1. org/app 名只有一处，将来改名或换存储后端只改这里；
2. 调用点不再重复构造，读代码时"配置存在哪"是一眼可见的，而不是散在 6 处；
3. 将来若要给 key 加统一前缀、迁移或默认值注册表，这里是唯一的落点。

**这里刻意不做** key 名常量表与默认值注册表：全应用 34 个 key 的搬迁改完行为
完全不变、也不消除任何既有缺陷，属于"能独立成一坨"但收益不成立的机械搬迁 ——
详见 dev/architecture_review.md 的「P3 实施计划」事实 3。
"""
from PyQt6.QtCore import QSettings

ORG_NAME = "tumuyan"
APP_NAME = "PinFrame"

_instance = None


def settings() -> QSettings:
    """返回进程内共享的 QSettings 实例（懒创建）。

    为什么缓存实例而不每次 new：不缓存也**不会**出错（同一 org/app 共享底层
    存储），但每次 new 都要重新解析一次组织/应用名与后端位置，而这三个模块里
    有的调用点在高频路径上（`image_formats.is_supported` 由模块级缓存挡着，
    但 `editor_settings_dialog` 的读写是直接的）。
    """
    global _instance
    if _instance is None:
        _instance = QSettings(ORG_NAME, APP_NAME)
    return _instance


# 调用点约定：**不要在调用点调 `clear()` / `sync()` / `remove()`。**
#
# 共享实例是一把双刃剑：org/app 名单点化（本模块存在的理由）顺带让三个模块的
# 读写都落在**同一个 QSettings 对象**上。于是 `clear()` 不再是"清我这块配置"，
# 而是清掉全应用 34 个 key（含语言、主题、布局比例、外部编辑器列表）；`sync()`
# 同理会把别人的待写改动一并落盘。
#
# 需要清某一项时，用 `settings().remove("<具体的 key>")`。
