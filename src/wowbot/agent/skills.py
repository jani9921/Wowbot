from __future__ import annotations

import math
from .combat_controller import CombatController
from wowbot.skills.ability_rules import AbilityRuleEngine
from .skill_contracts import CONTRACTS, SkillContract  # noqa: F401  (SkillContract re-exported)
from .skill_availability import SkillAvailabilityMixin
from .skill_commands import SkillCommandsMixin
from .skill_verification import SkillVerificationMixin


class SkillRegistry(SkillVerificationMixin, SkillCommandsMixin, SkillAvailabilityMixin):
    def __init__(self, bindings=None):
        self.bindings = bindings
        self.contracts = {c.name: c for c in CONTRACTS}
        self.turn_rate = math.pi  # Updated from measured facing deltas after short movement arcs.
        self.combat = CombatController(bindings)
        # Pure preview shared with the active CombatSkill and diagnostics. It
        # cannot update the compatibility CombatController or send input.
        self._ability_rules = AbilityRuleEngine(bindings)
        self.combat_uses = self.combat.uses  # compatibility/read-only diagnostics alias

