# Talon Strike: open ground-target Extra Action path

Observed in the user-run 2026-10-27 00:44:13 capture.

## Exact evidence

- Quest 65956 Talon Strike: progress objective 423624 (Djaradin defenses disrupted).
- Its hidden gameobject credit 423631 references Siege Arbalest 376104.
- Extra Action in the live state: visible=true, usable=true,
  action=EXTRAACTIONBUTTON1, action_type=spell, action_id=369553.
- The local SpellName record calls 369553 Blacktalon Marker.
- SpellTargetRestrictions 277278: SpellID=369553, DifficultyID=0, Targets=64, TargetCreatureType=0.
- SpellEffect 914986/914999: destination-area enemy selector 16, stun/damage.
- SpellMisc 484413: SpellID=369553, RangeIndex=160.
- SpellRange 160: RangeMin=[0,0], RangeMax=[30,40].
- No StartItem, ItemDrop or live special_item for this quest in this capture.

The existing quest item -> ItemEffect pipeline cannot supply an item ID for it.
QuestDomain's Extra Action admission currently permits exact API special_item matches or an explicit
goal action authorization. It does not automatically establish this spell -> bonus objective link.
ExtraActionHandler currently binds the known Extra Action and waits for quest credit; it has no
targeting-cursor/ground-aim phase.

## Completed separate fix

The arbalest's server-object approach used a hard-coded centre distance even after the shared
collision-edge detector yielded. It now consumes the shared edge and exact live gameobject soft
recipient, including skill-side rechecks. This sends the existing F7 interaction request; it does not
implement Blacktalon Marker.

## Remaining implementation requirements

1. Establish a sourced, quest-scoped Extra Action spell association (including bonus progress bars),
   not a hard-coded quest/spell pair or blanket authorization for every visible Extra Action.
2. Export a current public targeting-cursor observation through the existing fast telemetry lane.
   Tie its lifecycle to the selected action; unknown/secret API results remain unknown.
3. Supply a fresh, verified ground-aim point on the current selected-PID viewport. Server world XYZ,
   a nameplate or minimap dot alone is not a verified pixel projection or a ground ray hit.
4. Extend the shared ExtraActionHandler with activate -> observe targeting -> aim -> click once ->
   verify the intended quest objective. Never use the button centre as the ground destination.
5. Bound and cancel on context change, unexpected cursor, invalid identity/projection, combat safety,
   action replacement or deadline. Preserve existing input ownership and verified bindings.
6. Validate with user-operated live Talon Strike casts; synthetic selector decoding does not validate
   aim accuracy, successful server cast, affected units or bonus-objective progress.

The addon need not be changed for the completed arbalest approach fix. Ground cursor telemetry and
the execution adapter are still open. No success is inferred from pressing F7 or Extra Action.
