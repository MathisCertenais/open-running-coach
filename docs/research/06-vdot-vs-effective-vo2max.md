# 06 — Daniels' VDOT versus Runalyze's "effective VO2max"

Status: research note. Not a spec.
Applies to: `app/coaching.py` (`_vdot`, `vo2max_and_predictions`),
`app/config.py` (`RACE_DISTANCES`), `GLOSSARY.md` (Effective VO2max, VDOT).
Last reviewed: 2026-10-25.

## The question

1. Is the `%VO2max` equation in `_vdot()` the published Daniels equation?
2. Over what range is it valid?
3. Is VDOT the same thing as Runalyze's "effective VO2max"?
4. Which estimator survives sparse race data, and which way is it biased against
   a laboratory VO2max?

## What the app does

```python
%VO2max = 0.8 + 0.1894393*exp(-0.012778*t) + 0.2989558*exp(-0.1932605*t)
VO2     = -4.60 + 0.182258*v + 0.000104*v^2          # v in m/min
VDOT    = VO2 / %VO2max
```

`t` is minutes, `v = distance_m / t`. `vo2max_and_predictions()` computes a VDOT
for every reference distance in `RACE_DISTANCES` (400 m through marathon) from
the athlete's all-time best effort at that distance, then returns the **maximum**
as `effective_vo2max` and uses that performance as the seed for Riegel
predictions.

## 1. Is the equation the published one?

The two equations are the ones Daniels publishes as the basis of his VDOT
tables: the oxygen-cost-of-running quadratic and the duration-dependent
fractional utilisation curve. They appear in *Daniels' Running Formula*
(Daniels 2014, 3rd ed., Human Kinetics) and descend from the tables in Daniels &
Gilbert (1979), *Oxygen Power: Performance Tables for Distance Runners*.

I could not read the book text online (print-only; no legal full text found).
Verification was therefore numerical, against table entries published in a
peer-reviewed validation study. Foreman, Lee & Lundstrom (2022) report that
their two groups had "VDOT 59.17" and "39.26", "analogous to 5000-m times of
17:15 and 24:27" (*Int J Sports Physiol Perform* 17(7):1030–1036,
doi:10.1123/ijspp.2021-0021, Table 1).

Running the app's exact code on those two performances:

| Performance | `%VO2max` | VDOT computed | VDOT published |
| --- | --- | --- | --- |
| 5000 m in 17:15 | 0.9626 | **59.2** | 59.17 |
| 5000 m in 24:27 | 0.9413 | **39.3** | 39.26 |

That is a match to rounding. **The transcription is correct**; the coefficients,
signs and units (`v` in m/min, `t` in minutes) are right, and the constant `0.8`
is the correct long-duration asymptote.

## 2. What is the valid range?

The curve is an empirical fit, not a physiological identity, and it shows it.
Evaluating it at short durations:

| Duration | `%VO2max` returned |
| --- | --- |
| 1 min (≈400 m) | **1.233** |
| 3.5 min (≈1 km) | **1.133** |
| 8 min | 1.035 |
| 11 min | ≈1.000 |
| 20 min (5 km) | 0.953 |
| 90 min (half) | 0.860 |
| 180 min (marathon) | 0.819 |
| 300 min | 0.804 |

A fraction of VO2max above 1.0 is unphysical: it says the athlete sustained
123% of VO2max for a minute. The fit is simply not constrained there, because
Daniels' tables begin at 1500 m and end at the marathon (Daniels 2014). The
practical domain is therefore roughly **3.5 to 250 minutes, 1500 m to
marathon**. Below ~11 minutes the returned "fraction" exceeds 1, and by 400 m
the model is being asked a question it was never fitted to answer.

Two further consequences:

- The asymptote is 0.8, so from about 4 hours onward the model says the athlete
  can hold 80% of VO2max indefinitely. Any prediction beyond the marathon is
  flat by construction.
- At marathon duration the fraction is 0.819, so the denominator has almost
  stopped falling. A runner whose marathon is relatively strong therefore gets a
  higher VDOT from it than from a 5 km (53.5 versus 49.8 in the example below).
  That is a statement about endurance versus speed, not a measurement of
  aerobic capacity — and the app's `max()` will select the marathon for exactly
  that reason.

## 3. VDOT is not "effective VO2max"

The two are different constructs, and `GLOSSARY.md` already says so:

- **VDOT**: "Daniels' single-number running ability score, derived from a race
  performance and used to compare and predict performances."
- **Effective VO2max**: "An estimate of aerobic capacity inferred from recent
  race performances rather than measured in a laboratory."

The app collapses them: `effective_vo2max` is literally `max(VDOT)`. That is a
vocabulary bug with a user-visible consequence — the UI presents a
performance-equivalence score as if it were an aerobic-capacity estimate.

Runalyze's "Effective VO2max" is a third thing again. Per its own documentation
(primary for what the platform does, not evidence about physiology):

- It is estimated **per activity from heart rate and pace**, not from a race
  result: "This estimation is based on your heart rate and your running pace.
  There are several studies for an approximate relation between heart rate and
  percentage of velocity at VO2max" (Runalyze Help, "VO2max",
  runalyze.com/help/article/vo2max).
- The current value is a 30-day average.
- An individual **correction factor** is fitted from the athlete's best race and
  its heart rate; typical manual values are 0.85–0.95.
- Elevation correction is optional and user-configurable.
- The stated goal is explicitly to *remove* running economy: "we use the
  Effective VO2max that somehow ignores the efficiency and is equal for runners
  with same results for e.g. a 10k race."

So Runalyze answers "what is the aerobic stimulus of this run, given my heart
rate?" and deliberately normalises away economy. Daniels answers "what flat
race performance is this result equivalent to?" and bakes an average economy
into the oxygen-cost curve. They are not interchangeable, and neither is a lab
VO2max.

I found no peer-reviewed validation of Runalyze's model. Its documentation cites
general HR–%vVO2max relationships and Noakes' *Lore of Running*; treat it as a
vendor model, not a validated instrument. That is not a criticism of Runalyze —
it is a statement about the evidence available.

## 4. Bias against laboratory VO2max

The one direct validation I could find is Scudamore, Barry & Coons (2018),
abstract:

> "VDOT underestimated VO2max in ATH (t(10) = −6.00, p < 0.001, d = 1.75) and
> REC (t(8) = −8.96, p < 0.001, d = 3.44) ... the difference between VDOT and
> VO2max was significantly greater in REC than in ATH."
> — *J Strength Cond Res* 32(4):1137–1143, doi:10.1519/JSC.0000000000001942.
> (ATH = NCAA Division I track athletes, n = 11; REC = recreational runners,
> n = 9; both from indoor 5 km time trials.)

So the known bias is **negative**: VDOT reads *lower* than a lab VO2max, and it
under-reads more in recreational runners. The mechanism is structural, not a
bug. VDOT divides the oxygen cost of the observed velocity by the fraction of
VO2max sustainable for that duration. A runner with better-than-average economy
reaches a given velocity at a lower oxygen cost, so the same race time yields a
lower VDOT than their lab VO2max. The more economical the runner, the larger the
apparent underestimate. Foreman et al. (2022) repeat the point: VDOT "may
underestimate true maximal VO2 in a trained population", citing Scudamore.

The app never compares against a lab value, so a negative bias is mostly
harmless for internal consistency. It matters if the number is presented to the
user as "your VO2max": it will read low, and it will read lowest for the most
economical athletes.

## 5. Robustness from sparse race data

Neither estimator is designed for sparse data; they fail differently.

**VDOT needs exactly one maximal performance.** No heart rate, no max HR, no
history. That makes it the only workable estimator for a user who has run one
race and imports GPX files without HR (the OpenTracks default; see
`GLOSSARY.md` and `AGENTS.md` on the missing HR channel). Its weakness is that
the result is only as good as the effort and the distance: a 400 m split from an
interval session is not a maximal 400 m, and even a maximal 400 m is outside the
model's range.

**Runalyze's model needs a maximum heart rate, clean HR for every activity, and
a race to calibrate the correction factor.** Sparse race data means the
correction factor is missing or fitted to a single point; the model then falls
back to a population HR–pace relation. That is a worse position than VDOT for a
local-first app whose default input is GPS without HR.

**The app's specific selection rule is the weakest part.** Taking the maximum
VDOT across seven distances selects the noisiest, most extrapolated estimate.
Worked example (computed with the app's own formula, illustrative athlete):

| Performance | VDOT |
| --- | --- |
| 400 m in 60 s | **68.9** |
| 1 km in 3:30 | 49.4 |
| 5 km in 20:00 | 49.8 |
| 10 km in 41:00 | 50.5 |
| Half marathon in 1:30:00 | 51.0 |
| Marathon in 3:00:00 | 53.5 |

The maximum is 68.9, from a 1-minute effort whose `%VO2max` is 1.23. Even
discounting the 400 m, the spread from 1 km to marathon is 4.1 VDOT points
(≈8%), which is larger than the year-to-year change most recreational runners
see. Reporting the maximum of a noisy set is an upward-biased estimator; one
fast downhill 400 m in a training run is enough to move the headline number by
more than a month of training.

## Verdict for this app

**The formula is right; the range, the aggregation and the label are wrong.**

- **Keep** the two equations exactly as they are. They reproduce Daniels'
  published table entries to the decimal, which is the strongest check available
  without the book.
- **Do not compute VDOT below 5 km.** `RACE_DISTANCES` includes 400 m and 1 km;
  both are outside or at the edge of the fit (400 m returns `%VO2max` = 1.23).
  Either remove them from the VDOT loop or add a guard inside `_vdot()`:
  return `None` when `distance_m < 5000` (and optionally when `t_min > 250`).
  Keep 400 m and 1 km in the *best-effort* table — they are useful as raw
  performances — but not as VDOT inputs.
- **Replace `max(...)` with a robust aggregate.** Compute VDOT over 5 km, 10 km,
  half and marathon; take the **median** (or a distance-weighted least-squares
  fit of a single VDOT across all performances, which is what Daniels'
  equivalence does implicitly). Report the spread. If the spread exceeds ~2
  VDOT points, surface that as "your short and long performances disagree",
  which is real coaching information.
- **Rename the field.** Return `vdot` and, separately, `effective_vo2max` only
  if it is computed by a different model. Today `effective_vo2max == max(vdot)`,
  which contradicts `GLOSSARY.md`. At minimum, change the API/UI label to
  "VDOT" and add a one-line explanation that it is a performance score, not a
  lab measurement. If the glossary is to be honoured literally, `_vdot` should
  be documented as producing VDOT, and "Effective VO2max" reserved for an
  HR-based estimate (which the app does not have).
- **State the bias in the helper text.** VDOT reads low against lab VO2max,
  increasingly so for economical runners (Scudamore et al. 2018). One sentence
  prevents the "my watch says 55, this says 49" support thread.
- **Feed the seed into prediction correctly.** Today the seed is the
  max-VDOT performance, so the race predictions in note 07 inherit the
  short-distance bias. Fixing the aggregation fixes both.

## Open questions

- Would a single-VDOT least-squares fit over 5 km–marathon be more stable than
  the median for users with 2–3 performances? Likely yes, but it needs a guard
  against two performances from the same day.
- Is the 0.8 asymptote defensible for 4 h+ efforts? The curve says 80% of
  VO2max forever; the ultramarathon literature does not support a flat
  asymptote. Out of scope here because `RACE_DISTANCES` stops at the marathon.

## Sources

Read in full:

- Foreman NA, Lee EJ, Lundstrom CJ. Assessment of a treadmill speed incline
  conversion chart: a validation study. *Int J Sports Physiol Perform.*
  2022;17(7):1030–1036. doi:10.1123/ijspp.2021-0021. (Open author manuscript,
  PMC10707652. Source of the published VDOT/5 km pairs used for verification.)
- Runalyze Help. "VO2max" and "Glossary: VO2max".
  https://runalyze.com/help/article/vo2max and
  https://runalyze.com/glossary/vo2max (vendor documentation; primary for what
  the platform computes, not a scientific validation).

Abstract only:

- Scudamore EM, Barry VW, Coons JM. An evaluation of time-trial-based
  predictions of VO2max and recommended training paces for collegiate and
  recreational runners. *J Strength Cond Res.* 2018;32(4):1137–1143.
  doi:10.1519/JSC.0000000000001942.

Book (not read in full; print only):

- Daniels J. *Daniels' Running Formula.* 3rd ed. Champaign, IL: Human Kinetics;
  2014.
- Daniels J, Gilbert J. *Oxygen Power: Performance Tables for Distance Runners.*
  Tempe, AZ; 1979.

The numerical tables in this note were computed by me with the app's own
formula; they are arithmetic, not claims from the papers, and are labelled as
such where they appear.
