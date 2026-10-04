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

Useful commands:

- `/aipc status` shows protocol/schema, refresh health, latest event, and rate.
- `/aipc show` opens the diagnostic panel.
- `/aipc error` prints the last addon error.
- `/aipc events` prints the event-buffer summary.
- `/aipc rate 0.5` changes the snapshot interval (allowed range: 0.2–10 seconds).
