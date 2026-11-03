"""Resolve unmarked 'about X' rows from a current talk objective's TDB topic.

Only a unique role/topic association selects a candidate. Live UI identity,
coordinates and quest-credit verification remain the existing skill's job.
"""
from __future__ import annotations

import re

from .models import number, words
from .quest_semantics import npc_name_matches
from wowbot.runtime.entity_identity import template_id


def self_introduction_option(eligible, options, reference, character_name):
    """An exact actor + an explicit introduction quest + our own greeting.

    No positional default: lore, paid/confirmed rows and multiple plausible
    self-introductions stay unresolved. The caller already verified the actor.
    """
    name = words(str(character_name or '')).strip()
    if not name:
        return None
    pattern = re.compile(r"^(?:i am|i['’]m|my name is)\s+"+re.escape(name)+r'(?!\w)')
    candidates = []
    for quest_id, objective in eligible:
        if objective.get('credit_action') != 'TALK' and objective.get('mechanism') != 'TALK':
            continue
        quest = reference.get(str(quest_id)) or {}
        text = words(' '.join(str(quest.get(k) or '') for k in ('title','objectives_text','description')))
        if not re.search(r'\b(?:introduce yourself|introductions)\b',text):
            continue
        for option in options:
            if (number(option.get('icon')) != 132053
                    or not pattern.search(words(str(option.get('name') or '')))
                    or option.get('box_coded') or option.get('box_text') or option.get('confirm')
                    or any((number(option.get(k)) or 0)>0 for k in ('cost','box_money','money'))):
                continue
            explicit = option.get('quest_id')
            if explicit not in (None,False,'','0',0) and template_id(explicit) != quest_id:
                continue
            candidates.append((quest_id,option))
    unique = {(qid,template_id(option.get('id'))):(qid,option) for qid,option in candidates}
    return next(iter(unique.values())) if len(unique)==1 else None


def quest_topic_option(eligible, options, reference, target):
    matches = {}
    for index, option in enumerate(options):
        text = words(str(option.get('name') or ''))
        if (number(option.get('icon')) != 132053 or not re.search(r'\b(?:about|regarding)\b', text)
                or option.get('box_coded') or option.get('box_text') or option.get('confirm')
                or any((number(option.get(key)) or 0) > 0 for key in ('cost', 'box_money', 'money'))):
            continue
        explicit = option.get('quest_id')
        explicit_id = template_id(explicit)
        if explicit not in (None, False, '', '0', 0) and explicit_id is None:
            continue
        related = set()
        for quest_id, objective in eligible:
            if explicit_id is not None and explicit_id != quest_id:
                continue
            if objective.get('credit_action') != 'TALK' and objective.get('mechanism') != 'TALK':
                continue
            quest = reference.get(str(quest_id)) or {}
            context = words(' '.join(str(value or '') for value in
                            (quest.get('objectives_text'), objective.get('credit_name'))))
            for role in quest.get('quest_roles') or ():
                name = str(role.get('name') or '').strip()
                if (not name or template_id(role.get('npc_id')) is None
                        or npc_name_matches(name, target.get('name'))):
                    continue
                pattern = r'(?<!\w)' + re.escape(words(name)) + r'(?!\w)'
                if re.search(pattern, context) and re.search(pattern, text):
                    related.add(quest_id)
        if len(related) == 1:
            matches[index] = (related.pop(), option)
    # Several rows about the same role do not prove which one advances it.
    counts = {}
    for quest_id, _option in matches.values():
        counts[quest_id] = counts.get(quest_id, 0) + 1
    return next(((quest_id, option) for quest_id, option in matches.values()
                 if counts[quest_id] == 1), None)
