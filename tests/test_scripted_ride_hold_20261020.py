"""Scripted Ralia ride (offline, live 2026-10-20 09:58:37-09:59:32).

F7 on the creature Ralia Dreamchaser (target
Creature-0-1465-2175-71046-156929-000053399A) started a client scene; at
09:58:39 the cursor named ClientActor-3-12-458 "Ralia Dreamchaser".  The
exported position stayed (71.6, -2132.4) for 52 s, in_vehicle/on_taxi false,
then the player stood on the rim (109, -2271) with "1/1 Ride Ralia
Dreamchaser to escape".  Meanwhile three floor-cue MOVEs failed at once.
"""
from wowbot.agent.scripted_ride_planning import ScriptedRideHold

RALIA = "Creature-0-1465-2175-71046-156929-000053399A"
SCENE_RALIA = "ClientActor-3-12-458"


def state(now, *, target=None, mouse=None, ride_done=False, x=71.6, y=-2132.4, **extra):
    return {"monotonic_time": now, "is_in_combat": False, "in_vehicle": False, "on_taxi": False,
            "target": target, "mouseover": mouse, "soft_targets": [],
            "player_world_position": {"x": x, "y": y, "instance_id": 2175},
            "active_quests": [{"quest_id": 55639, "is_complete": ride_done, "objectives": [
                {"objective_id": "55639:0", "description": "5/5 Trapped Expedition Member rescued from cocoons",
                 "is_complete": True},
                {"objective_id": "55639:1", "description": "1/1 Defeat Hrun to rescue Ralia Dreamchaser",
                 "is_complete": True},
                {"objective_id": "55639:2", "description": f"{int(ride_done)}/1 Ride Ralia Dreamchaser to escape",
                 "is_complete": ride_done}]}],
            **extra}


def creature(guid=RALIA, name="Ralia Dreamchaser"):
    return {"guid": guid, "name": name}


def test_the_ride_holds_still_until_the_credit_and_the_landing():
    hold = ScriptedRideHold()
    assert hold.propose(state(452507.6, target=creature())) == []          # the F7 press
    first = hold.propose(state(452509.0, mouse=creature(SCENE_RALIA)))
    assert first[0].skill == "WAIT_EVENT" and first[0].priority > 120
    assert first[0].parameters["objective_ids"] == ["55639:2"]
    # Mid-ride the cursor shows nothing; the hold stays.
    assert hold.propose(state(452540.0))[0].skill == "WAIT_EVENT"
    # 09:59:31: set down on the rim with the credit.
    assert hold.propose(state(452561.6, x=109., y=-2271., ride_done=True)) == []
    assert hold.ride is None


def test_a_landing_or_the_time_limit_ends_the_hold():
    hold = ScriptedRideHold()
    hold.propose(state(10., target=creature()))
    hold.propose(state(11., mouse=creature(SCENE_RALIA)))
    assert hold.propose(state(40., x=109., y=-2271.)) == []              # free, no credit yet
    hold = ScriptedRideHold()
    hold.propose(state(10., target=creature()))
    hold.propose(state(11., mouse=creature(SCENE_RALIA)))
    assert hold.propose(state(100.))
    assert hold.propose(state(132.)) == []                               # 120 s since last seen


def test_combat_pauses_the_hold_without_ending_it():
    hold = ScriptedRideHold()
    hold.propose(state(10., target=creature()))
    hold.propose(state(11., mouse=creature(SCENE_RALIA)))
    assert hold.propose(state(12., is_in_combat=True)) == []
    assert hold.propose(state(13.))[0].skill == "WAIT_EVENT"


def test_bare_client_actors_and_vehicles_start_nothing():
    cadaver = {"guid": "ClientActor-3-12-77", "name": "Monstrous Cadaver"}
    hold = ScriptedRideHold()
    assert hold.propose(state(10., mouse=cadaver)) == []                 # never a creature
    assert hold.propose(state(11., mouse=creature(SCENE_RALIA))) == []   # Ralia never a creature here
    late = ScriptedRideHold()
    late.propose(state(10., target=creature()))
    assert late.propose(state(17., mouse=creature(SCENE_RALIA))) == []   # not a takeover
    riding = ScriptedRideHold()
    riding.propose(state(10., target=creature()))
    assert riding.propose(state(11., mouse=creature(SCENE_RALIA), in_vehicle=True)) == []
    other = ScriptedRideHold()                                            # not named by an objective
    other.propose(state(10., target=creature(name="Grimaxe")))
    assert other.propose(state(11., mouse=creature(SCENE_RALIA, name="Grimaxe"))) == []


def test_one_wait_attempt_spans_the_ride():
    """The 15 s WAIT_EVENT contract timed out mid-ride; the failure memory then
    let INSPECT/SEEK run (replay 393 s / 419 s).  The ride asks for its window."""
    from types import SimpleNamespace
    from wowbot.agent.models import Proposal
    from wowbot.runtime.skill_executor import SkillExecutor
    hold = ScriptedRideHold()
    hold.propose(state(10., target=creature()))
    proposal = hold.propose(state(11., mouse=creature(SCENE_RALIA)))[0]
    assert proposal.parameters["wait_seconds"] >= 60.
    executor = SkillExecutor.__new__(SkillExecutor)
    executor.registry = SimpleNamespace(contracts={"WAIT_EVENT": SimpleNamespace(
        timeout=15., expected="quest_event_or_objective_progress", success_condition="")})
    world = SimpleNamespace(state=state(11.), latest=SimpleNamespace(observation_id="o"))
    timeouts = SimpleNamespace(resolve=lambda skill, value, context: value)
    plan = SimpleNamespace(plan_id="plan")
    attempt = executor.create_attempt(proposal, (), world=world, goal=None, current_plan=plan,
                                      timeouts=timeouts, memory=None, now=11.)
    assert attempt.prediction.deadline == 11.+SkillExecutor.MAX_EVENT_WAIT_SECONDS
    plain = Proposal.make("WAIT_EVENT", "event", {"quest_ids": [55639]})
    short = executor.create_attempt(plain, (), world=world, goal=None, current_plan=plan,
                                    timeouts=timeouts, memory=None, now=11.)
    assert short.prediction.deadline == 26.
