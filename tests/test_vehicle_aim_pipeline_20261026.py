"""12:57--13:07 live regression: selected targets, pitch correction lost to WAIT.

Exercise the shared planner/ranker, commitment, navigation and command gate,
not just ServerVehicleCombatPolicy's unfiltered proposal.
"""
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.autonomy_loop import AutonomousLoop, CommittedSubgoal
from wowbot.agent.hover_control import COUPLED, HoverControl
from wowbot.agent.models import Goal, Observation
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.vehicle_abilities import CLOSE, choose_attack_action
from wowbot.agent.vehicle_combat_planning import ServerVehicleCombatPolicy
from wowbot.agent.world import WorldModel
from wowbot.navigation.service import NavigationService
from wowbot.runtime.supervisor import Supervisor


GUID = "Creature-0-3769-2444-47-193994-0000DF407F"
VEHICLE = "Vehicle-0-3769-2444-47-186771-00005F4023"
BARK = dict(action="ACTIONBUTTON1", id=382778, name="Burning Bark", max_range=20.,
            source="VEHICLE_BAR", is_usable=True, is_harmful=True, cooldown_remaining=0., in_range=False)
SPEED = dict(action="ACTIONBUTTON2", id=383137, name="Speed of Flight", max_range=0.,
             description="Increases your movement speed for a short time.",
             source="VEHICLE_BAR", is_usable=True, cooldown_remaining=0.)
LIFE = dict(action="ACTIONBUTTON3", id=383133, name="Call of Life", max_range=60.,
            description="Call insects of the Ruby Lifeshrine to attack enemies in front of the whelpling.",
            source="VEHICLE_BAR", is_usable=True, cooldown_remaining=0.)


@pytest.fixture
def scene(monkeypatch):
    # Rounded live 12:59:25 geometry: target 9.7 yd away, ahead, but below.
    monkeypatch.setitem(COUPLED, "186771", True)
    monkeypatch.setattr("wowbot.agent.vehicle_abilities.db2_trajectory", lambda ids: 382778 in ids)
    position = dict(x=1583.46, y=-289.22, z=266.35, z_known=True, z_observed=True,
                    source="PACKET_CLIENT_MOVEMENT", coordinate_space="WORLD_YARDS", instance_id=2444)
    unit = dict(x=1579.38, y=-296.50, z=261.38, guid=GUID, quest_id="70061",
                objective_id="70061:1", instance_id=2444, entry_id=193994)
    state = dict(session_id="vehicle-aim-regression", monotonic_time=100., map_id=2022,
                 player_present=True, vehicle_controls=True, in_vehicle=True, vehicle_guid=VEHICLE,
                 orientation=4.2678, player_world_position=position, movement=dict(flying=True),
                 server_mode=dict(selected=True, active=True), is_in_combat=False,
                 target=dict(guid=GUID, npc_id=193994, name="Agitated Weedling", attackable=True, dead=False),
                 target_sample_time=100., actionbar=[dict(BARK), dict(SPEED), dict(LIFE)],
                 active_quests=[dict(quest_id=70061, title="Training Wings", is_complete=False,
                    objectives=[dict(type="KILL", raw_type="monster", description="2/12 Agitated Weedling slain",
                                     current=2, required=12, is_complete=False)])])
    state["packet_vehicle_pose"] = dict(position=position, pitch=-.0048, facing=state["orientation"],
                                         sample_time=100., vehicle_mover=True, can_fly=True, flying=True)
    monkeypatch.setattr("wowbot.agent.vehicle_combat_planning.kill_objective_units", lambda state: [unit])
    return state, unit


def world_for(state):
    world = WorldModel()
    world.ingest(Observation.create(state, state["monotonic_time"]))
    # These are already merged sensor fields, as in the live telemetry dump.
    world.state.update(state)
    return world


@pytest.mark.parametrize("combat", [False, True])
def test_selected_target_aim_survives_planner_commitment_and_fires_after_alignment(scene, combat):
    state, unit = scene
    state["is_in_combat"] = combat
    world = world_for(state)
    registry, goal = SkillRegistry(), Goal.parse("Questelj", 100.)
    planner = Planner(registry)
    proposals = planner.candidates(goal, world, 100.)
    aim = proposals[0]
    assert (aim.skill, aim.parameters.get("purpose")) == ("MOVE", "VEHICLE_AIM")
    assert Supervisor.combat_admissible(aim.skill, aim.parameters)
    loop = AutonomousLoop()
    loop.commitment = CommittedSubgoal("target", goal.goal_id, "70061:1", "TARGET", GUID,
                                       None, ("70061:1",), "TARGET", 100., 100.)
    assert loop._matching(aim, world)
    assert loop.choose(proposals, aim, goal, world, 100.).skill == "MOVE"

    # A new measured pitch, not merely having sent a movement command.
    p = state["player_world_position"]
    world.state["packet_vehicle_pose"]["pitch"] = math.atan2(unit["z"]-p["z"], math.hypot(unit["x"]-p["x"], unit["y"]-p["y"]))
    press = planner.candidates(goal, world, 100.1)[0]
    assert press.skill == "VEHICLE_ABILITY"
    assert [c.binding for c in registry.commands(press, world)] == ["ACTIONBUTTON1"]
    world.state["target"] = {"guid": "Creature-0-3769-2444-47-194142-00005F3FED"}
    with pytest.raises(ValueError, match="IDENTITY_UNCERTAIN"):
        registry.commands(press, world)


@pytest.mark.parametrize("aim_in_place", [False, True])
def test_air_navigation_preserves_height_and_aim_through_the_real_service(scene, monkeypatch, aim_in_place):
    state, unit = scene
    policy = ServerVehicleCombatPolicy()
    move = (policy._aim(state, unit) if aim_in_place else policy._approach(state, unit, 12., "approach"))
    nav = NavigationService()
    # The hover target already has a measured/derived air height. A ground
    # query here changed it to the floor in the recording.
    def no_floor(*args, **kwargs):
        pytest.fail("an explicit hover destination must not be resolved onto the ground")
    monkeypatch.setattr(nav._z, "resolve_target", no_floor)
    nav.start_skill_request("MOVE", dict(move.parameters), state, "aim-owner", 100.)
    assert isinstance(nav._movement.flight, HoverControl)
    assert nav._movement.flight.face["z"] == unit["z"]
    assert nav._movement.destination["z"] == move.parameters["hover_point"]["z"]
    assert nav._active_request.correlation_id == "aim-owner"
    commands = nav.command(state, "next", 100.1)
    assert commands and any(c.binding == "SITORSTAND" for c in commands)


def test_can_fly_vehicle_keeps_flight_contract_when_addon_flying_flag_flickers(scene):
    state, unit = scene
    state["movement"]["flying"] = False
    move = ServerVehicleCombatPolicy._aim(state, unit)
    guarded = NavigationProposalAdapter._guard_physical_move(move, SimpleNamespace(state=state))
    assert guarded.parameters["require_navmesh"] is False
    assert not Supervisor.combat_admissible("MOVE", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION"})


def test_real_three_button_bar_never_uses_speed_or_empty_slots_as_an_attack(scene):
    state, _ = scene
    state["actionbar"].append(dict(action="ACTIONBUTTON4", id=0, source="VEHICLE_BAR", is_usable=True))
    learned = {"382778": {"miss_entries": {"193994": 4}}}
    assert choose_attack_action(state, learned)["id"] == LIFE["id"]
    state["actionbar"][0]["cooldown_remaining"] = 2.
    state["actionbar"][2]["cooldown_remaining"] = 8.
    assert choose_attack_action(state, learned) is None


def test_area_ability_keeps_its_mode_when_used_against_server_identified_unit(scene):
    state, _ = scene
    (press,) = ServerVehicleCombatPolicy().propose(state, LIFE, cooling=False, mode=CLOSE)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["use_mode"] == CLOSE


def test_all_attacks_cooling_report_the_ability_instead_of_picking_the_speed_buff(scene):
    state, _ = scene
    state["actionbar"][0]["cooldown_remaining"] = 2.
    state["actionbar"][2]["cooldown_remaining"] = 8.
    world = world_for(state)
    (wait,) = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 100.), world, 100.)
    assert wait.skill == "WAIT" and wait.parameters["spell_id"] == BARK["id"]
    assert wait.parameters["waiting_for"] == ["VEHICLE_ABILITY_READY"]
    assert "Burning Bark" in wait.reason


def test_vertical_approach_is_not_suppressed_as_arrived_on_the_same_xy(scene):
    state, unit = scene
    # Hover point shares the player's XY, but its height is still far away.
    unit.update(x=state["player_world_position"]["x"]+6., y=state["player_world_position"]["y"], z=220.)
    world = world_for(state)
    selected = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 100.), world, 100.)[0]
    assert selected.skill == "MOVE" and selected.parameters.get("hover_point")
