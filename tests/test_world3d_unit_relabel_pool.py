import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_world3d_unit_relabel_pool.py"
_spec = importlib.util.spec_from_file_location("build_world3d_unit_relabel_pool", _TOOL)
pool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pool)


def test_humanoid_creature_and_corpse_merge_and_rare_classes_drop():
    assert [pool.remap_class(c) for c in range(7)] == [1, 1, 1, 3, None, 5, None]


def test_read_yolo_boxes_remaps_and_skips_dropped_classes(tmp_path):
    label = tmp_path / "a.txt"
    label.write_text("1 0.5 0.5 0.2 0.4\n4 0.1 0.1 0.1 0.1\n2 0.25 0.75 0.1 0.1\n", encoding="utf-8")
    boxes = pool.read_yolo_boxes(label, 100, 100)
    assert [class_id for class_id, _ in boxes] == [1, 1]
    assert boxes[0][1] == [40.0, 30.0, 60.0, 70.0]


class _Boxes:
    cls = xyxy = conf = ()


class _StubModel:
    def predict(self, *_args, **_kwargs):
        return [type("Result", (), {"boxes": _Boxes()})()]


def test_append_adds_only_missing_saved_frames_and_never_touches_existing(tmp_path):
    import json
    import cv2
    import numpy as np

    pools = tmp_path / "datasets"
    pool_dir = pools / "world3d_dragonflight_part7_300_v1" / "review"
    for sub in ("images", "reviews", "labels"):
        (pool_dir / sub).mkdir(parents=True)
    for stem, status in (("vid__f1__t1", "REVIEWED"), ("vid__f2__t2", "REVIEWED"), ("vid__f3__t3", None)):
        cv2.imwrite(str(pool_dir / "images" / f"{stem}.jpg"), np.zeros((20, 40, 3), np.uint8))
        (pool_dir / "labels" / f"{stem}.txt").write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
        if status:
            (pool_dir / "reviews" / f"{stem}.json").write_text(
                json.dumps({"image": f"review/images/{stem}.jpg", "review_status": status}), encoding="utf-8")

    out = tmp_path / "relabel" / "review"
    for sub in ("images", "reviews", "labels", "proposals"):
        (out / sub).mkdir(parents=True)
    already = "s0_world3d_annotation_combined_1077_v1__vid__f1__t1"
    (out / "manifest.jsonl").write_text(json.dumps({"image": f"review/images/{already}.jpg"}) + "\n",
                                        encoding="utf-8")
    (out / "reviews" / f"{already}.json").write_text('{"reviewer": "HUMAN"}', encoding="utf-8")

    args = type("Args", (), {"source": pools, "out": tmp_path / "relabel", "conf": .06, "imgsz": 64,
                             "device": "cpu"})()
    totals = pool.append_from_pools(_StubModel(), args)

    assert totals["frames"] == 1 and totals["already_present"] == 1
    manifest = (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest) == 2
    assert json.loads(manifest[1])["image"] == "review/images/world3d_dragonflight_part7_300_v1__vid__f2__t2.jpg"
    assert (out / "reviews" / f"{already}.json").read_text(encoding="utf-8") == '{"reviewer": "HUMAN"}'
    added_label = (out / "labels" / "world3d_dragonflight_part7_300_v1__vid__f2__t2.txt").read_text(encoding="utf-8")
    assert added_label.split()[0] == "1"


def test_original_stem_strips_combine_prefixes():
    assert pool.original_stem("s0_world3d_a__s0_world3d_b__vid__f1__t1") == "vid__f1__t1"


def test_only_unlabeled_non_duplicate_units_become_proposals():
    labels = [(1, [10, 10, 30, 50]), (5, [100, 0, 110, 10])]
    detections = [
        ([11, 11, 31, 51], .9),     # already labeled
        ([100, 0, 110, 10], .4),    # overlaps only a symbol label -> still a missing unit
        ([200, 50, 220, 90], .3),   # missing
        ([201, 51, 221, 91], .2),   # duplicate of the previous detection
    ]
    kept = pool.missing_unit_proposals(labels, detections)
    assert [box for box, _ in kept] == [[100, 0, 110, 10], [200, 50, 220, 90]]


def test_unlabeled_frames_enter_as_unreviewed_even_without_proposals(tmp_path):
    import json
    import cv2
    import numpy as np

    pool_dir = tmp_path / "world3d_wow_screenshots_20260927_v1"
    for sub in ("images", "reviews"):
        (pool_dir / "review" / sub).mkdir(parents=True)
    rows = []
    for stem in ("shot1", "shot2"):
        cv2.imwrite(str(pool_dir / "review" / "images" / f"{stem}.png"), np.zeros((20, 40, 3), np.uint8))
        rows.append(json.dumps({"image": f"review/images/{stem}.png"}))
    (pool_dir / "review" / "manifest.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (pool_dir / "review" / "reviews" / "shot1.json").write_text("{}", encoding="utf-8")  # already saved by hand

    out = tmp_path / "relabel" / "review"
    for sub in ("images", "reviews", "labels", "proposals"):
        (out / sub).mkdir(parents=True)
    (out / "manifest.jsonl").write_text("", encoding="utf-8")
    args = type("Args", (), {"out": tmp_path / "relabel", "conf": .2, "imgsz": 64, "device": "cpu"})()

    totals = pool.append_unlabeled_frames(_StubModel(), args, pool_dir)

    assert totals["frames"] == 1 and totals["skipped_saved"] == 1
    stem = "world3d_wow_screenshots_20260927_v1__shot2"
    assert json.loads((out / "proposals" / f"{stem}.json").read_text(encoding="utf-8"))["proposals"] == []
    assert not (out / "reviews" / f"{stem}.json").exists()
    assert pool.append_unlabeled_frames(_StubModel(), args, pool_dir)["already_present"] == 1
