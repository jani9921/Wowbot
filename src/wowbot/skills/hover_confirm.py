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
from wowbot.agent.pointer_tracking import follow_pointer, live_pointer_point, world_pointer_blocked

HOVER_CONFIRM_SECONDS = .45
# A completed paged STATE can arrive only about every .7 s when FAST is
# temporarily unreadable. Do not invalidate its reply with a second pointer
# move after .45 s. This is a bounded maximum wait, NOT a click delay or a
# relaxation of the original sample clocks / shared ID command guard.
STATE_HOVER_CONFIRM_SECONDS = 1.
MAX_HOVERS = 3
# After the click the target must show within this much of fresh target
# samples, or the box is hovered again (live 2026-10-05: one click on an empty
# spot waited out the whole 8 s TARGET deadline).
CLICK_CONFIRM_SECONDS = .7
# Live 2026-10-03 13:20: a porcupine corpse was hovered three times at the
# same remembered point (where its live box was) and never named; a corpse
# lies lower/sideways after the death animation.  Without a live box the
# retries walk a small pattern around the remembered point.
# Live 13:46: a dead goat lay ~.06 below its standing box centre and .05
# sideways; the pattern reaches lower than it reaches up.
CORPSE_SEARCH_OFFSETS = ((0., 0.), (0., .05), (0., .09), (-.05, .07), (.05, .07),
                         (-.06, .03), (.06, .03), (0., -.03))


def pointer_acquisition_retired(world_state: dict | None) -> bool:
    """REV4 (user 2026-10-30): the SERVER composition never moves the pointer
    onto a screen box to acquire a unit or corpse.  Server GUIDs, Tab and the
    Interact key do it; the dispatcher already withheld the HOVER, so a skill
    used to wait out its whole deadline for a confirmation that never came."""
    from wowbot.agent.server_mode import server_profile
    return server_profile(world_state or {})


def valid_point(x, y) -> tuple[float, float] | None:
    x, y = number(x), number(y)
    if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
        return None
    return x, y


def confirmed_cursor_handoff(parameters: dict, world_state: dict, now: float) -> bool:
    """The exact current cursor/GUID proof may be consumed once, without re-aim.

    Match TARGET admission's strict sample/point bounds against the actual
    skill start clock too. A stale/missing proof only permits hover recovery.
    """
    expected = parameters.get("guid")
    mouse, cursor = world_state.get("mouseover") or {}, world_state.get("cursor_position") or {}
    point = valid_point(parameters.get("x"), parameters.get("y"))
    current = valid_point(cursor.get("nx"), cursor.get("ny"))
    sample = number(world_state.get("mouseover_sample_time"))
    cursor_sample = number(world_state.get("cursor_sample_time"))
    return bool(expected and str(mouse.get("guid") or "") == str(expected)
                and not world_pointer_blocked(world_state) and point and current
                and sample is not None and cursor_sample is not None
                and 0 <= now-sample <= .35 and 0 <= now-cursor_sample <= .35
                and abs(sample-cursor_sample) <= .05
                and abs(point[0]-current[0]) <= .002 and abs(point[1]-current[1]) <= .002)


def live_track_point(world_state: dict, track_id, *, lower: bool = False) -> tuple[float, float] | None:
    """Current hover point of the World3D track (box centre or lower part)."""
    if track_id is None or pointer_acquisition_retired(world_state):
        return None
    for item in world_state.get("visual_candidates") or ():
        if (isinstance(item, dict) and item.get("source") == "WORLD3D"
                and str(item.get("track_id")) == str(track_id)):
            box = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
            frame = item.get("frame_size") if isinstance(item.get("frame_size"), dict) else {}
            from wowbot.agent.track_motion import predicted_point
            y = None
            if lower and None not in (number(box.get("top")), number(box.get("bottom")),
                                      number(frame.get("height"))) and number(frame.get("height")):
                y = (number(box["top"]) + .75*(number(box["bottom"])-number(box["top"]))) / number(frame["height"])
            # Lead a moving box (user 2026-10-05: the pointer lagged behind).
            return valid_point(*(predicted_point(item, world_state, y=y)
                                 or (item.get("x"), item.get("y") if y is None else y)))
    return None


def hover_confirm_step(context: dict, world_state: dict, now: float, *,
                       expected_guid: str, click_button: str = "LEFT",
                       lower: bool = False, max_hovers: int = MAX_HOVERS,
                       search_offsets: tuple = (), deadline: float | None = None):
    """Return ("CLICK"|"HOVER"|"WAIT"|"FAILED"|"EMPTY", commands)."""
    if pointer_acquisition_retired(world_state):
        return "FAILED", ()
    mouse = world_state.get("mouseover") or {}
    hovered_at = number(context.get("hovered_at"))
    following = context.get("pointer_follow") or {}
    moved_at = number(following.get("sent_at"))
    if (deadline is not None and now >= deadline) or (
            deadline is None and following and now-following["started_at"] >= 2.):
        return "FAILED", ()
    if world_pointer_blocked(world_state):
        return "WAIT", ()
    sample = number(world_state.get("mouseover_sample_time"))
    # Only a mouseover sampled after the hover confirms it.  Live 2026-10-05
    # 616937: the confirm read the mouseover of the previous INSPECT spot
    # (sampled before the hover), clicked, and nothing was under the pointer.
    # A missing sample time after a hover proves nothing (issue #88): the
    # retained GUID may predate the pointer move.
    cursor_sample = number(world_state.get("cursor_sample_time"))
    fresh = (sample is not None and 0 <= now-sample <= .5
             and (cursor_sample is None or (0 <= now-cursor_sample <= .5 and abs(sample-cursor_sample) <= .05))
             and (hovered_at is None or (sample is not None and sample >= hovered_at))
             and (moved_at is None or (sample is not None and sample >= moved_at)))
    if fresh and expected_guid and str(mouse.get("guid") or "") == str(expected_guid):
        if mouse.get("lootable") is False:
            return "EMPTY", ()
        return "CLICK", (Command("CLICK_CURRENT_CURSOR", button=click_button),)
    if (hovered_at is not None and fresh and mouse.get("guid")
            and str(mouse["guid"]) != str(expected_guid)):
        return "FAILED", ()                 # the followed box named a different unit
    if hovered_at is not None or moved_at is not None:
        # At 25-30 Hz, re-aiming on every frame can keep sent_at forever ahead
        # of the addon's 50-150 ms delayed sample. Give that exact pointer move
        # a bounded chance to be acknowledged. Click as soon as fresh GUID
        # proof arrives above; this is a maximum hold, never a minimum delay.
        barrier = max(value for value in (moved_at, hovered_at) if value is not None)
        hold = (STATE_HOVER_CONFIRM_SECONDS
                if world_state.get("transport_kind") in {"STATE", "STATE_Z"}
                else HOVER_CONFIRM_SECONDS)
        if (sample is None or sample < barrier) and 0 <= now-barrier < hold:
            return "WAIT", ()
    # While the addon answers, follow this exact *live* track without sending
    # a second click, restarting the attempt, or spending its retry budget.
    point = live_pointer_point(world_state, context.get("track_id"), now)
    if point is not None and hovered_at is not None:
        if lower:
            point = live_track_point(world_state, context.get("track_id"), lower=True) or point
        following = context.setdefault("pointer_follow", {})
        command = follow_pointer(following, world_state, context.get("track_id"), now, point=point)
        if command is not None:
            context["hover_point"] = (command.x, command.y)
            return "HOVER", (command,)
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
