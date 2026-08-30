import os
from dataclasses import dataclass
from typing import List, Optional, Tuple
from PIL import Image
from core.transform import (base_size, composite_origin,
                            resolve_frame_geometry, scaled_size_floor)
from model.project_data import ProjectData
from utils.debug_config import export_debug

# 导出期源图缓存的默认字节预算：256 MiB。
#
# 为什么必须设上限：缓存的收益来自"几十上百帧共用一张精灵表"，而风险来自"几百帧各
# 用各的大图" —— 后者若无限缓存，峰值内存从 1 张变成 N 张，比不缓存更容易 OOM。
# 有上限之后，最坏情况退化为"缓存没命中"，不会比改之前更差。
DEFAULT_SOURCE_CACHE_BYTES = 256 * 1024 * 1024


# 单帧合成失败的原因（ExportError.kind 的取值）。
#
# 分两类而不是笼统记一个"失败"：源文件缺失是**用户能自己修**的（找回文件、改素材
# 路径），而尺寸退化为 0 是**帧参数**问题（缩放得太小），两者的处置完全不同。
MISSING_SOURCE = "missing_source"
DEGENERATE_SIZE = "degenerate_size"
# 合成过程中抛出的异常也进同一份清单，kind 固定为它
EXCEPTION = "exception"


class SourceImageCache:
    """导出期生命周期的源图缓存：`{path: PIL.Image}`。

    `compose_frame` 原本对每一帧都 `Image.open(path).convert("RGBA")` —— 精灵表工程
    里几百帧共用同一张源图，于是同一文件被完整解码几百遍（P2-7 第 4 点）。这里按
    路径缓存**解码后、未裁切**的原图。

    缓存未裁切的原图是安全的：`compose_frame` 随后对它做的 crop / resize /
    transpose / rotate **一律返回新对象**，PIL 从不在原地修改图像，所以多帧共享
    同一张原图不会互相污染。

    缓存按 LRU 淘汰（`dict` 保序：命中就重新插到末尾），上限是字节预算而非张数 ——
    与 `core.image_cache` 同一套理由，一份大图与一张小图标不能等量齐观。
    """

    def __init__(self, max_bytes: int = DEFAULT_SOURCE_CACHE_BYTES):
        self._images = {}
        self._bytes = 0
        self._max_bytes = max(0, int(max_bytes))

    def get(self, path: str) -> Image.Image:
        """取解码后的 RGBA 原图；未缓存则打开、转换并纳入缓存。"""
        img = self._images.pop(path, None)
        if img is not None:
            # 命中：重新插到末尾，维持 LRU 顺序
            self._images[path] = img
            return img

        # 用 `with` 显式关掉中间那个解码对象，而不是依赖 `convert()` 的副作用：
        # `convert()` 触发的 `load()` 确实会在读完后自行关文件（实测 PNG：fp 变
        # None，循环 200 次 fd 增量为 0），但那是 Pillow 对具体格式的实现细节 ——
        # 多帧格式（GIF / TIFF）未必如此。转换结果是全新对象，不受这里关闭的影响。
        with Image.open(path) as decoded:
            img = decoded.convert("RGBA")

        size = self._image_bytes(img)
        self._evict_to_fit(size)
        self._images[path] = img
        self._bytes += size
        return img

    def close(self) -> None:
        """释放全部缓存图像的文件句柄。

        防御性的，不是修一个已存在的泄漏：`convert()` 的结果通常已不持有 fp（实测
        PNG 如此）。但对多帧格式（GIF / TIFF）Pillow 可能仍保持着 fp，故导出结束时
        统一关一遍。
        """
        for img in self._images.values():
            try:
                img.close()
            except Exception:      # noqa: BLE001 - close 失败不该中断导出
                pass
        self._images.clear()
        self._bytes = 0

    def __enter__(self) -> "SourceImageCache":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    def __len__(self) -> int:
        return len(self._images)

    @property
    def total_bytes(self) -> int:
        return self._bytes

    @staticmethod
    def _image_bytes(img: Image.Image) -> int:
        # get() 里统一 convert("RGBA")，故恒为 4 通道、每通道 1 字节
        return img.width * img.height * 4

    def _evict_to_fit(self, incoming_bytes: int) -> None:
        while self._images and self._bytes + incoming_bytes > self._max_bytes:
            path, victim = next(iter(self._images.items()))
            del self._images[path]
            self._bytes -= self._image_bytes(victim)
            victim.close()


@dataclass(frozen=True)
class ExportError:
    """一次单帧导出失败的记录。

    导出里最容易被忽略的失败**不是异常**，而是 `compose_frame` 返回 `False`
    （`missing_source` / `degenerate_size`）—— 它**不抛异常**。三个导出方法此前都
    不看这个返回值：PNG 序列照样 `canvas.save()` 写出一张全透明的空图、精灵表留
    一个空白格、GIF 补一个空白帧。用户的观感是"导出成功"，只是少了几张素材 ——
    而"工程被移动 / 素材被删 / 工程从别人机器上拷来"恰恰是最常见的现实场景。

    `frame_index` 是**工程内帧号**（用户能对着时间轴找到它），不是导出批次内的
    序号 —— 导出可以只导选中范围，批次序号对不上时间轴。展示时按 1 基显示
    （时间轴的序号是 1 基）。

    `frozen` 不是洁癖：`errors` 会被**跨层**传回 `MainWindow` 再逐条展示，可变的
    记录对象让"谁改了它"无从追查。代价是要改一条记录得整体替换。
    """

    kind: str          # MISSING_SOURCE | DEGENERATE_SIZE | EXCEPTION
    frame_index: int
    detail: str = ""


class ExportFailedError(Exception):
    """整批导出彻底失败（一帧都没成功）。

    单帧失败**不**抛，而是记进 `errors` 让其余帧继续导出 —— "缺 3 帧但其余 97
    帧导出来了"是有价值的，不该整体失败。但"一帧都没导出"就不是部分成功了，
    此时必须抛出，否则用户拿到一个空的/不存在的文件却看到"导出完成"。

    `str(e)` 是**给开发者的诊断文本，不是给用户看的文案**。它最终会原样显示在
    状态栏上（调用方是 `except Exception as e: showMessage(f"...: {e}")`），所以
    UI 层要单独 `except ExportFailedError` 挑出来、改说本地化的一句话；用户可见
    的逐条清单则由 `errors` 出参承载，走 i18n。
    """

    def __init__(self, errors: List[ExportError]):
        super().__init__(f"export failed: {len(errors)} error(s)")
        self.errors = errors


def _record_error(errors: Optional[List[ExportError]], kind: str,
                  frame_index: int, detail: str = "") -> None:
    """把一条失败记进调用方给的清单；`errors` 为 None 时什么都不做。

    None 表示调用方不关心错误（保持加这个功能之前的静默行为），故三个导出方法的
    既有调用点无需改动。

    记错点**一律**走本函数，不要在调用处写
    `if errors is not None: errors.append(...)`：漏掉那个 `if` 会在 `errors=None`
    时 AttributeError，而 None 恰恰是既有调用方（`transform_baseline.py` /
    `verify_image_cache.py`）的常态 —— 只测"传了 errors"的路径是测不出这个错的。

    位置必须在 `ExportError` **之后**：注解 `List[ExportError]` 在函数定义时就
    要求值，放前面会 NameError（挪动顺序时踩过）。
    """
    if errors is not None:
        errors.append(ExportError(kind=kind, frame_index=frame_index,
                                  detail=detail))


def _compose_into_canvas(canvas: Image.Image, frame, canvas_w: int, canvas_h: int,
                         source_cache, frame_index: int,
                         errors: Optional[List[ExportError]]) -> bool:
    """调 `compose_frame` 并把失败记进 `errors`；返回是否成功。

    失败种类靠复现 `compose_frame` 自己的两个判据来区分 —— 它只回一个 bool，
    而"源文件没了"与"缩放后尺寸退化成 0"对用户的含义完全不同。判断顺序必须与
    `compose_frame` 内部一致（先查文件存在、再查尺寸退化），**且只在失败路径上
    执行**，故不引入额外的常态开销。

    `errors` 为 None 时只返回结果、什么都不记 —— 这保留了加本参数之前的行为，
    现有调用方（`dev/transform_baseline.py`、`dev/verify_image_cache.py`）因此零改动。
    """
    if Exporter.compose_frame(canvas, frame, canvas_w, canvas_h, source_cache):
        return True

    if not os.path.exists(frame.file_path):
        kind = MISSING_SOURCE
    else:
        kind = DEGENERATE_SIZE

    _record_error(errors, kind, frame_index, frame.file_path)
    return False


class Exporter:
    @staticmethod
    def compose_frame(canvas: Image.Image, frame, canvas_w: int, canvas_h: int,
                      source_cache: Optional[SourceImageCache] = None) -> bool:
        """把一帧按其变换合成到 canvas 上（导出路径的唯一变换实现）。

        几何语义来自 core.transform（与 canvas 预览共用同一来源）；此处只负责
        PIL 侧的像素化：`scaled_size_floor` 的整数尺寸、transpose 翻转、
        rotate(expand=True) 旋转，最后按 `composite_origin` 给出的整数左上角
        alpha_composite。这些量化行为是刻意保持的现状，详见 core.transform 的
        模块说明与 dev/export_pipeline_precision.md。

        `source_cache` 是导出期共享的源图缓存（`SourceImageCache`），多帧共用一张
        源图时能省掉重复的解码；不传则每次自己打开（行为与加缓存前一致）。

        返回 True 表示已合成；源文件缺失或缩放后尺寸退化为 0 时返回 False。
        """
        if not os.path.exists(frame.file_path):
            return False

        geo = resolve_frame_geometry(frame)
        if source_cache is not None:
            src_img = source_cache.get(frame.file_path)
        else:
            src_img = Image.open(frame.file_path).convert("RGBA")

        if geo.crop_rect:
            x, y, w, h = geo.crop_rect
            src_img = src_img.crop((x, y, x + w, y + h))

        base_w, base_h = base_size(geo, src_img.width, src_img.height)
        new_w, new_h = scaled_size_floor(geo, base_w, base_h)
        if new_w <= 0 or new_h <= 0:
            return False

        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 镜像：几何解析把 scale/aspect_ratio 的负号拆成了 flip 标志
        if geo.flip_h:
            src_img = src_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if geo.flip_v:
            src_img = src_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        # PIL 的 rotate 正向为逆时针，与 QPainter.rotate 相反，故取负
        if geo.rotation != 0:
            src_img = src_img.rotate(-geo.rotation,
                                     resample=Image.Resampling.BICUBIC,
                                     expand=True)

        dest = composite_origin(geo, canvas_w, canvas_h,
                                src_img.width, src_img.height)
        canvas.alpha_composite(src_img, dest)
        return True

    @staticmethod
    def parse_range_string(range_str: str, total_count: int) -> List[int]:
        """
        Parses a range string like '1,3,5-7,10-' into a list of 0-based indices.
        """
        if not range_str or not range_str.strip():
            return []
            
        indices = set()
        parts = range_str.replace('，', ',').split(',')
        
        for part in parts:
            part = part.strip()
            if not part: continue
            
            if '-' in part:
                sub_parts = part.split('-')
                try:
                    start = int(sub_parts[0]) - 1
                    if sub_parts[1].strip():
                        end = int(sub_parts[1]) - 1
                        # Clamp
                        start = max(0, min(start, total_count - 1))
                        end = max(0, min(end, total_count - 1))
                        for i in range(min(start, end), max(start, end) + 1):
                            indices.add(i)
                    else:
                        # Open range like '10-'
                        start = max(0, min(start, total_count - 1))
                        for i in range(start, total_count):
                            indices.add(i)
                except ValueError:
                    continue
            else:
                try:
                    idx = int(part) - 1
                    if 0 <= idx < total_count:
                        indices.add(idx)
                except ValueError:
                    continue
                    
        return sorted(list(indices))

    @staticmethod
    def export_iter(project: ProjectData, output_dir: str, use_original_filenames: bool = True,
                    frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
                    errors: Optional[List[ExportError]] = None):
        """逐帧导出 PNG 序列，yield (当前序号, 总数) 供进度条使用。

        `errors` 是**出参**：单帧失败不抛异常，而是往里追加一条 `ExportError`，
        其余帧继续导出。不传则与加本参数之前完全一致（失败只是不产出该文件）。
        调用方在生成器消费完之后读它 —— 生成器是惰性的，未消费完就读取会漏。
        """
        export_debug(f"[Export] Starting export_iter: output_dir={output_dir}, use_original_filenames={use_original_filenames}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        used_filenames = set()
        # Counter for virtual-sliced frames sharing the same source image path.
        # Each source image gets its own 0-based index so exported frames become
        # "originalname_0.png", "originalname_1.png", ... and never overwrite the
        # original sprite sheet itself.
        slice_counters = {}
        
        # project.frames 是属性（每次读取都会向 TimelineModel 取一份实时快照），
        # 故取一次存到局部变量，避免在推导式里反复取用
        all_frames = project.frames
        # If no indices provided, export all active frames
        if frame_indices is None:
            # We must map indices from the original project.frames
            frames_to_export = [(i, f) for i, f in enumerate(all_frames) if not f.is_disabled]
        else:
            frames_to_export = [(i, all_frames[i]) for i in frame_indices if i < len(all_frames)]
            
        total_frames = len(frames_to_export)
        if total_frames == 0:
            export_debug("[Export] No frames to export")
            return
        
        export_debug(f"[Export] Exporting {total_frames} frames")
            
        # 源图缓存的生命周期就是这一次导出：退出 with 时 close 掉全部文件句柄
        with SourceImageCache() as source_cache:
            for progress_idx, (orig_idx, frame) in enumerate(frames_to_export):
                yield progress_idx + 1, total_frames # Progress bar info
            
                # Create a blank canvas with BG color
                canvas = Image.new('RGBA', (project.width, project.height), bg_color)
            
                try:
                    # 合成失败（源图缺失 / 尺寸退化）时**不**写文件 —— 否则用户会
                    # 拿到一张全透明的空 PNG，还以为只是素材本来就是空的。
                    if not _compose_into_canvas(canvas, frame, project.width,
                                                project.height, source_cache,
                                                orig_idx, errors):
                        continue

                    # Save
                    if use_original_filenames:
                        base_name = os.path.basename(frame.file_path)
                        name, ext = os.path.splitext(base_name)

                        if frame.crop_rect:
                            # Virtual-sliced frame: use "originalname_<index>" so the
                            # original sprite sheet is never overwritten when exporting
                            # into the same directory.
                            idx = slice_counters.get(frame.file_path, 0)
                            slice_counters[frame.file_path] = idx + 1
                            filename = f"{name}_{idx}{ext}"
                        else:
                            filename = base_name
                            dup_count = 1
                            while filename in used_filenames:
                                filename = f"{name}_{dup_count}{ext}"
                                dup_count += 1

                        used_filenames.add(filename)
                    else:
                        filename = f"frame_{progress_idx:04d}.png"

                    canvas.save(os.path.join(output_dir, filename))

                except Exception as e:
                    # 不静默：进 errors 供调用方汇总提示（errors 为 None 时至少
                    # 走 debug 框架，比裸 print 强 —— 它可被 export 分类开关关掉）
                    export_debug(f"[Export] Frame {orig_idx} failed: {e}")
                    _record_error(errors, EXCEPTION, orig_idx, str(e))

        export_debug(f"[Export] Export_iter completed: {total_frames} frames exported")
                
    @staticmethod
    def export_sprite_sheet(project: ProjectData, output_path: str,
                            frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
                            errors: Optional[List[ExportError]] = None):
        """导出精灵表。

        `errors` 是出参，语义同 `export_iter`：单帧失败不中断整批，该格留空并记一条。
        """
        export_debug(f"[Export] Starting sprite sheet export: output_path={output_path}")

        all_frames = project.frames      # 属性读取会取实时快照，只取一次
        if frame_indices is None:
            # 带上工程内帧号：导出可能只覆盖选中范围，批次序号对不上时间轴，
            # 报错时用户没法按批次序号找到是哪一帧。
            frames_to_export = [(i, f) for i, f in enumerate(all_frames)
                                if not f.is_disabled]
        else:
            frames_to_export = [(i, all_frames[i]) for i in frame_indices
                                if i < len(all_frames)]

        if not frames_to_export:
            return
            
        cols = project.export_sheet_cols
        padding = project.export_sheet_padding
        rows = (len(frames_to_export) + cols - 1) // cols
        
        fw, fh = project.width, project.height
        total_w = cols * fw + (cols + 1) * padding
        total_h = rows * fh + (rows + 1) * padding
        
        # The main sheet can also have transparency or a default. 
        # Usually sprite sheets are saved with transparent BG unless specified.
        # However, the individual cells should respect bg_color.
        sheet = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
        
        with SourceImageCache() as source_cache:
            for i, (orig_idx, frame) in enumerate(frames_to_export):
                # Render individual frame to a temporary canvas with bg_color
                canvas = Image.new('RGBA', (fw, fh), bg_color)
            
                try:
                    # 合成失败则该格留空（不 composite），但格子仍然占位 ——
                    # 精灵表是按 col/row 定位的，跳过一帧会让后面所有帧整体错位。
                    if _compose_into_canvas(canvas, frame, fw, fh, source_cache,
                                            orig_idx, errors):
                        row_idx = i // cols
                        col_idx = i % cols

                        sheet_x = col_idx * fw + (col_idx + 1) * padding
                        sheet_y = row_idx * fh + (row_idx + 1) * padding

                        sheet.alpha_composite(canvas, (sheet_x, sheet_y))

                except Exception as e:
                    export_debug(f"[Export] Sheet frame {orig_idx} failed: {e}")
                    _record_error(errors, EXCEPTION, orig_idx, str(e))
                
        sheet.save(output_path)
        export_debug(f"[Export] Sprite sheet saved: {output_path}, {len(frames_to_export)} frames, {cols}x{rows} grid")

    @staticmethod
    def export_gif(project: ProjectData, output_path: str,
                   frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
                   errors: Optional[List[ExportError]] = None):
        """导出 GIF。

        `errors` 是出参，语义同 `export_iter`。唯一的不同是**整批失败会抛**
        `ExportFailedError`：GIF 是单文件产物，一帧都没渲染出来时不存在"部分成功"，
        静默生成一个空文件或干脆不生成都会让用户以为成功了。
        """

        export_debug(f"[Export] Starting GIF export: output_path={output_path}")

        all_frames = project.frames      # 属性读取会取实时快照，只取一次
        if frame_indices is None:
            frames_to_export = [(i, f) for i, f in enumerate(all_frames)
                                if not f.is_disabled]
        else:
            frames_to_export = [(i, all_frames[i]) for i in frame_indices
                                if i < len(all_frames)]

        if not frames_to_export:
            # 刻意静默返回，不抛 ExportFailedError：这里不是"一帧都没渲染出来"，
            # 而是"压根没有帧可导"。两者后果不同 —— 后者没有产物是**正确的**
            # （空工程本就导不出东西），抛异常反而把正常流程变成报错。
            # 调用方（MainWindow）在此前已用 `if not indices: return` 挡过一次。
            return

        pil_frames = []
        duration = int(1000 / project.fps) if project.fps > 0 else 100
        
        with SourceImageCache() as source_cache:
            for orig_idx, frame in frames_to_export:
                canvas = Image.new('RGBA', (project.width, project.height), bg_color)
            
                try:
                    # 合成失败则**不 append**：GIF 没有"占位帧"的概念，补一帧空白
                    # 会让动画时长与节奏都变掉，比少一帧更糟。
                    if _compose_into_canvas(canvas, frame, project.width,
                                            project.height, source_cache,
                                            orig_idx, errors):
                        # Convert to RGB or keep RGBA?
                        # GIF doesn't support full alpha, but PIL can handle it with trans index.
                        # To be safe and simple, let's keep it in RGBA and let PIL handle it,
                        # or convert if necessary.
                        pil_frames.append(canvas)
                
                except Exception as e:
                    export_debug(f"[Export] GIF frame {orig_idx} failed: {e}")
                    _record_error(errors, EXCEPTION, orig_idx, str(e))

        if pil_frames:
            # save_all=True will save the first image followed by all others in pil_frames[1:]
            pil_frames[0].save(
                output_path, 
                save_all=True, 
                append_images=pil_frames[1:], 
                duration=duration, 
                loop=0,
                disposal=2 # Help with transparency artifacts
            )
            export_debug(f"[Export] GIF saved: {output_path}, {len(pil_frames)} frames, duration={duration}ms")
        else:
            # 一帧都没渲染出来：这是整批失败，不是部分成功。此前只是 print，调用方
            # 随后照样弹"导出完成"，而磁盘上根本没有这个文件（P3-11）。
            export_debug(f"[Export] GIF export failed: no frames rendered for {output_path}")
            raise ExportFailedError(list(errors) if errors is not None else [])
