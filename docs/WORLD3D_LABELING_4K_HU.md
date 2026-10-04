# World3D 4K címkéző

Indítás: `START_WORLD3D_LABELING_4K.bat`.

Nem kell megvárni a videók teljes feldolgozását. A címkéző élőben figyeli a
`review/images` könyvtárat, és `Enter` után az időközben elkészült képeket is
felveszi a sorba. A fejlécben az `[EXTRACTING: live folder]` jelzi ezt az állapotot.

- Kattints a felső színes osztálygombra, vagy nyomd meg a `0`–`6` billentyűt.
- Húzz téglalapot a címkézendő NPC, mob, holttest vagy más releváns objektum köré.
- Egy képen több, eltérő színű téglalap is lehet.
- `Enter`: mentés és következő még nem címkézett kép.
- `E`: ellenőrzött üres kép mentése és ugrás a következőre.
- `D`: kijelölt téglalap törlése.
- `N` / `P`: következő / előző kép.
- `]` / `[`: következő / előző még nem címkézett kép.
- `Q` vagy `Esc`: kilépés. Az addig Enterrel/E-vel mentett munka megmarad.

Ne jelöld be a saját, középen/hátulról látható játékoskaraktert és annak mountját.
A szín vizuális osztályt jelent, nem játékbeli szemantikát: például a humanoid test még
nem automatikusan NPC, hostile vagy quest giver.

## 2026-09-24 – asszisztensi 300-as 4K audit

- Kiinduló kézzel ellenőrzött állomány: 277 frame / 740 box.
- A 277 frame-ből készült ideiglenes annotációsegéd modell:
  `models/world3d_annotation_assist_277.pt`. Ez nem runtime-modell és nem ground truth.
- A következő 300 még nem ellenőrzött frame kontaktlapjai kézzel át lettek nézve
  (`output/manual_4k_500_assist/sheet_00.jpg`–`sheet_74.jpg`). A proposal csak
  téglalap-kiindulópont volt; a látható objektumot és az osztályt vizuálisan kellett
  megerősíteni.
- A megfigyelt kerítésoszlop-, tűzeffekt- és UI false positive-ok nem kerültek be.
- A döntési napló:
  `output/manual_4k_500_assist/decisions_manual_300.json`.
- A dataset jelenlegi állapota: 577 review / 577 label / 983 box.
- Ellenőrzött export:
  `datasets/world3d_labeling_4k_reviewed_577_export_v3`.
- Audit: 577 kép, 983 box, 0 invalid label, 0 hiányzó vagy árva label,
  0 split overlap; `training_ready=true`.

Ez modell által segített, de kontaktlapon kézzel auditált címkézés. Az annotációsegéd
nem írhat közvetlenül runtime szemantikát, és nem tekintendő a végső held-out teszt
eredményének. A következő közös tréning előtt az Exile's Reach 500-as csomagot is
ugyanilyen review/audit kapuval kell lezárni.
# 2026-09-24 kombinált annotációs segédmodell

- Exile's Reach: 500/500 explicit review, 1224 doboz.
- Korábbi 4K gameplay: 577/577 explicit review.
- Kombinált export: `datasets/world3d_annotation_combined_1077_v1` (1077 kép, 2207 doboz).
- Modell: `models/world3d_annotation_assist_combined_1077_v1.pt`.
- Állapot: `OFFLINE_TRAINED`, kizárólag annotációs javaslatokra; runtime-ba nincs automatikusan előléptetve.
- Az összes mentett címke újbóli vizuális ellenőrzése: `REVIEW_ALL_WORLD3D_LABELS.bat`.
- A `world_object_like` (1 példa) és `entrance_or_door_like` (5 példa) osztály még adat-hiányos.
