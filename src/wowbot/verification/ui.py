"""Pure UI-panel-state postcondition evaluation (V4-040)."""
from __future__ import annotations

from typing import Any

from wowbot.runtime import FailureReason, VerificationResult


class UiPanelVerifier:
    """Evaluate whether a named UI panel opened or closed as expected.

    ``panel_key`` names the same state sub-surfaces ``world_ui_reducer.py``
    already reads (e.g. ``"quest_ui"``, ``"gossip_ui"``, ``"vendor_ui"``,
    ``"world_map"``). No input, no controller mutation, no retries, no
    planner calls -- only a before/after comparison.
    """

    def evaluate(self, before: dict[str, Any], after: dict[str, Any], *,
                panel_key: str, expect_open: bool) -> VerificationResult:
        before_open = self._is_open(before, panel_key)
        after_open = self._is_open(after, panel_key)
        if after_open == expect_open:
            transitioned = before_open != after_open
            confidence = .9 if transitioned else .6
            evidence = ("panel_transitioned",) if transitioned else ("panel_already_in_expected_state",)
            return VerificationResult(True, confidence, None, evidence)
        return VerificationResult(False, .0, FailureReason.WRONG_UI)

    @staticmethod
    def _is_open(state: dict[str, Any], panel_key: str) -> bool:
        panel = state.get(panel_key)
        if isinstance(panel, dict):
            return bool(panel.get("open"))
        return bool(state.get(f"{panel_key}_open"))
