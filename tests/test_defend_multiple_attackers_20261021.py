"""Several attackers: after the first one dies the next one is fought (live 2026-10-21).

User: "defensive/combat bugos, több támadó mobnál, ha az első meghal, nem
csinál semmit, csak kis idő múlva, vagy semmit se csinál, és közben támadnak".
15:24:42-15:24:46 in combat with nothing selected only WAIT ran; 15:24:47-50
the COMBAT had no rage and F7 would have gone to the first whelp's corpse (the
soft-interact unit), so nothing attacked; 15:24:50-58 a failed COMBAT was
blocked for 8 s while the live whelp kept hitting.
"""
from types import SimpleNamespace

from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.models import Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import SkillStatus
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.skills import CombatSkill
from wowbot.skills.target import TargetSkill

from test_m0_combat_loot_skills import active
from test_server_kill_target_20261020 import unit

FIRST = "Creature-0-3769-2444-47-193876-000058BCBC"
SECOND = "Creature-0-3769-2444-47-193876-000158BCBC"


def fight(target=None, **extra):
    return {"is_in_combat": True, "monotonic_time": 100., "target": target or {},
            "player_world_position": {"x": 0., "y": 0., "z": 50., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "packet_entities": {SECOND: unit(SECOND, 4., 1.), FIRST: unit(FIRST, 1., 0., flags=0x4)},
            **extra}


def test_in_combat_without_a_live_target_tab_picks_any_attacker():
    policy = CombatPlanningPolicy(SkillRegistry())
    dead_selected = fight({"guid": FIRST, "attackable": True, "dead": True})
    tab = policy._defend_tab(dead_selected, 10.)
    assert tab.skill == "TARGET" and tab.parameters["activation_source"] == "TAB_DEFEND"
    assert tab.parameters["guid"] == SECOND                     # nearest live unit, not the corpse
    assert policy._defend_tab(dead_selected, 10.1) is None       # one Tab per 0.25 s (user 2026-10-31)
    assert policy._defend_tab(dead_selected, 10.3) is not None
    # No server units: the dead target's GUID pins the press.
    alone = {**fight({"guid": FIRST, "dead": True}), "packet_entities": {}}
    assert CombatPlanningPolicy(SkillRegistry())._defend_tab(alone, 10.).parameters["guid"] == FIRST


def test_the_defend_tab_is_allowed_only_in_combat_and_accepts_any_live_enemy():
    tab = Proposal.make("TARGET", "t", {"guid": SECOND, "activation_source": "TAB_DEFEND"})
    world = SimpleNamespace(state=fight())
    assert SkillRegistry().available(tab, world)
    assert not SkillRegistry().available(tab, SimpleNamespace(state={**fight(), "is_in_combat": False}))
    skill = TargetSkill()
    state = active("TARGET", tab.parameters, fight({"guid": FIRST, "dead": True}), deadline=5)
    started = skill.begin(state, fight({"guid": FIRST, "dead": True}))
    assert [c.binding for c in started.commands] == ["TARGETNEARESTENEMY"]
    assert check_command_identity("TARGET", tab.parameters, {"guid": SECOND}, fight(), started.commands, 1.)
    other = "Creature-0-3769-2444-47-193876-0000D8BCBC"
    picked = fight({"guid": other, "attackable": True, "dead": False})
    assert skill.verify(state, picked, 2.).status is SkillStatus.SUCCESS
    still_dead = fight({"guid": FIRST, "attackable": True, "dead": True})
    assert skill.verify(state, still_dead, 2.).status is SkillStatus.RUNNING


def test_without_rage_a_bound_start_attack_key_starts_the_melee():
    class Bindings:
        def __init__(self, keys):
            self.keys = set(keys)

        def contains(self, action):
            return action in self.keys
    live = fight({"guid": SECOND, "attackable": True, "dead": False},
                 soft_targets=[{"source_unit": "softinteract", "guid": FIRST}],
                 soft_targets_sample_time=100., target_sample_time=100.,
                 actionbar=[{"id": 1464, "kind": "spell", "action": "ACTIONBUTTON2", "name": "Slam",
                             "is_harmful": True, "is_usable": False, "lacks_resource": True,
                             "in_range": True, "max_range": 0}])
    skill = CombatSkill(bindings=Bindings({"STARTATTACK", "INTERACTTARGET", "ACTIONBUTTON2"}))
    state = active("COMBAT", {"guid": SECOND}, live)
    started = skill.begin(state, live, 100.)
    assert [c.binding for c in started.commands] == ["STARTATTACK"]
    # Not bound: F7 is still withheld while a corpse is the interact unit.
    plain = CombatSkill(bindings=Bindings({"INTERACTTARGET", "ACTIONBUTTON2"}))
    state = active("COMBAT", {"guid": SECOND}, live)
    assert "INTERACTTARGET" not in [c.binding for c in plain.begin(state, live, 100.).commands]
