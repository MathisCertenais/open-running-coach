# 08 — Grade-adjusted pace: Minetti, Strava, Daniels, and what a linear model costs

Status: research note. Not a spec.
Applies to: `app/config.py` (`GAP_UPHILL_FACTOR`, `GAP_DOWNHILL_FACTOR`,
`GAP_MAX_DOWN_GRADE`), `app/analysis.py` (`_gap_factor`, `compute_gap`,
`_steps`, `_smooth_altitudes`).
Last reviewed: 2026-10-25.

## The question

The app converts every step's grade into a multiplicative speed factor with a
straight line: +3% of equivalent speed per +1% grade, −0.5% per −1% grade, with
descents clipped at −15%. How far is that from the published energy-cost model
(Minetti et al. 2002), what does Strava actually do, and what would a better
approximation look like using only the standard library?

## What the app does

```python
factor(g) = 1 + 3.0*g        # g > 0, g as a fraction
factor(g) = 1 + 0.5*g        # g < 0, g clipped at -0.15
gap_time += dt_moving / factor
```

The algebra is correct. If `factor = v_flat / v_actual` (the ratio of the speed
you could hold on the flat to the speed you actually held), then covering a step
of duration `dt` takes `dt / factor` at flat speed for the same distance. So
`compute_gap()` is internally consistent: dividing time by a speed ratio is the
right operation, and the result is a flat-equivalent pace.

The question is whether `factor(g)` resembles any published curve.

## Minetti et al. (2002): the energy-cost reference

Minetti AE, Moia C, Roi GS, Susta D, Ferretti G. "Energy cost of walking and
running at extreme uphill and downhill slopes." *J Appl Physiol.*
2002;93(3):1039–1046. doi:10.1152/japplphysiol.01177.2001.

Ten runners on a treadmill at grades from −0.45 to +0.45. The running cost of
transport (J·kg⁻¹·m⁻¹) was fitted with a fifth-order polynomial:

```
Cr(i) = 155.4·i^5 − 30.4·i^4 − 43.3·i^3 + 46.3·i^2 + 19.5·i + 3.6
```

where `i` is the gradient as a fraction, R² = 0.999. Reported values:
level cost 3.40 ± 0.24 J·kg⁻¹·m⁻¹, minimum 1.73 ± 0.36 at −0.20, and
18.93 ± 1.74 at +0.45 (abstract). The polynomial's intercept is 3.6, not the
measured 3.40 — the fit trades a little level-ground accuracy for the extremes.
Normalising by the polynomial's own `Cr(0) = 3.6` is the convention Strava used
in its original Minetti-based GAP, and it is the one used below.

Two things this model is and is not:

- It is **metabolic cost at a constant treadmill speed**. It is not measured
  overground pace, and it does not include the biomechanical cost of turning,
  technical terrain, or the fact that runners choose different speeds downhill.
- It is **not an effort model**. Strava's own engineering write-up is blunt about
  this: the original paper "accurately predicted uphill race performance, but
  errs on downhill race performance by as much as a factor of 3x" (Robb, "An
  Improved GAP Model", Strava Engineering, 2017). That is a vendor statement, not
  a peer-reviewed finding, but it is consistent with the shape of the curve.

### Minetti versus the app's line

Factor = `Cr(g) / Cr(0)`. Equivalent flat pace shown for an actual 5:00/km.

| Grade | Minetti factor | App factor | App GAP | Minetti GAP |
| --- | --- | --- | --- | --- |
| +15% | 2.060 | 1.450 | 3:26 | 2:25 |
| +10% | 1.658 | 1.300 | 3:50 | 3:00 |
| +5% | 1.301 | 1.150 | 4:20 | 3:50 |
| +2% | 1.113 | 1.060 | 4:43 | 4:29 |
| 0% | 1.000 | 1.000 | 5:00 | 5:00 |
| −2% | 0.897 | 0.990 | 5:03 | 5:34 |
| −5% | 0.763 | 0.975 | 5:07 | 6:33 |
| −10% | 0.598 | 0.950 | 5:15 | 8:21 |
| −15% | 0.510 | 0.925 | 5:24 | 9:48 |

Read the uphill half first. At the origin Minetti's cost rises at
`Cr'(0)/Cr(0) = 19.5/3.6 = 5.4%` per 1% grade. The app uses 3.0%, i.e. **56% of
the published slope**. The gap compounds: at +5% the app is 15 percentage points
low, at +10% it is 36 points low. In pace terms, a 5:00/km effort up a steady 5%
climbs to 4:20 GAP in the app but 3:50 by Minetti — 30 s/km of under-credit.

Now the downhill half, where the comparison changes character. The app's
0.5%-per-1% line is *hugely* flatter than Minetti: at −5% it gives 0.975 where
Minetti gives 0.763; at −15% it gives 0.925 where Minetti gives 0.510. If Minetti
were the right target, the app would be wrong by 40 percentage points at the
cap. But the Minetti GAP of 9:48 for a 5:00/km descent at −15% is obviously not
"the same effort" — nobody runs 9:48/km effort downhill. That absurdity is the
point: Minetti prices the *metabolic cost* of downhill running, and much of that
cost is eccentric muscle work that does not translate into a proportionally
slower flat-equivalent pace. **Minetti is the right reference uphill and the
wrong reference downhill.**

## What Strava does

Strava's current GAP is not Minetti. Two vendor sources:

- **Strava Support, "What is Grade-Adjusted Pace (GAP) on Strava?"**: "Athlete
  data has shown that the downhill adjustment peaks around −10%, after which it
  becomes slightly less extreme." (support.strava.com, article 15402117)
- **Strava Engineering, "An Improved GAP Model" (2017)**: the old model was
  Minetti-based; the new model was fitted to heart-rate-derived efficiency from
  a very large activity dataset, and is defined so that "GAP should be the pace
  that a runner could achieve at the same heart rate while running on level
  ground." Reported properties: the new curve's slope uphill is close to
  Minetti's, shifted right by ~2%; downhill it predicts a **minimum adjustment
  of about 0.88 at −9%**, returning to **1.0 by −18%**, against the old model's
  ~0.5 at −18%.

Strava does not publish the coefficients. What can be taken from this is the
*shape*: uphill ~5% per 1% grade, downhill a shallow valley with a minimum
around −9% to −10% and a recovery toward 1.0 beyond it.

The app's downhill line has the wrong shape in both directions: too little
adjustment from 0 to −10% (0.95 at −10% versus Strava's 0.88), and too much
adjustment beyond −12% (0.925 at −15%, where Strava is heading back toward 1.0).
It is, accidentally, not far from Strava at −15% — but for the wrong reason.

## Daniels' incline table is not a fix

Daniels' treadmill speed–incline conversion chart (the one popularised by
HillRunner.com) is sometimes proposed as a GAP model. It was tested directly:
Foreman, Lee & Lundstrom (2022) ran trained runners at chart-equivalent
speed/incline combinations and found the chart valid only **at or below a 4%
incline**. Above 4%, "supposedly equivalent stages result in increased exercise
intensity" — VO2, heart rate, blood lactate and leg RPE all rose despite the
chart's speed reduction (*Int J Sports Physiol Perform* 17(7):1030–1036,
doi:10.1123/ijspp.2021-0021).

So the Daniels/HillRunner chart under-corrects above 4%, just like the app's
line, and it is validated only for submaximal treadmill running. It is not a
better GAP model than Minetti; it is a different, narrower tool.

## The bigger problem: the grade input

`compute_gap()` applies `_gap_factor()` to the grade of each individual step.
`_steps()` computes that grade as `(alt_b − alt_a) / d` between consecutive GPS
points, using altitude smoothed by a 5-point moving average
(`_smooth_altitudes(window=5)`). At 1 Hz and 3 m/s, a step is ~3 m long and the
altitude window is ~15 m.

Consumer GPS vertical error is metres, not centimetres (note 09 reports
horizontal errors of 7–9 m; vertical is typically worse). A ±3 m altitude error
over a 3 m step is a grade of ±100%. Applying a 3.0 multiplier to a signal that
swings between −100% and +100% does not produce a noisy GAP; it produces a
random walk. No choice of `GAP_UPHILL_FACTOR` fixes that. **Grade must be
computed over a distance long enough for the elevation signal to exceed the
noise** — 50–100 m, or 20–30 s, is the usual engineering compromise for
consumer GPS.

## A better approximation, stdlib only

Two changes, in order of importance.

### 1. Compute grade over a window

```python
GAP_GRADE_WINDOW_M = 50.0  # metres; below this, altitude noise dominates


def _windowed_grade(distances, altitudes, i, window=GAP_GRADE_WINDOW_M):
    """Grade over the smallest surrounding window of at least `window` metres."""
```

Walk backwards and forwards from point `i` until at least `window` metres of
horizontal distance are covered, then divide the altitude difference by the
horizontal distance. Clip the result to ±0.15. Use the *same* grade for every
step inside the window (or interpolate between window centres) so the correction
is smooth.

### 2. Replace the straight line

**Minimum change (keeps the linear form):**

- `GAP_UPHILL_FACTOR = 5.4` (Minetti's slope at the origin), not 3.0.
- `GAP_DOWNHILL_FACTOR = 1.5` with `GAP_MAX_DOWN_GRADE = 0.09` and an explicit
  floor, e.g. `max(0.88, 1 + 1.5*g)`. This approximates Strava's published
  minimum without pretending to model the turnaround.

That is a two-line change and moves uphill GAP to within ~10% of Minetti up to
about 8%, which is as far as a line can go.

**Better (keeps Minetti uphill, bounded effort curve downhill):**

```python
def _cost_ratio(grade: float) -> float:
    """Minetti et al. (2002) running cost, normalised to flat.

    Cr(i) = 155.4 i^5 - 30.4 i^4 - 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6
    Valid for -0.45 <= i <= 0.45; we clip to +/-0.15.
    """
    i = max(-0.15, min(0.15, grade))
    cr = 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6
    return cr / 3.6


def _gap_factor(grade: float | None) -> float:
    if not grade:
        return 1.0
    if grade > 0:
        return _cost_ratio(grade)
    # Downhill: Minetti prices eccentric work, not achievable pace.
    # Anchor on Strava's published points (0, 1.0), (-0.09, 0.88), (-0.18, 1.0).
    g = max(-0.18, grade)
    return max(0.88, 1.0 + 2.667 * g + 14.81 * g * g)
```

The downhill quadratic is an **engineering fit**, not a published model: it is
the parabola through the three points Strava reports. It reproduces 0.88 at −9%,
0.90 at −5%, 0.89 at −12% and 1.0 at −18%. It should be documented as such, with
the Strava reference, and treated as provisional until better data exists.

Optionally, clamp the uphill input at +12% rather than +15%: the polynomial is
steep there (2.06 at +15%), so small grade errors become large pace errors.

## Where GAP should be used

- **Pace zones.** `intensity_distribution()` buckets raw pace (note 05). On a
  hilly course that turns easy uphill running into "moderate" or "hard" time.
  Zones should be assigned on GAP pace, not raw pace.
- **Split comparison and matched runs.** Comparing a hilly run to a flat one is
  the entire purpose of GAP; comparing raw pace across routes is a known trap.
- **Not** for records or best efforts. A best effort is a raw performance; a
  "GAP 5 km best" is a different, invented distance. Keep them separate.

## Verdict for this app

**Not defensible as a physical model, though it is not dangerous.** Three
findings:

1. **Uphill is under-corrected by roughly a factor of two.** Minetti's slope at
   the origin is 5.4% per 1% grade; `GAP_UPHILL_FACTOR = 3.0` is 56% of that. At
   +5% the app's GAP is 30 s/km slower than the energy model for a 5:00/km
   effort; at +10% it is 50 s/km slower. If GAP is meant to be an
   energy-equivalence pace, this is a real error. Set
   `GAP_UPHILL_FACTOR = 5.4` at minimum, or implement `_cost_ratio()`.
2. **Downhill is the wrong shape, not merely the wrong slope.**
   `GAP_DOWNHILL_FACTOR = 0.5` with `GAP_MAX_DOWN_GRADE = 0.15` gives a monotone
   0.925 at −15%. Both the energy model (minimum ~0.49 at −18%) and Strava's
   effort model (minimum ~0.88 at −9%, back to 1.0 at −18%) disagree. Replace
   the linear descent with the bounded quadratic above; keep the −15% cap only
   as an input guard.
3. **The per-step grade makes both constants moot.** With `_smooth_altitudes`
   over five points and grades computed between adjacent 3 m steps, the input is
   dominated by altitude noise. **This is the highest-priority fix**: compute
   grade over ≥50 m before applying any factor. Without it, changing the
   constants is cosmetic.

Also:

- **Say what GAP means.** The config comment calls it a "simplified model". Make
  it explicit: *uphill = Minetti energy cost; downhill = bounded effort curve
  anchored on Strava's published points; not validated for trail or technical
  terrain.* `CODING_STANDARDS.md` requires formula-bearing code to name its
  source; right now it names none.
- **Pin the curve to an external reference in tests.** `tests/test_analysis.py`
  has three GAP tests, but they assert the implementation against its own
  constants (`1 + GAP_UPHILL_FACTOR * 0.05`), so they would pass for any
  coefficient. Add reference-value tests at fixed grades (+/−2, 5, 10, 15%)
  computed from the chosen model, so a constant change cannot silently move the
  curve. `CODING_STANDARDS.md` rule 14 says literature beats implementation;
  these tests are the mechanism.

## Sources

Read in full:

- Minetti AE, Moia C, Roi GS, Susta D, Ferretti G. Energy cost of walking and
  running at extreme uphill and downhill slopes. *J Appl Physiol.*
  2002;93(3):1039–1046. doi:10.1152/japplphysiol.01177.2001. (Abstract and
  results section including the polynomial read at the publisher's site.)
- Foreman NA, Lee EJ, Lundstrom CJ. Assessment of a treadmill speed incline
  conversion chart: a validation study. *Int J Sports Physiol Perform.*
  2022;17(7):1030–1036. doi:10.1123/ijspp.2021-0021. (Open author manuscript,
  PMC10707652.)

Vendor documentation (primary for what the platform does, not evidence about
physiology):

- Robb D. "An Improved GAP Model." Strava Engineering, 3 October 2017.
  https://medium.com/strava-engineering/an-improved-gap-model-8b07ae8886c3
- Strava Support. "What is Grade-Adjusted Pace (GAP) on Strava?"
  https://support.strava.com/en-us/articles/15402117

The factor table and all pace conversions in this note were computed by me from
the Minetti polynomial and the app's constants; they are arithmetic, not values
reported in the papers.
