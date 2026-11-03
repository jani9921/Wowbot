"""Pick up an objective's unit with Interact; pick it up again after combat.

Live 2026-10-23 01:18-01:20 (A Last Hope 66001): "Pick up the Infused Dragon
Egg" names egg creatures (190090 ...); the agent hunted the egg with Tab (not
attackable) while it was the client's soft-interact unit 1.5 yd away, and the
user picked it up.  User: in combat the egg is put down to fight, then it
must be picked up again and carried on; the quest POI then points back to
the first egg although the dropped one lies beside the player.
"""
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.skills.interact import InteractSkill

EGG = "Creature-0-3769-2444-47-190090-00005824C8"
DROPPED = "Creature-0-3769-2444-47-190522-00005A9A2F"


def state(*, picked=False, egg=EGG, entry=190090, distance=1.5, soft=True, combat=False):
    objectives = [{"description": "1/1 Meet Sendrax by the ritual site", "is_complete": True},
                  {"description": f"{1 if picked else 0}/1 Pick up the Infused Dragon Egg",
                   "is_complete": picked},
                  {"description": "0/1 Carry the egg to safety", "is_complete": False}]
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022, "is_in_combat": combat,
        "player_world_position": {"x": 4220., "y": 113., "z": 52., "instance_id": 2444},
        "active_quests": [{"quest_id": 66001, "is_complete": False, "objectives": objectives}],
        "reference_knowledge": {"quests": {"66001": {"objectives": [
            {"credit_kind": "CREATURE_CREDIT", "credit_name": "Kill Credit: Pick Up Egg [DNT]",
             "credit_object_id": 191888, "description": "Pick up the Infused Dragon Egg",
             "named_creatures": [{"entry": 190090, "name": "Infused Dragon Egg"},
                                 {"entry": 190522, "name": "Infused Dragon Egg"}]},
            {"credit_kind": "CREATURE_CREDIT", "credit_name": "Egg Returned to Safety Kill Credit [DNT]",
             "credit_object_id": 190211, "description": "Carry the egg to safety"}]}}},
        "packet_entities": {egg: {"guid": egg, "kind": "CREATURE", "entry_id": entry, "map_id": 2444,
                                  "info": {"npc_flags": 0},
                                  "position": {"x": 4220.+distance, "y": 113., "z": 52.}}},
        "soft_targets": [{"source_unit": "softinteract", "guid": egg}] if soft else [],
        "soft_targets_sample_time": 100.,
    }


def test_the_egg_is_picked_up_not_hunted():
    assert "190090" not in kill_objective_entries(state())
    (press,) = ServerNpcInteractionPolicy().propose(state())
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == EGG
    assert press.parameters["purpose"] == "OBJECTIVE_PICKUP"
    assert press.parameters["interaction_kind"] == "PICKUP"
    # Verified by quest credit, not by a window.
    assert InteractSkill._credit_purpose(press.parameters)
    # Not yet beside it: walk to its server point.
    (move,) = ServerNpcInteractionPolicy().propose(state(distance=30., soft=False))
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == EGG


def test_the_egg_put_down_in_combat_is_picked_up_again_beside_us():
    dropped = dict(picked=True, egg=DROPPED, entry=190522, distance=2.8)
    assert ServerNpcInteractionPolicy().propose(state(**dropped, combat=True)) == []   # fight first
    (press,) = ServerNpcInteractionPolicy().propose(state(**dropped))
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == DROPPED
    # Only the one put down beside us; the original far egg is not walked back to.
    assert ServerNpcInteractionPolicy().propose(state(**{**dropped, "distance": 40.}, soft=False)) == []
