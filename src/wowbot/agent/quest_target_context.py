"""Quest role constraints at the shared skill identity boundary."""
from wowbot.quests.mechanics import QuestTargetContext
from .quest_reference_matching import reference_objectives


def physical_target_problem(skill, parameters, wanted, state):
    qid, oid = parameters.get('quest_id'), parameters.get('objective_id')
    if qid is None or oid is None:
        return None
    quest = next((q for q in state.get('active_quests') or ()
                  if isinstance(q, dict) and str(q.get('quest_id')) == str(qid)), None)
    if quest is None:
        return None  # absence is a separate baseline/quest-lifecycle question
    row = next((o for i, o in enumerate(quest.get('objectives') or ())
                if isinstance(o, dict) and str(o.get('objective_id', f'{qid}:{i}')) == str(oid)), None)
    if row is None:
        return None
    reference = ((state.get('reference_knowledge') or {}).get('quests') or {}).get(str(qid)) or {}
    matches = reference_objectives(qid, oid, row.get('description'), reference.get('objectives') or ())
    # A current quest-specific UI relationship can supersede a stale static
    # actor list. Generic yellow markers still do not identify a quest actor.
    ui = state.get('quest_ui') or {}
    if (isinstance(ui, dict) and ui.get('open') is True and str(ui.get('quest_id')) == str(qid)
            and ui.get('npc_guid') and ui.get('npc_guid') == wanted.get('guid')):
        return None
    entity = (state.get('packet_entities') or {}).get(wanted.get('guid')) or {}
    binding = ((state.get('server_quest_objectives') or {}).get(str(qid)) or {}).get(str(oid)) or {}
    native_id = binding.get('server_objective_id')
    technical = ({native_id} if type(native_id) is int and native_id > 0 else
                 {row.get('quest_objective_id'), *(m.get('objective_id') for m in matches)})
    server_objective = (entity.get('info') or {}).get('quest_objective_id')
    if type(server_objective) is int and server_objective > 0 and server_objective in technical:
        return None
    context = QuestTargetContext.from_objective(qid, oid, row, matches[0] if len(matches) == 1 else None)
    from wowbot.runtime.entity_identity import guid_template, template_id
    fields = {**guid_template(wanted.get('guid')), **wanted}
    object_kind = fields.get('object_id') is not None
    entry = template_id(fields.get('object_id' if object_kind else 'npc_id'))
    if entry is None:
        return None
    allowed = context.allows_physical_entry(entry, object_kind=object_kind)
    if skill in {'USE_ON_TARGET', 'ASSIST', 'VEHICLE_ABILITY'} and context.spell_target_entries:
        allowed = entry in context.spell_target_entries
    return 'QUEST_PHYSICAL_TARGET_ROLE_MISMATCH' if allowed is False else None
