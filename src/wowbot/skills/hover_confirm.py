"""Hover a unit's live World3D box, confirm its GUID, then click.

Live 2026-10-03 (Coastal Goats / Prickly Porcupines): TARGET clicked the
current cursor right after a SEEK step that was still turning/walking the
character; the goat slid out from under the pointer and 7 TARGETs failed
(``target_not_found``).  LOOT right-clicked a remembered point once and
waited 12 s without ever checking what was under the pointer.  Both now
hover the unit's current box, wait for the addon mouseover to name the
expected GUID (and, for a corpse, not ``lootable=false``), then click the
current cursor.  The box is re-hovered at its fresh position a few times.
"""
from __future__ import annotations

from wowbot.agent.models import Command, number

HOVER_CONFIRM_SECONDS = .45
MAX_HOVERS = 3
# Live 2026-10-03 13:20: a porcupine corpse was hovered three times at the
# same remembered point (where its live box was) and never named; a corpse
# lies lower/sideways after the death animation.  Without a live box the
# retries walk a small pattern around the remembered point.
# Live 13:46: a dead goat lay ~.06 below its standing box centre and .05
# sideways; the pattern reaches lower than it reaches up.
CORPSE_SEARCH_OFFSETS = ((0., 0.), (0., .05), (0., .09), (-.05, .07), (.05, .07),
                         (-.06, .03), (.06, .03), (0., -.03))


def valid_point(x, y) -> tuple[float, float] | None:
    x, y = number(x), number(y)
    if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
        return None
    return x, y


def live_track_point(world_state: dict, track_id, *, lower: bool = False) -> tuple[float, float] | None:
    """Current hover point of the World3D track (box centre or lower part)."""
    if track_id is None:
        return None
    for item in world_state.get("visual_candidates") or ():
        if (isinstance(item, dict) and item.get("source") == "WORLD3D"
                and str(item.get("track_id")) == str(track_id)):
            box = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
            frame = item.get("frame_size") if isinstance(item.get("frame_size"), dict) else {}
            if lower and None not in (number(box.get("top")), number(box.get("bottom")),
                                      number(frame.get("height"))) and number(frame.get("height")):
                y = (number(box["top"]) + .75*(number(box["bottom"])-number(box["top"]))) / number(frame["height"])
                return valid_point(item.get("x"), y)
            return valid_point(item.get("x"), item.get("y"))
    return None


def hover_confirm_step(context: dict, world_state: dict, now: float, *,
                       expected_guid: str, click_button: str = "LEFT",
                       lower: bool = False, max_hovers: int = MAX_HOVERS,
                       search_offsets: tuple = ()):
    """Return ("CLICK"|"HOVER"|"WAIT"|"FAILED"|"EMPTY", commands)."""
    mouse = world_state.get("mouseover") or {}
    if expected_guid and str(mouse.get("guid") or "") == str(expected_guid):
        if mouse.get("lootable") is False:
            return "EMPTY", ()
        return "CLICK", (Command("CLICK_CURRENT_CURSOR", button=click_button),)
    hovered_at = number(context.get("hovered_at"))
    if hovered_at is not None and now - hovered_at < HOVER_CONFIRM_SECONDS:
        return "WAIT", ()
    hovers = int(context.get("hovers") or 0)
    if hovers >= max_hovers:
        return "FAILED", ()
    live = live_track_point(world_state, context.get("track_id"), lower=lower)
    if live is not None:
        point = live
        context["hover_point"] = point
    else:
        base = context.setdefault("hover_origin", context.get("hover_point"))
        point = valid_point(*(base or (None, None)))
        if point is not None and search_offsets:
            dx, dy = search_offsets[hovers % len(search_offsets)]
            point = valid_point(point[0]+dx, point[1]+dy) or point
    if point is None:
        return "FAILED", ()
    context["hovers"] = int(context.get("hovers") or 0) + 1
    context["hovered_at"] = now
    return "HOVER", (Command("HOVER", x=point[0], y=point[1], duration=.05),)
