# Design spec 30–32: Travel, kockázat-alapú útvonal, questing (állapot)

2026-11-02, Claude. A felhasználó kérte, hogy a 30–32. pontot (utazás,
harc-tudatos útvonal, mechanika-alapú questing) zárjuk be.

Minden alábbi tétel **offline tesztelt**. Élő igazolás egyiknél sincs.

## 30. Travel

| Pont | Megvalósítás |
|---|---|
| 30.1 TravelPlanner / jelöltek | `navigation/travel_planner.py`: GROUND, MOUNTED_GROUND, FLIGHT és MIXED jelölt explicit leg-sorral (GroundLeg → Mount → Takeoff → Flight → Land → GroundLeg), `TravelCostModel`-lel pontozva (becsült másodpercek: út, átmenet, veszély, kockázat). A nem kivitelezhető jelölt típusos blokkolóval marad. |
| | A `TravelModePolicy` mostantól a tervezőt kérdezi. Gyalog vagy mount: a meglévő kapuk (képesség, blokkolók, hiszterézis) után a költség dönt; a fordulópont ~39 yd, a régi 40 yd-es küszöb szerint. Skyriding és steady repülés: a tervező vétózhat, ha a földi út olcsóbb. Nagy magasságkülönbségnél a földi jelölt kiesik. |
| | A `TripExecutor` legjei most a mountot, a lovaglást és a vegyes út kezdő gyalog-legjét is megnevezik, a kész útvonalból és az aktuális módból. |
| 30.2 TransitionSystem | `navigation/mode_transitions.py`: `ModeTransitionMachine`, minden váltásra szerződéssel: előfeltétel → akció → ellenőrzés → időkorlát → helyreállítás. A mount-gomb elküldése nem siker: a mount-állapot kell. A felszállás repülés-állapotot vagy valódi Z-emelkedést igényel. A földet érés földön, esés nélkül igazolt. A megfigyelt (akció nélküli) váltások is tényként kerülnek be. |
| 30.3 Három szint | Változatlanul megvan: utazás → útvonal → lokális lease-es vezérlés. A harci pozicionálás lokális kérést ad, harcban nincs mountolás. |

## 31. Harc-tudatos útvonal

| Pont | Megvalósítás |
|---|---|
| 31.1 RouteScore | Már megvolt (ETA, távolság, harc, átmenet, bizonytalanság, hibakockázat, helyreállítás, megbízhatóság). |
| 31.2 Földi kockázat | `DangerMap.corridor_hostiles`: ha egy nem harci út folyosóján legalább 2 sima ellenséges mob áll (`hostile_detour_count`), a tervező navmesh-kerülőt próbál. Csak akkor tartja meg, ha a veszéllyel együtt olcsóbb. Az elit ×3, a ritka ×2, a csoport ×2 harcidőt nyom, és nő a hibavalószínűség is. |
| 31.3 Repülési kockázat | Ismeretlen emeletű leszállás bizonytalansága (`landing_floor_unknown`). Ha egy felszállás nemrég ugyanott elbukott, az kockázatként számít a tervezőben. |
| 31.4 Karakterfüggő költség | `agent/fight_statistics.py`: a karakter saját, megnyert harcainak medián hossza (legalább 3 harc) kerül a `character_profile.expected_fight_seconds`-be. Alacsony HP-nál a harcidő ×1,75-ig nő. |

## 32. Questing

| Pont | Megvalósítás |
|---|---|
| 32.1 MechanicRegistry | `playbooks.registry_name`: saját mechanikák → spec-nevek (KILL_TARGET, KILL_FOR_ITEM, USE_ITEM_SELF / _ON_TARGET / _AT_LOCATION, EXPLORE_LOCATION, FOLLOW_NPC …). Az ismeretlen UNKNOWN_MECHANIC, sosem találgatás. |
| 32.2 QuestTargetContext | Új mezők: `nav_target` (hová menjünk) és `search_region` (hol keressünk, pl. AreaTrigger-ek), a szereplő-, objektum-, spell- és kredit-szerepek mellett. |
| 32.3 MechanicContract | `registry_name`, `success_condition`, `failure_reasons`, `recovery_options` (a 8.2-es recovery-élekből, a könyv lépéseire szűrve). |
| 32.4 QuestExecutionGraph | Feltételes ág (`condition`), amely sosem blokkolja a következő lépést: a kísérés védekezése és újraindítása, a loot csak lootolható tetemnél vagy loot-ablaknál. VAGY-ág (`alternative_of`, `any_of`): az ismeretlen forrásnál a beszéd vagy a tárgyhasználat. A párhuzamos objective-ek a `QuestGraph`-ban vannak. |
| 32.5 Hiba-taxonómia | Új hibaokok: WRONG_FLOOR, MISSING_BINDING, MECHANIC_UNKNOWN, PHASE_MISMATCH, WAITING_SERVER_STATE, SCENE_NOT_RESOLVED, SPELL_NO_EFFECT, LOCATION_UNKNOWN. A spec-szinonimák a meglévő tagokra mutatnak (pl. ROUTE_UNREACHABLE → NO_ROUTE). Mindegyik új ok kapott helyreállítási irányt. A hiányzó cache-binding most MISSING_BINDING. |

## Ami nyitva maradt

- **32 ObjectiveExecutor:** a végrehajtás továbbra is a meglévő policy-flow-kban él (lásd a P8.5 táblázatát), nincs egyetlen executor-osztály. Ez nagyobb, külön bontás.
- **30.1 repülés:** a Skyriding és steady repülést továbbra is a régi szabályok indítják, a tervező csak vétózhat. A MIXED jelöltet a nyílt ég alá vezető séta indítja, a tervező nem önállóan választja.
- **31.2:** a veszély csak a kerülő-útvonal választásába és a pontszámba számít, a navmesh poligon-költségbe nem (a Detour-szűrőnek nincs régiónkénti költsége).
- **Kalibráció:** minden sebesség és átmeneti idő becslés, élőben nincs illesztve.

## Tesztek

- `tests/test_mode_transitions_20261102.py`
- `tests/test_travel_planner_20261102.py`
- `tests/test_route_risk_20261102.py`
- `tests/test_quest_contract_graph_20261102.py`
- új eset a `test_trip_lifecycle_20261030`-ban

Tudatosan módosult régi teszt: a `test_travel_mode_20261020` tételes
snapshot-ellenőrzése (két új snapshot-kulcs).
