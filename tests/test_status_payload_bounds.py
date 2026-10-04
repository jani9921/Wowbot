import json

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _addon():
    return {"session_id": "s", "frame_id": "a", "timestamp": 1, "map_id": 1409,
            "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True}


def test_aggregate_visual_belief_does_not_embed_track_histories():
    world = WorldModel()
    addon = Observation.create(_addon(), 1)
    world.ingest(addon)
    huge = {"track_id": "WORLD3D:1", "source": "WORLD3D",
            "kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "confidence": .8, "stable_frames": 10,
            "appearance_history": [{"pixels": "x"*10000} for _ in range(32)],
            "bbox_history": [{"left": i} for i in range(32)]}
    obs = Observation.create({"session_id": "s", "frame_id": "v1", "timestamp": 1.1,
                              "visual_candidates": [huge]}, 1.1, "WORLD3D")
    world.ingest(obs)
    aggregate = world.belief("visual_candidates", 1.1)
    encoded = json.dumps(aggregate)
    assert len(encoded) < 3000
    assert "appearance_history" not in encoded
    assert world.state["visual_candidates"][0]["appearance_history"] == huge["appearance_history"]


def test_snapshot_hashes_large_contradiction_values_instead_of_embedding_them():
    world = WorldModel()
    addon = Observation.create(_addon(), 1)
    world.ingest(addon)
    for index, source in enumerate(("VISION", "WORLD3D"), start=1):
        obs = Observation.create({"session_id": "s", "frame_id": f"v{index}",
            "timestamp": 1+index*.1, "claim": {"payload": ("a" if index == 1 else "b")*100000}},
            1+index*.1, source)
        world.ingest(obs)
    snapshot = world.snapshot(1.3)
    encoded = json.dumps(snapshot["contradiction_history"])
    assert len(encoded) < 10000
    if snapshot["contradiction_history"]:
        assert "chosen_value_sha256" in snapshot["contradiction_history"][-1]

