"""Internal objective execution graph over the existing shared playbooks.

QuestGraph owns quest/objective dependencies. These nodes describe stages
inside one objective; neither graph dispatches actions or invents credits.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum

from .objective_mechanics import classify
from .playbooks import PLAYBOOKS


class MechanicNodeState(StrEnum):
    READY = 'READY'
    BLOCKED = 'BLOCKED'
    VERIFIED = 'VERIFIED'
    UNSUPPORTED = 'UNSUPPORTED'
    CONDITIONAL = 'CONDITIONAL'      # a branch entered only while its condition holds


@dataclass(frozen=True, slots=True)
class QuestTargetContext:
    quest_id: str
    objective_id: str
    actor_entries: tuple[int, ...] = ()
    interaction_objects: tuple[int, ...] = ()
    spell_target_entries: tuple[int, ...] = ()
    credit_entries: tuple[int, ...] = ()
    navigation_source: str | None = None
    # Design spec 32.2: where to go and where to search are separate roles.
    nav_target: dict | None = None
    search_region: dict | None = None

    @classmethod
    def from_objective(cls, quest_id, objective_id, row, reference=None):
        reference = reference or {}
        def ids(values):
            return tuple(sorted({v for v in values if type(v) is int and v > 0}))
        entity = row.get('target_entity') or {}
        objects = reference.get('interaction_objects') or ()
        actors = [entity.get('npc_id')]
        actors.extend(r.get('entry') for key in ('named_creatures', 'talk_creatures', 'talk_actor_candidates', 'spellclick_creatures')
                      for r in reference.get(key) or () if isinstance(r, dict))
        return cls(str(quest_id), str(objective_id), ids(actors),
                   ids([entity.get('object_id'), (reference.get('object_template') or {}).get('object_id'),
                        *(r.get('object_id') for r in objects if isinstance(r, dict))]),
                   ids(row.get('spell_target_entries') or ()),
                   ids([reference.get('credit_object_id'), row.get('credit_object_id')]),
                   (row.get('target_location') or {}).get('source'),
                   _point(row.get('target_location')), _region(row, reference))

    def allows_physical_entry(self, entry, *, object_kind=False):
        allowed = self.interaction_objects if object_kind else self.actor_entries
        if not allowed:
            return None  # an unspecified actor is not the technical credit proxy
        return type(entry) is int and entry in allowed


def _point(location):
    if not isinstance(location, dict) or location.get('x') is None or location.get('y') is None:
        return None
    return {k: location.get(k) for k in ('x', 'y', 'z', 'instance_id', 'coordinate_space', 'source')
            if location.get(k) is not None}


def _region(row, reference):
    region = row.get('search_region') or reference.get('search_region')
    if isinstance(region, dict):
        return dict(region)
    triggers = reference.get('area_triggers')
    return {'kind': 'AREA_TRIGGERS', 'ids': list(triggers)} if triggers else None


@dataclass(frozen=True, slots=True)
class MechanicContract:
    mechanism: str
    targets: QuestTargetContext
    preconditions: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    missing_handlers: tuple[str, ...]
    retry_cooldown_seconds: float = 15.
    failure_scope: str = 'OBJECTIVE_STAGE_TARGET'
    # Design spec 32.1/32.3: registry name, success, failure reasons, recovery.
    registry_name: str = 'UNKNOWN_MECHANIC'
    success_condition: str = 'objective_progress_verified'
    failure_reasons: tuple[str, ...] = ()
    recovery_options: tuple[tuple[str, str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class MechanicNode:
    node_id: str
    name: str
    capabilities: tuple[str, ...]
    dependencies: tuple[str, ...]
    state: MechanicNodeState
    expected: str
    preconditions: tuple[str, ...]
    any_of: tuple[str, ...] = ()            # OR: one of these verified is enough
    condition: str | None = None            # a conditional branch


class MechanicResolver:
    def resolve(self, quest_id, objective_id, row, reference=None):
        reference = reference or {}
        # Current server/client objective semantics precede static hints.
        mechanism = row.get('mechanism') or reference.get('mechanism')
        if mechanism == 'ESCORT' and row.get('escort_mode') == 'FOLLOW_ACTOR':
            mechanism = 'ESCORT_FOLLOW'
        if not mechanism:
            facts = {**(reference.get('mechanic_facts') or {}), **row}
            if type(facts.get('type')) is not int:
                facts['type'] = 0  # unresolved credit; shared text classifier may refine it
            mechanism = classify(facts)['mechanism']
        book = PLAYBOOKS.get(str(mechanism))
        missing = book.missing if book else ('mechanism_handler',)
        from .playbooks import FAILURE_CLASSES, RECOVERY_EDGES, registry_name
        steps = {s.name for s in book.steps} if book else set()
        recovery = tuple((failed, kind, tuple(s for s in repair if s in steps))
                         for (failed, kind), repair in sorted(RECOVERY_EDGES.items())
                         if (failed == '*' or failed in steps) and any(s in steps for s in repair))
        return MechanicContract(str(mechanism), QuestTargetContext.from_objective(
            quest_id, objective_id, row, reference), ('objective_active', 'fresh_context', 'skill_authority'),
            tuple(s.expected for s in book.steps) if book else (), tuple(missing),
            registry_name=registry_name(mechanism, (row.get('db2_item_use') or {}).get('target_mode')),
            success_condition=('objective_progress_verified' if book and book.steps
                               else 'unsupported_no_success_claim'),
            failure_reasons=tuple(sorted(FAILURE_CLASSES)) if book and book.steps else ('MECHANIC_UNKNOWN',),
            recovery_options=recovery)


class QuestExecutionGraph:
    def build(self, contract: MechanicContract, *, verified_steps=(), current_step=None):
        book = PLAYBOOKS.get(contract.mechanism)
        if book is None or not book.steps:
            return (MechanicNode(contract.targets.objective_id+':unsupported', 'UNSUPPORTED', (), (),
                                 MechanicNodeState.UNSUPPORTED, 'supported_mechanic_evidence', contract.preconditions),)
        verified = set(verified_steps)
        nodes = []
        mainline: list[MechanicNode] = []     # the last required step, or an OR group of them
        for step in book.steps:
            identity = f'{contract.targets.objective_id}:{contract.mechanism}:{step.name}'
            if step.alternative_of:
                # OR: same predecessors as the step it is an alternative of.
                partner = next(n for n in nodes if n.name == step.alternative_of)
                deps, any_of = partner.dependencies, partner.any_of
            else:
                deps = (mainline[0].node_id,) if len(mainline) == 1 else ()
                any_of = tuple(n.node_id for n in mainline) if len(mainline) > 1 else ()
            done = {n.node_id for n in nodes if n.name in verified}
            ready = (all(d in done for d in deps) and (not any_of or any(a in done for a in any_of)))
            state = (MechanicNodeState.VERIFIED if step.name in verified else
                     MechanicNodeState.CONDITIONAL if step.condition and ready else
                     MechanicNodeState.READY if ready or step.name == current_step else
                     MechanicNodeState.BLOCKED)
            node = MechanicNode(identity, step.name, step.skills, deps, state, step.expected,
                                step.preconditions, any_of, step.condition)
            nodes.append(node)
            if step.condition:
                continue                       # a branch never blocks the next step
            mainline = [*mainline, node] if step.alternative_of else [node]
        return tuple(nodes)

    @staticmethod
    def diagnostic(nodes):
        return [{**asdict(n), 'state': n.state.value} for n in nodes]
