import os
from PIL import Image
from model.project_data import ProjectData

class Exporter:
    @staticmethod
    def export_iter(project: ProjectData, output_dir: str, use_original_filenames: bool = True):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        used_filenames = set()
        enabled_frames = [f for f in project.frames if not f.is_disabled]
        total_frames = len(enabled_frames)
            
        for i, frame in enumerate(enabled_frames):
            yield i + 1, total_frames # Progress
            
            # Create a blank canvas
            # PIL uses (width, height)
            canvas = Image.new('RGBA', (project.width, project.height), (0, 0, 0, 0))
            
            try:
                if os.path.exists(frame.file_path):
                    src_img = Image.open(frame.file_path).convert("RGBA")
                    
                    # Apply Crop (Virtual Slice)
                    if frame.crop_rect:
                        x, y, w, h = frame.crop_rect
                        src_img = src_img.crop((x, y, x + w, y + h))
                    
                    # Apply Scale
                    if frame.scale != 1.0:
                        new_w = int(src_img.width * frame.scale)
                        new_h = int(src_img.height * frame.scale)
                        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    # Calculate position
                    # Frame position is center-relative to canvas center (assuming (0,0) is center)
                    # PIL paste needs top-left coordinates.
                    
                    # Canvas Center
                    cx, cy = project.width / 2, project.height / 2
                    
                    # Image Center
                    # src_img center should be at (cx + frame.x, cy + frame.y)
                    # So top-left is:
                    # x = (cx + frame.x) - src_w/2
                    # y = (cy + frame.y) - src_h/2
                    
                    dest_x = int((cx + frame.position[0]) - src_img.width / 2)
                    dest_y = int((cy + frame.position[1]) - src_img.height / 2)
                    
                    # Paste
                    canvas.alpha_composite(src_img, (dest_x, dest_y))
                
                # Save
                if use_original_filenames:
                    base_name = os.path.basename(frame.file_path)
                    name, ext = os.path.splitext(base_name)
                    filename = base_name
                    
                    # Handle duplicates
                    dup_count = 1
                    while filename in used_filenames:
                        filename = f"{name}_{dup_count}{ext}"
                        dup_count += 1
                    
                    used_filenames.add(filename)
                else:
                    filename = f"frame_{i:04d}.png"
                    
                canvas.save(os.path.join(output_dir, filename))
                
            except Exception as e:
                print(f"Error exporting frame {i}: {e}")
                
    @staticmethod
    def export_sprite_sheet(project: ProjectData, output_path: str):
        enabled_frames = [f for f in project.frames if not f.is_disabled]
        if not enabled_frames:
            return
            
        cols = project.export_sheet_cols
        padding = project.export_sheet_padding
        rows = (len(enabled_frames) + cols - 1) // cols
        
        # Canvas size for each frame
        fw, fh = project.width, project.height
        
        # Total Sheet size
        total_w = cols * fw + (cols + 1) * padding
        total_h = rows * fh + (rows + 1) * padding
        
        sheet = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
        
        for i, frame in enumerate(enabled_frames):
            # Render individual frame to a temporary canvas
            canvas = Image.new('RGBA', (fw, fh), (0, 0, 0, 0))
            
            try:
                if os.path.exists(frame.file_path):
                    src_img = Image.open(frame.file_path).convert("RGBA")
                    
                    if frame.crop_rect:
                        x, y, w, h = frame.crop_rect
                        src_img = src_img.crop((x, y, x + w, y + h))
                        
                    if frame.scale != 1.0:
                        new_w = int(src_img.width * frame.scale)
                        new_h = int(src_img.height * frame.scale)
                        src_img = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        
                    cx, cy = fw / 2, fh / 2
                    dest_x = int((cx + frame.position[0]) - src_img.width / 2)
                    dest_y = int((cy + frame.position[1]) - src_img.height / 2)
                    canvas.alpha_composite(src_img, (dest_x, dest_y))
                
                # Position on sheet
                row_idx = i // cols
                col_idx = i % cols
                
                sheet_x = col_idx * fw + (col_idx + 1) * padding
                sheet_y = row_idx * fh + (row_idx + 1) * padding
                
                sheet.alpha_composite(canvas, (sheet_x, sheet_y))
                
            except Exception as e:
                print(f"Error merging frame {i}: {e}")
                
        sheet.save(output_path)
