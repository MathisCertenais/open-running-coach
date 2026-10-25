# 05 — Intensity distribution: what "80/20" actually measures

Status: research note. Not a spec, not an ADR.
Applies to: `app/config.py` (`PACE_ZONES`, `INTENSITY_GROUPS`, `INTENSITY_TARGET`,
`PLAN_EASY_FRACTION`, `PLAN_HARD_FRACTION`, `WORKOUT_PACES`),
`app/coaching.py` (`intensity_distribution`, `_build_week`).
Last reviewed: 2026-10-25.

## The question

Three questions are tangled together in the "80/20" label:

1. **Denominator** — is 80% of *sessions*, *time*, or *distance*?
2. **Numerator** — the remaining 20% is high intensity, threshold, or both?
3. **Shape** — is the ideal polarized (little threshold work) or pyramidal
   (a decreasing staircase: most easy, some moderate, little hard)?

The app currently answers (1) with time and distance, (2) with a 10/10 split,
and calls the result "polarized". Two of those three choices need qualification.

## What the app does

- `PACE_ZONES` defines six pace bands in s/km (Z1 recovery to Z6 sprint).
- `INTENSITY_GROUPS` collapses them to Easy (Z1–Z2), Moderate (Z3), Hard
  (Z4–Z6).
- `INTENSITY_TARGET = {"easy": 0.80, "moderate": 0.10, "hard": 0.10}`.
- `intensity_distribution()` sums `time_s` and `distance_m` per group over a
  7-day and a 28-day window and returns percentages of each. It never counts
  sessions.
- `_build_week()` splits weekly volume with `PLAN_EASY_FRACTION = 0.80` and
  `PLAN_HARD_FRACTION = 0.20`, then divides the hard block into a "tempo" and
  an "intervals" session. `WORKOUT_PACES["tempo"]` is 275 s/km, which falls in
  Z4 (260–290 s/km) under the default `PACE_ZONES`, i.e. **hard**, not
  moderate.

The config comment states the intent: "Polarized ideal (80/20): ~80% easy; the
remaining ~20% should favour hard work over the 'grey zone' moderate, so we
target 80/10/10."

## What the primary literature says

### 1. Seiler's 80/20 is a session ratio

Seiler's review is explicit about the unit:

> "Numerous descriptive studies ... seem to converge on a typical intensity
> distribution in which about 80% of training sessions are performed at low
> intensity (2 mM blood lactate), with about 20% dominated by periods of
> high-intensity work, such as interval training at approx. 90% VO2max."
> — Seiler (2010), *Int J Sports Physiol Perform* 5(3):276–291,
> doi:10.1123/ijspp.5.3.276, p. 276.

The conclusion repeats it: "an approximate 80-to-20 ratio of LIT to ThT/HIT
intensity training gives excellent long-term results" (p. 287), and later
"about 20% of training sessions" (p. 286).

Seiler also argues *why* sessions are the right unit. Heart-rate time-in-zone
"tends to underestimate the time spent working at high intensity (due to heart
rate lag time during intervals)" and "does not seem to correspond well with
perceived effort" (p. 279). Allocating each session to the intensity of its
primary block — the "session goal approach" — "yields better matching between
heart rate analysis and athlete perception of session effort" (p. 279). His
summary: "the unit of stress perceived and responded to by the athlete is the
stress of entire training sessions or perhaps training days, not minutes in any
given heart rate zone."

That is a direct argument against treating a time-in-zone percentage as the
primary compliance metric. It does not make time-in-zone wrong; it makes it a
*different* quantity from the one the 80/20 rule was derived from.

### 2. Time and distance versions land near 80/20 too, but not exactly

The same review reports the descriptive studies in their own units:

| Study | Unit | Distribution |
| --- | --- | --- |
| Billat et al. (2001), elite marathoners, 12 wk pre-trials | % of **km** | 78% below marathon pace, 4% at marathon pace, 18% at 10 km/3 km pace (as reported by Seiler 2010, p. 279) |
| Esteve-Lanao et al. (2005), Spanish distance runners, 6 mo | % of **time** in HR zones | 71% < VT1, 21% VT1–VT2, 8% > VT2 (Seiler 2010, p. 280) |
| Esteve-Lanao et al. (2007), randomised Z1 vs Z2 groups | % of **time** in HR zones | Z1 group 81/12/8; Z2 group 67/25/8 (Seiler 2010, p. 284) |
| Seiler & Kjerland (2006), junior cross-country skiers, 32 d | session goal / time | ~75% below VT1, 5–10% between VT1 and VT2, 15–20% above VT2 (the 75/15–20 split is in the abstract; the 5–10% middle band is tabulated by Stöggl & Sperlich 2015, Table 1) |

So the three denominators give roughly the same *easy* share (~75–81%) but
different moderate/hard splits. The 2007 trial is the closest existing
measurement to the app's target: **81/12/8** by time is almost exactly
80/10/10. That is a real, cited precedent for the app's number.

The flip side: a 32-day session-goal study of skiers produced **75/5–10/15–20**,
i.e. more hard work and less moderate than the app targets. So 80/10/10 is one
point inside the observed range, not "the" polarized ideal.

### 3. Polarized versus pyramidal

The two shapes are distinct and both are observed:

- **Pyramidal**: most time easy, then progressively less threshold, then least
  high intensity. Stöggl & Sperlich's review found that "the majority of studies
  present a 'pyramidal' TID", with 84–95% of preparation-phase time in zone 1
  and only 2–9% in zone 3 (*Front Physiol* 2015;6:295,
  doi:10.3389/fphys.2015.00295).
- **Polarized**: a deliberately *hollowed-out* middle — high easy volume plus a
  meaningful hard block, with threshold work minimised. The review quantifies
  the canonical shape as "80:20%, or 75–80% with low intensity, 5% threshold
  intensity, and 15–20% as high intensity training" (ibid., Key Concept 5).

The one randomised controlled trial usually cited for polarization tested a much
more extreme distribution than 80/10/10. In Stöggl & Sperlich (2014,
*Front Physiol* 5:33, doi:10.3389/fphys.2014.00033), the polarized group trained
**68% low / 6% threshold / 26% high** by time over 9 weeks, against 83/16/1 for
high-volume, 46/54/0 for threshold, and 43/0/57 for HIIT. Polarized produced the
largest gains in VO2peak (+11.7%), time to exhaustion (+17.4%) and peak velocity
(+5.1%). The authors describe this as mimicking the retrospective elite pattern
of "~75% below or well above (~15–20%) the LT".

Two conclusions follow. First, "polarized" in the intervention literature means
roughly **70/5/25 by time**, not 80/10/10. Second, 80/10/10 is best described as
a *mildly polarized* or *pyramidal-leaning* target — closer to the runners in
Esteve-Lanao (2007) than to the canonical polarized model.

### 4. The "80/10/20" formulation is arithmetically impossible

80 + 10 + 20 = 110. Any three-way target must sum to 100. There are only two
coherent readings:

- **Two-way**: 80% easy / 20% not-easy (`easy` vs `moderate + hard` combined),
  which is what Seiler's session rule and `PLAN_EASY_FRACTION` /
  `PLAN_HARD_FRACTION` implement.
- **Three-way**: 80% easy, and the remaining 20 split between moderate and hard.
  The evidence puts moderate at roughly 5–12% and hard at 8–20% for runners, so
  **80/10/10** and **80/5/15** are both defensible; **80/10/10** matches the
  measured 81/12/8 of Esteve-Lanao et al. (2007).

What is *not* defensible is 80/10/20, and what is misleading is calling any
three-way split "the" polarized ideal when the tested polarized distribution is
closer to 70/5/25.

## Where the app departs from the evidence

1. **Denominator mismatch.** The evidence's headline rule is session-based; the
   app reports only time and distance. The app has the data to count sessions
   (each `Activity` has a type and a primary pace), so this is a reporting gap,
   not a data gap.
2. **Zone assignment uses raw pace.** `intensity_distribution()` buckets by
   `PACE_ZONES` on raw pace. On a hilly run an easy effort uphill crosses into
   Z3/Z4, so the app records "moderate" or "hard" time that was aerobically
   easy. This is the exact failure mode GAP exists to remove (see note 08).
3. **The plan and the target disagree.** `_build_week()` produces 80% easy and
   20% hard with essentially no Z3 time (its "tempo" pace is Z4), while
   `INTENSITY_TARGET` asks for 10% moderate. A user following the generated plan
   can never hit the displayed target.
4. **Precision is overstated.** A 10/10 split is presented as a target with no
   tolerance. Given day-to-day variation and pace-zone width, ±3 percentage
   points is noise; the UI treats any deviation as a finding.

## Verdict for this app

**Defensible, with corrections.**

- `INTENSITY_TARGET = 80/10/10` is defensible *as a time-in-zone target for
  runners*: it is close to the 81/12/8 measured in Esteve-Lanao et al. (2007),
  with hard work at the low end of the 15–20% reported by Seiler & Kjerland
  (2006). Keep the numbers.
- The **"80/10/20"** formulation is wrong and must not reappear. If a two-way
  number is needed, write **80/20** and say what the 20 contains.
- The comment in `app/config.py` should not call 80/10/10 "the polarized ideal".
  Call it what it is: *80/20 with a 10/10 moderate/hard split; a mildly polarized
  target consistent with time-in-zone data from sub-elite runners.* Cite
  Esteve-Lanao et al. (2007) and Seiler (2010) by name, as
  `CODING_STANDARDS.md` requires for formula-bearing code.
- **Add a session-based distribution** and make it the headline. Seiler's rule is
  about sessions, and the session-goal method is the one that tracks perceived
  effort. Concretely: classify each activity by its dominant group (majority of
  moving time, or its workout type), report "easy sessions / total sessions" next
  to the time percentages, and label the two metrics differently in the UI.
- **Compute the zone buckets on GAP, not raw pace.** `_zone_group_totals()` calls
  `compute_pace_zones()` on raw step speeds; that call should use GAP-adjusted
  step paces (note 08). Until then, hilly athletes get a systematically
  harder-looking distribution.
- **Make the plan honour the target.** Either set
  `INTENSITY_TARGET = {"easy": 0.80, "moderate": 0.00, "hard": 0.20}` to match
  what `_build_week()` actually schedules, or move `WORKOUT_PACES["tempo"]` into
  Z3 (roughly 300–320 s/km with the default zones) and give the plan a real
  moderate block. The two must not disagree.
- **Name the tolerance.** A band of ±3 points is honest; a single number is not.

## What would change this verdict

- A prospective trial in recreational runners showing that session-count 80/20
  and time-in-zone 80/10/10 predict performance differently.
- Evidence that 400 m–5 km pace bands misclassify easy running badly enough that
  the zone model needs a heart-rate or RPE input. The app has neither
  (`GLOSSARY.md`: single-user, GPS-only by default), so pace remains the only
  available signal — which is an argument for GAP-corrected pace, not against
  the target.

## Sources

Read in full:

- Seiler S. What is best practice for training intensity and duration
  distribution in endurance athletes? *Int J Sports Physiol Perform.*
  2010;5(3):276–291. doi:10.1123/ijspp.5.3.276. (Full text consulted.)
- Stöggl T, Sperlich B. Polarized training has greater impact on key endurance
  variables than threshold, high intensity, or high volume training.
  *Front Physiol.* 2014;5:33. doi:10.3389/fphys.2014.00033. (Open access.)
- Stöggl T, Sperlich B. The training intensity distribution among well-trained
  and elite endurance athletes. *Front Physiol.* 2015;6:295.
  doi:10.3389/fphys.2015.00295. (Open access.)

Abstract only (paywalled full text):

- Seiler KS, Kjerland GØ. Quantifying training intensity distribution in elite
  endurance athletes: is there evidence for an "optimal" distribution?
  *Scand J Med Sci Sports.* 2006;16(1):49–56.
  doi:10.1111/j.1600-0838.2004.00418.x.
- Esteve-Lanao J, San Juan AF, Earnest CP, Foster C, Lucía A. How do endurance
  runners actually train? Relationship with competition performance.
  *Med Sci Sports Exerc.* 2005;37(3):496–504.
  doi:10.1249/01.MSS.0000155393.78744.86.
- Esteve-Lanao J, Foster C, Seiler S, Lucía A. Impact of training intensity
  distribution on performance in endurance athletes. *J Strength Cond Res.*
  2007;21(3):943–949. doi:10.1519/R-19725.1.
- Billat VL, Demarle A, Slawinski J, Paiva M, Koralsztein JP. Physical and
  training characteristics of top-class marathon runners. *Med Sci Sports
  Exerc.* 2001;33(12):2089–2097. doi:10.1097/00005768-200112000-00018.

Numbers from these four papers are quoted as reported by Seiler (2010) and
Stöggl & Sperlich (2015); I did not read their full texts, and this note says so
where it matters.
