from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    path = ROOT / "tools" / "apply_annotation_audit.py"
    spec = importlib.util.spec_from_file_location("apply_annotation_audit_tool", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path, decision: dict) -> tuple[Path, Path, Path]:
    dataset = tmp_path / "dataset"
    image = dataset / "review" / "images" / "frame.jpg"
    proposal = dataset / "review" / "proposals" / "frame.json"
    image.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    assert cv2.imwrite(str(image), np.zeros((32, 48, 3), dtype=np.uint8))
    proposal.write_text(json.dumps({"proposals": []}), encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps([{
        "frame_id": 7,
        "proposal_file": "frame.json",
        "image": "review/images/frame.jpg",
        "boxes": [],
    }]), encoding="utf-8")
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({
        "reviewer": "TEST_REVIEWER",
        "decisions": [{"frame_id": 7, **decision}],
    }), encoding="utf-8")
    return dataset, mapping, decisions


def test_explicit_empty_writes_reviewed_empty_provenance(tmp_path, monkeypatch) -> None:
    dataset, mapping, decisions = _fixture(tmp_path, {
        "empty": True,
        "notes": "full-resolution visual check",
    })
    tool = _load_tool()
    monkeypatch.setattr(sys, "argv", ["apply_annotation_audit.py", str(dataset),
                                      str(mapping), str(decisions)])

    assert tool.main() == 0

    assert (dataset / "review" / "labels" / "frame.txt").read_text() == ""
    review = json.loads((dataset / "review" / "reviews" / "frame.json").read_text())
    assert review["review_status"] == "REVIEWED_EMPTY"
    assert review["accepted_count"] == 0
    assert review["notes"] == "full-resolution visual check"


def test_explicit_empty_rejects_conflicting_box_decision(tmp_path, monkeypatch) -> None:
    dataset, mapping, decisions = _fixture(tmp_path, {
        "empty": True,
        "manual_boxes": [
            {"left": 1, "top": 1, "right": 5, "bottom": 5, "class_id": 0},
        ],
    })
    tool = _load_tool()
    monkeypatch.setattr(sys, "argv", ["apply_annotation_audit.py", str(dataset),
                                      str(mapping), str(decisions)])

    with pytest.raises(ValueError, match="explicitly empty"):
        tool.main()
