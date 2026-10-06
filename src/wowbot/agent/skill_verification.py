"""SkillRegistry.verify(): the postcondition check of a running skill attempt.

Split out of skills.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
import re
from .models import Outcome, number
from .world import WorldModel
from .skill_contracts import _world_map_open

INSPECT_EMPTY_HOVER_SECONDS = .4


class SkillVerificationMixin:
    """Methods of SkillRegistry (skills.py); moved verbatim."""

    def verify(self, attempt, world: WorldModel, now: float) -> tuple[Outcome, str]:
        # See commands(): SkillRegistry is intentionally no longer a second
        # authority for quest-dialog semantics.  The engine has a canonical
        # typed path through QuestDialogSkill.
        if attempt.proposal.skill in {"QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "OBJECT_USE", "USE", "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION"}:
            return Outcome.FAILURE, "canonical_quest_dialog_skill_required"
        if not world.latest or world.latest.observation_id == attempt.observation_id:
            # observation_id is content-addressed. A fresh re-read of identical
            # pixels deliberately keeps the same ID, but WorldModel advances
            # last_received because it still proves the capture/decode pipe is
            # alive. Do not mislabel an unchanged game state as a telemetry
            # outage; at the deadline it is simply missing the expected change.
            repeated_after_action = (world.latest is not None
                                     and world.last_received > attempt.started_at
                                     and world.fresh(now))
            if now >= attempt.deadline:
                return (Outcome.FAILURE,
                        "expected_observation_missing" if repeated_after_action
                        else "telemetry_stalled")
            return (Outcome.PENDING, "awaiting_new_observation")
        before, after, name = attempt.baseline, world.state, attempt.proposal.skill
        old_target, target = before.get("target") or {}, after.get("target") or {}
        events = [e for e in after.get("events", []) if (number(e.get("sequence")) or 0) > (number(before.get("event_sequence")) or 0)]
        event_names = {e.get("event_type") for e in events}
        quest_changed = world.quest_signature(before) != world.quest_signature(after)
        def counts(inventory):
            result = {}
            for item in (inventory or {}).get("items", []):
                key, count = item.get("item_id"), number(item.get("count"))
                if key is not None and count is not None:
                    result[key] = result.get(key, 0) + count
            return result
        old_items, new_items = counts(before.get("inventory")), counts(after.get("inventory"))
        inventory_changed = any(count > old_items.get(key, 0) for key, count in new_items.items())
        def objective_progress(quest_ids=None):
            quest_ids = set(quest_ids or [])
            old = {(q.get("quest_id"), i): number(o.get("current"))
                   for q in before.get("active_quests", []) for i, o in enumerate(q.get("objectives", []))
                   if not quest_ids or q.get("quest_id") in quest_ids}
            return [(q.get("quest_id"), i) for q in after.get("active_quests", [])
                    for i, o in enumerate(q.get("objectives", []))
                    if (not quest_ids or q.get("quest_id") in quest_ids)
                    and number(o.get("current")) is not None
                    and number(o.get("current")) > (old.get((q.get("quest_id"), i)) or 0)]
        def digest_progress(quest_ids=None):
            # active_quests (objective_progress above) only refreshes on the
            # slow full/paged snapshot; quest_digest carries the same per-quest
            # "done" count on the FAST lane (already in world.py fast_keys), so
            # quest-linked loot/gather/use progress is visible in well under a
            # second instead of waiting out verify()'s timeout for the next
            # slow page.
            quest_ids = set(quest_ids or [])
            old = {d.get("id"): number(d.get("done")) for d in before.get("quest_digest") or []}
            return [d.get("id") for d in after.get("quest_digest") or []
                    if (not quest_ids or d.get("id") in quest_ids)
                    and number(d.get("done")) is not None
                    and number(d.get("done")) > (old.get(d.get("id")) or 0)]
        success = False
        if name == "WAIT":
            success = True
        elif name in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            if name == "REACQUIRE_TARGET":
                guid = attempt.proposal.parameters.get("guid")
                target = after.get("target") or {}
                tracks = after.get("visual_candidates") or []
                reacquired = (target.get("guid") == guid and any(
                    item.get("track_state") in {"ACTIVE", "STABLE", "REACQUIRE_CANDIDATE"}
                    and (item.get("associated_entity_guid") == guid
                         or any(candidate.get("guid") == guid or candidate.get("identity_key") == guid
                                for candidate in item.get("entity_candidates") or []))
                    for item in tracks))
                if reacquired:
                    return Outcome.SUCCESS, "committed_target_visually_reacquired"
            previous = before.get("camera_state") or {}
            current = after.get("camera_state") or {}
            motion = current.get("camera_motion_px") or {}
            old_motion = previous.get("camera_motion_px") or {}
            changed = (number(motion.get("dx")), number(motion.get("dy"))) != (
                number(old_motion.get("dx")), number(old_motion.get("dy")))
            before_orientation = number(before.get("orientation"))
            after_orientation = number(after.get("orientation"))
            orientation_changed = bool(
                before_orientation is not None and after_orientation is not None
                and abs(math.atan2(math.sin(after_orientation-before_orientation),
                                   math.cos(after_orientation-before_orientation))) >= .01)
            camera_changed = bool(
                changed and (abs(number(motion.get("dx")) or 0)
                             + abs(number(motion.get("dy")) or 0) >= 1)
                and (number(motion.get("confidence")) or 0) >= .08)
            success = name == "CAMERA_CONTROL" and (orientation_changed or camera_changed)
        elif name == "INSPECT":
            if attempt.proposal.parameters.get("camera_pan"):
                if now - attempt.started_at >= .4:
                    return Outcome.CANCELLED, "view_turn_sent_reobserve"
                return Outcome.PENDING, "awaiting_post_view_rotation_observation"
            if attempt.proposal.parameters.get("map_zoom_in"):
                if not after.get("world_map_open"):
                    return Outcome.CANCELLED, "world_map_closed"
                if now - attempt.started_at >= .4:
                    return Outcome.CANCELLED, "map_zoom_sent_reobserve_fresh_markers"
                return Outcome.PENDING, "awaiting_post_zoom_observation"
            if attempt.proposal.parameters.get("map_step_out"):
                if not after.get("world_map_open"):
                    return Outcome.CANCELLED, "world_map_closed"
                expected = number(attempt.proposal.parameters.get("expected_parent_map_id"))
                active = number((after.get("map_context") or {}).get("active_map_id"))
                if expected is not None and active == expected:
                    return Outcome.SUCCESS, "parent_map_context_observed"
                if now - attempt.started_at >= .75:
                    return Outcome.FAILURE, "parent_map_context_not_observed"
                return Outcome.PENDING, "awaiting_parent_map_context"
            mouse, old_mouse = after.get("mouseover") or {}, before.get("mouseover") or {}
            map_mouse, old_map = after.get("map_mouseover") or {}, before.get("map_mouseover") or {}
            identity = bool(mouse.get("guid")) and mouse.get("guid") != old_mouse.get("guid")
            world_tooltip = bool(mouse.get("tooltip_text") or mouse.get("tooltip")) and (
                mouse.get("tooltip_text") or mouse.get("tooltip"), mouse.get("tooltip_data")) != (
                old_mouse.get("tooltip_text") or old_mouse.get("tooltip"), old_mouse.get("tooltip_data"))
            tooltip = bool(map_mouse.get("tooltip")) and (map_mouse.get("tooltip"), map_mouse.get("quest_id")) != (old_map.get("tooltip"), old_map.get("quest_id"))
            cursor = after.get("cursor_position") or {}
            x, y = number(cursor.get("nx")), number(cursor.get("ny"))
            params = attempt.proposal.parameters
            # The hover may lead a moving box (track_motion): probe the sent point.
            probe_x, probe_y = next(((command.x, command.y) for command in getattr(attempt, "commands", None) or ()
                                     if getattr(command, "kind", None) == "HOVER"
                                     and command.x is not None and command.y is not None),
                                    (params["x"], params["y"]))
            at_probe = x is not None and y is not None and math.hypot(x-probe_x, y-probe_y) <= .015
            # A fresh mouseover GUID is addon-confirmed identity and needs no cursor
            # corroboration (cursor_position is null whenever WoW is in mouse-look
            # camera mode). Tooltip-text diffs are weaker heuristics and keep
            # requiring at_probe when cursor telemetry is available.
            success = identity or (at_probe and (world_tooltip or tooltip))
            sample = number(after.get("mouseover_sample_time"))
            if (not success and at_probe and not mouse.get("guid")
                    and not (mouse.get("tooltip_text") or mouse.get("tooltip"))
                    and not map_mouse.get("tooltip")
                    and sample is not None and sample >= attempt.started_at + INSPECT_EMPTY_HOVER_SECONDS):
                # The pointer is on the probe and a sample taken well after
                # the hover names nothing: answer now instead of waiting out
                # the 5 s contract (live 2026-10-05: 49 empty INSPECTs, 5.6 s
                # each).  WoW names a unit under the pointer the next frame.
                return Outcome.FAILURE, "expected_observation_missing"
        elif name == "TARGET":
            guid = attempt.proposal.parameters.get("guid")
            expected_name = str(attempt.proposal.parameters.get("expected_name") or "").casefold().strip()
            selected_name = str(target.get("name") or "").casefold().strip()
            success = (target.get("guid") == guid if guid else
                       bool(target) and target != old_target
                       and bool(target.get("guid"))
                       and (not expected_name or selected_name == expected_name))
        elif name == "ACQUIRE_TARGET":
            success = target.get("attackable", target.get("is_attackable")) is True
        elif name == "APPROACH_TARGET":
            if old_target.get("guid") != target.get("guid"):
                return Outcome.CANCELLED, "target_identity_changed"
            success = any(a.get("is_harmful") is True and a.get("in_range") is True
                          for a in after.get("actionbar", []))
        elif name in {"INTERACT", "TALK"}:
            old_ui, ui = before.get("quest_ui") or {}, after.get("quest_ui") or {}
            # Paged/compact telemetry may add an explicit closed UI object to
            # a baseline where the field was absent. That is not interaction
            # success. Only an actually opened quest/gossip surface or quest
            # state transition verifies INTERACT/TALK.
            ui_opened = (ui.get("open") is True and
                         (old_ui.get("open") is not True or
                          (ui.get("action"), ui.get("quest_id")) !=
                          (old_ui.get("action"), old_ui.get("quest_id"))))
            # quest_ui itself only refreshes on the slow full/paged snapshot
            # (world.py fast_keys deliberately excludes it, like active_quests).
            # quest_ui_open/quest_ui_action/quest_ui_quest_id carry the same
            # fact on the FAST lane, so a visibly-opened dialog is not missed
            # while INTERACT/TALK waits out its timeout for the next slow page.
            fast_ui_opened = (after.get("quest_ui_open") is True and
                               (before.get("quest_ui_open") is not True or
                                (after.get("quest_ui_action"), after.get("quest_ui_quest_id")) !=
                                (before.get("quest_ui_action"), before.get("quest_ui_quest_id"))))
            # A vendor NPC answers with its shop (quest BUY/SELL objectives).
            vendor_opened = ((after.get("vendor_ui") or {}).get("open") is True
                             and (before.get("vendor_ui") or {}).get("open") is not True)
            success = quest_changed or ui_opened or fast_ui_opened or vendor_opened
        elif name == "LOOT":
            params = attempt.proposal.parameters
            progress = objective_progress(params.get("quest_ids"))
            loot_event = any(e.get("event_type") == "LOOT_RECEIVED" and
                (not (e.get("payload") or {}).get("source_guid") or
                 (e.get("payload") or {}).get("source_guid") == params.get("guid")) for e in events)
            changed_to_other = bool(target.get("guid")) and target.get("guid") != old_target.get("guid")
            if changed_to_other and not loot_event:
                return Outcome.CANCELLED, "target_identity_changed"
            success = inventory_changed or bool(progress) or loot_event or bool(digest_progress(params.get("quest_ids")))
        elif name in {"GATHER", "HERB", "MINE", "USE"}:
            params = attempt.proposal.parameters
            matching_resource_event = any(e.get("event_type") in {"RESOURCE_GATHERED", "ITEM_RECEIVED"}
                and (not params.get("node_id") or (e.get("payload") or {}).get("node_id") == params.get("node_id")) for e in events)
            matching_use_event = any(e.get("event_type") == "OBJECT_USED" and
                (not params.get("object_id") or str((e.get("payload") or {}).get("object_id")) == str(params.get("object_id")))
                and (not params.get("item_id") or str((e.get("payload") or {}).get("item_id")) == str(params.get("item_id"))) for e in events)
            success = (inventory_changed or bool(objective_progress(params.get("quest_ids")))
                       or matching_resource_event or matching_use_event
                       or bool(digest_progress(params.get("quest_ids"))))
        elif name == "FISH":
            binding = attempt.proposal.parameters.get("binding")
            action = next((item for item in before.get("actionbar", []) if item.get("action") == binding), None)
            spell_id = action.get("id", action.get("spell_id")) if action else None
            matched_cast = any(event.get("event_type") == "SPELLCAST_SUCCEEDED"
                               and spell_id is not None
                               and (event.get("payload") or {}).get("spell_id") == spell_id for event in events)
            # "fishing" is never assigned anywhere (not the addon, not any
            # Python adapter) -- the spellcast event is the only real signal.
            success = matched_cast
        elif name == "EXIT_VEHICLE":
            success = after.get("in_vehicle") is False
        elif name == "VEHICLE_ABILITY":
            # Live 2026-10-04: a vehicle ability is cast by the vehicle; the
            # addon's "player" UNIT_SPELLCAST_FAILED (Cast-2-0-0-0-...) came
            # while the boar did lunge ~30 yd.  So success is any of: a cast
            # event (any unit, addon 0.9.50), the cooldown, objective progress
            # or the observed forward lunge -- and the observed effect is
            # learned per spell (see vehicle_abilities).
            from .vehicle_abilities import DASH_MIN_YARDS, forward_displacement, learn_effect
            params = attempt.proposal.parameters
            spell_id = params.get("spell_id")
            cast = any(event.get("event_type") == "SPELLCAST_SUCCEEDED" and spell_id is not None
                       and (event.get("payload") or {}).get("spell_id") == spell_id for event in events)
            after_action = next((item for item in after.get("actionbar") or ()
                                 if isinstance(item, dict) and item.get("action") == params.get("binding")), {})
            cooldown_started = (number(after_action.get("cooldown_remaining")) or 0.) > .1
            progressed = (bool(objective_progress(params.get("quest_ids")))
                          or bool(digest_progress(params.get("quest_ids"))))
            moved = forward_displacement(before, after)
            lunged = bool(moved and moved[0] >= DASH_MIN_YARDS and moved[0] >= .7*moved[1])
            settled = now-attempt.started_at >= .9 or now >= attempt.deadline
            success = progressed or lunged or ((cast or cooldown_started) and settled)
            if success:
                learn_effect(world.__dict__.setdefault("vehicle_ability_effects", {}),
                             spell_id, before, after, hit=progressed)
        elif name == "MOUNT":
            success = after.get("is_mounted") is True
        elif name == "DISMOUNT":
            success = before.get("is_mounted") is True and after.get("is_mounted") is False
        elif name == "REPAIR":
            old_cost = number((before.get("vendor_ui") or {}).get("repair_all_cost"))
            new_cost = number((after.get("vendor_ui") or {}).get("repair_all_cost"))
            success = new_cost is not None and (new_cost == 0 or
                      (old_cost is not None and new_cost < old_cost))
        elif name == "OPEN_BAGS":
            success = after.get("bags_open") is True
        elif name in {"BUY_VENDOR", "SELL_VENDOR"}:
            params = attempt.proposal.parameters
            progress = bool(objective_progress(params.get("quest_ids"))) or bool(digest_progress(params.get("quest_ids")))
            item_id = params.get("item_id")
            def item_count(snapshot):
                return sum((number(item.get("count")) or 0)
                           for item in (snapshot.get("inventory") or {}).get("items", [])
                           if str(item.get("item_id")) == str(item_id))
            old_count, new_count = item_count(before), item_count(after)
            old_money, new_money = number(before.get("money")), number(after.get("money"))
            if name == "BUY_VENDOR":
                success = progress or new_count > old_count or (
                    old_money is not None and new_money is not None and new_money < old_money)
            else:
                success = progress or new_count < old_count or (
                    old_money is not None and new_money is not None and new_money > old_money)
        elif name == "CLOSE_MAP":
            success = _world_map_open(after) is False
        elif name == "OPEN_MAP":
            success = _world_map_open(after) is True
        elif name in {"COMBAT", "DEFEND"}:
            old_hp, hp = number(old_target.get("health")), number(target.get("health"))
            same = old_target.get("guid") == target.get("guid") and old_target.get("guid") is not None
            issued_bindings = {command.binding for command in attempt.commands}
            cast = next((item for item in before.get("actionbar", [])
                         if item.get("action") in issued_bindings), None)
            cast_verified = any(e.get("event_type") == "SPELLCAST_SUCCEEDED" and cast and (e.get("payload") or {}).get("spell_id") == cast.get("id") for e in events)
            # PREPARED 2026-09-14, UNTESTED LIVE -- requires the matching
            # addon change (combat_hint) to be installed/reloaded; until
            # then combat_last_spell_id/combat_last_cast_at are simply
            # always None and this is a no-op, same as before. Mirrors the
            # fast/slow fallback already used for `action` a few lines above
            # for quest_ui: cast_verified above depends on the slow/paged
            # `events` list, which this session measured arriving several
            # seconds late; this fast-lane pair lets a landed cast confirm
            # in well under a second once the addon side is live-validated
            # (see docs/LIVE_VALIDATION.md).
            fast_cast_verified = (cast is not None
                and number(after.get("combat_last_spell_id")) == number(cast.get("id"))
                and (number(after.get("combat_last_cast_at")) or -1)
                    > (number(before.get("combat_last_cast_at")) or -1))
            combat_progress = bool(objective_progress(attempt.proposal.parameters.get("quest_ids")))
            corpse_confirmed = any(e.get("event_type") == "MOUSEOVER_CHANGED"
                and str(((e.get("payload") or {}).get("guid")
                         or ((e.get("payload") or {}).get("tooltip_data") or {}).get("guid")
                         or ((e.get("payload") or {}).get("tooltip_data") or {}).get("unit_guid") or ""))
                    == str(old_target.get("guid") or "")
                and ((e.get("payload") or {}).get("is_dead") is True
                     or re.search(r"(?:^|\s|~)corpse(?:$|\s|~)",
                                  str((e.get("payload") or {}).get("tooltip") or ""), re.IGNORECASE))
                for e in events)
            turned = False
            if issued_bindings <= {"TURNLEFT", "TURNRIGHT"} and issued_bindings:
                old_facing, facing = number(before.get("orientation")), number(after.get("orientation"))
                if old_facing is not None and facing is not None:
                    turned = abs((facing-old_facing+math.pi) % math.tau-math.pi) > .05
            success = turned or corpse_confirmed or (same and (target.get("dead", target.get("is_dead")) is True or
                       (hp is not None and old_hp is not None and hp < old_hp))) or cast_verified or fast_cast_verified or combat_progress
        elif name == "ASSIST":
            params = attempt.proposal.parameters
            same_target = old_target.get("guid") == target.get("guid") and old_target.get("guid") is not None
            item_event = any(e.get("event_type") == "ITEM_USED"
                and (e.get("payload") or {}).get("item_id") == params.get("item_id") for e in events)
            success = bool(objective_progress(params.get("quest_ids"))) or item_event or bool(digest_progress(params.get("quest_ids")))
            if not same_target and not success:
                return Outcome.CANCELLED, "target_identity_changed"
        elif name == "USE_ON_TARGET":
            params = attempt.proposal.parameters
            same_target = old_target.get("guid") == target.get("guid") and old_target.get("guid") is not None
            item_event = any(e.get("event_type") == "ITEM_USED"
                and str((e.get("payload") or {}).get("item_id")) == str(params.get("item_id")) for e in events)
            success = bool(objective_progress(params.get("quest_ids"))) or item_event or bool(digest_progress(params.get("quest_ids")))
            if not same_target and not success:
                return Outcome.CANCELLED, "target_identity_changed"
        elif name == "FOLLOW_INSTRUCTION":
            params = attempt.proposal.parameters
            same_target = old_target.get("guid") == target.get("guid") and old_target.get("guid") is not None
            action = next((item for item in before.get("actionbar", [])
                           if item.get("action") == params.get("binding")), None)
            spell_id = action.get("id", action.get("spell_id")) if action else None
            cast = any(event.get("event_type") == "SPELLCAST_SUCCEEDED"
                       and spell_id is not None
                       and str((event.get("payload") or {}).get("spell_id")) == str(spell_id)
                       for event in events)
            success = cast or bool(objective_progress(params.get("quest_ids"))) or bool(digest_progress(params.get("quest_ids")))
            if not same_target and not success:
                return Outcome.CANCELLED, "target_identity_changed"
        elif name == "DEATH_RECOVERY":
            if attempt.proposal.parameters.get("action") == "RELEASE_SPIRIT":
                success = after.get("is_ghost") is True or after.get("is_dead") is False
            else:
                success = after.get("is_ghost") is False and after.get("is_dead") is False
        elif name == "ESCAPE":
            old_player, player = number(before.get("health")), number(after.get("health"))
            success = (before.get("is_in_combat") and not after.get("is_in_combat")) or (
                old_player is not None and player is not None and player > old_player)
        elif name in {"MOVE", "RECOVER"}:
            old_pos, pos = before.get("position") or {}, after.get("position") or {}
            if all(number(p.get(k)) is not None for p in (old_pos, pos) for k in ("x", "y")) and before.get("map_id") == after.get("map_id"):
                moved = math.hypot(pos["x"] - old_pos["x"], pos["y"] - old_pos["y"]) > .00008
                if name == "RECOVER":
                    success = moved
                else:
                    p = attempt.proposal.parameters
                    previous_distance = math.hypot(p["x"] - old_pos["x"], p["y"] - old_pos["y"])
                    distance = world.distance(p)
                    old_facing, facing = number(before.get("orientation")), number(after.get("orientation"))
                    turned = False
                    if old_facing is not None and facing is not None and attempt.commands and attempt.commands[0].simultaneous:
                        delta = abs((facing - old_facing + math.pi) % math.tau - math.pi)
                        if .005 < delta < 1.:
                            self.turn_rate = min(6., max(.5, .7 * self.turn_rate + .3 * delta / max(.01, attempt.commands[0].duration)))
                            turned = True
                    success = moved and distance is not None and distance < previous_distance - .00001
        if success:
            return Outcome.SUCCESS, "expected_observation_verified"
        if name in {"COMBAT", "LOOT", "INTERACT"} and old_target.get("guid") != target.get("guid"):
            return Outcome.CANCELLED, "target_identity_changed"
        error_relevant_skills = {"INTERACT", "TALK", "LOOT", "GATHER",
            "HERB", "MINE", "FISH", "USE", "USE_ON_TARGET", "ASSIST",
            "FOLLOW_INSTRUCTION", "COMBAT", "DEFEND", "MOVE", "FOLLOW",
            "REACH_LOCATION", "REACH_OBJECT", "APPROACH_TARGET", "VISUAL_APPROACH",
            "MOUNT", "DISMOUNT", "REPAIR", "BUY_VENDOR", "SELL_VENDOR", "VEHICLE_ABILITY"}
        if (name in error_relevant_skills and after.get("ui_error")
                and after.get("ui_error") != before.get("ui_error")):
            return Outcome.FAILURE, f"client_error:{after['ui_error']}"
        return (Outcome.FAILURE, "expected_observation_missing") if now >= attempt.deadline else (Outcome.PENDING, "awaiting_expected_change")
