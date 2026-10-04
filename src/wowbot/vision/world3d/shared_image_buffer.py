"""Single-owner BGR shared-memory transport for process YOLO inference.

Only one request may be in flight, so a ring is unnecessary: the producer
writes, publishes an even sequence, and waits for the consumer result before
it can overwrite the buffer. The queue carries only tiny metadata.
"""
from __future__ import annotations

from multiprocessing import shared_memory
import struct
from typing import Any
import uuid

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover
    from adapters.numpy_runtime import np


_HEADER_FORMAT = "<qiii"  # sequence, width, height, byte_count
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)


class SharedBgrImageBuffer:
    def __init__(self, header: shared_memory.SharedMemory,
                 data: shared_memory.SharedMemory, capacity: int, *, owns: bool):
        self._header = header
        self._data = data
        self.capacity = int(capacity)
        self._owns = owns

    @classmethod
    def create(cls, *, max_width: int, max_height: int) -> "SharedBgrImageBuffer":
        token = uuid.uuid4().hex[:12]
        header = shared_memory.SharedMemory(
            name=f"aipc_yolo_{token}_hdr", create=True, size=_HEADER_SIZE)
        capacity = max(1, int(max_width) * int(max_height) * 3)
        data = shared_memory.SharedMemory(
            name=f"aipc_yolo_{token}_data", create=True, size=capacity)
        instance = cls(header, data, capacity, owns=True)
        struct.pack_into(_HEADER_FORMAT, header.buf, 0, 0, 0, 0, 0)
        return instance

    @classmethod
    def attach(cls, *, header_name: str, data_name: str,
               capacity: int) -> "SharedBgrImageBuffer":
        return cls(shared_memory.SharedMemory(name=header_name, create=False),
                   shared_memory.SharedMemory(name=data_name, create=False),
                   capacity, owns=False)

    @property
    def descriptor(self) -> tuple[str, str, int]:
        return self._header.name, self._data.name, self.capacity

    def write(self, image: Any) -> int:
        contiguous = np.ascontiguousarray(image, dtype=np.uint8)
        if contiguous.ndim != 3 or contiguous.shape[2] != 3:
            raise ValueError("shared YOLO image must be HxWx3 BGR")
        height, width = int(contiguous.shape[0]), int(contiguous.shape[1])
        byte_count = int(contiguous.nbytes)
        if byte_count > self.capacity:
            raise ValueError(
                f"YOLO image ({byte_count} bytes) exceeds shared capacity ({self.capacity})")
        sequence = struct.unpack_from("<q", self._header.buf, 0)[0]
        if sequence % 2:
            sequence += 1
        struct.pack_into("<q", self._header.buf, 0, sequence + 1)
        self._data.buf[:byte_count] = contiguous.reshape(-1)
        struct.pack_into(_HEADER_FORMAT, self._header.buf, 0, sequence + 2,
                         width, height, byte_count)
        return sequence + 2

    def view(self, expected_sequence: int) -> Any:
        before, width, height, byte_count = struct.unpack_from(
            _HEADER_FORMAT, self._header.buf, 0)
        if before != int(expected_sequence) or before % 2:
            raise RuntimeError("shared YOLO frame was replaced before inference")
        if width < 1 or height < 1 or byte_count != width * height * 3:
            raise RuntimeError("invalid shared YOLO frame metadata")
        image = np.ndarray((height, width, 3), dtype=np.uint8,
                           buffer=self._data.buf, offset=0)
        after = struct.unpack_from("<q", self._header.buf, 0)[0]
        if after != before:
            raise RuntimeError("shared YOLO frame changed during acquisition")
        return image

    def close(self) -> None:
        self._header.close()
        self._data.close()

    def unlink(self) -> None:
        if not self._owns:
            raise RuntimeError("only creator may unlink shared YOLO buffer")
        self._header.unlink()
        self._data.unlink()
