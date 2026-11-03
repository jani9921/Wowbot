"""Rolling high-level plans use live credit and existing execution only."""
from copy import deepcopy
from types import SimpleNamespace
import threading
import time

import pytest

from wowbot.agent.agenda_advice import request, validate
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Goal, Mode, Observation, Proposal
from wowbot.agent.quest_agenda import QuestAgenda
from wowbot.agent.semantic_advisor import SemanticAdvisor
from wowbot.agent.world import WorldModel


def quest(qid, complete=False):
    return {"quest_id": qid, "title": f"Quest {qid}", "is_complete": complete,
            "objectives": [{"objective_id": f"{qid}:0", "type": "KILL", "description": "Creatures slain",
                            "is_complete": complete, "current": 1 if complete else 0, "total": 1}]}


def world(quests=None, *, x=0., y=0., at=10., work_z=10.):
    quests = quests if quests is not None else [quest(1), quest(2), quest(3)]
    references, locations = {}, []
    for q in quests:
        qid = q["quest_id"]
        references[str(qid)] = {"quest_id": qid, "verified_build": 66384,
            "quest_roles": [{"npc_id": 900+qid, "role": "QUEST_ENDER"}],
            "spawn_candidates": [{"spawn_id": 40+qid, "world_map_id": 2175, "x": -200.+qid*25,
                                  "y": 0., "z": 10., "role": "QUEST_ENDER", "entity_kind": "CREATURE",
                                  "entry": 900+qid, "context": {}, "verified_build": 66384}]}
        if not q["is_complete"]:
            locations.append({"quest_id": qid, "map_id": 1409, "source": "QUEST_POI",
                              "world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                                 "x": 100.+qid*10, "y": 0., "z": work_z, "z_known": True}})
    model = WorldModel()
    model.ingest(Observation.create({"session_id": "agenda", "frame_id": f"f{at}", "monotonic_time": at,
        "player_present": True, "map_id": 1409, "orientation": 0., "position": {"x": .5, "y": .5},
        "active_quests": quests, "quest_locations": locations,
        "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                  "x": x, "y": y, "z": 10., "z_known": True},
        "reference_knowledge": {"quests": references}}, at))
    return model


def goal(**params):
    return Goal.parse("Questelj", 1., params)


def by_key(agenda):
    return {step["key"]: step for step in agenda.snapshot()["steps"]}


def test_three_area_quests_have_work_then_grounded_turnins_and_next_quest_checks():
    agenda = QuestAgenda()
    model = world()
    before = deepcopy(model.state)
    agenda.refresh(goal(), model, 10.)
    steps = by_key(agenda)
    assert agenda.groups == [["1", "2", "3"]]
    assert agenda.preferred_key == "work:1"
    assert steps["turnin:2"]["npc_ids"] == ["902"]
    assert steps["turnin:2"]["location"]["x"] == -150.
    assert steps["turnin:2"]["status"] == "BLOCKED"
    assert steps["discover:2"]["depends_on"] == ["turnin:2"]
    assert model.state == before                  # plan is not a WorldModel writer


def test_finished_one_waits_for_its_known_cohort_then_nearest_ender_is_planned():
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, world(), 10.)
    agenda.refresh(g, world([quest(1, True), quest(2), quest(3)], x=120., at=11.), 11.)
    assert by_key(agenda)["work:1"]["status"] == "VERIFIED"
    assert by_key(agenda)["turnin:1"]["status"] == "BATCH_DEFERRED"
    assert agenda.preferred_key == "work:2"
    agenda.refresh(g, world([quest(1, True), quest(2, True), quest(3, True)], x=120., at=12.), 12.)
    assert agenda.preferred_key == "turnin:3"   # nearest ender, not log order
    assert all(by_key(agenda)[f"turnin:{q}"]["status"] == "READY" for q in (1, 2, 3))
    agenda.refresh(g, world([quest(1, True), quest(2, True)], x=-125., at=13.), 13.)
    assert "turnin:3" not in by_key(agenda)      # left live log; do not return there
    assert agenda.preferred_key == "turnin:2"


def test_another_cave_level_is_not_merged_with_same_xy_work():
    model = world()
    model.state["quest_locations"][1]["world_position"].update(x=110., z=-90.)
    agenda = QuestAgenda()
    agenda.refresh(goal(), model, 10.)
    assert not any("1" in group and "2" in group for group in agenda.groups)


def test_unknown_or_cross_map_positions_do_not_become_routes():
    model = world()
    model.state["quest_locations"][0]["world_position"]["instance_id"] = 1
    model.state["quest_locations"][1]["world_position"].update(x=float("nan"))
    agenda = QuestAgenda()
    agenda.refresh(goal(), model, 10.)
    steps = by_key(agenda)
    assert steps["work:1"]["location"] is None and steps["work:2"]["location"] is None


def test_explicit_primary_and_campaign_policy_are_not_overridden_by_batching():
    agenda = QuestAgenda()
    agenda.refresh(goal(primary_quest_id=2), world(), 10.)
    assert {step["quest_id"] for step in agenda.steps} == {"2"}
    model = world()
    model.quest_model.records[2].raw["is_campaign"] = True
    agenda.refresh(goal(mode="MAIN_CAMPAIGN"), model, 11.)
    assert {step["quest_id"] for step in agenda.steps} == {"2"}


def test_offer_plan_waits_for_live_acceptance_before_work_is_ready():
    model = world([])
    model.state["quest_ui"] = {"open": True, "entries": [
        {"kind": "AVAILABLE", "quest_id": 4, "title": "Offered quest"}]}
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, model, 10.)
    assert by_key(agenda)["accept:4"]["status"] == "READY"
    assert by_key(agenda)["future-work:4"]["status"] == "BLOCKED"
    agenda.refresh(g, world([quest(4)], at=11.), 11.)
    assert "accept:4" not in by_key(agenda)
    assert by_key(agenda)["work:4"]["status"] == "READY"


def test_tdb_chain_alone_is_not_a_live_offer():
    model = world([quest(1)])
    model.state["reference_knowledge"]["quests"]["1"]["chain"] = {"NextQuestID": 9}
    agenda = QuestAgenda()
    agenda.refresh(goal(), model, 10.)
    assert by_key(agenda)["discover:1"]["candidate_quest_ids"] == ["9"]
    assert "accept:9" not in by_key(agenda)


def test_goal_or_session_change_drops_old_cohort_and_advice():
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, world(), 10.)
    agenda.advisor_order = ("work:3",)
    model = world([quest(1, True)], at=11.)
    model.state["session_id"] = "other-session"
    agenda.refresh(g, model, 11.)
    assert not agenda.advisor_order and not agenda.groups
    assert by_key(agenda)["work:1"]["location"] is None


def test_historical_quests_do_not_push_current_work_out_of_the_read_ahead_budget():
    model = world([quest(q) for q in range(1, 40)])
    model.quest_model.ingest([quest(900)], "new-log", 11.)
    model.state["active_quests"] = [quest(900)]
    agenda = QuestAgenda()
    agenda.refresh(goal(), model, 11.)
    assert by_key(agenda)["work:900"]["status"] == "READY"


def test_prepared_llm_order_guides_the_next_task_after_credit_not_the_running_one():
    g, model, agenda = goal(), world(), QuestAgenda()
    class Advisor:
        def ask(self, task, key, payload):
            # Put quest 3 first while retaining all dependency edges.
            tasks = sorted(payload["tasks"], key=lambda t: (0 if t["quest_id"] == "3" else 1,
                {"WORK": 0, "TURN_IN": 1, "CHECK_NEXT_QUESTS": 2}.get(t["kind"], 3)))
            return {"order": [task["key"] for task in tasks]}
    agenda.refresh(g, model, 10.)
    assert agenda.preferred_key == "work:1"
    agenda.refresh(g, model, 11.1, advisor=Advisor())
    assert agenda.preferred_key == "work:1" and agenda.advice == "grounded_local_llm"
    model = world([quest(1, True), quest(2), quest(3)], x=120., at=12.)
    agenda.refresh(g, model, 12.)
    assert agenda.preferred_key == "work:3"


def test_batch_deferral_is_bounded_and_does_not_hide_all_unavailable_actions():
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, world(), 10.)
    model = world([quest(1, True), quest(2), quest(3)], at=11., x=120.)
    agenda.refresh(g, model, 11.)
    work = Proposal.make("MOVE", "work", {"quest_id": 2, "purpose": "OBJECTIVE"}, priority=60.)
    turnin = Proposal.make("MOVE", "turnin", {"quest_id": 1, "purpose": "LOCATE_TURN_IN_REGION"}, priority=80.)
    registry = SimpleNamespace(available=lambda p, w: True)
    assert [p.key for p in agenda.apply([turnin, work], model, 11., registry=registry, blocked_until={})] == [work.key]
    # No available work => do not create an empty-plan WAIT loop.
    assert turnin.key in [p.key for p in agenda.apply([turnin, work], model, 11., registry=registry,
                                                     blocked_until={work.key: 12.})]
    agenda.refresh(g, model, 612.)
    assert by_key(agenda)["turnin:1"]["status"] == "READY"


def test_batch_defers_the_return_trip_not_an_already_available_local_turnin():
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, world(), 10.)
    model = world([quest(1, True), quest(2), quest(3)], at=11., x=120.)
    agenda.refresh(g, model, 11.)
    work = Proposal.make("MOVE", "work", {"quest_id": 2, "purpose": "OBJECTIVE"}, priority=60.)
    local = Proposal.make("TALK", "verified local ender", {"quest_id": 1, "purpose": "TURN_IN", "guid": "current-npc"}, priority=90.)
    result = agenda.apply([work, local], model, 11., registry=SimpleNamespace(available=lambda p, w: True), blocked_until={})
    assert [proposal.key for proposal in result] == [work.key, local.key]
    assert result[1].priority == 90.


def test_ranking_changes_only_existing_quest_routes_not_keys_or_combat_loot():
    agenda, g, model = QuestAgenda(), goal(), world()
    agenda.refresh(g, model, 10.)
    proposals = [Proposal.make(skill, skill, {"quest_id": 1}, priority=50.)
                 for skill in ("MOVE", "LOOT", "COMBAT", "QUEST_DIALOG")]
    result = agenda.apply(proposals, model, 10., registry=SimpleNamespace(available=lambda p, w: True), blocked_until={})
    assert [p.key for p in result] == [p.key for p in proposals]
    assert [p.priority for p in result] == [50., 50., 50., 50.]
    route_only = agenda.apply(proposals[:1], model, 10., registry=SimpleNamespace(available=lambda p, w: True), blocked_until={})
    assert route_only[0].priority == 62. and route_only[0].key == proposals[0].key


def test_ready_object_use_never_loses_to_an_agenda_boosted_visual_search():
    agenda, g, model = QuestAgenda(), goal(), world()
    agenda.refresh(g, model, 10.)
    seek = Proposal.make("SEEK_VISUAL_CUE", "look", {"quest_id": 1}, priority=82.)
    use = Proposal.make("OBJECT_USE", "verified object", {"quest_id": 1}, priority=85.)
    result = agenda.apply([seek, use], model, 10., registry=SimpleNamespace(available=lambda p, w: True), blocked_until={})
    assert [p.priority for p in result] == [82., 85.]


def test_blocked_planned_task_yields_to_an_available_existing_route_without_a_new_brain():
    agenda, g, model = QuestAgenda(), goal(), world()
    agenda.refresh(g, model, 10.)
    one = Proposal.make("MOVE", "first", {"quest_id": 1}, priority=50.)
    two = Proposal.make("MOVE", "second", {"quest_id": 2}, priority=50.)
    result = agenda.apply([one, two], model, 10., registry=SimpleNamespace(available=lambda p, w: True),
                          blocked_until={one.key: 20.})
    assert agenda.preferred_key == "work:2"
    assert result[1].key == two.key and result[1].priority == 62.
    assert agenda.snapshot()["selection_reason"].startswith("planned_task_not_executable")


def test_field_completion_does_not_plan_an_npc_trip_or_batch_deferral():
    agenda, g = QuestAgenda(), goal()
    agenda.refresh(g, world(), 10.)
    model = world([quest(1, True), quest(2), quest(3)], at=11.)
    model.quest_model.records[1].raw["completion_mode"] = "FIELD_TURN_IN"
    agenda.refresh(g, model, 11.)
    turnin = by_key(agenda)["turnin:1"]
    assert turnin["completion_mode"] == "FIELD_TURN_IN"
    assert turnin["status"] == "READY" and turnin["location"] is None


def test_completion_ui_of_another_quest_cannot_change_a_quest_ender_plan():
    model = world([quest(1, True), quest(2, True)])
    model.state["quest_ui"] = {"open": True, "quest_id": 2, "action": "TURN_IN"}
    model.state["quest_completion_mode"] = "FIELD_TURN_IN"
    agenda = QuestAgenda()
    agenda.refresh(goal(primary_quest_id=1), model, 10.)
    turnin = by_key(agenda)["turnin:1"]
    assert turnin["completion_mode"] == "UNKNOWN" and turnin["location"]["x"] == -175.


def test_every_open_objective_has_an_inspectable_strategy_and_verification_boundary():
    agenda = QuestAgenda()
    agenda.refresh(goal(), world(), 10.)
    objective = by_key(agenda)["work:1"]["objective_plans"][0]
    assert objective["objective_id"] == "1:0"
    assert objective["capabilities"] == ["IDENTIFY_TARGET", "TARGET", "APPROACH", "COMBAT", "LOOT_IF_NEEDED", "VERIFY_QUEST_CREDIT"]
    assert objective["execution"].startswith("REVALIDATE_EACH_CAPABILITY")


def test_real_planner_consumes_work_order_then_reorders_actual_turnin_moves():
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner, g = Planner(SkillRegistry()), goal()
    proposals = planner.candidates(g, world(), 10.)
    assert proposals[0].skill == "MOVE" and proposals[0].parameters["quest_id"] == 1
    planner.candidates(g, world([quest(1, True), quest(2), quest(3)], x=0., at=11.), 11.)
    assert planner.agenda.preferred_key == "work:2"
    complete = world([quest(1, True), quest(2, True), quest(3, True)], x=120., at=12.)
    proposals = planner.candidates(g, complete, 12.)
    assert proposals[0].skill == "MOVE" and proposals[0].parameters["quest_id"] == 3
    assert proposals[0].parameters["purpose"] == "LOCATE_TURN_IN_REGION"
    assert proposals[0].parameters["require_navmesh"] is True


def test_full_conditional_itinerary_visits_shared_work_before_distant_turnins_without_credit():
    agenda, model = QuestAgenda(), world()
    before = deepcopy(model.state["active_quests"])
    agenda.refresh(goal(), model, 10.)
    itinerary = agenda.snapshot()["itinerary"]
    order = [step["step"] for step in itinerary["steps"]]
    assert order[:3] == ["work:1", "work:2", "work:3"]
    assert order[3] == "turnin:3"
    assert order.index("turnin:2") < order.index("turnin:1")
    assert all(step["conditional"] for step in itinerary["steps"])
    assert itinerary["changes_quest_state"] is False and itinerary["navmesh_validated"] is False
    assert model.state["active_quests"] == before
    assert by_key(agenda)["turnin:3"]["status"] == "BLOCKED"


def test_route_preview_does_not_assume_a_missing_prerequisite_or_expand_unboundedly():
    from wowbot.agent.agenda_route_preview import route_preview
    broken = [{"key": "a", "kind": "WORK", "quest_id": "1", "status": "BLOCKED", "depends_on": ["missing"]}]
    assert route_preview(broken, {}, None)["steps"] == []
    independent = [{"key": str(i), "kind": "WORK", "quest_id": str(i), "status": "READY", "depends_on": []}
                   for i in range(100)]
    result = route_preview(independent, {}, None)
    assert len(result["steps"]) == 24 and result["unplanned_steps"] == 76


@pytest.mark.parametrize("answer", [None, {"order": ["invented"]}, {"order": ["a", "a"]},
                                     {"order": ["b", "a"]}, {"order": [1, 2]}])
def test_llm_cannot_invent_steps_or_break_dependencies(answer):
    payload = {"tasks": [{"key": "a", "depends_on": []}, {"key": "b", "depends_on": ["a"]}]}
    assert validate(payload, answer) == {}
    assert validate(payload, {"order": ["a", "b"], "completed": True, "keys": ["F7"]}) == {"order": ["a", "b"]}


def test_local_advisor_is_nonblocking_and_uses_the_existing_worker():
    entered, release = threading.Event(), threading.Event()
    def transport(system, payload, config):
        entered.set()
        release.wait(2.)
        return {"order": [task["key"] for task in payload["tasks"]]}
    advisor = SemanticAdvisor({"enabled": True}, transport=transport)
    agenda, model, g = QuestAgenda(), world(), goal()
    try:
        agenda.refresh(g, model, 10., advisor=advisor)
        assert agenda.preferred_key == "work:1" and advisor.queue
        advisor.poll()
        assert entered.wait(1.)
        agenda.refresh(g, model, 11.1, advisor=advisor)
        assert not release.is_set() and agenda.preferred_key == "work:1"
    finally:
        release.set()
        advisor.close()


def test_plan_refresh_during_running_attempt_does_not_reenter_skill_selection(monkeypatch):
    from test_active_pointer_tracking import attempt
    from test_agent_core import state
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Questelj", 10.)
    agent.set_mode(Mode.FULL_AI)
    agent.world.ingest(Observation.create(state(10., active_quests=[quest(1)]), 10.))
    agent.pending = attempt("WAIT_EVENT", {"event_type": "QUEST_CREDIT"})
    before = agent.pending.action_id
    monkeypatch.setattr(agent.planner, "candidates", lambda *a, **kw: pytest.fail("active skill reentered planner"))
    agent.tick(state(10.1, active_quests=[quest(1)]), 10.1)
    assert agent.pending.action_id == before
    assert agent.planner.agenda.snapshot()["steps"]
