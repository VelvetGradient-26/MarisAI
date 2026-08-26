# Publishable research topics in MarisAI

A catalogue of papers this codebase can support, written 2026-08-15 and revised
2026-08-17. Each entry states the **claim**, the **evidence that already exists
in this repository**, **what is still missing** before it can be written, and a
plausible **venue**.

Entries move between tiers as work lands, and three did on 2026-08-17: the
percentile climatology and the upwelling detector were built (Tier 3 → 1.10,
1.11), and one of them returned a **negative** result strong enough to be its own
paper (1.12). A catalogue whose tiers are not maintained is a wish list.

The organising principle is honesty about distance: Tier 1 topics are results
already sitting in `machine_learning/reports/`, `research/data/results/` or a
CLAUDE.md paragraph, needing only writing; Tier 2 needs one bounded experiment;
Tier 3 needs a build. Nothing here is a topic the platform could *conceivably*
address — only ones where this repo holds an artefact no one else has.

Shipped already: **"Rising Skill, Falling Skill"** (`papers/`, `README.md`) —
persistence is an insufficient baseline for statistical ocean forecasting. Every
topic below is checked against it for overlap; where a topic is a natural
follow-on, that is said.

---

## Tier 1 — the experiment is done; the paper is not

### 1.1 Ensemble weighting by softmax over CV skill, not proportion

**Claim.** Proportional weighting of ensemble members by a skill score whose
chance level is zero (TSS, Kappa, Cohen's d) compresses a large quality gap into
a small weight gap, and can produce an ensemble that scores **below its own best
member**. A softmax over the same scores fixes it, at a stated cost in spatial
calibration.

**Evidence in repo.** `machine_learning/reports/fish_habitat_summary.json`:
MaxEnt CV TSS 0.619 against LightGBM's 0.826 — less than half as good on the
holdout — still drew 27% of the vote under proportional weighting. The
proportional ensemble scored 0.694 holdout against its best member's 0.788.
Softmax at temperature 0.05 gives 0.792, above every member; Boyce index falls
0.936 → 0.905, so the trade is real and measurable in both directions. Both
weighting modes are retained in code, so the baseline reproduces exactly.

**Missing.** A temperature sweep (currently one point, 0.05) and a second
problem to show it is not habitat-specific — HAB early warning has three
horizons with member scores already logged in MLflow. Ideally one non-marine
public benchmark so the claim is about ensembling, not about tuna.

**Why it is publishable.** Species distribution modelling papers routinely
weight ensembles by AUC or TSS proportionally; this is a concrete demonstration
that the convention is unsound whenever the metric's floor is 0 and the spread
is wide. Small, self-contained, immediately actionable.

**Venue.** *Ecological Modelling*, *Methods in Ecology and Evolution*, or
*Diversity and Distributions* (short methods note).

---

### 1.2 What going global actually buys a species distribution model

**Claim.** Expanding a regional habitat model to the global ocean multiplies
labels ~170× but does not extend the usable time window by a single year, and
buys nothing at all for the locally important species — the exact opposite of
the intuition that motivates going global.

**Evidence in repo.** Verified against OBIS 2026-08-10 and recorded in
`marine_ml/config.py` + CLAUDE.md. Yellowfin worldwide: 67,780 records 2000–2013
vs **772** after 2013; bigeye 29,982 vs **59**. The post-2014 target-species
drought is global, not an artefact of the `NORTH_INDIAN_OCEAN` box. Inside the
window, global gives ~117,000 records against ~800 regional. And oil sardine has
**112 records worldwide, all of them already inside the regional box**; Indian
mackerel 243. Model side: regional CV TSS 0.826 (LightGBM) vs global 0.901, with
completely different SHAP orderings — regional leads on `depth` and
`distance_to_coast`, global on dissolved oxygen and 60-day lagged temperature.

**The headline number now exists, and it is the opposite of the intuition.**
Measured 2026-08-15 by `scripts/validate_global_on_region.py`, written to
`reports/global_vs_regional_habitat.csv`: on **identical rows** (the regional
holdout, 885 rows / 167 presences), the regional ensemble scores **TSS 0.798 /
Boyce 0.923** against the global ensemble's **0.448 / 0.721** — while the global
model trained on **123,104 rows against 1,902**, i.e. 64.7× the data for less
than half the skill on the water that matters. The comparison is only valid
because the shipped global model had trained on this water, so it is refitted
with the regional holdout's spatial *blocks* removed — blocks, not rows, since a
global point 50 km away is the same water.

**And the obvious explanation is ruled out by the same file.** "The global model
is extrapolating" is the natural defence; the MESS columns say it is not. The
global model extrapolates *less* — 1.24% of holdout rows outside its training
envelope against the regional model's 9.04%, median similarity 0.205 vs 0.442.
It has seen more of the environmental space and still performs worse on it,
which points at label dilution and at the loss of the coastal-geometry features
the regional model leads on, not at coverage.

**Missing.** Nothing blocking. A second region would turn one instance into a
claim about scale.

**Why it is publishable.** "More data is better" is unexamined in SDM practice.
This is a controlled instance where scale changes the learned mechanism (coastal
geometry → water-mass chemistry) while the label window is fixed by the same
archival drought at every scale.

**Venue.** *Diversity and Distributions*, *Fish and Fisheries*, *ICES Journal of
Marine Science*.

---

### 1.3 Target-group background sampling cannot be enumerated globally

**Claim.** The standard target-group-background recipe for pseudo-absences
assumes you can enumerate the target group. At global scale you cannot — OBIS
returns 21.8 million records for the group — and every obvious workaround
(page cap, truncation) produces a *spatially ordered* prefix, which is the worst
possible failure for a pool whose entire purpose is representing survey effort.
The fix is effort-proportional cell sampling without replacement.

**Evidence in repo.** `marine_ml/sources/obis.py` raises rather than truncating;
`sample_target_group` draws from `/occurrence/grid/{precision}` (~7,700 cells,
1.4 MB, one call), without replacement with probability ∝ effort, equal quota per
cell. The largest single cell holds **2.15M records, ~10% of the planet's
total** — which is why with-replacement sampling collapses. The design is forced
by `labels.build_background` thinning to one point per (0.25° cell, month) slot.
Regional comparison: 10,051 records over `NORTH_INDIAN_OCEAN`, so the regional
path never hits this and no existing paper would have noticed.

**Missing.** A measured comparison of the resulting model against (a) naive
truncation and (b) uniform random background, on the same labels. That is a
three-run experiment on an existing pipeline.

**Venue.** *Methods in Ecology and Evolution*, *Ecography*.

---

### 1.4 Silent aggregation error when merging multi-cadence ocean products

**Claim.** Joining environmental products of differing native cadence before
temporal aggregation silently substitutes an **instantaneous sample** for a
period mean, with no NaN, no exception and no warning — and the error is
systematically signed, not noise.

**Evidence in repo.** `services/download/cleaning.py`'s `build_dataframe`
ordering (resolve codes → aggregate → `xr.merge(join="inner")`), and the
measurement behind it: on a synthetic 3 °C diurnal cycle the old path reported
**23.0 where the daily mean is 20.0** — wrong by the full amplitude, in every
row, always the same direction. Scope of the real impact is quantified:
**13 of 32 configured forecasting variables were feeding at least one covariate
to training this way** — every wave variable (3-hourly target, hourly wind),
every biogeochemistry variable (daily target, hourly SST), all three
depth-resolved ones. The companion finding is that resolution must precede
aggregation because derivations are non-linear: `current_speed = hypot(u, v)`,
and a current rotating through the day at constant 1 m/s averages to ~0
components and reports as slack water.

**Missing.** The retrain of those 13 variables so that before/after skill
numbers exist. (This is no longer scoped anywhere in TODO.md — the cadence bug
was fixed and the affected variables were left to be retrained on their next
touch, so the before/after comparison this paper wants has to be run
deliberately.) Without it the paper says "this is wrong"; with it, it says
"and it cost this much skill."

**Why it is publishable.** This is a data-engineering hazard that every
multi-source marine ML pipeline has and nobody reports. It is also a rare case
where the affected fraction of a real, running system is countable.

**Venue.** *Environmental Modelling & Software*, *Computers & Geosciences*, or
a workshop on ML data quality (e.g. NeurIPS Datasets & Benchmarks track).

---

### 1.5 Circular variables break at four independent layers, and three of the
fixes are not enough

**Claim.** A directional variable (wind, wave, current bearing) must be handled
circularly at *every* stage — target construction, interpolation, difference,
colour ramp — and fixing three of four leaves a system that looks correct and
is not.

**Evidence in repo.** All four failures are documented with their symptoms.
(i) Resampling: linear interpolation of 359° and 1° gives 180°, the exact
reverse; fixed by sin/cos + `atan2` in `services/field_sampling.py`.
(ii) Difference: naive forecast-minus-anchor needs a signed veer wrapped to
[−180, 180). (iii) Legend: percentiles computed round a circle produced a
shipped grid with `display_max: 400`; a cyclic ramp whose first and last stop
match by construction fixes it. (iv) **Still open, and it is the modelling
half**: with `target_mode: delta`, a 5° veer across north trains as −355. The
particle layers were never affected because they carry `u`/`v` components,
which is precisely the recommended answer. There is also a clean negative
result: forecast wind particles are impossible from `wind_speed` +
`wind_direction` for exactly this reason, which is why `wind_u`/`wind_v` were
trained as variables of their own (2026-08-15).

**Missing.** The component-forecast retrain for `wave_direction` and
`current_direction`, and a paired evaluation against the angle-regressed models
— i.e. how much skill the linear treatment actually costs.

**Venue.** *Environmental Modelling & Software*, *Weather and Forecasting*
(short note), or *Journal of Atmospheric and Oceanic Technology*.

---

### 1.6 Delta targets are what make gradient-boosted trees viable on
autocorrelated ocean series

**Claim.** A tree ensemble cannot represent the identity function, so on
strongly autocorrelated series a level-fitted model loses to persistence *at
every horizon including h=1*. Regressing the change makes persistence the
constant zero, which a tree represents exactly.

**Evidence in repo.** Same data, same features, same folds: skill **−0.12 level
vs +0.20 delta** (`forecasting/README.md`, CLAUDE.md). The `skill_score` metric
and the `WORSE THAN PERSISTENCE` training banner exist specifically so this
class of failure cannot ship silently. `decode_prediction` treats a missing
anchor as a hard error rather than a guess. Notebook `02_feature_engineering`
already contains the delta-vs-level comparison figure.

**Overlap warning.** This is adjacent to the shipped paper and is arguably one
of its sections rather than its own paper. Publish separately only if paired
with 1.7 below into a "what a tree can and cannot represent in forecasting"
methods piece.

**Venue.** Combined with 1.7: *Machine Learning* (applied track), *Applied
Soft Computing*, or an ECML/PKDD applied-track paper.

---

### 1.7 Hampel outlier filtering inverts on smooth geophysical fields

**Claim.** Local-scale outlier filters assume the local scale is meaningful.
On a smooth field it is not — the local MAD collapses to zero *because* the
field is smooth — and the filter then flags clean data at a high, stable rate
across every parameter setting.

**Evidence in repo.** Measured on a clean Copernicus SST series: Hampel flagged
**5–12% of values at every window/threshold tried**, and **74 of 365 values had
a local MAD of exactly zero**. Disabling it raised 7-day skill from **+0.138 to
+0.202**. The filters remain one config line away for genuinely noisy
observational sources, so the paper's recommendation is conditional rather than
absolute.

**Missing.** Repetition across more than one variable — currently the
measurement is SST. Wave height and chlorophyll (much noisier) would give the
contrast that makes the conditional claim, and both are in the history cache.

**Venue.** As above, or *Journal of Atmospheric and Oceanic Technology*.

---

### 1.8 Detecting eddies without tracking them, and why the count is not a census

**Claim.** An Okubo–Weiss detector with a variance-relative threshold is a
*consistent detector under a changing mask*, not a measurement of how many
eddies exist — and a system that reports the count without saying so is
reporting an artefact of its own coverage.

**Evidence in repo.** `services/eddies.py`, shipped 2026-08-15. Measured on the
live field: **2,097 features globally**, densest exactly where they should be
(Gulf Stream, Kuroshio 35N/155E, Agulhas, Somali Great Whirl 11.8N/47.8E),
median radius ~55 km, whole global pass **0.1 s** over a resident cache. Four
findings worth a methods section:
- **Polarity is `sign(ζ) == sign(latitude)`**, not `sign(ζ)`. A detector reading
  the vorticity sign alone is right in one hemisphere and confidently wrong in
  the other; the ±5° band is excluded because *f* vanishes there.
- **The antimeridian fails in three separate places** — periodic derivatives,
  `ndimage.label` component union, and the centroid, where the arithmetic mean
  of +179 and −179 is 0 and relocates a Pacific eddy to the Gulf of Guinea.
- **On white noise the detector still returns features** (a relative threshold
  always has cells below it) but every one comes back at the 40 km floor. A
  *large* detection is evidence of structure; a small one may not be. A test
  pins the asymmetry.
- **The per-component loop is the entire cost**: `np.nonzero(labels == index)`
  per feature is 37 s at global scale; sort-once-and-slice is 0.1 s, bit-identical.

**Missing.** Validation against a published eddy atlas (AVISO/META3.2), and the
closed-SSH-contour cross-check. Both are essential — without an external
reference this is an engineering note, with it, it is a paper.

**Venue.** *Ocean Modelling*, *Remote Sensing of Environment*, or *Journal of
Atmospheric and Oceanic Technology*.

---

### 1.9 A NaN-holed grid cannot be bilinearly resampled, and the coastline is
where it matters

**Claim.** Bilinear interpolation over a field with a land mask is *poisoned* by
the mask — any pixel with one NaN neighbour returns NaN — so the painted ocean
retreats a full cell from every coast, and the retreat lands exactly on the
coastal band that carries the signal.

**Evidence in repo.** `services/field_sampling.py`. Quantified: ~110 km of
axis-aligned staircase at 1°, and **3,609 of chlorophyll's 42,499 ocean cells
(8.5%) erased** — the coastal band the layer is most about. The fix separates
values (nearest-filled, so coastal cells stay finite) from a 0/1 coverage field
thresholded at 0.5 after interpolation, so the edge follows the bilinear 0.5
contour. Ocean cell centres still sample to their own value at 0.0 error.
Alpha-feathering was tried and rejected on a measured basis (over a near-black
basemap a soft edge reads as haze, not land). Adjacent measured result: **no
ramp end clears 2:1 contrast against the `#030f1e` basemap even at opacity
1.0** — darkest steps measured 1.13–1.27:1 — so the "unforecastable water"
discriminator had to move from colour to texture.

**Venue.** *Computers & Geosciences*, *Transactions in GIS*, or an IEEE VIS
short paper for the contrast half.

---

### 1.10 A percentile climatology, and the reanalysis that cannot supply one

**Claim.** Percentile-baseline anomaly detection across many variables is
blocked on one artefact nobody costs — a per-cell, per-day-of-year percentile
stack — and **the obvious source for it cannot provide it at all**. The
high-resolution ocean reanalyses everyone reaches for begin far too recently for
a 30-year baseline, so the baseline has to come from a coarse, old, unglamorous
satellite analysis instead.

**Evidence in repo.** Built 2026-08-17: `services/climatology/`, 1991–2020, 1°,
271 MB, fetched in ~25 min and fitted in 761 s. The cost model in the *previous
revision of this file was wrong in the interesting direction* — it assumed the
expensive global Copernicus fetch path. Every Copernicus provider here starts
recently (physics 2022-06-01, waves 2022-11-01, wind 2024-06-13, BGC
2021-11-01), so a 30-year baseline is not expensive there, it **does not
exist**. NOAA OISST v2.1 on the ERDDAP host `crw.py` already used gives daily
0.25° from 1981; one year strided to 1° is 94.6 MB in 51 s.

Three findings came from getting the build wrong first, and all three generalise
to any long-record fetch: a **5-day probe predicted ~11 min/year against an
actual ~50 s** (13× off — per-request overhead dominates a small griddap
request); a **2 s/4 s retry backoff lost a run in six seconds** to a host that
flaps on the ~100 s scale, converting a recoverable outage into a failed job
while adding load; and **short years are the archive, not a truncated
response** — 1993 returns 163 days, re-fetches identically, and the dataset
itself reports ~1,200 days genuinely absent, so a per-*year* completeness check
would reject a real baseline forever. What protects a percentile is a floor on
samples per *estimate*; the shipped fit is 89.3% complete.

Verified against the raw record rather than trusted: a hand-computed p90 at
20.1°N 65.1°E day 200 over 290 pooled samples reproduces the stored value
exactly. And **`p90 >= mean` is false** on 1,940 of 15,761,058 finite cells —
median violation 5e-06 °C (float32 rounding), the largest on the Antarctic ice
margin where a sample pinned at the freezing point with warm excursions is
right-skewed enough to put the mean above the 90th percentile. `p10 <= p90`
holds and is the ordering worth testing.

**Missing.** Nothing for the methods note. The application paper — a
Hobday-compliant marine-heatwave climatology for the Indian Ocean — needs the
detector run over a season and written up; `services/heatwaves.py` ships and
reports 9,003 of 31,830 ocean cells (60°S–60°N) in heatwave on 2026-08-01, with
the five-day clause removing 6.7 points against a same-day threshold test.

**Venue.** *Environmental Modelling & Software* or SoftwareX (the
infrastructure); *Progress in Oceanography*, *Frontiers in Marine Science* (the
MHW application).

---

### 1.11 A detector's corroboration needs a control arm

**Claim.** When a wind-derived index is corroborated against an independent
observation, the corroborated fraction on its own is uninterpretable and reads
as confirmation. Reported against a **control arm where the corroborating signal
is not expected**, the same number can show the agreement is barely better than
chance — and in the case measured here, it does.

**Evidence in repo.** `services/upwelling.py` ships Bakun's index (Ekman
transport from bulk wind stress, projected onto a coastal normal derived from
the model land mask) and, since 2026-08-17, corroborates it against a cold SST
anomaly scored on the 1.10 climatology. Measured live on the global field:
**19.9%** of upwelling-favourable coastal cells were cool for the season —
against **17.2% of downwelling-favourable ones**, where cool water is not
expected at all. The strong tier is indistinguishable (4.1% vs 3.9% below the
seasonal 10th percentile) and favourable coasts are on average the *warmer* of
the two (+0.91 °C vs +0.60 °C). So a corroborated cell is a real observation of
cool water and a weak coincidence, not evidence that this wind drove it.

`control_cool_fraction` is therefore computed and returned with **every**
response and rendered beside the count in the UI, on the same rule this
codebase already applies to HAB precision: a level is not a finding without its
base rate.

Two constructions make the detector itself worth describing. The coastal normal
is derived from the ocean mask the currents field already carries, because no
service here supplies coastline geometry — and the mask cannot come from the
*wind* field, which is defined over land, so its coverage edge is not a coast.
And the hemisphere asymmetry falls out of the sign of the Coriolis parameter
rather than a latitude branch; a test fixture that put land to the west and
called it an eastern boundary caught the one error that would have reported
every upwelling coast as downwelling, in an entirely plausible field.

**Missing.** The honest experiment this points at: upwelling responds to wind
integrated over days, and both arms here are snapshots. A short rolling wind
history would let the index be computed on a multi-day mean and the control
re-run — that is the difference between "these two snapshots barely agree" and
"the wind does not drive the SST response at this resolution".

**Why it is publishable.** Detector papers overwhelmingly report the agreement
rate and stop. The contribution is the discipline: the control arm is cheap,
it is computed from data already in hand, and here it converts a
confident-sounding 20% into a 2.7-point lift. Negative, small, and immediately
transferable.

**Venue.** *Journal of Atmospheric and Oceanic Technology*, *Remote Sensing of
Environment* (methods), *Continental Shelf Research*.

---

### 1.12 A baseline fitted on one product cannot score another

**Claim.** Anomaly detection routinely scores an observation against a
climatology fitted on a *different* product, because the long record and the
fresh observation rarely come from the same source. The substitution is treated
as free. It is not: it injects per-cell noise wider than the decision threshold,
it concentrates on exactly the water such studies care about, and it **inverts a
tail-based test while leaving a mean-based one apparently unharmed** — which is
the failure mode most likely to be shipped.

**Evidence in repo.** Measured 2026-08-17 while trying to fix 1.11's weak
agreement by replacing the 14.5-day-old OISST record with the live hourly
Copernicus physics field. Both arms over an identical wind field, contrast =
favourable minus control: the weak tier was unchanged (+0.022 against +0.026)
and the strong tier **inverted, to −0.149** — downwelling-favourable coasts came
out below their seasonal 10th percentile three times as often as favourable
ones.

The cause is measured separately, a full day of hourly physics daily-averaged
onto the OISST grid: **no systematic offset** (mean +0.005 °C over 60°S–60°N,
medians ~0, so a bias constant would be a fudge with nothing to fix), but
per-cell disagreement of **sd 0.467 °C in open water and 0.758 °C across the
coastal band**, where 24.9% of cells differ by more than 0.5 °C and 10.0% by
more than 1.0 °C. The threshold being fed was 0.5 °C. A below-percentile test is
a *tail* test and cannot survive noise the width of its own signal; a
mean-offset test degrades gracefully and hides it.

**Missing.** The general form: repeat across two or three product pairs and both
tiers, to state the rule as "the substitution is safe up to threshold ≈ k × the
inter-product sd" rather than as one instance. Every input is public.

**Why it is publishable.** The practice is near-universal in operational anomaly
products and the check is almost never reported. It also carries a concrete
piece of advice — fit the baseline on the product you will score, or quote the
inter-product spread beside the threshold — and a diagnostic that costs one
day of overlapping data.

**Venue.** *Journal of Atmospheric and Oceanic Technology*, *Remote Sensing of
Environment*, *Earth System Science Data*.

---

### 1.13 Bloom-warning precision is set by regional base rate, not by skill

**Claim.** Harmful-algal-bloom early-warning systems are compared across regions
by precision at a fixed recall, and that comparison is close to meaningless:
across five regions the operating-point precision tracks the regional bloom
**base rate** almost monotonically. Two regions at the same prevalence can
differ threefold in skill over persistence while reporting nearly identical
precision, so precision ranks the water, not the model.

**Evidence in repo.** Five regions trained, thresholds and climatology fitted
**per region** because they define what counts as a bloom — one region's
distribution must not set another's labels. Operating points at target recall
0.8, from `reports/hab_early_warning_*_summary.json`:

| region | base rate | t+3 | t+5 | t+7 |
| --- | --- | --- | --- | --- |
| california_current | 0.266 | 0.950 | 0.904 | **0.844** |
| benguela | 0.154 | 0.806 | 0.659 | 0.566 |
| baltic_sea | 0.139 | 0.699 | 0.521 | 0.416 |
| bay_of_bengal | 0.078 | 0.461 | 0.272 | 0.187 |
| arabian_sea | 0.076 | 0.449 | 0.280 | 0.202 |

Precision is ordered exactly by base rate at all three horizons, with no
crossings. **The Bay of Bengal is what makes this a claim rather than an
observation**: it sits at the Arabian Sea's prevalence (0.078 vs 0.076) and
reports the same precision — yet carries roughly **three times the lift over
persistence at t+7** (+0.150 against +0.053). Same apparent performance, very
different models.

**Why it is publishable.** The literature quotes precision and false-alarm rate
per system, and systems are built in regions of wildly different prevalence.
This is a controlled demonstration — one pipeline, one label definition, one
validation discipline, five basins — that the headline number is dominated by
the basin. The honest reporting recipe follows directly: quote precision
*because a user experiences it*, and lift over persistence *because a modeller
has to judge it*, and never rank regions on the former.

**Missing.** Nothing blocking. The Arabian Sea's "screening only past +3 d"
caveat is a regional statement and should be labelled as one, not as a property
of HAB forecasting.

**Venue.** *Harmful Algae*, *Remote Sensing of Environment*, *Ecological
Informatics*.

---

## Tier 2 — one bounded experiment away

**2.3 is missing from this tier because it was run.** It is now 1.13; the number
is left as a gap for the reason given under Tier 3.


### 2.1 The union of OBIS and GBIF runs in both directions

**Claim.** GBIF is not a superset of OBIS for marine fish, so combining them is
a genuine union requiring deduplication — and which source dominates *reverses*
between oceanic and coastal species, so dropping either guts a different half of
the model.

**Evidence in repo.** Measured 2026-08-05, in CLAUDE.md. *Thunnus albacares*
globally: OBIS 246,964 vs GBIF 174,799 with coordinates. Inside
`NORTH_INDIAN_OCEAN`, 2000–2013: yellowfin 394 OBIS / **1,228** GBIF, skipjack
280 / **1,622**, bigeye 283 / **678** — but Indian mackerel **67** / 9 and oil
sardine **112** / 9. The two species that matter most for Indian coastal
fisheries are ~10× better served by OBIS. GBIF adds essentially nothing
post-2014 (bigeye: 4 records either way), confirming the archival drought is not
an OBIS artefact. Dedup must be on `occurrenceID` falling back to
(dataset, catalogNumber, lat, lon, date), because a large share of GBIF's marine
records are republished OBIS datasets — merging naively double-counts *exactly
where the pseudo-absence scheme is most sensitive to sampling effort*.

**Experiment needed.** Wire the GBIF source, run the dedup, retrain, report
per-species skill deltas. TODO §4 (Machine learning) already scopes it.

**Venue.** *Ecological Informatics*, *Biodiversity Data Journal*, *Scientific
Data*.

---

### 2.2 True absences versus target-group pseudo-absences, measured

**Claim.** Every quantification of pseudo-absence error to date has been against
synthetic data, because presence-only and presence-absence sources rarely cover
the same water. ICES DATRAS (trawl surveys with real zero-catch hauls) and RLS
(standardised reef transects with abundance and real zeros) are the two sources
that permit a direct measurement.

**Evidence in repo.** Both surveyed and probed live 2026-08-05 (CLAUDE.md,
Tier 1/2 tables) — DATRAS `getSurveyList` verified 200, SOAP/XML, North Atlantic
and European only; RLS reachable but CSV-download-only. The full target-group
pipeline, the background thinning scheme and the validation harness (spatial
block CV) already exist and are region-agnostic.

**Experiment needed.** Move the model region to DATRAS coverage, train the same
architecture twice — once on true absences, once on target-group
pseudo-absences drawn from the same water — and compare. TODO §6 (Parked) calls this
"the biggest accuracy lever, and a strategic call."

**Why it is publishable.** It is the control experiment the SDM pseudo-absence
literature is structurally missing. It also costs the project its Indian-Ocean
focus, which is the strategic call — worth stating in the paper as a limitation
of where true absences exist at all.

**Venue.** *Ecography*, *Methods in Ecology and Evolution*, *ICES Journal of
Marine Science*.

---

### 2.4 Softmax-weighted stacking versus weighted averaging for SDM ensembles

Natural companion to 1.1: TODO records that **stacking was never attempted** for
the fish-habitat ensemble. Three members with logged CV scores and a spatial
block CV harness are already in place, so a stacked meta-learner is a bounded
addition. Only worth a separate paper if stacking loses — a negative result on
spatially blocked data (meta-learner overfits the block structure) would be more
interesting than a win.

---

### 2.5 Memory-equivalent batched sampling of a global 4-D feature store

**Claim.** Batching a spatiotemporal point-sampling job by year is only
*equivalent* rather than merely cheaper if two specific things are handled, and
both are non-obvious.

**Evidence in repo.** `sample_at_points(batch_years=True)`, built because this
machine has 9 GB and the unbatched global path OOMs. The two load-bearing
details: **slices are padded ±45 days** (products are stamped mid-month with
nearest-in-time selection, so a 31 December point's nearest timestep is the next
year's 15 January — with the pad at 0 the equivalence test fails on `thetao` by
**2.92**, verified not assumed); and **eddy kinetic energy is handed the record
mean**, being the one derived field that reduces over time, so a one-year batch
would measure anomalies against that year's mean under the same column name.
Tested for value-identity, not just for running.

**Experiment needed.** Little — this is nearly Tier 1. It needs framing as a
general pattern (any fit-then-apply reduction inside a batched apply) plus one
more instance to show it generalises. Best folded into 1.4 as a joint
"silent-correctness in geospatial data engineering" paper.

**Venue.** *Computers & Geosciences*, *SoftwareX*, *Environmental Modelling &
Software*.

---

## Tier 3 — needs a build first, but the build is scoped

**3.1 and 3.3 are missing from this tier because they were built.** They are now
1.10 (the percentile climatology) and 1.11 (upwelling detection, plus the
control-arm result the corroboration produced). The numbers are left as gaps
rather than closed up, so a reference to "3.1" written before 2026-08-17 still
resolves to the right topic instead of silently pointing at a different one.

### 3.2 Eddy tracking validated against an atlas, not against plausibility

**Claim.** Frame-to-frame eddy assignment is where detection becomes
storytelling: a matcher that flickers identity produces trajectories that are
artefacts presented as observations, and they look completely convincing.

**Status.** Deliberately not built. `services/eddies.py` holds no state between
refreshes on purpose, so tracking starts from a clean sheet. TODO is explicit
that it must be validated against a published eddy atlas rather than against how
plausible the tracks look.

**Why it is the interesting half.** The detection paper (1.8) can honestly say
"we do not track." A tracking paper whose contribution is *the validation
protocol* — how you tell a real track from a matcher artefact, with an atlas as
ground truth — is more valuable than another matcher.

**Venue.** *Ocean Modelling*, *Journal of Geophysical Research: Oceans*.

---

### 3.4 ConvLSTM / U-Net spatial forecasting against the per-point tree baseline

**Claim.** The engine's 26 griddable variables are currently forecast per point
and assembled into a grid; a spatial model forecasts the field directly. The
useful contribution is not "deep learning works" but a fair comparison on
identical data with identical validation discipline (rolling origin, embargo ≥
horizon, never random K-fold) against a strong, honestly-baselined tree.

**Evidence in repo.** The tree baseline is unusually well characterised — it is
the subject of the shipped paper, scored against both persistence *and*
climatology across 13 variables × 4 horizons × 24 sites, with the flattery
failure mode already documented. That makes it a much better comparison point
than the persistence-only baselines most spatial-forecasting papers use. The
forecast grids are built and the count moves with every incremental `--all` run
(8 on 2026-08-14, 28 on 2026-08-17), so **count the directory rather than
quoting a number from a document** — the repo's own rule, and the reason this
entry no longer states one. `tests/test_forecast_grid.py` pins the grid path to
the point path cell-for-cell at 1e-6, so train/serve skew is already
controlled.

**Venue.** *Environmental Data Science*, *Artificial Intelligence for the Earth
Systems* (AIES), *Geoscientific Model Development*.

---

### 3.5 Grounding checks for a tool-calling assistant over live scientific data

**Claim.** A domain assistant that answers from tool output can be checked
against that output, but the check has failure modes that train users to ignore
it — and cry-wolf is a worse outcome than no banner.

**Evidence in repo.** `services/chat/` implements it: the answer's numbers are
checked against everything the tools returned. Two design findings are already
recorded. (i) **`grounded` cannot be streamed** — it is computed against the
*finished* text, so it rides the terminal `meta` event, which constrains the UI
to render streaming text as *unverified* and resolve at the end; a badge shown
earlier asserts a check that has not run. (ii) **The number regex must handle
thousands separators**: without a grouped branch, "2,048 m" split into "2" and
"048", neither of which appears in any tool result, so a correct answer was
flagged as carrying two untraceable figures **on any depth over a thousand
metres**. A model's own unit conversion ("roughly 6,700 ft") is still flagged,
and that is correct — no tool reported it.

**Missing.** An evaluation set: N questions, human-labelled for whether each
number is traceable, so precision and recall of the checker can be reported.
That is the whole paper and it does not exist yet.

**Venue.** An NLP venue's applied/industry track (EMNLP Industry, NAACL
Industry), or a trustworthy-AI workshop.

---

## Tier 4 — infrastructure and reproducibility notes

These are short-format contributions (SoftwareX, JOSS, *Scientific Data*, or a
reproducibility workshop). Each is real, measured, and currently invisible
outside this repo.

### 4.1 An MLflow dependency inverted rather than added

`marine_ml/tracking.py` tracks the backend forecasting engine **without the
backend importing MLflow**: the backend writes an immutable
`_reports/runs/<timestamp>/` of plain stdlib JSON, and `ingest_forecasting`
reads it from the ML side. `backend/tests/test_training_run_record.py` asserts
`mlflow` never appears in `backend/`, because the obvious "improvement" later is
to log directly from the training script. Two supporting decisions:
`mlflow-skinny` never plain `mlflow` (the full package pins `pandas<3` /
`pyarrow<23` and would major-version-downgrade pandas under a 3.9M-row parquet
store), and tracking **never fails a training run** — a HAB run is ~40 minutes,
so every path degrades to a warning.

### 4.2 Reproducing a 52-model audit in 0.8 s per variable instead of 700 s

Already written up in `research/README.md` but publishable as a standalone
reproducibility note: pinning `as_of` so every cached provider request has a
stable key, plus `MARISAI_FROZEN_HISTORY_CACHE=1` serving the disk cache
regardless of its 6-hour TTL — correct because a pinned historical window cannot
be revised upstream, and deliberately set by no serving path. Together these are
what made 52 models plus **1,248 held-out fits** practical at all.

### 4.3 Access-pattern-dependent performance in ARCO zarr stores

Copernicus Marine publishes the same data through two zarr services with
opposite chunking, and picking wrong turns a ~10 s fetch into hours.
Measured 2026-08-10 on one year of global monthly physics coarsened to 0.25°:
**geo-series 7.5 s, time-series 89.0 s** — and the ordering *reverses* for a
bounded-area/many-timesteps request. Three access patterns exist in this one
codebase (map snapshot, regional download, whole-globe-many-timesteps for the
forecast grid) and each needs a different answer. Companion finding: the 50-level
reanalysis products need a **server-side depth bound** or a request that did not
finish in 15 minutes; with it, ~60 s.

### 4.4 ERDDAP servers answer 404 while reloading a dataset

An operational note with a correction attached, which is what makes it worth
writing. NOAA CoastWatch's `GEBCO_2020` was recorded here as retired; re-probed
2026-08-05, it returns 200 with correct depths. What actually happens is the
server flaps — fully 503, then `NOAA_DHW` and `GEBCO_2020` each 404 for ~100 s —
because ERDDAP unloads a dataset while reloading it and answers 404 "Currently
unknown datasetID", **indistinguishably from a removed one**. The dataset search
index drops entries during instability too, so a search result is not evidence
either. Hence: retry 404 **exactly once**. Both halves measured — retrying a
permanent failure 3× with backoff turns a warm 2.2 s forecast into 14.5 s, while
one transient GEBCO 503 cost 6 of 24 training points, a quarter of a model's
geography. Verified end-to-end: 404 → 2 attempts/2.0 s, 400 → 1, 503 → 3/8.0 s.

### 4.5 A survey of marine biodiversity data access, with live probe results

CLAUDE.md holds a three-tier survey of ~40 sources probed live on 2026-08-05,
with verdicts: which are open REST/JSON and occurrence-shaped, which are gated
or bulk-download-only, and — the section that motivated it — that **no Indian
marine data source has a machine-readable API**. Specific findings worth
publishing: `fishbase.ropensci.org` is dead (DNS); VertNet is defunct (portal
404, appspot API 500); PANGAEA's ES endpoint is gone (use OAI-PMH); WCPFC's
public-domain URLs are 404; the `*.icar.gov.in` hostnames for CIFRI/CIFT/CIBA/CIFA
all fail DNS/TLS while the `.res.in` domains work; and IndOBIS needs no new
integration at all — it is reachable through the existing OBIS API as node
`1a3b0f1a-4474-4d73-9ee1-d28f92a83996` (79 datasets, 110,905 records, 19,210
species, 1743–2025), so the node filter is a provenance facet, not extra data.
A survey ages fast, which is the argument for publishing it now with dated
probes rather than later.

**Venue.** *Scientific Data*, *Biodiversity Data Journal*, *Ecological
Informatics*.

---

## Cross-cutting theme, if you want one paper instead of ten

Nearly every Tier 1 entry is the same story: **a marine ML system fails
silently, plausibly, and in a signed direction**. The persistence baseline
flatters (shipped paper); the mixed-cadence merge reports an instantaneous
sample as a mean (1.4); the linear interpolation reverses a bearing (1.5); the
outlier filter deletes clean data (1.7); the eddy detector returns features from
white noise (1.8); the bilinear resample erases the coastline (1.9); the
proportional ensemble scores below its best member (1.1); the batched sampler
measures anomalies against the wrong mean (2.5); the cross-product baseline
inverts a tail test while leaving a mean test intact (1.12).

Two more instances are of a different and arguably worse kind, because the
output is not merely wrong but *rhetorically* wrong: a corroboration rate with
no control arm reads as confirmation when it is nearly chance (1.11), and a
model trained on 64.7× the data reads as an upgrade while scoring less than half
the skill on the water it will be used for (1.2); and a bloom warner reports the
precision of its *basin* as though it were the precision of its model (1.13). In
every case the system keeps running, produces output of the right shape and
units, and looks correct.

A single paper — *"Silent failure modes in operational marine machine
learning"* — with eleven measured instances from one running system, each with its
detection method and its fix, is probably higher-impact than any individual
entry above and is **already fully evidenced**. It needs writing, not
experiments. That is the recommendation.

The sharpest framing available: **every one of these was found by a check that
was cheap and is almost never reported** — a second baseline, a control arm, a
hand-computed value, a synthetic field with a known answer, a fixture built
deliberately backwards. That is a paper about practice, not about the ocean.

**Venue.** *Environmental Modelling & Software*, *Nature Scientific Reports*,
or a high-visibility perspective slot in *Frontiers in Marine Science*.

---

## Priority ordering

Revised 2026-08-17. Four entries moved up because the work landed, and the top
of the table is now unusually cheap: **the first five need writing, not
experiments.** That is the headline of this revision — the constraint on
publishing from this repo is no longer evidence, it is prose.

| # | Topic | Distance | Value |
| --- | --- | --- | --- |
| 1 | Silent failure modes (cross-cutting) | writing only | highest |
| 2 | 1.2 What going global buys an SDM | **writing only** — headline measured | high |
| 3 | 1.12 Cross-product baselines invert tail tests | writing only; generalising is optional | high, transfers widely |
| 4 | 1.11 Corroboration needs a control arm | writing only | high, small, negative |
| 5 | 1.13 HAB precision is base rate, not skill | **writing only** — five regions run | high |
| 6 | 1.1 Softmax ensemble weighting | one sweep | high, self-contained |
| 7 | 1.10 Percentile climatology + MHW | built; MHW application needs a season | high, unblocked four features |
| 8 | 1.8 + 3.2 Eddy detection, then tracking | atlas validation | high |
| 9 | 2.1 GBIF ∪ OBIS | one integration | medium-high |
| 10 | 2.2 True absences vs pseudo-absences | region change | highest ceiling, highest cost |
| 11 | 4.5 Data-access survey | writing only | medium, perishable |
| 12 | 3.4 ConvLSTM vs the tree baseline | large build | medium |

**1.2 changed rank for a reason worth noting**: it was ranked 4th at "one
training run away", and that run has since been done — and *reversed the
expected sign*. The paper is now "more data made it worse, and here is why it is
not extrapolation", which is a better paper than the one originally catalogued.
