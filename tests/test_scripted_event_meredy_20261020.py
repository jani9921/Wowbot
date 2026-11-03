"""The Rescue of Meredy Huntswell (55763), live 2026-10-20 08:47-08:49.

"0/1 Meredy Huntswell rescued" is a KILL objective: talking to Meredy starts
the rescue, harpies and wolves come into the area in waves and Bloodbeak
arrives last; its death is the credit (user). The cursor rested on Meredy 76
times (quest_related, quest 55763) and no friendly-NPC rule admitted her.
"""
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_giver_evidence import friendly_npc_relevant, objective_named_unit

MEREDY = {"guid": "Creature-0-1465-2175-71046-153211-000053399A", "identity_source": "WOW_API_MOUSEOVER",
          "is_attackable": False, "name": "Meredy Huntswell", "npc_id": 153211, "quest_id": 55763,
          "quest_related": True, "unit_type": "NPC"}
QUEST = {"quest_id": 55763, "is_complete": False, "title": "The Rescue of Meredy Huntswell",
         "objectives": [{"current": 0, "description": "0/1 Meredy Huntswell rescued", "is_complete": False,
                         "raw_type": "monster", "required": 1, "type": "KILL"}]}


def state(**changes):
    return {"monotonic_time": 100., "active_quests": [QUEST], "mouseover": dict(MEREDY),
            "player_world_position": {"x": 495., "y": -2350., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"}, **changes}


def test_meredy_is_relevant_although_the_objective_is_a_kill():
    live = state()
    assert objective_named_unit(live, MEREDY["guid"]) is True
    assert friendly_npc_relevant(live, MEREDY["guid"], {"KILL"}, unit_name="Meredy Huntswell") is True
    # Her create block has npc_flags 1 (gossip, no QuestGiver): the objective
    # rule comes before the server quest-giver rule.
    live["packet_entities"] = {MEREDY["guid"]: {"guid": MEREDY["guid"], "kind": "CREATURE",
                                                "entry_id": 153211, "info": {"npc_flags": 1}}}
    assert friendly_npc_relevant(live, MEREDY["guid"], {"KILL"}, unit_name="Meredy Huntswell") is True


def test_unrelated_or_finished_friendly_units_stay_irrelevant():
    other = {**MEREDY, "guid": "Creature-0-1465-2175-71046-154300-000053399A", "name": "Bjorn Stouthands",
             "npc_id": 154300}
    assert not objective_named_unit(state(mouseover=other), other["guid"])
    assert not objective_named_unit(state(mouseover={**MEREDY, "quest_related": False}), MEREDY["guid"])
    done = {**QUEST, "is_complete": True}
    assert not objective_named_unit(state(active_quests=[done]), MEREDY["guid"])


def _gossip_open(now=100.):
    return state(monotonic_time=now, target={**MEREDY, "attackable": False},
                 quest_ui={"open": True, "action": "GOSSIP_OPTION_SELECT", "entries": [],
                           "gossip_option": {"id": 51234, "name": "I'll get you out of here.",
                                             "x": .3, "y": .6}},
                 quest_ui_open=True, quest_ui_action="GOSSIP_OPTION_SELECT")


def test_scripted_gossip_then_waves_hold_the_agent_in_place():
    policy = QuestDialogPlanningPolicy()
    chosen = policy.propose(_gossip_open(), None)
    option = next(p for p in chosen if p.skill == "QUEST_DIALOG")
    assert option.parameters["gossip_transition"] == "SCRIPTED_COMBAT"
    closed = dict(state(monotonic_time=104.), target={**MEREDY, "attackable": False})
    assert not [p for p in policy.propose(closed, None) if p.skill == "WAIT_EVENT"]   # no fight yet
    assert not policy.propose({**closed, "monotonic_time": 106., "is_in_combat": True}, None)
    held = [p for p in policy.propose({**closed, "monotonic_time": 130.}, None) if p.skill == "WAIT_EVENT"]
    assert held and held[0].priority == 113 and held[0].parameters["quest_ids"] == ["55763"]
    # More than 45 s without a wave: the event is over.
    assert not [p for p in policy.propose({**closed, "monotonic_time": 152.}, None) if p.skill == "WAIT_EVENT"]


def test_hold_ends_on_credit_on_no_fight_and_away_from_the_event():
    policy = QuestDialogPlanningPolicy()
    policy.propose(_gossip_open(), None)
    policy.propose({**state(monotonic_time=105.), "is_in_combat": True}, None)
    credited = state(monotonic_time=120., active_quests=[{**QUEST, "is_complete": True}])
    assert not policy.propose(credited, None)
    policy = QuestDialogPlanningPolicy()
    policy.propose(_gossip_open(), None)
    assert not policy.propose(state(monotonic_time=120.), None)      # nothing started within 15 s
    assert policy.scripted_event is None
    policy.propose(_gossip_open(200.), None)
    policy.propose({**state(monotonic_time=203.), "is_in_combat": True}, None)
    away = state(monotonic_time=210., player_world_position={"x": 600., "y": -2350., "instance_id": 2175,
                                                             "coordinate_space": "WORLD_YARDS"})
    assert not [p for p in policy.propose(away, None) if p.skill == "WAIT_EVENT"]


# --- user 2026-10-20: walk right up to the NPC at its server x,y,z, then F7 ---

from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries

REFERENCE = {"quests": {"55763": {"objectives": [
    {"objective_id": 389900, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 153964,
     "description": "Meredy Huntswell rescued",
     "named_creatures": [{"entry": 153211, "name": "Meredy Huntswell"}]}]}}}


def server_state(px, py, *, facing=0., soft=(), npc_flags=1, **changes):
    meredy = {"guid": MEREDY["guid"], "kind": "CREATURE", "entry_id": 153211, "map_id": 2175,
              "info": {"object_kind": "UNIT", "npc_flags": npc_flags},
              "position": {"x": 495.4, "y": -2354.6, "z": 163.2, "source": "PACKET_CREATE_MOVEMENT",
                           "age": 10.}}
    return {"monotonic_time": 100., "active_quests": [QUEST], "reference_knowledge": REFERENCE,
            "orientation": facing, "soft_targets": list(soft), "map_id": 1409,
            "player_world_position": {"x": px, "y": py, "z": 163., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "packet_entities": {MEREDY["guid"]: meredy}, **changes}


def test_objective_named_entries_come_from_the_reference():
    entries = objective_npc_entries(server_state(0., 0.))
    assert entries["153211"] == "55763" and entries["153964"] == "55763"


def test_far_npc_is_walked_to_at_its_exact_server_point_and_faced():
    (move,) = ServerNpcInteractionPolicy().propose(server_state(470., -2354.6))
    assert move.skill == "MOVE" and move.parameters["face_on_arrival"] is True
    assert (move.parameters["x"], move.parameters["z"]) == (495.4, 163.2)
    assert move.parameters["server_entity_guid"] == MEREDY["guid"] and "target_guid" not in move.parameters


def test_close_faced_npc_with_matching_soft_target_gets_one_f7():
    soft = [{"source_unit": "softinteract", "unit_type": "NPC", "guid": MEREDY["guid"]}]
    policy = ServerNpcInteractionPolicy()
    (press,) = policy.propose(server_state(492.4, -2354.6, soft=soft))
    assert press.skill == "INTERACT" and press.parameters["activation_source"] == "SOFT_INTERACT"
    assert press.parameters["soft_guid"] == MEREDY["guid"]
    policy.note_dispatched(MEREDY["guid"], 100.)       # presses count once dispatched
    assert policy.propose(server_state(492.4, -2354.6, soft=soft, monotonic_time=101.)) == []
    # Her window opened: no new approach/press for a while.
    opened = server_state(492.4, -2354.6, soft=soft, monotonic_time=102., quest_ui_open=True)
    policy.propose(opened)
    assert policy.propose(server_state(492.4, -2354.6, soft=soft, monotonic_time=120.)) == []


def test_other_soft_target_combat_or_untalkable_npc_get_nothing():
    corpse = [{"source_unit": "softinteract", "unit_type": "CREATURE", "guid": "Creature-0-1-2175-1-152571-1"}]
    assert ServerNpcInteractionPolicy().propose(server_state(492.4, -2354.6, soft=corpse)) == []
    assert ServerNpcInteractionPolicy().propose(server_state(470., -2354.6, is_in_combat=True)) == []
    assert ServerNpcInteractionPolicy().propose(server_state(470., -2354.6, npc_flags=0)) == []
    assert ServerNpcInteractionPolicy().propose({**server_state(470., -2354.6), "packet_entities": {}}) == []
