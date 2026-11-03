from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import time
from typing import Any


class FlowDirection(StrEnum):
    CLIENT_TO_SERVER = "CLIENT_TO_SERVER"
    SERVER_TO_CLIENT = "SERVER_TO_CLIENT"


@dataclass(frozen=True)
class PidTcpFlow:
    pid: int
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    first_seen: float = 0.0

    @property
    def flow_id(self) -> str:
        value = f"{self.pid}|{self.local_ip}:{self.local_port}|{self.remote_ip}:{self.remote_port}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class RawPacket:
    captured_at: float
    link_type: int
    payload: bytes
    interface: str
    captured_length: int
    original_length: int


@dataclass(frozen=True)
class TcpSegment:
    captured_at: float
    source_ip: str
    source_port: int
    destination_ip: str
    destination_port: int
    sequence: int
    acknowledgement: int
    flags: int
    payload: bytes


@dataclass(frozen=True)
class StreamChunk:
    captured_at: float
    flow: PidTcpFlow
    direction: FlowDirection
    sequence_start: int
    payload: bytes


@dataclass(frozen=True)
class AgentPacketEvent:
    event_id: str
    schema: str
    timestamp: float
    received_at: float
    selected_pid: int
    flow_id: str
    direction: str
    event_type: str
    semantic_status: str
    opcode: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    @classmethod
    def create(
        cls,
        *,
        pid: int,
        flow_id: str,
        direction: FlowDirection | str,
        event_type: str,
        timestamp: float,
        semantic_status: str,
        opcode: int | None = None,
        payload: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> "AgentPacketEvent":
        body = payload or {}
        identity = json.dumps(
            {
                "pid": pid,
                "flow": flow_id,
                "direction": str(direction),
                "type": event_type,
                "opcode": opcode,
                "timestamp": timestamp,
                "payload": body,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        encoded = identity.encode('utf-8')
        epoch = (provenance or {}).get('capture_epoch')
        root = hashlib.sha256(encoded).hexdigest()[:24]
        if isinstance(epoch, str) and epoch:
            provenance = {**provenance, 'semantic_record_id':root}
            encoded += b'|capture_epoch:'+epoch.encode('utf-8')
        return cls(
            event_id=hashlib.sha256(encoded).hexdigest()[:24],
            schema="aipc.packet-event.v1",
            timestamp=float(timestamp),
            received_at=time.time(),
            selected_pid=int(pid),
            flow_id=flow_id,
            direction=str(direction),
            event_type=str(event_type),
            semantic_status=str(semantic_status),
            opcode=opcode,
            payload=body,
            provenance=provenance or {},
            confidence=max(0.0, min(1.0, float(confidence))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
