# MarisAI Frontend

React 19 + TypeScript + Vite + MapLibre GL JS 6 + Zustand. Eight surfaces — a
map, a global dashboard, a page per metric, point analytics, a comparison, an
assistant, a bulk downloader and long-form docs — over one hand-rolled router
and one token file.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to the backend
npm run build      # tsc -b, then the production build
npm run lint       # oxlint
```

## Layout

```
src/
  app/            Hand-rolled router, providers, App shell
  components/     Navbar, toaster, error boundary, Markdown, reactbits/ (vendored)
  features/
    map/          The map engine: managers, layer registry, GPU vector fields
    dashboard/    Ocean Intelligence Dashboard + the per-metric pages
    assistant/    The chat thread
    insights/     LLM commentary panels
  pages/          Hand-rolled pages: landing, download, compare, feedback, docs/
  store/          Zustand: theme, timezone, map, map preferences, ui, toasts
  styles/         tokens.css — the one place a colour or type step is chosen
```

## The conventions that are load-bearing

**The router is hand-rolled**, not react-router: `app/router.tsx` (`AppRouter`
context, `Link`, `navigate`) plus `app/routerContext.ts`. `App.tsx` renders one
`<Navbar />` above a plain if/else on `pathname`.

**Route transitions exclude `/map`, deliberately.** `RouteTransition` cross-fades
pages with framer-motion but returns the map route unwrapped: a keyed animated
wrapper makes React remount `MapView` on every navigation, which destroys and
rebuilds the MapLibre WebGL context and discards the layer state
`mapPreferencesStore` exists to preserve. Everything else uses `mode="wait"`,
because overlapping two full-height pages makes the scrollbar jump.

**One shared `Navbar`, `position: fixed`.** Every page needs top padding
≥ `var(--navbar-h, 64px)` on its outermost content. On the map it is a floating
overlay — the map stays full-bleed `100vh` and only the overlaid panels get the
offset. Don't let a page grow its own header again.

**Per-page theming over one token file.** Each themed page defines its own
`--xx-*` custom properties plus a `.page--light` block and reads
`useThemeStore`. Those blocks now *alias* `styles/tokens.css` (`--ma-*`) rather
than restating literals: seven private palettes had drifted into four dark
canvases, four body greys and two accents, all visible while navigating under
one translucent navbar. A page can still deviate deliberately; it can no longer
deviate by accident. Theme is stamped as `data-theme` on `<html>` by `App.tsx`
**and** pre-stamped by an inline script in `index.html` reading the same
localStorage key, so the first paint is correct — change the key in one place
and you must change it in the other.

**No UI kit, no CSS framework, no form or date-picker library** — outside two
deliberate exceptions. `features/dashboard/` uses Tailwind v4 (imported without
preflight, with its own resets scoped to `.oid-root` and placed in `@layer base`
so a Tailwind utility can still win), React Query and Recharts.
`features/assistant/` uses `@assistant-ui/react`'s **headless primitives** only,
styled with the existing `pages/chat.css`. `components/reactbits/` is vendored
source, not a dependency — read its README before adding another; every one
needs its literal colours repointed at tokens and an explicit reduced-motion
path.

**Import `framer-motion`, never `motion`.** They are the same library under two
package names and installing both ships it twice.

**API clients live under `features/map/api/*.ts`** — yes, even the non-map ones
like `download.ts` and `feedback.ts`. That is established precedent; don't start
a second `api/` location.

## The map engine

`MapManager` owns the MapLibre instance; `LayerManager`, `BasemapManager` and
`ControlManager` are child managers. Managers never import Zustand — they emit
through a small pub-sub, and only `useMapManager` bridges those events into the
store. State flows one way: MapLibre → managers → store → components, and
nothing writes back into MapLibre except through a manager method.

**`layers/layerRegistry.ts` is the single source of truth for overlays.** Adding
a layer is an entry there, not a new component. Layers come in three kinds:
raster tiles, GeoJSON (vessels, eddies), and `CustomLayerInterface` GPU particle
layers for the vector fields. Forecast layers are the exception that proves the
rule — they exist only where a model is trained *and* its grid built, so
`hooks/useForecastGridLayers.ts` fetches the backend catalog and calls
`LayerManager.register()` at runtime. A newly built grid becomes a map layer
with no edit here.

### Layer z-order

`LayerCategory` is `'ocean' | 'flow' | 'ai' | 'reference'`, **bottom to top**,
with the basemap always beneath all four. Particle layers render above scalar
colour fields like SST; labels and boundaries stay legible above particles. The
original architecture document's own hierarchy diagram was ambiguous about
stacking direction, so this is a documented assumption rather than a settled
decision — `types/index.ts` points here for that reason.

The layer panel groups the same four categories, and one of them behaves
differently: **Ocean & Atmosphere is exclusive** (a dropdown — these are
full-coverage colour fields that would simply hide each other), while Wind &
Currents, Boundaries & Reference and AI (Experimental) stack freely.

### Vector fields

One GPU particle engine (`features/map/vectorField/`, WebGL2 transform feedback)
over an RGBA U/V texture encoded server-side. It draws live wind, surface
currents, Stokes drift, currents at six depths, a combined drift field per
drifting object, and the forecast pairs. Four things about it are not
negotiable:

- **The texture's geographic frame is data, not a constant.** Each texture
  reports its own outer cell edges and the shader takes them as a uniform.
  Hardcoding the wind product's frame stretched the currents grid's sampling
  latitude by 5.6% — while still covering the screen and still animating.
- **`VISUAL_SPEED_SCALE` belongs to the field.** Wind's 1800 makes 8 m/s read as
  ~40 px/s; currents run an order of magnitude slower, so at 1800 a 0.3 m/s
  current is a still image. Currents use 12000.
- **A forecast field is drawn exactly like its live counterpart.** Comparison is
  the only thing anyone wants from it, so `PAIR_VISUALS` in
  `layers/forecastVectorLayers.ts` carries the ramp and speed scale per pair, and
  the legend reads the same stops the particles are coloured by. Before that,
  forecast wind was drawn as currents: one flat top colour, advecting ~265 px/s.
  Both failures animate convincingly.
- **Currents are named for where the water goes; wind for where it comes from.**
  180° apart, and reusing wind's formula makes every arrow backwards and
  entirely plausible.

### MapLibre gotchas already paid for

- `new maplibregl.LngLatBounds(a, b)` treats its args literally as `(sw, ne)` —
  it does **not** sort them. Normalise min/max yourself.
- **Never call `map.setGlyphs()` mid-session.** It triggers an async style
  reload and sources added in the same tick are intermittently lost; the symptom
  is an empty disc with no coastlines.
- **Source specs are `structuredClone`d before `addSource`.** They are
  module-level singletons shared by both vector basemaps *and* by concurrent map
  instances (the `/map` view and the dashboard panel can be alive at once), and
  MapLibre annotates a spec it is handed.
- **`MapManager` observes its container's size.** MapLibre's `trackResize` only
  listens to *window* resize, so the dashboard's embedded panel — which settles
  its height after the map is constructed — kept a stale canvas and rendered
  blank. Don't remove the `ResizeObserver`.
- **There is deliberately no 3D terrain.** It was built and removed: MapLibre
  drapes raster overlays onto the terrain mesh, and on a bathymetric DEM that
  mesh is the *seafloor*, so SST ended up ~16 km below the camera. Sea-surface
  data and raised seafloor geometry are mutually exclusive by construction.

## Charts

Recharts on the small dashboard summaries; **uPlot (canvas) on the metric pages**,
because Recharts mounts a DOM node per point and degrades past ~5k while those
charts routinely carry thousands and must stay interactive while zooming. Three
traps this feature already fell into:

- **Never key a Recharts axis on a formatted label.** "4 Aug" repeats yearly, so
  hover resolved to the first matching category and the crosshair cycled through
  year one forever. Key on the raw timestamp, format via `tickFormatter`.
- **Recharts' entry animation is off here, deliberately.** It began before
  `ResponsiveContainer` settled its width, advanced its clip rect to ~12px of
  646 and stalled — correct paths, clipped to invisible.
- **Do not rely on `IntersectionObserver` alone for lazy mounting.** In this app
  it was constructed and observing but never fired, leaving every chart
  unmounted. `LazyMount` measures geometry directly on mount and on scroll.

## Docs (`pages/docs/`)

Long-form reference, one file per chapter under `chapters/`, listed in reading
order in `chapters/index.ts` — that list drives the sidebar, the pager and the
mobile picker, and there is no second place to update. Chapter selection lives
in the query string (`/docs?c=<id>`) so every chapter is bookmarkable and the
back button walks the reading order. The "on this page" rail is derived from the
rendered DOM rather than a declared heading list, which would be a second source
of truth that goes stale the first time someone edits a heading.

Chapters are written against the tiny presentational primitives in
`primitives.tsx` (`Callout`, `Term`, `Table`, `Formula`, `VariableGrid`) so a
chapter file reads as content rather than as a wall of divs.

## Adding things

- **A basemap** — a file in `features/map/basemaps/` exporting a
  `BasemapDefinition`, added to `basemaps/index.ts`. The type is a discriminated
  union on `kind`: `raster` (one source, one layer, inherently blurry between
  zoom levels) or `vector` (many sources, GPU geometry redrawn at the exact
  fractional zoom — this is what makes zoom continuous).
- **An overlay layer** — an entry in `layers/layerRegistry.ts`. Pick the
  category carefully: `flow` is for observed and diagnostic fields, `ai` for
  model output. Eddies are `flow`, not `ai`, because filing a diagnostic
  computed from an observed field under "AI (Experimental)" would label an
  observation as an inference.
- **A cross-page preference** — a Zustand store with the `persist` middleware,
  like `themeStore` and `timezoneStore`. Timestamps display through
  `utils/formatTime.ts`, never a bare `toLocaleString()`.
- **A docs chapter** — a component in `pages/docs/chapters/` plus an entry in
  `chapters/index.ts`.

## Known gaps

- No test suite. The manager classes are written to be unit-testable in
  isolation (no React or Zustand imports) but nothing exercises that.
- Bundle size warning on build, largely MapLibre itself — normal for a WebGL
  mapping library, worth revisiting with code-splitting if initial load matters.
- `react-hooks/exhaustive-deps` is intentionally suppressed once in
  `useMapManager.ts`; see the comment there.

`../CLAUDE.md` (local, untracked) carries these conventions at greater length,
and `../TODO.md` carries the open work.
