# CTL, ATL and TSB: what the Performance Management Chart actually measures

This note covers `fitness_series` and `_form_band` in `app/coaching.py`, and the
constants `CTL_TAU_DAYS`, `ATL_TAU_DAYS`, and `FORM_NEUTRAL_BAND` in
`app/config.py`. The load input to these series is discussed in
`01-pace-zone-load.md` and `02-session-rpe.md`; ACWR is discussed separately in
`04-acwr.md`.

## 1. The model as implemented

```
CTL_t = CTL_{t-1} + (TL_t - CTL_{t-1}) / 42
ATL_t = ATL_{t-1} + (TL_t - ATL_{t-1}) / 7
TSB_t = CTL_t - ATL_t
```

Both series start at `0.0` on the first day with an activity, the daily series is
zero-filled, and TSB is banded as `fresh` above +5, `fatigued` below −5, and
`neutral` in between.

This is the Performance Management Chart (PMC) popularised by Coggan and Allen.
It is an exponentially weighted moving average of daily training load with two
time constants. Nothing more.

## 2. Where the model comes from

The intellectual lineage is the Banister impulse-response model (Banister et al.,
1975; Calvert et al., 1976; Morton et al., 1990). In that model a training impulse
produces two responses, a positive "fitness" term and a negative "fatigue" term,
each decaying exponentially, with performance modelled as their difference. The
two time constants are **fitted to the individual athlete's performance data**;
Clarke and Skiba (2013) describe the model as having five adjustable parameters,
including the two decay constants, and explain that it is calibrated by nonlinear
regression against repeated time trials.

Coggan's PMC keeps the shape and fixes the constants. TSS was introduced in 2003
and the PMC was presented in 2008; the constants and the chart are documented in
Allen and Coggan's *Training and Racing with a Power Meter* and in the
TrainingPeaks/WKO documentation (TrainingPeaks, 2016; WKO, 2022). The software
defaults are 42 days for the chronic term and 7 days for the acute term.

**Where 42 and 7 come from.** I could not find a peer-reviewed derivation or
validation of this specific pair. They are not the original Banister model
parameters: Calvert et al. (1976) specified a fitness time constant of 50 days and
a fatigue time constant of 15 days for their swimmer, and later work fits the
constants per athlete, with values in the literature ranging from 4 to 51 days for
the fitness constant and 4 to 74 days for the fatigue constant (Vermeire et al.,
2022). The most defensible statement is that 42 days is six weeks and 7 days is one
week, matching the conventional mesocycle and microcycle units of training
planning. Hulin et al. (2014), writing about the ACWR's 1-week/4-week windows,
describe that choice as "arbitrary" but convenient for exactly this reason. The
same logic applies here.

I could not access Allen and Coggan's book (print/paid), so I cannot quote
Coggan's own rationale. I am reporting the absence of a published derivation, not
asserting that none exists in the book.

## 3. What evidence supports the constants

Very little, and what exists is about the model family rather than the pair.

- Morton et al. (1990) fitted the two-component model to running performance data
  and reported significant correlations between predicted and actual performance
  during training and tapering. That is an individual-level model fit, not a
  population validation, and the constants were fitted rather than fixed.
- Clarke and Skiba (2013) show that the impulse-response model can fit individual
  data well (R² > 0.90 in some cases) when its parameters are estimated. That is
  evidence for fitting, not for 42/7.
- Vermeire et al. (2022) show that the parameters are not independently
  identifiable: different combinations of time constants and gain terms produce
  similar model errors, and the fitted values depend on the starting values, the
  optimisation method, and the load metric used. Their conclusion is explicit:
  "the use of general constants should be avoided since they do not account for
  interindividual differences and differences between training-load methods."
- Imbach et al. (2022) reach a similar conclusion from the modelling side: the
  fitness-fatigue family is univariate and simplifies the physiology, and its
  predictive performance is "mitigated".

There is, as far as I can find, **no validation of the 42/7 pair in recreational
runners**. The PMC was built for cycling power data; TrainingPeaks' own WKO
documentation states that the chart "was originally designed for cycling" and
that "its efficacy for runners has not been widely reported". That is a vendor
statement about industry practice, not evidence, but it is the most direct
published comment on the running use case.

## 4. Is CTL a measure of fitness?

No, and the app's glossary overstates it when it says CTL represents "the fitness
an athlete has built".

CTL is a low-pass filter applied to a load proxy. It is monotone in load, not in
performance. An athlete can raise CTL with high-volume easy running and get
slower; another can lower CTL during a taper and race a personal best. The number
has no physiological unit, no calibration against a measured capacity, and no
performance term.

This is not a reason to delete it. An exponentially weighted average of recent
load is a useful descriptive summary, and the qualitative behaviour it encodes —
load accumulates slowly, fatigue clears quickly — is robust. The problem is the
label. "Fitness" is a claim; "chronic load" is a description. The same applies to
"fatigue" for ATL and "form" for TSB. The glossary's own hedging ("a slow-moving
average of daily training load") is correct, but the first clause of the
definition is not.

## 5. What happens with irregular training

This is where the implementation produces numbers that are not about training at
all. There are four distinct effects.

### 5.1 Cold start

Because `ctl` and `atl` both start at 0, the series needs months to converge even
under a perfectly constant load. With a constant 100 units per day:

| Day | CTL | ATL | TSB | App label |
| --- | --- | --- | --- | --- |
| 21 | 39.7 | 96.1 | −56.4 | fatigued |
| 42 | 63.7 | 99.9 | −36.2 | fatigued |
| 84 | 86.8 | 100.0 | −13.2 | fatigued |
| 126 | 95.2 | 100.0 | −4.8 | neutral |

For the first four months of **constant** training the app reports the athlete as
fatigued, because ATL converges in about three weeks and CTL takes about four
months to reach 95 % of its steady state. This is an initialisation artefact, not
a physiological finding. A new user will be told they are fatigued for a whole
training block no matter what they do.

### 5.2 Layoffs read as freshness

After 100 days at 100 units/day (CTL ≈ 90.8, ATL ≈ 100), ten days off gives
CTL ≈ 71.6 and ATL ≈ 24.0, so TSB ≈ +47.6 and the app says "fresh". The athlete
is detrained, not fresh. The same happens after illness or injury. A "fresh" label
should require recent load, not merely the absence of it.

### 5.3 Zero-fill and sparse data

`full_load_series` fills every calendar day, which is correct for exponential
decay. But it also means a week with no uploads — a watch failure, a holiday
without GPS — decays both series as if the athlete had rested. There is no way to
distinguish "did not train" from "did not record".

### 5.4 Source switching

The daily load can come from pace one day and RPE the next, and those two sources
are on different scales (see `02-session-rpe.md`). Starting to log RPE therefore
raises ATL faster than CTL and produces a negative TSB that reflects a change in
measurement, not training.

## 6. Two smaller implementation points

- **Discretisation.** The update `ctl += (tl - ctl) / 42` is the Euler form. It
  converges to the same steady state as the exact exponential
  `ctl·e^(−1/42) + tl·(1 − e^(−1/42))`, but its effective time constant is 41.5
  days rather than 42. This is negligible in practice and is noted only for
  completeness.
- **TSB timing.** Coggan's chart conventionally plots TSB from the previous day's
  CTL and ATL, because today's session has not been absorbed when the athlete
  wakes up. The app computes TSB after adding today's load. Neither is wrong;
  they answer slightly different questions. The docstring should say which one
  it does.

## 7. The unit problem

The app's CTL is in "zone-minutes per day", not TSS. A recreational runner doing
five hours per week entirely in Z2 accumulates 600 units per week, or 85.7 per
day, so their steady-state CTL is about 86. In TSS terms the same training is
roughly 35–40 per day. The number 86 looks like a trained cyclist's CTL and is not
one. This matters because published PMC guidance (for example, "CTL 100") is in
TSS units, and because `FORM_NEUTRAL_BAND = 5.0` is expressed in the app's units,
where five units is a much smaller fraction of a typical CTL than five TSS points
is of a typical TSS-based CTL.

## References

- Allen H, Coggan AR. *Training and Racing with a Power Meter.* 2nd ed. Boulder,
  CO: VeloPress; 2010. (3rd ed., 2019.)
- Banister EW, Calvert TW, Savage MV, Bach TM. A systems model of training for
  athletic performance. *Aust J Sports Med.* 1975;7(3):57–61.
- Calvert TW, Banister EW, Savage MV, Bach TM. A systems model of the effects of
  training on physical performance. *IEEE Trans Syst Man Cybern.*
  1976;SMC-6(2):94–102. doi:10.1109/TSMC.1976.5409179
- Clarke DC, Skiba PF. Rationale and resources for teaching the mathematical
  modeling of athletic training and performance. *Adv Physiol Educ.*
  2013;37(2):134–152. doi:10.1152/advan.00078.2011
- Hulin BT, Gabbett TJ, Blanch P, Chapman PC, Bailey D, Orchard JW. Spikes in
  acute workload are associated with increased injury risk in elite cricket fast
  bowlers. *Br J Sports Med.* 2014;48(8):708–712.
  doi:10.1136/bjsports-2013-092524
- Imbach F, Sutton-Charani N, Montmain J, Candau R, Perrey S. The use of
  fitness-fatigue models for sport performance modelling: conceptual issues and
  contributions from machine-learning. *Sports Med Open.* 2022;8(1):29.
  doi:10.1186/s40798-022-00426-x
- Morton RH, Fitz-Clarke JR, Banister EW. Modeling human performance in running.
  *J Appl Physiol.* 1990;69(3):1171–1177. doi:10.1152/jappl.1990.69.3.1171
- TrainingPeaks. Normalized Power, Intensity Factor and Training Stress Score.
  2016. https://www.trainingpeaks.com/learn/articles/normalized-power-intensity-
  factor-training-stress/ (industry documentation, not evidence).
- Vermeire K, Ghijs M, Bourgois JG, Boone J. The fitness–fatigue model: what's in
  the numbers? *Int J Sports Physiol Perform.* 2022;17(5):810–813.
  doi:10.1123/ijspp.2021-0494
- WKO. How to analyze runners' training load in WKO using the Performance Manager
  Chart. 2022. https://wko5.zendesk.com/hc/en-us/articles/8012212996621
  (industry documentation, not evidence).

### Access notes

Allen and Coggan's book is not open access and I could not read it; the PMC
defaults are therefore cited from the secondary technical documentation above and
from the constants as implemented in this app. Calvert et al. (1976) was read as
an abstract, which states the 50-day and 15-day time constants; the full text is
paywalled. Morton et al. (1990) was read as an abstract (the full text is
paywalled); the claim about fitted time constants is supported by Clarke and Skiba
(2013), which was read in full. Banister et al. (1975) was not read directly; it is
cited through Clarke and Skiba (2013). TrainingPeaks and WKO pages are vendor
documentation and are cited only as evidence of what the industry does, not as
scientific support.

## Verdict for this app

**The EWMA is defensible as a descriptive summary. The physiological labels, the
cold start, and the fixed band are not.**

CTL and ATL are arithmetic on a load proxy. That is a legitimate thing for an app
to compute and plot, and the qualitative behaviour is useful. What is not
defensible is presenting the output as "fitness", "fatigue", and "form" without
qualification, and then labelling an athlete "fatigued" for four months because
the moving averages started at zero.

Concrete changes, in priority order:

1. **Fix the cold start.** Either initialise `ctl` and `atl` from the first 28
   days of load, or suppress the form band until 42 days of history exist, or
   display a "still calibrating" state. The current behaviour is the single
   largest source of wrong labels in the app.
2. **Make `FORM_NEUTRAL_BAND` scale-relative.** A fixed ±5 in arbitrary load units
   has no stable meaning. Express it as a fraction of CTL (for example
   `FORM_NEUTRAL_BAND_PCT = 0.10`) and keep the absolute constant only as a
   fallback.
3. **Add a detraining state.** If ATL is well below CTL after a layoff, that is
   not "fresh". A third condition on recent load (or on days since the last
   activity) is needed before the `fresh` label is shown.
4. **Rename the user-facing concepts.** "Fitness" should be "chronic load";
   "fatigue" should be "acute load"; "form" should be "load balance". The glossary
   already defines them as averages; the UI should not upgrade that to a
   physiological claim.
5. **Keep `CTL_TAU_DAYS = 42.0` and `ATL_TAU_DAYS = 7.0` as defaults, but document
   them as conventions.** Do not claim they are validated. If they are ever made
   user-adjustable, say what range the literature reports (4–51 and 4–74 days;
   Vermeire et al., 2022).
6. **Normalise the load unit** (see `01-pace-zone-load.md`) so that CTL is
   comparable to published TSS-based guidance. Until then, do not show CTL against
   any external benchmark.
7. **State the TSB convention** in the docstring: same-day or previous-day. Pick
   one and keep it.

Defensible use of the current numbers: as a smooth trend line for one athlete on
one load source, with the axis labelled "arbitrary units". Not defensible: as a
readiness score, as a comparison between athletes, or as a reason to change
training on its own.
