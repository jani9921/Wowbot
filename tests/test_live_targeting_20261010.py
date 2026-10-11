"""Live 2026-10-10 17:22 (new character, Murloc Mania 55122)."""
from types import SimpleNamespace

from wowbot.agent import quest_giver_evidence as evidence
from wowbot.agent.target_planning import _dead_or_spent

JAINA = "Creature-0-4249-2175-14921-156626-00004A4F8E"
SPEARHUNTER = "Creature-0-4249-2175-14921-150228-00004A578B"


def test_a_corpse_under_the_cursor_is_never_an_enemy_target():
    """17:25:05: right after the loot the cursor rested on the corpse and the
    enemy-mouseover TARGET selected it; the agent waited until ESC."""
    world = SimpleNamespace(owned_corpse_guids={}, looted_corpse_guids={})
    alive = {"guid": SPEARHUNTER, "is_attackable": True}
    assert not _dead_or_spent(world, alive)
    # A present-but-empty "dead" key must not hide the FAST lane's is_dead.
    assert _dead_or_spent(world, {**alive, "dead": None, "is_dead": True})
    assert _dead_or_spent(world, {**alive, "health": 0})
    world.looted_corpse_guids[SPEARHUNTER] = 1.
    assert _dead_or_spent(world, alive)
    world = SimpleNamespace(_model=SimpleNamespace(owned_corpse_guids={SPEARHUNTER: 1.},
                                                   looted_corpse_guids={}))
    assert _dead_or_spent(world, alive)


def _state(complete: bool) -> dict:
    return {"active_quests": [{"quest_id": 55122, "is_complete": complete, "objectives": [
                {"description": "2/6 First Aid Kits recovered from defeated Murlocs",
                 "current": 6 if complete else 2, "required": 6}]}],
            "reference_knowledge": {"quests": {"55122": {"quest_roles": [
                {"npc_id": 156626, "quest_id": 55122, "role": "QUEST_STARTER"},
                {"npc_id": 156626, "quest_id": 55122, "role": "QUEST_ENDER"}]}}},
            "mouseover": {"guid": JAINA, "name": "Lady Jaina Proudmoore", "is_attackable": False},
            "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                      "x": -399.7, "y": -2594.7}}


def test_the_grey_question_mark_of_an_unfinished_quest_does_not_attract(monkeypatch):
    """17:25:37: a symbol over Jaina (the detector cannot tell the grey "?"
    of the unfinished quest from a yellow one) made her relevant at 2/6; the
    agent left the murlocs and walked to her."""
    monkeypatch.setattr(evidence, "npc_shows_quest_symbol", lambda state, guid: True)
    unfinished = _state(False)
    assert evidence.ender_of_unfinished_quest_only(unfinished, JAINA)
    assert not evidence.friendly_npc_relevant(unfinished, JAINA, {"COLLECT"},
                                              unit_name="Lady Jaina Proudmoore")
    finished = _state(True)
    assert not evidence.ender_of_unfinished_quest_only(finished, JAINA)
    assert evidence.friendly_npc_relevant(finished, JAINA, {"COLLECT"},
                                          unit_name="Lady Jaina Proudmoore")
    # A symbol over an NPC who ends none of our quests still counts ("!").
    other = "Creature-0-4249-2175-14921-156607-00004A4F8F"
    assert evidence.friendly_npc_relevant(unfinished, other, {"COLLECT"}, unit_name="Alaria")


AUSTIN = "Creature-0-4249-2175-14921-156610-00004A4F8E"


def _first_aid_world(target):
    from test_agent_core import state, world
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    quest = {"quest_id": 54951, "title": "Emergency First Aid", "is_complete": False,
             "special_item": {"item_id": 168410, "item_name": "First Aid Kit",
                              "source": "QUEST_LOG_SPECIAL_ITEM"},
             "objectives": [{"objective_id": "54951:2", "type": "USE_ITEM", "raw_type": "monster",
                             "description": "0/1 First Aid Kit used on Austin Huxworth",
                             "item_id": 168410, "current": 0, "required": 1}]}
    reference = {"quests": {"54951": {"quest_roles": [], "pois": [], "spawn_candidates": [
        {"role": "OBJECTIVE", "entity_kind": "CREATURE", "entry": 156610, "objective_id": "54951:2",
         "world_map_id": 2175, "x": -300., "y": -2560., "z": 10., "context": {}, "spawn_id": 5}]}}}
    value = WorldModel()
    value.ingest(Observation.create(state(
        active_quests=[quest], map_id=1409, player_world_position=world(-380, -2620),
        target=target, reference_knowledge=reference,
        inventory={"items": [{"item_id": 168410, "bag": 0, "slot": 3, "is_locked": False,
                              "is_quest_item": True}], "free_slots": 10}), 1))
    return value


def _ranked(world):
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    return sorted(Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1),
                  key=lambda item: -item.priority)


def test_emergency_first_aid_uses_the_kit_on_the_selected_soldier():
    """Live 2026-10-10 17:37: Austin Huxworth was selected, yet a priority-96
    TDB objective MOVE won and no executable item use was proposed (ASSIST
    cannot press an Interact-key special item); object-cue searches followed."""
    selected = _ranked(_first_aid_world(
        {"guid": AUSTIN, "name": "Austin Huxworth", "attackable": False, "dead": False}))
    best = selected[0]
    assert best.skill == "USE_ON_TARGET" and best.parameters["activation_source"] == "INTERACT_KEY"
    assert best.parameters["guid"] == AUSTIN
    assert all(item.priority < best.priority for item in selected if item.skill == "MOVE")
    # Nothing selected: the TDB spawn of the objective NPC is the way there.
    alone = _ranked(_first_aid_world(None))
    assert alone[0].skill == "MOVE" and alone[0].parameters.get("source") == "TDB_SPAWN"
    # "used on <NPC>" never starts a world-object search for the kit.
    assert not any(item.parameters.get("purpose") == "SEARCH_LOCAL_OBJECT"
                   for item in selected + alone)


def _marker(x, y):
    return {"x": x, "y": y, "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "z_known": False, "source": "MINIMAP_TARGET_MARKER", "marker_colour": "GREEN"}


def test_an_off_screen_selected_unit_is_walked_to_by_its_minimap_marker():
    """User 2026-10-11: a selected unit is drawn on the minimap; when it is
    not seen in 3D, walk to that marker (friendly and hostile alike)."""
    from wowbot.agent.target_marker_approach import minimap_target_move
    state = {"map_id": 1409, "player_world_position": {"coordinate_space": "WORLD_YARDS",
                                                        "instance_id": 2175, "x": 0., "y": 0.}}
    far = {"guid": "Creature-0-1-2175-1-156860-01", "world_position": _marker(40., 0.)}
    move = minimap_target_move(state, far, min_distance=10., stop_distance=4.5, priority=93,
                               reason="test")
    assert move.skill == "MOVE" and move.parameters["purpose"] == "APPROACH_SELECTED_TARGET"
    assert (move.parameters["x"], move.parameters["target_guid"]) == (40., far["guid"])
    assert move.parameters["require_navmesh"] is True
    near = {**far, "world_position": _marker(6., 0.)}
    assert minimap_target_move(state, near, min_distance=10., stop_distance=4.5, priority=93,
                               reason="test") is None
    on_screen = {**far, "screen_position": {"x": .5, "y": .5}}
    assert minimap_target_move(state, on_screen, min_distance=10., stop_distance=4.5, priority=93,
                               reason="test") is None
    api = {**far, "world_position": {**_marker(40., 0.), "source": "QUEST_API"}}
    assert minimap_target_move(state, api, min_distance=10., stop_distance=4.5, priority=93,
                               reason="test") is None


def test_the_marker_walk_ends_when_the_unit_shows_up_or_changes():
    from types import SimpleNamespace
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.models import Proposal
    guid = "Creature-0-1-2175-1-156860-01"
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "marker", {
        "purpose": "APPROACH_SELECTED_TARGET", "target_guid": guid, "x": 40., "y": 0.}))
    hidden = {"target": {"guid": guid}}
    assert movement_visual_interrupt(attempt, hidden) is None
    seen = {"target": {"guid": guid, "screen_position": {"x": .5, "y": .5}}}
    assert movement_visual_interrupt(attempt, seen)["reason"] == "selected_target_on_screen"
    other = {"target": {"guid": "Creature-0-1-2175-1-1-02"}}
    assert movement_visual_interrupt(attempt, other)["reason"] == "selected_target_changed"
