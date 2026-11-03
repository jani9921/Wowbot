"""REV4 survival supplement: eat during the pre-pull rest (food from the client DB2).

Food/drink is classified from ItemEffect -> SpellEffect auras, never from the
localized item text.  REST presses one ready action-bar FOOD button once per
attempt while standing still out of combat; success is still observed health."""
from pathlib import Path

import pytest

from wowbot.agent.consumables import ConsumableCatalog, usable_consumable
from wowbot.runtime import SkillStatus
from wowbot.skills.rest import RestSkill
from test_pre_pull_regeneration_20261031 import _rest_state, health

BREAD, JERKY, WATER, HEARTHSTONE = 4540, 117, 159, 6948


class FakeCatalog:
    SPELLS = {BREAD: (1291822, (20, 226)), JERKY: (433, (84,)), WATER: (1291950, (21, 226)), HEARTHSTONE: (8690, ())}

    def item_use(self, item_id):
        spell, _ = self.SPELLS.get(item_id, (None, ()))
        return {"effects": [{"spell_id": spell, "trigger_type": 0}]} if spell else {}

    def spell_effects(self, spell_id):
        for spell, auras in self.SPELLS.values():
            if spell == spell_id:
                return [{"effect": 6, "aura": aura} for aura in auras] or [{"effect": 252, "aura": 0}]
        return []


class Bindings:
    def __init__(self, *names):
        self.names = set(names)

    def contains(self, name):
        return name in self.names


def bar(item=BREAD, binding="ACTIONBUTTON5", usable=True, cooldown=0.):
    return [{"kind": "spell", "id": 6343, "action": "ACTIONBUTTON1", "is_usable": True, "cooldown_remaining": 0.},
            {"kind": "item", "id": item, "action": binding, "is_usable": usable, "cooldown_remaining": cooldown}]


def resting(value=300., **extra):
    return health(value, actionbar=bar(), movement={"moving": False}, **extra)


def test_food_and_drink_come_from_the_spell_auras():
    catalog = ConsumableCatalog(FakeCatalog())
    assert [catalog.kind(item) for item in (BREAD, JERKY, WATER, HEARTHSTONE, 99999, None)] == [
        "FOOD", "FOOD", "DRINK", None, None, None]


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "data" / "client_supplement.sqlite3").is_file(),
                    reason="client DB2 supplement not present")
def test_the_pinned_client_data_classifies_real_items():
    catalog = ConsumableCatalog()
    assert [catalog.kind(item) for item in (BREAD, JERKY, WATER, HEARTHSTONE)] == ["FOOD", "FOOD", "DRINK", None]


def test_rest_eats_once_from_a_ready_bound_food_button_then_verifies_health():
    skill = RestSkill(bindings=Bindings("ACTIONBUTTON5"), consumables=ConsumableCatalog(FakeCatalog()))
    state = _rest_state()
    assert not skill.begin(state, resting(), 10.).commands
    eat = skill.verify(state, resting(), 10.2)
    assert eat.status is SkillStatus.RUNNING and [c.binding for c in eat.commands] == ["ACTIONBUTTON5"]
    assert eat.metadata["food_item_id"] == BREAD and "food_used" in eat.evidence
    assert not skill.verify(state, resting(), 10.5).commands                       # once per attempt
    assert skill.verify(state, resting(950.), 14.).status is SkillStatus.SUCCESS   # success is observed health


@pytest.mark.parametrize("change", [
    {"is_mounted": True}, {"movement": {"moving": True}}, {"is_casting": True},
    {"actionbar": bar(WATER)}, {"actionbar": bar(HEARTHSTONE)}, {"actionbar": bar(usable=False)},
    {"actionbar": bar(cooldown=12.)}, {"actionbar": bar(binding="ACTIONBUTTON9")}, {"actionbar": []},
])
def test_no_food_press_without_a_ready_bound_food_button_or_while_not_standing_still(change):
    skill = RestSkill(bindings=Bindings("ACTIONBUTTON5"), consumables=ConsumableCatalog(FakeCatalog()))
    state = _rest_state()
    skill.begin(state, resting(), 10.)
    result = skill.verify(state, {**resting(), **change}, 10.2)
    assert result.status is SkillStatus.RUNNING and not result.commands


def test_no_food_when_the_health_is_unknown_or_already_high():
    skill = RestSkill(bindings=Bindings("ACTIONBUTTON5"), consumables=ConsumableCatalog(FakeCatalog()))
    state = _rest_state()
    skill.begin(state, resting(), 10.)
    unknown = {**resting(), "packet_own_health": None}
    assert not skill.verify(state, unknown, 10.2).commands
    assert usable_consumable(resting(), ConsumableCatalog(FakeCatalog()), "FOOD", Bindings()) is None


def test_the_supervisor_dispatches_the_food_press_and_keeps_the_rest_running():
    from types import SimpleNamespace
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
    from wowbot.runtime.m0_dispatch import M0SkillDispatcher
    from wowbot.runtime.verification_engine import VerificationEngine
    rest = RestSkill(bindings=Bindings("ACTIONBUTTON5"), consumables=ConsumableCatalog(FakeCatalog()))
    supervisor = ActiveSkillSupervisor(m0_skills=M0SkillDispatcher(rest=rest, **{name: SimpleNamespace(begin=None, verify=None) for name in (
        'target', 'interact', 'combat', 'defend_wait', 'loot', 'object_use', 'quest_dialog',
        'field_turnin', 'quest_tool', 'quest_item', 'instructed_spell')}), verification_engine=VerificationEngine(),
                                       interaction_runtime=None, combat_runtime=None, loot_runtime=None, registry=None)
    state = _rest_state()
    rest.begin(state, resting(), 10.)
    attempt = SimpleNamespace(proposal=state.attempt.proposal)
    step = supervisor.step(attempt, state, SimpleNamespace(state=resting(), latest=None),
                           world_observation_id="o", visual_observation_id="v", now=10.2)
    assert [c.binding for c in step.commands] == ["ACTIONBUTTON5"] and step.terminal_outcome is None
    after = supervisor.step(attempt, state, SimpleNamespace(state=resting(950.), latest=None),
                            world_observation_id="o2", visual_observation_id="v2", now=14.)
    assert after.terminal_outcome is not None and after.terminal_outcome.value == "SUCCESS"
