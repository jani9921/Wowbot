"""Open the bag container that holds a quest item (REV4 P8.4 COLLECT_CONTAINER).

The census: an objective item that comes only from a bag container
("open the Sack of ..."), TDB ``item_loot_template`` (container entry ->
item).  The quest-item path already right-clicks an addon-reported bag
button (DIRECTED_QUEST_ITEM, live 2026-10-31 26391 "Extinguishing Hope");
the same click opens the container.  Its loot window is then the shared
LOOT step's; an autolooted item credits at once.  No addon button needed.
"""
from __future__ import annotations

from .models import Proposal, number

PRIORITY = 70.


def _slot_ok(item: dict) -> bool:
    return (item.get("coordinate_space") == "CLIENT_BOTTOM_LEFT"
            and type(item.get("bag")) is int and 0 <= item["bag"] <= 5
            and type(item.get("slot")) is int and item["slot"] > 0
            and all(number(item.get(k)) is not None and 0 < number(item[k]) < 1 for k in ("x", "y")))


def container_targets(state: dict) -> list[tuple[str, str, dict]]:
    """(quest id, objective id, bag item) for open objectives whose item a
    container in the bags holds (the client reports it lootable, or unknown)."""
    from .quest_reference_matching import reference_objectives
    refs = (state.get("reference_knowledge") or {}).get("quests") or {}
    items = (state.get("inventory") or {}).get("items") or ()
    result = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        qid = str(quest.get("quest_id"))
        for index, objective in enumerate(quest.get("objectives") or ()):
            if not isinstance(objective, dict) or objective.get("is_complete") is True:
                continue
            matched = reference_objectives(qid, objective.get("objective_id"), objective.get("description"),
                                           (refs.get(qid) or {}).get("objectives") or [])
            if len(matched) != 1:
                continue
            containers = {str(v) for v in matched[0].get("container_items") or ()}
            item = next((i for i in items if isinstance(i, dict) and str(i.get("item_id")) in containers
                         and i.get("has_loot") is not False and i.get("is_locked") is not True), None)
            if item is not None:
                result.append((qid, str(objective.get("objective_id") or f"{qid}:{index}"), item))
    return result


class ContainerOpenPolicy:
    def propose(self, state: dict) -> list[Proposal]:
        if (state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost")
                or (state.get("loot_ui") or {}).get("open") is True or state.get("is_casting")):
            return []
        targets = container_targets(state)
        if not targets:
            return []
        quest_id, objective_id, item = targets[0]
        common = {"quest_ids": [quest_id], "objective_ids": [objective_id], "item_id": item.get("item_id"),
                  "purpose": "OPEN_QUEST_CONTAINER", "target_required": False, "item_target_mode": "SELF"}
        if state.get("bags_open") is not True:
            return [Proposal.make("OPEN_BAGS", "Quest-tárgyat tartalmazó konténer: kinyitom a táskát",
                                  {**common, "purpose": "QUEST_ITEM"}, priority=PRIORITY,
                                  evidence=("tdb_item_loot_container", "bag_item"))]
        if not _slot_ok(item):
            return []
        return [Proposal.make(
            "USE_ON_TARGET", "Quest-tárgyat tartalmazó konténer kinyitása (jobb klikk a táskában)",
            {**common, "activation_source": "INVENTORY_COORDINATE",
             **{k: item[k] for k in ("bag", "slot", "x", "y", "coordinate_space")}},
            confidence=.85, priority=PRIORITY, evidence=("tdb_item_loot_container", "bag_item"))]
