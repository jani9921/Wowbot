"""Lock-free, single-writer/single-reader shared-memory frame ring buffer.

Built to move a captured screen frame from a separate capture PROCESS to
the main process without paying multiprocessing.Queue's pickle+pipe-copy
cost on multi-megabyte frame bytes on every poll (see
docs/PROCESS_BASED_CAPTURE_DESIGN_2026-09-22.txt). Three rotating slots
mean the writer never touches the slot the reader is currently allowed to
read; a seqlock-style even/odd sequence counter around each header update
lets the reader detect (and retry past) a write that happened concurrently
with its own read, without either side ever blocking on a lock.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from multiprocessing import shared_memory

SLOT_COUNT = 3
_STATUS_MAX_BYTES = 128
# Decoded AIPC5 pixel-strip packet of the slot's frame (optional).  The
# capture process decodes it next to the pixels so the main process does not
# spend its GIL on the strip (live 2026-09-30: 12-17 % of one core).
PAYLOAD_MAX_BYTES = 4096
PAYLOAD_NONE, PAYLOAD_DECODED, PAYLOAD_NOT_VISIBLE = 0, 1, 2
# sequence(int64) | slot_index(int32) | width(int32) | height(int32) |
# captured_at(float64) | status_len(int32) | slot_size(int32) |
# status(128 raw bytes) | frame_id(int64) | payload_len(int32) |
# payload_state(int32).  slot_size must be explicit: on
# Windows an attached SharedMemory reports the page-rounded mapping size, not
# necessarily the byte count requested by the creator.  frame_id advances only
# when a new frame is written; status-only updates (120 Hz "no_new_frame")
# advance ``sequence`` but keep the frame identity, so readers in different
# processes agree on which captured frame they hold.
_HEADER_FORMAT = "<qiiidii128sqii"
HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)
_MAX_READ_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    sequence: int
    raw: bytes | None
    width: int
    height: int
    status: str
    captured_at: float
    frame_id: int = 0
    payload: str | None = None
    payload_state: int = PAYLOAD_NONE


class SharedFrameRingBuffer:
    """One writer, one reader. Use `create()` on the owning side (before the
    other process starts) and `attach()` on the other side; both sides call
    `close()` when done, only the creator calls `unlink()`."""

    def __init__(self, header_shm: shared_memory.SharedMemory,
                 data_shm: shared_memory.SharedMemory, slot_size: int, *, owns: bool,
                 payload_shm: shared_memory.SharedMemory | None = None) -> None:
        self._header = header_shm
        self._data = data_shm
        self._payload = payload_shm
        self.slot_size = slot_size
        self._owns = owns
        self._write_slot = -1
        self._frame_id = 0

    @classmethod
    def create(cls, *, name_prefix: str, max_width: int, max_height: int) -> "SharedFrameRingBuffer":
        slot_size = max(1, int(max_width) * int(max_height) * 4)
        header_shm = shared_memory.SharedMemory(name=f"{name_prefix}_hdr", create=True, size=HEADER_SIZE)
        data_shm = shared_memory.SharedMemory(name=f"{name_prefix}_data", create=True, size=slot_size * SLOT_COUNT)
        payload_shm = shared_memory.SharedMemory(
            name=f"{name_prefix}_pay", create=True, size=PAYLOAD_MAX_BYTES * SLOT_COUNT)
        instance = cls(header_shm, data_shm, slot_size, owns=True, payload_shm=payload_shm)
        # Zero-initialized shared memory would otherwise unpack as
        # slot_index=0, making an unwritten buffer indistinguishable from a
        # real zero-byte frame in slot 0.
        instance._write_header(slot_index=-1, width=0, height=0,
                               status="not_started", captured_at=time.monotonic())
        return instance

    @classmethod
    def attach(cls, *, name_prefix: str) -> "SharedFrameRingBuffer":
        header_shm = shared_memory.SharedMemory(name=f"{name_prefix}_hdr", create=False)
        data_shm = shared_memory.SharedMemory(name=f"{name_prefix}_data", create=False)
        header = struct.unpack_from(_HEADER_FORMAT, header_shm.buf, 0)
        slot_size = int(header[6])
        if slot_size <= 0 or slot_size * SLOT_COUNT > data_shm.size:
            header_shm.close()
            data_shm.close()
            raise RuntimeError("invalid shared frame slot size")
        try:
            payload_shm = shared_memory.SharedMemory(name=f"{name_prefix}_pay", create=False)
        except FileNotFoundError:
            payload_shm = None
        return cls(header_shm, data_shm, slot_size, owns=False, payload_shm=payload_shm)

    @property
    def name_prefix(self) -> str:
        # SharedMemory strips a leading "psm_" prefix on some platforms; the
        # name it reports back is always the one a fresh attach() can use.
        return self._header.name.removesuffix("_hdr")

    # --------------------------------------------------------------- writer
    def write_frame(self, raw: bytes, width: int, height: int, status: str,
                    captured_at: float, *, payload: str | None = None,
                    payload_state: int = PAYLOAD_NONE) -> int:
        if len(raw) > self.slot_size:
            raise ValueError(f"frame ({len(raw)} bytes) exceeds slot_size ({self.slot_size})")
        if width <= 0 or height <= 0 or len(raw) != width * height * 4:
            raise ValueError("frame dimensions do not match the BGRA payload")
        # Claim the whole publication before touching a data slot. Marking
        # only the header update as in-progress is insufficient: after three
        # quick writes the producer can wrap around and overwrite the slot a
        # slow reader is still copying while the header still looks stable.
        sequence = self._begin_write()
        self._write_slot = (self._write_slot + 1) % SLOT_COUNT
        offset = self._write_slot * self.slot_size
        self._data.buf[offset:offset + len(raw)] = raw
        payload_len = 0
        if self._payload is None:
            payload_state = PAYLOAD_NONE
        elif payload is not None and payload_state != PAYLOAD_NONE:
            encoded = payload.encode("utf-8")
            if len(encoded) > PAYLOAD_MAX_BYTES:
                payload_state, encoded = PAYLOAD_NONE, b""
            payload_offset = self._write_slot * PAYLOAD_MAX_BYTES
            self._payload.buf[payload_offset:payload_offset + len(encoded)] = encoded
            payload_len = len(encoded)
        self._frame_id += 1
        self._finish_write(sequence, slot_index=self._write_slot, width=width, height=height,
                           status=status, captured_at=captured_at, frame_id=self._frame_id,
                           payload_len=payload_len, payload_state=payload_state)
        return sequence + 2

    def write_status(self, status: str, captured_at: float) -> None:
        """No new frame this cycle -- update status/timestamp, keep the last
        successfully captured frame (if any) available to the reader."""
        self._write_status(status, captured_at)

    def _write_status(self, status: str, captured_at: float) -> None:
        current = self._read_raw_header()
        self._write_header(slot_index=current[1] if current else -1,
                           width=current[2] if current else 0,
                           height=current[3] if current else 0,
                           status=status, captured_at=captured_at,
                           frame_id=current[6] if current else 0,
                           payload_len=current[7] if current else 0,
                           payload_state=current[8] if current else PAYLOAD_NONE)

    def _write_header(self, *, slot_index: int, width: int, height: int,
                      status: str, captured_at: float, frame_id: int = 0,
                      payload_len: int = 0, payload_state: int = PAYLOAD_NONE) -> None:
        sequence = self._begin_write()
        self._finish_write(sequence, slot_index=slot_index, width=width, height=height,
                           status=status, captured_at=captured_at, frame_id=frame_id,
                           payload_len=payload_len, payload_state=payload_state)

    def _begin_write(self) -> int:
        sequence = self._peek_sequence()
        if sequence % 2:
            sequence += 1
        struct.pack_into("<q", self._header.buf, 0, sequence + 1)
        return sequence

    def _finish_write(self, sequence: int, *, slot_index: int, width: int, height: int,
                      status: str, captured_at: float, frame_id: int = 0,
                      payload_len: int = 0, payload_state: int = PAYLOAD_NONE) -> None:
        status_bytes = status.encode("utf-8")[:_STATUS_MAX_BYTES]
        struct.pack_into(_HEADER_FORMAT, self._header.buf, 0, sequence + 1, slot_index,
                         width, height, captured_at, len(status_bytes), self.slot_size,
                         status_bytes, int(frame_id), int(payload_len), int(payload_state))
        struct.pack_into("<q", self._header.buf, 0, sequence + 2)

    def _peek_sequence(self) -> int:
        return struct.unpack_from("<q", self._header.buf, 0)[0]

    # --------------------------------------------------------------- reader
    def peek_frame_id(self) -> int:
        """Current frame identity from the header only (no pixel copy).

        Pollers must check this before read(): read() copies the whole frame
        (2-8 MB) and a 500 Hz poll loop spent most of its GIL time copying the
        same frame again (live 2026-09-30)."""
        return int(self._read_raw_header()[6])

    def read(self) -> CapturedFrame | None:
        for _ in range(_MAX_READ_ATTEMPTS):
            (sequence, slot_index, width, height, captured_at, status, frame_id,
             payload_len, payload_state) = self._read_raw_header()
            if sequence % 2 != 0:
                continue  # write in progress; retry
            raw = None
            payload = None
            if slot_index >= 0:
                offset = slot_index * self.slot_size
                raw = bytes(self._data.buf[offset:offset + width * height * 4])
                if (self._payload is not None and payload_state != PAYLOAD_NONE
                        and 0 <= payload_len <= PAYLOAD_MAX_BYTES):
                    payload_offset = slot_index * PAYLOAD_MAX_BYTES
                    payload = bytes(self._payload.buf[
                        payload_offset:payload_offset + payload_len]).decode("utf-8", errors="replace")
            after_sequence = self._peek_sequence()
            if after_sequence != sequence:
                continue  # writer moved on mid-read; retry
            return CapturedFrame(sequence, raw, width, height, status, captured_at, frame_id,
                                 payload, payload_state if payload is not None else PAYLOAD_NONE)
        return None

    def _read_raw_header(self):
        (sequence, slot_index, width, height, captured_at, status_len, _slot_size, status_raw,
         frame_id, payload_len, payload_state) = struct.unpack_from(_HEADER_FORMAT, self._header.buf, 0)
        status = status_raw[:status_len].decode("utf-8", errors="replace")
        return (sequence, slot_index, width, height, captured_at, status, frame_id,
                payload_len, payload_state)

    # ------------------------------------------------------------ lifecycle
    def close(self) -> None:
        self._header.close()
        self._data.close()
        if self._payload is not None:
            self._payload.close()

    def unlink(self) -> None:
        if not self._owns:
            raise RuntimeError("only the creating side may unlink shared memory")
        self._header.unlink()
        self._data.unlink()
        if self._payload is not None:
            self._payload.unlink()
