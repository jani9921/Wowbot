# Kritikusút-kódaudit — 2026-10-07

Ez a `projekt` élő forrásmásolatának **célzott, mély kritikusút-auditja**, nem a 390 Python-modul soronkénti áttekintése. A korábbi `DOMAIN_PROGRESS.md` százalékai leltárbecslések; az audit nem tekinti őket bizonyított készültségnek. A hét fő érintett runtime/vision/memory forrásfájl hash-e egyezett a GitHub exportéval. Az addon vagy WoW kliens nem kapott inputot, és sem a `projekt`, sem a futási adatok nem módosultak.

## Ellenőrzött útvonalak

- Runtime élesítési feltételek → perception readiness → FAST/medium scheduler → supervisor/input.
- Perception worker/process → WORLD3D projection → WorldModel TTL/belief → `visual_tracks()` → vizuális keresés/INSPECT/mouseover tanítás.
- NavigationService → ReachMovementController FAST mozgás és harc/halál preemption.
- Questlista → determinisztikus ajánlatválasztás → ACCEPT/REWARD_SELECT, valamint a kapcsolódó regressziós tesztek.
- AgentMemory aszinkron writer → `drain_writes()` → observations/hydration.

## Bizonyított hibák és bizonyítékuk

1. **Lejárt vizuális jelölt cselekvési query-ben — [#69](https://github.com/jani9921/Wowbot/issues/69).** `world_evidence_reducer.py` 2 s TTL-t tesz az evidence-re, de a `projections` payloadra nem. `world_state_projection.py` minden state-rebuildben újra beteszi a régi tracket, `world_query.py:217` pedig korhatár nélkül adja vissza. Izolált WorldModel reprodukció: t=2 WORLD3D track, t=100 FAST update → a query még visszaadta, a belief státusza már `STALE`. A background worker kivételkor megtartja a régi listát, a process worker child-exit után is visszaadja; az armingon túl nincs `ready_for_action()` ellenőrzés. Ez identity/hover/INSPECT kockázat, nem puszta vizuális villogás. [#35](https://github.com/jani9921/Wowbot/issues/35) ezért #69 által blokkolt.
2. **FAST MOVE későn reagál harcra/halálra — [#70](https://github.com/jani9921/Wowbot/issues/70).** `fast_movement_lane.py` csak session/presence/loading/input-blocked átmenetnél állít le; a FAST `is_in_combat`, `is_dead`, `is_ghost` értékeket nem gate-eli. A NavigationService/ReachMovementController sem szakít ilyen esetben. Izolált FAST-lane reprodukcióban mindhárom külön-külön igaz jelzés mellett `dispatched=True` és egy új mozgásparancs keletkezett, `force_medium` nélkül. A supervisor csak a mozgás alatt 1 s-os medium körben preemptál. Az input-fókusz védelme ettől külön működik. Ez kódszintű időablak; az adott felhasználói halál konkrét okát külön élő napló nélkül nem tulajdonítjuk neki.
3. **Háttér-SQLite írás hibánál adatvesztést rejthet — [#71](https://github.com/jani9921/Wowbot/issues/71).** `memory.py:_writer_loop` kiveszi a batch-et a sorból, az írási kivételt logolja, de nem teszi vissza és nem ad error státuszt. Izolált szimulált íráshibánál `drain_writes() == True`, `attempted=1`, `inserted=0`, `stored=0`. Nem bizonyított, hogy élesben már történt ilyen DB-hiba; a hibapálya viszont reprodukált.
4. **Detector warm-up élesítési kapu — meglévő [#30](https://github.com/jani9921/Wowbot/issues/30).** `runtime.py` hozzáadja a `waiting_for_world3d_detector` kijelzési blockerhez, de a `set_mode(FULL_AI)` feltétele nem vizsgálja `detector_ready` értékét. A `ready_for_action()` friss World3D eredményt mér, nem a tanult detektor első eredményét. A korábban lezárt #56 élesítési munkát ez nem semmisíti meg, de hiányzó acceptance gate maradt.

## Regressziós ellenőrzés és minősítés

`py -3.13 -m pytest -q tests/test_m1_quest_dialog_skill.py tests/test_m1_quest_item_skill.py tests/test_quest_dialog_fast_lane.py tests/test_agent_runtime.py tests/test_fast_world_position.py`: **62 passed, 1 failed**. A bukó `test_complete_offline_quest_combat_loot_turnin_replay` régi fixture-t használ. Kommentje szerint az mmap nélküli normalizált turn-in waypoint nem adhat közvetlen MOVE-ot, az assertion mégis 6 parancsot vár a kapott 4 helyett. Ez **teszt/viselkedés eltérés**, nem bizonyított élő quest-regresszió; a meglévő [#17](https://github.com/jani9921/Wowbot/issues/17) és [#34](https://github.com/jani9921/Wowbot/issues/34) alatt kell eldönteni az új helyes elvárást. A korábbi teljes suite: 2454 passed, 5 skipped, 15 failed; ebben a menetben nem ismételtük meg.

## Nem igazolt / további auditkapuk

- A több-questes UI kódban az első látható, addon-igazolt sort determinisztikusan választja; az ACCEPT és reward külön ágon van. Ez **offline tesztelt**, de nem bizonyít több quest egymás utáni önálló live teljesítését.
- A 13 képességterülethez tartozó alacsony százalékokat nem lehet a fenti öt kritikusútból precízen újraszámolni. Egy végleges értékeléshez mindegyikre producer → WorldModel → planner → skill/input → verifier → élő acceptance bizonyíték és kockázati súlyozás kell. A hiányzó éles producerű herb/mining/fishing/dungeon/PvP továbbra is 0% felhasználói képesség, a meglévő scaffold nem live feature.
- Nincs új WoW-live teszt. A felhasználó indítja a klienst; az asszisztens csak a naplókat olvassa, és nem hagy FULL_AI-t futva.
