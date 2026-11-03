"""Read-only geometry and quest checks for directed, self-activated items."""
from __future__ import annotations
import math

from .models import number
from .packet_entity_facts import best_position, entity, unit_dead
from .quest_item_knowledge import current_use, authorized_item
from .quest_reference_matching import reference_objectives
from wowbot.runtime.entity_identity import check_entity_identity, template_id

PURPOSE = "DIRECTED_QUEST_ITEM"


def delivery(use):
    use = use or {}
    value = (use or {}).get("delivery") or {}
    radius, degrees = number(value.get("radius")), number(value.get("cone_degrees"))
    return {**value, "radius": radius, "cone_degrees": degrees} if (use.get("status") == "RESOLVED" and use.get("target_mode") == "SELF"
                     and value.get("mode") == "FORWARD_CONE" and value.get("status") == "RESOLVED"
                     and type(value.get("effect_index")) is int and 0 <= value["effect_index"] < 32
                     and radius is not None and 0 < radius <= 100
                     and degrees is not None and 0 < degrees <= 180) else None


def subject_links(use, row):
    shape = delivery(use)
    if not shape:
        return []
    return [link for link in use.get("credit_links") or ()
            if link.get("source") == "TDB_SPELL_HIT_CREDIT"
            and link.get("kind") == row.get("credit_kind") == "CREATURE_CREDIT"
            and link.get("id") == row.get("credit_object_id")
            and link.get("hit_spell_id") == shape.get("spell_id")
            and len(link.get("target_conditions") or ()) == 1
            and (link["target_conditions"][0].get("SourceGroup") or 0)
                == 1 << shape.get("effect_index", -1)
            and template_id(link.get("subject_entry")) is not None]


def objective_use(state, params):
    if (params.get("purpose") != PURPOSE or params.get("target_required") is not False
            or params.get("item_target_mode") != "SELF" or params.get("guid")
            or params.get("npc_id") or params.get("object_id")):
        return None, None
    qids = {str(q) for q in params.get("quest_ids") or ()}
    oid = str(params.get("objective_id") or "")
    item = params.get("item_id")
    if (not oid or type(item) is not int or item <= 0
            or not authorized_item(state, item, qids)):
        return None, None
    use = current_use(state, item, qids)
    if not delivery(use or {}) or use.get("spell_id") != params.get("item_spell_id"):
        return None, None
    refs = (state.get("reference_knowledge") or {}).get("quests") or {}
    for quest in state.get("active_quests") or ():
        qid = str(quest.get("quest_id"))
        if qid not in qids or quest.get("is_complete") is True:
            continue
        for index, obj in enumerate(quest.get("objectives") or ()):
            if str(obj.get("objective_id") or f"{qid}:{index}") != oid or obj.get("is_complete") is True:
                continue
            current, required = number(obj.get("current")), number(obj.get("required"))
            if current is not None and required is not None and 0 < required <= current:
                continue
            rows = reference_objectives(qid, oid, obj.get("description"),
                                        (refs.get(qid) or {}).get("objectives") or [])
            if len(rows) != 1:
                continue
            items = rows[0].get("item_uses") or []
            if len(items) == 1 and items[0].get("item_id") == item and subject_links(use, rows[0]):
                return use, rows[0]
    return None, None


def aim_state(state, params, now):
    now = number(now)
    if now is None:
        return "POSE_UNKNOWN", None
    use, row = objective_use(state, params)
    if use is None:
        return "ITEM_CONTEXT_CHANGED", None
    shape = delivery(use)
    entry = template_id(params.get("item_aim_entry"))
    guid = params.get("item_aim_guid")
    if entry not in {link["subject_entry"] for link in subject_links(use, row)}:
        return "WRONG_SUBJECT", None
    unit = entity(state, guid)
    if (not unit or unit.get("kind") != "CREATURE" or unit_dead(unit)
            or not check_entity_identity({"guid": guid, "npc_id": entry},
                                         {"guid": unit.get("guid"), "npc_id": unit.get("entry_id")})):
        return "SUBJECT_GONE", None
    point = best_position(unit)
    player = state.get("player_world_position") or {}
    age = number((point or {}).get("age"))
    position = unit.get("position") or {}
    settled = (str(position.get("source") or "").startswith("PACKET_CREATE_")
               or position.get("destination") is not None)
    from .world_packet_reducer import POSITION_MAX_AGE
    if (point is None or str(point.get("instance_id")) != str(player.get("instance_id"))
            or player.get("z_known") is not True or player.get("z_observed") is not True
            or any(number(player.get(k)) is None for k in ("x", "y", "z"))
            or age is None or age < 0 or not settled and age > POSITION_MAX_AGE):
        return "POSE_UNKNOWN", point
    point = {**point, **{key: number(point[key]) for key in ("x", "y", "z")}}
    sampled = number(player.get("sample_time", state.get("monotonic_time")))
    if sampled is None or not 0 <= now-sampled <= 1.5:
        return "POSE_STALE", point
    flat = math.hypot(point["x"]-number(player["x"]), point["y"]-number(player["y"]))
    dz = point["z"]-number(player["z"])
    if abs(dz) > 5:
        return "OTHER_FLOOR", point
    if math.hypot(flat, dz) > shape["radius"]*.8:
        return "OUT_OF_RANGE", point
    facing = number(state.get("orientation"))
    if facing is None:
        return "POSE_UNKNOWN", point
    tolerance = min(.3, math.radians(shape["cone_degrees"])*.375)
    error = abs((math.atan2(point["y"]-number(player["y"]), point["x"]-number(player["x"]))-facing+math.pi)%math.tau-math.pi)
    if flat > .5 and error > tolerance:
        return "NOT_FACING", point
    movement = state.get("movement") or {}
    if movement.get("moving") is True or (number(movement.get("speed")) or 0) > .1:
        return "MOVING", point
    return "READY", point


def ready_for_use(state, params, now):
    if (state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost")
            or state.get("is_mounted") or state.get("is_casting") or state.get("is_channeling")
            or state.get("world_map_open") or state.get("quest_ui_open")
            or (state.get("vendor_ui") or {}).get("open")):
        return False
    status, _ = aim_state(state, params, now)
    if status != "READY":
        return False
    from .quest_tool_resolver import QuestToolResolver
    row = QuestToolResolver.self_state(state, params["item_id"], params.get("quest_ids"), now=now)
    return QuestToolResolver.self_ready(row)


def credit_window(state, params):
    """Bounded effect duration plus telemetry assembly time; no input authority."""
    use, _ = objective_use(state, params)
    if use is None:
        return 0.
    duration = number(delivery(use).get("duration_ms"))
    return min(15., duration/1000.+3.) if duration is not None and duration > 0 else 8.

