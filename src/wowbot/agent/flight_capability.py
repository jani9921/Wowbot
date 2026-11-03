"""May the character fly its own mount here and now (Steady Flight)?

User 2026-10-25: "first plain riding in the air".  Every condition is
explicit addon evidence (0.9.76); a missing or unknown value fails closed:

* the zone allows flying (``flight.flyable_area``) and the character knows a
  flying riding skill (Expert/Artisan/Master, ``flying_riding_known``),
* an action-bar slot summons a flying mount (its mount type is a known
  flying type), the slot has a key bound and the client reports it usable,
* not indoors, in combat, in a vehicle or on a taxi, and
* the session has not seen Skyriding: Steady Flight hovers without input
  and climbs/descends on Jump/Sit; a gliding character (Skyriding style) is
  not flown by this controller.
"""
from __future__ import annotations

# Retail mountTypeID values that fly (Steady Flight capable): 247 Red Flying
# Cloud, 248 flying, 402/424 Skyriding (fly steady when the style is
# Steady), 407/436 flying + aquatic.  Unknown types are not assumed to fly.
FLYING_MOUNT_TYPES = frozenset({247, 248, 402, 407, 424, 436})


def ghost_steady_flight_available(state: dict) -> bool:
    """Current ghost mount in an explicitly flyable, non-gliding context.

    A graveyard ghost mount is not an active journal mount/action-bar slot.
    Its existing mount is controlled by the normal bounded Steady loop; no
    mount is summoned and no Skyriding ability is inferred from an old bar.
    """
    flight, movement = state.get('flight') or {}, state.get('movement') or {}
    return (state.get('is_ghost') is True and state.get('is_mounted') is True
            and flight.get('flyable_area') is True and flight.get('can_glide') is False
            and flight.get('gliding') is not True and movement.get('indoors') is False
            and not any(state.get(key) is True for key in
                        ('is_in_combat', 'in_vehicle', 'on_taxi', 'loading')))


def flying_mount_action(state: dict) -> dict | None:
    """The bound, usable action-bar slot that summons a known flying mount."""
    for entry in state.get("actionbar") or ():
        mount = entry.get("mount") if isinstance(entry, dict) else None
        if (not isinstance(mount, dict) or entry.get("kind") != "summonmount"
                or not entry.get("action")
                or not (entry.get("binding_primary") or entry.get("binding_secondary"))):
            continue
        if (mount.get("mount_type_id") in FLYING_MOUNT_TYPES and mount.get("mount_collected") is not False
                and mount.get("mount_usable") is not False and entry.get("is_usable") is not False):
            return entry
    return None


def flight_blockers(state: dict) -> list[str]:
    """Why flying is not possible now; empty when it is."""
    blockers = []
    flight = state.get("flight") or {}
    capability = state.get("mount_capability") or {}
    movement = state.get("movement") or {}
    if flight.get("flyable_area") is not True:
        blockers.append("zone_not_flyable" if flight.get("flyable_area") is False else "flyable_area_unknown")
    if capability.get("flying_riding_known") is not True:
        blockers.append("no_flying_riding_skill")
    if state.get("skyriding_seen") is True or flight.get("gliding") is True:
        blockers.append("skyriding_style_set_flight_style_to_steady")
    if movement.get("indoors") is not False:
        blockers.append("indoors_or_unknown")
    if state.get("is_in_combat"):
        blockers.append("in_combat")
    if state.get("in_vehicle") is True or state.get("on_taxi") is True:
        blockers.append("vehicle_or_taxi")
    if state.get("is_mounted") is True:
        if not on_flying_mount(state):
            blockers.append("mounted_on_a_non_flying_mount")
    elif flying_mount_action(state) is None:
        blockers.append("no_bound_flying_mount_on_actionbar")
    return blockers


SKYRIDING_MOUNT_TYPES = frozenset({402, 424})


def skyriding_blockers(state: dict) -> list[str]:
    """Why Skyriding travel is not possible now; empty when it is.

    Skyriding needs no flying riding skill: live 2026-10-25 the character
    knew only Journeyman riding (33391) and skyrode all four lessons.  It
    needs an advanced-flyable zone, a mount that glides there (``can_glide``
    when mounted, a bound usable Skyriding mount slot when not), outdoors and
    out of combat.  A mount set to Steady Flight is flown by FlightControl.
    """
    from .travel_mode import flight_mount_action
    blockers = []
    flight = state.get("flight") or {}
    movement = state.get("movement") or {}
    if flight.get("advanced_flyable_area") is not True:
        blockers.append("zone_not_skyriding" if flight.get("advanced_flyable_area") is False
                        else "advanced_flyable_area_unknown")
    if movement.get("indoors") is not False:
        blockers.append("indoors_or_unknown")
    for key, reason in (("is_in_combat", "in_combat"), ("is_dead", "dead"), ("is_ghost", "ghost"),
                        ("in_vehicle", "vehicle_or_taxi"), ("on_taxi", "vehicle_or_taxi")):
        if state.get(key) is True and reason not in blockers:
            blockers.append(reason)
    if state.get("is_mounted") is True:
        if flight.get("can_glide") is not True and movement.get("flying") is not True:
            blockers.append("mounted_on_a_non_skyriding_mount")
    else:
        chosen = flight_mount_action(state, "SKYRIDING")
        if chosen is None:
            blockers.append("no_bound_skyriding_mount_on_actionbar")
        elif (chosen.get("mount") or {}).get("mount_steady_flight") is True:
            blockers.append("mount_set_to_steady_flight")
    return blockers


def on_flying_mount(state: dict) -> bool:
    """Mounted on a mount that flies: in the air now, or the active mount is
    a known flying type (its action-bar slot says so)."""
    if state.get("is_mounted") is not True:
        return False
    if (state.get("movement") or {}).get("flying") is True:
        return True
    return any(isinstance(entry, dict) and isinstance(entry.get("mount"), dict)
               and entry["mount"].get("mount_active") is True
               and entry["mount"].get("mount_type_id") in FLYING_MOUNT_TYPES
               for entry in state.get("actionbar") or ())


def can_fly(state: dict) -> bool:
    return not flight_blockers(state)
