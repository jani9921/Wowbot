"""Reducer for non-addon perception evidence entering the canonical model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Observation, json_copy as deepcopy, number

if TYPE_CHECKING:
    from .world import WorldModel


class WorldEvidenceReducer:
    """Apply a perception projection to the supplied sole WorldModel writer."""

    _METADATA_KEYS = frozenset({
        "session_id", "timestamp", "frame_id", "surface", "confidence", "provenance",
    })

    def apply(self, model: "WorldModel", observation: Observation,
              *, defer_rebuild: bool = False) -> bool:
        confidence = number(observation.payload.get("confidence"))
        confidence = 1. if confidence is None else max(0., min(1., confidence))
        evidence_keys: list[str] = []
        for key, value in observation.payload.items():
            if key in self._METADATA_KEYS:
                continue
            evidence_keys.append(key)
            model.add_evidence(key, model._diagnostic_claim_value(key, value), observation,
                               confidence=confidence, ttl=2.)
        model.projections[observation.source] = deepcopy(observation.payload)
        model.__dict__.setdefault("projection_received_at", {})[observation.source] = \
            observation.received_at
        if observation.source in {"WORLD3D", "UI_CV"}:
            model.latest_visual_observation_id = observation.observation_id
        if defer_rebuild:
            model._state_dirty = True
        else:
            model._rebuild_state()
        model.history.append(observation)
        for item in observation.payload.get("visual_candidates", []):
            track_id = item.get("track_id")
            if not track_id:
                continue
            visual_value = {
                "semantic_type": "UNKNOWN",
                "visual_type": item.get("detector_kind") or item.get("kind"),
                "appearance": item.get("appearance") or {},
                "candidate_labels": item.get("candidate_labels") or [],
                "visual_relations": item.get("visual_relations") or [],
                "lifecycle": item.get("lifecycle") or item.get("track_state"),
                "stable_frames": item.get("stable_frames"),
            }
            item_confidence = number(item.get("confidence")) or confidence
            model.add_evidence(f"visual_track:{track_id}", visual_value, observation,
                               item_confidence, ttl=4.)
            model.link(f"track:{track_id}", "observed_by",
                       f"observation:{observation.observation_id}", observation,
                       item_confidence, "HYPOTHESIS")
            for relation in item.get("visual_relations") or []:
                other = relation.get("subject_track_id") or relation.get("symbol_track_id")
                if other:
                    model.link(f"track:{track_id}", str(relation.get("type") or "VISUALLY_RELATED"),
                               f"track:{other}", observation, item_confidence,
                               str(relation.get("belief") or "HYPOTHESIS"))
        model._update_track_lifecycle(observation)
        model._update_belief_lifecycle(observation, evidence_keys)
        if defer_rebuild:
            model._deferred_prediction_obs.append(observation)
        else:
            model._evaluate_world_predictions(observation)
        return model._accepted(observation)
