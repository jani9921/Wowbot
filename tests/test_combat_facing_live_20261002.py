"""Combat facing without nameplates (live 2026-10-02, Murloc Watershaper).

Retail 12 exposes neither the target's screen position nor nameplate
positions, so the combat visual follow and the facing recovery never had a
bearing live: COMBAT failed "facing the wrong way" in 1.5 s and the agent
then WAITed ~14 s while the murloc kept hitting it.
"""
from wowbot.agent.models import Observation, Outcome
from wowbot.agent.world import WorldModel
from test_outcome_bookkeeping import attempt, setup
from wowbot.agent.outcome_bookkeeping import AttemptOutcomeBookkeeper
from types import SimpleNamespace

MURLOC = "Creature-0-3896-2175-13447-150229-00003FF1A8"


def _state(at, x=None):
    return {"session_id": "s", "frame_id": f"f:{at}", "timestamp": at, "monotonic_time": at,
            "map_id": 1409, "player_present": True, "is_in_combat": True,
            "target": {"guid": MURLOC, "attackable": True, "dead": False},
            "events": [], "event_sequence": 0, "actionbar": [], "active_quests": [],
            "visual_candidates": ([{"source": "WORLD3D", "track_id": "WORLD3D:7",
                                    "detector_kind": "unknown_subject_candidate", "x": x, "y": .42,
                                    "observed_at": at, "bbox": {"x": 1}, "bbox_height_fraction": .2}]
                                  if x is not None else [])}


def test_selected_target_follows_the_hovered_track_without_nameplates():
    world = WorldModel()
    world.ingest(Observation.create(_state(1., .70), 1.))
    assert (world.state["target"]).get("screen_position") is None    # nothing bound yet
    # TARGET clicked the hovered box: the addon mouseover GUID was bound to it.
    world.mouseover_screen_anchors[MURLOC] = {"guid": MURLOC, "x": .6, "y": .45,
                                              "track_id": "WORLD3D:7", "observed_at": 1.}
    world.ingest(Observation.create(_state(2., .72), 2.))
    screen = world.state["target"]["screen_position"]
    assert (screen["x"], screen["source"], screen["track_id"]) == (.72, "BOUND_WORLD3D_TRACK", "WORLD3D:7")
    assert screen["sample_time"] == 2.
    # The binding is remembered after the hover anchor expires.
    world.mouseover_screen_anchors.clear()
    world.ingest(Observation.create(_state(3., .80), 3.))
    assert world.state["target"]["screen_position"]["x"] == .80
    # Behind the character: no current box, no invented position.
    world.ingest(Observation.create(_state(4.), 4.))
    assert world.state["target"].get("screen_position") is None


def _apply(reason, live):
    goal, world, planner, failures, manager, loop, retries = setup({"guid": MURLOC})
    world.state = live
    value = attempt("COMBAT", {"guid": MURLOC})
    AttemptOutcomeBookkeeper.apply(
        value, Outcome.FAILURE, reason, 10., goal=goal, world=world, planner=planner,
        failures=failures, failure_manager=manager, loop_guard=loop, retries=retries,
        failure_decision=SimpleNamespace(retry_allowed=True, backoff_seconds=7.))
    return planner.blocked_until[value.proposal.key]


def test_facing_failure_while_still_fighting_retries_at_once():
    fighting = {"is_in_combat": True, "target": {"guid": MURLOC, "attackable": True, "dead": False}}
    assert _apply("facing_failed", fighting) == 10.5
    # Other failures, or after the fight, keep the failure manager's backoff.
    assert _apply("spell_not_ready", fighting) == 17.
    assert _apply("facing_failed", {"is_in_combat": False, "target": {}}) == 17.


def test_kill_of_a_tracked_target_leaves_a_lootable_corpse_anchor():
    """Live 20:46:19: the Spearhunter died, ownership was recorded, but no
    corpse position existed (hover point expired by movement, no nameplate
    box), so LOOT was never proposed.  The followed track's last box is it."""
    world = WorldModel()
    world.ingest(Observation.create(_state(1., .70), 1.))
    world.mouseover_screen_anchors[MURLOC] = {"guid": MURLOC, "x": .6, "y": .45,
                                              "track_id": "WORLD3D:7", "observed_at": 1.}
    world.ingest(Observation.create(_state(2., .66), 2.))
    world.mouseover_screen_anchors.clear()          # moved: the hover point expired
    world.mark_combat_kill(MURLOC, 3.)
    corpse = world.corpse_anchors[MURLOC]
    assert corpse["ownership_confirmed"] is True and corpse["x"] == .66
    assert corpse["anchor_source"] == "TARGET_TRACK_AT_DEATH"
