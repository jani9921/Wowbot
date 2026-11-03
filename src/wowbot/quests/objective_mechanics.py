"""What an objective asks the player to do, read ahead from TDB + client DB2.

User 2026-10-26: "a tdb-be nem tudunk rájönni hányféle különböző quest van, és
rákészülni?"  The live surprises of that day were each visible in static data:
- Sharp Practice: the kill credit's creatures are friendly gossip NPCs.
- Kavia's Scouting Scope: a game object's spell gives the kill credit (DB2
  KILL_CREDIT).
- The whelp: a vehicle reached by spellclick.

One pure ``classify`` names the mechanism from facts. Two fact sources share
one interface:
- ``TdbQueryFacts``: per-entry SQL with caches, for the runtime quest
  reference;
- ``TdbIndexFacts``: preloaded, for the census tool.

The runtime reference and the census report therefore always agree.

What the server's C++ scripts do after a gossip (attack or speech), or when
an object opens, is not in the data. The mechanism says what to expect; the
live state still decides.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import re

KILL_CREDIT_EFFECTS = (90, 134)        # SPELL_EFFECT_KILL_CREDIT / KILL_CREDIT2
GOSSIP_NPC_FLAG = 0x1
PROXY_NAME = re.compile(r"kill ?credit|\[dnt\]|\bcredit\b|\bbunny\b|\btrigger\b", re.IGNORECASE)
ESCORT_TEXT = re.compile(r"\b(?:escort|accompany|follow (?:me|him|her|them|us)|"
                         r"keep (?:him|her|them) safe|protect (?:him|her|them) (?:while|as))\b", re.IGNORECASE)
MOUNT_CREDIT = re.compile(r"\bride\b.*\bmount\b|\bmount up\b|\b(?:dragon|sky)riding mount\b", re.IGNORECASE)
TRIGGER_HOPS = 2
LOOT_TABLES = (("creature_loot_template", "CREATURE"), ("gameobject_loot_template", "GAMEOBJECT"),
               ("item_loot_template", "CONTAINER"), ("spell_loot_template", "SPELL"))

# When TDB/DB2 name no credit source (technical "[DNT] Kill Credit", a
# credit spell from a script, a creature without TDB spawns), the objective's
# own verb says what to do.  Census 2026-10-26: "Talk to Marithos", "Dance
# Party Started", "Arrive at the meeting", "Memory of Erasure witnessed",
# "Collector used on live Oozelings", "Open the escape pod".  First match wins.
TEXT_HINTS = (
    ("ESCORT", re.compile(r"\b(?:escort\w*|protect\w*|defend\w*|guard\w*|convoy|survive\w*|accompan\w*|"
                          r"keep \w+ safe)\b")),
    ("EMOTE", re.compile(r"\b(?:danc\w*|cheer\w*|salut\w*|bow\w*|wav\w*|hug\w*|applau\w*|emote\w*)\b"
                         r"|(?:^|\s)/[a-z]+")),
    ("WITNESS", re.compile(r"\b(?:witness\w*|observ\w*|watch\w*|listen\w*|eavesdrop\w*|overhear\w*|wait\w*|ceremony|story heard|"
                           r"leaves|departs)\b")),
    ("TALK", re.compile(r"^(?:talk|speak|report|ask)\b|\b(?:consulted|confronted|approached|greeted|questioned|"
                        r"spoken|informed|convinced|persuaded|briefed|comforted|reassured)\b")),
    ("USE_ITEM", re.compile(r"\b(?:used on|use (?:the |a |an )?[\w' -]+ on|placed|planted|thrown|tossed|applied|"
                            r"poured|fed|sprayed|marked|tagged)\b")),
    ("ARRIVE", re.compile(r"^(?:go|travel|arrive|reach|enter|head|return|fly|climb|find|explore|investigate|"
                          r"search|scout|meet)\b|\b(?:arrived|reached|entered|explored|discovered|located|"
                          r"scouted|investigated)\b")),
    ("INTERACT", re.compile(r"\b(?:open\w*|activat\w*|ignit\w*|lit|light\w*|burn\w*|examin\w*|inspect\w*|"
                            r"repair\w*|freed|rescu\w*|releas\w*|disabl\w*|sabotag\w*|smash\w*|collected|"
                            r"gathered)\b")),
    ("KILL", re.compile(r"\b(?:slain|killed|defeated|destroyed|bested|vanquished|slay|kill|defeat|destroy)\b")),
)
UNKNOWN_SOURCE = {"UNRESOLVED", "PROXY_UNKNOWN", "SPELL_CREDIT"}


def text_hint(description) -> str | None:
    text = re.sub(r"^\s*\d+\s*/\s*\d+\s*", "", str(description or "")).strip().casefold()
    return next((name for name, pattern in TEXT_HINTS if pattern.search(text)), None) if text else None


_TYPE_MECHANISM = {
    2: "OBJECT_USE", 3: "TALK", 10: "AREA_TRIGGER", 19: "AREA_TRIGGER", 20: "AREA_TRIGGER",
    14: "CRITERIA_TREE", 15: "PROGRESS_BAR", 21: "KILL_LABEL",
    11: "PET_BATTLE", 12: "PET_BATTLE", 13: "PET_BATTLE", 9: "PVP", 5: "LEARN_SPELL",
    4: "RESOURCE", 6: "RESOURCE", 7: "RESOURCE", 8: "RESOURCE", 16: "RESOURCE", 17: "RESOURCE", 18: "RESOURCE",
}

# status: LIVE (validated in a live run), PARTIAL (handled in some cases or
# offline only), NONE (no handler), OUT_OF_SCOPE (not planned now).
COVERAGE = {
    "MOUNT": ("LIVE", "TravelModePolicy (mount / skyriding)", "Hop on a dragonriding mount (66116)"),
    "ESCORT": ("PARTIAL", "EscortPolicy: follow, defend its attackers, abandon a FAILED quest", "Black Wagon Flight 65793 (follow live; defence/abandon offline)"),
    "EMOTE": ("PARTIAL", "EmotePolicy + addon quest-action button (ADDON_ACTION)", "offline 2026-11-02; needs the user's binding"),
    "WITNESS": ("PARTIAL", "ObjectiveSpeechHold (+ server Conversation object) / ScriptedRideHold / scene hold", "Edress speech; conversation end offline"),
    "ARRIVE": ("PARTIAL", "ArrivalTargetPolicy (client AreaTrigger XYZ) / quest POI / zone sweep", "trigger target offline 2026-11-02"),
    "INTERACT": ("PARTIAL", "OBJECT_USE / INTERACT when the server shows the target", ""),
    "KILL": ("LIVE", "server_kill_planning + combat", "Exile's Reach, Waking Shores kills"),
    "KILL_LABEL": ("PARTIAL", "kill hunt when the label's creatures are named", "no live case yet"),
    "COLLECT_DROP": ("LIVE", "kill + server loot", "Murloc Mania kits (2026-10-20)"),
    "COLLECT_OBJECT": ("PARTIAL", "object_interaction_flow (game-object loot)", "cocoons/totems; not every chest type"),
    "COLLECT_VENDOR": ("PARTIAL", "BUY_VENDOR", "Stocking Up on Supplies (offline)"),
    "COLLECT_CONTAINER": ("PARTIAL", "ContainerOpenPolicy: bag right-click + LOOT", "offline 2026-11-02"),
    "COLLECT_SPELL": ("PARTIAL", "the spell/use that creates it (USE_ITEM, OBJECT_USE)", ""),
    "COLLECT_OTHER": ("PARTIAL", "ObjectiveProbeLadder at the objective POI", "scripted/spell rewards, item-use crafts"),
    "OBJECT_USE": ("LIVE", "OBJECT_USE F7 (server GUID + flags)", "Harpy Totems 10-19, battle plans 10-26"),
    "CREDIT_OBJECT": ("LIVE", "credit_objects -> OBJECT_USE", "Scouting Scope 2026-10-26 23:08"),
    "TALK": ("LIVE", "ServerNpcInteractionPolicy + QUEST_DIALOG (+ speech hold)", "Fao, Kavia; Edress hold offline"),
    "GOSSIP_ACTOR": ("PARTIAL", "sparring_entries: talk -> option -> fight", "Sharp Practice (offline)"),
    "SPELLCLICK": ("LIVE", "SPELLCLICK F7", "First Aid Kit, Scout-o-Matic (2026-10-25)"),
    "SPELLCLICK_VEHICLE": ("LIVE", "vehicle boarding + VEHICLE_ABILITY", "Giant Boar, Training Wings whelp"),
    "VEHICLE_ABILITY": ("LIVE", "vehicle_abilities (DB2 shapes)", "Training Wings, proto-drake harpoon"),
    "USE_ITEM": ("PARTIAL", "USE_ON_TARGET / quest item opener + DB2 ItemEffect", "Unit/self routing offline-tested; ground/object/mixed targeting needs an execution adapter"),
    "SPELL_CREDIT": ("PARTIAL", "ObjectiveProbeLadder: local gossip NPCs, usable POI objects", "26209 Murder Was The Case (live 2026-10-31)"),
    "AREA_TRIGGER": ("PARTIAL", "ArrivalTargetPolicy (client AreaTrigger XYZ + radius)", "offline 2026-11-02"),
    "PROGRESS_BAR": ("PARTIAL", "hidden kill rows fill the bar", "Fighting Fire with... Water (2026-10-22)"),
    "CRITERIA_TREE": ("PARTIAL", "ObjectiveProbeLadder at the objective POI", "achievement-style criteria"),
    "PROXY_UNKNOWN": ("PARTIAL", "ObjectiveProbeLadder at the objective POI", "technical credit, no source found in TDB/DB2"),
    "UNRESOLVED": ("PARTIAL", "ObjectiveProbeLadder at the objective POI", "no spawn and no credit source in TDB/DB2"),
    "PET_BATTLE": ("OUT_OF_SCOPE", "-", ""), "PVP": ("OUT_OF_SCOPE", "-", ""),
    "RESOURCE": ("PARTIAL", "currency/money/reputation from other work", ""),
    "LEARN_SPELL": ("PARTIAL", "level-up; trainer (S7) later", ""),
    "OTHER": ("NONE", "-", ""),
}


def classify(facts: dict) -> dict:
    """{"mechanism": str, "tags": [..]} from one objective's facts."""
    kind = facts.get("type")
    tags = set()
    if facts.get("escort"):
        tags.add("ESCORT")
    if facts.get("scripted"):
        tags.add("SCRIPTED")
    if facts.get("conversation_actor"):
        tags.add("CONVERSATION")
    if facts.get("proxy"):
        tags.add("PROXY_CREDIT")
    if facts.get("gossip_actor"):
        tags.add("GOSSIP_ACTOR")
    casters = set(facts.get("credit_casters") or ())
    if facts.get("vendor_buy"):
        mechanism = "COLLECT_VENDOR"            # "Any item purchased from <NPC>"
    elif kind == 0:
        if facts.get("mount_credit"):
            mechanism = "MOUNT"                  # "Kill Credit: Ride Any Dragonriding Mount [DNT]"
        elif facts.get("ride_credit"):
            mechanism = "SPELLCLICK_VEHICLE"     # "Kill Credit: Ride Vehicle [DNT]"
        elif facts.get("talk_credit"):
            mechanism = "TALK"
        elif facts.get("spellclick"):
            mechanism = "SPELLCLICK_VEHICLE" if facts.get("vehicle") else "SPELLCLICK"
        elif "GAMEOBJECT" in casters:
            mechanism = "CREDIT_OBJECT"
        elif "SPELLCLICK" in casters:
            mechanism = "SPELLCLICK"
        elif "CREATURE" in casters:
            mechanism = "VEHICLE_ABILITY"
        elif facts.get("gossip_actor") and not facts.get("proxy"):
            # Friendly gossip NPCs: their KillCredit counts after a duel
            # (Blacktalons, 66078), or the talk itself is the credit
            # ("Archivist Edress consulted"; Fao's script casts 372292).
            mechanism = "GOSSIP_ACTOR" if facts.get("credit_sources") else "TALK"
        elif casters:
            mechanism = "USE_ITEM" if facts.get("quest_items") else "SPELL_CREDIT"
        elif facts.get("credit_sources") or (facts.get("spawned") and not facts.get("proxy")):
            mechanism = "KILL"
        elif facts.get("proxy"):
            mechanism = "PROXY_UNKNOWN"
        else:
            mechanism = "UNRESOLVED"
    elif kind == 1:
        sources = set(facts.get("item_sources") or ())
        mechanism = ("COLLECT_DROP" if "CREATURE" in sources else "COLLECT_OBJECT" if "GAMEOBJECT" in sources
                     else "COLLECT_VENDOR" if "VENDOR" in sources
                     else "COLLECT_CONTAINER" if "CONTAINER" in sources
                     else "COLLECT_SPELL" if "SPELL" in sources else "COLLECT_OTHER")
    else:
        mechanism = _TYPE_MECHANISM.get(kind, "OTHER")
    if mechanism in UNKNOWN_SOURCE:
        hint = text_hint(facts.get("description"))
        if hint is not None:
            mechanism = hint
            tags.add("FROM_TEXT")
        elif mechanism == "UNRESOLVED" and facts.get("named_credit"):
            mechanism = "KILL"                   # a named creature the TDB never spawned
            tags.add("NO_TDB_SPAWN")
    return {"mechanism": mechanism, "tags": sorted(tags)}


def objective_facts(world, db2, *, kind, credit_entry, credit_name=None, named=(), credit_action=None,
                    item_sources=None, quest_items=False, escort=False, scripted_quest=False,
                    description=None) -> dict:
    """Facts for ``classify`` from one objective; ``world``/``db2`` are fact sources.
    ``credit_action`` is the TDB provider's text reading (TALK/RIDE/BUY)."""
    facts = {"type": kind, "escort": bool(escort), "quest_items": bool(quest_items),
             "talk_credit": credit_action == "TALK", "ride_credit": credit_action == "RIDE",
             "vendor_buy": credit_action == "BUY", "scripted": bool(scripted_quest),
             "description": description}
    if kind == 1:
        # Quest-item relations first (the runtime reference carries them as
        # item_sources); loot tables only when they name no unit or object.
        kinds = set(item_sources) if item_sources is not None else set(world.item_source_kinds(credit_entry))
        if type(credit_entry) is int and not kinds & {"CREATURE", "GAMEOBJECT"}:
            kinds |= world.loot_source_kinds(credit_entry)
        facts["item_sources"] = kinds
        return facts
    if kind != 0 or type(credit_entry) is not int:
        return facts
    credit = world.creature(credit_entry) or {}
    name = credit_name if credit_name is not None else credit.get("name")
    sources = world.killcredit_sources(credit_entry)
    actors = {credit_entry, *sources, *(entry for entry in named if type(entry) is int)}
    templates = {entry: world.creature(entry) or {} for entry in actors}
    clicked = [entry for entry in actors if world.spellclick_spells(entry)]
    casters = set()
    for spell in credit_spells(db2, credit_entry):
        found = world.spell_casters(spell)
        casters |= found or {"UNKNOWN"}
    facts.update(
        proxy=bool(PROXY_NAME.search(str(name or ""))),
        mount_credit=bool(MOUNT_CREDIT.search(str(name or ""))),
        named_credit=bool(credit) and not PROXY_NAME.search(str(name or "")),
        credit_sources=bool(sources),
        spawned=any(world.spawned(entry) for entry in actors),
        spellclick=bool(clicked),
        vehicle=any(int(templates[entry].get("VehicleId") or 0) > 0 for entry in clicked),
        gossip_actor=any(world.has_gossip(entry) or int(templates[entry].get("npcflag") or 0) & GOSSIP_NPC_FLAG
                         for entry in actors),
        conversation_actor=any(world.conversation_actor(entry) for entry in actors),
        credit_casters=sorted(casters),
        scripted=bool(scripted_quest) or any(templates[entry].get("ScriptName") for entry in actors))
    return facts


def credit_spells(db2, credit_entry) -> set:
    """KILL_CREDIT spells for the entry plus the spells that trigger them."""
    found = set(db2.kill_credit_spells(credit_entry))
    frontier = set(found)
    for _ in range(TRIGGER_HOPS):
        frontier = {parent for spell in frontier for parent in db2.trigger_parents(spell)} - found
        found |= frontier
    return found


class TdbQueryFacts:
    """Per-entry lookups on the read-only WORLD rows (runtime)."""

    def __init__(self, rows, tables):
        self.rows, self.tables = rows, set(tables)

    def _query(self, table, sql, args):
        if table not in self.tables:
            return []
        try:
            return self.rows(sql, args)
        except Exception:                       # older dumps without a column
            return []

    @lru_cache(maxsize=2048)
    def creature(self, entry):
        rows = self._query("creature_template", "SELECT name, npcflag, VehicleId, ScriptName FROM creature_template "
                                                "WHERE entry=?", (entry,))
        return dict(rows[0]) if rows else None

    @lru_cache(maxsize=1024)
    def killcredit_sources(self, entry):
        return frozenset(row["entry"] for row in self._query(
            "creature_template", "SELECT entry FROM creature_template WHERE KillCredit1=? OR KillCredit2=? LIMIT 64",
            (entry, entry)))

    @lru_cache(maxsize=2048)
    def spawned(self, entry):
        return bool(self._query("creature", "SELECT 1 FROM creature WHERE id=? LIMIT 1", (entry,)))

    @lru_cache(maxsize=2048)
    def spellclick_spells(self, entry):
        return frozenset(row["spell_id"] for row in self._query(
            "npc_spellclick_spells", "SELECT spell_id FROM npc_spellclick_spells WHERE npc_entry=?", (entry,)))

    @lru_cache(maxsize=2048)
    def has_gossip(self, entry):
        return bool(self._query("creature_template_gossip",
                                "SELECT 1 FROM creature_template_gossip WHERE CreatureID=? LIMIT 1", (entry,)))

    @lru_cache(maxsize=2048)
    def conversation_actor(self, entry):
        return bool(self._query("conversation_actors",
                                "SELECT 1 FROM conversation_actors WHERE CreatureId=? LIMIT 1", (entry,)))

    @lru_cache(maxsize=1024)
    def spell_casters(self, spell):
        kinds = set()
        if self._query("gameobject_template", "SELECT 1 FROM gameobject_template WHERE (type=22 AND Data0=?) "
                                              "OR (type=10 AND Data10=?) LIMIT 1", (spell, spell)):
            kinds.add("GAMEOBJECT")
        if self._query("npc_spellclick_spells", "SELECT 1 FROM npc_spellclick_spells WHERE spell_id=? LIMIT 1",
                       (spell,)):
            kinds.add("SPELLCLICK")
        if self._query("creature_template_spell", "SELECT 1 FROM creature_template_spell WHERE Spell=? LIMIT 1",
                       (spell,)):
            kinds.add("CREATURE")
        return frozenset(kinds)

    @lru_cache(maxsize=512)
    def loot_source_kinds(self, item):
        kinds = set()
        for table, kind in LOOT_TABLES:
            if self._query(table, f"SELECT 1 FROM {table} WHERE Item=? AND ItemType=0 LIMIT 1", (item,)):
                kinds.add(kind)
        return frozenset(kinds)

    def item_source_kinds(self, item):
        kinds = set()
        if self._query("creature_questitem", "SELECT 1 FROM creature_questitem WHERE ItemId=? LIMIT 1", (item,)):
            kinds.add("CREATURE")
        if self._query("gameobject_questitem", "SELECT 1 FROM gameobject_questitem WHERE ItemId=? LIMIT 1", (item,)):
            kinds.add("GAMEOBJECT")
        if self._query("npc_vendor", "SELECT 1 FROM npc_vendor WHERE item=? LIMIT 1", (item,)):
            kinds.add("VENDOR")
        return frozenset(kinds)


class TdbIndexFacts:
    """The same lookups preloaded from a WORLD sqlite connection (census)."""

    def __init__(self, connection):
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        def rows(table, sql):
            return connection.execute(sql).fetchall() if table in tables else []
        self.creatures = {entry: {"name": name, "npcflag": flags, "VehicleId": vehicle, "ScriptName": script}
                          for entry, name, flags, vehicle, script, _, _ in rows(
                              "creature_template", "SELECT entry, name, npcflag, VehicleId, ScriptName, "
                                                   "KillCredit1, KillCredit2 FROM creature_template")}
        self.sources = defaultdict(set)
        for entry, first, second in rows("creature_template",
                                         "SELECT entry, KillCredit1, KillCredit2 FROM creature_template"):
            for credit in (first, second):
                if credit:
                    self.sources[credit].add(entry)
        self.spawns = {row[0] for row in rows("creature", "SELECT DISTINCT id FROM creature")}
        self.clicks = defaultdict(set)
        for npc, spell in rows("npc_spellclick_spells", "SELECT npc_entry, spell_id FROM npc_spellclick_spells"):
            self.clicks[npc].add(spell)
        self.clicked_spells = {spell for spells in self.clicks.values() for spell in spells}
        self.gossip = {row[0] for row in rows("creature_template_gossip",
                                              "SELECT DISTINCT CreatureID FROM creature_template_gossip")}
        self.actors = {row[0] for row in rows("conversation_actors",
                                              "SELECT DISTINCT CreatureId FROM conversation_actors WHERE CreatureId")}
        self.object_spells = set()
        for kind, data0, data10 in rows("gameobject_template", "SELECT type, Data0, Data10 FROM gameobject_template"):
            if kind == 22 and data0:
                self.object_spells.add(data0)
            if kind == 10 and data10:
                self.object_spells.add(data10)
        self.creature_spells = {row[0] for row in rows("creature_template_spell",
                                                       "SELECT DISTINCT Spell FROM creature_template_spell")}
        self.items = defaultdict(set)
        for table, kind in (("creature_questitem", "CREATURE"), ("gameobject_questitem", "GAMEOBJECT")):
            for (item,) in rows(table, f"SELECT DISTINCT ItemId FROM {table}"):
                self.items[item].add(kind)
        for (item,) in rows("npc_vendor", "SELECT DISTINCT item FROM npc_vendor"):
            self.items[item].add("VENDOR")
        self.loot = defaultdict(set)
        for table, kind in LOOT_TABLES:
            for (item,) in rows(table, f"SELECT DISTINCT Item FROM {table} WHERE ItemType=0"):
                self.loot[item].add(kind)

    def creature(self, entry):
        return self.creatures.get(entry)

    def killcredit_sources(self, entry):
        return frozenset(self.sources.get(entry, ()))

    def spawned(self, entry):
        return entry in self.spawns

    def spellclick_spells(self, entry):
        return frozenset(self.clicks.get(entry, ()))

    def has_gossip(self, entry):
        return entry in self.gossip

    def conversation_actor(self, entry):
        return entry in self.actors

    def spell_casters(self, spell):
        return frozenset(kind for kind, known in (("GAMEOBJECT", self.object_spells),
                                                  ("SPELLCLICK", self.clicked_spells),
                                                  ("CREATURE", self.creature_spells)) if spell in known)

    def item_source_kinds(self, item):
        return frozenset(self.items.get(item, ()))

    def loot_source_kinds(self, item):
        return frozenset(self.loot.get(item, ()))


class Db2IndexFacts:
    """KILL_CREDIT spells and trigger parents preloaded from the client catalog."""

    def __init__(self, connection):
        self.credits, self.parents = defaultdict(set), defaultdict(set)
        for spell, effect, misc, trigger in connection.execute(
                "SELECT spell_id, effect, misc1, trigger_spell FROM spell_effects "
                "WHERE effect IN (90, 134) OR trigger_spell > 0"):
            if effect in KILL_CREDIT_EFFECTS and misc:
                self.credits[misc].add(spell)
            if trigger:
                self.parents[trigger].add(spell)

    def kill_credit_spells(self, entry):
        return sorted(self.credits.get(entry, ()))

    def trigger_parents(self, spell):
        return sorted(self.parents.get(spell, ()))


class _NoDb2:
    def kill_credit_spells(self, entry):
        return []

    def trigger_parents(self, spell):
        return []


def client_db2_facts(path=None):
    """The preloaded client-catalog index (0.16 s once per file version)."""
    from pathlib import Path
    from wowbot.quests.client_catalog import default_catalog_path
    target = Path(path or default_catalog_path())
    try:
        status = target.stat()
    except OSError:
        return _NoDb2()
    return _db2_index(str(target), status.st_mtime_ns, status.st_size)


@lru_cache(maxsize=2)
def _db2_index(path, modified, size):
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
            return Db2IndexFacts(connection)
    except sqlite3.Error:
        return _NoDb2()
