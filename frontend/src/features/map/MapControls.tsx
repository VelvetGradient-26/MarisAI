import { useEffect, useRef, useState } from 'react';
import { useMapManagerContext } from './hooks/MapManagerContext';
import { useMapStore } from '../../store/mapStore';
import { useMapPreferencesStore } from '../../store/mapPreferencesStore';
import { useUiStore } from '../../store/uiStore';
import { GradientBar } from './GradientBar';
import type { MapManager } from './managers/MapManager';
import type { LayerManager, LayerState } from './layers/LayerManager';
import type {
  BasemapId,
  LayerCategory,
  LayerDescriptor,
  LayerLegend,
  ProjectionMode,
} from './types';

const CATEGORY_GROUPS: Array<{ category: LayerCategory; label: string; exclusive: boolean }> = [
  { category: 'ocean', label: 'Ocean & Atmosphere', exclusive: true },
  { category: 'flow', label: 'Wind & Currents', exclusive: false },
  { category: 'reference', label: 'Boundaries & Reference', exclusive: false },
  { category: 'ai', label: 'AI (Experimental)', exclusive: false },
];

export function MapControls() {
  const manager = useMapManagerContext();
  const basemap = useMapStore((s) => s.basemap);
  const layerState = useMapStore((s) => s.layers);
  const panelOpen = useUiStore((s) => s.controlPanelOpen);
  const togglePanel = useUiStore((s) => s.toggleControlPanel);

  if (!manager) return null;
  const basemapManager = manager.getBasemapManager();
  const layerManager = manager.getLayerManager();
  if (!basemapManager || !layerManager) return null;

  const registered = layerManager.getRegistered();

  return (
    <div className={`map-controls ${panelOpen ? 'open' : 'collapsed'}`}>
      <button
        className="panel-toggle"
        onClick={togglePanel}
        aria-label={panelOpen ? 'Collapse control panel' : 'Expand control panel'}
        aria-expanded={panelOpen}
      >
        {panelOpen ? '✕' : '☰'}
      </button>

      <div className="map-controls__body" aria-hidden={!panelOpen}>
        <ProjectionToggle manager={manager} />

        <section>
          <h3>Basemap</h3>
          <div className="basemap-grid">
            {basemapManager.getAvailable().map((def) => (
              <button
                key={def.id}
                className={def.id === basemap ? 'active' : ''}
                onClick={() => basemapManager.switchTo(def.id as BasemapId)}
                title={def.blurb ?? def.name}
              >
                {def.name}
              </button>
            ))}
          </div>
        </section>

        {CATEGORY_GROUPS.map(({ category, label, exclusive }) => {
          const descriptors = registered.filter((descriptor) => descriptor.category === category);
          if (descriptors.length === 0) return null;

          return (
            <section key={category}>
              <h3>{label}</h3>
              {exclusive ? (
                <MapButtonGroup descriptors={descriptors} layerState={layerState} layerManager={layerManager} />
              ) : (
                <LayerDropdown
                  label={label}
                  descriptors={descriptors}
                  layerState={layerState}
                  layerManager={layerManager}
                />
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

const PROJECTIONS: Array<{ mode: ProjectionMode; label: string }> = [
  { mode: 'mercator', label: '2D Map' },
  { mode: 'globe', label: '3D Globe' },
];

/**
 * Flattened web-mercator map vs. the 3D globe — see
 * MapManager.setProjectionMode. The selection lives in mapPreferencesStore,
 * not local state: the MapManager is destroyed on every navigation away from
 * /map, so a manager-held mode reverted to the globe default each time the
 * user came back. useMapManager seeds the new instance from the same store.
 */
function ProjectionToggle({ manager }: { manager: MapManager }) {
  const mode = useMapPreferencesStore((s) => s.projection);
  const setProjection = useMapPreferencesStore((s) => s.setProjection);

  return (
    <section>
      <h3>View</h3>
      <div className="basemap-grid">
        {PROJECTIONS.map(({ mode: value, label }) => (
          <button
            key={value}
            className={mode === value ? 'active' : ''}
            onClick={() => {
              setProjection(value);
              manager.setProjectionMode(value);
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

/**
 * A "pick one" group of complete maps rather than stackable overlays —
 * every entry here renders full-coverage color data, so letting two be
 * active together just produces visual noise. A single dropdown (not a
 * button per option) makes that "exactly one, or none" constraint obvious
 * without a grid of nitpicky-looking buttons. Selecting "None" turns the
 * currently active one off; selecting another switches to it.
 */
function MapButtonGroup({
  descriptors,
  layerState,
  layerManager,
}: {
  descriptors: LayerDescriptor[];
  layerState: Map<string, LayerState>;
  layerManager: LayerManager;
}) {
  const active = descriptors.find((d) => layerState.get(d.id)?.active);

  return (
    <>
      <select
        className="map-exclusive-select"
        value={active?.id ?? ''}
        onChange={(e) => {
          const id = e.target.value;
          layerManager.setExclusive(id || (active?.id ?? ''));
        }}
      >
        <option value="">None</option>
        {descriptors.map((descriptor) => (
          <option
            key={descriptor.id}
            value={descriptor.id}
            disabled={descriptor.implemented === false}
          >
            {descriptor.name}
            {descriptor.implemented === false ? ' (coming soon)' : ''}
          </option>
        ))}
      </select>
      {active && <LayerStatus state={layerState.get(active.id)} />}
      {active?.legend && <Legend legend={active.legend} />}
    </>
  );
}

/**
 * Whether the selected layer's tiles are still arriving, or failed.
 *
 * This group is where the full-coverage colour fields live — SST, and every
 * forecast/change grid — and all of them share a failure mode where nothing
 * renders. A forecast grid is a near-black ramp over a near-black ocean at 0.7
 * opacity, so "still fetching", "scored nothing here" and "the tile request
 * 404'd" were three very different states that all looked like an unchanged
 * map. Only the first two are legitimate, and neither was previously
 * distinguishable from the third.
 */
function LayerStatus({ state }: { state: LayerState | undefined }) {
  if (!state?.active) return null;

  if (state.error) {
    return (
      <p className="layer-status layer-status--error" role="status">
        <span className="layer-status__dot" aria-hidden="true" />
        Tiles failed to load — {state.error}
      </p>
    );
  }

  if (state.loading) {
    return (
      <p className="layer-status layer-status--loading" role="status">
        <span className="layer-status__spinner" aria-hidden="true" />
        Loading tiles…
      </p>
    );
  }

  return null;
}

/**
 * A stackable group, collapsed behind a dropdown.
 *
 * Two constraints shaped this rather than a native `<select>`. These groups
 * are *stackable* — EEZ and marine protected areas are meant to be readable
 * together, and the AI group carries eight entries — so a single-choice
 * control would remove a capability rather than tidy one. And the panel body
 * is a fixed-width scrolling box (`overflow-x: hidden`), so an absolutely
 * positioned popover would be clipped by its own container.
 *
 * Hence an inline disclosure: the trigger summarises what is on, the menu
 * expands in normal flow, and selecting does not close it because picking two
 * layers is the common case. The active layers' opacity slider and legend stay
 * *outside* the menu, so adjusting one does not mean reopening the dropdown.
 */
function LayerDropdown({
  label,
  descriptors,
  layerState,
  layerManager,
}: {
  label: string;
  descriptors: LayerDescriptor[];
  layerState: Map<string, LayerState>;
  layerManager: LayerManager;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // "Outside" is the whole group, not just the menu — the active-layer
  // controls below the menu are part of this dropdown as far as the user is
  // concerned, and closing when they drag an opacity slider would be hostile.
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const active = descriptors.filter((descriptor) => layerState.get(descriptor.id)?.active);
  const summary =
    active.length === 0
      ? 'None'
      : active.length === 1
        ? active[0].name
        : `${active.length} selected`;

  return (
    <div className="layer-dropdown" ref={containerRef}>
      <button
        type="button"
        className={`layer-dropdown__trigger ${open ? 'open' : ''}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="layer-dropdown__summary">{summary}</span>
        <span className="layer-dropdown__caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {/* The wrapper exists to animate the height. A `grid-template-rows`
          0fr -> 1fr reveal is the one way to animate to *auto* height in CSS
          alone, so the menu pushes the controls below it down smoothly instead
          of appearing at full size in a single frame.

          Entry only, and the menu stays conditionally mounted. Animating the
          exit would mean keeping a zero-height menu in the flex column, which
          adds a phantom 8px gap and leaves eight checkboxes in the tab order
          while invisible — a keyboard trap traded for a flourish nobody waits
          around to see. */}
      {open && (
        <div className="layer-dropdown__reveal">
          <ul className="layer-dropdown__menu" role="group" aria-label={label}>
            {descriptors.map((descriptor) => {
              const disabled = descriptor.implemented === false;
              return (
                <li key={descriptor.id} className={disabled ? 'disabled' : ''}>
                  <label title={descriptor.attribution}>
                    <input
                      type="checkbox"
                      checked={layerState.get(descriptor.id)?.active ?? false}
                      disabled={disabled}
                      onChange={() => layerManager.toggle(descriptor.id)}
                    />
                    {descriptor.name}
                    {disabled && <span className="badge">not wired yet</span>}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {active.length > 0 && (
        <ul className="layer-list">
          {active.map((descriptor) => {
            const state = layerState.get(descriptor.id);
            if (!state) return null;
            return (
              <li key={descriptor.id}>
                <span className="layer-list__name">{descriptor.name}</span>
                {!descriptor.hideOpacitySlider && (
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={state.opacity}
                    onChange={(e) => layerManager.setOpacity(descriptor.id, Number(e.target.value))}
                  />
                )}
                {descriptor.type === 'custom' && (
                  <VectorFieldControls descriptorId={descriptor.id} layerManager={layerManager} />
                )}
                <LayerStatus state={state} />
                {descriptor.legend && <Legend legend={descriptor.legend} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * Density/speed sliders for particle layers (Task 13, partial) — pure
 * GPU-side uniform changes via the CustomVectorFieldLayer instance itself,
 * not round-tripped through LayerManager's state/emitter since nothing else
 * needs to react to them.
 */
function VectorFieldControls({
  descriptorId,
  layerManager,
}: {
  descriptorId: string;
  layerManager: LayerManager;
}) {
  const [density, setDensity] = useState<'auto' | 'world' | 'regional' | 'local'>('auto');
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const instance = layerManager.getCustomLayerInstance(descriptorId);

  return (
    <div className="vector-field-controls">
      <label>
        Density
        <select
          value={density}
          onChange={(e) => {
            const tier = e.target.value as typeof density;
            setDensity(tier);
            instance?.setDensityTier?.(tier);
          }}
        >
          <option value="auto">Auto (by zoom)</option>
          <option value="world">World</option>
          <option value="regional">Regional</option>
          <option value="local">Local</option>
        </select>
      </label>
      <label>
        Speed ×{speedMultiplier.toFixed(2)}
        <input
          type="range"
          min={0.25}
          max={3}
          step={0.25}
          value={speedMultiplier}
          onChange={(e) => {
            const value = Number(e.target.value);
            setSpeedMultiplier(value);
            instance?.setSpeedMultiplier?.(value);
          }}
        />
      </label>
    </div>
  );
}

function Legend({ legend }: { legend: LayerLegend }) {
  if (legend.type === 'categories') {
    return (
      <ul className="layer-legend">
        {legend.categories.map((category) => (
          <li key={category.label}>
            <span className="layer-legend__swatch" style={{ background: category.color }} />
            <span className="layer-legend__label">{category.label}</span>
            <span className="layer-legend__range">{category.range}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (legend.type === 'gradient') {
    return (
      <div className="layer-legend layer-legend--gradient">
        <GradientBar legend={legend} />
      </div>
    );
  }

  if (legend.type === 'swatch') {
    return (
      <div className="layer-legend layer-legend--inline">
        <span className="layer-legend__swatch" style={{ background: legend.color }} />
        <span className="layer-legend__label">{legend.label}</span>
      </div>
    );
  }

  if (legend.type === 'image') {
    return (
      <div className="layer-legend layer-legend--image">
        <img src={legend.src} alt={legend.alt} />
      </div>
    );
  }

  return <p className="layer-legend layer-legend--note">{legend.text}</p>;
}
