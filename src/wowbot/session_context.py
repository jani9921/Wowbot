"""One session/context authority. Neither input nor packet capture belongs here.

A capture baseline identifies the selected character; it is not a baseline of
questlog, inventory, phase or health. Those coverages remain independently
unknown. Addon identity is a labelled migration source, never a guessed GUID.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from collections.abc import Mapping

from .context_contracts import SessionContext, SessionIdentity, WorldContext


class BaselineState(StrEnum):
    NO_BASELINE = "NO_BASELINE"
    READY = "READY"
    GAP = "GAP"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    selected_pid: int
    generation: str
    game_build: int | None = None

    def __post_init__(self):
        if type(self.selected_pid) is not int or self.selected_pid <= 0:
            raise ValueError("explicit selected PID required")
        if not isinstance(self.generation, str) or not self.generation:
            raise ValueError("process generation required")
        if self.game_build is not None and (type(self.game_build) is not int or self.game_build <= 0):
            raise ValueError('invalid observed process build')


class SessionContextProvider:
    def __init__(self, process: ProcessIdentity, *, maps_compatible=None):
        self.process = process
        self.context: SessionContext | None = None
        self.state = BaselineState.NO_BASELINE
        self.source = "UNKNOWN"
        self.capture_epoch = None
        self.continuity_generation = 0
        self._retired_epochs = []
        self.sequence = -1
        self.reason = "own_character_baseline_missing"
        self.revision = 0
        self.maps_compatible = maps_compatible or (lambda a, b: a == b)
        self.server_world_map_id = None
        self.local_ui_ready = False
        self.last_world_change_at = None
        self._field_coverage = {}
        self._packet_rebaseline_required = False

    def observe_addon(self, state: Mapping) -> None:
        from .packetio.context import evaluate_addon_context
        candidate = evaluate_addon_context(state).bind(self.process.selected_pid)
        if candidate is None:
            if state.get("loading") or state.get("player_present") is False:
                self.local_ui_ready = False
                self.invalidate("loading_or_player_absent")
            return
        if self._packet_rebaseline_required:
            return  # local UI cannot repair a missing world/quest/inventory delivery
        if self.context and (self.source == "PACKET_BASELINE" or self.server_world_map_id is not None):
            if (candidate.identity.character_guid != self.context.identity.character_guid
                    or candidate.identity.game_build != self.context.identity.game_build):
                self.invalidate("addon_packet_identity_mismatch", BaselineState.MISMATCH)
                return
            if not self.maps_compatible(candidate.world.instance_id, self.server_world_map_id):
                self.local_ui_ready = False
                self.reason = 'awaiting_matching_addon_world_context'
                return
            # UI map/phase are separate addon observations, not packet facts.
            world = WorldContext(candidate.world.instance_id, candidate.world.ui_map_id,
                                 candidate.world.phase)
            if self.state is BaselineState.READY:
                self._set(SessionContext(self.context.identity, world), self.source)
                sampled = state.get('monotonic_time')
                self.local_ui_ready = (self.last_world_change_at is None or type(sampled) in {int, float}
                                       and sampled >= self.last_world_change_at)
        elif self.state is not BaselineState.MISMATCH:
            self._set(candidate, "ADDON_MIGRATION")
            self.local_ui_ready = True

    def accept_baseline(self, event: Mapping) -> bool:
        from .packetio.validation import normalize_event, verified_semantics
        try:
            safe = normalize_event(dict(event))
        except (ValueError, TypeError, OverflowError):
            return False
        if (safe["event_type"] != "SESSION_BASELINE" or not verified_semantics(safe)
                or safe["selected_pid"] != self.process.selected_pid):
            return False
        body, source = safe["payload"], safe["provenance"]
        epoch, sequence = body["capture_epoch"], body["sequence"]
        if body["process_generation"] != self.process.generation or epoch in self._retired_epochs:
            return False
        if self.process.game_build is not None and source['game_build'] != self.process.game_build:
            self.invalidate('process_packet_build_mismatch', BaselineState.MISMATCH)
            return False
        if epoch == self.capture_epoch and sequence < self.sequence:
            return False
        if self.capture_epoch is not None and epoch != self.capture_epoch:
            # A new producer must supply a complete correlated login baseline.
            self.invalidate("capture_epoch_changed")
            self._retired_epochs = [*self._retired_epochs[-7:], self.capture_epoch]
        guid = body["character_guid"]
        if self.context and self.source == "ADDON_MIGRATION":
            if (guid != self.context.identity.character_guid
                    or source["game_build"] != self.context.identity.game_build):
                self.invalidate("addon_packet_identity_mismatch", BaselineState.MISMATCH)
                return False
            session_id = self.context.identity.session_id
            ui_map, phase = self.context.world.ui_map_id, self.context.world.phase
        elif (self.context and self.capture_epoch == epoch
              and self.context.identity.character_guid == guid
              and self.context.identity.game_build == source["game_build"]):
            session_id = self.context.identity.session_id
            ui_map, phase = self.context.world.ui_map_id, self.context.world.phase
        else:
            token = sha256((self.process.generation+":"+epoch+":"+guid).encode()).hexdigest()[:24]
            session_id, ui_map, phase = "packet-session:"+token, None, None
        if self.capture_epoch != epoch:
            self.continuity_generation += 1
            self._field_coverage.clear()
        self.capture_epoch, self.sequence = epoch, sequence
        instance = body['world_map_id']
        self.server_world_map_id = instance
        if self.context and self.maps_compatible(instance, self.context.world.instance_id):
            instance = self.context.world.instance_id
        elif self.context:
            ui_map, phase = None, None
            self.local_ui_ready = False
        self._set(SessionContext(SessionIdentity(self.process.selected_pid, session_id, guid,
                                                source["game_build"]),
                                 WorldContext(instance, ui_map, phase)), "PACKET_BASELINE")
        self._packet_rebaseline_required = False
        return True

    def require_packet_baseline(self, reason):
        """A lost semantic delivery may include a map/identity transition."""
        self._packet_rebaseline_required = True
        self.invalidate(reason)

    def advance_world(self, event):
        """Authenticated caller's server transition; UI readiness is separate."""
        from .packetio.validation import normalize_event, verified_semantics
        safe = normalize_event(event)
        if (self.context is None or self.state is not BaselineState.READY
                or safe['event_type'] != 'MAP_CHANGED' or not verified_semantics(safe)
                or safe['selected_pid'] != self.process.selected_pid
                or safe['provenance']['game_build'] != self.context.identity.game_build):
            return False
        raw = safe['payload'].get('world_map_id')
        if type(raw) is not int or not 0 <= raw < 2**16:
            return False
        instance = (self.context.world.instance_id if self.maps_compatible(raw, self.context.world.instance_id) else raw)
        self.server_world_map_id, self.local_ui_ready = raw, False
        self.last_world_change_at = event.get('sampled_at_monotonic')
        self._set(SessionContext(self.context.identity, WorldContext(instance, None, None)), self.source)
        return True

    def invalidate(self, reason: str, state=BaselineState.GAP):
        changed = self.state != state or self.reason != reason
        self.state, self.reason = state, reason
        self.local_ui_ready = False
        self._field_coverage.clear()
        if changed:
            self.revision += 1
            self.continuity_generation += 1

    def _set(self, context, source):
        if self.context is None or context.entity_scope() != self.context.entity_scope():
            self._field_coverage.clear()
            self.continuity_generation += 1
        if context != self.context or source != self.source or self.state is not BaselineState.READY:
            self.revision += 1
        self.context, self.source = context, source
        self.state, self.reason = BaselineState.READY, "ready"

    def expected(self, pid: int):
        if pid != self.process.selected_pid or self.state is not BaselineState.READY:
            return None
        return self.context.as_dict() if self.context else None

    def normalize_addon(self, payload):
        if not isinstance(payload, dict):
            return payload
        self.observe_addon(payload)
        return self.session_alias(payload)

    def session_alias(self, payload):
        """The packet-baseline session name for an addon sample, without
        observing it (the parallel control thread reads raw FAST samples).

        Live 2026-11-02 16:00: after a logout/login in the same capture the
        packet baseline kept its session while the addon started a new one;
        the medium tick was renamed but the parallel FAST lane was not, so
        every sample was "session_changed" and all walking ran stop-go on the
        medium lane (a ghost at ~3 yd/s)."""
        if not isinstance(payload, dict):
            return payload
        expected = self.expected(self.process.selected_pid)
        if expected and self.source == "PACKET_BASELINE":
            return {**payload, "session_id": expected["session_id"]}
        return payload

    def observe_field_coverage(self, field, completeness, sampled_at, *, context):
        """Baseline metadata only; WorldModel continues to own every value."""
        import math
        incoming = SessionContext.from_mapping(context)
        if (field not in {'own_health', 'questlog', 'inventory'}
                or completeness not in {'COMPLETE', 'PARTIAL', 'UNKNOWN'}
                or self.state is not BaselineState.READY or incoming is None
                or self.context is None or incoming.entity_scope() != self.context.entity_scope()
                or type(sampled_at) not in {int, float} or not math.isfinite(sampled_at)):
            return False
        previous = self._field_coverage.get(field)
        if previous and sampled_at < previous['observed_at']:
            return False
        self._field_coverage[field] = {'completeness': completeness, 'observed_at': sampled_at}
        return True

    def diagnostics(self):
        return {"state": self.state.value, "reason": self.reason, "source": self.source,
                "revision": self.revision, "capture_epoch": self.capture_epoch,
                'continuity_generation': self.continuity_generation,
                'packet_rebaseline_required': self._packet_rebaseline_required,
                "sequence": self.sequence, "process_generation": self.process.generation,
                'local_ui_ready': self.local_ui_ready, 'server_world_map_id': self.server_world_map_id,
                "context": self.expected(self.process.selected_pid),
                'coverage_samples': {key: dict(value) for key, value in self._field_coverage.items()},
                "coverage": {"own_identity": self.state.value, **{
                    key: self._field_coverage.get(key, {}).get('completeness', 'UNKNOWN')
                    for key in ('questlog', 'inventory', 'own_health')}}}
