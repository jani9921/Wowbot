"""Executable skill vocabulary for docs/QUEST_PLAYBOOKS.md.

These describe possible stages, not permission to run them. Existing proposal
policies supply candidates and the skill registry/executor verify readiness.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookStep:
    name: str
    skills: tuple[str, ...]
    expected: str
    preconditions: tuple[str, ...] = ("live_candidate_and_skill_preconditions",)
    # Design spec 32.4: a conditional branch is entered only while its
    # condition holds and never blocks the next step; an alternative is the
    # OR of another step (either verified lets the chain continue).
    condition: str | None = None
    alternative_of: str | None = None


@dataclass(frozen=True)
class QuestPlaybook:
    mechanism: str
    steps: tuple[PlaybookStep, ...]
    missing: tuple[str, ...] = ()


APPROACH = PlaybookStep("APPROACH", ("MOVE", "REACH_OBJECT", "REACH_LOCATION",
    "APPROACH_TARGET", "VISUAL_APPROACH"), "arrival_and_facing_verified")
TARGET = PlaybookStep("TARGET", ("TARGET", "ACQUIRE_TARGET", "REACQUIRE_TARGET"), "target_identity_verified")
TALK = PlaybookStep("TALK", ("INTERACT", "TALK"), "dialog_or_quest_progress")
DIALOG = PlaybookStep("DIALOG", ("QUEST_DIALOG",), "quest_linked_dialog_transition")
OBSERVE = PlaybookStep("OBSERVE", ("WAIT_EVENT",), "objective_progress_or_event_transition",
    ("quest_linked_event_is_active",))
FIGHT = PlaybookStep("FIGHT", ("COMBAT", "DEFEND"), "target_death_or_threat_removed")
LOOT = PlaybookStep("LOOT", ("LOOT",), "loot_or_objective_progress", ("own_lootable_corpse",))
# A kill credits without loot unless our corpse is lootable (32.4 branch).
LOOT_IF_LOOTABLE = PlaybookStep("LOOT", ("LOOT",), "loot_or_objective_progress", ("own_lootable_corpse",),
                                condition="own_lootable_corpse")
USE_OBJECT = PlaybookStep("USE_OBJECT", ("OBJECT_USE", "INTERACT"), "quest_object_credit")
USE_ITEM = PlaybookStep("USE_ITEM", ("USE_ON_TARGET", "ASSIST", "EXTRA_ACTION"), "quest_item_objective_progress")
BOARD = PlaybookStep("BOARD", ("INTERACT", "TALK", "QUEST_DIALOG"), "vehicle_or_scripted_transport_started")
VEHICLE = PlaybookStep("VEHICLE_ACTION", ("VEHICLE_ABILITY",), "vehicle_cast_or_objective_progress",
    ("vehicle_controls_and_exact_action_ready",))


def _book(mechanism, steps, *missing):
    return QuestPlaybook(mechanism, steps, missing)


PLAYBOOKS = {
    "KILL": _book("KILL", (APPROACH, TARGET, FIGHT, LOOT_IF_LOOTABLE)),
    "KILL_LABEL": _book("KILL_LABEL", (APPROACH, TARGET, FIGHT, LOOT_IF_LOOTABLE), "label_entity_resolution"),
    "PROGRESS_BAR": _book("PROGRESS_BAR", (APPROACH, TARGET, FIGHT, LOOT_IF_LOOTABLE)),
    "COLLECT_DROP": _book("COLLECT_DROP", (APPROACH, TARGET, FIGHT, LOOT)),
    "COLLECT_OBJECT": _book("COLLECT_OBJECT", (APPROACH, USE_OBJECT, LOOT)),
    "COLLECT_VENDOR": _book("COLLECT_VENDOR", (APPROACH, TALK, DIALOG,
        PlaybookStep("PURCHASE", ("BUY_VENDOR",), "purchase_and_objective_progress"))),
    "COLLECT_SPELL": _book("COLLECT_SPELL", (APPROACH, TARGET, USE_ITEM), "script_only_item_source"),
    "TALK": _book("TALK", (APPROACH, TALK, DIALOG, OBSERVE)),
    "WITNESS": _book("WITNESS", (APPROACH, TALK, DIALOG, OBSERVE), "conversation_end_signal"),
    "GOSSIP_ACTOR": _book("GOSSIP_ACTOR", (APPROACH, TALK, DIALOG, FIGHT)),
    "OBJECT_USE": _book("OBJECT_USE", (APPROACH, USE_OBJECT)),
    "CREDIT_OBJECT": _book("CREDIT_OBJECT", (TALK, DIALOG, APPROACH, USE_OBJECT)),
    "INTERACT": _book("INTERACT", (APPROACH, USE_OBJECT)),
    "USE_ITEM": _book("USE_ITEM", (APPROACH, TARGET, USE_ITEM), "ground_object_mixed_target_adapter"),
    "SPELLCLICK": _book("SPELLCLICK", (APPROACH, BOARD)),
    "SPELLCLICK_VEHICLE": _book("SPELLCLICK_VEHICLE", (APPROACH, BOARD, VEHICLE)),
    "VEHICLE_ABILITY": _book("VEHICLE_ABILITY", (APPROACH, BOARD, VEHICLE)),
    "MOUNT": _book("MOUNT", (PlaybookStep("MOUNT", ("MOUNT",), "mounted_verified"),)),
    "NPC_TRANSPORT": _book("NPC_TRANSPORT", (APPROACH, BOARD, OBSERVE)),
    "ARRIVE": _book("ARRIVE", (APPROACH,), "alternate_landing_search"),
    "AREA_TRIGGER": _book("AREA_TRIGGER", (APPROACH,), "complete_trigger_to_objective_resolution"),
    # REV4 P8.5: every mechanism-specific policy is a step of its book.
    "ESCORT": _book("ESCORT", (TALK, DIALOG,
        PlaybookStep("FOLLOW", ("MOVE", "WAIT_EVENT"), "escort_actor_progress", ("escort_actor_identity",)),
        PlaybookStep("DEFEND", ("TARGET", "COMBAT", "DEFEND"), "escort_threat_removed_or_progress",
                     ("escort_attacker_targets_escort",), condition="escort_attacker_targets_escort"),
        PlaybookStep("RESTART", ("ADDON_ACTION",), "failed_quest_abandoned_then_reaccepted",
                     ("quest_log_failed",), condition="quest_log_failed")), "live_validation"),
    "EMOTE": _book("EMOTE", (APPROACH, TARGET,
        PlaybookStep("EMOTE", ("ADDON_ACTION",), "emote_objective_progress",
                     ("addon_quest_action_emote_applied", "user_binding"))), "live_validation"),
    "COLLECT_CONTAINER": _book("COLLECT_CONTAINER", (
        PlaybookStep("OPEN_CONTAINER", ("OPEN_BAGS", "USE_ON_TARGET"), "container_loot_window_or_credit",
                     ("tdb_item_loot_container_in_bags",)),
        PlaybookStep("LOOT", ("LOOT",), "loot_or_objective_progress", ("loot_window_open",),
                     condition="loot_window_open")), "live_validation"),
    "ESCORT_FOLLOW": _book("ESCORT_FOLLOW", (APPROACH,
        PlaybookStep('FOLLOW', ('FOLLOW', 'MOVE'), 'escort_actor_progress', ('escort_actor_identity',)),
        PlaybookStep('DEFEND', ('DEFEND', 'COMBAT', 'WAIT_EVENT'), 'escort_threat_removed_or_progress', ('escort_event_active',)), OBSERVE)),
}

# Unknown credit sources (P8.1): bounded probes at the objective's POI --
# each local gossip NPC once, then each usable object once -- then the typed
# "I don't know, I'm telling you" endpoint (needs_user).  Not a guess loop.
PROBE = PlaybookStep("PROBE_TALK", ("INTERACT", "QUEST_DIALOG"),
                     "objective_progress_or_probes_exhausted", ("server_objective_poi", "local_gossip_npc"))
PROBE_OBJECT = PlaybookStep("PROBE_OBJECT", ("OBJECT_USE",), "objective_progress_or_probes_exhausted",
                            ("server_objective_poi", "server_usable_object"), alternative_of="PROBE_TALK")
for _mechanism in ("SPELL_CREDIT", "PROXY_UNKNOWN", "UNRESOLVED", "COLLECT_OTHER", "CRITERIA_TREE"):
    PLAYBOOKS[_mechanism] = _book(_mechanism, (APPROACH, PROBE, PROBE_OBJECT, OBSERVE), "credit_source")

# Written playbooks with no complete execution adapter remain explicitly absent.
for _mechanism, _missing in {
    "PET_BATTLE": "pet_battle_handler", "PVP": "pvp_handler",
    "RESOURCE": "resource_handler", "LEARN_SPELL": "trainer_handler", "OTHER": "mechanism_handler",
}.items():
    PLAYBOOKS[_mechanism] = _book(_mechanism, (), _missing)


# REV4 P8.2: recovery edges.  A failed step's typed reason names the step
# that repairs it, instead of only avoiding the failed option.  Reasons are
# the terminal reasons the skills report (lower case, free form); a class
# groups them.  An edge only biases among proposals that already exist.
FAILURE_CLASSES = {
    "TARGET_MISSING": ("target_not_found", "target_lost", "identity_uncertain", "invalid_target",
                       "reach_object_identity_or_position_lost", "target_moved"),
    "OUT_OF_RANGE": ("out_of_range", "no_reach_intent", "route_endpoint_outside_arrival_envelope",
                     "arrival_not_confirmed"),
    "FACING": ("facing_failed", "facing_wrong_way", "line_of_sight"),
    "ROUTE": ("required_navmesh_route_unavailable", "no_route", "path_blocked", "supported_stuck", "stuck",
              "server_position_probe_timeout", "flight_plan_no_landing_spot", "post_plan_feedback_timeout"),
    "NO_ITEM": ("expected_item_not_received", "quest_item_missing", "item_missing", "no_item",
                "item_not_in_bags"),
    "NO_CREDIT": ("quest_credit_not_received", "objective_not_progressing"),
    "NO_RESPONSE": ("no_response", "not_interactable", "wrong_ui", "loot_ui_not_opened"),
}

# (failed step, class) -> steps that repair it, most specific first.  "*"
# matches any failed step.  The failed option itself stays avoided.
RECOVERY_EDGES = {
    ("TARGET", "TARGET_MISSING"): ("APPROACH",),          # search / approach, then target again
    ("FIGHT", "TARGET_MISSING"): ("TARGET", "APPROACH"),  # reacquire the lost target
    ("*", "TARGET_MISSING"): ("TARGET", "APPROACH"),
    ("*", "OUT_OF_RANGE"): ("APPROACH",),
    ("APPROACH", "FACING"): ("TARGET", "APPROACH"),
    ("*", "FACING"): ("APPROACH",),
    ("*", "ROUTE"): ("APPROACH",),                        # another approach option
    ("*", "NO_ITEM"): ("LOOT", "FIGHT", "USE_OBJECT", "PURCHASE"),   # collect it first
    ("USE_ITEM", "NO_CREDIT"): ("TARGET", "APPROACH"),    # another subject
    ("*", "NO_CREDIT"): ("TARGET", "TALK", "USE_OBJECT"),
    ("*", "NO_RESPONSE"): ("APPROACH", "TALK"),
}


# Design spec 32.1 MechanicRegistry names for our mechanisms (diagnostics).
REGISTRY_NAMES = {
    "KILL": "KILL_TARGET", "COLLECT_DROP": "KILL_FOR_ITEM", "KILL_LABEL": "KILL_FOR_CREDIT",
    "PROGRESS_BAR": "KILL_FOR_CREDIT", "OBJECT_USE": "INTERACT_GAMEOBJECT", "INTERACT": "INTERACT_GAMEOBJECT",
    "CREDIT_OBJECT": "USE_OBJECT_AND_WAIT", "TALK": "INTERACT_NPC", "GOSSIP_ACTOR": "GOSSIP_SELECT",
    "USE_ITEM": "USE_ITEM_ON_TARGET", "COLLECT_SPELL": "CAST_ON_TARGET", "COLLECT_OBJECT": "COLLECT_WORLD_OBJECT",
    "COLLECT_VENDOR": "COLLECT_WORLD_OBJECT", "COLLECT_CONTAINER": "LOOT_CORPSE",
    "AREA_TRIGGER": "AREA_TRIGGER", "ARRIVE": "EXPLORE_LOCATION", "SPELLCLICK": "ENTER_VEHICLE",
    "SPELLCLICK_VEHICLE": "ENTER_VEHICLE", "VEHICLE_ABILITY": "VEHICLE_ABILITY", "ESCORT": "ESCORT",
    "ESCORT_FOLLOW": "FOLLOW_NPC", "EMOTE": "EMOTE", "WITNESS": "WAIT_FOR_STATE",
    "NPC_TRANSPORT": "SCRIPTED_SEQUENCE", "MOUNT": "SCRIPTED_SEQUENCE",
}


def registry_name(mechanism, item_target_mode=None) -> str:
    """The spec registry name; unknown sources are UNKNOWN_MECHANIC, never a guess."""
    if mechanism == "USE_ITEM":
        return {"SELF": "USE_ITEM_SELF", "GROUND": "USE_ITEM_AT_LOCATION"}.get(str(item_target_mode),
                                                                            "USE_ITEM_ON_TARGET")
    return REGISTRY_NAMES.get(str(mechanism), "UNKNOWN_MECHANIC")


def failure_class(reason) -> str | None:
    text = str(reason or "").casefold()
    for name, words in FAILURE_CLASSES.items():
        if any(text == word or text.startswith(word + ":") for word in words):
            return name
    return None


def recovery_steps(step: str, reason) -> tuple[str, tuple[str, ...]] | None:
    """(class, repairing steps) for one failed step, or None."""
    kind = failure_class(reason)
    if kind is None:
        return None
    steps = RECOVERY_EDGES.get((str(step), kind)) or RECOVERY_EDGES.get(("*", kind))
    return (kind, steps) if steps else None
