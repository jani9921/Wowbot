"""Passive, PID-scoped packet telemetry for the autonomous agent.

The package deliberately separates capture, transport decoding and semantic
forwarding.  Nothing in this package can generate client traffic or execute an
agent action.
"""

from .models import AgentPacketEvent, FlowDirection, PidTcpFlow, RawPacket, StreamChunk, TcpSegment
from .pkt import OpcodeManifest, PktEventDecoder, PktFileFollower, PktFormatError, PktHeader, PktRecord, PktV31StreamParser

__all__ = [
    "AgentPacketEvent",
    "FlowDirection",
    "PidTcpFlow",
    "RawPacket",
    "StreamChunk",
    "TcpSegment",
    "OpcodeManifest",
    "PktEventDecoder",
    "PktFileFollower",
    "PktFormatError",
    "PktHeader",
    "PktRecord",
    "PktV31StreamParser",
]
