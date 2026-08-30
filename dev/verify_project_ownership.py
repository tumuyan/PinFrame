#!/usr/bin/env python3
"""结构性检查：`MainWindow` 持有 `ProjectData` 的契约不许被绕过。

---------------------------------------------------------------------------
为什么需要这条检查（而不是靠 review 发现）
---------------------------------------------------------------------------
`MainWindow` 有三条**互相支撑**的约定。它们的共同点是：**违反后程序照常运行，
全量回归照样全绿** —— 症状要么根本不出现，要么在很久以后以毫不相关的形式出现。

  - `project` 是只读 property，替换工程对象的唯一途径是 `_adopt_project()`。
    只要有人图省事写回 `self.project = ...`（或加一个 setter），就退回
    "换对象"与"重新绑定 frames 数据源"可能只发生其一的旧状态 —— 任何持有
    旧引用的协作者都会静默读到过期工程对象。
  - `_adopt_project()` 内部先赋值、后绑定；调用方必须先 `timeline.clear()`。
    次序反了会让新工程**短暂报告上一个工程的帧**。
  - 两个视图的公开接口够用了，因此不该再有跨层私有访问。

其中次序这条尤其阴险：**两种次序的终态完全相同**。按错误次序，adopt 那一刻新工程
报告的是上一个工程的帧数，而终态是对的 —— 所以任何"跑一遍看结果"的测试都测不到，
只有像本文件这样在 AST 上比较行号才能拦住。

---------------------------------------------------------------------------
六条判据
---------------------------------------------------------------------------
1. `self.project = ...` 的赋值点为 0（backing 字段是 `_project`，只允许
   `__init__` 初始化与 `_adopt_project` 内部两处 `self._project = ...`）。
2. `main_window.py` 里函数/方法体内的 `import` 为 0 —— 一律提到模块顶部。
   刻意**只扫这一个文件**：它已从 35 处清到 0，这条是守住成果。
   `src/` 下另有 5 个文件还有少量函数内 import（多为真实懒加载），一刀切
   会误报，故不纳入。
3. 跨层私有访问 `self.timeline._*` / `self.timeline.grid_view._*` 为 0。
   出现即说明 `TimelineWidget` 的公开接口不够用，正确做法是补公开接口。
4. `bind_frames_provider` 的调用点恰好 1 处，且位于 `_adopt_project` 内。
5. `_load_from_path` / `_reset_project_to_empty` 中，`self.timeline.clear()`
   必须早于 `self._adopt_project(...)`。
6. `MainWindow.project` 必须有 `@property` getter 且**没有 setter**。
   有 setter 就等于允许随处替换，#1 会被合法绕过。

---------------------------------------------------------------------------
自检（self-test）
---------------------------------------------------------------------------
一个永远返回 0 的检查器比没有检查更糟 —— 它给虚假的安全感。所以 `self_test()`
用内置源码验证每条判据"该报的报、该放行的放行"，自检不过直接退出 1。

依赖：仅标准库。
运行： ./venv/bin/python dev/verify_project_ownership.py
退出码：0 = 全部符合；1 = 有违反项，或自检失败。
"""
import ast
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "src" / "ui" / "main_window.py"

# 跨层私有访问的"前缀"。MainWindow 伸手进这些前缀即视为越界。
CROSS_LAYER_PREFIXES = ("self.timeline._", "self.timeline.grid_view._")

# 必须先 `timeline.clear()` 再 `_adopt_project()` 的方法。
ADOPTERS = ("_load_from_path", "_reset_project_to_empty")


# ---------------------------------------------------------------------------
# AST 小工具
# ---------------------------------------------------------------------------
def _dotted(node):
    """把 `a.b.c` 这样的 Attribute 链还原成字符串；不是纯名称链则返回 None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _iter_funcdefs(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _decorator_names(node):
    names = []
    for d in node.decorator_list:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(d.attr)
    return names


def _find_class(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


# ---------------------------------------------------------------------------
# 六条判据
# ---------------------------------------------------------------------------
def check_no_project_assignment(tree):
    """#1 `self.project = ...` 必须为 0 处。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for t in targets:
            if _dotted(t) == "self.project":
                out.append((node.lineno,
                            "self.project = ... —— project 是只读 property，"
                            "替换工程对象请走 _adopt_project()"))
    return out


def check_no_indented_imports(tree):
    """#2 函数/方法体内的 import 必须为 0 处（一律提到模块顶部）。"""
    out = []
    for func in _iter_funcdefs(tree):
        for sub in ast.walk(func):
            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                out.append((sub.lineno,
                            "函数内 import: %s （在 %s() 内，请提到模块顶部）"
                            % (ast.unparse(sub), func.name)))
    return out


def check_no_cross_layer_private(tree):
    """#3 跨层私有访问必须为 0 处。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted(node)
        if dotted and any(dotted.startswith(p) for p in CROSS_LAYER_PREFIXES):
            out.append((node.lineno,
                        "跨层私有访问: %s —— TimelineWidget 的公开接口不够用时，"
                        "正确做法是补一个公开方法，不是伸手进私有成员" % dotted))
    return out


def check_single_bind_site(tree):
    """#4 bind_frames_provider 恰好 1 处，且在 _adopt_project 内。"""
    sites = []
    for func in _iter_funcdefs(tree):
        for sub in ast.walk(func):
            if isinstance(sub, ast.Call):
                dotted = _dotted(sub.func) or ""
                if dotted.endswith(".bind_frames_provider"):
                    sites.append((sub.lineno, func.name))

    out = []
    if len(sites) != 1:
        out.append((sites[0][0] if sites else 0,
                    "bind_frames_provider 调用点应为 1 处，实际 %d 处: %s"
                    % (len(sites), sites)))
    for lineno, owner in sites:
        if owner != "_adopt_project":
            out.append((lineno,
                        "bind_frames_provider 出现在 %s() 内 —— 绑定只允许发生在 "
                        "_adopt_project() 里" % owner))
    return out


def check_clear_before_adopt(tree):
    """#5 clear() 必须早于 _adopt_project()。

    注意用 min() 而不是"遍历时第一次遇到"：`ast.walk` 按嵌套层级（BFS）走，
    不是按行号，直接取首个匹配会拿到错误的那个。
    """
    out = []
    for func in _iter_funcdefs(tree):
        if func.name not in ADOPTERS:
            continue
        clears, adopts = [], []
        for sub in ast.walk(func):
            if not isinstance(sub, ast.Call):
                continue
            dotted = _dotted(sub.func) or ""
            if dotted == "self.timeline.clear":
                clears.append(sub.lineno)
            elif dotted == "self._adopt_project":
                adopts.append(sub.lineno)

        if not clears or not adopts:
            out.append((func.lineno,
                        "%s() 中缺少 self.timeline.clear() 或 self._adopt_project(...) "
                        "调用（本检查的前提不成立？）" % func.name))
        elif min(clears) > min(adopts):
            out.append((func.lineno,
                        "%s() 次序反了：clear() 在第 %d 行，_adopt_project() 在第 %d 行 "
                        "—— 绑定后 project.frames 就是 timeline 的实时内容，先绑定会让"
                        "新工程短暂报告【上一个工程】的帧"
                        % (func.name, min(clears), min(adopts))))
    return out


def check_project_is_readonly(tree):
    """#6 project 必须有 @property getter、没有 setter。"""
    cls = _find_class(tree, "MainWindow")
    if cls is None:
        return [(0, "找不到 class MainWindow —— 本检查的前提不成立（改名了？）")]

    has_getter = has_setter = False
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "project":
            continue
        decs = _decorator_names(node)
        if "property" in decs:
            has_getter = True
        if "setter" in decs:
            has_setter = True

    out = []
    if not has_getter:
        out.append((cls.lineno,
                    "MainWindow.project 不是 @property —— 只读契约就是靠它实现的"))
    if has_setter:
        out.append((cls.lineno,
                    "MainWindow.project 有 setter —— 有 setter 就等于允许随处替换工程"
                    "对象，判据 #1 会被合法绕过（替换请走 _adopt_project()）"))
    return out


ALL_CHECKS = (
    check_no_project_assignment,
    check_no_indented_imports,
    check_no_cross_layer_private,
    check_single_bind_site,
    check_clear_before_adopt,
    check_project_is_readonly,
)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
SRC_GOOD = '''
import os

class MainWindow:
    @property
    def project(self):
        return self._project

    def _adopt_project(self, project):
        self._project = project
        project.bind_frames_provider(self.timeline.get_all_frames)

    def _load_from_path(self, path):
        self.timeline.clear()
        self._adopt_project(project)
        self.timeline.apply_selection_to_view([])
        self.timeline.clear_thumbnail_cache()

    def _reset_project_to_empty(self):
        self.timeline.clear()
        self._adopt_project(ProjectData())
'''

SRC_ASSIGN = '''
class MainWindow:
    def _load_from_path(self, path):
        self.project = ProjectData()
        self.timeline.clear()
        self._adopt_project(self.project)
'''

SRC_IMPORT = '''
import os

class MainWindow:
    def open_thing(self):
        from PyQt6.QtCore import Qt
'''

SRC_CROSS = '''
class MainWindow:
    def f(self):
        self.timeline._apply_selection_to_view([])
        self.timeline.grid_view._clear_thumbnail_cache()
'''

SRC_BIND_OUTSIDE = '''
class MainWindow:
    def _load_from_path(self, path):
        self.timeline.clear()
        project.bind_frames_provider(self.timeline.get_all_frames)
'''

SRC_ORDER = '''
class MainWindow:
    def _adopt_project(self, project):
        project.bind_frames_provider(self.timeline.get_all_frames)

    def _reset_project_to_empty(self):
        self._adopt_project(ProjectData())
        self.timeline.clear()
'''

SRC_SETTER = '''
class MainWindow:
    @property
    def project(self):
        return self._project

    @project.setter
    def project(self, value):
        self._project = value
'''

# (标签, 源码, 要验的检查函数, 是否应报出)。检查函数为 None 表示跑全部六条。
SELF_TEST_CASES = (
    ("self.project = 赋值（该报）", SRC_ASSIGN, check_no_project_assignment, True),
    ("函数内 import（该报）", SRC_IMPORT, check_no_indented_imports, True),
    ("跨层私有访问（该报）", SRC_CROSS, check_no_cross_layer_private, True),
    ("bind 出现在 _adopt_project 外（该报）", SRC_BIND_OUTSIDE,
     check_single_bind_site, True),
    ("clear 晚于 adopt（该报）", SRC_ORDER, check_clear_before_adopt, True),
    ("project 带 setter（该报）", SRC_SETTER, check_project_is_readonly, True),
    ("合规形态（六条全放行）", SRC_GOOD, None, False),
)


def self_test():
    """验证检查器本身有效 —— 该报的报，该放行的放行。"""
    failures = []
    for label, source, check_fn, should_report in SELF_TEST_CASES:
        tree = ast.parse(source, filename="<self_test>")
        checks = (check_fn,) if check_fn else ALL_CHECKS
        found = []
        for fn in checks:
            found.extend(fn(tree))
        reported = bool(found)
        if reported != should_report:
            detail = "; ".join("第 %d 行 %s" % (n, m) for n, m in found) or "无"
            failures.append(
                "  %s: 期望%s，实际%s（%s）"
                % (label, "报出" if should_report else "放行",
                   "报出" if reported else "放行", detail))
    return failures


# ---------------------------------------------------------------------------
def main():
    print("自检检查器本身…")
    failures = self_test()
    if failures:
        print("FAIL  自检未通过 —— 检查器本身有问题，下面的结果不可信：")
        print("\n".join(failures))
        return 1
    print("  自检通过（7 例：6 条判据各 1 反例 + 1 份合规形态全放行）")

    if not TARGET.is_file():
        print("FAIL: 找不到目标文件: %s" % TARGET)
        return 1

    try:
        source = TARGET.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(TARGET))
    except (OSError, UnicodeDecodeError) as e:
        print("FAIL: 读取失败: %s: %s" % (TARGET, e))
        return 1
    except SyntaxError as e:
        print("FAIL: 语法错误（第 2 项 compileall 会先报，这里不重复判定）: %s" % e)
        return 1

    print("扫描 %s" % TARGET.relative_to(REPO_ROOT).as_posix())

    found = []
    for fn in ALL_CHECKS:
        found.extend(fn(tree))

    if not found:
        print("OK: ProjectData 持有契约完好（6 条判据全过）")
        return 0

    print("FAIL: 检出 %d 处违反 —— 契约见本文件顶部「六条判据」" % len(found))
    for lineno, msg in sorted(found):
        print("  第 %d 行: %s" % (lineno, msg))
    return 1


if __name__ == "__main__":
    sys.exit(main())
