"""Food and drink from the client DB2, never from localized item text (REV4 P7).

An item is FOOD when one of its on-use ItemEffect spells applies a health
regeneration aura (SpellEffect APPLY_AURA 6 with aura OBS_MOD_HEALTH 20 or
MOD_REGEN 84), DRINK for the mana auras (OBS_MOD_POWER 21, MOD_POWER_REGEN
85).  Checked on the pinned 12.1 client data: Tough Hunk of Bread 4540
(spell 1291822, aura 20), Tough Jerky 117 (spell 433, aura 84), Refreshing
Spring Water 159 (spell 1291950, aura 21); the Hearthstone is neither.
An unknown item, or a missing catalog, is no consumable (UNKNOWN, not FOOD).
"""
from __future__ import annotations

from wowbot.value_helpers import number

APPLY_AURA = 6
FOOD_AURAS = frozenset({20, 84})
DRINK_AURAS = frozenset({21, 85})
ON_USE = 0


class ConsumableCatalog:
    def __init__(self, catalog=None) -> None:
        self._catalog = catalog
        self._kinds: dict[int, str | None] = {}

    def _client(self):
        if self._catalog is None:
            from wowbot.quests.client_catalog import ClientCatalog
            self._catalog = ClientCatalog()
        return self._catalog

    def kind(self, item_id) -> str | None:
        if type(item_id) is not int or item_id <= 0:
            return None
        if item_id not in self._kinds:
            self._kinds[item_id] = self._resolve(item_id)
        return self._kinds[item_id]

    def _resolve(self, item_id: int) -> str | None:
        try:
            catalog = self._client()
            uses = (catalog.item_use(item_id) or {}).get("effects") or ()
            auras = set()
            for use in uses:
                spell = use.get("spell_id")
                if use.get("trigger_type") != ON_USE or type(spell) is not int or spell <= 0:
                    continue
                auras.update(row.get("aura") for row in catalog.spell_effects(spell) or ()
                             if row.get("effect") == APPLY_AURA)
        except Exception:                 # a missing catalog never invents a consumable
            return None
        return "FOOD" if auras & FOOD_AURAS else "DRINK" if auras & DRINK_AURAS else None


def usable_consumable(state: dict, catalog: ConsumableCatalog, kind: str, bindings=None) -> dict | None:
    """A ready action-bar button of this kind (keyboard only, no bag clicks)."""
    for action in state.get("actionbar") or ():
        if not isinstance(action, dict) or action.get("kind") != "item" or not action.get("action"):
            continue
        item = number(action.get("id"))
        cooldown = number(action.get("cooldown_remaining"))
        if (item is None or item != int(item) or action.get("is_usable") is not True
                or cooldown is None or not 0 <= cooldown <= .1
                or (bindings is not None and not bindings.contains(action["action"]))):
            continue
        if catalog.kind(int(item)) == kind:
            return {"item_id": int(item), "binding": action["action"]}
    return None
