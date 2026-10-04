"""Loot regressions from the live run on 2026-10-02 (Murloc Mania).

1. The Murloc Spearhunter loot succeeded (auto-loot, "First Aid Kit x2"),
   but LOOT was verified "not opened": the verifier looked for LOOT_OPENED
   while the addon emits LOOT_WINDOW_OPENED, and the loot events reached
   Python after the 3 s deadline.
2. COMBAT on the Murloc Watershaper failed on facing, the murloc still died,
   and its hovered corpse was never looted: no kill had been recorded.
"""
from types import SimpleNamespace

from wowbot.agent.world import WorldModel
from wowbot.verification.loot import LootVerifier

CORPSE = "Creature-0-3896-2175-13447-151268-0000BF9E2A"


def _event(sequence, kind, **payload):
    return {"sequence": sequence, "event_type": kind, "payload": payload,
            "source": "WOW_EVENT", "timestamp": 1790964236}


BEFORE = {"event_sequence": 13975,
          "events": [_event(13973, "UI_ERROR_MESSAGE"), _event(13975, "COMBAT_ENDED")]}


def test_retail_auto_loot_window_events_verify_the_loot():
    after = {"events": [*BEFORE["events"], _event(13976, "LOOT_WINDOW_OPENED"),
                        _event(13978, "LOOT_WINDOW_CLOSED")]}
    result = LootVerifier().evaluate(BEFORE, after, corpse_guid=CORPSE)
    assert result.success and "loot_window_cycled" in result.evidence


def test_live_loot_received_message_verifies_the_loot():
    after = {"events": [*BEFORE["events"], _event(13976, "LOOT_WINDOW_OPENED"),
                        _event(13979, "LOOT_WINDOW_CLOSED"),
                        _event(13980, "LOOT_RECEIVED", message="You receive loot: [First Aid Kit]x2")]}
    result = LootVerifier().evaluate(BEFORE, after, corpse_guid=CORPSE)
    assert result.success and "loot_received" in result.evidence


def test_events_from_before_the_click_never_verify_a_new_loot():
    stale = {"event_sequence": 13980,
             "events": [_event(13976, "LOOT_WINDOW_OPENED"), _event(13979, "LOOT_WINDOW_CLOSED"),
                        _event(13980, "LOOT_RECEIVED", message="old")]}
    result = LootVerifier().evaluate(stale, dict(stale), corpse_guid=CORPSE)
    assert not result.success
    # A window that only opened (not yet closed) is evidence, not success.
    opened = {"events": [*stale["events"], _event(13981, "LOOT_WINDOW_OPENED")]}
    partial = LootVerifier().evaluate(stale, opened, corpse_guid=CORPSE)
    assert not partial.success and "loot_ui_open" in partial.evidence


def _world_at(at):
    world = WorldModel()
    world.last_received = at
    return world


def test_a_unit_we_fought_is_our_corpse_even_after_combat_failed():
    world = _world_at(356906.0)
    world.set_runtime_context(active_skill={"skill": "COMBAT", "target_guid": CORPSE})
    # COMBAT failed on facing; the active skill and the target are gone...
    world.last_received = 356908.0
    world.set_runtime_context(active_skill=None)
    # ...the murloc died to auto-attack and was hovered dead 24-48 s later.
    assert world.corpse_is_combat_correlated(CORPSE, 356930.5)
    assert world.corpse_is_combat_correlated(CORPSE, 356954.1)
    assert not world.corpse_is_combat_correlated(CORPSE, 356906.0 + WorldModel.ENGAGED_CORPSE_SECONDS + 1.)
    # Units we never fought stay someone else's.
    assert not world.corpse_is_combat_correlated("Creature-0-1-2-3-4-OTHER", 356930.5)


def test_engagement_requires_a_combat_skill_on_a_creature():
    world = _world_at(10.)
    world.set_runtime_context(active_skill={"skill": "INTERACT", "target_guid": CORPSE})
    world.set_runtime_context(active_skill={"skill": "COMBAT", "target_guid": "Player-1-ABC"})
    world.set_runtime_context(active_skill=None)   # the fight is over
    assert not world.corpse_is_combat_correlated(CORPSE, 20.)
    assert not world.corpse_is_combat_correlated("Player-1-ABC", 20.)


AVATAR = {"source": "WORLD3D", "track_id": "WORLD3D:22", "detector_kind": "unknown_subject_candidate",
          "kind": "unknown_subject_candidate", "x": .498, "y": .446,
          "bbox": {"left": 404, "top": 223, "right": 437, "bottom": 303, "coordinate_space": "CLIENT_PIXELS"},
          "appearance": {"screen_anchored": True, "self_avatar_region_overlap": 1.0}}


def test_corpse_at_the_feet_is_never_bound_to_the_players_own_box():
    """Live 21:12: the dead murloc lay at the character's feet without a box of
    its own; its hover point was bound to the player's box (WORLD3D:22) and the
    first LOOT right-clicked the player.  The exact hover point is the corpse."""
    from wowbot.agent.combat_planning import CombatPlanningPolicy
    from wowbot.agent.models import Observation
    world = WorldModel()
    base = {"session_id": "s", "map_id": 1409, "player_present": True, "events": [],
            "event_sequence": 0, "actionbar": [], "active_quests": [], "visual_candidates": [AVATAR]}
    world.ingest(Observation.create({**base, "frame_id": "f:1", "timestamp": 1., "monotonic_time": 1.}, 1.))
    world.set_runtime_context(active_skill={"skill": "COMBAT", "target_guid": CORPSE})
    dead = {"guid": CORPSE, "name": "Murloc Watershaper", "is_dead": True, "npc_id": 151268}
    world.ingest(Observation.create({**base, "frame_id": "f:2", "timestamp": 2., "monotonic_time": 2.,
                                     "mouseover": dead, "cursor_position": {"nx": .509, "ny": .482},
                                     "cursor_sample_time": 2., "mouseover_sample_time": 2.}, 2.))
    assert world.mouseover_screen_anchors[CORPSE].get("track_id") is None
    world.mark_combat_kill(CORPSE, 3.)
    corpse = world.corpse_anchors[CORPSE]
    live, point, _near = CombatPlanningPolicy._corpse_view({"visual_candidates": [AVATAR]}, corpse)
    assert live is None and point == (.509, .482)
    # Even an anchor recorded before the fix never sends the click to the player.
    old = {**corpse, "track_id": "WORLD3D:22", "bbox": AVATAR["bbox"]}
    assert CombatPlanningPolicy._corpse_view({"visual_candidates": [AVATAR]}, old)[1] == (.509, .482)


def test_an_empty_corpse_is_released_after_one_try():
    from test_outcome_bookkeeping import attempt, setup
    from wowbot.agent.models import Outcome
    from wowbot.agent.outcome_bookkeeping import AttemptOutcomeBookkeeper
    for lootable, expected in ((False, [CORPSE]), (None, [])):
        goal, world, planner, failures, manager, loop, retries = setup()
        released = []
        world.note_loot_failure = lambda guid, at, limit=2: released.append(guid) if limit == 1 else None
        world.state = {"mouseover": {"guid": CORPSE, "is_dead": True, "lootable": lootable}}
        AttemptOutcomeBookkeeper.apply(
            attempt("LOOT", {"guid": CORPSE}), Outcome.FAILURE, "loot_ui_not_opened", 10.,
            goal=goal, world=world, planner=planner, failures=failures, failure_manager=manager,
            loop_guard=loop, retries=retries, failure_decision=None)
        assert released == expected
