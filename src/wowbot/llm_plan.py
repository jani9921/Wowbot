"""A bounded advisory task DAG. No coordinates, commands or new identities."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class LLMPlanStep:
    step_id: str
    capability: str
    candidate_id: str | None
    actor_ref: str | None
    objective_ref: str | None
    item_ref: str | None
    evidence_refs: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LLMPlan:
    context_token: str
    steps: tuple[LLMPlanStep, ...]

    @classmethod
    def validate(cls, value, context):
        if (not isinstance(value, dict) or set(value) != {'schema', 'context_token', 'steps'}
                or value.get('schema') != 'aipc.llm-plan.v1'
                or not isinstance(value.get('context_token'), str)
                or value['context_token'] != context.get('scope_token')):
            raise ValueError('llm_plan_scope_mismatch')
        raw = value['steps']
        if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
            raise ValueError('llm_plan_step_bound')
        refs = context.get('allowed_refs') or {}
        candidates = {c['id']: c for c in context.get('candidates', ())}
        capabilities = set(context.get('capabilities') or (c['skill'] for c in candidates.values()))
        allowed = {'id', 'capability', 'candidate_id', 'actor_ref', 'objective_ref', 'item_ref', 'evidence_refs', 'depends_on'}
        steps, seen = [], set()
        for item in raw:
            if (not isinstance(item, dict) or set(item)-allowed or not {'id', 'capability', 'evidence_refs', 'depends_on'} <= item.keys()
                    or not isinstance(item['id'], str) or not 1 <= len(item['id']) <= 64 or item['id'] in seen
                    or not isinstance(item['capability'], str) or item['capability'] not in capabilities):
                raise ValueError('llm_plan_invalid_step')
            candidate = item.get('candidate_id')
            if candidate is not None and (not isinstance(candidate, str) or candidate not in candidates or candidates[candidate]['skill'] != item['capability']):
                raise ValueError('llm_plan_candidate_mismatch')
            for field, group in (('actor_ref', 'entities'), ('objective_ref', 'objectives'), ('item_ref', 'items')):
                ref = item.get(field)
                if ref is not None and (not isinstance(ref, str) or ref not in refs.get(group, ())):
                    raise ValueError('llm_plan_unknown_reference')
            evidence, dependencies = item['evidence_refs'], item['depends_on']
            if (not isinstance(evidence, list) or len(evidence) > 16
                    or any(not isinstance(r, str) or r not in refs.get('evidence', ()) for r in evidence)
                    or not isinstance(dependencies, list) or len(dependencies) > 8
                    or any(not isinstance(r, str) or r not in seen for r in dependencies)):
                raise ValueError('llm_plan_dependency_or_evidence_invalid')
            steps.append(LLMPlanStep(item['id'], item['capability'], candidate,
                item.get('actor_ref'), item.get('objective_ref'), item.get('item_ref'), tuple(evidence), tuple(dependencies)))
            seen.add(item['id'])
        return cls(value['context_token'], tuple(steps))

    def as_dict(self):
        return {'schema': 'aipc.llm-plan.v1', 'context_token': self.context_token,
                'steps': [{'id': step.step_id, **{k: (list(v) if isinstance(v, tuple) else v)
                            for k, v in asdict(step).items() if k != 'step_id'}} for step in self.steps]}

    def revalidate(self, context):
        try:
            self.validate(self.as_dict(), context)
            return True
        except (ValueError, TypeError):
            return False
