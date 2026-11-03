"""Optional passive sensor adapter; no skill, input or planner ownership."""
from __future__ import annotations

import os
import math
import secrets
import time

from .models import Observation
from wowbot.context_contracts import ContextState, SessionContext
from wowbot.packetio.context import evaluate_addon_context, reported_game_build


class RuntimePacketSource:
    """Mailbox lifecycle runs alongside the existing runtime, disabled by default.

    The endpoint key is our local IPC capability, never a WoW auth/session key.
    No capture process, driver installation or PKT producer is launched here.
    """

    SNAPSHOT_RETRY_SECONDS = 5.
    SNAPSHOT_MAX_ATTEMPTS = 3
    RECOVERY_HEALTHY_SECONDS = 5.

    def __init__(self, pid, output, source=None, *, wall_clock=time.time,
                 session_provider=None, independent_context=False):
        self.pid, self.source = pid, source
        self.session_provider = session_provider
        self.independent_context = independent_context or session_provider is not None
        self.path = output / "packet_endpoint.json"
        self.runtime_id = secrets.token_hex(16)
        self.wall_clock = wall_clock
        self.context = self.signature = None
        self.session_context = None
        self.context_status = "waiting_for_addon_context"
        self.context_state = ContextState.PENDING
        self.missing_context_fields = ()
        self.observed_game_build = None
        self.error = None
        self.started = False
        self.closed = False
        self.observations_emitted = 0
        self.stale_event_discards = self.stale_entity_discards = self.wrong_context_discards = 0
        self.invalid_time_discards = 0
        self.capture_epoch_discards = 0
        self.capture_epoch_error = None
        self.entity_snapshot_requests = 0
        self.entity_snapshot_request_error = None
        self._last_snapshot_request_at = None
        self._snapshot_request_pending = False
        self._snapshot_attempts = 0
        self._snapshot_healthy_since = None
        self.last_accepted_at = None
        self.delivery_losses = 0
        self.delivery_loss_reason = None
        self._delivery_loss_generation = 0
        self._collection_delivery_ids = []
        self._progress_sequence = 0
        self.enabled = source is not None or os.environ.get("AIPC_PACKET_TELEMETRY", "0").lower() in {"1", "true", "yes", "on"}

    def start(self):
        if self.started or not self.enabled:
            return
        self.started = True
        try:
            if self.independent_context and self.session_provider is None:
                self.context_status = 'selected_process_metadata_pending'
                from wowbot.packetio.process_identity import selected_process_identity
                from wowbot.session_context import SessionContextProvider
                from .world_packet_reducer import same_world_map
                self.session_provider = SessionContextProvider(selected_process_identity(self.pid), maps_compatible=same_world_map)
                self.context_status = 'waiting_for_session_baseline'
            if self.source is None:
                from wowbot.packetio.inbox import PacketEventInbox
                self.source = PacketEventInbox(self.pid, port=int(os.environ.get("AIPC_PACKET_PORT", "47651")))
        except (OSError, ValueError, AttributeError):
            self.error = ('selected_process_metadata_unavailable'
                          if self.context_status == 'selected_process_metadata_pending' else 'packet_inbox_unavailable')
            if self.source is not None:
                self.source.close()
            self.source = None  # this optional sensor cannot break GUI/client startup

    def observations(self, payload, world, current):
        if self.source is None or self.closed:
            return ()
        try:
            return self._observations(payload, world, current)
        except Exception:
            self.error = "packet_sensor_failed"
            return ()

    def _observations(self, payload, world, current):
        from adapters.atomic_file import write_json_replace
        self._observe_delivery(world)
        state = {**world.addon_state, **(payload or {})}
        if self.session_provider is not None:
            self.session_provider.observe_addon(state)
            world.session_context_provider = self.session_provider
            expected = self.session_provider.expected(self.pid)
            self.session_context = SessionContext.from_mapping(expected)
            self.context_status = self.session_provider.reason
            self.context_state = ContextState.VALID if expected else ContextState.PENDING
            self.observed_game_build = (expected or {}).get("game_build")
            signature = {**(expected or {"selected_pid": self.pid, "bootstrap": True}),
                         "process_generation": self.session_provider.process.generation}
            self._configure(signature)
            return self._read_events(current, world)
        evaluation = evaluate_addon_context(state)
        self.context_status = evaluation.reason
        self.context_state = evaluation.state
        self.missing_context_fields = evaluation.missing_fields
        self.observed_game_build = reported_game_build(state)
        self.session_context = evaluation.bind(self.pid)
        if evaluation.state is ContextState.VALID and self.session_context is None:
            self.context_status = "invalid_selected_pid"
            self.context_state = ContextState.MISMATCH
        signature = self.session_context.as_dict() if self.session_context else None
        self._configure(signature)
        return self._read_events(current, world)

    def _observe_delivery(self, world):
        read = getattr(self.source, 'delivery_status', None)
        if not callable(read):
            return False  # old sources cannot claim retained-state continuity
        status = read()
        generation = status.get('loss_generation')
        if type(generation) is not int or generation <= self._delivery_loss_generation:
            return False
        self.delivery_losses += generation-self._delivery_loss_generation
        self._delivery_loss_generation = generation
        self.delivery_loss_reason = status.get('last_loss')
        if self.session_provider is None:
            # Explicit migration mode retains its existing current-entity
            # recovery, but never carries old native fields across a loss.
            world.discard_packet_fields()
        else:
            world.session_context_provider = self.session_provider
            self.session_provider.require_packet_baseline('ipc_delivery_discontinuity')
            self._configure({'selected_pid':self.pid, 'bootstrap':True,
                             'process_generation':self.session_provider.process.generation})
        return self.session_provider is not None

    @staticmethod
    def _transport_scope(signature):
        return None if signature is None else {k: v for k, v in signature.items() if k != "map_id"}

    def _configure(self, signature):
        from adapters.atomic_file import write_json_replace
        if (signature is not None and self.context is not None
                and self._transport_scope(signature) == self._transport_scope(self.signature)):
            return  # a UI-map step in the same world keeps the transport nonce (see world_packet_reducer)
        if signature != self.signature or self.context is None and signature is not None:
            self.signature = signature
            self.context = ({**signature, "runtime_id": self.runtime_id,
                "context_id": secrets.token_hex(12), "started_wall": self.wall_clock()} if signature else None)
            descriptor = self.source.configure(self.context)
            self._last_snapshot_request_at = None
            self._snapshot_request_pending = False
            self._snapshot_attempts = 0
            self._snapshot_healthy_since = None
            self.last_accepted_at = None
            self.entity_snapshot_request_error = None
            self._collection_delivery_ids = []
            self._progress_sequence = 0
            try:
                write_json_replace(self.path, descriptor if self.context else {
                    "schema": "aipc.packet-endpoint.v1", "status": "inactive", "context": None})
            except OSError:
                self.error = "packet_endpoint_write_failed"

    def _read_events(self, current, world=None):
        events = self.source.poll(limit=128)
        take_stale = getattr(self.source, "take_stale_counts", None)
        stale_total, stale_entity_count = take_stale() if callable(take_stale) else (0, 0)
        self.stale_event_discards += stale_total
        self.stale_entity_discards += stale_entity_count
        if world is not None and self._observe_delivery(world):
            return ()  # discard a batch that lost its complete delivery history
        if self.context is None:
            return ()
        observations = []
        stale_entities = stale_entity_count > 0
        from wowbot.packetio.validation import ENTITY_EVENTS
        for event in events:
            if event.get("ipc_context") != self.context:
                self.wrong_context_discards += 1
                continue
            sampled = event.get("sampled_at_monotonic")
            if type(sampled) not in {int, float} or not math.isfinite(sampled) or current < sampled:
                self.invalid_time_discards += 1
                continue
            from .world_packet_reducer import freshness_limit
            if current-sampled > freshness_limit(event.get("event_type")):
                self.stale_event_discards += 1
                if event.get("event_type") in ENTITY_EVENTS and event.get("semantic_status") == "CONFIRMED":
                    self.stale_entity_discards += 1
                    stale_entities = True
                continue
            if event.get("event_type") == "SESSION_BASELINE" and self.session_provider is not None:
                if self.session_provider.accept_baseline(event):
                    self.capture_epoch_error = None
                    self._configure({**self.session_provider.expected(self.pid),
                                     "process_generation": self.session_provider.process.generation})
                continue
            if self.context.get("bootstrap") is True:
                continue
            if event.get('event_type')=='SOURCE_PROGRESS':
                if self.session_provider is not None and event.get('delivery_state')=='CONTIGUOUS':
                    from .runtime_packet_progress import observation as progress_observation
                    observations.append(progress_observation(event,self.context,self.session_provider,
                        self._collection_delivery_ids,self._progress_sequence))
                    self._collection_delivery_ids=[]
                    self._progress_sequence=event['delivery_stream']['sequence']
                continue
            if (self.session_provider is not None and self.session_provider.capture_epoch is not None
                    and event.get('semantic_status') == 'CONFIRMED'
                    and (event.get('provenance') or {}).get('capture_epoch') != self.session_provider.capture_epoch):
                self.wrong_context_discards += 1
                self.capture_epoch_discards += 1
                self.capture_epoch_error = ('capture_epoch_missing' if not (event.get('provenance') or {}).get('capture_epoch')
                                            else 'capture_epoch_mismatch')
                continue
            observations.append(self._observation(event))
            from wowbot.packetio.stream_progress import COLLECTION_EVENTS
            if event.get('event_type') in COLLECTION_EVENTS:
                if len(self._collection_delivery_ids)<1024:
                    self._collection_delivery_ids.append(event['event_id'])
                else:
                    self._collection_delivery_ids=['collection_proof_budget_exceeded']
            if event.get("semantic_status") == "CONFIRMED":
                self.capture_epoch_error = None
                self.last_accepted_at = sampled
        if stale_entities:
            self._snapshot_request_pending = True
            self._snapshot_healthy_since = None
        elif observations:
            if self._snapshot_healthy_since is None:
                self._snapshot_healthy_since = current
            elif current-self._snapshot_healthy_since >= self.RECOVERY_HEALTHY_SECONDS:
                self._snapshot_attempts = 0
                self._snapshot_request_pending = False
                self.entity_snapshot_request_error = None
        elif self.last_accepted_at is None or current-self.last_accepted_at > 2.:
            self._snapshot_healthy_since = None
        if self._snapshot_request_pending:
            self._request_entity_snapshot(current)
        self.observations_emitted += len(observations)
        return tuple(observations)

    def _observation(self, event):
        return Observation.create({
            "session_id": self.context["session_id"], "timestamp": event["timestamp"],
            "frame_id": "packet:"+event["event_id"], "packet_event": event,
            "packet_context": self.context, "confidence": event["confidence"],
            "provenance": {"producer": "RuntimePacketSource", "selected_pid": self.pid,
                "independence_group": "packet-record:"+(event.get('provenance') or {}).get('semantic_record_id',event['event_id'])},
        }, event["received_at_monotonic"], "PACKET_TELEMETRY")

    def peek_own_movement(self, world, current) -> bool:
        """Fast-lane flight feedback: the newest client movement, not consumed.

        Called by the fast control lane under the agent lock; the medium tick
        still polls and applies the same event (see
        ``WorldPacketReducer.peek_own_movement``)."""
        peek = getattr(self.source, "peek_movement", None)
        if self._observe_delivery(world) or (self.session_provider is not None
                and self.session_provider.expected(self.pid) is None):
            return False
        if self.closed or self.context is None or not callable(peek):
            return False
        from .world_packet_reducer import WorldPacketReducer
        updated = False
        try:
            for event in peek():
                sampled = event.get("sampled_at_monotonic")
                if (event.get("ipc_context") != self.context or type(sampled) not in {int, float}
                        or not math.isfinite(sampled) or not 0 <= current-sampled <= 2.):
                    continue
                updated = WorldPacketReducer.peek_own_movement(world, self._observation(event)) or updated
        except Exception:
            self.error = "packet_sensor_failed"
            return False
        return updated

    def _request_entity_snapshot(self, current):
        """Recover a startup backlog from the producer's *current* entity cache.

        Do not freshen queued movement/quest/combat or weaken the two-second
        input gate. The existing authenticated producer replays only its
        still-current, bounded entity facts in the same PID/session/map context.
        """
        previous = self._last_snapshot_request_at
        interval = self.SNAPSHOT_RETRY_SECONDS * 2**max(0, self._snapshot_attempts-1)
        if self.context is None or (previous is not None and 0 <= current-previous < interval):
            return
        if self._snapshot_attempts >= self.SNAPSHOT_MAX_ATTEMPTS:
            self.entity_snapshot_request_error = "snapshot_recovery_exhausted"
            return
        self._last_snapshot_request_at = current
        self._snapshot_attempts += 1
        try:
            from adapters.atomic_file import write_json_replace
            # configure(same_context) is idempotent: retain the inbox queue,
            # key and context, unlike inventing a new session to force replay.
            descriptor = self.source.configure(self.context)
            request = self.entity_snapshot_requests + 1
            write_json_replace(self.path, {**descriptor, "entity_snapshot_request": request})
            self.entity_snapshot_requests = request
            self._snapshot_request_pending = False
            self.entity_snapshot_request_error = None
        except Exception:
            self.entity_snapshot_request_error = "entity_snapshot_request_failed"

    def diagnostics(self):
        try:
            source = self.source.diagnostics() if self.source is not None else {}
        except Exception:
            source = {"status": "packet_diagnostics_failed"}
        result = {"enabled": self.enabled, "error": self.error,
            "session_provider": self.session_provider.diagnostics() if self.session_provider else None,
            "observations_emitted": self.observations_emitted,
            "stale_event_discards": self.stale_event_discards,
            "stale_entity_discards": self.stale_entity_discards,
            "wrong_context_discards": self.wrong_context_discards,
            "invalid_time_discards": self.invalid_time_discards,
            'capture_epoch_discards': self.capture_epoch_discards,
            'capture_epoch_error': self.capture_epoch_error,
            'delivery_losses': self.delivery_losses,
            'delivery_loss_reason': self.delivery_loss_reason,
            'source_restart_required': self.capture_epoch_error == 'capture_epoch_missing',
            "entity_snapshot_requests": self.entity_snapshot_requests,
            "entity_snapshot_request_error": self.entity_snapshot_request_error,
            "entity_snapshot_request_pending": self._snapshot_request_pending,
            "entity_snapshot_attempts": self._snapshot_attempts,
            "last_accepted_at": self.last_accepted_at,
            "game_build": (self.context or {}).get("game_build"),
            "observed_game_build": self.observed_game_build, "context_status": self.context_status,
            "context_state": self.context_state.value, "missing_context_fields": list(self.missing_context_fields),
            "endpoint": str(self.path) if self.source is not None else None,
            "status": "disabled", **source}
        if self.context is None and self.source is not None:
            result["status"] = self.context_status
        if self.error:
            result["status"] = "unavailable"
        elif self.capture_epoch_error:
            result['status'] = ('source_restart_required' if result['source_restart_required']
                                else 'waiting_for_current_capture_epoch')
        if self.closed:
            result["status"] = "closed"
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.source is None:
            return
        try:
            self.source.configure(None)
        except Exception:
            self.error = "packet_close_failed"
        try:
            self.source.close()
        except Exception:
            self.error = "packet_close_failed"
        try:
            from adapters.atomic_file import write_json_replace
            write_json_replace(self.path, {"schema": "aipc.packet-endpoint.v1", "status": "closed", "context": None})
        except OSError:
            self.error = "packet_endpoint_close_write_failed"
