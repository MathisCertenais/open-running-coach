# Pace-based load now, heart rate later, without reworking the model

Training load is computed from pace zones and moving time (optionally overridden
per activity by session-RPE). Heart rate is not required anywhere in the load
pipeline, and its absence is not simulated.

## Why

Current recording devices in this project produce no heart-rate samples, but the
OpenTracks schema declares the field and some users will have a chest strap
tomorrow. Designing load around "minutes in zone × weight" means the same shape
serves heart rate later: only the zone classifier changes, from pace bands to
heart-rate bands, and the weights can be re-derived from a TRIMP curve. A model
built on "average HR" or "suffer score" would have to be rewritten.

## Consequences

- `activity_load()` returns a `source` field (`pace` or `rpe`) so consumers never
  need to guess how a number was produced.
- Session-RPE deliberately overrides pace load for the same activity; using both
  would double-count.
- When heart rate arrives, the change is a second zone classifier plus a config
  flag — not a change to CTL/ATL, ACWR, the daily series, or any API payload.
- Any new load source must keep the same contract: minutes × weight per day, so
  the downstream series stays unit-comparable.
