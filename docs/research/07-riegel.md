# 07 — Riegel's 1.06: what it was fitted to, and where it breaks

Status: research note. Not a spec.
Applies to: `app/config.py` (`RIEGEL_EXPONENT`, `RACE_DISTANCES`),
`app/coaching.py` (`_riegel`, `vo2max_and_predictions`).
Last reviewed: 2026-10-25.

## The question

Riegel's endurance equation is used to predict every distance from 400 m to the
marathon from one recent best effort. What data produced the 1.06 exponent, over
what range is the equation valid, where does it fail, and what should replace it?

## What the app does

```python
T2 = T1 * (D2 / D1) ** 1.06
```

`RIEGEL_EXPONENT = 1.06`. The seed is the athlete's single best recent effort —
in practice the performance with the highest VDOT (note 06), which is usually the
shortest one. `RACE_DISTANCES` includes 400 m, 1 km, 5 km, 10 km, half and
marathon, so the model routinely extrapolates a 400 m or 1 km effort upward by
40–100× in distance.

## What Riegel actually published

I read the original article (a scan of *American Scientist* 69(3):285–290, May–
June 1981; PMID 7235349). The relevant facts are all in the paper itself.

### The fit

> "Within the endurance range, the logarithms of time vs. distance for each sport
> were best-fitted to straight lines, using least-squares technique. The
> curve-fitting process produced an 'endurance equation,' which is a simple power
> function ... The equation is of the form *t = ax^b*, where *t* = time,
> *x* = distance, and *a* and *b* are constants unique for each activity."
> — Riegel (1981), p. 286.

The data were **world records**, "based on records up to 1 November 1979"
(Table 1, footnote). He pooled running, race walking, Nordic skiing,
roller skating, cycling, speed skating, swimming and man-powered flight, fitting
each separately. It is a description of record performances across different
athletes, not a model of an individual athlete's fatigue curve. Riegel says so:

> "The endurance equation is not set forth as a fundamental theory of human
> locomotion. It is only a simple description of what is observed."
> — p. 290.

### The exponent

Table 1 of the paper gives, for each activity, the fitted *a*, *b*, distance
range and time range. The running rows are:

| Group | *a* | *b* (exponent) | Distance range (km) | Time range (min) |
| --- | --- | --- | --- | --- |
| Running, men | 2.299 | **1.07732** | 1.5–42.2 | 3.5–129 |
| Running, women | 2.598 | **1.08263** | 1.5–42.2 | 3.9–147 |
| Running, men over 40 | 2.569 | 1.05352 | 1.5–42.2 | 4.2–145 |
| Running, men over 50 | 2.841 | 1.05374 | 1.5–42.2 | 4.9–168 |
| Running, men over 60 | 3.204 | 1.05603 | 1.5–42.2 | 5.4–189 |
| Running, men over 70 | 3.654 | 1.06370 | 1.5–42.2 | 5.9–147 |

Riegel calls *b* the "fatigue factor" and notes that "world-class runners, men
and women, have an identical fatigue factor of 1.08", while runners aged 40–70
sit at 1.05–1.06 (p. 286).

**So 1.06 is not the running coefficient in Riegel (1981).** The fitted value for
open men is 1.077 (women 1.083). The 1.06 convention appears to come from
Riegel's earlier popular article (ref. 1 in the paper: "Time predicting",
*Runner's World* 12(8), 1977), which I could not obtain, and it has been copied
between race calculators ever since. As a piece of citation hygiene this matters:
`RIEGEL_EXPONENT = 1.06` is attributed to Riegel (1981) but the paper's own
running fit is 1.077.

### The valid range

Riegel is unusually explicit about where the line stops being straight:

> "In the plot of log (time) vs. log (distance), linearity is lost at times below
> 3 to 4 minutes. This region of athletic competition includes sprints and other
> activity involving transient body processes. Hence it is not included in this
> analysis ... Another region begins above 230 minutes, when the time-distance
> curves begin to bend upward ..."
> — p. 285.

He defines the usable window as the "endurance range" of **3.5 to 230 minutes**,
and closes with:

> "I have avoided extrapolation beyond the limits of the endurance range because
> of the obvious pitfalls."
> — p. 290.

For running the fitted window is narrower still: **1.5–42.2 km, 3.5–129 min**.

The 400 m target in `RACE_DISTANCES` is ≈1 minute — below the floor by a factor
of 3.5. The 1 km target is ≈3–5 minutes — at or below the floor. Both are
sprints in Riegel's taxonomy, where "transient body processes" (anaerobic
capacity, acceleration) dominate and the power law does not hold.

## How far off is it in practice?

Using the app's formula (arithmetic, illustrative):

| Seed performance | Predicted with *b* = 1.06 | Predicted with *b* = 1.077 |
| --- | --- | --- |
| 400 m in 60 s → 5 km | 14:33 | 15:11 |
| 400 m in 60 s → marathon | 2:19:30 | 2:31:00 |
| 5 km in 20:00 → marathon | 3:11:49 | 3:18:54 |
| 5 km in 17:15 → marathon | 2:45:27 | 2:51:33 |

Two separate problems are visible.

1. **The short anchor is catastrophic.** A 60-second 400 m is a respectable club
   sprint, not a 2:19 marathon. The prediction is not "a bit optimistic": it
   ignores the entire anaerobic contribution that made the 400 m fast, and
   Riegel's own fit excludes that region. This is an out-of-range extrapolation,
   not a modelling nuance.
2. **The exponent choice is a calibration decision.** For a recreational 20:00
   5 km runner, 1.06 predicts 3:11:49 and 1.077 predicts 3:18:54. Most such
   runners do not run 3:19, so 1.06 may look better *for that population* even
   though it is not Riegel's fitted running value. The honest statement is that
   1.06 is a deliberately forgiving exponent, not a reproduction of the paper.
   Either justify it as such in the config comment, or use 1.077 and accept that
   predictions will read slow until the athlete's endurance is established.

A third, subtler issue: Riegel's data are *maximal, evenly paced, measured-course
race performances*. The app's seed is a best effort extracted from an ordinary
training run. That segment may be:
- not maximal (seed time too slow → predictions too slow), or
- measured on GPS distance that over-reads by 2–6% (note 05), which makes the
  apparent pace faster → predictions too fast.

The two errors do not cancel reliably. Predictions should therefore carry a
range, not a point.

## Alternatives

### 1. VDOT equivalence (Daniels)

Instead of a power law, invert the two Daniels equations: find the time *t* at
distance *D* such that `VO2(D/t) = VDOT · %VO2max(t)`. This is Daniels' own
definition of equivalent performance and is already 80% implemented in
`_vdot()`; it needs a bisection over *t*. Advantages: internally consistent with
the number the app already displays, and it naturally slows the predicted
exponent at long durations because `%VO2max` flattens. Disadvantages: it inherits
the VDOT range limits (1500 m–marathon) and the average-economy assumption.

### 2. Critical speed

The two-parameter model `D = CS·t + D'` (CS = critical speed, D' = finite
distance capacity) is the standard alternative for efforts of a few minutes.
Drake, Finke & Ferguson (2024) show that the hyperbolic (critical-power) form
"unrealistically represents efforts that are short (< 2 minutes) or long
(> 15 minutes)", and that within 2–15 min a hyperbolic curve merely approximates
a power law (*Eur J Appl Physiol* 124(2):507–526,
doi:10.1007/s00421-023-05274-5). Critical speed is therefore a good model for
1–5 km and a poor one for the marathon, and it needs at least two maximal efforts
in the 3–15 min range. It cannot replace Riegel for a single-seed,
400 m-to-marathon table.

### 3. A power law with an individual exponent

The same paper argues the power-law form is the better global description and
"a safer tool for pace selection" than critical power. Zinoubi, Vandewalle &
Driss (2017) fitted power laws to two elite runners and eleven physical-education
students and found the exponent was **not constant**: "Exponent γ is close to 1
in elite runners and lower in PESs (from 0.625 to 0.872) ... exponent γ can be
considered as an index of aerobic endurance" (*J Strength Cond Res*
31(7):1859–1867, doi:10.1519/JSC.0000000000001542; abstract).

This is the strongest argument against a global constant: the exponent is an
athlete property, correlated with endurance, not a law of nature. With one
performance you cannot estimate it; with two you can.

### 4. Machine learning

Lerebourg et al. (2023) predicted marathon time from 10 km time, BMI, age and sex
using k-nearest neighbours and an artificial neural network; KNN achieved a mean
absolute error of 2.4% versus 5.6% for the ANN (*Int J Sports Med* 44(5):352–360,
doi:10.1055/a-1993-2371; abstract). Accurate, but it needs a population dataset
and cannot run offline on one athlete's history. Not a fit for a local-first,
stdlib-only app.

### 5. "Camargo et al."

I could not identify a peer-reviewed running-performance prediction model
attributable to Camargo et al. Searches of Crossref and Europe PMC for
author = Camargo with race-time/performance-prediction terms returned nothing
relevant. If this reference is real, it needs a full citation before it can be
used; until then it should not be cited. The credible published alternatives are
the four above.

## Verdict for this app

**Not defensible as implemented.** Three independent problems, in order of
severity:

1. **Out-of-range targets.** 400 m and 1 km are outside Riegel's endurance range
   (3.5–230 min; running fit 1.5–42.2 km). Predicting a marathon from a 400 m
   effort is a 100× extrapolation into a region the author explicitly refused to
   extrapolate into. **Remove 400 m and 1 km from the prediction targets** (keep
   them as recorded best efforts). Restrict `RACE_DISTANCES` to 5 km–marathon,
   or split it into `BEST_EFFORT_DISTANCES` (all, for display) and
   `PREDICTION_DISTANCES` (5 km–marathon, for the model).
2. **Wrong anchor.** The seed is chosen by maximum VDOT, which selects the
   shortest, least reliable performance (note 06). Anchor on the **longest**
   recent maximal effort in 5 km–half marathon, or on a robust VDOT fit. Do not
   seed from anything shorter than 5 km.
3. **Unjustified exponent.** `RIEGEL_EXPONENT = 1.06` is attributed to Riegel
   (1981) but the paper's running fit is 1.077 (men) / 1.083 (women); 1.06 is a
   rounded convention from his earlier popular article. Either set
   `RIEGEL_EXPONENT = 1.077` and cite the paper accurately, or keep 1.06 and
   change the comment to say it is a deliberately conservative-for-recreational
   exponent, not Riegel's fitted value. What must not stand is the current
   combination of the number and the citation.

Additionally:

- **Bound the extrapolation.** Even within 5 km–marathon, refuse to predict more
  than ~2× away from the anchor distance, or mark those rows as "extrapolated".
  A 5 km → marathon prediction is 8.4× and already at the edge of usefulness;
  400 m → marathon is 105×.
- **Report a range.** ±3–5% is honest given GPS distance error (note 05) and
  pace variability. A single predicted time to the second implies precision the
  model does not have.
- **Prefer VDOT inversion when a VDOT is available.** It is the same model the
  app already trusts for the fitness number, it degrades gracefully at long
  durations, and it needs no new dependency (bisection over `t` in ~40
  iterations). Keep Riegel as the fallback for users with only one performance.
- **Do not cite "Camargo et al."** until a full reference exists. Add the
  Zinoubi and Drake references to the config comment if the exponent is to be
  defended as an individual property.

## Sources

Read in full (scan of the original):

- Riegel PS. Athletic records and human endurance. *American Scientist.*
  1981;69(3):285–290. PMID 7235349. (No DOI; JSTOR 27850427.)

Read in full (open access):

- Drake JP, Finke A, Ferguson RA. Modelling human endurance: power laws vs
  critical power. *Eur J Appl Physiol.* 2024;124(2):507–526.
  doi:10.1007/s00421-023-05274-5.

Abstract only (paywalled full text):

- Zinoubi B, Vandewalle H, Driss T. Modeling of running performances in humans:
  comparison of power laws and critical speed. *J Strength Cond Res.*
  2017;31(7):1859–1867. doi:10.1519/JSC.0000000000001542.
- Lerebourg L, Saboul D, Clémençon M, Coquart JB. Prediction of marathon
  performance using artificial intelligence. *Int J Sports Med.*
  2023;44(5):352–360. doi:10.1055/a-1993-2371.

Not obtained:

- Riegel PS. Time predicting. *Runner's World.* 1977;12(8). Cited as ref. 1 by
  Riegel (1981); the likely origin of the 1.06 convention. I could not retrieve
  it, so the claim that 1.06 originates there is inference, not established fact.

All predicted times in this note were computed with the app's formula and are
arithmetic illustrations, not values reported in the papers.
