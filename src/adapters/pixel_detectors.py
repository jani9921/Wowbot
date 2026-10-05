"""Colour/shape detectors on captured client frames (quest marker, campfire, nameplates).

Split out of pixel_bridge.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations
from typing import Optional
from src.adapters.numpy_runtime import np


def detect_quest_marker(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Return a click point below a yellow quest exclamation marker."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    mask = (red > 210) & (green > 145) & (blue < 65) & (red.astype(np.int16) > blue.astype(np.int16) * 3)
    mask[:45, :] = False
    mask[int(height * 0.70):, :] = False
    mask[:, :8] = False
    mask[:, width - 8:] = False
    # At long range the dot and hook/stem of a quest marker are separate
    # components. A one-pixel dilation joins them without merging ordinary
    # torches or the fixed objective tracker text.
    dilated = mask.copy()
    dilated[1:, :] |= mask[:-1, :]
    dilated[:-1, :] |= mask[1:, :]
    dilated[:, 1:] |= mask[:, :-1]
    dilated[:, :-1] |= mask[:, 1:]
    ys, xs = np.nonzero(dilated)
    candidates = set(zip(xs.tolist(), ys.tolist()))
    if not candidates:
        return None
    groups: list[list[tuple[int, int]]] = []
    while candidates:
        start = candidates.pop()
        group, stack = [start], [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                             (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if neighbor in candidates:
                    candidates.remove(neighbor); group.append(neighbor); stack.append(neighbor)
        if len(group) >= 5:
            groups.append(group)
    matches = []
    compact_matches = []
    distant_world_matches = []
    for group in groups:
        xs, ys = [p[0] for p in group], [p[1] for p in group]
        box_width, box_height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        center_x = sum(xs) // len(xs)
        center_y = sum(ys) // len(ys)
        # Ignore the retail objective tracker/tutorial flyout region. Those
        # fixed yellow arrows otherwise look like world-space quest markers.
        in_right_side_ui = center_x > width * 0.70 and center_y < height * 0.72
        density = len(group) / max(1, box_width * box_height)
        aspect = box_height / max(1, box_width)
        if (
            not in_right_side_ui
            and 6 <= box_width <= 24
            and 14 <= box_height <= 35
            and 1.15 <= aspect <= 2.6
            and density >= 0.52
        ):
            # Retail's world quest marker is a dense, vertically oriented
            # badge. This rejects quest-tracker text, the large completion
            # arrow, and yellow ship geometry.
            matches.append((len(group), sum(xs) // len(xs), min(ys), max(ys)))
        elif (
            width < 400
            and not in_right_side_ui
            and 3 <= box_width <= 8
            and 6 <= box_height <= 12
        ):
            # Preserve recognition of genuinely tiny markers in low-resolution
            # replay fixtures; Retail's normal client render uses the stronger
            # badge geometry above.
            compact_matches.append((len(group), sum(xs) // len(xs), min(ys), max(ys)))
        elif (
            width >= 400
            and width * 0.18 <= center_x <= width * 0.70
            and height * 0.10 <= center_y <= height * 0.58
            and 5 <= box_width <= 10
            and 5 <= box_height <= 13
            and len(group) >= 14
        ):
            # A distant world marker on the island can render as only a few
            # yellow pixels. Restrict this fallback to the central 3D view so
            # taskbar icons and the objective tracker cannot match it.
            distant_world_matches.append(
                (len(group), sum(xs) // len(xs), min(ys), max(ys))
            )
    if not matches:
        matches = compact_matches or distant_world_matches
    if not matches:
        return None
    _, center_x, _top, bottom = max(matches, key=lambda item: item[0])
    return center_x, min(height - 1, bottom + 35)


def detect_campfire(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the strongest nearby orange fire cluster in the playable world area."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    red16, green16 = red.astype(np.int16), green.astype(np.int16)
    mask = (
        (red > 170)
        & (green > 65)
        & (green < 200)
        & (blue < 80)
        & (red16 > green16 * 1.25)
    )
    # Exclude the addon strip, action bars and edge UI. Nearby campfires occupy
    # the central/lower world view; distant torches usually form smaller blobs.
    mask[:int(height * 0.30), :] = False
    mask[int(height * 0.78):, :] = False
    mask[:, :int(width * 0.10)] = False
    mask[:, int(width * 0.85):] = False
    ys, xs = np.nonzero(mask)
    points = set(zip(xs.tolist(), ys.tolist()))
    matches: list[tuple[float, int, int]] = []
    while points:
        start = points.pop()
        component, stack = [start], [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                             (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if neighbor in points:
                    points.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        if len(component) < 10:
            continue
        component_xs, component_ys = [p[0] for p in component], [p[1] for p in component]
        box_width = max(component_xs) - min(component_xs) + 1
        box_height = max(component_ys) - min(component_ys) + 1
        if box_width <= 35 and box_height <= 35:
            center_x = round(sum(component_xs) / len(component_xs))
            center_y = round(sum(component_ys) / len(component_ys))
            center_penalty = abs(center_x - width / 2) / max(1, width)
            matches.append((len(component) - center_penalty * 8, center_x, center_y))
    if not matches:
        return None
    # Without OCR several neutral mobs can have identical gold bars. Accept a
    # fresh bearing only near the central interaction corridor; the temporal
    # tracker may then follow small subsequent motion. This prevents a restart
    # from locking onto an unrelated edge nameplate and circling toward it.
    central_matches = [
        match for match in matches
        if width * 0.28 <= match[1] <= width * 0.72
    ]
    if not central_matches:
        return None
    _, center_x, center_y = max(
        central_matches,
        key=lambda match: match[0] - abs(match[1] - width / 2) * 2.0 + match[2] * 0.15,
    )
    return center_x, center_y


def detect_friendly_nameplate(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the strongest bright-green world name and return a point on the unit below it."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    mask = (
        (green > 165)
        & (green.astype(np.float32) > red * 1.8)
        & (green.astype(np.float32) > blue * 1.45)
        & (red < 125)
    )
    mask[:42, :] = False
    mask[int(height * 0.70):, :] = False
    mask[:, :6] = False
    mask[:, width - 6:] = False
    mask[int(height * 0.22):int(height * 0.50), :int(width * 0.42)] = False
    # The addon transport contains dense green pixel rows. World-name text
    # is sparse, so drop only rows that are too dense to be text.
    dense_limit = max(35, int(width * 0.075))
    row_counts = mask.sum(axis=1)
    mask[row_counts >= dense_limit, :] = False
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    bin_x, bin_y = xs // 64, ys // 22
    keys = bin_y * ((width + 63) // 64) + bin_x
    unique, counts = np.unique(keys, return_counts=True)
    best = unique[int(np.argmax(counts))]
    bx, by = int(best % ((width + 63) // 64)), int(best // ((width + 63) // 64))
    selected = (np.abs(bin_x - bx) <= 1) & (np.abs(bin_y - by) <= 1)
    if int(selected.sum()) < 8:
        return None
    center_x = int(xs[selected].mean())
    bottom = int(ys[selected].max())
    return center_x, min(height - 1, bottom + 46)


def detect_enemy_nameplate(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the selected enemy's long gold world-nameplate, excluding fixed UI."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    # A close selected neutral/hostile unit uses a large red world-name
    # instead of a gold health bar. This text band provides its screen bearing.
    red_name = (
        (red > 170)
        & (green < 105)
        & (blue < 105)
        & (red.astype(np.int16) > green.astype(np.int16) * 2)
    )
    red_name[:int(height * 0.49), :] = False
    red_name[int(height * 0.70):, :] = False
    red_name[:, :int(width * 0.08)] = False
    red_name[:, int(width * 0.78):] = False
    row_counts = red_name.sum(axis=1)
    active_rows = np.flatnonzero(row_counts >= 10)
    if active_rows.size:
        bands: list[list[int]] = [[int(active_rows[0])]]
        for row in active_rows[1:]:
            row = int(row)
            if row <= bands[-1][-1] + 1:
                bands[-1].append(row)
            else:
                bands.append([row])
        red_matches: list[tuple[int, float, int, int]] = []
        for band in bands:
            y0, y1 = band[0], band[-1]
            ys, xs = np.nonzero(red_name[y0:y1 + 1])
            if not xs.size:
                continue
            box_width = int(xs.max() - xs.min() + 1)
            box_height = y1 - y0 + 1
            if 35 <= box_width <= 300 and 5 <= box_height <= 28:
                center_x = int(xs.mean())
                center_y = int(y0 + ys.mean())
                center_penalty = abs(center_x - width / 2) / max(1, width)
                red_matches.append((int(xs.size), center_penalty, center_x, center_y))
        if red_matches:
            _, _, center_x, center_y = max(
                red_matches, key=lambda item: item[0] - item[1] * 80
            )
            return center_x, center_y
    mask = (
        (red > 100)
        & (green > 80)
        & (blue < 70)
    )
    mask[:int(height * 0.05), :] = False
    mask[int(height * 0.72):, :] = False
    mask[:, :int(width * 0.04)] = False
    mask[:, int(width * 0.78):] = False
    # The fixed selected-target frame has the same gold fill but is not a
    # world-space bearing.
    mask[:int(height * 0.16), int(width * 0.62):] = False
    ys, xs = np.nonzero(mask)
    points = set(zip(xs.tolist(), ys.tolist()))
    matches: list[tuple[int, int, int]] = []
    while points:
        start = points.pop()
        component, stack = [start], [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                             (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if neighbor in points:
                    points.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        if len(component) < 180:
            continue
        component_xs, component_ys = [p[0] for p in component], [p[1] for p in component]
        box_width = max(component_xs) - min(component_xs) + 1
        box_height = max(component_ys) - min(component_ys) + 1
        if 80 <= box_width <= 135 and 5 <= box_height <= 18:
            matches.append((len(component), round((min(component_xs) + max(component_xs)) / 2),
                            round((min(component_ys) + max(component_ys)) / 2)))
    if not matches:
        return None
    _, center_x, center_y = max(matches)
    return center_x, center_y
