# Done

Completed work, and **the findings that outlived it**. Nothing here is a task.

This file exists because most of what was learned building MarisAI is only
legible as the residue of finished work: a measured number, a decision with its
reason attached, or a mistake worth not repeating. TODO.md holds pending work
only; anything that ships moves here with its evidence rather than being
deleted.

Numbers were measured, not estimated. Re-verify before relying on any of them if
it has been a while.

---

## Forecasting engine

### `wind_u` / `wind_v` — trained 2026-08-15

Both variables ship at all four horizons, 0 of 5 folds negative everywhere:

| | h1 | h3 | h7 | h30 |
| --- | --- | --- | --- | --- |
| `wind_u` | +0.217 | +0.301 | +0.385 | +0.398 |
| `wind_v` | +0.300 | +0.366 | +0.398 | +0.450 |

Forecast wind particles ship on top of them. Both grids carry **no covariates at
all** — `pressure` and `air_temperature` are Open-Meteo, a point API, so no
global field for them can exist — and `missing_covariates` names them in the
layer attribution, because LightGBM routes an absent feature down its
missing-value branch without complaint and the map would otherwise look exactly
as confident as a complete one.

**A dependency recorded as blocked was not.** This entry claimed upwelling was
waiting on these models. Upwelling needs wind *components*, and
`copernicus_wind.snapshot()` had exposed live `u`/`v` all along for
`services/drift.py` to sum; the training run produced *forecast* grids, which is
a different thing and the wrong footing for a detector. **Check what a dependency
actually needs before recording it as blocked.**

### The `--all` grid build — complete

Verified on disk 2026-08-17: 28 grids; the only 5 trained variables without one
are the Open-Meteo point-API variables `grid_history.ungriddable_reason` already
refuses. **0 grids stale** against their models. Count the directory, never a
number in a document — it was 8 on 2026-08-14 and 28 two days later.

### The 13 mixed-cadence variables — retrained 2026-08-15

`cleaning.py` merged providers and *then* resampled, so an hourly covariate
paired with a daily target survived as its 00:00 sample standing in for a 24-hour
mean. On a synthetic 3 °C diurnal cycle the old path returned **23.0 where the
daily mean is 20.0** — wrong by the full amplitude, in the same direction, in
every row, with nothing raised. Fixed by reordering to resolve codes → aggregate
per provider → merge.

**Skill then moved by less than ±0.03 everywhere, in no consistent direction**
(worst: `chlorophyll_a` h30 −0.028, `nitrate` h7 −0.030). That does not make the
fix wrong — the old path provably misrepresented a daily mean — but it answers
"how much was riding on it": on these series, the difference between a
covariate's daily mean and its midnight sample does not propagate into forecast
skill. Worth knowing before budgeting a retrain against a similar find.

**The rejections reproduced, which is the more interesting half.** A retrain
trains every *configured* horizon and has no concept of rejection, so the batch
silently resurrected six horizons deleted on their own merits — and all six
failed again with the same signature. The 2026-08-10 rejections were signal, not
fold noise. `scripts/apply_shipping_bar.py` makes the check mechanical: it reads
`metrics.json` rather than the aggregate log line, and **moves** failures to
`_rejected/<date>/` because the artifact is the evidence for the decision. Run it
after every batch retrain; nothing else catches a resurrected horizon.

### Circular variables — closed 2026-08-17

Everything downstream of the model had handled bearings since 2026-08-13
(sin/cos resampling recombined with `atan2`, a signed veer wrapped to [−180,
180), a cyclic ramp on the true 0–360 domain, `circular` living only in
`VariableInfo`). **The model itself was still linear**: with `target_mode:
delta` a 5° veer across north trains as −355, teaching an excursion that never
happened and leaving no trace — the model fits, scores and returns bearings in
range.

`current_direction` and `wind_direction` are now assembled from their forecast
components (`forecasting/derived.py`). The grid path combines two existing
component grids in **~1 second instead of ~25 minutes**; verified on the real
grids, 200 random ocean cells agree with the point path to **0.0e+00 degrees**
with NaN structure matching the components exactly. The interval is propagated
through `atan2` rather than copied, so a faster vector gets a tighter bearing —
and it widens to the full circle as the vector vanishes, because slack water
genuinely has no heading.

**`wave_direction` stays trained** and still carries the linear-target flaw: the
registry has no wave components to decompose. That asymmetry is stated in the
catalog rather than hidden.

### `current_direction` was reported in the wrong convention — fixed 2026-08-17

`cleaning.py::_derive_direction_to` returned the bare mathematical angle,
`degrees(atan2(v, u))`, where a compass bearing is `90 − that`:

| flow | downloader (old) | live map layer |
| --- | --- | --- |
| east | 0 | 90 |
| north | 90 | 0 |
| west | 180 | 270 |
| south | 270 | 180 |
| north-east | **45** | **45** |

Water flowing due east was reported as due north — in range, smooth, and wrong
everywhere except the 45° diagonal, which is the one test vector a person is
most likely to try by hand. The sibling `_derive_direction_from` was never
affected: `270 − angle` is `(90 − angle) + 180`, the correct bearing plus the
half turn that makes it a "from". **The two derivations sit three lines apart and
only one was wrong**, which is why it survived. It reached the downloader's CSV
exports, the trained model and its grid; the model is retired to
`_rejected/20260817/` and the grid rebuilt from components.

### Rejections to respect, not retry

A horizon ships only if **overall skill > 0 AND at most 1 of 5 folds is
negative**. The second clause is load-bearing: *six* rejected horizons print
`beats persistence` on the aggregate line.

- **`sea_surface_salinity` — dropped entirely.** h3 −0.152, h7 −0.118.
- **`water_salinity` h3/h7 deleted, h1+h30 kept.** Same physics, different
  evidence: h1 is +0.179 with 0/5 folds negative and tightly clustered.
- **`bottom_temperature` h1 only.** "Forecastable a day out, not beyond."
- **`humidity` h1 deleted.** −0.020, 2/5 negative (one at −0.435).
- **`nitrate` h3 deleted**, then legitimately returned at +0.103 (1/5 negative).
- **`sea_level_anomaly` h7/h30 deleted.** Both printed `beats persistence`
  (+0.073, +0.111) with **2 of 5 folds negative** — the cleanest demonstration
  in the repo of why the second clause exists.

Weakest thing kept: `diffuse_attenuation` h3 at +0.026 (1/5 negative). Revisit it
first if the bar is ever tightened.

### The daily-Copernicus question — settled 2026-08-15: **do not swap**

Measured through the real fetch path on a 10-day window:

| | s/timestep | a 45-day grid window |
| --- | --- | --- |
| hourly physics, thetao+so | **0.89** | 1080 reads = **15.9 min** |
| daily thetao, depth-bounded | **1.16** | 45 reads = **0.9 min** |
| daily thetao, *no* depth bound | 8.63 (2-day window) | 45 reads = 6 min |

Daily is ~18x cheaper, not the ~40x on record, and hourly costs ~16 min rather
than ~35. **Every earlier figure was wrong in both directions** — a short window
is dominated by per-request overhead (the same daily read measured 3.89
s/timestep over 2 days and 1.16 over 10), which is how a probe produces a number
that reverses a ranking.

Rejected anyway, on grounds cost does not settle: it would cost the downloader
`Resolution.hourly` for the seven variables on `copernicus_physics`, turn one
provider into three, and force a full retrain of everything carrying SST /
salinity / currents as a covariate. Revisit only if the grid builder becomes
fetch-bound again, or if a *new* variable needs a daily-only field.

---

## Detection

### The climatology — built 2026-08-17

`services/climatology/` holds a per-cell, per-day-of-year **percentile** stack.
1991–2020, 1°, 271 MB, 30 years fetched in ~25 min and fitted in 761 s.

**The cost was mis-stated as "the expensive global fetch path", and that path
cannot supply it at all.** Every Copernicus provider starts recently — physics
2022-06-01, waves 2022-11-01, wind 2024-06-13, BGC 2021-11-01 — so a 30-year
baseline is not expensive there, it does not exist. **NOAA OISST v2.1** is on the
same CoastWatch ERDDAP `crw.py` already uses: daily 0.25°, 1981-09-01 onward, one
year strided to 1° is **94.6 MB in 51 s**.

Verified against the raw record rather than trusted: a hand-computed p90 at
20.1°N 65.1°E day 200 over 290 pooled samples matches the stored value exactly
(29.6130 / mean 28.4055); the seasonal cycle is hemispherically opposite; global
p90 spans −1.80…35.68 °C.

Four things learned, each from getting it wrong first:

- **A 5-day probe measured 8.9 s and would have predicted ~11 min per year** —
  13× off. Per-request overhead dominates a small griddap request.
- **Retry backoff of 2 s/4 s lost the first run inside six seconds**, to a host
  that had served the identical URL twenty minutes earlier. CoastWatch flaps on
  the ~100 s scale, so a policy tighter than the flap cannot outlast one — it
  converts a recoverable outage into a failed job while adding load.
- **Short years are the archive, not a truncated response.** 1991 returns 365
  days and 1993 returns **163**; re-fetching 1993 healthy returns the identical
  163, and the dataset reports `evenlySpaced=false` over 15,210 values across
  ~16,400 days — **~1,200 days genuinely absent**. A per-year completeness check
  written against the wrong diagnosis would have rejected a real baseline
  forever. What protects a percentile is a floor on samples per *estimate*.
  Completeness of the shipped fit: **89.3%**.
- **`p90 >= mean` is false** on 1,940 of 15,761,058 finite cells. Median
  violation 5e-06 °C (float32 rounding); the largest on the Antarctic ice margin,
  where the sample is pinned at the freezing point with warm excursions — a
  right-skewed sample legitimately puts its mean above its 90th percentile.
  `p10 <= p90` does hold and is the ordering worth testing.

Two constructions in the fit are load-bearing and silent when wrong: the
day-of-year index is **leap-adjusted** (pandas puts 1 March at 60 in a common
year and 61 in a leap one), and the pooling window **wraps the year**.

### Eddy detection — shipped 2026-08-15

`services/eddies.py`, Okubo-Weiss (W < −0.2σ) over the live surface-current
cache. **2,097 features globally**, densest exactly where they should be (Gulf
Stream, Kuroshio, Agulhas, the Somali Great Whirl), median radius ~55 km, whole
pass **0.1 s**.

- **Never loop `np.nonzero(labels == index)` per component** — that rescans the
  grid once per feature, measured **37 s** at global scale. Sorting the labelled
  cells once and slicing gives a bit-identical answer in 0.1 s.
- **Polarity is `sign(ζ) == sign(latitude)`**, not `sign(ζ)`: a detector reading
  the vorticity sign alone is right in one hemisphere and confidently wrong in
  the other.
- **On white noise it still returns features** — a relative threshold always has
  cells below it — but every one comes back at the 40 km floor. A *large*
  detection is evidence of real structure; a small one may not be.

### Marine heatwaves — shipped 2026-08-17

`services/heatwaves.py`, to the Hobday definition: SST above the
seasonally-varying 90th percentile for **at least five consecutive days**,
categorised by multiples of the mean-to-p90 gap.

End-to-end on real data: **9,003 of 31,830 ocean cells (60°S–60°N), 28.3%**,
mostly moderate and 16 extreme. That looked high, so it was checked rather than
assumed: **35.0% of cells are above p90 on the latest day alone**, so the
five-day clause removes 6.7 points and is doing its job. The remainder is genuine
warming against a fixed 1991–2020 baseline — which a fixed baseline reports more
of over time by construction, and the layer says so.

Each day is compared against **its own** threshold: over a 30-day window in
spring the seasonal p90 moves measurably, and reusing the latest day's threshold
biases run length in whichever direction the season is going.

### Coastal upwelling — shipped 2026-08-17

`services/upwelling.py`, Bakun's index: Ekman transport from bulk wind stress
projected onto the offshore normal. Reads the live wind and currents caches.

- **The coastal normal is derived from the currents field's own land mask**
  (smooth the ocean mask, take its gradient), because no service supplies
  coastline geometry. Coarse at ~0.25°, so `coastline_confidence` reports how
  well-defined each normal is and an ambiguous cell is dropped rather than given
  an invented bearing. The mask cannot come from the *wind* field — wind is
  defined over land, so its coverage edge is the whole globe.
- **The hemisphere asymmetry falls out of the sign of f**, never a latitude
  branch.
- **A test fixture caught a mistake worth keeping.** The first one put land to
  the west and called it an eastern boundary. That is a *western* boundary, where
  an equatorward wind correctly downwells — so the physics was right and the
  geometry was backwards. Had the code been "fixed" to match, every upwelling
  coast would have been reported as downwelling, in an entirely plausible field.
- **Not corroborated against SST or chlorophyll** at first, deliberately: Bakun's
  index says the wind is favourable, not that cold nutrient-rich water surfaced.
  The SST half shipped later the same day — see below.

### Upwelling corroborated by SST — shipped 2026-08-17

A favourable-wind cell whose water is also cool for the season is a materially
stronger claim than either half alone, and the baseline it needs already existed:
`services/climatology/` fits p10 as the cold mirror of the heatwave p90.

- **One fetch, one baseline, two detectors.** The anomaly is computed in
  `services/heatwaves.py` — same OISST tail, same fitted climatology, sign
  reversed — and exposed as `sst_anomaly_field()`. A second module opening a
  second OISST tail would be a second answer to "how unusual is this water".
  The export is a narrow `SstAnomalyField`, not the whole `HeatwaveField`: a
  caller that could reach `category` and `run_days` eventually would.
- **The index is bit-identical with and without SST, and a test says so.**
  Corroboration adds a claim; it never edits or filters the wind-derived one, so
  a cold SST cache degrades the layer to what it always was rather than failing
  it.
- **Two tiers, because one of them needs a number chosen by hand.**
  `cool_anomaly` is ≥0.5 °C below the seasonal mean — a judgement, and named as
  one. `confirmed_below_p10` is below the local seasonal 10th percentile, defined
  by the distribution and needing no constant. The strong tier is reported
  separately for exactly that reason.
- **`sst_unavailable` is a fifth state, not a falsy `corroborated`.** A coast
  OISST does not cover is neither confirmed nor refuted, and it is excluded from
  the denominator: `favourable_cells_with_sst` is the denominator, not
  `favourable_cells`. Collapsing the two would report a gap in coverage as a
  finding about the ocean — the same rule as the dashboard's `unavailable`.
- **The lag is published rather than folded into one timestamp.** This is where
  it differs from `services/drift.py`, which reports the stalest of its terms
  because they are the same quantity. Wind and currents are hourly; OISST
  publishes daily with a week or more of lag. So the response carries both
  stamps and `lag_hours`, and the wording throughout is "the wind is favourable
  now, and at the most recent SST field, N days ago, this coast was cool for the
  season" — never "the water responded to this wind". Past `MAX_SST_LAG_DAYS`
  (30) even that is withheld with a reason.
- **The cache key is both stamps, held separately from the field.** Keyed on the
  wind alone, a corroboration computed against a fortnight-old SST field would
  survive every OISST publication until the wind happened to move; read back off
  the field, a detection whose SST was refused for age records no SST stamp and
  would never match itself, recomputing on every request.
- **The agreement is weak, and measuring that is the most useful thing here.**
  Live global field, 2026-08-17: **28,203 coastal cells, 13,887
  upwelling-favourable, of which OISST covers 9,316** — a third of the coastal
  band has no SST at all, which is why `sst_unavailable` had to be a state.
  Of those checked, **1,874 (19.9%) were cool for the season and 381 (4.1%)
  below the seasonal p10**. The control makes the reading:

  | | cool (≤ −0.5 °C) | below p10 | mean anomaly |
  | --- | --- | --- | --- |
  | upwelling-favourable | 19.9% | 4.1% | **+0.91 °C** |
  | downwelling-favourable (control) | 17.2% | 3.9% | +0.60 °C |

  Cool water is nearly as common where the wind is piling water *onto* the
  coast, the p10 tiers are indistinguishable, and the favourable coasts are on
  average the *warmer* of the two. With a 14.5-day-old SST field it could hardly
  be otherwise. So a corroborated cell is a real observation of cool water and a
  weak coincidence — not evidence this wind drove it.
  - **The control therefore ships in the response** (`control_cool_fraction`)
    and in the status chip, rather than being left for a reader to think of.
    Same rule as HAB precision against base rate: a level is not a finding
    without the level it beat. Shipping the corroborated count alone would have
    been the most confidently misleading number in the product.
- **The live SST field was tried as the fix and measured worse — that is the
  finding, and it is why `services/sst_anomaly.py` exists to hold it.** The
  obvious reading of the weak contrast above is latency: a 14.5-day-old SST
  field cannot respond to today's wind. So the corroboration was rebuilt on the
  live hourly Copernicus field (hours old) that the SST map layer already
  caches, and both arms were run over the identical wind/currents field:

  | source | cool contrast | below-p10 contrast |
  | --- | --- | --- |
  | OISST record (14.5 d old) | +0.026 | +0.002 |
  | live physics field (current) | +0.022 | **−0.149** |

  Closing a fortnight of latency bought nothing on the weak tier and **inverted**
  the strong one — downwelling-favourable coasts came out below their seasonal
  p10 three times as often as favourable ones. The cause is a product mismatch,
  measured separately on 2026-08-01 (a full day of hourly physics, daily-averaged
  onto the OISST grid):

  | water | mean | median | sd | \|d\|>0.5 °C | \|d\|>1.0 °C |
  | --- | --- | --- | --- | --- | --- |
  | open ocean | +0.033 | +0.011 | 0.467 | 14.3% | 3.9% |
  | **coastal band** | +0.131 | −0.002 | **0.758** | **24.9%** | **10.0%** |

  There is **no systematic offset to correct** — the medians are ~0, so a bias
  constant would have been a fudge with nothing to fix. What there is instead is
  per-cell noise of 0.76 °C on exactly the water this feature scores, wider than
  the 0.5 °C `COOL_ANOMALY_C` threshold, and a below-p10 test is a *tail* test
  that cannot survive noise the width of its own signal. The coast is twice as
  bad as open water because a 1° cell there averages a coastline the two products
  resolve differently.
  - **Latency is not the binding constraint; the baseline's product is.** The
    route forward is a climatology fitted on the Copernicus reanalysis, not a
    fresher observation scored against OISST's. In TODO.md.
  - The live path was **deleted rather than kept behind a flag**. A switch that
    silently makes the detector worse is worth less than the paragraph
    explaining why it does.
- **The lag can be negative, and the bound is on its magnitude.** The wind blend
  lagged the currents by 1.3 days on 2026-08-17, so an SST field *newer* than the
  wind is a normal state rather than an impossible one. A bare `>` on the signed
  lag would wave through an SST field arbitrarily far in the wind's future.
- **On the map it is an outline, never a third fill colour.** The fill answers
  "what is the wind doing" and the stroke answers "and is the water cool too" —
  blended, neither is readable without the other, and a reader could take a
  cold-SST cell home as a stronger *wind* index. Full-width stroke for the p10
  tier, thin for the mean tier. A stroke cannot say "we could not look", so the
  status chip always states how many favourable cells could be checked.

### All three detectors reach the UI — 2026-08-17

Two GeoJSON cell layers in the `flow` category plus status chips, because **a
blank ocean is the most likely output of either layer and it is a result**. The
brief gained a "Detected events" section and an upwelling row; `compare.py`
inherits both. A censored run says "or more" rather than claiming a duration the
window cannot support.

**A 404 that no retry could fix**: `refresh_cache` asked for a date range ending
today, but OISST publishes with a lag (coverage ended 2026-08-01 on 2026-08-17),
and a griddap range past the dataset's end answers 404 — indistinguishable by
status code from the reload 404 the module deliberately retries. Every refresh
burned five attempts and ~8 minutes of backoff. Fixed by asking in index space
with `last`, letting the dataset name its own end.

---

## Machine learning

### The HAB regions — all four run

All of `california_current`, `benguela`, `baltic_sea` and `bay_of_bengal` are
trained beside the `arabian_sea` control. Thresholds and climatology stay fitted
**per region** — they define what counts as a bloom.

| region | base rate | t+3 precision | t+7 precision | t+7 lift |
| --- | --- | --- | --- | --- |
| arabian_sea (control) | 0.076 | 0.449 | 0.202 | +0.053 |
| bay_of_bengal | 0.078 | 0.461 | 0.187 | **+0.150** |
| baltic_sea | 0.139 | 0.699 | 0.416 | — |
| benguela | 0.154 | — | 0.566 | +0.111 |
| california_current | 0.266 | — | 0.844 | +0.076 |

**Base rate does not explain the Arabian Sea.** With three regions the spread
read as prevalence. The Bay of Bengal breaks that: **the same base rate (0.078 vs
0.076) and roughly 3x the lift**. A neighbouring basin at identical prevalence
forecasts substantially better, so the Arabian Sea is genuinely the hard region
rather than the low-prevalence one — a physical question, not an artefact.

Quote both framings: **a user experiences precision**, four-in-five false alarms
being unusable however good the lift, while **a modeller has to judge lift**
because a high base rate makes precision cheap.

**HAB stays multi-region rather than global on arithmetic**: the same six years
worldwide at 0.25° is ~1.6 billion rows and **~650 GB**, most of it open-ocean
rows that are near-constant negatives.

### The global PFZ model is worse over the Indian Ocean — measured 2026-08-15

Scored on **identical rows** (the regional model's own spatial-block holdout, 885
rows / 167 presences):

| | TSS | PR-AUC | ROC-AUC | Boyce |
| --- | --- | --- | --- | --- |
| regional model | **+0.798** | **+0.804** | **+0.945** | **+0.923** |
| global model | +0.448 | +0.489 | +0.790 | +0.721 |

The global model loses 0.35 TSS on the water this platform exists for, despite
training on 123,104 rows against 1,902. **The regional models stay the baseline
and the served artifact.** Going global buys ~170x the labels and spends them on
the wrong ocean.

Two things make the comparison trustworthy: the two shipped reports score
different water and cannot be compared, and the shipped global model was trained
on this water, so `scripts/validate_global_on_region.py` refits it with the
regional holdout's spatial **blocks** removed (blocks, not rows — a global point
50 km away is the same water).

### Fish-habitat ensemble — softmax weighting, 2026-08-13

Members weighted by a **softmax over CV TSS** at temperature 0.05 rather than
proportionally; the ensemble is finally above every member (0.792 against
LightGBM's 0.788). **The cost is real and is why the temperature is a named
constant:** Boyce falls 0.936 → 0.905, so the old ensemble was the better
spatially *calibrated* surface. `proportional` is kept so the earlier baseline
reproduces exactly.

### Per-member experiment tracking — 2026-08-17

Ensemble members are nested MLflow runs rather than flattened metric names
(`cv_tss_lightgbm`, `holdout_boyce_maxent`). Flattened is legible in one run and
useless across runs: MLflow cannot sort, filter or plot by a member when the
member is part of the key. Each member also carries the weight it drew beside its
own quality — the pair that motivated the softmax change.

### HAB t+7 sits at the edge of usefulness

At the 0.8-recall operating point: precision 0.202, false-alarm rate 0.798.
Defensible for a screening tool where a miss costs more than a false alarm, and
recorded as a decision: the layer is named `Bloom Risk (+7d, screening)` and its
attribution carries the per-horizon operating point (+3d 0.449 / +5d 0.280 / +7d
0.202). **Not a bug — listed because it constrains anything built on top of it.**

---

## Platform

### Catching a false refusal — the check `grounded` cannot make — 2026-08-24

The gap the previous multi-agent pass left open, closed the same day.
`_ungrounded_numbers` checks one direction — a number in the answer no tool
reported — and is structurally blind to the opposite failure: the
orchestrator claiming it "couldn't get" something the ledger already holds,
because a refusal states no numbers to check against. `services/chat/agent.py`
now has a second, independent check, `_false_refusal`, riding beside
`grounded` as its own `possible_false_refusal` field rather than folded into
it — the same "two claims, two blocks" shape `services/upwelling.py` uses for
corroboration, because a refusal and a fabricated number are different
failure modes and conflating them into one flag would make the UI's message
generic where it could be specific.

**Three iterations, each broken by a live run before the next one shipped —
this is the record of what a plausible-looking heuristic misses in practice,
not just the final answer:**

1. **v1: flag a refusal-shaped answer with zero numbers anywhere.** Live
   testing (the same Kochi→Kanyakumari question from the prompt-tightening
   pass) reproduced the exact original bug twice — and the check fired on
   neither. Cause: the live model wrote "couldn't" with a **curly Unicode
   apostrophe** (`'`, U+2019), which a straight-quote-only regex (`couldn't`,
   tested only against ASCII in the unit tests) never matches. Every
   provider does this routinely; the check's own unit tests were quietly
   testing an input shape that never occurs in production.
2. **v2: same check, apostrophe-fixed.** Caught 2 of 4 live recurrences. The
   other 2 were refusals that padded themselves with an unrelated real
   number ("GEBCO's 0.05° grid" — true, but general knowledge, not from any
   tool call that turn), which a "zero numbers anywhere" rule can't
   distinguish from an answer that actually used its data.
3. **v3, shipped: flag only when the answer quotes *none* of the numbers the
   ledger's tools actually returned**, matched with the same rendering-
   tolerant comparison `_ungrounded_numbers` already uses (just inverted).
   First live batch at this version: 2 of 3 refusals still slipped through,
   because `ledger.as_text()` includes each call's recorded `arguments` as
   well as its `result` — and both surviving refusals restated the *input*
   coordinates ("I asked to route from 10.02°N, 76.96°E...") without ever
   using a result value. Matching against `result` fields only fixed it:
   **8 of 8 live-reproduced refusals correctly flagged** in the final
   verification run, with zero false positives across every other live run
   in the same session (including partial-success answers that legitimately
   apologise for one missing piece while reporting a real figure for another).
- Shipped in `services/chat/agent.py` (`_false_refusal`, `_allowed_set`, both
  `answer()`/`answer_stream()`), `frontend/src/features/assistant/` (a
  `possible_false_refusal` field through `stream.ts`/`runtime.ts`, and a
  banner in `AssistantThread.tsx`'s `Provenance` reusing `.chat-flag`'s
  styling), and 4 new unit tests in `tests/test_chat.py` (29/29 passing,
  585/585 across the full backend suite).
- **Never made a hard gate**, matching `agent.py`'s own reasoning for why
  `_ungrounded_numbers` only annotates: there is no template to fall back to
  for a whole conversation, so the response states the finding rather than
  discarding or blocking the answer.

### Cyclone and severe-weather alerts, from GDACS and IMD's CAP feed — 2026-08-24

PS2's own example queries name "any lightning or cyclone alerts in my area",
and nothing in the platform answered it — `get_active_alerts` is threshold
rules over SST/wave/bloom fields, and there was no cyclone-track or
lightning source anywhere in the codebase. TODO.md flagged this as the
biggest gap against the problem statement and called for a probe pass before
assuming IMD had a usable feed. It did, plus a genuinely good global fallback
— both found live, both shipped as chat tools.

**IMD's cyclone/weather pages are HTML only, but a real CAP feed was found
embedded in one of them.** `mausam.imd.gov.in/imd_latest/contents/cyclone.php`
links to `https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml` — a public,
anonymous-read S3 bucket (public domain) that is IMD's own NWFC division
feeding a standard OASIS CAP 1.2 alert stream into a third-party aggregator
(`alert-hub.appspot.com`; the bucket hosts many countries' feeds, not just
India's). No key, no auth, real live data — confirmed current as of the probe
date and structurally a proper CAP document per alert (event, severity/
urgency/certainty, onset/expiry, polygon or circle geometry).

**It answers "lightning", not "cyclone" — measured, not assumed.** Sampling
the alerts issued during five major India-landfalling cyclones spanning
2021-2024 (Biparjoy, Michaung, Tauktae, Remal, Dana) found every one of them
recorded in this feed only as `event`="Heavy Rain"/"Heavy rainfall"/
"Extremely heavy" — never as "Cyclone". This is IMD's rainfall/heatwave/
thunderstorm nowcast channel, not RSMC New Delhi's cyclone-track bulletin
(which is PDF-only). It does carry a genuine `event` of "Thunderstorm,
hailstorm, gusty winds and lightning" during pre-monsoon season (confirmed
live, an April 2023 alert) — a real, if indirect, answer to "any lightning
alerts": IMD relays a warning that a strike is likely, it does not report
individual strikes (no such free public source was found for India).

**GDACS closed the cyclone half, and it is a strong source, not a
compromise.** `gdacs.org/gdacsapi` is free, keyless, and aggregates JTWC's
(and other RSMCs') tropical cyclone bulletins into one global GeoJSON feed —
exactly the NOAA/JTWC fallback TODO.md named. Verified against
`country=India` history: it correctly carries Biparjoy-23, Michaung-23,
Remal-24, Dana-24, Fengal-24, Montha-25 and more, each sourced from JTWC, with
real position, intensity, alert level, and (via a second endpoint,
`getgeometry`) uncertainty-cone polygons and per-timestep wind-radii features.
**Its `eventtypes=TC` query parameter does not reliably filter server-side**
— measured, a request with that parameter still returned floods, earthquakes,
droughts, volcanoes and wildfires — so `services/cyclones.py` filters on
`properties.eventtype == "TC"` itself rather than trusting the query string.

**Shipped:**
- `services/cyclones.py` — `get_active_cyclones()` (every GDACS-current TC
  worldwide) and `check_point(lat, lon, radius_km)` (nearest active storm,
  distance, and a coarse "within watch radius" flag against its last reported
  fix — not its forecast cone; see TODO.md for the wind-radii refinement).
  15-minute cache, one GDACS call regardless of how many points are checked.
- `services/severe_weather.py` — parses the CAP 1.2 XML properly (namespace-
  aware, `cap:polygon`/`cap:circle` geometry via shapely, `status`/`msgType`
  filtering that excludes `Test`/`Exercise` and `Cancel` messages, an
  `onset <= now <= expires` activity window). `get_active_alerts()` and
  `check_point(lat, lon)` (point-in-polygon/circle against every alert
  currently valid). 10-minute cache.
- Two new chat tools on the `weather_safety` specialist,
  `get_cyclone_alerts`/`get_severe_weather_alerts` — its system prompt now
  states which tool owns which question explicitly (a cyclone's position or
  category always goes to `get_cyclone_alerts`, even if the question also
  mentions rain or wind), since the two sources' scopes overlap in exactly
  the way a demo question is likely to ask about.
- **No REST router** — deliberately matching `geofencing`/`pfz`/`routing`'s
  existing precedent that a new PS2 capability ships as a chat tool first,
  not a map layer, until there is a reason to add one (see TODO.md).
- 17 new unit tests (both services fully mocked, no network) plus the tool
  count bump (12 -> 14) and specialist-prompt update in the existing chat
  suite; 42/42 passing.

**Verified live end to end, not just unit-tested**: `run_specialist` against
the real configured LLM asked "any active cyclone or lightning/severe-weather
alerts near Chennai" correctly called both new tools with sensible arguments
and produced a grounded, accurate answer (no active North Indian Ocean
cyclone at probe time, nearest storm ~5,900 km away near Japan, no IMD warning
covering the point). One more live run, phrased more casually, surfaced the
grounding checker correctly flagging the model's own "roughly 5,900 km"
paraphrase of the tool's precise 5992.7 — the same documented, intentional
behavior as CLAUDE.md's "a model's own unit conversion is still flagged, and
that is correct" rule. Not a defect in the new tools; the safety net working
as designed on a new data source.

### Multi-agent: prompt tightening and a visible delegation trace — 2026-08-24

Two of the three items TODO.md's "usage surfaced two things worth tightening"
named after the 2026-08-22 Kochi→Kanyakumari run, where the orchestrator's
synthesis added seafloor-depth figures no tool had returned (caught correctly
by grounding, but a flagged answer in front of a demo audience is worse than
one that never needed flagging).

- **`geospatial_risk`'s system prompt now names the failure mode directly**:
  never state a depth figure without calling `get_seafloor_depth`, never state
  a boundary/MPA proximity without calling `check_geofence`, explicitly
  including the case where the number "seems obvious from context" — that
  qualifier exists because the original failure was exactly a plausible-sounding
  generic figure ("generally >200 m"), not an implausible one.
  - **Verified live against the configured provider** (`ollama` /
    `gpt-oss:20b-cloud`), not just by inspection — and the first live run
    caught a real regression the prompt change introduced: asked to plan a
    route *and* describe depth "along the way", the model dutifully called
    `get_seafloor_depth` once per waypoint and burned through
    `SUB_MAX_ITERATIONS` (4) with no turn left to answer, so the specialist
    fell back to its truncated-answer text and the orchestrator improvised an
    apology around it — `grounded: true` (no fabricated numbers) but useless.
    Fixed with two changes together: the prompt now bounds depth checks to
    "two or three calls (start, end, a midpoint)" for a route question, and
    `SUB_MAX_ITERATIONS` went 4 -> 5 for headroom. Re-run afterward:
    `truncated: False`, a real per-waypoint depth table, and land waypoints
    correctly reported as "no depth data" rather than guessed.
  - **One live run out of three still produced a refusal** ("I couldn't pull
    a safe-route plan") despite `plan_safe_route` and `get_seafloor_depth`
    having succeeded and populated the ledger — `grounded` stayed `true`
    because a refusal states no numbers to check, so grounding cannot catch
    this failure mode at all. A repeat of the identical question immediately
    after succeeded normally. This reads as the small provider model
    occasionally discarding a successful tool result during synthesis rather
    than anything the prompt or iteration-budget change touched — pre-existing
    and orthogonal to this fix, not re-created by it. Left open in TODO.md;
    grounding needs a second check for "claims failure when the ledger has
    data" symmetric to its existing "claims a number the ledger doesn't have".
- **The orchestrator's delegation reasoning is now a first-class event, not an
  inference from the tool-call list.** `agent.py::_record_delegation` reads the
  `question` argument already present on every `delegate_to_*` call — the
  orchestrator was always producing this text, it just was not surfaced — and
  emits it as a `delegate` SSE event the moment the call is made, before that
  specialist has run at all. It rides the terminal `meta.delegations` too, for
  a client that only reads the finished reply. `services/chat/orchestrator.py`
  and the specialists' own tool calls are unchanged; this is purely making an
  existing decision visible.
  - **Ahead of, not folded into, the tool-call list.** It answers "why was this
    specialist asked", the tool list answers "what did it do once asked" — the
    two questions the reasoning-trace gap named separately.
  - Not persisted to the chat transcript (`services/chat/store.py` keeps
    `observations`/`sources` only) — same call already made for the delegate
    call itself, which is "orchestration plumbing, not a data observation".
  - `frontend/src/features/assistant/`: a `chat-delegation` line (specialist
    pill + its question, in the same muted style as a live tool call) appears
    in the live thinking indicator ahead of that specialist's own calls, and
    persists in the finished message's provenance block, unconditionally
    visible rather than folded into the collapsed "N data calls" disclosure.
  - `tests/test_chat.py` pins the ordering (`delegate` before that specialist's
    `tool` events, before any `delta`) and the event's exact shape.

The third item — a live browser pass on `/assistant` to eyeball the specialist
pill and the new delegation line — is still owed; see §6, same
`requestAnimationFrame`-never-fires limitation as the map.

### Observability — the request was a bug report

Two logging systems had grown side by side (loguru in 13 modules, stdlib
`logging` in 31) and *nothing in the server process configured either*:

    logging.getLogger("services.forecast_tiles").isEnabledFor(logging.INFO)  -> False
    logging.getLogger().handlers                                             -> []

Every `logger.info(...)` in 31 modules was discarded at source, including most of
the forecasting engine and the whole chat agent. **This codebase's silent
failures need the log to be the mitigation**, since the caches are
fire-and-forget tasks whose exceptions asyncio swallows. If a second logging
library ever appears, it has to route into the configured one rather than sit
beside it.

### Also shipped

| | outcome |
|---|---|
| globe click | Rotates toward a clicked point out near the limb, past a screen-space threshold. |
| field documentation | Two chapters in an "Ocean & atmosphere" docs group. |
| backend strays | `test.py`, `others/`, `dependencies/` gone; runtime state moved to `backend/data/`. |
| README | Rewritten. It described the product as "a single interactive map". |
| branches | 8 remote branches to 1; the prototype preserved as tag `prototype-2026-07`. |
| motion foundation | A motion budget in `styles/tokens.css`, `useReveal` promoted to `hooks/`, applied to the compare page. |

### Motion, applied — 2026-08-17

The three remaining targets, all in CSS. No new JS, no new dependency, and
nothing added to a code path that measures geometry.

- **The dashboard's range-change transitions** and **the metric pages' chart
  swaps** share one class, `.oid-swap-in` — a fade on the arriving state.
  **Opacity only, and that is a constraint rather than a taste**: these panels
  are what `AnalyticsGrid`'s `LazyMount` measures, and they host Recharts, whose
  own entry animation is already disabled here for running before
  `ResponsiveContainer` settled. A transform or height animation moves the thing
  being measured *as it is measured*; opacity changes no geometry. It is a class
  and not a wrapper component for the same reason — the chart region is a
  `flex-1` child whose height feeds `ResponsiveContainer`, and an extra div
  between them collapses the chart.
- **The bigger half of the chart swap was not motion at all.** Changing the
  range on a metric page unmounted a 340px chart and put a ~170px placeholder in
  its place, so the whole page jumped up and back down — under the reader's
  cursor, on a control they are likely to click twice. The loading state now
  reserves the chart's height. Reserved on the *placeholder* rather than floored
  on the panel, because a floor would also pad "no model has been trained" to the
  size of a chart that is never coming.
- **The map's layer picker** animates open with `grid-template-rows: 0fr -> 1fr`,
  the one way to animate to *auto* height in CSS alone. The groups run 8-14 rows,
  so no `max-height` guess is right for all of them. Entry only: animating the
  exit means keeping a zero-height menu in the flex column, which adds a phantom
  8px gap and leaves eight checkboxes in the tab order while invisible — a
  keyboard trap traded for a flourish nobody waits around to see.
- **The parallax was the only expensive thing here, and it was not the one this
  file suspected.** `useReveal` detaches its own listeners the moment it fires,
  so the landing page's eight reveals cost eight one-shot subscriptions.
  `useScrollProgress` stays subscribed for the life of the page and routed a
  per-frame number through React state — reconciling a subtree containing
  `HeroField`'s WebGL canvas once per scroll frame, to move one headline. It now
  takes an `apply` callback and writes to the node inside the same rAF that
  measured it. Same formula, same frames, no re-render. The inline style stays as
  the value at rest, so first paint and reduced motion both land on the neutral
  transform without waiting for a frame.

**Verified headlessly, because these are mechanism questions with numeric
answers.** Chrome over CDP against a harness of the two mechanisms, sampling
computed style every 45ms:

| | t=0 | 45ms | 90ms | 135ms | 180ms |
|---|---|---|---|---|---|
| disclosure height | 16px | 179px | 211px | 216px | 217px |
| swap opacity | 0 | 0.83 | 0.97 | 0.998 | 1 |

The content below the menu tracked it (45px -> 246px), i.e. it is pushed rather
than overlapped. Under emulated `prefers-reduced-motion: reduce` both land on the
finished state within 30ms — full height, opacity 1 — and **the same probe with
the reduced-motion blocks removed showed mid-animation values**, so that rule is
doing work rather than being decorative.

What is *not* verified is how any of it feels in the real app: agent-driven
Chrome tabs never fire `requestAnimationFrame` (§6), so this checks the
mechanisms, not the product.

### The `<!doctype` bug — every JSON API client, 2026-08-17

Activating the eddy, marine-heatwave or upwelling layer failed with
`Unexpected token '<', "<!doctype "... is not valid JSON`.

**Twenty-odd API clients opened with `const API_BASE_URL =
import.meta.env.VITE_API_BASE_URL;` and that line is a bug without a fallback.**
Vite only defines a `VITE_*` variable when an `.env` declares it; there is no
committed `.env` in `frontend/` (the dev server proxies `/api` to :8000
instead), so the value is `undefined` and every template literal built from it
produced `"undefined/api/ocean/eddies"` — a *relative* path. The dev server
answers any unmatched path with `index.html`, so the fetch came back **200 OK
with an HTML body**, sailed past the `response.ok` check every client performs,
and died in `.json()` with a message naming neither the URL nor the variable.

- **Three of the clients had independently grown `|| window.location.origin`**,
  which is exactly why the symptom looked so selective: the raster and tile
  layers worked, and only the JSON-fetching detector layers failed.
  `forecastLayers.ts` even carried a written-up diagnosis of the tile half of
  this — a full dropdown of silently blank layers — without the fix reaching the
  other seventeen files.
- Now one guarded constant in `utils/apiBase.ts`. Same-origin is the right
  default rather than merely a safe one: in development it hands the path to
  Vite's proxy, and in a normal deployment the API is same-origin.
- **`fetchJson` there also checks the content type**, so this class of failure
  can never again surface as a parse error: a 200 that is not JSON now throws a
  message naming the URL and saying the request never reached the API. The two
  detector clients use it.
- Verified end to end against a running backend: the old shape returns
  `200 text/html`, the fixed shape returns `application/json`, and in a real
  browser the three layers now show data or an honest `503` chip with **zero
  JSON-parse errors**.

**`npx tsc --noEmit` checks nothing in this repo.** `tsconfig.json` is a
solution file with `"files": []` and two references, so `--noEmit` compiles an
empty project and exits 0 — it reported success on a file with an undefined
identifier. Use `npx tsc -b` (what `npm run build` runs), which caught it.

### Scroll-driven CSS, and the cards as 3D objects — 2026-08-17

The hero parallax now runs on `animation-timeline: view()`, and the four
platform cards' glyphs are 3D objects that turn as they cross the viewport.

- **`overflow: hidden` silently kills a view timeline, and this cost two
  debugging rounds.** `hidden` computes the other axis to `auto`, which makes
  the element a **scroll container** — and `view()` resolves against the
  subject's nearest scrollport, not the viewport. Three ancestors were doing it
  (`.lp-root` for the marquee, `.lp-hero`, and `.lp-surface` for its pointer
  wash), so the animations existed, reported themselves as running, held a real
  `ViewTimeline`, and sat frozen at progress 0. **`overflow: clip` clips
  identically and creates no scrollport.**
- **The screenshots lied and the numbers did not.** The 3D cards looked correct
  in a still at any scroll position — they were angled, the plates receded —
  because the *static* pose is also 3D. Only sampling the computed matrix across
  five scroll positions showed it byte-identical each time. A still of a
  scroll-driven animation cannot tell you it is animating.
- **The glyphs are HTML boxes, not SVG internals.** `transform-style:
  preserve-3d` is flattened inside an `<svg>`, so separating the existing line
  art's own paths in depth is not available however natural it looks. Two plate
  elements sit behind each glyph in Z instead.
- **Hover is on the face, not the stage.** A running animation beats a
  transition for the same property, so a hover pose written on the animated
  element is simply never seen. The face is a child, so its lift composes with
  whatever the stage is doing.
- Measured after the fix: the stage matrix passes through near-identity as the
  card centres and rotates oppositely either side; the plates' `translateZ`
  spreads −33 → −41 and back. Under emulated reduced motion both elements report
  **zero animations** and hold the static angled pose, with the hero at opacity 1
  at every scroll position.
- The JS path remains for browsers without view timelines, and is *disabled*
  rather than merely overridden where the CSS is in charge — the cascade would
  win anyway, but the listeners would still measure every frame to write a value
  nothing paints.

### Regrouping `services/` — deliberately not done

Measured before deciding: the 31 flat modules are referenced from **222 import
sites**, several as grouped `from services import (a, b, c)` blocks. The taxonomy
is genuinely arguable (`forecast_tiles` is as much delivery as derived field) and
CLAUDE.md documents the flat layout as the convention. A large, history-obscuring
rename imposing a debatable grouping over a documented one is a bad trade. If
ever taken up: one mechanical commit, no behaviour change, prose in the same
commit, and settle the taxonomy first.

Likewise **`models/` was not renamed** despite colliding with `app/models/`; the
README's structure listing disambiguates them, which buys most of the clarity for
none of the risk.

### The botocore connection pool — 2026-08-17

copernicusmarine builds its S3 client without `max_pool_connections`, so it
falls back to botocore's default of 10 while the zarr read fans out wider —
producing "Connection pool is full, discarding connection" once or twice a second
for every fetch. Nothing is lost; the cost is a fresh TLS handshake per discarded
connection. There is no upstream setting, so the lever is botocore's mutable
`Config.OPTION_DEFAULTS`. Raising the `urllib3` log threshold was rejected: it
hides every urllib3 warning, including the ones worth reading when CloudFerro
flaps, and leaves the handshakes in place.

---

## Hazards that will bite the next person

- **Partial success is the more dangerous failure mode.** Training the full
  variable set in one day exceeds Open-Meteo's free quota. When it blew,
  `sea_level_anomaly` failed *loudly* (hard error, nothing written) while
  `rainfall` **degraded silently** — 10 of 24 points survived, every one
  northern-hemisphere, a different subset per horizon. A global model carrying
  lat/lon and no southern data extrapolates across the equator on the one
  variable whose seasonality inverts. **Check `skipped_points` before shipping,
  not just the metrics.** It fired again on `wind_v` h1 (21 of 24 points) and the
  run printed `beats persistence` regardless.
- **Widening what the model is shown widens what it is allowed to say.**
  `agent._ungrounded_numbers` permits every figure the model was shown, including
  the system prompt. Adding the dataset catalog made
  `GLOBAL_ANALYSISFORECAST_BGC_001_028` parse as 1 and 28, so a fabricated
  "28.4 °C" traced back to a product code and passed — a safety check that failed
  by going quiet. **Check the negative case after adding prompt context.**
- **ERDDAP hosts flap, and a 404 is not proof of permanence.** ERDDAP answers
  404 "Currently unknown datasetID" while reloading a dataset, indistinguishably
  from a removed one. **Do not "fix" `services/crw.py`'s `NOAA_DHW` id**;
  switching to a `_Lon0360` dataset would silently change the longitude
  convention while the query kept working. Note the retry policy legitimately
  differs by caller: one retry on the request path (where three cost ~8 s per
  forecast), unlimited-within-budget in an offline batch job where waiting is
  free.
- **Git LFS: a slow push may be a rejected one.** GitHub answered `GH008 —
  unknown LFS objects` (`pre-receive hook declined`) after the pre-push hook
  failed to register them. The symptom looks like a slow upload. `git lfs push
  --all origin main` uploads them, after which the ref push succeeds.

---

## Considered and rejected, with the reason

Recorded so these are not re-proposed.

- **A Fishing Opportunity Index.** Composite indices with hand-chosen weights
  have nothing to validate against — the habitat model has a holdout TSS of
  0.792, an FOI has no ground truth at all. Folding in GFW vessel activity also
  makes it circular ("fish are where the boats are"). **Ship the components side
  by side.**
- **Maritime route optimisation.** A different product, and a liability surface
  far past a dashboard if anyone navigates by it. The honest 10% version is
  *conditions along a route the user supplies*.
- **Scenario simulator ("what if SST +2 °C?").** Asks a LightGBM model fitted on
  observed covariance about a joint state it has never seen; it will answer
  confidently and meaninglessly. SHAP already provides the defensible version.
- **"Ocean digital twin."** A renaming of what the platform already is.
- **An ocean time machine scrubbing 2000–2026.** Cost mis-stated as a slider: a
  scrubbable multi-decade global map is a precomputed tile archive, not a UI
  control. The affordable version is coarse monthly means for a few variables.
- **"Open marine data API."** The API already exists; what is proposed is
  documentation, versioning and a stability contract — worth doing when there is
  an actual external consumer, since a public contract is a promise not to change
  things.
- **"RAG over ocean data."** A category mismatch: RAG retrieves from unstructured
  text; this platform's data is numeric grids. You do not retrieve SST, you query
  it. The catalog version shipped as prompt-stuffing. *Scientific literature on
  HABs is the one legitimate RAG target left*, as its own project.
- **A database for caching.** Every in-process cache is already bounded; the
  on-disk fetch cache is 4.6 MB. Memory was concentrated in a few global float64
  arrays and addressed directly (SST cache ~140 MB → ~35 MB). Redis/Mongo would
  relocate those bytes while adding a resident copy plus serialization on the hot
  path.
- **A database for the ML feature store.** Parquet is correct for wide float
  matrices: 3.9M rows × 151 columns at 1.59 GB, and a 20-column read costs 0.1 s
  against 3.5 s for the full table. If it outgrows one machine, DuckDB reads
  these same files in place.
- **3D terrain on the map.** Built and removed. MapLibre drapes raster overlays
  onto the terrain mesh, and on a bathymetric DEM that mesh is the *seafloor*, so
  SST ended up ~16 km below the camera. Sea-surface data and raised seafloor
  geometry are mutually exclusive by construction.
