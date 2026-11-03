"""User 2026-10-31: in combat, Tab until the selected unit is one that attacks us.

"Do not start casting on the first Tab: it may not be the one attacking us;
Tab until we target the creature that attacks us."  The server names our
attackers (unit field target == us).  Without that knowledge any live enemy a
defence Tab selects still counts, as before.  No 1.5 s pause between Tabs:
0.25 s (user)."""
from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.target import TargetSkill
from test_unit_fields_20261027 import citadel

ATTACKER = "Creature-0-1461-2534-147807-186892-attacker"
BYSTANDER = "Creature-0-1461-2534-147807-186892-bystander"


def world(selected=None):
    state = citadel(attacker=(12., 0., 260., {"targets_me": True, "health": 10}),
                    bystander=(4., 0., 260., {"health": 10}))
    state.update(is_in_combat=True, monotonic_time=10.)
    if selected:
        state["target"] = {"guid": selected, "attackable": True, "dead": False, "npc_id": 186892}
    return state


def tab_state(now=10.):
    proposal = Proposal.make("TARGET", "defend", {"guid": ATTACKER, "activation_source": "TAB_DEFEND",
                                                  "purpose": "DEFEND_RETARGET"})
    attempt = Attempt("a", proposal, {}, "o", now, now+4., (), Prediction("p", "a", "x", now, now+4., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("TARGET", proposal.parameters, ATTACKER), attempt=attempt, now=now)
    return runtime.state


def test_a_tab_onto_a_bystander_tabs_again_until_the_attacker_is_selected():
    skill, state = TargetSkill(), tab_state()
    assert [c.binding for c in skill.begin(state, world()).commands] == ["TARGETNEARESTENEMY"]
    assert skill.verify(state, world(BYSTANDER), 10.1).status is SkillStatus.RUNNING     # settling, no cast
    again = skill.verify(state, world(BYSTANDER), 10.3)
    assert again.status is SkillStatus.RUNNING and [c.binding for c in again.commands] == ["TARGETNEARESTENEMY"]
    done = skill.verify(state, world(ATTACKER), 10.6)
    assert done.status is SkillStatus.SUCCESS and done.metadata["attacker_verified"] is True


def test_the_retab_is_bounded():
    skill, state = TargetSkill(), tab_state()
    skill.begin(state, world())
    at, presses = 10.3, 0
    for _ in range(10):
        result = skill.verify(state, world(BYSTANDER), at)
        presses += bool(result.commands)
        at += .3
        if result.status is not SkillStatus.RUNNING:
            break
    assert result.status is SkillStatus.FAILURE and result.metadata["detail"] == "tab_did_not_reach_an_attacker"
    assert presses == TargetSkill.DEFEND_TAB_LIMIT - 1


def test_without_server_attackers_any_live_enemy_still_defends():
    skill, state = TargetSkill(), tab_state()
    skill.begin(state, world())
    unknown = world(BYSTANDER)
    unknown["packet_entities"] = {}
    result = skill.verify(state, unknown, 10.3)
    assert result.status is SkillStatus.SUCCESS and result.metadata["attacker_verified"] is False


def test_the_planner_retargets_instead_of_defending_a_bystander():
    policy = CombatPlanningPolicy.__new__(CombatPlanningPolicy)
    state = world(BYSTANDER)
    proposal = policy._defend_tab(state, 10.)
    assert proposal.skill == "TARGET" and proposal.parameters["guid"] == ATTACKER
    assert policy._defend_tab(state, 10.1) is None                       # 0.25 s between Tabs
    assert policy._defend_tab(state, 10.3) is not None
    assert CombatPlanningPolicy.DEFEND_TAB_SECONDS == .25


def test_live_1101_the_deadline_always_ends_the_defence_tab():
    """Westfall gnolls: past its deadline the branch kept RUNNING with no press
    for 70 s while the character was killed (twice)."""
    skill, state = TargetSkill(), tab_state()
    skill.begin(state, world())
    result = skill.verify(state, world(BYSTANDER), 14.5)                 # deadline 14.
    assert result.status is SkillStatus.FAILURE and result.metadata["detail"] == "tab_did_not_reach_an_attacker"
    nothing = TargetSkill()
    other = tab_state()
    nothing.begin(other, world())
    assert nothing.verify(other, world(), 14.5).status is SkillStatus.FAILURE    # Tab found nobody


def test_an_attacker_behind_is_faced_before_the_next_tab():
    skill, state = TargetSkill(), tab_state()
    skill.begin(state, world())
    behind = world(BYSTANDER)
    behind["orientation"] = 3.14159                        # facing away from the attacker at +x
    turn = skill.verify(state, behind, 10.3)
    assert [c.binding for c in turn.commands] in (["TURNLEFT"], ["TURNRIGHT"]) and turn.metadata["face_attacker"]
    facing = world(BYSTANDER)
    facing["orientation"] = 0.
    tab = skill.verify(state, facing, 10.6)
    assert [c.binding for c in tab.commands] == ["TARGETNEARESTENEMY"]
