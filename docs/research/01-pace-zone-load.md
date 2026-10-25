# Pace-zone load: is "minutes in zone × weight 1..6" defensible?

This note examines the pace-based training load implemented in `app/coaching.py`
(`pace_zone_minutes`, `pace_load`, `activity_load`) against the constants
`PACE_ZONES` and `PACE_ZONE_WEIGHTS` in `app/config.py`. Session-RPE is covered
in `02-session-rpe.md`, the CTL/ATL layer in `03-ctl-atl-tsb.md`, and ACWR in
`04-acwr.md`.

## 1. The model as implemented

Each step between consecutive GPS points is classified by its instantaneous
pace in seconds per kilometre, taken from raw ground speed (`compute_pace_zones`
uses `step["speed"]`, not grade-adjusted pace). The moving seconds of that step
are added to one of six absolute pace bands, and the activity load is:

```
PaceLoad = Σ_z  minutes_in_zone_z × weight_z
weights  = (1, 2, 3, 4, 5, 6)
```

A 60-minute run entirely in Z2 scores 120; entirely in Z4, 240; entirely in Z6,
360. The weights are positional: they rise by one per band, not in proportion to
speed, metabolic rate, or any measured physiological response.

Two implementation facts matter for everything below.

- The bands are **absolute** (`PACE_ZONES` defaults: 390/330/290/260/230 s/km).
  They are not anchored to the athlete's threshold pace. A 5:00/km run is a hard
  tempo for one runner and an easy run for another, but it scores the same load
  for both, and it scores the same load for the same runner after six months of
  training even though it now costs less.
- The classifier uses **raw pace**, not GAP, even though the app computes GAP
  elsewhere. A hilly easy run is therefore scored as if it were flat.

## 2. What the named models actually are

The docstring calls this a "Banister-TRIMP analog on pace". That is not accurate,
and the distinction is not cosmetic.

| Model | Intensity input | Weighting | Anchoring |
| --- | --- | --- | --- |
| Banister TRIMP (Banister, 1991) | Heart-rate reserve fraction, `HRr = (HR − HRrest)/(HRmax − HRrest)` | Exponential: `t × HRr × 0.64 × e^(1.92·HRr)` for men, `0.86 × e^(1.67·HRr)` for women | HRmax and HRrest |
| Edwards TRIMP (Edwards, 1993) | Time in five %HRmax bands | Linear 1–5 | %HRmax |
| Lucía TRIMP (Lucía et al., 2003) | Time in three bands | Linear 1–3 | Ventilatory thresholds (VT1, RCP) |
| Coggan TSS (Allen & Coggan, 2010) | Normalised power / FTP | `IF² × hours × 100` | Functional threshold power |
| Running TSS (rTSS) | Normalised graded pace / threshold pace | `IF² × hours × 100` | Functional threshold pace |
| **This app** | **Time in six absolute pace bands** | **Linear 1–6 by band index** | **None (fixed s/km)** |

Banister's exponential term was designed to reflect the curvilinear rise in blood
lactate with fractional heart-rate reserve, rather than a linear one, and the
curve is fitted to that relationship (Banister, 1991; Morton et al., 1990; Foster
et al., 2001, describe the same non-linear multiplier). The app's linear,
index-based weighting is the **Edwards/Lucía summated-zone family**, applied to
pace. Foster et al. (2001) used exactly that Edwards method as the criterion for
their session-RPE work, and Haddad et al. (2017) note plainly that the Edwards
weighting "was not validated with a known physiological response".

So the honest description is: a summated pace-zone index with arbitrary ordinal
weights. That is a legitimate thing to compute. It is not TRIMP.

## 3. Is a linear weighting defensible on pace at all?

Partially yes, but not in the form used here.

The strongest argument for a pace-based load is that the metabolic cost of running
per unit distance is approximately constant and independent of speed: di Prampero
et al. (1986) measured 0.179 ± 0.017 mL O₂·kg⁻¹·m⁻¹ above rest across a wide range
of speeds. If cost per metre is constant, then cost per minute is proportional to
speed. A load linear in **speed** therefore has a physiological anchor.

The app is not linear in speed. It is linear in **band order**, with bands defined
on pace (the inverse of speed). Between the middle of Z2 and the middle of Z6,
speed rises by roughly 60–70 % while the weight triples. Within a band, pace can
change by 60 s/km with no change in load. The result is a step function that is
monotone in effort but not proportional to it, and whose steps are arbitrary.

For comparison, Banister's curve over the same range is not wildly different:
going from 0.60 to 0.80 HRR multiplies the per-minute weight by about 1.96, and
from 0.60 to 0.90 by about 2.67 (computed from the formula above). The app's Z2→Z4
step is 2.0× and Z2→Z5 is 2.5×. The **shape** is therefore not absurd. What is
unjustified is (a) the anchoring of the bands, (b) the claim of equivalence to
TRIMP, and (c) the treatment of the output as a ratio-scale quantity.

## 4. What the literature says about estimating load from pace rather than HR

Pace and speed are **external** load; heart rate and RPE are **internal** load
(Bourdon et al., 2017). The consensus statement is explicit that the two should be
used together, because the same external session can produce very different
internal responses depending on fatigue, heat, illness, and fitness. A pace-only
model cannot see any of that. It also cannot see cardiac drift, so it will
under-count a hot or fatigued run that is run at the same pace.

The best direct evidence for a pace-derived load in runners is rTSS, not a linear
zone sum. Wallace et al. (2014, *Eur J Appl Physiol*) had seven trained runners
complete 15 weeks of training and compared session-RPE, Banister TRIMP, and rTSS
as inputs to a fitness-fatigue model. All three were judged "appropriate" for
quantifying endurance training dose; correlations between modelled and actual
1,500 m performance were r = 0.70 (rTSS), 0.60 (session-RPE), and 0.65 (TRIMP).
That is a small sample, but it is the closest published test of the question, and
it supports **rTSS** — normalised graded pace relative to an individual threshold,
with a squared intensity term — not an absolute six-band linear index.

The counterweight is reliability. In a separate study, Wallace et al. (2014,
*J Strength Cond Res*) found poor test-retest reliability for the load metrics
themselves: coefficient of variation 15.6% for Banister TRIMP, 10.7% for Lucía
TRIMP, and 28.1% for session-RPE, against 3.9% for heart rate. Any of these
metrics is noisy at the session level; the pace-zone index is not exempt.

Sanders (2018), in a published letter, makes the specific criticism that
applies here: Edwards-style linear weights "increase linearly and are arbitrary",
the zone widths are arbitrary, and the resulting claim that five minutes in the
top zone equals five times the stress of five minutes in the bottom zone is
"not supported by evidence of a particular physiological phenomenon".

## 5. What the app gets right

- Using moving time and per-step classification rather than session average pace
  preserves within-run variability, which is the right instinct: a session with
  surges is not the same as a steady one at the same average pace.
- Returning a `source` field (`pace` or `rpe`) is good practice and is required by
  ADR-0006.
- Keeping the load unit as "minutes × dimensionless weight" means CTL/ATL and
  ACWR remain dimensionally consistent whatever the source.

## 6. Where it fails

1. **No individual anchor.** Because zones are absolute, the same physical run
   changes nothing when fitness changes. A training-load metric that does not
   respond to the athlete's improving capacity is measuring the route, not the
   stress.
2. **No terrain correction.** Raw pace misclassifies hilly runs. The app already
   has `GAP_UPHILL_FACTOR`, `GAP_DOWNHILL_FACTOR`, and `GAP_MAX_DOWN_GRADE`; the
   zone classifier simply does not use them.
3. **Arbitrary step weights.** Six equal-index steps are not derived from any
   dose-response curve and are not documented as ordinal.
4. **Wrong attribution.** Calling it a Banister analog will mislead the next
   person who reads the code, and violates the project rule that formula-bearing
   functions name the model and source correctly.
5. **Scale drift against session-RPE.** A 60-minute easy run scores about 120 on
   pace but 180–240 if the athlete logs RPE 3–4. The two sources are not on the
   same scale (see `02-session-rpe.md`), so mixing them moves CTL for measurement
   reasons.
6. **False precision.** CTL is rounded to one decimal and displayed as "fitness".
   The underlying quantity has no calibrated unit.

## 7. What would make it defensible

1. **Anchor the zones to the athlete.** Express band boundaries as percentages of
   threshold pace (the rTSS convention) or of critical speed, not fixed s/km.
   Without this, nothing else matters much.
2. **Classify on GAP.** `compute_pace_zones` should take the grade-adjusted speed
   already computed in `analysis.py`.
3. **Replace index weights with a stated function.** Either weight by speed
   relative to threshold (approximately linear in metabolic cost), or keep the
   1–6 scale but document it explicitly as ordinal (Edwards-type), not
   physiological.
4. **Normalise the unit.** Scale the output so that 60 minutes at threshold pace
   equals 100 units, matching the rTSS/TSS convention. Then `FORM_NEUTRAL_BAND`
   and any published CTL/TSB guidance become interpretable.
5. **Calibrate against session-RPE.** `activity_load` already returns both
   `load` and `pace_load` for RPE-tagged activities. The median ratio over
   activities with both would give an empirical conversion factor, turning the
   current scale mismatch into a measured correction.
6. **Label it honestly.** "Pace-zone load (ordinal)" rather than "TRIMP analog".

## References

- Allen H, Coggan AR. *Training and Racing with a Power Meter.* 2nd ed. Boulder,
  CO: VeloPress; 2010. (3rd ed., 2019.)
- Banister EW. Modeling elite athletic performance. In: Green HJ, McDougall JD,
  Wenger HA, eds. *Physiological Testing of the High-Performance Athlete.*
  Champaign, IL: Human Kinetics; 1991.
- Bourdon PC, Cardinale M, Murray A, Gastin P, Kellmann M, Varley MC, Gabbett TJ,
  Coutts AJ, Burgess DJ, Gregson W, Cable NT. Monitoring athlete training loads:
  consensus statement. *Int J Sports Physiol Perform.* 2017;12(Suppl 2):S2-161–
  S2-170. doi:10.1123/ijspp.2017-0208
- di Prampero PE, Atchou G, Brückner JC, Moia C. The energetics of endurance
  running. *Eur J Appl Physiol Occup Physiol.* 1986;55(3):259–266.
  doi:10.1007/BF02343797
- Edwards S. *The Heart Rate Monitor Book.* Port Washington, NY: Polar Electro Oy;
  1993.
- Foster C, Florhaug JA, Franklin J, Gottschall L, Hrovatin LA, Parker S,
  Doleshal P, Dodge C. A new approach to monitoring exercise training.
  *J Strength Cond Res.* 2001;15(1):109–115.
  doi:10.1519/00124278-200102000-00019
- Haddad M, Stylianides G, Djaoui L, Dellal A, Chamari K. Session-RPE method for
  training load monitoring: validity, ecological usefulness, and influencing
  factors. *Front Neurosci.* 2017;11:612. doi:10.3389/fnins.2017.00612
- Impellizzeri FM, Rampinini E, Coutts AJ, Sassi A, Marcora SM. Use of RPE-based
  training load in soccer. *Med Sci Sports Exerc.* 2004;36(6):1042–1047.
  doi:10.1249/01.MSS.0000128199.23901.2F
- Lucía A, Hoyos J, Santalla A, Earnest C, Chicharro JL. Tour de France versus
  Vuelta a España: which is harder? *Med Sci Sports Exerc.* 2003;35(5):872–878.
  doi:10.1249/01.MSS.0000064999.82036.B4
- Morton RH, Fitz-Clarke JR, Banister EW. Modeling human performance in running.
  *J Appl Physiol.* 1990;69(3):1171–1177. doi:10.1152/jappl.1990.69.3.1171
- Sanders D. Quantification of training load in endurance sports: additional
  considerations [letter]. *Strength Cond J.* 2018;40(2):115–116.
  doi:10.1519/SSC.0000000000000355
- Wallace LK, Slattery KM, Coutts AJ. A comparison of methods for quantifying
  training load: relationships between modelled and actual training responses.
  *Eur J Appl Physiol.* 2014;114(1):11–20. doi:10.1007/s00421-013-2745-1
- Wallace LK, Slattery KM, Impellizzeri FM, Coutts AJ. Establishing the criterion
  validity and reliability of common methods for quantifying training load.
  *J Strength Cond Res.* 2014;28(8):2330–2337.
  doi:10.1519/JSC.0000000000000416

### Access notes

The Banister (1991) chapter and the Allen & Coggan book are not open access; I
could not read them in full. The Banister formula and its sex-specific constants
are taken from the primary journal literature that reports and applies them
(Morton et al., 1990; Lucía et al., 2003) and from the abstract of Banister's
work. The Edwards (1993) book is also unavailable; the method is cited from
Foster et al. (2001), who reproduce it in full, and from Haddad et al. (2017).
Wallace et al. (2014, *Eur J Appl Physiol*) was read as an abstract (paywalled
full text); the correlation coefficients quoted are from that abstract. di
Prampero et al. (1986) was read as an abstract plus published summary; the
0.179 mL O₂·kg⁻¹·m⁻¹ figure is from that abstract. Bourdon et al. (2017) was read
in the relevant "Defining Training Load" section, not cover to cover. rTSS is
attributed by TrainingPeaks/WKO documentation to Stephen McGregor (December 2008);
I did not find a peer-reviewed primary description of rTSS itself, so it is cited
here as the industry implementation of the TSS formula on pace, not as a
peer-reviewed method paper.

## Verdict for this app

**Acceptable as a proxy, not preferable to session-RPE, and currently presented
with more precision than it has.**

The arithmetic is transparent and monotone, and the shape of the 1–6 weighting is
not far from Banister's exponential curve over the middle of the range. Used as a
within-athlete trend line, on consistent terrain, it will usually move in the
right direction. That is the limit of the claim that can be defended.

It is **not** a Banister-TRIMP analog, it is **not** comparable across athletes,
and it does **not** track changes in fitness, because `PACE_ZONES` are absolute.
It is also an external measure, so it cannot capture heat, illness, fatigue, or
cardiac drift; where an RPE exists, session-RPE has better direct validity
(Foster et al., 2001; Impellizzeri et al., 2004) and should win, as the code
already does.

Concrete changes, in priority order:

1. Replace the absolute `PACE_ZONES` defaults with bands derived from the
   athlete's threshold pace (or critical speed). Keep the s/km constants only as
   a fallback when no threshold is known.
2. Make `compute_pace_zones` classify on GAP, reusing the existing
   `GAP_UPHILL_FACTOR` / `GAP_DOWNHILL_FACTOR` / `GAP_MAX_DOWN_GRADE` machinery.
3. Keep `PACE_ZONE_WEIGHTS` but rescale them so that 60 minutes at threshold pace
   scores 100 (set the threshold band's weight to 100/60 ≈ 1.67 and scale the rest
   proportionally), and document them in `config.py` as **ordinal** Edwards-type
   weights rather than a TRIMP curve.
4. Rewrite the `pace_load` docstring to say "summated pace-zone index (Edwards/
   Lucía family), not Banister TRIMP".
5. Rename the user-facing "fitness" derived from this number (see
   `03-ctl-atl-tsb.md`) and stop displaying one decimal place.
6. Add a calibration step using the `pace_load` and RPE values already returned
   together by `activity_load`, so the two sources share one scale.

Until at least items 1–3 are done, the honest description of the current metric
is "a load-shaped number", and it should not be used to justify a training
decision on its own.
