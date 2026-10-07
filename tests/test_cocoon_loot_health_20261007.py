"""Live 2026-10-07 12:06 (pid 15440, addon 0.9.61, "Who Lurks in the Pit" 5/5).

* Every FAST packet carried ``health=0``: 12.1 returns a secret
  UnitHealth("player") and the addon's safeNumber turned it into 0, so the
  agent saw 0 % health for the whole run (defensive-spell rules fired).
* The 4th cocoon's freeing cast was running (is_casting) when OBJECT_USE
  failed "credit not received"; the credit arrived 1.9 s later.
* After the FAST digest credited the 5th cocoon, the snapshot still showed
  4/5 and a second OBJECT_USE right-clicked the freed prisoner.
* When combat ended, the suspended MOVE was preferred over the LOOT of the
  fresh kill; the agent walked off, and the later LOOT had no corpse
  position (``corpse_not_found``) -- LOOT/MOVE back and forth.  (Barrow
  Spiderlings are lootable: ``lootable=false`` only means looted or too far.)
"""
from pathlib import Path
from types import SimpleNamespace

from adapters.telemetry_packets import normalize
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.planning_orchestration import PlanningOrchestrator
from wowbot.agent.models import Proposal
from wowbot.skills.object_use import ObjectUseSkill

ADDON = Path(__file__).resolve().parents[1] / "addon" / "AIPlayerControllerExport"


def test_a_living_player_at_zero_health_is_unknown_health():
    assert normalize({"health": 0, "max_health": 472, "is_dead": False})["health"] is None
    assert normalize({"health": 0, "max_health": 472, "is_dead": True})["health"] == 0
    assert normalize({"health": 300, "max_health": 472})["health"] == 300
    lua = (ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    assert 'health = optionalNumber(safeCall(UnitHealth, "player"))' in lua
    assert 'health = safeNumber(safeCall(UnitHealth, "player"))' not in lua


def test_object_use_waits_while_its_cast_runs_after_the_deadline():
    skill = ObjectUseSkill()
    context = {"used_at": 100.}
    casting = {"is_casting": True, "state_sample_time": 103.}         # snapshot is fresh
    assert skill._use_cast_running(context, casting, 104., 103.)
    assert not skill._use_cast_running(context, {**casting, "is_casting": False}, 104., 103.)
    assert not skill._use_cast_running(context, casting, 109.5, 103.)  # bounded
    assert not skill._use_cast_running({}, casting, 104., 103.)       # nothing was used


def _cursor(t, x=.51, y=.52):
    return {"monotonic_time": t, "cursor_position": {"nx": x, "ny": y}}


def test_no_second_object_use_on_the_object_just_credited():
    flow = ObjectInteractionFlow()
    flow.note_result({"action_id": "a1", "skill": "OBJECT_USE", "outcome": "SUCCESS"}, _cursor(10.))
    assert flow.just_credited(_cursor(11.))
    assert not flow.just_credited(_cursor(11., x=.70))              # another object
    assert not flow.just_credited(_cursor(13.5))                    # the hold is short
    other = ObjectInteractionFlow()
    other.note_result({"action_id": "a2", "skill": "OBJECT_USE", "outcome": "FAILURE"}, _cursor(10.))
    assert not other.just_credited(_cursor(11.))


class _Supervisor:
    def __init__(self):
        self.cleared = None

    def resume_candidate(self, state, now):
        return SimpleNamespace(intent=SimpleNamespace(skill_type="MOVE", parameters={"x": 1., "y": 2.}),
                               token="resume-1")

    def clear_resume(self, reason):
        self.cleared = reason


def _orchestrator():
    orchestrator = PlanningOrchestrator.__new__(PlanningOrchestrator)
    orchestrator.supervisor = _Supervisor()
    orchestrator.registry = SimpleNamespace(available=lambda proposal, world: True)
    return orchestrator


def test_the_post_combat_resume_waits_for_the_loot_of_the_kill():
    orchestrator, world = _orchestrator(), SimpleNamespace(state={})
    loot = Proposal.make("LOOT", "Halott target lootjának ellenőrzése", {"guid": "Creature-1"}, priority=85)
    proposals = [loot]
    assert orchestrator._inject_supervisor_resume(proposals, world, 1.) is None
    assert proposals == [loot] and orchestrator.supervisor.cleared is None   # kept for later
    approach = Proposal.make("VISUAL_APPROACH", "corpse", {"purpose": "LOOT"})
    assert orchestrator._inject_supervisor_resume([approach], world, 1.) is None
    use = Proposal.make("OBJECT_USE", "cocoon", {"x": .5, "y": .5})
    assert orchestrator._inject_supervisor_resume([use], world, 1.) is None
    move = Proposal.make("MOVE", "other", {"x": 3., "y": 4.})
    resumed = orchestrator._inject_supervisor_resume([move], world, 1.)
    assert resumed is not None and resumed.parameters["_resume_token"] == "resume-1"


def test_a_sent_click_always_gets_time_for_its_credit():
    skill = ObjectUseSkill()
    assert skill._click_recent({"click_sent_at": 107.}, 108.5, 108.)     # deadline just passed
    assert not skill._click_recent({"click_sent_at": 107.}, 112.5, 108.)
    assert not skill._click_recent({}, 108.5, 108.)                     # nothing clicked


def test_out_of_combat_a_dead_targets_loot_outranks_location_moves():
    import inspect
    from wowbot.agent import combat_planning
    source = inspect.getsource(combat_planning)
    assert 'priority=85 if state.get("is_in_combat") else 107' in source
