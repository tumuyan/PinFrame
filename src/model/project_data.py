import json
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
    
    def to_dict(self):
        return {
            "file_path": self.file_path,
            "scale": self.scale,
            "position": self.position,
            "rotation": self.rotation,
            "target_resolution": self.target_resolution,
            "is_disabled": self.is_disabled,
            "crop_rect": self.crop_rect
        }

    @classmethod
    def from_dict(cls, data):
        data_target_res = data.get("target_resolution", None)
        target_res = tuple(data_target_res) if data_target_res else None
        
        data_crop_rect = data.get("crop_rect", None)
        crop_rect = tuple(data_crop_rect) if data_crop_rect else None
        
        return cls(
            file_path=data["file_path"],
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
    export_use_orig_names: bool = True
    export_sheet_cols: int = 4
    export_sheet_padding: int = 0

    def to_json(self):
        return json.dumps({
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "background_color": self.background_color,
            "frames": [f.to_dict() for f in self.frames],
            "last_export_path": self.last_export_path,
            "export_use_orig_names": self.export_use_orig_names,
            "export_sheet_cols": self.export_sheet_cols,
            "export_sheet_padding": self.export_sheet_padding
        }, indent=4)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        project = cls(
            fps=data.get("fps", 6),
            width=data.get("width", 512),
            height=data.get("height", 512),
            background_color=data.get("background_color", "#000000")
        )
        if "frames" in data:
            project.frames = [FrameData.from_dict(f) for f in data["frames"]]
            
        project.last_export_path = data.get("last_export_path", "")
        project.export_use_orig_names = data.get("export_use_orig_names", True)
        project.export_sheet_cols = data.get("export_sheet_cols", 4)
        project.export_sheet_padding = data.get("export_sheet_padding", 0)
        return project
