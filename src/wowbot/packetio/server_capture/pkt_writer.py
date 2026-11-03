"""Incremental PKT 3.1 writer, byte-compatible with Ymir's sniffer id 0x15 dumps.

The 40-byte header session-key field is always written as zeros: key material is
never persisted. Every record is flushed immediately so ``PktFileFollower`` can
read the file while it is still being written (Ymir only finalises on exit).
"""
from __future__ import annotations

from pathlib import Path
import struct
import threading
import time

PKT_VERSION = 0x0301
SNIFFER_ID = 0x15
SNIFFER_VERSION = 0x0103
_SMSG = 0x47534D53
_CMSG = 0x47534D43


def encode_header(*, build: int, locale: str, start_unix: int, start_tick: int = 0,
                  optional: bytes) -> bytes:
    locale_bytes = locale.encode("ascii")[:4].ljust(4, b"\0")
    return (b"PKT" + struct.pack("<HBI", PKT_VERSION, SNIFFER_ID, int(build)) + locale_bytes
            + bytes(40) + struct.pack("<IIi", int(start_unix), int(start_tick), len(optional))
            + optional)


def default_optional_header(utc_offset_seconds: int) -> bytes:
    return struct.pack("<Hi", SNIFFER_VERSION, int(utc_offset_seconds))


def encode_record(*, server_to_client: bool, connection_index: int, tick: int,
                  optional: bytes, opcode: int, payload: bytes) -> bytes:
    packet = struct.pack("<I", opcode & 0xFFFFFFFF) + payload
    return (struct.pack("<IiIii", _SMSG if server_to_client else _CMSG, int(connection_index),
                        tick & 0xFFFFFFFF, len(optional), len(packet)) + optional + packet)


class PktWriter:
    def __init__(self, path: Path, *, build: int, locale: str, start_time: float | None = None):
        self.path = Path(path)
        self.start_time = time.time() if start_time is None else float(start_time)
        self.records = 0
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("xb")
        offset = time.localtime(self.start_time).tm_gmtoff or 0
        self._stream.write(encode_header(
            build=build, locale=locale, start_unix=int(self.start_time),
            optional=default_optional_header(offset)))
        self._stream.flush()

    def write(self, *, server_to_client: bool, connection_index: int, timestamp: float,
              opcode: int, payload: bytes) -> None:
        tick = int(max(0.0, timestamp - self.start_time) * 1000.0)
        optional = struct.pack("<d", timestamp * 1000.0) + b"\x00"
        record = encode_record(server_to_client=server_to_client,
                               connection_index=connection_index, tick=tick,
                               optional=optional, opcode=opcode, payload=payload)
        with self._lock:
            if self._stream.closed:
                return
            self._stream.write(record)
            self._stream.flush()
            self.records += 1

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.close()
