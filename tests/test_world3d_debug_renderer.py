from PIL import Image

from wowbot.vision.world3d import (PixelRect, World3DDebugRenderer,
                                   World3DPipeline, WorldSceneROI)


def frame(width=120, height=90):
    image = Image.new("RGBA", (width, height), (20, 30, 40, 255))
    red, green, blue, alpha = image.split()
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes(), width, height


def source_track():
    return {"track_id": "WORLD3D:1", "source": "WORLD3D",
            "detector_kind": "unknown_subject_candidate", "confidence": .8,
            "lifecycle": "ACTIVE", "bbox": {"left": 30, "top": 20,
            "right": 60, "bottom": 70}, "appearance": {},
            "candidate_labels": []}


def test_replay_contains_every_required_typed_record():
    pipeline = World3DPipeline()
    pipeline.observe(frame(), {}, [source_track()],
                     WorldSceneROI(PixelRect(0, 0, 120, 90)), observed_at=1., frame_id="f1")
    replay = pipeline.replay_record()
    types = {row["record_type"] for row in replay["records"]}

    assert types == {"FRAME_META", "DETECTOR_OUTPUT", "TRACK_UPDATE", "CAMERA_MOTION",
                     "EGO_MOTION", "GEOMETRY", "SEMANTIC_FUSION", "NEGATIVE_EVIDENCE",
                     "PROBE_REQUEST", "PROBE_RESULT"}
    assert replay["schema_version"] == 1
    assert replay["debug_overlay"]["tracks"][0]["track_id"] == "WORLD3D:1"


def test_renderer_creates_visual_overlay_without_any_action_authority(tmp_path):
    pipeline = World3DPipeline()
    original = frame()
    pipeline.observe(original, {}, [source_track()],
                     WorldSceneROI(PixelRect(0, 0, 120, 90)), observed_at=1.)
    output = tmp_path/"overlay.png"
    World3DDebugRenderer().render(original, pipeline.debug_overlay(), output)

    rendered = Image.open(output).convert("RGBA")
    assert output.exists()
    assert rendered.getpixel((30, 20)) != (20, 30, 40, 255)
    assert "input" not in pipeline.debug_overlay()

