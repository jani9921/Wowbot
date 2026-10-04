from wowbot.agent.collect_strategy import CollectStrategy, CollectStrategyTracker


def test_unknown_objective_starts_with_unknown_best_guess():
    tracker = CollectStrategyTracker()
    assert tracker.best_guess("q1", "o1") is CollectStrategy.UNKNOWN


def test_spec_worked_example_kill_then_loot_progress_strengthens_mob_loot():
    tracker = CollectStrategyTracker()
    # kill succeeds -> objective does not progress: no belief update for KILL
    # since kill was never a candidate collect strategy on its own.
    # corpse lootable -> loot -> objective increases -> strengthen MOB_LOOT.
    guess = tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT,
                                   objective_progressed=True)
    assert guess is CollectStrategy.MOB_LOOT
    assert tracker.confidence_of("q1", "o1", CollectStrategy.MOB_LOOT) > 0.0


def test_loot_succeeds_but_no_progress_weakens_and_forces_reevaluation():
    tracker = CollectStrategyTracker()
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT, objective_progressed=True)
    before = tracker.confidence_of("q1", "o1", CollectStrategy.MOB_LOOT)
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT, objective_progressed=False)
    after = tracker.confidence_of("q1", "o1", CollectStrategy.MOB_LOOT)
    assert after < before


def test_repeated_success_increases_confidence_but_never_past_one():
    tracker = CollectStrategyTracker(strengthen_step=0.6)
    for _ in range(5):
        tracker.record_outcome("q1", "o1", strategy=CollectStrategy.GROUND_OBJECT,
                               objective_progressed=True)
    assert tracker.confidence_of("q1", "o1", CollectStrategy.GROUND_OBJECT) == 1.0


def test_confidence_never_goes_below_zero():
    tracker = CollectStrategyTracker(weaken_step=0.9)
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.DIRECT_INTERACT, objective_progressed=False)
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.DIRECT_INTERACT, objective_progressed=False)
    assert tracker.confidence_of("q1", "o1", CollectStrategy.DIRECT_INTERACT) == 0.0


def test_best_guess_tracks_whichever_strategy_currently_has_the_strongest_evidence():
    tracker = CollectStrategyTracker()
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT, objective_progressed=True)
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.QUEST_ITEM_MECHANIC, objective_progressed=True)
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.QUEST_ITEM_MECHANIC, objective_progressed=True)
    assert tracker.best_guess("q1", "o1") is CollectStrategy.QUEST_ITEM_MECHANIC


def test_objectives_are_tracked_independently():
    tracker = CollectStrategyTracker()
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT, objective_progressed=True)
    assert tracker.best_guess("q1", "o2") is CollectStrategy.UNKNOWN


def test_clear_resets_the_belief_for_that_objective():
    tracker = CollectStrategyTracker()
    tracker.record_outcome("q1", "o1", strategy=CollectStrategy.MOB_LOOT, objective_progressed=True)
    tracker.clear("q1", "o1")
    assert tracker.best_guess("q1", "o1") is CollectStrategy.UNKNOWN
