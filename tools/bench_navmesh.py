"""Measure the mmap router (step 1 of docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md).

Random polygon pairs at several distances on one map: route time (cold graph
build vs warm cache), loaded / route polygons, failure reasons, and how often
an x,y has several stacked walkable layers (the 2D-leak risk).

Usage: python tools/bench_navmesh.py [--mmaps PATH] [--map 2175] [--pairs 20]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh  # noqa: E402


def map_tiles(mesh: TrinityMMapNavMesh, instance_id: int) -> list[tuple[int, int]]:
    names = mesh.source.names() if hasattr(mesh.source, "names") else []
    if not names:
        import zipfile
        path = Path(mesh.source.path)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = [Path(name).name for name in archive.namelist()]
        else:
            names = [item.name for item in path.iterdir()]
    tiles = []
    for name in names:
        if name.startswith(f"{instance_id:04d}_") and name.endswith(".mmtile"):
            _, gx, gy = name[:-7].split("_")
            tiles.append((int(gx), int(gy)))
    return sorted(tiles)


def world_point(mesh, poly, instance_id: int) -> dict:
    point = mesh._detour_to_world(poly.center, instance_id)
    return {**point, "instance_id": instance_id, "coordinate_space": "WORLD_YARDS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmaps", default=json.loads(
        (ROOT / "output/agent/agent_gui.json").read_text(encoding="utf-8")).get("mmap_path"))
    parser.add_argument("--map", type=int, default=2175)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    random.seed(args.seed)
    mesh = TrinityMMapNavMesh(args.mmaps)
    tiles = map_tiles(mesh, args.map)
    started = time.perf_counter()
    polygons = [poly for gx, gy in tiles for poly in mesh._load_tile(args.map, gx, gy)
                if poly.flags & mesh.allowed_flags]
    load_seconds = time.perf_counter() - started
    print(f"map {args.map}: {len(tiles)} tiles, {len(polygons)} walkable polygons, "
          f"tile parse {load_seconds:.1f} s")

    # Stacked layers: walkable polygon centres sharing a 2 yd x,y bin with
    # a height difference > 4 yd (bridge over path, cave under hill).
    bins = collections.defaultdict(list)
    for poly in polygons:
        x, y, z = poly.center
        bins[(round(x / 2), round(z / 2))].append(y)
    stacked = sum(1 for heights in bins.values() if max(heights) - min(heights) > 4.)
    print(f"stacked x,y bins (>4 yd apart): {stacked} of {len(bins)} "
          f"({100 * stacked / max(1, len(bins)):.2f} %)")

    # Same connected walkable area only: the map also has islands and sea
    # floor; a pair across them is legitimately unreachable.
    started = time.perf_counter()
    by_key = {poly.key: poly for poly in polygons}
    adjacency, _portals = mesh._adjacency(by_key)
    component, components = {}, []
    for key in by_key:
        if key in component:
            continue
        stack, members = [key], []
        component[key] = len(components)
        while stack:
            current = stack.pop()
            members.append(current)
            for other in adjacency[current]:
                if other not in component:
                    component[other] = len(components)
                    stack.append(other)
        components.append(members)
    components.sort(key=len, reverse=True)
    main = [by_key[key] for key in components[0]]
    print(f"global adjacency {time.perf_counter() - started:.1f} s; components {len(components)}, "
          f"largest {len(main)} polys ({100 * len(main) / len(polygons):.0f} %), next "
          f"{[len(c) for c in components[1:4]]}")
    polygons = main
    cells = collections.defaultdict(list)
    for poly in polygons:
        cells[(int(poly.center[0] // 50), int(poly.center[2] // 50))].append(poly)

    def partner(first, distance):
        cx, cz = first.center[0], first.center[2]
        for _ in range(40):
            angle = random.random() * math.tau
            tx, tz = cx + distance * math.cos(angle), cz + distance * math.sin(angle)
            cell = cells.get((int(tx // 50), int(tz // 50)))
            if cell:
                return random.choice(cell)
        return None

    for distance in (50., 200., 500., 1000., 2000.):
        times_cold, times_warm, route_polys, loaded, reasons = [], [], [], [], collections.Counter()
        attempts = 0
        while len(times_cold) < args.pairs and attempts < args.pairs * 200:
            attempts += 1
            first = random.choice(polygons)
            second = partner(first, distance)
            if second is None:
                continue
            d = math.dist((first.center[0], first.center[2]), (second.center[0], second.center[2]))
            if not .7 * distance <= d <= 1.3 * distance:
                continue
            start = world_point(mesh, first, args.map)
            goal = world_point(mesh, second, args.map)
            mesh._graph_cache.clear()
            t = time.perf_counter()
            path = mesh.find_path(args.map, start, goal)
            times_cold.append(time.perf_counter() - t)
            reasons[mesh.last_diagnostics.get("reason")] += 1
            if path is not None:
                route_polys.append(path.polygon_count)
                loaded.append(mesh.last_diagnostics.get("loaded_polygon_count", 0))
                t = time.perf_counter()
                mesh.find_path(args.map, start, goal)
                times_warm.append(time.perf_counter() - t)
        if not times_cold:
            print(f"{distance:6.0f} yd: no pairs")
            continue
        def ms(values):
            return f"{1000 * statistics.median(values):7.1f} / {1000 * max(values):7.1f} ms" if values else "   n/a"
        print(f"{distance:6.0f} yd: n={len(times_cold):2d} cold med/max {ms(times_cold)} | warm {ms(times_warm)} | "
              f"route polys med {statistics.median(route_polys) if route_polys else 0:5.0f} | "
              f"loaded med {statistics.median(loaded) if loaded else 0:6.0f} | {dict(reasons)}")
    mesh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
