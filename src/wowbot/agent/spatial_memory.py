"""Connect the existing identity and map-point stores, without mixing their roles."""
from __future__ import annotations
import time
import math
from .models import number
from wowbot.vision.entity_memory import EntityMemory
from wowbot.vision.world_point_memory import WorldPointMemory
from wowbot.vision.map_mouseover import normalize_map_mouseover


class SpatialMemory:
    def __init__(self, directory):
        self.entities = EntityMemory(directory / "entity_memory.sqlite3")
        self.points = WorldPointMemory(directory / "world_point_memory.sqlite3")
        self.seen = {}
        self.locations = []
        self.last_query = 0.
        self.context = None
        self.marker_observations = []
        self._spawn_key = None
        self._spawn_candidates = []
        self._quest_role_key = None
        self._quest_role_candidates = []

    def spawn_reference(self, state):
        from .spawn_catalog import candidates
        player = state.get("player_world_position") or {}
        target = state.get("target") or {}
        # UnitPosition's instance/map coordinate context is NOT the UI map ID.
        key = (player.get("instance_id"), target.get("npc_id"))
        if key != self._spawn_key:
            self._spawn_key = key
            self._spawn_candidates = candidates(*key) if all(v is not None for v in key) else []
        px, py = number(player.get("x")), number(player.get("y"))
        rows = [{**row, "distance_yards": math.hypot(row["x"]-px, row["y"]-py)
                 if px is not None and py is not None else None}
                for row in self._spawn_candidates]
        return {"world_map_id": key[0], "npc_id": key[1],
                "target_guid": target.get("guid"), "candidates": rows,
                "status": "REFERENCE_REQUIRES_LIVE_VALIDATION" if rows else "NO_REFERENCE",
                "navigation_enabled": False,
                "fallback_policy": "SELECTED_NPC_LOCAL_UNIQUE_AFTER_MAP_UNAVAILABLE_OR_FAILED"}

    def quest_role_reference(self, state, role="QUEST_STARTER"):
        """Nearby TDB role/location hypotheses for identity-free last fallback.

        Phase variants at effectively the same location are deliberately
        clustered: reaching a region does not assert which NPC is present.
        """
        from .spawn_catalog import quest_role_candidates
        player = state.get("player_world_position") or {}
        world_map_id = player.get("instance_id")
        key = (world_map_id, role)
        if key != self._quest_role_key:
            self._quest_role_key = key
            self._quest_role_candidates = quest_role_candidates(world_map_id, role) if world_map_id is not None else []
        px, py, pz = (number(player.get(axis)) for axis in ("x", "y", "z"))
        if None in (px, py, pz):
            return {"candidates": [], "status": "NO_PLAYER_WORLD_POSITION"}
        phase = state.get("phase")
        nearby = []
        for row in self._quest_role_candidates:
            x, y, z = (number(row.get(axis)) for axis in ("x", "y", "z"))
            row_phase = (row.get("context") or {}).get("PhaseId")
            if (None in (x, y, z) or not all(math.isfinite(v) for v in (x, y, z))
                    or math.hypot(x-px, y-py) > 120 or abs(z-pz) > 15
                    or phase is not None and str(row_phase) not in {"0", str(phase)}):
                continue
            nearby.append({**row, "distance_yards": math.hypot(x-px, y-py)})
        clusters = self.cluster_locations(
            sorted(nearby, key=lambda item: item["distance_yards"]),
            extra_fields={"npc_ids": "npc_id", "spawn_ids": "spawn_id"},
            list_union_fields={"quest_ids": "quest_ids"},
            base_fields={"role_hypothesis": role, "identity_confirmed": False,
                        "location_kind": "TDB_ROLE_LOCATION_HYPOTHESIS"})
        return {"world_map_id": world_map_id, "role": role, "candidates": clusters,
                "status": "REFERENCE_REQUIRES_LIVE_VALIDATION" if clusters else "NO_REFERENCE",
                "navigation_enabled": False,
                "fallback_policy": "ONLY_AFTER_WORLD3D_AND_WORLD_MAP_EXHAUSTED"}

    def get_candidate_locations(self, map_id=None, *, as_of=None, max_age=86400):
        """DESIGN-080: real stored WORLD_MAP inspection points for `map_id`.

        Thin, side-effect-free read over `WorldPointMemory` -- the same
        store `ingest()` already populates and queries into `self.locations`,
        exposed here as a directly callable query independent of the
        ingest/poll cadence.
        """
        return self.points.points(map_id, as_of=as_of, max_age=max_age)

    @staticmethod
    def cluster_locations(rows, *, xy_radius=1.0, z_radius=2.0,
                          extra_fields=None, list_union_fields=None, base_fields=None):
        """DESIGN-080: merge nearby location rows into position clusters.

        Rows within `xy_radius` (map/world units) and `z_radius` of an
        existing cluster's anchor row are folded into it rather than kept as
        separate candidates -- extracted from the clustering `quest_role_reference()`
        already performed inline, now reusable and independently testable.
        `extra_fields` (cluster_key -> source_field) collects that source
        field from every merged row into a list on the cluster; `list_union_fields`
        does the same but flattens+dedupes list-valued source fields;
        `base_fields` are merged onto a newly created cluster only.
        """
        extra_fields = extra_fields or {}
        list_union_fields = list_union_fields or {}
        clusters: list[dict] = []
        for row in rows:
            x, y = row.get("x"), row.get("y")
            z = row.get("z")
            cluster = next((item for item in clusters
                            if math.hypot(item["x"]-x, item["y"]-y) <= xy_radius
                            and (z is None or item.get("z") is None or abs(item["z"]-z) <= z_radius)), None)
            if cluster is None:
                cluster = {**row, **{key: [] for key in extra_fields}, **{key: [] for key in list_union_fields},
                          **(base_fields or {})}
                clusters.append(cluster)
            for cluster_key, source_field in extra_fields.items():
                cluster[cluster_key].append(row.get(source_field))
            for cluster_key, source_field in list_union_fields.items():
                cluster[cluster_key] = list(dict.fromkeys(cluster[cluster_key] + list(row.get(source_field) or ())))
        return clusters

    @staticmethod
    def reliability_score(row, *, now=None, max_age=86400.) -> float:
        """DESIGN-080: bounded [0,1] reliability from real repeat-observation
        and recency signals already stored per point (`seen_count`/`last_seen`
        from `WorldPointMemory`) -- more independent sightings and a more
        recent sighting both raise reliability; nothing here is invented
        beyond those two stored counters.
        """
        seen_count = max(1, int(row.get("seen_count") or 1))
        repetition = min(1.0, 0.3 + 0.15 * (seen_count - 1))
        last_seen = row.get("last_seen")
        if last_seen is None:
            return round(repetition, 4)
        reference = now if now is not None else time.time()
        age = max(0.0, float(reference) - float(last_seen))
        recency = max(0.0, 1.0 - min(1.0, age / max(1e-9, float(max_age))))
        return round(repetition * (0.5 + 0.5 * recency), 4)

    def ingest(self, state, now, probe=None, *, learn_only=False):
        context = (state.get("session_id"), state.get("map_id"))
        if context != self.context:
            self.context = context
            self.seen.clear()
            self.locations = []
            self.marker_observations = []
            self.last_query = -100
        wall = time.time()
        mouse = state.get("mouseover") or {}
        guid = mouse.get("guid")
        if guid and now-self.seen.get(guid, -100) > 2:
            position = mouse.get("world_position") or {}
            self.entities.record_mouseover(mouse,
                map_id=position.get("map_id", state.get("map_id")),
                map_x=number(position.get("x")), map_y=number(position.get("y")),
                zone=state.get("zone_name"), observed_at=wall, phase=state.get("phase"),
                instance_id=state.get("instance_id"),
                quest_revision=state.get("quest_state_revision"), observation_id=state.get("frame_id"))
            self.seen[guid] = now
        # A visual appearance is learned only when the cursor is still at the
        # inspected 3D track and addon mouseover provides an explicit identity.
        cursor = state.get("cursor_position") or {}
        cursor_x, cursor_y = number(cursor.get("nx")), number(cursor.get("ny"))
        if (probe and probe.get("source") == "WORLD3D" and guid
                and cursor_x is not None and cursor_y is not None
                and number(probe.get("x")) is not None and number(probe.get("y")) is not None
                and math.hypot(cursor_x-probe["x"], cursor_y-probe["y"]) <= .015
                and probe.get("visual_signature")):
            identity_key = self.entities.identity_key(mouse)
            visual_key = f"visual:{identity_key}:{probe['visual_signature'].get('signature_id')}"
            if identity_key and now-self.seen.get(visual_key, -100) > 2:
                previous = self.entities.recognize_visual(probe["visual_signature"])
                for candidate in previous:
                    if candidate["identity_key"] != identity_key:
                        self.entities.record_visual_outcome(candidate["identity_key"],
                                                            probe["visual_signature"], False, wall)
                self.entities.record_visual_outcome(identity_key, probe["visual_signature"], True, wall)
                self.seen[visual_key] = now
        # Fast telemetry can carry a simultaneous cursor/GUID label at a much
        # higher rate than a complete addon state. In that case the caller
        # requests only the bounded identity/appearance update above; map
        # memory, fallback searches and other full-state work must wait.
        if learn_only:
            return self.locations
        raw = state.get("map_mouseover") or {}
        raw = dict(raw)  # Preserve the original addon observation unchanged.
        x, y = cursor_x, cursor_y
        source_surface = {"MINIMAP_CV": "MINIMAP", "WORLD_MAP_CV": "WORLD_MAP"}
        associated = (probe and source_surface.get(probe.get("source")) == raw.get("surface")
                      and raw.get("surface") in {"MINIMAP", "WORLD_MAP"}
                      and x is not None and y is not None
                      and number(probe.get("x")) is not None and number(probe.get("y")) is not None
                      and math.hypot(x-probe["x"], y-probe["y"]) <= .015)
        # A minimap appearance may be associated only while the cursor is on
        # that exact tracked marker and addon mouseover identifies a unit.  It
        # is stored in a separate representation space inside the signature,
        # so a map icon cannot collide with a 3D body crop.
        map_unit = raw.get("unit") or {}
        map_identity = self.entities.identity_key(map_unit)
        if associated and map_identity and probe.get("visual_signature"):
            map_identity = self.entities.record_mouseover(
                map_unit, map_id=raw.get("map_id", state.get("map_id")),
                map_x=None, map_y=None, zone=state.get("zone_name"), observed_at=wall,
                phase=state.get("phase"), instance_id=state.get("instance_id"),
                quest_revision=state.get("quest_state_revision"), observation_id=state.get("frame_id"))
            visual_key = f"visual:minimap:{map_identity}:{probe['visual_signature'].get('signature_id')}"
            if now-self.seen.get(visual_key, -100) > 2:
                previous = self.entities.recognize_visual(probe["visual_signature"])
                for candidate in previous:
                    if candidate["identity_key"] != map_identity:
                        self.entities.record_visual_outcome(candidate["identity_key"],
                                                            probe["visual_signature"], False, wall)
                self.entities.record_visual_outcome(map_identity, probe["visual_signature"], True, wall)
                self.seen[visual_key] = now
        if associated and raw.get("tooltip"):
            detector_kind = probe.get("detector_kind") or probe.get("kind")
            if detector_kind:
                semantic = raw.get("semantic_type") or "UNKNOWN"
                observation = {"surface": raw["surface"], "map_id": raw.get("map_id"),
                               "tooltip": raw["tooltip"], "quest_id": raw.get("quest_id"),
                               "unit": raw.get("unit"), "semantic_type": semantic,
                               "semantic_hypothesis": "UNKNOWN", "detector_kind": detector_kind,
                               "source": "CV_MARKER_AND_ADDON_TOOLTIP", "confirmed": semantic != "UNKNOWN",
                               "observed_at": now, "local_x": raw.get("local_x"), "local_y": raw.get("local_y")}
                self.marker_observations = [m for m in self.marker_observations
                                            if (m["surface"], m["tooltip"]) != (observation["surface"], observation["tooltip"])]
                self.marker_observations.append(observation)
        self.marker_observations = [m for m in self.marker_observations if now-m["observed_at"] <= 60][-32:]
        point = normalize_map_mouseover(raw)
        inside_map_content = bool(
            point and number(point.x) is not None and number(point.y) is not None
            and .015 < point.x < .985 and .015 < point.y < .985)
        if (point and point.surface == "WORLD_MAP" and inside_map_content
                and point.semantic_type != "UNKNOWN" and point.tooltip):
            unit = raw.get("unit") or {}
            key = self.points.point_key(point, name=unit.get("name"), npc_id=unit.get("npc_id"))
            if key and now-self.seen.get(key, -100) > 2:
                self.points.record(point, name=unit.get("name"), npc_id=unit.get("npc_id"), observed_at=wall,
                    provenance={"source": "ADDON_MAP_MOUSEOVER", "quest_id": raw.get("quest_id"),
                        "semantic_source": raw.get("semantic_source") or "TOOLTIP_INTERPRETATION",
                        "coordinate_source": raw.get("coordinate_source") or "MAP_CURSOR",
                        "track_id": probe.get("track_id") if associated else None,
                        "marker_associated": bool(associated), "frame_id": state.get("frame_id"),
                        "session_id": state.get("session_id"), "observed_monotonic": now})
                self.seen[key] = now
                self.last_query = -100  # Expose a new waypoint before closing the map.
        if now-self.last_query > 2:
            self.locations = [{**p, "source": "WORLD_POINT_MEMORY", "confirmed": False, "confidence": .65}
                              for p in self.points.points(state.get("map_id"), as_of=wall, max_age=86400)]
            self.last_query = now
        return self.locations
