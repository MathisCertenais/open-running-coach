# open-running-coach

A local-first running analysis and coaching application. This glossary fixes the
vocabulary used across the code, the API payloads, the UI copy and the issue
tracker. Definitions state **what a term is**, not how it is implemented.

Formulas and their sources live in `docs/research/` and in the code that
implements them, not here.

## Language

### Recording and measurement

**Activity**:
One recorded run, read from one file. It owns its points, segments and markers.
_Avoid_: Session (reserved for a planned unit), workout, run file.

**Track Point**:
A single timestamped GPS sample inside an activity.
_Avoid_: Sample, fix, location.

**Segment**:
A contiguous run of track points inside one activity, delimited by a manual
start/stop. Segments are what the app calls laps.
_Avoid_: Track, lap, interval (an interval is a training intent, not a recording).

**Lap**:
The user-facing name for a segment.
_Avoid_: Split.

**Split**:
A fixed-distance slice of an activity, usually one kilometre, computed after the
fact. Independent of how the athlete segmented the recording.
_Avoid_: Lap.

**Marker**:
A waypoint the athlete dropped during the activity, with an optional name and
note.
_Avoid_: Point, flag, waypoint.

**Moving Time**:
Elapsed time during which the athlete was actually travelling, excluding pauses,
IDLE samples and implausibly long gaps between points.
_Avoid_: Active time, elapsed time.

**Elapsed Time**:
Wall-clock duration from first to last track point, pauses included. Never
confused with moving time.
_Avoid_: Total time.

**Best Effort**:
The fastest time an activity contains over one of the reference distances
(400 m, 1 km, 1 mile, 5 km, 10 km, half marathon, marathon), regardless of where
in the activity it occurs. Measured in moving time.
_Avoid_: Record, PR.

**Matched Run**:
Another activity covering the same route, detected by route similarity rather
than by name.
_Avoid_: Duplicate, repeat.

### Intensity

**Pace Zone**:
One of six pace bands, from recovery (Z1) to sprint (Z6), used to classify time
spent at a given intensity without heart rate.
_Avoid_: Intensity zone, HR zone, effort level.

**Zone Group**:
The three-way collapse of the pace zones used for intensity distribution: Easy
(Z1–Z2), Moderate (Z3), Hard (Z4–Z6).
_Avoid_: Category, bucket.

**GAP (Grade-Adjusted Pace)**:
A pace recalculated to the equivalent flat-ground effort, so a hilly run can be
compared with a flat one.
_Avoid_: Adjusted pace, normalised pace.

**Intensity Distribution**:
The split of training **time** across the zone groups, compared with the
polarised target of 80% easy / 10% moderate / 10% hard.
_Avoid_: Training mix, zone breakdown.

### Load and form

**Training Load (TL)**:
A single number for one day expressing how much training stress that day
contains, comparable across days and weeks.
_Avoid_: Load score, stress, points.

**Pace-Based Load**:
Training load derived automatically from the time spent in each pace zone,
weighted so that faster zones count more. Used when no RPE is logged.
_Avoid_: Zone load, TRIMP.

**Session-RPE Load**:
Training load derived from the athlete's rating of perceived exertion multiplied
by the session duration. Used whenever an RPE is logged, and preferred over
pace-based load for that activity.
_Avoid_: RPE score, perceived load.

**RPE (Rating of Perceived Exertion)**:
The athlete's 1–10 judgement of how hard a session felt, on the Foster scale.
_Avoid_: Effort, intensity rating.

**CTL (Chronic Training Load) / Fitness**:
A slow-moving average of daily training load, representing the fitness an
athlete has built. Rises slowly, decays slowly.
_Avoid_: Fitness score, form.

**ATL (Acute Training Load) / Fatigue**:
A fast-moving average of daily training load, representing recent fatigue. Rises
and falls quickly.
_Avoid_: Fatigue score, load.

**TSB (Training Stress Balance) / Form**:
The gap between chronic and acute load. Positive means fresher than usual,
negative means more fatigued than usual. It is a consequence of training, not a
target to train for.
_Avoid_: Readiness, freshness score.

**Calibrating**:
The state of the chronic/acute averages while they are still dominated by the
cold start rather than by the athlete's history. No form band is shown until
calibration is over.
_Avoid_: Warming up, provisional.

**Load Change (acute:chronic ratio)**:
Recent load (7 days) compared with the 28 days before it. It says how fast
training is changing. It is not a risk score.
_Avoid_: Injury risk, ACWR risk, danger score.

**Ramping Down / Steady / Ramping Up / Sharp Increase**:
The four load-change bands. They describe the direction of the change, not the
athlete's condition.
_Avoid_: Undertraining, sweet spot, caution, high risk.

**After a Break**:
The state of the load-change metric once more than a week has passed without a
recorded activity. The ratio is withheld rather than shown as a decrease.
_Avoid_: Detraining, undertraining.

### Performance

**Effective VO2max**:
An estimate of aerobic capacity inferred from the athlete's recorded best
efforts rather than measured in a laboratory.
_Avoid_: Real VO2max, lab VO2max.

**VDOT**:
Daniels' single-number running ability score, derived from a race performance
and used to compare and predict performances.
_Avoid_: VO2max (they are related but not the same).

**Race Prediction**:
An estimated finish time over a target distance, extrapolated from a recent
performance.
_Avoid_: Forecast, projection.

### Planning

**Plan**:
A saved, dated sequence of weeks and sessions built to reach one goal.
_Avoid_: Programme, schedule.

**Session**:
One planned training unit inside a plan, with a workout type, a duration or
distance, and target zones.
_Avoid_: Workout (reserved for imported strength sessions), activity.

**Workout Type**:
The intent of a session: recovery, easy, long run, tempo, or intervals.
_Avoid_: Session type, category.

**Periodisation**:
The arrangement of training volume and intensity across weeks so that fitness
builds and fatigue is released before the goal.
_Avoid_: Progression, planning.

**Deload**:
A planned week of reduced volume, repeated on a fixed cycle, that lets
adaptation catch up with the load.
_Avoid_: Rest week, recovery week.

**Weekly Progression**:
The increase in volume from one week to the next during a build block.
_Avoid_: Ramp, increase.
