"""Bounded loopback inbox scoped to the selected runtime AND addon context."""
from __future__ import annotations

from collections import deque
import json
import secrets
import socket
import threading
import time

from .ipc import verify
from .validation import normalize_event
from .delivery import DeliveryContinuity

# Live 2026-10-31 (logins, Westfall): the agent drains this inbox slowly while
# it starts and the client loads; the quest POI answers the server sends once
# per login expired here after 2 s and never came back (the client queries
# POIs only at login and on accept).  A POI is static quest geometry with its
# own lifetime (world_packet_reducer.QUEST_POI_MAX_AGE); every other event
# keeps the 2 s rule.
LONG_LIVED_EVENT_AGE = {"QUEST_POI_UPDATE": 1800.}


def max_event_age(event_type, default: float = 2.) -> float:
    return LONG_LIVED_EVENT_AGE.get(event_type, default)


class PacketEventInbox:
    MAX_EVENT_AGE = 2.

    def __init__(self, selected_pid, host="127.0.0.1", port=47651, *, max_queue=4096,
                 autostart=True, wall_clock=time.time, clock=time.monotonic):
        if host != "127.0.0.1" or int(selected_pid) <= 0 or not 1 <= max_queue <= 16384:
            raise ValueError("positive selected PID, loopback and bounded queue required")
        self.selected_pid = int(selected_pid)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind((host, int(port)))
            self.socket.settimeout(.1)
        except BaseException:
            self.socket.close()
            raise
        self._descriptor = {"schema": "aipc.packet-endpoint.v1", "host": host,
            "port": self.socket.getsockname()[1], "ipc_key": secrets.token_urlsafe(32), "context": None}
        self._wall_clock, self._clock = wall_clock, clock
        self.queue = deque(maxlen=max_queue)
        self._movement = {}
        self._states = {}
        self._entities = {}
        self._progress = {}
        self._stale_counts = [0, 0]
        self._lock = threading.Lock()
        self._seen = deque(maxlen=max_queue*2)
        self._seen_set = set()
        self._stop = threading.Event()
        self._thread = None
        self.received = self.rejected = self.dropped = self.coalesced = self.duplicates = 0
        self.last_received_at = self.last_error = None
        self._sequence = 0
        self._delivery = DeliveryContinuity()
        if autostart:
            self._thread = threading.Thread(target=self._receive, name="aipc-packet-inbox", daemon=True)
            self._thread.start()

    def configure(self, context):
        """Only the runtime adapter calls this, from authoritative addon fields."""
        with self._lock:
            if context != self._descriptor["context"]:
                self.queue.clear()
                self._movement.clear()
                self._states.clear()
                self._entities.clear()
                self._progress.clear()
                self._stale_counts[:] = [0, 0]
                self._seen.clear()
                self._seen_set.clear()
                self._delivery.reset()
                self.last_received_at = None  # an old context cannot look like fresh receipt
                self._descriptor["context"] = dict(context) if context else None
            return {**self._descriptor, "context": dict(context) if context else None}

    def _receive(self):
        while not self._stop.is_set():
            try:
                raw, address = self.socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    self.last_error = "packet_receive_failed"
                return
            self.ingest_datagram(raw, address)

    def ingest_datagram(self, raw, address=("127.0.0.1", 0)):
        try:
            if address[0] != "127.0.0.1" or len(raw) > 60000:
                raise ValueError("invalid packet datagram")
            value = json.loads(raw.decode("utf-8"))
            with self._lock:
                context = self._descriptor["context"]
                if not context:
                    raise ValueError("waiting_for_addon_context")
                verified=verify(value,self._descriptor)
                from .stream_progress import SCHEMA as PROGRESS_SCHEMA, inbox_record
                control=isinstance(verified,dict) and verified.get('schema')==PROGRESS_SCHEMA
                if control and value.get('schema')!='aipc.packet-envelope.v2':
                    raise ValueError('progress requires sequenced IPC')
                event=inbox_record(verified) if control else normalize_event(verified)
                if event["selected_pid"] != self.selected_pid:
                    raise ValueError("different_selected_pid")
                wall, now = self._wall_clock(), self._clock()
                age = wall-event["timestamp"]
                if (not -.1 <= age <= max_event_age(event.get("event_type"), self.MAX_EVENT_AGE)
                        or event["timestamp"] < context["started_wall"]):
                    raise ValueError("stale_or_future_packet")
                stream = value.get('stream') if value.get('schema') == 'aipc.packet-envelope.v2' else None
                if not self._delivery.accept(stream):
                    self.duplicates += 1
                    return False
                if event["event_id"] in self._seen_set:
                    self.duplicates += 1
                    return False
                if len(self._seen) == self._seen.maxlen:
                    self._seen_set.discard(self._seen.popleft())
                self._seen.append(event["event_id"])
                self._seen_set.add(event["event_id"])
                self._sequence += 1
                event = {**event, "ipc_context": dict(context), "received_at_monotonic": now,
                         "sampled_at_monotonic": now-max(0., age), "receive_sequence": self._sequence,
                         'delivery_stream':dict(stream) if stream else None,
                         'delivery_state':self._delivery.state}
                movement = event["event_type"] == "MOVEMENT_UPDATE" and not event["payload"].get("teleport")
                from .validation import ENTITY_EVENTS
                if control:
                    self._progress={'latest':event}  # cumulative watermark, no semantic delta is lost
                elif event["event_type"] in ENTITY_EVENTS:
                    self._queue_entity(event)
                elif (event['event_type'] == 'OWN_POWER_UPDATE' or event['event_type'] in {'OWN_UNIT_UPDATE', 'OWN_PROFILE_UPDATE'}
                      and event['payload'].get('sample_kind') != 'CREATE'):
                    fields = tuple(sorted(set(event['payload'])-{'mover_guid', 'world_map_id', 'sample_kind'}))
                    key = (event['flow_id'], event['event_type'], event['payload'].get('mover_guid'),
                           event['payload'].get('power_type'), fields, event['provenance'].get('capture_epoch'))
                    previous = self._states.get(key)
                    if previous and previous['timestamp'] > event['timestamp']:
                        raise ValueError('out_of_order_state')
                    if previous:
                        self.coalesced += 1
                    if len(self._states) >= 256 and key not in self._states:
                        self._states.pop(next(iter(self._states)))
                        self.dropped += 1
                        self._delivery.lost('state_mailbox_overflow')
                    self._states[key] = event
                elif movement:
                    # Only the newest position per mover/server entity matters;
                    # nearby walking mobs must not flood the discrete queue.
                    key = (event["flow_id"], event["payload"].get("mover_guid"), event["direction"],
                           event['provenance'].get('capture_epoch'))
                    previous = self._movement.get(key)
                    if previous is not None:
                        if previous["timestamp"] > event["timestamp"]:
                            raise ValueError("out_of_order_movement")
                        self.coalesced += 1
                    if len(self._movement) >= 256 and key not in self._movement:
                        self._movement.pop(next(iter(self._movement)))
                        self.dropped += 1
                        self._delivery.lost('movement_mailbox_overflow')
                    self._movement[key] = event
                else:
                    if event["event_type"] == "MAP_CHANGED" or event["payload"].get("teleport"):
                        epoch = event['provenance'].get('capture_epoch')
                        for mailbox in (self._movement, self._states, self._entities):
                            obsolete = [k for k,e in mailbox.items() if e['provenance'].get('capture_epoch') == epoch]
                            for key in obsolete: mailbox.pop(key)
                    if len(self.queue) == self.queue.maxlen:
                        self.dropped += 1
                        self._delivery.lost('event_mailbox_overflow')
                    self.queue.append(event)
                self.received += 1
                self.last_received_at = now
                return True
        except (ValueError, TypeError, OverflowError, KeyError, RecursionError, UnicodeDecodeError):
            self.rejected += 1
            # Never echo sender-controlled raw strings into logs/status.
            self.last_error = "invalid_or_out_of_scope_packet"
            return False

    def _queue_entity(self, event):
        """Latest state per GUID/kind; lifecycle barriers cannot be reordered.

        Entity snapshot retries are state, not thousands of discrete events.
        Combat, quest, loot, teleport etc. retain the separate FIFO unchanged.
        Caller owns _lock and has authenticated/validated the event already.
        """
        guid, kind = event["payload"].get("entity_guid"), event["event_type"]
        epoch = event['provenance'].get('capture_epoch')
        key = (guid, kind, epoch)
        previous = self._entities.get(key)
        if previous is not None and previous["timestamp"] > event["timestamp"]:
            raise ValueError("out_of_order_entity_state")
        if kind in {"ENTITY_CREATED", "ENTITY_REMOVED"}:
            obsolete = [slot for slot in self._entities if slot[0] == guid and slot[2] == epoch]
            for slot in obsolete:
                self._entities.pop(slot)
                self.coalesced += 1
        elif (guid, "ENTITY_REMOVED", epoch) in self._entities:
            self.coalesced += 1
            return  # late position/flags cannot resurrect a removed entity
        previous = self._entities.pop(key, None)
        if previous is not None:
            self.coalesced += 1
        if len(self._entities) >= self.queue.maxlen:
            self._entities.pop(next(iter(self._entities)))
            self.dropped += 1
            self._delivery.lost('entity_mailbox_overflow')
        self._entities[key] = event

    def poll(self, limit=128):
        limit = max(0, min(512, int(limit)))
        with self._lock:
            # Old queued state must not hide fresh input behind 4096 stale
            # snapshot records. Keep the original clock; never restamp here.
            from .validation import ENTITY_EVENTS
            now = self._clock()
            def fresh(event, loss=True):
                if now-event["sampled_at_monotonic"] <= max_event_age(event.get("event_type"), self.MAX_EVENT_AGE):
                    return True
                self._stale_counts[0] += 1
                self._stale_counts[1] += int(event["event_type"] in ENTITY_EVENTS
                                             and event.get("semantic_status") == "CONFIRMED")
                if loss:
                    self._delivery.lost('queued_sample_expired')
                return False
            # Live 2026-10-31 (logins, Westfall): while the agent drained this
            # inbox late, 182 expired positions were each a delivery loss; each
            # loss re-baselined the session and discarded the whole batch, the
            # login's quest POI answers with it.  The movement and entity
            # mailboxes hold only the newest sample per key: an expired one is a
            # stale sample (a newer one replaces it; stale entities request a
            # snapshot), not a lost delta.  Discrete events, own-state fields
            # and progress still make a delivery gap.
            self.queue = deque((e for e in self.queue if fresh(e)), maxlen=self.queue.maxlen)
            self._movement = {k: e for k, e in self._movement.items() if fresh(e, loss=False)}
            self._states = {k: e for k, e in self._states.items() if fresh(e)}
            self._entities = {k: e for k, e in self._entities.items() if fresh(e, loss=False)}
            self._progress = {k:e for k,e in self._progress.items() if fresh(e)}
            events = sorted([*self.queue, *self._movement.values(), *self._entities.values(), *self._states.values(), *self._progress.values()],
                            key=lambda e: e["receive_sequence"])
            output = events[:limit]
            consumed = {event["event_id"] for event in output}
            self.queue = deque((e for e in self.queue if e["event_id"] not in consumed), maxlen=self.queue.maxlen)
            self._movement = {k: e for k, e in self._movement.items() if e["event_id"] not in consumed}
            self._states = {k: e for k, e in self._states.items() if e['event_id'] not in consumed}
            self._entities = {k: e for k, e in self._entities.items() if e["event_id"] not in consumed}
            self._progress = {k:e for k,e in self._progress.items() if e['event_id'] not in consumed}
            return output

    def peek_movement(self, direction="CLIENT_TO_SERVER"):
        """Newest queued movement per mover in one direction, NOT consumed.

        The medium tick drains this inbox at 1-3 Hz; a flight loop needs the
        client's own newest sample between those polls (user 2026-10-25)."""
        with self._lock:
            now = self._clock()
            return [dict(event) for event in self._movement.values()
                    if event["direction"] == direction
                    and now-event["sampled_at_monotonic"] <= self.MAX_EVENT_AGE]

    def take_stale_counts(self):
        with self._lock:
            result = tuple(self._stale_counts)
            self._stale_counts[:] = [0, 0]
            return result

    def diagnostics(self):
        with self._lock:
            return {"status": "listening" if self._descriptor["context"] else "waiting_for_addon_context",
                "selected_pid": self.selected_pid, "received": self.received, "rejected": self.rejected,
                "duplicates": self.duplicates, "dropped": self.dropped, "coalesced": self.coalesced,
                "queued": len(self.queue)+len(self._movement)+len(self._entities)+len(self._states)+len(self._progress),
                'queued_progress':len(self._progress),
                'queued_states': len(self._states),
                "queued_entities": len(self._entities), "last_received_at": self.last_received_at,
                "last_error": self.last_error, 'delivery':self._delivery.snapshot()}

    def delivery_status(self):
        with self._lock:
            return self._delivery.snapshot()

    def close(self):
        self._stop.set()
        self.socket.close()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.)
