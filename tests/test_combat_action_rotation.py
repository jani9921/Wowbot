from wowbot.agent.models import Command, Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel, Observation


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False, **extra}, 1))
    return value


SPELL_A = {"action": "ACTIONBUTTON1", "kind": "spell", "name": "Frostbolt", "id": 111,
          "is_harmful": True, "is_usable": True, "cooldown_remaining": 0, "in_range": True}
SPELL_B = {"action": "ACTIONBUTTON2", "kind": "spell", "name": "Fireball", "id": 222,
          "is_harmful": True, "is_usable": True, "cooldown_remaining": 0, "in_range": True}
TARGET = {"guid": "Creature-1", "attackable": True, "dead": False, "health": 100, "max_health": 100}


def test_combat_action_rotates_among_equally_eligible_abilities():
    registry = SkillRegistry()
    state = {"actionbar": [SPELL_A, SPELL_B], "target": TARGET}
    proposal = Proposal.make("COMBAT", "test", {"guid": "Creature-1"})
    w = world(actionbar=[SPELL_A, SPELL_B], target=TARGET)
    first = registry.commands(proposal, w)
    second = registry.commands(proposal, w)
    third = registry.commands(proposal, w)
    picked = [c[0].binding for c in (first, second, third)]
    # Both abilities get used, not just the first one repeated forever.
    assert set(picked) == {"ACTIONBUTTON1", "ACTIONBUTTON2"}
    assert picked[0] != picked[1]


def test_combat_action_still_deterministic_with_a_single_ability():
    registry = SkillRegistry()
    w = world(actionbar=[SPELL_A], target=TARGET)
    proposal = Proposal.make("COMBAT", "test", {"guid": "Creature-1"})
    for _ in range(3):
        commands = registry.commands(proposal, w)
        assert commands[0].binding == "ACTIONBUTTON1"


def test_combat_action_still_prioritizes_defensive_at_low_health():
    registry = SkillRegistry()
    defensive = {**SPELL_B, "id": 333}
    low_health_state = {"health": 20, "max_health": 100, "defensive_spell_ids": [333]}
    w = world(actionbar=[SPELL_A, defensive], target=TARGET, **low_health_state)
    action = registry.combat_action(w.state)
    assert action["id"] == 333  # defensive tier still wins the very first pick


def test_combat_uses_are_tracked_per_registry_instance_not_globally():
    a, b = SkillRegistry(), SkillRegistry()
    w = world(actionbar=[SPELL_A, SPELL_B], target=TARGET)
    proposal = Proposal.make("COMBAT", "test", {"guid": "Creature-1"})
    a.commands(proposal, w)
    # A fresh registry has not "used" anything yet, so it picks the same
    # first-eligible ability a fresh sequence would.
    assert b.combat_uses == {}

