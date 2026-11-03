from pathlib import Path
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
for name,head,entry in (
 ('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
 '''2026-10-30 REV4 P5/P7 range/facing follow-up — **OFFLINE_TESTED / full
ownership migration PARTIAL**. Mobility opener range no longer becomes the
sustained rotation's approach radius; ranged envelopes remain distinct from
melee defaults and do not permit spells. Three existing entity-pose helpers
have one pure canonical implementation with exact old reexports. Final facing
uses pure source/GUID/map assessment; missing identity/position cannot fall
back to an old request point or silently re-arm a terminal attempt. Bounded
terminal failure geometry/last-command diagnostics persist beyond image-ring
limits. Existing screen-space FaceController is preserved byte-for-byte.
Selected regression: **4015 passed, 2 skipped, 10 unchanged deselections, 324
modules, exit 0**, 163.87 s pytest; 557 source + 633 test Python files parse,
203 rows unchanged. Eleven recorded live facing failures are not all declared
fixed. No assistant live input/capture/database writes, addon/Ymir unchanged.
See [follow-up and checkpoint](reform/rev4-20261029/P7_RANGE_FACING_FOLLOWUP.md).

'''),
 ('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
 '''## 2026-10-30 — sustained range/facing follow-up (offline)

Charge's former ~20 yd recovery radius is replaced by the non-mobility
rotation range; known ranged envelopes remain available, no spell is allowed
by geometry alone. Pure canonical pose/facing helpers preserve one authority.
Unknown/removed/wrong-GUID/world actor cannot silently use a stale point for
turning. Typed identity loss is terminal until explicit restart; a bounded
NAVIGATION_FAILURE_DETAIL records exact geometry, sample and recent commands.
The existing screen-space FaceController was restored byte-identically after
an initial import collision. A positive old test fixture now supplies its
required initial actor; the new negative test preserves fail-closed semantics.

Final selected regression: **4015 passed, 2 skipped, 10 unchanged deselections**,
324 modules, 163.87 s pytest / 166.87 s runner, exit 0; 557 source + 633 test
Python files parse, all 203 rows persist. No assistant game/capture/FULL_AI/
input/live DB write; no new live acceptance. The recorded eleven facing
failures and dialog/route-floor cases are not all declared solved.
[Details/checkpoint](reform/rev4-20261029/P7_RANGE_FACING_FOLLOWUP.md).

''')):
 p=root/name;s=p.read_text(encoding='utf-8-sig');assert head in s
 p.write_text(s.replace(head,head+entry,1),encoding='utf-8')
base=root/'docs/reform/rev4-20261029'
for name in ('P1E_P9_IMPLEMENTATION.md','ATVETEL_ES_ATALLASI_TERV.md'):
 p=base/name;s=p.read_text(encoding='utf-8-sig')
 s=s.replace('3999 passed','4015 passed').replace('323 modul','324 modul').replace('229.76 s','163.87 s')
 s=s.replace('553 source + 632 tests Python-fájl; 631 test_*.py','557 source + 633 tests Python-fájl; 632 test_*.py')
 s=s.replace('teljes 631 modulos','teljes 632 modulos')
 p.write_text(s,encoding='utf-8')
p=base/'P1E_P9_IMPLEMENTATION.md';s=p.read_text(encoding='utf-8')
needle='P3 folytatás: a korrelált saját loginhoz'
assert needle in s
s=s.replace(needle,'''A [range/facing follow-up](P7_RANGE_FACING_FOLLOWUP.md) a sustained támadási
távot külön kezeli a mobility openerétől, a három tiszta entity-pose helper
egy canonical implementációba került, és a végső facinghez GUID/map/reason
vizsgálat és bounded terminal diagnostics tartozik. Ez nem a teljes mozgó
entity-goal/floor migráció és nem minden élő facing-hiba igazolt javítása.

'''+needle,1);p.write_text(s,encoding='utf-8')
print('follow-up documentation saved')
