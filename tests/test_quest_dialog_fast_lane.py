from wowbot.agent.planner import QuestDomain
from wowbot.agent.models import Goal
from wowbot.agent.world import WorldModel


def base_state():
    return dict(map_id=1409, session_id="test", monotonic_time=1,
                target={}, active_quests=[])


def test_quest_dialog_uses_fast_lane_coordinates_when_slow_snapshot_is_stale():
    # The slow/paged quest_ui always carries x=0,y=0 as its zero-value
    # default (the addon never omits these keys), so a plain
    # dict.get("x", state.get("quest_ui_x"))-style fallback never actually
    # reaches the fresher fast-lane fields. QUEST_DETAIL fires the fast hint
    # (action known) well before the next slow paged snapshot refreshes
    # quest_ui's own x/y.
    state = base_state()
    state.update(quest_ui={"open": True, "action": "", "x": 0, "y": 0, "quest_id": 0},
                 quest_ui_open=True, quest_ui_action="ACCEPT",
                 quest_ui_x=.42, quest_ui_y=.87, quest_ui_quest_id=55122)
    world = WorldModel()
    world.state = state
    proposals = QuestDomain().propose(world, None)
    dialog = next((p for p in proposals if p.skill == "QUEST_DIALOG"), None)
    assert dialog is not None, "QUEST_DIALOG must be proposed from fast-lane x/y when the slow snapshot is stale"
    assert dialog.parameters["x"] == .42
    assert dialog.parameters["y"] == .87
    assert dialog.parameters["action"] == "ACCEPT"
    assert dialog.parameters["quest_id"] == 55122


def test_quest_dialog_prefers_slow_lane_coordinates_once_refreshed():
    # Once the slow snapshot itself carries a real (non-zero) position, it
    # remains the authoritative source and is not overridden by a possibly
    # older fast-lane sample.
    state = base_state()
    state.update(quest_ui={"open": True, "action": "ACCEPT", "x": .5, "y": .6, "quest_id": 55122},
                 quest_ui_open=True, quest_ui_action="ACCEPT",
                 quest_ui_x=.42, quest_ui_y=.87, quest_ui_quest_id=55122)
    world = WorldModel()
    world.state = state
    proposals = QuestDomain().propose(world, None)
    dialog = next((p for p in proposals if p.skill == "QUEST_DIALOG"), None)
    assert dialog is not None
    assert dialog.parameters["x"] == .5
    assert dialog.parameters["y"] == .6


def test_no_quest_dialog_proposal_without_any_valid_coordinate():
    state = base_state()
    state.update(quest_ui={"open": True, "action": "", "x": 0, "y": 0, "quest_id": 0},
                 quest_ui_open=True, quest_ui_action="ACCEPT")
    world = WorldModel()
    world.state = state
    proposals = QuestDomain().propose(world, None)
    assert not any(p.skill == "QUEST_DIALOG" for p in proposals)


def test_gossip_row_is_a_selection_step_not_an_imagined_accept_click():
    state = base_state()
    state["quest_ui"] = {"open": True, "action": "", "entries": [
        {"kind": "AVAILABLE", "quest_id": 55122, "title": "A quest", "x": .31, "y": .42,
         "acceptable": True},
    ]}
    world = WorldModel()
    world.state = state
    proposal = next(p for p in QuestDomain().propose(world, None) if p.skill == "QUEST_DIALOG")
    assert proposal.parameters["action"] == "GOSSIP_SELECT"
    assert proposal.parameters["gossip_kind"] == "AVAILABLE"
    assert proposal.parameters["quest_id"] == 55122


def test_multiple_gossip_offers_select_one_visible_row_then_allow_goal_override():
    state = base_state()
    state["quest_ui"] = {"open": True, "entries": [
        {"kind": "AVAILABLE", "quest_id": 10, "x": .21, "y": .31, "acceptable": True},
        {"kind": "AVAILABLE", "quest_id": 20, "x": .22, "y": .41, "acceptable": True},
    ]}
    world = WorldModel()
    world.state = state
    domain = QuestDomain()
    proposals = domain.propose(world, Goal.parse("Questelj", 1.))
    dialog = next(item for item in proposals if item.skill == "QUEST_DIALOG")
    assert dialog.parameters["quest_id"] == 10
    assert dialog.parameters["action"] == "GOSSIP_SELECT"
    assert not any(item.parameters.get("reason") == "quest_offer_selection_required"
                   for item in proposals)

    selected = domain.propose(world, Goal.parse("Questelj", 1., {"quest_id": 20}))
    dialog = next(item for item in selected if item.skill == "QUEST_DIALOG")
    assert dialog.parameters["quest_id"] == 20


def test_visible_gossip_rows_without_coordinates_block_world_navigation():
    state = base_state()
    state["quest_ui"] = {"open": True, "action": "", "entries": [
        {"kind": "AVAILABLE", "quest_id": 55186, "title": "Down with the Quilboar",
         "x": 0, "y": 0, "acceptable": True},
        {"kind": "AVAILABLE", "quest_id": 55184, "title": "Quilboar Shadow Magic",
         "x": 0, "y": 0, "acceptable": True},
    ]}
    world = WorldModel()
    world.state = state
    proposals = QuestDomain().propose(world, Goal.parse("Questelj", 1.))
    blocked = next(item for item in proposals
                   if item.parameters.get("reason") == "quest_dialog_rows_unaddressable")
    assert blocked.skill == "WAIT"
    assert blocked.priority == 110
    assert blocked.parameters["offered_quest_ids"] == ["55184", "55186"]
    assert not any(item.skill == "QUEST_DIALOG" for item in proposals)


def test_reward_choice_needs_goal_policy_and_emits_only_the_exact_exported_row():
    state = base_state()
    state["quest_ui"] = {"open": True, "action": "REWARD_SELECT", "quest_id": 42,
                         "reward_choices": [
                             {"index": 1, "item_id": 100, "x": .2, "y": .3, "selected": False},
                             {"index": 2, "item_id": 200, "x": .4, "y": .5, "selected": False},
                         ]}
    world = WorldModel()
    world.state = state
    domain = QuestDomain()
    # A goal may still forbid an automatic choice explicitly.
    blocked = domain.propose(world, Goal.parse("Questelj", 1., {"reward_policy": "BLOCKED"}))
    assert not any(item.skill == "QUEST_DIALOG" and item.parameters.get("action") == "REWARD_SELECT"
                   for item in blocked)
    # User 2026-10-04: without a goal policy the deterministic AUTO rule picks
    # (usable -> item level -> vendor price -> lowest row), so the turn-in
    # never stalls in the reward window.
    automatic = domain.propose(world, Goal.parse("Questelj", 1.))
    dialog = next(item for item in automatic
                  if item.skill == "QUEST_DIALOG" and item.parameters.get("action") == "REWARD_SELECT")
    assert dialog.parameters["reward_choice_index"] == 1

    selected = domain.propose(world, Goal.parse("Questelj", 1., {"reward_item_id": 200}))
    dialog = next(item for item in selected
                  if item.skill == "QUEST_DIALOG" and item.parameters.get("action") == "REWARD_SELECT")
    assert dialog.parameters["reward_choice_index"] == 2
    assert dialog.parameters["x"] == .4 and dialog.parameters["y"] == .5
