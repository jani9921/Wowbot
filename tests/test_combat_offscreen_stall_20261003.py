"""COMBAT stalled with the target off-screen (live 2026-10-03 13:12).

Prickly Porcupine selected, Charge pressed, the client answered "facing the
wrong way" and the off-screen facing recovery sent ONE 75 ms turn.  It then
waited for the post-recovery cast, nothing was usable and the wait never
ended: no input for 4.5 min (the attempt deadline was never checked).
"""
from wowbot.runtime import FailureReason, SkillStatus
from wowbot.skills import CombatSkill
from test_m0_combat_loot_skills import active

GUID = "Creature-0-3102-2175-11354-161131-000040DFAA"


def _offscreen(**extra):
    return {"target": {"guid": GUID, "attackable": True, "dead": False},
            "is_in_combat": False,
            "actionbar": [{"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
                           "is_harmful": True, "is_usable": False, "in_range": None,
                           "cooldown_remaining": 0}], **extra}


def test_post_recovery_wait_is_bounded_and_an_idle_attempt_fails_for_replan():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": GUID}, _offscreen(), deadline=1000)
    skill.begin(state, _offscreen(), 1.)
    state.skill_context["combat"]["await_post_recovery_cast"] = True
    results = [skill.verify(state, _offscreen(monotonic_time=t), t)
               for t in (1.1, 2., 2.7, 4., 6., 7.2)]
    assert not state.skill_context["combat"]["await_post_recovery_cast"]
    assert all(r.status is SkillStatus.RUNNING and not r.commands for r in results[:-1])
    stalled = results[-1]
    assert stalled.status is SkillStatus.FAILURE
    assert stalled.reason is FailureReason.FACING_FAILED and stalled.metadata["combat_stalled"]


def test_a_visible_or_melee_target_is_not_a_stall():
    skill = CombatSkill()
    melee = _offscreen()
    melee["actionbar"][0].update(in_range=True, is_usable=False)
    state = active("COMBAT", {"guid": GUID}, melee, deadline=1000)
    skill.begin(state, melee, 1.)
    for t in (2., 5., 8., 12.):
        assert skill.verify(state, melee, t).status is SkillStatus.RUNNING


def test_offscreen_facing_recovery_alternates_turns_and_attack_keys():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": GUID}, _offscreen(), deadline=1000)
    skill.begin(state, _offscreen(), 1.)
    first = skill._local_recovery_request(state, _offscreen(), FailureReason.FACING_WRONG_WAY, 2.)
    assert [c.binding for c in first.commands] == ["TURNLEFT", "INTERACTTARGET"]
    assert not state.skill_context["combat"].get("await_post_recovery_cast")


class _Bindings:
    def __init__(self, *actions):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def test_melee_target_without_rage_starts_auto_attack_by_interact_key():
    """Live 2026-10-03 13:37: a neutral Coastal Goat stood in melee over the
    character, 0 rage; the right click at its box hit our own model."""
    goat = {"target": {"guid": GUID, "attackable": True, "dead": False,
                       "screen_position": {"x": .5, "y": .63}},
            "actionbar": [{"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
                           "is_harmful": True, "is_usable": False, "in_range": True,
                           "lacks_resource": True, "cooldown_remaining": 0}]}
    skill = CombatSkill(_Bindings("INTERACTTARGET", "ACTIONBUTTON2"))
    state = active("COMBAT", {"guid": GUID}, goat, deadline=1000)
    started = skill.begin(state, goat, 1.)
    assert [(c.kind, c.binding) for c in started.commands] == [("BIND", "INTERACTTARGET")]


def test_registry_admits_melee_auto_attack_without_a_screen_box():
    from wowbot.agent.skills import SkillRegistry
    state = {"target": {"guid": GUID, "attackable": True, "dead": False},
             "actionbar": [{"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
                            "is_harmful": True, "is_usable": False, "in_range": True}]}
    assert SkillRegistry()._auto_attack_available(state)
    assert not SkillRegistry(_Bindings())._auto_attack_available(state)


def test_under_attack_combat_is_admissible_without_range_or_usable_data():
    """Live 2026-10-03 13:58: 80 s of WAIT while a goat killed the character;
    in combat Retail exported no range/usable values for its abilities."""
    from types import SimpleNamespace
    from wowbot.agent.models import Proposal
    from wowbot.agent.skills import SkillRegistry
    state = {"is_in_combat": True,
             "target": {"guid": GUID, "attackable": True, "dead": False},
             "actionbar": [{"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
                            "is_harmful": True, "is_usable": None, "in_range": None}]}
    proposal = Proposal.make("DEFEND", "t", {"guid": GUID})
    assert SkillRegistry().available(proposal, SimpleNamespace(state=state))
    assert not SkillRegistry().available(proposal, SimpleNamespace(state={**state, "is_in_combat": False}))
