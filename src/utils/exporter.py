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
                # We could yield error here too if we change signature, but printing is okay for now.
