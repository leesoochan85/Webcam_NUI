"""Pure geometry; no webcam, MediaPipe or operating-system imports."""
from dataclasses import dataclass
from enum import Enum
from math import acos, degrees, hypot
from .config import Config


class Pose(str, Enum):
    POINT = "POINT"
    LEFT_PINCH = "LEFT_PINCH"
    RIGHT_PINCH = "RIGHT_PINCH"
    SCROLL = "SCROLL"
    OPEN = "OPEN_PALM"
    FIST = "FIST"
    TOGGLE = "PINKY_ONLY"
    OTHER = "OTHER"


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True)
class Observation:
    pose: Pose
    x: float
    y: float
    palm_x: float
    palm_y: float
    pinch_ratio: float = 1.0


def distance(a: Point, b: Point):
    return hypot(a.x - b.x, a.y - b.y)


def angle(a: Point, b: Point, c: Point):
    u, v = (a.x - b.x, a.y - b.y), (c.x - b.x, c.y - b.y)
    divisor = hypot(*u) * hypot(*v)
    if divisor < 1e-9:
        return 0.0
    return degrees(acos(max(-1.0, min(1.0, (u[0]*v[0] + u[1]*v[1])/divisor))))


class Classifier:
    def __init__(self, config: Config):
        self.config = config
        self.left_latched = False
        self.right_latched = False

    def reset(self):
        self.left_latched = self.right_latched = False

    def classify(self, landmarks, width: int, height: int):
        if len(landmarks) != 21:
            raise ValueError("21 landmarks required")
        # Pixel coordinates avoid aspect-ratio distortion of angles/distances.
        p = [Point(v.x*width, v.y*height) for v in landmarks]
        scale = max(distance(p[5], p[17]), distance(p[0], p[9])*0.65, 1.0)
        extended = []
        for base in (5, 9, 13, 17):
            extended.append(
                angle(p[base], p[base+1], p[base+3]) > 155
                and distance(p[base+3], p[0]) > distance(p[base+1], p[0])*1.12
            )
        index, middle, ring, pinky = extended
        left_ratio = distance(p[4], p[8])/scale
        right_ratio = distance(p[4], p[12])/scale
        # A curled fist may also place thumb/index tips close together.
        left_eligible = (not middle and not ring and not pinky
                         and distance(p[8], p[0]) > distance(p[5], p[0])*1.12)
        right_eligible = (index and not ring and not pinky
                          and distance(p[12], p[0]) > distance(p[9], p[0])*1.12)
        left_limit = self.config.pinch_open if self.left_latched else self.config.pinch_close
        right_limit = self.config.pinch_open if self.right_latched else self.config.pinch_close
        self.left_latched = left_eligible and left_ratio < left_limit
        self.right_latched = right_eligible and right_ratio < right_limit
        thumb_open = angle(p[2], p[3], p[4]) > 145 and distance(p[4], p[5])/scale > 0.55
        if all(extended) and thumb_open:
            pose = Pose.OPEN
        elif self.left_latched:
            pose = Pose.LEFT_PINCH
        elif self.right_latched:
            pose = Pose.RIGHT_PINCH
        elif not any(extended):
            pose = Pose.FIST
        elif pinky and not index and not middle and not ring:
            pose = Pose.TOGGLE
        elif index and middle and not ring and not pinky:
            pose = Pose.SCROLL
        elif index and not middle and not ring and not pinky:
            pose = Pose.POINT
        else:
            pose = Pose.OTHER
        palm = [landmarks[i] for i in (0, 5, 9, 13, 17)]
        return Observation(pose, landmarks[8].x, landmarks[8].y,
                           sum(v.x for v in palm)/5, sum(v.y for v in palm)/5,
                           left_ratio)
