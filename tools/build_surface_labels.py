"""Build navmesh surface labels / regions / cave entrances for one map.

Writes ``output/navigation/surface_labels_<map>.json`` and a top-down PNG
(SURFACE grey, COVERED purple, CAVE regions bright purple, ELEVATED orange,
entrances red with the inward direction).

Usage: python tools/build_surface_labels.py [--map 2175] [--retail PATH] [--mmaps PATH]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh  # noqa: E402
from wowbot.navigation.surface_labels import (COVERED, ELEVATED, SURFACE,  # noqa: E402
                                              SurfaceLabeler)
from wowbot.world_geometry.terrain_maps import TrinityMapTerrain  # noqa: E402

COLOURS = {SURFACE: (150, 150, 150), COVERED: (120, 60, 160), ELEVATED: (235, 150, 40)}


def render(label_map, navmesh, path: Path, size: int = 2400, window=None, markers=None) -> None:
    """``window`` = (centre_x, centre_y, half_size_yd) limits the view."""
    from PIL import Image, ImageDraw
    polygons = {}
    for key in label_map.labels:
        tile = key[0] % 10_000
        polygons.setdefault((tile // 100, tile % 100), set()).add(key)
    points = []
    shapes = []
    caves = {region.region_id for region in label_map.regions if region.kind == "CAVE"}
    for (gx, gy), keys in polygons.items():
        for poly in navmesh._load_tile(label_map.instance_id, gx, gy):
            if poly.key not in keys:
                continue
            world = [(v[2], v[0]) for v in poly.vertices]
            if window and (abs(world[0][0]-window[0]) > window[2] or abs(world[0][1]-window[1]) > window[2]):
                continue
            points.extend(world)
            label = label_map.labels[poly.key]
            colour = COLOURS.get(label, (60, 60, 60))
            if label == COVERED and label_map.region_of[poly.key] in caves:
                colour = (210, 90, 255)
            shapes.append((world, colour))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    scale = (size - 20) / max(max_x - min_x, max_y - min_y)

    def screen(x, y):
        # North (+x) up, west (+y) left: matches the in-game map orientation.
        return 10 + (max_y - y) * scale, 10 + (max_x - x) * scale

    image = Image.new("RGB", (size, size), (20, 20, 28))
    draw = ImageDraw.Draw(image)
    for world, colour in shapes:
        draw.polygon([screen(x, y) for x, y in world], fill=colour)
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("arial.ttf", max(14, size // 70))
    except OSError:
        font = ImageFont.load_default()
    for number, region in enumerate(sorted((r for r in label_map.regions if r.kind == "CAVE"),
                                           key=lambda r: -r.area), start=1):
        x, y, _z = region.centroid
        if window and (abs(x-window[0]) > window[2] or abs(y-window[1]) > window[2]):
            continue
        sx, sy = screen(x, y)
        draw.text((sx + 10, sy - 10), f"B{number}", fill=(255, 255, 255), font=font,
                  stroke_width=2, stroke_fill=(0, 0, 0))
    for name, (x, y) in (markers or {}).items():
        sx, sy = screen(x, y)
        draw.rectangle((sx - 7, sy - 7, sx + 7, sy + 7), outline=(80, 220, 255), width=3)
        draw.text((sx + 10, sy + 4), name, fill=(80, 220, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    legend = [("felszín (SURFACE)", COLOURS[SURFACE]), ("fedett / sziklaalj", COLOURS[COVERED]),
              ("BARLANG (CAVE)", (210, 90, 255)), ("emelt: híd, épület", COLOURS[ELEVATED]),
              ("bejárat + befelé irány", (255, 40, 40)), ("É = fel, Ny = balra", (220, 220, 220))]
    for row, (text, colour) in enumerate(legend):
        top = 12 + row * (font.size + 8)
        draw.rectangle((12, top, 12 + font.size, top + font.size), fill=colour)
        draw.text((20 + font.size, top - 2), text, fill=(235, 235, 235), font=font)
    for entrance in label_map.entrances:
        x, y, _z = entrance["centre_world"]
        sx, sy = screen(x, y)
        dx, dy = entrance["inward_direction"]
        draw.ellipse((sx - 6, sy - 6, sx + 6, sy + 6), outline=(255, 40, 40), width=3)
        draw.line((sx, sy, sx - dy * 25, sy - dx * 25), fill=(255, 40, 40), width=3)
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", type=int, default=2175)
    parser.add_argument("--around", type=float, nargs=3, metavar=("X", "Y", "HALF"),
                        help="also render a zoomed view around world X,Y (half size in yd)")
    parser.add_argument("--retail", default=os.environ.get(
        "WOWBOT_WORLD_DATA_PATH", r"C:\Program Files (x86)\World of Warcraft\_retail_"))
    parser.add_argument("--mmaps", default=json.loads(
        (ROOT / "output/agent/agent_gui.json").read_text(encoding="utf-8")).get("mmap_path"))
    args = parser.parse_args()
    navmesh = TrinityMMapNavMesh(args.mmaps)
    terrain = TrinityMapTerrain(args.retail, max_cached_tiles=64)
    started = time.perf_counter()
    label_map = SurfaceLabeler(navmesh, terrain).build(args.map)
    seconds = time.perf_counter() - started
    out = ROOT / "output" / "navigation"
    out.mkdir(parents=True, exist_ok=True)
    data = {**label_map.to_dict(), "build_seconds": round(seconds, 1)}
    (out / f"surface_labels_{args.map}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    render(label_map, navmesh, out / f"surface_labels_{args.map}.png")
    if args.around:
        render(label_map, navmesh, out / f"surface_labels_{args.map}_zoom.png", size=1600,
               window=tuple(args.around),
               markers={"Cooking Meat": (-196., -2507.)} if args.map == 2175 else None)
    print(json.dumps(label_map.stats, indent=1))
    print(f"build {seconds:.1f} s")
    for region in sorted(label_map.regions, key=lambda r: -r.area):
        if region.kind == "CAVE" and (not args.around or (
                abs(region.centroid[0]-args.around[0]) <= args.around[2]
                and abs(region.centroid[1]-args.around[1]) <= args.around[2])):
            print("CAVE", region.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
