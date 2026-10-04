import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_pixel_strip_resolution_profiles import frame
from tools.screenshot_session_replay import rebuild


def _save_frame(path: Path, width: int, height: int, payload: str) -> None:
    bgra = np.frombuffer(frame(width, height, payload), dtype=np.uint8).reshape(height, width, 4)
    cv2.imwrite(str(path), bgra[:, :, :3])  # JPEG has no alpha channel


def _write_manifest(segment: Path, rows: list[tuple[str, float]]) -> None:
    with (segment / "manifest.jsonl").open("w", encoding="utf-8") as handle:
        for name, at in rows:
            handle.write(json.dumps({"frame": name, "observed_monotonic": at}) + "\n")


def test_rebuild_reassembles_a_single_page_state_and_a_following_fast_update(tmp_path):
    segment = tmp_path / "segment"
    segment.parent.mkdir(parents=True, exist_ok=True)
    segment.mkdir()
    width, height = 640, 480
    state_body = json.dumps({"map_id": 1409, "monotonic_time": 100.0})
    fast_body = json.dumps({"target": {"guid": "g1"}, "monotonic_time": 100.5})
    _save_frame(segment / "001.jpg", width, height, f"AIPC5|s1|1|0|1|STATE|{state_body}")
    _save_frame(segment / "002.jpg", width, height, f"AIPC5|s1|2|0|1|FAST|{fast_body}")
    _write_manifest(segment, [("001.jpg", 10.0), ("002.jpg", 10.5)])

    results = rebuild(segment)

    assert len(results) == 2
    assert results[0]["at"] == 10.0
    assert results[0]["state"]["map_id"] == 1409
    assert results[1]["at"] == 10.5
    assert results[1]["state"]["target"]["guid"] == "g1"
    # PacketAssembler.feed() itself only carries identity fields (character_*,
    # addon*, schema/game_version) forward on a FAST delta -- merging the rest
    # against the last full snapshot is WorldModel.ingest()'s job downstream,
    # exactly as it is in the live pipeline. map_id is correctly absent here.
    assert "map_id" not in results[1]["state"]


def test_rebuild_skips_frames_with_no_decodable_strip(tmp_path):
    segment = tmp_path / "segment"
    segment.mkdir()
    width, height = 640, 480
    cv2.imwrite(str(segment / "blank.jpg"), np.zeros((height, width, 3), dtype=np.uint8))
    _write_manifest(segment, [("blank.jpg", 1.0)])

    assert rebuild(segment) == []


def test_rebuild_requires_a_manifest(tmp_path):
    segment = tmp_path / "segment"
    segment.mkdir()
    with pytest.raises(FileNotFoundError):
        rebuild(segment)
