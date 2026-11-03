"""Live 2026-10-31 02:09-02:12 (Fargodeep Mine entrance), offline evidence only.

The client's UI map flipped between Elwynn (37) and the mine (39) every few
seconds while the character stood at one spot of world 0.  Each flip was a
MAP_CONTEXT invalidation: it cancelled the MOVE and reset navigation (the
tracked own floor with it), and every in-flight own movement packet was
dropped with the old transport nonce (see test_packet_agent_bridge).  A UI-map
step inside one known world without a jump is UI_MAP: only UI-map views are
refreshed.  A world change, a jump or an unknown world stays MAP_CONTEXT.
"""
from dataclasses import replace

from wowbot.runtime import InvalidationEvent, StateInvalidationPolicy


def state(map_id, *, x=-9826., y=198., instance=0, loading=False):
    position = {"x": x, "y": y, "z": None, "coordinate_space": "WORLD_YARDS"}
    if instance is not None:
        position["instance_id"] = instance
    return {"map_id": map_id, "loading": loading, "is_dead": False, "phase_id": 1, "floor_id": None,
            "in_vehicle": False, "active_quests": [], "player_world_position": position}


def events(before, after):
    policy = StateInvalidationPolicy()
    return policy.detect(policy.context(before), policy.context(after))


def test_a_same_world_ui_map_flip_at_one_spot_is_no_context_change():
    assert events(state(37), state(39)) == (InvalidationEvent.UI_MAP,)
    assert events(state(39), state(37, x=-9824.5)) == (InvalidationEvent.UI_MAP,)
    decision = StateInvalidationPolicy().decision(InvalidationEvent.UI_MAP)
    assert not (decision.cancel_active or decision.reset_navigation or decision.reset_commitment
                or decision.reset_camera or decision.invalidate_objective)
    assert decision.reset_map_search                      # the UI-map-derived search view is refreshed


def test_a_world_change_a_jump_or_an_unknown_world_stays_a_map_context_change():
    assert InvalidationEvent.MAP_CONTEXT in events(state(37), state(39, instance=1))
    assert InvalidationEvent.MAP_CONTEXT in events(state(37), state(39, x=-9600.))
    assert InvalidationEvent.MAP_CONTEXT in events(state(37, instance=None), state(39, instance=None))
    assert InvalidationEvent.MAP_CONTEXT in events(state(37), state(39, loading=True))


def test_a_timed_out_position_wait_may_tap_again_but_bounded(monkeypatch):
    """After one unanswered tap the next MOVEs waited 3 s each without a tap."""
    from test_position_before_route_20261030 import configured, request, standing
    nav, plans = configured(monkeypatch)
    taps, at = [], 10.
    for attempt in range(5):
        nav.start_request(replace(request(), request_id=f"r{attempt}"), standing(at), at)
        taps.append(nav.command(standing(at), f"probe-{attempt}", at))
        result = nav.observe(standing(at+3.1), f"timeout-{attempt}", at+3.1)
        assert result.terminal and result.reason == "server_position_probe_timeout"
        at += 3.5
    assert [len(tap) for tap in taps] == [1, 1, 1, 1, 0]        # 3 releases per 30 s window
    assert plans == []
    nav.start_request(replace(request(), request_id="later"), standing(at+30.), at+30.)
    assert nav.command(standing(at+30.), "probe-later", at+30.)  # the window has passed


def test_the_ui_map_step_applies_only_its_declared_resets():
    from wowbot.agent.world import WorldModel
    calls = []
    runtime = {name: (lambda reason, name=name: calls.append(name)) for name in (
        "invalidate_objective", "reset_navigation", "reset_camera", "reset_commitment", "reset_map_search")}
    StateInvalidationPolicy().apply(InvalidationEvent.UI_MAP, WorldModel(), runtime)
    assert calls == ["reset_map_search"]
