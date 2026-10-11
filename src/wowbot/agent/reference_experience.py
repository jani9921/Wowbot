"""Context-scoped learned additions to the immutable reference catalogue.

Uses the existing EntityMemory transaction/lock. Never rewrites source data,
never promotes a dispatched click or an empty view to a confirmed fact.
"""
from __future__ import annotations

import json
import math
import hashlib
import time
from .models import canonical, number
from .quest_creature_memory import npc_id_from_guid


def context_for(state):
    return {"character": state.get("character_guid") or state.get("session_id"),
            "map_id": state.get("map_id"), "world_map_id": (state.get("player_world_position") or {}).get("instance_id"),
            "phase": state.get("phase"), "instance_id": state.get("instance_id"),
            "faction": state.get("faction") or state.get("player_faction")}


def world_position(value):
    if not isinstance(value, dict) or value.get("coordinate_space") != "WORLD_YARDS":
        return None
    xyz = {axis: number(value.get(axis)) for axis in ("x", "y", "z")}
    if any(v is None or not math.isfinite(v) for v in xyz.values()) or value.get("instance_id") is None:
        return None
    return {**xyz, "instance_id": value["instance_id"], "coordinate_space": "WORLD_YARDS"}


class ReferenceExperience:
    def __init__(self, entities):
        self.entities = entities
        self.revision = 0
        self._seen = {}
        self._route = None
        from .learned_world import LearnedWorld, learned_path_for
        # The learned second TDB (tdb_learned.sqlite3, same tables as the
        # TDB) next to the profile's entity memory (user 2026-10-11).
        self.learned = LearnedWorld(learned_path_for(entities), on_change=self._learned_changed,
                                    legacy_entities=entities)
        with entities._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS reference_experience (
                    evidence_key TEXT PRIMARY KEY, kind TEXT NOT NULL, quest_id TEXT,
                    npc_id INTEGER, context TEXT NOT NULL, observed_at REAL NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS reference_experience_quest ON reference_experience(quest_id,context,observed_at);
                CREATE INDEX IF NOT EXISTS reference_experience_npc ON reference_experience(npc_id,context,observed_at);
            ''')

    def _learned_changed(self):
        self.revision += 1

    def record(self, key, kind, state, data, *, quest_id=None, npc_id=None):
        with self.entities._connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO reference_experience VALUES (?,?,?,?,?,?,?)",
                (key, kind, str(quest_id) if quest_id is not None else None, npc_id,
                 canonical(context_for(state)), time.time(), canonical(data)))
            self.revision += cursor.rowcount

    def query(self, state, *, quest_id=None, npc_id=None, limit=32, max_age=30*86400):
        sql = "SELECT kind,observed_at,data FROM reference_experience WHERE context=?"
        args = [canonical(context_for(state))]
        if max_age is not None:
            sql += " AND observed_at>=?"; args.append(time.time()-max_age)
        if quest_id is not None:
            sql += " AND quest_id=?"; args.append(str(quest_id))
        elif npc_id is not None:
            sql += " AND npc_id=?"; args.append(npc_id)
        else:
            return []
        sql += " ORDER BY observed_at DESC LIMIT ?"; args.append(limit)
        with self.entities._connect() as db:
            rows = db.execute(sql, args).fetchall()
        return [{"kind": kind, "observed_at": at, **json.loads(data)} for kind,at,data in rows]

    def observe(self, state, now, attempt=None):
        context = canonical(context_for(state))
        if state.get("transport_kind") != "FAST":
            for quest in state.get("active_quests") or ():
                if not isinstance(quest, dict) or quest.get("quest_id") is None:
                    continue
                details = {"quest_id": quest["quest_id"], "title": quest.get("title"),
                           "completion_text": quest.get("completion_log_text"),
                           "description": quest.get("description"), "source": "ADDON_QUEST_HISTORY",
                           "objectives": [{k: o.get(k) for k in ("objective_id", "description", "type", "raw_type")}
                                          for o in quest.get("objectives") or () if isinstance(o, dict)]}
                digest = hashlib.sha256((context+canonical(details)).encode()).hexdigest()
                key = ("quest-details", str(quest["quest_id"]), digest)
                if key not in self._seen:
                    self.record("quest:"+digest, "QUEST_DETAILS", state, details, quest_id=quest["quest_id"])
                    self._seen[key] = now
        for lane in ("target", "mouseover"):
            unit = state.get(lane) or {}
            guid = unit.get("guid")
            npc = npc_id_from_guid(guid)
            if not guid or npc is None or unit.get("is_player") is True:
                continue
            if unit.get("npc_id") is not None and str(unit["npc_id"]) != str(npc):
                continue  # contradictory ID/GUID must not teach
            position = world_position(unit.get("world_position"))
            stamp = (context, guid, canonical(position))
            unit_stamp = (context, guid, "any-position")
            if 0 <= now-self._seen.get(unit_stamp, float("-inf")) < 2:
                continue
            if 0 <= now-self._seen.get(stamp, float("-inf")) < 30:
                continue
            self._seen[stamp] = now
            self._seen[unit_stamp] = now
            if len(self._seen) > 256:
                self._seen = {stamp: now}
            self.entities.record_mouseover({**unit, "npc_id": npc}, map_id=state.get("map_id"),
                map_x=None, map_y=None, zone=state.get("zone_name"), observed_at=time.time(),
                phase=state.get("phase"), instance_id=state.get("instance_id"), observation_id=state.get("frame_id"))
            self.record(f"seen:{context}:{guid}:{state.get('frame_id')}:{now}", "ENTITY_SEEN", state,
                        {"npc_id": npc, "guid": guid, "name": unit.get("name"),
                         "source": "ADDON_"+lane.upper(), "position": position,
                         "location_kind": "ENTITY_POSITION" if position else "NO_EXACT_POSITION"}, npc_id=npc)
        if len(self._seen) > 512:
            self._seen.clear()
        if attempt is None or attempt.proposal.skill not in {"MOVE", "VISUAL_APPROACH", "APPROACH_TARGET"}:
            return
        if self._route is None or self._route["action_id"] != attempt.action_id:
            self._route = {"action_id": attempt.action_id, "context": context, "points": [],
                           "last_at": float("-inf"), "truncated": False}
        if self._route["context"] != context:
            self._route["truncated"] = True
            return
        if now-self._route["last_at"] < 1:
            return
        position = world_position(state.get("player_world_position"))
        if position:
            points = self._route["points"]
            if len(points) < 256:
                points.append({**position, "elapsed": round(now-attempt.started_at, 3),
                               "falling": (state.get("movement") or {}).get("falling")})
            else:
                self._route["truncated"] = True
            self._route["last_at"] = now

    def finish(self, attempt, outcome, reason, state):
        params, before = attempt.proposal.parameters, attempt.baseline
        qid = params.get("quest_id")
        if context_for(before) != context_for(state):
            self._route = None
            return
        self._learn_world(attempt, outcome, before, state)
        if self._route and self._route["action_id"] == attempt.action_id:
            route, self._route = self._route, None
            self.record("route:"+attempt.action_id, "ROUTE_OUTCOME", state,
                {"action_id": attempt.action_id, "plan_id": attempt.plan_id,
                 "points": route["points"], "truncated": route["truncated"],
                 "skill": attempt.proposal.skill, "outcome": str(outcome), "reason": reason,
                 "source": "OBSERVED_PLAYER_ROUTE", "navigation_trusted": False,
                 "target_guid": params.get("guid"), "reference_hint_id": params.get("reference_hint_id")},
                quest_id=qid, npc_id=npc_id_from_guid(params.get("guid")))
        if params.get("reference_hint_id"):
            # Failure downweights this attempt in this context, never declares
            # an NPC absent or overwrites a location. Cancellation teaches nothing.
            if str(outcome) in {"SUCCESS", "FAILURE"}:
                self.record("hint:"+attempt.action_id, "HINT_OUTCOME", state,
                    {"hint_id": params["reference_hint_id"], "outcome": str(outcome), "reason": reason,
                     "source": "VERIFIED_ATTEMPT_RESULT"}, quest_id=qid)
        if (str(outcome) == "SUCCESS" and qid is not None and attempt.proposal.skill in
                {"OBJECT_USE", "USE", "USE_ON_TARGET", "COMBAT", "INTERACT", "TALK"}):
            old = next((q for q in before.get("active_quests") or () if str(q.get("quest_id")) == str(qid)), {})
            new = next((q for q in state.get("active_quests") or () if str(q.get("quest_id")) == str(qid)), {})
            position = world_position(state.get("player_world_position"))
            old_objectives = old.get("objectives") or []
            for index, obj in enumerate(new.get("objectives") or []):
                if index >= len(old_objectives) or position is None:
                    continue
                previous = old_objectives[index]
                # Stable objective correspondence is required; shuffled stages
                # must not attribute another objective's counter to this place.
                if (previous.get("objective_id"), previous.get("description")) != (obj.get("objective_id"), obj.get("description")):
                    continue
                a = number(previous.get("current", previous.get("current_count")))
                b = number(obj.get("current", obj.get("current_count")))
                oid = str(obj.get("objective_id") or f"{qid}:{index}")
                if a is not None and b is not None and b > a and str(params.get("objective_id")) == oid:
                    self.record("objective:"+attempt.action_id+":"+oid, "OBJECTIVE_REGION", state,
                        {"objective_id": oid, "position": position, "source": "VERIFIED_OBJECTIVE_PROGRESS",
                         "location_kind": "OBSERVER_SEARCH_REGION", "before": a, "after": b,
                         "skill": attempt.proposal.skill, "confirmed_historical": True}, quest_id=qid)
        if str(outcome) != "SUCCESS" or attempt.proposal.skill != "QUEST_DIALOG" or qid is None:
            return
        ui = before.get("quest_ui") or {}
        if str(ui.get("quest_id", before.get("quest_ui_quest_id"))) != str(qid):
            return
        action = str(params.get("action") or ui.get("action") or before.get("quest_ui_action") or "").upper()
        event_kind, role = (("QUEST_ACCEPTED", "QUEST_STARTER") if action == "ACCEPT" else
                            ("QUEST_TURNED_IN", "QUEST_ENDER") if action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"} else (None,None))
        events = [e for e in state.get("events") or () if isinstance(e, dict) and e not in (before.get("events") or ())]
        event = next((e for e in events if e.get("event_type") == event_kind
                      and str((e.get("payload") or {}).get("quest_id")) == str(qid)), None)
        if event is None:
            return
        target = before.get("target") or {}
        text = before.get("quest_text") or {}
        guid = params.get("guid") or target.get("guid")
        npc = npc_id_from_guid(guid)
        dialog_guid = text.get("giver_guid" if role == "QUEST_STARTER" else "ender_guid")
        if (npc is None or target.get("guid") != guid or not target.get("name")
                or str(text.get("quest_id")) != str(qid) or dialog_guid != guid):
            return  # no attribution to arbitrary selected unit or stale dialog
        self.learned.record_role("CREATURE", npc, qid, role, target["name"], source=event_kind)
        self.learned.record_spawn("CREATURE", npc, target["name"], before.get("player_world_position"),
                                  phase=before.get("phase"), source=event_kind)
        self.record("role:"+attempt.action_id, "QUEST_ROLE", state,
                    {"npc_id": npc, "guid": guid, "name": target["name"], "role": role,
                     "source": event_kind+"_AND_DIALOG_GUID", "evidence": event,
                     "observer_position": world_position(before.get("player_world_position")),
                     "location_kind": "OBSERVER_POSITION", "confirmed_historical": True},
                    quest_id=qid, npc_id=npc)

    # Interactions that need proximity: the player's position is the place
    # of the NPC/object within a few yards (user 2026-10-10: the TDB is the
    # world memory, and what the agent verifies live is saved next to it).
    PROXIMITY_SKILLS = {"TALK", "INTERACT", "COMBAT", "DEFEND", "OBJECT_USE", "LOOT"}

    def _learn_world(self, attempt, outcome, before, state):
        skill = attempt.proposal.skill
        if str(outcome) != "SUCCESS" or skill not in self.PROXIMITY_SKILLS:
            return
        params = attempt.proposal.parameters
        position = state.get("player_world_position") or before.get("player_world_position")
        phase = state.get("phase")
        if skill == "OBJECT_USE":
            mouse = before.get("mouseover") or {}
            name = (params.get("tdb_object_name") or mouse.get("name")
                    or str(mouse.get("tooltip") or "").split("~", 1)[0].strip()
                    or next(iter(params.get("subjects") or ()), None))
            entry = params.get("tdb_object_id") or params.get("object_id") or mouse.get("object_id")
            self.learned.record_spawn("GAMEOBJECT", entry, name, position, phase=phase,
                                      source="OBJECT_USE_VERIFIED")
            return
        target = before.get("target") or {}
        guid = params.get("guid") or target.get("guid")
        npc = npc_id_from_guid(guid)
        if npc is None or target.get("is_player") is True:
            return
        name = target.get("name") if target.get("guid") == guid else params.get("name")
        self.learned.record_spawn("CREATURE", npc, name, position, phase=phase,
                                  source=skill+"_VERIFIED")

