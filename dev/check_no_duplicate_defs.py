#!/usr/bin/env python3
"""结构性检查：同一个命名空间里不许有**重复的类/函数/方法定义**。

---------------------------------------------------------------------------
为什么需要这条检查（而不是靠 review 发现）
---------------------------------------------------------------------------
Python 对重名定义**既不报错也不警告** —— 后出现的静默覆盖先出现的，前者从此
是死代码。于是"我改了这段代码怎么没效果"这类问题会以最费解的形式出现：
`inspect.getsource()` 显示的是你改的那份，实际跑的是文件后面的另一份。

`MainWindow` 真实踩过：`configure_reference_settings` 定义了 3 份、
`update_onion_state` 定义了 3 份，都是复制粘贴后忘了删。排查参考帧问题时，
同一片区域里躺着 5 个永不执行的函数体，严重误导定位。

覆盖范围：
  - 类体内的方法（含嵌套类）；
  - 模块顶层的**类**（见下方"类的判据"）；
  - 模块顶层的函数（dev/ 的测试脚本尤其要查：它们的 `_run_all()` 用
    `globals()` 收集 `test_` 函数，重名会让其中一个**静默不跑** —— 测试数量
    少一条却不报错，是最难察觉的假通过）。

---------------------------------------------------------------------------
判据一（函数/方法）：只有"至少一个定义不带任何装饰器"才报错
---------------------------------------------------------------------------
以下三种重名是**合法**的，必须放行，否则这个检查会淹没在误报里：

  - `@property` + `@x.setter` / `@x.deleter`（同一个属性的读写端）；
  - `@pyqtSlot(int)` + `@pyqtSlot(str)` 之类 Qt 的重载槽；
  - `typing.overload`。

它们有一个共同点：**每个定义都带装饰器**。而真人复制粘贴出来的死定义几乎都
是裸 `def`（`MainWindow` 那 5 份无一例外）。所以判据定为：重名且**存在不带
装饰器的定义** → 报错；全都带装饰器 → 视为有意的重载，放行。

代价：两个都带 `@staticmethod` 的真重复会被漏掉。这个漏网概率远低于"误报多到
没人看"，且那种写法本身罕见，接受。

---------------------------------------------------------------------------
判据二（类）：同名即报错，不看装饰器
---------------------------------------------------------------------------
这条是 2026-08-30 补的 —— 本检查原先只收集 `FunctionDef`，**完全看不见类**，
于是一份 `src/utils/exporter.py` 里躺着两个 `ExportError`（一个 `@dataclass`、
一个 `@dataclass(frozen=True)`）而本项全绿通过。

函数的装饰器判据**不能沿用到类**：类没有"重载"这回事，同名 class 后定义必然
覆盖前定义，没有例外。而 `@dataclass` / `@dataclass(frozen=True)` 恰恰是类最常
见的装饰器 —— 沿用"全都带装饰器就放行"会**正好放行**这类重复，等于没查。

实测过那份重复定义的迷惑性：`inspect.getsourcelines()` 报告的是**前面那份
死代码**的行号，而 `frozen` 等类属性来自后面那份。`inspect` 显示正确、行为却
是另一份，正是本检查存在的理由。

类与函数同名也报（后定义覆盖前定义，同样静默）。

---------------------------------------------------------------------------
自检（self-test）
---------------------------------------------------------------------------
本脚本自己必须先被验证：一个永远返回 0 的检查器比没有检查更糟 —— 它给你虚假
的安全感。所以 `self_test()` 用三段内置源码验证"该报的报、不该报的不报"，
自检不过直接退出 1，**不等同于被测代码有问题**。

依赖：仅标准库（比 PyQt6 那几项快得多，适合放在回归最前面）。
运行： ./venv/bin/python dev/check_no_duplicate_defs.py
退出码：0 = 无重复；1 = 检出重复，或自检失败。
"""
import ast
import collections
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# 扫描范围：入口 + src 全部 + dev 的脚本（dev 的理由见文件头）。
SCAN_GLOBS = ("src/**/*.py", "dev/*.py")
SCAN_FILES = ("main.py",)

# 已知例外。留在这里是为了让"还有活儿没干"显式可见，而不是悄悄跳过。
#
# 此集合**应当恒为空**。它曾装过 `src/ui/temp_prop.py`（`PropertyPanel` 的旧副本、
# 无人 import），那个"死文件"已于 2026-08-30 随 P3-10 删除，检查从此覆盖全仓库。
#
# 若将来又想往这里加东西，先问一句"能不能直接删掉那个文件"：放进本集合等于
# 让它永久躲过检查，而"死文件"的正确处理是删除（git 保有历史），不是豁免。
# 唯一合理的例外是"重名是有意的且无法改名"（如 vendored 的第三方代码），
# 那种情况要在此写明理由与预计的移除时间。
EXCLUDE_FILES = frozenset()


#: 一个命名空间体里可能出现重名的定义节点类型。
#:
#: **`ast.ClassDef` 必须在这里。** 它原先不在（只收集函数），于是顶层重复的类
#: 定义完全查不出来 —— `src/utils/exporter.py` 的两个 `ExportError` 就是这么
#: 混过全量回归的。类的判据与函数不同，见 `_duplicates`。
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _duplicates(body):
    """返回 (名字, [行号...])；函数的放行规则见文件头，类同名一律报。

    为什么按名字分组后再判断装饰器：property 的 getter/setter 是两个不同节点，
    必须放在一起看才知道它们是"一对"，逐个节点看装饰器永远看不出来。
    """
    by_name = collections.defaultdict(list)
    for n in body:
        if isinstance(n, _DEF_NODES):
            by_name[n.name].append(n)

    out = []
    for name, defs in by_name.items():
        if len(defs) < 2:
            continue
        # 只要组里有类，就**不看装饰器**直接报：类没有重载语义，@dataclass 也
        # 不产生新的类型标识（详见文件头"判据二"）。
        if any(isinstance(d, ast.ClassDef) for d in defs):
            out.append((name, sorted(d.lineno for d in defs)))
            continue
        # 剩下的全是函数：全都带装饰器 → 判为有意的重载，放行
        if all(d.decorator_list for d in defs):
            continue
        out.append((name, sorted(d.lineno for d in defs)))
    return sorted(out)


def check_source(source, filename):
    """检查一段源码，返回 [(限定名, [行号...]), ...]。"""
    tree = ast.parse(source, filename=filename)
    found = []

    top = _duplicates(tree.body)
    for name, lines in top:
        found.append((name, lines))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for name, lines in _duplicates(node.body):
                found.append((f"{node.name}.{name}", lines))

    return found


def iter_python_files():
    seen = set()
    for name in SCAN_FILES:
        p = REPO_ROOT / name
        if p.is_file():
            seen.add(p)
    for pattern in SCAN_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            seen.add(p)
    for p in sorted(seen):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel in EXCLUDE_FILES:
            continue
        yield p, rel


#: 自检用例：`(说明, 源码, 是否应当报出)`。
#:
#: 放模块级而不是 `self_test()` 里，是为了让 `main()` 能打印例数 —— 例数写死在
#: 字符串里每次加用例都会漂，而漂了的例数会让人误以为自检还是原来那些。
SELF_TEST_CASES = [
        ("两个裸 def 同名（复制粘贴的典型形态）",
         "class A:\n    def f(self):\n        return 1\n    def f(self):\n        return 2\n",
         True),
        ("property getter + setter（合法，必须放行）",
         "class A:\n"
         "    @property\n    def f(self):\n        return 1\n"
         "    @f.setter\n    def f(self, v):\n        self._v = v\n",
         False),
        ("两个 pyqtSlot 式重载（都带装饰器，放行）",
         "class A:\n"
         "    @pyqtSlot(int)\n    def f(self, i):\n        pass\n"
         "    @pyqtSlot(str)\n    def f(self, s):\n        pass\n",
         False),
        ("同名但只有一个（不该报）",
         "class A:\n    def f(self):\n        return 1\n",
         False),
        ("模块级裸 def 重名（dev/ 测试脚本的典型形态）",
         "def test_x():\n    pass\n\ndef test_x():\n    pass\n",
         True),
        ("一裸一带装饰器（真重复：裸的那份是死代码）",
         "class A:\n    def f(self):\n        return 1\n"
         "    @staticmethod\n    def f():\n        return 2\n",
         True),
        # ---- 类：同名即报，不看装饰器（文件头"判据二"）-------------------
        # 这两个用例是 2026-08-30 补的，对应的正是当时漏网的真实缺陷：
        # exporter.py 里 `@dataclass class ExportError` 与
        # `@dataclass(frozen=True) class ExportError` 并存。
        ("两个同名 @dataclass（类不适用函数的装饰器放行规则）",
         "@dataclass\nclass E:\n    x: int\n"
         "@dataclass(frozen=True)\nclass E:\n    x: int\n    y: int\n",
         True),
        ("类与同名函数（后定义覆盖先定义，同样静默）",
         "class E:\n    pass\n\ndef E():\n    pass\n",
         True),
        ("同名类只有一个（不该报）",
         "@dataclass\nclass E:\n    x: int\n",
         False),
]


def self_test():
    """验证检查器本身有效 —— 该报的报，不该报的不报。"""
    failures = []
    for label, src, should_report in SELF_TEST_CASES:
        found = check_source(src, "<self_test>")
        reported = bool(found)
        if reported != should_report:
            failures.append(
                f"  {label}: 期望{'报出' if should_report else '放行'}，"
                f"实际{'报出' if reported else '放行'}")
    return failures


def main():
    print("自检检查器本身…")
    failures = self_test()
    if failures:
        print("FAIL  自检未通过 —— 检查器本身有问题，下面的结果不可信：")
        print("\n".join(failures))
        return 1
    # 例数动态算：写死数字每次加用例都会漂（曾经就是这么错的）
    print(f"  自检通过（{len(SELF_TEST_CASES)} 例：该报的报、该放行的放行）")

    total = 0
    offenders = []
    for path, rel in iter_python_files():
        total += 1
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"  跳过（读取失败）: {rel}: {e}")
            continue
        try:
            found = check_source(source, rel)
        except SyntaxError as e:
            # 语法错误由第 1 项 compileall 负责，这里不重复报错
            print(f"  跳过（语法错误）: {rel}: {e}")
            continue
        if found:
            offenders.append((rel, found))

    print(f"扫描 {total} 个文件")
    if not offenders:
        print("OK: 无重复定义")
        return 0

    print(f"FAIL: {len(offenders)} 个文件存在重复定义")
    print("     Python 只保留**最后**一个定义，前面的永不执行。")
    print("     类同名一律报（类无重载语义）；函数只在有裸 def 时报（放行 property/")
    print("     pyqtSlot/overload 那类带装饰器的重载）。")
    for rel, found in offenders:
        print(f"  {rel}")
        for name, lines in found:
            loc = ", ".join(f"第 {n} 行" for n in lines)
            print(f"    {name}  ({loc})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
