"""Live 2026-10-04 (Stocking Up on Supplies, 55194): "Any item purchased
from Quartermaster Richter" / "Any item sold to Quartermaster Richter".

The server reported numFulfilled=1/1 with finished=false, so both objectives
looked complete; and the API `object` type made them generic INTERACTs with
no NPC.  The agent hovered Richter again and again but never opened her shop.
"""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_giver_evidence import friendly_npc_relevant, npc_objective_subjects
from wowbot.agent.quest_model import objective_type, vendor_clause
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

QUEST = {"quest_id": 55194, "title": "Stocking Up on Supplies", "is_complete": False, "is_accepted": True,
         "objectives": [
             {"current": 1, "required": 1, "is_complete": False, "raw_type": "object", "type": "INTERACT",
              "description": "Any item purchased from Quartermaster Richter"},
             {"current": 1, "required": 1, "is_complete": False, "raw_type": "object", "type": "INTERACT",
              "description": "Any item sold to Quartermaster Richter"}]}
RICHTER = {"guid": "Creature-0-1463-2175-58799-156800-0000C2113D", "name": "Quartermaster Richter",
           "npc_id": 156800, "attackable": False, "is_attackable": False, "dead": False, "reaction": "friendly"}
GOAL = Goal.parse("Questelj az Exile's Reach szigeten", 1.)


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0.}, "active_quests": [QUEST], "money": 500,
        "world_map_open": False, **extra}, 1.))
    return world


def _top(world, count=4):
    proposals = Planner(SkillRegistry()).candidates(GOAL, world, 1.)
    return sorted(proposals, key=lambda proposal: -proposal.priority)[:count]


def test_trade_clauses_name_the_vendor_and_the_kind():
    assert vendor_clause({"description": "Any item purchased from Quartermaster Richter"}) \
        == ("BUY", "Quartermaster Richter")
    assert vendor_clause({"description": "Any item sold to Quartermaster Richter"}) \
        == ("SELL", "Quartermaster Richter")
    assert vendor_clause({"description": "0/1 Buy a Fishing Pole from Fiona."}) == ("BUY", "Fiona")
    assert vendor_clause({"description": "Return to Captain Garrick"}) is None
    raw = dict(QUEST["objectives"][0])
    assert objective_type(raw)[0] == "BUY"
    # Real interactions keep their type.
    assert objective_type({"description": "Open the supply crate", "raw_type": "object",
                           "type": "INTERACT"})[0] == "INTERACT"


def test_api_finished_false_beats_full_counters():
    world = _world()
    objectives = world.quest_model.records[next(iter(world.quest_model.records))].objectives
    assert [(o.type, o.completion_state) for o in objectives] == [("BUY", "IN_PROGRESS"), ("SELL", "IN_PROGRESS")]
    assert all(o.target_entity["name"] == "Quartermaster Richter" for o in objectives)
    assert [o.type for o in world.quest_model.ready()] == ["BUY", "SELL"]
    # Counters alone still complete an objective when finished is not given.
    done = WorldModel()
    done.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "player_present": True, "active_quests": [{"quest_id": 7, "objectives": [
            {"current": 8, "required": 8, "raw_type": "monster", "description": "8/8 Boar slain"}]}]}, 1.))
    assert done.quest_model.records[next(iter(done.quest_model.records))].objectives[0].completion_state == "COMPLETE"


def test_only_the_named_vendor_is_relevant():
    world = _world()
    subjects = npc_objective_subjects(world.quest_model.ready())
    assert friendly_npc_relevant(world.state, RICHTER["guid"], {"BUY", "SELL"},
                                 unit_name="Quartermaster Richter", npc_subjects=subjects)
    assert not friendly_npc_relevant(world.state, "Creature-0-1-2-3-4-5", {"BUY", "SELL"},
                                     unit_name="Captain Garrick", npc_subjects=subjects)


def test_hovered_vendor_is_selected_then_its_shop_opened():
    hover = dict(RICHTER, exists=True, quest_related=True, quest_id=55194, identity_source="WOW_API_MOUSEOVER")
    top = _top(_world(mouseover=hover, cursor_position={"nx": .77, "ny": .53}))[0]
    assert (top.skill, top.parameters.get("guid")) == ("TARGET", RICHTER["guid"])
    top = _top(_world(target=RICHTER))[0]
    assert (top.skill, top.parameters.get("purpose")) == ("INTERACT", "OPEN_VENDOR")


def test_open_shop_buys_the_cheapest_item_and_sells_junk():
    vendor = {"open": True, "npc_name": "Quartermaster Richter", "items": [
        {"slot": 1, "name": "Bread", "price": 25, "item_id": 4540, "is_purchasable": True, "x": .1, "y": .3},
        {"slot": 2, "name": "Water", "price": 20, "item_id": 159, "is_purchasable": True, "x": .2, "y": .3}]}
    junk = {"items": [{"bag": 0, "slot": 3, "item_id": 117, "count": 2, "sell_price": 1, "quality": 0,
                       "x": .8, "y": .5}]}
    skills = [(p.skill, p.parameters.get("slot")) for p in
              _top(_world(target=RICHTER, vendor_ui=vendor, bags_open=False, inventory=junk), 2)]
    assert skills == [("OPEN_BAGS", None), ("BUY_VENDOR", 2)]
    skills = [p.skill for p in _top(_world(target=RICHTER, vendor_ui=vendor, bags_open=True, inventory=junk), 2)]
    assert set(skills) == {"SELL_VENDOR", "BUY_VENDOR"}


def test_interact_is_verified_by_the_vendor_shop_opening():
    from wowbot.agent.models import Proposal
    world = _world(target=RICHTER)
    registry = SkillRegistry()
    proposal = Proposal.make("INTERACT", "test", {"guid": RICHTER["guid"], "purpose": "OPEN_VENDOR"}, priority=74)

    class Attempt:
        pass
    attempt = Attempt()
    attempt.proposal, attempt.baseline = proposal, dict(world.state)
    attempt.observation_id, attempt.started_at, attempt.deadline = "old", 0., 7.
    attempt.commands = ()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 2., "frame_id": "g", "monotonic_time": 2., "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True, "target": RICHTER,
        "player_world_position": {"x": 0., "y": 0.}, "active_quests": [QUEST], "money": 500,
        "vendor_ui": {"open": True, "npc_name": "Quartermaster Richter", "items": []}}, 2.))
    outcome, _ = registry.verify(attempt, world, 2.)
    assert outcome.value == "SUCCESS"
