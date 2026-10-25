# ACWR: the 7:28 ratio, the "sweet spot", and why the evidence is weaker than the chart suggests

This note covers `acwr_series`, `_acwr_band`, and `_rolling_avg` in
`app/coaching.py`, and `ACWR_ACUTE_DAYS`, `ACWR_CHRONIC_DAYS`, and `ACWR_BANDS`
in `app/config.py`.

## 1. The model as implemented

```
acute   = mean daily load over the last 7 days
chronic = mean daily load over the last 28 days   (includes the last 7)
ACWR    = acute / chronic
```

with four bands: `< 0.8` undertraining, `0.8–1.3` sweet spot, `1.3–1.5` caution,
`>= 1.5` high risk. The chronic window contains the acute window. This is the
**coupled** rolling-average formulation.

## 2. Where the 7:28 ratio comes from

The first study to use it was Hulin et al. (2014) on 28 elite cricket fast
bowlers. Workload was estimated both externally (balls bowled per week) and
internally (session-RPE × duration). One week was the acute window and a four-week
rolling average was the chronic window. A negative training-stress balance was
associated with injury in the following week (RR 2.2 for internal load, 2.1 for
external), and a ratio above 200 % carried RR 4.5 and 3.3 respectively.

The authors were explicit about the choice of windows:

> "the most appropriate and valid method of developing a training-stress balance is
> still unknown. Given that periodisation models have traditionally used 1-week
> microcycles and 4-week mesocycles, it could be argued that this arbitrary method
> is the most convenient way..."
> — Hulin et al. (2014)

That is the origin: a convenient 1-week/4-week split, borrowed from periodisation
convention, not derived from tissue healing, adaptation kinetics, or dose-response
estimation.

Gabbett (2016) generalised the finding into the "training-injury prevention
paradox". The paper describes acute load as fatigue and chronic load as fitness,
calls ACWR "a best practice predictor of training-related injuries", and states:

> "acute:chronic workload ratios within the range of 0.8–1.3 could be considered
> the training 'sweet spot', while acute:chronic workload ratios ≥1.5 represent
> the 'danger zone'."

Crucially, the same paragraph adds:

> "It is possible that different sports will have different training load–injury
> relationships; until more data is available, applying these recommendations to
> individual sport athletes should be performed with caution."

Runners are individual-sport athletes. The model's author warned about exactly
this application.

The 1.3–1.5 "caution" band in the app sits between the published "sweet spot"
upper bound (1.3) and the published "danger zone" threshold (1.5). Gabbett (2016)
does not attach a risk estimate to that interval.

## 3. What the evidence base looks like

The ACWR literature is dominated by elite team sports: Australian football,
rugby league, soccer, cricket, Gaelic football. It is observational, it uses
time-loss injury as the outcome, and the samples are small. Three systematic
reviews summarise it:

- Griffin et al. (2020): 22 studies, median Newcastle–Ottawa score 8. Supports an
  association with non-contact injury and favours EWMA over rolling averages,
  while noting that the best windows and load variables may be sport-specific.
- Maupin et al. (2020): 27 studies, "high variability" in load variables, ratio
  categories, and reference groups. Reports a trend toward 0.80–1.30 having the
  lowest risk, and states that "there may be issues with the ACWR method that
  must be addressed before it is confidently used to mitigate injury risk."
- Büttner et al. (2020): a methodological review of the professional team-sport
  literature, focused on how inconsistently the ratio has been calculated and
  applied.

None of these is a validation in recreational runners, and none is a prospective
test of whether changing training in response to ACWR reduces injuries.

## 4. The methodological criticism

### 4.1 Mathematical coupling

The acute week is part of the chronic window. Lolli et al. (2019) simulated 1,000
athletes with four independent 7-day blocks of high-speed distance. The blocks
were uncorrelated with each other (all pairwise r < 0.06). Nevertheless, the
correlation between acute load and the *coupled* chronic load was r = 0.52
(95 % CI 0.47–0.56). Removing the acute week from the chronic calculation dropped
it to r = 0.01 (95 % CI −0.05 to 0.07). The same data gave an ACWR of 1.45 with
coupling and 1.71 without.

The correlated variables are not evidence of a biological relationship; they are
an artefact of the arithmetic. The classic statement of the problem is Pearson
(1897) on spurious correlation of indices, and the modern treatment is Kronmal
(1993).

### 4.2 The ratio is a rescaling of the numerator

Impellizzeri et al. (2020, *IJSPP*) set out the conceptual problems: no study has
estimated a causal effect, the ratio does not normalise the numerator by the
denominator even when uncoupled, the metric is ambiguous, and it is not
consistently or unidirectionally related to injury. Their conclusion is blunt:
"There is no evidence supporting the use of ACWR in training-load-management
systems or for training recommendations aimed at reducing injury risk."

Impellizzeri et al. (2021, *Sports Med*) then tested the denominator directly.
Using previously published data, they replaced the real chronic load with fixed
and randomly generated values:

| Denominator | Odds ratio for injury |
| --- | --- |
| Real ACWR | 2.45 (95 % CI 1.28–4.71) |
| Fixed chronic value (1,510) | 1.95 (1.18–3.52) |
| Random chronic values | mean 1.89 (range 1.42–2.70) |

Dividing acute load by *random numbers* reproduced the association. The ratio was
also causing artificial reclassification: injured players with the lowest acute
loads were moved into the highest ACWR categories. And the predictive value was
nil: c-statistic 0.574 for ACWR, 0.544 for acute load alone, 0.500 for an
intercept-only model, with identical Brier scores (0.0351) for ACWR and the null
model. Their recommendation: "ACWR should be dismissed as a framework and model."

### 4.3 The exchange with Gabbett

Gabbett and colleagues responded in three places.

- **Windt and Gabbett (2019)** accepted the coupling critique, set out how to
  convert between coupled and uncoupled ratios, and argued that neither method
  had enough evidence to be declared superior. They urged a critical approach to
  load management "wherein ACWRs may play a part".
- **Gabbett et al. (2019)** used real data from 28 cricket fast bowlers. Coupled
  and uncoupled ACWR were related with R² = 0.99, and there was no significant
  difference in injury likelihood between the two methods. They concluded: "We
  found no evidence to support the discontinuation of coupled ACWRs in a
  real-world practical setting."
- **Coyne et al. (2019)** independently reported trivial-to-small effect sizes
  between coupled and uncoupled variants in basketball and weightlifting data,
  and argued that coupling is unlikely to be producing the observed associations.

The exchange is worth reading carefully, because the two sides are not measuring
the same thing.

Gabbett's defence is about **coupling**, the narrowest of the three criticisms. It
shows that the choice of denominator transform does not change the practical
answer much. But that result is also exactly what Impellizzeri's critique
predicts: if coupled and uncoupled ACWR are almost perfectly correlated, and
random denominators reproduce the same odds ratios, then the chronic term is not
doing independent work. The ratio is a monotone rescaling of acute load. Gabbett
reads that as "the choice does not matter"; Impellizzeri reads it as "the
denominator is not doing what the theory says it does". Both readings fit the
data, and the second one undermines the *theory* without necessarily undermining
the *practical heuristic* of "don't spike your load".

What Gabbett's response does **not** address is:

1. the absence of any causal estimate;
2. the absence of predictive value at the individual level (c-statistic ≈ 0.57);
3. the artificial reclassification of low-load athletes into high-risk bands.

Those are the claims that matter if the app puts a risk label on a runner.

## 5. The running-specific evidence points the other way

This is the part that matters most for this app, and it is rarely mentioned in
ACWR summaries.

- **Nielsen et al. (2014)** followed 874 novice runners for a year. There were no
  statistically significant differences in injury rates across progression groups
  overall. Runners increasing weekly distance by more than 30 % had a higher rate
  of distance-related injuries than those increasing by less than 10 % (HR 1.59,
  95 % CI 0.96–2.66, p = 0.07). There was no dose-response: 10–30 % was
  indistinguishable from < 10 %. The authors describe the study as exploratory.
- **Damsted et al. (2018)** systematically reviewed changes in training load and
  running-related injury. Four studies met the criteria; three found some
  association. Their conclusion: "Very limited evidence exists supporting that a
  sudden change in training load is associated with increased risk of
  running-related injury."
- **Nakaoka et al. (2021)** analysed 435 recreational runners, calculating ACWR
  with chronic windows from 4 to 12 weeks and three methods (coupled, uncoupled,
  EWMA). The association was **inverse**: runners with ACWR below 0.70 had about a
  10 % predicted probability of injury, while those above 1.38 had about 1 %.
  Higher ACWR meant *lower* risk.
- **Dijkhuis et al. (2020)** followed 23 competitive runners for 24 months and
  found that *small* fortnightly increases in ACWR (0.10–0.78) were associated
  with increased injury risk (p < 0.001), which is the opposite of the "spike"
  story.

Both ACWR-specific running cohorts fail to reproduce the team-sport direction.
Nakaoka et al. (2021) find that higher ACWR goes with *lower* risk; Dijkhuis et
al. (2020) find that *small* increases, not spikes, accompany injury. A plausible
explanation is reverse causation: an incipient injury causes a runner to reduce
load before reporting it, so low acute load marks the pre-injury period. That
explanation is also available for the team-sport data, which is one reason the
causal critique matters.

## 6. What the current consensus supports

There is no consensus that ACWR predicts injury in an individual athlete.

There is broad agreement that:

- large, rapid increases in training load are *plausibly* relevant to injury;
- the ACWR as a ratio has serious statistical problems (coupling, rescaling,
  discretisation, sparse data, confounding) and should not be treated as a causal
  variable;
- if load monitoring is used at all, it belongs inside a multimodal system with
  wellness, previous injury, and sport-specific exposure, not as a stand-alone
  number.

The 2016 International Olympic Committee consensus statement on load and injury
(Soligard et al., 2016) is widely cited as endorsing ACWR as part of load
monitoring. It predates the methodological critique above. I did not read its
full text, so I am not quoting its exact recommendation; what can be said is that
no subsequent primary methodological paper I found supports ACWR thresholds as
risk criteria.

## 7. Specific problems in this implementation

1. **It is coupled.** `_rolling_avg(window, ACWR_CHRONIC_DAYS)` averages the last
   28 days including the last 7. That is the formulation Lolli et al. (2019)
   criticised. The uncoupled version is a one-line change and removes the
   spurious correlation, even if Gabbett argues the practical difference is
   small.
2. **The band names overclaim.** `high_risk` and `sweet_spot` are risk claims. The
   project glossary already says ACWR is "not an injury score" and lists "injury
   score" and "risk index" under *Avoid*. The code contradicts the glossary.
3. **Source switching produces fake spikes.** The daily load can switch from pace
   to RPE between days. Because the two sources differ by roughly a factor of two
   (`02-session-rpe.md`), a user who starts logging RPE will double acute load
   while the 28-day chronic average lags, and ACWR can jump from ~1.0 to ~1.6
   without any change in training. The app would then display "high risk".
4. **Gaps are treated as rest.** `full_load_series` zero-fills every day. After a
   two-week break, a return to normal load gives, for example, acute 600 and
   chronic (600 + 0 + 0 + 600) / 4 = 300, so ACWR = 2.0 and the band reads
   "high risk". This is the classic post-layoff spike, and it is arguably the one
   case where the signal is meaningful, but the chronic average at that moment is
   the least reliable it will ever be.
5. **A normal scheduling wobble flips the band.** Three runs of 200 units per week
   is 600. If one run slips just outside the 7-day window, acute is 400 and ACWR
   is 0.67, which reads "undertraining". No training change occurred.
6. **The window is short relative to running periodisation.** A 7-day numerator
   over a 28-day denominator is volatile for runners who do one long run per week.
   An exponentially weighted version is more sensitive in team-sport data (Murray
   et al., 2017), but it introduces its own initial-load problem and has produced
   sparse, non-significant results in runners (Nakaoka et al., 2021). It is not an
   obvious upgrade here.

## References

- Büttner F, Winters M, Delahunt E, et al. Is the acute:chronic workload ratio
  (ACWR) associated with risk of time-loss injury in professional team sports? A
  systematic review of methodology, variables and injury risk in practical
  situations. *Sports Med.* 2020. doi:10.1007/s40279-020-01308-6
- Coyne JOC, Nimphius S, Newton RU, Haff GG. Does mathematical coupling matter to
  the acute to chronic workload ratio? A case study from elite sport. *Int J
  Sports Physiol Perform.* 2019;14(10):1447–1454. doi:10.1123/ijspp.2018-0874
- Damsted C, Glad S, Nielsen RO, Sørensen H, Malisoux L. Is there evidence for an
  association between changes in training load and running-related injuries? A
  systematic review. *Int J Sports Phys Ther.* 2018;13(6):931–942.
  doi:10.26603/ijspt20180931
- Dijkhuis TB, Otter R, Aiello M, Velthuijsen H, Lemmink K. Increase in the
  acute:chronic workload ratio relates to injury risk in competitive runners.
  *Int J Sports Med.* 2020;41(11):736–743. doi:10.1055/a-1171-2331
- Gabbett TJ. The training-injury prevention paradox: should athletes be training
  smarter and harder? *Br J Sports Med.* 2016;50(5):273–280.
  doi:10.1136/bjsports-2015-095788
- Gabbett TJ, Hulin B, Blanch P, Chapman P, Bailey D. To couple or not to couple?
  For acute:chronic workload ratios and injury risk, does it really matter? *Int J
  Sports Med.* 2019;40(9):597–600. doi:10.1055/a-0955-5589
- Griffin A, Kenny IC, Comyns TM, Lyons M. The association between the
  acute:chronic workload ratio and injury and its application in team sports: a
  systematic review. *Sports Med.* 2020;50(3):561–580.
  doi:10.1007/s40279-019-01218-2
- Hulin BT, Gabbett TJ, Blanch P, Chapman PC, Bailey D, Orchard JW. Spikes in
  acute workload are associated with increased injury risk in elite cricket fast
  bowlers. *Br J Sports Med.* 2014;48(8):708–712.
  doi:10.1136/bjsports-2013-092524
- Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:chronic workload
  ratio: conceptual issues and fundamental pitfalls. *Int J Sports Physiol
  Perform.* 2020;15(6):907–913. doi:10.1123/ijspp.2019-0864
- Impellizzeri FM, Woodcock S, Coutts AJ, Fanchini M, McCall A, Vigotsky AD. What
  role do chronic workloads play in the acute to chronic workload ratio? Time to
  dismiss ACWR and its underlying theory. *Sports Med.* 2021;51(4):581–592.
  doi:10.1007/s40279-020-01378-6
- Kronmal RA. Spurious correlation and the fallacy of the ratio standard revisited.
  *J R Stat Soc Ser A.* 1993;156(3):379–392. doi:10.2307/2983064
- Lolli L, Batterham AM, Hawkins R, Kelly DM, Strudwick AJ, Thorpe RT, Gregson W,
  Atkinson G. Mathematical coupling causes spurious correlation within the
  conventional acute-to-chronic workload ratio calculations. *Br J Sports Med.*
  2019;53(15):921–922. doi:10.1136/bjsports-2017-098110
- Maupin D, Schram B, Canetti E, Orr R. The relationship between acute:chronic
  workload ratios and injury risk in sports: a systematic review. *Open Access J
  Sports Med.* 2020;11:51–75.
- Murray NB, Gabbett TJ, Townshend AD, Blanch P. Calculating acute:chronic
  workload ratios using exponentially weighted moving averages provides a more
  sensitive indicator of injury likelihood than rolling averages. *Br J Sports
  Med.* 2017;51(9):749–754. doi:10.1136/bjsports-2016-097152
- Nakaoka G, Barboza SD, Verhagen E, van Mechelen W, Hespanhol L. The association
  between the acute:chronic workload ratio and running-related injuries in Dutch
  runners: a prospective cohort study. *Sports Med.* 2021;51(11):2437–2447.
  doi:10.1007/s40279-021-01483-0
- Nielsen RO, Parner ET, Nohr EA, Sørensen H, Lind M, Rasmussen S. Excessive
  progression in weekly running distance and risk of running-related injuries: an
  association which varies according to type of injury. *J Orthop Sports Phys
  Ther.* 2014;44(10):739–747. doi:10.2519/jospt.2014.5164
- Pearson K. Mathematical contributions to the theory of evolution—on a form of
  spurious correlation which may arise when indices are used in the measurement of
  organs. *Proc R Soc Lond.* 1897;60:489–498. doi:10.1098/rspl.1896.0076
- Soligard T, Schwellnus M, Alonso JM, et al. How much is too much? (Part 1)
  International Olympic Committee consensus statement on load in sport and risk of
  injury. *Br J Sports Med.* 2016;50(17):1030–1041.
  doi:10.1136/bjsports-2016-096581
- Wang C, Vargas JT, Stokes T, Steele R, Shrier I. Analyzing activity and injury:
  lessons learned from the acute:chronic workload ratio. *Sports Med.*
  2020;50(7):1243–1254. doi:10.1007/s40279-020-01280-1
- Windt J, Gabbett TJ. Is it all for naught? What does mathematical coupling mean
  for acute:chronic workload ratios? *Br J Sports Med.* 2019;53(16):988–990.
  doi:10.1136/bjsports-2017-098925

### Access notes

Gabbett (2016) and Hulin et al. (2014) were read in full (open access). Lolli et
al. (2019) was read in full via the accepted manuscript. Impellizzeri et al.
(2020) was read as an abstract (paywalled); Impellizzeri et al. (2021) was read in
full via an institutional repository copy. Nakaoka et al. (2021) and Nielsen et
al. (2014) were read as abstracts plus the publisher's available full text.
Dijkhuis et al. (2020) was read as an abstract. Damsted et al. (2018) was read as
an abstract/full text (open access). Pearson (1897) and Kronmal (1993) were not
read directly; they are cited as the standard references for spurious correlation
of ratios, as used by Lolli et al. (2019) and Impellizzeri et al. (2021). Maupin
et al. (2020) was read in full (open access). The Büttner et al. (2020) abstract
was read; the full text is paywalled.

## Verdict for this app

**Not defensible as a risk indicator. Defensible, with changes, as a descriptive
load-change number.**

The implementation is the coupled rolling average, which is the exact
formulation the methodological literature criticises. It then attaches risk
labels (`sweet_spot`, `high_risk`) that the source author explicitly cautioned
against applying to individual-sport athletes, and that the project's own
glossary says ACWR is not. The running-specific evidence is weak, and neither of
the two running cohorts reproduces the team-sport direction. No study has shown
that acting on ACWR reduces injuries in runners.

Concrete changes, in priority order:

1. **Remove the risk vocabulary.** Rename `ACWR_BANDS` to descriptive load-change
   states, for example `load_falling` (< 0.8), `stable` (0.8–1.3), `load_rising`
   (1.3–1.5), `load_rising_sharply` (≥ 1.5). Delete `high_risk` and `sweet_spot`.
   This resolves the contradiction with `GLOSSARY.md` and is the single change
   that most reduces harm.
2. **Uncouple the denominator.** Compute the chronic mean over days 8–35 (the four
   weeks *before* the acute week), behind a constant such as
   `ACWR_COUPLED = False`. This removes the spurious correlation at negligible
   cost and makes the number interpretable.
3. **Show the absolute loads.** Display `acute` and `chronic` alongside the ratio,
   and never the ratio alone. A ratio of 1.2 from 200/167 and a ratio of 1.2 from
   1,200/1,000 are different situations.
4. **Handle gaps explicitly.** Add a maximum-gap constant and suppress the ratio
   (or show "insufficient recent data") when the athlete has not trained for more
   than, say, 10 days. Do not let a layoff masquerade as a spike.
5. **Stabilise the load source.** Either freeze the source used for the ACWR
   series per athlete, or calibrate pace load to RPE load (`02-session-rpe.md`)
   before mixing them. A measurement change must not be able to trigger a band
   change.
6. **Do not use it to predict injury, and say so in the UI.** If the product needs
   an injury-risk feature, the evidence does not support one built on ACWR. The
   honest alternative is a plain week-over-week load change, which is what the
   running literature actually studied (Nielsen et al., 2014) and even that is
   described as "very limited evidence".

If items 1–5 are done, what remains is a useful, honestly labelled description of
how this week compares with the last month. That is worth having. It is not a
risk score, and the code should stop calling it one.
