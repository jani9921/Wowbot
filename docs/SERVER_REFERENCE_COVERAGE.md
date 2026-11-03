# Server reference data: current coverage and gaps

2026-10-29 — initial source inventory, **PARTIAL**, not a complete opcode audit.
The user's intended authority order is fresh server evidence, current public
quest API evidence, then retained/static reference data. The shared WorldModel,
planner, skills and verification remain authoritative.

The required path is packet -> verified decoder -> normalized event -> WorldModel
-> quest/entity knowledge -> planner -> normal execution -> credit verification.
Opcode names alone do not implement that path. Unknown payloads in `pkt.py`
remain opcode/count/hash diagnostics, not usable quest facts.

| Current TDB/reference dependency | Existing live packet path | Gap |
| --- | --- | --- |
| Quest POI metadata and XYZ | QUEST_POI_UPDATE, WorldModel projection, completion resolver | 16:06 retained 70185 state has no packet POI. Current API completion pin now wins over historical spawns; capture/query/projection absence still needs diagnosis. |
| Creature/object GUID, entry, position and movement | UPDATE_OBJECT subset, ENTITY_CREATED/POSITION/UNIT_UPDATE/REMOVED, monster movement | Live entities do not provide every template field or historical spawn. |
| Quest progress and credit | QUEST_CREDIT_ADDED, QUEST_COMPLETED/UPDATED plus addon state | Full quest-definition/objective query responses are not decoded into equivalent live reference records here. |
| NPC/object -> offered/rewarded quest ID | QUEST_GIVER_STATUS and observed addon dialog history | Status names a GUID, not every quest ID. Quest-list/details/request-items/offer-reward response decoding and GUID/quest correlation are missing. |
| Gossip menus, vendor/trainer records | GOSSIP_SELECTED records the selected outgoing row | This is not the full server menu/inventory response. Equivalent live reference builders are missing. |
| NPC/object names and template properties | Entry/GUID facts and addon names | Full creature/gameobject query-response templates are absent from the current normalized schema. |
| Item/spell mechanics, geometry | Runtime action evidence plus local client catalog | Client DB2-derived effects/geometry have separate provenance; they are not all established as server-table messages. |
| `smart_scripts` and conditions | SQL reference lookups | No complete script/condition-table event exists in the current schema. Which observed outcomes replace each dependency remains to be established. |

Checked boundaries: `agent/reference_world_sqlite.py`, `agent/tdb_locations.py`,
`packetio/opcodes_12_1.py`, `packetio/pkt.py`, `packetio/validation.py`,
`agent/world_packet_reducer.py`, `agent/quest_poi_evidence.py` and
`agent/turnin_resolver.py`. No new payload layout was guessed or enabled.

WPP generates SQL candidates from parsed observations and can compare them with
an existing world database; it also uses supplemental data. WPP-populated rows
therefore do not prove a complete database snapshot is resent at every login.
Primary source: [WPP documentation](https://github.com/TrinityCore/WowPacketParser#databases).

Next decoder work: quest definition/objective responses and giver list/details/
reward relations, then creature/object query templates and server gossip menus.
Each requires an exact supported-build layout, normalized schema, PID/session/
build provenance, a consumer, tests and real-capture validation. Retained observed
relations can then be updated without overriding fresh evidence.

The 2026-10-29 changes implement completion-POI priority, shared ghost movement
and mount/retry recovery. They do not implement the missing response families
above or claim complete runtime replacement of TDB.
