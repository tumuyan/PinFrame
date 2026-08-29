#!/usr/bin/env python3
"""P2-7 三层缓存的回归验证：image_cache 的字节预算 + LRU，以及导出期源图缓存。

为什么单独一个文件
------------------
这四处改动（字节预算、LRU、删 `crop_rect` 死参数、导出期源图缓存）有一个共同点：
**改错了功能依然完全正常**，只有性能/内存会退化，而且退化得很隐蔽。

  - 上限退回"按张数"：500 张 4K 图照样能吃满 32 GB（这正是要修的东西）；
  - 淘汰退回 FIFO：只在"某张图加载得早却一直被反复访问"时才慢，肉眼几乎看不出；
  - `crop_rect` 参数加回来：没人传它，代码照样跑；
  - 导出期缓存去掉：导出结果**逐字节相同**，只是同一张精灵表被解码几百遍。

所以本脚本断言的是**预算、淘汰顺序、解码次数**这些"看不见的量"，而不是渲染结果。
像素正确性由 `transform_baseline.py` 覆盖（导出路径改了缓存，它的哈希必须不变）。

运行： ./venv/bin/python dev/verify_image_cache.py
退出码非 0 表示有失败。
"""
import atexit
import inspect
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

from core.image_cache import ImageCache, _image_bytes, image_cache  # noqa: E402
from model.project_data import FrameData, ProjectData  # noqa: E402
from utils.exporter import Exporter, SourceImageCache  # noqa: E402

app = QApplication(sys.argv)

_TMP = None


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _tmpdir():
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix="pinframe_cache_")
        atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
    return _TMP


def _png(name, w, h, color=(200, 40, 40, 255)):
    """生成一张纯色 PNG，返回绝对路径。"""
    path = os.path.join(_tmpdir(), name)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    assert img.save(path), f"夹具写入失败: {path}"
    return path


def _bytes_of(path):
    """这张图进缓存后占多少字节。"""
    return _image_bytes(QImage(path))


def _fresh(budget):
    """把全局缓存清空并设成给定预算 —— 用例之间必须隔离（它是单例）。"""
    image_cache.clear()
    image_cache.set_budget(budget)
    return image_cache


class _count_image_open:
    """统计 `PIL.Image.open` 的调用（导出期源图缓存是否生效的唯一可观测点）。"""

    def __enter__(self):
        self.calls = []
        self._orig = Image.open

        def counting(fp, *args, **kwargs):
            self.calls.append(fp)
            return self._orig(fp, *args, **kwargs)

        Image.open = counting
        return self

    def __exit__(self, *exc_info):
        Image.open = self._orig
        return False


def _is_closed(img):
    """PIL 里"已 close"的可观测后果：`load()` 抛 ValueError。"""
    try:
        img.load()
    except ValueError:
        return True
    return False


def _sprite_project(n=8):
    """一个典型的切片工程：n 帧**共用同一张**精灵表，裁切各不相同。

    这正是 P2-7 第 4 点要优化的场景，也是缓存最容易翻车的场景（多帧共享一张原图）。
    帧上带了旋转与镜像，`compose_frame` 会走 crop → resize → transpose → rotate 全
    流程 —— 只要其中任何一步是原地修改，共享就会互相污染。
    """
    sheet = _png("sheet.png", 64, 32)
    frames = []
    for i in range(n):
        frames.append(FrameData(
            file_path=sheet,
            crop_rect=(i * 8, 0, 8, 32),
            scale=1.0 + 0.15 * (i % 3),
            rotation=17.0 * (i % 2),
            aspect_ratio=-1.0 if i % 4 == 0 else 1.0,
        ))
    p = ProjectData(fps=12, width=64, height=32)
    p.frames = frames
    return p


# ---------------------------------------------------------------------------
# 用例：image_cache
# ---------------------------------------------------------------------------

def test_get_signature_has_no_crop_rect():
    """`get()` 不得再有 `crop_rect` 参数 —— 它诱导误用（P2-7 第 2 点）。

    cache key 从来只用 path，参数从头到尾没参与过计算。留着它的唯一后果是让下一个
    人以为"传了就会按裁切区缓存"。
    """
    params = list(inspect.signature(ImageCache.get).parameters)
    assert params == ["self", "file_path"], \
        f"get() 的签名应为 (self, file_path)，实际 {params}"

    src = inspect.getsource(ImageCache.get)
    assert "crop_rect" not in src, (
        "get() 的实现里又出现了 crop_rect —— 要么它真的参与了 key（那就要连 "
        "preload/remove 一起改），要么又是死参数")


def test_eviction_is_driven_by_bytes_not_count():
    """淘汰由**字节**决定，不是张数（P2-7 第 1 点）。

    场景：预算刚好装下"1 张大图 + 3 张小图"。再放第 4 张小图时，唯一合理的淘汰对象
    是那张大图（它占掉 99% 的预算）；而**任何**按张数的上限在这里都远没到（才 5 张），
    所以若实现退回"张数上限"，本用例会红。
    """
    big = _png("big.png", 64, 64)
    t = [_png(f"t{i}.png", 4, 4) for i in range(4)]
    big_b, tiny_b = _bytes_of(big), _bytes_of(t[0])
    assert big_b >= 16 * tiny_b, \
        f"夹具失效：大图/小图字节比只有 {big_b / tiny_b:.1f}x，测不出差异"

    cache = _fresh(big_b + 3 * tiny_b)
    cache.get(big)
    for p in t[:3]:
        cache.get(p)
    assert cache.size == 4, f"前置条件失败：4 张都该装得下，实际 {cache.size} 张"

    cache.get(t[3])
    assert not cache.contains(big), (
        "预算只多了 1 张小图的量，该被淘汰的是那张占掉绝大部分预算的大图，"
        f"它却还在 —— 淘汰不是按字节算的（当前 {cache.size} 张 / {cache.total_bytes} 字节）")
    assert all(cache.contains(p) for p in t), "小图被连带淘汰了，淘汰顺序不对"
    assert cache.total_bytes == 4 * tiny_b, \
        f"字节账不平：{cache.total_bytes} != {4 * tiny_b}"


def test_eviction_is_lru_not_fifo():
    """命中必须续命：被反复访问的图不得先于"加载后再没碰过"的图被踢掉。

    FIFO 与 LRU 唯一的区别就是命中时是否把条目挪到队尾。序列 A→B→A→C 下，
    FIFO 淘汰 A，LRU 淘汰 B。
    """
    paths = [_png(f"lru_{i}.png", 64, 64) for i in range(3)]
    a, b, c = paths
    cache = _fresh(2 * _bytes_of(a))

    cache.get(a)
    cache.get(b)
    assert cache.get(a) is not None       # 命中 a：a 变成最近使用
    cache.get(c)                          # 超预算 → 该淘汰 b

    assert cache.contains(a), \
        "刚刚命中的图被淘汰了 —— 淘汰是 FIFO 而非 LRU（反复访问的图反而最先丢）"
    assert not cache.contains(b), "最久未使用的图没被淘汰"
    assert cache.contains(c), "新加载的图不在缓存里"


def test_oversized_image_is_kept_and_reused():
    """单张超过预算的图必须留在缓存里，不能"放进即踢"。

    否则大图每次访问都重新解码 —— 比不缓存更慢（还多了一次淘汰遍历）。
    这是"淘汰时绝不淘汰本次正要放进去的那张"这条规则的目的。
    """
    tiny = _png("tiny.png", 4, 4)
    huge = _png("huge.png", 128, 128)
    cache = _fresh(_bytes_of(tiny))       # 预算只有一张 4x4 的量

    first = cache.get(huge)
    assert first is not None, "前置条件失败：图没加载上"
    assert cache.contains(huge), \
        "单张超预算的图被立刻淘汰了 —— 会退化成每次访问都重新解码"
    assert cache.total_bytes == _bytes_of(huge), "超预算时字节账也要记准"

    # 超预算是允许的（有意为之），但二次访问必须是命中而非重新解码
    assert cache.get(huge) is first, "二次访问没命中缓存，大图被反复解码"


def test_bytes_accounting_on_remove_and_clear():
    """字节账必须在 remove / clear 之后仍然对得上。

    `remove()` 是外部编辑器改图后的失效入口（`_reload_edited_images`），账目漂移会让
    预算在若干次编辑之后彻底失真 —— 不报错，只是缓存慢慢失效或慢慢撑爆。
    """
    a, b = _png("acc_a.png", 32, 32), _png("acc_b.png", 16, 16)
    cache = _fresh(64 * 1024 * 1024)

    cache.get(a)
    cache.get(b)
    assert cache.total_bytes == _bytes_of(a) + _bytes_of(b), "入账不对"

    cache.remove(a)
    assert cache.size == 1, "remove 之后张数不对"
    assert cache.total_bytes == _bytes_of(b), "remove 未销账"

    cache.remove(a)                       # 重复 remove 不得把账算成负数
    assert cache.total_bytes == _bytes_of(b), \
        f"重复 remove 把字节账弄坏了: {cache.total_bytes}"

    cache.clear()
    assert cache.size == 0 and cache.total_bytes == 0, "clear 未清零"


# ---------------------------------------------------------------------------
# 用例：导出期源图缓存
# ---------------------------------------------------------------------------

def test_export_decodes_each_source_once():
    """一次导出里，每张源图只解码一次（P2-7 第 4 点：投入产出比最高的那条）。

    三种导出模式共用 `compose_frame`，缓存也共用同一套注入方式，故三个都验。
    """
    project = _sprite_project()
    frames = project.frames
    out = os.path.join(_tmpdir(), "out_seq")

    # 前置自校验：**不开**缓存时确实是每帧解码一次。计数器若失灵，
    # 后面的"只解码 1 次"就会变成恒真的假通过。
    with _count_image_open() as counter:
        for f in frames:
            Exporter.compose_frame(Image.new("RGBA", (project.width, project.height)),
                                   f, project.width, project.height)
    assert len(counter.calls) == len(frames), \
        f"前置条件失败：无缓存时应解码 {len(frames)} 次，实际 {len(counter.calls)}"

    with _count_image_open() as counter:
        for _ in Exporter.export_iter(project, out):
            pass
    assert len(counter.calls) == 1, \
        f"PNG 序列：{len(frames)} 帧共用一张源图，却解码了 {len(counter.calls)} 次"
    assert len([n for n in os.listdir(out) if n.endswith(".png")]) == len(frames), \
        "PNG 序列导出数量不对 —— 缓存改动不应影响产出"

    sheet_path = os.path.join(_tmpdir(), "sheet.png")
    with _count_image_open() as counter:
        Exporter.export_sprite_sheet(project, sheet_path)
    assert len(counter.calls) == 1, \
        f"精灵表：源图被解码了 {len(counter.calls)} 次"

    gif_path = os.path.join(_tmpdir(), "out.gif")
    with _count_image_open() as counter:
        Exporter.export_gif(project, gif_path)
    assert len(counter.calls) == 1, \
        f"GIF：源图被解码了 {len(counter.calls)} 次"


def test_shared_source_image_is_not_mutated():
    """多帧共享一张原图不得互相污染。

    缓存成立的唯一前提是：PIL 的 crop / resize / transpose / rotate 一律**返回新对象**。
    一旦哪天有人改成原地操作（或换成某个原地 API），导出结果会静默错帧 —— 而
    `transform_baseline.py` 的夹具里每帧源图各不相同，**抓不到**这种交叉污染，
    所以这条必须单独钉住。
    """
    project = _sprite_project(6)
    frames = project.frames
    w, h = project.width, project.height

    def render(frame, cache=None):
        canvas = Image.new("RGBA", (w, h))
        Exporter.compose_frame(canvas, frame, w, h, cache)
        return canvas.tobytes()

    baseline = [render(f) for f in frames]        # 不走缓存（改动前的行为）

    with SourceImageCache() as cache:
        cached = [render(f, cache) for f in frames]
        again = [render(f, cache) for f in frames]  # 第二轮：全部命中缓存

    assert cached == baseline, "走缓存后的合成结果与不走缓存不同 —— 共享的原图被改了"
    assert again == cached, "第二轮（全部命中缓存）结果与第一轮不同"


def test_cached_images_survive_source_close():
    """缓存返回的图必须独立于打开时的中间对象，拿到手就是可用的。

    `SourceImageCache.get()` 用 `with Image.open(path) as decoded:` 显式关掉中间那个
    解码对象。转换结果是新对象、不受影响，但这是个**容易踩反**的点：若哪天改成让
    `get()` 返回那个即将被关闭的中间对象（例如省掉 `convert()`），缓存里的图会在
    `with` 退出的同一刻失效，而首帧仍能正常导出 —— 错误要等到第 2 帧才开始出现。

    所以这里刻意**不**用 PNG：GIF 是多帧格式，Pillow 对它的 fp 处理与 PNG 不同，
    是这条性质更容易翻车的地方。
    """
    gif_path = os.path.join(_tmpdir(), "multi.gif")
    Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(gif_path)

    with SourceImageCache() as cache:
        img = cache.get(gif_path)
        assert img.mode == "RGBA", f"前置条件失败：期望 RGBA，实际 {img.mode}"
        # 关键：取到手就能用，不依赖 with 尚未退出
        assert img.tobytes()[:4] == bytes((10, 20, 30, 255)), \
            "缓存返回的图像内容不对 —— 中间对象被关闭后数据跟着没了"
        # 对照必须在 close 之前做：之后 img 已关闭，比对会抛异常而非给出结论
        with Image.open(gif_path) as decoded:
            assert decoded.convert("RGBA").tobytes() == img.tobytes(), \
                "走缓存与不走缓存得到的像素不同"

    # with 已退出，此刻才该是"已关闭"状态
    assert _is_closed(img), "with 退出后缓存里的图未被 close（见 close() 的防御性说明）"


def test_source_cache_is_bounded_and_closed():
    """导出期缓存必须有字节上限，且导出结束要 close 掉全部文件句柄。

    上限是防 OOM 的：缓存让峰值内存从"1 张源图"变成"N 张"，几百帧各用各的大图时会
    比不缓存更容易撑爆内存。
    """
    a, b = _png("sc_a.png", 64, 64), _png("sc_b.png", 64, 64)
    one = 64 * 64 * 4

    cache = SourceImageCache(max_bytes=one)
    img_a, img_b = cache.get(a), cache.get(b)
    assert len(cache) == 1, f"预算只够一张，实际缓存了 {len(cache)} 张"
    assert cache.total_bytes == one, f"字节账不对: {cache.total_bytes}"
    assert _is_closed(img_a), "被淘汰的那张没有 close，文件句柄会一直挂着"
    assert not _is_closed(img_b), "留在缓存里的图不该被 close"

    # with 退出 = 一次导出结束：全部 close 且清空
    with SourceImageCache() as c2:
        kept = [c2.get(a), c2.get(b)]
        assert not any(_is_closed(i) for i in kept), "前置条件失败：缓存中的图不该是关着的"
    assert len(c2) == 0 and c2.total_bytes == 0, "with 退出后缓存未清空"
    assert all(_is_closed(i) for i in kept), "with 退出后未 close 缓存里的图"


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
