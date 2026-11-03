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

Order: learned effect > the spell's client DB2 effects > tooltip description
> local LLM > spell range.  The DB2 is structural and language-free (user
2026-10-26: "van még 1 rahedli vehicle ... magától csinálja mindet"):
charge/leap/jump to the caster's front is a dash, damage at the selected
target is targeted, damage around the caster or in a cone is close.  A
server-scripted button (Trample 305556 is a bare DUMMY) shows its effect
in the spells the vehicle casts right after the press (321627, CHARGE_DEST
to the front, 30 yd); those are learned as ``follow_up`` and read the same
way.  The description is the addon's live ``C_Spell.GetSpellDescription``
text (0.9.50), not reference data; its word list is only the fallback.
"""
from __future__ import annotations

from functools import lru_cache
import math
import re

from .models import Proposal, number

FORWARD_DASH, TARGETED, CLOSE = "FORWARD_DASH", "TARGETED", "CLOSE"

# Client DB2 SpellEffect numbering (SpellEffectName / Targets as decoded;
# checked 2026-10-26 on the 12.1 tables: CHARGE 533x "target enemy",
# CHARGE_DEST 146x "caster front", LEAP with "caster front"/"front leap").
_MOVE_EFFECTS = {29, 41, 42, 96, 149}            # LEAP, JUMP, JUMP_DEST, CHARGE, CHARGE_DEST
_HARM_EFFECTS = {1, 2, 9, 17, 31, 58, 98, 121, 144}   # kill/damage/leech/weapon/knockback
_TRIGGER_EFFECTS = {64, 140, 142, 151}           # trigger / force-cast: same caster, now
_MISSILE_EFFECTS = {32, 148}                     # what they trigger lands at the impact
_APPLY_AURA, _PERIODIC_TRIGGER = 6, 23
_HARM_AURAS = {3, 89}                            # PERIODIC_DAMAGE(_PERCENT): Call of Life's cone
_FRONT = {47, 55, 78}                            # DEST_CASTER_FRONT, ..._FRONT_LEAP, DEST_DEST_FRONT
_AT_TARGET = {6, 25, 53, 63, 89}                 # UNIT/DEST_TARGET_ENEMY/ANY, DEST_TRAJ (aimed missile)
_AREA = {7, 8, 15, 16, 24, 54}                   # area around caster / its cone in front
_TRAJECTORY = 89                                 # DEST_TRAJ: flown along the caster's pitch
CHAIN_DEPTH = 3

_DASH = re.compile(r"\b(charg\w*|dash\w*|rush\w*|lunge\w*|leap\w*|ram|rams|ramming|trampl\w*|"
                   r"stampede\w*|gallop\w*|barrel\w*|plow\w*|forward|ahead)\b")
_AROUND = re.compile(r"\b(around (?:you|the \w+)|nearby|within \d+ (?:yards|yds)|"
                     r"stomp\w*|slam\w* the ground|whirl\w*|spin\w*)\b")
_NOT_ATTACK = re.compile(r"\b(eject|exit|leave|dismount|heal\w*|shield\w*|repair\w*|"
                         r"speed boost|cancel)\b")
_SPEED_BUFF = re.compile(r"\bmovement speed\b")

DASH_MIN_YARDS = 6.          # forward displacement after a press that proves a dash


def _text(action: dict) -> str:
    return " ".join(str(action.get(key) or "") for key in ("name", "description")).casefold()


def spell_shape(spell_ids, effects_of) -> str | None:
    """FORWARD_DASH / TARGETED / CLOSE from DB2 effects, or None (unknown).

    ``effects_of(spell_id)`` returns ClientCatalog.spell_effects rows.  The
    trigger chain is followed; a movement effect counts only when the caster
    itself performs it (not under a missile's impact)."""
    seen, found = set(), set()

    def walk(spell, depth, via_missile):
        if spell in seen or depth > CHAIN_DEPTH:
            return
        seen.add(spell)
        for effect in effects_of(spell) or ():
            kind, targets = effect.get("effect"), set(effect.get("targets") or ())
            if kind in _MOVE_EFFECTS and not via_missile:
                found.add(FORWARD_DASH if targets & _FRONT else TARGETED if targets & _AT_TARGET else None)
            if (kind in _HARM_EFFECTS or kind in _MISSILE_EFFECTS
                    or (kind == _APPLY_AURA and effect.get("aura") in _HARM_AURAS)):
                found.add(TARGETED if targets & _AT_TARGET else CLOSE if targets & _AREA else None)
            trigger = effect.get("trigger_spell")
            if type(trigger) is int and trigger > 0 and (
                    kind in _TRIGGER_EFFECTS or kind in _MISSILE_EFFECTS
                    or (kind == _APPLY_AURA and effect.get("aura") == _PERIODIC_TRIGGER)):
                walk(trigger, depth+1, via_missile or kind in _MISSILE_EFFECTS)

    for spell in spell_ids:
        if type(spell) is int and spell > 0:
            walk(spell, 0, False)
    return next((mode for mode in (FORWARD_DASH, TARGETED, CLOSE) if mode in found), None)


@lru_cache(maxsize=512)
def _catalog_shape(spell_ids: tuple, path: str, stamp: tuple) -> str | None:
    from wowbot.quests.client_catalog import ClientCatalog
    return spell_shape(spell_ids, ClientCatalog(path).spell_effects)


def db2_mode(spell_ids) -> str | None:
    """spell_shape() from the local client DB2 catalog (cached per file)."""
    from wowbot.quests.client_catalog import default_catalog_path
    ids = tuple(sorted({int(s) for s in spell_ids if str(s).isdigit() and int(s) > 0}))
    path = default_catalog_path()
    try:
        status = path.stat()
    except OSError:
        return None
    return _catalog_shape(ids, str(path), (status.st_mtime_ns, status.st_size)) if ids else None


@lru_cache(maxsize=512)
def _catalog_trajectory(spell_ids: tuple, path: str, stamp: tuple) -> bool:
    from wowbot.quests.client_catalog import ClientCatalog
    catalog = ClientCatalog(path)
    return any(_TRAJECTORY in (effect.get("targets") or ()) for spell in spell_ids
               for effect in catalog.spell_effects(spell))


def db2_trajectory(spell_ids) -> bool:
    """A missile flown along the caster's pitch (DEST_TRAJ): aim it with the
    pitch (live 2026-10-26: Burning Bark at +77 degrees hit nothing)."""
    from wowbot.quests.client_catalog import default_catalog_path
    ids = tuple(sorted({int(s) for s in spell_ids if str(s).isdigit() and int(s) > 0}))
    path = default_catalog_path()
    try:
        status = path.stat()
    except OSError:
        return False
    return bool(ids) and _catalog_trajectory(ids, str(path), (status.st_mtime_ns, status.st_size))


def ability_mode(action: dict, learned: dict | None = None, advice: dict | None = None) -> str:
    """Learned effect > DB2 effects > explicit tooltip words > local LLM > range.

    The LLM only decides what the deterministic rules leave open (master v4
    0.3); benchmark 2026-10-04: llama3.2:3b once read Trample's "charge
    forward" as CLOSE.
    """
    effect = (learned or {}).get(str(action.get("id")))
    if isinstance(effect, dict) and effect.get("mode"):
        return str(effect["mode"])
    follow = effect.get("follow_up") if isinstance(effect, dict) else None
    structural = db2_mode([action.get("id"), *(follow or ())])
    if structural is not None:
        return structural
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
            and (number(action.get("id")) or 0.) > 0.
            and str(action.get("action") or "").startswith("ACTIONBUTTON")]


def ready(action: dict) -> bool:
    return (action.get("is_usable") is not False
            and (number(action.get("cooldown_remaining")) or 0.) <= .1)


def stationary_vehicle_controls(state: dict) -> bool:
    """Utility/unknown vehicle bars do not authorize normal ground input.

    Known harmful/ranged/dash bars retain the existing drivable combat path.
    A newly boarded utility vehicle, even before its full bar arrives, owns
    stationary quest input. No lifecycle or dispatch authority lives here.
    """
    if state.get("in_vehicle") is not True or not state.get("vehicle_controls"):
        return False
    return not any(action.get("is_harmful") is True
                   or (number(action.get("max_range")) or 0.) > 0.
                   or ability_mode(action) == FORWARD_DASH
                   for action in vehicle_actions(state))


def _objective_caption(text) -> tuple[str, ...]:
    text = re.sub(r"^\s*\d+\s*/\s*\d+\s*", "", str(text or ""))
    return tuple(re.findall(r"\w+", text.casefold()))


def stationary_objective_actions(state: dict) -> list[Proposal]:
    """Exact objective caption -> live, non-targeted VEHICLE_ABILITY.

    Existing skill/binding/quest-verification authorities own execution.
    Never choose an unrelated utility button or guess a spell/binding.
    """
    if not stationary_vehicle_controls(state) or state.get("is_casting"):
        return []
    actions = vehicle_actions(state)
    matches = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True or quest.get("quest_id") is None:
            continue
        qid = str(quest["quest_id"])
        for index, objective in enumerate(quest.get("objectives") or ()):
            if not isinstance(objective, dict) or objective.get("is_complete") is True:
                continue
            caption = _objective_caption(objective.get("description"))
            named = [action for action in actions if caption and _objective_caption(action.get("name")) == caption]
            if len(named) != 1:
                continue
            action = named[0]
            oid = str(objective.get("objective_id") or index)
            oid = oid if oid.startswith(qid+":") else qid+":"+oid
            matches.append((quest["quest_id"], oid, action))
    result = []
    for qid, oid, action in matches:
        if (sum(other[2].get("action") == action.get("action") for other in matches) != 1
                or action.get("is_usable") is not True or not ready(action)
                or number(action.get("max_range")) != 0. or action.get("id") is None):
            continue
        result.append(Proposal.make(
            "VEHICLE_ABILITY", "Jármű quest-céljával pontosan egyező, célpont nélküli képesség",
            {"binding": action["action"], "spell_id": action["id"], "target_required": False,
             "require_objective_progress": True, "objective_id": oid, "objective_ids": [oid],
             "quest_id": qid, "quest_ids": [qid], "purpose": "VEHICLE_QUEST_OBJECTIVE"},
            confidence=.95, priority=120, evidence=("live_vehicle_bar_exact_objective_name",)))
    return result


MISS_ROTATE = 4


def entry_of(guid) -> str | None:
    parts = str(guid or "").split("-")
    return parts[5] if len(parts) > 6 and parts[0] in {"Creature", "Vehicle"} else None


def choose_attack_action(state: dict, learned: dict | None = None,
                         advice: dict | None = None, preferred=(), *, require_ready=True) -> dict | None:
    """The vehicle ability to use on an objective unit, or None.

    Defensive/utility buttons (eject, heal, shield...) are skipped; among the
    rest an ability that is known/likely to damage comes first, then bar
    order (the main attack is conventionally button 1).  Per target kind:
    a button that credited on it comes first, and one cast on it MISS_ROTATE
    times without any credit goes last -- a whelp's "fireball at nearby
    weeds" may not touch the insects (2026-10-26).
    """
    target = state.get("target") or {}
    kind = str(target.get("npc_id") or entry_of(target.get("guid")) or "")
    def utility(action: dict) -> bool:
        hint = (advice or {}).get(str(action.get("id"))) or {}
        return (hint.get("mode") in {"NOT_ATTACK", "SELF_BUFF"}
                or bool(_NOT_ATTACK.search(_text(action)))
                or (bool(_SPEED_BUFF.search(_text(action))) and action.get("is_harmful") is not True
                    and db2_mode([action.get("id")]) is None))

    candidates = [action for action in vehicle_actions(state)
                  if (not require_ready or ready(action)) and not utility(action)]
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
        record = (learned or {}).get(str(action.get("id"))) or {}
        hits_here = bool(kind) and kind in (record.get("hit_entries") or ())
        missed_here = (bool(kind) and not hits_here
                       and int((record.get("miss_entries") or {}).get(kind) or 0) >= MISS_ROTATE)
        return (1 if missed_here else 0, 0 if hits_here else 1, 0 if learned_attack else 1,
                0 if named else 1, 0 if harmful or advised_attack else 1, index)

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


FOLLOW_UP_LIMIT = 8


def learn_effect(learned: dict, action_id, before: dict, after: dict, *,
                 hit: bool = False, follow_ups=(), target=None) -> str | None:
    """Record what pressing ``action_id`` did; return the learned mode.

    ``follow_ups``: spells the vehicle/pet cast right after the press (the
    server script's real effect), read through the DB2 by ability_mode."""
    if action_id is None:
        return None
    entry = learned.setdefault(str(action_id), {"samples": 0})
    entry["samples"] = int(entry.get("samples") or 0)+1
    if hit:
        entry["hit"] = True
    kind = entry_of(target)
    if kind and hit:
        entry["hit_entries"] = sorted({*(entry.get("hit_entries") or ()), kind})[:32]
    elif kind:
        misses = entry.setdefault("miss_entries", {})
        misses[kind] = int(misses.get(kind) or 0) + 1
    extra = [int(s) for s in follow_ups or () if str(s).isdigit() and str(s) != str(action_id)]
    if extra:
        entry["follow_up"] = sorted({*(entry.get("follow_up") or ()), *extra})[:FOLLOW_UP_LIMIT]
    moved = forward_displacement(before, after)
    if moved is not None:
        forward, total = moved
        if forward >= DASH_MIN_YARDS and forward >= .7*total:
            entry.update(mode=FORWARD_DASH, dash_yards=round(max(forward, number(entry.get("dash_yards")) or 0.), 1))
    return entry.get("mode")


def aim_tolerance(width_fraction: float | None) -> float:
    """Screen centre-line tolerance: the box must straddle the facing line."""
    return max(.03, min(.08, .4*(width_fraction or .1)))
