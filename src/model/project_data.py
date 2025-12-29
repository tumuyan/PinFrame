import json
import os
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class FrameData:
    file_path: str
    scale: float = 1.0
    position: Tuple[int, int] = (0, 0)
    rotation: float = 0.0
    target_resolution: Optional[Tuple[int, int]] = None
    is_disabled: bool = False
    crop_rect: Optional[Tuple[int, int, int, int]] = None # (x, y, w, h)
    
    def to_dict(self, base_dir: Optional[str] = None):
        path = self.file_path
        if base_dir and os.path.isabs(path):
            try:
                # Normalize both to ensure matching on Windows
                norm_path = os.path.normpath(path)
                norm_base = os.path.normpath(base_dir)
                rel = os.path.relpath(norm_path, norm_base)
                if not rel.startswith('..') and not os.path.isabs(rel):
                    path = rel.replace('\\', '/') # Use forward slashes for cross-platform JSON
            except ValueError:
                pass
                
        return {
            "file_path": path,
            "scale": self.scale,
            "position": self.position,
            "rotation": self.rotation,
            "target_resolution": self.target_resolution,
            "is_disabled": self.is_disabled,
            "crop_rect": self.crop_rect
        }

    @classmethod
    def from_dict(cls, data, base_dir: Optional[str] = None):
        file_path = data["file_path"]
        
        # Resolution logic:
        # 1. If absolute and exists -> OK
        # 2. If relative and base_dir provided -> join and check
        # 3. If absolute and NOT exists, try to treat as if it were relative to base_dir
        
        if not os.path.isabs(file_path):
            if base_dir:
                abs_path = os.path.abspath(os.path.join(base_dir, file_path))
                if os.path.exists(abs_path):
                    file_path = abs_path
        else:
            if not os.path.exists(file_path) and base_dir:
                # Try to find it relative to project dir even if stored as absolute
                # e.g. D:/old/img.png -> project_dir/old/img.png or just project_dir/img.png?
                # Usually users want "if I move the folder, it finds it".
                # Let's try joining the tail.
                tail = os.path.basename(file_path)
                test_path = os.path.abspath(os.path.join(base_dir, tail))
                if os.path.exists(test_path):
                    file_path = test_path
                else:
                    # Also try preserving the relative structure if possible? 
                    # Complex, but let's stick to basics for now.
                    pass
        data_target_res = data.get("target_resolution", None)
        target_res = tuple(data_target_res) if data_target_res else None
        
        data_crop_rect = data.get("crop_rect", None)
        crop_rect = tuple(data_crop_rect) if data_crop_rect else None
        
        return cls(
            file_path=file_path,
            scale=data.get("scale", 1.0),
            position=tuple(data.get("position", (0, 0))),
            rotation=data.get("rotation", 0.0),
            target_resolution=target_res,
            is_disabled=data.get("is_disabled", data.get("is_active", False)),
            crop_rect=crop_rect
        )

@dataclass
class ProjectData:
    fps: int = 6
    width: int = 512
    height: int = 512
    frames: List[FrameData] = field(default_factory=list)
    background_color: str = "#000000"
    
    # Persistent Settings
    last_export_path: str = ""
    last_gif_export_path: str = ""
    export_use_orig_names: bool = True
    export_sheet_cols: int = 4
    export_sheet_padding: int = 0
    export_bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0)
    export_range_mode: str = "all" # "all", "selected", "custom"
    export_custom_range: str = ""

    def to_json(self, project_file_path: Optional[str] = None):
        base_dir = os.path.abspath(os.path.dirname(project_file_path)) if project_file_path else None
        return json.dumps({
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "background_color": self.background_color,
            "frames": [f.to_dict(base_dir) for f in self.frames],
            "last_export_path": self.last_export_path,
            "last_gif_export_path": self.last_gif_export_path,
            "export_use_orig_names": self.export_use_orig_names,
            "export_sheet_cols": self.export_sheet_cols,
            "export_sheet_padding": self.export_sheet_padding,
            "export_bg_color": self.export_bg_color,
            "export_range_mode": self.export_range_mode,
            "export_custom_range": self.export_custom_range
        }, indent=4)

    @classmethod
    def from_json(cls, json_str, project_file_path: Optional[str] = None):
        base_dir = os.path.abspath(os.path.dirname(project_file_path)) if project_file_path else None
        data = json.loads(json_str)
        project = cls(
            fps=data.get("fps", 6),
            width=data.get("width", 512),
            height=data.get("height", 512),
            background_color=data.get("background_color", "#000000")
        )
        if "frames" in data:
            project.frames = [FrameData.from_dict(f, base_dir) for f in data["frames"]]
            
        project.last_export_path = data.get("last_export_path", "")
        project.last_gif_export_path = data.get("last_gif_export_path", "")
        project.export_use_orig_names = data.get("export_use_orig_names", True)
        project.export_sheet_cols = data.get("export_sheet_cols", 4)
        project.export_sheet_padding = data.get("export_sheet_padding", 0)
        project.export_bg_color = tuple(data.get("export_bg_color", (0, 0, 0, 0)))
        project.export_range_mode = data.get("export_range_mode", "all")
        project.export_custom_range = data.get("export_custom_range", "")
        return project
