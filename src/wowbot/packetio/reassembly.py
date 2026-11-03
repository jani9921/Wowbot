"""Bounded per-direction TCP reconstruction, including overlap and sequence wrap."""
from __future__ import annotations
from dataclasses import dataclass, field

from .models import FlowDirection, PidTcpFlow, StreamChunk, TcpSegment


@dataclass
class _HalfStream:
    next_sequence: int | None = None
    pending: dict[int, bytes] = field(default_factory=dict)
    last_seen: float = 0.

    def feed(self, sequence, payload):
        if not payload:
            return None
        if self.next_sequence is None:
            self.next_sequence = sequence
        # Unwrap uint32 relative to the expected byte. Captures spanning more
        # than half the TCP sequence space without progress are not trusted.
        delta = ((sequence-(self.next_sequence & 0xFFFFFFFF)+2**31) % 2**32)-2**31
        sequence = self.next_sequence+delta
        end = sequence+len(payload)
        if end <= self.next_sequence:
            return None
        if sequence < self.next_sequence:
            payload = payload[self.next_sequence-sequence:]
            sequence = self.next_sequence
        old = self.pending.get(sequence)
        if old is None or len(payload) > len(old):
            self.pending[sequence] = payload
        start, pieces = self.next_sequence, []
        for at in sorted(self.pending):
            if at > self.next_sequence:
                break
            piece = self.pending.pop(at)
            offset = self.next_sequence-at
            if offset < len(piece):
                pieces.append(piece[offset:])
                self.next_sequence += len(piece)-offset
        return (start & 0xFFFFFFFF, b"".join(pieces)) if pieces else None


class TcpStreamReassembler:
    def __init__(self, *, max_pending_segments=4096, max_pending_bytes=2*1024*1024,
                 max_streams=128, idle_seconds=120.):
        self.max_pending_segments = max(1, int(max_pending_segments))
        self.max_pending_bytes = max(1, int(max_pending_bytes))
        self.max_streams = max(1, int(max_streams))
        self.idle_seconds = max(1., idle_seconds)
        self._streams = {}
        self.resets = 0

    def feed(self, segment: TcpSegment, flow: PidTcpFlow, direction: FlowDirection):
        key = flow.flow_id, str(direction)
        for old in [k for k, stream in self._streams.items()
                    if segment.captured_at-stream.last_seen > self.idle_seconds]:
            del self._streams[old]
        if segment.flags & 2:  # a fresh SYN cannot inherit an earlier connection
            self.reset_flow(flow.flow_id)
        if key not in self._streams and len(self._streams) >= self.max_streams:
            del self._streams[min(self._streams, key=lambda k: self._streams[k].last_seen)]
            self.resets += 1
        stream = self._streams.setdefault(key, _HalfStream())
        stream.last_seen = segment.captured_at
        sequence = (segment.sequence+bool(segment.flags & 2)) & 0xFFFFFFFF
        if segment.flags & 2:
            stream.next_sequence = sequence
        result = stream.feed(sequence, segment.payload)
        if (len(stream.pending) > self.max_pending_segments
                or sum(map(len, stream.pending.values())) > self.max_pending_bytes):
            self.reset_flow(flow.flow_id)
            self.resets += 1
            return None
        if segment.flags & 5:  # FIN/RST; no bytes bridge a reconnect
            self.reset_flow(flow.flow_id)
        if result is None:
            return None
        sequence, payload = result
        return StreamChunk(segment.captured_at, flow, direction, sequence, payload)

    def reset_flow(self, flow_id):
        for key in [key for key in self._streams if key[0] == flow_id]:
            del self._streams[key]
