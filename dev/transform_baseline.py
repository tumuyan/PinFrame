#!/usr/bin/env python3
"""变换重构的像素基线工具（开发用，非应用代码）。

用途：在重构 P0-1（把 9 处变换实现收敛到 core/transform.py）前后各跑一次，
比对输出哈希，确证「零行为差异」。

覆盖的渲染路径：
  - Exporter.export_iter        (PNG 序列)
  - Exporter.export_sprite_sheet(精灵表)
  - Exporter.export_gif         (GIF)
  - CanvasWidget 普通路径        (canvas.py draw_frame_normal)
  - CanvasWidget 栅格化路径      (canvas.py _render_to_buffer / draw_frame_buffer)
  - PropertyPanel 单选预览
  - PropertyPanel 多选预览

分两组输出：
  MAIN —— 重构前后必须【完全一致】
  EDGE —— aspect_ratio == 0，属已知既存缺陷，重构后【预期改变】（不再崩溃/空白）

用法：
    python dev/transform_baseline.py            # 跑一次并打印/落盘哈希
    python dev/transform_baseline.py --compare  # 与上次结果比对
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

# 必须在导入 QtWidgets 之前设置，保证无显示环境可用
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 忠实复现 `python main.py` 的导入环境：
#   sys.path[0] = 仓库根（解释器对脚本目录的处理），外加 src/
# 仓库根是必需的 —— canvas.py / property_panel.py 目前用的是
# `from src.core.image_cache import ...`（带 src. 前缀），只有仓库根在
# sys.path 中才能解析。基线必须复现现状，不能提前"修正"环境。
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, REPO_ROOT)

from PIL import Image  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from model.project_data import FrameData, ProjectData  # noqa: E402
from utils.exporter import Exporter  # noqa: E402

TMP = os.path.join(REPO_ROOT, "dev", "tmp_baseline")
ASSETS = os.path.join(TMP, "assets")
OUT = os.path.join(TMP, "out")
RESULT_JSON = os.path.join(TMP, "hashes.json")

PROJ_W, PROJ_H = 200, 150


# --------------------------------------------------------------------------
# 素材生成（确定性，无随机；四象限异色 + 角标，任何翻转/旋转都可检出）
# --------------------------------------------------------------------------
def _make_asymmetric(path, w, h):
    """生成左右上下均不对称的图，带 alpha 渐变。"""
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            left = x < w // 2
            top = y < h // 2
            if left and top:
                c = (220, 40, 40)
            elif top:
                c = (40, 160, 220)
            elif left:
                c = (240, 200, 60)
            else:
                c = (60, 200, 120)
            # alpha 沿 x 递增，进一步破坏左右对称
            a = 90 + int(165 * x / max(1, w - 1))
            px[x, y] = (c[0], c[1], c[2], a)
    # 左上角白色实心方块：旋转/镜像后位置立刻可辨
    for y in range(min(6, h)):
        for x in range(min(6, w)):
            px[x, y] = (255, 255, 255, 255)
    img.save(path)


def _make_sheet(path, cell_w, cell_h, cols, rows):
    """生成 cols×rows 的精灵表，每格颜色不同，供 crop_rect 切片测试。"""
    img = Image.new("RGBA", (cell_w * cols, cell_h * rows))
    px = img.load()
    palette = [
        (200, 60, 60), (60, 200, 60), (60, 60, 200),
        (200, 200, 60), (200, 60, 200), (60, 200, 200),
    ]
    for r in range(rows):
        for c in range(cols):
            base = palette[(r * cols + c) % len(palette)]
            for y in range(cell_h):
                for x in range(cell_w):
                    # 每格内再加对角渐变，避免纯色格掩盖旋转
                    k = int(80 * (x + y) / max(1, cell_w + cell_h - 2))
                    px[c * cell_w + x, r * cell_h + y] = (
                        min(255, base[0] + k), min(255, base[1] + k),
                        min(255, base[2] + k), 255)
    img.save(path)


def build_assets():
    os.makedirs(ASSETS, exist_ok=True)
    a = os.path.join(ASSETS, "asset_even.png")   # 偶数尺寸
    b = os.path.join(ASSETS, "asset_odd.png")    # 奇数尺寸：暴露 int() 截断
    s = os.path.join(ASSETS, "sheet.png")
    _make_asymmetric(a, 64, 40)
    _make_asymmetric(b, 63, 41)
    _make_sheet(s, 64, 32, 2, 2)
    return a, b, s


# --------------------------------------------------------------------------
# 测试工程
# --------------------------------------------------------------------------
def build_project(asset_even, asset_odd, sheet):
    """构造覆盖全部变换维度的工程。

    镜像帧按 property_panel._mirror_axis 的真实语义构造：
      H 镜像 -> scale 与 aspect_ratio 同时取负，rotation 取负
      V 镜像 -> 仅 aspect_ratio 取负，rotation 取负
    """
    p = ProjectData(fps=12, width=PROJ_W, height=PROJ_H,
                    background_color="#000000")
    p.export_sheet_cols = 3
    p.export_sheet_padding = 4
    p.frames = [
        # 基准
        FrameData(asset_even, scale=1.0, position=(0, 0), rotation=0.0),
        # 纯缩放
        FrameData(asset_even, scale=1.7, position=(0, 0), rotation=0.0),
        # 非 90° 倍数旋转（最容易暴露中心量化差异）
        FrameData(asset_even, scale=1.0, position=(0, 0), rotation=17.0),
        # 水平镜像
        FrameData(asset_even, scale=-1.3, position=(10, 5), rotation=-25.0,
                  aspect_ratio=-1.0),
        # 垂直镜像
        FrameData(asset_even, scale=1.0, position=(-8, 12), rotation=0.0,
                  aspect_ratio=-1.0),
        # 裁切 + 旋转 + 缩放 + 偏移
        FrameData(sheet, scale=0.85, position=(20, -15), rotation=33.0,
                  crop_rect=(0, 0, 64, 32)),
        # X/Y 失真（非镜像）
        FrameData(asset_even, scale=1.0, position=(0, 0), rotation=0.0,
                  aspect_ratio=1.6),
        # 偏移 + 负角旋转
        FrameData(asset_even, scale=1.15, position=(37, -23), rotation=-47.0),
        # 禁用帧（frame_indices=None 时应被跳过）
        FrameData(asset_even, scale=1.0, position=(0, 0), rotation=0.0,
                  is_disabled=True),
        # 第二个切片格 + 90° 旋转
        FrameData(sheet, scale=1.0, position=(0, 0), rotation=90.0,
                  crop_rect=(64, 32, 64, 32)),
        # 奇数尺寸源图 + 旋转 + 非整数缩放：暴露 int() 截断
        FrameData(asset_odd, scale=1.33, position=(-11, 7), rotation=17.0),
    ]
    return p


def build_edge_project(asset_even):
    """aspect_ratio == 0：既存缺陷用例，重构后预期行为改变。"""
    p = ProjectData(fps=12, width=PROJ_W, height=PROJ_H)
    p.frames = [FrameData(asset_even, scale=1.0, position=(0, 0),
                          rotation=0.0, aspect_ratio=0.0)]
    return p


# --------------------------------------------------------------------------
# 哈希工具
# --------------------------------------------------------------------------
def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def hash_dir(d):
    """目录内所有文件的 {相对名: 哈希}。"""
    out = {}
    for name in sorted(os.listdir(d)):
        fp = os.path.join(d, name)
        if os.path.isfile(fp):
            out[name] = file_hash(fp)
    return out


# --------------------------------------------------------------------------
# 各渲染路径
# --------------------------------------------------------------------------
def run_exporters(project, tag, results):
    seq_dir = os.path.join(OUT, f"{tag}_seq")
    os.makedirs(seq_dir, exist_ok=True)
    try:
        for _ in Exporter.export_iter(project, seq_dir,
                                      use_original_filenames=False,
                                      bg_color=(0, 0, 0, 0)):
            pass
        for name, h in hash_dir(seq_dir).items():
            results[f"{tag}/export_iter/{name}"] = h
    except Exception as e:            # noqa: BLE001
        results[f"{tag}/export_iter"] = f"EXCEPTION:{type(e).__name__}"

    sheet_path = os.path.join(OUT, f"{tag}_sheet.png")
    try:
        Exporter.export_sprite_sheet(project, sheet_path,
                                     bg_color=(0, 0, 0, 0))
        results[f"{tag}/export_sprite_sheet"] = file_hash(sheet_path)
    except Exception as e:            # noqa: BLE001
        results[f"{tag}/export_sprite_sheet"] = f"EXCEPTION:{type(e).__name__}"

    gif_path = os.path.join(OUT, f"{tag}_anim.gif")
    try:
        Exporter.export_gif(project, gif_path, bg_color=(0, 0, 0, 0))
        results[f"{tag}/export_gif"] = file_hash(gif_path)
    except Exception as e:            # noqa: BLE001
        results[f"{tag}/export_gif"] = f"EXCEPTION:{type(e).__name__}"


def _render_widget(widget, w, h, path):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    widget.render(img)
    img.save(path)
    return file_hash(path)


def run_canvas(project, tag, results):
    from ui.canvas import CanvasWidget

    active = [f for f in project.frames if not f.is_disabled]

    # 普通路径
    try:
        c = CanvasWidget()
        c.resize(320, 240)
        c.set_project_settings(project.width, project.height)
        c.set_background_mode("black")
        c.set_selected_frames(active)
        results[f"{tag}/canvas_normal"] = _render_widget(
            c, 320, 240, os.path.join(OUT, f"{tag}_canvas_normal.png"))
    except Exception as e:            # noqa: BLE001
        results[f"{tag}/canvas_normal"] = f"EXCEPTION:{type(e).__name__}"

    # 栅格化路径（raster_enabled 且 view_scale > 1.0 才走 _render_to_buffer）
    try:
        c2 = CanvasWidget()
        c2.resize(320, 240)
        c2.set_project_settings(project.width, project.height)
        c2.set_background_mode("black")
        c2.set_selected_frames(active)
        c2.set_rasterization_settings(True, QColor(128, 128, 128), 5.0, True)
        c2.view_scale = 3.0
        results[f"{tag}/canvas_raster"] = _render_widget(
            c2, 320, 240, os.path.join(OUT, f"{tag}_canvas_raster.png"))
    except Exception as e:            # noqa: BLE001
        results[f"{tag}/canvas_raster"] = f"EXCEPTION:{type(e).__name__}"


def run_property_panel(project, tag, results):
    from ui.property_panel import PropertyPanel

    active = [f for f in project.frames if not f.is_disabled]

    def snap(frames, label):
        try:
            p = PropertyPanel()
            p.resize(320, 900)
            p.set_project_info(project.width, project.height)
            p.set_selection(frames)
            p.show()
            pm = p.preview_label.pixmap()
            if pm is None or pm.isNull():
                results[f"{tag}/{label}"] = "NO_PIXMAP"
                return
            out = os.path.join(OUT, f"{tag}_{label}.png")
            pm.save(out)
            results[f"{tag}/{label}"] = file_hash(out)
        except Exception as e:        # noqa: BLE001
            results[f"{tag}/{label}"] = f"EXCEPTION:{type(e).__name__}"

    if active:
        snap([active[0]], "panel_single")
        # 取多个含旋转/镜像/裁切的帧，确认叠加与重叠关系
        snap(active[:6], "panel_multi")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def collect():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    asset_even, asset_odd, sheet = build_assets()
    main_proj = build_project(asset_even, asset_odd, sheet)

    app = QApplication.instance() or QApplication(sys.argv)

    main_results = {}
    run_exporters(main_proj, "MAIN", main_results)
    run_canvas(main_proj, "MAIN", main_results)
    run_property_panel(main_proj, "MAIN", main_results)

    del app

    # EDGE 组必须隔离到子进程：aspect_ratio == 0 会让 paintEvent 抛
    # ZeroDivisionError，而 PyQt6 对虚函数内未捕获异常的处理是 abort 整个
    # 进程（实测退出码 127，无 traceback）。若在本进程内跑，基线会被带走。
    edge_results = {}
    for part in ("exporters", "canvas", "panel"):
        edge_results.update(_run_edge_in_subprocess(part))
    return main_results, edge_results


def _run_edge_in_subprocess(part):
    """在子进程中跑一个 EDGE 子检查；进程被 abort 时记为 ABORT。"""
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), f"--edge-part={part}"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[len("JSON:"):])
    return {f"EDGE/{part}": f"ABORT(returncode={proc.returncode})"}


def edge_worker(part):
    """子进程入口：只跑一个 EDGE 子检查并把结果以 JSON 行输出。"""
    os.makedirs(OUT, exist_ok=True)
    asset_even = os.path.join(ASSETS, "asset_even.png")
    proj = build_edge_project(asset_even)
    app = QApplication.instance() or QApplication(sys.argv)
    results = {}
    if part == "exporters":
        run_exporters(proj, "EDGE", results)
    elif part == "canvas":
        run_canvas(proj, "EDGE", results)
    elif part == "panel":
        run_property_panel(proj, "EDGE", results)
    del app
    print("JSON:" + json.dumps(results))
    return 0


def digest(d):
    """把一组哈希压成单个摘要，便于一眼比对。"""
    h = hashlib.sha256()
    for k in sorted(d):
        h.update(f"{k}={d[k]};".encode())
    return h.hexdigest()[:16]


def report(main_results, edge_results):
    print("=" * 72)
    print("MAIN 组（重构前后必须完全一致）")
    print("=" * 72)
    for k in sorted(main_results):
        print(f"  {main_results[k]}  {k}")
    print(f"\n  >>> MAIN_DIGEST = {digest(main_results)}\n")

    print("=" * 72)
    print("EDGE 组（aspect_ratio == 0，重构后预期改变）")
    print("=" * 72)
    for k in sorted(edge_results):
        print(f"  {edge_results[k]}  {k}")
    print(f"\n  >>> EDGE_DIGEST = {digest(edge_results)}")


def main():
    for arg in sys.argv[1:]:
        if arg.startswith("--edge-part="):
            return edge_worker(arg.split("=", 1)[1])

    compare = "--compare" in sys.argv
    prev = None
    if compare and os.path.exists(RESULT_JSON):
        with open(RESULT_JSON, encoding="utf-8") as f:
            prev = json.load(f)

    main_results, edge_results = collect()
    report(main_results, edge_results)

    payload = {"main": main_results, "edge": edge_results,
               "main_digest": digest(main_results),
               "edge_digest": digest(edge_results)}

    if compare and prev:
        print("\n" + "=" * 72)
        print("与上次结果比对")
        print("=" * 72)
        ok = prev.get("main_digest") == payload["main_digest"]
        print(f"  MAIN_DIGEST  上次 {prev.get('main_digest')}"
              f"  本次 {payload['main_digest']}"
              f"  -> {'一致 [OK]' if ok else '不一致 [FAIL]'}")
        if not ok:
            for k in sorted(set(prev.get("main", {})) | set(main_results)):
                a, b = prev.get("main", {}).get(k), main_results.get(k)
                if a != b:
                    print(f"    差异 {k}: {a} -> {b}")
        e_prev, e_now = prev.get("edge_digest"), payload["edge_digest"]
        print(f"  EDGE_DIGEST  上次 {e_prev}  本次 {e_now}"
              f"  -> {'未变' if e_prev == e_now else '已变（预期）'}")
        for k in sorted(set(prev.get("edge", {})) | set(edge_results)):
            a, b = prev.get("edge", {}).get(k), edge_results.get(k)
            if a != b:
                print(f"    EDGE 差异 {k}: {a} -> {b}")
        return 0 if ok else 1

    os.makedirs(TMP, exist_ok=True)
    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n已写入 {os.path.relpath(RESULT_JSON, REPO_ROOT)}")
    print("重构完成后运行：python dev/transform_baseline.py --compare")
    return 0


if __name__ == "__main__":
    sys.exit(main())
