"""World-model hypothesis prediction lifecycle without control authority."""
from __future__ import annotations

import hashlib
import math
import uuid

from .models import Prediction, PredictionError, canonical, json_copy, number


class WorldPredictionRuntime:
    """Create and evaluate bounded world hypotheses on behalf of WorldModel."""

    def create(self, world, kind: str, subject: str, predicted_state: dict,
               obs, *, horizon: float, confidence: float):
        if any(item.prediction_kind == kind and item.subject == subject
               and item.status == "PENDING" for item in world.predictions):
            return None
        trials = world.prediction_calibration.get(
            kind, {"successes": 0, "failures": 0})
        reliability = ((trials["successes"] + 2)
                       / (trials["successes"] + trials["failures"] + 4))
        adjusted = min(confidence, .5 * confidence + .5 * reliability)
        prediction_id = hashlib.sha256(canonical({
            "kind": kind, "subject": subject, "state": predicted_state,
            "observation": obs.observation_id,
            "revision": world.model_revision}).encode()).hexdigest()[:24]
        prediction = Prediction(
            prediction_id, "WORLD_MODEL", kind, obs.received_at,
            obs.received_at+horizon, obs.observation_id, confidence=adjusted,
            provenance=(obs.observation_id,), prediction_kind=kind,
            subject=subject, predicted_state=json_copy(predicted_state),
            model_revision=world.model_revision)
        world.predictions.append(prediction)
        world.link(subject, "has_prediction", f"prediction:{prediction_id}",
                   obs, adjusted, "HYPOTHESIS")
        return prediction

    def finish(self, world, prediction: Prediction, outcome: str, reason: str,
               obs, *, mismatch: bool = False) -> None:
        prediction.status, prediction.reason = outcome, reason
        calibration = world.prediction_calibration.setdefault(
            prediction.prediction_kind, {"successes": 0, "failures": 0})
        if outcome == "SUCCESS":
            calibration["successes"] += 1
            world._emit_derived_event("PREDICTION_VERIFIED", {
                "prediction_id": prediction.prediction_id,
                "prediction_kind": prediction.prediction_kind,
                "subject": prediction.subject}, obs)
        elif mismatch:
            calibration["failures"] += 1
            error = PredictionError(
                uuid.uuid4().hex, prediction.prediction_id,
                prediction.action_id, prediction.expected, reason,
                prediction.created_at, obs.received_at,
                prediction.observation_id, obs.observation_id,
                failure_type="WORLD_MODEL_MISMATCH")
            world.record_prediction_error(error)
            world.model_revision += 1
            world._emit_derived_event("PREDICTION_ERROR", {
                "prediction_id": prediction.prediction_id,
                "prediction_kind": prediction.prediction_kind,
                "subject": prediction.subject, "reason": reason,
                "new_model_revision": world.model_revision}, obs)

    def evaluate(self, world, obs) -> None:
        for prediction in list(world.predictions):
            if (prediction.prediction_kind == "ACTION_OUTCOME"
                    or prediction.status != "PENDING"):
                continue
            if prediction.prediction_kind == "ENTITY_PERSISTENCE":
                self._evaluate_entity_persistence(world, prediction, obs)
            elif prediction.prediction_kind == "QUEST_MARKER_APPEARANCE":
                self._evaluate_quest_marker(world, prediction, obs)

    def _evaluate_entity_persistence(self, world, prediction, obs) -> None:
        expected = prediction.predicted_state
        observed = None
        for key in ("target", "mouseover"):
            unit = world.state.get(key) or {}
            identity = (
                f"entity:npc:{unit['npc_id']}" if unit.get("npc_id") is not None
                else f"entity:{unit.get('guid')}" if unit.get("guid") else None)
            if identity == prediction.subject and unit.get("world_position"):
                observed = unit["world_position"]
                break
        if observed:
            dx = (number(observed.get("x")) or 0) - expected["x"]
            dy = (number(observed.get("y")) or 0) - expected["y"]
            if math.hypot(dx, dy) <= expected.get("tolerance", .03):
                self.finish(world, prediction, "SUCCESS",
                            "entity_observed_near_predicted_location", obs)
            else:
                self.finish(world, prediction, "FAILURE",
                            "entity_observed_outside_predicted_region", obs,
                            mismatch=True)
        elif obs.received_at >= prediction.deadline:
            self.finish(world, prediction, "UNOBSERVED",
                        "deadline_without_identity_observation", obs)

    def _evaluate_quest_marker(self, world, prediction, obs) -> None:
        quest_id = prediction.predicted_state.get("quest_id")
        marker_lists = [world.state.get("map_marker_observations", []),
                        world.state.get("visual_candidates", [])]
        matched = any(
            str(marker.get("quest_id")) == str(quest_id)
            for markers in marker_lists for marker in markers)
        if matched:
            self.finish(world, prediction, "SUCCESS",
                        "quest_marker_observed_for_quest", obs)
            return
        if obs.source in {"MINIMAP_CV", "WORLD_MAP_CV", "SPATIAL_MEMORY"}:
            coverage = prediction.predicted_state.setdefault(
                "coverage_observations", [])
            if obs.observation_id not in coverage:
                coverage.append(obs.observation_id)
        coverage = prediction.predicted_state.get("coverage_observations", [])
        if obs.received_at >= prediction.deadline and len(coverage) >= 3:
            self.finish(world, prediction, "FAILURE",
                        "quest_marker_absent_after_sufficient_surface_observation",
                        obs, mismatch=True)
        elif obs.received_at >= prediction.deadline + 5:
            self.finish(world, prediction, "UNOBSERVED",
                        "insufficient_map_surface_observation", obs)
