"""Who a quest is turned in to.

Retail exposes no "quest ender" for a unit (live-verified), and the agent
inspected several NPCs around a hub before finding the right one.  The
quest's own words usually say it: "Return to Captain Garrick", "Speak with
Lindie Springstock", or "report back to me" (the giver, whom addon 0.9.52
records from the quest dialog).  Order of evidence:

1. text pattern naming the NPC (waypoint text, objective lines, objectives
   text, completion/progress text, description);
2. "back to me" wording -> the recorded quest giver;
3. the local LLM (semantic_advisor ``turnin`` task) when 1-2 found nothing.

The result is a name to *recognise* on hover/target, never an identity by
itself: the addon GUID/name of the selected unit stays authoritative.
"""
from __future__ import annotations

import re

_NAME = r"([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,3})"
_TO_NAME = re.compile(
    r"\b(?i:return|report|speak|talk|go back|head back|turn (?:it|them) in|"
    r"(?:bring|deliver|take)\b[^.!?]{0,60}?)\s+(?i:to|with)\s+(?:(?i:the)\s+)?" + _NAME)
_BACK_TO_GIVER = re.compile(
    r"\b(?:report|return|come|head|hurry) back\b(?! to [A-Z])|\b(?:return|report|come back) to me\b|"
    r"\bback to me\b|\bbring (?:it|them|those|these|that|this)(?: back)? to me\b", re.IGNORECASE)
_NOT_A_PERSON = {"me", "you", "us", "them", "it", "camp", "the camp", "town"}


def _texts(quest: dict, texts: dict | None) -> list[tuple[str, str]]:
    texts = texts or {}
    sources = []
    waypoint = quest.get("waypoint") if isinstance(quest.get("waypoint"), dict) else {}
    if waypoint.get("text"):
        sources.append(("WAYPOINT_TEXT", str(waypoint["text"])))
    for objective in quest.get("objectives") or ():
        if isinstance(objective, dict) and objective.get("description"):
            sources.append(("OBJECTIVE_TEXT", str(objective["description"])))
    for key, label in (("objectives_text", "QUEST_OBJECTIVES_TEXT"), ("completion_text", "COMPLETION_TEXT"),
                       ("progress_text", "PROGRESS_TEXT"), ("description", "QUEST_DESCRIPTION")):
        value = texts.get(key) or (quest.get(key) if key == "description" else None)
        if value:
            sources.append((label, str(value)))
    return sources


def turn_in_from_text(quest: dict, texts: dict | None = None) -> dict | None:
    """Deterministic turn-in NPC from the quest's own words, or None."""
    texts = texts or {}
    for source, text in _texts(quest, texts):
        if source == "QUEST_DESCRIPTION":
            continue           # a story names many people; only explicit asks below
        match = _TO_NAME.search(text)
        if match and match[1].strip().casefold() not in _NOT_A_PERSON and len(match[1].strip()) >= 3:
            return {"name": match[1].strip(), "source": f"QUEST_TEXT_PATTERN:{source}",
                    "evidence": match[0][:120]}
    giver = str(texts.get("giver_name") or "").strip()
    if giver:
        for source, text in _texts(quest, texts):
            if _BACK_TO_GIVER.search(text):
                return {"name": giver, "source": f"QUEST_GIVER:{source}",
                        "giver_guid": texts.get("giver_guid")}
    return None


def turn_in_names(state: dict, *, complete_only: bool = True) -> list[str]:
    """Names of the NPCs the (complete) active quests are turned in to."""
    known = state.get("quest_turn_in_names") or {}
    names = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or (complete_only and quest.get("is_complete") is not True):
            continue
        entry = known.get(str(quest.get("quest_id"))) or {}
        if entry.get("name"):
            names.append(str(entry["name"]))
    return names
