"""Accept greetings must not hide the next explicit conversation objective."""
from copy import deepcopy

from wowbot.agent.conversation_actors import conversation_actors
from wowbot.agent.objective_speech_planning import ObjectiveSpeechHold
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries

GUID = "Creature-0-3769-2444-47-186681-00005824C7"
TEXT = "Speak with Wrathion to begin the assault"


def state(now=10., *, soft_name=False):
    return {"session_id": "test", "map_id": 2022, "monotonic_time": now, "orientation": 0.,
        "player_world_position": {"x": 0., "y": 0., "z": 10., "z_known": True, "instance_id": 2444},
        "target": False, "quest_ui": {"open": False},
        "soft_targets_sample_time": now,
        "soft_targets": [{"guid": GUID, "source_unit": "softinteract", "npc_id": 186681,
                         **({"name": "Wrathion", "is_attackable": False, "is_dead": False} if soft_name else {})}],
        "active_quests": [{"quest_id": 65939, "is_complete": False, "objectives": [
            {"current": 0, "required": 1, "description": "0/1 "+TEXT, "is_complete": False, "type": "KILL"}]}],
        "reference_knowledge": {"quests": {"65939": {
            "quest_roles": [{"npc_id": 186681, "name": "Wrathion", "role": "QUEST_STARTER", "source": "LEARNED"}],
            "objectives": [{"objective_id": 423594, "description": TEXT, "credit_name": "Kill Credit",
                "credit_object_id": 189679, "credit_kind": "CREATURE_CREDIT",
                "named_creatures": [{"entry": 57767, "name": "Wrathion"}, {"entry": 57777, "name": "Wrathion"}]}]}}},
        "packet_entities": {GUID: {"guid": GUID, "entry_id": 186681, "kind": "CREATURE", "map_id": 2444,
            "info": {"npc_flags": 3}, "position": {"x": 2., "y": 0., "z": 10.,
                "source": "PACKET_CREATE_MOVEMENT", "sampled_at": now}}}}


def test_current_server_wrathion_beats_truncated_old_named_variants():
    value = state()
    assert conversation_actors(value, 65939)[0]["entry"] == 186681
    assert objective_npc_entries(value)["186681"] == "65939"
    (interact,) = ServerNpcInteractionPolicy().propose(value)
    assert interact.skill == "INTERACT" and interact.parameters["soft_guid"] == GUID
    assert interact.parameters["quest_id"] == "65939"


def test_current_client_name_with_server_identity_can_resolve_a_missing_role():
    value = state(soft_name=True)
    value["reference_knowledge"]["quests"]["65939"]["quest_roles"] = []
    assert conversation_actors(value, 65939)[0]["entry"] == 186681
    value["soft_targets_sample_time"] = 1.
    assert conversation_actors(value, 65939) == []


def test_wrong_instance_removed_hostile_or_completed_actor_is_not_adopted():
    for kind in ("map", "removed", "hostile", "done", "wrong_name"):
        value = state(soft_name=True)
        unit = value["packet_entities"][GUID]
        if kind == "map":
            unit["map_id"] = 999
        elif kind == "removed":
            unit["removed"] = {"reason": "DESTROYED"}
        elif kind == "hostile":
            unit["info"]["npc_flags"] = 0
        elif kind == "done":
            value["active_quests"][0]["objectives"][0]["is_complete"] = True
        else:
            value["active_quests"][0]["objectives"][0]["description"] = "Speak with Sendrax"
        assert conversation_actors(value, 65939) == []


def test_accept_greeting_is_not_a_credit_speech_hold_but_real_gossip_still_is():
    value = state(soft_name=True)
    value["quest_ui"] = {"open": True, "action": "ACCEPT", "quest_id": 65939}
    value["events"] = [{"event_type": "NPC_INSTRUCTION", "sequence": 1,
                        "payload": {"sender": "Wrathion", "message": "On your signal champion!"}}]
    hold = ObjectiveSpeechHold()
    hold.observe(value)
    closed = deepcopy(value)
    closed.update(monotonic_time=11., quest_ui={"open": False})
    assert hold.propose(closed) == []
    value["quest_ui"]["action"] = "GOSSIP_OPTION_SELECT"
    hold.observe(value)
    assert hold.propose(closed)[0].skill == "WAIT_EVENT"


def test_accepting_new_quest_releases_the_previous_offer_interaction_cooldown():
    policy = ServerNpcInteractionPolicy()
    before = state()
    before["active_quests"] = []
    policy.propose(before)
    policy.note_interaction(GUID, 10.)
    value = state(11.)
    assert policy.propose(value)[0].skill == "INTERACT"
    policy.note_interaction(GUID, 11.)
    assert policy.propose(state(12.)) == []  # unchanged context still throttled


def test_actual_conversation_option_uses_the_current_actor_not_ancient_ids():
    value = state(soft_name=True)
    value["target"] = {"guid": GUID, "npc_id": 186681, "name": "Wrathion", "attackable": False, "dead": False}
    value["target_sample_time"] = 10.
    option = {"id": 77, "name": "(Quest) I am ready to begin the assault.", "quest_label_prepend": True,
              "available": True, "x": .1, "y": .3}
    value["quest_ui"] = {"open": True, "action": "GOSSIP_OPTION_SELECT", "npc_guid": GUID,
                         "gossip_options": [option], "gossip_option": option}
    pick = QuestDialogPlanningPolicy._talk_gossip(value, True)
    assert pick and pick.parameters["target_guid"] == GUID
    assert pick.parameters["gossip_option_id"] == 77 and pick.parameters["quest_id"] == 65939
