"""Skill contracts: timeouts, preconditions and costs of every agent skill.

Split out of skills.py (2026-10-05); unchanged.  ``SkillRegistry`` and the
skill mixins import ``CONTRACTS`` / ``SkillContract`` from here.
"""
from __future__ import annotations

from dataclasses import dataclass


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
