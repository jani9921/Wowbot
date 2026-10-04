"""Structured, incomplete-by-design quest and objective model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .models import canonical, number, words
from .quest_graph import QuestGraph
from .quest_state import ObjectiveState, QuestState, derive_objective_state, derive_quest_state


OBJECTIVE_TYPES = {"TALK_TO", "FIND", "TRAVEL_TO", "COLLECT", "DELIVER", "KILL",
                   "ESCORT", "INTERACT", "EXPLORE", "USE_OBJECT", "WAIT", "DEFEND",
                   "FOLLOW", "RETURN", "BUY", "SELL", "UNKNOWN",
                   # V4-016 minimum-support additions. Additive only: no
                   # existing alias/regex/API mapping below was changed, so
                   # no previously-classified input can change type.
                   "INTERACT_NPC", "KILL_NAMED", "LOOT", "USE_ITEM_ON_TARGET",
                   "REACH_AREA", "EMOTE", "GOSSIP_CHOICE", "VEHICLE",
                   "EXTRA_ACTION", "QUEST_TOOL_BUTTON", "SPECIAL_UI",
                   "SCRIPTED_EVENT", "FIELD_TURN_IN", "MULTI_STAGE"}

_API_TYPES = {"monster": "KILL", "player": "KILL", "item": "COLLECT", "currency": "COLLECT",
              "object": "INTERACT", "progressbar": "UNKNOWN"}
_ALIASES = {"TALK": "TALK_TO", "TALK_TO_ENTITY": "TALK_TO", "MOVE_TO": "TRAVEL_TO",
            "LOOT": "COLLECT", "GATHER": "COLLECT", "USE_ITEM": "USE_OBJECT",
            "TURN_IN": "RETURN", "AREA": "EXPLORE"}
_TEXT_RULES = [
    ("ESCORT", (r"\bescort\b", r"\baccompany\b", r"\bkiserd\b")),
    ("DEFEND", (r"\bdefend\b", r"\bprotect\b", r"\bvedd meg\b")),
    ("FOLLOW", (r"\bfollow\b", r"\bkovesd\b")),
    ("RETURN", (r"\breturn to\b", r"\breport to\b", r"\bturn in\b", r"\bterj vissza\b", r"\bjelentkezz\b")),
    ("TALK_TO", (r"\btalk to\b", r"\bspeak (?:to|with)\b", r"\bmeet\b", r"\bbeszelj\b")),
    ("KILL", (r"\bkill\b", r"\bslay\b", r"\bslain\b", r"\bdefeat\b", r"\bdestroy\b", r"\bold meg\b", r"\bold le\b", r"\bgyozd le\b", r"\bpusztitsd\b")),
    ("BUY", (r"\bpurchased?\b", r"\bbuy\b", r"\bbought\b", r"\bvasarolj\b", r"\bvegyel\b")),
    ("SELL", (r"\bsell\b", r"\bsold\b", r"\beladas\b", r"\badj el\b")),
    ("COLLECT", (r"\bcollect\b", r"\bgather\b", r"\bretrieve\b", r"\brecover\b", r"\bloot\b", r"\bgyujts(?:d)?\b", r"\bszerezz\b", r"\bszedd ossze\b")),
    ("USE_OBJECT", (r"\buse\b", r"\bcook\b", r"\bburn\b", r"\bhasznald\b", r"\bfozd\b", r"\begesd\b")),
    ("INTERACT", (r"\binteract\b", r"\bopen\b", r"\bexamine\b", r"\bnyisd\b", r"\bvizsgald\b")),
    ("TRAVEL_TO", (r"\btravel\b", r"\breach\b", r"\bgo to\b", r"\bmenj\b", r"\berd el\b")),
    ("FIND", (r"\bfind\b", r"\blocate\b", r"\bkeresd\b", r"\btalald\b")),
    ("WAIT", (r"\bwait\b", r"\bvarj\b")),
]


@dataclass(frozen=True)
class ObjectiveClassification:
    """Deterministic classification evidence for the M1 quest layer."""
    type: str
    confidence: float
    evidence: tuple[dict, ...]
    canonical_kind: str


_OBJECT_CLAUSES = (
    r"\b(?:cook|burn)\b.{0,60}?\b(?:on|at|in)\s+(?:the\s+)?[a-z]",
    r"^(?:open|examine|inspect|interact with)\s+(?:the\s+)?[a-z]",
)


# Live 2026-10-04: "0/1 Use Scout-o-Matic 5000 to scout the area" and "0/1
# Ride the Giant Boar" arrive as `monster` objectives (normalized KILL), but
# the named unit is a friendly vehicle NPC that is used/ridden, not killed.
_USE_NPC_CLAUSE = r"^(?:use|ride|mount|board|enter)\s+(?:the\s+)?([a-z][a-z0-9 '\-]*?[a-z0-9])(?:\s+to\b.*)?$"


def use_npc_subject(raw: dict) -> str | None:
    """Name of the unit a "Use <unit> to ..." monster objective addresses."""
    if words(str(raw.get("raw_type") or "")) != "monster" and str(raw.get("type") or "").upper() != "KILL":
        return None
    text = words(str(raw.get("description") or raw.get("text") or ""))
    text = re.sub(r"^\d+\s*/\s*\d+\s*", "", text).strip()
    match = re.search(_USE_NPC_CLAUSE, text)
    name = match[1].strip() if match else ""
    if not 2 < len(name) < 60 or " on " in f" {name} ":
        return None       # "Use <item> on <unit>" is an item use, not a unit to use
    return name


_RIDE_CLAUSE = r"^(?:ride|mount|board|enter)\b"

# Live 2026-10-04 (Stocking Up on Supplies): "Any item purchased from
# Quartermaster Richter" / "Any item sold to Quartermaster Richter" arrive as
# API `object` objectives (-> INTERACT).  The clause names the trade and the
# vendor, so the objective is a BUY/SELL done at that NPC.
_VENDOR_CLAUSES = (
    ("BUY", r"\b(?:purchased?|bought|buy)\b.*?\bfrom\s+(?:the\s+)?(.+?)[\s.!]*$"),
    ("SELL", r"\b(?:sold|sell)\b.*?\bto\s+(?:the\s+)?(.+?)[\s.!]*$"),
)


def vendor_clause(raw: dict) -> tuple[str, str] | None:
    """(BUY|SELL, vendor name) of a "bought from X" / "sold to X" objective."""
    text = str(raw.get("description") or raw.get("text") or "")
    text = re.sub(r"^\s*\d+\s*/\s*\d+\s*", "", text).strip()
    for kind, pattern in _VENDOR_CLAUSES:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        name = match[1].strip() if match else ""
        if 2 < len(name) < 60:
            return kind, name
    return None


def ride_objective_done(quest: dict) -> bool:
    """The quest has a completed "Ride/Mount/Board/Enter <unit>" objective."""
    for objective in quest.get("objectives") or ():
        if not isinstance(objective, dict) or objective.get("is_complete") is not True:
            continue
        text = re.sub(r"^\d+\s*/\s*\d+\s*", "", words(str(objective.get("description") or ""))).strip()
        if re.search(_RIDE_CLAUSE, text) and use_npc_subject(objective):
            return True
    return False


def remount_quests(quests: list, *, in_vehicle, on_taxi=False, skip_quest_ids=()) -> list:
    """Re-open a done "Ride/Mount/Board <vehicle>" objective when needed.

    User 2026-10-04 (Giant Boar): leaving the world dismounts the vehicle,
    but "1/1 Ride the Giant Boar" stays complete, so with "0/8 Monstrous
    Cadaver slain" still open the agent had nothing to do and WAITed.  While
    the player is not in a vehicle and the same quest still has open
    objectives, the done ride objective is presented as open again
    (``remount_required``), so the ordinary named-NPC interaction mounts it.
    """
    if in_vehicle is not False or on_taxi is True:
        return quests
    skip = {str(value) for value in skip_quest_ids or ()}
    result = []
    for quest in quests:
        objectives = quest.get("objectives") if isinstance(quest, dict) else None
        if (not objectives or quest.get("is_complete") is True
                or str(quest.get("quest_id")) in skip
                or not any(isinstance(o, dict) and o.get("is_complete") is not True for o in objectives)):
            result.append(quest)
            continue
        changed = []
        for index, objective in enumerate(objectives):
            text = words(str((objective or {}).get("description") or ""))
            text = re.sub(r"^\d+\s*/\s*\d+\s*", "", text).strip()
            following = objectives[index+1] if index+1 < len(objectives) else None
            # Live 2026-10-04 18:25: started after the scripted dismount, the
            # agent reopened "Ride the Giant Boar" although its stage (8/8
            # cadavers) was over and only "Torgok slain" (on foot) remained.
            # The vehicle serves the objective right after the ride one: ride
            # again only while that one is still open.
            stage_open = isinstance(following, dict) and following.get("is_complete") is not True
            if (isinstance(objective, dict) and objective.get("is_complete") is True and stage_open
                    and re.search(_RIDE_CLAUSE, text) and use_npc_subject(objective)):
                objective = {**objective, "is_complete": False, "current": 0,
                             "remount_required": True}
            changed.append(objective)
        result.append({**quest, "objectives": changed})
    return result


def _object_clause(raw: dict) -> bool:
    text = words(str(raw.get("description") or raw.get("text") or ""))
    text = re.sub(r"^\d+\s*/\s*\d+\s*", "", text).strip()
    return any(re.search(pattern, text) for pattern in _OBJECT_CLAUSES)


class ObjectiveClassifier:
    """Classify normalized objective input without planning or executing it."""
    _canonical = {
        "TALK_TO": "SPEAK", "KILL": "KILL", "COLLECT": "COLLECT",
        "INTERACT": "INTERACT_OBJECT", "USE_OBJECT": "USE_ITEM",
        "TRAVEL_TO": "TRAVEL", "EXPLORE": "AREA_TRIGGER", "WAIT": "WAIT_EVENT",
        "DEFEND": "DEFEND", "FOLLOW": "FOLLOW", "ESCORT": "ESCORT",
        "RETURN": "TURN_IN", "UNKNOWN": "UNKNOWN",
        # V4-016 minimum-support additions (additive; see OBJECTIVE_TYPES).
        "INTERACT_NPC": "INTERACT_NPC", "KILL_NAMED": "KILL_NAMED", "LOOT": "LOOT",
        "USE_ITEM_ON_TARGET": "USE_ITEM_ON_TARGET", "REACH_AREA": "REACH_AREA",
        "EMOTE": "EMOTE", "GOSSIP_CHOICE": "GOSSIP_CHOICE", "VEHICLE": "VEHICLE",
        "EXTRA_ACTION": "EXTRA_ACTION", "QUEST_TOOL_BUTTON": "QUEST_TOOL_BUTTON",
        "SPECIAL_UI": "SPECIAL_UI", "SCRIPTED_EVENT": "SCRIPTED_EVENT",
        "FIELD_TURN_IN": "FIELD_TURN_IN", "MULTI_STAGE": "MULTI_STAGE",
    }

    def classify(self, raw: dict) -> ObjectiveClassification:
        supplied = str(raw.get("type") or "").upper()
        normalized = _ALIASES.get(supplied, supplied)
        if normalized == "COLLECT" and _object_clause(raw):
            # Live 2026-10-03: "Cook the meat on the campfire" arrives as an
            # `item` objective (the cooked item is the credit) but is done by
            # using a world object.  An explicit cook/burn/open clause naming
            # the object makes it an object interaction.
            evidence = ({"type": "INTERACT", "confidence": .8, "source": "OBJECT_CLAUSE_TEXT"},)
            return ObjectiveClassification("INTERACT", .8, evidence, self._canonical["INTERACT"])
        vendor = vendor_clause(raw) if normalized in {"INTERACT", "UNKNOWN", ""} else None
        if vendor is not None:
            evidence = ({"type": vendor[0], "confidence": .85, "source": "VENDOR_CLAUSE_TEXT"},)
            return ObjectiveClassification(vendor[0], .85, evidence, self._canonical.get(vendor[0], vendor[0]))
        if normalized in {"KILL", "UNKNOWN", ""} and use_npc_subject(raw):
            evidence = ({"type": "INTERACT_NPC", "confidence": .8, "source": "USE_NPC_CLAUSE_TEXT"},)
            return ObjectiveClassification("INTERACT_NPC", .8, evidence, self._canonical["INTERACT_NPC"])
        if normalized in OBJECTIVE_TYPES and normalized != "UNKNOWN":
            evidence = ({"type": normalized, "confidence": .95, "source": "ADDON_NORMALIZED"},)
            return ObjectiveClassification(normalized, .95, evidence, self._canonical.get(normalized, normalized))
        api = words(str(raw.get("raw_type") or ""))
        if api in _API_TYPES:
            kind = _API_TYPES[api]
            evidence = ({"type": kind, "confidence": .95, "source": "QUEST_API_TYPE"},)
            return ObjectiveClassification(kind, .95, evidence, self._canonical.get(kind, kind))
        text = words(str(raw.get("description") or raw.get("text") or ""))
        candidates = tuple({"type": kind, "confidence": .65, "source": "TEXT_PATTERN"}
                           for kind, patterns in _TEXT_RULES
                           if any(re.search(pattern, text) for pattern in patterns))
        if len(candidates) == 1:
            kind = candidates[0]["type"]
            return ObjectiveClassification(kind, candidates[0]["confidence"], candidates,
                                           self._canonical.get(kind, kind))
        return ObjectiveClassification("UNKNOWN", .0 if not candidates else .45, candidates, "UNKNOWN")


_CLASSIFIER = ObjectiveClassifier()


def objective_type(raw: dict) -> tuple[str, float, tuple[dict, ...]]:
    """Compatibility projection used by the existing normalized QuestModel."""
    result = _CLASSIFIER.classify(raw)
    return result.type, result.confidence, result.evidence


@dataclass
class QuestObjective:
    objective_id: str
    type: str
    description: str
    target_entity: dict | None
    target_location: dict | None
    target_object: dict | None
    required_count: float | None
    current_count: float | None
    completion_state: str
    confidence: float
    evidence: tuple[str, ...]
    dependencies: tuple[str, ...]
    branch_type: str = "UNKNOWN"
    optional: bool = False
    condition: Any = None
    semantic_candidates: tuple[dict, ...] = ()
    raw: dict = field(default_factory=dict)
    condition_state: str = "NOT_APPLICABLE"
    condition_evidence: tuple[str, ...] = ()
    entity_candidates: tuple[dict, ...] = ()
    location_candidates: tuple[dict, ...] = ()
    status: ObjectiveState = ObjectiveState.PENDING
    failure_memory_key: tuple[str, str] | None = None


@dataclass
class QuestRecord:
    quest_id: int | str
    title: str | None
    description: str | None
    current_state: str
    objectives: list[QuestObjective]
    dependencies: tuple[str, ...]
    known_entities: list[dict]
    known_locations: list[dict]
    required_items: list[dict]
    required_events: list[str]
    completion_conditions: list[dict]
    evidence: tuple[str, ...]
    history: list[dict]
    raw: dict = field(default_factory=dict)
    lifecycle_state: QuestState = QuestState.UNKNOWN
    confidence: float = 0.
    giver_belief: dict | None = None
    turnin_belief: dict | None = None
    reward_belief: dict | None = None
    last_updated_at: float | None = None
    chain_relations: tuple[dict, ...] = ()


# LLM objective actions (semantic_advisor) -> objective types.
_SEMANTIC_TYPES = {"KILL": "KILL", "USE_ITEM_ON_TARGET": "USE_ITEM_ON_TARGET",
                   "RIDE_VEHICLE": "INTERACT_NPC", "TALK": "TALK_TO", "INTERACT_OBJECT": "INTERACT",
                   "COLLECT": "COLLECT", "ESCORT": "ESCORT", "GO_TO": "TRAVEL_TO", "DEFEND": "DEFEND",
                   "USE_VEHICLE_ABILITY": "KILL"}


def apply_semantic_hint(objective: "QuestObjective", hint: dict | None) -> None:
    """Attach a local-LLM interpretation as subordinate evidence.

    The API/addon classification stays authoritative.  The hint decides
    only an UNKNOWN type, or a ``monster`` (KILL) objective the text says
    is ridden / talked to (the Giant Boar / Scout-o-Matic class of errors);
    it may name a missing target/item, but only with words copied from the
    quest's own text (validated in semantic_advisor).
    """
    objective.semantic_hint = dict(hint) if hint else None
    if not hint:
        return
    action = str(hint.get("action") or "UNKNOWN")
    mapped = _SEMANTIC_TYPES.get(action)
    sources = {str(item.get("source")) for item in objective.semantic_candidates or () if isinstance(item, dict)}
    evidence = {"type": mapped, "confidence": .6, "source": "LLM_SEMANTIC", "model": hint.get("model")}
    if mapped and objective.type == "UNKNOWN":
        objective.type, objective.confidence = mapped, .6
        objective.semantic_candidates = tuple(objective.semantic_candidates or ()) + (evidence,)
    elif (objective.type == "KILL" and action in {"RIDE_VEHICLE", "TALK"} and hint.get("target")
          and sources & {"QUEST_API_TYPE", "ADDON_NORMALIZED"}):
        objective.type, objective.confidence = "INTERACT_NPC", .7
        objective.semantic_candidates = tuple(objective.semantic_candidates or ()) + (evidence,)
    elif (hint.get("complex_quest") and objective.type in {"KILL", "COLLECT"}
          and sources & {"QUEST_API_TYPE", "ADDON_NORMALIZED"}
          and mapped in {"USE_ITEM_ON_TARGET", "INTERACT", "ESCORT", "DEFEND"} and hint.get("target")
          and (mapped != "USE_ITEM_ON_TARGET" or hint.get("item"))):
        # User 2026-10-04: on complex quests the LLM's reading of the text
        # may correct the API's coarse monster/item label.
        objective.type, objective.confidence = mapped, .65
        objective.semantic_candidates = tuple(objective.semantic_candidates or ()) + (evidence,)
    if objective.target_entity is None and hint.get("target") and objective.type in {
            "KILL", "INTERACT_NPC", "TALK_TO", "USE_ITEM_ON_TARGET", "ESCORT", "DEFEND"}:
        objective.target_entity = {"npc_id": None, "name": hint["target"], "source": "LLM_OBJECTIVE_TEXT"}
    if (objective.target_object is None and hint.get("item")
            and objective.type in {"USE_ITEM_ON_TARGET", "USE_OBJECT"}):
        objective.target_object = {"item_id": None, "name": hint["item"], "source": "LLM_OBJECTIVE_TEXT"}


def semantic_objective_key(text) -> str:
    return re.sub(r"^\d+\s*/\s*\d+\s*", "", words(str(text or ""))).strip()


class QuestModel:
    def __init__(self):
        self.records: dict[int | str, QuestRecord] = {}
        self.quest_graph = QuestGraph()
        # (quest_id, objective text without counter) -> semantic_advisor hint
        self.semantic_hints: dict[tuple[str, str], dict] = {}

    def apply_semantic_hints(self) -> None:
        for qid, record in self.records.items():
            for objective in record.objectives:
                if getattr(objective, "semantic_hint", None) is None:
                    apply_semantic_hint(objective, self.semantic_hints.get(
                        (str(qid), semantic_objective_key(objective.description))))

    def ingest(self, quests: list[dict], observation_id: str, at: float):
        present = set()
        for raw in quests:
            qid = raw.get("quest_id")
            if qid is None:
                continue
            present.add(qid)
            objectives = [self._objective(qid, index, value, observation_id)
                          for index, value in enumerate(raw.get("objectives") or [])]
            for objective in objectives:
                apply_semantic_hint(objective, self.semantic_hints.get(
                    (str(qid), semantic_objective_key(objective.description))))
            # Ordering is inferred only when the producer explicitly declares
            # SEQUENTIAL. Array order alone is not treated as quest semantics.
            for index, objective in enumerate(objectives):
                if objective.branch_type == "SEQUENTIAL" and not objective.dependencies and index > 0:
                    objective.dependencies = (objectives[index-1].objective_id,)
            current_state = "COMPLETED" if raw.get("is_complete") is True else "FAILED" if raw.get("is_failed") is True else "ACTIVE"
            lifecycle_state = derive_quest_state(raw, objectives)
            signature = canonical({"state": current_state, "lifecycle_state": lifecycle_state.value,
                                   "objectives": [(o.objective_id, o.current_count, o.completion_state) for o in objectives]})
            old = self.records.get(qid)
            history = list(old.history) if old else []
            if not history or history[-1]["signature"] != signature:
                history.append({"at": at, "observation_id": observation_id,
                                "state": current_state, "lifecycle_state": lifecycle_state.value,
                                "signature": signature})
            # A waypoint supplied in the *current* normalized Quest API
            # record is provenance-bearing map evidence, unlike a remembered
            # location.  It still does not identify an NPC by itself, but a
            # newly completed quest may use it as the bounded turn-in search
            # region when no field-completion UI is present.
            locations = [{**value, "source": value.get("source") or "QUEST_API_WAYPOINT"}
                         for value in [raw.get("waypoint")] if isinstance(value, dict)]
            locations.extend(o.target_location for o in objectives if o.target_location)
            objective_entities = [o.target_entity for o in objectives if o.target_entity]
            objective_items = [{"item_id": o.target_object.get("item_id"), "required_count": o.required_count,
                                "objective_id": o.objective_id}
                               for o in objectives if o.target_object and o.target_object.get("item_id") is not None]
            objective_events = [o.type for o in objectives if o.type in {"ESCORT", "DEFEND", "EXPLORE", "WAIT"}]
            record = QuestRecord(qid, raw.get("title"), raw.get("description"), current_state,
                                 objectives, tuple(str(x) for x in raw.get("dependencies", [])),
                                 list(raw.get("known_entities") or []) + objective_entities, locations,
                                 list(raw.get("required_items") or []) + objective_items,
                                 list(dict.fromkeys(list(raw.get("required_events") or []) + objective_events)),
                                 list(raw.get("completion_conditions") or []), (observation_id,), history[-100:], dict(raw))
            record.lifecycle_state = lifecycle_state
            record.confidence = number(raw.get("confidence")) if number(raw.get("confidence")) is not None else .95
            record.giver_belief = dict(raw.get("giver_belief") or {}) or None
            record.turnin_belief = dict(raw.get("turnin_belief") or {}) or None
            record.reward_belief = dict(raw.get("reward_belief") or {}) or None
            record.last_updated_at = at
            record.chain_relations = self.quest_graph.normalize_relations(qid, raw)
            self.records[qid] = record
        for qid, record in self.records.items():
            if qid not in present and record.current_state in {"ACTIVE", "COMPLETED", "FAILED"}:
                record.current_state = "ABSENT"
                record.lifecycle_state = QuestState.ABSENT
                record.history.append({"at": at, "observation_id": observation_id,
                                       "state": "ABSENT", "signature": "ABSENT"})

    @staticmethod
    def _objective(qid, index, raw, observation_id):
        oid = str(raw.get("objective_id") or f"{qid}:{index}")
        kind, confidence, candidates = objective_type(raw)
        required, current = number(raw.get("required", raw.get("required_count"))), number(raw.get("current", raw.get("current_count")))
        # Live 2026-10-04 (Stocking Up on Supplies): the server reported
        # numFulfilled=1/1 for an unfinished objective; the API's explicit
        # finished=false wins over the counters.
        complete = raw.get("is_complete") is True or (
            raw.get("is_complete") is not False
            and required is not None and current is not None and current >= required)
        completion = "COMPLETE" if complete else "IN_PROGRESS" if current is not None else "UNKNOWN"
        location = raw.get("target_location") or raw.get("position")
        if location is None and all(raw.get(key) is not None for key in ("map_id", "x", "y")):
            location = {"map_id": raw.get("map_id"), "x": raw.get("x"), "y": raw.get("y"),
                        "coordinate_space": raw.get("coordinate_space", "NORMALIZED_MAP"),
                        # Preserve Blizzard C_Map's explicit conversion.  The
                        # objective-localization layer otherwise sees only UI
                        # map percentages and cannot request an mmap route.
                        **({"world_position": dict(raw["world_position"])}
                           if isinstance(raw.get("world_position"), dict) else {})}
        dependencies = tuple(str(value if isinstance(value, str) and ":" in value else f"{qid}:{value}")
                             for value in raw.get("dependencies", []))
        target_entity = raw.get("target_entity")
        if target_entity is None and (raw.get("target_npc_id") is not None or raw.get("target_name")):
            target_entity = {"npc_id": raw.get("target_npc_id"), "name": raw.get("target_name"),
                             "source": "QUEST_API"}
        if target_entity is None and kind == "INTERACT_NPC" and use_npc_subject(raw):
            target_entity = {"npc_id": None, "name": use_npc_subject(raw), "source": "OBJECTIVE_TEXT"}
        if target_entity is None and kind in {"BUY", "SELL"} and vendor_clause(raw):
            target_entity = {"npc_id": None, "name": vendor_clause(raw)[1], "source": "VENDOR_CLAUSE_TEXT"}
        target_object = raw.get("target_object")
        if target_object is None and (raw.get("item_id") is not None or raw.get("object_id") is not None):
            target_object = {"item_id": raw.get("item_id"), "object_id": raw.get("object_id"),
                             "source": "QUEST_API"}
        condition = raw.get("condition")
        if condition is None:
            condition_state, condition_evidence = "NOT_APPLICABLE", ()
        elif isinstance(condition, bool):
            condition_state, condition_evidence = ("SATISFIED" if condition else "UNSATISFIED"), (observation_id,)
        elif isinstance(condition, dict) and condition.get("status") in {"SATISFIED", "UNSATISFIED", "UNKNOWN"}:
            condition_state, condition_evidence = condition["status"], (observation_id,)
        elif isinstance(condition, dict) and isinstance(condition.get("is_met"), bool):
            condition_state = "SATISFIED" if condition["is_met"] else "UNSATISFIED"
            condition_evidence = (observation_id,)
        else:
            condition_state, condition_evidence = "UNKNOWN", (observation_id,)
        objective = QuestObjective(oid, kind, str(raw.get("description") or raw.get("text") or ""),
                                   target_entity, location, target_object, required, current,
                                   completion, confidence, (observation_id,), dependencies,
                                   str(raw.get("branch_type") or "UNKNOWN").upper(), bool(raw.get("optional")),
                                   condition, candidates, dict(raw), condition_state, condition_evidence)
        objective.status = derive_objective_state(raw, completion)
        objective.failure_memory_key = (str(qid), oid)
        return objective

    def graph(self) -> dict:
        return self.quest_graph.build(self.records)

    def readiness(self) -> dict[str, dict]:
        return self.quest_graph.readiness(self.records)

    def resolve_hypotheses(self, entity_memory, *, as_of: float | None = None,
                           max_age: float | None = None) -> None:
        """Resolve missing objective identity/location as explicit hypotheses."""
        if entity_memory is None:
            return
        from .quest_semantics import resolve_entity_candidates, resolve_location_candidates
        for record in self.records.values():
            if record.current_state != "ACTIVE":
                continue
            for objective in record.objectives:
                if objective.completion_state == "COMPLETE":
                    continue
                candidates = resolve_entity_candidates({
                    "type": objective.type, "description": objective.description,
                    "target_entity": objective.target_entity, "is_complete": False,
                }, entity_memory)
                objective.entity_candidates = candidates
                objective.location_candidates = resolve_location_candidates(
                    candidates, entity_memory, as_of=as_of, max_age=max_age)

    def apply_event(self, event):
        states = {"QUEST_TURNED_IN": ("TURNED_IN", QuestState.TURNED_IN),
                  "QUEST_COMPLETED": ("COMPLETED", QuestState.COMPLETED),
                  "QUEST_ABANDONED": ("ABANDONED", QuestState.ABANDONED),
                  "QUEST_ABANDONED_OR_REMOVED": ("ABSENT", QuestState.ABSENT),
                  "QUEST_ACCEPTED": ("ACTIVE", QuestState.ACTIVE)}
        state = states.get(event.event_type)
        if not state:
            return
        for qid in event.quest_ids:
            record = self.records.get(qid)
            if record is None:
                continue
            record.current_state, record.lifecycle_state = state
            record.last_updated_at = event.received_at
            if not record.history or record.history[-1].get("state") != state[0]:
                record.history.append({"at": event.received_at, "observation_id": event.observation_id,
                                       "event_id": event.event_id, "state": state[0],
                                       "lifecycle_state": state[1].value, "signature": state[0]})

    def ready(self) -> list[QuestObjective]:
        return self.quest_graph.ready(self.records)

    def snapshot(self) -> list[dict]:
        return [asdict(record) for record in self.records.values()]
