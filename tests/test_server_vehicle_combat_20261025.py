"""Fight from a quest vehicle by server positions (live 2026-10-23 01:32-01:33).

Training Wings (70061) in the flying Ruby Whelpling: button 1 "Burning
Bark" (harmful, 20 yd).  The vehicle MOVE was forced onto the navmesh
(none for a flying vehicle), COMBAT/DEFEND reported unsupported_mechanic,
and the three description-less TDB kill rows matched no live objective.
"""
from types import SimpleNamespace

from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.vehicle_combat_planning import ServerVehicleCombatPolicy
from wowbot.runtime.supervisor import Supervisor

WEEDLING = "Creature-0-3769-2444-47-193994-00005A9A11"
PUPSTINGER = "Creature-0-3769-2444-47-194142-00005A9A92"
BARK = {"action": "ACTIONBUTTON1", "binding_primary": "1", "id": 382778, "name": "Burning Bark",
        "description": "Fires an engulfing fireball at nearby weeds, inflicting 4,410 damage.",
        "is_harmful": True, "is_usable": True, "kind": "spell", "max_range": 20, "min_range": 0,
        "source": "VEHICLE_BAR", "cooldown_remaining": 0, "in_range": False}


def kill_row(entry, name, objective_id):
    return {"credit_kind": "CREATURE_CREDIT", "credit_name": name, "credit_object_id": entry,
            "description": "", "named_creatures": [], "objective_id": objective_id, "raw_type": 0}


def state(*, target=None, in_range=False, flying=True, orientation=0., weedling_x=1612.):
    return {
        "monotonic_time": 100., "orientation": orientation, "map_id": 2022, "in_vehicle": True,
        "vehicle_controls": True, "movement": {"flying": flying},
        "player_world_position": {"x": 1577., "y": -221., "instance_id": 2444, "z_known": False},
        "actionbar": [{**BARK, "in_range": in_range}],
        "target": target or {},
        "active_quests": [{"quest_id": 70061, "is_complete": False, "objectives": [
            {"description": "1/1 Ruby Whelpling chosen", "is_complete": True},
            {"description": "0/12 Agitated Weedling slain", "is_complete": False, "raw_type": "monster", "type": "KILL"},
            {"description": "0/6 Intrusive Pupstinger slain", "is_complete": False, "raw_type": "monster", "type": "KILL"}]},
            {"quest_id": 68795, "is_complete": False, "objectives": [
                {"description": "0/1 Speak to Lord Andestrasz about Skyriding", "is_complete": False,
                 "raw_type": "monster", "type": "KILL"}]}],
        "reference_knowledge": {"quests": {
            "70061": {"objectives": [kill_row(193994, "Agitated Weedling", 429861),
                                     kill_row(194142, "Intrusive Pupstinger", 429862)]},
            "68795": {"objectives": [{"credit_kind": "CREATURE_CREDIT", "credit_name": "Lord Andestrasz",
                                      "credit_object_id": 193287, "objective_id": 1,
                                      "description": "Speak to Lord Andestrasz about Skyriding",
                                      "named_creatures": [{"entry": 193359, "name": "Lord Andestrasz"}]}]}}},
        "packet_entities": {
            WEEDLING: {"guid": WEEDLING, "kind": "CREATURE", "entry_id": 193994, "map_id": 2444,
                       "position": {"x": weedling_x, "y": -221., "z": 40.}},
            PUPSTINGER: {"guid": PUPSTINGER, "kind": "CREATURE", "entry_id": 194142, "map_id": 2444,
                         "position": {"x": 1610.6, "y": -254.9, "z": 41.}}},
    }


def test_credit_names_bind_the_hidden_kill_rows_and_talks_are_never_kills():
    wanted = kill_objective_entries(state())
    assert wanted["193994"] == ("70061", "70061:1") and wanted["194142"] == ("70061", "70061:2")
    assert not {"193287", "193359"} & set(wanted)         # "Speak to Lord Andestrasz"


def test_flies_to_the_nearest_unit_then_tabs_it():
    (move,) = ServerVehicleCombatPolicy().propose(state(), BARK, cooling=False)
    assert move.skill == "MOVE" and move.parameters["purpose"] == "VEHICLE_ATTACK_APPROACH"
    assert move.parameters["server_entity_guid"] == WEEDLING
    assert move.parameters["direct_flight"] is True and move.parameters["require_navmesh"] is False
    # Since 2026-10-26 (live 11:05, the whelp far above): hover 6 yd above
    # and 6 yd short of it, inside the 20 yd button and the Tab range.
    assert move.parameters["hover_point"] == {"x": 1606., "y": -221., "z": 46.}
    assert move.parameters["stop_distance"] == 3.0
    near = state(weedling_x=1592.)                                     # 15 yd straight ahead
    (tab,) = ServerVehicleCombatPolicy().propose(near, BARK, cooling=False)
    assert tab.skill == "TARGET" and tab.parameters["guid"] == WEEDLING
    assert tab.parameters["activation_source"] == "TAB_SERVER_GUID"


def test_presses_the_button_on_the_selected_unit_in_range_and_in_front():
    selected = {"guid": WEEDLING, "name": "Agitated Weedling", "attackable": True, "dead": False}
    (press,) = ServerVehicleCombatPolicy().propose(state(target=selected, in_range=True), BARK, cooling=False)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["binding"] == "ACTIONBUTTON1"
    assert press.parameters["guid"] == WEEDLING and press.parameters["quest_ids"] == ["70061"]
    # Facing away: turn toward it first; cooling: hold.
    (turn,) = ServerVehicleCombatPolicy().propose(
        state(target=selected, in_range=True, orientation=3.1), BARK, cooling=False)
    assert turn.skill == "MOVE" and turn.parameters["face_on_arrival"] is True
    (hold,) = ServerVehicleCombatPolicy().propose(state(target=selected, in_range=True), BARK, cooling=True)
    assert hold.skill == "WAIT"


def test_a_flying_vehicle_move_keeps_no_navmesh_and_vehicle_combat_is_admissible():
    (move,) = ServerVehicleCombatPolicy().propose(state(), BARK, cooling=False)
    world = SimpleNamespace(state={**state(), "session_id": "live"})
    guarded = NavigationProposalAdapter._guard_physical_move(move, world)
    assert guarded.parameters["require_navmesh"] is False
    on_foot = SimpleNamespace(state={**state(flying=False), "in_vehicle": False, "session_id": "live"})
    assert NavigationProposalAdapter._guard_physical_move(move, on_foot).parameters["require_navmesh"] is True
    assert Supervisor.combat_admissible("VEHICLE_ABILITY", {})
    assert Supervisor.combat_admissible("MOVE", {"purpose": "VEHICLE_ATTACK_APPROACH"})
    assert not Supervisor.combat_admissible("MOVE", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION"})


def test_any_selected_attacker_is_fought_with_the_vehicle_button_in_combat():
    raider = "Creature-0-3769-2444-47-555555-00005A9AAA"
    current = state(target={"guid": raider, "attackable": True, "dead": False}, in_range=True)
    current["is_in_combat"] = True
    current["packet_entities"][raider] = {"guid": raider, "kind": "CREATURE", "entry_id": 555555,
                                          "map_id": 2444, "position": {"x": 1590., "y": -221., "z": 40.}}
    (press,) = ServerVehicleCombatPolicy().propose(current, BARK, cooling=False)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["guid"] == raider


def test_above_the_unit_but_out_of_range_descends_in_bounded_steps():
    selected = {"guid": WEEDLING, "attackable": True, "dead": False}
    policy = ServerVehicleCombatPolicy()
    # Only a button that has also reported True means it by False (live
    # 2026-10-26: the whelp's bar said False always).
    policy.range_trusted.add(("vehicle", "ACTIONBUTTON1"))
    current = state(target=selected, in_range=False, weedling_x=1585.)   # 8 yd on the map
    (step,) = policy.propose(current, BARK, cooling=False)
    assert step.skill == "RECOVER" and step.parameters["recovery_step"] == "DESCEND"
    assert Supervisor.combat_admissible("RECOVER", step.parameters)
    (again,) = policy.propose(current, BARK, cooling=False)           # same tick: no second step
    assert again.skill == "MOVE"


def test_a_bar_that_never_said_in_range_is_judged_by_the_server_distance():
    """Live 2026-10-26 12:17: a Pupstinger 6-12 yd away for minutes, in_range
    False on every sample, and no press at all."""
    selected = {"guid": WEEDLING, "attackable": True, "dead": False}
    current = state(target=selected, in_range=False, weedling_x=1585.)   # 8 yd on the map
    (press,) = ServerVehicleCombatPolicy().propose(current, BARK, cooling=False)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["guid"] == WEEDLING


def test_the_chosen_kill_target_is_kept_unless_another_is_clearly_nearer():
    """Live 2026-10-26 14:11-14:24: the nearest mob flipped between plans."""
    from wowbot.agent import server_kill_planning as kill
    policy = kill.ServerKillTargetPolicy()
    base = {"monotonic_time": 10., "orientation": 0., "target": {}, "actionbar": [],
            "player_world_position": {"x": 0., "y": 0., "z": 0., "z_observed": True, "instance_id": 1}}
    def unit(guid, x):
        return {"guid": guid, "x": x, "y": 30., "z": 0., "instance_id": 1, "quest_id": "q", "objective_id": "q:0",
                "entry_id": 1}
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(kill, "tab_target_check", lambda *a, **k: (False, "NOT_FACING"))
        mp.setattr(kill, "kill_objective_units", lambda state: [unit("a", 10.), unit("b", 12.)])
        (first,) = policy.propose(base)
        assert first.parameters["server_entity_guid"] == "a"
        mp.setattr(kill, "kill_objective_units", lambda state: [unit("a", 12.), unit("b", 10.)])
        (kept,) = policy.propose({**base, "monotonic_time": 11.})
        assert kept.parameters["server_entity_guid"] == "a"            # b only a little nearer
        mp.setattr(kill, "kill_objective_units", lambda state: [unit("a", 60.), unit("b", 5.)])
        (switched,) = policy.propose({**base, "monotonic_time": 12.})
        assert switched.parameters["server_entity_guid"] == "b"
    finally:
        mp.undo()


def test_a_flying_kill_target_is_approached_on_the_ground_below():
    """Live 2026-10-26 14:28-14:39: proto-dragons 90-140 yd above the
    ground; walks to their point in the air had no navmesh route."""
    from wowbot.agent import server_kill_planning as kill
    import pytest
    policy = kill.ServerKillTargetPolicy()
    state = {"monotonic_time": 10., "orientation": 0., "target": {}, "actionbar": [],
             "player_world_position": {"x": 0., "y": 0., "z": 100., "z_observed": True, "instance_id": 1}}
    dragon = {"guid": "d", "x": 60., "y": 0., "z": 230., "instance_id": 1, "quest_id": "66122",
              "objective_id": "66122:1", "entry_id": 187212}
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(kill, "tab_target_check", lambda *a, **k: (False, "OUT_OF_TAB_RANGE"))
        mp.setattr(kill, "kill_objective_units", lambda state: [dragon])
        (move,) = policy.propose(state)
    finally:
        mp.undo()
    assert move.parameters["z_known"] is False and "z" not in move.parameters
    assert move.parameters["airborne_target"] is True and move.parameters["require_navmesh"] is True


def test_under_a_flying_quest_mob_tab_is_measured_in_3d_and_combat_takes_the_selected_one():
    """Live 2026-10-26 17:04-17:06: under the drake Tab said OTHER_FLOOR every
    time; after the user's Tab the agent walked toward the point in the air."""
    from wowbot.agent import server_kill_planning as kill
    import pytest
    calls = []
    def check(state, guid, player_z=None, **kw):
        calls.append(kw)
        return (True, "") if kw.get("airborne") else (False, "OTHER_FLOOR")
    state = {"monotonic_time": 10., "orientation": 0., "target": {}, "actionbar": [],
             "player_world_position": {"x": 0., "y": 0., "z": 90., "z_observed": True, "instance_id": 1}}
    drake = {"guid": "Creature-0-3769-2444-47-187212-00005F797C", "x": 5., "y": 0., "z": 110., "instance_id": 1,
             "quest_id": "66122", "objective_id": "66122:1", "entry_id": 187212}
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(kill, "tab_target_check", check)
        mp.setattr(kill, "kill_objective_units", lambda state: [drake])
        (tab,) = kill.ServerKillTargetPolicy().propose(state)
        assert tab.skill == "TARGET" and calls[-1]["airborne"] is True and calls[-1]["max_yards"] == 35.
        selected = {**state, "target": {"guid": drake["guid"]}}
        assert kill.ServerKillTargetPolicy().propose(selected) == []      # COMBAT opens it with F7
    finally:
        mp.undo()
