"""User-recorded forge/fragment failures: server identity, pose and bounded retries."""
from copy import deepcopy
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.movement_controller import ReachMovementController
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.packet_entity_facts import objective_objects, server_object_interactable
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, linked_object_entries
from wowbot.runtime import SkillStatus
from wowbot.skills.object_use import ObjectUseSkill
from test_linked_big_object_20261027 import large
from test_linked_quest_object_20261026 import TABLE


FORGE = "GameObject-0-1461-2534-147807-377013-000060A8EF"
SCENERY = "GameObject-0-1461-2534-147807-383636-000060A8EF"


def forge(*, corner=False):
    # Coordinates, types and links from telemetry-20261027-180155, rows 100/209.
    state = {
        "session_id": "forge-run", "monotonic_time": 100., "map_id": 2022, "orientation": 1.4235,
        "soft_targets": [], "soft_targets_sample_time": 100.,
        "movement": {"moving": False, "speed": 0.},
        "player_world_position": {"x": 2131.23, "y": 2691.23, "z": 207.38,
                                  "z_known": True, "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 66056, "is_complete": False, "objectives": [
            {"description": "0/1 Earth-Warder's Forge Activated", "current": 0, "is_complete": False}]}],
        "reference_knowledge": {"quests": {"66056": {"objectives": [
            {"objective_id": 423854, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 194540,
             "description": "Earth-Warder's Forge Activated"}]}}},
        "packet_entities": {}}
    for guid, entry, kind, x, y, z in (
            (SCENERY, 383636, 5, 2132.6633, 2696.0754, 210.0223),
            (FORGE, 377013, 22, 2128.6946, 2719.1338, 206.9892)):
        state["packet_entities"][guid] = {
            "guid": guid, "entry_id": entry, "kind": "GAMEOBJECT", "map_id": 2444,
            "info": {"go_type": kind, "quest_objective_id": 423854},
            "dynamic_flags": {"value": 49668},
            "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_STATIONARY"}}
    if corner:
        state["player_world_position"].update(x=2118.07, y=2708.70)
        state["orientation"] = .6409
        state["soft_targets"] = [{"source_unit": "softinteract", "guid": FORGE}]
    return state


def test_actual_forge_beats_nearer_same_objective_scenery_in_both_planners_and_dispatch():
    state = forge()
    assert linked_object_entries(state) == {"377013": "66056"}
    known = {o["guid"]: o["usable"] for o in objective_objects(state, 66056)}
    assert known == {SCENERY: False, FORGE: True}
    spot, known = ObjectInteractionFlow().packet_use_spot(state, 66056, 207.38)
    assert known and spot["guid"] == FORGE
    (move,) = ServerNpcInteractionPolicy().propose(state)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == FORGE
    assert not server_object_interactable(state, SCENERY)
    assert not ObjectUseSkill.packet_object_usable({"object_guid": SCENERY}, state)


@pytest.mark.parametrize("go_type", [5, 6, 8])
def test_activate_does_not_turn_a_passive_type_into_an_interaction_target(go_type):
    state = forge()
    state["packet_entities"][SCENERY]["info"]["go_type"] = go_type
    assert "383636" not in linked_object_entries(state)
    assert not server_object_interactable(state, SCENERY)


def test_unknown_or_new_server_entry_is_not_replaced_with_a_tdb_id():
    state = forge()
    value = state["packet_entities"].pop(FORGE)
    guid = FORGE.replace("377013", "987654")
    value.update(guid=guid, entry_id=987654)
    value["info"]["go_type"] = 99
    state["packet_entities"][guid] = value
    (move,) = ServerNpcInteractionPolicy().propose(state)
    assert move.parameters["object_id"] == 987654
    assert move.parameters["server_entity_guid"] == guid


def test_fresh_exact_client_recipient_can_confirm_a_scripted_passive_type():
    state = forge()
    state["soft_targets"] = [{"source_unit": "softinteract", "guid": SCENERY}]
    assert server_object_interactable(state, SCENERY)
    state["soft_targets_sample_time"] = 90.
    assert not server_object_interactable(state, SCENERY)


def test_large_surface_recipient_stops_move_even_far_from_the_centre():
    state = forge(corner=True)
    flow = ObjectInteractionFlow()
    walk = {"purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": 66056, "server_entity_guid": FORGE}
    assert flow.object_move_handoff(state, walk, 207.38)["kind"] == "SERVER_QUEST_OBJECT_READY"
    (use,) = ServerNpcInteractionPolicy(flow).propose(state)
    assert use.skill == "OBJECT_USE" and use.parameters["object_guid"] == FORGE
    assert ObjectUseSkill.packet_object_usable(use.parameters, state)
    stale = deepcopy(state)
    stale["soft_targets_sample_time"] = 90.
    assert flow.object_move_handoff(stale, walk, 207.38) is None


def test_fragment_behind_the_player_requires_an_in_place_turn_despite_exact_soft_guid():
    state = large(soft=TABLE, x=12., facing=0.)
    (turn,) = ServerNpcInteractionPolicy().propose(state)
    assert turn.skill == "MOVE" and turn.parameters["face_on_arrival"]
    assert turn.parameters["stop_distance"] >= 2.
    controller = ReachMovementController()
    controller.start(turn.parameters, state, "start", 10.)
    for i in range(1, 5):
        controller.observe(state, str(i), 10.+i*.1)
    commands = controller.command(state, "face", 10.5)
    assert commands and all(c.binding in {"TURNLEFT", "TURNRIGHT"} for c in commands)
    state["orientation"] = math.pi
    (use,) = ServerNpcInteractionPolicy().propose(state)
    assert use.skill == "OBJECT_USE"


def test_failed_edge_is_not_relearned_or_used_and_a_navmesh_probe_replaces_the_centre():
    domain = QuestDomain()
    flow = domain.location_policy.object_interaction
    state = large()
    flow._learn_packet_reach(TABLE, 377106, 5.5)
    domain.note_object_interaction_result({"action_id": "bad-use", "skill": "OBJECT_USE",
        "outcome": "FAILURE", "reason": "quest_credit_not_received", "object_guid": TABLE}, state, {})
    (probe,) = domain.server_npcs.propose(state)
    p = probe.parameters
    assert probe.skill == "MOVE" and p["object_approach_probe"] == 1 and p["require_navmesh"]
    assert (p["x"], p["y"]) != (10., 0.)
    assert p["face_towards"]["x"] == 10.
    assert flow.object_move_handoff(state, p, 10.) is None
    assert flow.packet_use_range({"guid": TABLE, "object_id": 377106}) == 3.5
    # A successful probe is navigation only: next approach still targets the same GUID.
    moved = deepcopy(state)
    moved["player_world_position"].update(x=p["x"], y=p["y"], z=p["z"])
    moved["orientation"] = math.atan2(-p["y"], 10.-p["x"])
    domain.note_object_interaction_result({"skill": "MOVE", "outcome": "SUCCESS"}, moved, p)
    (next_step,) = domain.server_npcs.propose(moved)
    assert next_step.skill == "MOVE" and not next_step.parameters.get("object_approach_probe")
    assert next_step.parameters["server_entity_guid"] == TABLE


def test_unreachable_probes_are_finite_and_never_change_the_target_identity():
    domain = QuestDomain()
    state = large()
    flow = domain.location_policy.object_interaction
    flow.packet_approach_search().reject(state, TABLE)
    points = set()
    for i in range(6):
        (probe,) = domain.server_npcs.propose(state)
        p = probe.parameters
        assert probe.skill == "MOVE" and p["server_entity_guid"] == TABLE
        assert p["require_navmesh"] and p["object_approach_probe"]
        points.add((p["x"], p["y"]))
        domain.note_object_interaction_result({"skill": "MOVE", "outcome": "FAILURE",
                                               "reason": "no_route"}, state, p)
    assert len(points) == 6
    assert domain.server_npcs.propose(state) == []
    # Only new quest progress/context reopens the search, not repeated planning.
    state["active_quests"][0]["objectives"][0]["current"] = 1
    (step,) = domain.server_npcs.propose(state)
    assert step.skill == "MOVE" and not step.parameters.get("object_approach_probe")


def test_failed_move_at_a_huge_model_starts_a_probe_without_blind_f7():
    domain = QuestDomain()
    state = forge()
    (move,) = domain.server_npcs.propose(state)
    domain.note_object_interaction_result({"skill": "MOVE", "outcome": "FAILURE",
                                           "reason": "supported_stuck"}, state, move.parameters)
    (probe,) = domain.server_npcs.propose(state)
    assert probe.skill == "MOVE" and probe.parameters.get("object_approach_probe")
    assert probe.parameters["server_entity_guid"] == FORGE


@pytest.mark.parametrize("change", ["floor", "removed", "map"])
def test_rejected_contact_does_not_authorize_another_floor_removed_or_foreign_object(change):
    state = large()
    if change == "floor":
        state["player_world_position"]["z"] = 30.
    elif change == "removed":
        state["packet_entities"][TABLE]["removed"] = True
    else:
        state["packet_entities"][TABLE]["map_id"] = 999
    search = ObjectInteractionFlow().packet_approach_search()
    search.reject(state, TABLE)
    point = {"guid": TABLE, "x": 10., "y": 0., "z": 10., "instance_id": 2444}
    assert search.goal(state, point) == {}


def active_use(state, params):
    return SimpleNamespace(intent=SimpleNamespace(parameters=params, objective_ref="66048:0", target_ref=None),
        skill_type="OBJECT_USE", skill_context={}, started_at=10., phase=None,
        before_snapshot=deepcopy(state), attempt=SimpleNamespace(deadline=20.))


def test_packet_use_waits_for_a_new_stopped_pose_then_sends_exactly_one_f7():
    state = large(soft=TABLE)
    state["movement"] = {"moving": True}
    (proposal,) = ServerNpcInteractionPolicy().propose(state)
    active = active_use(state, proposal.parameters)
    skill = ObjectUseSkill()
    assert not skill.begin(active, state).commands
    state.update(monotonic_time=11., soft_targets_sample_time=11.)
    assert not skill.verify(active, state, 11.).commands
    state["movement"]["moving"] = False
    result = skill.verify(active, state, 11.1)
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.binding) for c in result.commands] == [("BIND", "INTERACTTARGET")]
    assert not skill.verify(active, state, 11.2).commands


def test_waiting_for_stop_never_uses_a_changed_pose_or_an_expired_attempt():
    state = large(soft=TABLE)
    state["movement"] = {"moving": True}
    (proposal,) = ServerNpcInteractionPolicy().propose(state)
    active = active_use(state, proposal.parameters)
    skill = ObjectUseSkill()
    skill.begin(active, state)
    state.update(monotonic_time=11., soft_targets_sample_time=11., orientation=math.pi)
    state["movement"]["moving"] = False
    result = skill.verify(active, state, 11.)
    assert result.status is SkillStatus.FAILURE and not result.commands
    state["orientation"] = 0.
    state.update(monotonic_time=21., soft_targets_sample_time=21.)
    result = skill.verify(active, state, 21.)
    assert result.status is SkillStatus.FAILURE and not result.commands


def test_a_late_stop_still_leaves_time_to_verify_the_single_use():
    state = large(soft=TABLE)
    state["movement"] = {"moving": True}
    (proposal,) = ServerNpcInteractionPolicy().propose(state)
    active = active_use(state, proposal.parameters)
    skill = ObjectUseSkill()
    skill.begin(active, state)
    state.update(monotonic_time=19., soft_targets_sample_time=19.)
    state["movement"]["moving"] = False
    assert skill.verify(active, state, 19.).commands
    state.update(monotonic_time=20.1, soft_targets_sample_time=20.1)
    result = skill.verify(active, state, 20.1)
    assert result.status is SkillStatus.RUNNING and not result.commands


def test_npc_behind_the_mounted_player_is_turned_to_before_interacting():
    state = forge()
    state["packet_entities"] = {}
    guid = "Creature-0-1461-2534-147807-186493-0000E0A8EF"
    state["player_world_position"].update(x=3., y=0., z=10.)
    state.update(orientation=0., is_mounted=True)
    state["packet_entities"][guid] = {"guid": guid, "entry_id": 186493, "kind": "CREATURE", "map_id": 2444,
        "quest_giver": {"reward_ready": True}, "position": {"x": 0., "y": 0., "z": 10.}}
    state["soft_targets"] = [{"source_unit": "softinteract", "guid": guid}]
    (turn,) = ServerNpcInteractionPolicy().propose(state)
    assert turn.skill == "MOVE" and turn.parameters["stop_distance"] > 3.
    state["orientation"] = math.pi
    (interact,) = ServerNpcInteractionPolicy().propose(state)
    assert interact.skill == "INTERACT" and interact.parameters["soft_guid"] == guid


@pytest.mark.parametrize("speed", [7.35, 14.])
def test_final_interaction_forward_lease_cannot_pass_the_stop_envelope(speed):
    state = {"monotonic_time": 10., "orientation": 0., "movement": {"moving": True, "speed": speed},
        "player_world_position": {"x": 0., "y": 0., "z": 10., "z_observed": True,
                                  "sample_time": 10., "instance_id": 2444}}
    controller = ReachMovementController()
    controller.start({"coordinate_space": "WORLD_YARDS", "instance_id": 2444, "x": 5., "y": 0.,
                      "stop_distance": 3., "face_on_arrival": True}, state, "start", 10.)
    controller.observe(state, "pose", 10.)
    (command,) = controller.command(state, "first", 10.)
    assert command.binding == "MOVEFORWARD" and command.duration <= 2./speed
    # A new vision/orientation observation may not refresh W from an old position.
    controller.observe(state, "same-position", 10.5)
    assert not controller.command(state, "same-position", 10.5)
    assert controller.phase.name != "ARRIVED"  # braking itself proves no arrival


def test_final_in_place_facing_does_not_jump_for_an_unneeded_height_sample():
    from test_server_arrival_facing_20261021 import ready_controller, enter_facing, seen
    controller = ready_controller(require_navmesh=True, z_known=True, z=2.)
    enter_facing(controller)
    state = seen(math.pi/2, .5)
    state["packet_telemetry"] = {"enabled": True}
    commands = controller.command(state, "turn-without-height-jump", .5)
    assert commands and all(c.binding in {"TURNLEFT", "TURNRIGHT"} for c in commands)


def test_old_stopped_pose_does_not_keep_forward_held_while_speed_is_still_unknown():
    state = {"monotonic_time": 10., "orientation": 0., "movement": {"moving": False, "speed": 0.},
        "player_world_position": {"x": 0., "y": 0., "sample_time": 10., "instance_id": 2444}}
    controller = ReachMovementController()
    controller.start({"coordinate_space": "WORLD_YARDS", "instance_id": 2444, "x": 5., "y": 0.,
                      "stop_distance": 3., "face_on_arrival": True}, state, "start", 10.)
    controller.observe(state, "pose", 10.)
    (command,) = controller.command(state, "first-pulse", 10.)
    assert command.binding == "MOVEFORWARD" and command.duration <= .1
    controller.observe(state, "vision-same-pose", 10.2)
    assert not controller.command(state, "vision-same-pose", 10.2)
    state["player_world_position"].update(x=.5, sample_time=10.3)
    controller.observe(state, "new-pose", 10.3)
    assert controller.command(state, "new-pose", 10.3)[0].binding == "MOVEFORWARD"


@pytest.mark.parametrize("end,reachable", [((10., 0., 10.5), True),
                                           ((3., 0., 10.), False), ((10., 0., 6.), False)])
def test_probe_navmesh_path_must_reach_its_sector_and_floor(end, reachable):
    from wowbot.navigation.contracts import NavigationRequest
    from wowbot.navigation.global_planner import GlobalNavigator
    from wowbot.navigation.mmap_navmesh import NavMeshPath
    class Geometry:
        def supports(self, instance):
            return True
        def find_path(self, instance, start, destination):
            return NavMeshPath((start, {**destination, **dict(zip(("x", "y", "z"), end))}), 1, 0, 5.)
    state = large()
    goal = {"x": 10., "y": 0., "z": 10., "z_known": True, "instance_id": 2444,
            "coordinate_space": "WORLD_YARDS", "object_approach_probe": 1}
    route = GlobalNavigator(navmesh=Geometry()).plan(
        NavigationRequest("probe", "same-object", "MOVE_TO_LOCATION", goal), state, 10.)
    assert bool(route.anchors) is reachable
