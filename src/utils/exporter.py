import os
from typing import List, Tuple, Optional
from PIL import Image
from model.project_data import ProjectData

class Exporter:
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
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        used_filenames = set()
        
        # If no indices provided, export all active frames
        if frame_indices is None:
            # We must map indices from the original project.frames
            frames_to_export = [(i, f) for i, f in enumerate(project.frames) if not f.is_disabled]
        else:
            frames_to_export = [(i, project.frames[i]) for i in frame_indices if i < len(project.frames)]
            
        total_frames = len(frames_to_export)
        if total_frames == 0:
            return
            
        for progress_idx, (orig_idx, frame) in enumerate(frames_to_export):
            yield progress_idx + 1, total_frames # Progress bar info
            
            # Create a blank canvas with BG color
            canvas = Image.new('RGBA', (project.width, project.height), bg_color)
            
            try:
                if os.path.exists(frame.file_path):
                    src_img = Image.open(frame.file_path).convert("RGBA")
                    
                    if frame.crop_rect:
                        x, y, w, h = frame.crop_rect
                        src_img = src_img.crop((x, y, x + w, y + h))
                    
                    # Handle scale and aspect_ratio (negative values indicate mirroring)
                    scale_x = frame.scale
                    scale_y = frame.scale / frame.aspect_ratio
                    
                    new_w = int(src_img.width * abs(scale_x))
                    new_h = int(src_img.height * abs(scale_y))
                    
                    if new_w > 0 and new_h > 0:
                        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        
                        # Apply mirroring if scales are negative
                        if scale_x < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        if scale_y < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                        
                        # Apply rotation
                        if frame.rotation != 0:
                            src_img = src_img.rotate(-frame.rotation, resample=Image.Resampling.BICUBIC, expand=True)
                    
                        cx, cy = project.width / 2, project.height / 2
                        dest_x = int((cx + frame.position[0]) - src_img.width / 2)
                        dest_y = int((cy + frame.position[1]) - src_img.height / 2)
                        
                        canvas.alpha_composite(src_img, (dest_x, dest_y))
                
                # Save
                if use_original_filenames:
                    base_name = os.path.basename(frame.file_path)
                    name, ext = os.path.splitext(base_name)
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
                
    @staticmethod
    def export_sprite_sheet(project: ProjectData, output_path: str, 
                           frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)):
        
        if frame_indices is None:
            frames_to_export = [f for f in project.frames if not f.is_disabled]
        else:
            frames_to_export = [project.frames[i] for i in frame_indices if i < len(project.frames)]
            
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
        
        for i, frame in enumerate(frames_to_export):
            # Render individual frame to a temporary canvas with bg_color
            canvas = Image.new('RGBA', (fw, fh), bg_color)
            
            try:
                if os.path.exists(frame.file_path):
                    src_img = Image.open(frame.file_path).convert("RGBA")
                    
                    if frame.crop_rect:
                        x, y, w, h = frame.crop_rect
                        src_img = src_img.crop((x, y, x + w, y + h))
                    
                    # Handle scale and aspect_ratio (negative values indicate mirroring)
                    scale_x = frame.scale
                    scale_y = frame.scale / frame.aspect_ratio
                    
                    new_w = int(src_img.width * abs(scale_x))
                    new_h = int(src_img.height * abs(scale_y))
                    
                    if new_w > 0 and new_h > 0:
                        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        
                        if scale_x < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        if scale_y < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                        
                        if frame.rotation != 0:
                            src_img = src_img.rotate(-frame.rotation, resample=Image.Resampling.BICUBIC, expand=True)
                        
                        cx, cy = fw / 2, fh / 2
                        dest_x = int((cx + frame.position[0]) - src_img.width / 2)
                        dest_y = int((cy + frame.position[1]) - src_img.height / 2)
                        canvas.alpha_composite(src_img, (dest_x, dest_y))
                
                row_idx = i // cols
                col_idx = i % cols
                
                sheet_x = col_idx * fw + (col_idx + 1) * padding
                sheet_y = row_idx * fh + (row_idx + 1) * padding
                
                sheet.alpha_composite(canvas, (sheet_x, sheet_y))
                
            except Exception as e:
                print(f"Error merging frame {i}: {e}")
                
        sheet.save(output_path)

    @staticmethod
    def export_gif(project: ProjectData, output_path: str, 
                   frame_indices: Optional[List[int]] = None, bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)):
        
        if frame_indices is None:
            frames_to_export = [f for f in project.frames if not f.is_disabled]
        else:
            frames_to_export = [project.frames[i] for i in frame_indices if i < len(project.frames)]
            
        if not frames_to_export:
            return
            
        pil_frames = []
        duration = int(1000 / project.fps) if project.fps > 0 else 100
        
        for frame in frames_to_export:
            canvas = Image.new('RGBA', (project.width, project.height), bg_color)
            
            try:
                if os.path.exists(frame.file_path):
                    src_img = Image.open(frame.file_path).convert("RGBA")
                    
                    if frame.crop_rect:
                        x, y, w, h = frame.crop_rect
                        src_img = src_img.crop((x, y, x + w, y + h))
                    
                    # Handle scale and aspect_ratio (negative values indicate mirroring)
                    scale_x = frame.scale
                    scale_y = frame.scale / frame.aspect_ratio
                    
                    new_w = int(src_img.width * abs(scale_x))
                    new_h = int(src_img.height * abs(scale_y))
                    
                    if new_w > 0 and new_h > 0:
                        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        
                        if scale_x < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        if scale_y < 0:
                            src_img = src_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                        
                        if frame.rotation != 0:
                            src_img = src_img.rotate(-frame.rotation, resample=Image.Resampling.BICUBIC, expand=True)
                        
                        cx, cy = project.width / 2, project.height / 2
                        dest_x = int((cx + frame.position[0]) - src_img.width / 2)
                        dest_y = int((cy + frame.position[1]) - src_img.height / 2)
                        canvas.alpha_composite(src_img, (dest_x, dest_y))
                
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
