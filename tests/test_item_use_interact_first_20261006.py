"""Live 2026-10-05 (Re-sizing the Situation): Interact on a far boar did
nothing, the agent switched to the bag item, whose right-click only armed a
targeting cursor; a later left click on a boar fired it (1/3), the user did
2/3 and 3/3.  User 2026-10-06: "használat előtt ki kéne targetelni, utána
interact target megfelelő yardon belül, vagy jobb klikk"."""
from types import SimpleNamespace

from test_item_use_no_combat_20261004 import BOAR, INVENTORY, QUEST, _quest_proposals, _world

from wowbot.runtime import SkillStatus
from wowbot.skills.quest_item import UseItemSkill

BAG = {"items": [{"bag": 0, "slot": 10, "item_id": 170557, "is_locked": False,
                  "coordinate_space": "CLIENT_BOTTOM_LEFT", "x": .98, "y": .24}], "free_slots": 5}
TRACKED_BOAR = {**BOAR, "screen_position": {**BOAR["screen_position"], "track_id": "WORLD3D:9"}}
BOX = {"source": "WORLD3D", "track_id": "WORLD3D:9", "x": .52, "y": .48, "observed_at": 10.}


def test_selected_target_gets_interact_even_with_the_bag_open():
    _, proposals = _quest_proposals(_world(inventory=BAG, bags_open=True))
    use = [p for p in proposals if p.skill == "USE_ON_TARGET"]
    assert use and use[0].parameters["activation_source"] == "INTERACT_KEY"


def test_no_bag_opening_for_a_special_item_on_a_selected_target():
    _, proposals = _quest_proposals(_world(inventory=INVENTORY))
    assert not any(p.skill == "OPEN_BAGS" for p in proposals)


def test_failed_item_use_out_of_range_approaches_the_target():
    world = _world(inventory=INVENTORY)
    world.set_runtime_context(last_result={"skill": "USE_ON_TARGET", "outcome": "FAILURE",
                                           "reason": "out_of_range"})
    _, proposals = _quest_proposals(world)
    assert any(p.skill == "VISUAL_APPROACH" and p.parameters["guid"] == BOAR["guid"] for p in proposals)


def _state(source, *, started=10., bindings_context=None):
    return SimpleNamespace(
        skill_context={"quest_item": {"guid": BOAR["guid"], "quest_ids": [56034],
                                      "objective_ids": ["56034:0"], "activation_source": source,
                                      **(bindings_context or {})}},
        before_snapshot={"active_quests": [QUEST]}, started_at=started,
        attempt=SimpleNamespace(deadline=started+6.), phase=None)


def test_interact_without_any_cast_is_out_of_range():
    skill = UseItemSkill()
    state = _state("INTERACT_KEY")
    world = {"target": BOAR, "active_quests": [QUEST], "is_casting": False}
    assert skill.verify(state, world, 11.).status is SkillStatus.RUNNING
    far = skill.verify(state, world, 11.6)
    assert far.status is SkillStatus.FAILURE and far.reason.value == "OUT_OF_RANGE"
    casting = _state("INTERACT_KEY")
    assert skill.verify(casting, {**world, "is_casting": True}, 10.5).status is SkillStatus.RUNNING
    assert skill.verify(casting, world, 11.6).status is SkillStatus.RUNNING   # a cast started


def test_bag_use_clicks_the_target_box_for_an_armed_cursor():
    skill = UseItemSkill()
    state = _state("INVENTORY_COORDINATE")
    world = {"target": TRACKED_BOAR, "active_quests": [QUEST], "visual_candidates": [BOX]}
    hover = skill.verify(state, world, 10.5)
    assert hover.commands[0].kind == "HOVER"
    confirmed = {**world, "mouseover": {"guid": BOAR["guid"]}, "mouseover_sample_time": 10.55}
    click = skill.verify(state, confirmed, 10.7)
    assert click.commands[0].kind == "CLICK_CURRENT_CURSOR" and click.commands[0].button == "LEFT"


def test_right_click_on_the_target_without_an_interact_binding():
    skill = UseItemSkill(bindings=SimpleNamespace(contains=lambda binding: binding != "INTERACTTARGET"))
    params = {"guid": BOAR["guid"], "item_id": 170557, "quest_ids": [56034], "objective_ids": ["56034:0"],
              "binding": "INTERACTTARGET", "activation_source": "INTERACT_KEY"}
    state = SimpleNamespace(
        intent=SimpleNamespace(parameters=params, target_ref=BOAR["guid"], objective_ref="56034:0"),
        skill_type="USE_ON_TARGET", skill_context={}, phase=None, started_at=10.,
        before_snapshot={"active_quests": [QUEST]}, attempt=SimpleNamespace(deadline=16.))
    world = {"target": TRACKED_BOAR, "actionbar": [], "active_quests": [QUEST], "visual_candidates": [BOX]}
    begun = skill.begin(state, world)
    assert begun.commands[0].kind == "HOVER"
    click = skill.verify(state, {**world, "mouseover": {"guid": BOAR["guid"]},
                                 "mouseover_sample_time": 10.1}, 10.6)
    assert click.commands[0].kind == "CLICK_CURRENT_CURSOR" and click.commands[0].button == "RIGHT"
