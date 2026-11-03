"""Talk-to and ride-vehicle credits are not kills (live 2026-10-21 16:13-16:15).

User: "ott a 3 megcsinálandó quest között move-ol folyamatosan oda-vissza".
"Inquire after the missing dragons" (70125) is the TDB credit "Kill Credit:
Talk to Sendrax [DNT]" and "Hop on the Surveyor's Disc" (66101) is "Kill
Credit: Ride Vehicle [DNT]".  The disc was hunted as a kill (Tab never
selected it), Sendrax was never spoken to, and the agent bounced between the
quest regions.
"""
from wowbot.agent.models import Proposal
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, ride_entries
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from wowbot.verification.quest_dialog import QuestDialogVerifier

from test_m0_combat_loot_skills import active

SENDRAX = "Creature-0-3769-2444-47-193362-00005824C1"
DISC = "Creature-0-3769-2444-47-193707-00005824C9"


def unit(guid, x, y, flags):
    return {"guid": guid, "kind": "CREATURE", "entry_id": int(guid.split("-")[5]), "map_id": 2444,
            "info": {"object_kind": "UNIT", "npc_flags": flags}, "dynamic_flags": {"value": 0},
            "position": {"x": x, "y": y, "z": 91., "source": "PACKET_CREATE_MOVEMENT", "age": 2.}}


def state(*units, **extra):
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [
            {"quest_id": 70125, "is_complete": False, "objectives": [
                {"description": "0/1 Inquire after the missing dragons", "type": "KILL", "is_complete": False}]},
            {"quest_id": 66101, "is_complete": False, "objectives": [
                {"description": "0/1 Hop on the Surveyor's Disc", "type": "KILL", "is_complete": False}]}],
        "reference_knowledge": {"quests": {
            "70125": {"objectives": [{"description": "Inquire after the missing dragons",
                                      "credit_kind": "CREATURE_CREDIT", "credit_object_id": 193817,
                                      "credit_name": "Kill Credit: Talk to Sendrax [DNT]", "credit_action": "TALK",
                                      "talk_creatures": [{"entry": 193362, "name": "Sendrax"}],
                                      "named_creatures": []}]},
            "66101": {"objectives": [{"description": "Hop on the Surveyor's Disc",
                                      "credit_kind": "CREATURE_CREDIT", "credit_object_id": 184913,
                                      "credit_name": "Kill Credit: Ride Vehicle [DNT]", "credit_action": "RIDE",
                                      "named_creatures": [{"entry": 193707, "name": "Surveyor's Disc"}]}]}}},
        "packet_entities": {item["guid"]: item for item in units}, "soft_targets": [], **extra}


def test_talk_and_ride_objectives_are_never_kill_targets():
    entries = kill_objective_entries(state())
    assert "193707" not in entries and "193817" not in entries and "193362" not in entries
    assert ride_entries(state()) == {"193707": "66101"}


def test_sendrax_and_the_disc_are_walked_up_to_at_their_server_position():
    policy = ServerNpcInteractionPolicy()
    (move,) = policy.propose(state(unit(SENDRAX, 30., 0., 3)))
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == SENDRAX
    (move,) = ServerNpcInteractionPolicy().propose(state(unit(DISC, 0., 30., 0)))    # no NPC flags
    assert move.parameters["server_entity_guid"] == DISC
    here = state(unit(DISC, 2., 0., 0), soft_targets=[{"source_unit": "softinteract", "guid": DISC}],
                 soft_targets_sample_time=100.)
    (press,) = ServerNpcInteractionPolicy().propose(here)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == DISC


OPTIONS = [{"id": 55001, "name": "What happened to the missing dragons?", "available": True, "x": .12, "y": .6},
           {"id": 55002, "name": "Goodbye for now.", "available": True, "x": .12, "y": .64}]


def dialog(**extra):
    return state(target={"guid": SENDRAX, "name": "Sendrax", "attackable": False, "dead": False},
                 quest_ui={"open": True, "action": "", "x": 0, "y": 0, "gossip_options": OPTIONS},
                 quest_ui_open=True, state_age=.4, **extra)


def test_in_sendraxs_window_the_row_about_the_missing_dragons_is_chosen():
    row = QuestDialogPlanningPolicy._talk_gossip(dialog(), True)
    assert row.parameters["gossip_option_id"] == 55001 and row.parameters["quest_id"] == 70125
    assert row.parameters["gossip_transition"] == "QUEST_PROGRESS"
    stranger = {**dialog(), "target": {"guid": "Creature-0-1-2444-1-1-1", "name": "Somebody",
                                       "attackable": False}}
    assert QuestDialogPlanningPolicy._talk_gossip(stranger, True) is None
    skill = QuestDialogSkill()
    started = skill.begin(active("QUEST_DIALOG", row.parameters, dialog()), dialog())
    assert started.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in started.commands] == [("CLICK", .12, .6)]
    credited = {**dialog(), "active_quests": [{**dialog()["active_quests"][0], "objectives": [
        {"description": "1/1 Inquire after the missing dragons", "type": "KILL", "is_complete": True,
         "current": 1}]}, dialog()["active_quests"][1]]}
    before = {**dialog(), "active_quests": [{**dialog()["active_quests"][0], "objectives": [
        {"description": "0/1 Inquire after the missing dragons", "type": "KILL", "is_complete": False,
         "current": 0}]}, dialog()["active_quests"][1]]}
    verdict = QuestDialogVerifier().evaluate(before, credited, quest_id=70125, action="GOSSIP_OPTION_SELECT",
                                             target_guid=SENDRAX, gossip_option_id=55001,
                                             gossip_transition="QUEST_PROGRESS")
    assert verdict.reason is None
