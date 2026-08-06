import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Play, X } from 'lucide-react';
import { Link } from '../../../app/router';
import { useMapManagerContext } from '../hooks/MapManagerContext';
import { buildStorySteps } from './storySteps';
import type { StoryStep } from './storySteps';
import './story.css';

/**
 * A guided walkthrough of the map.
 *
 * The problem it solves: the platform's depth is not discoverable. Someone
 * seeing this for the first time gets a coloured map and no reason to believe
 * there is a forecasting engine, an explainability layer or a grounded
 * assistant behind it. The tour spends ninety seconds showing them.
 *
 * Design notes:
 *
 * * **It drives the map through `LayerManager`, never MapLibre directly.** The
 *   managers own the map; the tour is just another component calling their
 *   methods, so it cannot desynchronise the store.
 * * **It restores what it changed.** Layer state on entry is captured and put
 *   back on exit, so taking the tour does not silently leave the map in a
 *   different configuration than the user set up.
 * * **It auto-runs once.** First visit only, remembered in localStorage, and
 *   never when the viewer prefers reduced motion — an unrequested animated
 *   takeover is hostile. After that it is a button.
 */

const SEEN_KEY = 'maris.map.tour.seen';

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

export function StoryMode() {
  const manager = useMapManagerContext();
  const [running, setRunning] = useState(false);
  const [index, setIndex] = useState(0);
  /** Layer visibility as it was before the tour started, for restoration. */
  const entryState = useRef<string[] | null>(null);

  const layerManager = manager?.getLayerManager() ?? null;

  /**
   * A signature of *which layers exist*, not of their visibility.
   *
   * Two requirements pull against each other here. Forecast layers register
   * asynchronously (`useForecastGridLayers` fetches a catalog first), so the
   * step list has to be rebuilt when they arrive or the tour's best step never
   * appears. But `LayerManager.subscribe` also fires on every add/remove —
   * including the ones the tour itself performs — and rebuilding on those would
   * churn `steps`, which would churn `start`, which would keep resetting the
   * auto-start timer so it never fired.
   *
   * Keying on the sorted id list satisfies both: it changes when a layer is
   * registered and stays identical when one is merely toggled.
   */
  const [registrySignature, setRegistrySignature] = useState('');

  useEffect(() => {
    if (!layerManager) return;
    const signature = () =>
      layerManager
        .getRegistered()
        .map((layer) => layer.id)
        .sort()
        .join(',');
    setRegistrySignature(signature());
    return layerManager.subscribe(() => {
      const next = signature();
      setRegistrySignature((current) => (current === next ? current : next));
    });
  }, [layerManager]);

  const steps = useMemo(
    () => buildStorySteps(layerManager),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the signature is the real input
    [layerManager, registrySignature],
  );

  const applyStep = useCallback(
    (step: StoryStep) => {
      const map = manager?.getMap();
      const layers = manager?.getLayerManager();
      if (!map || !layers) return;

      // Layers first so tiles begin fetching while the camera is still moving.
      const state = layers.getState();
      for (const descriptor of layers.getRegistered()) {
        // `reference-labels` is chrome, not content — leave it alone.
        if (descriptor.id === 'reference-labels') continue;
        const shouldBeOn = step.layers.includes(descriptor.id);
        const isOn = state.get(descriptor.id)?.active ?? false;
        if (shouldBeOn && !isOn) layers.add(descriptor.id);
        if (!shouldBeOn && isOn) layers.remove(descriptor.id);
      }

      const camera = {
        center: step.camera.center,
        zoom: step.camera.zoom,
        bearing: step.camera.bearing ?? 0,
      };
      if (prefersReducedMotion()) {
        map.jumpTo(camera);
      } else {
        map.flyTo({ ...camera, duration: 2200, essential: true, curve: 1.3 });
      }
    },
    [manager],
  );

  const start = useCallback(() => {
    const layers = manager?.getLayerManager();
    if (!layers || steps.length === 0) return;
    entryState.current = [...layers.getState().entries()]
      .filter(([, layerState]) => layerState.active)
      .map(([id]) => id);
    setIndex(0);
    setRunning(true);
    applyStep(steps[0]);
  }, [manager, steps, applyStep]);

  const stop = useCallback(() => {
    setRunning(false);
    window.localStorage.setItem(SEEN_KEY, '1');

    // Put the map back the way it was found.
    const layers = manager?.getLayerManager();
    const previous = entryState.current;
    if (layers && previous) {
      const state = layers.getState();
      for (const descriptor of layers.getRegistered()) {
        const shouldBeOn = previous.includes(descriptor.id);
        const isOn = state.get(descriptor.id)?.active ?? false;
        if (shouldBeOn && !isOn) layers.add(descriptor.id);
        if (!shouldBeOn && isOn) layers.remove(descriptor.id);
      }
    }
    entryState.current = null;
  }, [manager]);

  const go = useCallback(
    (next: number) => {
      if (next < 0 || next >= steps.length) return;
      setIndex(next);
      applyStep(steps[next]);
    },
    [steps, applyStep],
  );

  // Auto-run once, and only once the map actually has layers registered —
  // starting before registration would apply a step against an empty registry.
  useEffect(() => {
    if (!layerManager || steps.length === 0) return;
    if (window.localStorage.getItem(SEEN_KEY)) return;
    if (prefersReducedMotion()) return;

    // Let the first tiles land before taking over the view.
    const timer = window.setTimeout(start, 1400);
    return () => window.clearTimeout(timer);
  }, [layerManager, steps.length, start]);

  useEffect(() => {
    if (!running) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') stop();
      if (event.key === 'ArrowRight') go(index + 1);
      if (event.key === 'ArrowLeft') go(index - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [running, index, go, stop]);

  if (steps.length === 0) return null;

  if (!running) {
    return (
      <button type="button" className="story-launch" onClick={start}>
        <Play size={13} fill="currentColor" />
        Take the tour
      </button>
    );
  }

  const step = steps[index];
  const isLast = index === steps.length - 1;

  return (
    <div className="story" role="dialog" aria-label="Guided tour" aria-live="polite">
      <div className="story__card">
        <button type="button" className="story__close" onClick={stop} aria-label="End tour">
          <X size={15} />
        </button>

        <div className="story__dots" aria-hidden="true">
          {steps.map((entry, dotIndex) => (
            <button
              key={entry.id}
              type="button"
              className={`story__dot ${dotIndex === index ? 'is-active' : ''} ${
                dotIndex < index ? 'is-done' : ''
              }`}
              onClick={() => go(dotIndex)}
              tabIndex={-1}
            />
          ))}
        </div>

        <div className="story__body" key={step.id}>
          <p className="story__step">
            {String(index + 1).padStart(2, '0')} / {String(steps.length).padStart(2, '0')}
          </p>
          <h2 className="story__title">{step.title}</h2>
          <p className="story__text">{step.body}</p>
          {step.footnote && <p className="story__footnote">{step.footnote}</p>}

          {step.actions && (
            <div className="story__actions">
              {step.actions.map((action) => (
                <Link key={action.to} to={action.to} className="story__action" onClick={stop}>
                  {action.label}
                  <ArrowRight size={14} />
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="story__nav">
          <button
            type="button"
            className="story__skip"
            onClick={stop}
          >
            {isLast ? 'Done' : 'Skip'}
          </button>
          <div className="story__nav-right">
            <button
              type="button"
              className="story__button story__button--ghost"
              onClick={() => go(index - 1)}
              disabled={index === 0}
            >
              Back
            </button>
            {!isLast && (
              <button type="button" className="story__button" onClick={() => go(index + 1)}>
                Next
                <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
