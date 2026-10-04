from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class WorldSceneROI:
    """Playable 3D-world ROI plus screen-space regions excluded as UI.

    ``self_avatar_rect`` is deliberately separate from ``excluded_rects``. It
    describes where the third-person avatar is likely to occur, but pixels in
    that region remain observable because a nearby NPC/object may overlap it.
    """
    rect: PixelRect
    excluded_rects: tuple[PixelRect, ...] = ()
    profile: str = "retail_generic"
    self_avatar_rect: PixelRect | None = None
    # Learned detectors are trained with HUD hard negatives and need a taller
    # view than the heuristic scene crop. In particular, distant overhead
    # quest markers can sit inside the otherwise excluded top HUD band.
    learned_rect: PixelRect | None = None
    # Opaque/stable UI regions that even the learned detector must ignore.
    # This is separate from broad optional HUD masks because real world units
    # may still be visible behind translucent quest/minimap overlays.
    hard_excluded_rects: tuple[PixelRect, ...] = ()


@dataclass(frozen=True, slots=True)
class WorldCandidate:
    """Appearance-only 3D observation; recognition happens downstream."""
    kind: str
    rect: PixelRect
    confidence: float
    evidence: str = ""
    relation: str | None = None
    class_name: str | None = None
    class_color: str | None = None
    track_id: int | None = None
    previous_relation: str | None = None
    relation_changed: bool = False
    appearance: dict[str, object] = field(default_factory=dict)
    candidate_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorldFrameObservation:
    width: int
    height: int
    scene: WorldSceneROI
    # A World3D result is never an anonymous image interpretation.  Keep the
    # capture identity with the source frame so replay, tracker association
    # and addon/vision correlation can all point at the same physical sample.
    frame_id: str
    client_id: str
    candidates: tuple[WorldCandidate, ...] = ()
    observed_at: float = 0.0
    source: str = "screen_capture"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("invalid frame dimensions")
        if not self.frame_id.strip():
            raise ValueError("source frame_id is required")
        if not self.client_id.strip():
            raise ValueError("source client_id is required")
        if self.observed_at < 0:
            raise ValueError("observed_at must be monotonic and non-negative")
        for candidate in self.candidates:
            if not 0.0 <= candidate.confidence <= 1.0:
                raise ValueError("candidate confidence must be within [0,1]")


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


@dataclass(frozen=True, slots=True)
class World3DObservationBatch:
    """Canonical, read-only World3D output.

    It contains perception evidence only.  It intentionally exposes no
    movement, interaction, combat, or planner commands.  The WorldModel owns
    cross-sensor fusion; users of this object may rank evidence but cannot
    treat a visual hypothesis as game truth.
    """
    frame_id: str
    timestamp: float
    client_id: str
    scene_roi: dict[str, Any]
    camera_state: dict[str, Any]
    ego_motion: dict[str, Any]
    entity_tracks: tuple[dict[str, Any], ...] = ()
    # Per-frame detector output stays distinct from temporal tracks.  A track
    # may survive an occlusion; a detection always names exactly one source
    # frame and carries an explicit UNKNOWN-first class distribution.
    detections: tuple[dict[str, Any], ...] = ()
    scene_geometry: dict[str, Any] = field(default_factory=dict)
    traversability: dict[str, Any] = field(default_factory=dict)
    obstacles: tuple[dict[str, Any], ...] = ()
    entrances: tuple[dict[str, Any], ...] = ()
    landmarks: tuple[dict[str, Any], ...] = ()
    interaction_candidates: tuple[dict[str, Any], ...] = ()
    negative_evidence: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # Frame lifecycle is evidence, not a UI-only performance counter.  A
    # consumer can therefore distinguish a stable scene from a stale one
    # whose intermediate captures were deliberately dropped under load.
    frame_events: tuple[dict[str, Any], ...] = ()
    processing_latency_ms: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-shaped snapshot safe to publish as an Observation."""
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "client_id": self.client_id,
            "scene_roi": dict(self.scene_roi),
            "camera_state": dict(self.camera_state),
            "ego_motion": dict(self.ego_motion),
            "entity_tracks": [dict(item) for item in self.entity_tracks],
            "detections": [dict(item) for item in self.detections],
            "scene_geometry": dict(self.scene_geometry),
            "traversability": dict(self.traversability),
            "obstacles": [dict(item) for item in self.obstacles],
            "entrances": [dict(item) for item in self.entrances],
            "landmarks": [dict(item) for item in self.landmarks],
            "interaction_candidates": [dict(item) for item in self.interaction_candidates],
            "negative_evidence": [dict(item) for item in self.negative_evidence],
            "diagnostics": dict(self.diagnostics),
            "frame_events": [dict(item) for item in self.frame_events],
            "processing_latency_ms": round(float(self.processing_latency_ms), 3),
        }
