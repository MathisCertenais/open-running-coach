# Analysis over social

The product is an **instrument for understanding one athlete's data**, not a
social network. There is no feed, no kudos, no segments leaderboard, no clubs
and no follower graph, now or later. Every feature must answer a question the
athlete has about their own training.

## Why

The value we can defend is *interpretation*: load, form, intensity
distribution, race prediction, and the link between what was lifted and where it
hurt. Social features are a different product with a different cost structure —
moderation, abuse handling, privacy exposure and scale — and a different
competitor (Strava), who has a decade of network effects we cannot touch.
Building social features would (a) lose to Strava, (b) add exactly the central
data collection ADR-0005 exists to avoid, and (c) put athlete health data behind
a feature that requires sharing it.

The parts of the product that are *inherently* shareable are not social: a plan,
a session, or an injury episode can be **exported** (Markdown, PDF, CSV) for a
coach or a physiotherapist. That is deliberate one-way sharing, chosen by the
athlete, and it needs no accounts.

## Consequences

- No follower model, no notifications, no "activity shared" concept in the
  schema.
- Motivation features must be intrinsic: personal records, matched runs,
  heatmap, plan adherence, trends against your own past.
- The AI coach reads a **local snapshot** and answers about one athlete. It never
  sees another person's data and has no idea who else is using the app.
- Export and print views are the sharing story, and they are a first-class
  feature rather than an afterthought.
- Comparisons are against the athlete's own history or published reference
  values (Daniels' tables, Seiler's distribution), never against other users.
