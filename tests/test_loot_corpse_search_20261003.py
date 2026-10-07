"""Corpse hover search (live 2026-10-03 13:20, Prickly Porcupines).

Four LOOTs failed corpse_not_found after hovering the same remembered point
three times; the corpse lay just beside it.  Without a live box the retries
walk a small pattern around the point.
"""
from wowbot.runtime import FailureReason, SkillStatus
from wowbot.skills import LootSkill
from wowbot.skills.hover_confirm import CORPSE_SEARCH_OFFSETS
from test_m0_combat_loot_skills import active

GUID = "Creature-0-3102-2175-11354-161131-000040E4B5"


def test_retries_search_around_the_remembered_point_then_click_the_named_corpse():
    skill = LootSkill()
    params = {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .4}
    state = active("LOOT", params, {}, deadline=1000)
    first = skill.begin(state, {})
    assert (first.commands[0].x, first.commands[0].y) == (.5, .4)
    points, now = [], 1.
    for _ in range(len(CORPSE_SEARCH_OFFSETS)-1):
        now += .5
        result = skill.verify(state, {}, now)
        points.append((round(result.commands[0].x, 3), round(result.commands[0].y, 3)))
    assert len(set(points)) == len(points) and (.5, .4) not in points
    named = skill.verify(state, {"mouseover": {"guid": GUID}, "mouseover_sample_time": now+.1}, now+.1)
    assert named.commands[0].kind == "CLICK_CURRENT_CURSOR"


def test_search_is_bounded():
    skill = LootSkill()
    state = active("LOOT", {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .4}, {}, deadline=1000)
    skill.begin(state, {})
    now, result = 1., None
    for _ in range(len(CORPSE_SEARCH_OFFSETS)+2):
        now += .5
        result = skill.verify(state, {}, now)
    assert result.status is SkillStatus.FAILURE and result.reason is FailureReason.CORPSE_NOT_FOUND


def test_cursor_already_on_the_corpse_clicks_at_once():
    skill = LootSkill()
    state = active("LOOT", {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .4}, {}, deadline=1000)
    result = skill.begin(state, {"mouseover": {"guid": GUID, "dead": True}})
    assert [(c.kind, c.button) for c in result.commands] == [("CLICK_CURRENT_CURSOR", "RIGHT")]


SOFT = [{"source_unit": "softinteract", "guid": GUID, "name": "Coastal Goat", "is_dead": True}]


def test_soft_interact_corpse_is_looted_with_the_interact_key():
    """Live 2026-10-03 13:46:09: softinteract = the dead goat (exact GUID)."""
    skill = LootSkill()
    state = active("LOOT", {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .4}, {}, deadline=1000)
    result = skill.begin(state, {"soft_targets": SOFT})
    assert [(c.kind, c.binding) for c in result.commands] == [("BIND", "INTERACTTARGET")]
    # During a hover search it takes over once.
    state = active("LOOT", {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .4}, {}, deadline=1000)
    skill.begin(state, {})
    first = skill.verify(state, {"soft_targets": SOFT}, 1.6)
    assert [(c.kind, c.binding) for c in first.commands] == [("BIND", "INTERACTTARGET")]


def test_soft_interact_needs_the_exact_dead_guid_and_no_other_selection():
    from wowbot.skills.loot import soft_interact_corpse
    assert soft_interact_corpse({"soft_targets": SOFT}, GUID)
    assert not soft_interact_corpse({"soft_targets": SOFT}, GUID[:-1] + "X")
    alive = [{**SOFT[0], "is_dead": False}]
    assert not soft_interact_corpse({"soft_targets": alive}, GUID)
    assert not soft_interact_corpse({"soft_targets": SOFT, "target": {"guid": "Creature-other"}}, GUID)


def test_planner_loots_an_owned_soft_interact_corpse_without_any_box():
    from test_combat_planning_policy import _world, _policy
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "objectives": [{
        "raw_type": "item", "type": "COLLECT",
        "description": "Raw Meat collected from wildlife", "current": 4, "required": 5}]}]
    world = _world(active_quests=quest, monotonic_time=10., soft_targets=SOFT)
    world.owned_corpse_guids[GUID] = 9.
    loot = [p for p in _policy(world, now=10.).proposals if p.skill == "LOOT"]
    assert loot and loot[0].parameters["soft_interact"] is True and loot[0].priority >= 100
    assert not [p for p in _policy(world, now=10.).proposals if p.skill == "RECOVER"]


def test_agent_loots_an_owned_soft_interact_corpse_through_the_planner_snapshot():
    """The planner receives a WorldSnapshot, not the WorldModel; the first
    version of this path raised AttributeError there (found by replay)."""
    from test_agent_core import agent, state
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False, "objectives": [{
        "raw_type": "item", "type": "COLLECT", "is_complete": False,
        "description": "4/5 Raw Meat collected from wildlife", "current": 4, "required": 5}]}]
    value, executor = agent()
    value.tick(state(1., active_quests=quest), 1.)
    value.world.owned_corpse_guids[GUID] = value.world.last_received
    result = value.tick(state(2., active_quests=quest, soft_targets=SOFT), 2.)
    assert result["decision"]["skill"] == "LOOT"
    assert ("BIND", "INTERACTTARGET") in [(c.kind, c.binding) for c in executor.commands]
