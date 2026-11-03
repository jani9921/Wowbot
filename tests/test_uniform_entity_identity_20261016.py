"""ID/GUID is action authority; visual tracking is only a pointer hypothesis.

Offline only: no game input, process access or invented coordinate authority.
"""
from copy import deepcopy
import json

import pytest

from adapters.telemetry_packets import PacketAssembler, normalize
from wowbot.agent.models import Attempt, Command, Observation, Prediction, Proposal
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillResult, SkillStatus, world_entity_id
from wowbot.runtime.entity_identity import check_entity_identity, template_id
from wowbot.runtime.skill_identity import guard_skill_result, pin_skill_identity
from wowbot.skills import InteractSkill, ObjectUseSkill, TargetSkill


GUID = "Creature-0-1-2175-3-156626-0000000ABC"
OTHER_GUID = "Creature-0-1-2175-3-156626-0000000ABD"
GO_GUID = "GameObject-0-1-2175-3-339568-0000000ABC"


def active(skill="TARGET", parameters=None, world=None):
    parameters = {"guid": GUID, "npc_id": 156626} if parameters is None else dict(parameters)
    world = deepcopy(world or {})
    proposal = Proposal.make(skill, "identity regression", parameters)
    attempt = Attempt("a", proposal, world, "o", 10., 18., (),
                      Prediction("p", "a", "identity", 10., 18., "o"))
    return ActiveSkillRuntime().start(
        intent=Intent(skill, parameters, world_entity_id(parameters.get("guid"))),
        attempt=attempt, now=10., before_snapshot=world)


def scene(**changes):
    unit = {"guid": GUID, "npc_id": 156626, "name": "Lady Jaina Proudmoore",
            "attackable": False, "is_attackable": False, "dead": False}
    return {"monotonic_time": 10., "target_sample_time": 10.,
            "mouseover_sample_time": 10., "cursor_sample_time": 10.,
            "target": dict(unit), "mouseover": dict(unit),
            "cursor_position": {"nx": .4, "ny": .6}, **changes}


@pytest.mark.parametrize("value", ["WORLD3D:453", "track:41", "npc:156626", "object:339568", 453, "453", "unknown"])
def test_visual_and_template_ids_never_become_instance_guids(value):
    assert world_entity_id(value) is None


@pytest.mark.parametrize("wanted,actual,matched", [
    ({"guid": GUID}, {"guid": GUID}, True),
    ({"guid": GUID}, {"guid": OTHER_GUID, "npc_id": 156626}, False),
    ({"npc_id": 156626}, {"guid": GUID}, True),  # public GUID contains the exact entry
    ({"npc_id": 156626}, {"name": "Lady Jaina Proudmoore"}, False),
    ({"npc_id": 156626}, {"guid": GUID, "npc_id": 9}, False),
    ({"object_id": 339568}, {"guid": GO_GUID}, True),
    ({"object_id": 339568}, {"object_id": 339568, "name": "Thick Cocoon"}, True),
    ({"object_id": 339568}, {"object_id": 0, "name": "Thick Cocoon"}, False),
    ({"object_id": 339568}, {"object_id": 44, "name": "Thick Cocoon"}, False),
    ({"guid": "WORLD3D:1"}, {"guid": "WORLD3D:1"}, False),
    ({}, {"guid": GUID}, False),
    ({"npc_id": True}, {"npc_id": True}, False),
    ({"object_id": "33.5"}, {"object_id": "33.5"}, False),
])
def test_one_comparison_enforces_all_constraints_without_name_override(wanted, actual, matched):
    assert bool(check_entity_identity(wanted, actual)) is matched


def test_repeated_normalization_does_not_drop_an_invalid_numeric_constraint():
    from wowbot.runtime.entity_identity import identity_fields
    from wowbot.runtime.skill_identity import expected_identity
    malformed = identity_fields({"guid": GUID, "npc_id": "not-an-npc-id"})
    actual = {"guid": GUID, "npc_id": 156626}
    assert not check_entity_identity(malformed, actual)
    assert not check_entity_identity(expected_identity(malformed), actual)
    assert not check_entity_identity({"guid": GUID}, malformed)


def test_conflicting_guid_aliases_or_pinned_target_ref_cannot_override_each_other():
    from wowbot.runtime.skill_identity import expected_identity
    conflicting = {"guid": GUID, "object_guid": OTHER_GUID}
    assert not check_entity_identity(conflicting, {"guid": GUID})
    assert not check_entity_identity({"guid": GUID}, conflicting)
    assert not check_entity_identity(expected_identity({"guid": OTHER_GUID}, GUID), {"guid": GUID})


def test_explicit_numeric_alias_is_preserved_and_cannot_override_conflicting_id():
    from wowbot.runtime.skill_identity import expected_identity
    actual = {"guid": GUID, "npc_id": 156626}
    assert check_entity_identity({"npc_id": None, "expected_npc_id": 156626}, actual)
    conflict = {"guid": GUID, "npc_id": 156626, "expected_npc_id": 9}
    assert not check_entity_identity(conflict, actual)
    assert not check_entity_identity(expected_identity(conflict), actual)


@pytest.mark.parametrize("value", [True, -1, 0, float("nan"), float("inf"), 1.1, "9" * 5000])
def test_invalid_numeric_identity_cannot_crash_or_become_proof(value):
    assert template_id(value) is None


@pytest.mark.parametrize("skill", ["INTERACT", "TALK", "COMBAT", "DEFEND", "USE_ON_TARGET",
                                   "ASSIST", "FOLLOW_INSTRUCTION", "EXTRA_ACTION", "VEHICLE_ABILITY", "APPROACH_TARGET"])
@pytest.mark.parametrize("bad", [{"guid": OTHER_GUID, "npc_id": 156626},
                                 {"guid": GUID, "npc_id": 7}])
def test_every_selected_entity_action_withholds_commands_on_wrong_guid_or_id(skill, bad):
    state = active(skill)
    pin_skill_identity(state, scene())
    result = guard_skill_result(state, scene(target=bad),
        SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "ACTIONBUTTON1"),)), 10.)
    assert result.status is SkillStatus.FAILURE
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN
    assert not result.commands


@pytest.mark.parametrize("skill", ["TARGET", "LOOT", "OBJECT_USE", "GATHER", "HERB", "MINE"])
def test_world_click_cannot_use_selected_identity_to_authorize_wrong_hover(skill):
    state = active(skill)
    pin_skill_identity(state, scene())
    result = guard_skill_result(state, scene(mouseover={"guid": OTHER_GUID, "npc_id": 156626}),
        SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR"),)), 10.)
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN and not result.commands


def test_same_guid_survives_new_visual_track_id_but_same_template_different_guid_does_not():
    before = scene()
    before["target"]["visual_track_id"] = "WORLD3D:222"
    state = active("INTERACT", world=before)
    after = scene()
    after["target"]["visual_track_id"] = "WORLD3D:453"
    after["mouseover"]["visual_track_id"] = "WORLD3D:237"
    skill = InteractSkill()
    assert skill.begin(state, after).commands[0].binding == "INTERACTTARGET"
    assert skill._fresh_hover(after, GUID, 9.8)
    changed = scene(target={"guid": OTHER_GUID, "npc_id": 156626})
    assert not guard_skill_result(state, changed,
        SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),)), 10.).commands


def test_target_handoff_checks_numeric_id_and_never_waits_for_a_new_box_when_proof_is_fresh():
    parameters = {"guid": GUID, "npc_id": 156626, "x": .4, "y": .6,
                  "ground_truth_handoff": True, "click_current_cursor": True,
                  "hover_x": .7, "hover_y": .7, "track_id": "WORLD3D:453"}
    run = active(parameters=parameters, world=scene())
    started = TargetSkill().begin(run, scene())
    assert [command.kind for command in started.commands] == ["CLICK_CURRENT_CURSOR"]
    wrong = scene(target={"guid": GUID, "npc_id": 1})
    assert TargetSkill().verify(run, wrong, 10.1).reason is FailureReason.IDENTITY_UNCERTAIN


def test_target_name_or_track_only_never_clicks():
    run = active(parameters={"expected_name": "Jaina", "track_id": "WORLD3D:453", "x": .4, "y": .6})
    result = TargetSkill().begin(run, scene())
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN and not result.commands


def test_object_name_can_hint_search_but_cannot_certify_use_without_object_id():
    expected = {"object_id": 339568, "tdb_object_name": "Thick Cocoon", "expected_tooltips": ["cocoon"]}
    mouse = {"name": "Thick Cocoon", "quest_related": True, "quest_id": 55639}
    assert ObjectInteractionFlow.mouseover_search_hint(expected, mouse)
    assert not ObjectInteractionFlow.mouseover_matches(expected, mouse)
    assert not ObjectUseSkill._identity_matches(expected, mouse)
    assert ObjectInteractionFlow.mouseover_matches(expected, {**mouse, "object_id": 339568})


def test_object_instance_is_pinned_across_retries_not_rebound_by_same_template_id():
    world = scene(mouseover={"guid": GO_GUID, "object_id": 339568})
    run = active("OBJECT_USE", {"object_id": 339568}, world)
    wanted = dict(pin_skill_identity(run, world))
    other = {**world, "mouseover": {"guid": GO_GUID[:-1] + "D", "object_id": 339568}}
    result = guard_skill_result(run, other,
        SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR", button="RIGHT"),)), 10.)
    assert not result.commands
    assert run.skill_context["entity_identity"] == wanted


def test_thick_cocoon_without_guid_can_be_used_with_public_object_id_and_verified_credit():
    quest = {"quest_id": 55639, "objectives": [{"objective_id": "0", "current": 0,
                                               "required": 5, "is_complete": False}]}
    world = scene(mouseover={"object_id": 339568, "name": "Thick Cocoon",
                             "quest_related": True, "quest_id": 55639}, active_quests=[quest])
    run = active("OBJECT_USE", {"object_id": 339568, "x": .4, "y": .6,
                               "quest_ids": [55639], "objective_ids": ["55639:0"]}, world)
    skill = ObjectUseSkill()
    assert [cmd.kind for cmd in skill.begin(run, world).commands] == ["HOVER"]
    confirmed = {**world, "monotonic_time": 10.2, "mouseover_sample_time": 10.2,
                 "cursor_sample_time": 10.2}
    assert [(cmd.kind, cmd.button) for cmd in skill.verify(run, confirmed, 10.2).commands] == [("CLICK", "RIGHT")]
    assert "guid" not in run.skill_context["entity_identity"]
    completed = deepcopy(confirmed)
    completed["active_quests"][0]["objectives"][0]["current"] = 1
    assert skill.verify(run, completed, 10.4).status is SkillStatus.SUCCESS


def test_soft_object_activation_checks_both_template_and_instance():
    soft = {"source_unit": "softinteract", "guid": GO_GUID, "object_id": 339568, "unit_type": "GAMEOBJECT"}
    world = scene(soft_targets=[soft], soft_targets_sample_time=10.)
    parameters = {"object_guid": GO_GUID, "object_id": 339568, "activation_source": "INTERACT_KEY",
                  "quest_ids": [55639]}
    assert ObjectUseSkill().begin(active("OBJECT_USE", parameters, world), world).commands[0].binding == "INTERACTTARGET"
    wrong = scene(soft_targets=[{**soft, "object_id": 77}], soft_targets_sample_time=10.)
    rejected = ObjectUseSkill().begin(active("OBJECT_USE", parameters, world), wrong)
    assert not rejected.commands


def test_visual_approach_probe_cannot_interact_with_a_competing_soft_recipient():
    from wowbot.agent.visual_approach import VisualApproachController
    from wowbot.agent.visual_approach_types import VisualApproachPhase
    controller = VisualApproachController()
    controller.intent = {"guid": GUID, "npc_id": 156626, "purpose": "INTERACT"}
    controller.phase = VisualApproachPhase.OCCLUDED
    world = scene(soft_targets=[{"source_unit": "softinteract", "guid": OTHER_GUID, "npc_id": 156626}],
                  soft_targets_sample_time=10.)
    assert not any(command.binding == "INTERACTTARGET" for command in controller.command(world, "o", 10.))


def test_facing_keeps_guid_when_box_changes_and_stops_for_another_instance():
    from wowbot.navigation.facing import FaceController, FaceStatus
    face = FaceController()
    face.begin({"guid": GUID, "track_id": "WORLD3D:1"}, 10.)
    assert face.tick({"guid": GUID, "track_id": "WORLD3D:999", "x": .5}, 10.1).status is FaceStatus.ALIGNED
    assert face.tick({"guid": OTHER_GUID, "track_id": "WORLD3D:999", "x": .5}, 10.2).status is FaceStatus.TARGET_LOST


@pytest.mark.parametrize("change", [
    {"target": {}},
    {"target": {"guid": OTHER_GUID, "npc_id": 156626}},
    {"target": {"guid": GUID, "npc_id": 9}},
    {"target_sample_time": 8.},
])
def test_visual_approach_stops_when_live_identity_is_lost_even_if_box_stays(change):
    from wowbot.agent.visual_approach import VisualApproachController
    controller = VisualApproachController()
    box = {"source": "WORLD3D", "track_id": "WORLD3D:41", "x": .54, "y": .5,
           "confidence": .9, "observed_at": 10., "lifecycle": "ACTIVE",
           "bbox_height_fraction": .03}
    world = scene(visual_candidates=[box])
    controller.start({"guid": GUID, "npc_id": 156626, "track_id": box["track_id"],
                      "purpose": "INTERACT"}, world, "v1", 10.)
    assert any(command.binding == "MOVEFORWARD" for command in controller.command(world, "v1", 10.))
    lost = {**world, **change}
    # Direct fast-lane refresh of the same visual frame must also stop.
    assert not controller.command(lost, "v1", 10.1)
    result = controller.observe(lost, "v2", 10.1)
    assert result.terminal and not result.success


def test_guidless_object_approach_uses_real_hover_object_id_not_selected_npc():
    from wowbot.agent.visual_approach import VisualApproachController
    controller = VisualApproachController()
    controller.intent = {"purpose": "INTERACT", "object_use_approach": True, "object_id": 339568}
    # The selected NPC is unrelated; a GameObject need not be a selected unit.
    world = scene(mouseover={"object_id": 339568, "name": "Thick Cocoon"})
    assert controller._approach_identity_check(world, 10.)
    assert not controller._approach_identity_check(scene(mouseover={"name": "Thick Cocoon"}), 10.)


def test_guidless_object_pin_upgrades_when_public_guid_arrives_and_never_rebinds():
    first = scene(mouseover={"object_id": 339568})
    run = active("OBJECT_USE", {"object_id": 339568}, first)
    assert "guid" not in pin_skill_identity(run, first)
    confirmed = scene(mouseover={"object_id": 339568, "guid": GO_GUID})
    click = SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR", button="RIGHT"),))
    assert guard_skill_result(run, confirmed, click, 10.).commands
    assert run.skill_context["entity_identity"]["guid"] == GO_GUID
    another = scene(mouseover={"object_id": 339568, "guid": GO_GUID[:-1]+"D"})
    assert not guard_skill_result(run, another, click, 10.).commands
    assert run.skill_context["entity_identity"]["guid"] == GO_GUID


@pytest.mark.parametrize("skill", ["VEHICLE", "VEHICLE_ABILITY"])
def test_targeted_vehicle_input_uses_same_identity_gate_but_targetless_actions_do_not(skill):
    from wowbot.skills.vehicle import VehicleSkill
    world = scene(in_vehicle=True, target={"guid": OTHER_GUID, "npc_id": 156626})
    params = {"guid": GUID, "npc_id": 156626, "vehicle_actions": ["ACTIONBUTTON1"]}
    if skill == "VEHICLE":
        rejected = VehicleSkill().begin(active(skill, params, world), world)
    else:
        rejected = guard_skill_result(active(skill, params, world), world,
            SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "ACTIONBUTTON1"),)), 10.)
    assert not rejected.commands and rejected.reason is FailureReason.IDENTITY_UNCERTAIN
    targetless = guard_skill_result(active(skill, {"target_required": False}, world), world,
        SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "ACTIONBUTTON1"),)), 10.)
    assert targetless.commands


@pytest.mark.parametrize("change", [{"target": {}}, {"target_sample_time": 8.},
                                    {"target": {"guid": OTHER_GUID, "npc_id": 156626}}])
def test_intermediate_route_waypoint_does_not_drop_committed_entity_identity(change):
    from types import SimpleNamespace
    from wowbot.navigation.service import NavigationService
    navigation = NavigationService()
    # A typed NavigationRequest always carries ``timeout`` (None: no explicit budget).
    navigation._active_request = SimpleNamespace(destination={"target_guid": GUID, "npc_id": 156626}, timeout=None)
    # Intermediate destination lacks target_guid to retain the corridor path.
    navigation._movement.destination = {"route_waypoint_final": False, "x": 1., "y": 2.}
    assert navigation._entity_route_identity_matches(scene(target={"guid": GUID, "npc_id": 156626,
                                                                   "track_id": "WORLD3D:999"}), 10.)
    wrong = scene(**change)
    assert not navigation.command(wrong, "new-fast-sample", 10.)
    assessment = navigation.observe(wrong, "new-fast-sample", 10.)
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "target_identity_changed"


@pytest.mark.parametrize("update", [{"mouseover_sample_time": 8.}, {"cursor_sample_time": 8.},
                                    {"cursor_sample_time": 9.8}])
def test_stale_or_uncorrelated_cursor_identity_never_authorizes_click(update):
    run = active(world=scene())
    result = guard_skill_result(run, scene(**update),
        SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR"),)), 10.)
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN and not result.commands


def test_f7_competing_soft_identity_is_not_overridden_by_matching_hard_target():
    run = active("INTERACT", world=scene())
    world = scene(soft_targets=[{"source_unit": "softinteract", "guid": OTHER_GUID, "npc_id": 156626}],
                  soft_targets_sample_time=10.)
    result = guard_skill_result(run, world,
        SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),)), 10.)
    assert not result.commands


@pytest.mark.parametrize("skill", ["TARGET", "COMBAT", "DEFEND", "INTERACT", "TALK",
                                   "LOOT", "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION", "EXTRA_ACTION"])
def test_real_skill_boundaries_do_not_dispatch_for_a_conflicting_numeric_id(skill):
    from wowbot.skills import CombatSkill, LootSkill
    from wowbot.skills.quest_item import UseItemSkill
    from wowbot.skills.quest_tool import ExtraActionHandler
    from wowbot.skills.instructed_spell import InstructedSpellSkill
    class Bindings:
        def contains(self, binding):
            return True
    params = {"guid": GUID, "npc_id": 156626, "x": .4, "y": .6,
              "ground_truth_handoff": True, "click_current_cursor": True,
              "quest_ids": [7], "objective_ids": ["7:0"], "item_id": 44,
              "binding": "ACTIONBUTTON1", "instruction": "Cast Execute now", "spell_id": 5308,
              "extra_action_type": "spell", "extra_action_id": 99, "target_required": True}
    hostile = skill in {"COMBAT", "DEFEND", "FOLLOW_INSTRUCTION"}
    unit = {"guid": GUID, "npc_id": 9, "attackable": hostile,
            "dead": skill == "LOOT", "health": 50}
    world = scene(target=unit, mouseover=unit, actionbar=[{
        "kind": "item" if skill in {"USE_ON_TARGET", "ASSIST"} else "spell",
        "id": 44 if skill in {"USE_ON_TARGET", "ASSIST"} else 5308,
        "name": "Execute", "action": "ACTIONBUTTON1", "is_usable": True,
        "cooldown_remaining": 0, "in_range": True, "is_harmful": hostile}],
        extra_action={"visible": True, "usable": True, "action": "EXTRAACTIONBUTTON1",
                      "action_type": "spell", "action_id": 99})
    implementation = {"TARGET": TargetSkill(), "COMBAT": CombatSkill(Bindings()),
        "DEFEND": CombatSkill(Bindings()), "INTERACT": InteractSkill(), "TALK": InteractSkill(),
        "LOOT": LootSkill(), "USE_ON_TARGET": UseItemSkill(Bindings()), "ASSIST": UseItemSkill(Bindings()),
        "FOLLOW_INSTRUCTION": InstructedSpellSkill(Bindings()), "EXTRA_ACTION": ExtraActionHandler(Bindings())}[skill]
    run = active(skill, params, world)
    result = (implementation.begin(run, world, 10.) if skill in {"COMBAT", "DEFEND"}
              else implementation.begin(run, world))
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN and not result.commands


def test_explicit_npc_id_mismatch_cannot_be_repaired_by_kill_subject_name():
    from wowbot.agent.entity_objective_flows import KillObjectiveFlow
    from wowbot.agent.quest_semantics import target_matches_objective
    from types import SimpleNamespace
    raw = {"description": "Defeat Murlocs", "target_entity": {"npc_id": 150229}}
    unit = {"guid": "Creature-other", "npc_id": 1, "name": "Murloc Watershaper", "attackable": True}
    assert not target_matches_objective(unit, raw)
    objective = SimpleNamespace(raw=raw, description=raw["description"], target_entity=raw["target_entity"])
    assert not KillObjectiveFlow.matches_target(objective, unit)


def test_dialog_owner_is_not_replaced_by_selected_target_or_visual_track():
    before = scene(quest_ui={"npc_guid": GUID})
    run = active("QUEST_DIALOG", {"quest_id": 7}, before)
    pin_skill_identity(run, before)
    command = SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=.2, y=.3),))
    assert guard_skill_result(run, before, command, 10.).commands
    wrong = scene(target={"guid": GUID}, quest_ui={"npc_guid": OTHER_GUID})
    assert not guard_skill_result(run, wrong, command, 10.).commands


def test_soft_interact_proposal_can_validate_soft_identity_with_a_different_hard_target():
    from wowbot.agent.skills import SkillRegistry
    world = WorldModel()
    soft = {"source_unit": "softinteract", "guid": GUID, "npc_id": 156626,
            "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    payload = scene(target={"guid": OTHER_GUID}, soft_targets=[soft], soft_targets_sample_time=10.)
    world.ingest(Observation.create({**payload, "timestamp": 10., "session_id": "s"}, 10.))
    proposal = Proposal.make("INTERACT", "soft NPC", {"soft_guid": GUID, "npc_id": 156626,
                                                       "activation_source": "SOFT_INTERACT"})
    assert SkillRegistry().available(proposal, world)
    assert SkillRegistry().commands(proposal, world)[0].binding == "INTERACTTARGET"
    run = active("INTERACT", proposal.parameters, payload)
    assert InteractSkill().begin(run, payload).commands[0].binding == "INTERACTTARGET"


def test_no_input_quest_credit_verification_can_finish_after_despawn():
    run = active("OBJECT_USE", {"object_id": 339568}, scene())
    verified = SkillResult(SkillStatus.SUCCESS, evidence=("objective_changed:55639:0",))
    assert guard_skill_result(run, {}, verified, 11.) is verified


def test_coordinate_search_and_ui_only_skills_do_not_require_an_unrelated_entity():
    for skill in ("MOVE", "SEEK_VISUAL_CUE", "INSPECT", "QUEST_DIALOG", "FIELD_TURN_IN", "FISH", "MOUNT"):
        run = active(skill, {})
        result = SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "ACTIONBUTTON1"),))
        checked = guard_skill_result(run, {}, result, 10.)
        assert checked.status is SkillStatus.RUNNING and checked.commands == result.commands


def test_nested_public_tooltip_id_survives_normalization_without_guessing_generic_id():
    state = normalize({"mouseover": {"tooltip_data": {"id": 12, "object_id": 339568}}})
    assert state["mouseover"]["object_id"] == 339568
    assert not normalize({"mouseover": {"tooltip_data": {"id": 12}}})["mouseover"].get("npc_id")


def test_packet_without_hover_does_not_refresh_old_hover_time():
    assembler = PacketAssembler()
    full = {"monotonic_time": 1., "timestamp": 1001., "character_guid": "Player-1",
            "mouseover": {"object_id": 339568}, "mouseover_sample_time": 1.}
    first = assembler.feed("AIPC5|s|1|0|1|STATE|" + json.dumps(full), 1.)
    fast = assembler.feed('AIPC5|s|2|0|1|FAST|{"monotonic_time":10}', 10.)
    assert "mouseover_sample_time" not in fast
    model = WorldModel()
    model.ingest(Observation.create(first, 1.))
    model.ingest(Observation.create({**fast, "timestamp": 1010.}, 10.))
    assert model.state["mouseover_sample_time"] == 1.


@pytest.mark.parametrize("lane", ["STATE", "FAST"])
def test_explicit_unknown_sample_times_are_not_repaired_from_packet_time(lane):
    world = WorldModel()
    payload = scene(transport_kind=lane, timestamp=1010., session_id="s",
                    target_sample_time=None, mouseover_sample_time=None, cursor_sample_time=None)
    evidence = Observation.create(payload, 10.)
    before = deepcopy(evidence.payload)
    assert world.ingest(evidence)
    assert evidence.payload == before
    for key in ("target_sample_time", "mouseover_sample_time", "cursor_sample_time"):
        assert world.state[key] is None
    checked = guard_skill_result(active("TARGET", world=payload), world.state,
        SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR"),)), 10.)
    assert not checked.commands and checked.reason is FailureReason.IDENTITY_UNCERTAIN


def test_compact_lua_object_id_and_soft_identity_round_trip():
    from test_agent_transport import lua_runtime
    for limit in (850, 1800, 3500):
        lua = lua_runtime()
        lua.execute('''data={monotonic_time=10,timestamp=1010,character_guid="Player-1",
          player_present=true,is_in_combat=false,player_world_position={x=100,y=-200,instance_id=2175},
          mouseover={guid="GameObject-0-1-2175-3-339568-0000000ABC",object_id=339568,
            name="Thick Cocoon",quest_related=true,quest_id=55639,tooltip=string.rep("long ",500)},
          cursor_position={nx=.4,ny=.6},soft_targets={{source_unit="softinteract",object_id=339568,
            guid="GameObject-0-1-2175-3-339568-0000000ABC",unit_type="GAMEOBJECT"}}}''')
        packet, _ = lua.eval(f"ns.NextLanePackets(data,data,{limit},850)")
        body = json.loads(packet.split("|", 6)[6])
        assert len(packet.encode()) <= limit + 100
        assert body["mouseover"]["object_id"] == 339568
        if limit >= 1800:
            assert body["soft_targets"][0]["object_id"] == 339568
            assert body["soft_targets"][0]["guid"] == GO_GUID


def test_soft_object_guid_can_be_read_even_when_unit_exists_is_false_without_secret_bypass():
    from pathlib import Path
    from test_agent_transport import lua_runtime
    source = (Path(__file__).resolve().parents[1] / "addon/AIPlayerControllerExport/AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = source.index("local function readSoftTargets()")
    end = source.index("\nend", start) + len("\nend")
    object_start = source.index("local function objectIdFromGuid(")
    object_end = source.index("\nend", object_start) + len("\nend")
    for secret in (False, True):
        lua = lua_runtime()
        result = lua.execute('''
          local function accessible(value) return canaccessvalue(value) end
          local function readUnit() return nil end -- UnitExists is false for this object
          local function safeCall(fn, ...) local value=fn(...); if accessible(value) then return value end end
          local function guidType(guid) return guid:match("^GameObject%-") and "OBJECT" end
          function UnitName() return "Thick Cocoon" end
          function UnitGUID(token)
            if token ~= "softinteract" then return nil end
            return ''' + ('{secret=true}' if secret else '"' + GO_GUID + '"') + '''
          end
        ''' + source[object_start:object_end] + "\n" + source[start:end] + "\nreturn readSoftTargets()")
        if secret:
            assert len(result) == 0
        else:
            assert result[1]["guid"] == GO_GUID and result[1]["object_id"] == 339568
