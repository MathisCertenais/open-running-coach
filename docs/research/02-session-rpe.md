# Session-RPE: Foster's method, the scale, and what it is worth

This note covers the session-RPE load in `app/coaching.py` (`activity_load`,
`daily_load_map`) and the RPE input contract exposed by `app/main.py`. It does
not re-argue the pace model (`01-pace-zone-load.md`); it treats session-RPE as
the reference method the pace model is implicitly competing with.

## 1. The original study

Foster et al. (2001) ran a two-part study:

- **Part 1:** 12 well-trained recreational cyclists (6 men, 6 women) performed
  steady-state and interval cycle bouts at controlled power outputs.
- **Part 2:** 14 collegiate men's basketball players were monitored through
  practice and competition.

Each bout was quantified twice. The session-RPE method asked the athlete, about
30 minutes after the session, "How was your workout?", and multiplied the single
global rating by the session duration in minutes. The criterion was a summated
heart-rate-zone method: five zones at 50–60, 60–70, 70–80, 80–90, and 90–100 % of
peak heart rate, with multipliers of 1, 2, 3, 4, and 5, summed over the session
(the Edwards method; Edwards, 1993).

The reported result is important in both directions. The relationship between
session-RPE load and the HR-zone load was "highly consistent", and the regression
lines from the cycling and basketball samples were "nearly overlapping", which the
authors read as evidence of mode independence. But the **absolute** session-RPE
score was significantly greater than the HR-zone score in both parts. Session-RPE
is therefore validated as a *relative* index that tracks another index, not as an
absolute quantity that can be compared across methods.

## 2. The scale Foster actually used

Foster used a **modified Borg CR-10 category-ratio scale**, not a 1–10 Likert
scale. The anchors are:

| Rating | Descriptor |
| --- | --- |
| 0 | Rest |
| 1 | Very, very easy |
| 2 | Easy |
| 3 | Moderate |
| 4 | Somewhat hard |
| 5 | Hard |
| 6 | (unlabelled) |
| 7 | Very hard |
| 8 | (unlabelled) |
| 9 | (unlabelled) |
| 10 | Maximal |

Foster changed some verbal anchors to American idiomatic English ("light" became
"easy", "strong/severe" became "hard") and deliberately left 6, 8, and 9 without
descriptors, so the athlete is not forced onto a word. The scale has a true zero
and is constructed as a category-ratio scale, which is what makes multiplication
by duration defensible in the first place.

This matters for the app. `app/main.py` accepts `1 <= rpe <= 10` and the glossary
describes the input as "the athlete's 1–10 judgement ... on the Foster scale".
Foster's scale is 0–10. A 1–10 scale without a true zero is an ordinal scale, and
multiplying ordinal values is not a defined operation. The practical effect is a
compression of the intensity range: if true perceived load is `p` in [0, 1], the
CR-10 gives `10p` while a 1–10 scale gives `1 + 9p`. A 30-minute session at
`p = 0.2` scores 60 on CR-10 but 84 on the 1–10 scale; a 90-minute session at
`p = 0.8` scores 720 but 738. The ratio between the two sessions falls from 12:1
to 8.8:1. Short easy sessions are inflated most.

## 3. The anchoring procedure

Foster's protocol has three parts, and all three are part of the method rather
than optional polish:

1. **Familiarisation before data collection.** The athlete is shown the scale and
   its verbal anchors in advance.
2. **A global question, not a momentary one.** "How was your workout?" asks for a
   single rating of the whole session. Foster reports that 80–90 % of athletes
   give one number; the rest insist on fractionating the session and summing the
   parts.
3. **A delay of about 30 minutes.** The delay exists so that a particularly hard
   or easy final segment does not dominate the rating.

Later work suggests 15 minutes is sufficient (Kraft et al., 2014, found no
difference between 15 and 30 minutes and r = 0.986 between the two). An app that
collects the rating whenever the athlete opens it is therefore not violating the
method, provided the prompt asks for the session as a whole rather than "how do
you feel now".

## 4. Validity evidence

The evidence is convergent rather than criterion-based, and that distinction
matters.

- Impellizzeri et al. (2004) collected 476 individual soccer sessions and
  correlated session-RPE with three TRIMP variants: r = 0.54–0.78 against
  Edwards, 0.50–0.77 against Banister, and 0.61–0.85 against Lucía.
- Haddad et al. (2017) reviewed 36 studies using the Foster method across
  individual, team, aquatic, and resistance activities, and concluded that the
  method has good reliability and internal consistency and can be used
  "standing alone".
- In runners specifically, session-RPE and an individualised TRIMP correlated at
  r = 0.79 in recreational marathoners (Manzi et al., 2009, as reported in the
  same literature).

The caveat is that the criterion in Foster's own study — Edwards' five-zone
summated HR — is itself an arbitrary weighting with no known physiological
calibration (Haddad et al., 2017). Session-RPE agreeing with Edwards' TRIMP means
two proxies agree, not that either is a gold standard. No method in this space
currently qualifies as one.

## 5. Reliability is weaker than validity

Wallace et al. (2014, *J Strength Cond Res*) compared the test-retest reliability
of the common methods in 10 recreational athletes over 18 sessions. The
coefficient of variation was:

| Method | CV |
| --- | --- |
| Heart rate | 3.9 % |
| RPE 6–20 (momentary) | 8.5 % |
| Lucía TRIMP | 10.7 % |
| Banister TRIMP | 15.6 % |
| Session-RPE | 28.1 % |

A 28 % coefficient of variation is large for a number that is multiplied by
duration and then fed into a 42-day moving average. It does not invalidate the
method — the same study still found session-RPE correlated with oxygen uptake —
but it means single-session differences of 20–30 % are indistinguishable from
noise. Session-RPE is a trend instrument, not a measurement.

## 6. Known limitations

**The duration confound.** Load = RPE × duration, but RPE itself rises with
duration even when work rate and physiological responses are held constant.
Fusco et al. (2020) demonstrated this directly in prolonged exercise. The product
therefore counts duration twice: once explicitly, once through the rating.
Desgorces et al. (2020) compared session-RPE with "RPE alone" in high-intensity
interval sessions and found that the multiplication inflated the load of long,
low-density sessions relative to short, dense ones; they argued for RPE alone as
the load measure. The product is still the published method and is defensible
because it preserves the volume term, but the double count is real and is the
main reason session-RPE and pace load cannot be assumed to be on the same scale.

**Monotony and strain.** Foster (1998) proposed two derived indices:

```
monotony = mean daily load over the week / SD of daily load over the week
strain   = weekly total load × monotony
```

Both are descriptive. The evidence linking them to overtraining and illness is
observational and thin; neither is a validated injury predictor. The app does not
currently compute either. If they are added, they should be labelled as
descriptive, not as risk scores.

**Other influences.** RPE is sensitive to sleep, mood, heat, altitude, glycogen
availability, and the athlete's understanding of the scale. It is also
susceptible to social desirability: an athlete who believes the coach wants a
"hard" session may anchor high. None of this is corrected by the arithmetic.

## 7. Is RPE × duration the right formula?

Yes, with qualifications. It is the operationalisation that the validity
literature actually tested, it keeps the volume term that every other load model
also has, and it has a true zero if the CR-10 is used. The alternatives are:

- **RPE alone.** Defensible for high-intensity, density-driven sessions
  (Desgorces et al., 2020), but it loses the volume dimension and would not be
  comparable with the pace model at all.
- **RPE × duration with a duration correction.** No validated correction exists.

For a running app whose other load source is minutes × weight, keeping
RPE × minutes is the only choice that preserves a common unit. The fix is not the
formula; it is the scale and the calibration.

## References

- Desgorces FD, Hourcade JC, Dubois R, Toussaint JF, Noirez P. Training load
  quantification of high intensity exercises: discrepancies between original and
  alternative methods. *PLoS One.* 2020;15(8):e0237027.
  doi:10.1371/journal.pone.0237027
- Edwards S. *The Heart Rate Monitor Book.* Port Washington, NY: Polar Electro Oy;
  1993.
- Foster C. Monitoring training in athletes with reference to overtraining
  syndrome. *Med Sci Sports Exerc.* 1998;30(7):1164–1168.
  doi:10.1097/00005768-199807000-00023
- Foster C, Florhaug JA, Franklin J, Gottschall L, Hrovatin LA, Parker S,
  Doleshal P, Dodge C. A new approach to monitoring exercise training.
  *J Strength Cond Res.* 2001;15(1):109–115.
  doi:10.1519/00124278-200102000-00019
- Fusco A, Knutson C, King C, Mikat RP, Porcari JP, Cortis C, Foster C. Session
  RPE during prolonged exercise training. *Int J Sports Physiol Perform.*
  2020;15(2):292–294. doi:10.1123/ijspp.2019-0137
- Haddad M, Stylianides G, Djaoui L, Dellal A, Chamari K. Session-RPE method for
  training load monitoring: validity, ecological usefulness, and influencing
  factors. *Front Neurosci.* 2017;11:612. doi:10.3389/fnins.2017.00612
- Impellizzeri FM, Rampinini E, Coutts AJ, Sassi A, Marcora SM. Use of RPE-based
  training load in soccer. *Med Sci Sports Exerc.* 2004;36(6):1042–1047.
  doi:10.1249/01.MSS.0000128199.23901.2F
- Kraft JA, Green JM, Thompson KR. Session ratings of perceived exertion
  responses during resistance training bouts equated for total work but differing
  in work rate. *J Strength Cond Res.* 2014;28(2):540–545.
  doi:10.1519/JSC.0b013e31829999e9
- Wallace LK, Slattery KM, Impellizzeri FM, Coutts AJ. Establishing the criterion
  validity and reliability of common methods for quantifying training load.
  *J Strength Cond Res.* 2014;28(8):2330–2337.

### Access notes

Foster et al. (2001) was read in full via a publicly posted copy of the published
article; the quotation of the method and the scale are from that text. Foster
(1998) was not read in full (paywalled); monotony and strain are cited from the
definition reproduced in Foster et al. (2001) and Haddad et al. (2017). Kraft et
al. (2014) was read as an abstract. The Manzi et al. (2009) running correlation is
reported second-hand through the review literature, not from the original paper,
and is flagged as such above. The Wallace et al. (2014) reliability table is from
the published abstract; the full text is paywalled.

## Verdict for this app

**The method is defensible and is the best-validated load source in the app. The
implementation of the scale is not.**

Keeping session-RPE as the preferred source when an RPE is logged is correct: it
has direct validity evidence (Foster et al., 2001; Impellizzeri et al., 2004),
whereas the pace-zone index does not (`01-pace-zone-load.md`). Using moving time
rather than elapsed time is also a defensible choice for running, though it
differs from the original protocol and should be stated in the docstring.

Problems, in priority order:

1. **The scale is 1–10, not 0–10.** Foster's instrument is the modified CR-10 with
   0 = rest. Change the API contract to accept 0, move the bounds out of
   `app/main.py` (where `1 <= rpe <= 10` is repeated inline, contrary to the
   project's no-magic-numbers rule) into `app/config.py` as `RPE_MIN = 0` and
   `RPE_MAX = 10`, and render the actual verbal anchors in the UI.
2. **The glossary is wrong.** `GLOSSARY.md` says "1–10 judgement ... on the Foster
   scale". It should say "0–10 modified CR-10 (Foster) scale".
3. **There is no anchoring step.** The method assumes the athlete was shown the
   scale and asked for a global rating. A first-use explainer and a prompt that
   says "rate the session as a whole, not the last kilometre" are part of the
   instrument, not decoration.
4. **The two load sources are on different scales.** A 60-minute easy run is about
   120 in pace units but 180–240 at RPE 3–4. Because `activity_load` switches
   source per activity, a user who starts logging RPE will see CTL step upward
   and ACWR spike for measurement reasons. Calibrate: use the `pace_load` and
   RPE values that `activity_load` already returns together to estimate a
   per-athlete conversion factor, then express both sources in the same unit.
5. **Optional, later:** add monotony and strain as clearly descriptive metrics
   (Foster, 1998), never as risk scores.

Until items 1–4 are done, the session-RPE path is scientifically sound but
numerically incompatible with the pace path it is supposed to override.
