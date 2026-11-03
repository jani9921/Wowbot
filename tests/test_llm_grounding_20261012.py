"""User 2026-10-12: make the local LLM smarter without a bigger model --
(1) TDB facts in the question, (2) a thinking model only for doubtful answers,
(3) the player's own verified objective -> action pairs as examples,
(4) a measurable benchmark against Exile's Reach gold labels."""
from pathlib import Path
import json
import sys
import time

from wowbot.agent.semantic_advisor import (SemanticAdvisor, doubtful, parse_json_answer,
                                           quest_requests, similar_examples, tdb_ender_names,
                                           tdb_objective_facts, turnin_request, update_world,
                                           validate_quest, validate_turnin, verified_action)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import semantic_benchmark  # noqa: E402

REFERENCE = {
    "objectives": [
        {"description": "Trapped Expedition Member rescued from cocoons", "credit_kind": "GAMEOBJECT",
         "object_template": {"name": "Thick Cocoon"}},
        {"description": "Re-Sizer v9.0.1 tested on Wandering Boars", "credit_kind": "CREATURE_CREDIT",
         "named_creatures": [{"entry": 156716, "name": "Wandering Boar"}]}],
    "turnin_candidates": [{"name": "Lady Jaina Proudmoore", "source": "TDB_REFERENCE"}]}
QUEST = {"quest_id": 56034, "title": "Re-sizing the Situation", "objectives": [
    {"description": "0/3 Re-Sizer v9.0.1 tested on Wandering Boars"}]}


def _settle(advisor):
    for _ in range(300):
        advisor.poll()
        if advisor.future is None and not advisor.queue:
            return
        time.sleep(.01)


def test_tdb_facts_are_part_of_the_question_and_accepted_names():
    facts = tdb_objective_facts(REFERENCE)
    assert facts["re-sizer v9.0.1 tested on wandering boars"] == {
        "kind": "CREATURE_CREDIT", "names": ["Wandering Boar"]}
    [(key, payload)] = quest_requests(QUEST, {}, facts=facts)
    assert payload["facts"] == {"o1": {"kind": "CREATURE_CREDIT", "names": ["Wandering Boar"]}}
    assert key != quest_requests(QUEST, {})[0][0]
    # A database name absent from the quest prose is still a valid answer.
    cocoon = {"quest_id": 55639, "title": "Who Lurks in the Pit", "objectives": [
        {"description": "Trapped Expedition Member rescued from cocoons"}]}
    [(_, payload)] = quest_requests(cocoon, {}, facts=facts)
    result = validate_quest(payload, {"o1": {"action": "INTERACT_OBJECT", "target": "Thick Cocoon"}})
    assert result["objectives"]["trapped expedition member rescued from cocoons"]["target"] == "Thick Cocoon"


def test_turnin_question_offers_the_database_enders():
    enders = tdb_ender_names(REFERENCE)
    key, payload = turnin_request(QUEST, {"description": "Report back."}, enders)
    assert payload["ender_candidates"] == ["Lady Jaina Proudmoore"]
    assert validate_turnin(payload, {"turn_in_to": "Lady Jaina Proudmoore"})["name"] == "Lady Jaina Proudmoore"


def test_doubtful_answers_are_the_unknown_the_nameless_and_the_fact_clashes():
    facts = tdb_objective_facts(REFERENCE)
    [(_, payload)] = quest_requests(QUEST, {}, facts=facts)
    good = validate_quest(payload, {"o1": {"action": "USE_ITEM_ON_TARGET", "target": "Wandering Boars"}})
    assert not doubtful("quest", payload, good)
    nameless = validate_quest(payload, {"o1": {"action": "USE_ITEM_ON_TARGET", "target": None}})
    assert doubtful("quest", payload, nameless)
    clash = validate_quest(payload, {"o1": {"action": "COLLECT", "target": "Wandering Boars"}})
    assert doubtful("quest", payload, clash)
    assert doubtful("quest", payload, validate_quest(payload, {"o1": {"action": "SMASH"}}))
    _, turnin = turnin_request(QUEST, {"description": "x"}, ["Lady Jaina Proudmoore"])
    assert doubtful("turnin", turnin, {"name": None, "giver": False})
    assert not doubtful("turnin", turnin, {"name": "Lady Jaina Proudmoore", "giver": False})


def test_doubtful_answer_is_reasked_once_with_the_thinking_model(tmp_path):
    calls = []

    def transport(system, payload, config):
        calls.append((config.get("model"), config.get("think")))
        if config.get("model") == "thinker":
            return {"o1": {"action": "USE_ITEM_ON_TARGET", "target": "Wandering Boars", "item": "Re-Sizer v9.0.1"}}
        return {"o1": {"action": "UNKNOWN"}}

    advisor = SemanticAdvisor({"enabled": True, "model": "fast", "escalation_model": "thinker"},
                              tmp_path / "cache.json", transport=transport)
    [(key, payload)] = quest_requests(QUEST, {}, facts=tdb_objective_facts(REFERENCE))
    advisor.ask("quest", key, payload)
    _settle(advisor)
    assert calls == [("fast", None), ("thinker", True)]
    entry = advisor.cache[key]
    assert entry["model"] == "thinker" and entry["escalated"] is True
    assert entry["result"]["objectives"]["re-sizer v9.0.1 tested on wandering boars"]["action"] == "USE_ITEM_ON_TARGET"
    assert advisor.metrics["escalated"] == 1


def test_no_escalation_without_a_configured_model(tmp_path):
    calls = []
    advisor = SemanticAdvisor({"enabled": True}, tmp_path / "cache.json",
                              transport=lambda s, p, c: calls.append(1) or {"o1": {"action": "UNKNOWN"}})
    [(key, payload)] = quest_requests(QUEST, {})
    advisor.ask("quest", key, payload)
    _settle(advisor)
    assert len(calls) == 1


def test_thinking_model_answers_are_parsed():
    assert parse_json_answer('<think>boars... re-sizer</think>\n{"o1": {"action": "KILL"}}') == {
        "o1": {"action": "KILL"}}
    assert parse_json_answer('Answer: {"turn_in_to": "GIVER"} done') == {"turn_in_to": "GIVER"}


def test_verified_examples_come_from_the_players_own_successes():
    assert verified_action("COMBAT") == "KILL"
    assert verified_action("COMBAT", in_vehicle=True) == "USE_VEHICLE_ABILITY"
    assert verified_action("INTERACT", in_vehicle=True) == "RIDE_VEHICLE"
    assert verified_action("USE_ON_TARGET") == "USE_ITEM_ON_TARGET"
    examples = [{"objective": "re-sizer v9.0.1 tested on wandering boars", "action": "USE_ITEM_ON_TARGET"},
                {"objective": "quilboar slain", "action": "KILL"}]
    picked = similar_examples("Re-Sizer v9.0.1 tested on Wild Boars", examples)
    assert picked == [{"objective": "re-sizer v9.0.1 tested on wandering boars", "action": "USE_ITEM_ON_TARGET"}]
    assert similar_examples("Ride the Giant Boar", examples) == []


class _Memory:
    def verified_progress(self):
        return [{"description": "3/3 Re-Sizer v9.0.1 tested on Wandering Boars", "skill": "USE_ON_TARGET",
                 "in_vehicle": 0, "total": 3}]


def test_update_world_sends_facts_enders_and_examples():
    seen = []
    advisor = SemanticAdvisor({"enabled": True},
                              transport=lambda s, p, c: seen.append(p) or {})
    model = type("Model", (), {})()
    model.state = {"active_quests": [{**QUEST, "special_item": {"item_id": 170557}}],
                   "reference_knowledge": {"quests": {"56034": REFERENCE}}}
    model.quest_creature_memory = _Memory()
    update_world(advisor, model, 1.)
    task, key, payload, overrides = advisor.queue[0]
    assert task == "quest" and payload["facts"]["o1"]["names"] == ["Wandering Boar"]
    assert payload["verified_examples"][0]["action"] == "USE_ITEM_ON_TARGET"
    # The examples do not change the question's cache key.
    assert key == quest_requests(QUEST, {}, facts=tdb_objective_facts(REFERENCE))[0][0]


def test_benchmark_scores_the_gold_labels_with_a_fake_model():
    gold = json.loads((Path(__file__).resolve().parents[1] / "data" / "semantic_benchmark"
                       / "exiles_reach_gold.json").read_text(encoding="utf-8"))
    from wowbot.agent.semantic_advisor import OBJECTIVE_ACTIONS
    for quest in gold["quests"]:
        for objective in quest["objectives"]:
            assert set(objective["action"]) <= set(OBJECTIVE_ACTIONS)
    cases = [{"quest_id": 56034, "title": "Re-sizing the Situation", "texts": {"description": "Test it."},
              "objectives": gold["quests"][-3]["objectives"], "facts": tdb_objective_facts(REFERENCE),
              "enders": ["Lady Jaina Proudmoore"], "turnin": True}]
    assert cases[0]["objectives"][0]["text"].startswith("Re-Sizer")

    def fake(system, payload, config):
        if "ender_candidates" in payload:
            return {"turn_in_to": "Lady Jaina Proudmoore"}
        return {"o1": {"action": "USE_ITEM_ON_TARGET", "target": "Wandering Boars"}}
    summary = semantic_benchmark.run_tdb_cases(cases, {}, use_facts=True, transport=fake, show=lambda *_: None)
    assert summary["accuracy"] == {"action": "1/1", "target": "1/1", "turnin": "1/1"}


def test_a_missing_escalation_model_does_not_pause_the_advisor(tmp_path):
    def transport(system, payload, config):
        if config.get("model") == "thinker":
            raise RuntimeError("model 'thinker' not found, try pulling it first")
        return {"o1": {"action": "UNKNOWN"}}
    advisor = SemanticAdvisor({"enabled": True, "model": "fast", "escalation_model": "thinker"},
                              tmp_path / "cache.json", transport=transport)
    [(key, payload)] = quest_requests(QUEST, {})
    advisor.ask("quest", key, payload)
    _settle(advisor)
    assert advisor.cache[key]["model"] == "fast"          # first answer kept
    assert advisor.status != "unavailable" and advisor.unavailable_until == 0.
    assert advisor.metrics["escalation_failed"] == 1
