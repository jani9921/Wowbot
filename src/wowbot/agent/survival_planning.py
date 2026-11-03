"""Out-of-combat readiness before a new pull (REV4 survival supplement 2026-10-30).

``docs/reform/rev4-20261029/input/STATUSZ_ES_TULELES_KIEGESZITES_20261030_HU.md``:
with low health the agent regenerates (keeping its quest goal) before it
starts another fight. Start and finish thresholds differ, so it never
alternates between resting and attacking. It is never demanded at every
pull, and it never blocks defending an attacked character.

Own health is the selected character's fresh field evidence only. On 12.1 the
addon reads ``UnitHealth("player")`` as a secret value, so the value is the
server's (Ymir CREATE/VALUES). VALUES arrive on change only, so a full or
unchanged health turns UNKNOWN two seconds later. UNKNOWN never becomes 100 %:
after a low reading without newer evidence the agent keeps resting instead
of pulling; with no low reading it cannot tell a full bar from no data.

Food is not chosen here yet: it needs a verified food item (identity,
effect, count, requirements) and an active binding or visible bag UI.
"""
from __future__ import annotations

from .models import Proposal, number

REST_START_FRACTION = .45
REST_END_FRACTION = .9
PRIORITY = 112.
# A rest that saw no regeneration (bounded, the skill's no-rise window)
# must not loop: the next one waits this long, the quest goes on.
NO_REGEN_RETRY_SECONDS = 30.
# New pulls a low/unknown-after-low health withholds. Defence, looting,
# talking and travel stay.
NEW_PULL_PURPOSES = frozenset({"APPROACH_SERVER_KILL_TARGET"})


def own_health_fraction(state: dict) -> float | None:
    """Fresh own health / max health, else None (UNKNOWN, never 100 %).

    Packet health is projected into ``state`` only while its field resolution
    is KNOWN (``packet_own_health.selected_fields``); an addon number counts
    only with its own sample time within the same two seconds.
    """
    health, maximum = number(state.get("health")), number(state.get("max_health"))
    if health is None or maximum is None or maximum <= 0 or health < 0:
        return None
    selected = ((state.get("packet_own_health") or {}).get("selected_fields") or {})
    if not {"health", "max_health"} <= set(selected):
        sample, now = number(state.get("health_sample_time")), number(state.get("monotonic_time"))
        if sample is None or now is None or not 0 <= now-sample <= 2.:
            return None
    return min(1., health/maximum)


def threatened(state: dict) -> bool:
    if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost"):
        return True
    from .packet_entity_facts import attackers
    return bool(attackers(state))


def escort_active(state: dict) -> bool:
    """An escorted unit in view moves on; resting here would lose it."""
    from .escort_planning import escort_objectives, escort_subject
    return any(escort_subject(state, row) is not None for _, row in escort_objectives(state))


class ReadinessPolicy:
    """Hysteretic REST before new pulls; the one place that withholds them."""

    def __init__(self) -> None:
        self.resting = False
        self.last_known: tuple[float, float] | None = None     # (fraction, at)
        self.retry_at = 0.
        self.scope = None
        self.noted = None

    def _observe(self, state: dict, now: float) -> float | None:
        scope = (state.get("session_id"), state.get("character_guid"))
        if scope != self.scope:
            self.scope, self.resting, self.last_known, self.retry_at = scope, False, None, 0.
        fraction = own_health_fraction(state)
        if fraction is not None:
            self.last_known = (fraction, now)
        return fraction

    def assess(self, state: dict, now: float) -> dict:
        fraction = self._observe(state, now)
        if threatened(state):
            self.resting = False
            return {"state": "THREATENED", "health_fraction": fraction}
        if fraction is None:
            low = self.last_known is not None and self.last_known[0] < REST_START_FRACTION
            if low or self.resting:
                # No evidence of recovery since a low reading.
                return {"state": "REST", "health_fraction": None, "reason": "unknown_after_low_health",
                        "last_known_fraction": round(self.last_known[0], 3) if self.last_known else None}
            return {"state": "UNKNOWN", "health_fraction": None}
        if self.resting and fraction >= REST_END_FRACTION or not self.resting and fraction >= REST_START_FRACTION:
            self.resting = False
            return {"state": "READY", "health_fraction": fraction}
        self.resting = True
        return {"state": "REST", "health_fraction": fraction, "reason": "low_health"}

    def note_result(self, result: dict | None, now: float) -> None:
        """The engine's last terminal projection, each one counted once."""
        result = result or {}
        key = (result.get("action_id"), result.get("skill"), result.get("outcome"), result.get("reason"))
        if result.get("skill") != "REST" or key == self.noted:
            return
        self.noted = key
        outcome = str(result.get("outcome") or "").upper()
        if outcome.endswith("SUCCESS"):
            self.resting = False
        elif outcome.endswith("FAILURE"):
            # No regeneration seen, or the bounded window ran out (an
            # interruption is CANCELLED, not FAILURE).
            self.retry_at = now + NO_REGEN_RETRY_SECONDS
            self.resting = False

    def apply(self, proposals: list[Proposal], state: dict, now: float,
              last_result: dict | None = None) -> list[Proposal]:
        """Add the REST proposal and withhold new pulls while resting."""
        self.note_result(last_result, now)
        readiness = self.assess(state, now)
        if readiness["state"] != "REST" or escort_active(state):
            return proposals
        kept = [proposal for proposal in proposals if not self.new_pull(proposal, state)]
        if now < self.retry_at:
            # The last rest saw no regeneration: bounded, no rest/pull loop.
            return proposals
        fraction = readiness.get("health_fraction")
        kept.append(Proposal.make(
            "REST", "Kevés élet harcon kívül: regenerálódás az új támadás előtt",
            {"purpose": "PRE_PULL_REGENERATION", "reason": readiness.get("reason"),
             "health_fraction": None if fraction is None else round(fraction, 3),
             "start_fraction": REST_START_FRACTION, "end_fraction": REST_END_FRACTION},
            confidence=.9, priority=PRIORITY, evidence=("own_health_field_evidence",)))
        return kept

    @staticmethod
    def new_pull(proposal: Proposal, state: dict) -> bool:
        params = proposal.parameters
        if proposal.skill == "COMBAT" and not state.get("is_in_combat"):
            return True
        if proposal.skill == "TARGET" and params.get("activation_source") == "TAB_SERVER_GUID":
            return True
        return proposal.skill == "MOVE" and params.get("purpose") in NEW_PULL_PURPOSES
