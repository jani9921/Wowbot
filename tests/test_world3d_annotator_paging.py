"""Annotator paging (user 2026-10-02): arrow keys step back/forward, and
paging never drops unsaved edits silently."""
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "review_world3d_annotations.py"
_spec = importlib.util.spec_from_file_location("review_world3d_annotations", _TOOL)
annotator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annotator)

LEFT, RIGHT = 2424832, 2555904  # cv2.waitKeyEx on Windows


def _pool(tmp_path, frames=3):
    review = tmp_path / "review"
    (review / "images").mkdir(parents=True)
    records = []
    for index in range(frames):
        name = f"f{index}.jpg"
        cv2.imwrite(str(review / "images" / name), np.full((100, 100, 3), 40 * index, np.uint8))
        records.append({"image": f"review/images/{name}", "split": "train"})
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    reviewer = annotator.Reviewer(tmp_path)
    reviewer.render()
    return reviewer


def _draw_box(reviewer):
    top = annotator.HEADER
    reviewer.mouse(cv2.EVENT_LBUTTONDOWN, 10, top + 10, 0, None)
    reviewer.mouse(cv2.EVENT_MOUSEMOVE, 50, top + 60, 0, None)
    reviewer.mouse(cv2.EVENT_LBUTTONUP, 50, top + 60, 0, None)


def test_arrow_keys_page_back_and_forward(tmp_path):
    reviewer = _pool(tmp_path)
    assert reviewer.handle_key(RIGHT) and reviewer.index == 1
    reviewer.handle_key(RIGHT)
    reviewer.handle_key(RIGHT)
    assert reviewer.index == 2          # clamped at the last frame
    reviewer.handle_key(LEFT)
    assert reviewer.index == 1
    reviewer.handle_key(65361)          # GTK left arrow
    assert reviewer.index == 0
    reviewer.handle_key(-1)             # no key pressed
    assert reviewer.index == 0
    assert reviewer.handle_key(ord("q")) is False


def test_paging_with_unsaved_edits_warns_once_then_discards(tmp_path):
    reviewer = _pool(tmp_path)
    _draw_box(reviewer)
    assert reviewer.dirty and len(reviewer.boxes) == 1
    reviewer.handle_key(RIGHT)
    assert reviewer.index == 0 and "UNSAVED" in reviewer.message
    reviewer.handle_key(RIGHT)          # same key again: discard and move
    assert reviewer.index == 1 and not reviewer.dirty
    reviewer.handle_key(LEFT)
    assert reviewer.boxes == []         # nothing was saved for frame 0
    assert not (tmp_path / "review" / "reviews" / "f0.json").exists()


def test_saved_edits_page_freely_and_reload(tmp_path):
    reviewer = _pool(tmp_path)
    _draw_box(reviewer)
    reviewer.handle_key(ord("s"))
    assert not reviewer.dirty
    reviewer.handle_key(RIGHT)
    assert reviewer.index == 1
    reviewer.handle_key(LEFT)
    assert reviewer.index == 0 and len(reviewer.boxes) == 1
    assert reviewer.message.startswith("REVIEWED")


def test_n_p_keys_are_guarded_too(tmp_path):
    reviewer = _pool(tmp_path)
    _draw_box(reviewer)
    reviewer.handle_key(ord("n"))
    assert reviewer.index == 0
    reviewer.handle_key(LEFT)           # a different key re-arms the warning
    assert reviewer.index == 0
    reviewer.handle_key(LEFT)
    assert reviewer.index == 0          # already first frame; edits discarded
    assert not reviewer.dirty


DELETE = 3014656  # Windows Delete key


def _manifest_images(tmp_path):
    lines = (tmp_path / "review" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["image"] for line in lines if line.strip()]


def _with_saved_frame(tmp_path, stem="f1"):
    review = tmp_path / "review"
    for sub in ("labels", "reviews", "proposals"):
        (review / sub).mkdir(exist_ok=True)
    (review / "labels" / f"{stem}.txt").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (review / "reviews" / f"{stem}.json").write_text('{"review_status": "REVIEWED", "boxes": []}', encoding="utf-8")
    (review / "proposals" / f"{stem}.json").write_text('{"proposals": []}', encoding="utf-8")


def test_delete_needs_two_presses_and_moves_image_and_labels_aside(tmp_path):
    reviewer = _pool(tmp_path)
    _with_saved_frame(tmp_path)
    reviewer.handle_key(RIGHT)
    assert reviewer.image_path.name == "f1.jpg"
    reviewer.handle_key(DELETE)
    assert "DEL again" in reviewer.message and (tmp_path / "review" / "images" / "f1.jpg").exists()
    reviewer.handle_key(DELETE)
    review = tmp_path / "review"
    assert not (review / "images" / "f1.jpg").exists()
    for sub in ("labels", "reviews", "proposals"):
        assert not list((review / sub).glob("f1.*"))
    trash = review / "deleted" / "f1"
    assert sorted(p.name for p in trash.iterdir()) == [
        "images__f1.jpg", "labels__f1.txt", "proposals__f1.json", "record.json", "reviews__f1.json"]
    assert _manifest_images(tmp_path) == ["review/images/f0.jpg", "review/images/f2.jpg"]
    assert len(reviewer.records) == 2 and reviewer.image_path.name == "f2.jpg"
    assert reviewer.message.startswith("DELETED f1")


def test_another_key_cancels_a_pending_delete(tmp_path):
    reviewer = _pool(tmp_path)
    reviewer.handle_key(DELETE)
    reviewer.handle_key(ord("a"))
    reviewer.handle_key(DELETE)
    assert (tmp_path / "review" / "images" / "f0.jpg").exists() and len(reviewer.records) == 3


def test_undo_restores_files_manifest_order_and_position(tmp_path):
    reviewer = _pool(tmp_path)
    _with_saved_frame(tmp_path)
    reviewer.handle_key(RIGHT)
    reviewer.handle_key(DELETE)
    reviewer.handle_key(DELETE)
    reviewer.handle_key(ord("u"))
    review = tmp_path / "review"
    assert (review / "images" / "f1.jpg").exists() and (review / "labels" / "f1.txt").exists()
    assert (review / "reviews" / "f1.json").exists() and (review / "proposals" / "f1.json").exists()
    assert _manifest_images(tmp_path) == ["review/images/f0.jpg", "review/images/f1.jpg", "review/images/f2.jpg"]
    assert reviewer.image_path.name == "f1.jpg" and reviewer.message.startswith("RESTORED")
    assert not (review / "deleted" / "f1").exists()
    reviewer.handle_key(ord("u"))
    assert reviewer.message == "Nothing to undo"


def test_reviewed_only_mode_keeps_hidden_manifest_lines(tmp_path):
    _pool(tmp_path)
    for stem in ("f0", "f2"):
        _with_saved_frame(tmp_path, stem)
    reviewer = annotator.Reviewer(tmp_path, reviewed_only=True)
    reviewer.render()
    assert [r["image"] for r in reviewer.records] == ["review/images/f0.jpg", "review/images/f2.jpg"]
    reviewer.handle_key(DELETE)
    reviewer.handle_key(DELETE)
    # f1 was never reviewed (hidden in this mode) and must stay in the pool.
    assert _manifest_images(tmp_path) == ["review/images/f1.jpg", "review/images/f2.jpg"]


def test_last_frame_cannot_be_deleted_and_header_button_works(tmp_path):
    reviewer = _pool(tmp_path, frames=2)
    action, (left, top, right, bottom) = next(item for item in reviewer.action_buttons if item[0] == "frame")
    for _ in range(2):
        reviewer.mouse(cv2.EVENT_LBUTTONDOWN, (left + right) // 2, (top + bottom) // 2, 0, None)
    assert len(reviewer.records) == 1
    reviewer.render()
    reviewer.handle_key(DELETE)
    reviewer.handle_key(DELETE)
    assert len(reviewer.records) == 1 and "cannot be deleted" in reviewer.message
