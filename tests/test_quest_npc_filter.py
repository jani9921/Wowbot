"""Questing with no active quest selects only quest NPCs (user 2026-10-02).

Live 20:44: the agent selected Kee-La (no "!") and lost ~45 s before Jaina.
The probe on Jaina proved Retail 12.1 has no quest-giver API on hover or
target, so the evidence is the overhead "!" (vision) or an API giver spot.
"""
from types import SimpleNamespace

from wowbot.agent.models import Goal, Outcome, Proposal
from wowbot.agent.quest_giver_evidence import (
    NOT_QUEST_GIVER_SECONDS, npc_shows_quest_symbol, quest_search_allows_npc, symbol_above)
from wowbot.agent.target_planning import TargetPlanningPolicy
from test_agent_core import quest_npc_boxes

KEELA = {"guid": "Creature-0-1-2-3-158000-1", "npc_id": 158000, "name": "Kee-La",
         "unit_type": "NPC", "is_attackable": False}


def _state(*, candidates=(), active_quests=(), pois=None, player=(0., 0.)):
    return {"mouseover": KEELA, "cursor_position": {"nx": .5, "ny": .6},
            "visual_candidates": list(candidates), "active_quests": list(active_quests),
            "player_world_position": {"x": player[0], "y": player[1], "instance_id": 2175},
            "map_pois": {"available_quests": pois or []}}


def _targets(state, goal="Questelj", objective_types=()):
    ready = [SimpleNamespace(type=kind) for kind in objective_types]
    world = SimpleNamespace(state=state, quest_model=SimpleNamespace(ready=lambda: ready))
    proposals = TargetPlanningPolicy().propose(
        world, Goal.parse(goal, 1.), target={}, cursor_matches_mouseover=True,
        state_time=1., mouse_time=1.)
    return [p for p in proposals if p.skill == "TARGET"]


def _body(x=.5, y=.6, track="WORLD3D:keela"):
    return quest_npc_boxes(x, y, track)[0]


def _giver(x, y):
    return {"quest_id": 55122, "x": .5, "y": .5, "source": "QUESTLINE_API",
            "world_position": {"x": x, "y": y, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}


def test_npc_without_a_quest_symbol_is_not_selected_while_questing():
    assert _targets(_state(candidates=[_body()])) == []


def test_npc_with_a_quest_symbol_over_its_head_is_selected():
    targets = _targets(_state(candidates=quest_npc_boxes(.5, .6, "WORLD3D:keela")))
    assert [t.parameters["guid"] for t in targets] == [KEELA["guid"]]


def test_without_any_symbol_an_npc_at_an_api_giver_spot_may_be_tried():
    near = _state(candidates=[_body()], pois=[_giver(10., 5.)])
    assert len(_targets(near)) == 1
    far = _state(candidates=[_body()], pois=[_giver(80., 5.)])
    assert _targets(far) == []
    # A "!" over somebody else means the giver is that one, not this NPC.
    jaina = quest_npc_boxes(.2, .6, "WORLD3D:jaina")
    for box in jaina:        # Jaina stands 300 px to the left of Kee-La
        box["bbox"] = {**box["bbox"], "left": box["bbox"]["left"]-300,
                       "right": box["bbox"]["right"]-300}
    other = [_body(), *jaina]
    assert _targets(_state(candidates=other, pois=[_giver(10., 5.)])) == []


def test_active_quest_selects_friendly_npcs_only_when_they_matter():
    """Live 2026-10-03 (Cooking Meat): with only a COLLECT objective the agent
    selected an Alliance Sparring Partner and another player's pet."""
    busy = _state(candidates=[_body()], active_quests=[{"quest_id": 1, "objectives": []}])
    assert len(_targets(busy, objective_types=["TALK_TO"])) == 1
    assert _targets(busy, objective_types=["COLLECT"]) == []
    # A "!"/"?" over the NPC still makes it worth a look.
    marked = _state(candidates=quest_npc_boxes(.5, .6, "WORLD3D:keela"),
                    active_quests=[{"quest_id": 1, "objectives": []}])
    assert len(_targets(marked, objective_types=["COLLECT"])) == 1
    # Other goals are not questing: friendly NPCs stay selectable.
    assert len(_targets(_state(candidates=[_body()]), goal="menj az npc-hez")) == 1


def test_a_companion_pet_is_never_selected():
    pet = {"guid": "Pet-0-3102-2175-11354-416-0104B063CD", "npc_id": 416, "name": "Pipfip",
           "unit_type": "NPC", "is_attackable": False}
    state = {**_state(candidates=quest_npc_boxes(.5, .6, "WORLD3D:pet"),
                      active_quests=[{"quest_id": 1, "objectives": []}]), "mouseover": pet}
    assert _targets(state, objective_types=["TALK_TO"]) == []
    assert _targets(state, goal="menj az npc-hez") == []


def test_a_corpse_the_addon_reports_empty_is_not_looted_again():
    from wowbot.agent.combat_planning import CombatPlanningPolicy
    goat = "Creature-0-3102-2175-11354-161130-0000408640"
    assert CombatPlanningPolicy._reported_empty({"mouseover": {"guid": goat, "lootable": False}}, goat)
    assert not CombatPlanningPolicy._reported_empty({"mouseover": {"guid": goat, "lootable": True}}, goat)
    assert not CombatPlanningPolicy._reported_empty({"target": {"guid": goat}}, goat)


def test_symbol_must_sit_over_the_head():
    body = _body()
    def mark(left, top, right, bottom):
        return {"bbox": {"left": left, "top": top, "right": right, "bottom": bottom,
                         "coordinate_space": "CLIENT_PIXELS"}}
    assert symbol_above(body, mark(520, 160, 540, 195))       # just above the head
    assert not symbol_above(body, mark(700, 160, 720, 195))   # beside, not above
    assert not symbol_above(body, mark(520, 0, 540, 20))      # far above (other unit)
    assert not symbol_above(body, mark(520, 250, 540, 280))   # on the body
    assert not symbol_above(body, mark(480, 10, 580, 199))    # taller than the NPC


def test_bound_hover_track_decides_which_box_is_the_npc():
    state = _state(candidates=quest_npc_boxes(.9, .2, "WORLD3D:keela"))
    state["confirmed_mouseover_anchors"] = {KEELA["guid"]: {"track_id": "WORLD3D:keela"}}
    assert npc_shows_quest_symbol(state, KEELA["guid"])        # far from cursor, but bound
    assert quest_search_allows_npc(state, KEELA["guid"])


def test_silent_npc_without_a_symbol_is_skipped_for_a_while():
    from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
    from wowbot.agent.quest_planning import QuestDomain
    quest = QuestDomain()
    world = SimpleNamespace(state={**_state(candidates=[_body()]), "target": KEELA,
                                   "monotonic_time": 100.},
                            quest_signature=lambda state: "[]")
    planner = SimpleNamespace(quest=quest, map_search_policy=SimpleNamespace(on_terminal=lambda *a: None),
                              camera_search_step=0, camera_search_next_at=0.)
    attempt = SimpleNamespace(proposal=Proposal.make("INTERACT", "t", {"guid": KEELA["guid"]}))
    ExecutionBookkeeper().record_terminal(attempt, Outcome.FAILURE, "no_response", 100.,
                                          planner=planner, world=world, recovery_resume=None)
    state = {"active_quests": []}
    assert KEELA["guid"] in quest.unresponsive_guid_set(state, 150.)
    assert KEELA["guid"] not in quest.unresponsive_guid_set(state, 100. + NOT_QUEST_GIVER_SECONDS + 1)
    # A "!" NPC's silence may only be range: it is not put on this list.
    quest2 = QuestDomain()
    world.state = {**world.state, "visual_candidates": quest_npc_boxes(.5, .6, "WORLD3D:keela")}
    planner.quest = quest2
    ExecutionBookkeeper().record_terminal(attempt, Outcome.FAILURE, "no_response", 100.,
                                          planner=planner, world=world, recovery_resume=None)
    assert KEELA["guid"] not in quest2.unresponsive_guid_set(state, 150.)



def test_hostile_named_in_its_tooltip_by_an_active_quest_is_targeted():
    """Live 2026-10-03 09:43: the porcupine's tooltip named "Cooking Meat" but
    quest_related arrived empty and it was never targeted."""
    from wowbot.agent.target_planning import tooltip_names_active_quest
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False, "objectives": []}]
    porcupine = {"guid": "Creature-0-3102-2175-11354-161131-000040B1B3", "npc_id": 161131,
                 "name": "Prickly Porcupine", "unit_type": "NPC", "is_attackable": True, "is_dead": False,
                 "tooltip": "Prickly Porcupine ~ Level 3 ~ Beast ~ Cooking Meat ~ 1/5 Raw Meat collected from wildlife"}
    state = {"mouseover": porcupine, "cursor_position": {"nx": .5, "ny": .6},
             "visual_candidates": [], "active_quests": quest}
    assert tooltip_names_active_quest(porcupine, state)
    targets = _targets(state, objective_types=["COLLECT"])
    assert [t.parameters["guid"] for t in targets] == [porcupine["guid"]]
    # A stale tooltip of another unit never counts.
    assert not tooltip_names_active_quest({**porcupine, "name": "Coastal Goat"}, state)
