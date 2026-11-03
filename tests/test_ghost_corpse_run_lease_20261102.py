"""Live 2026-11-01 (Westfall, two deaths): the corpse runs took 253 s for 900 yd.

The ghost ran at 9.1 yd/s, but the shared fast-control safety gate treated the
ghost *state* as a death transition: every 30 Hz sample stopped W and handed
the tick back, so the ghost moved stop-go at ~3.5 yd/s.  Only the edge
(release / resurrect) is a transition."""
from wowbot.agent.parallel_view import control_safety


def sample(**extra):
    return {"session_id": "s", "monotonic_time": 10., **extra}


def test_a_corpse_run_started_as_a_ghost_keeps_its_movement_lease():
    base = {"session_id": "s", "is_ghost": True, "is_dead": False}
    assert control_safety(base, sample(is_ghost=True, is_dead=False), 10., 10.) is None
    assert control_safety(base, sample(), 10., 10.) is None                  # FAST without the flag


def test_the_release_and_resurrect_edges_and_death_still_stop():
    alive = {"session_id": "s", "is_ghost": False}
    assert control_safety(alive, sample(is_ghost=True), 10., 10.) == "death_transition"
    assert control_safety({"session_id": "s"}, sample(is_ghost=True), 10., 10.) == "death_transition"
    ghost = {"session_id": "s", "is_ghost": True}
    assert control_safety(ghost, sample(is_ghost=False), 10., 10.) == "death_transition"
    assert control_safety(alive, sample(is_dead=True), 10., 10.) == "death_transition"
