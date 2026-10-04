"""Shared verifier contract (V4-040).

A verifier only evaluates evidence/deltas: it sends no input, mutates no
controller state, performs no retries, and never calls back into the
planner. Every verifier in this package (``combat.py``, ``interaction.py``,
``loot.py``, ``quest.py``, ``movement.py``, ``ui.py``) already follows the
same ``evaluate(before, after, **kwargs) -> VerificationResult`` shape; this
module names that shape once as a structural ``Protocol`` so a new verifier
has something to type against instead of re-discovering the convention.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from wowbot.runtime import VerificationResult


@runtime_checkable
class Verifier(Protocol):
    """Structural contract every M0 verifier satisfies.

    ``before``/``after`` are already-captured state snapshots -- never a
    live query. Implementations must not send input, mutate a controller,
    retry, or call the planner; they only compare two snapshots and typed
    evidence into one ``VerificationResult``.
    """

    def evaluate(self, before: dict[str, Any], after: dict[str, Any],
                **kwargs: Any) -> VerificationResult:
        ...
