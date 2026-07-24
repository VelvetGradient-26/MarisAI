import { useMapManagerContext } from './hooks/MapManagerContext';
import { useMapStore } from '../../store/mapStore';
import { useUiStore } from '../../store/uiStore';
import type { BasemapId } from './types';

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

  return (
    <div className={`map-controls ${panelOpen ? 'open' : 'collapsed'}`}>
      <button className="panel-toggle" onClick={togglePanel} aria-label="Toggle control panel">
        {panelOpen ? '✕' : '☰'}
      </button>

      {panelOpen && (
        <>
          <section>
            <h3>Basemap</h3>
            <div className="basemap-grid">
              {basemapManager.getAvailable().map((def) => (
                <button
                  key={def.id}
                  className={def.id === basemap ? 'active' : ''}
                  onClick={() => basemapManager.switchTo(def.id as BasemapId)}
                >
                  {def.name}
                </button>
              ))}
            </div>
          </section>

          <section>
            <h3>Layers</h3>
            <ul className="layer-list">
              {layerManager.getRegistered().map((descriptor) => {
                const state = layerState.get(descriptor.id);
                const disabled = descriptor.implemented === false;
                return (
                  <li key={descriptor.id} className={disabled ? 'disabled' : ''}>
                    <label>
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
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={state.opacity}
                        onChange={(e) => layerManager.setOpacity(descriptor.id, Number(e.target.value))}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
