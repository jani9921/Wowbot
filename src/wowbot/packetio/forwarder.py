from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import socket
import secrets
import threading
import time
from typing import Iterable

from .models import AgentPacketEvent
from .validation import ALLOWED_EVENTS, DIAGNOSTIC_EVENTS, normalize_event


DEFAULT_ALLOWED_EVENTS = ALLOWED_EVENTS - DIAGNOSTIC_EVENTS


class EventPolicy:
    def __init__(self, allowed_events: Iterable[str] = DEFAULT_ALLOWED_EVENTS, *, allow_unknown: bool = False):
        self.allowed_events = frozenset(str(value) for value in allowed_events)
        self.allow_unknown = bool(allow_unknown)

    def prepare(self, event: AgentPacketEvent) -> dict | None:
        if (event.event_type not in ALLOWED_EVENTS
                or event.event_type in DIAGNOSTIC_EVENTS and not self.allow_unknown):
            return None
        if event.event_type not in self.allowed_events and event.event_type not in DIAGNOSTIC_EVENTS:
            return None
        try:
            return normalize_event(event.to_dict())
        except (ValueError, TypeError, OverflowError):
            return None


class EventSink:
    def emit(self, event: AgentPacketEvent) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class UdpJsonForwarder(EventSink):
    def __init__(self, host: str = "127.0.0.1", port: int = 47651, *, policy: EventPolicy | None = None,
                 descriptor_path=None, process_generation=None):
        if host != "127.0.0.1":
            raise ValueError("packet forwarding is loopback-only")
        self.address = (host, int(port))
        self.descriptor_path = descriptor_path
        self.process_generation = process_generation
        self._descriptor = None
        self._descriptor_refresh = 0.
        self.policy = policy or EventPolicy()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0
        self.dropped = 0
        self._sender_id = secrets.token_hex(16)
        self._delivery_sequence = 0
        self._delivery_context = None
        self._send_lock = threading.Lock()

    def emit(self, event: AgentPacketEvent) -> bool:
        with self._send_lock:
            return self._emit(event)

    def _emit(self, event: AgentPacketEvent) -> bool:
        value = self.policy.prepare(event)
        if value is None:
            self.dropped += 1
            return False
        from .ipc import canonical, envelope, read_descriptor
        # Unsigned legacy messages cannot enter the live agent. Offline
        # recording does not need an endpoint and remains a separate sink.
        if self.descriptor_path is None:
            self.dropped += 1
            return False
        try:
            descriptor = self._current_descriptor()
            if (descriptor['context'].get('process_generation') is not None
                    and descriptor['context']['process_generation'] != self.process_generation):
                self.dropped += 1
                return False
            if descriptor["context"].get("selected_pid") != event.selected_pid:
                self.dropped += 1
                return False
            if descriptor["context"].get("bootstrap") is True:
                from .validation import verified_semantics
                if event.event_type != "SESSION_BASELINE" or not verified_semantics(value):
                    self.dropped += 1
                    return False
            if event.timestamp < descriptor["context"]["started_wall"]:
                self.dropped += 1
                return False
            if (event.semantic_status == "CONFIRMED" and descriptor["context"].get("bootstrap") is not True
                    and descriptor["context"].get("game_build") != event.provenance.get("game_build")):
                self.dropped += 1
                return False
        except (OSError, ValueError, TypeError, KeyError):
            self.dropped += 1
            return False
        return self._send_value(value,descriptor)

    def emit_progress(self, value):
        """Authenticated local control message, excluded from gameplay/JSONL."""
        from .stream_progress import normalize
        with self._send_lock:
            try:
                value=normalize(value)
                descriptor=self._current_descriptor()
                context=descriptor['context']
                if (context.get('bootstrap') or context.get('selected_pid')!=value['selected_pid']
                        or context.get('game_build')!=value['game_build']
                        or context.get('process_generation')!=value['process_generation']
                        or self.process_generation!=value['process_generation']
                        or value['timestamp']<context['started_wall']):
                    raise ValueError('out of scope decoder progress')
            except (OSError,ValueError,TypeError,KeyError):
                self.dropped+=1
                return False
            return self._send_value(value,descriptor)

    def _send_value(self, value, descriptor):
        from .ipc import canonical, envelope
        context_id = descriptor['context'].get('context_id')
        if context_id != self._delivery_context:
            self._delivery_context, self._delivery_sequence = context_id, 0
        self._delivery_sequence += 1
        encoded = canonical(envelope(value, descriptor, stream={
            'sender_id':self._sender_id, 'sequence':self._delivery_sequence}))
        address = descriptor['host'],descriptor['port']
        if len(encoded) > 60_000:
            self.dropped += 1
            return False
        self.socket.sendto(encoded, address)
        self.sent += 1
        return True

    def _current_descriptor(self) -> dict:
        from .ipc import read_descriptor
        now = time.monotonic()
        if self._descriptor is None or now >= self._descriptor_refresh:
            self._descriptor_refresh = now+.25
            self._descriptor = read_descriptor(self.descriptor_path)
        return self._descriptor

    def context_id(self) -> str | None:
        """The live runtime context the endpoint currently names, if any."""
        if self.descriptor_path is None:
            return None
        try:
            return str(self._current_descriptor()["context"].get("context_id") or "") or None
        except (OSError, ValueError, TypeError, KeyError):
            self._descriptor = None
            return None

    def entity_snapshot_request(self) -> int:
        """Runtime-owned recovery revision; never a new IPC/session identity."""
        try:
            revision = self._current_descriptor().get("entity_snapshot_request", 0)
            return revision if type(revision) is int and 0 <= revision < 2**63 else 0
        except (OSError, ValueError, TypeError, KeyError):
            return 0

    def close(self) -> None:
        self.socket.close()


class EntitySnapshot:
    """Latest server facts per entity GUID, for a runtime context that starts late.

    Live 2026-10-19 15:22:47: the login burst created every nearby object
    (five Harpy Totems among them) ~20 s before the agent's packet context
    existed; those creates were dropped and the agent never knew where the
    totems were.  The snapshot is re-sent, freshly stamped, to each new
    context.  It holds only allowlisted CONFIRMED entity events.
    """

    LIMIT = 2048
    SLOTS = {"ENTITY_CREATED": "created", "ENTITY_POSITION": "position",
             "ENTITY_FLAGS": "flags", "QUEST_GIVER_STATUS": "giver", "ENTITY_UNIT_UPDATE": "unit"}

    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.removed: dict[str, AgentPacketEvent] = {}

    def note(self, event: AgentPacketEvent) -> None:
        if event.event_type == "MAP_CHANGED":
            self.entities.clear()
            self.removed.clear()
            return
        guid = event.payload.get("entity_guid")
        if not guid or event.semantic_status != "CONFIRMED":
            return
        if event.event_type == "ENTITY_REMOVED":
            self.entities.pop(guid, None)
            self.removed.pop(guid, None)
            self.removed[guid] = event
            while len(self.removed) > self.LIMIT:
                self.removed.pop(next(iter(self.removed)))
            return
        slot = self.SLOTS.get(event.event_type)
        if slot is None:
            return
        if guid in self.removed:
            if slot != "created":
                return  # a late spline/flag update cannot undo a destroy
            self.removed.pop(guid, None)
        entry = self.entities.pop(guid, {})
        if slot == "created":
            entry.pop("position", None)          # a new create supersedes older moves
        entry[slot] = event
        self.entities[guid] = entry
        while len(self.entities) > self.LIMIT:
            self.entities.pop(next(iter(self.entities)))

    @staticmethod
    def _settled(event: AgentPacketEvent, now_wall: float) -> dict:
        payload = dict(event.payload)
        duration = payload.get("move_time_ms")
        if "destination_x" not in payload or not duration:
            return payload
        progress = max(0., min(1., (now_wall-event.timestamp)*1000./duration))
        for axis in ("x", "y", "z"):
            target = payload["destination_" + axis]
            payload[axis] = payload[axis]+(target-payload[axis])*progress
        if progress >= 1.:
            for key in ("destination_x", "destination_y", "destination_z", "move_time_ms"):
                payload.pop(key, None)
        else:
            payload["move_time_ms"] = int(duration*(1.-progress))
        return payload

    RESTAMPABLE = frozenset(SLOTS) | {"ENTITY_REMOVED"}

    @classmethod
    def restamp(cls, event: AgentPacketEvent, now_wall: float) -> AgentPacketEvent:
        """The same still-current fact, stamped now (a spline at its current point)."""
        payload = (cls._settled(event, now_wall) if event.event_type == "ENTITY_POSITION"
                   else event.payload)
        return AgentPacketEvent.create(
            pid=event.selected_pid, flow_id=event.flow_id, direction=event.direction,
            event_type=event.event_type, timestamp=now_wall,
            semantic_status=event.semantic_status, opcode=event.opcode,
            payload=payload, provenance=event.provenance, confidence=event.confidence)

    def replay(self, now_wall: float) -> list[AgentPacketEvent]:
        active = [self.restamp(entry[slot], now_wall)
                  for entry in list(self.entities.values())
                  for slot in ("created", "position", "flags", "giver", "unit") if entry.get(slot) is not None]
        return active + [self.restamp(event, now_wall) for event in list(self.removed.values())]


class SnapshotReplayForwarder(EventSink):
    """Forward to the runtime; re-send the entity snapshot to every new context."""

    REPLAY_BATCH = 64
    REPLAY_INTERVAL = .5

    def __init__(self, forwarder: UdpJsonForwarder, *, wall_clock=time.time):
        from .quest_poi_snapshot import QuestPoiSnapshot
        self.forwarder = forwarder
        self.snapshot = EntitySnapshot()
        self.quest_pois = QuestPoiSnapshot()
        self.session_baseline = None
        self.wall_clock = wall_clock
        self._context_id = None
        self._snapshot_request = 0
        self.replayed = 0
        self._pending_replay = deque()
        self._next_replay_at = 0.

    def emit(self, event: AgentPacketEvent) -> bool:
        context_id = self._prepare_replay()
        self.snapshot.note(event)
        self.quest_pois.note(event)
        if event.event_type == "SESSION_BASELINE":
            from .validation import verified_semantics
            if verified_semantics(event.to_dict()):
                self.session_baseline = event
        elif event.event_type == "MAP_CHANGED" and self.session_baseline is not None:
            from .validation import verified_semantics
            if verified_semantics(event.to_dict()):
                from dataclasses import replace
                previous = self.session_baseline
                self.session_baseline = replace(previous, payload={**previous.payload,
                    "world_map_id": event.payload["world_map_id"],
                    "sequence": previous.payload["sequence"]+1})
        self.flush()
        sent = self.forwarder.emit(event)
        if (not sent and context_id is not None and event.semantic_status == "CONFIRMED"
                and event.event_type in EntitySnapshot.RESTAMPABLE):
            # Only producer-owned current entity facts may be restamped;
            # never movement/quest credit/combat or an old inbox record.
            sent = self.forwarder.emit(self.snapshot.restamp(event, self.wall_clock()))
            self.replayed += int(sent)
        if not sent and context_id is not None and event.event_type == 'QUEST_POI_UPDATE':
            current = self.quest_pois.replay(event.payload.get('quest_id'), self.wall_clock())
            if current is not None:
                sent = self.forwarder.emit(current)
                self.replayed += int(sent)
        return sent

    def reset_capture(self):
        """A rotated capture cannot replay the previous decoder's objects."""
        from .quest_poi_snapshot import QuestPoiSnapshot
        self.snapshot=EntitySnapshot()
        self.quest_pois=QuestPoiSnapshot()
        self.session_baseline=None
        self._pending_replay.clear()
        self._context_id=None
        self._next_replay_at=0.

    def _prepare_replay(self):
        context_id = self.forwarder.context_id()
        request = getattr(self.forwarder, "entity_snapshot_request", lambda: 0)()
        if context_id is None:
            self._context_id = None
            self._pending_replay.clear()
            return None
        if context_id is not None and (context_id != self._context_id or request != self._snapshot_request):
            if context_id != self._context_id:
                self._next_replay_at = 0.
            self._context_id = context_id
            self._snapshot_request = request
            # Store references, not freshly stamped events waiting in a FIFO.
            # Active facts lead historical removals; every send reads today's
            # cache so a destroy/create while replaying cannot be undone.
            self._pending_replay = deque(
                ([(None, 'session_baseline')] if self.session_baseline is not None else [])
                + [(quest_id, 'quest_poi') for quest_id in self.quest_pois.events]
                + [(guid, slot) for guid, entry in self.snapshot.entities.items()
                 for slot in ("created", "position", "flags", "giver", "unit") if slot in entry]
                + [(guid, "removed") for guid in self.snapshot.removed])
        return context_id

    def flush(self):
        if self._prepare_replay() is None:
            return
        now = self.wall_clock()
        if now < self._next_replay_at:
            return
        self._next_replay_at = now+self.REPLAY_INTERVAL
        for _ in range(min(self.REPLAY_BATCH, len(self._pending_replay))):
            guid, slot = self._pending_replay.popleft()
            if slot == 'session_baseline':
                # Identity/world scope only. Never freshen an own position,
                # movement ACK, quest credit, health, or inventory baseline.
                from dataclasses import replace
                import secrets
                event = replace(self.session_baseline, timestamp=now, event_id=secrets.token_hex(12))
                self.replayed += int(self.forwarder.emit(event))
                continue
            if slot == 'quest_poi':
                current = self.quest_pois.replay(guid, now)
                if current is not None:
                    self.replayed += int(self.forwarder.emit(current))
                continue
            current = (self.snapshot.removed.get(guid) if slot == "removed"
                       else self.snapshot.entities.get(guid, {}).get(slot))
            if current is not None:
                self.replayed += int(self.forwarder.emit(self.snapshot.restamp(current, now)))

    def close(self) -> None:
        self.forwarder.close()


class JsonlEventRecorder(EventSink):
    def __init__(self, path: str | Path, *, policy: EventPolicy | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy or EventPolicy(allow_unknown=True)
        self._lock = threading.Lock()

    def emit(self, event: AgentPacketEvent) -> bool:
        value = self.policy.prepare(event)
        if value is None:
            return False
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
        return True


class CompositeSink(EventSink):
    def __init__(self, *sinks: EventSink):
        self.sinks = tuple(sinks)

    def emit(self, event: AgentPacketEvent) -> bool:
        emitted = False
        for sink in self.sinks:
            emitted = sink.emit(event) or emitted
        return emitted

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()

    def flush(self) -> None:
        for sink in self.sinks:
            flush = getattr(sink, "flush", None)
            if callable(flush):
                flush()


class InMemorySink(EventSink):
    def __init__(self, limit: int = 1024):
        self.events = deque(maxlen=limit)

    def emit(self, event: AgentPacketEvent) -> bool:
        self.events.append(event)
        return True
