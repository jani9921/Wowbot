"""Live 2026-10-28 12:05:11-13:04 (Black Wagon Flight 65793, "Escort the
wagon"): the server summoned our own Inconspicuous Wagon (190935) beside us;
the agent flew 535 yd to the quest POI (the destination), the wagon left its
view at 12:05:23 and the agent waited 59 min."""
from types import SimpleNamespace

from wowbot.agent.escort_planning import EscortPolicy, escort_objectives
from wowbot.runtime import SkillStatus
from wowbot.skills.defend_wait import DefendWaitSkill

WAGON = "Creature-0-1463-2444-47-190935-000061D6E7"
STATIC = "Creature-0-1463-2444-47-191020-0000616823"


def bulwark(*, wagon=(1835.1, 1157.9), player=(1840.6, 1155.5), ours=True, removed=False, t=100.):
    entities = {STATIC: {"guid": STATIC, "kind": "CREATURE", "entry_id": 191020, "map_id": 2444,
                         "position": {"x": 1836., "y": 1160., "z": 202.7}, "unit": {"health": 17248}}}
    if wagon is not None:
        entities[WAGON] = {"guid": WAGON, "kind": "CREATURE", "entry_id": 190935, "map_id": 2444,
                           "position": {"x": wagon[0], "y": wagon[1], "z": 202.7},
                           "unit": {"health": 17248, "created_by_me": ours},
                           **({"removed": {"reason": "OUT_OF_RANGE", "age": 1.}} if removed else {})}
    return {
        "monotonic_time": t, "map_id": 2022, "is_in_combat": False,
        "player_world_position": {"x": player[0], "y": player[1], "z": 219.2, "z_observed": True,
                                  "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 65793, "is_complete": False, "objectives": [
            {"description": "1/1 Hop on a dragonriding mount (Optional)", "is_complete": True},
            {"description": "1/1 Speak with Sabellian to begin moving the eggs", "is_complete": True},
            {"description": "0/1 Escort the wagon", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"65793": {"objectives": [
            {"description": "Speak with Sabellian to begin moving the eggs", "mechanism": "TALK", "order": 1},
            {"description": "Escort the wagon", "mechanism": "ESCORT", "order": 2, "storage_index": 1,
             "credit_object_id": 191087,
             "escort_creatures": [{"entry": 191020, "name": "Inconspicuous Wagon"},
                                  {"entry": 190935, "name": "Inconspicuous Wagon"}]}]}}},
        "packet_entities": entities}


def test_beside_our_wagon_the_agent_holds_instead_of_leaving():
    (hold,) = EscortPolicy().propose(bulwark())
    assert hold.skill == "WAIT_EVENT" and hold.priority > 56            # the POI MOVE was 56
    assert hold.parameters["server_entity_guid"] == WAGON and hold.parameters["objective_kind"] == "ESCORT"


def test_the_wagon_moving_on_is_followed_on_the_ground_point():
    (move,) = EscortPolicy().propose(bulwark(wagon=(1838., 1120.)))
    assert move.skill == "MOVE" and move.parameters["purpose"] == "ESCORT_FOLLOW"
    assert (move.parameters["x"], move.parameters["y"]) == (1838., 1120.)
    assert move.parameters["objective_id"] == "65793:2"


def test_a_static_wagon_or_someone_elses_is_not_escorted():
    assert EscortPolicy().propose(bulwark(wagon=None)) == []          # only the static 191020
    assert EscortPolicy().propose(bulwark(ours=False)) == []


def test_out_of_view_we_go_back_to_where_we_last_saw_it_once():
    policy = EscortPolicy()
    policy.propose(bulwark(wagon=(1838., 1120.)))
    away = bulwark(wagon=(1838., 1120.), removed=True, player=(1843.5, 623.7), t=130.)
    (back,) = policy.propose(away)
    assert back.parameters["purpose"] == "ESCORT_RETURN" and (back.parameters["x"], back.parameters["y"]) == (1838., 1120.)
    there = bulwark(wagon=(1838., 1120.), removed=True, player=(1839., 1125.), t=200.)
    assert policy.propose(there) == [] and policy.propose(away) == []   # not there: no endless return


def test_no_escort_once_the_objective_is_done():
    done = bulwark()
    done["active_quests"][0]["objectives"][2].update(description="1/1 Escort the wagon", is_complete=True)
    assert escort_objectives(done) == [] and EscortPolicy().propose(done) == []


def _hold(state):
    (hold,) = EscortPolicy().propose(state)
    active = SimpleNamespace(intent=SimpleNamespace(parameters=hold.parameters), skill_context={},
                             phase=None, before_snapshot=state,
                             attempt=SimpleNamespace(deadline=1e9))
    skill = DefendWaitSkill()
    skill.begin(active, state, 100.)
    return skill, active


def test_the_hold_ends_when_the_wagon_moves_on_or_after_a_while():
    skill, active = _hold(bulwark())
    assert skill.verify(active, bulwark(t=103.), 103.).status is SkillStatus.RUNNING
    assert skill.verify(active, bulwark(wagon=(1838., 1120.), t=104.), 104.).status is SkillStatus.CANCELLED
    skill, active = _hold(bulwark())
    assert skill.verify(active, bulwark(t=109.), 109.).status is SkillStatus.CANCELLED   # re-check
