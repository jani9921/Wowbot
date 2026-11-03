"""Deterministic M0 skill FSMs backed by ActiveSkillRuntime state."""

from .target import TargetSkill
from .interact import InteractSkill
from .interaction_result import InteractionEffectKind, InteractionResultClassifier, InteractionResultKind
from .action_error_correlation import AbilityAttempt, AbilityCorrelation, ActionErrorCorrelator
from wowbot.combat.ability.contracts import (AbilityCandidate, AbilityDefinition, AbilityRule,
                                             AbilityRuntimeState, AbilityTag)
from wowbot.combat.ability.evaluator import AbilityRuleEngine
from .combat import CombatSkill
from .defend_wait import DefendWaitPhase, DefendWaitSkill
from .rest import RestPhase, RestSkill
from .loot import LootSkill
from .object_use import ObjectUseSkill
from .quest_dialog import QuestDialogSkill
from .field_turnin import FieldTurnInPhase, FieldTurnInSkill
from .quest_tool import ExtraActionHandler, QuestToolSkill
from .quest_item import QuestItemSkill, UseItemPhase, UseItemSkill
from .instructed_spell import InstructedSpellSkill
from .movement import MovementSkillRunner, MovementStep
from .interaction_runtime import InteractionRuntimeRunner, InteractionRuntimeStep
from .combat_runtime import CombatRuntimeRunner, CombatRuntimeStep
from .loot_runtime import LootRuntimeRunner, LootRuntimeStep
from .visual_runtime import VisualRuntimeRunner, VisualRuntimeStep
from .vehicle import VehiclePhase, VehicleSkill, is_vehicle_override_active, rotation_allowed

__all__ = ("AbilityAttempt", "AbilityCorrelation", "AbilityCandidate", "AbilityDefinition", "AbilityRule", "AbilityRuleEngine", "AbilityRuntimeState", "AbilityTag", "ActionErrorCorrelator", "CombatRuntimeRunner", "CombatRuntimeStep", "CombatSkill", "DefendWaitPhase", "DefendWaitSkill", "ExtraActionHandler", "FieldTurnInPhase", "FieldTurnInSkill", "InstructedSpellSkill", "InteractSkill", "InteractionEffectKind", "InteractionResultClassifier", "InteractionResultKind", "InteractionRuntimeRunner", "InteractionRuntimeStep", "LootRuntimeRunner", "LootRuntimeStep", "LootSkill", "MovementSkillRunner", "MovementStep", "ObjectUseSkill", "QuestDialogSkill", "QuestItemSkill", "UseItemPhase", "UseItemSkill", "QuestToolSkill", "RestPhase", "RestSkill", "SearchSkill", "TargetSkill", "VehiclePhase", "VehicleSkill", "VisualApproachSkill", "VisualRuntimeRunner", "VisualRuntimeStep", "is_vehicle_override_active", "rotation_allowed",)


def __getattr__(name):
    from importlib import import_module
    modules = {"SearchSkill": ".search", "VisualApproachSkill": ".visual_approach"}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(modules[name], __name__), name)
    globals()[name] = value
    return value
