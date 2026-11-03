"""Quest adapter for scene paths stored in the local client-data catalog.

This module resolves quest objectives and route evidence. It does not choose
mounts, issue input, inspect flight state or decide when to take off/land/walk.
"""
from __future__ import annotations

from functools import lru_cache

from .client_catalog import ClientCatalog
from wowbot.agent.models import Proposal, number
from wowbot.navigation.flight_path import FlightPath


def counter_condition(quest_id, objective, minimum):
    quest = {"field": "quest_id", "equals": str(quest_id)}
    select = {"field": "description", "contains": objective["Description"]}
    prefix = ["active_quests", quest, "objectives", select]
    return {"kind": "COUNTER_AT_LEAST", "minimum": minimum, "paths": [
        {"path": ["packet_quest_credits", str(quest_id), str(objective["ObjectID"]), "count"]},
        {"path": [*prefix, "current"]}, {"path": [*prefix, "current_count"]},
        {"path": [*prefix, "description"], "parse": "FRACTION"}]}


def course_path(course):
    """Task data -> generic route contract; no decisions about current motion."""
    point = lambda values: dict(zip(("x", "y", "z"), values[:3]))
    return FlightPath.from_dict({
        "instance_id": course["map_id"], "mode": "SKYRIDING",
        "waypoints": [point(values) for values in course["rings"]], "landing": point(course["target"]),
        "checkpoint_conditions": [counter_condition(course["quest_id"], course["checkpoint_objective"], i+1)
                                  for i in range(len(course["rings"]))],
        "arrival_condition": counter_condition(course["quest_id"], course["arrival_objective"], 1),
    })


class QuestScenePathPolicy:
    def __init__(self, catalog=None):
        self.catalog = catalog or ClientCatalog()

    def propose(self, state):
        if any(state.get(k) is True for k in ("is_dead", "is_ghost", "is_in_combat", "in_vehicle", "on_taxi")):
            return []
        available = self.catalog.courses()
        instance = (state.get("player_world_position") or {}).get("instance_id")
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, dict) or quest.get("is_complete") is True:
                continue
            key = str(quest.get("quest_id"))
            course = available.get(key)
            if course is None or str(course["map_id"]) != str(instance):
                continue
            objective = course["checkpoint_objective"]
            live = [row for row in quest.get("objectives") or () if isinstance(row, dict)
                    and objective["Description"].casefold() in str(row.get("description", "")).casefold()]
            if len(live) != 1:
                continue  # reference geometry cannot invent a current task
            amount = live[0].get("required", live[0].get("required_count"))
            if amount is not None and amount != len(course["rings"]):
                continue
            path = course_path(course)
            destination = {**path.landing, "z_known": True, "z_source": "LOCAL_DB2_PATH",
                           "coordinate_space": "WORLD_YARDS", "instance_id": path.instance_id,
                           "map_id": state.get("map_id"), "quest_id": key,
                           "purpose": "QUEST_SCENE_PATH", "flight_path": path.to_dict(),
                           "stop_distance": path.radius,
                           "route_reference": {"catalog": "client_reference.sqlite3", "path_id": course["path_id"],
                                               "scene_package_id": course["scene_package"],
                                               "association_kind": course["association_kind"]}}
            return [Proposal.make("MOVE", f"Quest pálya: {course['title']}", destination,
                                  confidence=.9, priority=128.,
                                  evidence=("local_client_db2_catalog", "live_quest_objectives"))]
        return []


def scene_counter(name, minimum):
    """The own client's scene trigger count (route_counters, WorldPacketReducer)."""
    return {"kind": "COUNTER_AT_LEAST", "minimum": minimum, "paths": [{"path": ["route_counters", "scene", name]}]}


def scene_course_path(course, instance_id):
    """A running scene's DB2 ring course; checkpoints are its own triggers."""
    point = lambda values: dict(zip(("x", "y", "z"), values[:3]))
    return FlightPath.from_dict({
        "instance_id": int(instance_id), "mode": "SKYRIDING",
        "waypoints": [point(values) for values in course["rings"]], "landing": point(course["target"]),
        "checkpoint_conditions": [scene_counter("checkpoints", i+1) for i in range(len(course["rings"]))],
        "arrival_condition": scene_counter("race_complete", 1),
    })


class SceneCoursePolicy:
    """Fly the ring course of the client scene that runs now (user 2026-10-25).

    No quest-ID binding: the server names the scene package (Ymir), the local
    DB2 catalog gives its ring path (ClientCatalog.scene_course), and the own
    client's "Checkpoint"/"RaceComplete" triggers are the progress.  Any
    other scene (cinematics) or an ambiguous course proposes nothing.
    """

    def __init__(self, catalog=None):
        self.catalog = catalog or ClientCatalog()
        self.last_reason = "no_scene"

    def propose(self, state):
        if any(state.get(k) is True for k in ("is_dead", "is_ghost", "is_in_combat", "in_vehicle", "on_taxi")):
            return []
        scene = state.get("packet_scene") or {}
        position = state.get("player_world_position") or {}
        if scene.get("active") is not True or type(scene.get("package_id")) is not int:
            self.last_reason = "no_active_scene"
            return []
        if scene.get("race_complete"):
            self.last_reason = "scene_course_complete"
            return []
        try:
            instance = int(position.get("instance_id"))
        except (TypeError, ValueError):
            self.last_reason = "no_instance"
            return []
        quests = [q.get("quest_id") for q in state.get("active_quests") or () if isinstance(q, dict)]
        course, self.last_reason = self.catalog.scene_course(
            scene["package_id"], scene.get("start_position") or position, quests)
        if course is None:
            return []
        path = scene_course_path(course, instance)
        destination = {**path.landing, "z_known": True, "z_source": "LOCAL_DB2_PATH",
                       "coordinate_space": "WORLD_YARDS", "instance_id": path.instance_id,
                       "map_id": state.get("map_id"), "purpose": "SCENE_COURSE",
                       "scene_instance_id": scene.get("scene_instance_id"),
                       "flight_path": path.to_dict(), "stop_distance": path.radius,
                       "route_reference": {"catalog": "client_reference.sqlite3", "path_id": course["path_id"],
                                           "scene_package_id": course["scene_package"],
                                           "selection": course["selection"]}}
        return [Proposal.make("MOVE", f"Scene pálya: package {course['scene_package']} / path {course['path_id']}",
                              destination, confidence=.9, priority=130.,
                              evidence=("server_scene", "local_client_db2_catalog"))]


@lru_cache(maxsize=64)
def _default_scene_course(package_id, x, y, quests):
    return ClientCatalog().scene_course(package_id, {"x": x, "y": y}, quests)


def active_scene_course(state):
    """(course, reason) of the ring scene running now, from the default DB2
    catalog; memoized per package/start/quests for the control lanes."""
    scene = state.get("packet_scene") or {}
    if scene.get("active") is not True or scene.get("race_complete") or type(scene.get("package_id")) is not int:
        return None, "no_active_scene"
    start = scene.get("start_position") or state.get("player_world_position") or {}
    x, y = number(start.get("x")), number(start.get("y"))
    if x is None or y is None:
        return None, "no_scene_start_position"
    quests = tuple(sorted(int(q["quest_id"]) for q in state.get("active_quests") or ()
                          if isinstance(q, dict) and str(q.get("quest_id", "")).isdigit()))
    return _default_scene_course(scene["package_id"], round(x), round(y), quests)


RETRY_LIMIT = 3                 # failed attempts of one course before it is left alone
RETRY_SOFT_YARDS = 6.5          # the starter as the client's F7 recipient this close
RETRY_INTERACT_SECONDS = 4.


class SceneCourseRetryPolicy:
    """Start a ring course again at the NPC that started it (user 2026-10-25).

    Live 21:06-21:09: after the Skytop race timed out the agent did other
    quests; the "Speak with Celormu" objective stayed 1/1, so nothing named
    the restart.  The packets do: the gossip row picked (Celormu 198040, menu
    29949, option 107284) just before the race scene started is the starter.
    After that scene ended without RaceComplete: walk to the starter, F7, pick
    the same option -- at most RETRY_LIMIT times per course.
    """

    def __init__(self, catalog=None):
        self.catalog = catalog or ClientCatalog()
        self.failures: dict[tuple, set] = {}
        self.pressed_at: dict[str, float] = {}
        self.last_reason = "no_failed_course"

    def propose(self, state):
        failed = state.get("failed_scene_course") or {}
        starter = failed.get("starter") or {}
        now = number(state.get("monotonic_time"))
        if (not failed or not starter or now is None or (state.get("packet_scene") or {}).get("active")
                or any(state.get(k) is True for k in ("is_dead", "is_ghost", "is_in_combat", "in_vehicle", "on_taxi"))):
            self.last_reason = "no_failed_course"
            return []
        course, reason = self.catalog.scene_course(failed.get("package_id"), failed.get("start_position") or {}, [
            q.get("quest_id") for q in state.get("active_quests") or () if isinstance(q, dict)])
        if course is None:
            self.last_reason = f"not_a_ring_course:{reason}"
            return []
        failures = self.failures.setdefault((failed.get("package_id"), starter.get("entry_id")), set())
        failures.add(failed.get("scene_instance_id"))
        if len(failures) > RETRY_LIMIT:
            self.last_reason = "retry_limit"
            return []
        option = self._listed_option(state, starter)
        if option is not None:
            self.last_reason = "select_starter_option"
            return [Proposal.make(
                "QUEST_DIALOG", "Scene pálya újraindítása: az indító NPC ugyanazon gossip-sora",
                {"action": "GOSSIP_OPTION_SELECT", "x": number(option["x"]), "y": number(option["y"]),
                 "target_guid": (state.get("target") or {}).get("guid"),
                 "gossip_option_id": int(starter["gossip_option_id"]),
                 "gossip_option_name": str(option.get("name") or ""), "gossip_transition": "SCENE_START",
                 "scene_package_id": failed.get("package_id")},
                confidence=.9, priority=119, evidence=("server_scene", "scene_starter_gossip"))]
        npc = self._starter(state, starter)
        if npc is None:
            self.last_reason = "starter_not_in_server_view"
            return []
        guid, point, distance = npc
        soft = next((row for row in state.get("soft_targets") or ()
                     if isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
        pressed = self.pressed_at.get(guid)
        if (soft is not None and str(soft.get("guid") or "") == guid and distance <= RETRY_SOFT_YARDS
                and (pressed is None or now-pressed >= RETRY_INTERACT_SECONDS)):
            self.pressed_at[guid] = now
            self.last_reason = "interact_starter"
            return [Proposal.make(
                "INTERACT", "Scene pálya újraindítása: az indító NPC előttem (soft-interact): F7",
                {"activation_source": "SOFT_INTERACT", "soft_guid": guid, "npc_id": starter.get("entry_id"),
                 "purpose": "SCENE_COURSE_RETRY", "interaction_kind": "TALK"},
                confidence=.9, priority=107, evidence=("server_scene", "scene_starter_soft_interact"))]
        self.last_reason = "approach_starter"
        return [Proposal.make(
            "MOVE", "Scene pálya újraindítása: odamegyek az indító NPC-hez",
            {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True, "z_source": "PACKET_ENTITY",
             "coordinate_space": "WORLD_YARDS", "instance_id": point["instance_id"], "map_id": state.get("map_id"),
             "purpose": "SCENE_COURSE_RETRY", "require_navmesh": True, "stop_distance": 3.0,
             "face_on_arrival": True, "server_entity_guid": guid, "npc_id": starter.get("entry_id")},
            confidence=.85, priority=107, evidence=("server_scene", "scene_starter_position"))]

    @staticmethod
    def _starter(state, starter):
        """(guid, point, distance) of the starter NPC: its GUID, else the
        nearest unit of the same entry (a respawn has a new GUID)."""
        from wowbot.agent.packet_entity_facts import best_position
        from wowbot.agent.server_npc_planning import server_npc_distance
        rows = []
        for value in (state.get("packet_entities") or {}).values():
            if (not isinstance(value, dict) or value.get("removed")
                    or (str(value.get("guid")) != str(starter.get("guid"))
                        and value.get("entry_id") != starter.get("entry_id"))):
                continue
            point = best_position(value)
            distance = server_npc_distance(state, point) if point is not None else None
            if distance is not None:
                rows.append((str(value.get("guid")) != str(starter.get("guid")), distance, str(value["guid"]), point))
        if not rows:
            return None
        _other, distance, guid, point = min(rows, key=lambda row: row[:3])
        return guid, point, distance

    @staticmethod
    def _listed_option(state, starter):
        """The starter's gossip row, when its dialog is open."""
        ui = state.get("quest_ui") or {}
        if ui.get("open") is not True and state.get("quest_ui_open") is not True:
            return None
        target = state.get("target") or {}
        if (str(target.get("guid") or "") != str(starter.get("guid"))
                and number(target.get("npc_id")) != starter.get("entry_id")):
            return None
        for option in ui.get("gossip_options") or ():
            if not isinstance(option, dict):
                continue
            x, y = number(option.get("x")), number(option.get("y"))
            if (number(option.get("id")) == starter.get("gossip_option_id") and option.get("available") is not False
                    and x is not None and y is not None and 0 < x < 1 and 0 < y < 1):
                return option
        return None
