# Client addons

Install exactly one matching addon. Never enable two AIPC Export copies at the
same time.

- `AIPlayerControllerExport` is the canonical Retail 12.1.0 development addon.
- `AIPlayerControllerExport-12.1.0` is an identical, version-labelled package.
- `AIPlayerControllerExport-7.3.5` is the legacy 7.3.5 package and does not have
  the Retail telemetry extensions.

For Retail, copy either Retail folder into `_retail_/Interface/AddOns`, but rename
the chosen folder to `AIPlayerControllerExport`. Restart WoW or run `/reload` after
replacing addon files.

The Retail addon is a read-only sensor. It exports AIPC5 pixel telemetry and
stores a bounded, structured event history in `AIPlayerControllerExportDB`; it
does not move the character, press keys, plan quests, or make combat decisions.

Version 0.9.20 schedules five FAST_STATE packets followed by one paged full-state
packet on the 60 Hz transport ticker. The nominal FAST lane is therefore 50 Hz;
the measured rate is display/capture dependent and is reported separately by the
agent's sensor diagnostics.

Retail 0.9.75 exports the option's API `flags` and the optional boolean
`quest_label_prepend`, evaluated using the running client's
`Enum.GossipOptionRecFlags.QuestLabelPrepend` and `FlagsUtil.IsSet`.
This is the flag Retail itself uses to add the quest label. A known API
boolean is preferred over decorated text; unavailable/inaccessible flags,
enum or helper leave it unknown, without a guessed bit mask. The existing
planner and skill still require fresh, unambiguous, exact NPC/option/point
evidence and verify actual quest progress after a click.

Retail also exports a gossip option's bounded `display_name` from
its matching visible row. Some UI labels add a colored `(Quest)` prefix
that is absent from `C_GossipInfo.GetOptions().name`. The raw API name/ID
remain unchanged; the Python planner and skill validate that a displayed
marker belongs to that same option. Button font strings and named-color
escapes are supported as well. Missing/secret/unrelated text supplies
no marker proof. This is a read-only sensor addition, not an automatic
gossip selection. Update the addon and reload/restart the client as well as
restarting the Python GUI/runtime.

Useful commands:

- `/aipc status` shows protocol/schema, refresh health, latest event, and rate.
- `/aipc show` opens the diagnostic panel.
- `/aipc error` prints the last addon error.
- `/aipc events` prints the event-buffer summary.
- `/aipc rate 0.5` changes the snapshot interval (allowed range: 0.2–10 seconds).
