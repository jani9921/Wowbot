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
    patterns = [r"\btalk to\s+([a-z][a-z '-]+)", r"\bspeak (?:to|with)\s+([a-z][a-z '-]+)",
                r"\breport to\s+([a-z][a-z '-]+)", r"\bmeet\s+(?:with\s+)?([a-z][a-z '-]+)",
                r"\bbeszelj\s+([a-z][a-z '-]+)", r"\bjelentkezz\s+([a-z][a-z '-]+)"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        subject = match[1].strip().rstrip(".")
        subject = re.split(r"\b(?:about|regarding|to (?:learn|discuss)|hogy|arrol)\b", subject)[0].strip()
        if 2 < len(subject) < 80:
            return subject
    return None


def use_on_subjects(objective: dict) -> list[str]:
    """Extract target names from an evidence-backed item-use objective."""
    if objective.get("is_complete"):
        return []
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
    if kind in {"TALK_TO", "RETURN"}:
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
                  "confidence": round(min(.85, (hit["seen_count"]+1)/(hit["seen_count"]+3)), 4),
                  "subject_text": subject, "source": "ENTITY_MEMORY_NAME_LOOKUP"}
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


def target_matches_structured_entity(target: dict, entity: dict | None) -> bool:
    if not target or not entity:
        return False
    if entity.get("npc_id") is not None and target.get("npc_id") is not None:
        return str(entity["npc_id"]) == str(target["npc_id"])
    expected, actual = words(str(entity.get("name") or "")), words(str(target.get("name") or ""))
    return bool(expected and actual and expected == actual)
