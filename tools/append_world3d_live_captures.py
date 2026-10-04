"""Append a bounded, session-diverse sample of agent live captures to a review pool."""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
import shutil

import cv2


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _uniform(paths: list[Path], count: int) -> list[Path]:
    if len(paths) <= count:
        return paths
    if count == 1:
        return [paths[len(paths) // 2]]
    indices = {round(index * (len(paths) - 1) / (count - 1)) for index in range(count)}
    return [paths[index] for index in sorted(indices)]


def _session_id(path: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", path.name.lower()).strip("-")[:32]
    digest = sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"live-{slug or 'session'}-{digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-output", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--max-per-session", type=int, default=5)
    args = parser.parse_args()
    if args.max_per_session < 1:
        raise SystemExit("--max-per-session must be positive")

    root = args.agent_output.resolve()
    dataset = args.dataset.resolve()
    manifest = dataset / "review" / "manifest.jsonl"
    if not root.is_dir() or not manifest.is_file():
        raise SystemExit("Missing agent output root or existing review manifest")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    hashes = {str(row.get("sha256")) for row in rows if row.get("sha256")}
    image_dir = dataset / "review" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    session_dirs = sorted({path.parent for path in root.rglob("manifest.jsonl")
                           if "live-captures" in {part.lower() for part in path.parts}})
    discovered = selected_count = written = duplicates = unreadable = 0
    for session_dir in session_dirs:
        images = sorted(path for path in session_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
        discovered += len(images)
        event_frames = [path for path in images
                        if path.stem.endswith(("-critical", "-state_change"))]
        heartbeat_frames = [path for path in images if path.stem.endswith("-heartbeat")]
        selected = _uniform(event_frames, args.max_per_session)
        if len(selected) < args.max_per_session:
            selected.extend(_uniform(
                heartbeat_frames, args.max_per_session - len(selected)))
        selected = sorted(set(selected))
        selected_count += len(selected)
        sid = _session_id(session_dir)
        for source_index, image_path in enumerate(selected):
            payload = image_path.read_bytes()
            digest = sha256(payload).hexdigest()
            if digest in hashes:
                duplicates += 1
                continue
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if frame is None:
                unreadable += 1
                continue
            hashes.add(digest)
            filename = f"{sid}__i{source_index:03d}__{image_path.name}"
            target = image_dir / filename
            shutil.copy2(image_path, target)
            height, width = frame.shape[:2]
            rows.append({
                "image": target.relative_to(dataset).as_posix(),
                "source_id": sid,
                "source_path": str(image_path),
                "source_frame": source_index,
                "timestamp_seconds": round(image_path.stat().st_mtime, 3),
                "width": width,
                "height": height,
                "sample_difference": None,
                "sha256": digest,
                "review_status": "UNREVIEWED",
            })
            written += 1

    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8", newline="\n")
    print(json.dumps({
        "sessions": len(session_dirs), "discovered_live_frames": discovered,
        "selected_before_dedup": selected_count, "written": written,
        "duplicates_skipped": duplicates, "unreadable": unreadable,
        "combined_review_frames": len(rows),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
