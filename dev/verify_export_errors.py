#!/usr/bin/env python3
"""导出失败可见化的回归验证。

为什么单独一个文件
------------------
本项修的是一类**没有报错、没有崩溃、功能看起来完全正常**的失败：素材文件没了，
导出照样跑完，PNG 序列照样写文件（写出一张全透明的空图）、精灵表留一个空格、
GIF 补一个空白帧。用户的观感是"导出完成"，直到打开才发现少了几张。

这类缺陷不可能被"跑一遍看结果"发现 —— 结果就是正常的。所以本脚本断言的是
**错误清单本身**：`errors` 出参里有没有该有的条目、缺帧时有没有写出空文件。

要钉住的三条契约
----------------
1. `compose_frame` 返回 `False` 必须被看见。它**不抛异常**（源文件缺失 / 缩放后
   尺寸退化为 0），三个导出点此前都忽略这个返回值 —— 这是本项的主体。
2. 缺帧时**不产出**该帧的文件。PNG 序列写出空图比不写更糟：空图看起来像"素材
   本来就是空的"，用户不会往"源文件丢了"那个方向想。
3. `errors=None` 时行为与加本参数之前完全一致。这是向后兼容的底线 ——
   `transform_baseline.py` 与 `verify_image_cache.py` 都还在不传参地调用。

运行： ./venv/bin/python dev/verify_export_errors.py
退出码非 0 表示有失败。
"""
import atexit
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from PIL import Image  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from model.project_data import FrameData, ProjectData  # noqa: E402
from utils.exporter import ExportFailedError, Exporter  # noqa: E402

app = QApplication(sys.argv)

_TMP = None


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _tmpdir():
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix="pinframe_exporterr_")
        atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
    return _TMP


def _subdir(name):
    """每个用例一个干净的输出目录 —— 断言"文件不存在"时不能被上一个用例污染。"""
    path = os.path.join(_tmpdir(), name)
    os.makedirs(path, exist_ok=True)
    for n in os.listdir(path):
        os.remove(os.path.join(path, n))
    return path


def _png(name, w, h, color=(200, 40, 40, 255)):
    """生成一张纯色 PNG，返回绝对路径。"""
    path = os.path.join(_tmpdir(), name)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    assert img.save(path), f"夹具写入失败: {path}"
    return path


def _project(paths, w=32, h=32):
    """每帧一张**独立**源图的工程。

    刻意不用精灵表（多帧共用一张）：本项要验的是"某一帧的源图没了"，共用一张源图
    会让删一个文件连带影响所有帧，分不清"缺的是哪一帧"。
    """
    p = ProjectData(fps=12, width=w, height=h)
    p.frames = [FrameData(file_path=path) for path in paths]
    return p


# ---------------------------------------------------------------------------
# 用例：compose_frame 的返回值必须被看见（本项的主体）
# ---------------------------------------------------------------------------

def test_missing_source_is_recorded_in_png_sequence():
    """PNG 序列：源图缺失要记一条 missing_source，且**不写出**该帧的文件。"""
    good = _png("seq_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "seq_DOES_NOT_EXIST.png")
    assert not os.path.exists(missing), "夹具失效：这个文件不该存在"

    project = _project([good, missing])
    out = _subdir("out_missing_seq")
    errors = []

    list(Exporter.export_iter(project, out, errors=errors))

    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].kind == "missing_source", \
        f"错误种类应为 missing_source，实际 {errors[0].kind}"
    # 帧号是**工程内**下标：时间轴里它是第 2 帧
    assert errors[0].frame_index == 1, \
        f"帧号应为工程内下标 1，实际 {errors[0].frame_index}"

    # 缺帧不该产出空文件：空图会让用户以为"素材本来就是空的"
    names = sorted(n for n in os.listdir(out) if n.endswith(".png"))
    assert names == ["seq_good.png"], \
        f"缺帧的源图不该产出文件（那会是一张全透明的空图），实际产出 {names}"

    written = Image.open(os.path.join(out, "seq_good.png"))
    assert written.size == (32, 32), "正常帧应照常导出"


def test_missing_source_is_recorded_in_sprite_sheet():
    """精灵表：源图缺失要记一条，且该格**留空但不占位错位**。"""
    good = _png("sheet_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "sheet_DOES_NOT_EXIST.png")
    project = _project([good, missing])
    sheet_path = os.path.join(_subdir("out_sheet"), "sheet.png")

    errors = []
    Exporter.export_sprite_sheet(project, sheet_path, errors=errors)

    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].kind == "missing_source", \
        f"错误种类应为 missing_source，实际 {errors[0].kind}"
    assert os.path.exists(sheet_path), "精灵表本身应照常产出"

    # 缺帧不该让后续帧整体错位：格子仍然占位，只是空白
    sheet = Image.open(sheet_path)
    cols = project.export_sheet_cols
    pad = project.export_sheet_padding
    expected_w = cols * project.width + (cols + 1) * pad
    assert sheet.width == expected_w, \
        f"精灵表宽度应为 {expected_w}（缺帧也要占位），实际 {sheet.width}"


def test_missing_source_is_recorded_in_gif():
    """GIF：源图缺失要记一条，且**不补空白帧**（补帧会改变动画时长与节奏）。"""
    good = _png("gif_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "gif_DOES_NOT_EXIST.png")
    project = _project([good, missing])
    gif_path = os.path.join(_subdir("out_gif"), "out.gif")

    errors = []
    Exporter.export_gif(project, gif_path, errors=errors)

    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].kind == "missing_source", \
        f"错误种类应为 missing_source，实际 {errors[0].kind}"
    assert os.path.exists(gif_path), "其余帧成功时 GIF 应照常产出"

    with Image.open(gif_path) as im:
        assert getattr(im, "n_frames", 1) == 1, \
            "缺帧不该补空白帧 —— 那会让动画时长和节奏都变掉"


def test_degenerate_size_is_distinguished_from_missing_source():
    """缩放导致尺寸退化为 0 时，kind 必须是 `degenerate_size` 而非 `missing_source`。

    `compose_frame` 对两种失败都只回 `False`，区分全靠 `_compose_into_canvas` 里
    那句 `os.path.exists` —— 而它是靠**猜**的（"文件在，那只能是尺寸退化"）。
    这个推断没有任何用例钉住，一旦 `compose_frame` 将来多一个 return False 的
    分支，这里就会开始谎报原因，而"源图丢了"和"缩放得太小"的用户动作完全不同。

    顺便钉住前置条件：本用例的源图**确实存在**，否则它退化成 missing_source 的
    又一个副本，测不出任何东西。
    """
    good = _png("degen_good.png", 32, 32)
    tiny = _png("degen_tiny.png", 32, 32)
    assert os.path.exists(tiny), "前置条件失败：源图必须存在，否则测不到本分支"

    project = ProjectData(fps=12, width=32, height=32)
    project.frames = [
        FrameData(file_path=good),
        # 32 * 0.001 = 0.032 → int() 截断为 0 → scaled_size_floor 退化
        FrameData(file_path=tiny, scale=0.001),
    ]

    errors = []
    list(Exporter.export_iter(project, _subdir("out_degenerate"), errors=errors))

    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].kind == "degenerate_size", \
        f"源图存在却报 {errors[0].kind} —— 说明尺寸退化被误判成源图缺失"
    assert errors[0].frame_index == 1, \
        f"帧号应为工程内下标 1，实际 {errors[0].frame_index}"
    assert errors[0].detail == tiny, \
        "detail 应是源图路径，用户要照它去改这一帧的缩放参数"


# ---------------------------------------------------------------------------
# 用例：整批失败必须抛，不能静默
# ---------------------------------------------------------------------------

def test_gif_raises_when_no_frame_rendered():
    """GIF 一帧都没渲染出来时必须抛 `ExportFailedError`。

    这是整批失败，不是部分成功：GIF 是单文件产物，静默不生成文件（或生成一个空
    文件）会让用户看到"导出完成"而磁盘上什么都没有。此前的实现只 `print` 一行。
    """
    missing = os.path.join(_tmpdir(), "all_DOES_NOT_EXIST.png")
    project = _project([missing, missing])
    gif_path = os.path.join(_subdir("out_gif_all"), "out.gif")

    errors = []
    raised = None
    try:
        Exporter.export_gif(project, gif_path, errors=errors)
    except ExportFailedError as e:
        raised = e

    assert raised is not None, \
        "全部帧失败时必须抛 ExportFailedError —— 静默返回会让调用方接着弹'导出完成'"
    assert len(errors) == 2, f"应记 2 条错误，实际 {len(errors)}"
    assert not os.path.exists(gif_path), "整批失败时不该产出文件"


def test_gif_succeeds_when_at_least_one_frame_renders():
    """只要有一帧成功，GIF 就不抛 —— 部分成功不该被当成失败。

    与上一条配成一对：单测"全失败要抛"很容易写成"有错误就抛"，那样这条会红。
    """
    good = _png("gif_partial_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "gif_partial_DOES_NOT_EXIST.png")
    project = _project([good, missing])
    gif_path = os.path.join(_subdir("out_gif_partial"), "out.gif")

    errors = []
    Exporter.export_gif(project, gif_path, errors=errors)   # 不该抛

    assert os.path.exists(gif_path), "有一帧成功就该产出 GIF"
    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}"


# ---------------------------------------------------------------------------
# 用例：单帧抛异常（另一条失败路径）
# ---------------------------------------------------------------------------

def test_exception_is_recorded_and_does_not_abort_batch():
    """单帧合成抛异常：记进 errors，且**不中断**整批。

    单帧合成抛异常走的是 `except Exception`。它比"忽略返回值"罕见，但同样静默。
    """
    good = _png("exc_good.png", 32, 32)
    broken = _png("exc_broken.png", 32, 32)
    project = _project([good, broken])

    # 让第 2 帧的合成抛异常：直接打在源图读取上，最贴近"素材文件损坏"这个现实场景
    orig_exists = os.path.exists
    calls = []

    def flaky(path):
        calls.append(path)
        if path == broken:
            raise OSError("simulated corrupt image")
        return orig_exists(path)

    os.path.exists = flaky
    try:
        out = _subdir("out_exception")
        errors = []
        list(Exporter.export_iter(project, out, errors=errors))
    finally:
        os.path.exists = orig_exists

    assert broken in calls, "前置条件失败：破坏点没生效，本用例会假通过"
    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].kind == "exception", \
        f"错误种类应为 exception，实际 {errors[0].kind}"
    assert errors[0].frame_index == 1, \
        f"帧号应为工程内下标 1，实际 {errors[0].frame_index}"

    names = sorted(n for n in os.listdir(out) if n.endswith(".png"))
    assert names == ["exc_good.png"], \
        f"单帧异常不该中断整批，其余帧要照常导出，实际产出 {names}"


# ---------------------------------------------------------------------------
# 用例：向后兼容（不传 errors 时行为不变）
# ---------------------------------------------------------------------------

def test_errors_omitted_behaves_as_before():
    """不传 `errors` 时不得抛异常、不得改变产出（向后兼容的底线）。

    `transform_baseline.py` 与 `verify_image_cache.py` 都还在不传参地调用三个导出
    方法；若加了这个参数反而要求必须传，那两处会直接炸。
    """
    good = _png("compat_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "compat_DOES_NOT_EXIST.png")
    project = _project([good, missing])

    out = _subdir("out_compat_seq")
    list(Exporter.export_iter(project, out))        # 不该抛

    sheet_path = os.path.join(_subdir("out_compat_sheet"), "s.png")
    Exporter.export_sprite_sheet(project, sheet_path)   # 不该抛
    assert os.path.exists(sheet_path)

    # GIF 全部帧失败、且没传 errors：仍要抛（整批失败与是否收集错误无关）
    project_all_missing = _project([missing])
    gif_path = os.path.join(_subdir("out_compat_gif"), "o.gif")
    try:
        Exporter.export_gif(project_all_missing, gif_path)
    except ExportFailedError:
        pass
    else:
        raise AssertionError("整批失败时抛异常，与是否传 errors 无关")


def test_errors_is_output_only_not_input():
    """`errors` 是出参：传入的既有内容不被消费，只被追加。

    调用方可能复用一个 list（或先塞了别的东西），把它当入参读取会导致丢错误。
    """
    good = _png("append_good.png", 32, 32)
    missing = os.path.join(_tmpdir(), "append_DOES_NOT_EXIST.png")
    project = _project([good, missing])

    errors = ["sentinel"]
    list(Exporter.export_iter(project, _subdir("out_append"), errors=errors))

    assert errors[0] == "sentinel", \
        "errors 是出参，不该动调用方已有的内容"
    assert len(errors) == 2, f"应追加 1 条，实际共 {len(errors)} 项: {errors}"


# ---------------------------------------------------------------------------
# 用例：帧号语义（用户要能按它找到帧）
# ---------------------------------------------------------------------------

def test_frame_index_is_project_index_not_batch_index():
    """`frame_index` 是工程内下标，不是导出批次内的序号。

    导出可以只导选中范围（如只导第 5、9 帧），批次序号 0、1 对不上时间轴 ——
    报"第 2 帧失败"用户会去时间轴第 2 帧找，那是错的帧。
    """
    paths = [_png(f"idx_{i}.png", 32, 32) for i in range(5)]
    missing = os.path.join(_tmpdir(), "idx_DOES_NOT_EXIST.png")
    paths[3] = missing          # 工程内第 4 帧（下标 3）缺源图
    project = _project(paths)

    errors = []
    # 只导出下标 3 与 4 —— 批次内它们是第 1、2 个
    list(Exporter.export_iter(project, _subdir("out_index"),
                              frame_indices=[3, 4], errors=errors))

    assert len(errors) == 1, f"应记 1 条错误，实际 {len(errors)}: {errors}"
    assert errors[0].frame_index == 3, \
        f"帧号应为工程内下标 3（时间轴第 4 帧），实际 {errors[0].frame_index}"


# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}")
            print(f"      {e}")
        except Exception as e:  # noqa: BLE001 - 用例里的任何异常都算失败
            failed += 1
            print(f"ERROR {name}")
            print(f"      {type(e).__name__}: {e}")
        else:
            print(f"PASS  {name}")

    print()
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
