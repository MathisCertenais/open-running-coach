# 09 — GPS speed thresholds: what is a defensible jump filter?

Status: research note. Not a spec.
Applies to: `app/activity.py` (`MAX_IMPLIED_SPEED`, `step_distance`,
`step_speed`, `is_moving_step`), `app/config.py` (`MOVING_SPEED_THRESHOLD`,
`MAX_MOVING_GAP`), `app/analysis.py` (`_steps`).
Last reviewed: 2026-10-25.

## The question

Three constants decide what counts as movement:

- `MAX_IMPLIED_SPEED = 10.0` m/s — above this, a step's displacement is treated
  as a GPS error and replaced by the speed-sensor distance (or zero).
- `MOVING_SPEED_THRESHOLD = 0.3` m/s — below this, a step is not moving time.
- `MAX_MOVING_GAP = 120` s — longer gaps are not moving time.

Are these defensible against the physics, the GPS accuracy literature, and what
the major platforms do?

## 1. Is 10 m/s a plausible ceiling?

No — it is below the world record.

Štuhec, Planjšek, Čoh & Mackala analysed Usain Bolt's 9.58 s 100 m (Berlin 2009)
from 100 Hz laser displacement data: **average velocity 10.44 m/s**, **maximum
velocity 12.32 m/s** reached at 52.51 m, with 10 m sections averaging 12.10–
12.32 m/s between 50 and 90 m (*Bioengineering* 2023;10(11):1254,
doi:10.3390/bioengineering10111254). The official record itself is 9.58 s for
100 m, i.e. 10.44 m/s mean.

So `MAX_IMPLIED_SPEED = 10.0` m/s is **96% of the world-record average** and
**81% of the world-record peak**. For a recreational running app that is a
perfectly reasonable *plausibility* filter — no user will sustain 10 m/s for a
whole step — but it cannot be described as a physical maximum, and it will clip
genuine data for sprint-trained users, downhill segments, and any activity where
two points are far apart in time.

That last case is the real defect. The test is `d / dt > 10`, so the distance
that triggers rejection scales with the sampling interval:

| `dt` | Distance that trips the filter |
| --- | --- |
| 1 s | 10 m |
| 5 s | 50 m |
| 30 s | 300 m |
| 120 s | 1200 m |

At 1 Hz, 10 m is exactly the scale of a bad fix. At 30 s — a normal smart-recording
interval, or a tunnel — a 300 m displacement is entirely plausible running and
passes; a genuine 400 m GPS excursion over 30 s (13 m/s) is rejected even though
the athlete may really have covered it on a downhill. The threshold is doing two
different jobs (noise rejection and gap handling) with one number.

## 2. What the GPS literature says about the noise floor

### Consumer watches under-report distance overall, but over-read noisy tracks

Gilgen-Ammann, Schweizer & Wyss tested eight sport watches (Apple, Coros, Garmin,
Polar, Suunto) at 1 Hz over 400–4300 m in urban, forest and track settings
(*JMIR mHealth uHealth* 2020;8(6):e17118, doi:10.2196/17118):

- Mean absolute percentage error **3.2% to 6.1%** across devices.
- Distances were **systematically underestimated**, by up to **9%**; worst in
  forest and urban settings, best on an open track (where six of eight watches
  over-read by 0.9–4.1%).
- **Running was worse than walking and cycling** in six of eight watches — the
  authors attribute this to gait-related arm swing, not speed.
- The paper's background reports horizontal location errors of **7.1–9.4 m**
  (SD 14–18 m) for GPS, GLONASS and GPS+GLONASS, citing reference station data.

Those are whole-activity numbers, after each manufacturer's own smoothing. They
bound the *aggregate* error, not the per-step error that `step_distance()`
operates on.

### Measurement error inflates distance, especially at high sampling rates

Ranacher, Brunauer, Trutschnig, Van der Spek & Reich show mathematically and
empirically that "the distance between two points recorded with a GPS is — on
average — bigger than the true distance", and that the bias "becomes relevant if
the influence of interpolation error can be neglected, which in practice is the
case for movement sampled at high frequencies" (*Int J Geogr Inf Sci*
2016;30(2):316–333, doi:10.1080/13658816.2015.1086924; abstract). They also show
the error is strongly autocorrelated in space and time, which is why it partly
cancels over long averages.

The consequence for a step filter: at 1 Hz, consecutive fixes are close enough
that positional noise dominates the true displacement of a 3 m step. A single
8–10 m error produces an implied speed of 8–10 m/s. `MAX_IMPLIED_SPEED = 10`
therefore sits **at the top of the routine noise distribution**, not above it.
It catches the gross outliers (a 34 m jump between adjacent fixes, the example in
the code comment) and lets through the 8–9 m ones, which are exactly the ones
that inflate distance.

### High-speed distance is the least accurate metric

Rampinini et al. compared 5 Hz and 10 Hz units against radar during shuttle
running (*Int J Sports Med* 2015;36(1):49–53, doi:10.1055/s-0034-1385866):

| Metric | 5 Hz error | 10 Hz error |
| --- | --- | --- |
| Total distance | 2.8% | 1.9% |
| High-speed distance (>4.17 m/s) | 7.5–23.2% | 4.7% |
| Very-high-speed distance (>5.56 m/s) | moderate–high | 10.5% |

"GPS accuracy increased with a higher sampling rate, but decreased with
increasing speed of movement." This is the opposite of what a speed-based jump
filter assumes: the fastest steps are the least trustworthy, so a filter that
only rejects above a fixed speed will systematically keep the noisiest data just
below the line.

### The processing is a black box

Malone et al. review how device sampling rate, fitting, satellite geometry and
"data-filtering methods" all change the reported metrics, and recommend that
researchers report brand, sampling frequency, satellite count, HDOP and firmware
(*Int J Sports Physiol Perform* 2017;12(S2):S218–S226,
doi:10.1123/ijspp.2016-0236). The practical implication for this app: two files
with the same nominal 1 Hz rate can carry very different error profiles, and no
single global speed threshold can be optimal for both.

## 3. What the platforms actually do

Only what is documented or visible in source is stated here. None of the major
platforms publishes a numeric jump-rejection threshold.

**Strava.** Their support documentation is unusually candid:

- Max speed is computed as "the fastest speed recorded between any two GPS
  coordinates", and "GPS errors can cause the value to be higher than expected"
  — i.e. Strava does **not** reject jumps for max speed
  (support.strava.com, "Moving Time, Speed, and Pace Calculations").
- Moving time uses "a speed threshold" for uploaded files; the value is not
  published. For runs recorded in the Strava app, an accelerometer is used
  instead.
- A manual "Correct Distance" action exists to "eliminate outlier GPS data"
  (support.strava.com, "How Distance is Calculated").

**Garmin.** Garmin documents two recording modes — "Smart Recording" (variable
interval) and "Every Second Recording" — and recommends every-second recording
for better GPS accuracy (Garmin Support FAQ, "GPS Distance, Speed, and Pace
Accuracy With Garmin Devices"). No public jump-rejection rule. Device-side
distance is usually computed by the watch before upload, so the app never sees
the raw filter.

**OpenTracks.** Inspected at source (Codeberg `OpenTracksApp/OpenTracks`,
default branch; Apache-2.0):

- `TrackPoint.distanceToPrevious()` calls Android `Location.distanceTo()` and
  `TrackStatisticsUpdater` adds it directly to total distance. There is **no
  implied-speed cap** anywhere in the distance path.
- Jumps are handled structurally, not statistically: if the distance to the last
  stored point exceeds `maxRecordingDistance`, the point is stored as
  `SEGMENT_START_AUTOMATIC`, i.e. it starts a new segment. The default
  `max_recording_distance_default` is **200 m**.
- The default `recording_distance_interval_default` is **10 m**, so points are
  stored only after 10 m of movement regardless of time.
- Speed comes from `Location.getSpeed()` (sensor/OS), not from differencing
  positions, which is why OpenTracks can afford no speed filter at all.

So the app's 10 m/s filter is **stricter than Strava, stricter than OpenTracks,
and comparable in spirit to nothing in particular** — it is a reasonable local
invention, not an industry standard.

## 4. The other two constants

### `MOVING_SPEED_THRESHOLD = 0.3` m/s

0.3 m/s is 1.08 km/h — well below walking (~1.4 m/s) and below any plausible
running pace. As a definition of "not stopped" it is conservative in the right
direction *if the speed comes from the sensor*. `step_speed()` prefers the
recorded sensor speed, which is near zero when stationary on a watch with a good
fix, so 0.3 m/s is fine there.

It is **too low when the speed is derived from positions**, which is the case for
GPX files without a speed extension (the Strava-export case, and the common
OpenTracks export). Ranacher et al.'s bias means a stationary receiver
accumulates apparent distance every second; with autocorrelated error the drift
is usually small, but with a poor fix it can exceed 0.3 m/s for several
consecutive samples. The result is a stationary athlete credited with moving
time and distance. A threshold of **0.5–0.7 m/s**, plus a requirement that two or
three consecutive steps exceed it (hysteresis), is more robust for positional
speed.

Strava does not publish its threshold; the fact that it offers a "moving time is
too short / pace too fast" support article for one device family shows how much
this choice moves the numbers.

### `MAX_MOVING_GAP = 120` s

There is no literature basis for 120 s; it is a data-quality policy. It is
generous — Garmin smart recording samples every 5–6 s, and a 2-minute hole means
a tunnel, a lost fix, or a paused device. Two issues:

1. **Distance across the gap is still counted.** `_steps()` computes `d` for
   every consecutive pair and `compute_stats()` adds it to total distance; only
   `dt_moving` is zeroed when `dt > MAX_MOVING_GAP`. So a 5-minute GPS hole with
   500 m of displacement adds 500 m of distance and 0 s of moving time. Pace =
   moving time / distance therefore reads **faster** than reality, sometimes
   dramatically.
2. **The threshold interacts with the jump filter.** A 120 s gap at 10 m/s allows
   1200 m before rejection, so the gap's distance is almost always accepted.

A tighter gap (60 s) plus "drop the distance as well as the time when the gap is
exceeded" would remove the artifact. The alternative — interpolating the missing
distance — invents data and should be avoided in a local-first, auditable app.

## Verdict for this app

**Partly defensible; one constant is mis-specified and one behaviour is a bug.**

- **`MAX_IMPLIED_SPEED = 10.0`** is defensible as a plausibility filter for
  recreational running, but it is **not** a physical ceiling: the world-record
  100 m averages 10.44 m/s and peaks at 12.32 m/s (Štuhec et al. 2023). Rename
  it to say what it is, and document the trade-off. Better: make it **12.5 m/s**
  (record peak plus margin) and add a second, relative test so that noise is
  still rejected:
  - reject if `d/dt > MAX_IMPLIED_SPEED` (12.5), **or**
  - reject if `d/dt > max(3.0, 3 × rolling median of the last 5 implied speeds)`
    — an outlier test that adapts to the athlete's actual pace and to the file's
    noise level.
  This catches the 8–9 m/s spikes that 10 m/s lets through while no longer
  clipping genuine fast running. New constants: `MAX_SPEED_OUTLIER_RATIO`,
  `SPEED_MEDIAN_WINDOW`.
- **`MOVING_SPEED_THRESHOLD = 0.3`** is fine when the file carries sensor speed
  and too low when it does not. Either raise it to **0.5 m/s** globally (simple,
  slightly conservative) or branch on source: 0.3 m/s for sensor speed, 0.6 m/s
  for positional speed, with a 2–3 sample hysteresis. The branch is more code
  but matches the data.
- **`MAX_MOVING_GAP = 120`** should come down to **60 s**, and the distance
  across a gap longer than the threshold must be dropped along with the time.
  Today the app credits distance without time, which biases pace fast — a
  silent, systematic error on exactly the runs with the worst GPS.
- **Add the missing guard for `dt`.** `step_distance()` only applies the speed
  test when `dt > 0`; a zero or negative timestamp difference falls through and
  returns the raw haversine distance. Duplicate timestamps are common in
  converted GPX/KMZ files. Reject `dt <= 0` explicitly.
- **Test the filter at the seams.** `tests/test_analysis.py` covers a gross jump
  (`test_step_distance_rejects_an_implied_speed_jump`, ~111 m in 1 s) and a
  plausible 3.3 m step. It does not cover (a) a 9 m one-second step just below
  the threshold, (b) a 90 s gap with 400 m displacement, (c) a stationary period
  with 5 m of drift, or (d) `dt <= 0`. Add those; they are the cases that
  distinguish a good filter from a lucky one.

## Open questions

- Does the app ever see 5–10 Hz data? KMZ from OpenTracks is typically 1 Hz or
  distance-triggered (10 m); GPX from watches may be smart-recorded. A single
  threshold for all three is a compromise; the relative outlier test above is the
  cheapest way to adapt without parsing device metadata.
- Is a 3× median multiplier right for the first few points of an activity, when
  there is no median yet? Use a fixed absolute floor (3.0 m/s) until five steps
  exist.

## Sources

Read in full:

- Štuhec S, Planjšek P, Čoh M, Mackala K. Multicomponent velocity measurement
  for linear sprinting: Usain Bolt's 100 m world-record analysis.
  *Bioengineering (Basel).* 2023;10(11):1254.
  doi:10.3390/bioengineering10111254.
- Gilgen-Ammann R, Schweizer T, Wyss T. Accuracy of distance recordings in eight
  positioning-enabled sport watches: instrument validation study. *JMIR mHealth
  uHealth.* 2020;8(6):e17118. doi:10.2196/17118.

Abstract only:

- Ranacher P, Brunauer R, Trutschnig W, Van der Spek S, Reich S. Why GPS makes
  distances bigger than they are. *Int J Geogr Inf Sci.* 2016;30(2):316–333.
  doi:10.1080/13658816.2015.1086924.
- Rampinini E, Alberti G, Fiorenza M, et al. Accuracy of GPS devices for
  measuring high-intensity running in field-based team sports. *Int J Sports
  Med.* 2015;36(1):49–53. doi:10.1055/s-0034-1385866.
- Malone JJ, Lovell R, Varley MC, Coutts AJ. Unpacking the black box:
  applications and considerations for using GPS devices in sport. *Int J Sports
  Physiol Perform.* 2017;12(S2):S218–S226. doi:10.1123/ijspp.2016-0236.

Vendor documentation and source code (primary for platform behaviour, not
evidence about measurement accuracy):

- Strava Support. "Moving Time, Speed, and Pace Calculations" and "How Distance
  is Calculated." https://support.strava.com/en-us/articles/15401804 and
  https://support.strava.com/en-us/articles/15401893
- Garmin Support. "GPS Distance, Speed, and Pace Accuracy With Garmin Devices."
  https://support.garmin.com/en-US/?faq=Te47runiFR93oKcUAItwU7
- OpenTracks (Apache-2.0), `src/main/java/de/dennisguse/opentracks/`:
  `data/models/TrackPoint.java` (`distanceToPrevious`),
  `data/statistics/TrackStatisticsUpdater.java`,
  `services/TrackRecordingManager.java` (`SEGMENT_START_AUTOMATIC`),
  `settings/PreferencesUtils.java`, `res/values/settings.xml`
  (`max_recording_distance_default` = 200 m,
  `recording_distance_interval_default` = 10 m).
