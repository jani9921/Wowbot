from __future__ import annotations

import math
from typing import Optional

import numpy as np

from wowbot.vision.minimap_geometry import MinimapGeometry
from wowbot.vision.models import (
    DetectedFeature,
    FeatureType,
    HeadingObservation,
    MapPoint,
    MarkerObservation,
    MinimapObservation,
)


def detect_minimap(
    buffer: bytes,
    width: int,
    height: int,
    *,
    observed_at: float = 0.0,
    geometry: MinimapGeometry | None = None,
    heading_degrees: float | None = None,
) -> MinimapObservation:
    """Detect local minimap facts; never emits movement/input commands."""
    geometry = geometry or MinimapGeometry()
    center = geometry.center(width, height)
    radius = geometry.radius(width, height)
    target = _detect_target(buffer, width, height, center, radius)
    markers: list[MarkerObservation] = []
    if target is not None:
        markers.append(target)

    pixels = _rgba(buffer, width, height)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    yy, xx = _ogrid(height, width)
    inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < radius**2

    quest_related = _detect_quest_related_ring(
        pixels, width, height, center, radius, target_marker=target
    )
    markers.extend(quest_related)

    symbol_markers = _detect_quest_symbols(
        pixels, width, height, center, radius, target_marker=target, quest_rings=quest_related
    )
    markers.extend(symbol_markers)

    direction_marker = _detect_quest_direction_arrow(
        pixels, width, height, center, radius, target_marker=target, quest_rings=quest_related, symbol_markers=symbol_markers
    )
    if direction_marker is not None:
        markers.append(direction_marker)

    treasure_direction_marker = _detect_treasure_direction_arrow(
        pixels, width, height, center, radius,
        target_marker=target, quest_rings=quest_related, symbol_markers=symbol_markers,
        quest_direction=direction_marker,
    )
    if treasure_direction_marker is not None:
        markers.append(treasure_direction_marker)

    # Detection is deliberately broader than recognition.  Compact, locally
    # salient shapes in the useful inner disc become UNKNOWN observations even
    # when they do not match one of today's colour/symbol rules.  The rim is
    # excluded because Retail draws fixed cardinal/frame ornaments there.
    markers.extend(_detect_unknown_markers(pixels, center, radius, markers))

    blue_mask = (blue > 85) & (blue.astype(int) > red.astype(int) + 25) & inside
    if blue_mask.any():
        dilated = blue_mask.copy()
        dilated[1:, :] |= blue_mask[:-1, :]
        dilated[:-1, :] |= blue_mask[1:, :]
        dilated[:, 1:] |= blue_mask[:, :-1]
        dilated[:, :-1] |= blue_mask[:, 1:]
        candidates = []
        for component in _components(_mask_points(dilated)):
            if not 80 <= len(component) <= 1400:
                continue
            xs, ys = zip(*component)
            box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if not (20 <= box_w <= 50 and 18 <= box_h <= 40):
                continue
            p = MapPoint(round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2))
            d = math.hypot(p.x - center.x, p.y - center.y)
            candidates.append((d, -len(component), p, component))
        if candidates:
            _, _, p, component = min(candidates)
            # Keep the same proven inside-area rule as the original adapter.
            quest = center if _component_encloses(component, center) else p
            xs, ys = zip(*component)
            markers.append(MarkerObservation(
                "unknown_minimap_marker", quest, 0.88,
                candidate_labels=("blue_region_like",),
                evidence=("appearance_only", "blue_region_like", "area_geometry"),
                bbox=(min(xs), min(ys), max(xs) + 1, max(ys) + 1)))

    # The entire detector stack above only proposes appearance evidence.  Its
    # historical names are retained as specialist CV implementations, while
    # this public runtime boundary removes all semantic claims.
    usable_radius = radius * .80
    normalized: list[MarkerObservation] = []
    for marker in markers:
        distance = math.hypot(marker.position.x-center.x, marker.position.y-center.y)
        if distance > usable_radius:
            continue
        label = marker.candidate_labels[0] if marker.candidate_labels else "visual_marker_like"
        normalized.append(MarkerObservation(
            "unknown_minimap_marker", marker.position, marker.confidence,
            marker_color=marker.marker_color, symbol=None,
            bearing_degrees=marker.bearing_degrees,
            candidate_labels=marker.candidate_labels or (label,),
            evidence=marker.evidence or ("appearance_only", label),
            bbox=marker.bbox,
        ))
    features: list[DetectedFeature] = []
    heading = None
    if isinstance(heading_degrees, (int, float)) and math.isfinite(float(heading_degrees)):
        # Telemetry-calibrated player heading is distinct from any visual
        # marker class; it is never inferred from the minimap rim.
        heading = HeadingObservation(float(heading_degrees) % 360., .92)
    return MinimapObservation(
        width=width,
        height=height,
        player_marker=center,
        heading=heading,
        markers=tuple(normalized),
        features=tuple(features),
        observed_at=observed_at,
        center_radius_px=radius,
        usable_radius_px=usable_radius,
    )


def _detect_unknown_markers(
    pixels: np.ndarray,
    center: MapPoint,
    radius: float,
    recognized: list[MarkerObservation],
) -> list[MarkerObservation]:
    """Return appearance-only candidates from the inner minimap disc.

    This detector intentionally has no colour-to-meaning table.  Local visual
    contrast proposes a candidate; temporal tracking and mouseover/addon facts
    must establish what it means.  Keeping the outer 18% masked prevents the
    four decorative frame arrows from becoming hover targets.
    """
    b = pixels[:, :, 0].astype(np.int16)
    g = pixels[:, :, 1].astype(np.int16)
    r = pixels[:, :, 2].astype(np.int16)
    luminance = (r * 3 + g * 6 + b) // 10
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    local = np.zeros_like(luminance)
    for dy, dx in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        shifted = np.roll(luminance, (dy, dx), axis=(0, 1))
        local = np.maximum(local, np.abs(luminance - shifted))
    yy, xx = _ogrid(pixels.shape[0], pixels.shape[1])
    radial = (xx - center.x) ** 2 + (yy - center.y) ** 2
    useful_disc = (radial < (radius * .82) ** 2) & (radial > (radius * .10) ** 2)
    mask = useful_disc & (local >= 48) & ((chroma >= 38) | (luminance >= 170))

    # Join the pixels of a tiny antialiased icon, without growing terrain into
    # a large component.  Geometry is only a proposal filter, not recognition.
    grown = mask.copy()
    grown[1:, :] |= mask[:-1, :]
    grown[:-1, :] |= mask[1:, :]
    grown[:, 1:] |= mask[:, :-1]
    grown[:, :-1] |= mask[:, 1:]
    exclusions = [(m.position.x, m.position.y, 11.0) for m in recognized]
    scored: list[tuple[float, MarkerObservation]] = []
    for component in _components(_mask_points(grown)):
        n = len(component)
        if not 5 <= n <= 150:
            continue
        xs, ys = zip(*component)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (2 <= bw <= 16 and 2 <= bh <= 16):
            continue
        if min(bw, bh) / max(bw, bh) < .38:
            continue
        point = MapPoint(round(sum(xs) / n), round(sum(ys) / n))
        if any(math.hypot(point.x-ex, point.y-ey) <= er for ex, ey, er in exclusions):
            continue
        contrast = float(np.mean([local[y, x] for x, y in component]))
        confidence = min(.78, .42 + contrast / 500.0 + min(n, 60) / 600.0)
        scored.append((contrast + n / 4.0, MarkerObservation(
            "unknown_minimap_marker", point, confidence,
            candidate_labels=("salient_marker_like",),
            evidence=("appearance_only", "salient_marker_like"))))
    # A noisy terrain frame must not flood the temporal tracker.
    return [marker for _, marker in sorted(scored, key=lambda row: row[0], reverse=True)[:6]]


def _detect_quest_symbols(
    pixels,
    width: int,
    height: int,
    center: MapPoint,
    radius: float,
    *,
    target_marker: Optional[MarkerObservation] = None,
    quest_rings: list[MarkerObservation] | None = None,
) -> list[MarkerObservation]:
    """Detect the two-part yellow/orange quest NPC symbols on the minimap.

    Conservative visual rule:
    - a quest-giver/turn-in icon is a vertically stacked glyph (symbol + dot),
      unlike the selected-target marker which is only a dot;
    - ! is narrower/taller in its upper stroke;
    - ? has a wider curved upper stroke.

    This is a visual hint only. Identity is not inferred here.
    """
    r = pixels[:, :, 2].astype(int)
    g = pixels[:, :, 1].astype(int)
    b = pixels[:, :, 0].astype(int)
    yy, xx = _ogrid(height, width)
    dist2 = (xx - center.x) ** 2 + (yy - center.y) ** 2
    inside = dist2 < radius ** 2
    # Gold/yellow UI glyph, deliberately more saturated than the map background.
    mask = (r > 150) & (g > 75) & (b < 120) & (r > g + 35) & (g > b + 15) & inside

    # A selected-target marker can sit immediately beside UI/map pixels of the
    # same yellow family. Those tiny target pixels must never be assembled into
    # a quest glyph. When a target marker is already confirmed, keep a small
    # exclusion radius around it for quest-glyph extraction. A real quest glyph
    # elsewhere on the minimap remains eligible.
    if target_marker is not None:
        tx, ty = target_marker.position.x, target_marker.position.y
        target_exclusion = (xx - tx) ** 2 + (yy - ty) ** 2 <= 12 ** 2
        mask &= ~target_exclusion
    if quest_rings:
        for ring in quest_rings:
            qx, qy = ring.position.x, ring.position.y
            # Keep glyph detection out of the larger quest-related ring and
            # its antialiased edge.
            ring_exclusion = (xx - qx) ** 2 + (yy - qy) ** 2 <= 16 ** 2
            mask &= ~ring_exclusion
    comps = []
    for component in _components(_mask_points(mask)):
        n = len(component)
        if not 2 <= n <= 60:
            continue
        xs, ys = zip(*component)
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if 1 <= bw <= 12 and 1 <= bh <= 18:
            comps.append((component, x0, x1, y0, y1, n))

    # Pair close components into a glyph group. A selected-target dot is left
    # as a single component and is handled by _detect_target().
    used: set[int] = set()
    out: list[MarkerObservation] = []
    for i, a in enumerate(comps):
        if i in used:
            continue
        best_j = None
        best_gap = None
        ax0, ax1, ay0, ay1 = a[1:5]
        acx = (ax0 + ax1) / 2
        for j in range(i + 1, len(comps)):
            if j in used:
                continue
            c = comps[j]
            bx0, bx1, by0, by1 = c[1:5]
            bcx = (bx0 + bx1) / 2
            # Must be vertically aligned and have a small vertical gap.
            overlap = min(ax1, bx1) - max(ax0, bx0) + 1
            if overlap <= 0:
                continue
            if abs(acx - bcx) > max(3.0, 0.55 * max(ax1 - ax0 + 1, bx1 - bx0 + 1)):
                continue
            top, bottom = sorted(((ay0, ay1), (by0, by1)))
            gap = bottom[0] - top[1] - 1
            if not (0 <= gap <= 10):
                continue
            if best_gap is None or gap < best_gap:
                best_gap, best_j = gap, j
        if best_j is None:
            continue
        b = comps[best_j]
        used.add(i); used.add(best_j)
        x0, x1 = min(a[1], b[1]), max(a[2], b[2])
        y0, y1 = min(a[3], b[3]), max(a[4], b[4])
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (2 <= bw <= 16 and 5 <= bh <= 26):
            continue
        top = a if a[3] <= b[3] else b
        bottom = b if top is a else a
        top_w = top[2] - top[1] + 1
        top_h = top[4] - top[3] + 1
        bottom_w = bottom[2] - bottom[1] + 1
        bottom_h = bottom[4] - bottom[3] + 1

        # A selected-target dot can fragment into two tiny antialiased blobs.
        # Reject compact dot-like pairs before classifying quest glyphs.
        if (top_w <= 4 and top_h <= 4 and bottom_w <= 4 and bottom_h <= 4 and bw <= 6 and bh <= 9):
            continue
        # Quest glyphs have a real upper stroke, not merely another tiny dot.
        if top_h < 3 and top_w < 5:
            continue
        # Conservative symbol classification by upper-stroke geometry.
        symbol = "!" if (top_w <= max(3, int(0.42 * bw)) and top_h >= 3) else "?"
        px = round((x0 + x1) / 2)
        py = round((y0 + y1) / 2)
        conf = min(0.97, 0.72 + 0.02 * min(len(a[0]) + len(b[0]), 12))
        label = "exclamation_symbol_like" if symbol == "!" else "question_symbol_like"
        out.append(MarkerObservation("unknown_minimap_marker", MapPoint(px, py), conf,
                                     marker_color="yellow", candidate_labels=(label,),
                                     evidence=("appearance_only", label)))
    return out



def _detect_quest_direction_arrow(
    pixels,
    width: int,
    height: int,
    center: MapPoint,
    radius: float,
    *,
    target_marker: Optional[MarkerObservation] = None,
    quest_rings: list[MarkerObservation] | None = None,
    symbol_markers: list[MarkerObservation] | None = None,
) -> Optional[MarkerObservation]:
    """Detect the small gold quest-direction arrow near the minimap perimeter.

    This is intentionally conservative. The arrow is a directional hint, not a
    quest destination itself. We report its screen-space bearing from the
    minimap center: 0=up, 90=right, 180=down, 270=left.
    """
    r = pixels[:, :, 2].astype(int)
    g = pixels[:, :, 1].astype(int)
    b = pixels[:, :, 0].astype(int)
    yy, xx = _ogrid(height, width)
    dist2 = (xx - center.x) ** 2 + (yy - center.y) ** 2
    inside = dist2 < (radius * 0.90) ** 2
    outside = dist2 > (radius * 0.52) ** 2
    gold = (r > 150) & (g > 95) & (b < 125) & (r > g + 20) & (g > b + 15) & inside & outside

    exclusions: list[tuple[float, float, float]] = []
    if target_marker is not None:
        exclusions.append((target_marker.position.x, target_marker.position.y, 13.0))
    for marker in quest_rings or []:
        exclusions.append((marker.position.x, marker.position.y, 14.0))
    for marker in symbol_markers or []:
        exclusions.append((marker.position.x, marker.position.y, 12.0))
    for ex, ey, er in exclusions:
        gold &= (xx - ex) ** 2 + (yy - ey) ** 2 > er ** 2

    candidates: list[tuple[float, int, MapPoint]] = []
    for component in _components(_mask_points(gold)):
        n = len(component)
        if not 12 <= n <= 120:
            continue
        xs, ys = zip(*component)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (5 <= bw <= 20 and 6 <= bh <= 20):
            continue
        aspect = min(bw, bh) / max(bw, bh)
        if aspect < 0.35:
            continue
        px = round(sum(xs) / n)
        py = round(sum(ys) / n)
        radial = math.hypot(px - center.x, py - center.y)
        if radial < radius * 0.55 or radial > radius * 0.90:
            continue
        # Direction-arrow references are compact and moderately filled, unlike
        # the large map frame and the larger quest-related ring.
        fill = n / float(bw * bh)
        if fill < 0.22:
            continue
        candidates.append((radial, -n, MapPoint(px, py)))

    if not candidates:
        return None
    _, neg_n, point = min(candidates, key=lambda item: (item[0], item[1]))
    dx = point.x - center.x
    dy = point.y - center.y
    bearing = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
    confidence = min(0.94, 0.60 + (-neg_n) / 250.0)
    return MarkerObservation(
        "unknown_minimap_marker",
        point,
        confidence,
        marker_color="yellow",
        symbol=None,
        bearing_degrees=round(bearing, 2),
        candidate_labels=("gold_direction_like",),
        evidence=("appearance_only", "gold_direction_like"),
    )


def _detect_treasure_direction_arrow(
    pixels,
    width: int,
    height: int,
    center: MapPoint,
    radius: float,
    *,
    target_marker: Optional[MarkerObservation] = None,
    quest_rings: list[MarkerObservation] | None = None,
    symbol_markers: list[MarkerObservation] | None = None,
    quest_direction: Optional[MarkerObservation] = None,
) -> Optional[MarkerObservation]:
    """Detect the small blue/gray treasure-direction arrow near the minimap rim.

    The treasure arrow is visually distinct from the gold quest arrow: it is
    blue-gray with a bright interior/edge and sits close to the minimap
    perimeter. It is reported as a directional hint only.
    """
    r = pixels[:, :, 2].astype(int)
    g = pixels[:, :, 1].astype(int)
    b = pixels[:, :, 0].astype(int)
    yy, xx = _ogrid(height, width)
    dist2 = (xx - center.x) ** 2 + (yy - center.y) ** 2
    radial = np.sqrt(dist2)
    inside = (radial < radius * 0.94) & (radial > radius * 0.58)

    # Blue-gray arrow: blue channel leads, but red/green remain substantial,
    # unlike saturated blue quest-area contours. This shape also excludes most
    # brown/orange map terrain and the gold quest arrow.
    blue_gray = (
        (b > 115)
        & (b > r + 12)
        & (b > g + 2)
        & (r > 45)
        & (g > 55)
        & (np.abs(g - r) < 75)
        & inside
    )

    exclusions: list[tuple[float, float, float]] = []
    if target_marker is not None:
        exclusions.append((target_marker.position.x, target_marker.position.y, 12.0))
    for marker in quest_rings or []:
        exclusions.append((marker.position.x, marker.position.y, 14.0))
    for marker in symbol_markers or []:
        exclusions.append((marker.position.x, marker.position.y, 12.0))
    if quest_direction is not None:
        exclusions.append((quest_direction.position.x, quest_direction.position.y, 13.0))
    for ex, ey, er in exclusions:
        blue_gray &= (xx - ex) ** 2 + (yy - ey) ** 2 > er ** 2

    candidates: list[tuple[float, int, float, MapPoint]] = []
    for component in _components(_mask_points(blue_gray)):
        n = len(component)
        if not 15 <= n <= 140:
            continue
        xs, ys = zip(*component)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (6 <= bw <= 22 and 6 <= bh <= 22):
            continue
        aspect = min(bw, bh) / max(bw, bh)
        if aspect < 0.42:
            continue
        fill = n / float(bw * bh)
        if fill < 0.20:
            continue
        px = round(sum(xs) / n)
        py = round(sum(ys) / n)
        rr = math.hypot(px - center.x, py - center.y)
        if not (radius * 0.60 <= rr <= radius * 0.94):
            continue
        # Arrow references are compact but usually show a slightly brighter
        # core than surrounding terrain.
        local_bright = (r[min(height - 1, py), min(width - 1, px)]
                        + g[min(height - 1, py), min(width - 1, px)]
                        + b[min(height - 1, py), min(width - 1, px)]) / 3.0
        candidates.append((rr, -n, local_bright, MapPoint(px, py)))

    if not candidates:
        return None
    _, neg_n, local_bright, point = min(candidates, key=lambda item: (item[0], item[1]))
    dx = point.x - center.x
    dy = point.y - center.y
    bearing = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
    confidence = min(0.93, 0.56 + (-neg_n) / 260.0 + max(0.0, local_bright - 120.0) / 1000.0)
    return MarkerObservation(
        "unknown_minimap_marker",
        point,
        confidence,
        marker_color="blue_gray",
        symbol=None,
        bearing_degrees=round(bearing, 2),
        candidate_labels=("blue_gray_direction_like",),
        evidence=("appearance_only", "blue_gray_direction_like"),
    )


def _detect_target(buffer: bytes, width: int, height: int, center: MapPoint, radius: float) -> Optional[MarkerObservation]:
    pixels = _rgba(buffer, width, height)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    yy, xx = _ogrid(height, width)
    inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < radius**2
    r, g, b = red.astype(int), green.astype(int), blue.astype(int)
    red_dot = (r > 170) & (r > g + 45) & (r > b + 45) & inside
    yellow_dot = (r > 185) & (g > 120) & (b < 110) & (r > b + 80) & inside
    green_dot = (g > 165) & (g > r + 45) & (g > b + 45) & inside
    mask = red_dot | yellow_dot | green_dot
    candidates: list[tuple[int, float, MapPoint, str, float]] = []
    for component in _components(_mask_points(mask)):
        size = len(component)
        if not 2 <= size <= 90:
            continue
        xs, ys = zip(*component)
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        # Selected-target markers are compact dots. Quest !/? glyph strokes
        # are elongated, so accepting only near-square components prevents a
        # quest glyph stroke from being mistaken for the target itself.
        if not (2 <= box_w <= 8 and 2 <= box_h <= 8):
            continue
        aspect = min(box_w, box_h) / max(box_w, box_h)
        if aspect < 0.72:
            continue
        fill_ratio = size / float(box_w * box_h)
        if fill_ratio < 0.22:
            continue
        p = MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
        # Selected target markers have a visible light/white halo around the
        # coloured target core. Quest-related yellow rings do not. Treat the
        # halo as a strong discriminator, while allowing a slightly weaker
        # fallback for very close/antialiased live targets.
        white_support = _white_halo_score(pixels, p, max(box_w, box_h))
        d = math.hypot(p.x - center.x, p.y - center.y)
        if d < 2:
            continue
        pts = list(component)
        red_count = sum(bool(red_dot[y, x]) for x, y in pts)
        yellow_count = sum(bool(yellow_dot[y, x]) for x, y in pts)
        green_count = sum(bool(green_dot[y, x]) for x, y in pts)
        counts = {"red": red_count, "yellow": yellow_count, "green": green_count}
        chosen_color = max(counts, key=counts.get)
        if counts[chosen_color] == 0:
            chosen_color = "unknown"
        candidates.append((size, d, p, chosen_color, white_support))
    if not candidates:
        return None
        # Prefer compact candidates that also have the observed light/white halo.
    # The halo is a discriminator, not a hard requirement, because some live
    # antialiased frames expose only part of it.
    strongest = max(candidates, key=lambda item: (item[4] >= 0.20, item[0]))
    best = min(candidates, key=lambda item: (item[1], -item[0]))
    chosen = strongest if (strongest[4] >= 0.20 or strongest[0] >= 2 * max((c[0] for c in candidates if c is not strongest), default=0)) else best
    marker_color = chosen[3]
    return MarkerObservation(
        "unknown_minimap_marker",
        chosen[2],
        min(0.98, 0.55 + chosen[0] / 120.0),
        marker_color=marker_color,
        relation=None,
        candidate_labels=("selected_target_like",),
        evidence=("appearance_only", "selected_target_like"),
    )


def _white_halo_score(pixels, point: MapPoint, core_size: int) -> float:
    r = pixels[:, :, 2].astype(int)
    g = pixels[:, :, 1].astype(int)
    b = pixels[:, :, 0].astype(int)
    x, y = int(point.x), int(point.y)
    outer = max(4, min(9, int(core_size) + 2))
    inner = max(1, int(core_size // 2))
    y0, y1 = max(0, y - outer), min(pixels.shape[0], y + outer + 1)
    x0, x1 = max(0, x - outer), min(pixels.shape[1], x + outer + 1)
    yy, xx = _ogrid(y1 - y0, x1 - x0)
    rr2 = (xx - (x - x0)) ** 2 + (yy - (y - y0)) ** 2
    annulus = (rr2 >= inner ** 2) & (rr2 <= outer ** 2)
    white = (r[y0:y1, x0:x1] > 175) & (g[y0:y1, x0:x1] > 175) & (b[y0:y1, x0:x1] > 175)
    denom = int(annulus.sum())
    if denom <= 0:
        return 0.0
    return float((white & annulus).sum()) / denom


def _detect_quest_related_ring(
    pixels, width: int, height: int, center: MapPoint, radius: float,
    *, target_marker: Optional[MarkerObservation] = None,
    symbol_markers: list[MarkerObservation] | None = None,
) -> list[MarkerObservation]:
    """Detect the larger plain-yellow quest-related ring/area marker.

    The user reference shows a yellow circular marker/ring without the light
    border seen around selected targets. It is intentionally reported only as
    QUEST_RELATED so later quest reasoning can refine whether it denotes an
    item, NPC, or another quest location.
    """
    r = pixels[:, :, 2].astype(int)
    g = pixels[:, :, 1].astype(int)
    b = pixels[:, :, 0].astype(int)
    yy, xx = _ogrid(height, width)
    inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < (radius * 0.92) ** 2
    # Strong yellow/gold, distinct from blue map contour.
    yellow = (r > 165) & (g > 95) & (b < 115) & (r > g + 25) & (g > b + 20) & inside
    components = _components(_mask_points(yellow))
    out: list[MarkerObservation] = []
    target_point = target_marker.position if target_marker is not None else None
    for component in components:
        n = len(component)
        if not 30 <= n <= 900:
            continue
        xs, ys = zip(*component)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (10 <= bw <= 70 and 10 <= bh <= 70):
            continue
        aspect = min(bw, bh) / max(bw, bh)
        if aspect < 0.60:
            continue
        px = round(sum(xs) / n)
        py = round(sum(ys) / n)
        # Approximate ringness: a filled disk would have too much yellow in
        # the central third. A ring has a relatively sparse centre.
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        rr = max(1.0, min(bw, bh) * 0.5)
        central = sum((x - cx) ** 2 + (y - cy) ** 2 <= (0.32 * rr) ** 2 for x, y in component)
        outer = sum((x - cx) ** 2 + (y - cy) ** 2 >= (0.62 * rr) ** 2 for x, y in component)
        if outer < 24 or central > max(18, int(0.55 * outer)):
            continue
        if target_point is not None and math.hypot(px - target_point.x, py - target_point.y) < 18:
            continue
        # A plain quest-related ring deliberately has little/no white halo.
        halo = _white_halo_score(pixels, MapPoint(px, py), max(2, min(bw, bh)))
        if halo > 0.35:
            continue
        conf = min(0.93, 0.60 + min(0.25, n / 1800.0))
        out.append(
            MarkerObservation(
                "unknown_minimap_marker",
                MapPoint(px, py),
                conf,
                marker_color="yellow",
                relation=None,
                candidate_labels=("ring_like",),
                evidence=("appearance_only", "ring_like"),
            )
        )
    return out


def _target_color(point: MapPoint, pixels) -> str:
    """Return the raw selected-target marker colour family at its centroid.

    The colour is retained as an observation; downstream systems may combine
    it with other evidence before treating the relation as confirmed.
    """
    x, y = int(point.x), int(point.y)
    y0, y1 = max(0, y - 2), min(pixels.shape[0], y + 3)
    x0, x1 = max(0, x - 2), min(pixels.shape[1], x + 3)
    patch = pixels[y0:y1, x0:x1, :3].reshape(-1, 3)
    # RGBA/RGB input is normalized to (R,G,B) by _rgba's channel access.
    # Use the dominant evidence rather than a single pixel.
    if len(patch) == 0:
        return "unknown"
    r = patch[:, 0].astype(int)
    g = patch[:, 1].astype(int)
    b = patch[:, 2].astype(int)
    scores = {
        "red": float((r - g).mean() + (r - b).mean()),
        "green": float((g - r).mean() + (g - b).mean()),
        "yellow": float((r + g - 2 * b).mean()),
    }
    color, score = max(scores.items(), key=lambda item: item[1])
    return color if score > 25 else "unknown"


def _rgba(buffer: bytes, width: int, height: int):
    import numpy as np
    return np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)


def _ogrid(height: int, width: int):
    import numpy as np
    return np.ogrid[:height, :width]


def _mask_points(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    return set(zip(xs.tolist(), ys.tolist()))


def _components(points: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    remaining = set(points)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        component = [start]
        stack = [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x-1,y),(x+1,y),(x,y-1),(x,y+1),(x-1,y-1),(x+1,y-1),(x-1,y+1),(x+1,y+1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components


def _component_encloses(component: list[tuple[int, int]], point: MapPoint) -> bool:
    blocked = set(component)
    xs, ys = [pixel[0] for pixel in component], [pixel[1] for pixel in component]
    left, right, top, bottom = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    if not (left < point.x < right and top < point.y < bottom):
        return False
    if (point.x, point.y) in blocked:
        return True
    outside = {(left, top)}
    stack = [(left, top)]
    while stack:
        x, y = stack.pop()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if left <= nx <= right and top <= ny <= bottom and neighbor not in blocked and neighbor not in outside:
                outside.add(neighbor)
                stack.append(neighbor)
    return (point.x, point.y) not in outside
