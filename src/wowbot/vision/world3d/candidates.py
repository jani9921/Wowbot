from __future__ import annotations

from dataclasses import dataclass
import math

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:
    from adapters.numpy_runtime import np

from .models import PixelRect, WorldCandidate, WorldSceneROI


@dataclass(frozen=True, slots=True)
class _Component:
    rect: PixelRect
    area: int
    fill: float
    mean_saturation: float
    mean_brightness: float
    mean_red: float
    mean_green: float
    mean_blue: float


CLASS_COLORS = {
    "death_knight": "#C41E3A",
    "demon_hunter": "#A330C9",
    "druid": "#FF7D0A",
    "evoker": "#33937F",
    "hunter": "#ABD473",
    "mage": "#69CCF0",
    "monk": "#00FF96",
    "paladin": "#F58CBA",
    "priest": "#FFFFFF",
    "rogue": "#FFF569",
    "shaman": "#0070DE",
    "warlock": "#9482C9",
    "warrior": "#C79C6E",
}

# Mage has two commonly observed screen representations. Keep the primary
# color above and accept the alternate client rendering as an alias.
CLASS_COLOR_ALIASES = {
    "mage": {"#3FC7EB"},
}


def _hex_rgb(value: str) -> tuple[float, float, float]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


_CLASS_RGB = {name: _hex_rgb(value) for name, value in CLASS_COLORS.items()}


def _components(mask: np.ndarray, min_area: int = 8, max_area: int = 5000) -> list[tuple[int, int, int, int, int]]:
    """Exact four-connected labelling, joining horizontal runs instead of pixels.

    Bounding boxes, areas and discovery order match the former flood fill. Large
    terrain patches cost one union per row rather than four Python visits/pixel.
    """
    parents, runs = [], []
    previous = []

    def root(label):
        while parents[label] != label:
            parents[label] = parents[parents[label]]
            label = parents[label]
        return label

    # Row-to-row union-find has a genuine sequential dependency (each row's
    # linking needs the previous row's finished runs) so the outer loop
    # can't be vectorized away. But the edge-finding itself is independent
    # per row -- batch the pad+diff once for the whole mask instead of
    # dispatching a fresh numpy call pair per row (this was the same math,
    # just paying numpy call overhead ~height times over).
    all_edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    for y in range(mask.shape[0]):
        edges = np.flatnonzero(all_edges[y]).tolist()
        current, cursor = [], 0
        for left, right in zip(edges[::2], edges[1::2]):
            label = len(parents)
            parents.append(label)
            runs.append((left, y, right, label))
            current.append((left, right, label))
            while cursor < len(previous) and previous[cursor][1] <= left:
                cursor += 1
            index = cursor
            while index < len(previous) and previous[index][0] < right:
                a, b = root(label), root(previous[index][2])
                parents[max(a, b)] = min(a, b)
                index += 1
        previous = current
    boxes = {}
    for left, y, right, label in runs:
        key = root(label)
        if key not in boxes:
            boxes[key] = [left, y, right, y + 1, right - left]
        else:
            box = boxes[key]
            box[0], box[2], box[3] = min(box[0], left), max(box[2], right), y + 1
            box[4] += right - left
    return [tuple(box) for box in boxes.values() if min_area <= box[4] <= max_area]


def _intersects(a: PixelRect, b: PixelRect) -> bool:
    return not (a.right <= b.left or a.left >= b.right or a.bottom <= b.top or a.top >= b.bottom)


def _rgb_stats(c: _Component) -> tuple[float, float, float]:
    return c.mean_red, c.mean_green, c.mean_blue


def _hue_sector(c: _Component) -> str:
    """Classify nameplate color using separated hue sectors.

    Yellow/gold is checked before red so a yellow plate with strong red energy
    from anti-aliasing cannot fall into the hostile bucket.
    """
    r, g, b = _rgb_stats(c)
    mx = max(r, g, b)
    mn = min(r, g, b)
    chroma = mx - mn
    if mx < 70:
        return "other"

    # Priest white is effectively achromatic; keep it as a distinct class
    # palette sector only when it is very bright.
    if mn >= 205 and chroma < 35:
        return "white"

    # Pink/magenta player colors: red + blue both substantial, green lower.
    if r >= 105 and b >= 70 and r - g >= 15 and b - g >= 8:
        return "pink"

    # Warrior's tan/brown class color is distinct enough from the relation
    # yellow to keep as a class cue (higher blue floor and red lead).
    if r >= 145 and g >= 110 and b >= 80 and r - g >= 28 and b >= 0.55 * g:
        return "tan"

    # Yellow/gold: red + green are both strong and close to each other.
    if r >= 105 and g >= 90 and b <= min(r, g) * 0.82 and chroma >= 40:
        if abs(r - g) <= max(42.0, 0.28 * max(r, g)):
            return "yellow"

    # Druid orange/tan player nameplate: red-dominant with meaningful green,
    # but very little blue. This is intentionally separated from hostile red.
    if r >= 95 and g >= 45 and b <= 45 and r >= 1.55 * g and g >= 1.8 * b:
        return "orange"

    # Mage cyan / blue class colors are sufficiently distinct from the
    # relationship colors to be useful as PLAYER/class evidence.
    if b >= 115 and g >= 130 and b >= r * 1.25 and g >= r * 1.15:
        return "cyan"
    if b >= 120 and b - r >= 45 and b - g >= 10:
        return "blue"

    # Monk jade is greener than relation-green but still carries a lot of blue.
    if g >= 180 and b >= 90 and g - r >= 90 and g - b <= 120:
        return "monk_green"

    # Green NPC nameplate.
    if g >= 95 and g - r >= max(22.0, 0.14 * g) and g - b >= max(34.0, 0.18 * g):
        return "green"

    # Red hostile nameplate. Red must lead clearly over both other channels.
    if r >= 100 and r - g >= max(38.0, 0.20 * r) and r - b >= max(28.0, 0.16 * r):
        return "red"

    return "other"


def _looks_green_nameplate(c: _Component) -> bool:
    return _hue_sector(c) == "green" and 20 <= c.rect.width <= 110 and 3 <= c.rect.height <= 12 and c.fill >= 0.45


def _looks_red_nameplate(c: _Component) -> bool:
    return _hue_sector(c) == "red" and 20 <= c.rect.width <= 110 and 3 <= c.rect.height <= 12 and c.fill >= 0.45


def _looks_yellow_nameplate(c: _Component) -> bool:
    return _hue_sector(c) == "yellow" and 20 <= c.rect.width <= 110 and 3 <= c.rect.height <= 12 and c.fill >= 0.45


def _looks_pink_nameplate(c: _Component) -> bool:
    return _hue_sector(c) == "pink" and 20 <= c.rect.width <= 110 and 3 <= c.rect.height <= 12 and c.fill >= 0.45


def _class_match(c: _Component) -> tuple[str | None, str | None]:
    """Return a class only for a strong, palette-consistent match.

    The primary class colors are intentionally kept separate from relation
    colors.  A class is returned only when the nearest palette match is strong
    enough and has a clear margin over the second-best class.
    """
    rgb = np.array([c.mean_red, c.mean_green, c.mean_blue], dtype=np.float32)
    scored: list[tuple[float, str, str]] = []
    for name, primary in _CLASS_RGB.items():
        targets = [primary, *[_hex_rgb(alias) for alias in CLASS_COLOR_ALIASES.get(name, ())]]
        distance = min(float(np.linalg.norm(rgb - np.array(target, dtype=np.float32))) for target in targets)
        scored.append((distance, name, CLASS_COLORS[name]))
    scored.sort(key=lambda row: row[0])
    if not scored:
        return None, None
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else float("inf")
    threshold = 78.0 if best[1] != "priest" else 105.0
    margin = 14.0 if best[1] not in {"priest", "mage"} else 10.0
    if best[0] <= threshold and (second - best[0]) >= margin:
        return best[1], best[2]
    return None, None


def _plate_components(crop: np.ndarray, left: int, top: int) -> list[_Component]:
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    chroma = mx - mn

    # One broad chromatic mask avoids different mask passes disagreeing about
    # yellow vs red. Semantic color is decided from the component statistics.
    mask = ((mx > 105) & (chroma > 28)) | ((mx >= 205) & (chroma < 35))
    bridged = mask.copy()
    bridged[:, 1:] |= mask[:, :-1]
    bridged[:, :-1] |= mask[:, 1:]
    bridged[:, 2:] |= mask[:, :-2]
    bridged[:, :-2] |= mask[:, 2:]

    results: list[_Component] = []
    for x0, y0, x1, y1, area in _components(bridged, min_area=2, max_area=600):
        bw, bh = x1 - x0, y1 - y0
        if not (20 <= bw <= 110 and 3 <= bh <= 12):
            continue
        # Nameplates are horizontal bars; reject tiny/color speck components.
        if bw / float(max(bh, 1)) < 2.5 or area < 30:
            continue
        comp = _plate_component_features(crop, mask, left, top, x0, y0, x1, y1, area)
        if comp.fill < 0.35:
            continue
        if _hue_sector(comp) in {"green", "red", "yellow", "pink", "orange"}:
            results.append(comp)
    return results


def _plate_component_features(crop_bgr: np.ndarray, mask: np.ndarray, gx0: int, gy0: int, x0: int, y0: int, x1: int, y1: int, area: int) -> _Component:
    patch = crop_bgr[y0:y1, x0:x1].astype(np.float32)
    selected = mask[y0:y1, x0:x1]
    if not bool(selected.any()):
        return _component_features(crop_bgr, gx0, gy0, x0, y0, x1, y1, area)
    pixels = patch[selected]
    maxc = pixels.max(axis=1)
    minc = pixels.min(axis=1)
    sat = maxc - minc
    rect = PixelRect(gx0 + x0, gy0 + y0, gx0 + x1, gy0 + y1)
    fill = area / float(max(1, rect.width * rect.height))
    return _Component(
        rect=rect,
        area=area,
        fill=fill,
        mean_saturation=float(sat.mean()),
        mean_brightness=float(maxc.mean()),
        mean_red=float(pixels[:, 2].mean()),
        mean_green=float(pixels[:, 1].mean()),
        mean_blue=float(pixels[:, 0].mean()),
    )


def _component_features(crop_bgr: np.ndarray, gx0: int, gy0: int, x0: int, y0: int, x1: int, y1: int, area: int) -> _Component:
    patch = crop_bgr[y0:y1, x0:x1].astype(np.float32)
    maxc = patch.max(axis=2)
    minc = patch.min(axis=2)
    sat = maxc - minc
    rect = PixelRect(gx0 + x0, gy0 + y0, gx0 + x1, gy0 + y1)
    fill = area / float(max(1, rect.width * rect.height))
    return _Component(
        rect=rect,
        area=area,
        fill=fill,
        mean_saturation=float(sat.mean()),
        mean_brightness=float(maxc.mean()),
        mean_red=float(patch[:, :, 2].mean()),
        mean_green=float(patch[:, :, 1].mean()),
        mean_blue=float(patch[:, :, 0].mean()),
    )


def _plate_appearance(plate: _Component) -> dict[str, object]:
    """Describe a horizontal colour cue without assigning an entity role."""
    return {
        "hue_family": _hue_sector(plate),
        "geometry": "horizontal",
        "brightness": round(plate.mean_brightness, 2),
        "saturation": round(plate.mean_saturation, 2),
        "cue": "possible_nameplate_like",
    }


def _visual_kind(c: _Component, plates: list[_Component]) -> tuple[str, float, str, dict[str, object], tuple[str, ...]]:
    w, h = c.rect.width, c.rect.height
    aspect = w / float(max(h, 1))

    for plate in plates:
        dx = abs((plate.rect.left + plate.rect.right) / 2 - (c.rect.left + c.rect.right) / 2)
        gap = c.rect.top - plate.rect.bottom
        if dx <= max(22.0, w * 0.65) and 5 <= gap <= 38 and h >= 8 and w <= 120:
            appearance = _plate_appearance(plate)
            appearance.update({"shape": "subject_like", "overhead_cue": True,
                               "nameplate_bbox": plate.rect.to_dict(space="SCREEN_PIXELS")})
            return "unknown_subject_candidate", 0.76, "subject shape + horizontal overhead colour cue", appearance, ("possible_nameplate_like",)

    # Body/silhouette evidence creates an UNKNOWN entity track without any
    # nameplate.  Mouseover/addon identity may recognize it later.  This keeps
    # nameplates as secondary relation hints rather than a prerequisite for
    # seeing an NPC or mob at all.
    if 14 <= h <= 110 and w <= 48 and 0.18 <= aspect <= 1.45 and c.area >= 45 and c.fill >= .10:
        return "unknown_subject_candidate", 0.61, "subject-shaped foreground mass", {"shape": "subject_like"}, ()

    if c.area >= 120 and c.fill >= 0.24 and c.mean_saturation < 65 and h >= 12:
        return "unknown_scene_candidate", 0.66, "compact low-saturation scene mass", {"shape": "compact_scene_mass"}, ()
    if 8 <= h <= 90 and 0.18 <= aspect <= 2.5 and c.area >= 28:
        if c.mean_saturation >= 55 and c.mean_brightness >= 105:
            return "unknown_object_candidate", 0.64, "compact foreground shape + color/brightness", {"shape": "compact", "brightness": round(c.mean_brightness, 2), "saturation": round(c.mean_saturation, 2)}, ()
    if c.area >= 80 and c.fill >= 0.22 and h >= 10:
        return "unknown_object_candidate", 0.56, "larger compact scene mass", {"shape": "compact"}, ()
    return "visual_candidate", 0.0, "coarse visual candidate", {"shape": "unknown"}, ()


def _looks_symbol_like(c: _Component) -> bool:
    """Appearance-only overhead-glyph proposal (never !/? or quest semantics)."""
    w, h = c.rect.width, c.rect.height
    aspect = w / float(max(h, 1))
    return (
        # Retail can render the overhead glyph inside a small, nearly square
        # badge (especially with a reduced UI scale). Keep this an
        # appearance-only proposal, but do not force symbol-like evidence to
        # be narrower than it is tall.
        4 <= w <= 30 and 7 <= h <= 40 and .12 <= aspect
        and (aspect <= .90 or (
            aspect <= 1.55 and (
                (12 <= w <= 30 and 12 <= h <= 30)
                or (11 <= w <= 30 and 9 <= h <= 30 and c.mean_saturation >= 70)
            )
        ))
        and c.area >= 18
        and (c.mean_brightness >= 120
             or (aspect > .90 and c.mean_saturation >= 75 and c.mean_brightness >= 110))
        and not (w > 10 and c.fill >= .80)
        and (c.mean_saturation >= 55 or min(c.mean_red, c.mean_green, c.mean_blue) >= 125)
    )


def _quest_badge_likeness(c: _Component, crop_bgr: np.ndarray, left: int, top: int) -> float:
    """Return appearance evidence for a compact glyph inside a dark badge.

    This is deliberately *not* quest recognition.  It only distinguishes the
    Retail overhead-badge appearance from isolated yellow scenery (torches,
    flowers, highlights) so downstream evidence fusion has a better cue.
    """
    w, h = c.rect.width, c.rect.height
    aspect = w / float(max(h, 1))
    if not (8 <= w <= 30 and 11 <= h <= 40 and .72 <= aspect <= 1.35):
        return 0.0
    x0, y0 = c.rect.left-left, c.rect.top-top
    x1, y1 = c.rect.right-left, c.rect.bottom-top
    pad_x, pad_y = max(5, w//2), max(4, h//3)
    px0, py0 = max(0, x0-pad_x), max(0, y0-pad_y)
    px1, py1 = min(crop_bgr.shape[1], x1+pad_x), min(crop_bgr.shape[0], y1+pad_y)
    patch = crop_bgr[py0:py1, px0:px1]
    if patch.size == 0:
        return 0.0
    brightness = patch.max(axis=2).astype(np.float32)
    ring = np.ones(brightness.shape, dtype=bool)
    ring[y0-py0:y1-py0, x0-px0:x1-px0] = False
    if not bool(ring.any()):
        return 0.0
    dark_surround = float((brightness[ring] < 82).mean())
    local_contrast = max(0.0, min(1.0, (c.mean_brightness-float(brightness[ring].mean()))/150.0))
    verticality = max(0.0, min(1.0, (1.35-aspect)/.85))
    scale_support = max(0.0, min(1.0, (h-10)/10.0))
    halo_score = (.38*dark_surround + .30*local_contrast
                  + .20*verticality + .12*scale_support)
    # The shield/badge outline itself is a compact near-square gold cluster;
    # it can sit over bright spell effects, where a dark-halo-only test is
    # unreliable.  This remains an appearance shape, never a quest fact.
    framed_cluster = (16 <= w <= 30 and 14 <= h <= 30
                      and .80 <= aspect <= 1.35 and .12 <= c.fill <= .72)
    frame_score = (.58 + .18*min(1., c.area/160.)
                   + .10*(1.-min(1., abs(aspect-1.0)))) if framed_cluster else 0.0
    return max(0.0, min(1.0, max(halo_score, frame_score)))


def detect_world_candidates(buffer: bytes, width: int, height: int, scene: WorldSceneROI) -> tuple[WorldCandidate, ...]:
    """Produce generic UNKNOWN visual candidates after UI filtering."""
    arr = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4))
    left, top, right, bottom = scene.rect.left, scene.rect.top, scene.rect.right, scene.rect.bottom
    crop = arr[top:bottom, left:right, :3]
    if crop.size == 0:
        return ()

    # Pairwise channel operations avoid a strided axis reduction and a full
    # int16 colour copy. max >= min, so uint8 chroma subtraction is exact.
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    maxc = np.maximum(np.maximum(b, g), r)
    minc = np.minimum(np.minimum(b, g), r)
    saturation = maxc - minc
    bright = maxc > 125
    mask = ((saturation > 55) | (bright & (minc > 95))) & (maxc > 90)

    neigh = np.zeros_like(mask, dtype=np.uint8)
    neigh[1:] += mask[:-1]
    neigh[:-1] += mask[1:]
    neigh[:, 1:] += mask[:, :-1]
    neigh[:, :-1] += mask[:, 1:]
    mask &= neigh >= 2

    raw_components: list[_Component] = []
    for x0, y0, x1, y1, area in _components(mask):
        bw, bh = x1 - x0, y1 - y0
        if bw < 2 or bh < 2 or bw > 140 or bh > 140:
            continue
        raw = _component_features(crop, left, top, x0, y0, x1, y1, area)
        if raw.fill < 0.08:
            continue
        if any(_intersects(raw.rect, ex) for ex in scene.excluded_rects):
            continue
        raw_components.append(raw)

    # A quest-style Retail badge contains several gold fragments separated by
    # its dark shield/background.  The broad foreground mask can connect that
    # badge to nearby name text or the subject body, so scan a much narrower
    # gold mask independently and keep the whole compact cluster as appearance
    # evidence.  No semantic quest role is assigned here.
    # Absolute channel bounds avoid two full-frame int16 temporaries in this
    # CPU hot path. They express the same narrow gold family for Retail UI.
    gold_mask = (r > 145) & (g > 105) & (b < 100)
    for x0, y0, x1, y1, area in _components(gold_mask, min_area=10, max_area=450):
        bw, bh = x1-x0, y1-y0
        if not (8 <= bw <= 30 and 11 <= bh <= 40):
            continue
        comp = _plate_component_features(crop, gold_mask, left, top, x0, y0, x1, y1, area)
        if any(_intersects(comp.rect, ex) for ex in scene.excluded_rects):
            continue
        if _quest_badge_likeness(comp, crop, left, top) < .52:
            continue
        if not any(existing.rect == comp.rect for existing in raw_components):
            raw_components.append(comp)

    plates = [p for p in _plate_components(crop, left, top) if not any(_intersects(p.rect, ex) for ex in scene.excluded_rects)]
    candidates: list[WorldCandidate] = []

    for plate in plates:
        body_left = max(left, int((plate.rect.left + plate.rect.right) / 2 - 36))
        body_right = min(right, int((plate.rect.left + plate.rect.right) / 2 + 36))
        body_top = plate.rect.bottom + 2
        body_bottom = min(bottom, body_top + 82)
        if body_bottom - body_top < 12:
            continue
        body_rect = PixelRect(body_left, body_top, body_right, body_bottom)
        if any(_intersects(body_rect, ex) for ex in scene.excluded_rects):
            continue
        if plate.rect.top >= min(bottom - 120, 360) or plate.rect.left >= right - 45:
            continue
        nearby_body = any(
            comp.rect.height >= 8
            and abs((comp.rect.left + comp.rect.right) / 2 - (plate.rect.left + plate.rect.right) / 2) <= 28
            and 5 <= comp.rect.top - plate.rect.bottom <= 38
            for comp in raw_components
        )
        if not nearby_body:
            # Body segmentation can be weak in a crowded scene even when a
            # horizontal overhead cue is stable.  Preserve a bounded UNKNOWN
            # inspection region below the cue rather than discarding it or
            # declaring an NPC/MOB.  Later tracking/mouseover may associate
            # the probe with a real entity; until then it is only an
            # information-value candidate.
            candidates.append(WorldCandidate(
                kind="unknown_subject_probe", rect=body_rect, confidence=.54,
                evidence="horizontal colour cue with unresolved subject region below",
                appearance={**_plate_appearance(plate),
                            "nameplate_bbox": plate.rect.to_dict(space="SCREEN_PIXELS"),
                            "shape": "subject_probe", "probe_origin": "horizontal_overhead_cue",
                            "proposal_semantics": "UNKNOWN"},
                candidate_labels=("possible_nameplate_like", "overhead_cue", "subject_probe_like"),
            ))

    for c in raw_components:
        if _looks_symbol_like(c):
            kind, visual_conf, reason = "unknown_symbol_candidate", .72, "small bright/high-contrast symbol-like shape"
            hue = _hue_sector(c)
            appearance = {"shape": "symbol_like", "hue_family": hue, "brightness": round(c.mean_brightness, 2), "saturation": round(c.mean_saturation, 2)}
            labels = ("overhead_symbol_like_cue",)
            # Appearance-only evidence: this improves inspection ranking but
            # deliberately does not assert QUEST_GIVER or any semantic fact.
            if hue in {"yellow", "orange"} and c.mean_saturation >= 60:
                visual_conf = .8
                reason = "saturated yellow overhead symbol-like shape"
                labels = ("overhead_symbol_like_cue", "quest_marker_like")
                badge_likeness = _quest_badge_likeness(c, crop, left, top)
                appearance["quest_badge_likeness"] = round(badge_likeness, 4)
                appearance["dark_badge_surround"] = badge_likeness >= .52
                if badge_likeness >= .52:
                    labels = (*labels, "quest_badge_like")
                    visual_conf = min(.88, visual_conf + .06*badge_likeness)
                    reason = "saturated overhead glyph with badge-like gold cluster"
        else:
            kind, visual_conf, reason, appearance, labels = _visual_kind(c, plates)
        if kind == "visual_candidate":
            if c.area < 18:
                continue
            confidence = min(0.78, 0.40 + 0.18 * min(c.fill, 1.0) + 0.20 * min(c.area / 120.0, 1.0))
            evidence = f"{reason}; area={c.area} fill={c.fill:.2f} sat={c.mean_saturation:.0f}"
        else:
            confidence = visual_conf
            evidence = f"{reason}; area={c.area} fill={c.fill:.2f} sat={c.mean_saturation:.0f}"
        candidates.append(WorldCandidate(kind=kind, rect=c.rect, confidence=float(confidence), evidence=evidence, appearance=appearance, candidate_labels=labels))

    rank = {"unknown_symbol_candidate": 5, "unknown_subject_candidate": 4,
            "unknown_subject_probe": 4, "unknown_object_candidate": 3,
            "unknown_scene_candidate": 2, "visual_candidate": 1}
    candidates.sort(key=lambda item: (rank.get(item.kind, 0), item.confidence, item.rect.width * item.rect.height), reverse=True)

    deduped: list[WorldCandidate] = []
    for item in candidates:
        duplicate = False
        cx = (item.rect.left + item.rect.right) / 2
        cy = (item.rect.top + item.rect.bottom) / 2
        for kept in deduped:
            if item.kind != kept.kind:
                continue
            kx = (kept.rect.left + kept.rect.right) / 2
            ky = (kept.rect.top + kept.rect.bottom) / 2
            if abs(cx - kx) <= 45 and abs(cy - ky) <= 45:
                duplicate = True
                break
            if _intersects(item.rect, kept.rect):
                duplicate = True
                break
        if not duplicate:
            deduped.append(item)
    return tuple(deduped[:32])
