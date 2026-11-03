"""Pure, shared freshness guard for explicitly addressed quest UI actions."""
from __future__ import annotations

import math
import re

from .models import number


FAST_BUTTON_ACTIONS = frozenset({"CONTINUE", "COMPLETE", "TURN_IN"})

_GOSSIP_COLOR = re.compile(r"\|c[0-9a-f]{8}|\|cn[A-Z0-9_]+:|\|r", re.IGNORECASE)
_QUEST_OPTION = re.compile(r"^\s*\(quest\)(?:\s|$)", re.IGNORECASE)


def quest_option_marked(option: dict) -> bool:
    """Prefer Retail's explicit label flag; otherwise prove a same-row prefix."""
    # The read-only addon resolves QuestLabelPrepend with the client's own
    # Enum and FlagsUtil. A known false flag outranks stale/decorated text;
    # absent evidence keeps older addon snapshots on the guarded text path.
    api_label = option.get("quest_label_prepend")
    if isinstance(api_label, bool):
        return api_label

    def plain(value):
        text = _GOSSIP_COLOR.sub("", str(value or ""))
        text = re.sub(r"\|T.*?\|t|\|A.*?\|a", "", text)
        return " ".join(text.split())
    name = plain(option.get("name"))
    if _QUEST_OPTION.match(name):
        return True
    displayed = plain(option.get("display_name"))
    marker = _QUEST_OPTION.match(displayed)
    return bool(name and marker and displayed[marker.end():].strip().casefold() == name.casefold())


def fast_button_matches(state: dict, params: dict, *, received_now: float | None) -> bool:
    """Only a co-sampled FAST button can outlive paged quest-detail data.

    This is not acceptance/quest-credit evidence, and cannot authorize row
    or reward selection. The skill rechecks the same proof at dispatch.
    """
    proof = state.get("quest_ui_fast_evidence") or {}
    ui = state.get("quest_ui") or {}
    now, sampled = number(state.get("monotonic_time")), number(proof.get("sample_time"))
    received, receive_clock = number(proof.get("received_at")), number(received_now)
    if (now is None or sampled is None or not math.isfinite(now) or not math.isfinite(sampled)
            or not 0 <= now-sampled <= .75
            or received is None or receive_clock is None
            or not math.isfinite(received) or not math.isfinite(receive_clock)
            or not 0 <= receive_clock-received <= .75
            or not state.get("session_id") or proof.get("session_id") != state["session_id"]
            or proof.get("open") is not True or ui.get("open") is not True
            or state.get("quest_ui_open") is False):
        return False
    action = str(params.get("action") or "").upper()
    if (action not in FAST_BUTTON_ACTIONS or str(proof.get("action") or "").upper() != action
            or str(ui.get("action") or "").upper() != action):
        return False
    quest_id = number(params.get("quest_id"))
    if (quest_id is None or not math.isfinite(quest_id) or quest_id <= 0
            or str(proof.get("quest_id")) != str(params.get("quest_id"))
            or str(ui.get("quest_id")) != str(params.get("quest_id"))):
        return False
    for axis in ("x", "y"):
        point = [number(row.get(axis)) for row in (params, proof, ui)]
        if (any(value is None or not math.isfinite(value) or not 0 < value < 1 for value in point)
                or max(point)-min(point) > .002):
            return False
    return True


def dialog_evidence_allows(state: dict, params: dict, *, received_now: float | None = None) -> bool:
    age = number(state.get("state_age", 0))
    if age is None or not math.isfinite(age) or age < 0:
        return False
    return age <= 2. or fast_button_matches(state, params, received_now=received_now)


def dialog_recipient(state: dict) -> dict:
    """Current owned NPC UI identity, or a fresh selected NPC when unowned.

    A gossip window can stay open after the game clears the hard target.
    Its explicit addon NPC GUID is then the UI owner, not a guessed target.
    This helper never changes selection or supplies a made-up friendliness
    flag. Contradicting/removed identities and stale detail are rejected.
    """
    from wowbot.runtime.entity_identity import check_entity_identity, guid_template, world_entity_id
    from wowbot.runtime.skill_identity import sample_fresh
    from .quest_semantics import friendly_live_npc

    ui = state.get("quest_ui") or {}
    if (not (ui.get("open") is True or state.get("quest_ui_open") is True)
            or not dialog_evidence_allows(state, {"action": "GOSSIP_OPTION_SELECT"})):
        return {}
    target = state.get("target") or {}
    owner = ui.get("npc_guid", state.get("quest_ui_npc_guid"))
    now = number(state.get("monotonic_time"))
    if ((now is None and any(state.get(key) for key in ("transport_kind", "telemetry_lane", "protocol_version")))
            or (now is not None and not math.isfinite(now))):
        return {}
    selected_fresh = now is None or sample_fresh(state, "target", now)
    if owner not in (None, False, "", 0, "0"):
        guid = world_entity_id(owner)
        if not guid:
            return {}
        entity = (state.get("packet_entities") or {}).get(str(guid)) or {}
        if entity.get("removed"):
            return {}
        if selected_fresh and str(target.get("guid") or "") == str(guid):
            if not check_entity_identity({"guid": guid}, target):
                return {}
            if (target.get("dead", target.get("is_dead")) is True
                    or target.get("attackable", target.get("is_attackable")) is True):
                return {}
            if friendly_live_npc(target):
                return {**target, "dialog_identity_source": "QUEST_UI_OWNER"}
        fields = guid_template(guid)
        if str(guid).startswith(("Creature-", "Vehicle-")) and fields.get("npc_id"):
            return {"guid": str(guid), **fields, "dialog_identity_source": "QUEST_UI_OWNER"}
        return {}
    return dict(target) if selected_fresh and friendly_live_npc(target) else {}
