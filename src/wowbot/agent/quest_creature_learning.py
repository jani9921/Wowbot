"""Feed ``QuestCreatureMemory`` from the world model and project it back.

Learning (full addon snapshots and hovers; user 2026-10-05):

* the quest dialog's giver/ender GUID -> GIVER/ENDER, the giver at the API
  "!" pin the quest was offered at;
* every objective counter rise -> PROGRESS (skill, binding, own spell, on
  foot / in a vehicle, the selected or hovered creature, where) plus the
  creature as OBJECTIVE and the boarded unit as VEHICLE;
* a hover -> the creature type's LOOK; a tooltip naming an open quest ->
  OBJECTIVE.

Projection (``state["quest_creatures"]``) tells planning which remembered
creatures the current situation wants: the givers of the nearby "!" pins,
the enders of finished quests, the creatures and the vehicle of open
objectives.  Decisions still rest on the live unit (hover/target GUID).
"""
from __future__ import annotations

from .map_poi_planning import reachable_records
from .models import number
from .planning_types import world_point
from .quest_creature_memory import _cosine, memory_for, npc_id_from_guid

PIN_GIVER_YARDS = 25.          # same radius as quest_giver_evidence.API_GIVER_RADIUS_YARDS
NEARBY_PIN_YARDS = 60.
CAST_RECENT_SECONDS = 5.
LIFT_MARGIN = .08


def _player_position(state: dict) -> dict | None:
    position = state.get("player_world_position") or {}
    x, y = number(position.get("x")), number(position.get("y"))
    if x is None or y is None:
        return None
    return {"x": x, "y": y, "instance_id": position.get("instance_id")}


def unit_npc_id(unit: dict | None) -> int | None:
    if not isinstance(unit, dict):
        return None
    value = unit.get("npc_id")
    if isinstance(value, (int, float)):
        return int(value)
    return npc_id_from_guid(unit.get("guid"))


def _creature_unit(unit) -> bool:
    return (isinstance(unit, dict) and bool(unit.get("name"))
            and unit.get("is_player") is not True
            and not str(unit.get("guid") or "").startswith(("Player-", "Pet-")))


# --------------------------------------------------------------------- learn
def learn_full_snapshot(model, state: dict, at: float) -> None:
    memory = memory_for(model)
    pins = model.__dict__.setdefault("_quest_pin_points", {})
    for record in (state.get("map_pois") or {}).get("available_quests") or ():
        point = world_point(record) if isinstance(record, dict) else None
        if point is not None and record.get("quest_id") is not None:
            pins[str(record["quest_id"])] = point
    if len(pins) > 400:
        for key in list(pins)[:-200]:
            pins.pop(key, None)
    player = _player_position(state)
    text = state.get("quest_text")
    if isinstance(text, dict) and text.get("quest_id") is not None:
        qid = str(text["quest_id"])
        if text.get("giver_name"):
            memory.record_role(qid, "GIVER", name=text["giver_name"],
                               npc_id=npc_id_from_guid(text.get("giver_guid")),
                               # Only the pin the quest was offered at: the
                               # addon keeps dialog texts across sessions, so
                               # the export may arrive far from the giver
                               # (live 2026-10-05 12:24, 55965/Bjorn).
                               position=pins.get(qid), source="QUEST_DETAIL_DIALOG", at=at)
        if text.get("ender_name"):
            memory.record_role(qid, "ENDER", name=text["ender_name"],
                               npc_id=npc_id_from_guid(text.get("ender_guid")),
                               position=player, source="QUEST_COMPLETE_DIALOG", at=at)
    _learn_vehicle_boarding(model, state)
    _learn_progress(model, memory, state, player, at)
    _apply_remembered(model, memory, state, at)


def _learn_vehicle_boarding(model, state: dict) -> None:
    riding = state.get("in_vehicle") is True
    if riding and model.__dict__.get("_creature_was_riding") is False:
        target = state.get("target") or {}
        if _creature_unit(target):
            model.__dict__["_boarded_unit"] = {"name": target.get("name"), "npc_id": unit_npc_id(target)}
    if not riding:
        model.__dict__.pop("_boarded_unit", None)
    model.__dict__["_creature_was_riding"] = riding


def _learn_progress(model, memory, state: dict, player, at: float) -> None:
    counts = model.__dict__.setdefault("_creature_objective_counts", {})
    seen = set()
    context = getattr(model, "runtime_context", {}) or {}
    active = context.get("active_skill") or {}
    last = context.get("last_result") or {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("quest_id") is None:
            continue
        qid = str(quest["quest_id"])
        for index, objective in enumerate(quest.get("objectives") or ()):
            if not isinstance(objective, dict):
                continue
            current = number(objective.get("current"))
            key = (qid, index)
            seen.add(key)
            previous = counts.get(key)
            counts[key] = current
            if current is None or previous is None or current <= previous:
                continue
            unit = state.get("target") if _creature_unit(state.get("target")) else state.get("mouseover")
            unit = unit if _creature_unit(unit) else {}
            spell = None
            cast_at, clock = number(state.get("combat_last_cast_at")), number(state.get("monotonic_time"))
            if cast_at is not None and clock is not None and 0 <= clock-cast_at <= CAST_RECENT_SECONDS:
                spell = number(state.get("combat_last_spell_id"))
            riding = state.get("in_vehicle") is True
            memory.record_progress(
                qid, index, description=str(objective.get("description") or ""),
                skill=(active.get("skill") if isinstance(active, dict) else None) or last.get("skill"),
                binding=last.get("last_binding"), spell_id=spell, in_vehicle=riding,
                target_npc_id=unit_npc_id(unit), target_name=unit.get("name"),
                map_id=state.get("map_id"), position=player, steps=int(current-previous), at=at)
            if unit.get("name"):
                memory.record_role(qid, "OBJECTIVE", name=unit["name"], npc_id=unit_npc_id(unit),
                                   position=player, source="OBJECTIVE_PROGRESS", at=at)
            boarded = model.__dict__.get("_boarded_unit")
            if riding and boarded and boarded.get("name"):
                memory.record_role(qid, "VEHICLE", name=boarded["name"], npc_id=boarded.get("npc_id"),
                                   source="BOARDED_BEFORE_PROGRESS", at=at)
    for key in list(counts):
        if key not in seen:
            counts.pop(key, None)


def _apply_remembered(model, memory, state: dict, at: float) -> None:
    """Remembered enders name the turn-in NPC; remembered objective creatures
    are quest-relevant creature types again (across sessions)."""
    from .tooltip_quest import objective_key, objective_still_open
    turn_in = model.__dict__.setdefault("quest_turn_in", {})
    relevant = model.__dict__.setdefault("quest_relevant_npcs", {})
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("quest_id") is None:
            continue
        qid = str(quest["quest_id"])
        if quest.get("is_complete") is True:
            ender = next(iter(memory.roles(qid).get("ENDER") or ()), None)
            if ender is not None:
                turn_in[qid] = {"name": ender["name"], "npc_id": ender.get("npc_id"),
                                "source": "QUEST_CREATURE_MEMORY"}
            continue
        for row in memory.progress(qid):
            npc = row.get("target_npc_id")
            key = objective_key(row.get("description"))
            if npc is None or not key or str(npc) in relevant:
                continue
            if objective_still_open(state, qid, [key]):
                relevant[str(npc)] = {"quest_id": quest["quest_id"], "objectives": [key],
                                      "observed_at": at, "source": "QUEST_CREATURE_MEMORY"}


def learn_hover(model, unit: dict, *, embedding, quest_id, map_id, at: float) -> None:
    if not _creature_unit(unit) or unit.get("is_dead", unit.get("dead")) is True:
        return
    memory = memory_for(model)
    npc = unit_npc_id(unit)
    if npc is not None and embedding:
        memory.record_look(npc, embedding, name=unit.get("name"), map_id=map_id, at=at)
    if quest_id is not None:
        memory.record_role(quest_id, "OBJECTIVE", name=unit.get("name"), npc_id=npc,
                           position=_player_position(model.state), source="HOVER_TOOLTIP", at=at)


# ------------------------------------------------------------------- project
def project(model) -> None:
    """``state["quest_creatures"]`` and a look lift on World3D subject boxes."""
    state = model.state
    memory = memory_for(model)
    wanted, pin_givers, uncovered_pins = [], [], 0
    for distance, record, _ in reachable_records(state, "available_quests"):
        if distance > NEARBY_PIN_YARDS:
            break
        givers = memory.roles(record.get("quest_id")).get("GIVER") or ()
        for row in givers:
            entry = {**row, "role": "GIVER", "quest_id": record.get("quest_id"),
                     "distance": round(distance, 1)}
            wanted.append(entry)
            if distance <= PIN_GIVER_YARDS:
                pin_givers.append(entry)
        if distance <= PIN_GIVER_YARDS and not givers:
            uncovered_pins += 1
    riding = state.get("in_vehicle") is True
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("quest_id") is None:
            continue
        roles = memory.roles(quest["quest_id"])
        if quest.get("is_complete") is True:
            wanted += [{**row, "role": "ENDER", "quest_id": quest["quest_id"]} for row in roles.get("ENDER") or ()]
            continue
        wanted += [{**row, "role": "OBJECTIVE", "quest_id": quest["quest_id"]}
                   for row in roles.get("OBJECTIVE") or ()]
        progressed_riding = any(row.get("in_vehicle") for row in memory.progress(quest["quest_id"]))
        if progressed_riding and not riding:
            wanted += [{**row, "role": "VEHICLE", "quest_id": quest["quest_id"]}
                       for row in roles.get("VEHICLE") or ()]
    state["quest_creatures"] = {
        "wanted": wanted, "pin_givers": pin_givers,
        # Every "!" pin next to the player has a remembered giver: a unit that
        # is none of them is not worth another hover (visual_inspection_planning).
        "pin_givers_known": bool(pin_givers) and uncovered_pins == 0,
    }
    _annotate_looks(state, memory.looks(state.get("map_id")), wanted)


def _annotate_looks(state: dict, looks: dict, wanted: list[dict]) -> None:
    """Closer to a wanted creature's look than to the other known looks here
    -> positive lift (probe first); the reverse -> negative.  Ordering only."""
    from .visual_prototypes import candidate_embedding
    wanted_ids = {int(row["npc_id"]) for row in wanted if row.get("npc_id") is not None}
    positives = [sample for npc, samples in looks.items() if npc in wanted_ids for sample in samples]
    negatives = [sample for npc, samples in looks.items() if npc not in wanted_ids for sample in samples]
    if not positives:
        return
    for item in state.get("visual_candidates") or ():
        if (not isinstance(item, dict) or item.get("source") != "WORLD3D"
                or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")):
            continue
        embedding = candidate_embedding(item)
        if embedding is None:
            continue
        positive = max(_cosine(embedding, other) for other in positives)
        negative = max((_cosine(embedding, other) for other in negatives), default=None)
        lift = 0. if negative is None else max(-1., min(1., (positive-negative)/LIFT_MARGIN))
        appearance = dict(item.get("appearance") or {})
        appearance.update({"creature_memory_positive": round(positive, 4),
                           "creature_memory_negative": None if negative is None else round(negative, 4),
                           "creature_memory_lift": round(lift, 4)})
        item["appearance"] = appearance

