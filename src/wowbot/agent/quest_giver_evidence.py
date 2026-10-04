"""Which friendly NPC may offer a quest -- from vision and map APIs only.

Verified live 2026-10-02 (``/aipc questprobe`` on Lady Jaina): Retail 12.1
exposes no quest-giver status on hover or target.  Available quests show only
as the overhead "!" (vision), in the gossip/quest window after INTERACT, and
as map pins / ``map_pois``.  With no active quest the agent therefore selects
a friendly NPC only when a symbol stands over its box, or -- when no symbol
is visible at all -- at an API quest-giver position (user 2026-10-02).
"""
from __future__ import annotations

import math

from .map_poi_planning import reachable_records
from .self_avatar import is_self_avatar_box
from .models import number

SYMBOL_LABELS = frozenset({"learned_symbol_like", "overhead_symbol_like",
                           "overhead_symbol_like_cue", "quest_marker_like"})
BADGE_LIKENESS = .52
API_GIVER_RADIUS_YARDS = 25.
NOT_QUEST_GIVER_SECONDS = 300.


def _labels(item: dict) -> set[str]:
    appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
    group = item.get("visual_group") if isinstance(item.get("visual_group"), dict) else {}
    labels = {str(value).lower() for value in item.get("candidate_labels") or ()}
    labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or ())
    labels.update(str(value).lower() for value in group.get("appearance_labels") or ())
    return labels


def _kind(item: dict) -> str:
    return str(item.get("detector_kind") or item.get("kind") or "").lower()


def is_symbol(item: dict) -> bool:
    return "symbol" in _kind(item) or bool(_labels(item) & SYMBOL_LABELS)


def _pixel_box(item: dict) -> tuple[float, float, float, float] | None:
    box = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    if box.get("coordinate_space") not in {None, "CLIENT_PIXELS"}:
        return None
    values = tuple(number(box.get(key)) for key in ("left", "top", "right", "bottom"))
    if None in values or values[2] <= values[0] or values[3] <= values[1]:
        return None
    return values  # type: ignore[return-value]


def symbol_above(subject: dict, symbol: dict) -> bool:
    """A symbol box sitting on or just over the subject's head (top-left pixels)."""
    body, mark = _pixel_box(subject), _pixel_box(symbol)
    if body is None or mark is None:
        return False
    left, top, right, bottom = body
    width, height = right-left, bottom-top
    centre = (mark[0]+mark[2]) / 2
    return (left - .35*width <= centre <= right + .35*width
            and top - .6*height <= mark[3] <= top + .25*height
            and (mark[3]-mark[1]) < height)


def subject_has_quest_symbol(subject: dict, candidates) -> bool:
    if not isinstance(subject, dict) or is_symbol(subject):
        return False
    appearance = subject.get("appearance") if isinstance(subject.get("appearance"), dict) else {}
    labels = _labels(subject)
    if "quest_badge_like" in labels or (number(appearance.get("quest_badge_likeness")) or 0) >= BADGE_LIKENESS:
        return True
    overhead = any(str(edge.get("type") or "").upper() == "ABOVE"
                   for edge in subject.get("visual_relations") or () if isinstance(edge, dict))
    if overhead and labels & SYMBOL_LABELS:
        return True
    return any(isinstance(item, dict) and item is not subject and is_symbol(item)
               and symbol_above(subject, item) for item in candidates)


def _world3d(state: dict) -> list[dict]:
    return [item for item in state.get("visual_candidates") or ()
            if isinstance(item, dict) and item.get("source") == "WORLD3D"]


def hovered_subject(state: dict, guid: str) -> dict | None:
    """The World3D box the addon mouseover GUID was associated with."""
    candidates = _world3d(state)
    anchor = (state.get("confirmed_mouseover_anchors") or {}).get(str(guid)) or {}
    track_id = anchor.get("track_id")
    if track_id is not None:
        bound = next((item for item in candidates if str(item.get("track_id")) == str(track_id)), None)
        if bound is not None:
            return bound
    cursor = state.get("cursor_position") or {}
    cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
    if cx is None or cy is None:
        return None
    subjects = [item for item in candidates if not is_symbol(item) and not is_self_avatar_box(item)
                and number(item.get("x")) is not None and number(item.get("y")) is not None]
    if not subjects:
        return None
    nearest = min(subjects, key=lambda item: math.hypot(float(item["x"])-cx, float(item["y"])-cy))
    return nearest if math.hypot(float(nearest["x"])-cx, float(nearest["y"])-cy) <= .09 else None


def npc_shows_quest_symbol(state: dict, guid: str) -> bool:
    subject = hovered_subject(state, guid)
    return subject is not None and subject_has_quest_symbol(subject, _world3d(state))


def quest_symbol_visible(state: dict) -> bool:
    return any(is_symbol(item) for item in _world3d(state))


def near_api_quest_giver(state: dict, radius: float = API_GIVER_RADIUS_YARDS) -> bool:
    """Close to an available-quest pin from the map API (``map_pois``).

    The TDB reference database is deliberately not used here: it is a last
    resort from the early OpenCV era, not quest-giver evidence (user 2026-10-02).
    """
    records = reachable_records(state, "available_quests")
    return bool(records) and records[0][0] <= radius


def quest_search_allows_npc(state: dict, guid: str) -> bool:
    """With no active quest: may this hovered friendly NPC be selected?"""
    if npc_shows_quest_symbol(state, guid):
        return True
    return not quest_symbol_visible(state) and near_api_quest_giver(state)


# Objective kinds that are done at (or with) a friendly NPC.  UNKNOWN keeps
# the former permissive behaviour when the quest API gave no usable type.
NPC_OBJECTIVE_TYPES = frozenset({
    "TALK", "TALK_TO", "SPEAK", "INTERACT_NPC", "INTERACT", "ESCORT", "FOLLOW",
    "USE_ON_TARGET", "BUY", "SELL", "UNKNOWN"})
TURN_IN_NPC_RADIUS_YARDS = 35.


def is_companion_pet(unit_or_guid) -> bool:
    """Battle pets / companions (``Pet-`` GUIDs) are never quest NPCs."""
    guid = unit_or_guid.get("guid") if isinstance(unit_or_guid, dict) else unit_or_guid
    return str(guid or "").startswith("Pet-")


def npc_objective_subjects(objectives) -> tuple[tuple[str, ...], bool]:
    """Names the ready NPC objectives address, and whether any names none."""
    from .quest_semantics import talk_to_subject
    names, unnamed = [], False
    for objective in objectives or ():
        if str(getattr(objective, "type", "") or "").upper() not in NPC_OBJECTIVE_TYPES:
            continue
        entity = getattr(objective, "target_entity", None) or {}
        name = entity.get("name") or talk_to_subject({
            **(getattr(objective, "raw", {}) or {}),
            "description": getattr(objective, "description", "")})
        if name:
            names.append(str(name))
        else:
            unnamed = True
    return tuple(dict.fromkeys(names)), unnamed


def friendly_npc_relevant(state: dict, guid: str, objective_types, *,
                          unit_name: str | None = None, npc_subjects=None) -> bool:
    """May questing select / talk to this friendly NPC right now?

    Live 2026-10-03 (Cooking Meat, collect Raw Meat from wildlife): with only
    a COLLECT objective active the agent selected and spoke to an "Alliance
    Sparring Partner" six times and to another player's pet, getting no
    answer.  With an active quest a friendly NPC is relevant only when an
    objective needs an NPC, it shows a quest symbol (more quests to take), or
    a finished quest's turn-in point is close by.
    """
    if is_companion_pet(guid):
        return False
    quests = [quest for quest in state.get("active_quests") or () if isinstance(quest, dict)]
    if not quests:
        return quest_search_allows_npc(state, guid)
    if {str(kind).upper() for kind in objective_types} & NPC_OBJECTIVE_TYPES:
        if npc_subjects is None:
            return True
        names, unnamed = npc_subjects
        from .quest_semantics import subject_matches_name
        # Live 2026-10-04 10:27: "Use Scout-o-Matic 5000" made every friendly
        # NPC relevant; Lindie Springstock was selected and approached again
        # and again.  A named NPC objective wants that NPC only.
        if unnamed or not names or subject_matches_name(list(names), unit_name):
            return True
    if npc_shows_quest_symbol(state, guid):
        return True
    complete = {str(quest.get("quest_id")) for quest in quests if quest.get("is_complete") is True}
    if not complete:
        return False
    from .quest_turn_in import turn_in_names
    from .quest_semantics import subject_matches_name
    names = turn_in_names(state)
    if names and unit_name and subject_matches_name(names, unit_name):
        return True          # the finished quest's text names this NPC as its ender
    position = state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    if px is None or py is None:
        return False
    from .planning_types import world_point
    for location in state.get("quest_locations") or ():
        point = world_point(location) if isinstance(location, dict) else None
        if (point is not None and str(location.get("quest_id")) in complete
                and math.hypot(point["x"]-px, point["y"]-py) <= TURN_IN_NPC_RADIUS_YARDS):
            return True
    return False
