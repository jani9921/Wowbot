"""Vehicle buttons read from the client DB2, not from a word list (2026-10-26).

User: "van még 1 rahedli vehicle a játékba, tök jó lenne ha magától
csinálná mindet".  A button's use mode comes from its SpellEffect rows (and
from the spells the vehicle casts right after the press), so a new vehicle
needs no code.  Scene ClientActors (the Giant Boar's Monstrous Cadavers)
are hit from their DB2 spawn points with any untargeted button.
"""
import math

import pytest

import wowbot.agent.vehicle_combat_planning as planning
from wowbot.agent.vehicle_abilities import (CLOSE, FORWARD_DASH, TARGETED, ability_mode, db2_mode,
                                            learn_effect, spell_shape)
from wowbot.agent.vehicle_combat_planning import ServerVehicleCombatPolicy
from wowbot.quests.client_catalog import ClientCatalog

CATALOG = ClientCatalog()
needs_catalog = pytest.mark.skipif(not CATALOG.path.is_file(), reason="local client DB2 catalog missing")


def effects(table):
    return lambda spell: table.get(spell, [])


def test_the_structural_rules():
    table = {
        1: [{"effect": 3, "targets": [1, 0]}],                                    # scripted DUMMY
        2: [{"effect": 149, "targets": [78, 138]}],                               # CHARGE_DEST to the front
        3: [{"effect": 32, "targets": [89, 0], "trigger_spell": 4}],              # aimed missile ...
        4: [{"effect": 149, "targets": [47, 0]}],                                 # ... its impact moves nobody
        5: [{"effect": 2, "targets": [22, 15]}],                                  # damage around the caster
        6: [{"effect": 96, "targets": [6, 0]}],                                   # charge the selected enemy
        7: [{"effect": 6, "aura": 23, "trigger_spell": 5}],                       # periodic trigger -> area
        8: [{"effect": 64, "trigger_spell": 8}],                                  # a trigger loop
    }
    shape = lambda *ids: spell_shape(ids, effects(table))
    assert shape(1) is None and shape(1, 2) == FORWARD_DASH
    assert shape(3) == TARGETED and shape(5) == CLOSE and shape(6) == TARGETED
    assert shape(7) == CLOSE and shape(8) is None


@needs_catalog
def test_the_real_client_spells():
    assert db2_mode([382778]) == TARGETED            # Burning Bark: a missile at the target
    assert db2_mode([305556]) is None                # Trample button: a bare server-script DUMMY
    assert db2_mode([305556, 321627]) == FORWARD_DASH          # ... the boar's cast: CHARGE_DEST front
    trample = {"id": 305556, "name": "Unnamed", "description": "", "max_range": 0}
    assert ability_mode(trample, {"305556": {"samples": 1, "follow_up": [321627, 321628]}}) == FORWARD_DASH


def test_the_vehicles_own_casts_after_a_press_are_learned():
    learned = {}
    learn_effect(learned, 305556, {}, {}, follow_ups=[321627, None, 305556, 321628])
    learn_effect(learned, 305556, {}, {}, follow_ups=[321627])
    assert learned["305556"]["follow_up"] == [321627, 321628] and learned["305556"]["samples"] == 2


def boar_state(x, y, facing, *, current=0, at=10.):
    position = {"x": x, "y": y, "z": 84., "z_observed": True, "instance_id": 2175,
                "coordinate_space": "WORLD_YARDS", "sample_time": at}
    return {"in_vehicle": True, "monotonic_time": at, "movement": {"flying": False}, "orientation": facing,
            "player_world_position": position, "map_id": 2175, "target": {}, "actionbar": [],
            "packet_scene": {"active": True, "package_id": 2712, "scene_instance_id": 7},
            # The boar's own (ground) movement sample: a ground vehicle.
            "packet_vehicle_pose": {"position": position, "facing": facing, "pitch": 0., "flying": False,
                                    "can_fly": False, "vehicle_mover": True, "sample_time": at},
            "active_quests": [{"quest_id": 55879, "objectives": [{"current": current, "required": 8}]}]}


@pytest.fixture
def cadavers(monkeypatch):
    monkeypatch.setattr(planning, "kill_objective_units", lambda state: [])
    monkeypatch.setattr(planning, "kill_objective_entries", lambda state: {"165150": ("55879", "55879:1")})
    points = CATALOG.scene_actor_spawns(2712).get(165150) or []
    if len(points) != 8:
        pytest.skip("scene 2712 not in the local catalog")
    return points


TRAMPLE = {"action": "ACTIONBUTTON1", "id": 305556, "name": "Trample"}


@needs_catalog
def test_the_boar_lines_up_short_of_a_cadaver_then_tramples_through_it(cadavers):
    first = cadavers[0]
    policy = ServerVehicleCombatPolicy()
    (move,) = policy.propose(boar_state(first["x"]-30., first["y"], math.pi), TRAMPLE,
                             cooling=False, mode=FORWARD_DASH)
    assert move.skill == "MOVE" and move.parameters["face_towards"]["x"] == pytest.approx(first["x"])
    assert move.parameters["x"] == pytest.approx(first["x"]-12.) and move.parameters["require_navmesh"] is True
    (dash,) = policy.propose(boar_state(first["x"]-15., first["y"], 0., at=11.), TRAMPLE,
                             cooling=False, mode=FORWARD_DASH)
    assert dash.skill == "VEHICLE_ABILITY" and dash.parameters["use_mode"] == FORWARD_DASH
    assert dash.parameters["guid"] is None and dash.parameters["scene_actor"] == "36040:0"
    # The credit right after the dash crosses that cadaver off: the next one.
    (_next,) = policy.propose(boar_state(first["x"]+15., first["y"], 0., current=1, at=12.), TRAMPLE,
                              cooling=False, mode=FORWARD_DASH)
    assert "36040:0" in policy.scene_done and _next.parameters["scene_actor"] != "36040:0"


@needs_catalog
def test_a_dash_without_credit_twice_gives_the_cadaver_up(cadavers):
    first = cadavers[0]
    policy = ServerVehicleCombatPolicy()
    for at in (10., 17., 24.):
        policy.propose(boar_state(first["x"]-15., first["y"], 0., at=at), TRAMPLE, cooling=False, mode=FORWARD_DASH)
    assert policy.scene_misses["36040:0"] == 2 and "36040:0" in policy.scene_done


@needs_catalog
def test_an_around_you_button_is_used_next_to_the_actor_and_a_targeted_one_never(cadavers):
    first = cadavers[0]
    stomp = {"action": "ACTIONBUTTON2", "id": 1, "name": "Stomp"}
    (move,) = ServerVehicleCombatPolicy().propose(boar_state(first["x"]-20., first["y"], 0.), stomp,
                                                  cooling=False, mode=CLOSE)
    assert move.skill == "MOVE" and move.parameters["x"] == pytest.approx(first["x"])
    (press,) = ServerVehicleCombatPolicy().propose(boar_state(first["x"]-4., first["y"], 0.), stomp,
                                                   cooling=False, mode=CLOSE)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["use_mode"] == CLOSE
    assert ServerVehicleCombatPolicy().propose(boar_state(first["x"]-4., first["y"], 0.), stomp,
                                               cooling=False, mode=TARGETED) == []


@needs_catalog
def test_a_periodic_damage_cone_is_close():
    assert db2_mode([383133]) == CLOSE        # Call of Life: periodic trigger -> PERIODIC_DAMAGE cone


def test_a_button_that_never_credits_on_a_kind_gives_way_to_the_next():
    from wowbot.agent.vehicle_abilities import choose_attack_action
    pupstinger = "Creature-0-3769-2444-47-194142-0000DF3622"
    bar = [{"action": "ACTIONBUTTON1", "id": 382778, "name": "Burning Bark", "is_harmful": True,
            "source": "VEHICLE_BAR", "is_usable": True},
           {"action": "ACTIONBUTTON3", "id": 383133, "name": "Call of Life", "source": "VEHICLE_BAR",
            "is_usable": True}]
    state = {"vehicle_controls": True, "actionbar": bar, "target": {"guid": pupstinger}}
    learned = {}
    for _ in range(4):
        learn_effect(learned, 382778, {}, {}, target=pupstinger)
    assert learned["382778"]["miss_entries"] == {"194142": 4}
    assert choose_attack_action(state, learned)["name"] == "Call of Life"
    weed = {**state, "target": {"guid": "Creature-0-3769-2444-47-193994-0001DF2CBA"}}
    assert choose_attack_action(weed, learned)["name"] == "Burning Bark"   # still first on the weeds
