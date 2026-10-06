"""Measured-route adapter around the rebuild's shared RoutePlanner.

No path is declared traversable merely because a quest pin points through it.
Only successful, short observed movement segments enter the route graph.
"""
from __future__ import annotations

import math
from wowbot.navigation.graph import NavGraph, NavGraphNode
from wowbot.navigation.planner import RoutePlanner, NoRouteError
from wowbot.vision.models import WorldPosition
from .models import number
from .models import canonical
import hashlib


DESTINATION_RETRY_COOLDOWN_SECONDS = 5.0
# ~4 yd on a zone map: the player must actually have walked this much without
# getting closer before a destination counts as "circling".
STALL_TRAVEL_MAP_UNITS = .004


class AgentNavigator:
    def __init__(self):
        self.graphs = {}
        self.progress = {}
        # key -> (last player position, map distance travelled since the
        # last progress mark).
        self.progress_motion = {}
        self.last_route = []
        self.blocked = {}
        self.obstacle_trials = {}
        self.obstacle_claims = {}
        self.topology = {}

    @staticmethod
    def _position(state):
        pos = state.get("position") or {}
        x, y = number(pos.get("x")), number(pos.get("y"))
        return WorldPosition(x, y) if x is not None and y is not None else None

    def observe_verified_move(self, before, after, destination=None):
        a, b = self._position(before), self._position(after)
        map_id = before.get("map_id")
        if not a or not b or map_id is None or map_id != after.get("map_id"):
            return
        distance = math.hypot(a.x-b.x, a.y-b.y)
        if not .00008 < distance < .01:
            return  # Ignore teleport/loading/other non-local transitions.
        # A verified move only refutes the obstacle hypothesis for the attempted
        # destination/heading. A sideways RECOVER pulse must not erase evidence
        # collected for the still-blocked forward corridor, and success on one
        # route must not clear unrelated routes on the same map.
        path_key = self._path_key(before, destination) if destination else None
        if path_key is not None:
            self.obstacle_trials.pop(path_key, None)
            self.obstacle_claims.pop(path_key, None)
        graph = self.graphs.setdefault(map_id, NavGraph())
        keys = []
        for pos in (a, b):
            key = f"{pos.x:.5f}:{pos.y:.5f}"
            graph.add_node(NavGraphNode(key, pos, confidence=.8))
            keys.append(key)
        edge_id = ":".join(keys)
        if edge_id not in graph.edges:
            # A walked edge is only evidence for that direction (ledges exist).
            from wowbot.navigation.graph import NavGraphEdge
            graph.add_edge(NavGraphEdge(edge_id, keys[0], keys[1], distance, distance, confidence=.8), bidirectional=False)
        topology_id = hashlib.sha256(f"{map_id}:{edge_id}".encode()).hexdigest()[:24]
        self.topology[topology_id] = {"feature_id": topology_id, "map_id": map_id,
            "type": "TRAVERSED_SEGMENT", "status": "SUPPORTED", "confidence": .8,
            "geometry": {"from": {"x": a.x, "y": a.y}, "to": {"x": b.x, "y": b.y}},
            "evidence": tuple(filter(None, (before.get("frame_id"), after.get("frame_id")))),
            "last_seen": after.get("monotonic_time")}

    def observe_topology(self, state, observation_id, now):
        allowed = {"AREA", "ROAD", "BUILDING", "ENTRANCE", "STAIRS", "PORTAL",
                   "QUEST_HUB", "NPC_CLUSTER", "RESOURCE_AREA"}
        changed = []
        for raw in state.get("topology_observations", []):
            kind = str(raw.get("type") or "UNKNOWN").upper()
            geometry = raw.get("geometry") or {key: raw.get(key) for key in ("x", "y", "bounds") if raw.get(key) is not None}
            if kind not in allowed or not geometry:
                continue
            feature_id = hashlib.sha256(canonical({"map": state.get("map_id"), "type": kind,
                                                    "geometry": geometry}).encode()).hexdigest()[:24]
            old = self.topology.get(feature_id)
            evidence = list(old.get("evidence", ())) if old else []
            if observation_id not in evidence:
                evidence.append(observation_id)
            trusted_source = raw.get("source") in {"ADDON_TELEMETRY", "VERIFIED_TRAVERSAL", "USER_CONFIG"}
            status = "CONFIRMED" if trusted_source and raw.get("confirmed") is True else (
                "SUPPORTED" if trusted_source and len(evidence) >= 3 else "HYPOTHESIS")
            feature = {"feature_id": feature_id, "map_id": state.get("map_id"), "type": kind,
                       "status": status, "confidence": min(1., number(raw.get("confidence")) or
                       (1. if status == "CONFIRMED" else .5 if status == "SUPPORTED" else .25)),
                       "geometry": geometry, "source": raw.get("source") or "UNKNOWN",
                       "evidence": tuple(evidence[-20:]), "last_seen": now}
            self.topology[feature_id] = feature
            if not old or old["status"] != status:
                changed.append(feature)
        return changed

    @staticmethod
    def _path_key(state, destination):
        pos = AgentNavigator._position(state)
        if not pos or destination.get("map_id") != state.get("map_id"):
            return None
        heading = round(math.atan2(destination["y"]-pos.y, destination["x"]-pos.x)/(math.pi/4)) % 8
        return (state.get("map_id"), round(pos.x, 3), round(pos.y, 3), heading)

    def observe_failed_move(self, before, after, destination, observation_id, now):
        key = self._path_key(before, destination)
        if key is None or before.get("map_id") != after.get("map_id"):
            return None
        a, b = self._position(before), self._position(after)
        if not a or not b or math.hypot(a.x-b.x, a.y-b.y) > .00008:
            return None
        hypotheses = [item for item in after.get("visual_candidates", [])
                      if item.get("source") == "WORLD3D"
                      and (item.get("detector_kind") or item.get("kind")) == "obstacle_candidate"
                      and (number(item.get("confidence")) or 0) >= .65
                      and (number(item.get("stable_frames")) or 0) >= 3
                      and .32 <= (number(item.get("x")) if number(item.get("x")) is not None else -1) <= .68]
        # V5 M4.8's temporal traversability belief is intentionally consumed
        # only after an independently observed no-progress movement attempt.
        # It never causes a direct input or an instant replan on one frame.
        hypotheses.extend(self._frontal_traversability_hypotheses(after))
        if not hypotheses:
            return None
        trial = self.obstacle_trials.setdefault(key, {"observations": [], "tracks": [], "first_seen": now})
        if observation_id not in trial["observations"]:
            trial["observations"].append(observation_id)
            trial["tracks"].extend(item.get("track_id") for item in hypotheses if item.get("track_id"))
        if len(trial["observations"]) >= 3:
            claim = {"path_key": key, "status": "SUPPORTED", "confidence": min(.9, .5+.1*len(trial["observations"])),
                     "evidence": tuple(trial["observations"][-10:]),
                     "track_ids": tuple(dict.fromkeys(trial["tracks"])), "expires": now+60}
            self.obstacle_claims[key] = claim
            return claim
        return {"path_key": key, "status": "HYPOTHESIS", "confidence": .3,
                "evidence": tuple(trial["observations"]), "expires": now+15}

    @staticmethod
    def _frontal_traversability_hypotheses(state):
        local = state.get("local_traversability") or {}
        if local.get("schema") != "WORLD3D_TRAVERSABILITY_V5":
            return []
        result = []
        for sector in local.get("sectors") or ():
            if sector.get("sector") not in {"CENTER_LEFT", "CENTER", "CENTER_RIGHT"}:
                continue
            if sector.get("state") != "BLOCKED" or sector.get("obstacle_lifecycle") != "CONFIRMED":
                continue
            confidence = number(sector.get("obstacle_confidence")) or 0.
            if confidence < .65:
                continue
            result.append({"source": "WORLD3D_TRAVERSABILITY", "kind": "traversability_block",
                           "track_id": f"traversability:{sector.get('sector')}",
                           "confidence": confidence, "stable_frames": 3, "x": .5,
                           "evidence_refs": tuple(sector.get("evidence") or ())})
        return result

    def path_obstacle(self, world, destination, now):
        key = self._path_key(world.state, destination)
        claim = self.obstacle_claims.get(key)
        if claim and claim["expires"] >= now:
            return claim
        if claim:
            self.obstacle_claims.pop(key, None)
        return None

    def waypoint(self, world, destination):
        graph = self.graphs.get(world.state.get("map_id"))
        start = self._position(world.state)
        self.last_route = []
        if not graph or not start:
            return destination
        finish = WorldPosition(destination["x"], destination["y"])
        nearest_start, nearest_end = graph.nearest_node(start), graph.nearest_node(finish)
        if math.hypot(nearest_start.position.x-start.x, nearest_start.position.y-start.y) > .003 or math.hypot(nearest_end.position.x-finish.x, nearest_end.position.y-finish.y) > .003:
            return destination
        try:
            route = RoutePlanner(graph).plan(start, finish)
        except NoRouteError:
            return destination
        self.last_route = list(route.node_ids)
        points = [(node_id, graph.nodes[node_id].position) for node_id in route.node_ids]
        # Remove only near-collinear interior points on already measured route
        # edges. This smooths harmless sampling noise without inventing an
        # unobserved shortcut through a corner or obstacle.
        smoothed = []
        for item in points:
            smoothed.append(item)
            while len(smoothed) >= 3:
                a, b, c = (entry[1] for entry in smoothed[-3:])
                ab, bc = (b.x-a.x, b.y-a.y), (c.x-b.x, c.y-b.y)
                cross = abs(ab[0]*bc[1]-ab[1]*bc[0])
                scale = max(1e-12, math.hypot(*ab)*math.hypot(*bc))
                if cross/scale > .12:
                    break
                smoothed.pop(-2)
        # Look ahead along the smoothed measured polyline instead of steering
        # at every tiny sampled node. The controller still receives only one
        # high-level destination and retains ownership of movement.
        lookahead = .004
        anchor = start
        travelled = 0.
        for node_id, pos in smoothed:
            segment = math.hypot(pos.x-anchor.x, pos.y-anchor.y)
            if segment <= 1e-9:
                anchor = pos
                continue
            if travelled+segment >= lookahead:
                ratio = (lookahead-travelled)/segment
                return {**destination,
                        "x": anchor.x+(pos.x-anchor.x)*ratio,
                        "y": anchor.y+(pos.y-anchor.y)*ratio,
                        "source": "MEASURED_ROUTE_LOOKAHEAD",
                        "route_node_id": node_id}
            travelled += segment
            anchor = pos
        if smoothed:
            node_id, pos = smoothed[-1]
            if math.hypot(pos.x-start.x, pos.y-start.y) > .001:
                return {**destination, "x": pos.x, "y": pos.y,
                        "source": "MEASURED_ROUTE_LOOKAHEAD", "route_node_id": node_id}
        return destination

    def permits(self, world, destination, now):
        key = (world.state.get("map_id"), round(destination["x"], 3), round(destination["y"], 3))
        distance = world.distance(destination)
        if distance is None:
            return False
        if self.path_obstacle(world, destination, now):
            return False
        if self.blocked.get(key, 0) > now:
            return False
        previous = self.progress.get(key)
        position_of = getattr(world, "player_position", None)
        position = position_of() if callable(position_of) else None
        if previous is None or distance < previous[0] - .0003:
            self.progress[key] = (distance, now)
            self.progress_motion[key] = (position, 0.)
            return True
        last, travelled = self.progress_motion.get(key, (position, 0.))
        if position is not None and last is not None:
            travelled += math.hypot(position[0]-last[0], position[1]-last[1])
        self.progress_motion[key] = (position, travelled)
        if position is not None and travelled < STALL_TRAVEL_MAP_UNITS:
            # Live 2026-10-06 09:42: the route was blocked after a 6 s INSPECT
            # with the player standing still.  Standing (INSPECT, combat,
            # loot) is no evidence of circling; restart the window.
            self.progress[key] = (previous[0], now)
            return True
        if now-previous[1] > 12:
            # A lack-of-progress trend is enough to stop blindly repeating
            # this exact route, but it is not proof that the destination is
            # unreachable.  Live logs showed the former 30 s quarantine as
            # repeated 29-30 s passive WAIT periods.  Keep a short bounded
            # cooldown so fresh localization/navmesh/visual evidence can
            # produce another controlled attempt promptly.
            self.blocked[key] = now + DESTINATION_RETRY_COOLDOWN_SECONDS
            self.progress.pop(key, None)
            return False  # Even successful turning arcs cannot circle forever.
        return True

    def retry_at(self, world, destination, now):
        """Return the exact temporary-route retry deadline, if any."""
        key = (world.state.get("map_id"), round(destination["x"], 3),
               round(destination["y"], 3))
        retry = self.blocked.get(key)
        return retry if retry is not None and retry > now else None

    def snapshot(self, now):
        return {"route": list(self.last_route),
                "supported_obstacles": [claim for claim in self.obstacle_claims.values()
                                        if claim["expires"] >= now],
                "blocked_destinations": [list(key) for key, until in self.blocked.items() if until > now],
                "topology": list(self.topology.values())}
