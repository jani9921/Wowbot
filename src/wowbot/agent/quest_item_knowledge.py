"""Quest-scoped ItemEffect knowledge, shared by reference projection and QuestModel."""
from __future__ import annotations

from copy import deepcopy
import math
import re


def _id(value):
    return value if type(value) is int and value > 0 else None


def _words(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def annotate_items(reference, supplement, extra_items=(), *, spell_hits=None, spell_targets=None):
    """Explicit item/credit/text links only; SourceSpellID is not an item ID."""
    items = reference.setdefault("items", {})
    ids = {_id(items.get("start_item_id")), *(_id(i) for i in items.get("drop_item_ids") or ()),
           *(_id(i) for i in extra_items)}
    ids.discard(None)
    profiles = {str(i): supplement.item(i) for i in sorted(ids)[:16]}
    if spell_hits is not None:
        for profile in profiles.values():
            for use in profile.get("uses") or ():
                for spell in use.get("triggered_spells") or ():
                    for credit in spell_hits(spell["spell_id"]):
                        use["credit_links"].append({**deepcopy(credit), "spell_chain": spell["spell_chain"]})
    if spell_targets is not None:
        for profile in profiles.values():
            for use in profile.get("uses") or ():
                if use.get("summoned_creatures") and use.get("target_mode") == "UNIT":
                    use["target_entries"] = deepcopy(spell_targets(use["spell_id"]))
    items["use_profiles"] = profiles
    for objective in reference.get("objectives") or ():
        candidates = []
        for key, profile in profiles.items():
            if profile.get("status") != "RESOLVED":
                continue
            uses = profile.get("uses") or []
            # Multiple active effects may be deliberate simultaneous spells.
            # Preserve them, but don't choose an arbitrary slot/spell.
            if len(uses) != 1:
                continue
            use = uses[0]
            credit = objective.get("credit_object_id")
            kind = objective.get("credit_kind")
            matches = [c for c in use.get("credit_links") or () if c["id"] == credit and c["kind"] == kind]
            name, text = _words(profile.get("name")), _words(objective.get("description"))
            named = bool(name and f" {name} " in f" {text} ")
            # The spell may create the boarding/credit actor, instead of
            # issuing kill credit. A decoded summon effect AND its exact
            # implicit-target condition bind the original physical subject.
            subjects = {row["entry"] for row in use.get("target_entries") or ()
                        for summon in use.get("summoned_creatures") or ()
                        if kind == "CREATURE_CREDIT" and summon["entry"] == credit
                        and row["effect_mask"] & summon["effect_mask"] == summon["effect_mask"]}
            summoned = use.get("target_mode") == "UNIT" and len(subjects) == 1
            if not matches and not named and not summoned:
                continue
            candidates.append({"item_id": int(key), "spell_id": use["spell_id"],
                               "match": ("SPELL_EFFECT_CREDIT" if matches else
                                         "SPELL_SUMMON_OBJECTIVE" if summoned else "OBJECTIVE_ITEM_NAME"),
                               **({"subject_entries": sorted(subjects)} if summoned else {}),
                               "credit_links": matches})
        objective["item_uses"] = candidates
        if len(candidates) == 1:
            objective["mechanism"] = "USE_ITEM"
            objective["mechanism_tags"] = sorted(set(objective.get("mechanism_tags") or ()) | {"DB2_ITEM_EFFECT"})


def apply_item_knowledge(objective, source, quest, reference):
    """Enrich one *matched* live objective, never change its completion/count."""
    profiles = (reference.get("items") or {}).get("use_profiles") or {}
    existing = _id((objective.target_object or {}).get("item_id"))
    candidates = {row["item_id"] for row in source.get("item_uses") or ()}
    if (len(candidates) == 1 and existing in candidates) or (existing and existing == (quest.get("special_item") or {}).get("item_id")
                                   and objective.type == "USE_ITEM_ON_TARGET"):
        chosen = existing
    elif len(candidates) == 1 and existing in {None, next(iter(candidates))}:
        chosen = next(iter(candidates))
    else:
        if candidates:
            objective.raw["db2_item_status"] = "AMBIGUOUS"
        return
    profile = profiles.get(str(chosen)) or {}
    uses = profile.get("uses") or []
    if profile.get("status") != "RESOLVED" or len(uses) != 1:
        objective.raw["db2_item_status"] = "UNRESOLVED"
        return
    use = uses[0]
    objective.raw["db2_item_use"] = {"item_id": chosen, "item_name": profile.get("name"), **deepcopy(use)}
    objective.raw["db2_item_status"] = use["status"]
    if use["status"] != "RESOLVED":
        return
    # Preserve/restore every field modified by this reference on the next
    # projection, so changed/removed item evidence cannot leave a stale plan.
    objective.raw["db2_item_original"] = {
        "type": objective.type, "target_entity": deepcopy(objective.target_entity),
        "target_object": deepcopy(objective.target_object),
    }
    objective.target_object = {**(objective.target_object or {}), "item_id": chosen,
                               "name": profile.get("name"), "source": "CLIENT_DB2_ITEM_EFFECT"}
    objective.type = "USE_ITEM_ON_TARGET"
    names = []
    if (objective.target_entity or {}).get("name"):
        names.append(objective.target_entity["name"])
    actors = (source.get("named_creatures") or []) if use["target_mode"] == "UNIT" else []
    subject_entries = {entry for candidate in source.get("item_uses") or ()
                       if candidate.get("item_id") == chosen
                       for entry in candidate.get("subject_entries") or ()}
    if subject_entries:
        actors = [{"entry": entry, "name": next((row.get("name") for row in actors
                    if row.get("entry") == entry), None)} for entry in sorted(subject_entries)]
    if (not actors and use["target_mode"] == "UNIT" and source.get("credit_kind") == "CREATURE_CREDIT"
            and source.get("credit_name") and not re.search(
            r"kill credit|credit:|proxy|\[dnt\]", source["credit_name"], re.I)):
        actors = [{"entry": source.get("credit_object_id"), "name": source["credit_name"]}]
    for row in actors:
        if row.get("name") and row["name"] not in names:
            names.append(row["name"])
    if len(actors) == 1 and not objective.target_entity and _id(actors[0].get("entry")):
        objective.target_entity = {"npc_id": actors[0]["entry"], "name": actors[0].get("name"),
                                   "source": "TDB_ITEM_SUBJECT"}
    objective.raw["item_target_names"] = names
    if use["target_mode"] not in {"UNIT", "SELF"}:
        objective.raw["db2_item_status"] = "UNSUPPORTED_TARGET_MODE"


def clear_item_knowledge(objective):
    original = objective.raw.pop("db2_item_original", None)
    if original:
        for key, value in original.items():
            setattr(objective, key, value)
    for key in ("db2_item_use", "db2_item_status", "item_target_names"):
        objective.raw.pop(key, None)


def authorized_item(state, item_id, quest_ids):
    """An active quest plus its exact observed item or unambiguous DB2 link."""
    ids = {str(i) for i in quest_ids or ()}
    for quest in state.get("active_quests") or ():
        qid = str(quest.get("quest_id"))
        if qid not in ids or quest.get("is_complete") is True:
            continue
        if str((quest.get("special_item") or {}).get("item_id")) == str(item_id):
            return True
        ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(qid) or {}
        from .quest_reference_matching import reference_objectives
        for objective in quest.get("objectives") or ():
            if objective.get("is_complete") is True:
                continue
            matched = reference_objectives(qid, objective.get("objective_id"), objective.get("description"),
                                           ref.get("objectives") or [])
            if len(matched) != 1:
                continue
            candidates = matched[0].get("item_uses") or []
            if len(candidates) == 1 and str(candidates[0]["item_id"]) == str(item_id):
                return True
            # P8.4 COLLECT_CONTAINER: the bag container whose loot (TDB
            # item_loot_template) holds this open objective's item.
            if str(item_id) in {str(v) for v in matched[0].get("container_items") or ()}:
                return True
    return False


def item_allows_dead_target(state, item_id, quest_ids) -> bool:
    """User 2026-11-03: some quests use the item on a dead NPC/mob.  The spell's
    own SPELL_ATTR2_ALLOW_DEAD_TARGET (client DB2) says so; unknown is False."""
    profile = current_use(state, item_id, quest_ids) or {}
    return profile.get("can_target_dead") is True


def current_use(state, item_id, quest_ids):
    """Return a unique projected profile; do not open a database on input dispatch."""
    values = []
    for qid in quest_ids or ():
        ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(qid)) or {}
        profile = ((ref.get("items") or {}).get("use_profiles") or {}).get(str(item_id)) or {}
        uses = profile.get("uses") or []
        if profile.get("status") == "RESOLVED" and len(uses) == 1:
            values.append(uses[0])
    return values[0] if values and all(v == values[0] for v in values) else None


def maximum_range(use):
    """Conservative reference range; live per-item in_range overrides it."""
    ranges = use.get("ranges") or []
    if len(ranges) != 1:
        return None
    values = ranges[0].get("RangeMax") or []
    relation = use.get("target_relation")
    selected = values[:1] if relation == "HOSTILE" else values[1:2] if relation == "FRIENDLY" else values
    if (not selected or any(type(n) not in {int, float} or not math.isfinite(n) or n <= 0 for n in selected)):
        return None
    return min(selected)
