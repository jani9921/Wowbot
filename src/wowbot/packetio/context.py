"""Pure addon context/GUID checks shared by sensor adapter and world reducer."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
import re

from wowbot.context_contracts import ContextState, SessionContext, SessionIdentity, WorldContext


def reported_game_build(state):
    value = state.get("game_build")
    if type(value) not in {str, int}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class AddonContextEvaluation:
    state: ContextState
    reason: str
    missing_fields: tuple[str, ...] = ()
    session_id: str | None = None
    character_guid: str | None = None
    game_build: int | None = None
    world: WorldContext | None = None

    def bind(self, selected_pid: int) -> SessionContext | None:
        if self.state is not ContextState.VALID:
            return None
        try:
            return SessionContext(SessionIdentity(selected_pid, self.session_id,
                                                  self.character_guid, self.game_build), self.world)
        except ValueError:
            return None


def evaluate_addon_context(state):
    """Validate logical fields without inventing a PID, phase or clock.

    Build/layout eligibility stays packet policy. This is the existing addon
    bootstrap facade, not an independent session provider.
    """
    from .builds import VERIFIED_OPCODE_BUILDS
    if not isinstance(state, Mapping):
        return AddonContextEvaluation(ContextState.MISMATCH, "invalid_addon_context")
    build = reported_game_build(state)
    if build is None:
        if state.get("game_build") in (None, ""):
            return AddonContextEvaluation(ContextState.PENDING, "waiting_for_addon_context", ("game_build",))
        return AddonContextEvaluation(ContextState.MISMATCH, "invalid_addon_context")
    if build not in VERIFIED_OPCODE_BUILDS:
        return AddonContextEvaluation(ContextState.MISMATCH, "unsupported_game_build", game_build=build)
    point = state.get("player_world_position")
    if point is None:
        point = {}
    if not isinstance(point, Mapping):
        return AddonContextEvaluation(ContextState.MISMATCH, "invalid_addon_context", game_build=build)
    fields = {"session_id": state.get("session_id"), "character_guid": state.get("character_guid"),
              "map_id": state.get("map_id"), "player_world_position.instance_id": point.get("instance_id")}
    missing = tuple(key for key, value in fields.items() if value is None or value == "")
    if missing or state.get("loading") or state.get("player_present") is False:
        return AddonContextEvaluation(ContextState.PENDING, "waiting_for_addon_context", missing, game_build=build)
    session, character = state["session_id"], state["character_guid"]
    try:
        if type(session) is not str or not session.strip() or type(character) is not str or not character.strip():
            raise ValueError("invalid identity")
        world = WorldContext(point["instance_id"], state["map_id"], state.get("phase"))
    except ValueError:
        return AddonContextEvaluation(ContextState.MISMATCH, "invalid_addon_context", game_build=build)
    return AddonContextEvaluation(ContextState.VALID, "ready", session_id=session,
                                  character_guid=character, game_build=build, world=world)


def addon_context_status(state):
    return evaluate_addon_context(state).reason


def addon_context(state, pid):
    context = evaluate_addon_context(state).bind(pid)
    return context.as_dict() if context else None


def same_player(raw_guid, addon_guid):
    """WPP WowGuid128 Player: type high>>58 == 2, realm (high>>42)&0x1FFF.

    Only the full Player low value and realm can match. No vehicle/name/
    proximity shortcut can turn another mover into the controlled character.
    """
    if not isinstance(raw_guid, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", raw_guid):
        return False
    player = re.fullmatch(r"Player-(\d+)-([0-9A-Fa-f]{1,16})", str(addon_guid or ""))
    if not player:
        return False
    high, low = int(raw_guid[:16], 16), int(raw_guid[16:], 16)
    return high >> 58 == 2 and (high >> 42) & 0x1FFF == int(player[1]) and low == int(player[2], 16)


_ADDON_ENTITY_KINDS = {7: "Conversation", 8: "Creature", 9: "Vehicle", 11: "GameObject"}


def addon_entity_guid(raw_guid):
    """WowGuid128 of a creature/vehicle/game object -> the addon UnitGUID text.

    Live 2026-10-19: the same session's addon and Ymir capture agreed on
    Creature-0-1465-2175-71046-156800-0000D3399A (Quartermaster Richter) and
    Creature-0-1465-2175-71046-245394-000053399A (Captain Garrick). Players
    and pets return None: they never become packet entity facts.
    """
    if not isinstance(raw_guid, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", raw_guid):
        return None
    high, low = int(raw_guid[:16], 16), int(raw_guid[16:], 16)
    kind = _ADDON_ENTITY_KINDS.get(high >> 58)
    if kind is None:
        return None
    return (f"{kind}-0-{(high >> 42) & 0x1FFF}-{guid_map_id(raw_guid)}-{low >> 40}"
            f"-{(high >> 6) & 0x7FFFFF}-{low & 0xFFFFFFFFFF:010X}")


def guid_map_id(raw_guid):
    return (int(raw_guid[:16], 16) >> 29) & 0x1FFF
