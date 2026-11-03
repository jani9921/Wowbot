"""Conservative text hypotheses; never a quest-ID-specific behavior script."""
import re
from typing import Any
from .models import words


def combat_subjects(objective: dict) -> list[str]:
    if objective.get("is_complete"):
        return []
    text = words(str(objective.get("description") or ""))
    patterns = [r"(?:defeated|slain|killed)\s+([a-z][a-z '-]+)",
                r"(?:\d+\s*/\s*\d+\s+)?([a-z][a-z '-]+?)\s+(?:slain|defeated|killed)"]
    result = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            subject = match[1].strip().rstrip(".")
            if 2 < len(subject) < 80:
                result.append(subject)
    return result


def talk_to_subject(objective: dict) -> str | None:
    """Extract an addressed entity name without turning it into a fact."""
    if objective.get("is_complete"):
        return None
    text = words(str(objective.get("description") or ""))
    patterns = [r"\bask\s+([a-z][a-z '&-]+?)\s+to\b",
                r"\btalk to\s+([a-z][a-z '&-]+)", r"\bspeak (?:to|with)\s+([a-z][a-z '&-]+)",
                r"\breport to\s+([a-z][a-z '&-]+)", r"\bmeet\s+(?:with\s+)?([a-z][a-z '&-]+)",
                r"\bbeszelj\s+([a-z][a-z '&-]+)", r"\bjelentkezz\s+([a-z][a-z '&-]+)"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        subject = match[1].strip().rstrip(".")
        # A location qualifies the conversation, not the NPC's name:
        # "Speak with Wrathion at the Oathstone" addresses Wrathion.
        subject = re.split(r"\b(?:about|regarding|to|at|near|inside|outside|hogy|arrol)\b", subject)[0].strip()
        if 2 < len(subject) < 80:
            return subject
    return None


NPC_SPEAK_TYPES = frozenset({"TALK_TO", "INTERACT_NPC", "BUY", "SELL"})
_NPC_TITLES = frozenset({"lady", "lord", "captain", "private", "apprentice", "master",
                         "quartermaster", "commander", "general", "doctor", "sir", "the",
                         "guard", "scout", "soldier", "someone", "anyone", "forgemaster"})


def npc_name_subjects(expected: str) -> tuple[str, ...]:
    """Explicitly coordinated SPEAK names, including the literal whole name.

    'Left and Right' can address either actor. Bare titles or pronouns do
    not become extra candidates. This is not a combat-target alias rule.
    """
    full = words(str(expected or "")).strip()
    meaningful = lambda part: any(len(token) >= 3 and (token not in _NPC_TITLES
                                  or part.startswith("the ") and token != "the")
                                  and token not in {"and", "or", "him", "her", "them", "you", "me"}
                                  for token in part.split())
    if not full or not meaningful(full):
        return ()
    parts = re.split(r"\s+(?:and|&)\s+", full)
    return tuple(dict.fromkeys([full, *parts])) if 2 <= len(parts) <= 3 and all(map(meaningful, parts)) else (full,)


def npc_name_matches(expected: str, actual: str) -> bool:
    """Whole-token short NPC names in a SPEAK context, never combat aliases.

    "Meredy" may address "Meredy Huntswell"; a bare title, word fragment,
    different surname, or arbitrary preceding name cannot identify an NPC.
    """
    observed = words(str(actual or "")).split()
    subjects = npc_name_subjects(expected)
    for subject in subjects:
        wanted = subject.split()
        for start in range(len(observed)-len(wanted)+1):
            if (observed[start:start+len(wanted)] == wanted
                    and (subject == subjects[0] or start+len(wanted) == len(observed))
                    and all(word in _NPC_TITLES and word not in {"someone", "anyone"}
                            for word in observed[:start])):
                return True
    return False


def npc_name_candidate_matches(expected: str, actual: str) -> bool:
    """Whole-name terms for TALK candidate discovery, not confirmed identity.

    Unknown prefixes need no title whitelist here. A definite role such as
    'the Forgemaster' can match a name or that NPC's own TDB subtitle. Callers
    must resolve competing names before returning executable actor entries.
    """
    observed = words(str(actual or "")).split()
    subjects = npc_name_subjects(expected)
    for subject in subjects:
        wanted = subject.removeprefix("the ").split()
        if not wanted:
            continue
        for start in range(len(observed) - len(wanted) + 1):
            if (observed[start:start+len(wanted)] == wanted
                    and (subject == subjects[0] or start+len(wanted) == len(observed))
                    and not {"someone", "anyone"}.intersection(observed[:start])):
                return True
    return False


def unique_npc_name_candidates(expected: str, candidates) -> list[dict]:
    """Prefer a full exact name, otherwise require one matching full NPC name.

    Several template entries with the same full name are static variants;
    their current server GUIDs still have to be resolved by the caller.
    A subtitle is candidate evidence only for an explicitly requested role.
    """
    query = words(str(expected or "")).removeprefix("the ").strip()
    role = words(str(expected or "")).startswith("the ")
    matched = [row for row in candidates if isinstance(row, dict) and row.get("name")
               and (npc_name_candidate_matches(expected, row["name"])
                    or role and any(npc_name_candidate_matches(expected, title)
                                    for title in row.get("titles") or ())) ]
    exact = [row for row in matched if not role and words(str(row["name"])) == query]
    matched = exact or matched
    return matched if len({words(str(row["name"])) for row in matched}) == 1 else []


def _objective_field(objective, key, default=None):
    return objective.get(key, default) if isinstance(objective, dict) else getattr(objective, key, default)


def friendly_live_npc(target: dict) -> bool:
    guid = str(target.get("guid") or "")
    return bool(guid and not guid.startswith("Player-") and target.get("is_player") is not True
                and str(target.get("unit_type") or "").upper() != "PLAYER"
                and target.get("dead") is not True and target.get("is_dead") is not True
                and target.get("attackable", target.get("is_attackable")) is False)


def speak_target_matches(objective, target: dict) -> bool:
    """One pure NPC association shared by location, targeting and dialog policy."""
    if (not friendly_live_npc(target) or _objective_field(objective, "is_complete") is True
            or _objective_field(objective, "completion_state") == "COMPLETE"):
        return False
    description = _objective_field(objective, "description", "")
    subject = talk_to_subject({"description": description})
    if str(_objective_field(objective, "type", "")).upper() not in NPC_SPEAK_TYPES and not subject:
        return False
    entity = _objective_field(objective, "target_entity") or {}
    # Explicit identity is decisive: a matching name must not repair a wrong ID.
    from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
    explicit = identity_fields(entity)
    if explicit:
        return bool(check_entity_identity(explicit, target))
    expected = entity.get("name") or subject
    if not expected or not npc_name_matches(expected, target.get("name")):
        return False
    alternatives = {words(str(row.get("name") or ""))
                    for row in _objective_field(objective, "entity_candidates", ()) or ()
                    if isinstance(row, dict) and npc_name_matches(expected, row.get("name"))}
    return len(alternatives) <= 1 or len(npc_name_subjects(expected)) > 1


def npc_referenced_by_objective(objective, target: dict) -> bool:
    """Gossip can serve SPEAK or a named scripted fight, but not a random NPC."""
    if (not friendly_live_npc(target) or _objective_field(objective, "is_complete") is True
            or _objective_field(objective, "completion_state") == "COMPLETE"):
        return False
    entity = _objective_field(objective, "target_entity") or {}
    from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
    explicit = identity_fields(entity)
    if explicit:
        return bool(check_entity_identity(explicit, target))
    subject = talk_to_subject({"description": _objective_field(objective, "description", "")})
    if str(_objective_field(objective, "type", "")).upper() in NPC_SPEAK_TYPES or subject:
        return speak_target_matches(objective, target)
    actual = words(str(target.get("name") or ""))
    description = words(str(_objective_field(objective, "description", "")))
    return bool(actual and f" {actual} " in f" {description} ")


def healing_subject(objective: dict) -> str | None:
    """A literal healing counter is an action, not a defend/wait event."""
    text = re.sub(r"^\d+\s*/\s*\d+\s*", "", words(str(objective.get("description") or "")))
    match = (re.fullmatch(r"([a-z][a-z '\-]{2,70}?)\s+(?:healed|treated|revived)", text)
             or re.fullmatch(r"(?:heal|treat|revive)\s+(?:the\s+)?([a-z][a-z '\-]{2,70})", text))
    return match[1].strip() if match else None


def use_on_subjects(objective: dict) -> list[str]:
    """Extract target names from an evidence-backed item-use objective."""
    if objective.get("is_complete"):
        return []
    if objective.get("db2_item_use") and objective.get("item_target_names"):
        return list(objective["item_target_names"])
    if (objective.get("quest_tool_kind") == "HEAL"
            and objective.get("quest_tool_item_id") is not None):
        subject = objective.get("item_target_name") or healing_subject(objective)
        return [str(subject)] if subject else []
    text = words(str(objective.get("description") or ""))
    supplied = str(objective.get("type") or "").upper()
    explicit_item_use = supplied in {"USE_ITEM", "USE_ITEM_ON_TARGET", "USE_OBJECT"}
    match = re.search(r"\buse\b.{0,40}?\bon\s+([a-z][a-z,'\- ]+)", text)
    if not match and explicit_item_use:
        # Some Retail objectives name the exact quest tool and say it was
        # "tested on" a unit, without the literal verb "use".  This broader
        # clause is admitted only after structured objective classification.
        match = re.search(r"\bon\s+([a-z][a-z,'\- ]+)", text)
    if not match:
        return []
    tail = re.split(r"[.;:]", match[1])[0]
    parts = re.split(r",|\band\b", tail)
    return [name.strip() for name in parts if 2 < len(name.strip()) < 40]


def subject_matches_name(subjects: list[str], name: str | None) -> bool:
    """Conservative whole-name match with only a trailing plural variation."""
    actual = words(str(name or "")).strip()
    if not actual:
        return False
    variants = {actual}
    if actual.endswith("s") and not actual.endswith("ss"):
        variants.add(actual[:-1])
    else:
        variants.add(actual + "s")
    for subject in subjects:
        expected = words(subject).strip()
        expected_variants = {expected}
        if expected.endswith("s") and not expected.endswith("ss"):
            expected_variants.add(expected[:-1])
        else:
            expected_variants.add(expected + "s")
        if variants & expected_variants:
            return True
    return False


def world_object_subjects(objective: dict) -> list[str]:
    """Extract tooltip-checkable object names from generic interaction clauses."""
    if objective.get("is_complete"):
        return []
    text = words(str(objective.get("description") or ""))
    patterns = [
        r"\b(?:cook|burn)\b.{0,60}?\b(?:on|at|in)\s+(?:the\s+)?([a-z][a-z '\-]+)",
        r"\buse\b.{0,50}?\b(?:on|at)\s+(?:the\s+)?([a-z][a-z '\-]+)",
        r"\b(?:open|examine|inspect|interact with)\s+(?:the\s+)?([a-z][a-z '\-]+)",
        # "Trapped Expedition Member rescued from cocoons" (Hrun's pit, 2026-10-06)
        r"\b(?:rescued|freed|released|saved|pulled)\s+from\s+(?:the\s+)?([a-z][a-z '\-]+)",
    ]
    result = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            subject = re.split(r"[.;:,]", match[1])[0].strip()
            if 2 < len(subject) < 60:
                result.append(subject)
    return list(dict.fromkeys(result))


def objective_subject(objective: dict) -> str | None:
    """Return a textual subject hypothesis, or None when unsupported."""
    target_entity = objective.get("target_entity") or {}
    if target_entity.get("name"):
        return str(target_entity["name"])
    kind = str(objective.get("type") or "").upper()
    if kind == "KILL":
        subjects = combat_subjects(objective)
        return subjects[0] if subjects else None
    if kind in {"TALK_TO", "INTERACT_NPC", "RETURN"}:
        return talk_to_subject(objective)
    return None


def resolve_entity_candidates(objective: dict, entity_memory, *, limit: int = 5) -> tuple[dict, ...]:
    target_entity = objective.get("target_entity") or {}
    if target_entity.get("npc_id") is not None or entity_memory is None:
        return ()
    subject = objective_subject(objective)
    if not subject:
        return ()
    hits = entity_memory.find_by_name(subject, limit=limit)
    return tuple({"identity_key": hit["identity_key"], "npc_id": hit["npc_id"], "name": hit["name"],
                  "unit_type": hit["unit_type"], "seen_count": hit["seen_count"],
                  "confidence": (.3 if hit.get("source") == "TDB_REFERENCE" else
                                 round(min(.85, (hit["seen_count"]+1)/(hit["seen_count"]+3)), 4)),
                  "subject_text": subject, "source": hit.get("source", "ENTITY_MEMORY_NAME_LOOKUP"),
                  "confirmed": False,
                  **{key: hit[key] for key in ("source_file", "source_sha256") if key in hit}}
                 for hit in hits)


def resolve_location_candidates(entity_candidates: tuple[dict, ...], entity_memory, *,
                                as_of: float | None = None, max_age: float | None = None,
                                limit: int = 5) -> tuple[dict, ...]:
    if entity_memory is None:
        return ()
    result: list[dict[str, Any]] = []
    for candidate in entity_candidates:
        for location in entity_memory.locations(candidate["identity_key"], limit=limit,
                                                 as_of=as_of, max_age=max_age):
            location_weight = min(.85, (location["seen_count"]+1)/(location["seen_count"]+3))
            result.append({**location, "identity_key": candidate["identity_key"],
                           "entity_confidence": candidate["confidence"],
                           "confidence": round(candidate["confidence"]*location_weight, 4),
                           "source": "ENTITY_MEMORY_LOCATION"})
    result.sort(key=lambda item: -item["confidence"])
    return tuple(result[:limit])


def target_matches_objective(target: dict, objective: dict) -> bool:
    from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
    explicit = identity_fields(objective.get("target_entity"))
    if explicit:
        return not objective.get("is_complete") and bool(check_entity_identity(explicit, target))
    name = words(str(target.get("name") or ""))
    if not name or objective.get("is_complete"):
        return False
    description = words(str(objective.get("description") or ""))
    if name in description:
        return True
    for subject in combat_subjects(objective):
        # "defeated Murlocs" can support "Murloc Watershaper", but a word
        # fragment such as "rat" must never identify "pirate".
        singular = subject[:-1] if subject.endswith("s") and not subject.endswith("ss") else subject
        if re.search(r"\b" + re.escape(singular) + r"\b", name):
            return True
    return False


def entity_constraints_allow(target: dict, entity: dict | None) -> bool:
    """Names may search only when no known numeric/GUID constraint rejects."""
    from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
    explicit = identity_fields(entity)
    return not explicit or bool(check_entity_identity(explicit, target))


def target_matches_structured_entity(target: dict, entity: dict | None) -> bool:
    if not target or not entity:
        return False
    from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
    expected = identity_fields(entity)
    if expected:
        return bool(check_entity_identity(expected, target))
    expected, actual = words(str(entity.get("name") or "")), words(str(target.get("name") or ""))
    return bool(expected and actual and expected == actual)
