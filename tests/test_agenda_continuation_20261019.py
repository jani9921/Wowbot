"""Rolling agenda survives real turn-in and prepares conditional next work."""
from copy import deepcopy
from types import SimpleNamespace

from test_quest_agenda import by_key, goal, quest, world
from wowbot.agent.models import Proposal
from wowbot.agent.quest_agenda import QuestAgenda


REGISTRY = SimpleNamespace(available=lambda proposal, model: True)


def _offer(model, qid=4):
    model.state["map_pois"] = {"available_quests": [{
        "quest_id": qid, "quest_name": "Available quest", "is_campaign": True,
        "map_id": 1409, "source": "QUESTLINE_API", "x": .5, "y": .5,
        "world_position": {"x": 120., "y": 0., "instance_id": 2175,
                           "coordinate_space": "WORLD_YARDS", "z_known": False}}]}


def _turn_in(model, qid=1, at=11.):
    model.quest_model.apply_event(SimpleNamespace(
        event_type="QUEST_TURNED_IN", quest_ids=(qid,), received_at=at,
        observation_id="verified-turnin", event_id="turnin-event"))
    model.state.update(active_quests=[], monotonic_time=at)
    model.state["reference_knowledge"] = {"quests": {}}


def test_live_offer_has_five_conditional_phases_not_just_accept_and_work():
    agenda, model = QuestAgenda(), world([])
    _offer(model)
    before = deepcopy(model.state)
    agenda.refresh(goal(), model, 10.)
    steps = by_key(agenda)
    order = [step["step"] for step in agenda.snapshot()["itinerary"]["steps"]]
    assert order == ["accept:4", "future-read:4", "future-work:4", "future-turnin:4", "discover:4"]
    assert steps["accept:4"]["status"] == "READY"
    assert all(steps[key]["status"] == "BLOCKED" for key in order[1:])
    assert "live_quest_complete" in steps["future-turnin:4"]["requires"]
    assert agenda.snapshot()["itinerary"]["steps"][3]["expects"] == "QUEST_TURN_IN_VERIFIED"
    assert all(step["if_evidence_missing"] == "GATHER_FRESH_EVIDENCE_THEN_REPLAN"
               for step in agenda.snapshot()["itinerary"]["steps"])
    assert model.state == before and not model.quest_model.records


def test_empty_known_quest_log_has_a_real_discovery_task_not_an_empty_agenda():
    agenda, model = QuestAgenda(), world([])
    agenda.refresh(goal(), model, 10.)
    step = by_key(agenda)["discover:available"]
    assert step["status"] == "READY" and step["quest_id"] is None
    assert agenda.preferred_key == step["key"]
    assert "fresh_gossip_or_map_api_availability" in step["requires"]


def test_unknown_quest_log_or_an_unread_active_quest_does_not_mean_no_quest():
    agenda, model = QuestAgenda(), world([])
    model.state.pop("active_quests")
    agenda.refresh(goal(), model, 10.)
    assert not agenda.steps
    model.state["active_quests"] = [{"quest_id": 9}]
    agenda.refresh(goal(), model, 11.)
    assert "discover:available" not in by_key(agenda)


def test_real_planner_exposes_and_consumes_discovery_then_the_new_offer():
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner, model, g = Planner(SkillRegistry()), world([]), goal()
    model.state.update(world_map_open=False, is_casting=False, is_in_combat=False, target={})
    discovery = planner.candidates(g, model, 10.)[0]
    assert discovery.skill == "OPEN_MAP"
    snapshot = planner.agenda.snapshot()
    assert snapshot["current_task"]["key"] == "discover:available"
    assert snapshot["recommendation"]["task"] == "discover:available"
    assert snapshot["recommendation"]["is_preferred_task"] is True
    assert snapshot["recommendation"]["status"] == "PLANNER_RECOMMENDATION_NOT_EXECUTION"
    _offer(model)
    route = planner.candidates(g, model, 10.1)[0]
    assert route.skill == "MOVE" and route.parameters["quest_id"] == 4
    assert planner.agenda.snapshot()["recommendation"]["task"] == "accept:4"


def test_verified_turnin_preserves_continuation_even_after_reference_projection_drops_it():
    agenda, model, g = QuestAgenda(), world([quest(1, True)]), goal()
    model.state["reference_knowledge"]["quests"]["1"]["chain"] = {"NextQuestID": 9}
    agenda.refresh(g, model, 10.)
    _turn_in(model)
    agenda.refresh(g, model, 11.)
    steps = by_key(agenda)
    assert steps["turnin:1"]["status"] == "VERIFIED"
    assert steps["turnin:1"]["source"] == "VERIFIED_QUEST_TURNED_IN"
    assert steps["discover:1"]["status"] == "READY"
    assert steps["discover:1"]["candidate_quest_ids"] == ["9"]
    assert "accept:9" not in steps
    assert agenda.preferred_key == "discover:1"


def test_quest_disappearance_is_not_a_verified_turnin():
    agenda, model, g = QuestAgenda(), world([quest(1, True)]), goal()
    agenda.refresh(g, model, 10.)
    model.quest_model.ingest([], "absent", 11.)
    model.state.update(active_quests=[], monotonic_time=11.)
    agenda.refresh(g, model, 11.)
    assert "turnin:1" not in by_key(agenda)
    assert by_key(agenda)["discover:available"]["source"] == "LIVE_QUEST_LOG_EMPTY"


def test_new_live_pin_replaces_discovery_immediately_without_one_second_delay():
    agenda, model, g = QuestAgenda(), world([]), goal()
    agenda.refresh(g, model, 10.)
    _offer(model)
    agenda.refresh(g, model, 10.1)
    assert agenda.preferred_key == "accept:4"
    assert "discover:available" not in by_key(agenda)
    assert by_key(agenda)["accept:4"]["title"] == "Available quest"


def test_first_known_empty_log_replaces_unknown_without_idle_refresh_delay():
    agenda, model, g = QuestAgenda(), world([]), goal()
    model.state.pop("active_quests")
    agenda.refresh(g, model, 10.)
    model.state["active_quests"] = []
    agenda.refresh(g, model, 10.1)
    assert agenda.preferred_key == "discover:available"


def test_tdb_future_location_never_authorizes_accept_or_work_after_turnin():
    agenda, model, g = QuestAgenda(), world([quest(1, True)]), goal()
    model.state["reference_knowledge"]["quests"]["1"].update(
        chain={"NextQuestID": 9}, follow_up_candidates=[{
            "quest_id": 9, "title": "Maybe next", "quest_roles": [],
            "availability": "REQUIRES_LIVE_AVAILABILITY"}])
    agenda.refresh(g, model, 10.)
    _turn_in(model)
    agenda.refresh(g, model, 11.)
    assert not any(step["kind"] in {"ACCEPT", "WORK"} for step in agenda.steps)
    assert not model.state["active_quests"]


def test_discovery_plan_consumes_only_existing_qualified_proposals_and_keeps_keys():
    agenda, model = QuestAgenda(), world([])
    agenda.refresh(goal(), model, 10.)
    request = Proposal.make("OPEN_MAP", "query quest locations", {
        "purpose": "DISCOVER_AVAILABLE_QUESTS"}, priority=60.)
    inspect = Proposal.make("INSPECT", "random body", {"track_id": "other"}, priority=60.)
    result = agenda.apply([inspect, request], model, 10., registry=REGISTRY, blocked_until={})
    assert [p.key for p in result] == [inspect.key, request.key]
    assert result[0].priority == 60. and result[1].priority == 72.
    assert agenda.apply([], model, 10., registry=REGISTRY, blocked_until={}) == []


def test_blocked_discovery_or_survival_action_does_not_get_an_agenda_boost():
    agenda, model = QuestAgenda(), world([])
    agenda.refresh(goal(), model, 10.)
    request = Proposal.make("OPEN_MAP", "query", {"purpose": "DISCOVER_AVAILABLE_QUESTS"}, priority=60.)
    combat = Proposal.make("COMBAT", "survive", {"guid": "enemy"}, priority=120.)
    result = agenda.apply([request, combat], model, 10., registry=REGISTRY, blocked_until={})
    assert [p.priority for p in result] == [60., 120.]
    result = agenda.apply([request], model, 10., registry=REGISTRY, blocked_until={request.key: 20.})
    assert result[0].priority == 60.


def test_new_session_cannot_inherit_old_chain_candidates_or_explicit_primary_scope():
    agenda, model, g = QuestAgenda(), world([quest(1, True)]), goal()
    model.state["reference_knowledge"]["quests"]["1"]["chain"] = {"NextQuestID": 9}
    agenda.refresh(g, model, 10.)
    other = world([], at=11.)
    other.state["session_id"] = "another-session"
    agenda.refresh(g, other, 11.)
    assert "discover:1" not in by_key(agenda)
    assert not by_key(agenda)["discover:available"].get("candidate_quest_ids")
    agenda.refresh(goal(primary_quest_id=1), other, 12.)
    assert not agenda.steps
