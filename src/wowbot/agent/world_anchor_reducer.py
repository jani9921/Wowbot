"""Stateless projection of confirmed screen-space entity anchors.

The supplied ``WorldModel`` remains the only owner of anchor, evidence and
relation state. This reducer has no cache, planner, controller or input path.
"""
from __future__ import annotations

from .self_avatar import is_self_avatar_box

from copy import deepcopy
import math
import re
from typing import TYPE_CHECKING

from .models import Observation, number

if TYPE_CHECKING:
    from .world import WorldModel


class WorldAnchorReducer:
    def project_corpse_event(self, model: "WorldModel", event: dict,
                             state: dict, observation: Observation) -> None:
        payload = event.get("payload") or {}
        tooltip = str(payload.get("tooltip") or payload.get("tooltip_text") or "")
        explicit_dead = payload.get("is_dead") is True
        corpse_word = re.search(
            r"(?:^|\s|~)corpse(?:$|\s|~)", tooltip, re.IGNORECASE)
        if event.get("event_type") == "LOOT_RECEIVED":
            source_guid = str(payload.get("source_guid") or "")
            if (not source_guid and model.last_loot_source_guid
                    and 0 <= observation.received_at-model.last_loot_received_at <= 2.):
                source_guid = model.last_loot_source_guid
            if not source_guid and model.corpse_anchors:
                source_guid = max(
                    model.corpse_anchors,
                    key=lambda guid: model.corpse_anchors[guid]["observed_at"])
            if source_guid:
                model.last_loot_source_guid = source_guid
                model.last_loot_received_at = observation.received_at
            model.mark_corpse_looted(source_guid, observation.received_at)
            return
        if (event.get("event_type") != "MOUSEOVER_CHANGED"
                or not (explicit_dead or corpse_word)):
            return
        metadata = payload.get("tooltip_data") or {}
        guid = str(payload.get("guid") or metadata.get("guid")
                   or metadata.get("unit_guid") or "")
        ownership_confirmed = model.corpse_is_combat_correlated(
            guid, observation.received_at)
        explicitly_lootable = (payload.get("lootable") is True
                               or metadata.get("lootable") is True)
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        state_time = number(state.get("monotonic_time"))
        cursor_time = number(state.get("cursor_sample_time"))
        event_time = number(event.get("timestamp"))
        snapshot_time = number(state.get("timestamp"))
        cursor_fresh = (None not in (state_time, cursor_time)
                        and 0 <= state_time-cursor_time <= 1.5)
        event_fresh = (None not in (event_time, snapshot_time)
                       and 0 <= snapshot_time-event_time <= 2.)
        if (not guid.startswith(("Creature-", "Vehicle-"))
                or not (ownership_confirmed or explicitly_lootable)
                or model.corpse_was_recently_looted(guid, observation.received_at)
                or x is None or y is None
                or not 0.02 < x < 0.98 or not 0.02 < y < 0.98
                or not cursor_fresh or not event_fresh
                or (state.get("map_mouseover") or {}).get("surface")
                    in {"MINIMAP", "WORLD_MAP"}):
            return
        model.corpse_anchors[guid] = {
            "guid": guid,
            "name": payload.get("name") or tooltip.split(" ~ ", 1)[0] or None,
            "x": x, "y": y, "coordinate_space": "CLIENT_BOTTOM_LEFT",
            "source": "ADDON_CORPSE_TOOLTIP_EVENT", "belief": "CONFIRMED",
            "ownership_confirmed": True,
            "ownership_source": ("OWN_COMBAT" if ownership_confirmed
                                 else "CLIENT_LOOTABLE"),
            "event_sequence": event.get("sequence"),
            "observation_id": observation.observation_id,
            "observed_at": observation.received_at,
        }
        model.add_evidence(
            f"corpse:{guid}", {"dead": True, "guid": guid}, observation,
            confidence=1., ttl=20.)
        model.link(
            f"entity:{guid}", "has_state", "state:DEAD_CORPSE",
            observation, 1., "CONFIRMED")

    @staticmethod
    def track_mouseover_object(model: "WorldModel", state: dict,
                               observation: Observation) -> None:
        """Remember where the cursor rested when a mouseover change arrived.

        Live 2026-10-03 14:16: the Campfire's name arrived ~0.5-2 s late in a
        slow-lane MOUSEOVER_CHANGED event, after the FAST sample had already
        dropped its bare quest flag.  The cursor position (and how long it had
        been still) at ingestion lets ``effective_mouseover`` keep naming the
        object while the cursor stays put.
        """
        memory = model.__dict__.setdefault("mouseover_object_memory", {})
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        now = observation.received_at
        if x is not None and y is not None:
            last = memory.get("cursor")
            if last is None or abs(last[0]-x) > .004 or abs(last[1]-y) > .004:
                memory["cursor"] = (x, y)
                memory["cursor_moved_at"] = now
        changes = [event for event in state.get("events") or ()
                   if isinstance(event, dict) and event.get("event_type") == "MOUSEOVER_CHANGED"]
        if not changes:
            return
        latest = max(changes, key=lambda event: number(event.get("sequence")) or -1)
        sequence = number(latest.get("sequence"))
        if sequence is None or sequence <= float(memory.get("sequence") or -1):
            return
        memory.update(sequence=sequence, payload=dict(latest.get("payload") or {}),
                      ingested_at=now, event_cursor=memory.get("cursor"),
                      still_for=(now - float(memory.get("cursor_moved_at", now))))

    @staticmethod
    def _note_unique_kill_target(model: "WorldModel", unit: dict, guid: str, state: dict,
                                 at: float) -> None:
        """User 2026-10-04: for a "0/1 <Name> slain" objective, a hovered corpse
        of <Name> means someone else killed it -- wait there for the respawn.
        Seen alive again (or the objective done) clears the watch."""
        name = str(unit.get("name") or "").strip()
        if not name:
            return
        from .quest_semantics import target_matches_objective
        watch = model.__dict__.setdefault("respawn_watch", {})
        for objective in model.quest_model.ready():
            if objective.type != "KILL" or (objective.required_count or 0) != 1:
                continue
            if not target_matches_objective({"name": name},
                                            {**objective.raw, "description": objective.description}):
                continue
            if unit.get("is_dead", unit.get("dead")) is True:
                position = state.get("player_world_position") or {}
                watch[objective.objective_id] = {
                    "name": name, "guid": guid, "seen_dead_at": at,
                    "player_world_position": dict(position) if isinstance(position, dict) else None}
            else:
                watch.pop(objective.objective_id, None)

    def project_live_mouseover(self, model: "WorldModel", state: dict,
                               observation: Observation) -> None:
        self.track_mouseover_object(model, state, observation)
        unit = state.get("mouseover") or {}
        guid = str(unit.get("guid") or "")
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        state_time = number(state.get("monotonic_time"))
        cursor_time = number(state.get("cursor_sample_time", state_time))
        mouse_time = number(state.get("mouseover_sample_time", state_time))
        fresh = (None not in (state_time, cursor_time, mouse_time)
                 and 0 <= state_time-cursor_time <= 1.5
                 and 0 <= state_time-mouse_time <= 1.5
                 and abs(cursor_time-mouse_time) <= .05)
        map_surface = (state.get("map_mouseover") or {}).get("surface")
        if (not guid or unit.get("is_player") is True
                or guid == str(state.get("character_guid") or "")
                or x is None or y is None
                or not 0.02 < x < 0.98 or not 0.02 < y < 0.98
                or not fresh or map_surface in {"MINIMAP", "WORLD_MAP"}):
            return
        player_world = state.get("player_world_position") or {}
        player_map = state.get("position") or {}
        camera = state.get("camera_state") or model.state.get("camera_state") or {}
        anchor = {
            "guid": guid, "x": x, "y": y,
            "coordinate_space": "CLIENT_BOTTOM_LEFT",
            "source": "CONFIRMED_MOUSEOVER_ANCHOR",
            "identity_source": "ADDON_MOUSEOVER",
            "quest_related": unit.get("quest_related") is True,
            "quest_id": unit.get("quest_id"),
            "name": unit.get("name"),
            "dead": unit.get("is_dead", unit.get("dead")) is True,
            "sample_time": state_time, "observed_at": observation.received_at,
            "observation_id": observation.observation_id,
            "player_world_snapshot": deepcopy(player_world),
            "player_map_snapshot": deepcopy(player_map),
            "orientation_snapshot": number(state.get("orientation")),
            "camera_yaw_snapshot": number(camera.get("yaw_estimate")),
        }
        candidates = [
            item for item in model.state.get("visual_candidates", [])
            if item.get("source") == "WORLD3D"
            and not is_self_avatar_box(item)
            and "subject" in str(item.get("detector_kind") or item.get("kind") or "")
            and number(item.get("x")) is not None
            and number(item.get("y")) is not None
        ]
        if candidates:
            nearest = min(candidates, key=lambda item: math.hypot(
                float(item["x"])-x, float(item["y"])-y))
            distance = math.hypot(float(nearest["x"])-x, float(nearest["y"])-y)
            if distance <= .09:
                anchor.update({
                    "track_id": nearest.get("track_id"),
                    "bbox": deepcopy(nearest.get("bbox")),
                    "bbox_height_fraction": nearest.get("bbox_height_fraction"),
                    "track_confidence": nearest.get("confidence"),
                    "track_association": "CANDIDATE",
                    "association_distance": round(distance, 6),
                    "visual_signature": deepcopy(nearest.get("visual_signature")),
                })
                if nearest.get("track_id"):
                    confidence = min(.95, max(.55, 1.-distance/.09))
                    model.link(
                        f"track:{nearest['track_id']}", "MOUSEOVER_OF",
                        f"entity:{guid}", observation, confidence, "SUPPORTED")
                    model.link(
                        f"entity:{guid}", "TRACK_OF",
                        f"track:{nearest['track_id']}", observation,
                        confidence, "SUPPORTED")
        model.mouseover_screen_anchors[guid] = anchor
        from .tooltip_quest import (creature_tooltip_open, tooltip_objectives_done,
                                    tooltip_open_objectives)
        creature = (unit.get("attackable", unit.get("is_attackable")) is True
                    or unit.get("npc_id") is not None
                    or str(guid).startswith(("Creature-", "Vehicle-")))
        quest_id = (unit.get("quest_id")
                    if not tooltip_objectives_done(unit)
                    and (not creature or creature_tooltip_open(unit, model.state)) else None)
        source = "ADDON_MOUSEOVER_TOOLTIP"
        if not (unit.get("quest_related") is True and quest_id is not None):
            # The addon flag arrives empty at times while the tooltip text
            # names the quest (live 2026-10-03); same title rule in Python.
            from .tooltip_quest import tooltip_quest_id
            quest_id = (tooltip_quest_id(unit, model.state)
                        if unit.get("attackable", unit.get("is_attackable")) is True else None)
            source = "MOUSEOVER_TOOLTIP_TITLE"
        # Free visual label for the hovered box (visual_prototypes): this
        # quest's target look, or a rejected look (corpse / unrelated unit).
        from .visual_prototypes import memory_for, open_quest_ids
        memory_for(model).observe_hover(
            model.state, guid=guid, unit=unit, track_id=anchor.get("track_id"), quest_id=quest_id,
            open_quest_ids=open_quest_ids(model.state), at=observation.received_at)
        if quest_id is not None:
            model.mouseover_entity_semantics[guid] = {
                "guid": guid, "name": unit.get("name"),
                "npc_id": unit.get("npc_id"), "quest_related": True,
                "quest_id": quest_id, "source": source,
                "observed_at": observation.received_at,
                "observation_id": observation.observation_id,
            }
        elif tooltip_objectives_done(unit) and unit.get("npc_id") is not None:
            # Done for this creature type: forget it (and its GUID judgements).
            (model.__dict__.get("quest_relevant_npcs") or {}).pop(str(unit["npc_id"]), None)
            model.mouseover_entity_semantics.pop(guid, None)
        if quest_id is not None:
            if unit.get("npc_id") is not None and tooltip_open_objectives(unit):
                # The quest line is in every unit of that creature type's
                # tooltip: other porcupines (and one selected before the
                # hover memory) are relevant while the quest is open.
                from .tooltip_quest import tooltip_open_objectives
                model.__dict__.setdefault("quest_relevant_npcs", {})[str(unit["npc_id"])] = {
                    "quest_id": quest_id, "observed_at": observation.received_at,
                    "objectives": tooltip_open_objectives(unit)}
        self._note_unique_kill_target(model, unit, guid, state, observation.received_at)
        if (unit.get("is_dead", unit.get("dead")) is True
                and guid.startswith(("Creature-", "Vehicle-"))
                and (model.corpse_is_combat_correlated(guid, observation.received_at)
                     or unit.get("lootable") is True)
                and not model.corpse_was_recently_looted(
                    guid, observation.received_at)):
            model.corpse_anchors[guid] = {
                "guid": guid, "name": unit.get("name"), "x": x, "y": y,
                "coordinate_space": "CLIENT_BOTTOM_LEFT",
                "source": "ADDON_DEAD_MOUSEOVER", "belief": "CONFIRMED",
                "ownership_confirmed": True,
                "ownership_source": (
                    "OWN_COMBAT" if model.corpse_is_combat_correlated(
                        guid, observation.received_at) else "CLIENT_LOOTABLE"),
                "observation_id": observation.observation_id,
                "observed_at": observation.received_at,
            }
            model.add_evidence(
                f"corpse:{guid}", {"dead": True, "guid": guid}, observation,
                confidence=1., ttl=20.)
