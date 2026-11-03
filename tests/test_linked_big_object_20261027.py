"""Large linked GO surface handoff: no repeated centre MOVE after arrival."""
from copy import deepcopy
import math

from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.skills.object_use import ObjectUseSkill
from test_linked_quest_object_20261026 import camp, TABLE, FAO


def large(now=10., x=4.5, facing=0., soft=None, z=10.):
    value = camp(x=x, y=0., facing=facing, soft=soft)
    value["monotonic_time"] = now
    value["soft_targets_sample_time"] = now
    value["player_world_position"].update(z=z, z_known=True)
    value["packet_entities"][TABLE]["position"].update(x=10., y=0., z=10., sampled_at=now)
    return value


def test_exact_fresh_gameobject_recipient_uses_edge_without_chasing_its_centre():
    value = large(soft=TABLE)
    (use,) = ServerNpcInteractionPolicy().propose(value)
    assert use.skill == "OBJECT_USE" and use.parameters["object_guid"] == TABLE
    assert ObjectUseSkill.packet_object_usable(use.parameters, value)
    wrong = deepcopy(value)
    wrong["soft_targets"][0]["guid"] = FAO
    assert not ObjectUseSkill.packet_object_usable(use.parameters, wrong)
    stale = deepcopy(value)
    stale["soft_targets_sample_time"] = 1.
    assert not ObjectUseSkill.packet_object_usable(use.parameters, stale)


def test_shared_edge_learning_hands_linked_object_move_to_use():
    domain = QuestDomain()
    flow = domain.location_policy.object_interaction
    assert domain.server_npcs.object_flow is flow
    value = large(now=1.)
    (move,) = domain.server_npcs.propose(value)
    assert move.skill == "MOVE" and move.parameters["stop_distance"] == 1.2
    assert flow.object_move_handoff(value, move.parameters, 10.) is None
    value = large(now=2.3, x=4.55)
    handoff = flow.object_move_handoff(value, move.parameters, 10.)
    assert handoff and handoff["kind"] == "SERVER_QUEST_OBJECT_EDGE"
    (use,) = domain.server_npcs.propose(value)
    assert use.skill == "OBJECT_USE" and use.parameters["server_interaction_range"] > 5.45
    assert ObjectUseSkill.packet_object_usable(use.parameters, value)
    # A changed pose before dispatch is rechecked, not covered by old arrival.
    far = large(now=2.4, x=-10.)
    assert not ObjectUseSkill.packet_object_usable(use.parameters, far)


def test_known_edge_turns_in_place_instead_of_taking_another_step_inside_model():
    flow = ObjectInteractionFlow()
    flow._learn_packet_reach(TABLE, 377106, 5.5)
    (turn,) = ServerNpcInteractionPolicy(flow).propose(large(facing=math.pi))
    assert turn.skill == "MOVE" and turn.parameters["face_on_arrival"]
    assert turn.parameters["stop_distance"] >= 5.5


def test_other_soft_recipient_and_nearer_interactive_object_never_authorize_f7():
    flow = ObjectInteractionFlow()
    flow._learn_packet_reach(TABLE, 377106, 5.5)
    assert ServerNpcInteractionPolicy(flow).propose(large(soft=FAO)) == []
    value = large()
    other = "GameObject-0-1-2444-1-999-0000000001"
    unit = deepcopy(value["packet_entities"][TABLE])
    unit.update(guid=other, entry_id=999)
    unit["info"]["quest_objective_id"] = 0
    unit["dynamic_flags"]["value"] = 0x8000
    unit["position"]["x"] = 5.
    value["packet_entities"][other] = unit
    assert not [p for p in ServerNpcInteractionPolicy(flow).propose(value) if p.skill == "OBJECT_USE"]


def test_other_floor_combat_disabled_or_removed_object_cannot_use_the_learned_edge():
    flow = ObjectInteractionFlow()
    flow._learn_packet_reach(TABLE, 377106, 5.5)
    for change in ("floor", "combat", "disabled", "removed"):
        value = large(soft=TABLE)
        if change == "floor":
            value["player_world_position"]["z"] = 30.
        elif change == "combat":
            value["is_in_combat"] = True
        elif change == "disabled":
            value["packet_entities"][TABLE]["dynamic_flags"]["value"] |= 0x80
        else:
            value["packet_entities"][TABLE]["removed"] = {"reason": "DESTROYED"}
        assert not [p for p in ServerNpcInteractionPolicy(flow).propose(value) if p.skill == "OBJECT_USE"]


def test_edge_learning_does_not_mistake_a_different_floor_for_object_collision():
    flow = ObjectInteractionFlow()
    walk = {"purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": 66048, "server_entity_guid": TABLE}
    assert flow.object_move_handoff(large(now=1., z=30.), walk, 30.) is None
    assert flow.object_move_handoff(large(now=3., z=30.), walk, 30.) is None
    assert flow.packet_use_range({"guid": TABLE, "object_id": 377106}) == 3.5
