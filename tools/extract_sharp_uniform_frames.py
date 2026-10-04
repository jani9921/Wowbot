from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract temporally uniform video frames while selecting the sharpest "
            "candidate inside each time bin."
        )
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--candidates-per-bin", type=int, default=5)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--prefix", default="frame")
    parser.add_argument("--source-fps", type=float, default=60.0)
    return parser.parse_args()


def video_duration(ffmpeg: Path, video: Path) -> float:
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(video), "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    metadata = proc.stderr
    marker = "Duration: "
    start = metadata.find(marker)
    if start < 0:
        raise RuntimeError("Could not read video duration from FFmpeg output")
    stamp = metadata[start + len(marker) :].split(",", 1)[0]
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def sharpness_score(path: Path) -> float:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return -math.inf
    # Downscaling makes scoring fast while retaining blur/edge information.
    width = 640
    height = max(1, round(image.shape[0] * width / image.shape[1]))
    sample = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    laplacian = float(cv2.Laplacian(sample, cv2.CV_64F).var())
    contrast = float(sample.std())
    brightness = float(sample.mean())
    exposure_factor = max(0.15, 1.0 - abs(brightness - 120.0) / 180.0)
    return (laplacian + 0.20 * contrast * contrast) * exposure_factor


def main() -> int:
    args = parse_args()
    if args.count < 1 or args.candidates_per_bin < 1:
        raise SystemExit("--count and --candidates-per-bin must be positive")
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")
    if not args.ffmpeg.is_file():
        raise SystemExit(f"FFmpeg not found: {args.ffmpeg}")

    duration = video_duration(args.ffmpeg, args.video)
    candidate_count = args.count * args.candidates_per_bin
    candidate_fps = candidate_count / duration
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="wowbot-frame-candidates-") as temp_dir:
        temp = Path(temp_dir)
        pattern = temp / "candidate_%06d.jpg"
        command = [
            str(args.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(args.video),
            "-vf",
            f"fps={candidate_fps:.12f}",
            "-frames:v",
            str(candidate_count),
            "-q:v",
            "2",
            str(pattern),
        ]
        subprocess.run(command, check=True)
        candidates = sorted(temp.glob("candidate_*.jpg"))
        if len(candidates) < args.count:
            raise RuntimeError(
                f"FFmpeg produced only {len(candidates)} candidates for {args.count} bins"
            )

        for bin_index in range(args.count):
            lo = round(bin_index * len(candidates) / args.count)
            hi = round((bin_index + 1) * len(candidates) / args.count)
            group = candidates[lo:max(lo + 1, hi)]
            selected = max(group, key=sharpness_score)
            candidate_index = int(selected.stem.rsplit("_", 1)[1])
            timestamp = min(duration, max(0.0, (candidate_index - 0.5) / candidate_fps))
            source_frame = round(timestamp * args.source_fps)
            destination = args.output / (
                f"{args.prefix}__f{source_frame:09d}__t{timestamp:011.3f}.jpg"
            )
            shutil.copy2(selected, destination)

    print(
        f"Extracted {args.count} frames across {duration:.2f}s into {args.output} "
        f"using {args.candidates_per_bin} sharpness candidates per time bin."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
