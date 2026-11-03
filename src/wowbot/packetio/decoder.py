from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
from typing import Iterable

from .models import AgentPacketEvent, StreamChunk


class StreamDecoder(ABC):
    """Versioned semantic decoder interface for one reassembled TCP stream."""

    @abstractmethod
    def feed(self, chunk: StreamChunk) -> Iterable[AgentPacketEvent]:
        raise NotImplementedError

    def reset_flow(self, flow_id):
        """Forget partial records when a TCP connection/gap is reset."""


class OpaqueStreamDecoder(StreamDecoder):
    """Transport-valid but semantically UNKNOWN output.

    Raw bytes are not forwarded.  A digest and byte count make capture gaps and
    replay correlation observable without leaking chat/auth payloads.
    """

    def feed(self, chunk: StreamChunk) -> Iterable[AgentPacketEvent]:
        yield AgentPacketEvent.create(
            pid=chunk.flow.pid,
            flow_id=chunk.flow.flow_id,
            direction=chunk.direction,
            event_type="NETWORK_STREAM_CHUNK",
            timestamp=chunk.captured_at,
            semantic_status="UNKNOWN",
            payload={
                "sequence_start": chunk.sequence_start,
                "byte_count": len(chunk.payload),
                "sha256": hashlib.sha256(chunk.payload).hexdigest(),
            },
            provenance={"producer": "OpaqueStreamDecoder", "transport": "TCP", "semantic_ground_truth": False},
            confidence=1.0,
        )


class JsonLineSemanticDecoder(StreamDecoder):
    """Decoder for a trusted sandbox-server packet mirror.

    Each TCP line must be one JSON object with at least ``event_type``.  This is
    intentionally separate from retail WoW wire decoding: it provides a safe,
    testable semantic backend while the build-specific opcode codec is added.
    """

    def __init__(self, *, max_line_bytes: int = 1_000_000, max_streams=128):
        self.max_line_bytes = int(max_line_bytes)
        self.max_streams = max(1, int(max_streams))
        self._buffers: dict[tuple[str, str], bytearray] = {}

    def feed(self, chunk: StreamChunk) -> Iterable[AgentPacketEvent]:
        key = (chunk.flow.flow_id, str(chunk.direction))
        if key not in self._buffers and len(self._buffers) >= self.max_streams:
            self._buffers.pop(next(iter(self._buffers)))
        buffer = self._buffers.setdefault(key, bytearray())
        buffer.extend(chunk.payload)
        if len(buffer) > self.max_line_bytes and b"\n" not in buffer:
            buffer.clear()
            return ()
        output: list[AgentPacketEvent] = []
        while True:
            try:
                boundary = buffer.index(10)
            except ValueError:
                break
            raw = bytes(buffer[:boundary]).rstrip(b"\r")
            del buffer[: boundary + 1]
            if not raw or len(raw) > self.max_line_bytes:
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(value, dict) or not value.get("event_type"):
                continue
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
            try:
                output.append(AgentPacketEvent.create(
                    pid=chunk.flow.pid,
                    flow_id=chunk.flow.flow_id,
                    direction=chunk.direction,
                    event_type=str(value["event_type"]),
                    timestamp=float(value.get("timestamp") or chunk.captured_at),
                    semantic_status=str(value.get("semantic_status") or "CONFIRMED"),
                    opcode=int(value["opcode"]) if value.get("opcode") is not None else None,
                    payload=payload,
                    provenance={"producer": "JsonLineSemanticDecoder", "transport": "TCP",
                                "semantic_ground_truth": False, "payload_scope": "SANDBOX_TEST_ONLY"},
                    confidence=float(value.get("confidence", 1.0)),
                ))
            except (ValueError, TypeError, OverflowError, RecursionError):
                continue
        if len(buffer) > self.max_line_bytes:
            buffer.clear()
        return output

    def reset_flow(self, flow_id):
        for key in [key for key in self._buffers if key[0] == flow_id]:
            del self._buffers[key]


class BuildCodecRegistry:
    """Explicit game-build codec registry; never guesses a nearby build."""

    def __init__(self):
        self._factories: dict[str, callable] = {}

    def register(self, game_build: str, factory) -> None:
        key = str(game_build).strip()
        if not key:
            raise ValueError("game build is required")
        if key in self._factories:
            raise ValueError(f"decoder already registered for build {key}")
        self._factories[key] = factory

    def create(self, game_build: str) -> StreamDecoder:
        key = str(game_build).strip()
        factory = self._factories.get(key)
        if factory is None:
            raise LookupError(f"no verified semantic packet decoder for exact game build {key}")
        return factory()

    @property
    def supported_builds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
