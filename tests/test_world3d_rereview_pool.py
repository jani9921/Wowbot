"""Full re-review pool (user 2026-10-02: "átnézem újra a képeket")."""
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_world3d_rereview_pool.py"
_spec = importlib.util.spec_from_file_location("build_world3d_rereview_pool", _TOOL)
pool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pool)

W, H = 1000, 500
AVATAR = [470., 300., 530., 480.]


def _saved(box, class_id=1):
    left, top, right, bottom = box
    return {"box_id": "b0", "left": left, "top": top, "right": right, "bottom": bottom,
            "class_id": class_id, "confidence": 1., "status": "ACCEPTED",
            "source": "HUMAN_DRAWN", "candidate_kind": ""}


def test_prior_boxes_stay_accepted_and_only_missing_confident_boxes_are_proposed():
    prior = [_saved([100, 100, 140, 180])]
    detections = [
        (1, [101., 101., 141., 181.], .9),   # already labeled
        (5, [105., 80., 115., 95.], .6),     # symbol over the unit: different class, missing
        (1, [600., 100., 640., 180.], .7),   # missing unit
        (1, [602., 102., 642., 182.], .5),   # duplicate of the previous detection
        (1, [800., 100., 840., 180.], .2),   # below the proposal threshold
    ]
    boxes = pool.rereview_boxes(prior, detections, W, H, conf=.4)
    assert [(b["status"], b["source"]) for b in boxes][0] == ("ACCEPTED", "PRIOR_REVIEW")
    proposed = [(b["class_id"], b["left"]) for b in boxes if b["status"] == "PROPOSED"]
    assert proposed == [(1, 600), (5, 105)]


def test_missing_avatar_gets_a_weak_proposal_but_a_labeled_one_does_not():
    weak_avatar = [(1, AVATAR, .08)]
    boxes = pool.rereview_boxes([], weak_avatar, W, H, conf=.4)
    assert [(b["candidate_kind"], b["status"]) for b in boxes] == [("self_avatar", "PROPOSED")]
    labeled = pool.rereview_boxes([_saved(AVATAR)], weak_avatar, W, H, conf=.4)
    assert [b["candidate_kind"] for b in labeled] == [""]
    # A confident avatar detection is one proposal, tagged, not two.
    strong = pool.rereview_boxes([], [(1, AVATAR, .8)], W, H, conf=.4)
    assert [b["candidate_kind"] for b in strong] == ["self_avatar"]
    # Off-centre units are not avatar candidates.
    side = pool.rereview_boxes([], [(1, [100., 300., 160., 480.], .08)], W, H, conf=.4)
    assert side == []


class _Boxes:
    def __init__(self, rows):
        self.cls = type("T", (), {"tolist": lambda _: [r[0] for r in rows]})()
        self.xyxy = type("T", (), {"tolist": lambda _: [r[1] for r in rows]})()
        self.conf = type("T", (), {"tolist": lambda _: [r[2] for r in rows]})()


class _StubModel:
    def predict(self, frames, **_):
        # 3-class model ids: 0 unit, 2 symbol
        rows = [(0, [600., 100., 640., 180.], .7), (0, AVATAR, .1)]
        return [type("Result", (), {"boxes": _Boxes(rows)})() for _ in frames]


def test_build_reads_the_source_pool_and_writes_only_the_new_pool(tmp_path):
    source = tmp_path / "world3d_units_v5_review"
    review = source / "review"
    for sub in ("images", "reviews", "labels"):
        (review / sub).mkdir(parents=True)
    records = []
    for stem in ("vid__f1", "vid__f2"):
        cv2.imwrite(str(review / "images" / f"{stem}.jpg"), np.zeros((H, W, 3), np.uint8))
        records.append({"image": f"review/images/{stem}.jpg", "split": "val", "source_pool": "x"})
    (review / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    saved = {"image": records[0]["image"], "review_status": "REVIEWED", "accepted_count": 1,
             "boxes": [_saved([100, 100, 140, 180])], "rejected_proposal_count": 3}
    (review / "reviews" / "vid__f1.json").write_text(json.dumps(saved), encoding="utf-8")
    before = {p: p.read_bytes() for p in review.rglob("*") if p.is_file()}

    out = tmp_path / "world3d_units_v6_rereview"
    totals = pool.build(_StubModel(), source, out, conf=.4, imgsz=64, device="cpu")

    assert totals["frames"] == 2 and totals["frames_without_saved_review"] == 1
    assert totals["model_proposals"] == 2 and totals["avatar_proposals"] == 2
    assert {p: p.read_bytes() for p in review.rglob("*") if p.is_file()} == before
    manifest = [json.loads(line) for line in (out / "review" / "manifest.jsonl").read_text().splitlines()]
    assert manifest == records                       # splits and source fields preserved
    assert list((out / "review" / "reviews").iterdir()) == []   # everything starts unreviewed
    first = json.loads((out / "review" / "proposals" / "vid__f1.json").read_text(encoding="utf-8"))
    assert [b["status"] for b in first["proposals"]] == ["ACCEPTED", "PROPOSED", "PROPOSED"]
    assert "self_avatar" in {b["candidate_kind"] for b in first["proposals"]}
