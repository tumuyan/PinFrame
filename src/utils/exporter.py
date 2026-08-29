import os
from typing import List, Tuple, Optional
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


class SourceImageCache:
    """导出期生命周期的源图缓存：`{path: PIL.Image}`。

    `compose_frame` 原本对每一帧都 `Image.open(path).convert("RGBA")` —— 精灵表工程
    里几百帧共用同一张源图，于是同一文件被完整解码几百遍（P2-7 第 4 点）。这里按
    路径缓存**解码后、未裁切**的原图，一次导出结束（`with` 退出）时统一 `close()`
    释放文件句柄。

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

        img = Image.open(path).convert("RGBA")
        size = self._image_bytes(img)
        self._evict_to_fit(size)
        self._images[path] = img
        self._bytes += size
        return img

    def close(self) -> None:
        """释放全部缓存图像的文件句柄。"""
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
                    frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)):
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
                    Exporter.compose_frame(canvas, frame, project.width, project.height,
                                           source_cache)

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
                    print(f"Error exporting frame {orig_idx}: {e}")
                
        export_debug(f"[Export] Export_iter completed: {total_frames} frames exported")
                
    @staticmethod
    def export_sprite_sheet(project: ProjectData, output_path: str, 
                           frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)):
        
        export_debug(f"[Export] Starting sprite sheet export: output_path={output_path}")

        all_frames = project.frames      # 属性读取会取实时快照，只取一次
        if frame_indices is None:
            frames_to_export = [f for f in all_frames if not f.is_disabled]
        else:
            frames_to_export = [all_frames[i] for i in frame_indices if i < len(all_frames)]
            
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
            for i, frame in enumerate(frames_to_export):
                # Render individual frame to a temporary canvas with bg_color
                canvas = Image.new('RGBA', (fw, fh), bg_color)
            
                try:
                    Exporter.compose_frame(canvas, frame, fw, fh,
                                           source_cache)

                    row_idx = i // cols
                    col_idx = i % cols
                
                    sheet_x = col_idx * fw + (col_idx + 1) * padding
                    sheet_y = row_idx * fh + (row_idx + 1) * padding
                
                    sheet.alpha_composite(canvas, (sheet_x, sheet_y))
                
                except Exception as e:
                    print(f"Error merging frame {i}: {e}")
                
        sheet.save(output_path)
        export_debug(f"[Export] Sprite sheet saved: {output_path}, {len(frames_to_export)} frames, {cols}x{rows} grid")

    @staticmethod
    def export_gif(project: ProjectData, output_path: str, 
                   frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)):
        
        export_debug(f"[Export] Starting GIF export: output_path={output_path}")

        all_frames = project.frames      # 属性读取会取实时快照，只取一次
        if frame_indices is None:
            frames_to_export = [f for f in all_frames if not f.is_disabled]
        else:
            frames_to_export = [all_frames[i] for i in frame_indices if i < len(all_frames)]
            
        if not frames_to_export:
            return
            
        pil_frames = []
        duration = int(1000 / project.fps) if project.fps > 0 else 100
        
        with SourceImageCache() as source_cache:
            for frame in frames_to_export:
                canvas = Image.new('RGBA', (project.width, project.height), bg_color)
            
                try:
                    Exporter.compose_frame(canvas, frame, project.width, project.height,
                                           source_cache)

                    # Convert to RGB or keep RGBA?
                    # GIF doesn't support full alpha, but PIL can handle it with trans index.
                    # To be safe and simple, let's keep it in RGBA and let PIL handle it, 
                    # or convert if necessary.
                    pil_frames.append(canvas)
                
                except Exception as e:
                    print(f"Error rendering gif frame: {e}")
                
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
            # All frames failed to render - log a warning so the failure is visible,
            # consistent with the other exporters.
            print(f"Error rendering gif: no frames could be rendered for {output_path}")
            export_debug(f"[Export] GIF export failed: no frames rendered for {output_path}")
