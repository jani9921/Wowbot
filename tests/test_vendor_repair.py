from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False, **extra}, 1))
    return value


VENDOR_OPEN_REPAIRABLE = {"open": True, "npc_name": "Quartermaster Richter", "can_repair": True,
                          "repair_all_cost": 250, "repair_x": .82, "repair_y": .3}
VENDOR_OPEN_NOTHING_TO_REPAIR = {"open": True, "npc_name": "Quartermaster Richter", "can_repair": True,
                                 "repair_all_cost": 0, "repair_x": .82, "repair_y": .3}
VENDOR_CLOSED = {"open": False}


# --- WorldQuery.vendor() ---------------------------------------------------

def test_world_query_vendor_reflects_addon_state():
    w = world(vendor_ui=VENDOR_OPEN_REPAIRABLE)
    assert w.query.vendor()["open"] is True
    assert w.query.vendor()["repair_all_cost"] == 250


def test_world_query_vendor_empty_when_no_addon_data():
    w = world()
    assert w.query.vendor() == {}


# --- SkillRegistry.available() ---------------------------------------------

def test_repair_available_when_vendor_open_and_repairable():
    w = world(vendor_ui=VENDOR_OPEN_REPAIRABLE)
    proposal = Proposal.make("REPAIR", "test", {"x": .82, "y": .3})
    assert SkillRegistry().available(proposal, w) is True


def test_repair_unavailable_when_nothing_to_repair():
    w = world(vendor_ui=VENDOR_OPEN_NOTHING_TO_REPAIR)
    proposal = Proposal.make("REPAIR", "test", {"x": .82, "y": .3})
    assert SkillRegistry().available(proposal, w) is False


def test_repair_unavailable_when_vendor_closed():
    w = world(vendor_ui=VENDOR_CLOSED)
    proposal = Proposal.make("REPAIR", "test", {"x": .82, "y": .3})
    assert SkillRegistry().available(proposal, w) is False


def test_repair_unavailable_without_click_coordinates():
    w = world(vendor_ui={**VENDOR_OPEN_REPAIRABLE, "repair_x": None, "repair_y": None})
    proposal = Proposal.make("REPAIR", "test", {})
    assert SkillRegistry().available(proposal, w) is False


# --- SkillRegistry.commands() -----------------------------------------------

def test_repair_command_clicks_addon_supplied_coordinates():
    w = world(vendor_ui=VENDOR_OPEN_REPAIRABLE)
    proposal = Proposal.make("REPAIR", "test", {"x": .82, "y": .3})
    commands = SkillRegistry().commands(proposal, w)
    assert len(commands) == 1
    assert commands[0].kind == "CLICK" and commands[0].x == .82 and commands[0].y == .3


# --- Planner.candidates() proposes REPAIR opportunistically -----------------

def test_planner_proposes_repair_when_vendor_open_with_cost():
    w = world(vendor_ui=VENDOR_OPEN_REPAIRABLE)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Explore", 1), w, 1)
    repairs = [p for p in proposals if p.skill == "REPAIR"]
    assert len(repairs) == 1
    assert repairs[0].parameters["x"] == .82 and repairs[0].parameters["y"] == .3


def test_planner_does_not_propose_repair_when_nothing_to_repair():
    w = world(vendor_ui=VENDOR_OPEN_NOTHING_TO_REPAIR)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Explore", 1), w, 1)
    assert not any(p.skill == "REPAIR" for p in proposals)


def test_planner_does_not_propose_repair_when_vendor_closed():
    w = world(vendor_ui=VENDOR_CLOSED)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Explore", 1), w, 1)
    assert not any(p.skill == "REPAIR" for p in proposals)


def test_planner_repair_outranks_a_low_priority_explore_move():
    w = world(vendor_ui=VENDOR_OPEN_REPAIRABLE)
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Explore", 1, {"destination": {"map_id": 1409, "x": .9, "y": .9}}), w, 1)
    assert proposals and proposals[0].skill == "REPAIR"


# --- End-to-end engine wiring: SUCCESS when repair_all_cost drops -----------

def test_engine_repair_succeeds_when_cost_drops_after_click():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Explore", 1.0)
    agent.set_mode("FULL_AI")
    now = 1.0
    for _ in range(3):
        now += .3
        agent.tick({"session_id": "s", "frame_id": f"f{now}", "timestamp": now, "map_id": 1409,
                   "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
                   "world_map_open": False, "vendor_ui": VENDOR_OPEN_REPAIRABLE}, now)
    assert agent.pending is not None and agent.pending.proposal.skill == "REPAIR"
    now += .3
    result = agent.tick({"session_id": "s", "frame_id": f"f{now}", "timestamp": now, "map_id": 1409,
                        "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
                        "world_map_open": False, "vendor_ui": VENDOR_OPEN_NOTHING_TO_REPAIR}, now)
    assert result["result"]["outcome"] == "SUCCESS" and result["result"]["skill"] == "REPAIR"


def test_engine_repair_fails_on_timeout_when_cost_never_drops():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Explore", 1.0)
    agent.set_mode("FULL_AI")
    now = 1.0
    result = {}
    for _ in range(20):
        now += .3
        result = agent.tick({"session_id": "s", "frame_id": f"f{now}", "timestamp": now, "map_id": 1409,
                            "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
                            "world_map_open": False, "vendor_ui": VENDOR_OPEN_REPAIRABLE}, now)
    assert result["result"].get("skill") == "REPAIR"
    assert result["result"].get("outcome") == "FAILURE"

