from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import MovementIntent
from wowbot.vision.models import WorldPosition


class MovementController(Protocol):
    """Execution boundary. Navigation supplies intent; this layer owns physical movement."""
    def execute(self, intent: MovementIntent) -> None: ...

    def stop(self) -> None: ...


class InputAdapter(Protocol):
    """Optional physical input adapter; kept separate from navigation and policy."""
    def set_forward(self, enabled: bool) -> None: ...
    def set_strafe(self, left: bool, right: bool) -> None: ...
    def set_heading(self, degrees: float) -> None: ...


@dataclass(frozen=True, slots=True)
class MovementFeedback:
    position: WorldPosition
    heading_deg: float | None
    moving: bool
    blocked: bool = False
    source: str = "client"
