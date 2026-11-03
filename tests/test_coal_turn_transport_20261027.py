"""22:02 coal / 22:08 Wrathion: real executor limits, useful turns and ride handoff."""
from copy import deepcopy
from types import SimpleNamespace
import math
import time

import pytest

from wowbot.agent.bindings import BindingsCache
from wowbot.agent.executor import InputExecutor
from wowbot.agent.models import Command
from wowbot.agent.movement_controller import ReachMovementController
from wowbot.agent.objective_speech_planning import ObjectiveSpeechHold
from wowbot.agent.objective_transport import transport_entries
from wowbot.agent.reference_knowledge import ReferenceKnowledge
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.runtime import SkillStatus
from wowbot.skills.defend_wait import DefendWaitSkill
from test_input_scheduler import Backend
from test_server_arrival_facing_20261021 import ready_controller, enter_facing, seen


DRAGON = "Vehicle-0-1461-2534-147807-191669-00006112D8"


def riding(*, named=True):
    return {"session_id": "new-transport", "monotonic_time": 100., "map_id": 2022,
        "orientation": 0., "movement": {"moving": False}, "is_in_combat": False,
        "player_world_position": {"x": 0., "y": 0., "z": 174., "z_observed": True,
                                  "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "soft_targets": [{"source_unit": "softinteract", "guid": DRAGON,
                          **({"name": "Wrathion", "npc_id": 191669} if named else {})}],
        "soft_targets_sample_time": 100., "target": False, "mouseover": False,
        "active_quests": [{"quest_id": 66057, "is_complete": False, "objectives": [
            {"description": "1/1 Speak with Wrathion", "is_complete": True, "current": 1},
            {"description": "0/1 Travel with Wrathion to the Throne", "is_complete": False, "current": 0}]}],
        "reference_knowledge": {"quests": {"66057": {"objectives": []}}},
        "packet_entities": {DRAGON: {"guid": DRAGON, "kind": "VEHICLE", "entry_id": 191669, "map_id": 2444,
            "info": {"npc_flags": 1}, "unit": {"health": 100, "created_by_me": True},
            "position": {"x": 3., "y": 0., "z": 174., "source": "PACKET_CREATE_MOVEMENT"}}}}


def test_slow_but_improving_turn_gets_time_without_failing_and_waiting_between_turns():
    controller = ready_controller()
    enter_facing(controller)
    for at, facing in ((1.5, 1.3), (3., 1.), (4.5, .6)):
        result = controller.observe(seen(facing, at), str(at), at)
        assert not result.terminal
        assert all(c.binding in {"TURNLEFT", "TURNRIGHT"} for c in controller.command(seen(facing, at), str(at), at))
    result = controller.observe(seen(.1, 5.5), "finally-facing", 5.5)
    assert result.terminal and result.success


def test_turn_progress_cannot_extend_the_total_budget_indefinitely():
    controller = ready_controller()
    enter_facing(controller)
    for at, angle in ((1., 1.4), (3., 1.2), (5., 1.), (7., .8)):
        assert not controller.observe(seen(angle, at), str(at), at).terminal
    result = controller.observe(seen(.6, 9.), "hard-limit", 9.)
    assert result.terminal and not result.success and result.reason == "facing_failed"


@pytest.mark.parametrize("gap", [.01, .2, .57, 1., 2.])
def test_final_approach_commands_obey_the_real_executor_minimum(gap):
    controller = ReachMovementController()
    state = {"orientation": 0., "movement": {"speed": 14., "moving": True},
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2444, "sample_time": 10.}}
    controller.start({"x": 3.+gap, "y": 0., "instance_id": 2444, "coordinate_space": "WORLD_YARDS",
                      "face_on_arrival": True, "stop_distance": 3.}, state, "start", 10.)
    controller.observe(state, "pose", 10.)
    commands = controller.command(state, "forward", 10.)
    assert commands  # no vacuous pass when a positive final gap never gets a step
    assert all(.04 <= c.duration <= .35 for c in commands)
    assert all(c.forward_duration is not None and .04 <= c.forward_duration <= .35 for c in commands)


def test_precision_forward_lease_is_released_by_the_real_scheduler_without_new_frames(tmp_path):
    path = tmp_path/"bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(path), backend)
    try:
        executor.execute_movement((Command("BIND", "MOVEFORWARD", .05, forward_duration=.05),))
        deadline = time.monotonic()+.3
        while backend.down.get("W") and time.monotonic() < deadline:
            time.sleep(.005)
        assert backend.down["W"] is False
        assert executor.scheduler.background_error is None
    finally:
        executor.close()


def test_travel_with_an_actor_resolves_the_current_vehicle_and_requests_boarding():
    state = riding()
    assert transport_entries(state) == {"191669": "66057"}
    (use,) = ServerNpcInteractionPolicy().propose(state)
    assert use.skill == "INTERACT" and use.parameters["soft_guid"] == DRAGON
    assert use.parameters["interaction_kind"] == "RIDE"
    assert use.parameters["expected_result"] == "VEHICLE_ENTERED"
    state["player_world_position"]["x"] = -20.
    state["soft_targets"] = []
    state["reference_knowledge"]["entities"] = {"191669": {"reference": {"name": "Wrathion"}}}
    (move,) = ServerNpcInteractionPolicy().propose(state)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == DRAGON


@pytest.mark.parametrize("change", ["wrong-name", "removed", "foreign", "not-vehicle", "done", "stale"])
def test_named_travel_does_not_authorize_an_unrelated_vehicle(change):
    state = riding()
    if change == "wrong-name":
        state["soft_targets"][0]["name"] = "Another Dragon"
    elif change == "removed":
        state["packet_entities"][DRAGON]["removed"] = True
    elif change == "foreign":
        state["packet_entities"][DRAGON]["map_id"] = 1
    elif change == "not-vehicle":
        state["packet_entities"][DRAGON]["kind"] = "CREATURE"
    elif change == "done":
        state["active_quests"][0]["objectives"][1]["is_complete"] = True
    else:
        state["soft_targets_sample_time"] = 90.
    assert transport_entries(state) == {}


def test_cached_catalogue_names_current_server_vehicles_without_hover_or_hard_target():
    calls = []
    catalog = SimpleNamespace(raw=None, status="READY", npc=lambda entry: calls.append(entry) or
        {"npc_id": entry, "name": "Wrathion"}, quest=lambda qid: None, records=lambda *args: [])
    entities = SimpleNamespace(get_profile=lambda key: None, guids=lambda key: [],
        locations=lambda *args, **kw: [], visual_observations=lambda *args, **kw: [])
    reference = ReferenceKnowledge(catalog, entities)
    state = riding(named=False)
    state["reference_knowledge"] = reference.snapshot(state, 100.)
    assert state["reference_knowledge"]["entities"]["191669"]["reference"]["name"] == "Wrathion"
    assert transport_entries(state) == {"191669": "66057"}
    reference.snapshot(state, 100.1)
    assert calls == [191669]


def test_transport_catalogue_lookup_is_bounded_and_handles_unknown_vehicle_distance():
    calls = []
    catalog = SimpleNamespace(raw=None, status="READY", npc=lambda entry: calls.append(entry) or
        {"npc_id": entry, "name": "Wrathion"}, quest=lambda qid: None, records=lambda *args: [])
    entities = SimpleNamespace(get_profile=lambda key: None, guids=lambda key: [],
        locations=lambda *args, **kw: [], visual_observations=lambda *args, **kw: [])
    reference = ReferenceKnowledge(catalog, entities)
    state = riding(named=False)
    original = state["packet_entities"][DRAGON]
    original["distance"] = None
    for index in range(6):
        guid = f"Vehicle-0-1461-2534-147807-{191670+index}-00006112D8"
        state["packet_entities"][guid] = {**deepcopy(original), "guid": guid,
            "entry_id": 191670+index, "unit": {"health": 100, "created_by_me": False},
            "distance": float(index)}
    snapshot = reference.snapshot(state, 100.)
    assert calls == [191669, 191670, 191671, 191672]
    assert len(snapshot["entities"]) == 4


def test_final_turn_progress_is_exposed_for_live_diagnostics():
    controller = ready_controller()
    enter_facing(controller)
    controller.observe(seen(1.1, 1.5), "turn-improved", 1.5)
    facing = controller.snapshot()["final_facing"]
    assert facing["last_progress_at"] == 1.5
    assert facing["best_error_radians"] == pytest.approx(1.1)
    assert facing["no_progress_timeout_seconds"] < facing["total_budget_seconds"]


def test_speech_hold_finishes_when_the_next_objective_requires_travel_with_the_speaker():
    state = riding()
    hold = ObjectiveSpeechHold()
    before = deepcopy(state)
    before["active_quests"][0]["objectives"] = [{"description": "Speak with Wrathion", "is_complete": False}]
    before["quest_ui"] = {"open": True}
    hold.propose(before)
    state["events"] = [{"event_type": "NPC_INSTRUCTION", "sequence": 1,
                        "payload": {"sender": "Wrathion", "message": "Be swift!"}}]
    assert hold.propose(state) == []
    active = SimpleNamespace(intent=SimpleNamespace(parameters={"quest_ids": [66057],
        "objective_kind": "NPC_SPEECH", "speaker_name": "wrathion"}),
        before_snapshot=deepcopy(state), skill_context={}, attempt=SimpleNamespace(deadline=120.), phase=None)
    skill = DefendWaitSkill()
    skill.begin(active, state, 100.)
    result = skill.verify(active, state, 101.)
    assert result.status is SkillStatus.CANCELLED and result.replan_required
