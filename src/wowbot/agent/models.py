from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from functools import cached_property
import hashlib
import json
import math
import re
import unicodedata
from typing import Any


def json_copy(value: Any) -> Any:
    """Fast isolated copy for JSON-shaped data (dict/list/tuple/scalar trees).

    Moved here from world.py (which aliased its own local copy of this to
    `deepcopy` on the hot ingest path) so other modules on that same path
    (e.g. world_evidence_reducer.py) can reuse it instead of paying
    copy.deepcopy's generic dispatch overhead for ordinary telemetry/vision
    trees -- profiled 2026-09-22 as a real per-tick cost at
    WorldEvidenceReducer.apply()'s `deepcopy(observation.payload)`.
    """
    from copy import deepcopy as _slow_deepcopy
    value_type = type(value)
    if value_type is dict:
        return {key: json_copy(item) for key, item in value.items()}
    if value_type is list:
        return [json_copy(item) for item in value]
    if value_type is tuple:
        return tuple(json_copy(item) for item in value)
    if value_type in {str, int, float, bool} or value is None:
        return value
    return _slow_deepcopy(value)


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with None so canonical() degrades
    gracefully instead of raising when a raw telemetry field is -inf/inf/nan."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def canonical(value: Any) -> str:
    # Perf (live/offline-profiled 2026-09-22): _json_safe() recursively
    # rebuilds every dict/list it visits, even when nothing needs fixing --
    # the overwhelming common case, since real telemetry/world-state values
    # are already all-finite. canonical() is called hundreds of times per
    # tick (world.py's add_evidence/_update_belief_lifecycle/etc.), and that
    # unconditional rebuild was the single largest CPU-time contributor in a
    # profiled tick(). Try the direct (zero-copy) encode first; only a
    # non-finite float (or, in principle, a cycle -- never actually produced
    # by this codebase's JSON-shaped inputs) raises here, and only then is
    # the sanitizing rebuild worth paying for.
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError:
        return json.dumps(_json_safe(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def words(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


class Mode(StrEnum):
    MANUAL = "MANUAL"
    ASSIST = "ASSIST"
    FULL_AI = "FULL_AI"
    STOPPED = "STOPPED"


class Outcome(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    session_id: str
    timestamp: float
    received_at: float
    source: str
    payload_json: str
    correlation_id: str

    @classmethod
    def create(cls, payload: dict, received_at: float, source: str = "ADDON_TELEMETRY") -> Observation:
        encoded = canonical(payload)
        session = str(payload.get("session_id") or payload.get("character_guid") or payload.get("character_name") or "unknown")
        digest = hashlib.sha256((source + session + encoded).encode()).hexdigest()[:24]
        return cls(digest, session, number(payload.get("timestamp")) or 0., received_at, source, encoded,
                   str(payload.get("frame_id") or digest))

    @cached_property
    def payload(self) -> dict:
        # Observations are immutable; parsing the same JSON repeatedly was one
        # of the largest costs in WorldModel.ingest during the live loop.
        return json.loads(self.payload_json)

    @property
    def sensor(self) -> str:
        return self.source

    @property
    def observation_type(self) -> str:
        payload = self.payload
        return str(payload.get("observation_type") or payload.get("event_type")
                   or payload.get("transport_kind") or "STATE")

    @property
    def coordinate_space(self) -> str | None:
        payload = self.payload
        explicit = payload.get("coordinate_space")
        if explicit is not None:
            return str(explicit)
        if self.source in {"MINIMAP_CV", "WORLD_MAP_CV", "WORLD3D"}:
            return {"MINIMAP_CV": "MINIMAP_LOCAL",
                    "WORLD_MAP_CV": "WORLD_MAP_PIXEL",
                    "WORLD3D": "SCREEN_NORMALIZED"}[self.source]
        return None


@dataclass
class Goal:
    goal_id: str
    text: str
    domain: str
    created_at: float
    parameters: dict = field(default_factory=dict)
    status: str = "ACTIVE"
    completed_steps: int = 0
    failures: int = 0
    priority: float = 0.5
    progress: float = 0.0
    failure_reason: str | None = None
    completed_at: float | None = None
    recovery_count: int = 0

    @classmethod
    def parse(cls, text: str, now: float, parameters: dict | None = None) -> Goal:
        value = words(text)
        rules = [("QUEST", ("quest", "kuldet", "karaktert", "level", "fejleszd")),
                 ("FISH", ("fish", "horgasz", "halasz")), ("HERB", ("herb", "gyogynoveny")),
                 ("MINE", ("mine", "mining", "ore", "erc")), ("EXPLORE", ("explore", "fedezd")),
                 ("DUNGEON", ("dungeon", "raid")), ("PVP", ("battleground", "bg", "arena", "pvp")),
                 ("MOVE", ("npc", "menj", "go to", "move")), ("FARM", ("farm", "item"))]
        domain = next((name for name, matches in rules if any(re.search(r"\b" + re.escape(w), value) for w in matches)), "UNKNOWN")
        params = dict(parameters or {})
        match = re.search(r"(?:npc\s*#?)(\d+)", value)
        if match:
            params.setdefault("npc_id", int(match[1]))
        duration = re.search(r"(\d+)\s*(hours?|ora|minutes?|perc)", value)
        if duration:
            params.setdefault("duration", int(duration[1]) * (3600 if duration[2].startswith(("hour", "ora")) else 60))
        if "bag" in value or "taska" in value:
            params.setdefault("until_bags_full", True)
        identity = hashlib.sha256(f"{text}:{now}".encode()).hexdigest()[:16]
        priority = number(params.get("priority"))
        priority = .5 if priority is None else max(0., min(1., priority))
        return cls(identity, text, domain, now, params, priority=priority)


@dataclass(frozen=True)
class Proposal:
    skill: str
    reason: str
    parameters_json: str = "{}"
    confidence: float = 1.0
    priority: float = 0.0
    evidence: tuple[str, ...] = ()

    @classmethod
    def make(cls, skill: str, reason: str, params: dict | None = None, confidence: float = 1., priority: float = 0., evidence=()):
        return cls(skill, reason, canonical(params or {}), confidence, priority, tuple(evidence))

    @property
    def parameters(self) -> dict:
        return json.loads(self.parameters_json)

    @property
    def key(self) -> str:
        identity = self.parameters_json
        if self.skill == "INSPECT" and self.parameters.get("inspection_id"):
            identity = canonical({"inspection_id": self.parameters["inspection_id"]})
        elif self.skill == "SEEK_VISUAL_CUE" and self.parameters.get("track_id"):
            # Live-observed 2026-09-13: without a stable identity, the default
            # key hashes the whole marker (x/y/confidence/active_perception
            # all drift a little every tick even while chasing the same
            # subject), so engine.py's universal failure backoff
            # (planner.blocked_until, exponential per proposal.key) never
            # actually accumulates across repeated "visual_track_lost"
            # attempts against the same track -- each retry looked like a
            # brand new proposal and got a clean slate, producing an
            # effectively infinite retry loop on one unreachable subject
            # instead of ever backing off to let a different candidate (or
            # OPEN_MAP) win. Same fix shape as the INSPECT case above.
            identity = canonical({"track_id": self.parameters["track_id"]})
        return hashlib.sha256((self.skill + identity).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Plan:
    plan_id: str
    goal_id: str
    subgoal_id: str
    objective_ref: str | None
    selected_proposal_id: str
    candidate_proposal_ids: tuple[str, ...]
    skill: str
    expected_outcome: str
    verification: str
    fallback: str
    created_at: float
    observation_id: str
    evidence: tuple[str, ...] = ()
    confidence: float = 1.0
    uncertainty: float = 0.0
    steps: tuple[dict[str, Any], ...] = ()
    constraints: tuple[str, ...] = ()
    replan_triggers: tuple[str, ...] = ()
    candidate_utilities: tuple[dict[str, Any], ...] = ()

    @classmethod
    def create(cls, goal: Goal, proposal: Proposal, candidates: list[Proposal], contract,
               now: float, observation_id: str, *, steps=(), constraints=(),
               replan_triggers=(), candidate_utilities=()) -> Plan:
        objective = proposal.parameters.get("objective_id")
        if objective is None and proposal.parameters.get("quest_id") is not None:
            objective = f"quest:{proposal.parameters['quest_id']}"
        subgoal_seed = canonical({"goal": goal.goal_id, "objective": objective,
                                  "proposal": proposal.key})
        subgoal_id = hashlib.sha256(subgoal_seed.encode()).hexdigest()[:16]
        plan_id = hashlib.sha256(f"{subgoal_id}:{observation_id}:{now}".encode()).hexdigest()[:24]
        return cls(plan_id, goal.goal_id, subgoal_id, str(objective) if objective is not None else None,
                   proposal.key, tuple(item.key for item in candidates), proposal.skill,
                   contract.expected, contract.success_condition, contract.recovery, now,
                   observation_id, proposal.evidence, max(0., min(1., proposal.confidence)),
                   round(1-max(0., min(1., proposal.confidence)), 6), tuple(steps),
                   tuple(constraints), tuple(replan_triggers), tuple(candidate_utilities))


@dataclass(frozen=True)
class Command:
    kind: str  # BIND, CLICK, CLICK_CURRENT_CURSOR, HOVER; never arbitrary code, macro, or shell text
    binding: str | None = None
    duration: float = .08
    x: float | None = None
    y: float | None = None
    button: str = "LEFT"
    simultaneous: tuple[str, ...] = ()


@dataclass
class Prediction:
    prediction_id: str
    action_id: str
    expected: str
    created_at: float
    deadline: float
    observation_id: str
    status: str = "PENDING"
    reason: str = "awaiting_new_observation"
    confidence: float = 1.0
    provenance: tuple[str, ...] = ()
    prediction_kind: str = "ACTION_OUTCOME"
    subject: str | None = None
    predicted_state: dict[str, Any] = field(default_factory=dict)
    model_revision: int = 1
    earliest_expected: float | None = None
    likely_start: float | None = None
    likely_end: float | None = None
    expected_observations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PredictionError:
    error_id: str
    prediction_id: str
    action_id: str
    expected: str
    reason: str
    created_at: float
    observed_at: float
    baseline_observation_id: str
    observed_observation_id: str | None
    investigation: str = "COLLECT_EVIDENCE_AND_REPLAN"
    failure_type: str = "UNKNOWN"
    observed: str = ""
    error_type: str = "UNOBSERVED"
    magnitude: float | None = None
    confidence: float = 0.5


@dataclass(frozen=True)
class VerificationRecord:
    verification_id: str
    action_id: str
    skill: str
    plan_id: str | None
    prediction_id: str
    expected: str
    outcome: str
    reason: str
    observed_at: float
    baseline_observation_id: str
    observed_observation_id: str | None
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    session_id: str
    sequence: int | None
    timestamp: float
    received_at: float
    event_type: str
    source: str
    observation_id: str
    entity_ids: tuple[str, ...]
    quest_ids: tuple[int | str, ...]
    marker_ids: tuple[str, ...]
    payload_json: str

    @classmethod
    def create(cls, raw: dict, observation: Observation) -> EventRecord:
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        sequence_value = number(raw.get("sequence"))
        sequence = int(sequence_value) if sequence_value is not None else None
        entity_ids = tuple(dict.fromkeys(str(value) for value in
            (payload.get("guid"), payload.get("entity_guid"), payload.get("target_guid")) if value))
        quest_ids = tuple(dict.fromkeys(value for value in
            (payload.get("quest_id"), raw.get("quest_id")) if value is not None))
        marker_ids = tuple(dict.fromkeys(str(value) for value in
            (payload.get("marker_id"), payload.get("track_id")) if value))
        event_type = str(raw.get("event_type") or "UNKNOWN")
        identity = canonical({"session": observation.session_id, "sequence": sequence,
                              "type": event_type, "payload": payload,
                              "observation": observation.observation_id if sequence is None else None})
        event_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        return cls(event_id, observation.session_id, sequence,
                   number(raw.get("timestamp")) or observation.timestamp,
                   observation.received_at, event_type, str(raw.get("source") or observation.source),
                   observation.observation_id, entity_ids, quest_ids, marker_ids, canonical(payload))

    @cached_property
    def payload(self) -> dict:
        return json.loads(self.payload_json)


@dataclass
class Attempt:
    action_id: str
    proposal: Proposal
    baseline: dict
    observation_id: str
    started_at: float
    deadline: float
    commands: tuple[Command, ...]
    prediction: Prediction
    plan_id: str | None = None

    def to_dict(self) -> dict:
        # Diagnostic serialization only; verifiers use the live `baseline`
        # attribute. Live-measured 2026-09-20: each Attempt's baseline is a
        # full world.state copy (~300 KB with the World3D batch), and this
        # dict was being logged per ACTION_INTENT/ACTION_EXECUTED into the
        # structured log (80% of a 4.4 MB status JSON re-dumped on every
        # write), the SQLite episode steps (1.36 GB/h growth) and the
        # pending status. The state is already durably stored as the
        # Observation named by `observation_id`, so only that reference is
        # kept here.
        result = asdict(self)
        result.pop("baseline", None)
        result["baseline_observation_id"] = self.observation_id
        return result
