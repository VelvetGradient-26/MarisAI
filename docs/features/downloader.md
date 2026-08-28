# MarisAI — Universal Ocean Data Downloader

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Universal Ocean Data Downloader (`services/download/`, `pages/DownloadPage.tsx`):
  34 of 36 spec variables against real data, across 14 providers, plus
  CSV/JSON/PDF export. Only `tidal_height` and `ammonium` remain
  `available: false` — neither has a global source (the Copernicus global BGC
  suite models nitrate/phosphate/silicate/iron but not ammonium).
  - **Two registries, deliberately split**: `registry.py` maps variable ->
    provider + source field; `catalog.py` maps provider -> dataset, grid
    spacing, native cadence, coverage start, citation, licence, and fetch
    function. `service.py` and `limits.py` are generic loops over
    `catalog.PROVIDERS` — adding a provider is one catalog entry, not an edit
    in four files. **One provider == one upstream dataset**; the five
    Copernicus BGC datasets are five providers precisely so their differing
    coverage windows stay correct without special cases.
  - **Every provider's `fetch` has the same keyword-only signature and returns
    an `xarray.Dataset`**, whatever it actually talked to. `providers/openmeteo.py`
    is a *point* JSON API that lays its own lat/lon grid and reassembles the
    responses; `providers/gebco.py` reads CSV from ERDDAP. Keep that contract —
    it's why `cleaning.py` never learns which provider is which.
  - **Cadence and grid vary a lot** (hourly/3-hourly/daily/time-invariant;
    0.083deg to 0.25deg). `cleaning.py` reindexes onto the *finest* grid
    present, so coarse fields repeat rather than fine fields being discarded.
  - **Time is aggregated per provider *before* the merge, and the order of the
    three stages in `build_dataframe` is load-bearing.** It is resolve codes ->
    aggregate to the requested cadence -> `xr.merge(join="inner")`, and each
    arrow was earned:
    - Aggregating before the join, because the join cannot aggregate. Left to
      itself the inner join keeps the *coarse* provider's timestamps and takes
      the fine provider's **instantaneous** value at each — an hourly field
      paired with a daily one survives as its 00:00 sample standing in for a
      24-hour mean. Nothing raises and nothing is NaN, so this was silent: on a
      synthetic 3 degC diurnal cycle the old path reported 23.0 where the daily
      mean is 20.0, wrong by the full amplitude in every row and always in the
      same direction. **13 of the 32 configured forecasting variables were
      feeding at least one covariate to training this way** — every wave
      variable (3-hourly target, hourly wind), every biogeochemistry variable
      (daily target, hourly SST) and all three depth-resolved ones.
    - Resolving codes before aggregating, because a derivation is non-linear.
      `current_speed` is `hypot(uo, vo)`, and the mean of hourly speeds is not
      the speed of the mean components — a current rotating through the day at
      a constant 1 m/s averages to ~0 components and would be reported as slack
      water. This ordering was already correct and is now pinned by a test, as
      moving aggregation earlier is exactly what would take derivations with it.
    - There is deliberately **no second resample after the merge**. Two places
      that could define the cadence is how the pre-merge one silently stops
      mattering. `tests/test_download_cadence.py` covers all of it.
  - **Gotcha that will bite again**: surface-level Copernicus datasets carry a
    scalar `depth` coord at differing float precision (0.494025 vs 0.49402538),
    and `xr.merge` treats that as a conflict — which broke every mixed
    physics + BGC request. `copernicus.py::_resolve_depth` drops it after
    selecting the surface, and keeps it only for the depth-selected datasets
    (where the resolved level is reported back in the export metadata).
  - **Depth-resolved variables** (`water_temperature`, `water_salinity`) read
    `DownloadRequest.depth_m` and snap to the nearest of 50 geometrically
    spaced levels. Below the seafloor the model is NaN, so an over-deep
    request legitimately returns nothing — the error names that case.
  - **The 50-level products need a server-side depth bound** (`minimum_depth`/
    `maximum_depth`), exactly as `machine_learning/` documents: without it the
    BGC fetches pull all 50 levels and effectively never finish. With it,
    ~7s.

