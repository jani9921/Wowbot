"""QuestDomain per-objective proposals: item use, vendor trade, NPC/object interaction.

Split out of quest_planning.py (2026-10-05); unchanged.
"""
from __future__ import annotations
from .models import Proposal, number
from .world import WorldModel
from .quest_semantics import target_matches_structured_entity, use_on_subjects, subject_matches_name


class QuestObjectivePlanningMixin:
    """Methods of QuestDomain (quest_planning.py); moved verbatim."""

    def _propose_objectives(self, world: WorldModel, state: dict, state_time, records,
                            primary_quest_id: str, primary_objective_id: str,
                            shop_open: bool, result: list) -> None:
        """Per-objective proposals of the ready quest objectives (appended to result).

        Split out of _propose (2026-10-05); the loop is unchanged.
        """
        for obj in world.quest_model.ready():
            qid = obj.objective_id.split(":", 1)[0]
            if primary_quest_id and qid != primary_quest_id:
                continue
            # Live 2026-10-04 (Richter): the primary objective was the BUY;
            # with no buyable row the SELL at the same open shop was skipped
            # and the agent waited.  Every trade objective uses the open shop.
            if (primary_objective_id and obj.objective_id != primary_objective_id
                    and not (shop_open and obj.type in {"BUY", "SELL"})):
                continue
            record = next((value for value in records.values() if str(value.quest_id) == qid), None)
            location_proposals = self.location_policy.propose_objective(world, obj, record, qid)
            result.extend(location_proposals)
            if obj.type in {"WAIT", "DEFEND"}:
                # Travel only when a concrete location is already known.
                # Missing/ambiguous markers must not turn a defend/wait event
                # into free-roaming SEARCH/INSPECT behavior.
                concrete_route = any(item.skill in {
                    "MOVE", "REACH_LOCATION", "REACH_OBJECT"
                } for item in location_proposals)
                if not concrete_route:
                    result.append(Proposal.make(
                        "WAIT_EVENT",
                        "Helyben maradó, bounded quest-esemény figyelés",
                        {"quest_ids": [record.quest_id if record else qid],
                         "objective_ids": [obj.objective_id],
                         "objective_kind": obj.type},
                        confidence=obj.confidence, priority=76,
                        evidence=("defend_wait_objective", "no_concrete_route")))
                    continue
            target = world.query.target()
            item_id = (obj.target_object or {}).get("item_id")
            subjects = use_on_subjects({**obj.raw, "description": obj.description}) if item_id is not None else []
            selected_item_target = bool(
                subjects and target and target.get("name")
                and subject_matches_name(subjects, target.get("name"))
                and not target.get("dead", target.get("is_dead")))
            if (any(proposal.skill == "SEEK_VISUAL_CUE" for proposal in location_proposals)
                    and not selected_item_target):
                # Live 2026-10-04 10:50: the local search SEEK also skipped
                # the item use on an already selected Wandering Boar.
                continue
            action = next((item for item in state.get("actionbar", [])
                           if item.get("kind") == "item" and str(item.get("id")) == str(item_id)
                           and item.get("is_usable") is True), None)
            inventory_item = next((item for item in (state.get("inventory") or {}).get("items", [])
                                   if str(item.get("item_id")) == str(item_id)
                                   and item.get("is_locked") is not True), None)
            activation = None
            if action:
                activation = {"binding": action.get("action"), "activation_source": "ACTIONBAR"}
            elif (state.get("bags_open") is True and inventory_item
                  and inventory_item.get("coordinate_space") == "CLIENT_BOTTOM_LEFT"
                  and number(inventory_item.get("x")) is not None
                  and number(inventory_item.get("y")) is not None):
                activation = {
                    "activation_source": "INVENTORY_COORDINATE",
                    "bag": inventory_item.get("bag"), "slot": inventory_item.get("slot"),
                    "x": inventory_item.get("x"), "y": inventory_item.get("y"),
                    "coordinate_space": "CLIENT_BOTTOM_LEFT",
                }
            elif inventory_item and selected_item_target and any(
                    str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
                    for quest in state.get("active_quests") or ()):
                # Live 2026-10-04 10:44: the Re-Sizer credit came from the
                # Interact key on the selected boar -- Retail's interact uses
                # an active quest's special item on its objective target.
                activation = {"binding": "INTERACTTARGET", "activation_source": "INTERACT_KEY"}
            guid = str(target.get("guid") or "") if target else ""
            last_result = (world.runtime_context.get("last_result") or {}) if hasattr(world, "runtime_context") else {}
            from wowbot.verification.interaction import classify_ui_error
            item_position_failure = (
                last_result.get("skill") == "USE_ON_TARGET"
                and any(token in str(last_result.get("reason") or "").casefold()
                        for token in ("range", "facing", "line_of_sight", "sight")))
            ui_position_error = classify_ui_error(state.get("ui_error"), state.get("ui_error_code"))
            if (guid in self.item_range_blocks and last_result.get("outcome") == "SUCCESS"
                    and last_result.get("skill") in {"VISUAL_APPROACH", "MOVE"}):
                self.item_range_blocks.pop(guid, None)     # approached: try the item again
            elif selected_item_target and guid and (ui_position_error or item_position_failure):
                # Too far, not in line of sight, or behind us (user): approach,
                # which also turns toward the target.
                self.item_range_blocks[guid] = state_time
            range_blocked = (selected_item_target and guid in self.item_range_blocks
                             and state_time is not None
                             and state_time - float(self.item_range_blocks[guid] or 0.) <= self.ITEM_RANGE_BLOCK_SECONDS)
            if range_blocked:
                approach = self._item_target_approach(state, target, obj, record, qid, state_time)
                if approach is not None:
                    result.append(approach)
                    continue
            target_matches_item_use = bool(
                subjects and target and target.get("name")
                and subject_matches_name(subjects, target.get("name"))
                and not target.get("dead", target.get("is_dead")))
            if (target_matches_item_use and not action and inventory_item
                    and state.get("bags_open") is not True):
                result.append(Proposal.make(
                    "OPEN_BAGS", "Quest special item pontos bag-slotjának megnyitása",
                    {"purpose": "QUEST_ITEM", "item_id": item_id,
                     "objective_id": obj.objective_id,
                     "quest_ids": [record.quest_id if record else qid]},
                    confidence=obj.confidence, priority=81,
                    evidence=("exact_active_quest_item", "inventory_item_present")))
            if (subjects and target and target.get("name")
                    and subject_matches_name(subjects, target.get("name"))
                    and target.get("attackable", target.get("is_attackable")) is False
                    and not target.get("dead", target.get("is_dead"))):
                if activation:
                    result.append(Proposal.make(
                        "ASSIST", "Névvel azonosított barátságos target: quest item használata",
                        {"guid": target.get("guid"), "item_id": item_id,
                         **activation, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=78))
            elif (subjects and target and target.get("name")
                    and subject_matches_name(subjects, target.get("name"))
                    and not target.get("dead", target.get("is_dead"))):
                if activation:
                    result.append(Proposal.make(
                        "USE_ON_TARGET", "Quest item használata névvel egyező, élő targeten",
                        {"guid": target.get("guid"), "item_id": item_id,
                         **activation, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=80))
            mouse = state.get("mouseover") or {}
            if (subjects and mouse.get("guid") and mouse.get("guid") != target.get("guid")
                    and subject_matches_name(subjects, mouse.get("name"))):
                cursor = state.get("cursor_position") or {}
                if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                    result.append(Proposal.make(
                        "TARGET", "Quest item névvel egyező mouseover targetjének kijelölése",
                        {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"],
                         "objective_id": obj.objective_id},
                        confidence=obj.confidence, priority=79))
            vendor = state.get("vendor_ui") or {}
            if obj.type == "BUY" and vendor.get("open") is True:
                money = number(state.get("money"))
                candidates = [item for item in vendor.get("items", [])
                              if item.get("is_purchasable") is True
                              and item.get("extended_cost") is not True
                              and number(item.get("x")) is not None and number(item.get("y")) is not None
                              and number(item.get("price")) is not None
                              and money is not None and item["price"] <= money]
                if candidates:
                    item = min(candidates, key=lambda value: (value.get("price", 0), value.get("slot", 0)))
                    result.append(Proposal.make(
                        "BUY_VENDOR", "Aktív quest vásárlási célja: legolcsóbb megvehető vendor-item",
                        {"x": item["x"], "y": item["y"], "slot": item.get("slot"),
                         "item_id": item.get("item_id"), "price": item.get("price"),
                         "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=82))
            if obj.type == "SELL" and vendor.get("open") is True:
                if state.get("bags_open") is not True:
                    result.append(Proposal.make(
                        "OPEN_BAGS", "Aktív quest eladási céljához meg kell nyitni a táskákat",
                        {"objective_id": obj.objective_id}, confidence=obj.confidence, priority=83))
                else:
                    sellable = [item for item in (state.get("inventory") or {}).get("items", [])
                                if item.get("is_quest_item") is not True and item.get("is_locked") is not True
                                and item.get("is_equippable") is not True
                                and (number(item.get("sell_price")) or 0) > 0
                                and number(item.get("x")) is not None and number(item.get("y")) is not None]
                    if sellable:
                        item = min(sellable, key=lambda value: (value.get("quality", 99), value.get("sell_price", 0)))
                        result.append(Proposal.make(
                            "SELL_VENDOR", "Aktív quest eladási célja: nem quest- és nem felszerelhető bag item",
                            {"x": item["x"], "y": item["y"], "bag": item.get("bag"),
                             "slot": item.get("slot"), "item_id": item.get("item_id"),
                             "count": item.get("count"), "objective_id": obj.objective_id,
                             "quest_ids": [record.quest_id if record else qid]},
                            confidence=obj.confidence, priority=82))
            if (obj.type in {"BUY", "SELL"} and vendor.get("open") is not True
                    and target_matches_structured_entity(target, obj.target_entity)
                    and target.get("attackable", target.get("is_attackable")) is False):
                # The named vendor is selected: interacting opens its shop.
                result.append(Proposal.make(
                    "INTERACT", "Quest vásárlás/eladás: a névvel azonosított vendor megnyitása",
                    {"guid": target.get("guid"), "purpose": "OPEN_VENDOR",
                     "objective_id": obj.objective_id,
                     "quest_id": record.quest_id if record else qid},
                    confidence=obj.confidence, priority=74))
            if obj.type in {"TALK_TO", "INTERACT_NPC", "INTERACT"} and target_matches_structured_entity(target, obj.target_entity):
                if target.get("attackable", target.get("is_attackable")) is False:
                    vehicle = (str(target.get("guid") or "").startswith("Vehicle-")
                               or (obj.target_entity or {}).get("source") == "OBJECTIVE_TEXT")
                    # A vehicle NPC (Scout-o-Matic 5000) seats the player and
                    # opens no dialog: INTERACT's verifier accepts the seat.
                    result.append(Proposal.make("TALK" if obj.type in {"TALK_TO", "INTERACT_NPC"} and not vehicle
                                                else "INTERACT",
                                                "Strukturált quest target explicit identity egyezés",
                                                {"guid": target.get("guid"), "objective_id": obj.objective_id,
                                                 "quest_id": record.quest_id if record else qid},
                                                confidence=obj.confidence, priority=72))
            from .tooltip_quest import effective_mouseover
            mouse = effective_mouseover(state)
            expected_object = obj.target_object or {}
            object_identity = self.location_policy.object_interaction.expected_identity(obj)
            object_match = self.location_policy.object_interaction.mouseover_matches(
                object_identity, mouse)
            cursor = state.get("cursor_position") or {}
            if obj.type in {"USE_OBJECT", "INTERACT"} and object_match and all(number(cursor.get(k)) is not None for k in ("nx", "ny")):
                result.append(Proposal.make("OBJECT_USE", "Strukturált quest object és addon mouseover egyezés",
                                            {"x": cursor["nx"], "y": cursor["ny"],
                                             "object_id": expected_object.get("object_id"),
                                             "item_id": expected_object.get("item_id"),
                                             "mouseover_tooltip": mouse.get("tooltip"),
                                             "objective_id": obj.objective_id,
                                             "quest_ids": [record.quest_id if record else qid]},
                                            confidence=obj.confidence, priority=75))

    def _item_target_approach(self, state: dict, target: dict, obj, record, qid, state_time):
        """Walk to a selected item-use target that answered "too far"."""
        guid = str(target.get("guid") or "")
        params = {"guid": guid, "objective_id": obj.objective_id,
                  "quest_ids": [record.quest_id if record else qid]}
        anchor = target.get("screen_position") or {}
        sample = number(anchor.get("sample_time"))
        if (number(anchor.get("x")) is not None and number(anchor.get("y")) is not None
                and sample is not None and state_time is not None
                and -5. <= state_time - sample < 30.):
            return Proposal.make(
                "VISUAL_APPROACH", "Quest item célpontja túl messze: képernyőn követett megközelítés",
                {**params, "purpose": "INTERACT", "track_id": anchor.get("track_id"),
                 "visual_signature": anchor.get("visual_signature"), "screen_position": anchor,
                 "ready_bbox_height": self.VISUAL_INTERACTION_HEIGHT},
                confidence=.8, priority=84)
        where = target.get("world_position") or {}
        if (where.get("coordinate_space") == "WORLD_YARDS"
                and number(where.get("x")) is not None and number(where.get("y")) is not None):
            # A minimap target marker estimate (user 2026-10-04) or API position.
            return Proposal.make(
                "MOVE", "Quest item célpontja túl messze: odamegyek a becsült helyére",
                {**params, "x": where["x"], "y": where["y"], "coordinate_space": "WORLD_YARDS",
                 "instance_id": where.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_ITEM_TARGET", "stop_distance": 6.0, "require_navmesh": True},
                confidence=.7, priority=84)
        return None
