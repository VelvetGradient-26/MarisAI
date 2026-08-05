import { useState } from 'react';
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
                <LayerList descriptors={descriptors} layerState={layerState} layerManager={layerManager} />
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
      {active?.legend && <Legend legend={active.legend} />}
    </>
  );
}

function LayerList({
  descriptors,
  layerState,
  layerManager,
}: {
  descriptors: LayerDescriptor[];
  layerState: Map<string, LayerState>;
  layerManager: LayerManager;
}) {
  return (
    <ul className="layer-list">
      {descriptors.map((descriptor) => {
        const state = layerState.get(descriptor.id);
        const disabled = descriptor.implemented === false;
        return (
          <li key={descriptor.id} className={disabled ? 'disabled' : ''}>
            <label title={descriptor.attribution}>
              <input
                type="checkbox"
                checked={state?.active ?? false}
                disabled={disabled}
                onChange={() => layerManager.toggle(descriptor.id)}
              />
              {descriptor.name}
              {disabled && <span className="badge">not wired yet</span>}
            </label>
            {state?.active && (
              <>
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
                {descriptor.legend && <Legend legend={descriptor.legend} />}
              </>
            )}
          </li>
        );
      })}
    </ul>
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
