"""A bounded post-use stage of ObjectUseSkill, sharing its identity and verifier."""
import math

from wowbot.agent.models import Command, number
from wowbot.agent.quest_reference_matching import reference_objectives
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.runtime.entity_identity import check_entity_identity


def pull_profile(parameters, world):
    wanted = str(parameters.get('object_id') or '')
    qids = {str(v) for v in parameters.get('quest_ids') or ()}
    if parameters.get('quest_id') is not None:
        qids.add(str(parameters['quest_id']))
    oids = {str(v) for v in parameters.get('objective_ids') or ()}
    if parameters.get('objective_id') is not None:
        oids.add(str(parameters['objective_id']))
    found = []
    refs = (world.get('reference_knowledge') or {}).get('quests') or {}
    for quest in world.get('active_quests') or ():
        qid = str(quest.get('quest_id'))
        if quest.get('is_complete') is True or qids and qid not in qids:
            continue
        for index, objective in enumerate(quest.get('objectives') or ()):
            oid = str(objective.get('objective_id') or f'{qid}:{index}')
            if objective.get('is_complete') is True or oids and oid not in oids:
                continue
            matches = reference_objectives(qid,oid,objective.get('description'),
                                            (refs.get(qid) or {}).get('objectives'))
            if len(matches) != 1:
                continue
            for obj in matches[0].get('interaction_objects') or ():
                if (str(obj.get('object_id')) == wanted and obj.get('motion') == 'PULL_BACKWARD'
                        and obj.get('source') == 'OBJECTIVE_TEXT_AND_TDB_GOOBER_SPELL'):
                    found.append({**obj,'quest_id':qid,'objective_id':oid})
    return found[0] if len(found) == 1 else None


def pull_identity(state, world):
    context = state.skill_context.get('object_use') or {}
    pull = context.get('pull') or {}
    params = state.intent.parameters
    guid = params.get('object_guid')
    entity = (world.get('packet_entities') or {}).get(guid) or {}
    if (not pull.get('profile') or context.get('used_at') is None or not guid
            or pull_profile(params,world) != pull['profile']
            or entity.get('kind') != 'GAMEOBJECT' or entity.get('removed')
            or str(entity.get('map_id')) != str((world.get('player_world_position') or {}).get('instance_id'))):
        return False
    pinned = state.skill_context.get('entity_identity') or {}
    return bool(check_entity_identity(pinned,{'guid':guid,'object_id':params.get('object_id')})
        and check_entity_identity(pinned,
        {'guid':entity.get('guid'),'object_id':entity.get('entry_id')}))


def channel_movement_allowed(state, world, now):
    if state is None or state.skill_type != 'OBJECT_USE':
        return False
    profile = pull_profile(state.intent.parameters,world)
    context = state.skill_context.get('object_use') or {}
    hint = world.get('combat_hint') or {}
    used, sampled = number(context.get('used_at')), number(hint.get('channel_at'))
    if (profile is None or used is None or sampled is None or not 0 <= now-sampled <= .75
            or not 0 <= now-used <= 16. or sampled < used
            or hint.get('channel_spell_id') != profile['spell_id']):
        return False
    guid = state.intent.parameters.get('object_guid')
    entity = (world.get('packet_entities') or {}).get(guid) or {}
    return bool(guid and entity.get('kind') == 'GAMEOBJECT' and not entity.get('removed')
        and check_entity_identity(state.skill_context.get('entity_identity') or {},
            {'guid':entity.get('guid'),'object_id':entity.get('entry_id')}))


def step(skill, state, world, now):
    context = state.skill_context.get('object_use')
    if context is None:
        return None
    pull = context.get('pull')
    if pull is None:
        profile = pull_profile(state.intent.parameters,world)
        if profile is None:
            return None
        pull = context['pull'] = {'profile':profile,'steps':0,'hold_seconds':0.}
        context['objective_ids'] = (profile['objective_id'],)
    used = number(context.get('used_at'))
    if used is None:
        return None
    if (world.get('is_in_combat') or world.get('is_dead') or world.get('is_ghost')
            or world.get('in_vehicle') or world.get('is_mounted')
            or (world.get('movement') or {}).get('falling')
            or world.get('session_id') != state.before_snapshot.get('session_id')):
        return SkillResult(SkillStatus.CANCELLED,FailureReason.INTERRUPTED,replan_required=True,
                           evidence=('object_pull_interrupted',))
    if not pull_identity(state,world):
        entity = (world.get('packet_entities') or {}).get(state.intent.parameters.get('object_guid')) or {}
        if pull['steps'] and (not entity or entity.get('removed')):
            gone_at = pull.setdefault('gone_at',now)
            if now-gone_at <= 3.:
                # Despawn can precede quest_digest credit. Release input,
                # then allow the same verifier to see that bounded delay.
                state.phase = 'VERIFY_PULL_CREDIT'
                return SkillResult(SkillStatus.RUNNING)
        return SkillResult(SkillStatus.FAILURE,FailureReason.IDENTITY_UNCERTAIN,replan_required=True,
                           metadata={'reason':'object_pull_identity_lost'})
    # Wait for the grabbing cast. A slow snapshot can miss it; a 3.5 s
    # settle then permits a bounded trial, never a success claim.
    if now-used < 3.5 and context.get('pull_cast_ended_at') is None:
        state.phase = 'WAIT_PULL_GRAB'
        return SkillResult(SkillStatus.RUNNING)
    position = world.get('player_world_position') or {}
    point = [number(position.get(k)) for k in ('x','y')]
    if None in point:
        return SkillResult(SkillStatus.BLOCKED,FailureReason.STALE_OBSERVATION,replan_required=True)
    start = pull.setdefault('start',point)
    travelled = math.dist(point,start)
    deadline = pull.setdefault('deadline',now+12.)
    if pull['steps'] >= 16 or pull['hold_seconds'] >= 4.8 or travelled >= 8. or now >= deadline:
        return SkillResult(SkillStatus.FAILURE,FailureReason.QUEST_CREDIT_NOT_RECEIVED,replan_required=True,
            evidence=('bounded_object_pull_without_credit',),metadata={'post_use_motion':dict(pull)})
    last = pull.get('last_step_at')
    if last is not None and now-last < .4:
        return SkillResult(SkillStatus.RUNNING)
    if skill.bindings is None or not skill.bindings.contains('MOVEBACKWARD'):
        return SkillResult(SkillStatus.BLOCKED,FailureReason.INPUT_FAILURE,replan_required=True,
                           metadata={'reason':'object_pull_backward_binding_missing'})
    if not callable(skill.step_guard) or not skill.step_guard(world):
        return SkillResult(SkillStatus.BLOCKED,FailureReason.NOT_INTERACTABLE,replan_required=True,
                           metadata={'reason':'object_pull_no_safe_backward_surface'})
    if last is not None and math.dist(point,pull.get('last_position',point)) < .1:
        pull['no_progress'] = pull.get('no_progress',0)+1
        if pull['no_progress'] >= 3:
            return SkillResult(SkillStatus.FAILURE,FailureReason.OBJECTIVE_NOT_PROGRESSING,replan_required=True,
                               metadata={'reason':'object_pull_no_displacement'})
    else:
        pull['no_progress'] = 0
    pull.update(last_step_at=now,last_position=point,steps=pull['steps']+1,
                hold_seconds=pull['hold_seconds']+.3)
    state.phase = 'PULL_BACKWARD'
    return SkillResult(SkillStatus.RUNNING,commands=(Command('BIND','MOVEBACKWARD',.3),),
        evidence=('post_use_pull_backward_trial',),metadata={'post_use_motion':dict(pull)})
