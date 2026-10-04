from wowbot.agent.quest_offer_selector import QuestOfferSelector


def _row(quest_id, y):
    return {"quest_id": quest_id, "gossip_kind": "AVAILABLE", "x": .3, "y": y}


def test_single_offer_is_selected_deterministically():
    result = QuestOfferSelector().select([_row(42, .5), _row(42, .3)])
    assert not result.requires_explicit_selection
    assert result.reason == "only_offer"
    assert [item["y"] for item in result.rows] == [.3, .5]


def test_multiple_offer_ids_select_one_addon_confirmed_visible_row():
    selector = QuestOfferSelector()
    first = selector.select([_row(9, .2), _row(10, .4)])
    assert not first.requires_explicit_selection
    assert first.reason == "deterministic_visible_offer"
    assert [item["quest_id"] for item in first.rows] == [9]
    assert first.offered_quest_ids == ("10", "9")

    chosen = selector.select([_row(9, .2), _row(10, .4)], 9)
    assert chosen.reason == "requested_offer"
    assert [item["quest_id"] for item in chosen.rows] == [9]


def test_multiple_offers_can_be_scored_against_exact_objective_title():
    rows = [
        {**_row(9, .2), "title": "A Warrior's End"},
        {**_row(10, .4), "title": "Murloc Mania"},
    ]
    chosen = QuestOfferSelector().select(
        rows, objective={"objective_title": "MURLOC mania"})
    assert chosen.reason == "objective_matched_offer"
    assert [item["quest_id"] for item in chosen.rows] == [10]


def test_fuzzy_or_ambiguous_objective_evidence_remains_blocked():
    rows = [
        {**_row(9, .2), "title": "Murloc Mania"},
        {**_row(10, .4), "title": "Murloc Mania"},
    ]
    ambiguous = QuestOfferSelector().select(
        rows, objective={"objective_title": "Murloc Mania"})
    fuzzy = QuestOfferSelector().select(
        rows, objective={"objective_title": "Murloc"})
    assert not ambiguous.requires_explicit_selection
    assert not fuzzy.requires_explicit_selection
    assert len(ambiguous.rows) == len(fuzzy.rows) == 1
