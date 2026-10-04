"""Verified cave/building entrances from IsIndoors flips (design doc §10.5).

When the client's IsIndoors() changes, the player is at an entrance.  The
last outdoor and first indoor positions are appended to
``<profile>/verified_entrances.jsonl``; a verified entrance overrides the one
computed from MAP + MMAP (``surface_labels``), and the pair measures that
computation's error (``tools/compare_entrances.py``).
"""
from __future__ import annotations

import json
from pathlib import Path


class EntranceObserver:
    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self.indoors: bool | None = None
        self.last_position: dict | None = None
        self.records: list[dict] = []

    @staticmethod
    def _position(state: dict) -> dict | None:
        point = state.get("player_world_position") or {}
        if not all(isinstance(point.get(axis), (int, float)) for axis in ("x", "y")):
            return None
        return {key: point.get(key) for key in ("x", "y", "z", "instance_id", "z_source")}

    def observe(self, state: dict, now: float) -> dict | None:
        indoors = (state.get("movement") or {}).get("indoors")
        if indoors is None:
            indoors = state.get("is_indoors")
        position = self._position(state)
        record = None
        if (isinstance(indoors, bool) and isinstance(self.indoors, bool)
                and indoors != self.indoors and position and self.last_position):
            record = {"at": now, "direction": "ENTER" if indoors else "EXIT",
                      "before": self.last_position, "after": position,
                      "map_id": state.get("map_id"), "zone": state.get("zone_name"),
                      "subzone": state.get("subzone_name")}
            self.records.append(record)
            if self.path is not None:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record) + "\n")
                except OSError:
                    pass
        if isinstance(indoors, bool):
            self.indoors = indoors
        if position:
            self.last_position = position
        return record
