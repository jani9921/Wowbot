"""Skyriding lessons through the shared planner -> MOVE -> navigation chain."""
from wowbot.agent.skyriding_control import SkyridingControl
from wowbot.quests.scene_path_planning import QuestScenePathPolicy
from wowbot.quests.client_catalog import ClientCatalog
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.agent.models import Goal
from types import SimpleNamespace
from wowbot.navigation.service import NavigationService

DRAKE = {"slot": 13, "action": "MULTIACTIONBAR1BUTTON1", "binding_primary": "SHIFT-1",
         "kind": "summonmount", "id": 1589, "is_usable": True,
         "mount": {"mount_id": 1589, "mount_type_id": 402, "mount_usable": True}}


def lesson_state(*, mounted=False, rings=0, credits=True, airborne=False, falling=False):
    state = {
        "monotonic_time": 100., "map_id": 2022, "orientation": .05, "is_mounted": mounted,
        "movement": {"flying": airborne, "falling": falling},
        "player_world_position": {"x": 1814.5, "y": 51.2, "z": 312.9, "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS", "z_observed": True,
                                  "z_source": "PACKET_CLIENT_MOVEMENT", "sample_time": 100.},
        "active_quests": [{"quest_id": 65118, "is_complete": False, "objectives": [
            {"description": f"{rings}/5 Glide Through The Rings", "is_complete": rings >= 5},
            {"description": "0/1 Land in the Target Area", "is_complete": False},
            {"description": "1/1 Hop on your Skyriding mount or the Renewed Red Protodrake", "is_complete": True}]}],
        "actionbar": [DRAKE],
        "packet_flight": {"sample_time": 100., "pitch": 0., "forward_velocity": 0., "up_velocity": 0.,
                          "adv_flying": airborne},
    }
    if credits:
        state["packet_quest_credits"] = {"65118": {"182800": {"count": rings, "required": 5}}}
    return state


def test_the_course_data_is_the_client_path():
    glide = ClientCatalog().courses()["65118"]
    import pytest
    assert len(glide["rings"]) == 5 and glide["rings"][0][:3] == pytest.approx([1924.18, 55.56, 270.43], abs=.01)
    path = QuestScenePathPolicy().propose(lesson_state(rings=2))[0].parameters["flight_path"]
    from wowbot.navigation.flight_path import FlightPath
    assert FlightPath.from_dict(path).progress(lesson_state(rings=2)) == 2
    assert FlightPath.from_dict(path).progress(lesson_state(rings=3, credits=False)) == 3


def test_mount_first_then_one_move_for_the_whole_course():
    initial = lesson_state()
    initial["mount_capability"] = {"has_collected_mount": True, "riding_capability_confirmed": True}
    moves = QuestScenePathPolicy().propose(initial)
    assert [p.skill for p in moves] == ["MOVE"]
    proposals = TravelModePolicy().apply(moves, Goal.parse("Questelj", 100.), SimpleNamespace(state=initial), 100.)
    mount = next(p for p in proposals if p.skill == "MOUNT")
    assert mount.parameters["binding"] == "MULTIACTIONBAR1BUTTON1"
    (move,) = QuestScenePathPolicy().propose(lesson_state(mounted=True))
    assert move.skill == "MOVE" and move.parameters["purpose"] == "QUEST_SCENE_PATH"
    assert len(move.parameters["flight_path"]["waypoints"]) == 5
    later = QuestScenePathPolicy().propose(lesson_state(mounted=True, rings=3))[0]
    assert later.key == move.key            # the running flight is never replaced between rings


def test_navigation_hands_the_course_to_the_skyriding_loop():
    (move,) = QuestScenePathPolicy().propose(lesson_state(mounted=True))
    navigation = NavigationService()
    state = lesson_state(mounted=True)
    navigation.start_skill_request("MOVE", dict(move.parameters), state, "obs-1", 100.)
    assert isinstance(navigation._movement.flight, SkyridingControl)
    commands = navigation.command(state, "obs-1", 100.)
    assert [c.binding for c in commands] == ["JUMP"]                         # take off
    # Gliding is "falling" to the client: never a fall hazard on this route.
    airborne = lesson_state(mounted=True, airborne=True, falling=True)
    for at in (101., 103., 106.):
        airborne["monotonic_time"] = at
        airborne["packet_flight"]["sample_time"] = at
        assessment = navigation.observe(airborne, f"obs-{at}", at)
        assert not assessment.terminal, assessment.reason


def test_the_executor_accepts_flight_keys_only_as_bounded_leases(tmp_path):
    import time
    import pytest
    from test_agent_core import Backend, binding_file
    from wowbot.agent.executor import ExecutionError, InputExecutor
    from wowbot.agent.bindings import BindingsCache
    from wowbot.agent.models import Command
    path = binding_file(tmp_path, 'bind "INSERT" "PITCHUP"\nbind "DELETE" "PITCHDOWN"\nbind "X" "SITORSTAND"\n')
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(path), backend)
    exe.execute_movement((Command("BIND", "PITCHDOWN", .08, simultaneous=("TURNLEFT",)),))
    exe.execute_movement((Command("BIND", "JUMP", .12),))
    exe.execute_movement((Command("BIND", "SITORSTAND", .35),))
    time.sleep(.45)
    assert ("DELETE", True) in backend.calls and ("DELETE", False) in backend.calls
    assert ("X", True) in backend.calls and ("X", False) in backend.calls
    with pytest.raises(ExecutionError):
        exe.execute_movement((Command("BIND", "PITCHUP", .6),))          # beyond the lease bound
    with pytest.raises(ExecutionError):
        exe.execute_movement((Command("BIND", "ACTIONBUTTON1", .08),))   # an ability, not movement
    exe.stop_movement()
