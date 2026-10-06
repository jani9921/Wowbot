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
from .world_entities import LocationCluster
from .world_query import WorldQuery
from .world_models import Belief, Evidence, WorldRelation


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
from .world_corpses import WorldCorpseMixin
from .world_entity_records import WorldEntityRecordsMixin
from .world_beliefs import WorldBeliefMixin, RELIABILITY, SENSOR_TIERS, SOURCE_TIERS


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


class WorldModel(WorldBeliefMixin, WorldEntityRecordsMixin, WorldCorpseMixin):
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

    ENGAGED_CORPSE_SECONDS = 120.

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
        # A packet without a timestamp (0) is not "older": the bounded FAST
        # variants omit it (live 2026-10-06: 25 s of FAST dropped this way).
        if (self.latest and obs.timestamp and obs.timestamp < self.latest.timestamp
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
