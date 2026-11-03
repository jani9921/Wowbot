"""Compact FAST must not turn a known corpse into another combat candidate."""
from types import SimpleNamespace

from wowbot.agent.target_planning import _dead_or_spent
from wowbot.agent.tooltip_quest import known_dead_unit
from wowbot.skills.hover_confirm import hover_confirm_step


GUID = "Creature-0-3769-2444-47-186777-00005A598B"


def view(guid=GUID, age=0.):
    return {"timestamp": 1000., "events": [{"event_type": "MOUSEOVER_CHANGED", "timestamp": 1000.-age,
        "sequence": 1, "payload": {"guid": guid, "is_dead": True, "classification": "elite"}}]}


def test_fresh_exact_guid_death_survives_compact_field_omission():
    unit = {"guid": GUID, "is_attackable": True}
    assert known_dead_unit(unit, view())
    assert _dead_or_spent(SimpleNamespace(state=view()), unit)
    assert not known_dead_unit(unit, view("another-guid"))
    assert not known_dead_unit(unit, view(age=4.))
    assert not known_dead_unit({**unit, "is_dead": False}, view())


def test_old_matching_hover_after_the_pointer_move_is_not_click_authority():
    context = {"hovered_at": 10., "hovers": 1, "hover_point": (.5, .5)}
    state = {"mouseover": {"guid": GUID}, "mouseover_sample_time": 10.1}
    verdict, commands = hover_confirm_step(context, state, 11., expected_guid=GUID, deadline=14.)
    assert verdict != "CLICK" and all(c.kind != "CLICK_CURRENT_CURSOR" for c in commands)


def test_matching_hover_with_a_different_cursor_sample_cannot_click():
    context = {"hovered_at": 10., "hovers": 1, "hover_point": (.5, .5)}
    state = {"mouseover": {"guid": GUID}, "mouseover_sample_time": 10.1, "cursor_sample_time": 10.3}
    assert hover_confirm_step(context, state, 10.35, expected_guid=GUID)[0] != "CLICK"


def test_fresh_matching_cursor_can_still_click_immediately():
    context = {"hovered_at": 10., "hovers": 1, "hover_point": (.5, .5)}
    state = {"mouseover": {"guid": GUID}, "mouseover_sample_time": 10.1, "cursor_sample_time": 10.1}
    verdict, commands = hover_confirm_step(context, state, 10.11, expected_guid=GUID)
    assert verdict == "CLICK" and len(commands) == 1
