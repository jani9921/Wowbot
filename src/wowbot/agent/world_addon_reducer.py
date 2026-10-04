"""Canonical reducer for decoded FAST and full addon state.

The reducer has no independent store.  It mutates only the supplied
``WorldModel`` and delegates event/entity/UI projections back to the model's
single composed reducers.  This is a responsibility extraction, not a second
world writer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import EventRecord, Observation, json_copy as deepcopy

if TYPE_CHECKING:
    from .world import WorldModel


class WorldAddonReducer:
    FAST_KEYS = frozenset({
        "timestamp", "monotonic_time", "map_id", "map_context", "position",
        "player_world_position", "orientation", "health", "max_health",
        "is_dead", "is_ghost", "is_in_combat", "is_mounted", "is_casting",
        "in_vehicle", "has_vehicle_ui", "on_taxi",
        "movement", "player_present", "ui_error", "ui_error_at", "ui_error_sequence",
        "ui_error_code", "input_blocked", "loading",
        "target", "current_target", "target_is_attackable", "target_is_dead",
        "target_sample_time", "mouseover", "mouseover_sample_time",
        "soft_targets",
        "cursor_position", "cursor_sample_time", "map_mouseover",
        "map_mouseover_sample_time", "state_age", "state_sequence",
        "state_sample_time", "state_encoding", "transport_session",
        "transport_kind", "telemetry_lane", "fast_sequence", "fast_received_at",
        "protocol_version", "telemetry_source", "session_id", "frame_id",
        "quest_digest", "accepted_quest_ids", "quest_state_revision",
        "quest_ui_open", "quest_ui_action", "quest_ui_x", "quest_ui_y",
        "quest_ui_quest_id", "extra_action", "bags_open", "world_map_open",
        "actionbar_fast", "combat_last_spell_id", "combat_last_cast_at",
    })

    def apply(self, model: "WorldModel", observation: Observation, previous: dict,
              *, defer_rebuild: bool = False) -> bool:
        model.latest = observation
        state = observation.payload
        if state.get("transport_kind") == "FAST":
            return self._apply_fast(model, state, observation,
                                    defer_rebuild=defer_rebuild)
        return self._apply_full(model, previous, state, observation)

    SCRIPTED_DISMOUNT_SECONDS = 30.

    @staticmethod
    def _note_quest_stage_completions(model: "WorldModel", quests, at: float) -> None:
        """Remember when an objective of each quest last turned complete."""
        counts = model.__dict__.setdefault("_quest_completed_counts", {})
        stamps = model.__dict__.setdefault("quest_stage_completed_at", {})
        for quest in quests or ():
            if not isinstance(quest, dict) or quest.get("quest_id") is None:
                continue
            qid = str(quest["quest_id"])
            done = sum(1 for objective in quest.get("objectives") or ()
                       if isinstance(objective, dict) and objective.get("is_complete") is True)
            if qid in counts and done > counts[qid]:
                stamps[qid] = at
                riding = model.__dict__.get("_last_in_vehicle") is True
                model.__dict__.setdefault("quest_stage_completed_in_vehicle", {})[qid] = riding
            counts[qid] = done

    def _note_vehicle_transition(self, model: "WorldModel", in_vehicle, at: float) -> None:
        """User 2026-10-04: a quest script may take the player off its vehicle
        when a stage is done (Giant Boar: 8/8 cadavers -> "Torgok slain" on
        foot); a logout/death dismount must be ridden again instead.  An exit
        within 30 s after one of the quest's objectives completed is scripted:
        that quest's ride objective is not reopened."""
        previous = model.__dict__.get("_last_in_vehicle")
        model.__dict__["_last_in_vehicle"] = in_vehicle
        scripted = model.__dict__.setdefault("scripted_dismount_quests", {})
        if in_vehicle is True:
            scripted.clear()
            return
        if previous is True and in_vehicle is False:
            for qid, completed_at in (model.__dict__.get("quest_stage_completed_at") or {}).items():
                if 0 <= at-completed_at <= self.SCRIPTED_DISMOUNT_SECONDS:
                    scripted[qid] = at

    def _apply_fast(self, model: "WorldModel", state: dict, observation: Observation,
                    *, defer_rebuild: bool) -> bool:
        fast_delta = deepcopy({key: value for key, value in state.items()
                               if key in self.FAST_KEYS})
        # FAST owns current dialog visibility. The bulky full snapshot can be
        # several seconds older and its nested quest_ui object otherwise stays
        # truthy even after FAST explicitly reports the frame closed. Keep the
        # nested canonical view coherent with the flattened control-lane facts.
        if "quest_ui_open" in fast_delta:
            quest_ui = deepcopy(model.addon_state.get("quest_ui") or {})
            if fast_delta.get("quest_ui_open") is not True:
                quest_ui.update({
                    "open": False, "action": "", "x": 0, "y": 0,
                    "quest_id": 0, "entries": [], "reward_choices": [],
                    "reward_selected_index": 0,
                })
            else:
                quest_ui["open"] = True
                for suffix in ("action", "x", "y", "quest_id"):
                    value = fast_delta.get(f"quest_ui_{suffix}")
                    if value is not None:
                        quest_ui[suffix] = value
            fast_delta["quest_ui"] = quest_ui
        # FAST can omit bulky identity fields. Merge only when the exact GUID
        # matches; a different GUID never inherits prior facts.
        for unit_key in ("target", "mouseover"):
            incoming = fast_delta.get(unit_key)
            existing = model.addon_state.get(unit_key)
            if (isinstance(incoming, dict) and isinstance(existing, dict)
                    and incoming.get("guid")
                    and incoming.get("guid") == existing.get("guid")):
                merged = deepcopy(existing)
                merged.update({key: value for key, value in incoming.items()
                               if value is not None})
                fast_delta[unit_key] = merged
        model.addon_state.update(fast_delta)
        vehicle = (model.addon_state.get("in_vehicle"), model.addon_state.get("on_taxi"))
        if (("in_vehicle" in fast_delta or "on_taxi" in fast_delta)
                and model.__dict__.get("_quest_ingest_vehicle") not in (None, vehicle)):
            # Mounting/dismounting re-opens or closes a ride objective now,
            # not at the next multi-page snapshot (quest_model.remount_quests).
            from .quest_model import remount_quests
            self._note_vehicle_transition(model, vehicle[0], observation.received_at)
            source = [quest for quest in model.addon_state.get("active_quests") or ()]
            model.quest_model.ingest(remount_quests(
                source, in_vehicle=vehicle[0], on_taxi=vehicle[1],
                skip_quest_ids=model.__dict__.get("scripted_dismount_quests") or ()),
                observation.observation_id, observation.received_at)
            model.__dict__["_quest_ingest_vehicle"] = vehicle
        if state.get("events"):
            # Live 2026-10-03 14:16: the merged control payload carried the
            # Campfire MOUSEOVER_CHANGED event 20 s before the next full
            # snapshot was ingested.  Only the object-name memory reads it.
            model._anchor_reducer.track_mouseover_object(
                model, {"events": state["events"],
                        "cursor_position": model.addon_state.get("cursor_position")},
                observation)
        if defer_rebuild:
            # FAST ground truth can update the existing query projection in
            # place.  If this batch also contains supplemental perception,
            # that reducer marks the model dirty and flush_pending() performs
            # the ordinary full atomic rebuild afterwards.
            model._state_projector.refresh_fast(model, fast_delta)
        else:
            model._rebuild_state()
        model.last_received = observation.received_at
        model.history.append(observation)
        model._project_live_mouseover_anchor(model.addon_state, observation)
        if defer_rebuild and not model._state_dirty:
            # Publish any new exact mouseover anchor in this same FAST tick.
            model._state_projector.refresh_fast(model, {})
        evidence_keys = ("position", "player_world_position", "orientation", "movement",
                         "target", "mouseover", "soft_targets", "map_mouseover", "map_context")
        for key in evidence_keys:
            if key in state:
                model.add_evidence(key, state.get(key), observation, ttl=1.)
        model._update_belief_lifecycle(observation, evidence_keys)
        if defer_rebuild:
            model._deferred_prediction_obs.append(observation)
        else:
            model._evaluate_world_predictions(observation)
        # Preserve the existing FAST return/revision contract. Receive
        # freshness is updated above even when the payload content is stable.
        return True

    def _apply_full(self, model: "WorldModel", previous: dict, state: dict,
                    observation: Observation) -> bool:
        # Nameplates are sampled only in the paged/full lane.  Stamp every
        # row at ingestion so a later FAST target update can use an exact-GUID
        # plate briefly without pretending that the old screen pixel is new.
        sampled_at = state.get("monotonic_time")
        for plate in state.get("nameplates") or ():
            if isinstance(plate, dict) and plate.get("sample_time") is None:
                plate["sample_time"] = sampled_at
        model.addon_state = deepcopy(state)
        model._rebuild_state()
        model.last_received = observation.received_at
        model.history.append(observation)
        model._project_live_mouseover_anchor(state, observation)
        # Addon 0.9.51 exports one quest's own text per snapshot (dialog /
        # quest-log description); keep them for the quest records and the
        # local-LLM objective interpreter (semantic_advisor).
        quest_text = state.get("quest_text")
        texts = model.__dict__.setdefault("quest_texts", {})
        if isinstance(quest_text, dict) and quest_text.get("quest_id") is not None:
            texts[str(quest_text["quest_id"])] = {
                key: quest_text.get(key) for key in
                ("description", "objectives_text", "progress_text", "completion_text",
                 "giver_name", "giver_guid", "ender_name")
                if quest_text.get(key)}
        # Who each quest is turned in to (quest_turn_in): text pattern or the
        # recorded giver; semantic_advisor may add an LLM reading later.
        from .quest_turn_in import turn_in_from_text
        turn_in = model.__dict__.setdefault("quest_turn_in", {})
        for quest in state.get("active_quests", []):
            if not isinstance(quest, dict) or quest.get("quest_id") is None:
                continue
            found = turn_in_from_text(quest, texts.get(str(quest["quest_id"])))
            current = turn_in.get(str(quest["quest_id"])) or {}
            if found and not str(current.get("source") or "").startswith("QUEST_TEXT_PATTERN"):
                turn_in[str(quest["quest_id"])] = found
        quests = [
            {**quest, "description": texts[str(quest.get("quest_id"))].get("description")}
            if isinstance(quest, dict) and not quest.get("description")
            and (texts.get(str(quest.get("quest_id"))) or {}).get("description") else quest
            for quest in state.get("active_quests", [])]
        from .quest_model import remount_quests
        self._note_quest_stage_completions(model, state.get("active_quests", []), observation.received_at)
        self._note_vehicle_transition(model, state.get("in_vehicle"), observation.received_at)
        quests = remount_quests(quests, in_vehicle=state.get("in_vehicle"), on_taxi=state.get("on_taxi"),
                                skip_quest_ids=model.__dict__.get("scripted_dismount_quests") or ())
        model.__dict__["_quest_ingest_source"] = quests
        model.__dict__["_quest_ingest_vehicle"] = (state.get("in_vehicle"), state.get("on_taxi"))
        model.quest_model.ingest(quests, observation.observation_id, observation.received_at)
        model.quest_model.resolve_hypotheses(
            model.entity_memory, as_of=observation.received_at, max_age=30 * 86400)
        for quest in state.get("active_quests", []):
            if quest.get("quest_id") is not None:
                model.link(
                    f"quest:{quest['quest_id']}", "observed_by",
                    f"observation:{observation.observation_id}", observation)
        evidence_keys = ("position", "target", "mouseover", "soft_targets", "active_quests",
                         "inventory", "map_mouseover", "map_context")
        for key in evidence_keys:
            model.add_evidence(
                key, state.get(key), observation,
                ttl=3. if key in {"target", "mouseover"} else 8.)
        model._update_belief_lifecycle(observation, evidence_keys)
        model._evaluate_world_predictions(observation)
        model._event_reducer.apply(model, state, observation)
        # Newly ingested corpse events must be visible in the same tick.
        model._rebuild_state()
        model._entity_reducer.apply(model, state, observation)
        if previous and model.quest_signature(previous) != model.quest_signature(state):
            event = {
                "event_type": "QUEST_STATE_CHANGED", "timestamp": observation.timestamp,
                "source": "WORLD_MODEL",
                "payload": {"observation_id": observation.observation_id},
            }
            model.events.append(event)
            model.event_records.append(EventRecord.create(event, observation))
        model._ui_reducer.apply(model, previous, state, observation)
        return model._accepted(observation)
