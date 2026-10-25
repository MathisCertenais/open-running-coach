# Coach Running — Sales Proposal

**Turn your Strava, Garmin and OpenTracks data into a coach that actually knows your training.**

---

## Executive summary

Coach Running is a privacy-first running intelligence platform. It imports your raw activity files from **Strava, Garmin and OpenTracks**, computes the metrics that actually matter — **injury risk, fitness/fatigue, 80/20 intensity, VO2max and race predictions** — and adds an **AI coach** that explains what the numbers mean and builds an action plan for your next competition.

Most tools show you data. Coach Running tells you **what to do next**, grounded in your own training rather than generic advice.

## The problem

Runners are data-rich and insight-poor:

- **Strava** shows maps, segments and kudos.
- **Garmin** shows device widgets.
- **OpenTracks** records tracks.
- None of them answers the questions that matter: *Am I at risk of injury? Am I training polarized? How fit am I, really? What should I do in the next 8 weeks for my race?*
- A human coach is expensive and not available after every run. Generic AI chatbots don't have your data — and make things up.

## The solution

Three layers, one product:

1. **Import & normalize** — one canonical activity model from KMZ, GPX and TCX; duplicate runs across sources are detected and merged automatically.
2. **Analyze** — scientifically grounded metrics, each explained in plain language.
3. **Coach** — an AI that reads those metrics, explains them, and turns them into a plan.

## Works with the data you already have

- **Strava** — export your history as GPX (bulk) or a single activity.
- **Garmin** — export TCX/GPX from Garmin Connect.
- **OpenTracks** — native KMZ files.
- Just drop the files in the app's data folder; they are auto-detected.
- The same run in two sources? Deduplicated automatically (fingerprint-based).

No vendor lock-in, and your files stay on your machine.

## The metrics that matter

| What | What it tells you | Grounded in |
|---|---|---|
| **Training load & ACWR** | Injury risk from sudden load spikes; the safe 0.8–1.3 "sweet spot" | Gabbett (2016) |
| **Fitness / fatigue / form** | CTL/ATL/TSB — are you building fitness or burning out? | Banister; Coggan |
| **80/20 intensity** | Are you polarized, or stuck in the "grey zone"? | Seiler (2010) |
| **VO2max & race predictor** | Your aerobic ceiling and realistic race times, 400 m → marathon | Daniels (VDOT); Riegel |
| **Session-RPE** | How hard it really felt — not just pace | Foster (2001) |
| **Splits, laps, GAP, best efforts** | The detail behind every run | — |

Every metric is **explainable in the app**: what it means, the formula behind it, and how to act on it.

## The AI coach

- **Explains your data** — "Your ACWR is 2.66 (high-risk band): here's why, and what to change this week."
- **Answers your questions** — "Why is my 80/20 off?", "Am I ready for a 10k?"
- **Reviews your week** — structured as Assessment → What the data says → Recommendations → Watch-outs.
- **Plans your next competition** — periodized weeks, 80/20 sessions, +10% progression, deloads and a taper.
- **Stays honest** — uses only your numbers, flags red flags, never diagnoses injuries, and tells you when to see a professional.
- **Respects privacy** — runs on a local model (Ollama) so your data never leaves your machine, or connects to your own API.

## From data to a race plan

1. **Set the goal** — distance + date.
2. **We compute** your current fitness, load, ACWR, VO2max and predicted time.
3. **The generator builds** your weeks and sessions (recovery, easy, long run, tempo, intervals) with target pace zones.
4. **You log** a 30-second post-run check-in (RPE, sleep, stress, pain).
5. **The coach adjusts** the plan every week and tapers you into race day.

## The 30-second post-run check-in

RPE, session intent, surface, completion, readiness, sleep, stress, legs, a structured **pain log** (location, side, severity, timing, trend) and a race flag. This is what turns raw GPS into real coaching context.

## Privacy by design

- **Local-first**: your files and database stay on your machine.
- **No account required.**
- **AI is opt-in**; only derived metrics are sent — never GPS coordinates.
- **Local-model option** keeps everything on-device.
- **Transparent formulas** — no black-box scores.

## Why Coach Running

- **One place** for Strava + Garmin + OpenTracks.
- **Explainable** metrics, not vanity charts.
- **AI grounded in your data**, not generic tips.
- **A plan**, not just a dashboard.
- **Private by architecture.**

## Who it's for

- Ambitious amateur runners training for a 5k, 10k, half or marathon.
- Self-coached athletes who want structure without a full-time coach.
- Privacy-conscious runners who don't want their GPS history in the cloud.
- (Roadmap) Coaches and clubs managing several athletes.

## Packaging (illustrative — to be adjusted)

| Plan | Includes | Price |
|---|---|---|
| **Core** | Import, dashboards, metrics, records, heatmap | Free |
| **Pro** | AI coach, race plans, post-run check-in, advanced analytics | €— / month |
| **Coach / Club** | Multi-athlete dashboards (roadmap) | Contact |

## Roadmap

- **FIT** file support (native Garmin device exports).
- Heart-rate zones when data is available.
- Opt-in cloud sync and a mobile companion.
- Multi-athlete support for coaches and clubs.

## Get started

Import your last 90 days, open the **Coaching** tab, and ask the coach for your first race plan. You'll have a personalised, science-based plan in minutes.

---

### Appendix — scientific references

- Banister EW, Calvert TW, Savage MV, Bach T (1975). A systems model of training for athletic performance.
- Morton RH, Fitz-Clarke JR, Banister EW (1990). Modeling human performance in running.
- Foster C, et al. (2001). A new approach to monitoring exercise training (session-RPE).
- Gabbett TJ (2016). The training–injury prevention paradox (ACWR).
- Seiler S (2010). What is best practice for training intensity and duration distribution?
- Daniels J. Daniels' Running Formula (VDOT).
- Coggan A. Training and Racing with a Power Meter (CTL/ATL/TSB).
- Riegel PS (1981). Athletic records and human endurance.

> Coach Running is a training tool, not a medical device. It does not diagnose or treat injuries.
