"""Generic handling of a ridden vehicle's / override bar's abilities.

User 2026-10-04: there are hundreds of quest vehicles and every one has
different abilities ("nem mindegyikbe trample van").  Nothing here is keyed
to one vehicle or spell.  An ability's *use mode* comes from what the client
shows about it and from what it was observed to do:

* ``FORWARD_DASH`` -- the vehicle lunges straight ahead along its facing
  (charge/trample/ram...).  Aim first, then press: the dash is the move, and
  whatever is in the way is hit.  Learned when a press moved the vehicle
  several yards forward (live: Giant Boar Trample, ~30 yd in 2 s).
* ``TARGETED`` -- the client reports a positive max range: select the unit,
  get in range, press.
* ``CLOSE`` -- around-you / melee style, or not yet known: close in first.

Order: learned effect > tooltip description > spell range.  The description
is the addon's live ``C_Spell.GetSpellDescription`` text (0.9.50), not
reference data.
"""
from __future__ import annotations

import math
import re

from .models import number

FORWARD_DASH, TARGETED, CLOSE = "FORWARD_DASH", "TARGETED", "CLOSE"

_DASH = re.compile(r"\b(charg\w*|dash\w*|rush\w*|lunge\w*|leap\w*|ram|rams|ramming|trampl\w*|"
                   r"stampede\w*|gallop\w*|barrel\w*|plow\w*|forward|ahead)\b")
_AROUND = re.compile(r"\b(around (?:you|the \w+)|nearby|within \d+ (?:yards|yds)|"
                     r"stomp\w*|slam\w* the ground|whirl\w*|spin\w*)\b")
_NOT_ATTACK = re.compile(r"\b(eject|exit|leave|dismount|heal\w*|shield\w*|repair\w*|"
                         r"speed boost|cancel)\b")

DASH_MIN_YARDS = 6.          # forward displacement after a press that proves a dash


def _text(action: dict) -> str:
    return " ".join(str(action.get(key) or "") for key in ("name", "description")).casefold()


def ability_mode(action: dict, learned: dict | None = None, advice: dict | None = None) -> str:
    """Learned effect > explicit tooltip words > local-LLM reading > range.

    The LLM only decides what the deterministic text rules leave open
    (master v4 0.3); benchmark 2026-10-04: llama3.2:3b once read Trample's
    "charge forward" as CLOSE.
    """
    effect = (learned or {}).get(str(action.get("id")))
    if isinstance(effect, dict) and effect.get("mode"):
        return str(effect["mode"])
    text = _text(action)
    if _DASH.search(text) and not _AROUND.search(text):
        return FORWARD_DASH
    if _AROUND.search(text):
        return CLOSE
    hint = (advice or {}).get(str(action.get("id")))
    if isinstance(hint, dict) and hint.get("mode") in {FORWARD_DASH, TARGETED, CLOSE}:
        return str(hint["mode"])
    if (number(action.get("max_range")) or 0.) > 0.:
        return TARGETED
    return CLOSE


def vehicle_actions(state: dict) -> list[dict]:
    if not state.get("vehicle_controls"):
        return []
    return [action for action in state.get("actionbar") or ()
            if isinstance(action, dict) and action.get("source") == "VEHICLE_BAR"
            and str(action.get("action") or "").startswith("ACTIONBUTTON")]


def ready(action: dict) -> bool:
    return (action.get("is_usable") is not False
            and (number(action.get("cooldown_remaining")) or 0.) <= .1)


def choose_attack_action(state: dict, learned: dict | None = None,
                         advice: dict | None = None, preferred=()) -> dict | None:
    """The vehicle ability to use on an objective unit, or None.

    Defensive/utility buttons (eject, heal, shield...) are skipped; among the
    rest an ability that is known/likely to damage comes first, then bar
    order (the main attack is conventionally button 1).
    """
    def utility(action: dict) -> bool:
        hint = (advice or {}).get(str(action.get("id"))) or {}
        return (hint.get("mode") in {"NOT_ATTACK", "SELF_BUFF"}
                or bool(_NOT_ATTACK.search(_text(action))))

    candidates = [action for action in vehicle_actions(state)
                  if ready(action) and not utility(action)]
    if not candidates:
        return None
    preferred_names = {str(name).casefold() for name in preferred or () if name}

    def rank(item):
        index, action = item
        harmful = action.get("is_harmful") is True
        learned_attack = bool((learned or {}).get(str(action.get("id")), {}).get("hit"))
        advised_attack = ((advice or {}).get(str(action.get("id"))) or {}).get("attack") is True
        # An NPC named it ("...so it can trample all of those monsters flat").
        named = str(action.get("name") or "").casefold() in preferred_names
        return (0 if learned_attack else 1, 0 if named else 1, 0 if harmful or advised_attack else 1, index)

    return min(enumerate(candidates), key=rank)[1]


def forward_displacement(before: dict, after: dict) -> tuple[float, float] | None:
    """(forward yards, total yards) moved between two states, or None."""
    a = before.get("player_world_position") or {}
    b = after.get("player_world_position") or {}
    facing = number(before.get("orientation"))
    if None in (number(a.get("x")), number(a.get("y")), number(b.get("x")), number(b.get("y")), facing):
        return None
    dx, dy = float(b["x"])-float(a["x"]), float(b["y"])-float(a["y"])
    return dx*math.cos(facing)+dy*math.sin(facing), math.hypot(dx, dy)


def learn_effect(learned: dict, action_id, before: dict, after: dict, *,
                 hit: bool = False) -> str | None:
    """Record what pressing ``action_id`` did; return the learned mode."""
    if action_id is None:
        return None
    entry = learned.setdefault(str(action_id), {"samples": 0})
    entry["samples"] = int(entry.get("samples") or 0)+1
    if hit:
        entry["hit"] = True
    moved = forward_displacement(before, after)
    if moved is not None:
        forward, total = moved
        if forward >= DASH_MIN_YARDS and forward >= .7*total:
            entry.update(mode=FORWARD_DASH, dash_yards=round(max(forward, number(entry.get("dash_yards")) or 0.), 1))
    return entry.get("mode")


def aim_tolerance(width_fraction: float | None) -> float:
    """Screen centre-line tolerance: the box must straddle the facing line."""
    return max(.03, min(.08, .4*(width_fraction or .1)))
