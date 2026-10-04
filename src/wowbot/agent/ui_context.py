"""Unified UiContext resolver (V4-011).

``WorldUiReducer`` already emits per-surface UI_OPENED/UI_CLOSED transition
events from a scatter of booleans. This module adds the spec's missing
single typed snapshot -- primary_panel + overlays[] + blocking_state +
confidence -- so a skill can react to ``blocking_state`` first instead of
re-deriving priority from individual flags every time.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class PrimaryPanel(StrEnum):
    WORLD = "WORLD"
    MAP = "MAP"
    QUEST_LOG = "QUEST_LOG"
    GOSSIP = "GOSSIP"
    QUEST_OFFER = "QUEST_OFFER"
    QUEST_COMPLETE = "QUEST_COMPLETE"
    QUEST_REWARD = "QUEST_REWARD"
    LOOT = "LOOT"
    VENDOR = "VENDOR"
    DIALOG = "DIALOG"
    POPUP = "POPUP"
    SPECIAL_UI = "SPECIAL_UI"
    UNKNOWN = "UNKNOWN"


class BlockingState(StrEnum):
    NONE = "NONE"
    LOADING = "LOADING"
    CINEMATIC = "CINEMATIC"
    DISCONNECTED = "DISCONNECTED"
    PLAYER_DEAD = "PLAYER_DEAD"
    VEHICLE_OVERRIDE = "VEHICLE_OVERRIDE"
    SCRIPTED_LOCK = "SCRIPTED_LOCK"


@dataclass(frozen=True, slots=True)
class UiContext:
    primary_panel: PrimaryPanel
    overlays: tuple[str, ...]
    blocking_state: BlockingState
    confidence: float


# blocking_state resolution priority -- "a skill must react to
# blocking_state first", so this is checked before any panel/overlay.
_BLOCKING_CHECKS: tuple[tuple[BlockingState, str], ...] = (
    (BlockingState.DISCONNECTED, "disconnected"),
    (BlockingState.PLAYER_DEAD, "is_dead"),
    (BlockingState.LOADING, "loading"),
    (BlockingState.CINEMATIC, "cinematic_playing"),
    (BlockingState.VEHICLE_OVERRIDE, "vehicle_ui"),
    (BlockingState.SCRIPTED_LOCK, "scripted_lock"),
)

_PANEL_CHECKS: tuple[tuple[PrimaryPanel, str], ...] = (
    (PrimaryPanel.QUEST_OFFER, "quest_offer_open"),
    (PrimaryPanel.QUEST_COMPLETE, "quest_complete_open"),
    (PrimaryPanel.QUEST_REWARD, "quest_reward_open"),
    (PrimaryPanel.GOSSIP, "gossip_open"),
    (PrimaryPanel.LOOT, "loot_ui_open"),
    (PrimaryPanel.VENDOR, "vendor_ui_open"),
    (PrimaryPanel.MAP, "world_map_open"),
    (PrimaryPanel.QUEST_LOG, "quest_log_open"),
    (PrimaryPanel.DIALOG, "quest_ui_open"),
    (PrimaryPanel.POPUP, "popup_open"),
    (PrimaryPanel.SPECIAL_UI, "special_ui_open"),
)

_OVERLAY_KEYS: tuple[tuple[str, str], ...] = (
    ("quest_tool_button", "quest_tool_button_visible"),
    ("extra_action_button", "extra_action_button_visible"),
    ("confirmation_popup", "confirmation_popup_visible"),
    ("tutorial_popup", "tutorial_popup_visible"),
    ("objective_popup", "objective_popup_visible"),
    ("field_complete_quest_button", "field_complete_quest_button_visible"),
)


def _flag(state: Mapping[str, Any], key: str) -> bool:
    value = state.get(key)
    if isinstance(value, Mapping):
        return bool(value.get("open"))
    return bool(value)


def resolve_ui_context(state: Mapping[str, Any]) -> UiContext:
    """Resolve one typed ``UiContext`` snapshot from a flat state dict."""
    blocking_state = BlockingState.NONE
    for candidate, key in _BLOCKING_CHECKS:
        if _flag(state, key):
            blocking_state = candidate
            break

    if blocking_state is not BlockingState.NONE:
        # A hard block owns the frame; panel identity beneath it is not
        # confidently resolvable from this snapshot alone.
        primary_panel = PrimaryPanel.UNKNOWN
        confidence = 0.9
    else:
        primary_panel = PrimaryPanel.WORLD
        confidence = 0.6
        for candidate, key in _PANEL_CHECKS:
            if _flag(state, key):
                primary_panel = candidate
                confidence = 0.85
                break

    overlays = tuple(name for name, key in _OVERLAY_KEYS if _flag(state, key))
    return UiContext(primary_panel, overlays, blocking_state, confidence)


class UiContextResolver:
    """Stateful canonical UI resolver with monotonic transition checks."""

    def __init__(self) -> None:
        self._context = UiContext(PrimaryPanel.UNKNOWN, (), BlockingState.NONE, 0.0)
        self._observed_at: float | None = None
        self._stable_since: float | None = None
        self._valid = False

    @property
    def current(self) -> UiContext:
        return self._context

    def resolve(self, observations: Mapping[str, Any], *, observed_at: float) -> UiContext:
        at = float(observed_at)
        if self._observed_at is not None and at < self._observed_at:
            return self._context
        candidate = resolve_ui_context(observations)
        if not self._valid or candidate != self._context:
            self._stable_since = at
        self._context = candidate
        self._observed_at = at
        self._valid = True
        return candidate

    def is_blocking(self) -> bool:
        return not self._valid or self._context.blocking_state is not BlockingState.NONE

    def stable_for(self, milliseconds: float, *, now: float) -> bool:
        if not self._valid or self._stable_since is None:
            return False
        elapsed = max(0.0, float(now)-self._stable_since)
        return elapsed + 1e-9 >= max(0.0, float(milliseconds))/1000.0

    def can_accept_quest(self) -> bool:
        return (not self.is_blocking()
                and self._context.primary_panel is PrimaryPanel.QUEST_OFFER
                and self._context.confidence >= .75)

    def can_turnin(self) -> bool:
        return (not self.is_blocking()
                and self._context.primary_panel in {
                    PrimaryPanel.QUEST_COMPLETE, PrimaryPanel.QUEST_REWARD}
                and self._context.confidence >= .75)

    def can_interact_world(self) -> bool:
        return not self.is_blocking() and self._context.primary_panel is PrimaryPanel.WORLD

    def invalidate(self) -> None:
        self._context = UiContext(PrimaryPanel.UNKNOWN, (), BlockingState.NONE, 0.0)
        self._observed_at = None
        self._stable_since = None
        self._valid = False
