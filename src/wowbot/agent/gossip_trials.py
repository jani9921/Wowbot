"""Bounded chat-row exploration inside the shared quest-attempt owner.

An option is a trial, never proof of credit. Reopening or moving a menu
does not reset its tried rows; a different quest stage/menu/session does.
"""
from __future__ import annotations

import hashlib
import re

from .models import canonical, number, words
from wowbot.runtime.entity_identity import template_id

MAX_TRIALS = 4


def option_for_quest(option, quest_id):
    explicit = option.get('quest_id')
    return explicit in (None, False, '', '0', 0) or template_id(explicit) == quest_id


def scope(state, quest_id, guid):
    quest = next((q for q in state.get('active_quests') or ()
                  if str(q.get('quest_id')) == str(quest_id)), None)
    if not quest or not guid:
        return None
    ui = state.get('quest_ui') or {}
    progress = [(o.get('objective_id'), o.get('description'),
                 o.get('current', o.get('current_count')), o.get('is_complete'))
                for o in quest.get('objectives') or () if isinstance(o, dict)]
    menu = sorted((str(o.get('id')), str(o.get('name') or ''))
                  for o in ui.get('gossip_options') or () if isinstance(o, dict))
    context = [state.get('session_id'), (state.get('player_world_position') or {}).get('instance_id'),
               state.get('map_id'), str(quest_id), str(guid), progress, menu]
    return hashlib.sha256(canonical(context).encode()).hexdigest()[:24]


def safe_chat(option):
    """Ordinary, addressable chat only; other services keep their own handlers."""
    if (number(option.get('icon')) != 132053 or option.get('available') is False
            or option.get('box_coded') or option.get('box_text') or option.get('confirm')
            or any((number(option.get(k)) or 0) != 0 for k in ('cost', 'box_money', 'money'))):
        return False
    text = words(str(option.get('name') or ''))
    return not re.search(r'\b(?:goodbye|farewell|never mind|teleport|resurrect|purchase|buy|sell|train)\b', text)


PAID_WORDS = re.compile(r'\b(?:copper|silver|gold|coins?|money|pay|bribe)\b')


def paid_chat(option) -> bool:
    """A row that offers payment (its money confirmation comes only after it)."""
    return bool(PAID_WORDS.search(words(str(option.get('name') or ''))))


def exploration_option(eligible, options, tried):
    """The caller has already bound the live menu owner to an open objective."""
    quests = {qid for qid, _ in eligible}
    if len(quests) != 1 or len(tried) >= MAX_TRIALS:
        return None
    quest_id = quests.pop()
    choices = [o for o in options if str(o.get('id')) not in tried and safe_chat(o)
               and option_for_quest(o, quest_id)]
    ready = [o for o in choices if re.match(r"^(?:i am|i['’]m) ready\b", words(str(o.get('name') or '')))]
    # Live 2026-10-31 10:31 (26209): the bribe row came first and opened a
    # money confirmation; the free question works too (user).  Free rows are
    # tried first; a paid row stays a later trial (its confirmation is
    # answered by quest_dialog_planning's GOSSIP_CONFIRM).
    choices.sort(key=paid_chat)
    return (quest_id, (ready or choices)[0]) if choices else None


def record_trial(attempt, outcome, reason, after, now, credit, memory):
    params = attempt.proposal.parameters
    if (attempt.proposal.skill != 'QUEST_DIALOG' or params.get('action') != 'GOSSIP_OPTION_SELECT'
            or params.get('gossip_transition') != 'QUEST_PROGRESS'
            or str(outcome) not in {'SUCCESS', 'FAILURE'}
            or not any(c.kind == 'CLICK' for c in attempt.commands)):
        return None
    # A failed preflight/identity/dispatch is not evidence that a row gives
    # no credit. Only a dispatched click with its complete wait can rule it out.
    if str(outcome) == 'FAILURE' and str(reason).lower() != 'expected_state_not_reached':
        return None
    context = scope(attempt.baseline, params.get('quest_id'), params.get('target_guid'))
    if context is None:
        return None
    row = {'action_id': attempt.action_id, 'at': now, 'scope': context,
           'quest_id': str(params.get('quest_id')), 'target_guid': params.get('target_guid'),
           'option_id': str(params.get('gossip_option_id')), 'outcome': str(outcome),
           'reason': str(reason), 'quest_credit': bool(credit and credit.success),
           'selection_basis': params.get('gossip_selection_basis')}
    return row if memory.record_gossip_trial(row) else None
