"""Selection/combat flag alone cannot authorize an unrelated elite fight."""
from wowbot.agent.combat_target_safety import combat_target_allowed
from wowbot.agent.models import Command
from wowbot.runtime.skill_identity import check_command_identity
from test_combat_planning_policy import _world, _policy


GUID = "Creature-0-3769-2444-47-186728-00005A4AE6"
PLAYER = "Player-1402-0B578799"


def fight(**extra):
    return {"is_in_combat": True, "character_guid": PLAYER, "monotonic_time": 10., "timestamp": 1000.,
            "target_sample_time": 10., "target": {"guid": GUID, "npc_id": 186728, "name": "Magmammoth Bull",
            "classification": "elite", "attackable": True, "dead": False}, **extra}


def event(kind="COMBAT_STARTED", **body):
    return {"event_type": kind, "timestamp": 1000., "sequence": 3,
            "payload": {"attacker_guid": GUID, "victim_guid": PLAYER, **body}}


def test_unverified_elite_cannot_enter_defend_or_dispatch_attack():
    state = fight()
    assert not combat_target_allowed(state, state["target"])
    world = _world(**state)
    proposals = _policy(world, now=10.).proposals
    assert not any(p.skill in {"COMBAT", "DEFEND", "VISUAL_APPROACH"} for p in proposals)
    checked = check_command_identity("DEFEND", {"guid": GUID}, {"guid": GUID}, state,
                                     (Command("BIND", "STARTATTACK"),), 10.)
    assert not checked and checked.reason == "UNVERIFIED_ELITE_TARGET"


def test_exact_attacker_pair_authorizes_defence_but_other_units_do_not():
    for body, allowed in (({}, True), ({"attacker_guid": "another"}, False),
                          ({"victim_guid": "another"}, False)):
        state = fight(events=[event(**body)])
        assert combat_target_allowed(state, state["target"]) is allowed
    stopped = fight(events=[event(), {**event("ATTACK_STOPPED"), "sequence": 4}])
    assert not combat_target_allowed(stopped, stopped["target"])


def test_explicit_objective_is_not_a_blanket_elite_ban():
    state = fight(is_in_combat=False)
    assert combat_target_allowed(state, state["target"], explicit_objective=True)
    assert not combat_target_allowed(state, state["target"])


def test_sparse_target_uses_only_its_own_classification_event():
    state = fight()
    state["target"].pop("classification")
    state["events"] = [{"event_type": "TARGET_CHANGED", "sequence": 1, "timestamp": 999.,
                        "payload": {"guid": GUID, "classification": "elite"}}]
    assert not combat_target_allowed(state, state["target"])
    state["events"][0]["payload"]["guid"] = "different-unit"
    assert combat_target_allowed(state, state["target"])


def test_normal_multi_attacker_defence_is_unchanged():
    state = fight()
    state["target"]["classification"] = "normal"
    assert combat_target_allowed(state, state["target"])


def test_a_numeric_kill_objective_can_still_authorize_an_elite():
    state = fight(active_quests=[{"quest_id": 7, "title": "A real named target", "objectives": [{
        "type": "KILL", "raw_type": "monster", "description": "0/1 Magmammoth Bull slain",
        "current": 0, "required": 1, "target_entity": {"npc_id": 186728}}]}])
    proposals = _policy(_world(**state), now=10.).proposals
    assert any(p.skill == "COMBAT" and p.parameters.get("elite_objective_verified") for p in proposals)


def test_the_elite_guard_does_not_hide_loot_on_an_owned_dead_target():
    state = fight(is_in_combat=False, loot_pending=True)
    state["target"].update(dead=True, lootable=True)
    assert any(p.skill == "LOOT" for p in _policy(_world(**state), now=10.).proposals)


def test_a_reference_credit_creature_authorizes_the_elite_kill():
    """Live 2026-10-26 (Proto-Fight 66122): "Proto-dragons slain" names the
    generic Proto-dragon; the elite Rumbling Proto-Dragon is one of its TDB
    credit creatures.  The agent waited 'Elit target ...' at it."""
    dragon = "Creature-0-3769-2444-47-187212-00005F4AA9"
    state = fight(is_in_combat=False, target={"guid": dragon, "npc_id": 187212, "name": "Rumbling Proto-Dragon",
                                              "classification": "elite", "attackable": True, "dead": False},
                  active_quests=[{"quest_id": 66122, "title": "Proto-Fight", "objectives": [
                      {"type": "KILL", "raw_type": "monster", "description": "1/3 Proto-dragons slain",
                       "current": 1, "required": 3}]}],
                  reference_knowledge={"quests": {"66122": {"objectives": [
                      {"credit_kind": "CREATURE_CREDIT", "credit_name": "Kill Credit: Q09 Proto-dragon [DNT]",
                       "credit_object_id": 189618, "description": "Proto-dragons slain", "raw_type": 0,
                       "credit_creatures": [{"entry": 187212, "name": "Rumbling Proto-Dragon"}],
                       "named_creatures": [{"entry": 184477, "name": "Proto-dragon"}]}]}}})
    proposals = _policy(_world(**state), now=10.).proposals
    assert not any(p.parameters.get("reason") == "unverified_elite_target" for p in proposals)
