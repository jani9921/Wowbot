"""SkillRegistry.available(): may this proposal run now?  Plus the action-bar helpers it uses.

Split out of skills.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import re
from .models import Proposal, number
from .world import WorldModel
from .skill_contracts import _world_map_open


class SkillAvailabilityMixin:
    """Methods of SkillRegistry (skills.py); moved verbatim."""

    def available(self, proposal: Proposal, world: WorldModel) -> bool:
        contract = self.contracts.get(proposal.skill)
        if not contract:
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
        detail_dependent = {"QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "GATHER", "HERB", "MINE", "USE", "FISH",
            "MOUNT", "DISMOUNT", "ASSIST", "USE_ON_TARGET",
            "FOLLOW_INSTRUCTION", "ESCAPE",
            "REPAIR", "BUY_VENDOR", "OPEN_BAGS", "SELL_VENDOR"}
        if proposal.skill in detail_dependent and detail_age > 2.:
            return False
        if self.bindings and any(not self.bindings.contains(a) for a in contract.required_bindings):
            return False
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
            return _world_map_open(world.state) is False and not world.state.get("is_in_combat") and not world.state.get("is_casting")
        if proposal.skill == "CLOSE_MAP":
            return _world_map_open(world.state) is True
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
                    and not target.get("dead", target.get("is_dead")))
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
                    and (not self.bindings or self.bindings.contains(binding)))
        if proposal.skill == "USE_ON_TARGET":
            target = world.state.get("target") or {}
            action = self.quest_item_action(world.state, proposal.parameters.get("item_id"))
            inventory = self.quest_item_inventory(world.state, proposal.parameters)
            interact_key = (proposal.parameters.get("activation_source") == "INTERACT_KEY"
                            and (not self.bindings or self.bindings.contains("INTERACTTARGET")))
            return (not world.state.get("is_casting")
                    and (action is not None or inventory is not None or interact_key)
                    and target.get("guid") == proposal.parameters.get("guid")
                    and not target.get("dead", target.get("is_dead")))
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
            return (vendor.get("open") is True and world.state.get("bags_open") is True
                    and item is not None and item.get("is_quest_item") is not True
                    and item.get("is_locked") is not True and item.get("is_equippable") is not True
                    and (number(item.get("sell_price")) or 0) > 0
                    and None not in (x, y, number(item.get("x")), number(item.get("y")))
                    and 0 < x < 1 and 0 < y < 1
                    and abs(x-number(item["x"])) <= .002 and abs(y-number(item["y"])) <= .002)
        if proposal.skill in {"TARGET", "INSPECT", "GATHER", "HERB", "MINE", "USE"}:
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
                expected_guid = proposal.parameters.get("guid")
                expected_name = str(proposal.parameters.get("expected_name") or "").strip()
                identity_matches = ((expected_guid and mouse.get("guid") == expected_guid)
                                    or (not expected_guid and expected_name
                                        and str(mouse.get("name") or
                                                (mouse.get("tooltip_data") or {}).get("unit_name") or "").strip()
                                            == expected_name))
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
        if proposal.skill in {"FISH", "MOUNT", "DISMOUNT"}:
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
    def quest_item_inventory(state: dict, parameters: dict) -> dict | None:
        """Resolve one exact, visible active-quest item bag slot."""
        if parameters.get("activation_source") != "INVENTORY_COORDINATE":
            return None
        item_id = parameters.get("item_id")
        quest_ids = {str(value) for value in parameters.get("quest_ids", ())}
        special_item_match = any(
            str(quest.get("quest_id")) in quest_ids
            and str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
            for quest in state.get("active_quests", ()))
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
