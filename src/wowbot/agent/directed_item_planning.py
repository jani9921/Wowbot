"""Directed quest-item proposals inside the existing QuestDomain."""
from __future__ import annotations
import math
from .models import Proposal, number
from .directed_item_facts import PURPOSE, delivery, subject_links, aim_state, ready_for_use
from .quest_item_knowledge import authorized_item

class DirectedItemPolicy:
    def __init__(self):
        self.visits = {}

    def note_result(self, result, state, params):
        if (result.get("skill") not in {"USE_ON_TARGET", "MOVE"}
                or params.get("purpose") != PURPOSE
                or result.get("outcome") not in {"SUCCESS", "FAILURE"}
                or result.get("skill") == "MOVE" and result.get("outcome") == "SUCCESS"):
            return
        now = number(state.get("monotonic_time"))
        if now is None:
            return
        key = (str(state.get("session_id")), str(params.get("objective_id")), str(params.get("item_aim_guid")))
        visit = self.visits.setdefault(key, {"attempts":0})
        visit["attempts"] += 1
        visit["until"] = now + (600 if result.get("outcome") == "SUCCESS" or visit["attempts"] >= 2 else 45)
        while len(self.visits) > 128:
            self.visits.pop(next(iter(self.visits)))

    def propose(self, obj, record, state, now):
        use = obj.raw.get("db2_item_use") or {}
        shape = delivery(use)
        base = {"quest_ids":[record.quest_id], "objective_id":obj.objective_id,
                "objective_ids":[obj.objective_id], "item_id":use.get("item_id"),
                "item_spell_id":use.get("spell_id"), "item_target_mode":"SELF",
                "target_required":False, "purpose":PURPOSE}
        def wait(reason):
            return [Proposal.make("WAIT", reason, base, priority=116)]
        if not shape:
            return wait("Az irányított quest item igazolt geometriájára várok")
        if state.get("is_in_combat"):
            return []
        if state.get("is_mounted"):
            return [Proposal.make("DISMOUNT", "Quest item használatához leszállás", base, priority=117)]
        ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(record.quest_id)) or {}
        row = next((r for r in ref.get("objectives") or [] if r.get("objective_id") == obj.raw.get("tdb_objective_id")), {})
        entries = {link["subject_entry"] for link in subject_links(use, row)}
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        now = number(now)
        if now is None or px is None or py is None:
            return wait("Az irányított quest itemhez a karakter friss helyére várok")
        choices = []
        entities = state.get("packet_entities") or {}
        for unit in (entities.values() if isinstance(entities, dict) else ()):
            if not isinstance(unit, dict) or unit.get("entry_id") not in entries:
                continue
            params = {**base,"item_aim_guid":unit.get("guid"),"item_aim_entry":unit.get("entry_id")}
            key = (str(state.get("session_id")), str(obj.objective_id), str(unit.get("guid")))
            if self.visits.get(key, {}).get("until", 0) > now:
                continue
            status, point = aim_state(state, params, now)
            if point is not None and status in {"READY","NOT_FACING","OUT_OF_RANGE","MOVING"}:
                choices.append((math.hypot(point["x"]-px,point["y"]-py),str(unit.get("guid")),params,point,status))
        if not choices:
            return []  # the existing objective locator owns area discovery
        _, _, params, point, status = min(choices, key=lambda choice: choice[:2])
        if status in {"OUT_OF_RANGE","NOT_FACING"}:
            return [Proposal.make("MOVE", "Irányított quest item: a szerveres célhoz megyek és felé fordulok",
                {**params, **point, "server_entity_guid":params["item_aim_guid"],
                 "map_id":state.get("map_id"),"z_known":True,"z_source":"PACKET_ENTITY",
                 "require_navmesh":True,"face_on_arrival":True,"stop_distance":min(4.,shape["radius"]*.5)},
                priority=117, evidence=("tdb_spell_hit_credit","db2_cone_geometry","server_entity_position"))]
        if status == "MOVING":
            return wait("Irányított quest item: megállásra várok")
        if not ready_for_use(state, params, now):
            return wait("A quest item friss használhatósági / cooldown adatára várok")
        if not authorized_item(state, use["item_id"], base["quest_ids"]):
            return []
        action = next((a for a in state.get("actionbar") or () if a.get("kind") == "item"
                       and str(a.get("id")) == str(use["item_id"]) and a.get("is_usable") is True
                       and number(a.get("cooldown_remaining")) is not None
                       and 0 <= number(a["cooldown_remaining"]) <= .1 and a.get("action")), None)
        if action:
            activation = {"activation_source":"ACTIONBAR", "binding":action["action"]}
        else:
            item = next((i for i in (state.get("inventory") or {}).get("items") or ()
                         if i.get("item_id") == use["item_id"] and i.get("is_locked") is not True), None)
            if not item:
                return wait("Az aktív quest készülékére várok a táskában")
            if state.get("bags_open") is not True:
                return [Proposal.make("OPEN_BAGS","Az irányított quest item táskagombjának megnyitása",
                                      {**params,"purpose":"QUEST_ITEM"},priority=117)]
            if (item.get("coordinate_space") != "CLIENT_BOTTOM_LEFT"
                    or type(item.get("bag")) is not int or not 0 <= item["bag"] <= 5
                    or type(item.get("slot")) is not int or item["slot"] <= 0
                    or any(number(item.get(k)) is None or not 0 < number(item[k]) < 1 for k in ("x","y"))):
                return wait("A quest item látható táskagombjának koordinátájára várok")
            activation = {"activation_source":"INVENTORY_COORDINATE",
                          **{k:item[k] for k in ("bag","slot","x","y","coordinate_space")}}
        return [Proposal.make("USE_ON_TARGET","A cél felé fordulva használom a quest készüléket",
                              {**params,**activation},priority=118,
                              evidence=("active_quest_item","verified_directed_item_pose"))]

