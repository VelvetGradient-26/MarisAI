# MarisAI — Map Rendering (basemaps, vector fields)

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Basemaps (`features/map/basemaps/`) come in two kinds and
  `BasemapDefinition` is a discriminated union on `kind`:
  - **`raster`** (Satellite, Blue Marble, Dark Marine) — one source, one
    layer. Inherently tiled: zoom scales the current bitmap until the next
    zoom level loads, so there is a blur-then-pop that no tuning removes.
    Blue Marble is also `maxzoom: 8`, so past that it is upscaled blur.
  - **`vector`** (Abyss, Bathymetry — the defaults) — many sources, ~13-14
    style layers, GPU-rendered geometry redrawn every frame at the exact
    fractional zoom. This is what makes zoom continuous. Backed by
    OpenFreeMap's keyless OpenMapTiles vector tiles.
  - `BasemapManager` tracks exactly what it added (`activeLayerIds` /
    `activeSourceIds`) rather than assuming a fixed source/layer pair, and
    tears layers down *before* sources — a source still referenced by a
    layer cannot be removed.
  - **OpenMapTiles has no landmass polygon.** Land is the *background* and
    `water` is drawn on top of it. Building a style the intuitive way round
    (ocean background + land fill) renders a uniformly blue planet with a few
    scattered forest patches, because `landcover` only carries wood/grass/ice.
  - Only `Noto Sans Regular` and `Noto Sans Bold` are served. `Noto Sans
    Medium` 404s, and a missing fontstack makes MapLibre silently drop the
    entire text layer.
  - Land/ocean contrast has to be exaggerated well past print-map norms or
    continents do not read from orbit — the first pass used colours a few
    luminance points apart and rendered as one flat mass.
- **`MapManager` observes its container's size.** MapLibre's `trackResize`
  only listens to *window* resize, so a map whose container changes size on
  its own is never told. That is exactly the dashboard's embedded panel: it
  lazy-loads into a flex column whose height settles after the map is
  constructed, so the canvas kept a stale size and the panel rendered blank.
  The `/map` route never hit this because it is full-viewport and correctly
  sized from the start. A `ResizeObserver` on the container fixes it; do not
  remove it.
- **Never call `map.setGlyphs()` mid-session.** It triggers an asynchronous
  style reload, and sources/layers added in the same tick are intermittently
  lost — the symptom is a basemap that comes up as an empty disc with no
  coastlines and no selected-location marker. Glyphs are set once in the
  initial style in `MapManager`; both vector basemaps use the same endpoint,
  so there is nothing to switch at runtime.
- **Source specs are `structuredClone`d before `addSource`.** The basemap
  source objects are module-level singletons shared by both vector basemaps
  *and* by every concurrent map instance (the `/map` view and the dashboard
  panel can be alive at once). MapLibre annotates a spec it is handed — it
  resolves a TileJSON `url` into `tiles`, among other things — so passing the
  shared object lets one map mutate state another is still using.
- **There is deliberately no 3D terrain.** It was built and removed. The
  reason it cannot work here is worth keeping: MapLibre drapes raster
  overlays onto the terrain mesh, and on a bathymetric DEM that mesh is the
  *seafloor*, so SST at 1.6x exaggeration ended up ~16 km below the camera
  and vanished. Verified by setting `exaggeration: 0`, at which the same
  layer rendered perfectly. Sea-surface data and raised seafloor geometry are
  mutually exclusive by construction — do not re-add `setTerrain` without
  solving that first.
  - The DEM itself survives in `basemaps/terrainSource.ts`, used only for
    Bathymetry's flat `hillshade` layer. That shades the seafloor without
    displacing geometry, so it does not affect overlays at all.
- Map page (`features/map/`): `MapManager` owns the MapLibre instance;
  `LayerManager`/`BasemapManager`/`ControlManager` are child managers;
  `layerRegistry.ts` is the single source of truth for overlay layers
  (raster tile layers plus `CustomLayerInterface` GPU particle layers for wind
  and currents). `mapStore.ts` mirrors MapLibre one-way (components call manager
  methods; managers mutate the map then emit back into the store — the store
  never fights MapLibre for ownership).
- Vector-field particle layers (`features/map/vectorField/`,
  `services/vector_field.py`, `services/vector_source.py`,
  `services/copernicus_currents.py`, `services/stokes_drift.py`,
  `services/currents_depth.py`, `services/drift.py`,
  `services/forecast_vectors.py`) — one GPU engine over live wind, live surface
  currents, Stokes drift, currents at six depth levels, a combined drift field
  per drifting object, and forecast currents at each horizon plus their anchor.
  `VectorFieldParticleLayer` was already generic; what was *not* generic, and
  had to be fixed before a second field could exist, is below.
  - **`vector_source.py` owns fetch/cache/encode/point; a live field is a
    `VectorSourceSpec`.** `copernicus_wind` is the one field still hand-rolled,
    deliberately: its candidate-timestep probe is specific to an L4 blend that
    publishes a day of all-NaN placeholders. It exposes `snapshot()` so the
    combined drift field can sum it like any other.
  - **The combined drift field is a sum of components, never of bearings**
    (`services/drift.py`): `u_total = u_curr + u_stokes + alpha * u_wind`.
    - **`alpha` is leeway, and it belongs to the *object*, not the ocean** —
      ~1.5% of wind speed for a swamped hull, ~6% for an undrogued life raft. So
      it is a request parameter with named presets served from
      `/api/ocean/drift/presets`, never a constant baked into the field, and one
      map layer exists per preset. The two water terms are composed once per
      refresh and only the wind multiplier varies per alpha, so a preset switch
      costs one PNG encode rather than three interpolations.
    - **Coverage is the intersection of the two water terms, not the union.**
      Treating a missing Stokes cell as zero is not neutral: Stokes drift is
      largest in exactly the high-sea-state water where the wave product is most
      likely masked, so the substituted zero biases the field low where it
      matters most. Wind is deliberately *not* in the coverage test — it is
      defined over land, and leeway only ever adds to a cell that already has
      water in it.
    - **The reported timestamp is the *stalest* term**, not the freshest: a
      composite is only as current as its oldest input, and the wind blend
      routinely lags hours behind the hourly currents.
    - **It is a field, not a trajectory**, and the layer attribution says so.
      Particles advect against a single snapshot, which is correct for a
      streamline and wrong for a drift forecast — that needs a time-indexed
      texture stack or a server-side integrator, and an uncertainty envelope
      rather than one line. See TODO.md.
  - **The texture's geographic frame is data, not a constant.** `fieldUV()` in
    `shaders.ts` used to hardcode `u = (lon+180)/360, v = (90-lat)/180` —
    exactly right for the wind product and wrong for everything else.
    Copernicus's global physics grid (the currents source) runs **latitude -80
    to 90**; read with the global frame it would have stretched sampling
    latitude by 5.6% and advected every particle with water from the wrong
    place, while still covering the screen and still animating. Each texture
    now reports its outer cell edges (`lon_west`/`lon_east`/`lat_south`/
    `lat_north`, verified live at -80.0417..89.9583) and the shader takes them
    as a uniform. `onField()` rejects samples outside that frame, because the
    textures are `CLAMP_TO_EDGE` and a clamped read below 80degS returns the
    southernmost row — the Southern Ocean advected with Antarctic coastal
    water. The update and draw passes must apply the *same* test or a particle
    the update pass gave up on is still drawn for a frame.
  - **`VISUAL_SPEED_SCALE` became a uniform because the right value belongs to
    the field.** Wind's 1800 makes a typical 8 m/s wind read as ~40px/s.
    Currents run an order of magnitude slower (open ocean 0.1-0.4 m/s), so at
    1800 a 0.3 m/s current moves ~1.5px/s — about 4 pixels over a particle's
    3-second life, i.e. a still image. Currents use 12000.
  - **The currents ramp is single-hue amber, and the single hue is the point.**
    Both layers live in the stackable `flow` group and are meant to be read
    together, but wind's Windy-convention rainbow has already spent every hue,
    so no second rainbow can be told from it. What separates them is
    *structure* — one cycles hues, the other never leaves amber. It is also a
    correct sequential scale: lightness rises 0.149 -> 0.926 with no reversal
    and every stop clears 3:1 on the Abyss basemap (min 3.65), unlike the
    raster ramps in `colormaps.py` whose dark ends needed a hatch to rescue.
  - **Currents are named for where the water goes; wind for where it comes
    from.** The two conventions are 180deg apart, so the field is
    `direction_toward_deg`, not a bare `direction_deg`. Reusing wind's formula
    would have every arrow backwards and entirely plausible.
  - **The encoder/shader contract crosses a language boundary and nothing type-
    checks it.** `tests/test_vector_field.py` reimplements `fieldUV()` in
    Python and asserts the encoded texture decodes *that way* back to the
    velocity that went in. Every way this breaks is silent — the layer still
    downloads a texture, still animates, still looks like a plausible ocean.
  - **`block_mean` crops rather than requiring divisibility.** The physics grid
    is **2041** latitudes; the old reshape-based downsample raised `ValueError`
    on any even factor, and inside a fire-and-forget refresh task asyncio would
    have swallowed it, leaving the cache empty forever and every endpoint
    503-ing with nothing logged.
  - **Forecast wind particles now ship, and the route to them is the rule for
    the next pair.** They could not be derived from `wind_speed` +
    `wind_direction`: direction is *circular* while every step to the screen is
    linear — averaging 359deg and 1deg gives 180deg, so the field would have
    flowed backwards along every wrap (same root cause as the
    `current_direction` raster note above). The fix was to forecast the
    components, exactly as `current_u`/`current_v` already did: `wind_u`/
    `wind_v` are registry entries of their own over the downloader's Copernicus
    `eastward_wind`/`northward_wind`, plus a YAML block and a training run each.
    Never compose a vector layer out of a forecast *bearing*.
  - **A forecast vector layer is drawn exactly like its live counterpart, and
    the visual identity travels with the field.** `PAIR_VISUALS` in
    `layers/forecastVectorLayers.ts` maps the backend's pair key to a ramp and a
    speed scale; `createForecastVectorParticleLayer` (renamed from
    `…ForecastCurrents…`) takes them as an argument. Before that, every pair was
    drawn as currents — an 8 m/s wind field on a ramp whose domain ends at
    2 m/s is one flat top colour, and at currents' 12000 speed scale it advects
    ~265 px/s. **Both failures animate convincingly**, which is the whole
    hazard. The legend reads the same stops the particles are coloured by
    (clamped to the pair's own legend maximum), and the attribution reads the
    pair's `direction_convention` rather than asserting the oceanographic one.
  - **`services/forecast_vectors.py::PAIRS` registers a pair before its grids
    exist**, and `catalog()` reports it with a reason while a component is
    missing. That is why the wind pair became a live layer with no frontend
    edit the moment `wind_u`/`wind_v` were trained and built.

