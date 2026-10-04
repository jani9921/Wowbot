from wowbot.agent.skills import SkillRegistry


def test_combat_and_defend_allow_time_for_slow_lane_confirmation():
    # Live-observed 2026-09-14: COMBAT never once verified as SUCCESS across
    # a 36-minute session. Its success evidence -- SPELLCAST_SUCCEEDED events
    # and objective_progress() reading active_quests -- both come only from
    # the slow/paged snapshot (neither is in world.py's fast_keys). GATHER/
    # HERB/MINE already use 8s for this exact same slow-lane category; a bare
    # 3s window for COMBAT/DEFEND was inconsistent with that sibling
    # precedent and shorter than the multi-second paged-snapshot delays this
    # same session's telemetry showed repeatedly.
    registry = SkillRegistry()
    assert registry.contracts["COMBAT"].timeout >= 8.
    assert registry.contracts["DEFEND"].timeout >= 8.


def test_combat_contract_owns_a_bounded_full_fight_not_one_button_press():
    registry = SkillRegistry()
    assert registry.contracts["COMBAT"].expected == "target_dead"
    assert registry.contracts["COMBAT"].timeout == 45.
