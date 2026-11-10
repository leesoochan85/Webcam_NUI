from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Config:
    camera_index: int = 0
    camera_width: int = 960
    camera_height: int = 540
    mirror: bool = True
    detection_confidence: float = 0.6
    tracking_confidence: float = 0.6
    pose_debounce: float = 0.07
    pinch_close: float = 0.30
    pinch_open: float = 0.48
    drag_hold: float = 0.28
    drag_distance_px: float = 14.0
    click_cooldown: float = 0.25
    alt_hold: float = 0.8
    alt_step_distance: float = 0.12
    alt_step_cooldown: float = 0.35
    capture_timeout: float = 2.8
    capture_cooldown: float = 3.0
    snipping_timeout: float = 20.0
    toggle_hold: float = 1.2
    lost_timeout: float = 0.35
    edge_margin: float = 0.12
    edge_reentry_band: float = 0.08
    edge_reentry_timeout: float = 3.0
    smoothing_tau: float = 0.045
    scroll_step: float = 0.035
    scroll_invert: bool = False

    def validate(self):
        integer_fields = {"camera_index", "camera_width", "camera_height"}
        boolean_fields = {"mirror", "scroll_invert"}
        for name, value in asdict(self).items():
            if name in integer_fields:
                if type(value) is not int:
                    raise ValueError(f"{name}: integer required")
            elif name in boolean_fields:
                if type(value) is not bool:
                    raise ValueError(f"{name}: true or false required")
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{name}: number required")
            if name not in boolean_fields and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name}: finite non-negative number required")
        if min(self.camera_width, self.camera_height) < 160:
            raise ValueError("camera size must be at least 160 pixels")
        if not 0 < self.pinch_close < self.pinch_open:
            raise ValueError("pinch_close must be smaller than pinch_open")
        if not 0 < self.edge_margin < 0.4:
            raise ValueError("edge_margin must be between 0 and 0.4")
        if not 0 < self.edge_reentry_band < 0.3:
            raise ValueError("edge_reentry_band must be between 0 and 0.3")
        for name in ("detection_confidence", "tracking_confidence"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name}: must be in (0, 1]")
        for name in ("scroll_step", "smoothing_tau", "alt_step_distance", "capture_timeout"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name}: must be positive")
        return self

    @classmethod
    def load(cls, path: Path):
        return cls(**json.loads(path.read_text(encoding="utf-8"))).validate()
