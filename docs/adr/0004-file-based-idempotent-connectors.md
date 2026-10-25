# File-based, idempotent connectors

External data enters through files dropped into `data/<source>/`: running
activities in `data/running/`, nutrition exports in `data/nutrition/`, workout
exports in `data/workout/`. Connectors read them on demand; re-importing a file
that has changed replaces the rows it previously produced rather than duplicating
them.

## Why

Direct integrations mean OAuth apps, token refresh, rate limits and a network
dependency that breaks the "works offline, forever" promise. A file drop works
with OpenTracks, Strava exports, OpenNutriTracker, wger and Waistline alike, and
survives any of those services changing or dying. Idempotency matters because the
athlete will re-export and re-drop the same data while experimenting.

## Consequences

- Import state is keyed on a connector-specific stable id, so re-import is
  replace-or-update, never append.
- Timestamps in exports are inconsistent; parsers normalise to UTC and tolerate
  local-time offsets.
- Users must export manually. That is the accepted cost of privacy and
  durability; the UI explains where each export lives.
- A connector must be safe to run twice and must report how many rows it
  replaced.
