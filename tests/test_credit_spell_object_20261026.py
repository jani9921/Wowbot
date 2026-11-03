"""Best Plans and Intentions (66048): "Talonstalker Kavia consulted" (credit
189507) is given by the Scouting Scope's spell 309772 (DB2 KILL_CREDIT).  The
server sent the scope with quest_objective_id 0 and NO_INTERACT (0x8080)
until Kavia's gossip, 0x8000 after it (live 2026-10-26 21:54:17).  The agent
re-talked to Kavia, wandered off and waited; it must look into the scope."""
from types import SimpleNamespace

from wowbot.agent.packet_entity_facts import (CREDIT_OBJECT_BASIS, credit_object_entries,
                                              server_object_interactable)
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, linked_object_entries
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.skills.object_use import ObjectUseSkill

SCOPE = "GameObject-0-3769-2444-47-376824-00005824C5"
KAVIA = "Creature-0-3769-2444-47-189507-00005824C5"


def camp(x=1686.2, y=1280.3, facing=1.4, soft=None, flags=0x8000, done=False):
    return {
        "monotonic_time": 10., "orientation": facing, "is_in_combat": False, "quest_ui": {"open": False},
        "player_world_position": {"x": x, "y": y, "z": 186.6, "z_observed": True, "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS"},
        "soft_targets": [{"source_unit": "softinteract", "guid": soft}] if soft else [],
        "soft_targets_sample_time": 10.,
        "active_quests": [{"quest_id": 66048, "is_complete": False, "objectives": [
            {"description": "1/1 Fao the Relentless consulted", "is_complete": True},
            {"description": f"{int(done)}/1 Talonstalker Kavia consulted", "is_complete": done}]}],
        "reference_knowledge": {"quests": {"66048": {"objectives": [
            {"objective_id": 427170, "description": "Talonstalker Kavia consulted",
             "credit_kind": "CREATURE_CREDIT", "credit_object_id": 189507,
             "credit_objects": [{"object_id": 376824, "name": "Scouting Scope", "type": 22,
                                 "spell_id": 309772}]}]}}},
        "packet_entities": {SCOPE: {"guid": SCOPE, "kind": "GAMEOBJECT", "entry_id": 376824, "map_id": 2444,
                                    "info": {"object_kind": "GAMEOBJECT", "go_type": 22, "quest_objective_id": 0},
                                    "dynamic_flags": {"value": flags},
                                    "position": {"x": 1684.46, "y": 1287.25, "z": 185.78, "sampled_at": 10.,
                                                 "source": "PACKET_CREATE_STATIONARY"}}}}


def test_the_scope_opens_only_after_the_talk():
    assert credit_object_entries(camp(flags=0x8080)) == {}                # before Kavia's gossip
    assert credit_object_entries(camp()) == {"376824": "66048"}
    assert linked_object_entries(camp()) == {"376824": "66048"}
    assert credit_object_entries(camp(done=True)) == {}                  # objective finished


def test_walk_to_the_scope_then_f7_with_the_credit_basis():
    (move,) = ServerNpcInteractionPolicy().propose(camp())
    assert move.skill == "MOVE" and move.parameters["object_id"] == 376824
    assert move.parameters["face_on_arrival"] is True
    (use,) = ServerNpcInteractionPolicy().propose(camp(x=1684.9, y=1286.2, facing=1.95))
    assert use.skill == "OBJECT_USE" and use.parameters["server_use_basis"] == CREDIT_OBJECT_BASIS
    state = camp(x=1684.9, y=1286.2, facing=1.95)
    assert server_object_interactable(state, SCOPE, CREDIT_OBJECT_BASIS)
    assert not server_object_interactable(state, SCOPE)                   # no Activate bit
    assert ObjectUseSkill.packet_object_usable(use.parameters, state)
    assert not ObjectUseSkill.packet_object_usable(use.parameters, camp(flags=0x8080))


def test_the_scope_goes_before_re_talking_to_kavia():
    state = camp(x=1687.0, y=1280.0)
    state["packet_entities"][KAVIA] = {
        "guid": KAVIA, "kind": "CREATURE", "entry_id": 189507, "map_id": 2444,
        "info": {"npc_flags": 3}, "quest_giver": {"quest_available": False, "reward_ready": False},
        "position": {"x": 1686.2, "y": 1280.3, "z": 186.6, "sampled_at": 10., "source": "PACKET_CREATE_STATIONARY"}}
    import wowbot.agent.server_npc_planning as planning
    original = planning.objective_npc_entries
    planning.objective_npc_entries = lambda state, **queries: {"189507": "66048"}
    try:
        (step,) = ServerNpcInteractionPolicy().propose(state)
    finally:
        planning.objective_npc_entries = original
    assert step.skill == "MOVE" and step.parameters.get("object_id") == 376824


class _Raw:
    tables = {"gameobject_template"}

    def __init__(self):
        self.calls = []

    def rows(self, sql, args=()):
        self.calls.append(args)
        return [{"entry": 376824, "name": "Scouting Scope", "type": 22, "Data0": 309772, "Data10": 0}] \
            if 309772 in args else []


def test_credit_objects_come_from_db2_kill_credit_spells(monkeypatch):
    import wowbot.quests.client_catalog as client
    monkeypatch.setattr(client.ClientCatalog, "kill_credit_spells",
                        lambda self, entry: [309772, 372300] if entry == 189507 else [])
    provider = TDBKnowledgeProvider(SimpleNamespace(raw=_Raw()))
    assert provider.credit_objects(189507) == [
        {"object_id": 376824, "name": "Scouting Scope", "type": 22, "spell_id": 309772}]
    assert provider.credit_objects(186331) == []
