from __future__ import annotations

from dataclasses import dataclass
import math
import re
from .models import Command, Outcome, Proposal, number
from .world import WorldModel
from .combat_controller import CombatController
from .obstacle_perception import obstacle_bearing
from wowbot.skills.ability_rules import AbilityRuleEngine


def _world_map_open(state: dict) -> bool | None:
    """Return the freshest canonical map visibility bit.

    Retail's compact FAST packet carries this inside ``map_context``.  Read
    that first so map toggles remain safe even when a transport adapter or a
    replay supplies an unflattened packet.
    """
    context = state.get("map_context") or {}
    nested = context.get("world_map_open") if isinstance(context, dict) else None
    if isinstance(nested, bool):
        return nested
    top_level = state.get("world_map_open")
    return top_level if isinstance(top_level, bool) else None


@dataclass(frozen=True)
class SkillContract:
    name: str
    expected: str
    timeout: float
    required_bindings: tuple[str, ...] = ()
    recovery: str = "inspect_then_replan"
    capability: str = ""
    preconditions: tuple[str, ...] = ()
    required_world_state: tuple[str, ...] = ()
    success_condition: str = ""
    failure_condition: str = "deadline_or_client_error"
    cost: float = 1.0
    retry_budget: int = 2
    verification_method: str = "GENERIC_POSTCONDITION_ENGINE"

    def __post_init__(self):
        if not self.capability:
            object.__setattr__(self, "capability", self.name)
        if not self.success_condition:
            object.__setattr__(self, "success_condition", self.expected)

    @property
    def expected_postconditions(self) -> tuple[str, ...]:
        return (self.success_condition,)

    @property
    def recovery_policy(self) -> str:
        return self.recovery


CONTRACTS = [
    SkillContract("WAIT", "new_observation", 2., cost=.05),
    SkillContract("WAIT_EVENT", "quest_event_or_objective_progress", 15.,
                  required_world_state=("active_quests",), cost=.05),
    # Reverted 2 -> back to 5 on 2026-09-13: too many other stability issues
    # in flight (telemetry-staleness detection, REACQUIRE_TARGET, target
    # flicker) to also carry the risk of a tighter INSPECT deadline. Revisit
    # once the rest of the agent is confirmed solid on a live run.
    SkillContract("INSPECT", "mouseover_evidence", 5., preconditions=("fresh_visual_track",), cost=.3),
    # AIPC5 publishes a complete paged snapshot in roughly 3–5 seconds under
    # live capture load. Horizontal player-turn/view pulses are <=180 ms and
    # pitch-only camera gestures <=140 ms; this timeout is only the no-input
    # observation window used to verify their consequence.
    SkillContract("CAMERA_CONTROL", "view_rotation_verified", 6.,
                  ("TURNLEFT", "TURNRIGHT"),
                  recovery="widen_or_change_scan_sector",
                  preconditions=("world_surface_visible",), cost=.2),
    SkillContract("REACQUIRE_TARGET", "committed_target_visually_reacquired", 8.,
                  ("TURNLEFT", "TURNRIGHT"),
                  recovery="widen_scan_then_preserve_target_identity",
                  preconditions=("committed_target", "last_supported_visual_location"), cost=.25),
    SkillContract("SEEK_VISUAL_CUE", "unknown_visual_candidate_or_identity_observed", 22.,
                  ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                  "world_map_then_reference_fallback",
                  preconditions=("world_surface_visible", "no_higher_priority_subgoal"), cost=.45),
    SkillContract("MOVE", "reach_destination", 90., ("MOVEFORWARD",), "recover_only_after_supported_stuck",
                  preconditions=("known_destination",), required_world_state=("position", "orientation", "map_id"), cost=.8),
    SkillContract("FOLLOW", "reach_follow_region", 90., ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                  "recover_only_after_supported_stuck", preconditions=("known_leader_location",),
                  required_world_state=("position", "orientation", "map_id"), cost=.7),
    SkillContract("REACH_OBJECT", "reach_object_interaction_range", 90.,
                  ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                  "recover_only_after_supported_stuck",
                  preconditions=("committed_target", "target_world_position"),
                  required_world_state=("player_world_position", "target.guid",
                                        "target.world_position", "orientation"), cost=.8),
    SkillContract("REACH_LOCATION", "reach_reference_inspection_region", 90.,
                  ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                  "recover_only_after_supported_stuck",
                  preconditions=("world_location_hypothesis", "map_search_exhausted"),
                  required_world_state=("player_world_position", "orientation"), cost=.8),
    # Retail target telemetry can trail the visual click by several addon
    # export frames.  Live validation observed the correct target arriving
    # Four-to-seven seconds after the click was observed under paged AIPC5
    # export/debug load.  Keep the confirmed identity committed long enough
    # for authoritative target telemetry instead of falling through to map/DB.
    SkillContract("TARGET", "target_identity_changed", 8.),
    SkillContract("ACQUIRE_TARGET", "attackable_target", 2., ("TARGETNEARESTENEMY",)),
    SkillContract("APPROACH_TARGET", "target_in_range", 12., ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT")),
    SkillContract("VISUAL_APPROACH", "visual_interaction_range_supported", 30.,
                  ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                  "reacquire_then_resume_same_target",
                  preconditions=("committed_target", "supported_live_visual_location"),
                  required_world_state=("target.guid",), cost=.75),
    # AIPC5 can publish the client UI error or quest-dialog state 4–6 seconds
    # after the keypress while paged export and live capture are active. Keep
    # the exact selected target committed during that observation window;
    # otherwise a valid out-of-range result is incorrectly attributed to the
    # next OPEN_MAP action.
    SkillContract("INTERACT", "dialog_or_quest_progress", 7., ("INTERACTTARGET",)),
    SkillContract("TALK", "dialog_opened", 7., ("INTERACTTARGET",)),
    SkillContract("USE", "interaction_effect", 4.),
    SkillContract("OBJECT_USE", "quest_object_credit", 8.,
                  preconditions=("current_mouseover_object_identity", "quest_objective"),
                  required_world_state=("mouseover", "cursor_position", "active_quests"), cost=.65),
    # AIPC5 exports the quest dialog and the resulting quest log in different
    # paged snapshots.  Live Retail validation observed the authoritative
    # active-quest projection several seconds after the Accept click.  Keep the
    # attempt pending for that ground truth instead of recording a false
    # QUEST_STATE_UNEXPECTED failure while the quest was actually accepted.
    SkillContract("QUEST_DIALOG", "quest_or_dialog_transition", 10.),
    SkillContract("FIELD_TURN_IN", "field_quest_completed", 10.,
                  preconditions=("confirmed_field_turnin_mode", "visible_completion_prompt"),
                  required_world_state=("quest_ui", "active_quests"), cost=.25),
    # This is not a generic action-bar click. A canonical QuestToolSkill
    # rechecks the addon's exact type+ID before the selected-cache binding is
    # used, and verifies only authoritative quest credit afterwards.
    SkillContract("EXTRA_ACTION", "quest_objective_progress", 8., ("EXTRAACTIONBUTTON1",),
                  preconditions=("visible_usable_exact_extra_action", "quest_action_identity"),
                  required_world_state=("extra_action", "active_quests"), cost=.55),
    # 6 s: loot events/quest credit arrive on the paged STATE 1-3 s after the
    # click (live 2026-10-02: verified "not opened" 1 s before LOOT_RECEIVED).
    SkillContract("LOOT", "loot_received_or_inventory_changed", 6., ("INTERACTTARGET",),
                  preconditions=("dead_target",), required_world_state=("target.guid", "target.dead"), cost=.4),
    # Death popup confirm (Release Spirit / Resurrect Now) at the addon's
    # exported button point; verified by the dead/ghost flags changing.
    SkillContract("DEATH_RECOVERY", "death_state_changed", 4., cost=.1),
    SkillContract("GATHER", "inventory_or_objective_progress", 8.),
    SkillContract("HERB", "herb_inventory_or_objective_progress", 8., preconditions=("confirmed_herb",), cost=.7),
    SkillContract("MINE", "ore_inventory_or_objective_progress", 8., preconditions=("confirmed_ore",), cost=.7),
    SkillContract("FISH", "fishing_cast_observed", 3.),
    # COMBAT is one persistent kill skill, not one ability press. Live logs on
    # 2026-09-28 showed an 8-second attempt timing out after Charge while the
    # target was still alive. The bounded 45-second budget lets the canonical
    # CombatSkill own Charge -> melee rotation -> confirmed death, while its
    # typed range/facing/LOS/player-death failures can still terminate early.
    SkillContract("COMBAT", "target_dead", 45.,
                  preconditions=("attackable_target", "combat_action_or_auto_attack_anchor"),
                  required_world_state=("target.guid", "actionbar"), cost=1.2),
    SkillContract("ASSIST", "beneficial_item_used_on_named_target_or_objective_progress", 3.,
                  preconditions=("friendly_named_target", "usable_beneficial_item"),
                  required_world_state=("target.guid", "actionbar"), cost=.6),
    SkillContract("USE_ON_TARGET", "quest_item_used_on_named_target_or_objective_progress", 4.,
                  preconditions=("named_living_target", "usable_quest_item"),
                  required_world_state=("target.guid", "actionbar"), cost=.65),
    SkillContract("FOLLOW_INSTRUCTION", "named_ability_cast_or_objective_progress", 3.,
                  preconditions=("npc_instruction_names_known_action", "attackable_target"),
                  required_world_state=("target.guid", "actionbar", "events"), cost=.8),
    # Same persistent-combat ownership and bounded budget as COMBAT above.
    SkillContract("DEFEND", "target_dead_or_threat_removed", 45., preconditions=("in_combat", "attackable_target"), cost=1.2),
    SkillContract("ESCAPE", "distance_or_combat_state_improved", 3., recovery="stop_and_request_evidence", cost=1.5),
    SkillContract("EXIT_VEHICLE", "left_vehicle", 2.5, preconditions=("in_vehicle",), cost=.2),
    SkillContract("VEHICLE_ABILITY", "vehicle_ability_cast_or_objective_progress", 3.,
                  preconditions=("vehicle_controls", "ready_vehicle_ability"), cost=.4),
    SkillContract("MOUNT", "mounted", 4., preconditions=("not_mounted", "not_in_combat", "mount_binding_known"),
                  required_world_state=("is_mounted",), cost=.35),
    SkillContract("DISMOUNT", "dismounted", 2., preconditions=("mounted", "mount_binding_known"),
                  required_world_state=("is_mounted",), cost=.15),
    SkillContract("CLOSE_MAP", "world_map_closed", 5., ("TOGGLEWORLDMAP",)),
    SkillContract("OPEN_MAP", "world_map_opened", 5., ("TOGGLEWORLDMAP",)),
    SkillContract("RECOVER", "position_changed", 2., ("STRAFELEFT", "STRAFERIGHT", "JUMP")),
    SkillContract("REPAIR", "gear_repaired_or_no_repair_needed", 5.,
                  # vendor_ui has no fast-lane equivalent (world.py fast_keys);
                  # 5s matches the same safety margin already used for
                  # CLOSE_MAP/OPEN_MAP against the documented 3-7s worst-case
                  # slow-snapshot cadence (was 3s, too tight against that).
                  preconditions=("vendor_open", "repairable", "not_in_combat"),
                  required_world_state=("vendor_ui",), cost=.3),
    SkillContract("BUY_VENDOR", "purchase_or_objective_progress", 5.,
                  # vendor_ui/money have no fast-lane equivalent, same as REPAIR.
                  preconditions=("vendor_open", "purchasable_item", "known_money"),
                  required_world_state=("vendor_ui", "money"), cost=.35),
    SkillContract("OPEN_BAGS", "inventory_ui_open", 4., ("OPENALLBAGS",),
                  preconditions=("vendor_open",), cost=.15),
    SkillContract("SELL_VENDOR", "sale_or_objective_progress", 5.,
                  preconditions=("vendor_open", "visible_safe_sell_item"),
                  required_world_state=("vendor_ui", "inventory"), cost=.35),
]


class SkillRegistry:
    def __init__(self, bindings=None):
        self.bindings = bindings
        self.contracts = {c.name: c for c in CONTRACTS}
        self.turn_rate = math.pi  # Updated from measured facing deltas after short movement arcs.
        self.combat = CombatController(bindings)
        # Pure preview shared with the active CombatSkill and diagnostics. It
        # cannot update the compatibility CombatController or send input.
        self._ability_rules = AbilityRuleEngine(bindings)
        self.combat_uses = self.combat.uses  # compatibility/read-only diagnostics alias

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

    def commands(self, proposal: Proposal, world: WorldModel) -> tuple[Command, ...]:
        name, params = proposal.skill, proposal.parameters
        # A dialog action is not a generic screen click.  Its preconditions
        # and result verification belong to QuestDialogSkill, dispatched via
        # M0SkillDispatcher.  This fail-closed guard prevents an un-migrated
        # caller from bypassing the normalized action and quest-id checks.
        if name in {"QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "OBJECT_USE", "USE", "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION"}:
            raise ValueError(f"{name} must be executed by its canonical quest skill")
        if name in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            from .camera_controller import view_control_command
            params = {**params, "camera_action":
                "REACQUIRE_TRACK" if name == "REACQUIRE_TARGET" else params.get("camera_action")}
            return (view_control_command(params),)
        if name == "INSPECT" and params.get("camera_pan"):
            if not self.available(proposal, world):
                raise ValueError("Camera search preconditions missing")
            from .camera_controller import view_control_command
            return (view_control_command({**params, "camera_action": "INSPECT_REGION",
                                          "target_x": params.get("x"),
                                          "target_y": params.get("y")}),)
        if name == "INSPECT" and params.get("map_zoom_in"):
            if not self.available(proposal, world):
                raise ValueError("World Map zoom preconditions missing")
            return (Command("MAP_ZOOM_IN", x=params["x"], y=params["y"]),)
        if name == "INSPECT" and params.get("map_step_out"):
            if not self.available(proposal, world):
                raise ValueError("World Map parent-step preconditions missing")
            return (Command("MAP_STEP_OUT", x=params["x"], y=params["y"], button="RIGHT"),)
        if name == "WAIT":
            return ()
        if name == "TARGET" and params.get("restore_last_target"):
            return (Command("BIND", "TARGETLASTTARGET"),)
        if name in {"TARGET", "GATHER", "HERB", "MINE", "USE", "INSPECT"}:
            return (Command("HOVER" if name == "INSPECT" else "CLICK", x=params["x"], y=params["y"],
                            button="RIGHT" if name in {"GATHER", "HERB", "MINE", "USE"} else "LEFT"),)
        if name == "REPAIR":
            return (Command("CLICK", x=params["x"], y=params["y"]),)
        if name in {"BUY_VENDOR", "SELL_VENDOR"}:
            return (Command("CLICK", x=params["x"], y=params["y"], button="RIGHT"),)
        if name == "OPEN_BAGS":
            return (Command("BIND", "OPENALLBAGS"),)
        if name == "DEATH_RECOVERY":
            return (Command("CLICK", x=params["x"], y=params["y"]),)
        if name == "LOOT" and params.get("corpse_anchor"):
            return (Command("CLICK", x=params["x"], y=params["y"], button="RIGHT"),)
        if name in {"LOOT", "INTERACT", "TALK", "ACQUIRE_TARGET"}:
            return (Command("BIND", "TARGETNEARESTENEMY" if name == "ACQUIRE_TARGET" else "INTERACTTARGET"),)
        if name in {"FISH", "MOUNT", "DISMOUNT"}:
            return (Command("BIND", params["binding"]),)
        if name in {"CLOSE_MAP", "OPEN_MAP"}:
            # TOGGLEWORLDMAP is not intrinsically idempotent.  Recheck the
            # current fast-lane state at dispatch so a delayed/replayed
            # proposal cannot invert an already achieved state.
            map_open = _world_map_open(world.state)
            if ((name == "CLOSE_MAP" and map_open is False)
                    or (name == "OPEN_MAP" and map_open is True)):
                return ()
            return (Command("BIND", "TOGGLEWORLDMAP"),)
        if name in {"COMBAT", "DEFEND"}:
            action = self.combat_action(world.state, record=True)
            if self.combat.needs_facing_recovery(world.state):
                # A WoW facing error proves the target is outside the forward
                # half-plane. A bounded ~pi-radian turn in either direction
                # places it inside the forward half-plane; split it into safe
                # <=350 ms input pulses, then retry the chosen ability in the
                # same verified combat attempt.
                pulse = min(.35, max(.2, math.pi / max(.5, self.turn_rate) / 3.))
                commands = [Command("BIND", "TURNLEFT", pulse) for _ in range(3)]
                self.combat.record_facing_recovery(world.state)
                if action is not None:
                    commands.append(Command("BIND", action["action"]))
                return tuple(commands)
            if action is None:
                return ()
            return (Command("BIND", action["action"]),)
        if name == "ASSIST":
            action = self.beneficial_action(world.state, params.get("item_id"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "EXIT_VEHICLE":
            return (Command("BIND", "VEHICLEEXIT"),)
        if name == "VEHICLE_ABILITY":
            # Refractory clock for the planner (1 s cooldown + lunge in flight).
            pressed = world.__dict__.setdefault("vehicle_ability_pressed_at", {})
            pressed[str(params.get("spell_id"))] = world.last_received
            return (Command("BIND", str(params["binding"])),)
        if name == "USE_ON_TARGET":
            if params.get("activation_source") == "INTERACT_KEY":
                return (Command("BIND", "INTERACTTARGET"),)
            action = self.quest_item_action(world.state, params.get("item_id"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "FOLLOW_INSTRUCTION":
            action = self.instructed_action(world.state, params.get("instruction"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "ESCAPE":
            return (Command("BIND", params["binding"], min(.3, max(.05, number(params.get("duration")) or .2))),)
        if name == "RECOVER":
            # The Navigation StuckResolver selects one evidence-gated step.
            # This execution layer merely maps that explicit step to one
            # bounded input request; it never advances the recovery ladder.
            step = str(params.get("recovery_step") or "STRAFE").upper()
            if step == "BACKWARD_REVEAL":
                # ~2.5 yd: a corpse under the character model comes into view.
                return (Command("BIND", "MOVEBACKWARD", .30), Command("BIND", "MOVEBACKWARD", .30))
            if step == "BACKWARD":
                # User 2026-10-02: back off clearly, not one step.  The
                # executor caps one input step at 350 ms, so ~0.9 s backwards
                # (about 4 yd) is three consecutive steps.
                return tuple(Command("BIND", "MOVEBACKWARD", .30) for _ in range(3))
            if step == "TURN":
                turn = "TURNLEFT" if params.get("attempt", 0) % 2 == 0 else "TURNRIGHT"
                return (Command("BIND", turn, .14),)
            if step == "JUMP_FORWARD":
                # Keep running through the jump arc so a low obstacle is cleared.
                return (Command("BIND", "MOVEFORWARD", .30, simultaneous=("JUMP",)),
                        Command("BIND", "MOVEFORWARD", .30))
            # Strafe away from a tagged obstacle when we can see roughly
            # where it is; fall back to bounded alternation when no obstacle
            # track is currently available.
            bearing = obstacle_bearing(world.state)
            if bearing is not None:
                side = "STRAFERIGHT" if bearing < .5 else "STRAFELEFT"
            else:
                side = "STRAFELEFT" if params.get("attempt", 0) % 2 == 0 else "STRAFERIGHT"
            return (Command("BIND", side, .25, simultaneous=("JUMP",)),)
        if name == "VISUAL_APPROACH":
            # The persistent VisualApproachController owns fast commands.
            return ()
        if name == "APPROACH_TARGET":
            screen = params.get("screen_position") or world.state["target"].get("screen_position") or {}
            x = screen["x"]
            error = x-.5
            if abs(error) > .08:
                turn = "TURNRIGHT" if error > 0 else "TURNLEFT"
                return (Command("BIND", "MOVEFORWARD", min(.15, max(.06, abs(error)*.45)), simultaneous=(turn,)),)
            return (Command("BIND", "MOVEFORWARD", .2),)
        if name == "MOVE":
            pos = world.player_position()
            dx, dy = params["x"] - pos[0], params["y"] - pos[1]
            dimensions = world.state.get("map_dimensions") or {}
            width, height = number(dimensions.get("width")), number(dimensions.get("height"))
            if width and height:
                dx, dy = dx * width, dy * height
            desired = math.atan2(-dx, -dy) % math.tau
            current = float(world.state["orientation"])
            error = (desired - current + math.pi) % math.tau - math.pi
            duration = min(.25, max(.06, (world.distance(params) or 0) * 15))
            if abs(error) > .12:
                turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
                if self.bindings and not self.bindings.contains(turn):
                    raise ValueError(f"Hiányzó irányítási binding: {turn}")
                duration = min(duration, abs(error) / self.turn_rate, .18)
                return (Command("BIND", "MOVEFORWARD", duration, simultaneous=(turn,)),)
            return (Command("BIND", "MOVEFORWARD", duration),)
        raise ValueError(f"Nincs skill: {name}")

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
            at_probe = x is not None and y is not None and math.hypot(x-params["x"], y-params["y"]) <= .015
            # A fresh mouseover GUID is addon-confirmed identity and needs no cursor
            # corroboration (cursor_position is null whenever WoW is in mouse-look
            # camera mode). Tooltip-text diffs are weaker heuristics and keep
            # requiring at_probe when cursor telemetry is available.
            success = identity or (at_probe and (world_tooltip or tooltip))
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
