from wowbot.agent.quest_reward_selector import QuestRewardSelector, RewardPolicy


def rows():
    return [
        {"index": 1, "item_id": 100, "x": .2, "y": .3, "selected": False},
        {"index": 2, "item_id": 200, "x": .4, "y": .5, "selected": False},
    ]


def test_multiple_rewards_fail_closed_without_an_explicit_choice_policy():
    selected = QuestRewardSelector().select(rows())
    assert selected.choice is None
    assert selected.requires_explicit_policy
    assert selected.reason == "reward_selection_policy_required"


def test_exact_reward_item_or_index_selects_only_the_exported_row():
    selector = QuestRewardSelector()
    assert selector.select(rows(), item_id=200).choice["index"] == 2
    assert selector.select(rows(), choice_index=1).choice["item_id"] == 100
    assert selector.select(rows(), item_id=999).choice is None


def test_first_unambiguous_requires_an_explicit_policy_and_one_row():
    selector = QuestRewardSelector()
    one = [rows()[0]]
    assert selector.select(one).requires_explicit_policy
    assert selector.select(one, policy="FIRST_UNAMBIGUOUS").choice["index"] == 1
    assert selector.select(rows(), policy="FIRST_UNAMBIGUOUS").requires_explicit_policy


def test_missing_exported_coordinates_remain_non_actionable():
    selected = QuestRewardSelector().select([{"index": 1, "item_id": 100, "x": 0, "y": .3}], choice_index=1)
    assert selected.choice is None
    assert selected.reason == "reward_choice_coordinates_unavailable"


# DESIGN-062: RewardPolicy STAT_RULE/VALUE_RULE/TEST_FIRST_VALID/BLOCKED.

def _rows_with_item_level(*levels_usable):
    return [{"index": i + 1, "item_id": 100 + i, "x": .2, "y": .3,
             "item_level": level, "is_usable": usable}
            for i, (level, usable) in enumerate(levels_usable)]


def test_stat_rule_picks_the_highest_item_level_among_usable_rows():
    rows_ = _rows_with_item_level((10, True), (25, True), (99, False))
    selected = QuestRewardSelector().select(rows_, policy=RewardPolicy.STAT_RULE)
    assert selected.choice["index"] == 2
    assert selected.reason == "stat_rule_highest_item_level"


def test_stat_rule_fails_closed_on_tie_or_missing_data():
    tied = _rows_with_item_level((10, True), (10, True))
    assert QuestRewardSelector().select(tied, policy=RewardPolicy.STAT_RULE).choice is None
    no_level = [{"index": 1, "item_id": 100, "x": .2, "y": .3, "is_usable": True}]
    result = QuestRewardSelector().select(no_level, policy=RewardPolicy.STAT_RULE)
    assert result.choice is None and result.reason == "stat_rule_missing_item_level"


def test_value_rule_requires_caller_supplied_values_never_invents_them():
    selected = QuestRewardSelector().select(rows(), policy=RewardPolicy.VALUE_RULE)
    assert selected.choice is None
    assert selected.reason == "value_rule_requires_values"


def test_value_rule_picks_the_highest_supplied_value():
    selected = QuestRewardSelector().select(
        rows(), policy=RewardPolicy.VALUE_RULE, values={1: 5.0, 2: 9.0})
    assert selected.choice["index"] == 2
    assert selected.reason == "value_rule_highest_value"


def test_test_first_valid_deterministically_picks_the_first_row():
    selected = QuestRewardSelector().select(rows(), policy=RewardPolicy.TEST_FIRST_VALID)
    assert selected.choice["index"] == 1
    assert selected.reason == "test_first_valid"


def test_blocked_policy_never_selects_anything():
    selected = QuestRewardSelector().select(rows(), policy=RewardPolicy.BLOCKED)
    assert selected.choice is None
    assert selected.reason == "reward_selection_explicitly_blocked"


def test_auto_policy_prefers_usable_then_item_level_then_vendor_price():
    from wowbot.agent.quest_reward_selector import QuestRewardSelector
    rows = [{"index": 1, "item_id": 175170, "x": .05, "y": .66, "is_usable": True, "item_level": 10, "sell_price": 50},
            {"index": 2, "item_id": 175173, "x": .13, "y": .66, "is_usable": True, "item_level": 10, "sell_price": 61},
            {"index": 3, "item_id": 1, "x": .21, "y": .66, "is_usable": False, "item_level": 30, "sell_price": 999}]
    selection = QuestRewardSelector().select(rows, policy="AUTO")
    assert selection.choice["index"] == 2 and selection.reason == "auto_usable_item_level_sell_price"
    # Live 2026-10-04: no item level / price exported -> lowest usable row.
    bare = [{"index": 1, "x": .05, "y": .66, "is_usable": True}, {"index": 2, "x": .13, "y": .66, "is_usable": True}]
    assert QuestRewardSelector().select(bare, policy="AUTO").choice["index"] == 1
