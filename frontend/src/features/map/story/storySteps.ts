import type { LayerManager } from '../layers/LayerManager';

/**
 * The guided tour's script.
 *
 * Each step is declarative — a camera position and a set of layers — so the
 * tour drives the map through `LayerManager`'s public API rather than reaching
 * into MapLibre itself. That matters because the map is already owned by the
 * managers (components call manager methods; managers mutate the map and emit
 * back into the store), and a tour that bypassed them would be the one thing
 * fighting that ownership.
 *
 * **Steps declare what they need and are dropped when it is absent.** Forecast
 * layers are registered at runtime — they exist only where a model is trained
 * *and* its grid has been built — so a step depending on one cannot be assumed
 * present. Silently showing an empty map would be the same failure the
 * dashboard forbids: presenting absence as if it were data.
 */

export interface StoryStep {
  id: string;
  title: string;
  /** One or two sentences. Read aloud in ~6 seconds. */
  body: string;
  /** Small print — provenance, caveats, the honest footnote. */
  footnote?: string;
  camera: {
    center: [number, number];
    zoom: number;
    /** Degrees. A little bearing makes the transition feel deliberate. */
    bearing?: number;
  };
  /** Layer ids to switch on for this step. Order matters: last wins z-order. */
  layers: string[];
  /**
   * Layer ids this step cannot run without. A step whose required layer is not
   * registered is dropped from the tour rather than shown broken.
   */
  requires?: string[];
  /** Optional call-to-action rendered on the final card. */
  actions?: { label: string; to: string }[];
}

/** The northern Indian Ocean — the platform's primary region of interest. */
const ARABIAN_SEA: [number, number] = [65, 15];
const BAY_OF_BENGAL: [number, number] = [88, 15];
const GLOBAL: [number, number] = [40, 10];

/**
 * Built as a function because the forecast layer id depends on which variable
 * and horizon actually have a grid — resolved at call time from what the
 * `LayerManager` has registered.
 */
export function buildStorySteps(manager: LayerManager | null): StoryStep[] {
  const registered = new Set((manager?.getRegistered() ?? []).map((layer) => layer.id));

  // Prefer the change field at +7d: the absolute forecast at a week out looks
  // almost identical to today, so the difference is the informative view — and
  // it is the one that makes the forecasting engine visible at a glance.
  const forecastLayer = [...registered].find(
    (id) => id.startsWith('forecast-') && id.includes('-h7-') && id.endsWith('-change'),
  );

  const steps: StoryStep[] = [
    {
      id: 'sst',
      title: 'The ocean, right now',
      body: 'Sea surface temperature across the globe, refreshed from the Copernicus Marine analysis — not a snapshot baked into the page.',
      footnote: 'GLOBAL_ANALYSISFORECAST_PHY_001_024 · 0.083° grid · hourly',
      camera: { center: ARABIAN_SEA, zoom: 3.4 },
      layers: ['sst'],
    },
    {
      id: 'wind',
      title: 'What moves it',
      body: 'Every particle traces real surface wind. Warm water piles up, upwelling drags cold water to the surface, and the wind field is what drives both.',
      footnote: 'WIND_GLO_PHY_L4_NRT_012_004 · scatterometer + model blend · hourly',
      camera: { center: ARABIAN_SEA, zoom: 3.8, bearing: -8 },
      layers: ['sst', 'wind'],
    },
    {
      id: 'chlorophyll',
      title: 'Where life concentrates',
      body: 'Chlorophyll marks phytoplankton — the base of the food web. It blooms exactly where upwelling brings nutrients up, which is why it tracks the cold water you just saw.',
      footnote: 'Copernicus ocean colour · spans three orders of magnitude, so the scale is logarithmic',
      camera: { center: BAY_OF_BENGAL, zoom: 3.6 },
      layers: ['chlorophyll', 'wind'],
    },
  ];

  if (forecastLayer) {
    steps.push({
      id: 'forecast',
      title: 'Seven days ahead',
      body: 'This is the forecast minus today — where the model expects the ocean to change, not what it expects it to be. A week out the absolute field looks almost like today; the difference is the signal.',
      footnote: 'LightGBM on the change, validated against persistence at 24 global points',
      camera: { center: GLOBAL, zoom: 2.6 },
      layers: [forecastLayer],
      requires: [forecastLayer],
    });
  }

  steps.push({
    id: 'deeper',
    title: 'Every variable, all the way down',
    body: forecastLayer
      ? 'Each of these has its own intelligence page — history, forecast, and the features the model actually leaned on. Or just ask the assistant, which answers from these same endpoints.'
      : 'Each variable has its own intelligence page — history, forecast, and the features the model actually leaned on. Or just ask the assistant, which answers from these same endpoints.',
    camera: { center: GLOBAL, zoom: 2.4 },
    layers: ['sst', 'wind'],
    actions: [
      { label: 'Explore a variable', to: '/dashboard/sea_surface_temperature' },
      { label: 'Ask the assistant', to: '/assistant' },
    ],
  });

  // Drop any step whose required layers never registered.
  return steps.filter((step) => (step.requires ?? []).every((id) => registered.has(id)));
}
