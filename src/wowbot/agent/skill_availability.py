"""SkillRegistry.available(): may this proposal run now?  Plus the action-bar helpers it uses.

Split out of skills.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import re
from .models import Proposal, number
from .world import WorldModel
from .skill_contracts import _world_map_open
from .quest_ui_evidence import dialog_evidence_allows
from .mount_capability import mount_capability_allows
from .packet_entity_facts import server_feign_death


class SkillAvailabilityMixin:
    """Methods of SkillRegistry (skills.py); moved verbatim."""

    def available(self, proposal: Proposal, world: WorldModel) -> bool:
        if (proposal.skill in {'SELL_VENDOR', 'BUY_VENDOR'}
                and (world.state.get('inventory') or {}).get('complete') is False):
            return False
        contract = self.contracts.get(proposal.skill)
        if not contract:
            return False
        if (proposal.skill == 'MOVE' and proposal.parameters.get('flight') is True
                and world.state.get('is_mounted') is not True
                and world.state.get('in_vehicle') is not True):
            # The shared travel policy can propose MOUNT and MOVE together.
            # Only verified mounting admits the own-mount flight, regardless
            # of learned utility scores or action-bar telemetry settling.
            return False
        from .server_mode import server_mode_selected
        from .planner import Planner
        if server_mode_selected(world.state) and Planner.vision_driven(proposal):
            return False
        if proposal.skill in {"COMBAT", "DEFEND"}:
            from .combat_target_safety import combat_target_allowed
            if not combat_target_allowed(world.state, world.state.get("target") or {},
                    explicit_objective=proposal.parameters.get("elite_objective_verified") is True):
                return False
        from .vehicle_abilities import stationary_vehicle_controls
        if (proposal.skill in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION", "RECOVER",
                               "VISUAL_APPROACH", "SEEK_VISUAL_CUE", "APPROACH_TARGET"}
                and stationary_vehicle_controls(world.state)):
            return False
        from wowbot.runtime.entity_identity import check_entity_identity
        from wowbot.runtime.skill_identity import entity_role, expected_identity
        role = entity_role(proposal.skill, proposal.parameters)
        wanted = expected_identity(proposal.parameters, include_item=proposal.skill == "OBJECT_USE")
        if role == "target" and wanted:
            from wowbot.runtime.skill_identity import soft_interact
            observed = (soft_interact(world.state) if proposal.parameters.get("activation_source") == "SOFT_INTERACT"
                        else world.state.get("target"))
            if not check_entity_identity(wanted, observed or {}):
                return False
        if proposal.skill == "ACQUIRE_TARGET":
            # TAB cannot guarantee the intended GUID. Search/hover first;
            # the exact-ID TARGET skill owns selection.
            return False
        if proposal.skill in {"GATHER", "HERB", "MINE"}:
            if not check_entity_identity(wanted, world.state.get("mouseover") or {}):
                return False
        if proposal.skill == "OBJECT_USE":
            from wowbot.skills.object_use import ObjectUseSkill
            from .tooltip_quest import effective_mouseover
            from wowbot.runtime.skill_identity import soft_interact
            activation = proposal.parameters.get("activation_source")
            if activation == "INTERACT_KEY_AT_SPAWN":
                return False
            if activation == "INTERACT_KEY_PACKET":
                return ObjectUseSkill.packet_object_usable(proposal.parameters, world.state)
            observed = (soft_interact(world.state) if activation == "INTERACT_KEY"
                        else effective_mouseover(world.state))
            if not ObjectUseSkill._identity_matches(proposal.parameters, observed or {}):
                return False
        detail_age = number(world.state.get("state_age")) or 0
        # TARGET is generated only from a simultaneous, fresh FAST
        # mouseover/cursor edge (QuestDomain verifies both sample times).
        # Do not reject that current ground truth merely because the separate
        # paged FULL_STATE snapshot is older than two seconds.
        # OPEN_MAP/CLOSE_MAP excluded: their own availability check below
        # (world_map_open/is_in_combat/is_casting) and verify() both read
        # only fast-lane fields, so gating them on the slow snapshot's age
        # just traps the bot with the map open and no way to close it while
        # state_age drifts past 2s (live-confirmed 2026-09-12: WAIT loop on
        # "missing TOGGLEWORLDMAP binding" while missing_bindings was
        # actually empty -- the real gate was this detail_age check).
        detail_dependent = {"QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "ADDON_ACTION", "GATHER", "HERB", "MINE", "USE", "FISH",
            "MOUNT", "DISMOUNT", "ASSIST", "USE_ON_TARGET",
            "FOLLOW_INSTRUCTION", "ESCAPE",
            "REPAIR", "BUY_VENDOR", "OPEN_BAGS", "SELL_VENDOR"}
        if proposal.skill in {"QUEST_DIALOG", "FIELD_TURN_IN"}:
            if not dialog_evidence_allows(world.state, proposal.parameters,
                                          received_now=getattr(world, "last_received", None)):
                return False
        elif proposal.skill in detail_dependent and detail_age > 2.:
            return False
        if self.bindings and any(not self.bindings.contains(a) for a in contract.required_bindings):
            return False
        if ((world.state.get("movement") or {}).get("falling") is True
                and proposal.skill in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION",
                                       "VISUAL_APPROACH", "SEEK_VISUAL_CUE"}):
            return False
        if (((world.state.get("quest_ui") or {}).get("open") is True
             or world.state.get("quest_ui_open") is True
             or (world.state.get("gossip_ui") or {}).get("open") is True
             or world.state.get("gossip_open") is True)
                and proposal.skill in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION",
                                       "VISUAL_APPROACH", "SEEK_VISUAL_CUE", "OPEN_MAP"}):
            return False
        if proposal.skill == "ADDON_ACTION":
            from wowbot.skills.quest_tool import addon_action_ready
            return addon_action_ready(proposal.parameters, world.state, self.bindings)
        if proposal.skill == "EXTRA_ACTION":
            params, extra = proposal.parameters, world.state.get("extra_action") or {}
            return (self.bindings is not None
                    and extra.get("visible") is True and extra.get("usable") is True
                    and str(extra.get("action") or "").upper() == "EXTRAACTIONBUTTON1"
                    and str(extra.get("action_type") or "").lower()
                        == str(params.get("extra_action_type") or "").lower()
                    and params.get("extra_action_id") is not None
                    and str(extra.get("action_id")) == str(params.get("extra_action_id"))
                    and bool(params.get("quest_ids") or params.get("objective_ids")))
        if proposal.skill == "OPEN_MAP":
            # Live 2026-10-11 15:47/15:48: the map was opened twice while
            # riding the Giant Boar (55879); the vehicle stage owns the input
            # and the map only hid the screen.
            # User 2026-10-11: opening the map closes an open quest/gossip or
            # vendor window ("Stocking Up on Supplies": map opened as soon as
            # the window appeared).
            ui_open = (world.state.get("quest_ui_open") is True
                       or (world.state.get("quest_ui") or {}).get("open") is True
                       or world.state.get("gossip_open") is True
                       or (world.state.get("vendor_ui") or {}).get("open") is True)
            return (_world_map_open(world.state) is False and not world.state.get("is_in_combat")
                    and not world.state.get("is_casting") and world.state.get("in_vehicle") is not True
                    and not ui_open)
        if proposal.skill == "CLOSE_MAP":
            return _world_map_open(world.state) is True
        if proposal.skill == "CLOSE_DIALOG":
            return (world.state.get("quest_ui_open") is True
                    and not world.state.get("world_map_open")
                    and not world.state.get("is_in_combat"))
        if proposal.skill in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            from .camera_controller import CAMERA_ACTIONS, camera_gesture
            params = camera_gesture({**proposal.parameters,
                                     "camera_action": ("REACQUIRE_TRACK"
                                         if proposal.skill == "REACQUIRE_TARGET"
                                         else proposal.parameters.get("camera_action"))})
            commitment = world.runtime_context.get("commitment") or {}
            return (params["camera_action"] in CAMERA_ACTIONS
                    and not world.state.get("world_map_open") and not world.state.get("is_in_combat")
                    and (proposal.skill != "REACQUIRE_TARGET"
                         or (commitment.get("target_guid")
                             and commitment.get("target_guid") == proposal.parameters.get("guid")))
                    and all(number(params.get(k)) is not None
                            and 0 < float(params[k]) < 1 for k in ("x", "y")))
        if proposal.skill == "SEEK_VISUAL_CUE":
            return (not world.state.get("world_map_open")
                    and not world.state.get("is_in_combat")
                    and not world.state.get("is_casting")
                    and not world.state.get("input_blocked")
                    and (not self.bindings or all(self.bindings.contains(action)
                         for action in ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"))))
        if proposal.skill in {"MOVE", "FOLLOW"}:
            params = proposal.parameters
            if params.get("coordinate_space") == "WORLD_YARDS":
                player = world.state.get("player_world_position") or {}
                player_instance = player.get("instance_id")
                destination_instance = params.get("instance_id", player_instance)
                return (proposal.skill == "MOVE"
                        and player.get("coordinate_space") in {None, "WORLD_YARDS"}
                        and player_instance is not None
                        and player_instance == destination_instance
                        and all(number(point.get(axis)) is not None
                                for point in (player, params) for axis in ("x", "y"))
                        and number(world.state.get("orientation")) is not None
                        and not world.state.get("is_casting"))
            return (world.distance(params) is not None
                    and number(world.state.get("orientation")) is not None)
        if proposal.skill == "REACH_OBJECT":
            target = world.state.get("target") or {}
            player = world.state.get("player_world_position") or {}
            destination = target.get("world_position") or {}
            if proposal.parameters.get("source") == "TDB_REFERENCE":
                from .location_fallback import reference_destination
                reference = reference_destination(world.state)
                if not reference or any(reference.get(k) != proposal.parameters.get(k)
                                        for k in ("spawn_id", "source_sha256", "x", "y", "z")):
                    return False
                destination = reference
            return (target.get("guid") == proposal.parameters.get("target_guid")
                    and not target.get("dead", target.get("is_dead"))
                    and destination.get("coordinate_space") in {None, "WORLD_YARDS"}
                    and player.get("coordinate_space") in {None, "WORLD_YARDS"}
                    and all(number(point.get(axis)) is not None
                            for point in (player, destination) for axis in ("x", "y"))
                    and number(world.state.get("orientation")) is not None
                    and not world.state.get("is_casting"))
        if proposal.skill == "REACH_LOCATION":
            player = world.state.get("player_world_position") or {}
            params = proposal.parameters
            candidates = world.state.get("quest_role_reference_candidates", [])
            matched = any(row.get("source") == "TDB_REFERENCE"
                          and row.get("source_sha256") == params.get("source_sha256")
                          and row.get("world_map_id") == params.get("world_map_id")
                          and row.get("spawn_ids") == params.get("spawn_ids")
                          and all(row.get(axis) == params.get(axis) for axis in ("x", "y", "z"))
                          for row in candidates)
            return (matched and params.get("coordinate_space") == "WORLD_YARDS"
                    and player.get("instance_id") == params.get("world_map_id")
                    and all(number(point.get(axis)) is not None
                            for point in (player, params) for axis in ("x", "y"))
                    and number(world.state.get("orientation")) is not None
                    and not world.state.get("is_casting"))
        if proposal.skill in {"COMBAT", "DEFEND"}:
            # Proposal admission must not mutate the retired CombatController.
            # The running M0 CombatSkill owns action selection and all attempt
            # state; this is only a stateless feasibility preview.
            target = world.state.get("target") or {}
            # Live 2026-10-03 13:58: a goat beat the character to death for
            # 80 s while COMBAT was "not admissible" (combat secrets: no
            # range/usable data).  Under attack with a live hostile selected,
            # CombatSkill must run (auto-attack, facing sweep).
            under_attack = (world.state.get("is_in_combat") is True and bool(target.get("guid"))
                            and target.get("attackable", target.get("is_attackable")) is True
                            and target.get("dead", target.get("is_dead")) is not True)
            return (not world.state.get("is_casting")
                    and (under_attack
                         or self._combat_action_available(world.state)
                         or self._auto_attack_available(world.state)))
        if proposal.skill == "ASSIST":
            target = world.state.get("target") or {}
            action = self.beneficial_action(world.state, proposal.parameters.get("item_id"))
            inventory = self.quest_item_inventory(world.state, proposal.parameters)
            return (not world.state.get("is_casting") and (action is not None or inventory is not None)
                    and target.get("guid") == proposal.parameters.get("guid")
                    and target.get("attackable", target.get("is_attackable")) is False
                    and (not target.get("dead", target.get("is_dead"))
                         or server_feign_death(world.state, target.get("guid"))
                         or self._dead_target_item(world.state, proposal.parameters)))
        if proposal.skill == "EXIT_VEHICLE":
            return (world.state.get("in_vehicle") is True and world.state.get("on_taxi") is not True
                    and (not self.bindings or self.bindings.contains("VEHICLEEXIT")))
        if proposal.skill == "VEHICLE_ABILITY":
            binding = str(proposal.parameters.get("binding") or "")
            action = next((item for item in world.state.get("actionbar") or ()
                           if isinstance(item, dict) and item.get("action") == binding
                           and item.get("source") == "VEHICLE_BAR"), None)
            return (bool(world.state.get("vehicle_controls")) and action is not None
                    and action.get("is_usable") is not False
                    and (number(action.get("cooldown_remaining")) or 0.) <= .1
                    and (proposal.parameters.get("spell_id") is None
                         or str(proposal.parameters["spell_id"]) == str(action.get("id")))
                    and (not proposal.parameters.get("require_objective_progress")
                         or (world.state.get("in_vehicle") is True and detail_age <= 2.
                             and action.get("is_usable") is True
                             and action.get("is_harmful") is not True
                             and number(action.get("max_range")) == 0.))
                    and (not self.bindings or self.bindings.contains(binding)))
        if proposal.skill == "USE_ON_TARGET":
            if proposal.parameters.get("item_aim_guid"):
                from .directed_item_facts import ready_for_use
                if not ready_for_use(world.state, proposal.parameters, world.state.get("monotonic_time")):
                    return False
            target = world.state.get("target") or {}
            action = self.quest_item_action(world.state, proposal.parameters.get("item_id"))
            inventory = self.quest_item_inventory(world.state, proposal.parameters)
            from .quest_tool_resolver import QuestToolResolver
            interact_key = (proposal.parameters.get("activation_source") == "INTERACT_KEY"
                            and (not self.bindings or self.bindings.contains("INTERACTTARGET"))
                            and QuestToolResolver.can_interact(
                                world.state, proposal.parameters.get("item_id"), proposal.parameters.get("guid"),
                                proposal.parameters.get("quest_ids")))
            return (not world.state.get("is_casting")
                    and (action is not None or inventory is not None or interact_key)
                    and ((proposal.parameters.get("target_required") is False
                          and proposal.parameters.get("item_target_mode") == "SELF"
                          and not proposal.parameters.get("guid"))
                         or (target.get("guid") == proposal.parameters.get("guid")
                             and (not target.get("dead", target.get("is_dead"))
                                  or server_feign_death(world.state, target.get("guid"))
                                  or self._dead_target_item(world.state, proposal.parameters)))))
        if proposal.skill == "FOLLOW_INSTRUCTION":
            target = world.state.get("target") or {}
            action = self.instructed_action(world.state, proposal.parameters.get("instruction"))
            return (not world.state.get("is_casting") and action is not None
                    and action.get("action") == proposal.parameters.get("binding")
                    and target.get("guid") == proposal.parameters.get("guid")
                    and target.get("attackable", target.get("is_attackable")) is True
                    and not target.get("dead", target.get("is_dead")))
        if (proposal.skill == "VISUAL_APPROACH"
                and proposal.parameters.get("purpose") == "LOOT"):
            track_id = proposal.parameters.get("track_id")
            return (bool(track_id) and not world.state.get("is_casting")
                    and not world.state.get("is_in_combat")
                    and any(item.get("track_id") == track_id
                            for item in world.state.get("visual_candidates") or ()))
        if (proposal.skill == "VISUAL_APPROACH"
                and proposal.parameters.get("object_use_approach") is True):
            from .object_interaction_flow import ObjectInteractionFlow, open_object_objective
            params = proposal.parameters
            quest_ids = params.get("quest_ids") or ()
            track_id = params.get("track_id")
            boxes = [item for item in world.state.get("visual_candidates") or ()
                     if isinstance(item, dict) and item.get("track_id") == track_id]
            return (bool(quest_ids) and bool(track_id)
                    and open_object_objective(world.state, quest_ids[0])
                    and not any(world.state.get(key) for key in (
                        "world_map_open", "quest_ui_open", "gossip_open",
                        "is_in_combat", "is_casting", "input_blocked"))
                    and ObjectInteractionFlow._confirmed_hover_box(
                        params, quest_ids[0], world.state, boxes) is not None)
        if (proposal.skill == "VISUAL_APPROACH" and not proposal.parameters.get("guid")
                and proposal.parameters.get("purpose") in {"VEHICLE_AIM", "VEHICLE_ATTACK"}):
            # An objective unit named by an earlier hover, not the selected
            # target (vehicle abilities here need no target): steer at its
            # live, non-avatar track.
            from .self_avatar import is_self_avatar_box
            track_id = proposal.parameters.get("track_id")
            return (bool(world.state.get("vehicle_controls")) and bool(track_id)
                    and any(isinstance(item, dict) and item.get("track_id") == track_id
                            and not is_self_avatar_box(item)
                            for item in world.state.get("visual_candidates") or ()))
        if proposal.skill in {"APPROACH_TARGET", "VISUAL_APPROACH"}:
            target = world.state.get("target") or {}
            screen = proposal.parameters.get("screen_position") or target.get("screen_position") or {}
            sampled = number(screen.get("sample_time"))
            at = number(world.state.get("monotonic_time"))
            purpose = proposal.parameters.get("purpose")
            allowed_target = (target.get("attackable", target.get("is_attackable")) is True
                              or (purpose in {"INTERACT", "VEHICLE_ATTACK", "VEHICLE_AIM"}
                                  and target.get("attackable", target.get("is_attackable")) is False))
            # Live 2026-10-04 08:57: Austin Huxworth (turn-in NPC) was on
            # screen as a GUID-bound World3D track; without these sources the
            # approach was "unavailable" and INTERACT kept failing out of range.
            allowed_source = (screen.get("source") == "NAMEPLATE_API"
                              or (purpose in {"INTERACT", "COMBAT", "VEHICLE_ATTACK", "VEHICLE_AIM"}
                                  and screen.get("source") in {"CONFIRMED_MOUSEOVER",
                                                               "CONFIRMED_MOUSEOVER_ANCHOR",
                                                               "BOUND_WORLD3D_TRACK",
                                                               "WORLD3D_TARGET_TRACK"}))
            maximum_age = (30. if screen.get("source") == "CONFIRMED_MOUSEOVER_ANCHOR"
                           else 3. if screen.get("source") in {"BOUND_WORLD3D_TRACK",
                                                               "WORLD3D_TARGET_TRACK"}
                           else 1.)
            return (target.get("guid") == proposal.parameters.get("guid") and allowed_target
                    and not target.get("dead") and allowed_source
                    and screen.get("coordinate_space") == "CLIENT_BOTTOM_LEFT"
                    and number(screen.get("x")) is not None and .02 < screen["x"] < .98
                    and sampled is not None and at is not None
                    # A World3D track is often newer than the slower addon
                    # snapshot clock (live 2026-10-04: -0.2..-3.6 s).
                    and -5. <= at-sampled < maximum_age
                    and not world.state.get("is_casting"))
        if proposal.skill == "REPAIR":
            vendor = world.state.get("vendor_ui") or {}
            cost = number(vendor.get("repair_all_cost"))
            x, y = number(proposal.parameters.get("x")), number(proposal.parameters.get("y"))
            vx, vy = number(vendor.get("repair_x")), number(vendor.get("repair_y"))
            return (not world.state.get("is_in_combat") and not world.state.get("is_casting")
                    and vendor.get("open") is True and vendor.get("can_repair") is True
                    and cost is not None and cost > 0 and None not in (x, y, vx, vy)
                    and 0 < x < 1 and 0 < y < 1
                    and abs(x-vx) <= .002 and abs(y-vy) <= .002)
        if proposal.skill == "BUY_VENDOR":
            vendor = world.state.get("vendor_ui") or {}
            x, y = number(proposal.parameters.get("x")), number(proposal.parameters.get("y"))
            slot = proposal.parameters.get("slot")
            item = next((candidate for candidate in vendor.get("items", [])
                         if candidate.get("slot") == slot), None)
            money, price = number(world.state.get("money")), number((item or {}).get("price"))
            return (vendor.get("open") is True and item is not None
                    and item.get("is_purchasable") is True and money is not None and price is not None
                    and price <= money and None not in (x, y, number(item.get("x")), number(item.get("y")))
                    and 0 < x < 1 and 0 < y < 1
                    and abs(x-number(item["x"])) <= .002 and abs(y-number(item["y"])) <= .002)
        if proposal.skill == "OPEN_BAGS":
            if proposal.parameters.get("purpose") == "QUEST_ITEM":
                item_id = proposal.parameters.get("item_id")
                quest_ids = {str(value) for value in proposal.parameters.get("quest_ids", ())}
                special_item_match = any(
                    str(quest.get("quest_id")) in quest_ids
                    and str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
                    for quest in world.state.get("active_quests", ()))
                inventory_match = any(
                    str(item.get("item_id")) == str(item_id) and item.get("is_locked") is not True
                    for item in (world.state.get("inventory") or {}).get("items", ()))
                if not special_item_match:
                    from .quest_item_knowledge import authorized_item
                    special_item_match = authorized_item(world.state, item_id, quest_ids)
                return (world.state.get("bags_open") is False
                        and special_item_match and inventory_match)
            return (world.state.get("vendor_ui") or {}).get("open") is True and world.state.get("bags_open") is False
        if proposal.skill == "SELL_VENDOR":
            vendor = world.state.get("vendor_ui") or {}
            params = proposal.parameters
            item = next((candidate for candidate in (world.state.get("inventory") or {}).get("items", [])
                         if candidate.get("bag") == params.get("bag")
                         and candidate.get("slot") == params.get("slot")), None)
            x, y = number(params.get("x")), number(params.get("y"))
            from .quest_objective_planning import quest_sellable
            return (vendor.get("open") is True and world.state.get("bags_open") is True
                    and item is not None and quest_sellable(item)
                    and None not in (x, y, number(item.get("x")), number(item.get("y")))
                    and 0 < x < 1 and 0 < y < 1
                    and abs(x-number(item["x"])) <= .002 and abs(y-number(item["y"])) <= .002)
        if proposal.skill in {"TARGET", "INSPECT", "GATHER", "HERB", "MINE", "USE"}:
            if proposal.skill == "TARGET" and proposal.parameters.get("activation_source") == "TAB_FRIEND_RESCUE":
                return (not world.state.get("is_in_combat") and bool(proposal.parameters.get("guid"))
                        and (self.bindings is None or self.bindings.contains("TARGETNEARESTFRIEND")))
            if proposal.skill == "TARGET" and proposal.parameters.get("activation_source") == "TAB_DEFEND":
                return (world.state.get("is_in_combat") is True and bool(proposal.parameters.get("guid"))
                        and (self.bindings is None or self.bindings.contains("TARGETNEARESTENEMY")))
            if proposal.skill == "TARGET" and proposal.parameters.get("activation_source") == "TAB_SERVER_GUID":
                from .packet_entity_facts import tab_target_check
                return (not world.state.get("is_in_combat")
                        and tab_target_check(world.state, proposal.parameters.get("guid"))[0]
                        and (self.bindings is None or self.bindings.contains("TARGETNEARESTENEMY")))
            if proposal.skill == "TARGET" and proposal.parameters.get("restore_last_target"):
                return (not (world.state.get("target") or {}).get("guid")
                        and bool(proposal.parameters.get("guid")) and self.bindings is not None
                        and self.bindings.contains("TARGETLASTTARGET"))
            if proposal.skill == "INSPECT" and proposal.parameters.get("camera_pan"):
                return (not world.state.get("world_map_open")
                        and not world.state.get("is_in_combat")
                        and (not self.bindings or all(self.bindings.contains(action)
                             for action in ("TURNLEFT", "TURNRIGHT"))))
            if proposal.parameters.get("map_zoom_in") or proposal.parameters.get("map_step_out"):
                if (proposal.skill != "INSPECT"
                        or proposal.parameters.get("source") not in {
                            "WORLD_MAP_CV", "WORLD_MAP_CONTEXT"}
                        or not world.state.get("world_map_open") or world.state.get("is_in_combat")):
                    return False
            if proposal.skill == "TARGET" and proposal.parameters.get("ground_truth_handoff"):
                # Identity (GUID/name) is durable evidence, while a screen
                # anchor is not. A handoff may click only if this exact current
                # cursor position still yields a fresh matching mouseover.
                # Movement, camera turns, track loss, and delayed dispatch all
                # therefore route back through INSPECT/reacquisition instead
                # of spending a click on a stale screen pixel.
                mouse = world.state.get("mouseover") or {}
                cursor = world.state.get("cursor_position") or {}
                now = number(world.state.get("monotonic_time"))
                mouse_time = number(world.state.get("mouseover_sample_time", now))
                cursor_time = number(world.state.get("cursor_sample_time", now))
                px, py = number(proposal.parameters.get("x")), number(proposal.parameters.get("y"))
                cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
                fresh_and_co_sampled = (None not in (now, mouse_time, cursor_time, px, py, cx, cy)
                                         and 0 <= now-mouse_time <= .35
                                         and 0 <= now-cursor_time <= .35
                                         and abs(mouse_time-cursor_time) <= .05
                                         and abs(px-cx) <= .002 and abs(py-cy) <= .002)
                identity_matches = check_entity_identity(wanted, mouse)
                if not (fresh_and_co_sampled and identity_matches):
                    return False
            if proposal.skill == "USE":
                # Object use is a screen-space interaction, so a planner crop
                # from an earlier hover is never enough. Require the exact
                # currently exported cursor point and a stable object/item ID.
                mouse, cursor = world.state.get("mouseover") or {}, world.state.get("cursor_position") or {}
                x, y = number(proposal.parameters.get("x")), number(proposal.parameters.get("y"))
                cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
                object_id, item_id = proposal.parameters.get("object_id"), proposal.parameters.get("item_id")
                identity_matches = ((object_id is not None and str(mouse.get("object_id")) == str(object_id))
                                    or (item_id is not None and str(mouse.get("item_id")) == str(item_id))
                                    or (bool(proposal.parameters.get("mouseover_tooltip"))
                                        and str(mouse.get("tooltip") or "")
                                            == str(proposal.parameters.get("mouseover_tooltip"))))
                if (None in (x, y, cx, cy) or abs(x-cx) > .002 or abs(y-cy) > .002
                        or not identity_matches):
                    return False
            return all(number(proposal.parameters.get(k)) is not None and 0 < float(proposal.parameters[k]) < 1 for k in ("x", "y"))
        if proposal.skill == "MOUNT":
            return (mount_capability_allows(world.state)
                    and bool(proposal.parameters.get("binding"))
                    and (not self.bindings or self.bindings.contains(proposal.parameters["binding"])))
        if proposal.skill in {"FISH", "DISMOUNT"}:
            return bool(proposal.parameters.get("binding")) and (not self.bindings or self.bindings.contains(proposal.parameters["binding"]))
        if proposal.skill == "ESCAPE":
            binding = proposal.parameters.get("binding")
            return bool(binding) and (not self.bindings or self.bindings.contains(binding))
        return True

    def combat_action(self, state: dict, *, record: bool = False) -> dict | None:
        """Compatibility adapter for direct legacy callers only.

        AutonomousAgent never invokes this method. Its stateful controller is
        retained temporarily for non-runtime diagnostics/tests while canonical
        M0 combat uses ``wowbot.skills.CombatSkill``.
        """
        self.combat.observe(state, number(state.get("monotonic_time")) or 0.)
        return self.combat.choose_action(state, record=record)

    def _combat_action_available(self, state: dict) -> bool:
        """Pure preview used by planner admission; performs no bookkeeping."""
        return self._ability_rules.choose(state) is not None

    def _auto_attack_available(self, state: dict) -> bool:
        """Pure admission check for CombatSkill's exact-target right click."""
        target = state.get("target") or {}
        screen = target.get("screen_position") or {}
        if (not target.get("guid")
                or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead")) is True):
            return False
        # Live 2026-10-03 13:37: a neutral goat in melee, 0 rage, no screen
        # box -> nothing admissible for 30 s.  The interact key starts the
        # auto-attack on the selected unit without any screen position.
        keyed = self.bindings is None or self.bindings.contains("INTERACTTARGET")
        if (number(screen.get("x")) is None or number(screen.get("y")) is None) and not keyed:
            return False
        for action in self._ability_rules.actionbar(state):
            definition = self._ability_rules.definition(action)
            if (action.get("kind") == "spell" and action.get("is_harmful") is True
                    and action.get("in_range") is True
                    and "MOVEMENT" not in definition.tags
                    and definition.max_range is not None and definition.max_range <= 5.):
                return True
        distance = number(target.get("distance", target.get("distance_yards")))
        return distance is not None and distance <= 5.

    def combat_actionbar(self, state: dict) -> list[dict]:
        """Canonical stable identities with FAST readiness/range overlaid."""
        return [dict(action) for action in self._ability_rules.actionbar(state)]

    def beneficial_action(self, state: dict, item_id) -> dict | None:
        """Choose only the explicit, usable, non-harmful quest item action."""
        if item_id is None:
            return None
        for action in state.get("actionbar", []):
            if action.get("kind") != "item" or str(action.get("id")) != str(item_id):
                continue
            if action.get("is_harmful") is True or action.get("is_usable") is not True:
                continue
            cooldown = number(action.get("cooldown_remaining"))
            if cooldown is None or cooldown > .1:
                continue
            if not action.get("action") or (self.bindings and not self.bindings.contains(action["action"])):
                continue
            return action
        return None

    def quest_item_action(self, state: dict, item_id) -> dict | None:
        """Resolve an exact quest item action without inferring its target semantics."""
        if item_id is None:
            return None
        for action in state.get("actionbar", []):
            if action.get("kind") != "item" or str(action.get("id")) != str(item_id):
                continue
            if action.get("is_usable") is not True:
                continue
            cooldown = number(action.get("cooldown_remaining"))
            if cooldown is None or cooldown > .1 or not action.get("action"):
                continue
            if self.bindings and not self.bindings.contains(action["action"]):
                continue
            return action
        return None

    @staticmethod
    def _dead_target_item(state: dict, parameters: dict) -> bool:
        from .quest_item_knowledge import item_allows_dead_target
        return item_allows_dead_target(state, parameters.get("item_id"), parameters.get("quest_ids") or ())

    @staticmethod
    def quest_item_inventory(state: dict, parameters: dict) -> dict | None:
        """Resolve one exact, visible active-quest item bag slot."""
        from .collection_coverage import inventory_ready
        if not inventory_ready(state):
            return None
        if parameters.get("activation_source") != "INVENTORY_COORDINATE":
            return None
        item_id = parameters.get("item_id")
        quest_ids = {str(value) for value in parameters.get("quest_ids", ())}
        special_item_match = any(
            str(quest.get("quest_id")) in quest_ids
            and str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
            for quest in state.get("active_quests", ()))
        if not special_item_match:
            from .quest_item_knowledge import authorized_item
            special_item_match = authorized_item(state, item_id, quest_ids)
        if not special_item_match or state.get("bags_open") is not True:
            return None
        candidate = next((item for item in (state.get("inventory") or {}).get("items", ())
                          if str(item.get("item_id")) == str(item_id)
                          and item.get("bag") == parameters.get("bag")
                          and item.get("slot") == parameters.get("slot")), None)
        x, y = number(parameters.get("x")), number(parameters.get("y"))
        ix, iy = number((candidate or {}).get("x")), number((candidate or {}).get("y"))
        if (candidate is None or candidate.get("is_locked") is True
                or candidate.get("coordinate_space") != "CLIENT_BOTTOM_LEFT"
                or parameters.get("coordinate_space") != "CLIENT_BOTTOM_LEFT"
                or None in (x, y, ix, iy) or not (0 < x < 1 and 0 < y < 1)
                or abs(x-ix) > .002 or abs(y-iy) > .002):
            return None
        return candidate

    def instructed_action(self, state: dict, instruction: str | None) -> dict | None:
        """Return an action only when fresh NPC text explicitly names it."""
        message = re.sub(r"[^a-z0-9]+", " ", str(instruction or "").casefold()).strip()
        if not message:
            return None
        matches = []
        for action in state.get("actionbar", []):
            name = re.sub(r"[^a-z0-9]+", " ", str(action.get("name") or "").casefold()).strip()
            if (action.get("kind") != "spell" or not name or name not in message
                    or action.get("is_usable") is not True or action.get("in_range") is False):
                continue
            cooldown = number(action.get("cooldown_remaining"))
            if cooldown is None or cooldown > .1 or not action.get("action"):
                continue
            if self.bindings and not self.bindings.contains(action["action"]):
                continue
            matches.append((len(name), action))
        return max(matches, key=lambda item: item[0])[1] if matches else None
