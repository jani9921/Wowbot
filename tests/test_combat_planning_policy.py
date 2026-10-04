from pathlib import Path

from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.autonomy_loop import AutonomousLoop, CommittedSubgoal
from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy


def _world(**overrides):
    state = {
        "session_id": "combat-policy", "frame_id": "f:1", "timestamp": 1.,
        "monotonic_time": 1., "map_id": 1609, "player_present": True,
        "is_in_combat": False, "health": 100, "max_health": 100,
        "target": None, "mouseover": None, "actionbar": [], "events": [],
        "event_sequence": 0, "active_quests": [], "confirmed_corpse_anchors": [],
    }
    state.update(overrides)
    value = WorldModel()
    value.ingest(Observation.create(state, 1.))
    return value


def _policy(world, *, parameters=None, now=1.):
    return CombatPlanningPolicy(SkillRegistry()).propose(
        world, Goal.parse("Questelj", now, parameters), now, QuestDomain())


def _quest(subject="Murloc"):
    return [{"quest_id": 101, "title": "Combat test", "objectives": [{
        "raw_type": "monster", "type": "KILL",
        "description": f"1 {subject} slain", "current": 0, "required": 1,
    }]}]


def test_matching_quest_target_produces_combat_with_scoped_credit_identity():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": True}])

    result = _policy(world)
    combat = next(proposal for proposal in result.proposals if proposal.skill == "COMBAT")

    assert combat.parameters["guid"] == "Creature-Murloc"
    assert combat.parameters["quest_ids"] == [101]
    assert combat.parameters["objective_ids"] == ["101:0"]
    assert tuple(item.objective_id for item in result.matching_objectives) == ("101:0",)


def test_selected_out_of_range_murloc_uses_world3d_visual_approach_without_hover():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Murloc", "npc_id": 150229,
                "name": "Murloc Watershaper", "attackable": True,
                "dead": False, "screen_position": None},
        mouseover=None,
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": False}],
        visual_candidates=[{
            "source": "WORLD3D", "detector_kind": "unknown_subject_candidate",
            "track_id": "WORLD3D:murloc", "x": .63, "y": .52,
            "confidence": .31, "stable_frames": 8, "lifecycle": "STABLE",
            "candidate_labels": ["learned_subject_like"],
            "appearance": {"learned_label_hypothesis": "creature_unit_like",
                           "learned_confidence": .31,
                           "screen_center_relevance": .74},
        }],
    )

    result = _policy(world)
    approach = next(proposal for proposal in result.proposals
                    if proposal.skill == "VISUAL_APPROACH")

    assert approach.parameters["guid"] == "Creature-Murloc"
    assert approach.parameters["track_id"] == "WORLD3D:murloc"
    assert approach.parameters["screen_position"]["track_association"] == \
        "CANDIDATE_SELECTED_TARGET"
    assert approach.parameters["screen_position"]["identity_source"] == \
        "SELECTED_TARGET_GUID"


def test_selected_target_without_hover_or_stable_visual_candidate_does_not_move_blindly():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                "attackable": True, "dead": False, "screen_position": None},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": False}],
        visual_candidates=[{
            "source": "WORLD3D", "detector_kind": "unknown_subject_candidate",
            "track_id": "WORLD3D:weak", "x": .6, "y": .5,
            "confidence": .14, "stable_frames": 2, "lifecycle": "TENTATIVE",
            "candidate_labels": ["learned_subject_like"],
        }],
    )

    assert not any(proposal.skill == "VISUAL_APPROACH"
                   for proposal in _policy(world).proposals)


def test_fast_out_of_range_target_with_visual_track_produces_visual_approach_without_world_xyz():
    screen = {
        "x": .56, "y": .72, "sample_time": 2., "source": "NAMEPLATE_API",
        "coordinate_space": "CLIENT_BOTTOM_LEFT", "track_id": "WORLD3D:47",
        "track_association": "CONFIRMED_GUID_NAMEPLATE",
    }
    world = _world(
        monotonic_time=2., active_quests=_quest(),
        target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                "attackable": True, "dead": False, "world_position": None,
                "screen_position": screen},
        actionbar=[{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                    "is_harmful": True, "is_usable": True, "in_range": True,
                    "cooldown_remaining": 0}],
        actionbar_fast=[[1, True, False, 0]],
    )

    result = _policy(world, now=2.)
    approach = next(proposal for proposal in result.proposals
                    if proposal.skill == "VISUAL_APPROACH")

    assert approach.parameters["guid"] == "Creature-Murloc"
    assert approach.parameters["track_id"] == "WORLD3D:47"
    assert approach.parameters["screen_position"] == screen


def test_unrelated_hostile_does_not_become_quest_combat_outside_combat():
    world = _world(
        active_quests=_quest("Cave Spider"),
        target={"guid": "Creature-Pirate", "name": "Pirate",
                "attackable": True, "dead": False})

    result = _policy(world)

    assert not any(proposal.skill in {"COMBAT", "DEFEND"} for proposal in result.proposals)
    assert not result.matching_objectives


def test_offscreen_out_of_range_quest_target_does_not_start_combat():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": False}],
    )

    result = _policy(world)

    assert not any(proposal.skill in {"COMBAT", "VISUAL_APPROACH"}
                   for proposal in result.proposals)


def test_kill_objective_does_not_use_blind_tab_as_visual_search():
    world = _world(active_quests=_quest(), target=None)

    proposals = QuestDomain().propose(world, Goal.parse("Questelj", 1.))

    assert not any(proposal.skill == "ACQUIRE_TARGET" for proposal in proposals)


def test_blind_tab_target_identity_is_not_promoted_without_location_or_range():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Goat", "name": "Coastal Goat",
                "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": False}],
    )
    loop = AutonomousLoop()
    loop.commitment = CommittedSubgoal(
        "acquire-1", "goal-1", "acquire:goal-relevant-target", "ACQUIRE",
        None, None, (), "ACQUIRE_TARGET", 0., 0., session_id=world.session_id,
        map_id=1609)

    loop._promote_late_acquired_target(world, 1.)

    assert loop.commitment is None
    assert loop.last_replan_trigger == "BLIND_TARGET_UNLOCATABLE"
    assert loop.lifecycle[-1]["event"] == "PHASE_CHANGED"


def test_in_range_tab_target_may_be_promoted_for_active_defense():
    world = _world(
        is_in_combat=True,
        target={"guid": "Creature-Attacker", "name": "",
                "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": True}],
    )
    loop = AutonomousLoop()
    loop.commitment = CommittedSubgoal(
        "acquire-2", "goal-1", "acquire:goal-relevant-target", "ACQUIRE",
        None, None, (), "ACQUIRE_TARGET", 0., 0., session_id=world.session_id,
        map_id=1609)

    loop._promote_late_acquired_target(world, 1.)

    assert loop.commitment is not None
    assert loop.commitment.kind == "TARGET"
    assert loop.commitment.target_guid == "Creature-Attacker"


def test_offscreen_selected_identity_does_not_suppress_world3d_search():
    world = _world(
        active_quests=_quest(),
        target={"guid": "Creature-Offscreen", "name": "Murloc Watershaper",
                "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": False}],
    )

    result = VisualSearchPlanningPolicy().propose(
        [], world=world, goal=Goal.parse("Questelj", 1.), now=1.,
        target=world.query.target(), matching_objectives=(object(),),
        active_perception=ActivePerception(), blocked_until={},
        world3d_probe_count=0, camera_search_step=0,
        camera_search_next_at=0., camera_search_position=None)

    assert any(proposal.skill == "SEEK_VISUAL_CUE" for proposal in result.proposals)


def test_active_unrelated_attacker_produces_defend_without_inventing_quest_credit():
    world = _world(
        is_in_combat=True, active_quests=_quest("Cave Spider"),
        target={"guid": "Creature-Pirate", "name": "Pirate",
                "attackable": True, "dead": False})

    result = _policy(world)
    defend = next(proposal for proposal in result.proposals if proposal.skill == "DEFEND")

    assert defend.parameters["guid"] == "Creature-Pirate"
    assert defend.parameters["quest_ids"] == []
    assert defend.parameters["objective_ids"] == []
    assert not any(proposal.skill == "COMBAT" for proposal in result.proposals)


def test_confirmed_corpse_anchor_is_looted_before_new_target_search():
    guid = "Creature-0-1-2-3-150228-00000001"
    world = _world(
        active_quests=_quest(),
        mouseover={"guid": guid, "name": "Murloc", "is_dead": True,
                   "lootable": True},
        cursor_position={"nx": .42, "ny": .51},
        cursor_sample_time=1., mouseover_sample_time=1., event_sequence=1,
        events=[{"sequence": 1, "timestamp": 1.,
                 "event_type": "MOUSEOVER_CHANGED",
                 "payload": {"tooltip": "Murloc ~ Corpse",
                             "tooltip_data": {"guid": guid, "unit_guid": guid,
                                              "lootable": True}}}],
    )
    anchor = world.state["confirmed_corpse_anchors"][0]

    result = _policy(world)
    loot = next(proposal for proposal in result.proposals if proposal.skill == "LOOT")

    assert loot.priority == 108
    assert loot.parameters["corpse_anchor"] is True
    assert loot.parameters["guid"] == guid
    assert loot.evidence == (anchor["observation_id"],)


def test_unowned_dead_target_is_not_looted_from_dead_state_alone():
    guid = "Creature-0-1-2-3-150228-00000099"
    world = _world(
        active_quests=_quest(),
        target={"guid": guid, "name": "Murloc", "attackable": True,
                "dead": True, "health": 0},
    )

    result = _policy(world)

    assert not any(proposal.skill == "LOOT" for proposal in result.proposals)


def test_target_commitment_reacquires_only_from_fresh_confirmed_same_guid_anchor():
    mouseover = {
        "guid": "Creature-Jaina", "name": "Lady Jaina Proudmoore",
        "npc_id": 156626, "unit_type": "NPC",
        "is_attackable": False, "is_dead": False,
    }
    world = _world(
        mouseover=mouseover, cursor_position={"nx": .63, "ny": .42},
        cursor_sample_time=1., mouseover_sample_time=1.,
    )
    world.runtime_context["commitment"] = {
        "kind": "TARGET", "target_guid": "Creature-Jaina"}
    world.ingest(Observation.create({
        "session_id": "combat-policy", "frame_id": "f:2", "timestamp": 2.,
        "monotonic_time": 2., "map_id": 1609, "player_present": True,
        "is_in_combat": False, "health": 100, "max_health": 100,
        "target": None, "mouseover": None, "actionbar": [], "events": [],
        "event_sequence": 0, "active_quests": [],
    }, 2.))

    result = _policy(world, now=2.)
    reacquire = next(proposal for proposal in result.proposals
                     if proposal.skill == "REACQUIRE_TARGET")

    assert reacquire.parameters == {
        "guid": "Creature-Jaina", "target_x": .63, "target_y": .42}

    world.ingest(Observation.create({
        "session_id": "combat-policy", "frame_id": "f:2", "timestamp": 40.,
        "monotonic_time": 40., "map_id": 1609, "player_present": True,
        "is_in_combat": False, "health": 100, "max_health": 100,
        "target": None, "mouseover": None, "actionbar": [], "events": [],
        "event_sequence": 0, "active_quests": [],
    }, 40.))
    stale = _policy(world, now=40.)
    assert not any(proposal.skill == "REACQUIRE_TARGET" for proposal in stale.proposals)


def test_combat_planning_module_has_no_execution_or_state_write_authority():
    source = Path("src/wowbot/agent/combat_planning.py").read_text(encoding="utf-8")
    forbidden = ("InputExecutor", "CommandDispatcher", ".dispatch(", ".ingest(",
                 "ReachMovementController", "ActiveSkillRuntime")
    assert all(token not in source for token in forbidden)


def test_target_judged_relevant_from_its_tooltip_gets_combat_at_once():
    """Live 2026-10-03 13:12: Prickly Porcupine targeted because its tooltip
    named the active "Raw Meat" quest; the objective ("from wildlife") names
    no creature and the target frame carries no quest flag -- MOVE won 18 s."""
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "objectives": [{
        "raw_type": "item", "type": "COLLECT",
        "description": "Raw Meat collected from wildlife", "current": 0, "required": 5}]}]
    porcupine = {"guid": "Creature-0-3102-2175-11354-161131-000040DFAA", "npc_id": 161131,
                 "name": "Prickly Porcupine", "attackable": True, "dead": False}
    bar = [{"id": 1, "kind": "spell", "is_harmful": True, "is_usable": True, "in_range": True}]
    world = _world(active_quests=quest, target=porcupine, actionbar=bar)
    assert not any(p.skill == "COMBAT" for p in _policy(world).proposals)
    world.quest_relevant_units[porcupine["guid"]] = 1.
    assert any(p.skill == "COMBAT" and p.priority >= 90 for p in _policy(world).proposals)
    # Old judgements expire.
    world.quest_relevant_units[porcupine["guid"]] = -700.
    assert not any(p.skill == "COMBAT" for p in _policy(world).proposals)


def test_corpse_hidden_under_the_character_is_revealed_by_one_step_back():
    """Live 2026-10-03 13:36: killed in melee, corpse under the character
    model -> no box, no anchor, no LOOT (screenshots 0263/0264)."""
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "objectives": [{
        "raw_type": "item", "type": "COLLECT",
        "description": "Raw Meat collected from wildlife", "current": 4, "required": 5}]}]
    world = _world(active_quests=quest, monotonic_time=10.)
    world.owned_corpse_guids["Creature-0-1-2-3-161131-000040E861"] = 9.
    reveal = [p for p in _policy(world, now=10.).proposals if p.skill == "RECOVER"]
    assert reveal and reveal[0].parameters["recovery_step"] == "BACKWARD_REVEAL"
    # Only once per corpse.
    assert not [p for p in _policy(world, now=10.5).proposals if p.skill == "RECOVER"]
    from wowbot.agent.skills import SkillRegistry
    commands = SkillRegistry().commands(reveal[0], world)
    assert [c.binding for c in commands] == ["MOVEBACKWARD", "MOVEBACKWARD"]


def test_tooltip_relevance_of_one_porcupine_covers_the_selected_other_one():
    """Live 2026-10-03 13:42: a Prickly Porcupine selected (after a restart)
    was never attacked -- its frame carries no quest flag."""
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False, "objectives": [{
        "raw_type": "item", "type": "COLLECT",
        "description": "Raw Meat collected from wildlife", "current": 4, "required": 5}]}]
    hovered = {"guid": "Creature-0-1-2-3-161131-00000000AA", "npc_id": 161131,
               "name": "Prickly Porcupine", "attackable": True, "dead": False,
               "tooltip": "Prickly Porcupine ~ Level 3 ~ Beast ~ Cooking Meat ~ 4/5 Raw Meat collected from wildlife"}
    world = _world(active_quests=quest, mouseover=hovered, cursor_position={"nx": .5, "ny": .5})
    selected = {"guid": "Creature-0-1-2-3-161131-00000000BB", "npc_id": 161131,
                "name": "Prickly Porcupine", "attackable": True, "dead": False}
    world.ingest(Observation.create({**world.state, "frame_id": "f:2", "monotonic_time": 2.,
                                     "mouseover": None, "target": selected}, 2.))
    assert world.state["target"].get("quest_relevant") is True
    assert str(world.state["target"].get("quest_id")) == "55174"


def test_a_completed_tooltip_objective_is_not_relevant_any_more():
    """Live 2026-10-03 13:52:47: 5/5 Raw Meat, yet the goat's tooltip still
    listed "Cooking Meat ~ 5/5 ..." and three more goats were killed."""
    from wowbot.agent.tooltip_quest import tooltip_objectives_done, tooltip_quest_id
    state = {"active_quests": [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False}]}
    goat = {"name": "Coastal Goat", "tooltip":
            "Coastal Goat ~ Level 3 ~ Beast ~ Cooking Meat ~ 5/5 Raw Meat collected from wildlife"}
    assert tooltip_objectives_done(goat) and tooltip_quest_id(goat, state) is None
    open_goat = {**goat, "tooltip": goat["tooltip"].replace("5/5", "4/5")}
    assert not tooltip_objectives_done(open_goat) and tooltip_quest_id(open_goat, state) == 55174
    assert not tooltip_objectives_done({"tooltip": "Murloc ~ Level 2 ~ Kill Quest"})


def test_remembered_creature_type_stops_counting_once_its_objective_is_done():
    from wowbot.agent.tooltip_quest import objective_still_open
    quest = {"quest_id": 55174, "is_complete": False, "objectives": [
        {"description": "5/5 Raw Meat collected from wildlife", "is_complete": True},
        {"description": "0/1 Cook the meat on the campfire", "is_complete": False}]}
    keys = ["raw meat collected from wildlife"]
    assert not objective_still_open({"active_quests": [quest]}, 55174, keys)
    quest["objectives"][0].update(description="4/5 Raw Meat collected from wildlife", is_complete=False)
    assert objective_still_open({"active_quests": [quest]}, 55174, keys)


def test_cook_on_the_campfire_is_an_object_use_not_more_hunting():
    """User 2026-10-03: after 5/5 Raw Meat the agent kept fighting; the quest
    wants "Cook the meat on the campfire" (an `item` objective in the API)."""
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False, "objectives": [
        {"raw_type": "item", "type": "COLLECT", "is_complete": True,
         "description": "5/5 Raw Meat collected from wildlife", "current": 5, "required": 5},
        {"raw_type": "item", "type": "COLLECT", "is_complete": False,
         "description": "0/1 Cook the meat on the campfire", "current": 0, "required": 1}]}]
    world = _world(active_quests=quest, cursor_position={"nx": .45, "ny": .55},
                   mouseover={"tooltip": "Campfire", "name": "Campfire"})
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1.), world, 1.)
    use = [p for p in proposals if p.skill == "OBJECT_USE"]
    assert use and use[0].parameters["objective_id"] == "55174:1"


def test_a_truncated_creature_tooltip_is_not_quest_evidence():
    """Live 2026-10-03 14:19: "Coastal Goat ~ Level 3 ~ Beast ~ Cooking Meat"
    (no objective line yet) made a goat relevant again after 5/5."""
    from wowbot.agent.tooltip_quest import creature_tooltip_open, tooltip_quest_id
    state = {"active_quests": [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False}]}
    truncated = {"name": "Coastal Goat", "attackable": True,
                 "tooltip": "Coastal Goat ~ Level 3 ~ Beast ~ Cooking Meat"}
    assert tooltip_quest_id(truncated, state) is None and not creature_tooltip_open(truncated)
    campfire = {"name": "Campfire", "tooltip": "Campfire ~ Cooking Meat ~ 0/1 Cook the meat on the campfire"}
    assert tooltip_quest_id(campfire, state) == 55174


COOKING = [{"quest_id": 55174, "title": "Cooking Meat", "is_complete": False, "objectives": [
    {"raw_type": "item", "type": "COLLECT", "is_complete": True,
     "description": "5/5 Raw Meat collected from wildlife", "current": 5, "required": 5},
    {"raw_type": "item", "type": "COLLECT", "is_complete": False,
     "description": "0/1 Cook the meat on the campfire", "current": 0, "required": 1}]}]


def test_fast_lane_quest_flag_without_text_needs_an_open_creature_objective():
    """Live 14:23: FAST mouseover {name: Coastal Goat, quest_related: true}."""
    from wowbot.agent.tooltip_quest import creature_tooltip_open
    goat = {"name": "Coastal Goat", "attackable": True, "quest_related": True, "quest_id": 55174}
    assert not creature_tooltip_open(goat, {"active_quests": COOKING})
    open_meat = [dict(COOKING[0], objectives=[dict(COOKING[0]["objectives"][0], is_complete=False,
                                                    description="4/5 Raw Meat collected from wildlife")])]
    assert creature_tooltip_open(goat, {"active_quests": open_meat})


def test_campfire_name_comes_from_the_mouseover_change_event():
    """Live 14:16: FAST mouseover {quest_related, quest_id}; the name only in
    MOUSEOVER_CHANGED "Campfire ~ Cooking Meat ~ 0/1 Cook the meat on the campfire"."""
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.tooltip_quest import effective_mouseover
    event = {"event_type": "MOUSEOVER_CHANGED", "sequence": 3354, "source": "WOW_API", "payload": {
        "object_id": 0, "quest_id": 55174, "quest_related": True,
        "tooltip": "Campfire ~ Cooking Meat ~ 0/1 Cook the meat on the campfire",
        "tooltip_data": {"guid": "", "unit_name": "Campfire", "raw_type": 4}}}
    state = {"mouseover": {"quest_related": True, "quest_id": 55174}, "events": [event]}
    assert effective_mouseover(state)["name"] == "Campfire"
    # A unit under the cursor, or another quest, never borrows the name.
    assert "tooltip" not in effective_mouseover({**state, "mouseover": {"guid": "Creature-1"}})
    assert "tooltip" not in effective_mouseover({**state, "mouseover": {"quest_related": True, "quest_id": 1}})
    world = _world(active_quests=COOKING, cursor_position={"nx": .68, "ny": .62},
                   mouseover={"quest_related": True, "quest_id": 55174}, events=[event],
                   event_sequence=3354)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert any(p.skill == "OBJECT_USE" for p in proposals)


def test_late_campfire_event_names_the_object_under_a_still_cursor():
    """Live 14:16 replay: the FAST sample dropped the bare quest flag before
    the slow-lane MOUSEOVER_CHANGED (Campfire) arrived; the cursor had been
    still for 2 s.  The object is attributed to that cursor until it moves."""
    from wowbot.agent.models import Observation
    from wowbot.skills.object_use import ObjectUseSkill
    from test_m0_combat_loot_skills import active
    event = {"event_type": "MOUSEOVER_CHANGED", "sequence": 3354, "source": "WOW_API", "payload": {
        "object_id": 0, "quest_id": 55174, "quest_related": True,
        "tooltip": "Campfire ~ Cooking Meat ~ 0/1 Cook the meat on the campfire",
        "tooltip_data": {"guid": "", "unit_name": "Campfire", "raw_type": 4}}}
    cursor = {"nx": .446, "ny": .539}
    world = _world(active_quests=COOKING, cursor_position=cursor, mouseover={})
    fast = {**world.state, "transport_kind": "FAST", "frame_id": "fast:3", "monotonic_time": 3.,
            "cursor_position": cursor, "mouseover": {}, "events": [event]}
    world.ingest(Observation.create(fast, 3.))
    from wowbot.agent.tooltip_quest import effective_mouseover
    assert effective_mouseover(world.state)["name"] == "Campfire"
    use = [p for p in __import__("wowbot.agent.planner", fromlist=["Planner"]).Planner(
        __import__("wowbot.agent.skills", fromlist=["SkillRegistry"]).SkillRegistry()).candidates(
        Goal.parse("Questelj", 3.), world, 3.) if p.skill == "OBJECT_USE"]
    assert use
    state = active("OBJECT_USE", use[0].parameters, world.state, deadline=100)
    clicked = ObjectUseSkill().begin(state, world.state)
    assert [(c.kind, c.button) for c in clicked.commands] == [("CLICK", "RIGHT")]
    # The cursor moves on: the old event no longer names what is under it.
    moved = {**fast, "frame_id": "fast:4", "monotonic_time": 4., "cursor_position": {"nx": .7, "ny": .3}}
    world.ingest(Observation.create(moved, 4.))
    assert effective_mouseover(world.state).get("name") is None
