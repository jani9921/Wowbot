"""QuestDomain per-objective proposals: item use, vendor trade, NPC/object interaction.

Split out of quest_planning.py (2026-10-05); unchanged.
"""
from __future__ import annotations

import re

from wowbot.runtime.entity_identity import identity_fields
import math
from .models import Proposal, number
from .world import WorldModel
from .quest_semantics import (target_matches_structured_entity, use_on_subjects, subject_matches_name,
                              speak_target_matches, entity_constraints_allow)
from .quest_giver_evidence import is_game_object_objective
from .quest_tool_resolver import QuestToolResolver
from .target_planning import _hover_box
from .tooltip_quest import known_dead_unit


# Retail's vendor gossip icon (Interface/GossipFrame/VendorGossipIcon).
VENDOR_GOSSIP_ICON = 132060
_VENDOR_OPTION_TEXT = re.compile(
    r"\b(for sale|browse|goods|wares|buy|purchase|shop|merchant|vendor)\b", re.IGNORECASE)


def vendor_gossip_option(options) -> dict | None:
    """The gossip row that opens the NPC's shop (vendor icon or wording)."""
    rows = [row for row in options or () if isinstance(row, dict) and row.get("available") is not False
            and row.get("id") is not None and str(row.get("name") or "").strip()
            and number(row.get("x")) is not None and number(row.get("y")) is not None
            and 0 < number(row["x"]) < 1 and 0 < number(row["y"]) < 1]
    return (next((row for row in rows if number(row.get("icon")) == VENDOR_GOSSIP_ICON), None)
            or next((row for row in rows if _VENDOR_OPTION_TEXT.search(str(row["name"]))), None))


def quest_sellable(item: dict) -> bool:
    """A bag item a SELL objective may sell: no quest item, not locked, not
    gear, and the client says it has a value.

    Live 2026-10-25 10:54:44-10:55:00 (Stocking Up on Supplies): addon 0.9.75
    read every bag item's price through the removed global GetItemInfo, so
    all 13 items had sell price 0 and the open vendor got nothing sold.
    Addon 0.9.76 exports the client's own ``has_no_value`` flag as well."""
    return (isinstance(item, dict) and item.get("is_quest_item") is not True
            and item.get("is_locked") is not True and item.get("is_equippable") is not True
            and ((number(item.get("sell_price")) or 0) > 0 or item.get("has_no_value") is False)
            and number(item.get("x")) is not None and number(item.get("y")) is not None)


def quest_vendor_item(items, description, money) -> dict | None:
    """The shop item a BUY objective names, else the cheapest affordable one.

    User 2026-10-21 (Cataloger Jakes, "Buy Archeologist Artifact Notes"): the
    wanted item is the one the objective names, priced in a currency
    (extended cost); the old cheapest-gold rule skipped it.
    """
    text = str(description or "").casefold()
    shown = [item for item in items or () if isinstance(item, dict)
             and item.get("is_purchasable") is True
             and number(item.get("x")) is not None and number(item.get("y")) is not None]
    named = [item for item in shown if str(item.get("name") or "").strip()
             and str(item["name"]).casefold() in text
             and (item.get("extended_cost") is True
                  or (money is not None and (number(item.get("price")) or 0) <= money))]
    if named:
        return max(named, key=lambda item: len(str(item["name"])))
    if any(str(item.get("name") or "").strip() and str(item["name"]).casefold() in text
           for item in items or () if isinstance(item, dict)):
        return None                     # the named item is not buyable now: buy nothing else
    cheapest = [item for item in shown if item.get("extended_cost") is not True
                and number(item.get("price")) is not None
                and money is not None and item["price"] <= money]
    return min(cheapest, key=lambda value: (value.get("price", 0), value.get("slot", 0))) if cheapest else None


EMPTY_DIALOG_CLOSES = 2
EMPTY_DIALOG_REST_SECONDS = 120.


def vendor_dialog_suppressed(closes: dict | None, guid, now) -> bool:
    """This NPC's window was closed empty twice lately: do not reopen it."""
    times = (closes or {}).get(str(guid or "")) or ()
    recent = [at for at in times if now is not None and 0 <= now-at <= EMPTY_DIALOG_REST_SECONDS]
    return len(recent) >= EMPTY_DIALOG_CLOSES


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
            # Live 2026-10-19 15:23-15:25: standing at Harpy Totems (another
            # quest's objects) while the primary was "Harpy Culling", their
            # use was never even proposed.  A server-usable quest object a
            # few yards away is worked like an item subject at hand.
            at_hand = self._server_object_at_hand(world, obj, state, qid)
            if primary_quest_id and qid != primary_quest_id and not at_hand:
                continue
            # Live 2026-10-04 (Richter): the primary objective was the BUY;
            # with no buyable row the SELL at the same open shop was skipped
            # and the agent waited.  Every trade objective uses the open shop.
            if (primary_objective_id and obj.objective_id != primary_objective_id
                    and not (shop_open and obj.type in {"BUY", "SELL"})
                    and not self._item_subject_at_hand(obj, state) and not at_hand):
                continue
            record = next((value for value in records.values() if str(value.quest_id) == qid), None)
            item_use = obj.raw.get("db2_item_use") or {}
            if (item_use.get("delivery") or {}).get("mode") == "FORWARD_CONE" and record:
                from .directed_item_planning import DirectedItemPolicy
                policy = self.__dict__.setdefault("directed_items", DirectedItemPolicy())
                steps = policy.propose(obj, record, state, state_time)
                result.extend(steps or self.location_policy.propose_objective(world, obj, record, qid))
                continue
            if item_use and (item_use.get("status") != "RESOLVED"
                             or item_use.get("target_mode") not in {"UNIT", "SELF"}):
                result.append(Proposal.make(
                    "WAIT", "Quest item: a katalógus célzási módjához még nincs igazolt végrehajtási út",
                    {"quest_ids": [record.quest_id if record else qid], "objective_id": obj.objective_id,
                     "item_id": item_use.get("item_id"), "item_spell_id": item_use.get("spell_id"),
                     "item_target_mode": item_use.get("target_mode"), "purpose": "UNSUPPORTED_ITEM_MECHANIC"},
                    priority=80, evidence=("db2_item_use_requires_supported_targeting",)))
                continue
            item_subject = self._server_item_subject(obj, record, state, state_time)
            if item_subject is not None:
                result.append(item_subject)
                continue
            if obj.raw.get("quest_tool_kind") == "HEAL":
                selected = state.get("target") or {}
                if self._quest_heal_used(obj, state, selected.get("guid"), state_time):
                    continue  # credit was verified; acquire another actor, never re-use this one
                if (selected.get("guid") and entity_constraints_allow(selected, obj.target_entity)
                        and selected.get("attackable", selected.get("is_attackable")) is not False):
                    result.append(Proposal.make(
                        "WAIT", "A gyógyítandó NPC barátságos target-bizonyítékára várok",
                        {"guid": selected["guid"], "objective_id": obj.objective_id,
                         "purpose": "QUEST_ITEM_READY"}, priority=117))
                    continue
            location_proposals = self.location_policy.propose_objective(world, obj, record, qid)
            result.extend(location_proposals)
            if item_use.get("target_mode") == "SELF":
                # The existing locator must verify arrival before self use.
                at_area = any(p.parameters.get("purpose") == "SEARCH_LOCAL_OBJECTIVE_AREA"
                              for p in location_proposals if p.skill == "SEEK_VISUAL_CUE")
                from .quest_item_knowledge import authorized_item
                quest_ids = [record.quest_id if record else qid]
                action = next((a for a in state.get("actionbar") or ()
                               if a.get("kind") == "item" and str(a.get("id")) == str(item_use["item_id"])
                               and a.get("is_usable") is True
                               and number(a.get("cooldown_remaining")) is not None
                               and 0 <= number(a["cooldown_remaining"]) <= .1), None)
                if at_area and action and authorized_item(state, item_use["item_id"], quest_ids):
                    result[:] = [p for p in result if p not in location_proposals]
                    result.append(Proposal.make("USE_ON_TARGET", "Questterület elérve: önmagamra ható quest item",
                        {"quest_ids": quest_ids, "objective_id": obj.objective_id, "item_id": item_use["item_id"],
                         "item_spell_id": item_use["spell_id"], "item_target_mode": "SELF", "target_required": False,
                         "binding": action.get("action"), "activation_source": "ACTIONBAR"},
                        priority=80, evidence=("db2_item_self_use", "objective_area_arrived")))
                continue
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
                target and (subjects and target.get("name")
                and subject_matches_name(subjects, target.get("name"))
                or item_use.get("target_mode") == "UNIT"
                and (obj.target_entity or {}).get("npc_id") is not None
                and str(target.get("npc_id")) == str(obj.target_entity["npc_id"]))
                and entity_constraints_allow(target, obj.target_entity)
                and (not known_dead_unit(target, state) or item_use.get("can_target_dead") is True))
            if (not (obj.type in {"USE_OBJECT", "INTERACT"} and is_game_object_objective(obj))
                    and state.get("packet_entities")):
                # Live 2026-10-23 (Library of Alexstrasza): "0/4 Books saved"
                # is credited by looting book chests the TDB lists only as
                # hidden item rows; the server names each chest's objective.
                from .packet_entity_facts import hidden_object_sources
                quest_key = record.quest_id if record else qid
                hidden = hidden_object_sources(state, quest_key)
                # A described item row only objects yield (the campfire's
                # Cooked Meat): its own objective uses the server object
                # once the server marks it usable; no learned-place walk or
                # zone sweep (the campfire is usable only after the meat).
                own_object_row = str(obj.raw.get("tdb_objective_id")) in {
                    objective for objective, _entry in hidden_object_sources(state, quest_key, described=True)}
                if hidden or own_object_row:
                    flow = self.location_policy.object_interaction
                    flow.note_result((world.runtime_context.get("last_result") or {})
                                     if hasattr(world, "runtime_context") else {}, state)
                    player_z = self.location_policy.player_layer_z(
                        world, state, navigation_queries=self.navigation_queries)
                    server_spot, _known = flow.packet_use_spot(state, quest_key, player_z)
                    steps = (self._server_object_steps(flow, state, server_spot, player_z, obj, quest_key)
                             if server_spot is not None else None)
                    if steps is not None:
                        result.extend(steps)
                        continue
                    remembered = (flow.remembered_object_spot(state, quest_key)
                                  if hidden and server_spot is None and not state.get("is_in_combat") else None)
                    if remembered is not None:
                        position = state.get("player_world_position") or {}
                        result.append(Proposal.make(
                            "MOVE", "Quest-tárgy tanult helye (a szerver most nem látja): odamegyek",
                            {"x": remembered["x"], "y": remembered["y"], "z": remembered["z"],
                             "z_known": True, "z_source": "LEARNED_SPAWN",
                             "coordinate_space": "WORLD_YARDS",
                             "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                             "purpose": "LOCATE_REMEMBERED_QUEST_OBJECT", "require_navmesh": True,
                             "stop_distance": 4.0, "reference_hint_id": remembered["hint"],
                             "object_id": remembered["object_id"],
                             "quest_id": quest_key, "objective_id": obj.objective_id},
                            confidence=.8, priority=90,
                            evidence=("remembered_object_spawn", "beyond_server_view")))
                        continue
                    cell = (flow.server_sweep_cell(state, quest_key)
                            if hidden and server_spot is None and remembered is None
                            and not state.get("is_in_combat") else None)
                    if cell is not None:
                        position = state.get("player_world_position") or {}
                        result.append(Proposal.make(
                            "MOVE", "Quest POI-zóna bejárása: a szerver útközben küldi a közeli tárgyakat",
                            {"x": cell["x"], "y": cell["y"],
                             **({"z": cell["z"], "z_known": True, "z_source": "TDB_QUEST_POI"}
                                if cell.get("z") is not None else {"z_known": False}),
                             "coordinate_space": "WORLD_YARDS",
                             "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                             "purpose": "SERVER_ZONE_SWEEP", "require_navmesh": True,
                             "stop_distance": 10.0, "quest_id": quest_key,
                             "objective_id": obj.objective_id},
                            confidence=.7, priority=85,
                            evidence=("quest_poi_polygon", "no_server_object_in_view")))
                        continue
            if obj.type in {"USE_OBJECT", "INTERACT"} and is_game_object_objective(obj):
                flow = self.location_policy.object_interaction
                flow.note_result((world.runtime_context.get("last_result") or {})
                                 if hasattr(world, "runtime_context") else {}, state)
                if flow.line_of_sight_blocked(state):
                    # A LOS error requires a changed vantage point. The
                    # generic OBJECT_USE fallback below must not re-click
                    # this same obstructed hover on every planner tick.
                    continue
                player_z = self.location_policy.player_layer_z(
                    world, state, navigation_queries=self.navigation_queries)
                quest_key = record.quest_id if record else qid
                server_spot, server_known = flow.packet_use_spot(state, quest_key, player_z)
                if server_spot is not None:
                    # The server names this exact object, its objective and
                    # whether it is usable for us (Ymir).  Walk to it, face
                    # it, press Interact out of combat; combat comes first.
                    steps = self._server_object_steps(flow, state, server_spot, player_z, obj, quest_key)
                    if steps is not None:
                        result.extend(steps)
                        continue
                    # UNIT_SOFT_TARGET / OTHER_OBJECT_NEARER / NO_POSE: F7 is
                    # ambiguous here; the hover/right-click flow below still
                    # names the object under the cursor.
                spot = (None if server_known else flow.tdb_use_spot(state, quest_key, player_z))
                soft_ready = flow.soft_target(flow.expected_identity(obj), state) is not None
                if spot is not None and spot["distance"] > flow.USE_RANGE_YARDS and not soft_ready:
                    # Live 2026-10-14 14:03-14:08: clicks from 7.4 / 16 yd
                    # (the large cocoon box looked near) -- walk to the
                    # exact spawn first, then hover and use it there.
                    position = state.get("player_world_position") or {}
                    result.append(Proposal.make(
                        "MOVE", "Quest-objektum TDB-helye a saját szinten: odalépek a használathoz",
                        {"x": spot["x"], "y": spot["y"], "z": spot["z"], "z_known": True,
                         "z_source": "TDB_SPAWN", "coordinate_space": "WORLD_YARDS",
                         "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                         "purpose": "APPROACH_QUEST_OBJECT_SPAWN", "require_navmesh": True,
                         "stop_distance": 2.5, "reference_hint_id": spot.get("hint"),
                         # Face it there: its soft-interact target, then the Interact key.
                         "face_on_arrival": True,
                         "quest_id": record.quest_id if record else qid,
                         "objective_id": obj.objective_id},
                        confidence=.85, priority=97,
                        evidence=("tdb_object_spawn_same_floor", "out_of_use_range")))
                    continue
                # A TDB spawn is a navigation destination, not proof of the
                # current Interact-key recipient. Hover/soft identity gates use.
                object_steps = flow.propose_object_steps(obj, record, state)
                approaching_object = any(
                    step.skill == "VISUAL_APPROACH"
                    and step.parameters.get("object_use_approach") is True
                    for step in object_steps)
                from .tooltip_quest import effective_mouseover
                identity = self.location_policy.object_interaction.expected_identity(obj)
                cursor = state.get("cursor_position") or {}
                mouse = effective_mouseover(state)
                usable_now = (not approaching_object and not flow.range_blocked(state)
                              and not flow.line_of_sight_blocked(state)
                              and not flow.just_credited(state)
                              and all(number(cursor.get(k)) is not None for k in ("nx", "ny")))
                id_matched = usable_now and self.location_policy.object_interaction.quest_mouseover_matches(
                    identity, mouse, state, quest_key)
                # Live 2026-10-19/20: every Harpy Totem was hovered with its
                # quest tooltip, but a game object has no public ID, so the
                # ID-only rule above never let one be used.  The client's own
                # quest tooltip line + the object name + a spawn within use
                # range certify it (out of combat: an attacker breaks the cast).
                tooltip_matched = (usable_now and not id_matched and not state.get("is_in_combat")
                                   and flow.tooltip_certified(identity, mouse, state, quest_key, player_z))
                if id_matched:
                    object_steps = [Proposal.make(
                        "OBJECT_USE", "Quest-objektum az egér alatt (tooltip egyezik): használat",
                        {"x": cursor["nx"], "y": cursor["ny"], **identity_fields(mouse),
                         "object_id": identity.get("object_id") or mouse.get("object_id"),
                         "mouseover_tooltip": mouse.get("tooltip") or mouse.get("name"),
                         "expected_tooltips": identity.get("expected_tooltips"),
                         "tdb_object_name": identity.get('tdb_object_name'),
                         "objective_id": obj.objective_id,
                         "quest_ids": [quest_key]},
                        confidence=.85, priority=92)] + object_steps
                elif tooltip_matched:
                    from wowbot.runtime.skill_identity import QUEST_OBJECT_TOOLTIP
                    object_steps = [Proposal.make(
                        "OBJECT_USE", "Quest-tárgy az egér alatt (a kliens quest-tooltipje igazolja): jobb klikk",
                        {"x": cursor["nx"], "y": cursor["ny"],
                         "identity_certification": QUEST_OBJECT_TOOLTIP,
                         "objective_object_id": identity.get("object_id"),
                         "mouseover_tooltip": mouse.get("tooltip") or mouse.get("name"),
                         "expected_tooltips": flow.objective_object_names(identity, state, quest_key),
                         "tdb_object_name": identity.get('tdb_object_name'),
                         "objective_id": obj.objective_id,
                         "quest_ids": [quest_key]},
                        confidence=.85, priority=95,
                        evidence=("client_quest_tooltip", "objective_object_name", "spawn_in_use_range"))] + object_steps
                if object_steps:
                    result.extend(object_steps)
                    continue
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
            from .quest_item_knowledge import authorized_item
            special_item = bool(inventory_item) and authorized_item(
                state, item_id, [record.quest_id if record else qid])
            guid = str(target.get("guid") or "") if target else ""
            quest_ids = [record.quest_id if record else qid]
            tool_context = ({"purpose": "HEAL_QUEST_ITEM", **identity_fields(obj.target_entity or {})}
                            if obj.raw.get("quest_tool_kind") == "HEAL" else {})
            if item_use:
                tool_context.update(item_spell_id=item_use["spell_id"], item_target_mode=item_use["target_mode"],
                                    **identity_fields(obj.target_entity or {}))
            readiness = QuestToolResolver.item_state(state, item_id, guid, quest_ids, now=state_time)
            activation = None
            if action:
                activation = {"binding": action.get("action"), "activation_source": "ACTIONBAR"}
            elif (special_item and selected_item_target
                  and QuestToolResolver.can_interact(state, item_id, guid, quest_ids, now=state_time)):
                # Keep near F7, but only when this exact item is ready on this
                # exact current recipient. Far F7 is auto-attack (user 10-18).
                activation = {"binding": "INTERACTTARGET", "activation_source": "INTERACT_KEY"}
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
            last_result = (world.runtime_context.get("last_result") or {}) if hasattr(world, "runtime_context") else {}
            from wowbot.verification.interaction import classify_ui_error
            item_position_failure = (
                last_result.get("skill") in {"USE_ON_TARGET", "ASSIST"}
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
            if selected_item_target and guid and not range_blocked:
                range_blocked = (readiness is not None and readiness.get("in_range") is False
                                 or readiness is None and (action is not None and action.get("in_range") is False
                                     or (action is None or action.get("in_range") is not True)
                                     and self._item_target_far(state, target, item_use)))
            if range_blocked:
                approach = self._item_target_approach(state, target, obj, record, qid, state_time)
                if approach is not None:
                    result.append(approach)
                    continue
                result.append(Proposal.make(
                    "WAIT", "A kijelölt quest-item célpont friss helyére várok; nem indulok másik spawnhoz",
                    {"guid": guid, "item_id": item_id, "objective_id": obj.objective_id,
                     "quest_ids": quest_ids, "purpose": "QUEST_ITEM_READY"}, priority=85))
                continue
            target_matches_item_use = selected_item_target
            if target_matches_item_use and readiness is not None and (
                    readiness.get("is_usable") is False
                    or (number(readiness.get("cooldown_remaining")) or 0.) > .1):
                result.append(Proposal.make(
                    "WAIT", "Az azonosított quest item még nem használható / cooldownon van",
                    {"guid": guid, "item_id": item_id, "objective_id": obj.objective_id,
                     "quest_ids": quest_ids, "purpose": "QUEST_ITEM_READY"}, priority=85))
                continue
            if (target_matches_item_use and not activation and inventory_item
                    and state.get("bags_open") is not True):
                result.append(Proposal.make(
                    "OPEN_BAGS", "Quest special item pontos bag-slotjának megnyitása",
                    {"purpose": "QUEST_ITEM", "item_id": item_id, "guid": guid,
                     "objective_id": obj.objective_id,
                     "quest_ids": [record.quest_id if record else qid]},
                    confidence=obj.confidence, priority=81,
                    evidence=("exact_active_quest_item", "inventory_item_present")))
            elif target_matches_item_use and not activation:
                result.append(Proposal.make(
                    "WAIT", "Kijelölt quest-item célpont: friss item/slot bizonyítékra várok",
                    {"guid": guid, "item_id": item_id, "objective_id": obj.objective_id,
                     "quest_ids": quest_ids, "purpose": "QUEST_ITEM_READY"}, priority=85))
            if (selected_item_target
                    and target.get("attackable", target.get("is_attackable")) is False):
                if activation and activation.get("activation_source") == "INTERACT_KEY":
                    # ASSIST can only press an action-bar item; the special
                    # item is used through Interact Target on its objective
                    # NPC (live 2026-10-10: Austin Huxworth selected, no
                    # executable proposal, the First Aid Kit never used).
                    result.append(Proposal.make(
                        "USE_ON_TARGET", "Névvel azonosított barátságos target: quest item interact gombbal",
                        {"guid": target.get("guid"), "item_id": item_id,
                          **activation, **tool_context, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=80))
                elif activation:
                    result.append(Proposal.make(
                        "ASSIST", "Névvel azonosított barátságos target: quest item használata",
                        {"guid": target.get("guid"), "item_id": item_id,
                          **activation, **tool_context, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=78))
            elif selected_item_target:
                if activation:
                    result.append(Proposal.make(
                        "USE_ON_TARGET", "Quest item használata névvel egyező, élő targeten",
                        {"guid": target.get("guid"), "item_id": item_id,
                          **activation, **tool_context, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=80))
            mouse = state.get("mouseover") or {}
            if (subjects and mouse.get("guid") and mouse.get("guid") != target.get("guid")
                    and subject_matches_name(subjects, mouse.get("name"))
                    and entity_constraints_allow(mouse, obj.target_entity)
                    and mouse.get("dead") is not True and mouse.get("is_dead") is not True):
                cursor = state.get("cursor_position") or {}
                if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                    result.append(Proposal.make(
                        "TARGET", "Quest item névvel egyező mouseover targetjének kijelölése",
                        {"x": cursor["nx"], "y": cursor["ny"], **identity_fields(mouse),
                         "ground_truth_handoff": True, "click_current_cursor": True,
                         **_hover_box(state, str(mouse["guid"])),
                         "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=79))
            vendor = state.get("vendor_ui") or {}
            if obj.type == "BUY" and vendor.get("open") is True:
                money = number(state.get("money"))
                item = quest_vendor_item(vendor.get("items", []), obj.description, money)
                if item is not None:
                        result.append(Proposal.make(
                        "BUY_VENDOR", "Aktív quest vásárlási célja: a megnevezett (vagy legolcsóbb) vendor-item",
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
                                if quest_sellable(item)]
                    if sellable:
                        # Junk first (grey), then the cheapest.
                        item = min(sellable, key=lambda value: (number(value.get("quality")) or 0,
                                                                number(value.get("sell_price")) or 0))
                        result.append(Proposal.make(
                            "SELL_VENDOR", "Aktív quest eladási célja: nem quest- és nem felszerelhető bag item",
                            {"x": item["x"], "y": item["y"], "bag": item.get("bag"),
                             "slot": item.get("slot"), "item_id": item.get("item_id"),
                             "count": item.get("count"), "objective_id": obj.objective_id,
                             "quest_ids": [record.quest_id if record else qid]},
                            confidence=obj.confidence, priority=82))
            # An open NPC window is QuestDialogPlanningPolicy's (vendor gossip row).
            dialog_open = ((state.get("quest_ui") or {}).get("open") is True
                           or state.get("quest_ui_open") is True)
            if (obj.type in {"BUY", "SELL"} and vendor.get("open") is not True and not dialog_open
                    and target_matches_structured_entity(target, obj.target_entity)
                    and target.get("attackable", target.get("is_attackable")) is False
                    and not vendor_dialog_suppressed(world.__dict__.get("empty_dialog_closes"),
                                                     target.get("guid"), number(state.get("monotonic_time")))):
                # The named vendor is selected: interacting opens its shop.
                result.append(Proposal.make(
                    "INTERACT", "Quest vásárlás/eladás: a névvel azonosított vendor megnyitása",
                    {"guid": target.get("guid"), "purpose": "OPEN_VENDOR",
                     "objective_id": obj.objective_id,
                     "quest_id": record.quest_id if record else qid},
                    confidence=obj.confidence, priority=74))
            if (obj.type in {"TALK_TO", "INTERACT_NPC", "INTERACT"}
                    and (speak_target_matches(obj, target) if obj.type != "INTERACT"
                         else target_matches_structured_entity(target, obj.target_entity))):
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
            object_match = self.location_policy.object_interaction.quest_mouseover_matches(
                object_identity, mouse, state, record.quest_id if record else qid)
            cursor = state.get("cursor_position") or {}
            if obj.type in {"USE_OBJECT", "INTERACT"} and object_match and all(number(cursor.get(k)) is not None for k in ("nx", "ny")):
                result.append(Proposal.make("OBJECT_USE", "Strukturált quest object és addon mouseover egyezés",
                                            {"x": cursor["nx"], "y": cursor["ny"],
                                             "object_id": object_identity.get("object_id") or mouse.get("object_id"),
                                             **identity_fields(mouse),
                                             "item_id": expected_object.get("item_id"),
                                             "mouseover_tooltip": mouse.get("tooltip"),
                                             "objective_id": obj.objective_id,
                                             "quest_ids": [record.quest_id if record else qid]},
                                            confidence=obj.confidence, priority=75))

    SERVER_OBJECT_AT_HAND_YARDS = 12.

    def _server_object_steps(self, flow, state: dict, server_spot: dict, player_z,
                             obj, quest_key) -> list[Proposal] | None:
        """OBJECT_USE / MOVE for a server-named usable quest object, [] in
        combat (the attacker would break the use cast), None when F7 is
        ambiguous here (another unit or object would take it)."""
        position = state.get("player_world_position") or {}
        ready = flow.packet_interact_ready(state, server_spot, player_z)
        if ready == "READY":
            return [Proposal.make(
                "OBJECT_USE", "Szerver által azonosított quest-tárgy előttem: Interact (F7)",
                {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
                 "object_guid": server_spot["guid"], "object_id": server_spot["object_id"],
                 "server_interaction_range": flow.packet_use_range(server_spot),
                 "objective_id": obj.objective_id, "quest_ids": [quest_key]},
                confidence=.92, priority=97,
                evidence=("server_game_object_identity", "server_activate_flag",
                          "facing_in_range_no_unit_soft_target"))]
        if ready in {"OUT_OF_RANGE", "NOT_FACING", "OTHER_FLOOR", "REPOSITION"}:
            approach = ({} if ready == "OTHER_FLOOR" else flow.packet_approach_search().goal(state, server_spot))
            if approach is None:
                return []
            return [Proposal.make(
                "MOVE", "Szerver: quest-tárgy pontos helye: odalépek és felé fordulok",
                {"x": server_spot["x"], "y": server_spot["y"], "z": server_spot["z"],
                 "z_known": True, "z_source": "PACKET_GAMEOBJECT",
                 "coordinate_space": "WORLD_YARDS",
                 "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_QUEST_OBJECT_SPAWN", "require_navmesh": True,
                 "stop_distance": (max(flow.packet_stop_distance(server_spot), server_spot["distance"]+.05)
                                   if ready == "NOT_FACING" else flow.packet_stop_distance(server_spot)),
                 "reference_hint_id": server_spot["hint"],
                 "server_entity_guid": server_spot["guid"], "face_on_arrival": True,
                 "quest_id": quest_key, "objective_id": obj.objective_id, **approach},
                confidence=.9, priority=97,
                evidence=("server_game_object_identity", ready.lower()))]
        if ready in {"IN_COMBAT", "NOT_INTERACTABLE"}:
            return []
        return None

    def _server_object_at_hand(self, world, obj, state: dict, qid) -> bool:
        """A usable object of this game-object objective is right here: the
        server (Ymir) shows one close by, or the cursor is on one and the
        client's quest tooltip certifies it (no Ymir needed)."""
        if obj.type not in {"USE_OBJECT", "INTERACT"} or not is_game_object_objective(obj):
            return False
        flow = self.location_policy.object_interaction
        player_z = self.location_policy.player_layer_z(
            world, state, navigation_queries=self.navigation_queries)
        if state.get("packet_entities"):
            spot, _known = flow.packet_use_spot(state, qid, player_z)
            if spot is not None and spot["distance"] <= self.SERVER_OBJECT_AT_HAND_YARDS:
                return True
        from .tooltip_quest import effective_mouseover
        return flow.tooltip_certified(flow.expected_identity(obj), effective_mouseover(state),
                                      state, qid, player_z)

    def _quest_heal_used(self, obj, state: dict, guid, now) -> bool:
        if not guid or now is None:
            return False
        key = (str(state.get("session_id")), str(obj.objective_id), str(guid))
        visit = self.__dict__.get("_quest_item_visits", {}).get(key) or {}
        return (number(visit.get("used_until")) or 0.) > now

    def _server_item_subject(self, obj, record, state: dict, now) -> Proposal | None:
        """Acquire a concrete item actor through existing MOVE/TARGET skills.

        No item is used here. The selected GUID, NPC identity, exact item,
        range/cooldown and recipient are rechecked by the normal item skill.
        The legacy friendly-tab activation is shared with rescue acquisition;
        it never authorizes an enemy Tab or accepts another GUID as a match.
        """
        healing = obj.raw.get("quest_tool_kind") == "HEAL"
        use = obj.raw.get("db2_item_use") or {}
        unit_item = use.get("status") == "RESOLVED" and use.get("target_mode") == "UNIT"
        if (not (healing or unit_item) or record is None or now is None
                or state.get("is_in_combat") or state.get("is_casting")
                or state.get("is_dead") or state.get("is_ghost") or state.get("in_vehicle")
                or (state.get("quest_ui") or {}).get("open") or state.get("world_map_open")):
            return None
        entry = (obj.target_entity or {}).get("npc_id")
        item_id = (obj.target_object or {}).get("item_id")
        if (entry is None or item_id is None
                or not any(str(row.get("item_id")) == str(item_id) and not row.get("is_locked")
                           for row in (state.get("inventory") or {}).get("items") or ())):
            return None
        from .packet_entity_facts import interaction_position
        from .tooltip_quest import known_dead_unit
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if px is None or py is None:
            return None
        visits = self.__dict__.setdefault("_quest_item_visits", {})
        from .quest_item_search import remember_subjects, search_proposal
        remember_subjects(visits, obj, state, now)
        choices = []
        for unit in (state.get("packet_entities") or {}).values():
            if (str(unit.get("entry_id")) != str(entry) or not unit.get("guid")
                    or (known_dead_unit(unit, state) and use.get("can_target_dead") is not True)):
                continue
            point = interaction_position(state, unit["guid"])
            if point is None:
                continue
            key = (str(state.get("session_id")), str(obj.objective_id), str(unit["guid"]))
            visit = visits.get(key) or {}
            presses = [at for at in visit.get("presses", ()) if 0 <= now-at <= 45.]
            if (self._quest_heal_used(obj, state, unit["guid"], now) or len(presses) >= 3
                    or (number(visit.get("settling_until")) or 0.) > now):
                continue
            target = state.get("target") or {}
            selected = str(target.get("guid")) == str(unit["guid"])
            distance = math.hypot(point["x"]-px, point["y"]-py)
            pz = number(player.get("z")) if player.get("z_known") is not False else None
            distance3d = math.hypot(distance, point["z"]-pz) if pz is not None else distance
            choices.append((not selected, distance3d, unit["guid"], point, presses, selected))
        if not choices:
            selected = state.get("target") or {}
            selected_visit = visits.get((str(state.get("session_id")), str(obj.objective_id),
                                         str(selected.get("guid")))) or {}
            if (selected.get("guid") and entity_constraints_allow(selected, obj.target_entity)
                    and (not known_dead_unit(selected, state) or use.get("can_target_dead") is True)
                    and not self._quest_heal_used(obj, state, selected["guid"], now)
                    and (number(selected_visit.get("settling_until")) or 0.) <= now):
                return None  # An already selected item recipient keeps readiness/use ownership.
            return search_proposal(visits, obj, record, state, now)
        _, distance, guid, point, presses, selected = min(choices, key=lambda row: row[:3])
        facing = number(state.get("orientation"))
        aligned = (distance < 1. or facing is not None and abs(
            (math.atan2(point["y"]-py, point["x"]-px)-facing+math.pi) % math.tau-math.pi) <= .45)
        params = {"guid": guid, "npc_id": entry, "item_id": item_id,
                  "quest_ids": [record.quest_id], "objective_id": obj.objective_id}
        if distance > 3. or not aligned:
            return Proposal.make("MOVE", "Quest item célpontja: pontos szerverhelyre és szembefordulás",
                {**point, **params, "server_entity_guid": guid, "map_id": state.get("map_id"),
                 "z_observed": True, "z_source": "PACKET_ENTITY", "require_navmesh": True,
                 "face_on_arrival": True, "stop_distance": 2., "purpose": "APPROACH_ITEM_TARGET"},
                confidence=.95, priority=118,
                evidence=("quest_tool_heal_clause" if healing else "db2_item_subject", "server_entity_identity"))
        if selected:
            return None  # Existing exact-item readiness/use proposals own it.
        if presses and now-presses[-1] < 4.:
            return Proposal.make("WAIT", "Quest-item célpont kijelölési visszajelzésére várok",
                                 {**params, "purpose": "QUEST_ITEM_ACQUIRE"}, priority=117)
        activation = "TAB_FRIEND_RESCUE"
        if not healing and presses:
            # A target-any item can need an enemy/neutral unit. Selecting
            # never attacks: the existing TargetSkill still verifies GUID.
            from .packet_entity_facts import tab_target_check
            if not tab_target_check(state, guid)[0]:
                return Proposal.make("WAIT", "A quest-item célpont biztonságos kijelölésére várok",
                    {**params, "purpose": "QUEST_ITEM_ACQUIRE"}, priority=117)
            activation = "TAB_SERVER_GUID"
        return Proposal.make("TARGET", "Quest-item NPC közel és előttem: kijelölés GUID-ellenőrzéssel",
            {**params, "activation_source": activation, "acceptable_guids": [guid],
             "purpose": "QUEST_ITEM_ACQUIRE"}, confidence=.9, priority=117)

    @staticmethod
    def _item_subject_at_hand(obj, state: dict) -> bool:
        """The unit an item objective is used on is hovered or selected now.

        Live 2026-10-05 (Emergency First Aid): the primary objective was the
        kit on Bjorn; Kee-La was hovered three times and then selected, but
        her objective -- same quest, same First Aid Kit -- was skipped as
        "not primary", so the kit was never used.
        """
        if (obj.target_object or {}).get("item_id") is None:
            return False
        subjects = use_on_subjects({**obj.raw, "description": obj.description})
        units = [state.get("target") or {}, state.get("mouseover") or {}]
        return bool(subjects) and any(
            isinstance(unit, dict) and unit.get("name")
            and not unit.get("dead", unit.get("is_dead"))
            and subject_matches_name(subjects, unit["name"]) for unit in units)

    # Interact range is a few yards; beyond this the key does nothing.
    ITEM_INTERACT_YARDS = 7.
    # A unit box this small on screen is clearly beyond interact range.
    ITEM_FAR_BOX_HEIGHT = .07

    def _item_target_far(self, state: dict, target: dict, item_use=None) -> bool:
        """The selected item target is known to be out of interact range."""
        player = state.get("player_world_position") or {}
        where = target.get("world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        tx, ty = number(where.get("x")), number(where.get("y"))
        from .quest_item_knowledge import maximum_range
        limit = maximum_range(item_use or {}) or self.ITEM_INTERACT_YARDS
        if (None not in (px, py, tx, ty) and where.get("coordinate_space") == "WORLD_YARDS"
                and where.get("source") != "UNIT_POSITION"
                and str(where.get("instance_id")) == str(player.get("instance_id"))):
            dz = 0.
            if player.get("z_known") is True and None not in (number(player.get("z")), number(where.get("z"))):
                dz = float(where["z"])-float(player["z"])
            return math.hypot(tx-px, ty-py, dz) > limit
        anchor = target.get("screen_position") or {}
        height = number(anchor.get("bbox_height_fraction") or anchor.get("height"))
        return height is not None and height < self.ITEM_FAR_BOX_HEIGHT

    def _item_target_approach(self, state: dict, target: dict, obj, record, qid, state_time):
        """Walk to a selected item-use target that answered "too far"."""
        guid = str(target.get("guid") or "")
        params = {"guid": guid, "item_id": (obj.target_object or {}).get("item_id"),
                  "objective_id": obj.objective_id,
                  "quest_ids": [record.quest_id if record else qid]}
        anchor = target.get("screen_position") or {}
        sample = number(anchor.get("sample_time"))
        from .server_mode import server_profile
        if (number(anchor.get("x")) is not None and number(anchor.get("y")) is not None
                and sample is not None and state_time is not None
                and -5. <= state_time - sample < 30. and not server_profile(state)):
            return Proposal.make(
                "VISUAL_APPROACH", "Quest item célpontja túl messze: képernyőn követett megközelítés",
                {**params, "purpose": "INTERACT", "item_use_approach": True,
                 "track_id": anchor.get("track_id"),
                 "visual_signature": anchor.get("visual_signature"), "screen_position": anchor,
                 "ready_bbox_height": self.VISUAL_INTERACTION_HEIGHT},
                confidence=.8, priority=84)
        where = target.get("world_position") or {}
        if (where.get("coordinate_space") == "WORLD_YARDS"
                and where.get("source") != "UNIT_POSITION"
                and number(where.get("x")) is not None and number(where.get("y")) is not None):
            # A minimap target marker estimate (user 2026-10-04) or API position.
            return Proposal.make(
                "MOVE", "Quest item célpontja túl messze: odamegyek a becsült helyére",
                {**params, "x": where["x"], "y": where["y"], "coordinate_space": "WORLD_YARDS",
                 "instance_id": where.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_ITEM_TARGET", "stop_distance": 6.0, "require_navmesh": True},
                confidence=.7, priority=84)
        return None
