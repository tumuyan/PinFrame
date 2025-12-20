import json
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class FrameData:
    file_path: str
    scale: float = 1.0
    position: Tuple[int, int] = (0, 0) # x, y relative to center or top-left? Let's say relative to center of canvas for now, or maybe top-left of canvas. 
                                       # Convention: Let's use center relative to canvas center for easier centering. 
                                       # Actually, simpler is: position is the offset from the top-left of the canvas.
    rotation: float = 0.0
    target_resolution: Optional[Tuple[int, int]] = None # (width, height)
    
    def to_dict(self):
        return {
            "file_path": self.file_path,
            "scale": self.scale,
            "position": self.position,
            "rotation": self.rotation,
            "target_resolution": self.target_resolution
        }

    @classmethod
    def from_dict(cls, data):
        data_target_res = data.get("target_resolution", None)
        target_res = tuple(data_target_res) if data_target_res else None
        
        return cls(
            file_path=data["file_path"],
            scale=data.get("scale", 1.0),
            position=tuple(data.get("position", (0, 0))),
            rotation=data.get("rotation", 0.0),
            target_resolution=target_res
        )

@dataclass
class ProjectData:
    fps: int = 12
    width: int = 512
    height: int = 512
    frames: List[FrameData] = field(default_factory=list)
    background_color: str = "#000000" # Hex color
    # maybe checkerboard option?

    def to_json(self):
        return json.dumps({
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "background_color": self.background_color,
            "frames": [f.to_dict() for f in self.frames]
        }, indent=4)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        project = cls(
            fps=data.get("fps", 12),
            width=data.get("width", 512),
            height=data.get("height", 512),
            background_color=data.get("background_color", "#000000")
        )
        if "frames" in data:
            project.frames = [FrameData.from_dict(f) for f in data["frames"]]
        return project
