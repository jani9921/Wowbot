# P7 — NPC cast-adatút, 2026-10-30

**Részleges provider, OFFLINE_TESTED. Nincs új élő combat-/interrupt-elfogadás.** A migráció kódoldali készültségének felhasználónak adott kb. 70%-a becslés; nem a tesztsikeresség vagy a P9 sorszáma alapján számolt százalék.

## Bekötés

PktEventDecoder → strict allowlisted schema → authenticated local inbox → RuntimePacketSource → WorldPacketReducer → bounded WorldModel cast facts → exact selected target cast projection.

Az öt opcode azonos a két SHA-pinnelt V12_1_0_69214 és V12_1_5_70340 táblában. A payload külön **WPP_12_1_SPELL_REVIEWED_V1** címkét kap, nem a korábbi élőn igazolt entity-layout címkéjét.

| Szerverpacket | Normalizált esemény | Határ |
|---|---|---|
| SMSG_SPELL_START | SPELL_CAST_STARTED | NPC/vehicle CasterUnit, exact CastID, spell ID, cast flags és deklarált cast time; a rögzített prefix olvasott, nem a teljes spell-record |
| SMSG_SPELL_GO | SPELL_CAST_RELEASED | Ugyanaz a castazonosság; a CastTime itt szerveróra, nem új cast-időtartam; a release nem találat/damage/quest-credit |
| SMSG_SPELL_FAILURE | SPELL_CAST_RESULT | Exact caster/cast/spell és numerikus kód; a teljes rövid record végéig olvasva, a kódhoz nem találgatunk hibaokot |
| SMSG_SPELL_FAILED_OTHER | SPELL_CAST_RESULT | Ugyanez byte-méretű eredménykóddal; exact record-end |
| SMSG_SPELL_INTERRUPT_LOG | SPELL_INTERRUPT_OBSERVED | Megszakított NPC, spell és interrupt spell; ebben a recordban nincs CastID, ezért nem gyártunk hozzá azonosítót |

Nem exportálódik játékos-caster/interruptor azonosító, spellnév, FailedBy, szabad szöveg vagy nyers payload. Hibás irány, player-caster, hiányos prefix, hibás azonosító vagy extra rövid-record tail nem ad megerősített casttényt. Az ismeretlen START/GO tail nem kerül továbbításra; a provenance világosan jelzi a prefix hatókörét.

A WorldModel legfeljebb 128 castrekordot tart. Régebbi esemény nem zárhat új castot; release/result csak azonos caster+CastID+spell mellett töröl. A célkijelölés nem történik meg ettől az adattól: csak a már kijelölt exact GUID kap castnézetet. Map/session/phase/loading vagy entity-removal törli az illető állapotot. A packet receipt nem frissíti az addon/input liveness-t.

A START capture-mintából és deklarált időtartamból számolt végpont becslés; nem szerveroldali start-ACK. A megkülönböztetést a [TrinityCore Spell.cpp](https://github.com/TrinityCore/TrinityCore/blob/master/src/server/game/Spells/Spell.cpp) is mutatja: SpellStart a cast időtartamát, SpellGo a szerveróra értékét írja. A payload sorrendjének elsődleges helyi referenciája a pinnelt WPP V12 SpellHandler.ReadSpellCastData, V9 SpellHandler spell-failure és V6 CombatLogHandler interrupt parser; ezek öröklődő Retail 12 feltételeit is figyelembe vesszük.

## Ami szándékosan továbbra is UNKNOWN

- Az interruptibility nem szerepel ebben a dekódolt prefixben: nem lesz automatikusan true. A CastReference/CombatArbitrator ezért nem engedélyez belőle interruptot.
- Az interrupt-log nem kap kitalált CastID-t. Nem minősíti saját exact-cast műveletünket sikeresnek, és a cast eltűnése/természetes vége sem.
- Channel-lifecycle, delay/update, teljes hazard/ground-AoE, CC-immunitás és talent/provider lefedettség nincs kész. Egy ismert spell indítása önmagában nem bizonyít talajveszélyt vagy dodge-célt.
- A layout offline ellenőrzött. A felhasználó futtatja az új élő próbákat; a normalizált cast state és a tényleges játékkép közötti egyezés ezekben vizsgálandó.

## Addon-betöltési regresszió

A 0.9.79 felhasználói indításkor nem töltődött be. Pontos offline reprodukció: Lua 5.1 és LuaJIT szerint a snapshot closure több mint 60 upvalue-ot fogott meg, Lua 5.4/5.5 szerint viszont lefordult. Az előző compile-only próba emiatt elégtelen volt.

A **0.9.80** a hozzáadott collection-állapotot a már használt namespace mögül olvassa. Mindkét addoncsomag teljes forrása Lua 5.1/LuaJIT/Lua 5.4 alatt fordul; a teljes TOC fájlsorrend hamis kliens API-val betöltődik Lua 5.1 alatt és regisztrálja az /aipc parancsot. Ez nem élő PLAYER_LOGIN vagy pixel-dekódolási próba.

Az asszisztens az új négy fájlt a meglévő WoW AddOns mappába másolta, a telepített 0.9.79 fájlokat előbb külön elmentette. Mind a négy telepített hash egyezik a projektével. Játékinput és /reload nem történt az asszisztens részéről; a felhasználó kapott /reload utasítást. Sikeres élő betöltés még nincs igazolva.
