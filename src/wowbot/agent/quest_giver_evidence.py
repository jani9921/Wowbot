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
    # A visual_group shares the overhead glyph's labels with its *subject*.
    # Those group labels describe a relation, not the subject's own class:
    # treating Cole's body as a symbol made his actual overhead ! unusable.
    appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
    own_labels = {str(value).lower() for value in item.get("candidate_labels") or ()}
    own_labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or ())
    hypothesis = str(appearance.get("learned_label_hypothesis") or "").lower()
    return ("symbol" in _kind(item) or hypothesis in SYMBOL_LABELS
            or bool(own_labels & SYMBOL_LABELS))


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


CURSOR_BOX_MARGIN = .012     # ~10 px of an 843 px wide client


def _box_holds_cursor(item: dict, cx: float, cy: float) -> bool:
    x, y = number(item.get("x")), number(item.get("y"))
    width, height = number(item.get("bbox_width_fraction")), number(item.get("bbox_height_fraction"))
    if None in (x, y, width, height):
        return False
    return (abs(cx-x) <= width/2 + CURSOR_BOX_MARGIN
            and abs(cy-y) <= height/2 + CURSOR_BOX_MARGIN)


def hovered_subjects(state: dict, guid: str) -> list[dict]:
    """Every box that may be the hovered unit: its bound track and, while
    the cursor is on it, the boxes under the cursor.

    Live 2026-10-05 12:24: Private Cole was hovered three times with a "!"
    exactly over his box, yet never selected -- the hover was bound to the
    probed track (a box beside him), whose head had no symbol.
    """
    candidates = _world3d(state)
    result = []
    first = hovered_subject(state, guid)
    if first is not None:
        result.append(first)
    mouse = state.get("mouseover") or {}
    cursor = state.get("cursor_position") or {}
    cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
    if str(mouse.get("guid") or "") == str(guid) and cx is not None and cy is not None:
        result += [item for item in candidates
                   if item not in result and not is_symbol(item) and not is_self_avatar_box(item)
                   and _box_holds_cursor(item, cx, cy)]
    return result


def npc_shows_quest_symbol(state: dict, guid: str) -> bool:
    candidates = _world3d(state)
    return any(subject_has_quest_symbol(subject, candidates)
               for subject in hovered_subjects(state, guid))


def selected_npc_shows_quest_symbol(state: dict, guid: str) -> bool:
    """A "!" over the selected unit's own box: hovered now, or its bound track.

    Unlike ``npc_shows_quest_symbol`` this never falls back to the box under
    the cursor -- that box belongs to whoever is hovered, not to the target.
    """
    if str((state.get("mouseover") or {}).get("guid") or "") == str(guid):
        return npc_shows_quest_symbol(state, guid)
    anchor = (state.get("confirmed_mouseover_anchors") or {}).get(str(guid)) or {}
    if anchor.get("track_id") is None:
        return False
    candidates = _world3d(state)
    subject = next((item for item in candidates
                    if str(item.get("track_id")) == str(anchor["track_id"])), None)
    return subject is not None and subject_has_quest_symbol(subject, candidates)


def quest_symbol_visible(state: dict) -> bool:
    # ``recent_quest_symbol_visible``: a "!" seen moments ago (see
    # TargetPlanningPolicy.SYMBOL_HOLD_SECONDS) still counts.
    return (state.get("recent_quest_symbol_visible") is True
            or any(is_symbol(item) for item in _world3d(state)))


def near_api_quest_giver(state: dict, radius: float = API_GIVER_RADIUS_YARDS) -> bool:
    """Close to an available-quest pin from the map API (``map_pois``).

    The TDB reference database is deliberately not used here: it is a last
    resort from the early OpenCV era, not quest-giver evidence (user 2026-10-02).
    """
    records = reachable_records(state, "available_quests")
    return bool(records) and records[0][0] <= radius


def server_marker_allows(state: dict, guid: str) -> bool | None:
    """The server's own "!" / yellow "?" for this unit (Ymir), or None if unknown.

    Per-player QuestGiverStatus beats every visual or map heuristic: live
    2026-10-19 the server showed Captain Garrick's "!" that the TDB lacked,
    and Henry Garrick with only a grey "?" left after two accepts.
    """
    from .packet_entity_facts import entity, quest_marker
    marker = quest_marker(state, guid)
    if marker is not None:
        return bool(marker.get("quest_available") or marker.get("reward_ready"))
    # The create block's NpcFlags (viewer-dependent): without QuestGiver
    # (0x2) the unit cannot open a quest dialog for this character at all.
    flags = ((entity(state, guid) or {}).get("info") or {}).get("npc_flags")
    if type(flags) is int and not flags & 0x2:
        return False
    return None


def quest_search_allows_npc(state: dict, guid: str) -> bool:
    """With no active quest: may this hovered friendly NPC be selected?"""
    server = server_marker_allows(state, guid)
    if server is not None:
        return server
    if npc_shows_quest_symbol(state, guid):
        return True
    from .quest_creature_memory import remembered_creature
    if remembered_creature(state, guid, pin_givers=True):
        # The quest dialog showed this unit offering a "!" quest next to us
        # (quest_creature_memory) -- also when its "!" is not detected
        # (live 2026-10-05: Henry Garrick's campaign "!" never was).
        return True
    return (not quest_symbol_visible(state) and near_api_quest_giver(state)
            and not known_other_than_pin_starters(state, guid))


def known_other_than_pin_starters(state: dict, guid: str,
                                  radius: float = API_GIVER_RADIUS_YARDS) -> bool:
    """The nearby "!" pins' starters are all known (TDB/learned) and this NPC
    is none of them.

    Live 2026-10-13 05:54: next to Alaria's pin (starter 156803) the agent
    hovered, selected, approached and talked to Bjorn (156891), who had
    nothing to give; Alaria was selected only when the cursor happened to
    drift onto her.
    """
    from .quest_creature_memory import npc_id_from_guid
    npc_id = npc_id_from_guid(guid)
    records = [record for distance, record, _destination in reachable_records(state, "available_quests")
               if distance <= radius]
    if npc_id is None or not records:
        return False
    quests = (state.get("reference_knowledge") or {}).get("quests") or {}
    starters: set[str] = set()
    for record in records:
        known = {str(row.get("npc_id")) for row in
                 (quests.get(str(record.get("quest_id"))) or {}).get("quest_roles") or ()
                 if isinstance(row, dict) and row.get("role") == "QUEST_STARTER"}
        if not known:
            return False            # an unknown starter: any NPC may be it
        starters |= known
    return str(npc_id) not in starters


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


def is_game_object_objective(objective) -> bool:
    """The live type, or a unique TDB type when live is missing, says GO.

    Live 2026-10-05 12:25 ("0/5 Trapped Expedition Member rescued from
    cocoons", raw type ``object``, normalized INTERACT): every friendly NPC
    became relevant and the agent selected and talked to Bjorn twice.
    """
    raw = getattr(objective, "raw", None) or {}
    # Vendor objectives ("Any item purchased from ...") are raw "object" too,
    # but their BUY/SELL type names the vendor NPC.
    return ((str(raw.get("raw_type") or "").lower() == "object"
             or (str(raw.get('tdb_objective_kind') or '') == 'GAMEOBJECT'
                 and not raw.get('raw_type')))
            and str(getattr(objective, "type", "") or "").upper() in {"INTERACT", "USE_OBJECT"})


def npc_objective_subjects(objectives) -> tuple[tuple[str, ...], bool]:
    """Names the ready NPC objectives address, and whether any names none."""
    from .quest_semantics import talk_to_subject
    names, unnamed = [], False
    for objective in objectives or ():
        if str(getattr(objective, "type", "") or "").upper() not in NPC_OBJECTIVE_TYPES:
            continue
        if is_game_object_objective(objective):
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


def ender_of_unfinished_quest_only(state: dict, guid: str) -> bool:
    """This NPC ends an active, unfinished quest and no finished one.

    Live 2026-10-10 17:25: at 2/6 First Aid Kits the agent selected Lady
    Jaina (the ender of Murloc Mania) and walked away from the murlocs.  The
    detector's symbol class cannot tell the grey "?" of an unfinished quest
    from a yellow "!"/"?", and the ender of an unfinished quest always shows
    the grey one.  The TDB/learned quest roles (reference_knowledge) say
    whose it is.
    """
    from .quest_creature_memory import npc_id_from_guid
    npc = npc_id_from_guid(guid)
    if npc is None:
        return False
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    unfinished = finished = False
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict):
            continue
        roles = (reference.get(str(quest.get("quest_id"))) or {}).get("quest_roles") or ()
        if any(str(row.get("npc_id")) == str(npc) and row.get("role") == "QUEST_ENDER"
               for row in roles if isinstance(row, dict)):
            if quest.get("is_complete") is True:
                finished = True
            else:
                unfinished = True
    return unfinished and not finished


def objective_named_unit(state: dict, guid: str, unit_name: str | None = None) -> bool:
    """A friendly unit the client ties to an open quest whose objective names it.

    Live 2026-10-20 08:48: "0/1 Meredy Huntswell rescued" is a KILL objective
    (the credit comes when Bloodbeak dies at the end of the event), but the
    event starts by talking to Meredy.  The cursor rested on her 76 times
    (quest_related, quest 55763) and no friendly-NPC rule admitted her.
    """
    unit = next((value for value in (state.get("mouseover"), state.get("target"))
                 if isinstance(value, dict) and str(value.get("guid") or "") == str(guid)), None)
    if not unit or unit.get("quest_related") is not True:
        return False
    quest = next((value for value in state.get("active_quests") or ()
                  if isinstance(value, dict) and str(value.get("quest_id")) == str(unit.get("quest_id"))
                  and value.get("is_complete") is not True), None)
    if quest is None:
        return False
    from .quest_semantics import npc_referenced_by_objective
    probe = {**unit, "name": unit_name or unit.get("name"),
             "attackable": unit.get("attackable", unit.get("is_attackable"))}
    return any(isinstance(objective, dict) and objective.get("is_complete") is not True
               and npc_referenced_by_objective(objective, probe)
               for objective in quest.get("objectives") or ())


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
    if objective_named_unit(state, guid, unit_name):
        return True          # named by an open objective and quest-linked by the client
    if {str(kind).upper() for kind in objective_types} & NPC_OBJECTIVE_TYPES:
        if npc_subjects is None:
            return True
        names, unnamed = npc_subjects
        from .quest_semantics import subject_matches_name
        # Live 2026-10-04 10:27: "Use Scout-o-Matic 5000" made every friendly
        # NPC relevant; Lindie Springstock was selected and approached again
        # and again.  A named NPC objective wants that NPC only.
        # No name and no unnamed NPC objective left: only game-object
        # objectives (cocoons), which no friendly NPC serves.
        if unnamed or (names and subject_matches_name(list(names), unit_name)):
            return True
    from .quest_creature_memory import remembered_creature
    server = server_marker_allows(state, guid)
    if server is not None:
        # The server says whether this unit has a quest to give or to take
        # back; a "!"-like glyph, a remembered ender role or a nearby
        # turn-in pin cannot override it.  A quest vehicle still can.
        return server or bool(remembered_creature(state, guid, name=unit_name, roles=("VEHICLE",)))
    if npc_shows_quest_symbol(state, guid) and not ender_of_unfinished_quest_only(state, guid):
        return True
    if remembered_creature(state, guid, name=unit_name, roles=("ENDER", "VEHICLE")):
        return True          # the remembered ender of a finished quest / the quest's vehicle
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
    # Issue #92: a nearby turn-in POI is search-area evidence, not identity.
    # It may admit an NPC only for a quest whose ender is still unnamed; a
    # named ender was already matched (or rejected) above.
    known_enders = state.get("quest_turn_in_names") or {}
    reference_quests = (state.get("reference_knowledge") or {}).get("quests") or {}
    unnamed = {quest_id for quest_id in complete
               if not (known_enders.get(quest_id) or {}).get("name")
               and not (reference_quests.get(quest_id) or {}).get("turnin_candidates")}
    for location in state.get("quest_locations") or ():
        point = world_point(location) if isinstance(location, dict) else None
        if (point is not None and str(location.get("quest_id")) in unnamed
                and math.hypot(point["x"]-px, point["y"]-py) <= TURN_IN_NPC_RADIUS_YARDS):
            return True
    return False
