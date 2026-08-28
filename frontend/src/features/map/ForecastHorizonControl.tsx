import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMapStore } from '../../store/mapStore';
import { useMapManagerContext } from './hooks/MapManagerContext';
import { forecastLayerId, parseForecastLayerId } from './layers/forecastLayers';

/** How long each horizon holds before the next. Slow enough to read the map,
 *  fast enough that a four-step loop reads as motion rather than as a slideshow.
 *  Tiles carry `Cache-Control: max-age=900`, so only the first pass waits on the
 *  network and every later one is instant. */
const DWELL_MS = 1400;

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/**
 * A scrubber over a forecast layer's horizon axis.
 *
 * Every forecast grid file already carries h1/h3/h7/h30, and the layer list
 * already exposes them — as four separate entries you toggle between one at a
 * time. That is the correct data model and a poor way to *read* a forecast:
 * the thing a reader wants is how the field evolves, and comparing four static
 * layers by clicking between them is exactly the comparison the eye is worst at.
 *
 * So this is a view over layers that already exist rather than any new data
 * path. Stepping calls `setExclusive` on the sibling layer for the next
 * horizon, which is safe precisely because forecast layers live in the
 * exclusive `ocean` category — the manager turns the previous one off as part
 * of turning the next one on, so there is never a frame with two horizons
 * painted over each other.
 *
 * It renders only while a forecast layer is active, and disappears for
 * everything else, because a horizon control over sea surface temperature
 * observations would be a control over nothing.
 */
export function ForecastHorizonControl() {
  const manager = useMapManagerContext();
  const layers = useMapStore((s) => s.layers);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);

  // The active forecast layer, if one is active at all. `find` rather than a
  // filter: the category is exclusive, so there is at most one.
  const active = useMemo(() => {
    for (const [id, state] of layers) {
      if (!state.active) continue;
      const parsed = parseForecastLayerId(id);
      if (parsed) return parsed;
    }
    return null;
  }, [layers]);

  // Which horizons this variable actually has. Read from the registered layer
  // ids rather than assumed to be [1, 3, 7, 30]: a variable ships only the
  // horizons that cleared the skill bar, so `bottom_temperature` has just h1 and
  // `nitrate` is missing h3. A hardcoded ladder would offer steps that 404.
  const horizons = useMemo(() => {
    if (!active) return [];
    const found: number[] = [];
    for (const id of layers.keys()) {
      const parsed = parseForecastLayerId(id);
      if (parsed && parsed.variable === active.variable && parsed.mode === active.mode) {
        found.push(parsed.horizon);
      }
    }
    return [...new Set(found)].sort((a, b) => a - b);
  }, [layers, active]);

  const show = active !== null && horizons.length > 1;

  const goTo = useCallback(
    (horizon: number) => {
      if (!manager || !active) return;
      const layerManager = manager.getLayerManager();
      if (!layerManager) return;
      layerManager.setExclusive(forecastLayerId(active.variable, horizon, active.mode));
    },
    [manager, active]
  );

  // Stop playing whenever the control stops applying — switching to a
  // non-forecast layer while the loop runs would otherwise keep stepping
  // layers the user is no longer looking at.
  useEffect(() => {
    if (!show) setPlaying(false);
  }, [show]);

  useEffect(() => {
    if (!playing || !active || horizons.length < 2) return;

    timer.current = window.setInterval(() => {
      const index = horizons.indexOf(active.horizon);
      goTo(horizons[(index + 1) % horizons.length]);
    }, DWELL_MS);

    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      timer.current = null;
    };
  }, [playing, active, horizons, goTo]);

  if (!show || !active) return null;

  const index = horizons.indexOf(active.horizon);

  return (
    <div className="horizon-control" aria-label="Forecast horizon">
      <div className="horizon-control__head">
        <span className="horizon-control__title">Forecast horizon</span>
        <button
          type="button"
          className="horizon-control__play"
          onClick={() => {
            // Reduced motion gets a step, not a loop. The control is still fully
            // usable — every horizon is one click away on the scrubber — but
            // nothing animates on its own.
            if (prefersReducedMotion()) {
              goTo(horizons[(index + 1) % horizons.length]);
              return;
            }
            setPlaying((value) => !value);
          }}
          aria-pressed={playing}
        >
          {playing ? '❙❙ Pause' : '▶ Play'}
        </button>
      </div>

      <input
        className="horizon-control__scrubber"
        type="range"
        min={0}
        max={horizons.length - 1}
        step={1}
        value={index < 0 ? 0 : index}
        onChange={(event) => {
          setPlaying(false);
          goTo(horizons[Number(event.target.value)]);
        }}
        aria-label={`Horizon: +${active.horizon} days`}
        aria-valuetext={`plus ${active.horizon} days`}
      />

      <div className="horizon-control__ticks">
        {horizons.map((horizon) => (
          <button
            key={horizon}
            type="button"
            className={
              horizon === active.horizon
                ? 'horizon-control__tick horizon-control__tick--current'
                : 'horizon-control__tick'
            }
            onClick={() => {
              setPlaying(false);
              goTo(horizon);
            }}
          >
            +{horizon}d
          </button>
        ))}
      </div>
    </div>
  );
}
