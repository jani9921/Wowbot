"""One deterministic arbitration policy over eligible combat actions."""
import math
from .contracts import CharacterProfile, CastReference, CombatCandidate


class CombatArbitrator:
    """Rank existing eligible actions; no rotation, input or target ownership."""
    def choose(self, abilities, state, now, *, expected_guid=None):
        target = state.get('target') or {}
        if expected_guid is not None and target.get('guid') != expected_guid:
            return None
        profile = CharacterProfile.from_state(state)
        cast = CastReference.from_state(state, now) if type(now) in {int, float} else None
        health, maximum = state.get('health'), state.get('max_health')
        health_fraction = (health/maximum if type(health) in {int, float} and type(maximum) in {int, float}
                           and math.isfinite(health) and math.isfinite(maximum) and maximum > 0 else None)
        candidates = []
        for ability in abilities:
            if not ability.eligible or not ability.binding:
                continue
            tags = set(ability.definition.tags)
            category, priority, deadline = 'ROTATION', 0, None
            if 'INTERRUPT' in tags:
                if cast is None or not cast.interruptible or cast.ends_at-now <= .15:
                    continue
                category, priority, deadline = 'INTERRUPT', 2, cast.ends_at
            if tags & {'DEFENSIVE', 'HEAL'} and health_fraction is not None and health_fraction <= .35:
                category, priority = 'SURVIVAL', 3 if health_fraction <= .2 else 1
            candidates.append((priority, ability.score, CombatCandidate(
                ability.ability_id, ability.binding,
                target.get('guid') if ability.definition.requires_target else None,
                cast.cast_id if category == 'INTERRUPT' else None, profile.bar_revision,
                category, deadline, ability.score)))
        return max(candidates, key=lambda c: (c[0], c[1]))[2] if candidates else None

    @staticmethod
    def verify_interrupt(expected: CastReference, events):
        for event in events:
            body = event.get('payload') or {}
            if (event.get('event_type') == 'SPELL_INTERRUPTED' and body.get('caster_guid') == expected.caster_guid
                    and body.get('cast_id') == expected.cast_id and body.get('spell_id') == expected.spell_id):
                return True
        return None  # cast disappeared/naturally ended is not an interrupt result
