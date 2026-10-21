# Graph Report - MarisAI  (2026-08-28)

## Corpus Check
- 1033 files · ~1,491,966 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 5296 nodes · 11649 edges · 220 communities (198 shown, 22 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 335 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `90ae239e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Forecasting Preprocessing Outlier
- Forecasting Registry Predictor
- Forecasting Uncertainty Interval
- Forecasting Feature Engineering
- Chat Flagged Number
- Forecasting Grid Predictor
- Upwelling Testcorroboration Wind
- Forecasting Climatology Paper
- Train Forecasting Commit
- Heatwave Testduration Testsstanomaly
- Download Limit Export
- Chat Session Variable
- Upwelling Field Cell
- Download Catalog Cleaning
- Download Progress Progressreporter
- Grid Cache Forecasting
- Chat Orchestrator Specialist
- Vector Source Vectorsource
- Dashboard Station Raw
- Chat Session Id
- Forecast Tile Colormap
- Stoke Drift Current
- Forecasting Evaluator Split
- Cyclone Point Severe
- NDBC Feed Latest
- Forecasting Shap Explainer
- Metric Sery Range
- Crw Summary Cache
- Dashboard Copernicu Sery
- Sst Anomaly Heatwave
- Edna Cell Coverage
- Logging Record Every
- Vector Source Drift
- Eddy Tracking Track
- Severe Weather Chat
- Routing Hazard Grid
- Grid Cache Brief
- Climatology Copernicu Reanalysi
- LLM Insight Generate
- Compare Against Eddy
- Download Cadence Field
- Ais Clean Vessel
- Gibs Product Cache
- Forecast Vector Tile
- Derived Testgrid Testconvention
- Vector Field Texture
- Security Insight Testinsightspromptbound
- Chat Agent Answer
- Field Sampling Prediction
- Climatology Oisst Recent
- Download Gebco Depth
- Rate Limit Security
- Eddy Vortex Rather
- Forecasting Derived Forecast
- Geofencing Point Eez
- Ocean State Field
- Dashboard Correlation Trend
- Chat Catalog Dataset
- Download Openmeteo Edna
- Copernicu Wind Marine
- Paper Asset Table
- Download Export Pdf
- Dashboard Trend Ocean
- Metric Story Fact
- Severe Weather Alert
- Forecasting Trainer Registry
- Tile Gfw Field
- Brief Section Forecast
- Field Sampling Cell
- Severe Weather Endpoint
- Copernicu Wind Fakearray
- Feature Assistant Thread
- Climatology Percentile Day
- Dashboard Quality Fold
- Eddy Detection Mean
- Forecast Warm Variable
- Routing Hazard Raise
- Biodiversity Box Point
- Copernicu Chlorophyll Current
- Vector Field Copernicu
- Dashboard Health Probe
- Forecast Grid Forecasting
- Stoke Drift Vector
- Dashboard Alert Formatting
- Feedback Security Name
- Openmeteo Port Ocean
- Drift Term Wind
- Dashboard Trend Report
- Forecasting Retried 404
- Metric Statistic Change
- Forecasting Quality Artifact
- Metric Forecasting Variable
- Copernicu Sst Colormap
- Current Depth Field
- Correlation Reported Variable
- Backend Severe Weather Alert
- Download Copernicu Global
- Backend Eddy Tracking Track
- Compare Delta Section
- Marine Risk Escalate
- Training Record Mlflow
- Middleware Logging Id
- Upwelling Upwellingfield Corroboration
- Climatology Path Available
- Cyclone Chat Active
- Copernicu Sst Grid
- Package Override Name
- Forecast Tile Vector
- Compare Row Forecast
- Dashboard Live Buoy
- Dashboard Summary Card
- Copernicu Current Marine
- Docs Chapter Search
- Oxlintrc Rule Package
- Climatology Testfit Nan
- Chat Session SSE
- Prediction Habitat Hab
- Climatology Copernicu S3
- Biodiversity Box Pole
- Hook Reveal Landing
- Marine Risk Assess
- Research Artifact Ablation
- Eddy Tracking Current
- Brief Pdf Compare
- Export Docs Routercontext
- Docs Query Nothing
- Database Session Async
- Measure Sst Corroboration
- Forecasting Historysery End
- Docs Word Search
- Climatology Testoisst Query
- Eddy Bbox 123
- Climatology Testserving Output
- Climatology Baseline Testbuild
- Climatology Testsamplefloor Year
- Climatology Testdayindex Year
- Pfz Sst Chlorophyll
- Chat Engine Client
- Brief Offline Fixture
- Climatology Testapply Anomaly
- Alembic Env Migration
- Apply Shipping Bar
- Chat Argument Validated
- Pfz Zone Candidate
- Climatology Testwindow Year
- Eddy Tracking State
- Chat Specialist Name
- Pyproject Marisai Pkg
- Docs Chapter Primitive
- Feature Assistant Map
- Feature Dashboard Hook
- Feature Map Layer
- Feature Dashboard Metric
- Package React Devdependency
- Frontend Feature Dashboard Metric
- Landing Diagram Split
- Feature Map Format
- Feature Dashboard Format
- Feature Map Download
- Landing Archive Ocean
- Package Radix UI
- Tsconfig Compileroption Ref
- Frontend Feature Dashboard Metric 175
- Feature Map Hook
- Frontend Feature Map Layer
- Frontend Feature Map Layer 178
- Feature Map Severe
- Frontend Tsconfig Compileroption Ref
- Feature Map Compare
- Feature Map Forecast
- Vector Field Feature
- Frontend Vector Field Feature
- Feature Dashboard Kpi
- Landing Scroll Reveal
- Feature Map Vessel
- Frontend Feature Dashboard Metric 191
- Frontend Feature Map Hook
- Feature Map Eddy
- Feature Map Vector
- Frontend Feature Map Hook 202
- Feature Map Basemap
- Frontend Feature Map Basemap
- Landing Map Descent
- Feature Map Drift
- Feature Map Feedback
- Error Boundary Errorboundary
- Feature Map Wind
- Feature Map Current
- Package React Dependency
- Frontend Feature Map Layer 222
- Landing Hero Field
- Landing Archive Dive
- Tsconfig Reference Json
- Package Leni Dependency
- Package Lucide React
- Package Maplibre Gl
- Frontend Package Radix UI
- Frontend Package Radix UI 237
- Frontend Package Radix UI 238
- Frontend Package Radix UI 239
- Package React Dom
- Package Rechart Dependency
- Package Tailwind Merge
- Package Tailwindcss Animate
- Package Tailwindcss Vite
- Package Uplot Dependency
- Package Zustand Dependency

## God Nodes (most connected - your core abstractions)
1. `react` - 97 edges
2. `cn()` - 67 edges
3. `Dataset` - 66 edges
4. `useMapStore` - 50 edges
5. `useThemeStore` - 46 edges
6. `Resolution` - 44 edges
7. `answer()` - 43 edges
8. `predict()` - 41 edges
9. `ForecastingError` - 40 edges
10. `get_config()` - 39 edges

## Surprising Connections (you probably didn't know these)
- `HistoryRequest` --uses--> `Resolution`  [INFERRED]
  forecasting/history.py → services/download/models.py
- `HistorySeries` --uses--> `Resolution`  [INFERRED]
  forecasting/history.py → services/download/models.py
- `fetch_recent()` --uses--> `Resolution`  [INFERRED]
  forecasting/history.py → services/download/models.py
- `_step()` --uses--> `Resolution`  [INFERRED]
  forecasting/predictor.py → services/download/models.py
- `clean()` --uses--> `Resolution`  [INFERRED]
  forecasting/preprocessing.py → services/download/models.py

## Import Cycles
- None detected.

## Communities (220 total, 22 thin omitted)

### Community 0 - "Forecasting Preprocessing Outlier"
Cohesion: 0.10
Nodes (25): FillStrategy, OutlierConfig, Outlier handling — see `preprocessing.py`. Detection replaces a flagged value…, detect_outliers(), fill_gaps(), _hampel_mask(), _iqr_mask(), PreprocessingError (+17 more)

### Community 1 - "Forecasting Registry Predictor"
Cohesion: 0.04
Nodes (66): BatchForecastRequest, create_batch_forecast(), create_forecast(), ForecastRequest, get_catalog(), get_model_detail(), get_models(), get_variable_detail() (+58 more)

### Community 2 - "Forecasting Uncertainty Interval"
Cohesion: 0.12
Nodes (23): Bootstrap prediction intervals — see `uncertainty.py`., UncertaintyConfig, bagged_interval(), fit_residual_quantiles(), _normal_z(), Any, ndarray, Bootstrap prediction intervals. A point forecast without an interval invites… (+15 more)

### Community 3 - "Forecasting Feature Engineering"
Cohesion: 0.04
Nodes (77): FeatureConfig, load_config(), model_validator, Path, One forecastable variable. `code` keys into…, Parse and validate the YAML. Raises ConfigError, never a raw yaml error., Which derived columns the feature builder emits. All of these are trailing by…, Longest trailing window any feature needs. The history fetch adds this to the… (+69 more)

### Community 4 - "Chat Flagged Number"
Cohesion: 0.09
Nodes (66): _collect(), conditions(), _delegate_call(), depth(), patched(), AIMessage, asyncio, fixture (+58 more)

### Community 5 - "Forecasting Grid Predictor"
Cohesion: 0.05
Nodes (67): clear_cache(), fetch_stack(), _fetch_with_timeout(), GridHistoryError, GridRequest, GridStack, _needed_fields(), ndarray (+59 more)

### Community 6 - "Upwelling Testcorroboration Wind"
Cohesion: 0.05
Nodes (33): _coast(), _favourable_case(), Tests for coastal upwelling detection. The hemisphere test is the one that…, Land in the western columns means offshore is east., Nothing to point away from, so the normal is meaningless and must not be…, The canonical case: land to the east, wind blowing toward the equator…, Identical geometry and identical wind, mirrored in latitude, must give the…, The index is per metre of coastline. Mid-ocean there is no coastline to be per… (+25 more)

### Community 7 - "Forecasting Climatology Paper"
Cohesion: 0.07
Nodes (58): apply_climatology(), _circular_window_mask(), Climatology, _curve_for(), _day_of_year(), fit_climatology(), _mean(), _nearest_fitted() (+50 more)

### Community 8 - "Train Forecasting Commit"
Cohesion: 0.20
Nodes (16): clear_cache(), Drop every cached series. Returns how many files were removed., _configure_logging(), _format(), _git_commit(), main(), _plot_diagnostics(), Any (+8 more)

### Community 9 - "Heatwave Testduration Testsstanomaly"
Cohesion: 0.06
Nodes (31): _climatology(), DataArray, parametrize, Tests for marine heatwave detection. Every failure mode pinned here produces a…, Categories are multiples of (p90 - mean), not of the exceedance., Where p90 == mean the multiple is a division by zero. Treating that as a large…, A 30-day window in spring crosses a moving seasonal threshold. Using the latest…, `services/crw.py` measured ice-margin cells tripling the global mean. The per-… (+23 more)

### Community 10 - "Download Limit Export"
Cohesion: 0.10
Nodes (42): download(), download_progress(), get_variables(), get, post, Request, Response, Universal Ocean Data Downloader endpoints. **Previously sign-in gated.**… (+34 more)

### Community 11 - "Chat Session Variable"
Cohesion: 0.17
Nodes (16): Base, ChatMessage, ChatSession, Persisted chat sessions. **This is the first feature in the codebase to…, DataSource, Location, Unit, VariableCategory (+8 more)

### Community 12 - "Upwelling Field Cell"
Cohesion: 0.11
Nodes (31): cells(), _coastal_band(), coriolis(), _corroborating_sst(), _current_field(), detect(), ekman_transport(), get_upwelling() (+23 more)

### Community 13 - "Download Catalog Cleaning"
Cohesion: 0.09
Nodes (25): _bgc_spec(), _copernicus_fetch(), _copernicus_spec(), FetchFn, licences(), date, Protocol, The provider table for the Universal Ocean Data Downloader. `registry.py`… (+17 more)

### Community 14 - "Download Progress Progressreporter"
Cohesion: 0.07
Nodes (37): active_count(), clear(), _Entry, _fraction(), ProgressReporter, _prune_locked(), Progress reporting for an in-flight download. Why this exists rather than a…, One upstream source finished. This is the only genuinely fine-grained signal in… (+29 more)

### Community 15 - "Grid Cache Forecasting"
Cohesion: 0.11
Nodes (32): _cache_get(), _cache_key(), _cache_put(), _fetch_provider(), Path, timedelta, Identify a cached global field by everything *except* which fields it holds.…, The filename for one cached fetch: its scope, then which fields it holds. The… (+24 more)

### Community 16 - "Chat Orchestrator Specialist"
Cohesion: 0.09
Nodes (31): build_delegate_tools(), DelegateArgs, Any, BaseMessage, BaseModel, StructuredTool, Specialist sub-agents the top-level loop in `agent.py` delegates to. **Why a…, One delegate tool per specialist, for the top-level orchestrator to call.… (+23 more)

### Community 17 - "Vector Source Vectorsource"
Cohesion: 0.07
Nodes (34): _Cache, Any, datetime, ndarray, A live U/V field, with its cache. One instance per (dataset, depth)., Refetch and re-encode. Never raises, and never clears a good cache. One…, Whether a refresh is in flight, derived from the existing lock rather than a…, This field's cached grid. Raises the field's own error if it is cold. (+26 more)

### Community 18 - "Dashboard Station Raw"
Cohesion: 0.07
Nodes (38): FastAPI, crw_cache(), _install_ndbc_cache(), asyncio, fixture, Tests for the dashboard services. Focused on the pure logic that was got wrong…, Not every station in `latest_obs.txt` is NDBC's own; a partner-network relay…, A 1-degree global grid with everything finite and unremarkable. (+30 more)

### Community 19 - "Chat Session Id"
Cohesion: 0.14
Nodes (35): enabled(), ensure_session(), history(), list_sessions(), Any, Persistence for chat sessions. **Degrades rather than fails.** `DATABASE_URL`…, Append the question and its answer, and bump the session's timestamp., Full stored messages for one session, or None if it is not this client's. (+27 more)

### Community 20 - "Forecast Tile Colormap"
Cohesion: 0.09
Nodes (30): ColorStop, build_colormap(), ndarray, Returns f(values) -> uint8 array of shape (*values.shape, 3). Piecewise-linear…, available(), catalog(), _field(), _hatch() (+22 more)

### Community 21 - "Stoke Drift Current"
Cohesion: 0.07
Nodes (42): get_biodiversity(), get_currents_depth_meta(), get_currents_depth_point(), get_drift_presets(), get_eddies(), get_eddy_track(), get_eddy_tracks(), get_edna_coverage() (+34 more)

### Community 22 - "Forecasting Evaluator Split"
Cohesion: 0.07
Nodes (40): ClimatologyFold, FitPredict, Rolling-origin settings. Never a random split — see `evaluator.py`., ValidationConfig, build_diagnostics(), chronological_split(), _circular_error(), compute_metrics() (+32 more)

### Community 23 - "Cyclone Point Severe"
Cohesion: 0.09
Nodes (37): get_cyclones(), get_cyclones_point(), get_geofence(), get_marine_risk(), get_pfz(), get_route(), get_severe_weather(), get_severe_weather_point() (+29 more)

### Community 24 - "NDBC Feed Latest"
Cohesion: 0.09
Nodes (35): BuoyObservation, _fetch(), _fetch_raw_feed(), _haversine_km(), health(), _is_fresh(), is_refreshing(), latest() (+27 more)

### Community 25 - "Forecasting Shap Explainer"
Cohesion: 0.05
Nodes (54): _patcher(), Any, One configured logger for the whole backend. **The problem this fixes is that…, ModelArtifact, A loaded model and everything needed to use and describe it., _align_features(), _apply_bounds(), classify_trend() (+46 more)

### Community 26 - "Metric Sery Range"
Cohesion: 0.09
Nodes (32): MetricsError, RuntimeError, Descriptive analytics for one variable at one point. The counterpart to…, Base for this package's errors. Matches the `XError(RuntimeError)` convention…, build(), decimate(), load_frame(), MetricSeries (+24 more)

### Community 27 - "Crw Summary Cache"
Cohesion: 0.11
Nodes (36): _area_weights(), bleaching_summary(), _build_query(), _CrwCache, CrwError, _haversine_km(), health(), hotspots() (+28 more)

### Community 28 - "Dashboard Copernicu Sery"
Cohesion: 0.09
Nodes (34): _cache_key(), _cached(), CopernicusSeriesError, _Entry, _integrate_heat_content(), _load_series(), ohc_key(), Any (+26 more)

### Community 29 - "Sst Anomaly Heatwave"
Cohesion: 0.08
Nodes (37): at_point(), _cached_field(), cells(), climatology_available(), current_field(), detect(), HeatwaveError, HeatwaveField (+29 more)

### Community 30 - "Edna Cell Coverage"
Cohesion: 0.06
Nodes (30): _coverage(), _point(), parametrize, eDNA sampling coverage from OBIS. Nothing here calls OBIS. What is pinned is…, The number a reader sees must not depend on how far they zoomed out. Cell size…, The cells are what gets drawn; the headline is a caption on them. Losing the…, Sampled area inside a small box over the area of the whole ocean is a ratio…, A zero-record cell painted at the ramp's bottom colour asserts a sample that… (+22 more)

### Community 31 - "Logging Record Every"
Cohesion: 0.07
Nodes (33): configure_logging(), InterceptHandler, _NoiseFilter, LogRecord, Drops third-party chatter, on the *handler* rather than on the logger. A…, Hands a stdlib record to loguru with its origin and traceback intact., Install one sink and route stdlib logging into it. Idempotent. Idempotence…, _configured() (+25 more)

### Community 32 - "Vector Source Drift"
Cohesion: 0.09
Nodes (33): get_drift_meta(), get_drift_point(), Combined drift velocity — current + Stokes + leeway — with its terms., _build_composed(), _Composed, DriftError, get_field_png(), get_meta() (+25 more)

### Community 33 - "Eddy Tracking Track"
Cohesion: 0.09
Nodes (31): _candidate_pairs(), _connected_components(), _Fix, _fix_from(), get_track(), get_tracks(), _haversine_km(), _in_bbox() (+23 more)

### Community 34 - "Severe Weather Chat"
Cohesion: 0.10
Nodes (33): _active_alerts(), _assess_risk(), _bloom_risk(), BloomArgs, _correlate(), CorrelationArgs, _current_conditions(), _cyclone_alerts() (+25 more)

### Community 35 - "Routing Hazard Grid"
Cohesion: 0.10
Nodes (32): _astar(), _connect_endpoint(), _DepthGrid, _edge_cost(), _fetch_hazard_batch(), _fetch_hazard_grid(), _grid_spacing_deg(), _haversine_km() (+24 more)

### Community 36 - "Grid Cache Brief"
Cohesion: 0.07
Nodes (30): The point brief — composition, and what it must never do. A brief is read away…, Habitat, bloom and forecast are predictions. A reader who cannot tell them from…, The converse, and the reason the two are separate sections at all., Open-Meteo's marine and weather endpoints each choose their own units. A brief…, The renderer must not assume rows exist. An all-empty brief is exactly what a…, Checked against the PDF's own bytes: reportlab compresses streams, so the…, A heatwave is meaningless without "relative to what", and the brief is read…, The window bounds what can be claimed. "12 days" when the record only reaches… (+22 more)

### Community 37 - "Climatology Copernicu Reanalysi"
Cohesion: 0.12
Nodes (29): _coarsen(), CopernicusReanalysisError, fetch_currents_day(), _fetch_currents_sync(), fetch_range(), _fetch_sync(), _open_lazy(), date (+21 more)

### Community 38 - "LLM Insight Generate"
Cohesion: 0.10
Nodes (24): post_generate_insights(), post, Request, _build_prompt(), generate_ocean_insights(), InsightsError, Any, RuntimeError (+16 more)

### Community 39 - "Compare Against Eddy"
Cohesion: 0.13
Nodes (34): _candidate_pairs(), _compare_polarity(), _connected_components(), _detect_for_day(), _haversine_km(), _load_atlas_day(), main(), _match() (+26 more)

### Community 40 - "Download Cadence Field"
Cohesion: 0.07
Nodes (55): Enum, Event, earliest_start(), date, The earliest date all of `codes` are simultaneously available. The *latest* of…, get(), build_dataframe(), DataFrame (+47 more)

### Community 41 - "Ais Clean Vessel"
Cohesion: 0.11
Nodes (30): AisError, _apply_message(), _clean_cog(), _clean_heading(), _clean_positive(), _clean_sog(), _clean_text(), _consume() (+22 more)

### Community 42 - "Gibs Product Cache"
Cohesion: 0.11
Nodes (28): Element, _fetch_capabilities(), _GibsCache, GibsError, health(), is_refreshing(), latest_product(), _layer_details() (+20 more)

### Community 43 - "Forecast Vector Tile"
Cohesion: 0.14
Nodes (31): ForecastTileError, _grid_dir(), _load_grid(), RuntimeError, A forecast grid is missing, malformed, or the request is out of range., available(), catalog(), clear_cache() (+23 more)

### Community 44 - "Derived Testgrid Testconvention"
Cohesion: 0.07
Nodes (15): ndarray, parametrize, Tests for bearings derived from component forecasts. Two failure modes here are…, Percentiles round a circle are what produced the shipped `display_max: 400`…, Land in one component is land in the bearing. A cell with only one component…, A grid that cannot say where it came from is one nobody can audit., No wave components exist in the download registry, so it stays trained — and…, Reusing one for the other gives a field that is backwards and completely… (+7 more)

### Community 45 - "Vector Field Texture"
Cohesion: 0.10
Nodes (31): _components(), _physics_like_field(), ndarray, Tests for the U/V field textures the GPU particle layer consumes. **What…, Below 80degS the currents product has nothing, and the shader must know.…, Zero velocity is a real reading — slack water. Land is not, and a particle must…, Row 0 of the image is the northernmost latitude. A flipped texture is the…, Some products publish latitude north-to-south. Encoding one as-is would invert… (+23 more)

### Community 46 - "Security Insight Testinsightspromptbound"
Cohesion: 0.16
Nodes (13): GenerateInsightsRequest, LocationContext, NearestPort, Any, BaseModel, field_validator, The prompt builder only reads a fixed set of keys, so extra ones are harmless —…, RequestedPoint (+5 more)

### Community 47 - "Chat Agent Answer"
Cohesion: 0.12
Nodes (34): _all_specialist_tool_texts(), _allowed_set(), answer(), answer_stream(), ChatError, _false_refusal(), _history_messages(), _model() (+26 more)

### Community 48 - "Field Sampling Prediction"
Cohesion: 0.11
Nodes (33): A field prepared for smooth resampling: values and coverage separately.…, The field on a tile's pixel-centre axes, as (y, x), NaN off-coverage., Sampler, available(), _export_dir(), hab_point(), _hab_sampler(), hab_slice() (+25 more)

### Community 49 - "Climatology Oisst Recent"
Cohesion: 0.11
Nodes (29): backoff_for(), build_query(), build_recent_query(), _drop_zlev(), expected_days(), fetch_range(), fetch_recent(), _get() (+21 more)

### Community 50 - "Download Gebco Depth"
Cohesion: 0.10
Nodes (25): MonkeyPatch, choose_stride(), fetch(), GebcoDownloadError, _parse_csv(), Any, RuntimeError, GEBCO bathymetry provider for the Universal Ocean Data Downloader.… (+17 more)

### Community 51 - "Rate Limit Security"
Cohesion: 0.17
Nodes (11): client_key(), enforce(), Request, RateLimiter, In-memory fixed-window rate limiting. Hand-rolled rather than pulling in…, Allows `limit` requests per `window_seconds` per key., Records a hit. Returns None if allowed, or the seconds remaining in the current…, Best-effort caller identity. Behind a proxy the socket address is the proxy's,… (+3 more)

### Community 52 - "Eddy Vortex Rather"
Cohesion: 0.14
Nodes (27): _grid(), Eddy detection. Every property pinned here fails *silently* in production: a…, The convention, and the reason it is not `sign(vorticity)`. Cyclonic means…, Not an exact match, and it should not be. The reported radius is the equivalent…, f goes to zero at the equator, so polarity there is a coin flip., Zero variance means the threshold is undefined, which is a different answer…, The seam, in both places it bites. `ndimage.label` sees a flat array, so a…, The method's known weakness, pinned rather than wished away. The threshold is… (+19 more)

### Community 53 - "Forecasting Derived Forecast"
Cohesion: 0.08
Nodes (34): combine(), combine_array(), combine_uncertainty(), derive_grid(), DerivedSpec, is_derived(), ndarray, Bearings derived from forecast components, rather than forecast directly. The… (+26 more)

### Community 54 - "Geofencing Point Eez"
Cohesion: 0.08
Nodes (17): MultiPolygon, _box(), check(), _haversine_km(), _polygon_from_zone(), ProtectedArea, Any, Polygon (+9 more)

### Community 55 - "Ocean State Field"
Cohesion: 0.13
Nodes (26): _area_weighted_stats(), FieldSpec, get_field(), health(), is_refreshing(), _load_all(), _load_field(), _load_field_with_retry() (+18 more)

### Community 56 - "Dashboard Correlation Trend"
Cohesion: 0.08
Nodes (36): get_alerts(), get_data_quality(), get_health(), get_live(), get_model_health(), get_satellites(), get_source_detail(), get_station_detail() (+28 more)

### Community 57 - "Chat Catalog Dataset"
Cohesion: 0.08
Nodes (23): build(), _cadence(), _licence_short(), The dataset catalog, rendered into the assistant's system prompt. TODO.md §6…, First clause only — the full citation is for exports, not for a prompt., The catalog as prompt text., The catalog in the prompt must be complete, honest, and not trip grounding.…, The placement the grounding checker depends on. (+15 more)

### Community 58 - "Download Openmeteo Edna"
Cohesion: 0.08
Nodes (46): Semaphore, build_grid(), fetch(), _fetch_window(), _get_batch(), OpenMeteoDownloadError, Any, AsyncClient (+38 more)

### Community 59 - "Copernicu Wind Marine"
Cohesion: 0.14
Nodes (24): get_wind_meta(), get_wind_point(), _beaufort(), _candidate_times(), _compass_label(), CopernicusWindError, _fetch_latest_grid(), get_field_png() (+16 more)

### Community 60 - "Paper Asset Table"
Cohesion: 0.22
Nodes (25): ablation_macros(), figure_ablation(), figure_loso(), figure_site_map(), figure_skill_by_horizon(), load(), load_ablation(), macros() (+17 more)

### Community 61 - "Download Export Pdf"
Cohesion: 0.17
Nodes (23): Image, _forecast_table(), _format_number(), Any, A point brief as a PDF. Rendering only — `services/brief.py` decides what a…, One brief, as PDF bytes., The forecast block is the one section with a real matrix shape, so it gets a…, render() (+15 more)

### Community 62 - "Dashboard Trend Ocean"
Cohesion: 0.12
Nodes (31): get_trends(), One variable's historical series at a point., _cached_response(), catalog(), _copernicus_series(), _endpoint(), multi_series(), Any (+23 more)

### Community 63 - "Metric Story Fact"
Cohesion: 0.10
Nodes (28): build(), _build_facts(), _generate(), _join(), Any, DataFrame, Ocean Story — the narrative at the top of every metric page. The design…, The story, written without an LLM. Both the fallback and the safety net. It… (+20 more)

### Community 64 - "Severe Weather Alert"
Cohesion: 0.14
Nodes (21): _active_alerts(), _Alert, _cached(), _Entry, _fetch_alerts(), get_active_alerts(), _get_text(), _haversine_km() (+13 more)

### Community 65 - "Forecasting Trainer Registry"
Cohesion: 0.07
Nodes (49): BaselineConfig, get_config(), Prophet, used for benchmarking only — never served as a forecast. Off by…, Process-wide config, parsed once. Cached because it is read on every request.…, clamp_to_coverage(), fetch(), fetch_recent(), HistoryRequest (+41 more)

### Community 66 - "Tile Gfw Field"
Cohesion: 0.14
Nodes (21): get_currents_depth_catalog(), get_currents_depth_field(), get_currents_field(), get_drift_field(), get_gfw_tile(), get_sst_tile(), get_stokes_field(), get_wind_field() (+13 more)

### Community 67 - "Brief Section Forecast"
Cohesion: 0.16
Nodes (22): _biodiversity_section(), _bloom_section(), build_brief(), _conditions_section(), _events_section(), _flow_section(), _forecast_section(), _habitat_section() (+14 more)

### Community 68 - "Field Sampling Cell"
Cohesion: 0.08
Nodes (40): angular_difference(), build_sampler(), cell_edges(), cell_spacing_m(), d_dx(), d_dy(), is_globally_periodic(), DataArray (+32 more)

### Community 69 - "Severe Weather Endpoint"
Cohesion: 0.09
Nodes (11): RuntimeError, The route could not be planned — a real failure, not "no path found because the…, RoutingError, RuntimeError, The IMD CAP feed could not be reached, or answered with nothing usable., SevereWeatherError, asyncio, routers/tools.py: thin-router checks over the five previously chat-only… (+3 more)

### Community 70 - "Copernicu Wind Fakearray"
Cohesion: 0.11
Nodes (17): FakeArray, FakeDataset, opened(), fixture, ndarray, The wind timestep screen. This product routinely publishes a day of time-index…, The newest usable timestep is the one wanted, so ordering is the answer., Better to raise than to cache a grid of NaN and call it wind. (+9 more)

### Community 71 - "Feature Assistant Thread"
Cohesion: 0.11
Nodes (23): INLINE_RULES, InlineRule, isTableDivider(), Markdown(), flushParagraph(), renderInline(), splitRow(), ShinyText() (+15 more)

### Community 72 - "Climatology Percentile Day"
Cohesion: 0.15
Nodes (20): apply_percentiles(), build_climatology(), ClimatologyBuildError, day_index(), fit_percentiles(), DataArray, date, datetime (+12 more)

### Community 73 - "Dashboard Quality Fold"
Cohesion: 0.05
Nodes (53): build(), _cache_state(), _CacheState, _cadence_label(), coverage(), DataQualityError, datasets(), _grade_from_skill() (+45 more)

### Community 74 - "Eddy Detection Mean"
Cohesion: 0.22
Nodes (13): _circular_mean_longitude(), detect(), Detection, _empty_detection(), _label_with_wrap(), okubo_weiss(), ndarray, Mesoscale eddy detection from the live surface-current field. The platform… (+5 more)

### Community 75 - "Forecast Warm Variable"
Cohesion: 0.18
Nodes (20): _catalog(), _Entry, _one_point(), asyncio, fixture, The forecast cache pre-warmer. What matters here is not that it warms — that is…, Not every upstream failure arrives as a `ForecastingError` — an httpx or zarr…, The catalog reads the model directory. A deploy with no models at all is a real… (+12 more)

### Community 76 - "Routing Hazard Raise"
Cohesion: 0.20
Nodes (20): _install_bathymetry(), _install_hazard(), asyncio, services/routing.py: A* over a live grid. No network is touched:…, The start point is trusted as navigable by design (see…, Real geofencing data (Malvan Marine Sanctuary), synthetic open water — the MPA…, Both ends sit either side of the real, treaty-sourced IMBL (Palk Strait / Gulf…, A band of high wave height across most of the box, gapped only near its… (+12 more)

### Community 77 - "Biodiversity Box Point"
Cohesion: 0.17
Nodes (19): at_point(), BiodiversityError, _box(), _box_area_km2(), _cached(), _Entry, _get(), Any (+11 more)

### Community 78 - "Copernicu Chlorophyll Current"
Cohesion: 0.10
Nodes (26): healthcheck(), lifespan(), get, get_vessel_feed_status(), get_vessels(), get, Vessels currently known inside the viewport, as GeoJSON. Reads an in-memory…, _build_interpolator() (+18 more)

### Community 79 - "Vector Field Copernicu"
Cohesion: 0.15
Nodes (17): anomaly_field(), This cache's live field, scored against a climatology fitted on the Copernicus…, axis_after_block_mean(), block_mean(), build_interpolator(), _edges(), encode(), FieldTexture (+9 more)

### Community 80 - "Dashboard Health Probe"
Cohesion: 0.16
Nodes (20): build(), _cache_probe(), detail(), _evaluate(), _explain(), HealthError, _history_key(), _predictions_probe() (+12 more)

### Community 81 - "Forecast Grid Forecasting"
Cohesion: 0.05
Nodes (61): output_grid(), Cell centres of the canonical global grid. Centres rather than edges, so a…, Delete entries too old for anything to reuse. Returns how many went. **This…, sweep_cache(), clear_model_cache(), Drop cached models — call after retraining in a long-lived process., _alpha_row(), cache_dir() (+53 more)

### Community 82 - "Stoke Drift Vector"
Cohesion: 0.13
Nodes (13): _spec(), Stokes drift, as a live particle field. The wave-induced mean transport of a…, This field's cached grid, for `services/drift.py`., snapshot(), StokesDriftError, RuntimeError, One live U/V field from Copernicus: fetch, cache, texture, point lookup.…, A live vector field is unavailable. Subclassed per field so a router can keep… (+5 more)

### Community 83 - "Dashboard Alert Formatting"
Cohesion: 0.22
Nodes (17): _alert(), _alert_id(), _bloom_alerts(), build(), _coral_alerts(), _heat_stress_alerts(), Any, Dashboard alerts, derived from thresholds on real fields. Every alert here is a… (+9 more)

### Community 84 - "Feedback Security Name"
Cohesion: 0.14
Nodes (15): FeedbackRequest, BaseModel, field_validator, post, Request, `name` is interpolated into the Subject header downstream. Python's email…, submit_feedback(), FeedbackError (+7 more)

### Community 85 - "Openmeteo Port Ocean"
Cohesion: 0.26
Nodes (17): _clean_string(), Coordinates, _extract_ocean_name(), _fetch_json(), _fetch_location_context(), _fetch_marine_current(), _fetch_weather_current(), get_realtime_ocean_conditions() (+9 more)

### Community 86 - "Drift Term Wind"
Cohesion: 0.13
Nodes (16): fixture, The combined drift field. The properties worth pinning here are the ones that…, A cell with current but no Stokes drift stays empty. The tempting alternative —…, A composite is only as current as its oldest input. Reporting the newest would…, A wind reported as "from the north" must push water southward. The one place in…, Leeway at alpha=0 contributes nothing, so its absence must not blank a point…, Current and Stokes drift add as vectors, not as speeds. The case chosen is the…, _snapshot() (+8 more)

### Community 87 - "Dashboard Trend Report"
Cohesion: 0.18
Nodes (17): Any, datetime, A short rolling history of KPI values, so the cards can show real sparklines.…, Append a KPI reading, subject to the throttle. Non-numeric values are ignored., Recorded points for one KPI, oldest first., Change across the recorded window. Returns None with fewer than two points — a…, Drop all history. Used by tests., record() (+9 more)

### Community 88 - "Forecasting Retried 404"
Cohesion: 0.14
Nodes (18): BaseException, is_retryable(), Whether another attempt could plausibly succeed. Retrying a *permanent* failure…, Exception, parametrize, A provider error wrapping an HTTP status, as the adapters raise them., The bug this classification exists to prevent. An upstream dataset answering…, 404 is the one ambiguous code, and the budget is what keeps it cheap. ERDDAP… (+10 more)

### Community 89 - "Metric Statistic Change"
Cohesion: 0.12
Nodes (22): _absent(), build(), _change_over(), compute(), _iso(), Any, DataFrame, date (+14 more)

### Community 90 - "Forecasting Quality Artifact"
Cohesion: 0.11
Nodes (33): delete(), describe(), exists(), list_trained(), load(), model_dir(), ModelDescription, ModelNotTrainedError (+25 more)

### Community 91 - "Metric Forecasting Variable"
Cohesion: 0.13
Nodes (25): HistoryError, ProviderUnavailableError, History could not be assembled for the requested point/variables. Means the…, An upstream provider failed the request (timeout, 5xx, auth). Deliberately…, get_ranges(), get_series(), get_statistics(), get_story() (+17 more)

### Community 92 - "Copernicu Sst Colormap"
Cohesion: 0.10
Nodes (29): get_sst_meta(), get_sst_point(), Generic continuous-value -> RGB colormap builder. Deliberately not SST-…, _build_interpolator(), CopernicusSstError, _fetch_latest_grid(), get_meta(), get_point() (+21 more)

### Community 93 - "Current Depth Field"
Cohesion: 0.20
Nodes (16): catalog(), _ensure_warming(), get_field_png(), get_meta(), get_point(), is_available(), is_refreshing(), Any (+8 more)

### Community 94 - "Correlation Reported Variable"
Cohesion: 0.12
Nodes (3): services/correlation.py: the alignment + statistics, not the trends fetch…, Two same-day readings for one variable and one for the other must collapse to a…, test_multiple_hourly_points_on_the_same_day_are_averaged()

### Community 95 - "Backend Severe Weather Alert"
Cohesion: 0.30
Nodes (15): _cap(), _install(), asyncio, The IMD CAP feed: RSS index -> per-alert CAP 1.2 XML -> active/point checks. No…, CAP requires `expires` on a real alert; a malformed one without it must not be…, test_a_cancel_message_is_excluded(), test_a_fetch_failure_raises_severe_weather_error(), test_a_not_yet_started_alert_is_excluded() (+7 more)

### Community 96 - "Download Copernicu Global"
Cohesion: 0.10
Nodes (33): Dataset, One cell, shaped like `history._fetch_frame`'s fetch result. Nearest-selection…, _choose_base(), _merge_provider_datasets(), Pick the provider whose grid every other provider is resampled onto. The finest…, Combine whichever providers were fetched onto one shared grid and time axis.…, _bounded_load(), _coarsen() (+25 more)

### Community 97 - "Backend Eddy Tracking Track"
Cohesion: 0.34
Nodes (13): _detection(), _eddy(), datetime, Frame-to-frame identity assignment, checked against controlled synthetic…, An anticyclonic eddy appearing exactly where a cyclonic one just was is a…, test_a_missed_frame_does_not_break_the_track(), test_a_repeated_timestamp_is_idempotent(), test_a_single_eddy_is_tracked_across_frames() (+5 more)

### Community 98 - "Compare Delta Section"
Cohesion: 0.17
Nodes (13): Comparing two coordinates. The whole output of this feature is a difference, so…, Latitude +3.0°, +30.3%" parses perfectly and means nothing. It restates the…, 1,204 m" must parse as 1204, not as 1. Exactly the failure…, A subtraction across mismatched units is the one output here that would be…, The asymmetry is often the most informative part of the comparison —…, _section(), test_a_row_only_one_point_has_is_kept_and_labelled(), test_a_thousands_separator_does_not_become_a_hundredfold_error() (+5 more)

### Community 99 - "Marine Risk Escalate"
Cohesion: 0.22
Nodes (15): _patch_all_clear(), services/marine_risk.py: the fixed rule table, not the live services it…, A calm-sea reading arriving after a cyclone hit must not walk the verdict back…, Any active alert covering this exact point is never nothing, even at IMD's…, test_a_distant_cyclone_outside_the_watch_radius_does_not_escalate(), test_a_failed_check_is_recorded_but_never_escalates_the_verdict(), test_caution_waves_escalate_to_moderate_only(), test_every_response_carries_the_fixed_rule_note() (+7 more)

### Community 100 - "Training Record Mlflow"
Cohesion: 0.22
Nodes (15): datetime, parametrize, Path, The training CLI must not destroy the previous run's report.…, The regression. Before this, the second batch destroyed the first., The ingester reads these in order; a timestamp that sorts wrong would silently…, A result has to map back to the code that produced it., The boundary this whole design exists to preserve. `machine_learning/` is kept… (+7 more)

### Community 101 - "Middleware Logging Id"
Cohesion: 0.15
Nodes (12): bind_request_id(), Set the id for the current context, and patch loguru to emit it. The patch is…, current_request_id(), Request, Response, Request correlation and the access log. One middleware, doing the two things…, The id of the request being served, or "-" outside one., Binds a request id for the duration of the request and logs the result. (+4 more)

### Community 102 - "Upwelling Upwellingfield Corroboration"
Cohesion: 0.23
Nodes (9): at_point(), _point_corroboration(), Any, One pass over one pair of snapshots., One cell's corroboration state. See `CORROBORATION_STATES`., How much of the favourable coast the water agrees with. Kept out of `coverage`,…, Upwelling state at one coordinate, for the point brief. Answers for open ocean…, The corroboration block for one cell. (+1 more)

### Community 103 - "Climatology Path Available"
Cohesion: 0.24
Nodes (13): Gridded percentile climatology — the baseline the platform did not have. **This…, available(), climatology_path(), ClimatologyNotBuilt, load(), Path, RuntimeError, Where a fitted climatology lives, and how it is read back. Deliberately **not**… (+5 more)

### Community 104 - "Cyclone Chat Active"
Cohesion: 0.30
Nodes (14): cyclones(), Stand in for the GDACS cyclone-check provider `_cyclone_alerts` calls., _feature(), _install(), asyncio, GDACS-backed active-cyclone tracking. No network is touched: `cyclones._get` is…, GDACS's `eventtypes` query param does not reliably filter server-side (measured…, test_a_distant_storm_is_not_within_the_watch_radius() (+6 more)

### Community 105 - "Copernicu Sst Grid"
Cohesion: 0.09
Nodes (19): cache(), _grid(), fixture, ndarray, The SST cache's memory shape, and the statistics read back out of it. This…, A small, fast-to-fit climatology — the point of these tests is…, `copernicus_sst.anomaly_field()`: the live cache scored against the Copernicus-…, The two climatologies must never collide under one key — see… (+11 more)

### Community 106 - "Package Override Name"
Cohesion: 0.15
Nodes (12): name, overrides, @maplibre/geojson-vt, private, scripts, build, dev, export-docs (+4 more)

### Community 107 - "Forecast Tile Vector"
Cohesion: 0.21
Nodes (13): get_catalog(), get_forecast_point(), get_forecast_tile(), get_vector_catalog(), get_vector_field(), get_vector_meta(), get_vector_point(), get (+5 more)

### Community 108 - "Compare Row Forecast"
Cohesion: 0.25
Nodes (13): _compare_forecast_row(), compare_points(), _compare_section(), _delta(), _parse_quantity(), Any, Two coordinates, side by side. The dashboard answers "what is happening…, One forecast variable across both points, horizon by horizon. Forecast rows are… (+5 more)

### Community 109 - "Dashboard Live Buoy"
Cohesion: 0.33
Nodes (12): Dashboard aggregation services. Each module answers one dashboard section and…, _age_seconds(), build(), _buoys(), _copernicus(), _coral(), _entry(), _ocean_state() (+4 more)

### Community 110 - "Dashboard Summary Card"
Cohesion: 0.32
Nodes (13): _bleaching_card(), build(), _card(), _field_card(), _habitat_card(), _heatwave_card(), Any, The dashboard's KPI row — six headline numbers about the global ocean. Every… (+5 more)

### Community 111 - "Copernicu Current Marine"
Cohesion: 0.19
Nodes (9): get_currents_meta(), get_currents_point(), CopernicusCurrentsError, get_meta(), get_point(), Any, Copernicus Marine surface currents, as a live particle field. Now a *binding*…, This field's cached grid, for `services/drift.py`. (+1 more)

### Community 112 - "Docs Chapter Search"
Cohesion: 0.28
Nodes (11): Chapter, getSearchIndex(), IndexEntry, renderToText(), searchChapters(), SearchResult, snippetAround(), textOf() (+3 more)

### Community 113 - "Oxlintrc Rule Package"
Cohesion: 0.20
Nodes (9): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, typescript, oxc, warn (+1 more)

### Community 114 - "Climatology Testfit Nan"
Cohesion: 0.23
Nodes (7): range, Land must not become 0. `nanpercentile` over an all-NaN column warns and…, A thin estimate has to be visible. Index 60 is leap-years-only, and a reader…, A synthetic daily record on a tiny global-width grid., The arithmetic, checked against numpy on exactly the rows the window should…, _record(), TestFit

### Community 115 - "Chat Session SSE"
Cohesion: 0.18
Nodes (14): ChatRequest, ChatTurn, delete_session(), get_session(), get_sessions(), post_chat(), post_chat_stream(), BaseModel (+6 more)

### Community 116 - "Prediction Habitat Hab"
Cohesion: 0.27
Nodes (11): get_hab_point(), get_hab_tile(), get_habitat_point(), get_habitat_tile(), get_manifest(), get, ML prediction endpoints — habitat suitability and bloom risk. Thin, per the…, Available products, their measured skill, drivers and caveats. (+3 more)

### Community 117 - "Climatology Copernicu S3"
Cohesion: 0.12
Nodes (22): Widen botocore's connection pool for the Copernicus zarr reads. The symptom is…, Raise the default `max_pool_connections` for new botocore clients. Idempotent,…, widen_s3_connection_pool(), _configure_logging(), _configure_logging(), _fetch_month_with_retry(), main(), date (+14 more)

### Community 118 - "Biodiversity Box Pole"
Cohesion: 0.17
Nodes (7): OBIS biodiversity at a point. Nothing here calls OBIS. What is worth pinning is…, A fixed-degree box is a different area at different latitudes, which is exactly…, The note is a required field, not small print. These counts measure survey…, Most of the open ocean has never been sampled. Reporting that as an error, or…, test_a_report_carries_the_bias_note(), test_an_empty_box_is_an_answer_not_a_failure(), test_box_area_shrinks_toward_the_poles()

### Community 119 - "Hook Reveal Landing"
Cohesion: 0.22
Nodes (9): prefersReducedMotion(), useReveal(), Closing(), Coverage(), Forecasting(), Metrics(), Platform(), Research() (+1 more)

### Community 120 - "Marine Risk Assess"
Cohesion: 0.47
Nodes (10): RiskLevel, assess(), _assess_conditions(), _assess_cyclone(), _assess_geofence(), _assess_severe_weather(), _escalate(), Any (+2 more)

### Community 121 - "Research Artifact Ablation"
Cohesion: 0.33
Nodes (10): _ablation_facts(), build(), hero_chart(), load(), mermaid(), pretty(), DataFrame, Numbers from the seasonality ablation, or dashes if it has not been run. Kept… (+2 more)

### Community 122 - "Eddy Tracking Current"
Cohesion: 0.18
Nodes (12): current_detection(), EddyError, get_eddies(), nearest(), Any, RuntimeError, Eddy detection is unavailable — almost always because the surface currents…, The detection for the currents cache's current timestep. Computed on demand… (+4 more)

### Community 123 - "Brief Pdf Compare"
Cohesion: 0.31
Nodes (9): get_brief(), get_brief_pdf(), get_compare(), get, Point brief — one coordinate as a document. Thin, like every router here: the…, Two coordinates aligned row by row, with deltas where they are defined. Under…, BriefError, RuntimeError (+1 more)

### Community 124 - "Export Docs Routercontext"
Cohesion: 0.29
Nodes (7): __dirname, ENTITIES, entries, htmlToText(), outPath, ROUTER_VALUE, RouterContext

### Community 125 - "Docs Query Nothing"
Cohesion: 0.27
Nodes (5): services/docs.py: word-overlap search over the exported docs index. The real…, test_a_title_match_outranks_a_body_only_match(), test_limit_caps_the_number_of_results(), test_the_snippet_centres_on_the_first_match_not_the_chapter_start(), _use_index()

### Community 126 - "Database Session Async"
Cohesion: 0.36
Nodes (9): _get_async_database_url(), get_async_db(), _get_async_engine(), get_async_session_factory(), _get_async_session_local(), get_db(), _get_engine(), _get_session_local() (+1 more)

### Community 127 - "Measure Sst Corroboration"
Cohesion: 0.47
Nodes (5): _contrasts(), main(), Re-run of `services/sst_anomaly.py`'s own control measurement, against…, The exact methodology `sst_anomaly.py`'s docstring table used, replicated here…, run()

### Community 128 - "Forecasting Historysery End"
Cohesion: 0.50
Nodes (3): HistorySeries, A point time series plus the provenance a forecast has to carry., Timestamp

### Community 129 - "Docs Word Search"
Cohesion: 0.33
Nodes (8): DocChapter, _load(), Search over MarisAI's own documentation, for the assistant's…, An excerpt around the earliest query-word match, not the chapter start. The…, Rank documentation chapters by word overlap with `query`. Word-overlap rather…, search(), _snippet(), _words()

### Community 130 - "Climatology Testoisst Query"
Cohesion: 0.22
Nodes (4): `providers/gebco.py` records a fronting Tomcat 400ing on a bare `[`., A deliberate departure from `forecasting/history.is_retryable`, which allows…, A first draft retried on 2s/4s and lost a whole year's fetch inside six…, TestOisst

### Community 131 - "Eddy Bbox 123"
Cohesion: 0.50
Nodes (4): Eddy, _in_bbox(), One detected rotating feature., Whether an eddy centre falls inside (south, west, north, east). East < west…

### Community 132 - "Climatology Testserving Output"
Cohesion: 0.25
Nodes (4): The output shape exists to be served by the existing sampler. If this breaks,…, A regional grid must not be wrapped and a global one must be. The climatology…, Not a FileNotFoundError: the caller's correct response is a 503 with the build…, TestServing

### Community 133 - "Climatology Baseline Testbuild"
Cohesion: 0.29
Nodes (3): A percentile fitted on 12 of 30 years is not the baseline it claims to be, and…, The fit/apply split only helps if the fit actually restricts., TestBuild

### Community 134 - "Climatology Testsamplefloor Year"
Cohesion: 0.29
Nodes (4): The guard that replaced a wrong one. A per-year completeness check was written…, Half of 1993's days removed, mimicking the real archive. The build must still…, A '1991-2020 baseline' built on a gappy archive is not 10,957 days, and a…, TestSampleFloor

### Community 135 - "Climatology Testdayindex Year"
Cohesion: 0.29
Nodes (3): The whole point of the leap adjustment. `pandas` gives 1 March dayofyear 60 in…, 31 December is the last index either way, which is what makes the circular…, TestDayIndex

### Community 136 - "Pfz Sst Chlorophyll"
Cohesion: 0.33
Nodes (3): _grid_point(), services/pfz.py: the heuristic PFZ scan over the cached SST/chlorophyll grids.…, test_ranks_a_high_chlorophyll_favourable_sst_cell_first()

### Community 137 - "Chat Engine Client"
Cohesion: 0.50
Nodes (4): client_id(), fresh_engine(), fixture, Dispose the async engine between tests. The engine and its pool are module-…

### Community 138 - "Brief Offline Fixture"
Cohesion: 0.67
Nodes (3): offline(), fixture, Every upstream unavailable. The interesting case, not the degenerate one: a…

### Community 139 - "Climatology Testapply Anomaly"
Cohesion: 0.33
Nodes (3): Tests for the gridded percentile climatology. The two constructions worth…, Letting xarray align would drop the non-matching cells silently., TestApply

### Community 140 - "Alembic Env Migration"
Cohesion: 0.20
Nodes (9): include_object(), Filter out system objects created by PostGIS and default system schemas so…, Run migrations in offline mode., Run migrations in online mode., run_migrations_offline(), run_migrations_online(), Application configuration., Settings (+1 more)

### Community 141 - "Apply Shipping Bar"
Cohesion: 0.11
Nodes (25): _disk_get(), _disk_path(), _disk_put(), _fetch_frame(), _fetch_with_retry(), frozen_cache(), _memory_get(), _memory_put() (+17 more)

### Community 143 - "Pfz Zone Candidate"
Cohesion: 0.50
Nodes (4): _candidate_grid(), find_zones(), Any, Potential Fishing Zone screening: "where near here looks favourable".…

### Community 147 - "Eddy Tracking State"
Cohesion: 0.67
Nodes (3): fixture, Module-level state, reset between tests the same way the cache-backed services…, _reset_tracking_state()

### Community 160 - "Docs Chapter Primitive"
Cohesion: 0.07
Nodes (55): DocsPage, AppRouter(), EntryState, nextEntryKey(), readEntryKey(), readLocation(), scrollPositions, Assistant() (+47 more)

### Community 161 - "Feature Assistant Map"
Cohesion: 0.13
Nodes (30): ChatStreamEvent, ChatStreamMeta, streamChat(), StreamChatArgs, url(), AssistantPage(), EASE, EMPTY (+22 more)

### Community 162 - "Feature Dashboard Hook"
Cohesion: 0.07
Nodes (51): fetchAlerts(), fetchDataQuality(), fetchHealth(), fetchLive(), fetchSatellites(), fetchSourceDetail(), fetchStationDetail(), fetchSummary() (+43 more)

### Community 163 - "Feature Map Layer"
Cohesion: 0.06
Nodes (29): BLOOM_RISK_STOPS, bloomRiskLayerId(), bloomRiskLayers(), compositeDates(), currentMonth(), CYCLONE_COLOR, DRIFT_PRESETS, EDDY_COLOR (+21 more)

### Community 164 - "Feature Dashboard Metric"
Cohesion: 0.06
Nodes (51): App(), ChatPage, ContactPage, MetricsIndexPage, ModelDossierPage, normalizePath(), renderPage(), SatelliteDossierPage (+43 more)

### Community 165 - "Package React Devdependency"
Cohesion: 0.13
Nodes (15): oxlint, devDependencies, oxlint, tsx, @types/node, @types/react, @types/react-dom, vite (+7 more)

### Community 166 - "Frontend Feature Dashboard Metric"
Cohesion: 0.06
Nodes (74): MetricIntelligencePage, OceanIntelligenceDashboard, AiInsights(), Status, ageSeconds(), AlertRow(), AlertsPanel(), DashboardMap() (+66 more)

### Community 167 - "Landing Diagram Split"
Cohesion: 0.11
Nodes (18): SplitText(), SplitTextProps, SpotlightCard(), SpotlightCardProps, useMagnetic(), AssistantGlyph(), DashboardGlyph(), DownloadGlyph() (+10 more)

### Community 168 - "Feature Map Format"
Cohesion: 0.08
Nodes (34): LiveClock(), generateOceanInsights(), readErrorDetail(), OceanInsightsResponse, fetchRealtimeOceanData(), normalizeRealtimeOceanResponse(), readErrorDetail(), CameraState (+26 more)

### Community 169 - "Feature Dashboard Format"
Cohesion: 0.17
Nodes (14): TrendRange, TrendVariable, downloadBlob(), METRIC_ALIASES, RANGE_ORDER, TrendChart, useTrend(), formatAxisTime() (+6 more)

### Community 170 - "Feature Map Download"
Cohesion: 0.07
Nodes (42): DownloadPage, DURATIONS, Toaster(), ToastRow(), Area, BboxArea, DownloadFile, DownloadHistoryEntry (+34 more)

### Community 171 - "Landing Archive Ocean"
Cohesion: 0.11
Nodes (25): band(), BirdItem, BubbleItem, buildBirds(), buildBubbles(), buildClouds(), buildFish(), buildJellies() (+17 more)

### Community 173 - "Tsconfig Compileroption Ref"
Cohesion: 0.07
Nodes (26): DOM, src, src/**/_archive/**, vite/client, compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly (+18 more)

### Community 175 - "Frontend Feature Dashboard Metric 175"
Cohesion: 0.18
Nodes (22): fetchBatchForecast(), fetchCatalog(), fetchForecast(), fetchModelDetail(), fetchSeries(), fetchStatistics(), fetchStory(), point() (+14 more)

### Community 176 - "Feature Map Hook"
Cohesion: 0.06
Nodes (58): Cyclone, CyclonesResponse, cyclonesToGeoJson(), fetchCyclones(), url(), fetchHeatwaveCells(), fetchUpwellingCells(), HeatwaveCell (+50 more)

### Community 177 - "Frontend Feature Map Layer"
Cohesion: 0.12
Nodes (8): CATEGORY_ORDER, LayerManager, LayerState, summariseTileError(), layerRegistry, LayerCategory, LayerDescriptor, createEmitter()

### Community 178 - "Frontend Feature Map Layer 178"
Cohesion: 0.08
Nodes (35): MapView, MapView, DepthResponse, fetchDepth(), fetchForecastGridCatalog(), fetchForecastPoint(), ForecastGridEntry, ForecastGridPoint (+27 more)

### Community 179 - "Feature Map Severe"
Cohesion: 0.07
Nodes (45): downloadBriefPdf(), url(), fetchHabitatPoint(), fetchHabPoint(), HabitatPoint, HabPoint, url(), fetchSevereWeatherAlerts() (+37 more)

### Community 181 - "Frontend Tsconfig Compileroption Ref"
Cohesion: 0.10
Nodes (19): node, vite.config.ts, compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection (+11 more)

### Community 182 - "Feature Map Compare"
Cohesion: 0.16
Nodes (18): ComparePage, CompareDelta, CompareForecastRow, ComparePoint, CompareResponse, CompareRow, CompareSection, fetchComparison() (+10 more)

### Community 183 - "Feature Map Forecast"
Cohesion: 0.19
Nodes (16): fetchForecastVectorMeta(), ForecastVectorEntry, forecastVectorFieldTextureUrl(), ForecastVectorMeta, ForecastVectorMode, url(), attributionFor(), forecastVectorLayerId() (+8 more)

### Community 184 - "Vector Field Feature"
Cohesion: 0.21
Nodes (13): COMPOSITE_FRAGMENT_SHADER, COMPOSITE_VERTEX_SHADER, DRAW_FRAGMENT_SHADER, DRAW_VERTEX_SHADER_BODY, UPDATE_FRAGMENT_SHADER, UPDATE_VERTEX_SHADER, createBuffer(), createFullscreenQuad() (+5 more)

### Community 185 - "Frontend Vector Field Feature"
Cohesion: 0.14
Nodes (8): asFloat32(), bindAttribute(), compileShader(), createDrawVAO(), createProgram(), createUpdateVAO(), loadTexture(), VectorFieldParticleLayer

### Community 186 - "Feature Dashboard Kpi"
Cohesion: 0.08
Nodes (26): react, AppProviders(), queryClient, Cursor(), isSupported(), Grain(), KineticText(), Marquee() (+18 more)

### Community 187 - "Landing Scroll Reveal"
Cohesion: 0.35
Nodes (8): prefersReducedMotion(), supportsViewTimeline(), useCountUp(), usePinnedProgress(), useScrollProgress(), Hero(), Metric(), rafThrottle()

### Community 189 - "Feature Map Vessel"
Cohesion: 0.19
Nodes (14): fetchVessels(), url(), VesselCollection, VesselProperties, HoveredVessel, LIVE_VESSELS_LAYER_ID, LiveVesselsState, VesselFeedStatus() (+6 more)

### Community 191 - "Frontend Feature Dashboard Metric 191"
Cohesion: 0.33
Nodes (8): bandPlugin(), ChartBand, ChartSeries, formatTick(), markerPlugin(), palette(), SeriesChart(), SeriesChartProps

### Community 192 - "Frontend Feature Map Hook"
Cohesion: 0.08
Nodes (34): fetchGeofence(), GeofenceProtectedArea, GeofenceResponse, url(), fetchPfz(), PfzResponse, PfzZone, url() (+26 more)

### Community 196 - "Feature Map Eddy"
Cohesion: 0.22
Nodes (11): EddiesResponse, eddiesToGeoJson(), EddyBounds, EddyFeatureProperties, fetchEddies(), url(), EddyDetectionStatus(), EddyTooltip() (+3 more)

### Community 199 - "Feature Map Vector"
Cohesion: 0.17
Nodes (19): currentsFieldTextureUrl(), CurrentsPointResponse, fetchCurrentsMeta(), fetchCurrentsPoint(), url(), fetchStokesMeta(), fetchStokesPoint(), stokesFieldTextureUrl() (+11 more)

### Community 202 - "Frontend Feature Map Hook 202"
Cohesion: 0.23
Nodes (13): buildMarkerInfrastructure(), clearMarkerData(), createPinImage(), emptyFeatureCollection(), ensureMarkerInfrastructure(), markerInfrastructure, setMarkerData(), setMarkerVisibility() (+5 more)

### Community 203 - "Feature Map Basemap"
Cohesion: 0.07
Nodes (21): GradientBar(), GradientLegend, useMapManager(), BASEMAP_BACKGROUND_LAYER_ID, BASEMAP_LAYER_ID, BasemapManager, ControlManager, ControlManagerOptions (+13 more)

### Community 208 - "Frontend Feature Map Basemap"
Cohesion: 0.12
Nodes (24): abyss, layers, bathymetry, layers, blueMarble, darkMarine, esriSatellite, basemaps (+16 more)

### Community 211 - "Landing Map Descent"
Cohesion: 0.23
Nodes (10): Eyebrow(), bandOpacity(), CAPTIONS, CENTER, CURRENTS_IN, easeInOutCubic(), EDDIES_IN, lerp() (+2 more)

### Community 212 - "Feature Map Drift"
Cohesion: 0.27
Nodes (10): driftFieldTextureUrl(), DriftMetaResponse, DriftPointResponse, DriftTerm, fetchDriftMeta(), fetchDriftPoint(), fetchLeewayPresets(), LeewayPreset (+2 more)

### Community 213 - "Feature Map Feedback"
Cohesion: 0.29
Nodes (8): FeedbackPage, extractErrorMessage(), FeedbackRequest, sendFeedback(), url(), FeedbackPage(), handleSubmit(), Status

### Community 214 - "Error Boundary Errorboundary"
Cohesion: 0.20
Nodes (3): ErrorBoundary, ErrorBoundaryProps, ErrorBoundaryState

### Community 216 - "Feature Map Wind"
Cohesion: 0.28
Nodes (10): fetchWindMeta(), fetchWindPoint(), url(), windFieldTextureUrl(), WindMetaResponse, WindPointResponse, createWindParticleLayer(), BEAUFORT_BANDS (+2 more)

### Community 217 - "Feature Map Current"
Cohesion: 0.36
Nodes (8): CurrentsMetaResponse, currentsDepthFieldTextureUrl(), CurrentsDepthLevel, CurrentsDepthMetaResponse, fetchCurrentsDepthCatalog(), fetchCurrentsDepthMeta(), url(), createCurrentsDepthParticleLayer()

### Community 219 - "Package React Dependency"
Cohesion: 0.08
Nodes (25): @assistant-ui/react, class-variance-authority, clsx, framer-motion, gsap, @gsap/react, ogl, dependencies (+17 more)

### Community 223 - "Landing Hero Field"
Cohesion: 0.40
Nodes (5): flow(), HeroField(), draw(), HeroFieldProps, Particle

## Knowledge Gaps
- **288 isolated node(s):** `Specialist`, `EntryState`, `Heading`, `CalloutKind`, `TableProps` (+283 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Dataset` connect `Download Copernicu Global` to `Forecasting Grid Predictor`, `Heatwave Testduration Testsstanomaly`, `Download Limit Export`, `Chat Session Variable`, `Download Catalog Cleaning`, `Apply Shipping Bar`, `Grid Cache Forecasting`, `Forecast Tile Colormap`, `Sst Anomaly Heatwave`, `Climatology Copernicu Reanalysi`, `Download Cadence Field`, `Forecast Vector Tile`, `Derived Testgrid Testconvention`, `Field Sampling Prediction`, `Climatology Oisst Recent`, `Download Gebco Depth`, `Forecasting Derived Forecast`, `Download Openmeteo Edna`, `Climatology Percentile Day`, `Climatology Path Available`, `Copernicu Sst Grid`, `Climatology Testfit Nan`, `Climatology Copernicu S3`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `react` connect `Feature Dashboard Kpi` to `Docs Chapter Primitive`, `Feature Assistant Map`, `Feature Dashboard Hook`, `Feature Dashboard Metric`, `Frontend Feature Dashboard Metric`, `Landing Diagram Split`, `Feature Map Format`, `Feature Dashboard Format`, `Feature Map Download`, `Landing Archive Ocean`, `Feature Map Hook`, `Frontend Feature Map Layer 178`, `Feature Map Severe`, `Feature Map Compare`, `Landing Scroll Reveal`, `Feature Map Vessel`, `Frontend Feature Dashboard Metric 191`, `Frontend Feature Map Hook`, `Feature Map Eddy`, `Feature Assistant Thread`, `Frontend Feature Map Hook 202`, `Feature Map Basemap`, `Landing Map Descent`, `Feature Map Feedback`, `Error Boundary Errorboundary`, `Feature Map Wind`, `Landing Hero Field`, `Landing Archive Dive`, `Docs Chapter Search`, `Oxlintrc Rule Package`, `Export Docs Routercontext`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `client()` connect `Download Openmeteo Edna` to `Severe Weather Alert`, `Severe Weather Endpoint`, `Biodiversity Box Point`, `Dashboard Station Raw`, `Openmeteo Port Ocean`, `Cyclone Point Severe`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **What connects `Specialist`, `EntryState`, `Heading` to the rest of the system?**
  _288 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Forecasting Preprocessing Outlier` be split into smaller, more focused modules?**
  _Cohesion score 0.10317460317460317 - nodes in this community are weakly interconnected._
- **Should `Forecasting Registry Predictor` be split into smaller, more focused modules?**
  _Cohesion score 0.04295704295704296 - nodes in this community are weakly interconnected._
- **Should `Forecasting Uncertainty Interval` be split into smaller, more focused modules?**
  _Cohesion score 0.1168091168091168 - nodes in this community are weakly interconnected._