"""Character/cast identity and arbitration over existing ability candidates."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import math


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    character_guid: str | None
    class_id: str | int | None
    specialization_id: int | None
    role: str
    style: str
    form: str | int | None
    resource_type: str | int | None
    bar_revision: str
    revision: str
    ability_ids: tuple[int, ...]

    @classmethod
    def from_state(cls, state):
        actions = [a for a in (state.get('actionbar') or ())[:256] if isinstance(a, dict)]
        identities = [(a.get('action'), a.get('id', a.get('spell_id')), a.get('kind')) for a in actions]
        bar = hashlib.sha256(json.dumps([state.get('actionbar_context'), identities], sort_keys=True,
                                       separators=(',', ':'), default=str).encode()).hexdigest()[:20]
        ranges = [a.get('max_range') for a in actions if a.get('is_harmful') is True
                  and type(a.get('max_range')) in {int, float} and math.isfinite(a['max_range'])]
        style = ('MIXED' if any(r <= 5. for r in ranges) and any(r >= 20. for r in ranges) else
                 'RANGED' if any(r >= 20. for r in ranges) else 'MELEE' if ranges else 'UNKNOWN')
        spec = state.get('specialization_id', state.get('spec_id'))
        spec = spec if type(spec) is int and spec > 0 else None
        class_id = next((state[k] for k in ('player_class_id', 'class_id')
                         if type(state.get(k)) is int and state[k] > 0), state.get('class'))
        owner = (state.get('session_id'), state.get('character_guid'), class_id, spec,
                 state.get('form'), state.get('in_vehicle'), state.get('power_type'), bar)
        revision = hashlib.sha256(json.dumps(owner, sort_keys=True, default=str).encode()).hexdigest()[:20]
        role = state.get('role') if state.get('role') in {'TANK', 'HEALER', 'DAMAGE'} else 'UNKNOWN'
        return cls(state.get('character_guid'), class_id, spec, role, style,
                   state.get('form'), state.get('power_type'), bar, revision,
                   tuple(a.get('id', a.get('spell_id')) for a in actions
                         if type(a.get('id', a.get('spell_id'))) is int and a.get('kind') == 'spell'))

    def diagnostic(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CastReference:
    caster_guid: str
    cast_id: str
    spell_id: int
    started_at: float
    ends_at: float
    observed_at: float
    interruptible: bool

    @classmethod
    def from_state(cls, state, now):
        target = state.get('target') or {}
        cast = target.get('cast')
        if not isinstance(cast, dict) or not target.get('guid') or cast.get('caster_guid') != target['guid']:
            return None
        fields = ('started_at', 'ends_at', 'observed_at')
        if (any(type(cast.get(k)) not in {int, float} or not math.isfinite(cast[k]) for k in fields)
                or not cast['started_at'] <= cast['observed_at'] <= now < cast['ends_at']
                or now-cast['observed_at'] > 1. or type(cast.get('interruptible')) is not bool
                or type(cast.get('spell_id')) is not int or cast['spell_id'] <= 0
                or not isinstance(cast.get('cast_id'), str) or not cast['cast_id']):
            return None
        return cls(target['guid'], cast['cast_id'], cast['spell_id'], cast['started_at'],
                   cast['ends_at'], cast['observed_at'], cast['interruptible'])


@dataclass(frozen=True, slots=True)
class CombatCandidate:
    ability_id: object
    binding: str
    target_guid: str | None
    cast_id: str | None
    bar_revision: str
    category: str
    deadline: float | None
    score: float


