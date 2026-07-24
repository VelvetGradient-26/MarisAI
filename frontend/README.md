# OceanMind Frontend

Phase 1–3 implementation of the architecture in `OceanMind_Frontend_Architecture_Proposal.docx`
and `OceanMind_ADR_Frontend_Architecture.docx`: mission-control map engine, basemap switching,
and a config-driven layer framework. React + TypeScript + Vite + MapLibre GL JS + Zustand.

## Run it

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-checks (tsc -b) then produces dist/
npm run lint      # oxlint
```

Verified in this environment: `tsc -b` (zero errors), `npm run build` (succeeds), `npm run lint`
(zero warnings), and `vite preview` serves the built bundle correctly. What I could **not** verify
here: the sandbox's network egress doesn't reach the tile servers (Esri, NASA GIBS, CARTO, OSM), so
I haven't visually confirmed tiles render — that needs a run with real internet access on your end.
If a basemap or layer comes back blank, check the browser console first; the most likely culprits
are called out below.

## What's real vs. stubbed

| Item | Status |
|---|---|
| Satellite (Esri), Dark (CARTO), Streets (OSM) basemaps | Real, verified endpoints |
| Blue Marble (NASA GIBS) basemap | Real endpoint; static layer, date segment intentionally omitted — see comment in `basemaps/blueMarble.ts` |
| Sea Surface Temperature layer | Real GIBS layer id (`GHRSST_L4_MUR_Sea_Surface_Temperature`), defaults to yesterday's date (UTC) since near-real-time products usually aren't available same-day |
| Chlorophyll-a layer | Real GIBS layer id (`MODIS_Aqua_L2_Chlorophyll_A` — NASA renamed this from `MODIS_Aqua_Chlorophyll_A` in 2022; the old id is dead) |
| Ocean Currents layer | **Placeholder** (`implemented: false`) — shows disabled in the layer panel. Currents are vector fields (OSCAR/HYCOM), which need particle or arrow rendering, not a raster tile. Not a Phase 1–3 task. |
| AI Hazard Prediction layer | **Placeholder** — wire to your model's tile output whenever that exists (Phase 6) |
| NOAA / Copernicus datasets | Not started — Phase 4–5 per the roadmap |

I didn't fabricate tile URLs for currents or AI predictions — a `LayerDescriptor` with
`implemented: false` registers in the framework (shows in the panel, greyed out) without ever
calling `map.addLayer()`, so the framework's shape is honest about what's real.

## Architecture decisions worth knowing about

**Basemap switching never touches overlays.** `BasemapManager.switchTo()` swaps a single raster
source+layer, not `map.setStyle()`. A full style swap would silently wipe every layer
`LayerManager` had added — this is the direct fix for "state duplication between React and
MapLibre," which the ADR itself flagged as a risk.

**LayerManager is config-driven.** Every scientific/reference layer is a `LayerDescriptor` object
in `features/map/layers/layerRegistry.ts` — id, category, source, opacity, visibility. Adding a
NOAA or Copernicus dataset later means adding an entry to that file, not writing a new component
or manager method.

**Managers don't import Zustand.** `MapManager`, `BasemapManager`, `LayerManager`, and
`ControlManager` are plain classes that only touch MapLibre — they emit changes through a small
pub-sub (`lib/createEmitter.ts`), and only `useMapManager` (the React-facing hook) bridges those
events into the Zustand store. This keeps the managers usable and testable outside React, and
keeps state flow one-directional: MapLibre → managers → Zustand → components. Nothing writes back
into MapLibre except through a manager method call.

**Layer z-order is a documented assumption, not a settled decision.** The ADR's own "Layer
Hierarchy" list is ambiguous about whether it's ordered top-of-stack-to-bottom or the reverse
(`Selection/Interaction` listed last is hard to reconcile with either reading). I picked a
category-based stacking order — `ocean < ai < reference`, basemap always beneath all three — that
seemed the most defensible for a data-visualization tool, but this is a real open question worth
resolving with whoever wrote the original hierarchy diagram before Phase 4 adds more categories.

**Map mutations wait for `load`.** MapLibre throws "Style is not done loading" if
`addSource`/`addLayer` is called before the style has finished loading — true even for the empty
placeholder style `MapManager` starts with. `register()` on `BasemapManager`/`LayerManager` only
writes in-memory metadata (safe anytime), but `basemapManager.init()` and
`layerManager.applyDefaults()` — which actually touch the map — are deferred to a `map.once('load', ...)`
handler in `MapManager.init()`.

**MapLibre's worker is wired explicitly.** v6 of `maplibre-gl` is ESM-only and loads its render
worker as a separate file; Vite's dev-mode dependency optimizer doesn't resolve that automatically
and fails with `The file does not exist at ".../maplibre-gl-worker.mjs"...`. `src/app/main.tsx`
calls `setWorkerUrl()` with an explicit `?worker&url` import before any `Map` is constructed, per
MapLibre's own Vite guidance — this must stay at the entry point, not inside `MapManager`, since it
has to run before the first `new maplibregl.Map()` call anywhere in the app.

**Cursor/camera sync is rAF-throttled**, not raw MapLibre event → Zustand on every fire — addresses
the "state duplication" and re-render-storm risk directly (see `utils/rafThrottle.ts`).

## Extending this

- **New basemap:** add a file to `features/map/basemaps/`, export a `BasemapDefinition`, add it to
  the array in `basemaps/index.ts`.
- **New overlay layer:** add a `LayerDescriptor` to `features/map/layers/layerRegistry.ts`. If it's
  a raster tile source, it works immediately. Vector/GeoJSON sources will need `LayerManager`'s
  `type` union extended (currently `'raster'` only, by design — Phase 1–3 didn't need more).
- **New control (non-built-in):** the `features/map/controls/` folder is reserved for this;
  `ControlManager` currently only wraps MapLibre's built-ins (nav, geolocate, fullscreen, scale).

## Known gaps / not done

- No test suite yet (no testing library installed) — the manager classes are written to be
  unit-testable in isolation (no React/Zustand imports) but nothing exercises that yet.
- No error boundary or tile-load-failure UI — if a tile server is unreachable, MapLibre just logs
  to console; there's no user-facing indicator.
- Bundle size warning on build (~1.2 MB JS, largely MapLibre GL itself) — normal for a WebGL
  mapping library, but worth revisiting with code-splitting if initial load time becomes a concern.
- `react-hooks/exhaustive-deps` is intentionally suppressed once in `useMapManager.ts` — the effect
  is meant to run exactly once per mount; see the comment there for why.
