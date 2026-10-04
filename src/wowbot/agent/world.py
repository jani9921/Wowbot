from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Any, Generic, TypeVar

# Preserve the existing call sites and copy-isolation contract while avoiding
# copy.deepcopy's dispatch overhead for ordinary telemetry/vision trees.
# json_copy now lives in models.py so other reducers on the same ingest hot
# path (e.g. world_evidence_reducer.py) can share it too.
from .models import (EventRecord, Observation, Prediction, PredictionError, canonical,
                     json_copy as _json_copy, number)
deepcopy = _json_copy
from .quest_model import QuestModel
from .world_entities import (AppearanceObservation, EntityIdentity, EntityStateObservation,
                             LocationCluster, LocationObservation, RoleObservation)
from .world_query import WorldQuery
from .world_models import Belief, ContradictionRecord, Evidence, WorldRelation


class _BoundedEventRecords(deque):
    """`deque(maxlen=...)` that also tracks member `event_id`s for O(1) dedup.

    Perf fix (offline-profiled 2026-09-22): `_emit_derived_event()`'s
    duplicate check used to linear-scan up to 500 entries on every single
    call (`any(item.event_id == record.event_id for item in
    self.event_records)`); under a churning-track workload this alone cost
    millions of comparisons across a session. `.append()` is the only
    mutator this deque ever receives (from `_emit_derived_event()` and two
    other reducers), so maintaining `.ids` here keeps all three call sites
    correct with no change to them.
    """

    def __init__(self, maxlen: int) -> None:
        super().__init__(maxlen=maxlen)
        self.ids: set[str] = set()

    def append(self, record) -> None:
        if self.maxlen is not None and len(self) == self.maxlen:
            self.ids.discard(self[0].event_id)
        super().append(record)
        self.ids.add(record.event_id)
from .world_snapshot import WorldSnapshotProjection
from .world_event_reducer import WorldEventReducer
from .world_entity_reducer import WorldEntityReducer
from .world_ui_reducer import WorldUiReducer
from .world_evidence_reducer import WorldEvidenceReducer
from .world_addon_reducer import WorldAddonReducer
from .world_state_projection import WorldStateProjector
from .world_anchor_reducer import WorldAnchorReducer
from .world_section_updates import WorldSectionUpdateTracker
from .world_state_contract import WorldStateContract
from .world_trace_graph import WorldTraceGraph
from .world_prediction_runtime import WorldPredictionRuntime
from wowbot.vision.models import MapMarker


RELIABILITY = {"ADDON_TELEMETRY": 1., "MOUSEOVER": 1., "TOOLTIP": .9,
               "ENTITY_MEMORY": .7, "SPATIAL_MEMORY": .7, "SEMANTIC_MEMORY": .7, "WORLD_MAP_CV": .6,
               "MINIMAP_CV": .55, "WORLD3D": .55, "WORLD3D_LOCAL_VIEW": .55, "UI_CV": .58, "VISION": .55,
               "CROSS_VIEW": .55, "AI": .3,
               "QUEST_STATE": 1., "PLAYER_STATE": 1.}

# AIPC5 exports one authoritative state through multiple pixel-strip pages.
# This packet-receipt window does not relax PID/focus/input safety checks in
# the runtime.
ADDON_RECEIVE_FRESH_SECONDS = 6.0
# This is deliberately *not* a liveness limit.  It marks only the paged
# detail projection stale for consumers that require a coherent full page
# (for example camera/map observation verification).
ADDON_DETAIL_STATE_MAX_AGE_SECONDS = 20.0
# In-memory relation graph bound (entries). Every other WorldModel
# collection is a bounded deque; this dict was the last unbounded one and
# grew with every visual track / derived event for the whole session.
MAX_RELATIONS = 20_000
# ``state_age`` belongs to the paged, slow detail snapshot.  It is retained
# as provenance for detail-dependent skills, but must not be a liveness gate:
# a dropped STATE page can leave it growing while the independent FAST lane
# still supplies fresh player presence, position, target, combat, cursor, and
# actionbar data.  Treating that as a disconnect previously stopped FULL_AI
# during a live fight despite packets arriving continuously.  Packet receipt
# and explicit player absence remain the control-safety contract.

SENSOR_TIERS = {
    "GROUND_TRUTH": 4,
    "STRONG": 3,
    "PERCEPTION": 2,
    "REASONING": 1,
    "UNKNOWN": 0,
}
SOURCE_TIERS = {
    "ADDON_TELEMETRY": "GROUND_TRUTH", "MOUSEOVER": "GROUND_TRUTH",
    "TOOLTIP": "GROUND_TRUTH", "QUEST_STATE": "GROUND_TRUTH",
    "PLAYER_STATE": "GROUND_TRUTH", "WORLD_MAP": "STRONG",
    "ENTITY_MEMORY": "STRONG", "SPATIAL_MEMORY": "STRONG",
    "SEMANTIC_MEMORY": "STRONG", "MINIMAP_CV": "PERCEPTION",
    "WORLD_MAP_CV": "PERCEPTION", "WORLD3D": "PERCEPTION", "WORLD3D_LOCAL_VIEW": "PERCEPTION", "UI_CV": "PERCEPTION",
    "VISION": "PERCEPTION", "CROSS_VIEW": "PERCEPTION", "AI": "REASONING", "VLM": "REASONING",
    "PREDICTION": "REASONING",
}

# These fields describe a continuously changing sampled state, not durable
# semantic claims.  Comparing the last two seconds of camera positions,
# candidate lists or traversability rasters as if they were mutually exclusive
# facts manufactured thousands of BELIEF_CHANGED/CONTRADICTION events per
# minute.  They remain normal evidence and remain queryable; only the durable
# *lifecycle event* projection is suppressed.  Their real transitions already
# have dedicated events/reducers (TARGET_CHANGED, combat, UI and track events).
TEMPORAL_STATE_BELIEF_KEYS = frozenset({
    "active_perception_ranking", "camera_state", "is_in_combat",
    "local_traversability", "map_mouseover", "mouseover", "movement",
    "orientation", "player_world_position", "position", "scene_geometry",
    "soft_targets", "spawn_reference_candidates",
    "tooltip_observation", "ui_observations", "visual_candidates",
    "world_map_state",
})


T = TypeVar("T")


class SensorHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Fact(Generic[T]):
    value: T
    observed_at_monotonic: float
    source_timestamp_wallclock: float | None
    observation_id: str
    source: str
    confidence: float
    revision: int

    def age(self, now: float) -> float:
        return max(0., now-self.observed_at_monotonic)

    def is_fresh(self, now: float, max_age: float) -> bool:
        return 0. <= now-self.observed_at_monotonic <= max_age


@dataclass(frozen=True)
class WorldSnapshot:
    """One planner-tick view; top-level state cannot change underneath it."""
    revision: int
    created_at_monotonic: float
    session_id: str
    player: Fact[dict]
    target: Fact[dict | None]
    quests: Fact[tuple]
    ui: Fact[dict]
    combat: Fact[dict]
    world3d_tracks: Fact[tuple]
    entities: Fact[tuple]
    traversability: Fact[dict]
    movement: Fact[dict]
    sensor_health: MappingProxyType
    active_transaction: dict | None
    active_commitment: dict | None
    source_revisions: MappingProxyType
    section_updates: MappingProxyType
    normalized_state: MappingProxyType
    state: MappingProxyType = field(repr=False)
    latest: Observation | None = field(repr=False)
    quest_model: Any = field(repr=False)
    query: Any = field(repr=False)
    runtime_context: MappingProxyType = field(repr=False)
    _model: Any = field(repr=False, compare=False)

    def player_position(self) -> tuple[float, float] | None:
        pos = self.state.get("position") or {}
        x, y = number(pos.get("x")), number(pos.get("y"))
        return ((x, y) if x is not None and y is not None
                and 0 <= x <= 1 and 0 <= y <= 1 else None)

    def distance(self, destination: dict) -> float | None:
        position = self.player_position()
        x, y = number(destination.get("x")), number(destination.get("y"))
        if (position is None or x is None or y is None
                or destination.get("map_id") != self.state.get("map_id")):
            return None
        return math.hypot(x-position[0], y-position[1])

    @staticmethod
    def quest_signature(state: dict) -> str:
        return WorldModel.quest_signature(state)

    def corpse_was_recently_looted(self, guid: str, now: float) -> bool:
        return self._model.corpse_was_recently_looted(guid, now)


class WorldModel:
    """Temporal facts with explicit contradiction history and session boundaries."""

    def __init__(self, reliability_provider=None, relation_sink=None, event_sink=None, entity_memory=None):
        self.reliability_provider = reliability_provider
        self.relation_sink = relation_sink
        self.event_sink = event_sink
        self.entity_memory = entity_memory
        self.session_id = ""
        self.latest: Observation | None = None
        self.addon_state: dict = {}
        self.state: dict = {}
        self.projections: dict[str, dict] = {}
        self._state_dirty = False
        self._deferred_prediction_obs: list[Observation] = []
        self.history = deque(maxlen=512)
        self.events = deque(maxlen=200)
        self.event_records = _BoundedEventRecords(maxlen=500)
        self.evidence: dict[str, deque[Evidence]] = {}
        self.seen_events: set[tuple] = set()
        self.entities: dict[str, dict] = {}
        self.entity_locations: dict[str, list[dict]] = {}
        self.entity_location_clusters: dict[str, dict[str, LocationCluster]] = {}
        self.entity_roles: dict[str, list[dict]] = {}
        self.entity_states: dict[str, list[dict]] = {}
        self.entity_appearances: dict[str, list[dict]] = {}
        self.entity_identity_evidence: dict[str, list] = {}
        self.predictions = deque(maxlen=100)
        self.prediction_errors = deque(maxlen=100)
        self.verifications = deque(maxlen=200)
        self.relations: dict[str, WorldRelation] = {}
        self.track_lifecycle: dict[str, dict[str, dict]] = {}
        self.last_beliefs: dict[str, tuple[str, str]] = {}
        self.contradiction_history = deque(maxlen=256)
        self.contradiction_state: dict[str, tuple[str, tuple[str, ...]]] = {}
        # Short-lived, client-confirmed corpse anchors.  These are screen-space
        # interaction observations, never guessed world locations.
        self.corpse_anchors: dict[str, dict] = {}
        # Last GUID-bound World3D box of every selected unit (nameplate/track
        # projection).  Live 2026-10-01: LOOT right-clicked the *last mouseover*
        # point, usually from before the fight, and missed the corpse.
        self.last_target_boxes: dict[str, dict] = {}
        # Loot ownership is not implied by DEAD.  Only a GUID correlated with
        # this agent's own active/successful combat (or explicit client
        # lootable telemetry) may become an actionable corpse anchor.
        self.owned_corpse_guids: dict[str, float] = {}
        # GUID -> last time a COMBAT/DEFEND skill fought it.  Live 2026-10-02:
        # COMBAT failed (facing), the murloc still died to auto-attack, and
        # its hovered corpse was never looted because no kill was recorded.
        self.combat_engaged: dict[str, float] = {}
        # A corpse can remain under the cursor after a successful auto-loot.
        # Keep a bounded tombstone so that the following mouseover sample does
        # not recreate the anchor and make the planner loot the same GUID again.
        self.looted_corpse_guids: dict[str, float] = {}
        self.last_loot_source_guid: str | None = None
        self.last_loot_received_at = -math.inf
        self.mouseover_screen_anchors: dict[str, dict] = {}
        # GUID -> time a hostile was judged quest-relevant from its own
        # mouseover (addon flag or tooltip naming an active quest).  The
        # target frame alone carries neither, so COMBAT needs this memory.
        self.quest_relevant_units: dict[str, float] = {}
        # A screen coordinate becomes invalid as soon as the player/camera
        # moves, but the identity fact learned from the addon tooltip does not.
        # Keep that fact separately and only for the exact GUID + active quest.
        self.mouseover_entity_semantics: dict[str, dict] = {}
        self.model_revision = 1
        self.prediction_calibration: dict[str, dict[str, int]] = {}
        self.quest_model = QuestModel()
        self.last_received = 0.
        self.last_identity = ""
        # Query construction is the single read-only boundary for all
        # planner/domain consumers.  The old in-file class remains only as a
        # temporary source-compatible definition while callers migrate; it is
        # not instantiated and owns no model state.
        self.query = WorldQuery(self, sensor_tiers=SENSOR_TIERS,
                                source_tiers=SOURCE_TIERS)
        self.runtime_context: dict = {}
        self.latest_visual_observation_id: str | None = None
        self.revision = 0
        self.source_revisions: dict[str, int] = {}
        self.source_latest: dict[str, Observation] = {}
        self.section_updates: dict[str, dict] = {}
        self._event_reducer = WorldEventReducer()
        self._entity_reducer = WorldEntityReducer()
        self._ui_reducer = WorldUiReducer()
        self._evidence_reducer = WorldEvidenceReducer()
        self._addon_reducer = WorldAddonReducer()
        self._state_projector = WorldStateProjector()
        self._anchor_reducer = WorldAnchorReducer()
        self._section_tracker = WorldSectionUpdateTracker()
        self._state_contract = WorldStateContract()
        self._trace_graph = WorldTraceGraph()
        self._prediction_runtime = WorldPredictionRuntime()

    def _accepted(self, obs: Observation) -> bool:
        self.revision += 1
        self.source_revisions[obs.source] = self.source_revisions.get(obs.source, 0) + 1
        self.source_latest[obs.source] = obs
        self._section_tracker.record(self, obs)
        return True

    def set_runtime_context(self, *, goal=None, subgoal=None, commitment=None,
                            sensor_health=None, active_skill=None, last_result=None,
                            primary_quest=None, quest_failure_memory=None) -> None:
        from dataclasses import asdict, is_dataclass
        def project(value):
            if value is None:
                return None
            return asdict(value) if is_dataclass(value) else deepcopy(value)
        self.runtime_context = {"goal": project(goal), "subgoal": project(subgoal),
                                "commitment": project(commitment),
                                "sensor_health": deepcopy(sensor_health or []),
                                "active_skill": project(active_skill),
                                "last_result": project(last_result),
                                "primary_quest": project(primary_quest),
                                "quest_failure_memory": project(quest_failure_memory)}
        active = self.runtime_context["active_skill"] or {}
        engaged = str(active.get("target_guid") or "") if isinstance(active, dict) else ""
        if (str(active.get("skill") or "").upper() in {"COMBAT", "DEFEND"}
                and engaged.startswith(("Creature-", "Vehicle-"))):
            self.__dict__.setdefault("combat_engaged", {})[engaged] = self.last_received

    def _emit_derived_event(self, event_type: str, payload: dict, obs: Observation):
        raw = {"event_type": event_type, "source": "WORLD_MODEL", "timestamp": obs.timestamp,
               "payload": payload}
        record = EventRecord.create(raw, obs)
        if record.event_id in self.event_records.ids:
            return record
        self.events.append(raw)
        self.event_records.append(record)
        if self.event_sink:
            self.event_sink(record)
        self.link(f"event:{record.event_id}", "observed_by",
                  f"observation:{obs.observation_id}", obs)
        return record

    def runtime_event(self, event_type: str, payload: dict):
        if not self.latest:
            return None
        return self._emit_derived_event(event_type, payload, self.latest)

    def mark_area_looted(self, at: float | None = None, *, window: float = 30.) -> None:
        """Retire own corpses killed within ``window`` s (Retail area loot)."""
        now = self.last_received if at is None else float(at)
        for guid, killed_at in list(self.owned_corpse_guids.items()):
            if killed_at is not None and 0 <= now-float(killed_at) <= window:
                self.mark_corpse_looted(guid, now)

    def note_loot_failure(self, guid: str | None, at: float | None = None,
                          *, limit: int = 2) -> None:
        guid = str(guid or "")
        if not guid:
            return
        failures = self.__dict__.setdefault("loot_failures", {})
        failures[guid] = failures.get(guid, 0) + 1
        if failures[guid] >= limit:
            self.mark_corpse_looted(guid, at)

    def mark_corpse_looted(self, guid: str | None, at: float | None = None) -> None:
        """Retire one confirmed corpse after authoritative loot progress."""
        guid = str(guid or "")
        if not guid:
            return
        observed_at = number(at)
        self.looted_corpse_guids[guid] = (self.last_received if observed_at is None else observed_at)
        self.owned_corpse_guids.pop(guid, None)
        self.corpse_anchors.pop(guid, None)
        if "confirmed_corpse_anchors" in self.state:
            self.state["confirmed_corpse_anchors"] = [
                anchor for anchor in self.state["confirmed_corpse_anchors"]
                if anchor.get("guid") != guid]
        self.state["owned_corpse_guids"] = list(self.owned_corpse_guids)

    def corpse_was_recently_looted(self, guid: str, now: float) -> bool:
        looted_at = self.looted_corpse_guids.get(guid)
        return looted_at is not None and 0 <= now-looted_at <= 300.

    def mark_combat_kill(self, guid: str | None, at: float | None = None) -> None:
        """Record exact-GUID loot ownership after verified local combat."""
        guid = str(guid or "")
        if not guid.startswith(("Creature-", "Vehicle-")):
            return
        observed_at = number(at)
        killed_at = self.last_received if observed_at is None else observed_at
        self.owned_corpse_guids[guid] = killed_at
        anchor = self.mouseover_screen_anchors.get(guid)
        boxed = self.last_target_boxes.get(guid)
        if (boxed and isinstance(boxed.get("bbox"), dict)
                and 0 <= killed_at-float(boxed.get("observed_at") or -1e9) <= 5.):
            anchor = {**(anchor or {}), **boxed, "anchor_source": "TARGET_TRACK_AT_DEATH"}
        if anchor and number(anchor.get("x")) is not None and number(anchor.get("y")) is not None:
            self.corpse_anchors[guid] = {
                **deepcopy(anchor), "guid": guid, "dead": True,
                "source": "OWN_COMBAT_CONFIRMED", "belief": "CONFIRMED",
                "ownership_confirmed": True, "ownership_source": "COMBAT_SUCCESS",
                "observed_at": killed_at,
            }
        if "confirmed_corpse_anchors" in self.state:
            self.state["confirmed_corpse_anchors"] = [
                deepcopy(item) for item in self.corpse_anchors.values()]
        self.state["owned_corpse_guids"] = list(self.owned_corpse_guids)

    ENGAGED_CORPSE_SECONDS = 120.

    def corpse_was_engaged(self, guid: str | None, now: float) -> bool:
        engaged_at = self.__dict__.get("combat_engaged", {}).get(str(guid or ""))
        return engaged_at is not None and 0 <= now-float(engaged_at) <= self.ENGAGED_CORPSE_SECONDS

    def corpse_is_owned(self, guid: str | None, now: float) -> bool:
        killed_at = self.owned_corpse_guids.get(str(guid or ""))
        return killed_at is not None and 0 <= now-killed_at <= 180.

    def corpse_is_combat_correlated(self, guid: str | None, now: float) -> bool:
        """Accept own-kill evidence already verified or still owned by COMBAT."""
        guid = str(guid or "")
        if self.corpse_is_owned(guid, now) or self.corpse_was_engaged(guid, now):
            return True
        active = self.runtime_context.get("active_skill") or {}
        if (str(active.get("skill") or "").upper() in {"COMBAT", "DEFEND"}
                and str(active.get("target_guid") or "") == guid):
            return True
        commitment = self.runtime_context.get("commitment") or {}
        if (commitment.get("kind") == "TARGET"
                and str(commitment.get("target_guid") or "") == guid
                and str(commitment.get("initial_skill") or "").upper()
                    in {"COMBAT", "DEFEND"}):
            return True
        # A full event page can arrive immediately after FAST already cleared
        # the dead target.  Preserve exact-GUID continuity from the preceding
        # combat observation; never infer ownership from proximity/name/dead.
        for observation in reversed(self.history):
            if observation is self.latest:
                continue
            if now-observation.received_at > 5.:
                break
            prior = observation.payload
            target = prior.get("target") or {}
            if (prior.get("is_in_combat") is True
                    and str(target.get("guid") or "") == guid):
                return True
        return False

    def _update_track_lifecycle(self, obs: Observation):
        if "visual_candidates" not in obs.payload:
            return
        active = self.track_lifecycle.setdefault(obs.source, {})
        seen = set()
        for item in obs.payload.get("visual_candidates", []):
            track_id = item.get("track_id")
            if not track_id:
                continue
            seen.add(track_id)
            state = str(item.get("track_state") or
                        ("STABLE" if (number(item.get("stable_frames")) or 0) >= 3 else "TENTATIVE"))
            prior = active.get(track_id)
            active[track_id] = {"state": state, "misses": int(number(item.get("missing_frames")) or 0),
                                "kind": item.get("detector_kind") or item.get("kind")}
            if prior is None:
                self._emit_derived_event("VISUAL_TRACK_APPEARED",
                    {"track_id": track_id, "surface": obs.source, "state": state}, obs)
            elif prior["state"] not in {"STABLE", "ACTIVE"} and state in {"STABLE", "ACTIVE"}:
                self._emit_derived_event("VISUAL_TRACK_STABILIZED",
                    {"track_id": track_id, "surface": obs.source, "state": state}, obs)
            if prior and state == "OCCLUDED" and prior["state"] != "OCCLUDED":
                self._emit_derived_event("TRACK_OCCLUDED",
                    {"track_id": track_id, "surface": obs.source}, obs)
            if prior and state == "REACQUIRE_CANDIDATE" and prior["state"] in {"OCCLUDED", "LOST_TEMPORARY"}:
                self._emit_derived_event("TRACK_REACQUIRE_CANDIDATE",
                    {"track_id": track_id, "surface": obs.source,
                     "identity_status": "CANDIDATE"}, obs)
        for track_id in list(active):
            if track_id in seen:
                continue
            active[track_id]["misses"] += 1
            if active[track_id]["misses"] >= 3:
                self._emit_derived_event("VISUAL_TRACK_LOST",
                    {"track_id": track_id, "surface": obs.source,
                     "previous_state": active[track_id]["state"]}, obs)
                del active[track_id]

    def _update_belief_lifecycle(self, obs: Observation, keys):
        for key in keys:
            if key in TEMPORAL_STATE_BELIEF_KEYS or key.startswith("world3d_"):
                continue
            belief = self.belief(key, obs.received_at)
            identity = (belief["status"], canonical(belief.get("value")))
            prior = self.last_beliefs.get(key)
            self.last_beliefs[key] = identity
            if prior is not None and prior != identity:
                self._emit_derived_event("BELIEF_CHANGED", {
                    "belief_key": key, "previous_status": prior[0],
                    "status": identity[0], "supporting_observations": belief.get("evidence", [])}, obs)
            contradictions = tuple(belief.get("contradictions") or ())
            contradiction_status = "AMBIGUOUS" if belief["status"] == "AMBIGUOUS" else (
                "RESOLVED" if contradictions else "NONE")
            contradiction_identity = (contradiction_status, contradictions)
            old_contradiction = self.contradiction_state.get(key)
            if contradictions and contradiction_identity != old_contradiction:
                resolution = str((belief.get("resolution") or {}).get("method") or "UNRESOLVED")
                self.contradiction_history.append(ContradictionRecord(
                    key, contradiction_status, resolution, canonical(belief.get("value")),
                    tuple(belief.get("supporting_evidence") or ()), contradictions, obs.received_at))
                self._emit_derived_event(
                    "CONTRADICTION_DETECTED" if contradiction_status == "AMBIGUOUS" else "CONTRADICTION_RESOLVED",
                    {"belief_key": key, "status": contradiction_status, "resolution": resolution,
                     "support": list(belief.get("supporting_evidence") or ()),
                     "contradictions": list(contradictions)}, obs)
            elif old_contradiction and old_contradiction[0] == "AMBIGUOUS" and not contradictions:
                self.contradiction_history.append(ContradictionRecord(
                    key, "RESOLVED", "NEW_EVIDENCE", canonical(belief.get("value")),
                    tuple(belief.get("supporting_evidence") or ()), old_contradiction[1], obs.received_at))
                self._emit_derived_event("CONTRADICTION_RESOLVED", {
                    "belief_key": key, "status": "RESOLVED", "resolution": "NEW_EVIDENCE",
                    "contradictions": list(old_contradiction[1])}, obs)
            self.contradiction_state[key] = contradiction_identity

    def _world_prediction(self, kind: str, subject: str, predicted_state: dict,
                          obs: Observation, *, horizon: float, confidence: float):
        return self._prediction_runtime.create(
            self, kind, subject, predicted_state, obs,
            horizon=horizon, confidence=confidence)

    def _finish_world_prediction(self, prediction: Prediction, outcome: str, reason: str,
                                 obs: Observation, *, mismatch=False):
        self._prediction_runtime.finish(
            self, prediction, outcome, reason, obs, mismatch=mismatch)

    def _evaluate_world_predictions(self, obs: Observation):
        self._prediction_runtime.evaluate(self, obs)

    def link(self, subject: str, predicate: str, object: str, obs: Observation,
             confidence: float = 1., status: str = "CONFIRMED"):
        # Edges whose object is an observation reference (observed_by,
        # based_on, ...) are keyed per subject+predicate, not per
        # observation: the newest observation becomes the object and the
        # `evidence` tuple keeps the last 20. Live-measured 2026-09-21 on a
        # 12.6 h session: keyed per observation, `track:* observed_by` alone
        # produced 2.47 M relation rows for 10.9 k tracks (~230 rows per
        # track, one per frame) and the world_relations table reached
        # 1.4 GB -- more than a third of a 4.1 GB memory DB -- for a graph
        # nothing reads back per frame (the observations themselves are the
        # durable record).
        identity = f"{subject}:{predicate}" if object.startswith("observation:") else f"{subject}:{predicate}:{object}"
        relation_id = __import__("hashlib").sha256(identity.encode()).hexdigest()[:24]
        old = self.relations.pop(relation_id, None)
        evidence = tuple(dict.fromkeys((*(old.evidence if old else ()), obs.observation_id)))[-20:]
        self.relations[relation_id] = WorldRelation(relation_id, subject, predicate, object,
            max(old.confidence if old else 0., max(0., min(1., confidence))), evidence, status, obs.received_at)
        # pop+reinsert above keeps dict order == last-touched order, so the
        # bound below evicts the least recently refreshed edges first.
        while len(self.relations) > MAX_RELATIONS:
            self.relations.pop(next(iter(self.relations)))
        if self.relation_sink:
            self.relation_sink(self.session_id, vars(self.relations[relation_id]))

    def record_plan_graph(self, goal, plan, obs: Observation):
        """Trace Goal → Subgoal → Plan → Observation without executing it."""
        self._trace_graph.record_plan(self, goal, plan, obs)

    def record_action_graph(self, attempt, obs: Observation):
        self._trace_graph.record_action(self, attempt, obs)

    def record_verification_graph(self, verification, obs: Observation):
        self._trace_graph.record_verification(self, verification, obs)

    def _ingest_execution_trace(self, obs: Observation):
        self._trace_graph.ingest(self, obs)

    def _record_entity_location(self, identity: str, position: dict, state: dict,
                                source: str, obs: Observation) -> LocationObservation | None:
        x, y, z = number(position.get("x")), number(position.get("y")), number(position.get("z"))
        if x is None or y is None:
            return None
        map_id = position.get("map_id", state.get("map_id"))
        phase, instance, zone = state.get("phase"), state.get("instance_id"), state.get("zone_name")
        coordinate_space = str(position.get("coordinate_space") or "NORMALIZED_MAP")
        context = canonical({"map_id": map_id, "phase": phase, "instance": instance,
                             "zone": zone, "coordinate_space": coordinate_space})
        clusters = self.entity_location_clusters.setdefault(identity, {})
        compatible = [cluster for cluster in clusters.values()
                      if cluster.context == context and math.hypot(x-cluster.center_x, y-cluster.center_y) <= .01]
        cluster = min(compatible, key=lambda item: math.hypot(x-item.center_x, y-item.center_y), default=None)
        if cluster is None:
            seed = canonical({"entity": identity, "context": context,
                              "cell_x": round(x/.005), "cell_y": round(y/.005)})
            cluster_id = __import__("hashlib").sha256(seed.encode()).hexdigest()[:24]
            cluster = LocationCluster(cluster_id, map_id, phase, instance, zone, context,
                                      coordinate_space, x, y, z, obs.received_at, obs.received_at,
                                      confidence=1., observation_ids=[obs.observation_id])
            clusters[cluster_id] = cluster
        else:
            count = cluster.seen_count + 1
            cluster.center_x = (cluster.center_x*cluster.seen_count+x)/count
            cluster.center_y = (cluster.center_y*cluster.seen_count+y)/count
            if z is not None:
                cluster.center_z = z if cluster.center_z is None else (cluster.center_z*cluster.seen_count+z)/count
            cluster.seen_count, cluster.last_seen = count, obs.received_at
            cluster.observation_ids = (cluster.observation_ids + [obs.observation_id])[-40:]
        record = LocationObservation(obs.observation_id, cluster.cluster_id, map_id, x, y, z,
                                     coordinate_space, phase, instance, zone, context, source, 1.,
                                     obs.received_at)
        locations = self.entity_locations.setdefault(identity, [])
        locations.append(vars(record))
        self.entity_locations[identity] = locations[-80:]
        return record

    def _record_entity_role(self, identity: str, unit: dict, state: dict,
                            source: str, obs: Observation) -> RoleObservation | None:
        role, role_source = unit.get("quest_role"), unit.get("quest_role_source")
        if not role or role == "UNKNOWN" or not role_source:
            return None
        quest_id, revision = unit.get("quest_id"), state.get("quest_state_revision")
        player_context = canonical({"level": state.get("level"), "combat": state.get("is_in_combat"),
                                    "quest_revision": revision, "session": obs.session_id})
        seed = canonical({"entity": identity, "role": role, "quest": quest_id,
                          "revision": revision, "phase": state.get("phase"),
                          "instance": state.get("instance_id"), "observation": obs.observation_id})
        role_id = __import__("hashlib").sha256(seed.encode()).hexdigest()[:24]
        record = RoleObservation(role_id, str(role), quest_id, revision, player_context,
                                 state.get("phase"), state.get("instance_id"), str(role_source),
                                 1., obs.received_at, obs.observation_id)
        roles = self.entity_roles.setdefault(identity, [])
        roles.append(vars(record))
        self.entity_roles[identity] = roles[-80:]
        return record

    def _record_entity_identity_evidence(self, identity: str, value, source_tag: str, obs: Observation) -> None:
        """V4-010: append one named-identity claim for later `fuse_identity()`."""
        if not value:
            return
        from .entity_belief import IdentityEvidence
        entries = self.entity_identity_evidence.setdefault(identity, [])
        entries.append(IdentityEvidence(str(source_tag), str(value), 1.0, obs.received_at))
        self.entity_identity_evidence[identity] = entries[-40:]

    def _record_entity_state_and_appearance(self, identity: str, unit: dict, state: dict,
                                            source: str, obs: Observation) -> None:
        values = {key: unit.get(key) for key in
                  ("health", "max_health", "dead", "is_dead", "attackable", "is_attackable",
                   "moving", "combat", "quest_available", "quest_complete") if key in unit}
        if values:
            seed = canonical({"entity": identity, "values": values, "observation": obs.observation_id})
            record = EntityStateObservation(__import__("hashlib").sha256(seed.encode()).hexdigest()[:24],
                values, state.get("phase"), state.get("instance_id"), source,
                obs.received_at, obs.observation_id)
            states = self.entity_states.setdefault(identity, [])
            states.append(vars(record)); self.entity_states[identity] = states[-80:]
        signature = unit.get("visual_signature") or unit.get("appearance")
        if isinstance(signature, dict) and signature:
            representation = str(signature.get("representation_space") or "UNKNOWN")
            seed = canonical({"entity": identity, "signature": signature,
                              "representation": representation, "observation": obs.observation_id})
            record = AppearanceObservation(__import__("hashlib").sha256(seed.encode()).hexdigest()[:24],
                representation, deepcopy(signature), source, obs.received_at, obs.observation_id)
            appearances = self.entity_appearances.setdefault(identity, [])
            appearances.append(vars(record)); self.entity_appearances[identity] = appearances[-80:]

    def add_evidence(self, key: str, value, obs: Observation, confidence: float = 1., ttl: float = 5.):
        entries = self.evidence.setdefault(key, deque(maxlen=20))
        if any(e.correlation_id == obs.correlation_id and e.source == obs.source for e in entries):
            return
        dynamic = self.reliability_provider(obs.source, self.addon_state) if self.reliability_provider else None
        reliability = dynamic if dynamic is not None else RELIABILITY.get(obs.source, .4)
        reliability = max(0., min(1., float(reliability)))
        sensor_tier = SOURCE_TIERS.get(obs.source, "UNKNOWN")
        context = {"session_id": obs.session_id, "map_id": obs.payload.get("map_id"),
                   "surface": obs.payload.get("surface")}
        provenance = obs.payload.get("provenance") or {}
        independence_group = str(provenance.get("independence_group") or
                                 (obs.correlation_id if obs.source in {"MINIMAP_CV", "WORLD_MAP_CV", "WORLD3D", "UI_CV", "VISION", "AI"}
                                  else obs.observation_id))
        entries.append(Evidence(obs.observation_id, obs.correlation_id, obs.source, obs.received_at,
                                obs.received_at + ttl, canonical(value), confidence, reliability,
                                canonical(context), independence_group, sensor_tier,
                                SENSOR_TIERS[sensor_tier], key,
                                str(obs.payload.get("entity_id") or obs.payload.get("guid") or "") or None,
                                str(obs.payload.get("quest_id") or "") or None,
                                str(obs.payload.get("objective_id") or "") or None))

    @staticmethod
    def _diagnostic_claim_value(key: str, value):
        """Bound collection claims without discarding their typed item evidence.

        Full visual candidates stay in the source projection and each track gets
        its own evidence claim below. The aggregate collection belief only needs
        identity/type/lifecycle metadata; embedding complete 32-frame histories
        recursively inflated contradiction records.
        """
        if key == "visual_candidates" and isinstance(value, list):
            return [{field: item.get(field) for field in
                     ("track_id", "source", "detector_kind", "kind", "semantic_type",
                      "belief", "confidence", "stable_frames", "lifecycle", "inspectable")}
                    for item in value if isinstance(item, dict)]
        if key == "visual_recognition_candidates" and isinstance(value, list):
            return [{"track_id": item.get("track_id"), "surface": item.get("surface"),
                     "appearance_signature_id": item.get("appearance_signature_id"),
                     "entity_candidates": [{field: candidate.get(field) for field in
                         ("identity_key", "status", "reliability", "similarity", "match_method")}
                        for candidate in item.get("entity_candidates", []) if isinstance(candidate, dict)]}
                    for item in value if isinstance(item, dict)]
        if key == "active_perception_ranking" and isinstance(value, list):
            return [{field: item.get(field) for field in
                     ("track_id", "source", "semantic_type", "detector_kind", "utility",
                      "expected_information_gain", "cost", "recognition_candidate_count",
                      "recommended_observation", "action_authority")}
                    for item in value if isinstance(item, dict)]
        return value

    def belief(self, key: str, now: float) -> dict:
        entries = list(self.evidence.get(key, ()))
        active = [e for e in entries if e.expires >= now]
        if not active:
            return {"status": "STALE" if entries else "UNKNOWN", "value": None, "evidence": []}
        # Several visual/AI passes over one captured frame are correlated. Keep
        # only the strongest vote in such a group rather than manufacturing
        # independent support from the same pixels.
        groups = {}
        for entry in active:
            current = groups.get(entry.independence_group)
            if current is None or (entry.tier_rank, entry.reliability * entry.confidence) > (
                    current.tier_rank, current.reliability * current.confidence):
                groups[entry.independence_group] = entry
        ranked = sorted(list(groups.values()),
                        key=lambda e: (e.tier_rank, e.reliability * e.confidence, e.at), reverse=True)
        winning_rank = ranked[0].tier_rank
        peers = [entry for entry in ranked if entry.tier_rank == winning_rank]
        value_scores: dict[str, float] = {}
        for entry in peers:
            value_scores[entry.value_json] = value_scores.get(entry.value_json, 0.) + entry.reliability*entry.confidence
        values = sorted(value_scores.items(), key=lambda item: item[1], reverse=True)
        best_value, best_score = values[0]
        best = max((entry for entry in peers if entry.value_json == best_value), key=lambda e: e.at)
        contradictions = [e for e in ranked if e.value_json != best_value]
        supporting = [e for e in ranked if e.value_json == best_value]
        peer_competitor = values[1][1] if len(values) > 1 else 0.
        ambiguous = peer_competitor > 0 and abs(best_score-peer_competitor) <= max(.1, .15*best_score)
        lower_tier_only = bool(contradictions) and all(e.tier_rank < winning_rank for e in contradictions)
        support_groups = len({entry.independence_group for entry in supporting})
        effective_tier = "STRONG" if best.sensor_tier == "PERCEPTION" and support_groups >= 3 else best.sensor_tier
        resolution = ({"status": "UNRESOLVED", "method": "EQUAL_TIER_CONFLICT"}
                      if ambiguous else
                      {"status": "RESOLVED", "method": "HIGHER_SENSOR_TIER"}
                      if lower_tier_only else
                      {"status": "RESOLVED", "method": "WEIGHTED_SUPPORT"}
                      if contradictions else {"status": "NONE", "method": "NO_CONTRADICTION"})
        import json
        return {"status": "AMBIGUOUS" if ambiguous else "CONFIRMED" if best.sensor_tier == "GROUND_TRUTH" else "SUPPORTED",
                "value": json.loads(best.value_json), "source": best.source,
                "confidence": min(1., best_score), "sensor_tier": effective_tier,
                "sensor_tier_rank": SENSOR_TIERS[effective_tier], "resolution": resolution,
                "evidence": [e.observation_id for e in ranked],
                "supporting_evidence": [e.observation_id for e in supporting],
                "contradictions": [e.observation_id for e in contradictions],
                "source_reliability": {e.source: e.reliability for e in ranked},
                "evidence_hierarchy": [{"observation_id": e.observation_id, "source": e.source,
                                        "tier": e.sensor_tier, "tier_rank": e.tier_rank,
                                        "weighted_confidence": e.reliability*e.confidence}
                                       for e in ranked],
                "correlation_groups": sorted({e.correlation_id for e in ranked}),
                "independence_groups": sorted({e.independence_group for e in ranked}),
                "context": json.loads(best.context_json)}

    def typed_belief(self, key: str, now: float) -> Belief:
        """Typed read projection; legacy dict callers remain source-compatible."""
        return Belief.from_projection(key, self.belief(key, now))

    def prune_expired_evidence(self, now: float) -> int:
        """Drop evidence keys with no still-active entry.

        Each key's own deque is already TTL-bounded, but the outer dict
        (one key per distinct field, plus one per distinct visual track ever
        seen this session) was never trimmed, growing for the life of a long
        session. Called periodically from runtime maintenance, not every
        tick -- snapshot()'s own beliefs projection separately skips dead
        keys on every call regardless of when this last ran.
        """
        dead = [k for k, entries in self.evidence.items() if not any(e.expires >= now for e in entries)]
        for k in dead:
            del self.evidence[k]
        return len(dead)

    def flush_pending(self) -> None:
        """Finish a supplemental batch with one state rebuild."""
        if self._state_dirty:
            self._rebuild_state()
            self._state_dirty = False
        if self._deferred_prediction_obs:
            pending, self._deferred_prediction_obs = self._deferred_prediction_obs, []
            for pending_observation in pending:
                self._evaluate_world_predictions(pending_observation)

    def ingest(self, obs: Observation, *, defer_rebuild: bool = False) -> bool:
        if obs.source != "ADDON_TELEMETRY":
            if obs.session_id != self.session_id:
                return False
            if obs.source == "AGENT_TRACE":
                self.history.append(obs)
                self._ingest_execution_trace(obs)
                return self._accepted(obs)
            if obs.source == "AGENT_RUNTIME":
                # Runtime lifecycle transitions are first-class observations.
                # Replaying the append-only stream must rebuild the same events
                # and graph edges as the live model; an in-memory-only event
                # would make recovery/hydration silently lose commitment state.
                self.history.append(obs)
                event_type = str(obs.payload.get("event_type") or "AUTONOMY_EVENT")
                self._emit_derived_event(event_type, obs.payload.get("payload") or {}, obs)
                return self._accepted(obs)
            return self._evidence_reducer.apply(self, obs, defer_rebuild=defer_rebuild)
        if self.latest and obs.session_id == self.session_id and obs.observation_id == self.latest.observation_id:
            # A successfully decoded duplicate still proves the capture/decode
            # pipeline is alive -- only the CONTENT is unchanged (stable
            # target/position, nothing new to react to). Conflating that with
            # "no packet arrived" was live-confirmed 2026-09-12: receive_gap
            # climbed past the 6s/8s freshness thresholds and forced MANUAL
            # while sensor_diagnostics (the capture thread's own polls/
            # updates/poll_ms) stayed perfectly healthy the whole time --
            # addon_payload_hz and the main-thread mailbox hand-off were both
            # fine, only this early return (before the self.last_received
            # assignment further down) was silently starving it during any
            # stretch where fast-lane content genuinely didn't change.
            self.last_received = obs.received_at
            return False  # Re-reading a frozen pixel strip is not a fresh observation.
        if self.session_id != obs.session_id:
            provider, sink, event_sink, entity_memory = (self.reliability_provider, self.relation_sink,
                                                          self.event_sink, self.entity_memory)
            self.__init__(provider, sink, event_sink, entity_memory)
            self.session_id = obs.session_id
        state = obs.payload
        is_fast_state = state.get("transport_kind") == "FAST"
        # A paged full snapshot is sampled before its final page is received,
        # so its source timestamp can legitimately precede the latest FAST
        # control sample. Receive order remains authoritative across lanes;
        # timestamp regression is rejected only within the same/FAST lane.
        latest_kind = self.latest.payload.get("transport_kind") if self.latest else None
        if (self.latest and obs.timestamp < self.latest.timestamp
                and (is_fast_state or latest_kind != "FAST")):
            # Same principle as the duplicate-observation_id return above: an
            # out-of-order packet is still proof of a live pipeline, just not
            # something that should replace newer state.
            self.last_received = obs.received_at
            return False
        previous = self.state
        if obs.source != "ADDON_TELEMETRY":
            for key, value in state.items():
                self.add_evidence(key, value, obs, ttl=2.)
            self.history.append(obs)
            return self._accepted(obs)
        return self._addon_reducer.apply(
            self, obs, previous, defer_rebuild=defer_rebuild)

    def planning_snapshot(self, now: float) -> WorldSnapshot:
        return WorldSnapshotProjection.planning(
            self, now, snapshot_type=WorldSnapshot, fact_type=Fact,
            sensor_health_type=SensorHealth, reliability=RELIABILITY,
        )

    def _project_corpse_event(self, event: dict, state: dict, obs: Observation) -> None:
        """Compatibility delegation to the stateless anchor reducer."""
        self._anchor_reducer.project_corpse_event(self, event, state, obs)

    def _project_live_mouseover_anchor(self, state: dict, obs: Observation) -> None:
        """Compatibility delegation to the stateless anchor reducer."""
        self._anchor_reducer.project_live_mouseover(self, state, obs)

    def record_prediction_error(self, error: PredictionError):
        self.prediction_errors.append(error)

    def _rebuild_state(self):
        """Build the query view without changing the immutable addon observation.

        Supplemental sensors own only their explicit projection fields. Source
        metadata stays in Observation/history/evidence instead of masquerading as
        addon ground truth.
        """
        self._state_projector.rebuild(self)

    @staticmethod
    def _screen_anchor_scene_valid(anchor: dict, state: dict) -> bool:
        return WorldStateProjector.screen_anchor_scene_valid(anchor, state)

    def fresh(self, now: float, ttl: float = ADDON_RECEIVE_FRESH_SECONDS) -> bool:
        return (self.latest is not None and 0 <= now - self.last_received <= ttl
                and self.state.get("player_present", True) is not False)

    def detail_snapshot_stale(self, now: float) -> bool:
        """Whether the paged detail view is too old for detail-only consumers.

        Fast control telemetry remains live independently; callers must never
        interpret this as a disconnect or use it to change mode on its own.
        """
        return ((number(self.state.get("state_age")) or 0)
                + max(0., now-self.last_received) > ADDON_DETAIL_STATE_MAX_AGE_SECONDS)

    @staticmethod
    def quest_signature(state: dict) -> str:
        return canonical([{ "id": q.get("quest_id"), "complete": q.get("is_complete"),
                           "objectives": [(o.get("current"), o.get("is_complete")) for o in q.get("objectives", [])]}
                          for q in state.get("active_quests", [])])

    def objective_graph(self) -> list[dict]:
        return self.quest_model.graph()["nodes"]

    def player_position(self) -> tuple[float, float] | None:
        pos = self.state.get("position") or {}
        x, y = number(pos.get("x")), number(pos.get("y"))
        return (x, y) if x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1 else None

    def distance(self, destination: dict) -> float | None:
        position = self.player_position()
        x, y = number(destination.get("x")), number(destination.get("y"))
        if position is None or x is None or y is None or destination.get("map_id") != self.state.get("map_id"):
            return None
        return math.hypot(x - position[0], y - position[1])

    def snapshot(self, now: float) -> dict:
        return WorldSnapshotProjection.diagnostic(
            self, now,
            addon_receive_fresh_seconds=ADDON_RECEIVE_FRESH_SECONDS,
            addon_detail_state_max_age_seconds=ADDON_DETAIL_STATE_MAX_AGE_SECONDS,
        )
