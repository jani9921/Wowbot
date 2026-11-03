from wowbot.combat_contracts import CharacterProfile, CastReference, CombatArbitrator
from wowbot.skills.ability_rules import AbilityRuleEngine


def action(spell_id, *, tags=(), **changes):
    return {'id': spell_id, 'action': 'ACTIONBUTTON'+str(spell_id), 'kind': 'spell',
            'is_harmful': True, 'is_usable': True, 'cooldown_remaining': 0., 'in_range': True,
            'tags': tags, **changes}


def state(**changes):
    return {'session_id': 's', 'character_guid': 'Player-1-1', 'class': 'MAGE', 'spec_id': 62,
            'health': 100., 'max_health': 100., 'power': 100.,
            'target': {'guid': 'Creature-1', 'attackable': True}, **changes}


def test_character_profile_is_derived_from_actual_bar_and_changes_with_spec_or_override():
    a = CharacterProfile.from_state(state(actionbar=[action(1, max_range=30.)]))
    b = CharacterProfile.from_state(state(actionbar=[action(1, max_range=30.)], spec_id=63))
    assert a.style == 'RANGED' and a.role == 'UNKNOWN' and a.revision != b.revision
    c = CharacterProfile.from_state(state(actionbar=[action(2, max_range=5.)], in_vehicle=True))
    assert c.style == 'MELEE' and c.bar_revision != a.bar_revision and c.ability_ids == (2,)


def test_interrupt_requires_exact_fresh_interruptible_cast_and_deadline():
    engine = AbilityRuleEngine()
    current = state(actionbar=[action(1, tags=('INTERRUPT',), combat_priority=100.), action(2)])
    assert engine.choose(current, now=10.)['id'] == 2
    cast = {'caster_guid': 'Creature-1', 'cast_id': 'cast-7', 'spell_id': 99,
            'started_at': 9., 'ends_at': 11., 'observed_at': 10., 'interruptible': True}
    current['target']['cast'] = cast
    assert engine.choose(current, now=10.)['id'] == 1
    assert engine.last_arbitration['cast_id'] == 'cast-7'
    cast['interruptible'] = False
    assert engine.choose(current, now=10.)['id'] == 2
    cast.update(interruptible=True, ends_at=10.1)
    assert engine.choose(current, now=10.)['id'] == 2


def test_explicit_facing_and_los_failures_are_not_eligible_casts():
    engine = AbilityRuleEngine()
    for missing in ({'target_facing': False}, {'target_has_los': False}):
        assert engine.choose(state(actionbar=[action(1)], **missing), now=10.) is None


def test_profile_owner_change_clears_old_character_cooldown_estimates():
    engine = AbilityRuleEngine()
    current = state(actionbar=[action(1)])
    engine.evaluate(current, now=10.)
    engine.local_ready_at[1] = 999.
    assert engine.choose(current, now=10.) is None
    assert engine.choose({**current, 'character_guid': 'Player-1-2'}, now=10.)['id'] == 1


def test_critical_survival_preempts_interrupt_and_natural_cast_end_is_not_interrupt_success():
    engine = AbilityRuleEngine()
    cast = {'caster_guid': 'Creature-1', 'cast_id': 'cast-7', 'spell_id': 99,
            'started_at': 9., 'ends_at': 11., 'observed_at': 10., 'interruptible': True}
    current = state(health=10., defensive_spell_ids=[3], actionbar=[
        action(1, tags=('INTERRUPT',)), action(3, tags=('DEFENSIVE',), is_harmful=False, requires_target=False)])
    current['target']['cast'] = cast
    assert engine.choose(current, now=10.)['id'] == 3
    expected = CastReference.from_state(current, 10.)
    assert CombatArbitrator.verify_interrupt(expected, [{'event_type': 'SPELLCAST_SUCCEEDED'}]) is None
    assert CombatArbitrator.verify_interrupt(expected, [{'event_type': 'SPELL_INTERRUPTED', 'payload': cast}]) is True
