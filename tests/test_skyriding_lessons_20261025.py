"""The Skyriding lessons flown by SkyridingControl in a flight model.

User 2026-10-25: "how to dive/glide with your dragon, how to use momentum --
these we have to do now".  Ring and target positions are the client DB2
scene paths (data/client_reference.sqlite3); the user's own glide runs were
credited within 10 yd of them.  The model is calibrated on the agent's own
77345 course (live 17:26-17:30): turn 2.35 rad/s, pitch 1.4 rad/s, packets
on key changes, delayed delivery and credits.
"""
import math

import pytest

from wowbot.agent.skyriding_control import SkyridingControl

from skyriding_sim import SkyridingSim
from wowbot.quests.client_catalog import ClientCatalog
from wowbot.quests.scene_path_planning import course_path

COURSES = ClientCatalog().courses()
START = (1814.5, 51.2, 312.9)            # beside Lord Andestrasz, where the user mounted


def fly(quest_id, seconds=None, **sim_options):
    course = COURSES[quest_id]
    points = [*course["rings"], course["target"]]
    first = points[0]
    facing = math.atan2(first[1]-START[1], first[0]-START[0]) % math.tau
    sim = SkyridingSim(START, facing, points, **sim_options)
    control = SkyridingControl(course_path(course))
    limit = seconds or 25. + 12.*len(points)
    while sim.t < limit:
        state = sim.state(quest_id, len(course["rings"]))
        verdict, reason = control.assess(state, sim.t)
        if verdict != "MOVING":
            return sim, verdict, reason
        for command in control.commands(state, sim.t):
            sim.apply(command)
        sim.run_tick()
    return sim, "TIMEOUT", control.last_reason


def misses(sim):
    return {index: round(min((d for i, d in sim.closest if i == index), default=math.inf), 1)
            for index in range(len(sim.course))}


@pytest.mark.parametrize("quest_id", ["65118", "65120", "65133", "77345"])
def test_every_ring_and_the_target_are_passed_in_order(quest_id):
    sim, verdict, reason = fly(quest_id)
    assert sim.passed == len(sim.course), (verdict, reason, misses(sim))
    assert verdict == "ARRIVED", reason


@pytest.mark.parametrize("quest_id", ["65118", "65133", "77345"])
def test_the_old_medium_tick_feedback_delay_no_longer_makes_it_orbit(quest_id):
    """Live 17:28: packets reached the loop 0.3-0.6 s late and it overshot every
    heading by ~1.3 rad.  The lease-ledger prediction absorbs that delay."""
    sim, verdict, reason = fly(quest_id, delivery=.45, credit_delay=1.)
    assert sim.passed == len(sim.course) and verdict == "ARRIVED", (verdict, reason, misses(sim))


@pytest.mark.parametrize("quest_id", ["65118", "65120", "65133"])
def test_a_heartbeat_only_glide_is_dead_reckoned(quest_id):
    """Without key changes the client sends a packet every ~0.5 s (2 Hz)."""
    sim, verdict, reason = fly(quest_id, packet_gap=.5, heartbeat=.5, delivery=.12)
    assert sim.passed == len(sim.course) and verdict == "ARRIVED", (verdict, reason, sim.passed)


def test_the_8_ring_course_is_flown_without_circling():
    """77345 took the agent 116 s live with loops around rings 4-5 and 6-7."""
    sim, verdict, _reason = fly("77345")
    assert verdict == "ARRIVED"
    gaps = [later-earlier for earlier, later in zip(sim.passed_at, sim.passed_at[1:])]
    assert max(gaps) < 12., gaps
