"""REV4 P8.4 (E2 classic escort): defend the escorted unit, notice a failure.

QUEST_PLAYBOOKS E2: "the mobs attack the NPC, not us".  The server's unit
target field names the victim; hostiles targeting our escort become kill
targets of the shared server-GUID Tab flow, the escort hold steps aside, and
combat counts them as quest-relevant.  A failed escort quest (addon 0.9.82
``is_failed``) is no longer held; restarting it (abandon + re-accept) has no
adapter yet and is reported typed."""
from wowbot.agent.escort_planning import EscortPolicy, escort_attackers, escort_objectives
from wowbot.agent.server_kill_planning import ServerKillTargetPolicy
from test_escort_wagon_20261028 import WAGON, bulwark

RAIDER = "Creature-0-1461-2534-147807-190000-00RAIDER01"
BYSTANDER = "Creature-0-1461-2534-147807-190001-00BYSTAND01"


def raided(x=1830., y=1150., victim=WAGON, **unit):
    state = bulwark()
    state["packet_entities"][RAIDER] = {
        "guid": RAIDER, "kind": "CREATURE", "entry_id": 190000, "map_id": 2444,
        "position": {"x": x, "y": y, "z": 202.7},
        "unit": {"health": 500, "target_entity": victim, **unit}}
    state["packet_entities"][BYSTANDER] = {
        "guid": BYSTANDER, "kind": "CREATURE", "entry_id": 190001, "map_id": 2444,
        "position": {"x": 1832., "y": 1152., "z": 202.7}, "unit": {"health": 500}}
    return state


def test_a_hostile_on_our_escort_is_a_kill_target_and_the_hold_steps_aside():
    state = raided()
    (row,) = escort_attackers(state)
    assert row["guid"] == RAIDER and row["escort_guid"] == WAGON and row["quest_id"] == "65793"
    assert EscortPolicy().propose(state) == []
    state["orientation"] = 3.6                        # facing it (south-west)
    (step,) = ServerKillTargetPolicy().propose(state)
    assert step.parameters.get("server_entity_guid", step.parameters.get("guid")) == RAIDER


def test_far_dead_or_other_victims_are_not_escort_attackers():
    assert escort_attackers(raided(x=1700.)) == []
    assert escort_attackers(raided(health=0)) == []
    assert escort_attackers(raided(victim=BYSTANDER)) == []
    assert EscortPolicy().propose(raided(victim=BYSTANDER))[0].skill == "WAIT_EVENT"


def test_a_failed_escort_quest_is_not_held_and_is_reported():
    state = bulwark()
    state["active_quests"][0]["is_failed"] = True
    assert escort_objectives(state) == []
    (report,) = EscortPolicy().propose(state)
    assert report.skill == "WAIT" and report.parameters["reason"] == "escort_quest_failed"
    assert report.parameters["needs"] == "ABANDON_AND_REACCEPT" and report.priority == 30
