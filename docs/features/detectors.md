# MarisAI — Detectors (eddies, upwelling, eDNA coverage)

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Eddy detection (`services/eddies.py`, `GET /api/ocean/eddies`,
  `features/map/hooks/useEddies.ts` + the `eddies` layer) — the platform's first
  **detector**: it turns a field into named things with a position, a size, a
  polarity and an intensity. Okubo-Weiss (`W = Sn² + Ss² − ζ² < −0.2σ`) over the
  live surface-current cache.
  - **It detects; it does not track.** Nothing holds state between refreshes,
    deliberately. Age and trajectory are a frame-to-frame assignment problem, and
    a matcher that flickers identity produces tracks that are artefacts presented
    as observations. See TODO.md.
  - **It reads the currents cache rather than fetching.** `detect()` is pure —
    snapshot in, features out — and `_current_detection()` keys its cache on the
    snapshot's own timestamp, so the hourly refresh invalidates it with no wiring
    between the two modules. The whole global pass is ~0.1 s over a grid that is
    already resident, which is why it is computed on demand rather than
    scheduled.
  - **Never loop `np.nonzero(labels == index)` per component.** That rescans the
    whole grid once per feature — measured **37 s** on ~2,000 global detections.
    Sorting the labelled cells once and slicing by `searchsorted` gives a
    bit-identical answer in 0.1 s.
  - **Polarity is `sign(ζ) == sign(latitude)`, not `sign(ζ)`.** Cyclonic means
    turning with the planet, so an identical counter-clockwise vortex is cyclonic
    at 25N and anticyclonic at 25S — a detector reading the vorticity sign alone
    is right in one hemisphere and confidently wrong in the other. The ±5°
    equatorial band is excluded entirely, because f vanishes there and the
    polarity would be a coin flip.
  - **The seam is closed in three places, and each fails silently otherwise.**
    Derivatives roll across the antimeridian when the grid is periodic (measured,
    via `field_sampling.is_globally_periodic`); `ndimage.label` sees a flat array,
    so components touching both edges are unioned afterwards; and the centroid is
    a circular mean, because the arithmetic mean of +179 and −179 is 0, which
    relocates a Pacific eddy to the Gulf of Guinea.
  - **The count is not a census, and the response says so.** The threshold is
    relative to the variance of the field in view, so it is a consistent detector
    under a changing mask rather than a measurement; `threshold`, `sigma_w`,
    `coverage` and `limits` ride with every response for that reason. The ~0.25°
    cache sets the smallest resolvable feature, and a strong jet can merge into
    one 300 km "eddy" — the Somali current does exactly this in the SW monsoon.
  - The map layer is in the **`flow`** category, not `ai`: it is a diagnostic
    computed from an observed field, and filing it under "AI (Experimental)"
    would label an observation as an inference. Rings are drawn at the eddy's
    true equivalent radius rather than as fixed-pixel dots, because the size is
    the measurement — and the tooltip says the ring is the equivalent radius of
    the rotating core, not the feature's outline. Polarity is the only
    categorical thing a detection carries, so it gets two colours and no ramp:
    teal cyclonic, amber anticyclonic, both clearing 3:1 on the Abyss basemap.
  - **`GET /api/ocean/eddies` answers 503, not 502, on a cold detector.** It
    reads a cache *this* server warms, so an unavailable answer is ours to
    explain — unlike the OBIS call beside it, where 502 correctly blames an
    upstream. A malformed `bbox` or `polarity` is 422, and the router rejects
    every caller error *before* calling the service, so anything reaching the
    `EddyError` handler is genuinely a cold or unusable currents cache.
  - **`eddies.nearest()` is why the point brief can report an absence.** A point
    well outside every detection is a real answer, so the brief's flow section
    prints the distance to the nearest feature rather than omitting the row —
    and its note states that eddies are not tracked, so none of them has an age.
- Coastal upwelling, corroborated by SST (`services/upwelling.py`,
  `GET /api/ocean/upwelling{,/point,/cells}`) — Bakun's wind-derived index, plus
  a second and separate claim about whether the water is actually cool. The
  index itself is described in its own module docstring; what generalises to the
  next detector that wants corroborating is the shape:
  - **Two claims, two blocks.** `coverage` describes the wind index alone and
    stays readable without the SST half; `corroboration` carries its own
    `available`, its own timestamp and its own baseline. The index is identical
    with and without SST and a test asserts it — corroboration *adds* a claim,
    it never edits or filters the one already made, so a cold SST cache degrades
    the layer rather than failing it.
  - **The anomaly is `services/heatwaves.py`'s own arithmetic, sign reversed.**
    `sst_anomaly_field()` exports it from the same OISST tail against the same
    fitted climatology, using the `p10` that `climatology/build.py` fits as the
    cold mirror of `p90`. A second module opening a second OISST tail would be a
    second answer to "how unusual is this water"; the export is deliberately
    narrow (`SstAnomalyField`), not the whole `HeatwaveField`.
  - **`sst_unavailable` is a state, not a falsy `corroborated`,** and
    `favourable_cells_with_sst` is the denominator. Water OISST does not cover
    is neither confirmed nor refuted — counting it as "not corroborated" reports
    a coverage gap as a finding about the ocean.
  - **The lag is published, not folded into one timestamp.** This is the
    opposite of `services/drift.py`, which reports the stalest of its terms
    because they are the same quantity. Here the wind is hourly and OISST
    publishes daily with a week or more of lag (16 days, measured 2026-08-17),
    so both stamps and `lag_hours` ride with the response and every wording is
    "the wind is favourable now, and the water was cool at the most recent SST
    field N days ago" — never "the water responded to this wind".
  - **The control ships in the response, because the agreement turned out to be
    weak.** Measured live 2026-08-17: 19.9% of upwelling-favourable coastal
    cells were cool for the season against **17.2% of downwelling-favourable
    ones**, the p10 tiers indistinguishable (4.1% vs 3.9%), and the favourable
    coasts *warmer* on average (+0.91 vs +0.60 degC). `control_cool_fraction` is
    computed with every response and rendered beside the corroborated count —
    same rule as HAB precision against base rate. Do not remove it and do not
    quote the corroborated fraction alone.
  - **Do not re-plumb this onto the live SST cache.** It was built and measured
    2026-08-17 and is worse: the weak tier's contrast was unchanged (+0.022 vs
    +0.026) and the strong tier **inverted** (−0.149). The climatology is fitted
    on OISST, and the live physics field disagrees with it by **sd 0.76 °C
    across the coastal band** (0.47 open ocean; 10% of coastal cells over
    1.0 °C) with a median of ~0 — noise, not an offset, so there is nothing a
    bias constant could fix, and it is wider than the 0.5 °C threshold it feeds.
    Latency is not the binding constraint; the baseline's product is. The fix is
    a climatology fitted on the Copernicus reanalysis — see TODO.md.
  - **`services/sst_anomaly.py` owns the shape of "SST against its baseline"**
    (the `SstAnomalyField` dataclass and the source labels) so that a second
    producer cannot drift into a second definition. `heatwaves.py` produces the
    OISST record's answer and labels it as the record's.
  - On the map, corroboration is an **outline over the sign-coloured fill**,
    never a third fill colour: blended, neither claim is readable without the
    other. A stroke cannot say "we could not look", which is why the status chip
    always states how many favourable cells could be checked.
- eDNA sampling coverage (`services/edna.py`, `GET /api/ocean/edna/coverage`
  and `/api/ocean/edna/point`, `features/map/hooks/useEdnaCoverage.ts` + the
  `edna-coverage` layer) — where the ocean has been sampled *molecularly*.
  **No new integration**: `hasextensions=DNADerivedData` is a filter on the same
  OBIS endpoints `biodiversity.py` already calls, so this adds a question rather
  than a provider.
  - **The empty map is the data, and it is the only layer here that is not a
    field.** Measured live 2026-08-16: 44,548,350 eDNA records worldwide,
    occupying **1,475 cells / 27,286 km² at precision 5 — 0.0075% of the ocean,
    smaller than Belgium**. A reader arriving from SST reads that blankness as a
    failed load, so `EdnaCoverageStatus` states the coverage unprompted.
  - **Coverage is quoted at a fixed `REFERENCE_PRECISION`, never at the drawn
    grid.** The same records cover **23.1%** of the ocean at precision 2 and
    **0.0075%** at precision 5 — a ~3,000x swing produced entirely by cell size,
    because a coarse cell credits one water bottle with everything around it.
    The map draws a coarser grid when zoomed out, so reading the fraction off
    the displayed level would put the most flattering number in the default view
    and shrink it as the reader looked closer. A bbox request reports **no**
    whole-ocean fraction at all, rather than a ratio between two unrelated areas.
  - **OBIS grids are geohash cells, so they are not square at even precisions**
    (p4 is 0.3516° x 0.1758°, p3 and p5 are square). A first draft derived them
    from one formula and was wrong by 2x in one axis and 4x in the other — in a
    field the frontend legend quotes. Cell extents are read off the returned
    polygons; `cell_dimensions_deg` derives the nominal size the way geohash
    actually works, and a test pins all five levels against measured values.
  - **The ramp is logarithmic on a *fixed* domain.** Occupied cells span six
    orders of magnitude (1 to 4,353,873 — the Australian Microbiome program off
    Sydney), so a linear ramp is a black planet with one bright pixel.
    Normalising against the loaded maximum was rejected: a cell would change
    colour on zoom and the legend could name no number. Violet, because effort
    is not a property of the water and should not look like the physical layers;
    the darkest stop measures 3.38:1 on the Abyss basemap.
  - **Counts are taxon-detections, not samples, individuals or abundance.** A
    microbial 16S dataset returns thousands of records per bottle where a fish
    survey returns a handful. `organismQuantity` arrives in *DNA sequence reads*
    — the one quantitative field conventional occurrences lack, and it scales
    with primer affinity and PCR cycles as much as with biomass. It is never
    reported as abundance.
  - **Absence means even less here than in OBIS generally.** A taxon can be
    missing because it shed no DNA, because the DNA degraded, because the primer
    did not amplify it, or because no reference sequence exists to name it —
    four links, any of which can break. `at_point` distinguishes *three* empty
    cases, not two: upstream failure, water nobody sampled at all, and water
    that was surveyed but never sequenced (the Arabian Sea case — 205
    conventional records, zero molecular).
  - **`molecular_share` is `None`, not `0`, on an empty box.** "0% molecular"
    reads as a finding about method choice when the truth is a missing
    denominator. The conventional total is fetched deliberately beside the eDNA
    one, because "8,814,299 molecular records" sounds like saturation and is one
    sequencing programme — beside the box total it becomes the real finding
    (86% of everything OBIS knows about the water off Sydney is molecular).
  - **Two things eDNA was checked for and cannot do — do not reopen these.**
    Both were measured against the live API on 2026-08-16:
    - **It does not reopen `HABITAT_END = 2013`.** eDNA records for
      `TARGET_SPECIES`: yellowfin **0**, oil sardine **0**, skipjack 44, bigeye
      19, Indian mackerel 45 — 108 in total. The post-2014 drought survives the
      change of *method*, just as it survived the GBIF union.
    - **It cannot validate HAB in the Arabian Sea.** The whole `ARABIAN_SEA` box
      holds **93** eDNA records across 4 datasets, and zero for *Noctiluca
      scintillans*, *Trichodesmium* or *Pseudo-nitzschia* (globally: 6,536 / 0 /
      50,510). The bloom taxa are sequenced elsewhere, not here.
  - No poll timer, unlike the eddy and vessel layers: OBIS publishes on a
    release cadence of weeks, the backend caches each precision for 24h, and the
    layer refetches on *zoom* only — the global payload is ≤348 KB at the finest
    level, so there is deliberately no viewport filtering to make pans cheap.
  - 502, not 503: a live upstream call, so an outage is the provider's — the
    same split as `/biodiversity` and the opposite of `/eddies`.

