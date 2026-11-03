"""Bounded live probes for objectives whose credit source is unknown (REV4 P8.1).

The census's largest unhandled class (SPELL_CREDIT, PROXY_UNKNOWN,
COLLECT_OTHER, CRITERIA_TREE, UNRESOLVED) has no static link from the
technical credit to what the player does.  Live 2026-10-31 08:27 (26209
"Murder Was The Case"): the clues are credit NPCs "Furlbrow Murder Info
001-004"; the real subjects are the homeless gossip NPCs at the farm (one
gives a clue, another attacks) and the link lives in a core script.  At the
objective's server POI the agent found no handler and waited forever.

This ladder works only from server facts at the objective's server POI:

1. each local gossip NPC (gossip flag, not a quest giver or service NPC) is
   walked up to and talked to once (MOVE, then F7 on the exact soft-interact
   GUID); its open window is eligible for the existing bounded gossip trial
   (``active_probe`` -> quest_dialog_planning);
2. a probed NPC that attacks is handled by the existing defence;
3. when every candidate was tried, a typed ``objective_probes_exhausted``
   WAIT replaces the generic "more data" one.

It proposes existing skills only, at a low priority, so every known handler
of the objective still leads.  No credit is assumed from a press.
"""
from __future__ import annotations

import math

from .models import Proposal, number

# WITNESS (2026-11-02, "Eavesdrop on Thugs."): go where the named speakers are.
PROBE_MECHANISMS = frozenset({"SPELL_CREDIT", "PROXY_UNKNOWN", "COLLECT_OTHER", "CRITERIA_TREE", "UNRESOLVED",
                              "WITNESS"})
GOSSIP_FLAG = 0x1
NOT_A_SUBJECT_FLAGS = (0x2 | 0x10 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800 | 0x1000 | 0x2000
                       | 0x10000 | 0x20000 | 0x400000)      # quest giver, trainer, vendor, repair, flight ...
AREA_YARDS = 45.
CANDIDATE_YARDS = 40.
TALK_SECONDS = 15.
PRIORITY = 60.


def objective_mechanism(state: dict, quest_id, objective) -> str:
    from .quest_reference_matching import reference_objectives
    refs = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    raw = dict(getattr(objective, "raw", None) or {})
    source = reference_objectives(str(quest_id), objective.objective_id, objective.description,
                                  refs.get("objectives"))
    reference = source[0] if len(source) == 1 else {}
    mechanism = raw.get("mechanism") or reference.get("mechanism")
    if not mechanism:
        from wowbot.quests.mechanics import MechanicResolver
        mechanism = MechanicResolver().resolve(quest_id, objective.objective_id, raw, reference).mechanism
    return str(mechanism)


def _subject(value: dict) -> bool:
    from .packet_entity_facts import unit_dead, unit_facts
    flags = (value.get("info") or {}).get("npc_flags")
    return (value.get("kind") == "CREATURE" and not value.get("removed") and not unit_dead(value)
            and type(flags) is int and bool(flags & GOSSIP_FLAG) and not flags & NOT_A_SUBJECT_FLAGS
            and unit_facts(value).get("targets_me") is not True)


class ObjectiveProbeLadder:
    def __init__(self) -> None:
        self.scope = None
        self.talked: dict[str, dict[str, float]] = {}      # quest -> {guid: first F7 proposal}
        self.exhausted: dict[tuple, float] = {}
        self.diagnostic: dict[str, str] = {}               # quest:objective -> why no probe / what ran
        self.areas: dict[str, list] = {}                   # quest -> POI points the player stands in

    def snapshot(self) -> dict:
        return {"diagnostic": dict(self.diagnostic),
                "talked": {quest: sorted(guids) for quest, guids in self.talked.items()},
                "deferred": sorted(f"{quest}:{objective}" for quest, objective in self.exhausted)}

    # P8.3: an exhausted objective is set aside in the agenda for this long;
    # then one fresh round (new actors may have arrived).  Progress on the
    # objective ends the deferral at once.
    DEFER_SECONDS = 300.

    def deferred(self, now: float) -> frozenset:
        """(quest id, objective id) whose probes are exhausted, still deferred."""
        for key, at in list(self.exhausted.items()):
            if not 0 <= now-at < self.DEFER_SECONDS:
                del self.exhausted[key]
                self.talked.pop(key[0], None)
                self.__dict__.get("used_objects", {}).pop(key[0], None)
                self.__dict__.get("used_items", {}).pop(key[0], None)
                self.__dict__.get("listened", {}).pop(key[0], None)
        return frozenset(self.exhausted)

    def _observe_progress(self, key: tuple, objective) -> None:
        progress = self.__dict__.setdefault("progress", {})
        value = (getattr(objective, "current_count", None), getattr(objective, "completion_state", None))
        if key in progress and progress[key] != value:
            self.exhausted.pop(key, None)
            self.talked.pop(key[0], None)
        progress[key] = value

    def _blobs(self, world, record, objective, now):
        """The objective's server POI; else the quest's server objective blobs;
        else the client's own DB2 quest POI (the same map area).

        Live 2026-10-31 09:41-10:18: the character stood in the middle of the
        quest area and did nothing; the login's server POI answers were lost
        in the packet stream, so no area was known.  The client DB2
        QuestPOIBlob/QuestPOIPoint is the geometry the map draws (area, not
        identity) and is always present; the NPCs still come from the server."""
        try:
            blobs = world.query.quest_objective_pois(record.quest_id, objective, now)
            if not blobs:
                blobs = tuple(blob for blob in world.query.quest_pois(record.quest_id, now)
                              if blob.get("objective_index", -1) >= 0)
        except Exception:
            blobs = ()
        return blobs or self._client_blobs(record.quest_id, now)

    def _client_blobs(self, quest_id, now) -> tuple:
        cache = self.__dict__.setdefault("client_pois", {})
        key = str(quest_id)
        if key not in cache:
            try:
                if self.__dict__.get("catalog") is None:
                    from wowbot.quests.client_catalog import ClientCatalog
                    self.catalog = ClientCatalog()
                details = self.catalog.quest(int(quest_id), details=True) or {}
            except Exception:
                details = {}
            points = {}
            for point in details.get("poi_points") or ():
                points.setdefault(point.get("blob_id"), []).append(point)
            cache[key] = tuple(
                {"world_map_id": data.get("MapID"), "ui_map_id": data.get("UiMapID"),
                 "objective_index": data.get("ObjectiveIndex"), "objective_id": data.get("ObjectiveID"),
                 "points": [{"x": p["x"], "y": p["y"], "z": p.get("z")} for p in points.get(row.get("record_id"), ())],
                 "blob_index": 0, "group_index": index, "player_condition_id": data.get("PlayerConditionID"),
                 "navigation_condition_id": data.get("NavigationPlayerConditionID"), "source": "CLIENT_DB2_QUEST_POI"}
                for index, (row, data) in enumerate((row, row.get("data") or {}) for row in details.get("records") or ()
                                                    if row.get("table") == "QuestPOIBlob")
                if type(data.get("ObjectiveIndex")) is int and 0 <= data["ObjectiveIndex"] < 32
                and points.get(row.get("record_id")))
        return tuple({**blob, "sample_time": now} for blob in cache[key])

    def _rescope(self, state: dict) -> None:
        scope = (state.get("session_id"), (state.get("player_world_position") or {}).get("instance_id"))
        if scope != self.scope:
            self.scope, self.talked, self.exhausted, self.progress = scope, {}, {}, {}
            self.used_objects, self.used_items, self.listened = {}, {}, {}

    @staticmethod
    def _soft_candidate(state: dict, candidates, now: float):
        from wowbot.runtime.skill_identity import check_interaction_recipient
        from .server_npc_planning import SOFT_RECIPIENT_YARDS
        soft = next((row for row in state.get("soft_targets") or () if isinstance(row, dict)
                     and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
        if (soft is None or soft.get("is_dead", soft.get("dead")) is True
                or soft.get("is_attackable", soft.get("attackable")) is True):
            return None
        wanted = str(soft.get("guid") or "")
        row = next((row for row in candidates if row[1] == wanted and row[0] <= SOFT_RECIPIENT_YARDS), None)
        sampled = number(state.get("monotonic_time"))
        if row is None or not check_interaction_recipient({"guid": wanted}, state,
                                                          sampled if sampled is not None else now):
            return None
        return row

    def active_probe(self, state: dict) -> dict | None:
        """The probed NPC whose window is open now, for the gossip trial."""
        from .quest_dialog_planning import dialog_recipient
        guid = str((dialog_recipient(state) or {}).get("guid") or "")
        for quest_id, guids in self.talked.items():
            if guid and guid in guids:
                return {"guid": guid, "quest_id": quest_id}
        return None

    def suppress_area_returns(self, proposals: list, state: dict) -> list:
        """While the ladder works an objective's area, its "go to the area"
        MOVE does not pull the player back to the POI centre between NPCs
        (live 2026-10-31 10:4x, 26209: five returns to the centre)."""
        if not self.areas:
            return proposals
        return [p for p in proposals
                if not (p.skill == "MOVE" and p.parameters.get("purpose") == "LOCATE_QUEST_OBJECTIVE_REGION"
                        and str(p.parameters.get("quest_id")) in self.areas)]

    def propose(self, world, state: dict, now: float) -> list[Proposal]:
        self._rescope(state)
        self.areas = {}
        if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost"):
            return []
        from .quest_poi_evidence import objective_destinations
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if px is None or py is None:
            return []
        for record in getattr(world.quest_model, "records", {}).values():
            if record.current_state != "ACTIVE":
                continue
            for objective in record.objectives:
                if objective.completion_state == "COMPLETE":
                    continue
                mechanism = objective_mechanism(state, record.quest_id, objective)
                if mechanism not in PROBE_MECHANISMS:
                    continue
                self._observe_progress((str(record.quest_id), str(objective.objective_id)), objective)
                key = f"{record.quest_id}:{objective.objective_id}"
                points = objective_destinations(state, self._blobs(world, record, objective, now))
                if not points:
                    try:
                        why = world.query.quest_poi_status(record.quest_id, now)
                    except Exception:
                        why = "unknown"
                    self.diagnostic[key] = f"no_server_objective_poi:{why}"
                    continue
                distance = min(math.hypot(p["x"]-px, p["y"]-py) for p in points)
                if distance > AREA_YARDS:
                    self.diagnostic[key] = f"away_from_poi:{round(distance)}"
                    continue
                self.areas[str(record.quest_id)] = points
                if mechanism == "WITNESS":
                    # Only listening (and the quest's own item) for a watched
                    # scene; no gossip/object probes, no exhaustion here.
                    proposal = (self._item_probe(state, str(record.quest_id), objective, now, points)
                                or self._listen_probe(state, str(record.quest_id), objective, points, now))
                else:
                    proposal = self._probe(state, str(record.quest_id), objective, points, now)
                if proposal is not None:
                    return [proposal]
        return []

    OBJECT_PRESS_YARDS = 3.5

    def _object_probe(self, state: dict, quest_id: str, objective, points, now: float) -> Proposal | None:
        """P8.1 rest: once the local NPCs are tried, each game object at the POI
        the server marks usable for us (Activate flag) is used once (F7 on the
        exact server GUID, rechecked by the identity guard)."""
        from .packet_entity_facts import best_position, server_object_interactable
        player = state.get("player_world_position") or {}
        px, py = float(player["x"]), float(player["y"])
        used = self.__dict__.setdefault("used_objects", {}).setdefault(quest_id, {})
        objects = []
        for value in (state.get("packet_entities") or {}).values():
            if not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed"):
                continue
            guid = str(value.get("guid") or "")
            started = used.get(guid)
            if not guid or (started is not None and now-started >= TALK_SECONDS):
                continue
            point = best_position(value)
            if (point is None or str(point.get("instance_id")) != str(player.get("instance_id"))
                    or min(math.hypot(point["x"]-p["x"], point["y"]-p["y"]) for p in points) > CANDIDATE_YARDS
                    or not server_object_interactable(state, guid)):
                continue
            objects.append((math.hypot(point["x"]-px, point["y"]-py), guid, value, point))
        if not objects:
            return None
        distance, guid, value, point = min(objects, key=lambda row: row[0])
        self.diagnostic[f"{quest_id}:{objective.objective_id}"] = f"probing_objects:{len(objects)}"
        common = {"quest_ids": [quest_id], "objective_id": str(objective.objective_id),
                  "object_id": value.get("entry_id"), "probe": "OBJECTIVE_OBJECT_PROBE"}
        if distance <= self.OBJECT_PRESS_YARDS and (state.get("movement") or {}).get("moving") is not True:
            used.setdefault(guid, now)
            return Proposal.make(
                "OBJECT_USE", "Ismeretlen kredit-forrás: a POI használható tárgya (szerver: Activate), F7",
                {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
                 "object_guid": guid, **common},
                confidence=.6, priority=PRIORITY, evidence=("server_objective_poi", "server_usable_object"))
        return Proposal.make(
            "MOVE", "Ismeretlen kredit-forrás: a POI használható tárgyához megyek",
            {"x": point["x"], "y": point["y"], "z": point.get("z"), "z_known": point.get("z") is not None,
             "z_source": "PACKET_GAMEOBJECT", "coordinate_space": "WORLD_YARDS",
             "instance_id": point["instance_id"], "map_id": state.get("map_id"),
             "purpose": "OBJECTIVE_OBJECT_PROBE_APPROACH", "require_navmesh": True,
             "stop_distance": 2., "face_on_arrival": True, "server_entity_guid": guid,
             "quest_id": quest_id, **common},
            confidence=.6, priority=PRIORITY, evidence=("server_objective_poi", "server_usable_object"))

    def _special_item(self, state: dict, quest_id: str) -> dict | None:
        """The quest log's own special item when the client DB2 resolves it as
        a self-cast use (no unit or ground target to guess)."""
        quest = next((q for q in state.get("active_quests") or () if isinstance(q, dict)
                      and str(q.get("quest_id")) == quest_id), None)
        item_id = number(((quest or {}).get("special_item") or {}).get("item_id"))
        if item_id is None:
            return None
        cache = self.__dict__.setdefault("item_profiles", {})
        if item_id not in cache:
            try:
                if self.__dict__.get("supplement") is None:
                    from wowbot.quests.client_supplement import ClientSupplement
                    self.supplement = ClientSupplement()
                value = self.supplement._query("item", int(item_id)) or {}
            except Exception:
                value = {}
            uses = [u for u in value.get("uses") or () if u.get("status") == "RESOLVED"]
            cache[item_id] = uses[0] if len(uses) == 1 else None
        use = cache[item_id]
        if not use or use.get("target_mode") != "SELF":
            return None
        return {"item_id": int(item_id), "spell_id": use.get("spell_id")}

    ITEM_USE_YARDS = 12.        # used near the POI area's centre ("at the back of the mine")

    def _item_probe(self, state: dict, quest_id: str, objective, now: float, points=()) -> Proposal | None:
        """Live 2026-11-02 (26228 "Livin' the Life"): "Use Two-Shoed Lou's Old
        House at the back of the Jangolode Mine" -- the house is the quest's
        special item (self-cast "Summon Lou's House"); TDB has no objective
        row, so the ladder only looked for NPCs and objects.  At the POI the
        quest's own self-cast item is tried first, once per round, by the
        existing bag right-click; only credit verifies it."""
        item = self._special_item(state, quest_id)
        used = self.__dict__.setdefault("used_items", {})
        if item is None or quest_id in used:
            return None
        bag = next((i for i in (state.get("inventory") or {}).get("items") or ()
                    if isinstance(i, dict) and i.get("item_id") == item["item_id"]
                    and i.get("is_locked") is not True), None)
        if bag is None:
            # Live 2026-11-02 17:15: right after start the bags were not read
            # yet, the ladder called itself exhausted and told the user.
            from .collection_coverage import inventory_ready
            if not inventory_ready(state) or not (state.get("inventory") or {}).get("items"):
                return Proposal.make("WAIT", "Ismeretlen kredit-forrás: a táska adataira várok a quest tárgyához",
                                     {"reason": "objective_item_probe_waiting_inventory", "quest_id": quest_id,
                                      "waiting_for": ["INVENTORY"]}, priority=PRIORITY-1)
            return None
        common = {"quest_ids": [quest_id], "objective_ids": [str(objective.objective_id)],
                  "item_id": item["item_id"], "item_target_mode": "SELF", "target_required": False,
                  "purpose": "OBJECTIVE_ITEM_PROBE", "probe": "OBJECTIVE_ITEM_PROBE"}
        player = state.get("player_world_position") or {}
        if points:
            cx = sum(p["x"] for p in points)/len(points)
            cy = sum(p["y"] for p in points)/len(points)
            if math.hypot(cx-float(player["x"]), cy-float(player["y"])) > self.ITEM_USE_YARDS:
                return Proposal.make(
                    "MOVE", "Ismeretlen kredit-forrás: a quest tárgyát a POI-terület közepén használom",
                    {"x": cx, "y": cy, "z_known": False, "coordinate_space": "WORLD_YARDS",
                     "instance_id": player.get("instance_id"), "map_id": state.get("map_id"),
                     "purpose": "OBJECTIVE_ITEM_PROBE_APPROACH", "require_navmesh": True,
                     # Live 2026-11-02 17:15: aimed 4 yd from the centre, the
                     # walk stalled 5.6 yd away inside the mine for 40 s; the
                     # use is fine anywhere within ITEM_USE_YARDS.
                     "stop_distance": self.ITEM_USE_YARDS-2.,
                     "quest_id": quest_id, "objective_id": str(objective.objective_id)},
                    confidence=.6, priority=PRIORITY+1, evidence=("server_objective_poi", "quest_special_item_self_cast"))
        if state.get("bags_open") is not True:
            return Proposal.make("OPEN_BAGS", "Ismeretlen kredit-forrás: a quest saját tárgyát használnám a POI-n",
                                 {**common, "purpose": "QUEST_ITEM"}, priority=PRIORITY+1,
                                 evidence=("server_objective_poi", "quest_special_item_self_cast"))
        if not (bag.get("coordinate_space") == "CLIENT_BOTTOM_LEFT"
                and all(number(bag.get(k)) is not None and 0 < number(bag[k]) < 1 for k in ("x", "y"))):
            return None
        used[quest_id] = now
        self.diagnostic[f"{quest_id}:{objective.objective_id}"] = f"probing_item:{item['item_id']}"
        return Proposal.make(
            "USE_ON_TARGET", "Ismeretlen kredit-forrás: a quest saját tárgya a POI-n (magára ható)",
            {**common, "activation_source": "INVENTORY_COORDINATE",
             **{k: bag[k] for k in ("bag", "slot", "x", "y", "coordinate_space")}},
            confidence=.7, priority=PRIORITY+1, evidence=("server_objective_poi", "quest_special_item_self_cast"))

    LISTEN_YARDS = 5.          # the thugs stand a few yards behind the house: no corner in between
    INDOOR_LISTEN_YARDS = 3.5   # indoors 7 yd can be through a wall (the farmhouse, 26232)
    LISTEN_SECONDS = 20.

    def _named_entries(self, state: dict, quest_id: str, objective) -> set[str]:
        from .quest_reference_matching import reference_objectives
        refs = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(quest_id) or {}
        rows = reference_objectives(quest_id, objective.objective_id, objective.description, refs.get("objectives"))
        row = rows[0] if len(rows) == 1 else {}
        return {str(c["entry"]) for c in row.get("named_creatures") or () if isinstance(c, dict) and c.get("entry")}

    def _listen_probe(self, state: dict, quest_id: str, objective, points, now: float) -> Proposal | None:
        """Live 2026-11-02 (26232 "Eavesdrop on Thugs."): the agent stood in the
        farmhouse at the POI centre; the thugs the text names stood behind it.
        Go within earshot of the objective's named creatures near the POI and
        listen (a bounded hold) for the credit or their conversation."""
        from .packet_entity_facts import best_position, unit_dead
        entries = self._named_entries(state, quest_id, objective)
        if not entries:
            return None
        player = state.get("player_world_position") or {}
        px, py = float(player["x"]), float(player["y"])
        near = []
        for value in (state.get("packet_entities") or {}).values():
            if (not isinstance(value, dict) or value.get("kind") != "CREATURE" or value.get("removed")
                    or str(value.get("entry_id")) not in entries or unit_dead(value)):
                continue
            point = best_position(value)
            if (point is None or str(point.get("instance_id")) != str(player.get("instance_id"))
                    or min(math.hypot(point["x"]-p["x"], point["y"]-p["y"]) for p in points) > CANDIDATE_YARDS):
                continue
            near.append((math.hypot(point["x"]-px, point["y"]-py), str(value["guid"]), point))
        if not near:
            return None
        listened = self.__dict__.setdefault("listened", {})
        started = listened.get(quest_id)
        if started is not None and now-started >= self.LISTEN_SECONDS:
            return None                                   # listened once this round: next probe
        distance, guid, point = min(near)
        key = f"{quest_id}:{objective.objective_id}"
        # User 2026-11-02: inside the house the thugs behind it do not count.
        # Indoors only standing right next to a speaker is earshot; the
        # navmesh walk to it leads out of the building.
        indoors = (state.get("movement") or {}).get("indoors") is True
        earshot = self.INDOOR_LISTEN_YARDS if indoors else self.LISTEN_YARDS
        if distance > earshot:
            self.diagnostic[key] = "approaching_named_speakers"
            return Proposal.make(
                "MOVE", "Ismeretlen kredit-forrás: a feladatban megnevezett NPC-k közelébe megyek (hallgatózás)",
                {"x": point["x"], "y": point["y"], "z": point.get("z"), "z_known": point.get("z") is not None,
                 "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
                 "instance_id": point["instance_id"], "map_id": state.get("map_id"),
                 "purpose": "OBJECTIVE_LISTEN_PROBE_APPROACH", "require_navmesh": True,
                 "stop_distance": max(2., earshot-2.), "server_entity_guid": guid,
                 "quest_id": quest_id, "objective_id": str(objective.objective_id)},
                confidence=.65, priority=PRIORITY+1, evidence=("server_objective_poi", "named_objective_creature"))
        listened.setdefault(quest_id, now)
        self.diagnostic[key] = "listening_to_named_speakers"
        return Proposal.make(
            "WAIT_EVENT", "A megnevezett NPC-k mellett hallgatózom: várom a beszélgetést / a kreditet",
            {"quest_ids": [quest_id], "objective_kind": "WITNESS_PROXIMITY", "objective_text": objective.description,
             "server_entity_guid": guid,
             "wait_seconds": round(max(1., self.LISTEN_SECONDS-(now-listened[quest_id])), 1)},
            confidence=.65, priority=PRIORITY+1, evidence=("server_objective_poi", "named_objective_creature"))

    def _probe(self, state: dict, quest_id: str, objective, points, now: float) -> Proposal | None:
        item = self._item_probe(state, quest_id, objective, now, points)
        if item is not None:
            return item
        listen = self._listen_probe(state, quest_id, objective, points, now)
        if listen is not None:
            return listen
        from .packet_entity_facts import best_position
        from .server_npc_planning import server_npc_interaction_ready
        player = state.get("player_world_position") or {}
        px, py = float(player["x"]), float(player["y"])
        talked = self.talked.setdefault(quest_id, {})
        candidates = []
        for value in (state.get("packet_entities") or {}).values():
            if not isinstance(value, dict) or not _subject(value):
                continue
            guid = str(value.get("guid") or "")
            started = talked.get(guid)
            if not guid or (started is not None and now-started >= TALK_SECONDS):
                continue
            point = best_position(value)
            if (point is None or str(point.get("instance_id")) != str(player.get("instance_id"))
                    or min(math.hypot(point["x"]-p["x"], point["y"]-p["y"]) for p in points) > CANDIDATE_YARDS):
                continue
            candidates.append((math.hypot(point["x"]-px, point["y"]-py), guid, value, point))
        key = (quest_id, str(objective.objective_id))
        self.diagnostic[f"{quest_id}:{objective.objective_id}"] = (
            f"probing:{len(candidates)}_candidates" if candidates else "exhausted")
        if not candidates:
            used = self._object_probe(state, quest_id, objective, points, now)
            if used is not None:
                return used
            self.exhausted.setdefault(key, now)
            return Proposal.make(
                "WAIT", "Ismeretlen kredit-forrás: a POI-n minden helyi NPC-t kipróbáltam, nincs több jelölt",
                {"reason": "objective_probes_exhausted", "quest_id": quest_id,
                 "objective_id": str(objective.objective_id), "probed": sorted(talked),
                 "waiting_for": ["QUEST_PROGRESS_OR_NEW_LOCAL_ACTOR"]}, priority=PRIORITY-1)
        _distance, guid, value, point = min(candidates, key=lambda row: row[0])
        # Live 2026-10-31 10:4x (26209): the homeless stand in a crowd; the
        # client's F7 recipient was often another untried one, so the press
        # for the planned NPC never came.  That recipient is an equally valid
        # subject: talk to it.
        recipient = self._soft_candidate(state, candidates, now)
        ready = recipient is not None
        if ready:
            _distance, guid, value, point = recipient
        common = {"quest_id": quest_id, "objective_id": str(objective.objective_id),
                  "npc_id": value.get("entry_id"), "probe": "OBJECTIVE_TALK_PROBE"}
        if ((ready or server_npc_interaction_ready(state, guid, point))
                and (state.get("movement") or {}).get("moving") is not True):
            talked.setdefault(guid, now)
            return Proposal.make(
                "INTERACT", "Ismeretlen kredit-forrás: helyi NPC megszólítása a quest POI-n (F7)",
                {"activation_source": "SOFT_INTERACT", "soft_guid": guid, "purpose": "OBJECTIVE_TALK_PROBE",
                 "interaction_kind": "TALK", **common},
                confidence=.6, priority=PRIORITY, evidence=("server_objective_poi", "server_gossip_npc"))
        return Proposal.make(
            "MOVE", "Ismeretlen kredit-forrás: a quest POI helyi NPC-jéhez megyek",
            {"x": point["x"], "y": point["y"], "z": point.get("z"), "z_known": point.get("z") is not None,
             "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
             "instance_id": point["instance_id"], "map_id": state.get("map_id"),
             "purpose": "OBJECTIVE_TALK_PROBE_APPROACH", "require_navmesh": True,
             "stop_distance": 3., "face_on_arrival": True, "server_entity_guid": guid, **common},
            confidence=.6, priority=PRIORITY, evidence=("server_objective_poi", "server_gossip_npc"))
