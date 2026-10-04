"""Empty INSPECT hovers are not repeated while the view is unchanged.

Live 2026-10-03: one screen point was hovered 12 times in ~100 s and another
11 times, every hover empty; replaying the 13:47 telemetry with this rule
hovered (0.49, 0.42) once.
"""
from types import SimpleNamespace

from wowbot.agent.visual_inspection_planning import VisualInspectionPolicy


def _world(x=0., y=0., facing=0., result=None):
    return SimpleNamespace(
        state={"player_world_position": {"x": x, "y": y}, "orientation": facing},
        runtime_context={"last_result": result or {}})


def test_empty_hover_suppresses_the_point_until_the_view_changes():
    policy = VisualInspectionPolicy()
    policy._inspect_points = {"k1": {"x": .49, "y": .42, "view": (0., 0., 0.)}}
    failed = {"skill": "INSPECT", "action_id": "a1", "key": "k1",
              "reason": "expected_observation_missing"}
    policy._note_inspect_outcome(_world(result=failed), 10.)
    assert policy._recently_empty(_world(), .495, .425, 12.)
    assert not policy._recently_empty(_world(), .60, .42, 12.)            # elsewhere
    assert not policy._recently_empty(_world(x=5.), .49, .42, 12.)        # walked on
    assert not policy._recently_empty(_world(facing=.5), .49, .42, 12.)   # turned
    policy._note_inspect_outcome(_world(), 40.)                            # window over
    assert not policy._recently_empty(_world(), .49, .42, 40.)


def test_corpse_hover_suppresses_its_track_for_two_minutes():
    # Live 2026-10-04 09:20: the same looted Quilboar Geomancer corpse was
    # hovered seven times while the quest area went unexplored.
    policy = VisualInspectionPolicy()
    policy._inspect_points = {"k1": {"x": .40, "y": .55, "view": (0., 0., 0.), "track_id": "WORLD3D:77"}}
    done = {"skill": "INSPECT", "action_id": "a1", "key": "k1", "reason": "skill_postcondition_verified"}
    world = _world(result=done)
    world.state["mouseover"] = {"guid": "Creature-0-1-2-3-4-5", "name": "Quilboar Geomancer", "is_dead": True}
    policy._note_inspect_outcome(world, 10.)
    # The same track is skipped even after walking/turning; other points are not.
    assert policy._recently_empty(_world(x=8., facing=1.), .70, .30, 60., "WORLD3D:77")
    assert not policy._recently_empty(_world(x=8., facing=1.), .70, .30, 60., "WORLD3D:78")
    policy._note_inspect_outcome(_world(), 131.)
    assert not policy._recently_empty(_world(), .40, .55, 131., "WORLD3D:77")
