from __future__ import annotations

import numpy as np
import pytest

from wowbot.vision.world3d.shared_image_buffer import SharedBgrImageBuffer


def test_shared_bgr_buffer_round_trip_without_queue_payload() -> None:
    owner = SharedBgrImageBuffer.create(max_width=32, max_height=24)
    header, data, capacity = owner.descriptor
    reader = SharedBgrImageBuffer.attach(
        header_name=header, data_name=data, capacity=capacity)
    try:
        source = np.arange(12 * 17 * 3, dtype=np.uint8).reshape(12, 17, 3)
        sequence = owner.write(source)

        observed = reader.view(sequence)

        assert observed.shape == source.shape
        assert np.array_equal(observed, source)
    finally:
        reader.close()
        owner.close()
        owner.unlink()


def test_shared_bgr_buffer_rejects_oversized_image() -> None:
    owner = SharedBgrImageBuffer.create(max_width=8, max_height=8)
    try:
        with pytest.raises(ValueError, match="exceeds shared capacity"):
            owner.write(np.zeros((9, 9, 3), dtype=np.uint8))
    finally:
        owner.close()
        owner.unlink()
