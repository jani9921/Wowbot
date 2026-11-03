"""Sharp Practice (66078): "0/8 Blacktalon tested" is a kill credit (187158)
of Blacktalon Avengers/Assassins, friendly gossip NPCs ("I'm here to test your
combat skills.").  Live 2026-10-26 23:09-23:11 the agent waited 1.5 yd from
one: the kill hunt skips service NPCs, the talk policy skips kill credits."""
from wowbot.agent.packet_entity_facts import kill_objective_units, sparring_entries
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy

AVENGER = "Creature-0-3769-2444-47-187187-00005FCA64"


def camp(npc_flags=1, dialog=False):
    state = {
        "monotonic_time": 10., "orientation": 0., "is_in_combat": False,
        "quest_ui": ({"open": True, "action": "GOSSIP_OPTION_SELECT",
                      "gossip_option": {"id": 0, "name": "I'm here to test your combat skills.",
                                        "x": .08, "y": .77}} if dialog else {"open": False}),
        "player_world_position": {"x": 1700., "y": 1250., "z": 180., "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS"},
        "soft_targets": [{"source_unit": "softinteract", "guid": AVENGER}], "soft_targets_sample_time": 10.,
        "target": {"guid": AVENGER, "name": "Blacktalon Avenger", "attackable": False, "dead": False},
        "active_quests": [{"quest_id": 66078, "is_complete": False, "objectives": [
            {"description": "0/8 Blacktalon tested", "is_complete": False, "type": "KILL",
             "raw_type": "monster"}]}],
        "reference_knowledge": {"quests": {"66078": {"objectives": [
            {"objective_id": 423893, "description": "Blacktalon tested", "credit_kind": "CREATURE_CREDIT",
             "credit_object_id": 187158, "credit_name": "Blacktalon Avenger", "raw_type": 0,
             "credit_creatures": [{"entry": 187187, "name": "Blacktalon Avenger"},
                                  {"entry": 187189, "name": "Blacktalon Assassin"}]}]}}},
        "packet_entities": {AVENGER: {
            "guid": AVENGER, "kind": "CREATURE", "entry_id": 187187, "map_id": 2444,
            "info": {"object_kind": "UNIT", "npc_flags": npc_flags}, "dynamic_flags": {"value": 0},
            "position": {"x": 1701.4, "y": 1250.3, "z": 180., "sampled_at": 10.,
                         "source": "PACKET_CREATE_STATIONARY"}}}}
    return state


def test_a_friendly_gossip_kill_credit_is_a_sparring_partner():
    assert sparring_entries(camp()) == {"187187": ("66078", "66078:0")}
    assert kill_objective_units(camp()) == []                          # not attacked while friendly
    assert sparring_entries(camp(npc_flags=0)) == {}                   # hostile now: the hunt owns it
    assert [unit["guid"] for unit in kill_objective_units(camp(npc_flags=0))] == [AVENGER]


def test_talk_to_it_then_pick_the_fight_option():
    (talk,) = ServerNpcInteractionPolicy().propose(camp())
    assert talk.skill == "INTERACT" and talk.parameters["npc_id"] == 187187
    proposals = QuestDialogPlanningPolicy().propose(camp(dialog=True), None)
    pick = next(p for p in proposals if p.skill == "QUEST_DIALOG")
    assert pick.parameters["gossip_option_name"] == "I'm here to test your combat skills."
    assert pick.parameters["gossip_transition"] == "SCRIPTED_COMBAT"
    assert str(pick.parameters["quest_id"]) == "66078"


def test_after_the_option_the_attackable_partner_is_hunted_even_with_its_gossip_flag():
    """User: "odamegy, f7 -> gossip opció választása, majd támadás"."""
    fight = camp()
    fight["target"]["attackable"] = True
    assert sparring_entries(fight) == {}
    assert [unit["guid"] for unit in kill_objective_units(fight)] == [AVENGER]
    assert all(p.skill != "INTERACT" for p in ServerNpcInteractionPolicy().propose(fight))


def test_a_sparring_duel_starts_no_wave_hold():
    policy = QuestDialogPlanningPolicy()
    policy.propose(camp(dialog=True), None)
    assert getattr(policy, "scripted_event", None) is None
