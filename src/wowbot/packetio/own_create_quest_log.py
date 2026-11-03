"""Selected-own CREATE continuation: UnitData remainder -> PlayerData QuestLog.

Reviewed against WPP UpdateFieldsHandler1215 (70340 family). Only numeric quest
slots are returned; account/guild/player names and GUIDs are skipped by size.
The later PlayerData/ActivePlayerData blocks are outside this prefix's scope.
"""
from .player_quest_log import SLOT_COUNT, _skip_guid, _slot, normalize_slots

OWNER, PARTY_MEMBER, UNIT_ALL, EMPATH = 1, 2, 4, 8


def _count(cursor, limit=512):
    value = cursor.u32()
    if value > limit:
        raise ValueError('unsupported own create array size')
    return value


def _skip_unit_remainder(cursor, flags):
    # UnitData immediately after CombatReach; no fixed guessed jump across
    # conditional owner/empath fields or dynamic collection bodies.
    cursor.take(4+4+1+4*4)  # DisplayScale, family/type, native/mount appearances
    if flags & (OWNER | EMPATH):
        cursor.take(4*4)    # min/max main/offhand damage
    cursor.take(4+4*4)      # StandState/pet/vis/anim; pet number/name/XP/next XP
    cursor.take(4*9)        # seven cast/haste/time modifiers, created spell/emote
    if flags & OWNER:
        cursor.take(5*4*4)  # stats and their positive/negative/support buffs
    if flags & (OWNER | EMPATH):
        cursor.take(7*4)    # resistances
    if flags & OWNER:
        cursor.take(7*2*4)  # resistance/mana cost modifiers
    cursor.take(4)          # BaseMana
    if flags & OWNER:
        cursor.take(4)      # BaseHealth
    cursor.take(4)          # sheath/PvP/pet/shapeshift bytes
    if flags & OWNER:
        cursor.take(18*4)   # attack/ranged power, lifesteal, ranged damage/cost
    cursor.take(2*4+14*4)   # max-health/hover modifiers, item/pet/interact/taxi IDs
    _skip_guid(cursor)      # GuildGUID: never construct/export it
    passive, effects, channels = _count(cursor), _count(cursor), _count(cursor)
    cursor.take(9*4)        # flight/glide/drive, max-health modifiers, silence/area/ranges
    _skip_guid(cursor)      # NameplateAttachToGUID
    cursor.take(passive*8+effects*4)
    for _ in range(channels):
        _skip_guid(cursor)
    cursor.reset()
    cursor.bit()            # Field_314
    if cursor.bit():        # optional UnitAssistActionData, contains player text
        cursor.reset()
        cursor.take(1+4)    # type and realm; skipped, not observed identity
        size = cursor.bits(6)
        cursor.take(size)   # player name bytes are never decoded/exported


def read_create_slots(cursor, flags, *, cosmetic_counts=None):
    """Continue only a verified own UnitData prefix, never another player."""
    if flags & ~0x0f or not flags & PARTY_MEMBER:
        return None
    _skip_unit_remainder(cursor, flags)
    cursor.reset()
    # PlayerData before QuestLog. Its cosmetic arrays occur later: only
    # their bounded counts are here. No account/guild/player ID is retained.
    for _ in range(3):
        _skip_guid(cursor)  # duel arbiter, WoW account, battle.net account
    cursor.take(8)          # GuildClubMemberID
    _skip_guid(cursor)      # LootTargetGUID
    cursor.take(5*4)        # flags, flagsEx, guild rank/delete/level
    customizations = _count(cursor,256)  # bodies follow after the quest prefix
    random_customizations = _count(cursor,256)
    if cosmetic_counts is not None:
        cosmetic_counts.update(customizations=customizations,random_customizations=random_customizations)
    cursor.take(6+2*4)      # party/sex/inebriation/title/faction, duel/guild time
    return normalize_slots([_slot(cursor, index, True) for index in range(SLOT_COUNT)])
