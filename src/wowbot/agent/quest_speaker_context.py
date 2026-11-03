"""Resolve 'find me at PLACE' to the quest's speaker, not an NPC named PLACE.

Only candidate template evidence. Current server visibility, exact GUID,
recipient, movement, interaction and credit remain their existing owners.
"""
from __future__ import annotations

import re

from .models import words
from wowbot.runtime.entity_identity import guid_template, template_id

_FIND_ME = re.compile(r'\b(?:find|meet|join)\s+(?:with\s+)?me\s+(?:at|by|near|with)\s+'
                      r'([^.!?\n]{1,100})(?:[.!?\n]|$)', re.IGNORECASE)
_ARTICLES = frozenset({'the', 'a', 'an'})


def speakers_at_subject(state, quest_id, subject, reference):
    """An explicitly addressed meeting place + its own first-person speaker."""
    wanted = set(re.findall(r'[a-z0-9]+', words(str(subject or '')))) - _ARTICLES
    if not wanted:
        return []
    live = state.get('quest_text') or {}
    current = str(live.get('quest_id')) == str(quest_id) and bool(live.get('description'))
    text = str(live['description'] if current else reference.get('description') or '')
    locations = [set(re.findall(r'[a-z0-9]+', words(match.group(1))))
                 for match in _FIND_ME.finditer(text)]
    if not any(wanted <= location for location in locations):
        return []
    if current and live.get('giver_guid'):
        # A same-quest client speaker outranks stale static role variants.
        # The old spawn GUID contributes only its template; it never supplies
        # another spawn's position, current selection or input authority.
        giver = str(live['giver_guid'])
        entry = guid_template(giver).get('npc_id') if giver.startswith('Creature-') else None
        return ([{'entry': entry, 'name': live.get('giver_name'),
                  'source': 'CURRENT_QUEST_TEXT_SPEAKER'}] if entry is not None else [])
    roles = [row for row in reference.get('quest_roles') or () if isinstance(row, dict)
             and template_id(row.get('npc_id')) is not None and row.get('name')]
    names = {words(str(row['name'])).strip() for row in roles}
    if len(names) != 1:
        return []
    return [{'entry': template_id(row['npc_id']), 'name': row['name'],
             'source': 'TDB_FIRST_PERSON_QUEST_SPEAKER'} for row in roles]
