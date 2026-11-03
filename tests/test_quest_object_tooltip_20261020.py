"""Game-object use proved by the client's quest tooltip (no Ymir needed).

Live 2026-10-19 15:23-15:25 and 2026-10-20 08:17-08:20 (Purge the Totems):
the agent hovered every Harpy Totem and the addon reported
``{"name": "Harpy Totem", "object_id": 0, "quest_id": 55881,
"quest_related": true}``, but input required the object's public ID, which
Retail never exposes for a world object, so no totem was ever used.
"""
from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.runtime.skill_identity import (QUEST_OBJECT_TOOLTIP, check_command_identity,
                                           quest_object_tooltip_matches)
from wowbot.skills.object_use import ObjectUseSkill

TOTEM_HOVER = {"name": "Harpy Totem", "object_id": 0, "quest_id": 55881, "quest_related": True}
PARAMS = {"identity_certification": QUEST_OBJECT_TOOLTIP, "quest_ids": [55881],
          "expected_tooltips": ["Harpy Totem"], "x": .5, "y": .6}


def test_live_totem_tooltip_certifies_the_object():
    assert quest_object_tooltip_matches(PARAMS, TOTEM_HOVER) is True


def test_units_other_ids_other_quests_and_plain_scenery_never_pass():
    assert not quest_object_tooltip_matches(PARAMS, {**TOTEM_HOVER, "guid": "Creature-0-1-2175-1-152571-1"})
    assert not quest_object_tooltip_matches(PARAMS, {**TOTEM_HOVER, "object_id": 342366})
    assert not quest_object_tooltip_matches(PARAMS, {**TOTEM_HOVER, "quest_related": False})
    assert not quest_object_tooltip_matches(PARAMS, {**TOTEM_HOVER, "quest_id": 55764})
    assert not quest_object_tooltip_matches(PARAMS, {**TOTEM_HOVER, "name": "Campfire"})
    assert not quest_object_tooltip_matches({**PARAMS, "identity_certification": None}, TOTEM_HOVER)


def _state(px, py, pz=142.):
    return {"player_world_position": {"x": px, "y": py, "z": pz, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "monotonic_time": 100., "is_in_combat": False,
            "active_quests": [{"quest_id": 55881, "is_complete": False, "objectives": [
                {"objective_id": "55881:0", "type": "INTERACT", "raw_type": "object", "is_complete": False}]}],
            "reference_knowledge": {"quests": {"55881": {"spawn_candidates": [
                {"entity_kind": "GAMEOBJECT", "x": 430.5, "y": -2487.5, "z": 142.3, "spawn_id": 1,
                 "world_map_id": 2175}]}}}}


def test_tooltip_needs_a_spawn_within_use_range():
    flow = ObjectInteractionFlow()
    identity = {"object_id": 327146, "tdb_object_name": "Harpy Totem", "expected_tooltips": ["Harpy Totem"]}
    assert flow.tooltip_certified(identity, TOTEM_HOVER, _state(429.6, -2486.1), 55881, 142.1)
    # 08:17 "You are too far away": never click from afar, walk first.
    assert not flow.tooltip_certified(identity, TOTEM_HOVER, _state(440., -2487.5), 55881, 142.1)
    assert flow.tooltip_certified(identity, TOTEM_HOVER, _state(429.6, -2486.1), 55881, None)


def _world(**changes):
    return {"monotonic_time": 100., "mouseover": dict(TOTEM_HOVER), "mouseover_sample_time": 99.9,
            "cursor_position": {"nx": .5, "ny": .6}, "cursor_sample_time": 99.9, **changes}


def test_guard_lets_the_certified_right_click_through_and_blocks_a_unit():
    click = (Command("CLICK", x=.5, y=.6, button="RIGHT"),)
    assert check_command_identity("OBJECT_USE", PARAMS, {}, _world(), click, 100.)
    unit = _world(mouseover={**TOTEM_HOVER, "guid": "Creature-0-1-2175-1-152571-1"})
    assert not check_command_identity("OBJECT_USE", PARAMS, {}, unit, click, 100.)
    moved = _world(cursor_position={"nx": .7, "ny": .6})
    assert not check_command_identity("OBJECT_USE", PARAMS, {}, moved, click, 100.)
    stale = _world(mouseover_sample_time=90., cursor_sample_time=90.)
    assert not check_command_identity("OBJECT_USE", PARAMS, {}, stale, click, 100.)


def test_skill_hovers_then_right_clicks_the_certified_object():
    from wowbot.runtime import SkillStatus
    skill = ObjectUseSkill()
    active = SimpleNamespace(
        intent=SimpleNamespace(parameters={**PARAMS, "objective_id": "55881:0"},
                               objective_ref="55881:0", target_ref=None),
        skill_type="OBJECT_USE", skill_context={}, started_at=100., phase=None,
        before_snapshot={}, attempt=SimpleNamespace(deadline=110.))
    started = skill.begin(active, _world())
    assert started.status is SkillStatus.RUNNING
    assert [c.kind for c in started.commands] == ["HOVER"]
    after = _world(monotonic_time=100.3, mouseover_sample_time=100.2, cursor_sample_time=100.2)
    clicked = skill.verify(active, after, 100.3)
    assert [(c.kind, c.button) for c in clicked.commands] == [("CLICK", "RIGHT")]


def test_a_certified_hover_at_a_spawn_stops_the_walk_to_another_spawn():
    """Live 2026-10-20 09:37 (Pit): the cursor was on a passed quest object
    and the MOVE walked on.  Without server data the client's quest tooltip
    at an unspent spawn in use range hands the walk back to the planner."""
    flow = ObjectInteractionFlow()
    live = {**_state(429.6, -2486.1), "mouseover": dict(TOTEM_HOVER), "mouseover_sample_time": 99.9}
    live["reference_knowledge"]["quests"]["55881"]["objectives"] = [
        {"objective_id": 389809, "credit_kind": "GAMEOBJECT", "credit_object_id": 327146,
         "object_template": {"object_id": 327146, "name": "Harpy Totem"}, "order": 0}]
    walk = {"x": 470., "y": -2487.5, "z": 142.3, "purpose": "APPROACH_QUEST_OBJECT_SPAWN",
            "quest_id": 55881, "objective_id": "55881:0"}
    assert flow.object_move_handoff(live, walk, 142.1)["kind"] == "QUEST_OBJECT_HOVERED"
    far = {**live, "player_world_position": {**live["player_world_position"], "x": 440.}}
    assert flow.object_move_handoff(far, walk, 142.1) is None              # too far to click
    plain = {**live, "mouseover": {**TOTEM_HOVER, "quest_related": False}}
    assert flow.object_move_handoff(plain, walk, 142.1) is None
    flow._spend_spot(live, 430.5, -2487.5, 99.)                             # just credited there
    assert flow.object_move_handoff(live, walk, 142.1) is None
