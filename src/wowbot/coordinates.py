"""Coordinate values shared by navigation, UI transport and legacy vision."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PixelRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self, *, space: str = "SCREEN_PIXELS") -> dict[str, object]:
        """Serialize a rectangle without ever dropping its coordinate space."""
        return {"left": self.left, "top": self.top, "right": self.right,
                "bottom": self.bottom, "coordinate_space": space}


@dataclass(frozen=True, slots=True)
class ScreenPoint:
    """A point with an explicit visual coordinate space.

    World3D must not leak unlabelled ``x/y`` pairs to consumers.  The
    compact dictionary representation deliberately matches the existing JSON
    observation transport.
    """
    x: float
    y: float
    space: str

    def to_dict(self) -> dict[str, object]:
        return {"x": round(float(self.x), 6), "y": round(float(self.y), 6),
                "coordinate_space": self.space}


@dataclass(frozen=True, slots=True)
class BearingEstimate:
    """Screen-relative, not world-coordinate, bearing evidence."""
    horizontal: float
    vertical: float
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {"horizontal": round(float(self.horizontal), 6),
                "vertical": round(float(self.vertical), 6),
                "coordinate_space": "CAMERA_RELATIVE_BEARING",
                "confidence": round(max(0.0, min(1.0, float(self.confidence))), 4)}


# Plain world/map values used by navigation and the server path; they lived in
# wowbot.vision.models until REV4 (2026-10-30).  That module re-exports these
# very classes, so isinstance checks and existing imports stay valid.
@dataclass(frozen=True, slots=True)
class MapPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class WorldPosition:
    x: float
    y: float
    z: float = 0.0


# Pure minimap geometry; it lived in wowbot.vision.minimap_quest_area (numpy
# CV) until REV4 (2026-10-31), which re-exports it.
def offsets_to_world(offsets, *, player_x: float, player_y: float, view_radius_yards: float,
                     rotate: bool = False, facing: float | None = None) -> list[tuple[float, float]]:
    """Minimap offsets -> WORLD_YARDS (x = north, y = west; facing 0 = +x).

    North-up minimap: screen up is north (+x) and screen left is west (+y).
    A rotating minimap puts the player's facing up instead.
    """
    import math
    heading = float(facing) if rotate and facing is not None else 0.
    forward = (math.cos(heading), math.sin(heading))
    right = (math.sin(heading), -math.cos(heading))
    result = []
    for dx, dy in offsets:
        up, across = -float(dy)*view_radius_yards, float(dx)*view_radius_yards
        result.append((player_x + up*forward[0] + across*right[0],
                       player_y + up*forward[1] + across*right[1]))
    return result
