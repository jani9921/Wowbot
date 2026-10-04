"""One typed dispatch boundary for canonical M0 skills.

The dispatcher owns no active state: all mutable state remains in the supplied
``ActiveSkillRuntime`` state. It merely prevents engine.py from carrying a
growing skill-type switch for every migrated M0 skill.
"""
from __future__ import annotations

from .active_skill import ActiveSkillState
from .contracts import SkillResult
from .skill_contract import SkillContractAdapter


class M0SkillDispatcher:
    CANONICAL = frozenset({"TARGET", "INTERACT", "TALK", "COMBAT", "DEFEND", "WAIT_EVENT", "LOOT", "OBJECT_USE", "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION"})

    def __init__(self, *, target, interact, combat, defend_wait, loot, object_use, quest_dialog, field_turnin, quest_tool, quest_item, instructed_spell):
        self.target, self.interact = target, interact
        self.combat, self.loot, self.quest_dialog = combat, loot, quest_dialog
        self.field_turnin = field_turnin
        self.quest_tool = quest_tool
        self.quest_item = quest_item
        self.instructed_spell = instructed_spell
        self.defend_wait = defend_wait
        self.object_use = object_use
        self._contracts = {
            "TARGET": SkillContractAdapter(
                lambda state, world: self.target.begin(state), self.target.verify),
            "INTERACT": SkillContractAdapter(self.interact.begin, self.interact.verify),
            "TALK": SkillContractAdapter(self.interact.begin, self.interact.verify),
            "COMBAT": SkillContractAdapter(
                lambda state, world: self.combat.begin(state, world, state.started_at), self.combat.verify),
            "DEFEND": SkillContractAdapter(
                lambda state, world: self.combat.begin(state, world, state.started_at), self.combat.verify),
            "WAIT_EVENT": SkillContractAdapter(
                lambda state, world: self.defend_wait.begin(state, world, state.started_at), self.defend_wait.verify),
            "LOOT": SkillContractAdapter(self.loot.begin, self.loot.verify),
            "OBJECT_USE": SkillContractAdapter(self.object_use.begin, self.object_use.verify),
            "QUEST_DIALOG": SkillContractAdapter(self.quest_dialog.begin, self.quest_dialog.verify),
            "FIELD_TURN_IN": SkillContractAdapter(self.field_turnin.begin, self.field_turnin.verify),
            "EXTRA_ACTION": SkillContractAdapter(self.quest_tool.begin, self.quest_tool.verify),
            "USE_ON_TARGET": SkillContractAdapter(self.quest_item.begin, self.quest_item.verify),
            "ASSIST": SkillContractAdapter(self.quest_item.begin, self.quest_item.verify),
            "FOLLOW_INSTRUCTION": SkillContractAdapter(self.instructed_spell.begin, self.instructed_spell.verify),
        }

    @classmethod
    def handles(cls, skill: str) -> bool:
        return skill in cls.CANONICAL

    def begin(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        return self.contract(state.skill_type).start(state, world_state)

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        return self.contract(state.skill_type).tick(state, world_state, now)

    def contract(self, skill: str) -> SkillContractAdapter:
        try:
            return self._contracts[skill]
        except KeyError as error:
            raise ValueError(f"Unsupported canonical M0 skill: {skill}") from error
