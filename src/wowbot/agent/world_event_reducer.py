"""The sole reducer for raw addon event records entering ``WorldModel``.

It deliberately receives the canonical model as its write target: this is an
extraction of mutation responsibility, not a second world state or event
cache.  It has no planner, executor, or input dependency.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import EventRecord, Observation

if TYPE_CHECKING:
    from .world import WorldModel


class WorldEventReducer:
    def apply(self, model: "WorldModel", state: dict, observation: Observation) -> int:
        """Apply each new source event exactly once and return its count."""
        applied = 0
        for raw_event in state.get("events", []):
            key = (observation.session_id, raw_event.get("sequence"))
            if key in model.seen_events:
                continue
            model.events.append(raw_event)
            model.seen_events.add(key)
            record = EventRecord.create(raw_event, observation)
            model.event_records.append(record)
            model.quest_model.apply_event(record)
            for entity_id in record.entity_ids:
                model.link(f"entity:{entity_id}", "participated_in", f"event:{record.event_id}", observation)
            for quest_id in record.quest_ids:
                model.link(f"quest:{quest_id}", "causes", f"event:{record.event_id}", observation)
            model.link(f"event:{record.event_id}", "observed_by", f"observation:{observation.observation_id}", observation)
            if record.event_type == "QUEST_ACCEPTED":
                for quest_id in record.quest_ids:
                    model._world_prediction("QUEST_MARKER_APPEARANCE", f"quest:{quest_id}",
                                            {"quest_id": quest_id, "coverage_observations": []}, observation,
                                            horizon=12., confidence=.6)
            model._project_corpse_event(raw_event, state, observation)
            applied += 1
        return applied
