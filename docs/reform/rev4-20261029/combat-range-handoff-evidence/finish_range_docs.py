from pathlib import Path
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
def prepend(relative,head,entry):
    p=root/relative;value=p.read_text(encoding='utf-8-sig');assert head in value
    p.write_text(value.replace(head,head+entry,1),encoding='utf-8')
prepend('docs/CURRENT_SOURCE_COVERAGE.md','# Current-source coverage ledger\n\n',
'''2026-10-30 REV4 P7 combat range handoff — **OFFLINE_TESTED / remaining combat
and facing gaps PARTIAL**. User trace shows OUT_OF_RANGE only 0.14 s after
combat start while a successful Charge was still moving; fresh melee range
followed ~0.2 s later. A bounded original-cast-time mobility settle prevents
that premature verdict and yields immediately to actual non-movement range.
Selected-position absence now uses the existing exact server actor helper
before the shared NavigationService approach. Identity/map/removal/freshness
gates remain; no retreat to force Charge and no guessed melee range. Selected
regression: **3999 passed, 2 skipped, 10 unchanged deselections, 323 modules,
exit 0**, 229.76 s pytest; 553 source + 632 test Python files parse, 203 numbered
rows unchanged. User's previous run provides live map-0 navmesh and native
session/gap recovery evidence, not post-range-fix quest acceptance. Eleven
facing failures and other recorded errors remain under investigation. Only
read-only SQL was used; no assistant game/capture/input/live DB mutation.
See [range handoff](reform/rev4-20261029/P7_COMBAT_RANGE_HANDOFF.md).

''')
prepend('docs/LIVE_VALIDATION.md','# Live validation evidence and unresolved issues\n\n',
'''## 2026-10-30 — longer user run: session/navmesh observed; combat handoff fixed offline

PID 7784's recorded run now has native Detour map-0 route_found and
PACKET_BASELINE / READY with CONTIGUOUS delivery after one sequence gap.
These are narrow user-run live data-path observations. Manual intervention
limits are unknown; 9 kill/8 loot verifier successes are not automatically
claimed as fully autonomous. Eleven facing failures, two dialog failures,
two route-envelope and two range failures were preserved as unresolved.

A concrete range failure occurred 0.14 s after combat start, during observed
Charge travel, before the next melee-range sample. Bounded original-time
mobility settling and exact server-position fallback for missing selected
UnitPosition are offline-tested; shared navigation/identity/verification and
input authority remain unchanged. The facing failures are not declared fixed.

Selected regression: **3999 passed, 2 skipped, 10 unchanged deselections**,
323 modules, 229.76 s pytest / 232.62 s runner, exit 0; 553 source + 632 test
Python files parse, 203 rows persist. Read-only SQL only, no assistant client/
capture/FULL_AI/input/live DB changes. No post-range-fix live validation.
[Bounded trace, details/checkpoint](reform/rev4-20261029/P7_COMBAT_RANGE_HANDOFF.md).

''')
base='docs/reform/rev4-20261029/'
for name in ('P1E_P9_IMPLEMENTATION.md','ATVETEL_ES_ATALLASI_TERV.md'):
    p=root/(base+name);value=p.read_text(encoding='utf-8-sig')
    value=value.replace('3984 passed','3999 passed').replace('322 modul','323 modul').replace('296.70 s','229.76 s')
    value=value.replace('552 source + 631 tests Python-fájl; 630 test_*.py','553 source + 632 tests Python-fájl; 631 test_*.py')
    value=value.replace('teljes 630 modulos','teljes 631 modulos')
    p.write_text(value,encoding='utf-8')
p=root/(base+'P1E_P9_IMPLEMENTATION.md');value=p.read_text(encoding='utf-8')
needle='P3 folytatás: a korrelált saját loginhoz'
assert needle in value
value=value.replace(needle,'''A hosszabb felhasználói próbában a natív session/gap-helyreállítás és a map-0
útvonal már megjelent. Egy [Charge/range átadási hiba](P7_COMBAT_RANGE_HANDOFF.md)
offline javítva: mozgási átmenet alatt nem zárja le 0.14 s után a harcot,
és üres addon targetpozíció esetén a meglévő exact szerverpozíciót használja.
A többi ráfordulási/dialog hiba nincs ettől lezárva.

'''+needle,1)
p.write_text(value,encoding='utf-8')
print('range documentation updated')
