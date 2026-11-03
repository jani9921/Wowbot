"""Primary static WORLD knowledge over the existing readonly catalog.

No new brain, action authority, database copy or write connection. Runtime
snapshots are bounded; larger service/condition data stays queryable on demand.
Live quest state and identity remain authoritative; credit IDs are not GUIDs.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math
import re

_TALK_CREDIT = re.compile(r"\b(?:talk|speak)\s+(?:to|with)\s+(?P<name>[^\[\]]+?)\s*(?:\[DNT\])?\s*$",
                          re.IGNORECASE)
_RIDE_CREDIT = re.compile(r"\b(?:ride|board|mount)\s+(?:the\s+)?vehicle\b", re.IGNORECASE)
# Live 2026-10-25 (Stocking Up on Supplies 55194): "Any item purchased from
# Quartermaster Richter" / "Any item sold to Quartermaster Richter" matched
# neither "purchase" nor a sell clause, so Richter, 5.6 yd away on the server,
# was never walked up to.
_BUY_VENDOR = re.compile(r"\b(?:buy|bought|purchased?)\b.+?\bfrom\s+(?P<name>[^\n]+?)\s*[.!?]?\s*$"
                         r"|\b(?:sell|sold)\b.+?\bto\s+(?P<seller>[^\n]+?)\s*[.!?]?\s*$",
                         re.IGNORECASE)
_CONVERSATION = re.compile(
    r"\b(?:convince|persuade|ask|tell)\s+(?P<name>[^.!?\n]{1,100}?)\s+to\s+"
    r"(?P<action>[^.!?\n]{1,300})", re.IGNORECASE)
_ORDERS_RECEIVED = re.compile(
    r"^(?:\d+\s*/\s*\d+\s*)?(?:orders|instructions|briefing)\s+"
    r"(?:received|heard)\s+from\s+(?P<name>[^.!?\n]{1,100}?)\s*[.!]?\s*$",
    re.IGNORECASE)
_ASK_ABOUT = re.compile(
    r"^(?:\d+\s*/\s*\d+\s*)?ask\s+(?P<name>[^.!?\n]{1,100}?)\s+"
    r"(?:about|regarding)\s+[^\n]{1,300}$", re.IGNORECASE)
# "Escort the wagon", "Escort Nadia safely from the cave": the escorted subject.
_ESCORT_SUBJECT = re.compile(
    r"^(?:\d+\s*/\s*\d+\s*)?(?:escort|protect|accompany)\s+(?:the\s+|an?\s+)?(?P<name>[A-Za-z' -]{3,60}?)"
    r"(?:\s+(?:to|from|safely|through|into|across|back|until|while|as)\b|\s*[.!]?\s*$)", re.IGNORECASE)
_CONVERSATION_STOP = frozenset({"your", "this", "that", "with", "their", "from", "have", "them", "then", "will"})


def _conversation_words(text):
    return {word for word in re.findall(r"[a-z]+", str(text).casefold())
            if len(word) >= 4 and word not in _CONVERSATION_STOP}


class TDBKnowledgeProvider:
    def __init__(self, catalog):
        self.catalog = catalog

    @lru_cache(maxsize=128)
    def object_motions(self, description):
        from wowbot.quests.object_motion import pull_subject, motion_for_template
        from wowbot.quests.client_supplement import ClientSupplement
        subject = pull_subject(description)
        raw = self.catalog.raw
        if not subject or raw is None or 'gameobject_template' not in raw.tables:
            return []
        try:
            from .tdb_builds import newest_rows
            rows = raw.rows('SELECT entry,name,type,Data10,VerifiedBuild FROM gameobject_template '
                            'WHERE name=? COLLATE NOCASE ORDER BY ABS(VerifiedBuild) DESC LIMIT 32', (subject,))
            rows = newest_rows(rows, lambda row: row['entry'])
        except Exception:                       # old/minimal catalogues have no motion data
            return []
        result = []
        for row in rows:
            spell = row.get('Data10')
            if type(spell) is not int or spell <= 0:
                continue
            name = ClientSupplement().record('SpellName',spell).get('Name_lang')
            motion = motion_for_template(description,row,name)
            if motion:
                result.append(motion)
        return result

    def lookup(self, table, record_id):
        """Allowlisted typed-key records; unknown/absent tables return empty."""
        return deepcopy(self.catalog.records('WORLD', table, record_id))

    @lru_cache(maxsize=128)
    def quest(self, quest_id):
        result = deepcopy(self.catalog.quest(quest_id))
        if not result:
            return None
        template = result.pop('template', {})
        result['verified_build'] = template.get('VerifiedBuild')
        details = (result.get('details') or [{}])[0]
        result['chain'] = {key: details.get(key) for key in
            ('PrevQuestID', 'NextQuestID', 'ExclusiveGroup', 'BreadcrumbForQuestId')}
        result['chain']['RewardNextQuest'] = template.get('RewardNextQuest')
        result['chain']['source_build'] = template.get('VerifiedBuild')
        result['eligibility'] = {'status': 'REQUIRES_LIVE_AVAILABILITY',
            'AllowableRaces': template.get('AllowableRaces', result.get('allowable_races')),
            **{key: details.get(key) for key in ('AllowableClasses', 'RequiredSkillID', 'RequiredSkillPoints',
                'RequiredMinRepFaction', 'RequiredMinRepValue', 'RequiredMaxRepFaction', 'RequiredMaxRepValue')}}
        result['items'] = {'start_item_id': template.get('StartItem'),
            'drop_item_ids': [template[f'ItemDrop{i}'] for i in range(1, 5) if template.get(f'ItemDrop{i}')],
            'fixed_rewards': [{'item_id': template.get(f'RewardItem{i}'), 'count': template.get(f'RewardAmount{i}')}
                              for i in range(1,5) if template.get(f'RewardItem{i}')],
            'choice_rewards': [{'item_id': template.get(f'RewardChoiceItemID{i}'), 'count': template.get(f'RewardChoiceItemQuantity{i}')}
                               for i in range(1,7) if template.get(f'RewardChoiceItemID{i}')],
            'source_spell_id': details.get('SourceSpellID')}
        raw = self.catalog.raw
        # Exact quest-role entries may be outside the bounded name-search
        # preview (Wrathion has many historical templates). Carry the name
        # of that exact catalogue entry so current server actors can be
        # matched to an explicitly addressed talk objective without hovering.
        npc_lookup = getattr(self.catalog, 'npc', None)
        if callable(npc_lookup):
            for role in result.get('quest_roles') or ():
                if role.get('name') or role.get('npc_id') is None:
                    continue
                npc = npc_lookup(role['npc_id'])
                if npc and npc.get('name'):
                    role['name'] = npc['name']
        result['faction_variants'] = (raw.rows('SELECT * FROM player_factionchange_quests WHERE alliance_id=? OR horde_id=?',
            (quest_id, quest_id)) if raw and 'player_factionchange_quests' in raw.tables else [])
        for objective in result.get('objectives', []):
            kind, entry = objective.get('raw_type'), objective.get('credit_object_id')
            motions = self.object_motions(str(objective.get('description') or ''))
            if motions:
                objective['interaction_objects'] = motions
            objective['credit_kind'] = {0:'CREATURE_CREDIT', 1:'ITEM', 2:'GAMEOBJECT', 3:'TALK_CREDIT'}.get(kind, 'OTHER')
            vendor = _BUY_VENDOR.search(str(objective.get('description') or ''))
            if vendor and raw:
                # Scripted BUY objectives can be raw type 14, not ITEM.
                # The objective explicitly names the seller; exact TDB
                # templates identify entry candidates, never a guessed GUID.
                objective['credit_action'] = 'BUY'
                objective['named_creatures'] = self.creatures_named(
                    (vendor.group('name') or vendor.group('seller')).strip())
            # Only an explicit gameobject objective identifies a gameobject
            # template. Monster/talk IDs can be invisible proxy credit NPCs.
            if kind == 2 and raw:
                obj = raw.gameobject(entry)
                objective['object_template'] = ({'object_id':entry, 'name':obj['name'],
                    'type':obj['template'].get('type'), 'confirmed':False} if obj else None)
            if kind == 1:
                objective['item_sources'] = self.item_sources(entry)
            if kind == 0 and raw and not vendor:
                # Live 2026-10-11 (56034): the credit entry 156722 is an
                # invisible proxy without spawns; the text names the real
                # creature ("... tested on Wandering Boars", 29 spawns).
                # Location knowledge only -- identity is still the tooltip.
                objective['named_creatures'] = self.named_creatures(
                    objective.get('description') or '', entry)
                # Live 2026-10-20 (Harpy Culling, "Harpies and cohorts
                # slain", credit 152843): Harpy Snatchers, Ambushers and
                # Hunting Worgs give that credit through KillCredit1.
                objective['credit_name'], objective['credit_creatures'] = self.kill_credit(entry)
                # Live 2026-10-26 21:54 (Best Plans and Intentions 66048):
                # "Talonstalker Kavia consulted" (credit 189507) is given by
                # the Scouting Scope's spell 309772 (DB2 KILL_CREDIT 189507);
                # the server sent the scope with quest_objective_id 0.  The
                # agent re-talked to Kavia in a loop.
                credit_objects = self.credit_objects(entry)
                if credit_objects:
                    objective['credit_objects'] = credit_objects
                # Live 2026-10-21 16:13-16:15: "Inquire after the missing
                # dragons" is credit "Kill Credit: Talk to Sendrax [DNT]" and
                # "Hop on the Surveyor's Disc" is "Kill Credit: Ride Vehicle
                # [DNT]"; both were hunted as kills and the agent bounced
                # between quests.  The credit name says what to do.
                talk = _TALK_CREDIT.search(str(objective.get('credit_name') or ''))
                if talk:
                    objective['credit_action'] = 'TALK'
                    objective['talk_creatures'] = self.creatures_named(talk.group('name').strip())
                elif _RIDE_CREDIT.search(str(objective.get('credit_name') or '')):
                    objective['credit_action'] = 'RIDE'
            if kind in {0, 3} and objective.get('credit_action') not in {'BUY', 'RIDE'}:
                from .quest_semantics import talk_to_subject, npc_name_subjects
                subject = talk_to_subject(objective)
                explicit_talk = re.search(r"\b(?:talk\s+to|speak\s+(?:with|to)|ask|report\s+to|beszelj|jelentkezz)\b",
                                          str(objective.get('description') or ''), re.IGNORECASE)
                if subject and explicit_talk:
                    if subject.startswith('the '):
                        # A literal template called 'Forgemaster' is not a
                        # unique answer to the role 'the Forgemaster'. Do not
                        # let the old text-preview lane bypass role resolution.
                        objective['named_creatures'] = []
                    actors = {row['entry']: row for row in objective.get('talk_creatures') or ()}
                    pending = {}
                    for name in npc_name_subjects(subject):
                        resolved = self.creatures_addressed(name)
                        for actor in resolved:
                            actors.setdefault(actor['entry'], actor)
                        if not resolved:
                            for actor in self.creature_name_candidates(name):
                                pending.setdefault(actor['entry'], actor)
                    if pending:
                        # Ambiguous names/roles are not navigation targets.
                        # The common conversation resolver must first narrow
                        # them to current server actors in this quest context.
                        objective['talk_actor_candidates'] = list(pending.values()) if len(pending) <= 256 else []
                        if len(pending) > 256:
                            objective['talk_actor_candidates_truncated'] = True
                    if actors or pending:
                        objective.update(credit_action='TALK', talk_creatures=list(actors.values())[:64])
            if kind in {0, 3} and not objective.get('credit_action'):
                # These explicit conversation captions can use technical
                # kill credits. The 2026-10-22 live "Ask <NPC> about ..."
                # actor was sent by the server but fell outside the generic
                # six-template preview; resolve its exact conversation name.
                description = str(objective.get('description') or '').strip()
                conversation = (_ORDERS_RECEIVED.fullmatch(description)
                                or _ASK_ABOUT.fullmatch(description))
                actors = self.creatures_named(conversation.group('name').strip()) if conversation else []
                if actors:
                    objective.update(credit_action='TALK', talk_creatures=actors,
                                     conversation_source='TDB_OBJECTIVE_TEXT',
                                     conversation_action_text=objective['description'])
            if kind == 0 and raw and not objective.get('credit_action'):
                # Live 2026-10-25 (Exile's Reach): "First Aid Kit used on
                # Kee-La", "Use Scout-o-Matic 5000" and "Ride the Giant Boar"
                # were hunted with Tab; each unit has npc_spellclick_spells,
                # so Interact (F7) on it is the whole objective.
                clickable = [row for row in [{'entry': entry}, *(objective.get('named_creatures') or ())]
                             if row.get('entry') is not None and self.spellclick(row['entry'])]
                if clickable:
                    objective['credit_action'] = 'SPELLCLICK'
                    objective['spellclick_creatures'] = [{'entry': row['entry'], 'name': row.get('name')}
                                                         for row in clickable]
        self._conversation_objective(result)
        # 'Speak with me when you are ready' names the quest's speaker,
        # while the actual objective may be an unrelated technical credit.
        # One role name can have several phase templates; carry their exact
        # catalogue ids, never an invented live GUID or a successful credit.
        if re.search(r'\b(?:speak|talk)\s+(?:with|to)\s+me\b',
                     str(result.get('description') or ''), re.IGNORECASE):
            roles = [r for r in result.get('quest_roles') or () if r.get('name')]
            names = {r['name'].strip().casefold(): r['name'] for r in roles}
            if len(names) == 1:
                result['conversation_speakers'] = self.creatures_addressed(next(iter(names.values())))
        self._mechanisms(result, template, details)
        supplement = getattr(getattr(self.catalog, 'client', None), 'supplement', None)
        if supplement is not None:
            from .quest_item_knowledge import annotate_items
            annotate_items(result, supplement, spell_hits=self.item_spell_hits,
                           spell_targets=self.item_spell_targets)
        return result

    def item_spell_hits(self, spell_id):
        from wowbot.quests.item_spell_hits import spell_hit_credits
        return spell_hit_credits(self, spell_id)

    def item_spell_targets(self, spell_id):
        from wowbot.quests.item_target_conditions import spell_target_entries
        return spell_target_entries(self, spell_id)

    def _mechanisms(self, reference, template, details):
        """objective['mechanism'] / ['mechanism_tags']: what the objective asks
        (objective_mechanics), read ahead from TDB + client DB2.  Knowledge
        only: the live state still decides every action."""
        raw = self.catalog.raw
        if not raw or not callable(getattr(raw, 'rows', None)):
            return
        from wowbot.quests.objective_mechanics import (ESCORT_TEXT, TdbQueryFacts, classify,
                                                       client_db2_facts, objective_facts)
        world = self.__dict__.get('_mechanism_world')
        if world is None or world.rows != raw.rows:
            world = self.__dict__['_mechanism_world'] = TdbQueryFacts(raw.rows, getattr(raw, 'tables', ()))
        db2 = client_db2_facts()
        text = " ".join(str(template.get(key) or '') for key in ('LogTitle', 'LogDescription', 'QuestDescription'))
        quest_items = bool(template.get('StartItem') or details.get('SourceSpellID')
                           or any(template.get(f'ItemDrop{i}') for i in range(1, 5)))
        for objective in reference.get('objectives') or ():
            named = [row.get('entry') for key in ('named_creatures', 'talk_creatures', 'spellclick_creatures')
                     for row in objective.get(key) or () if isinstance(row, dict)]
            sources = objective.get('item_sources')
            try:
                facts = objective_facts(
                    world, db2, kind=objective.get('raw_type'), credit_entry=objective.get('credit_object_id'),
                    credit_name=objective.get('credit_name'), named=named,
                    credit_action=objective.get('credit_action'),
                    item_sources=({row.get('kind') for row in sources if isinstance(row, dict)}
                                  if sources is not None else None),
                    quest_items=quest_items, escort=bool(ESCORT_TEXT.search(text)),
                    scripted_quest=bool(details.get('ScriptName')), description=objective.get('description'))
            except Exception:                       # knowledge only; never break the reference
                continue
            result = classify(facts)
            objective['mechanism'], objective['mechanism_tags'] = result['mechanism'], result['tags']
            if result['mechanism'] == 'ESCORT':
                subject = _ESCORT_SUBJECT.match(str(objective.get('description') or '').strip())
                creatures = (self.escort_creatures(subject.group('name').strip(), objective.get('credit_object_id'))
                             if subject else [])
                if creatures:
                    objective['escort_creatures'] = creatures

    @lru_cache(maxsize=128)
    def escort_creatures(self, name, credit_entry=None):
        """Creature templates an escort objective's subject names ("wagon":
        Inconspicuous Wagon), nearest the credit entry: a quest's own
        creatures are numbered together (live 2026-10-28, 65793: credit
        191087, wagons 190935/191020).  Identity stays the server's
        created-by-us unit; this only says which entries can be it."""
        raw = self.catalog.raw
        if not raw or not name or 'creature_template' not in raw.tables:
            return []
        word = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        try:
            rows = raw.rows("SELECT entry, name FROM creature_template WHERE name LIKE ? LIMIT 400",
                            ('%' + name.replace('%', '').replace('_', '') + '%',))
        except Exception:
            return []
        rows = [row for row in rows if word.search(str(row['name'])) and row['entry'] != credit_entry
                and not str(row['name']).startswith('Kill Credit')]
        if type(credit_entry) is int:
            rows.sort(key=lambda row: abs(int(row['entry'])-credit_entry))
        return [{'entry': row['entry'], 'name': row['name']} for row in rows[:16]]

    def _conversation_objective(self, reference):
        """Ground one explicit instruction in an exact named NPC and objective.

        Technical credit entries ("Send Up Flare") are not the actor. A
        single "Convince <exact TDB NPC> to ..." clause can identify it when
        the action unambiguously overlaps one non-wait objective. This does
        not bind a live GUID or authorize input; the live UI still must match.
        """
        clauses = list(_CONVERSATION.finditer(str(reference.get('objectives_text') or '')))
        if len(clauses) != 1:
            return
        clause = clauses[0]
        if _CONVERSATION.search(clause.group('action')):
            return  # multiple actors/actions in one sentence remain unresolved
        actors = self.creatures_named(clause.group('name').strip())
        if not actors:
            return
        wanted = _conversation_words(clause.group('action'))
        scored = []
        for row in reference.get('objectives') or ():
            text = str(row.get('description') or '').strip()
            if (row.get('raw_type') not in {0, 3} or row.get('credit_action')
                    or not text or re.match(r"^(?:\d+\s*/\s*\d+\s*)?(?:wait|defend)\b", text, re.I)):
                continue
            score = len(wanted & _conversation_words(text))
            if score >= 2:
                scored.append((score, row))
        scored.sort(key=lambda pair: -pair[0])
        if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
            return
        row = scored[0][1]
        row.update(credit_action='TALK', talk_creatures=actors,
                   conversation_source='TDB_OBJECTIVES_TEXT',
                   conversation_action_text=clause.group('action').strip())

    @lru_cache(maxsize=512)
    def spellclick(self, npc_id) -> bool:
        """The creature has npc_spellclick_spells rows (Interact casts on it)."""
        if not callable(getattr(self.catalog, 'records', None)):
            return False
        try:
            return bool(self.lookup('npc_spellclick_spells', npc_id))
        except (TypeError, ValueError):
            return False

    @lru_cache(maxsize=256)
    def creatures_named(self, name):
        """Creature templates with exactly this name (Sendrax has ten)."""
        raw = self.catalog.raw
        if not raw or not name or 'creature_template' not in raw.tables:
            return []
        return [{'entry': row['entry'], 'name': row['name']}
                for row in raw.rows("SELECT entry, name FROM creature_template WHERE name=? LIMIT 24", (name,))]

    @lru_cache(maxsize=256)
    def creatures_addressed(self, name):
        """One full SPEAK name, including unknown titles; static variants only."""
        from .quest_semantics import unique_npc_name_candidates
        return unique_npc_name_candidates(name, self.creature_name_candidates(name))

    @lru_cache(maxsize=256)
    def creature_name_candidates(self, name):
        """Bounded lexical hypotheses; ambiguous results are never auto-routes."""
        raw = self.catalog.raw
        if not raw or not name or 'creature_template' not in raw.tables:
            return []
        from .models import words
        from .quest_semantics import npc_name_candidate_matches
        from .tdb_builds import newest_rows
        text = words(str(name)).removeprefix('the ').strip()
        if not text:
            return []
        # A full name is stronger than a shared role or short name. Do not
        # lose exact variants behind a broad LIKE result's row bound.
        role = words(str(name)).startswith('the ')
        escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        clauses, args = ["name LIKE ? ESCAPE '\\'"], ['%'+escaped+'%']
        if role:
            for field in self._creature_title_columns():
                clauses.append(f'"{field}" LIKE ? ESCAPE \'\\\'')
                args.append('%'+escaped+'%')
        for exact in ((False,) if role else (True, False)):
            rows = (raw.rows('SELECT * FROM creature_template WHERE name=? COLLATE NOCASE LIMIT 257', (text,))
                    if exact else raw.rows('SELECT * FROM creature_template WHERE '+
                                           ' OR '.join(clauses)+' LIMIT 257', tuple(args)))
            if len(rows) > 256:
                return []                # incomplete pool cannot prove uniqueness
            has_build = getattr(raw, '_has_build_column', None)
            if rows and callable(has_build) and has_build('creature_template'):
                # Resolve versions by entry before filtering names: an old
                # matching name must not survive a newer rename/removal of title.
                entries = tuple(dict.fromkeys(row['entry'] for row in rows))
                rows = raw.rows('SELECT * FROM creature_template WHERE entry IN ('+
                                ','.join('?' for _ in entries)+')', entries)
            result = []
            for row in newest_rows(rows, lambda r: r['entry']):
                if exact and words(str(row['name'])) != text:
                    continue
                titles = list(dict.fromkeys(str(row[field]).strip() for field in ('subname', 'TitleAlt')
                                           if isinstance(row.get(field), str) and row[field].strip()))
                if (npc_name_candidate_matches(name, row['name']) or role and any(
                        npc_name_candidate_matches(name, title) for title in titles)):
                    result.append({'entry': row['entry'], 'name': row['name'], **({'titles': titles} if titles else {})})
            if result:
                return result
        return []

    @lru_cache(maxsize=1)
    def _creature_title_columns(self):
        """Optional structured subtitle columns; older/minimal dumps still work."""
        columns = {row.get('name') for row in self.catalog.raw.rows('PRAGMA table_info(creature_template)')}
        return tuple(field for field in ('subname', 'TitleAlt') if field in columns)

    @lru_cache(maxsize=256)
    @lru_cache(maxsize=256)
    def credit_objects(self, credit_entry):
        """Game-object templates whose use spell gives this kill credit:
        SPELLCASTER (22) Data0 or GOOBER (10) Data10 is a DB2 KILL_CREDIT
        spell for the entry.  Location/link knowledge only; the server's GUID
        and flags stay the use authority."""
        raw = self.catalog.raw
        if not raw or type(credit_entry) is not int or 'gameobject_template' not in raw.tables:
            return []
        from wowbot.quests.client_catalog import ClientCatalog
        spells = [int(spell) for spell in ClientCatalog().kill_credit_spells(credit_entry)
                  if type(spell) is int and spell > 0][:32]
        if not spells:
            return []
        marks = ",".join("?" * len(spells))
        try:
            rows = raw.rows(f"SELECT entry, name, type, Data0, Data10 FROM gameobject_template "
                            f"WHERE (type=22 AND Data0 IN ({marks})) OR (type=10 AND Data10 IN ({marks})) "
                            f"ORDER BY entry LIMIT 16", (*spells, *spells))
        except Exception:                      # dumps without Data columns
            return []
        return [{'object_id': row['entry'], 'name': row['name'], 'type': row['type'],
                 'spell_id': row['Data0'] if row['type'] == 22 else row['Data10']} for row in rows]

    def kill_credit(self, credit_entry):
        """(credit template name, creatures whose kill gives that credit)."""
        raw = self.catalog.raw
        if not raw or credit_entry is None or 'creature_template' not in raw.tables:
            return None, []
        try:
            named = raw.rows("SELECT name FROM creature_template WHERE entry=?", (credit_entry,))
            rows = raw.rows("SELECT entry, name FROM creature_template "
                            "WHERE KillCredit1=? OR KillCredit2=? LIMIT 32", (credit_entry, credit_entry))
        except Exception:                      # older dumps without KillCredit columns
            return None, []
        return ((named[0]['name'] if named else None),
                [{'entry': row['entry'], 'name': row['name']} for row in rows])

    @lru_cache(maxsize=256)
    def named_creatures(self, description, credit_entry=None):
        """Creature templates named in an objective text (longest names)."""
        raw = self.catalog.raw
        text = str(description or '').strip()
        if not raw or len(text) < 6 or 'creature_template' not in raw.tables:
            return []
        rows = raw.rows("SELECT entry, name FROM creature_template "
                        "WHERE length(name) >= 4 AND ? LIKE '%' || name || '%' LIMIT 64", (text,))
        # SQLite LIKE ignores case: "rescue Ralia" matched a template named
        # "Rescue", "ogre transformation" one named "Transformation".  A
        # creature name is capitalised in quest text, so require it verbatim.
        # Live 2026-11-02 (26232 "Eavesdrop on Thugs."): a short name (4-5
        # letters) counts only as a whole capitalised word, plural allowed.
        import re
        rows = [r for r in rows if str(r['name']) in text and (
            len(str(r['name'])) >= 6
            or re.search(r'(?<![A-Za-z])' + re.escape(str(r['name'])) + r'(?:s|es)?(?![A-Za-z])', text))]
        names = {str(r['name']) for r in rows}
        longest = {name for name in names
                   if not any(name != other and name.casefold() in other.casefold() for other in names)}
        return [{'entry': r['entry'], 'name': r['name']} for r in rows
                if r['name'] in longest and r['entry'] != credit_entry][:6]

    @lru_cache(maxsize=128)
    def item_sources(self, item_id):
        raw = self.catalog.raw
        if not raw:
            return []
        result = []
        for table, field, kind in (('creature_questitem','CreatureEntry','CREATURE'),
                                   ('gameobject_questitem','GameObjectEntry','GAMEOBJECT')):
            if table in raw.tables:
                order = ' ORDER BY ABS(VerifiedBuild) DESC' if raw._has_build_column(table) else ''
                result.extend({'kind':kind, 'entry':r[field], 'item_id':item_id,
                    'metadata':r, 'relation':'QUEST_ITEM_ASSOCIATION', 'confirmed':False}
                    for r in raw.rows(f'SELECT * FROM {table} WHERE ItemId=?{order} LIMIT 64', (item_id,)))
        # These are acquisition candidates, not guaranteed drops or purchase permission.
        if 'npc_vendor' in raw.tables:
            order = ' ORDER BY ABS(VerifiedBuild) DESC' if raw._has_build_column('npc_vendor') else ''
            result.extend({'kind':'VENDOR', 'entry':r['entry'], 'item_id':item_id,
                'metadata':r, 'relation':'VENDOR_STOCK', 'confirmed':False}
                for r in raw.rows(f'SELECT * FROM npc_vendor WHERE item=? AND type=1{order} LIMIT 64', (item_id,)))
        return result

    @lru_cache(maxsize=64)
    def services(self, npc_id):
        menus = self.lookup('creature_template_gossip', npc_id)
        trainers = self.lookup('creature_trainer', npc_id)
        return {'npc_id': npc_id, 'source':'TDB_REFERENCE', 'confirmed':False,
            'gossip': [{'menu_id':m['MenuID'], 'options':self.lookup('gossip_menu_option', m['MenuID'])} for m in menus],
            'spellclick':self.lookup('npc_spellclick_spells', npc_id),
            'vendor':self.lookup('npc_vendor', npc_id),
            'trainers':[{'relation':t, 'trainer':self.lookup('trainer', t['TrainerID']),
                         'spells':self.lookup('trainer_spell', t['TrainerID'])} for t in trainers],
            'combat_context': {'spells':self.lookup('creature_template_spell', npc_id),
                               'resistances':self.lookup('creature_template_resistance', npc_id)}}

    def quest_locations(self, reference, state, learned=None):
        """Map-scoped spawns for explicit roles / object objectives / item sources.

        An unobserved phase/difficulty is kept in context and filtered at use.
        We never translate a monster credit into a creature to attack.
        """
        position = state.get('player_world_position') or {}
        world_map = position.get('instance_id')
        if world_map is None:
            return []
        wanted = []
        for r in reference.get('quest_roles', ()):
            wanted.append(('CREATURE', r['npc_id'], r['role'], None))
        for r in reference.get('object_roles', ()):
            wanted.append(('GAMEOBJECT', r['object_id'], r['role'], None))
        names = {}
        for o in reference.get('objectives', ()):
            if o.get('raw_type') == 2:
                wanted.append(('GAMEOBJECT', o['credit_object_id'], 'OBJECTIVE', o['objective_id']))
                names[('GAMEOBJECT', o['credit_object_id'])] = (o.get('object_template') or {}).get('name')
            # A "Talk to <NPC>" credit's NPC is where the objective is done; its
            # learned spawns (tdb_learned: Sendrax 193362, four places) count.
            for named in [*(o.get('named_creatures') or ()), *(o.get('talk_creatures') or ())]:
                wanted.append(('CREATURE', named['entry'], 'OBJECTIVE', o['objective_id']))
                names[('CREATURE', named['entry'])] = named.get('name')
            for source in o.get('item_sources') or ():
                wanted.append(('GAMEOBJECT' if source['kind']=='GAMEOBJECT' else 'CREATURE',
                               source['entry'], 'ITEM_SOURCE', o['objective_id']))
        candidates = []
        for kind, entry, role, oid in dict.fromkeys(wanted):
            spawns = (self.catalog.spawn_candidates(world_map, entry) if kind=='CREATURE' else
                      self.catalog.raw.object_spawns(world_map, entry) if self.catalog.raw else ())
            if learned is not None:
                # Live-verified places confirm TDB rows or fill their gaps
                # (script-summoned NPCs have no `creature` row at all).
                from .learned_world import merge_spawns
                spawns = merge_spawns(spawns, learned.spawns(world_map, kind, entry, names.get((kind, entry))))
            for spawn in spawns:
                candidates.append({**spawn, 'entity_kind':kind, 'entry':entry,
                                   'role':role, 'objective_id':oid})
        def distance(row):
            return math.hypot(float(row['x'])-float(position.get('x') or 0), float(row['y'])-float(position.get('y') or 0))
        ordered = sorted(candidates, key=distance)
        # Reserve one candidate for each typed role/objective group before
        # filling by proximity. Otherwise 32 nearby kill spawns hide the
        # known distant ender from both look-ahead and the shared resolver.
        reserved = {}
        for row in ordered:
            group = row['role'], row['entity_kind'], row['entry'], row.get('objective_id')
            reserved.setdefault(group, row)
        selected = list(reserved.values())[:32]
        selected_ids = {id(row) for row in selected}
        for row in ordered:
            if len(selected) >= 32:
                break
            if id(row) not in selected_ids:
                selected.append(row)
                selected_ids.add(id(row))
        return sorted(selected, key=distance)
