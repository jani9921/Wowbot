"""Ground playbook descriptions in existing proposals and verified outcomes.

No action generation, input, guessed identity or retry-budget reset lives here.
All trial records belong to the existing shared QuestAttemptMemory.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from wowbot.quests.playbooks import PLAYBOOKS, QuestPlaybook, PlaybookStep, recovery_steps
from .models import canonical, number
from .objective_transport import transport_subject
from .quest_reference_matching import reference_objectives


@dataclass(frozen=True)
class PlaybookContext:
    quest_id: str
    objective_id: str
    episode_id: str
    book: QuestPlaybook
    step: PlaybookStep
    option: str
    target: str


def _ids(params, singular, plural):
    return {str(v) for v in [*(params.get(plural) or ()), params.get(singular)] if v is not None}


def _target(params):
    return next((str(params[k]) for k in ("object_guid", "soft_guid", "server_entity_guid", "guid", "target_guid")
                 if params.get(k)), "")


def _objectives(state, quest_id):
    for quest in state.get("active_quests") or ():
        if isinstance(quest, dict) and str(quest.get("quest_id")) == quest_id:
            for index, row in enumerate(quest.get("objectives") or ()):
                if isinstance(row, dict):
                    yield str(row.get("objective_id") or f"{quest_id}:{index}"), row


def _complete(row):
    current, required = number(row.get("current", row.get("current_count"))), number(row.get("required", row.get("required_count")))
    return row.get("is_complete") is True or (row.get("is_complete") is not False
        and None not in (current, required) and current >= required)


def _step(book, proposal, include_missing=False):
    if book is None:
        return None
    if not book.steps and include_missing:
        return PlaybookStep("HANDLER_MISSING", (), "required_execution_handler_missing")
    params = proposal.parameters
    if proposal.skill == "INTERACT" and params.get("object_id") is not None:
        return next((s for s in book.steps if s.name == "USE_OBJECT"), None)
    return next((s for s in book.steps if proposal.skill in s.skills), None)


def context_for(proposal, state, *, include_missing=False) -> PlaybookContext | None:
    """Unique active objective only. Hidden-row order is never a name/ID guess."""
    params = proposal.parameters
    qids, oids = _ids(params, "quest_id", "quest_ids"), _ids(params, "objective_id", "objective_ids")
    if not qids and not oids:
        return None
    target = _target(params)
    entity = (state.get("packet_entities") or {}).get(target) or {}
    entry = params.get("object_id") or params.get("npc_id") or entity.get("entry_id")
    refs = (state.get("reference_knowledge") or {}).get("quests") or {}
    matches = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        qid = str(quest.get("quest_id"))
        if qids and qid not in qids:
            continue
        candidates = []
        for oid, row in _objectives(state, qid):
            if _complete(row) or (oids and oid not in oids):
                continue
            source = reference_objectives(qid, oid, row.get("description"), (refs.get(qid) or {}).get("objectives"))
            reference = source[0] if len(source) == 1 else {}
            mechanism = row.get("mechanism") or reference.get("mechanism")
            if not mechanism:
                from wowbot.quests.mechanics import MechanicResolver
                mechanism = MechanicResolver().resolve(qid, oid, row, reference).mechanism
                if mechanism in {'UNRESOLVED', 'OTHER'}:
                    mechanism = None  # preserve the existing typed objective horizon
            if mechanism == "ARRIVE" and transport_subject(row.get("description")):
                mechanism = "NPC_TRANSPORT"
            book = PLAYBOOKS.get(str(mechanism))
            step = _step(book, proposal, include_missing)
            if step is None:
                continue
            linked = {str(reference.get("credit_object_id")), str((reference.get("object_template") or {}).get("object_id"))}
            linked.update(str(n.get("entry")) for field in ("named_creatures", "talk_creatures", "talk_actor_candidates", "spellclick_creatures")
                          for n in reference.get(field) or () if isinstance(n, dict))
            linked.update(str(n.get('object_id')) for n in reference.get('interaction_objects') or ())
            strong = bool(oids or (entry is not None and str(entry) in linked)
                or (mechanism == "NPC_TRANSPORT" and params.get("interaction_kind") == "RIDE"))
            candidates.append((strong, oid, row, book, step))
        strong = [v for v in candidates if v[0]]
        # Skill compatibility alone cannot disambiguate several unfinished objectives.
        unresolved = [row for _oid, row in _objectives(state, qid) if not _complete(row)]
        candidates = strong or (candidates if len(unresolved) == 1 else [])
        matches.extend((qid, *v[1:]) for v in candidates)
    if len(matches) != 1:
        return None
    qid, oid, row, book, step = matches[0]
    scope = {"session": state.get("session_id") or state.get("character_guid"),
        "instance": (state.get("player_world_position") or {}).get("instance_id"),
        "map": state.get("map_id"), "phase": state.get("phase"), "quest": qid, "objective": oid,
        "mechanism": book.mechanism, "progress": [number(row.get("current", row.get("current_count"))),
            number(row.get("required", row.get("required_count"))), row.get("is_complete")]}
    episode = hashlib.sha256(canonical(scope).encode()).hexdigest()[:20]
    # Times, guidance scores and changed boxes cannot create another option.
    variant = {k: params[k] for k in ("object_approach_probe", "face_on_arrival",
        "activation_source", "action", "gossip_option_id", "option_id", "item_id", "binding")
        if params.get(k) is not None}
    skill = proposal.skill
    if (skill in {"INTERACT", "TALK", "OBJECT_USE"}
            and (params.get("activation_source") in {"SOFT_INTERACT", "INTERACT_KEY", "INTERACT_KEY_PACKET"}
                 or (skill in {"INTERACT", "TALK"} and not params.get("activation_source")))):
        # TALK and INTERACT pressing the same F7 are one option, not a
        # different solution or another strategy budget under a new label.
        skill = "INTERACTTARGET"
        variant.update(activation_source="INTERACTTARGET", binding="INTERACTTARGET")
    if not target and proposal.skill in {"MOVE", "REACH_LOCATION"}:
        variant["point"] = [params.get(k) for k in ("x", "y", "z", "instance_id")]
    option = hashlib.sha256(canonical([step.name, skill, target, variant]).encode()).hexdigest()[:20]
    return PlaybookContext(qid, oid, episode, book, step, option, target)


def scores_for(proposals, state, attempt_memory):
    """Small, explained bias among already proposed actions; no new commands."""
    episodes = attempt_memory.playbook_summary()
    result = {}
    for proposal in proposals:
        ctx = context_for(proposal, state)
        if ctx is None:
            continue
        episode = episodes.get(ctx.episode_id, {})
        failures = episode.get("failed", {})
        count, total = failures.get(ctx.option, 0), sum(failures.values())
        # P8.2: the newest failure's typed reason names the repairing step
        # (recovery edge).  Without an edge the former "any alternative" bias
        # remains; the failed option is avoided either way.
        last = episode.get("last_failure") or {}
        edge = recovery_steps(last.get("step"), last.get("reason")) if last else None
        recovery = None
        if count:
            adjustment, selection = -min(12., 4.*count), "avoid_failed_option"
        elif edge is not None:
            kind, steps = edge
            # The repairing step leads; any other existing alternative still
            # beats the failed option (e.g. a direct object use after a
            # failed approach facing).
            repairs = ctx.step.name in steps and ctx.option != last.get("option")
            adjustment = 8. if repairs else 4.
            selection = "recovery_edge" if repairs else "try_available_alternative"
            recovery = {"failed_step": last.get("step"), "reason": last.get("reason"), "class": kind,
                        "repair_steps": list(steps), "repairs": repairs}
        else:
            adjustment = 6. if total else 0.
            selection = "try_available_alternative" if total else "ordinary_step"
        result[proposal.key] = {"mechanism": ctx.book.mechanism, "step": ctx.step.name,
            "quest_id": ctx.quest_id, "objective_id": ctx.objective_id, "episode_id": ctx.episode_id,
            "option": ctx.option, "prior_failures": count, "episode_failures": total,
            "target_ref": ctx.target, "adjustment": adjustment,
            "verified_predecessors": sorted(episode.get("verified", {}).get(ctx.target, ())),
            "selection": selection, "recovery": recovery,
            "expected": ctx.step.expected, "missing": list(ctx.book.missing)}
        from wowbot.quests.mechanics import MechanicResolver, QuestExecutionGraph
        row = dict(_objectives(state, ctx.quest_id)).get(ctx.objective_id) or {}
        contract = MechanicResolver().resolve(ctx.quest_id, ctx.objective_id, {**row, 'mechanism': ctx.book.mechanism})
        verified = episode.get('verified', {}).get(ctx.target, ())
        nodes = QuestExecutionGraph().build(contract, verified_steps=verified, current_step=ctx.step.name)
        result[proposal.key]['execution_graph'] = QuestExecutionGraph.diagnostic(nodes)
        result[proposal.key]['retry_cooldown_seconds'] = contract.retry_cooldown_seconds
    return result


def horizon_for(proposal, state):
    ctx = context_for(proposal, state, include_missing=True)
    if ctx is None:
        return None
    after = ctx.book.steps[ctx.book.steps.index(ctx.step)+1:] if ctx.book.steps else ()
    previous = f'{ctx.objective_id}:{ctx.book.mechanism}:{ctx.step.name}'
    stages = []
    for step in after:
        node = f'{ctx.objective_id}:{ctx.book.mechanism}:{step.name}'
        stages.append({'capability': step.skills[0], 'expected_observation': step.expected,
                       'preconditions': list(step.preconditions), 'playbook_step': step.name,
                       'node_id': node, 'depends_on': [previous]})
        previous = node
    return ctx, tuple(stages)


def record_trial(attempt, outcome, reason, state, now, attempt_memory):
    before = attempt.baseline
    ctx = context_for(attempt.proposal, before)
    if ctx is None or str(outcome) not in {"SUCCESS", "FAILURE"}:
        return None
    previous = [r for r in attempt_memory.playbook_snapshot() if r["episode_id"] == ctx.episode_id]
    old = dict(_objectives(before, ctx.quest_id)).get(ctx.objective_id) or {}
    new = dict(_objectives(state, ctx.quest_id)).get(ctx.objective_id)
    credit = False
    if new is not None:
        a, b = number(old.get("current", old.get("current_count"))), number(new.get("current", new.get("current_count")))
        credit = (_complete(new) and not _complete(old)) or (None not in (a, b) and b > a)
    success = str(outcome) == "SUCCESS"
    row = {"action_id": attempt.action_id, "at": now, "episode_id": ctx.episode_id,
        "quest_id": ctx.quest_id, "objective_id": ctx.objective_id, "mechanism": ctx.book.mechanism,
        "step": ctx.step.name, "skill": attempt.proposal.skill, "option": ctx.option,
        "target_ref": ctx.target, "outcome": str(outcome), "reason": str(reason),
        "expected": ctx.step.expected, "action_verified": success, "quest_credit": credit,
        "after_failed_action": next((r["action_id"] for r in reversed(previous) if r["outcome"] == "FAILURE"), None),
        "baseline_observation_id": attempt.observation_id,
        "point": {k: attempt.proposal.parameters[k] for k in ("x", "y", "z", "instance_id", "object_approach_probe")
                  if k in attempt.proposal.parameters}}
    return row if attempt_memory.record_playbook_trial(row) else None
