"""Immutable logical context shared by sensors and the world boundary.

These values describe identity and scope, not input authority or freshness.
The authenticated IPC runtime/context nonce and all sample-time checks remain
separate. No process-start, phase, or dungeon-instance identity is inferred.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContextState(str, Enum):
    VALID = "VALID"
    PENDING = "PENDING"
    MISMATCH = "MISMATCH"


def _integer(value: Any, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {name}")


def _text(value: Any, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"invalid {name}")


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    selected_pid: int
    session_id: str
    character_guid: str
    game_build: int

    def __post_init__(self) -> None:
        _integer(self.selected_pid, "selected_pid", 1)
        _text(self.session_id, "session_id")
        _text(self.character_guid, "character_guid")
        _integer(self.game_build, "game_build", 1)


@dataclass(frozen=True, slots=True)
class WorldContext:
    # Legacy instance_id names the world/map dataset used by navigation.
    # It does not establish a unique dungeon-run identity. Map 0 is valid.
    instance_id: int
    ui_map_id: int | None = None
    phase: int | str | None = None

    def __post_init__(self) -> None:
        _integer(self.instance_id, "instance_id")
        if self.ui_map_id is not None:
            _integer(self.ui_map_id, "ui_map_id")
        if self.phase is not None:
            if type(self.phase) is int:
                _integer(self.phase, "phase")
            else:
                _text(self.phase, "phase")


@dataclass(frozen=True, slots=True)
class SessionContext:
    identity: SessionIdentity
    world: WorldContext

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SessionIdentity) or not isinstance(self.world, WorldContext):
            raise ValueError("invalid session/world context")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> SessionContext | None:
        """Parse legacy logical fields, ignoring transport metadata.

        UI map may be absent in a stored entity scope. Packet bootstrap must
        additionally require a known UI map. Malformed values never become a
        partially usable identity; phase=None remains unknown.
        """
        if not isinstance(value, Mapping):
            return None
        try:
            identity = SessionIdentity(value.get("selected_pid"), value.get("session_id"),
                                       value.get("character_guid"), value.get("game_build"))
            world = WorldContext(value.get("instance_id"), value.get("map_id"), value.get("phase"))
            return cls(identity, world)
        except ValueError:
            return None

    def as_dict(self) -> dict[str, Any]:
        return {"selected_pid": self.identity.selected_pid, "session_id": self.identity.session_id,
                "character_guid": self.identity.character_guid, "game_build": self.identity.game_build,
                "map_id": self.world.ui_map_id, "instance_id": self.world.instance_id,
                "phase": self.world.phase}

    def entity_scope(self) -> dict[str, Any]:
        """World facts survive UI-map steps, never a session/phase change."""
        result = self.as_dict()
        result.pop("map_id")
        return result


def context_matches(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None,
                    *, include_ui_map: bool = True) -> bool:
    """Logical comparison only; cannot replace authenticated IPC equality."""
    a, b = SessionContext.from_mapping(left), SessionContext.from_mapping(right)
    if a is None or b is None:
        return False
    if include_ui_map:
        return a == b
    return (a.identity == b.identity and a.world.instance_id == b.world.instance_id
            and a.world.phase == b.world.phase)
