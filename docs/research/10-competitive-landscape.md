# Competitive landscape — running, strength, mobility, nutrition and metrics

Surveyed **October 2026** against vendor documentation and product pages. Prices
are US list prices from the vendor at that date and change often; treat them as
indicative and check the vendor before quoting them to a customer.

Legend: ✅ supported · ◐ partial or device-dependent · — absent · ? not verified
from a primary source.

---

## 1. What we are actually competing with

"Running app" is four different markets that happen to share a stopwatch:

1. **Recording** — phone/watch captures the track (Strava, Garmin, Coros, Polar,
   Xiaomi, OpenTracks, FitoTrack).
2. **Analysis & coaching** — turns files into load, fitness, predictions,
   plans (Strava Premium, TrainingPeaks, Runalyze, GoldenCheetah, intervals.icu,
   Garmin/Coros/Polar first-party).
3. **Strength & mobility** — programming and logging (GOWOD, Pliability, wger,
   Garmin/Coros strength modes).
4. **Nutrition** — food diaries and macros (MyFitnessPal, Cronometer,
   OpenNutriTracker, Waistline, wger).

Almost nobody sells all four. **That is the gap this project occupies** — but
note carefully that we compete in *analysis* against mature, funded products,
and only *participate* in the other three.

---

## 2. Training and analysis

| Capability | **Open Running Coach** | Strava | Garmin Connect | Coros | Polar Flow | TrainingPeaks | Runalyze | Mi Fitness / Zepp Life | GoldenCheetah |
|---|---|---|---|---|---|---|---|---|---|
| Self-hosted / local data | ✅ | — | — | — | — | — | — | — | ✅ (desktop) |
| Open source | ✅ AGPL-3.0 | — | — | — | — | — | — (OSS abandoned 2019) | — | ✅ GPL |
| Records GPS on phone/watch | — (imports files) | ✅ | ✅ (device) | ✅ (device) | ✅ (device) | — (syncs) | — (syncs) | ✅ (band/watch) | ◐ (import, ANT+) |
| Imports KMZ/GPX/TCX | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ |
| Splits, laps, pace zones, GAP | ✅ | ◐ (splits; GAP yes) | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ |
| Best efforts / matched routes | ✅ | ✅ (subscription) | ◐ | ◐ | ◐ | ◐ | ✅ | — | ◐ |
| CTL / ATL / TSB ("fitness & freshness") | ✅ | ✅ (subscription) | ✅ (acute/chronic) | ✅ (base fitness) | ◐ (cardio load) | ✅ | ✅ | ◐ | ✅ |
| ACWR with risk bands | ✅ | — | ◐ (Load Ratio = acute/chronic, no bands) | ◐ | — | — | — | — | — |
| Intensity distribution vs a target | ✅ 80/10/10 | ◐ (zone charts) | ◐ (load focus: low/high aerobic, anaerobic) | ◐ | ◐ | ◐ | ◐ | — | ◐ |
| VO2max estimate | ✅ Daniels VDOT from best efforts | — | ✅ (device, HR/GPS) | ✅ | ✅ | — | ✅ Effective VO2max (HR-based) | ◐ inconsistent | ◐ |
| Race prediction | ✅ Riegel + VDOT | ◐ | ✅ | ✅ | ✅ | ◐ | ✅ | — | ◐ |
| Auto-generated periodised plan | ✅ 3–6 sessions, deload | — (Runna bundle) | ✅ (Garmin Coach) | ✅ | ◐ | ✅ (human coach) | ◐ | — | — |
| Strength session logging | ✅ | ◐ | ✅ (watch) | ✅ | ◐ | ◐ | — | ◐ | — |
| Exercise-level detail | ✅ | ◐ | ◐ | ◐ | — | ◐ | — | — | — |
| Exercise → injury correlation | ✅ **unique** | — | — | — | — | — | — | — | — |
| Social feed, segments, kudos | — | ✅ | ◐ | ◐ | ◐ | ◐ | — | — | — |
| Live tracking / safety | — | ✅ (Beacon) | ✅ (LiveTrack) | ✅ | ✅ | — | — | — | — |
| Mobile app | — (browser) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ web | ✅ | — desktop |
| Price | **free** | $11.99/mo · $79.99/yr | free with device | free with device | free with device | ◐ free Basic; paid tier ~$19.95/mo | ◐ free tier; paid from ~€2.50/mo | free with device | free |

---

## 3. Strength, mobility and nutrition

| Capability | **Open Running Coach** | wger | Waistline | OpenNutriTracker | MyFitnessPal | GOWOD | Pliability | Garmin | Strava |
|---|---|---|---|---|---|---|---|---|---|
| Strength programming | ◐ (log + plan sessions) | ✅ | — | — | — | — | — | ✅ | ◐ |
| Exercise library with video | — | ✅ (200+) | — | — | — | ✅ (240+) | ✅ | ◐ | ◐ |
| Mobility / stretching routines | ◐ (log only) | ◐ | — | — | — | ✅ | ✅ | ◐ (yoga activity) | — |
| Food database / barcode | — (imports exports) | ◐ | ◐ | ✅ (OFF, USDA, BLS) | ✅ (largest) | — | — | — | — |
| Daily macros from an export | ✅ CSV/JSON/ZIP | ✅ | ✅ | ✅ | ✅ | — | — | — | — |
| Steps | ✅ (imported) | — | ✅ | ✅ | ◐ | — | — | ✅ | — |
| Weight history | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | ✅ | ◐ (weight) |
| Supplements / fueling check-in | ✅ | — | — | — | ◐ | — | — | — | — |
| Knowledge of your *training* | ✅ (same DB as runs) | — | — | — | — | ◐ | ◐ | ✅ | ✅ |
| Open source | ✅ AGPL-3.0 | ✅ AGPL-3.0 | ✅ | ✅ | — | — | — | — | — |
| Price | **free** | free (self-host) | free | free | $19.99/mo · $79.99/yr (Premium+ $24.99 / $99.99) | free tier · ~$10/mo | ~$19.95/mo · $14.99/mo annual | device | $11.99/mo |

---

## 4. Metric-by-metric, against the literature

This is the part that matters most, because it is where we are *different*, not
just smaller. Sources and verdicts are in `docs/research/01`–`09`.

| Metric | Who exposes it | Our implementation | Honest assessment |
|---|---|---|---|
| **Training load** | Garmin (EPOC-based), Coros, Polar, Strava (Relative Effort), TP (TSS), Runalyze | Minutes-in-zone × weight 1–6, overridden by session-RPE | An Edwards/Lucía summated-zone index, **not** Banister TRIMP. Defensible ordinal proxy; our weights are not calibrated to anything. Note 01. |
| **CTL / ATL / TSB** | Strava (paid), TP, GoldenCheetah, Runalyze, intervals.icu | 42/7 EWMA, explicit formula in the UI | Same arithmetic as everyone. 42/7 are chart conventions, not physiology, and we cold-start at zero (issue #7). |
| **ACWR** | **Only Garmin** ships an analogue ("Load Ratio"), without bands | 7:28 ratio with four bands | The *only* consumer product framing it with risk bands — and the literature (Impellizzeri, Lolli) does not support that framing. Our differentiator is also our weakest scientific claim (issue #5). |
| **VO2max** | Garmin/Coros/Polar (device, HR), Runalyze (HR-based effective VO2max) | Daniels VDOT from best efforts, no HR needed | Works without a chest strap, which is genuinely unusual. But 400 m is outside Daniels' valid range and `max()` across distances biases upward. Note 06. |
| **Intensity distribution** | Garmin "load focus", others chart zones | Explicit 80/10/10 target with a weekly and 28-day view | Nobody else gives you the *target* as a number; most give a distribution without a benchmark. Note 05. |
| **Race prediction** | Garmin, Coros, Polar, Runalyze | Riegel 1.06 from one best effort | Riegel's own paper fits 1.077–1.083 and refuses extrapolation beyond 1.5–42 km; we predict 400 m and marathon anyway. Note 07. |
| **GAP** | Strava (proprietary), Garmin | Linear 3%/1% model | Under-corrects uphill by roughly half vs Minetti. Note 08. |
| **Injury link** | **nobody** | Episode from run pain reports × hard session × exercise muscles | Unique in the market. Also unvalidated: it surfaces co-occurrence, and the UI says so. |

The pattern worth internalising: **we are not differentiated by having CTL/ATL,
VO2max or race prediction — the incumbents have those.** We are differentiated
by (a) local-first and open, (b) the 80/10/10 target, (c) exercise-level injury
correlation, (d) one database spanning running + strength + mobility + nutrition.

---

## 5. Where we stand

### We win outright
- **Open source, AGPL-3.0, self-hosted.** The only product in this table that is
  a full analysis/coaching application rather than a recorder or a food diary.
  Runalyze — the closest analogue — **discontinued its open-source edition in
  2019** and is now proprietary SaaS. That is both an opportunity (the niche is
  empty) and a warning (it was not economically viable for them).
- **All four domains in one place.** No competitor reads your runs *and* your
  strength sessions *and* your macros *and* your weight from one store.
- **Exercise → injury correlation.** Nobody else attempts it.
- **Explainability.** Formulas, sources and limitations are in the repo and in
  the UI. Commercial apps deliberately hide theirs.
- **Zero cost, zero account, zero telemetry.**

### We reach parity
- Splits, laps, pace zones, GAP, best efforts, heatmap, monthly stats.
- CTL/ATL/TSB, race prediction, VO2max estimation.
- Strength-session logging.

### We lose, clearly
- **Recording.** Every competitor records on a phone or watch. We import files.
  This is the single biggest adoption barrier and cannot be hand-waved: a runner
  will not export a KMZ after every run.
- **Social and segments.** Strava's moat. We have nothing and should not try.
- **Food database and barcode.** MyFitnessPal and OpenNutriTracker own this. We
  import an export; we are not a food logger.
- **Device integration.** Garmin/Coros/Polar measure HR, HRV, sleep, power and
  running dynamics we cannot see. Our metrics are pace-only by design.
- **Mobile UX.** Browser-only, desktop-shaped, no offline record.
- **Content.** GOWOD/Pliability have hundreds of coached videos; we have a text
  field.

### We are alone
- Local-first, open, full-stack training intelligence with exercise-level
  injury reasoning.
- 80/10/10 as an explicit target.
- ACWR with bands — which is precisely the thing the literature says not to do
  (issue #5). Being alone here is not automatically good.

---

## 6. Strategic reading

**The unoccupied square** is not "a better Strava". It is *the athlete who
already owns a watch and a phone app, distrusts subscriptions and cloud storage,
and wants the analysis layer to be theirs* — the F-Droid / self-hosted / privacy
crowd, plus coaches who want to run analysis on a client's files without
uploading health data anywhere.

Three consequences:

1. **Do not compete on recording or social.** Import-only is defensible if it is
   honest and frictionless — which is exactly why the drag-and-drop import
   (commit `920a143`) matters more than it looks. It is the difference between
   "move files into a folder" and "a product".
2. **The metric claims must survive scrutiny.** Our ACWR framing and the
   "injury risk" label are the two places where a knowledgeable reviewer will
   attack us — and where Garmin is more careful than we are (they ship a load
   ratio, not a verdict). Fixing issues #5, #6 and #7 is a competitive move, not
   housekeeping.
3. **Exercise-level injury correlation is the one thing worth building a story
   around.** It is unique, it uses data nobody else collects in the same place,
   and it is currently a heuristic with no validation. It should be presented as
   "patterns worth discussing with your physio", never as a diagnosis.

### Risks
- **Garmin already has Load Ratio**; adding bands is a sprint for them, not a
  moat.
- **AI coaches are commoditising advice.** An LLM wrapper is not defensible;
  the defensible part is the private, structured dataset it reasons over.
- **Sustainability.** Runalyze's founders closed their source to fund the work.
  AGPL-3.0 protects the commons but does not pay for maintenance; a
  hosted-or-support revenue model should be decided before the project's
  popularity forces the question.
- **Scope.** Four domains in one product is our advantage and our maintenance
  burden; the nutrition side in particular is shallow compared to a dedicated
  logger.

### Recommended positioning sentence
> The analysis layer that belongs to you: open source, local-first, and the only
> running coach that connects your strength work to the pain you report.

---

## 7. Sources

- Strava pricing — <https://www.strava.com/pricing> · subscription features —
  <https://support.strava.com/en-us/articles/15402044> · Fitness & Freshness —
  <https://support.strava.com/en-us/articles/15402032>
- Garmin training load, acute/chronic and load ratio —
  <https://support.garmin.com/en-US/?faq=SEkNpdGyhR917js0qQL3Q6> ·
  <https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/training-load/>
- Coros training load — <https://coros.com/stories/coros-metrics/c/training-load>
- TrainingPeaks CTL/ATL/TSB —
  <https://www.trainingpeaks.com/coach-blog/a-coachs-guide-to-atl-ctl-tsb/> ·
  pricing — <https://www.trainingpeaks.com/blog/trainingpeaks-pricing/>
- Runalyze Effective VO2max — <https://runalyze.com/glossary/vo2max> ·
  open-source edition discontinued —
  <https://github.com/Runalyze/Runalyze> (archived 2019)
- Xiaomi training load —
  <https://www.mi.com/global/support/article/KA-108983/> (vendor support page;
  the exact model is not published)
- OpenTracks — <https://github.com/OpenTracksApp/OpenTracks> · FitoTrack —
  <https://f-droid.org/en/packages/de.tadris.fitness/> · Gadgetbridge —
  <https://gadgetbridge.org/>
- GoldenCheetah — <https://www.goldencheetah.org/>
- wger — <https://github.com/wger-project/wger> · OpenNutriTracker —
  <https://play.google.com/store/apps/details?id=com.opennutritracker.ont.opennutritracker>
- MyFitnessPal pricing —
  <https://blog.myfitnesspal.com/myfitnesspal-membership-pricing-tiers/>
- GOWOD — <https://www.gowod.app/> · Pliability —
  <https://pliability.com/stories/gowod-vs-pliability>
