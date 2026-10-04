"""Bounded visual evidence for the current REACH destination; never input."""
from __future__ import annotations

import math


def finite(value):
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) else None)


class ArrivalEvidence:
    """BBox growth is weak evidence, associated through a fresh mouseover anchor.

    A single retained sample belongs to one GUID/track. Camera rotation and
    target-distance trends corroborate scale changes; missing inputs discard
    the baseline instead of bridging unobserved camera motion.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._reset_visual()
        self.quest_baseline = None
        self.ui_baseline = None
        self.minimap_previous = None
        self.map_baseline = None

    def _reset_visual(self):
        self.previous = None

    @staticmethod
    def _quest_row(state: dict, destination: dict):
        wanted_quest = str(destination.get("quest_id") or "")
        wanted_objective = str(destination.get("objective_id") or "")
        if not wanted_quest:
            return None
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, dict) or str(quest.get("quest_id") or "") != wanted_quest:
                continue
            objective_row = None
            if wanted_objective:
                local_id = wanted_objective.partition(":")[2] or wanted_objective
                for objective in quest.get("objectives") or ():
                    if not isinstance(objective, dict):
                        continue
                    oid = str(objective.get("objective_id") or "")
                    if oid in {wanted_objective, local_id}:
                        objective_row = (
                            finite(objective.get("current", objective.get("current_count"))),
                            finite(objective.get("required", objective.get("required_count"))),
                            objective.get("is_complete") is True,
                        )
                        break
            return (quest.get("is_complete") is True, objective_row)
        return None

    def _quest_area_evidence(self, destination: dict, state: dict) -> dict:
        current = self._quest_row(state, destination)
        if self.quest_baseline is None:
            self.quest_baseline = current
            return {}
        previous = self.quest_baseline
        self.quest_baseline = current
        if previous is None or current is None:
            return {}
        if current[0] and not previous[0]:
            return {"quest_area_state_change": True}
        old_objective, new_objective = previous[1], current[1]
        if old_objective is None or new_objective is None:
            return {}
        count_increased = (
            old_objective[0] is not None and new_objective[0] is not None
            and old_objective[1] == new_objective[1]
            and new_objective[0] > old_objective[0]
        )
        completed = new_objective[2] and not old_objective[2]
        return {"quest_area_state_change": True} if count_increased or completed else {}

    @staticmethod
    def _ui_state(state: dict) -> tuple[bool, bool, bool]:
        quest = state.get("quest_ui") or {}
        gossip = state.get("gossip_ui") or {}
        merchant = state.get("merchant_ui") or {}
        return (
            quest.get("open") is True or state.get("quest_ui_open") is True,
            gossip.get("open") is True or state.get("gossip_open") is True,
            merchant.get("open") is True or state.get("merchant_open") is True,
        )

    def _interaction_evidence(self, destination: dict, state: dict, now: float) -> dict:
        current_ui = self._ui_state(state)
        if self.ui_baseline is None:
            self.ui_baseline = current_ui
            return {}
        previous_ui = self.ui_baseline
        self.ui_baseline = current_ui
        guid = str(destination.get("target_guid") or "")
        target = state.get("target") or {}
        sample_at = finite(target.get("sample_time", state.get("target_sample_time")))
        if (not guid or str(target.get("guid") or "") != guid
                or sample_at is None or not 0 <= now-sample_at <= 1.5):
            return {}
        opened = any(current and not previous
                     for previous, current in zip(previous_ui, current_ui))
        return {"interaction_ready": True} if opened else {}

    def _minimap_evidence(self, destination: dict, state: dict, now: float) -> dict:
        """Weak convergence only for the exact marker bound to this intent."""
        marker_id = (destination.get("minimap_marker_id")
                     or destination.get("marker_id"))
        if not marker_id:
            self.minimap_previous = None
            return {}
        rows = [row for row in state.get("map_marker_observations", ())
                if row.get("surface") == "MINIMAP"
                and str(row.get("marker_id") or row.get("track_id")) == str(marker_id)]
        if len(rows) != 1:
            self.minimap_previous = None
            return {}
        row = rows[0]
        local = row.get("local_position") or {}
        distance = finite(local.get("distance"))
        observed_at = finite(row.get("observed_at", row.get("last_seen")))
        lifecycle = str(row.get("lifecycle") or row.get("track_state") or "").upper()
        if (distance is None or distance < 0 or observed_at is None
                or not 0 <= now-observed_at <= .75
                or lifecycle not in {"ACTIVE", "STABLE", "TRACKED"}):
            self.minimap_previous = None
            return {}
        sample = (str(marker_id), observed_at, distance)
        old = self.minimap_previous
        if old and old[:2] == sample[:2]:
            return {}
        self.minimap_previous = sample
        if (old and old[0] == sample[0] and 0 < observed_at-old[1] <= 1.
                and distance < old[2] * .95):
            return {"minimap_convergence": True}
        return {}

    def _map_transition_evidence(self, destination: dict, state: dict) -> dict:
        current = state.get("map_id")
        current_instance = ((state.get("player_world_position") or {}).get("instance_id")
                            or state.get("instance_id"))
        sample = (current, current_instance)
        if self.map_baseline is None:
            self.map_baseline = sample
            return {}
        previous = self.map_baseline
        self.map_baseline = sample
        expected_map = destination.get("expected_map_id")
        expected_instance = destination.get("expected_instance_id")
        explicitly_expected = expected_map is not None or expected_instance is not None
        reached_expected = (
            (expected_map is None or str(current) == str(expected_map))
            and (expected_instance is None or str(current_instance) == str(expected_instance)))
        changed = sample != previous
        return ({"map_transition": True}
                if explicitly_expected and changed and reached_expected else {})

    def observe(self, destination: dict, state: dict, now: float, distance: float) -> dict:
        evidence = self._quest_area_evidence(destination, state)
        evidence.update(self._interaction_evidence(destination, state, now))
        evidence.update(self._minimap_evidence(destination, state, now))
        evidence.update(self._map_transition_evidence(destination, state))
        guid = destination.get("target_guid")
        anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
        stamp = finite(anchor.get("sample_time"))
        track_id = anchor.get("track_id")
        camera = state.get("camera_state") or {}
        yaw = finite(camera.get("yaw_estimate"))
        if (not guid or not track_id or stamp is None or not 0 <= now-stamp <= .75
                or yaw is None or destination.get("route_waypoint_final") is False):
            self._reset_visual()
            return evidence
        matches = [t for t in state.get("visual_candidates", ())
                   if t.get("source") == "WORLD3D" and t.get("track_id") == track_id]
        if len(matches) != 1:
            self._reset_visual()
            return evidence
        track = matches[0]
        at = finite(track.get("observed_at", track.get("last_seen")))
        height = finite(track.get("bbox_height_fraction"))
        if (at is None or not 0 <= now-at <= .45 or height is None or not 0 < height <= 1
                or track.get("lifecycle", track.get("track_state")) not in {"ACTIVE", "STABLE"}):
            self._reset_visual()
            return evidence
        old = self.previous
        sample = (guid, track_id, at, height, yaw, distance)
        if old and old[:2] == sample[:2] and at == old[2]:
            return evidence
        self.previous = sample
        if (old and old[:2] == sample[:2] and 0 < at-old[2] <= .45
                and abs(yaw-old[4]) <= 2. and distance < old[5]
                and height >= old[3] * 1.03):
            evidence["bbox_growth"] = True
        return evidence
