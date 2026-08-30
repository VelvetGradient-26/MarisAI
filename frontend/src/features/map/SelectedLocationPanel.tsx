import { useEffect, useState } from 'react';
import { Link } from '../../app/router';
import { useMapStore } from '../../store/mapStore';
import { useUiStore } from '../../store/uiStore';
import { useTimezoneStore } from '../../store/timezoneStore';
import { formatFullDateTime } from '../../utils/formatTime';
import { fetchSstPoint } from './api/sst';
import type { SstPointResponse } from './api/sst';
import { fetchWindPoint } from './api/wind';
import type { WindPointResponse } from './api/wind';
import { fetchCurrentsPoint } from './api/currents';
import { downloadBriefPdf } from './api/brief';
import type { CurrentsPointResponse } from './api/currents';
import { useSelectedLocationPredictions } from './hooks/useSelectedLocationPredictions';
import type { PredictionPointResult } from './hooks/useSelectedLocationPredictions';
import { useToolsStore } from '../../store/toolsStore';
import { useRoutePlanner } from './hooks/useRoutePlanner';
import { useDriftTrajectoryPlanner } from './hooks/useDriftTrajectoryPlanner';
import { fetchLeewayPresets } from './api/drift';
import type { LeewayPreset } from './api/drift';
import { subscribeWatch } from './api/watch';
import type { NearestPort, RealtimeOceanConditions, RealtimeOceanUnits } from './types';

const METRICS: Array<{
  key: keyof RealtimeOceanConditions & keyof RealtimeOceanUnits;
  label: string;
}> = [
  { key: 'sea_surface_temperature', label: 'Sea Surface Temperature' },
  { key: 'wave_height', label: 'Wave Height' },
  { key: 'wave_direction', label: 'Wave Direction' },
  { key: 'ocean_current_velocity', label: 'Ocean Current' },
  { key: 'ocean_current_direction', label: 'Current Direction' },
  { key: 'wind_speed', label: 'Wind Speed' },
  { key: 'air_temperature', label: 'Air Temperature' },
];

export function SelectedLocationPanel() {
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const data = useMapStore((s) => s.selectedLocationData);
  const status = useMapStore((s) => s.selectedLocationDataStatus);
  const error = useMapStore((s) => s.selectedLocationDataError);
  const panelOpen = useUiStore((s) => s.selectedLocationPanelOpen);
  const togglePanel = useUiStore((s) => s.toggleSelectedLocationPanel);
  const timezone = useTimezoneStore((s) => s.timezone);

  const sstLayerActive = useMapStore((s) => s.layers.get('sst')?.active ?? false);
  const [sstPoint, setSstPoint] = useState<SstPointResponse | null>(null);
  const [sstStatus, setSstStatus] = useState<'idle' | 'loading' | 'error' | 'success'>('idle');

  useEffect(() => {
    if (!sstLayerActive || !selectedLocation) {
      setSstPoint(null);
      setSstStatus('idle');
      return;
    }

    const controller = new AbortController();
    setSstStatus('loading');
    fetchSstPoint(selectedLocation, controller.signal)
      .then((response) => {
        setSstPoint(response);
        setSstStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSstStatus('error');
      });

    return () => controller.abort();
  }, [sstLayerActive, selectedLocation]);

  const windLayerActive = useMapStore((s) => s.layers.get('wind')?.active ?? false);
  const [windPoint, setWindPoint] = useState<WindPointResponse | null>(null);
  const [windStatus, setWindStatus] = useState<'idle' | 'loading' | 'error' | 'success'>('idle');

  useEffect(() => {
    if (!windLayerActive || !selectedLocation) {
      setWindPoint(null);
      setWindStatus('idle');
      return;
    }

    const controller = new AbortController();
    setWindStatus('loading');
    fetchWindPoint(selectedLocation, controller.signal)
      .then((response) => {
        setWindPoint(response);
        setWindStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setWindStatus('error');
      });

    return () => controller.abort();
  }, [windLayerActive, selectedLocation]);

  const currentsLayerActive = useMapStore((s) => s.layers.get('currents')?.active ?? false);
  const [currentsPoint, setCurrentsPoint] = useState<CurrentsPointResponse | null>(null);
  const [currentsStatus, setCurrentsStatus] = useState<'idle' | 'loading' | 'error' | 'success'>(
    'idle'
  );

  useEffect(() => {
    if (!currentsLayerActive || !selectedLocation) {
      setCurrentsPoint(null);
      setCurrentsStatus('idle');
      return;
    }

    const controller = new AbortController();
    setCurrentsStatus('loading');
    fetchCurrentsPoint(selectedLocation, controller.signal)
      .then((response) => {
        setCurrentsPoint(response);
        setCurrentsStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCurrentsStatus('error');
      });

    return () => controller.abort();
  }, [currentsLayerActive, selectedLocation]);

  const predictions = useSelectedLocationPredictions(selectedLocation);
  const pfz = useToolsStore((s) => s.pfz);
  const {
    start: routeStart,
    end: routeEnd,
    status: routeStatus,
    result: routeResult,
    error: routeError,
    setStart: setRouteStart,
    setEnd: setRouteEnd,
    planRoute,
    clear: clearRoute,
  } = useRoutePlanner();
  const {
    preset: driftPreset,
    horizonHours: driftHorizonHours,
    status: driftStatus,
    result: driftResult,
    error: driftError,
    setPreset: setDriftPreset,
    setHorizonHours: setDriftHorizonHours,
    planTrajectory,
    clear: clearDriftTrajectory,
  } = useDriftTrajectoryPlanner();
  const [leewayPresets, setLeewayPresets] = useState<LeewayPreset[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetchLeewayPresets(controller.signal)
      .then(setLeewayPresets)
      .catch(() => {
        // The dropdown just falls back to the one preset already selected by
        // default — not worth a visible error state for a list that rarely
        // changes and degrades harmlessly.
      });
    return () => controller.abort();
  }, []);

  // Three-way rather than a boolean: 'building' and 'failed' are different
  // answers, and a brief takes long enough (bathymetry plus a point API) that
  // a button with no feedback reads as broken.
  const [briefStatus, setBriefStatus] = useState<'idle' | 'loading' | 'error'>('idle');

  // sihtodo.md item 8 — proactive alert watches. Local state, not a store:
  // this is a one-shot form submission, the same shape `briefStatus` above
  // already uses, not something another component needs to read.
  const [watchEmail, setWatchEmail] = useState('');
  const [watchStatus, setWatchStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [watchError, setWatchError] = useState<string | null>(null);

  return (
    <aside className={`selected-location-panel ${panelOpen ? 'open' : 'collapsed'}`}>
      <button
        className="panel-toggle"
        onClick={togglePanel}
        aria-label={panelOpen ? 'Collapse realtime marine conditions' : 'Expand realtime marine conditions'}
        aria-expanded={panelOpen}
      >
        {panelOpen ? '✕' : '☰'}
      </button>

      <div className="selected-location-panel__header">
        <h3>Realtime Marine Conditions</h3>
        {selectedLocation && data ? (
          <>
            <span>{data.location_context.ocean_name ?? 'Ocean: Unknown'}</span>
            <span>{formatNearestPort(data.location_context.nearest_port)}</span>
            <span>{formatCoordinates(selectedLocation.lat, selectedLocation.lng)}</span>
          </>
        ) : (
          <span>
            {selectedLocation ? formatCoordinates(selectedLocation.lat, selectedLocation.lng) : 'No location selected'}
          </span>
        )}
      </div>

      {selectedLocation && (
        <div className="selected-location-panel__brief">
          <button
            type="button"
            className="selected-location-panel__brief-button"
            disabled={briefStatus === 'loading'}
            onClick={() => {
              if (!selectedLocation) return;
              setBriefStatus('loading');
              downloadBriefPdf(selectedLocation)
                .then(({ blob, filename }) => {
                  // Same hand-rolled anchor click the download page uses. No
                  // library, and no navigation: the map keeps its WebGL context.
                  const href = URL.createObjectURL(blob);
                  const anchor = document.createElement('a');
                  anchor.href = href;
                  anchor.download = filename;
                  anchor.click();
                  URL.revokeObjectURL(href);
                  setBriefStatus('idle');
                })
                .catch(() => setBriefStatus('error'));
            }}
          >
            {briefStatus === 'loading' ? 'Building brief…' : '↓ Point brief (PDF)'}
          </button>
          {briefStatus === 'error' && (
            <span className="selected-location-panel__brief-error">
              Could not build the brief. Try again in a moment.
            </span>
          )}
        </div>
      )}

      <div className="selected-location-panel__body" aria-hidden={!panelOpen}>
        {sstLayerActive && selectedLocation && (
          <div className="selected-location-panel__sst-point">
            <span className="selected-location-panel__sst-point-label">Copernicus SST (cursor)</span>
            {sstStatus === 'loading' && <span>Loading…</span>}
            {sstStatus === 'error' && (
              <span className="selected-location-panel__state--error">SST data unavailable</span>
            )}
            {sstStatus === 'success' && sstPoint && (
              <span className="selected-location-panel__sst-point-value">
                {sstPoint.is_land_or_no_data || sstPoint.temperature_c === null
                  ? 'No data (land or no coverage)'
                  : `${sstPoint.temperature_c.toFixed(1)} °C`}
              </span>
            )}
          </div>
        )}

        {windLayerActive && selectedLocation && (
          <div className="selected-location-panel__wind-point">
            <span className="selected-location-panel__wind-point-label">Copernicus Wind (cursor)</span>
            {windStatus === 'loading' && <span>Loading…</span>}
            {windStatus === 'error' && (
              <span className="selected-location-panel__state--error">Wind data unavailable</span>
            )}
            {windStatus === 'success' && windPoint && (
              <>
                {windPoint.is_land_or_no_data || windPoint.speed_ms === null ? (
                  <span className="selected-location-panel__wind-point-value">No data</span>
                ) : (
                  <>
                    <span className="selected-location-panel__wind-point-value">
                      {windPoint.speed_ms.toFixed(1)} m/s
                    </span>
                    <DirectionValue degrees={windPoint.direction_from_deg} unit="°" mode="from" />
                    {windPoint.beaufort && (
                      <span className="selected-location-panel__wind-point-beaufort">
                        F{windPoint.beaufort.force} · {windPoint.beaufort.label}
                      </span>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        )}

        {currentsLayerActive && selectedLocation && (
          <div className="selected-location-panel__wind-point">
            <span className="selected-location-panel__wind-point-label">
              Copernicus Currents (cursor)
            </span>
            {currentsStatus === 'loading' && <span>Loading…</span>}
            {currentsStatus === 'error' && (
              <span className="selected-location-panel__state--error">
                Currents data unavailable
              </span>
            )}
            {currentsStatus === 'success' && currentsPoint && (
              <>
                {currentsPoint.is_land_or_no_data || currentsPoint.speed_ms === null ? (
                  <span className="selected-location-panel__wind-point-value">No data</span>
                ) : (
                  <>
                    <span className="selected-location-panel__wind-point-value">
                      {currentsPoint.speed_ms.toFixed(2)} m/s
                    </span>
                    {/* "towards", not "from" — a current is named for where the
                        water goes, the opposite of the wind row above. The two
                        rows sit next to each other, so the mode label is what
                        stops one being read as the other. */}
                    <DirectionValue
                      degrees={currentsPoint.direction_toward_deg}
                      unit="°"
                      mode="towards"
                    />
                  </>
                )}
              </>
            )}
          </div>
        )}

        {predictions.length > 0 && selectedLocation && (
          <div className="selected-location-panel__predictions">
            <span className="selected-location-panel__predictions-label">
              Maris AI model output (cursor)
            </span>
            {predictions.map((prediction) => (
              <PredictionRow key={prediction.layerId} prediction={prediction} />
            ))}
            <span className="selected-location-panel__predictions-note">
              Model estimates, not observations. See each layer's attribution for how it was
              trained and where it applies.
            </span>
          </div>
        )}

        {pfz.active && selectedLocation && (
          <div className="selected-location-panel__predictions">
            <span className="selected-location-panel__predictions-label">
              Potential Fishing Zones (screening)
            </span>
            {pfz.loading && <span className="selected-location-panel__state">Scanning…</span>}
            {!pfz.loading && pfz.unavailableReason && (
              <span className="selected-location-panel__state--error">{pfz.unavailableReason}</span>
            )}
            {!pfz.loading && pfz.response?.available && (pfz.response.zones?.length ?? 0) === 0 && (
              <span className="selected-location-panel__state">
                No open-ocean cells with data in this radius.
              </span>
            )}
            {!pfz.loading &&
              pfz.response?.available &&
              (pfz.response.zones ?? []).map((zone) => (
                <div key={`${zone.latitude}-${zone.longitude}`} className="selected-location-panel__prediction">
                  <span className="selected-location-panel__prediction-name">
                    {zone.latitude.toFixed(2)}°, {zone.longitude.toFixed(2)}°
                  </span>
                  <span className="selected-location-panel__prediction-value">
                    {zone.chlorophyll_mg_m3.toFixed(3)} mg/m³
                    <span className="selected-location-panel__prediction-unit">chl · {zone.sst_c.toFixed(1)}°C</span>
                  </span>
                </div>
              ))}
            <span className="selected-location-panel__predictions-note">
              Heuristic screening, not a validated PFZ advisory or an official INCOIS product.
            </span>
          </div>
        )}

        {selectedLocation && (
          <div className="selected-location-panel__route">
            <span className="selected-location-panel__predictions-label">Plan a Route</span>
            <div className="selected-location-panel__route-points">
              <RoutePointRow
                label="Start"
                point={routeStart}
                onSet={() => setRouteStart(selectedLocation)}
              />
              <RoutePointRow
                label="Destination"
                point={routeEnd}
                onSet={() => setRouteEnd(selectedLocation)}
              />
            </div>
            <div className="selected-location-panel__route-actions">
              <button
                type="button"
                className="selected-location-panel__brief-button"
                disabled={!routeStart || !routeEnd || routeStatus === 'loading'}
                onClick={() => void planRoute()}
              >
                {routeStatus === 'loading' ? 'Planning…' : 'Plan route'}
              </button>
              {(routeStart || routeEnd) && (
                <button type="button" className="selected-location-panel__brief-button" onClick={clearRoute}>
                  Clear
                </button>
              )}
            </div>
            {routeStatus === 'error' && (
              <span className="selected-location-panel__state--error">
                {routeError ?? 'Route planning failed.'}
              </span>
            )}
            {routeStatus === 'success' && routeResult && (
              <div className="selected-location-panel__route-result">
                <span>{routeResult.distance_km.toFixed(1)} km (direct: {routeResult.great_circle_km.toFixed(1)} km)</span>
                <span className={`selected-location-panel__route-hazard selected-location-panel__route-hazard--${routeResult.hazard_level}`}>
                  {routeResult.hazard_level}
                  {routeResult.max_wave_height_m != null &&
                    ` · max wave ${routeResult.max_wave_height_m.toFixed(1)} m`}
                </span>
              </div>
            )}
          </div>
        )}

        {selectedLocation && (
          <div className="selected-location-panel__route">
            <span className="selected-location-panel__predictions-label">Plan a Drift Forecast</span>
            <div className="selected-location-panel__route-points">
              <div className="selected-location-panel__route-point">
                <span className="selected-location-panel__route-point-label">Object</span>
                <select
                  className="selected-location-panel__drift-select"
                  value={driftPreset}
                  onChange={(event) => setDriftPreset(event.target.value)}
                >
                  {(leewayPresets.length > 0
                    ? leewayPresets
                    : [{ key: driftPreset, label: driftPreset, alpha: 0, note: '' }]
                  ).map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="selected-location-panel__route-point">
                <span className="selected-location-panel__route-point-label">Horizon</span>
                <select
                  className="selected-location-panel__drift-select"
                  value={driftHorizonHours}
                  onChange={(event) => setDriftHorizonHours(Number(event.target.value))}
                >
                  {[6, 12, 24, 48, 72, 96].map((hours) => (
                    <option key={hours} value={hours}>
                      {hours}h
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="selected-location-panel__route-actions">
              <button
                type="button"
                className="selected-location-panel__brief-button"
                disabled={driftStatus === 'loading'}
                onClick={() => void planTrajectory()}
              >
                {driftStatus === 'loading' ? 'Planning…' : 'Plan drift forecast'}
              </button>
              {driftStatus !== 'idle' && (
                <button type="button" className="selected-location-panel__brief-button" onClick={clearDriftTrajectory}>
                  Clear
                </button>
              )}
            </div>
            {driftStatus === 'error' && (
              <span className="selected-location-panel__state--error">
                {driftError ?? 'Drift trajectory planning failed.'}
              </span>
            )}
            {driftStatus === 'success' && driftResult && (
              <div className="selected-location-panel__route-result">
                <span>
                  {driftResult.n_members}-member ensemble, {driftResult.horizon_hours}h horizon, leeway{' '}
                  {driftResult.leeway_alpha.toFixed(3)}
                </span>
                {driftResult.degraded_terms.length > 0 && (
                  <span className="selected-location-panel__state--error">
                    {driftResult.degraded_terms.join('; ')}
                  </span>
                )}
                <span className="selected-location-panel__drift-note">{driftResult.note}</span>
              </div>
            )}
          </div>
        )}

        {selectedLocation && (
          <div className="selected-location-panel__watch">
            <span className="selected-location-panel__predictions-label">Watch This Location</span>
            <span className="selected-location-panel__predictions-note">
              Get an email when severe weather, a cyclone, or harmful algal bloom risk appears
              here — a threshold rule, not an issued marine warning.
            </span>
            {watchStatus === 'success' ? (
              <span className="selected-location-panel__state">
                Check your email to confirm this watch.
              </span>
            ) : (
              <>
                <div className="selected-location-panel__watch-form">
                  <input
                    type="email"
                    className="selected-location-panel__watch-input"
                    placeholder="you@example.com"
                    value={watchEmail}
                    disabled={watchStatus === 'loading'}
                    onChange={(e) => setWatchEmail(e.target.value)}
                  />
                  <button
                    type="button"
                    className="selected-location-panel__brief-button"
                    disabled={!watchEmail || watchStatus === 'loading'}
                    onClick={() => {
                      if (!selectedLocation) return;
                      setWatchStatus('loading');
                      setWatchError(null);
                      const label = data?.location_context.nearest_port
                        ? `Near ${data.location_context.nearest_port.name}`
                        : formatCoordinates(selectedLocation.lat, selectedLocation.lng);
                      subscribeWatch({
                        email: watchEmail,
                        label,
                        latitude: selectedLocation.lat,
                        longitude: selectedLocation.lng,
                      })
                        .then(() => setWatchStatus('success'))
                        .catch((err) => {
                          setWatchStatus('error');
                          setWatchError(err instanceof Error ? err.message : 'Could not create the watch.');
                        });
                    }}
                  >
                    {watchStatus === 'loading' ? 'Sending…' : 'Watch this location'}
                  </button>
                </div>
                {watchStatus === 'error' && (
                  <span className="selected-location-panel__state--error">
                    {watchError ?? 'Could not create the watch.'}
                  </span>
                )}
              </>
            )}
          </div>
        )}

        {!selectedLocation && (
          <p className="selected-location-panel__state">
            Click any ocean location on the map to load sea surface temperature, wave, current, wind,
            and air temperature data.
          </p>
        )}

        {selectedLocation && status === 'loading' && (
          <p className="selected-location-panel__state">Loading latest marine and weather data…</p>
        )}

        {selectedLocation && status === 'error' && (
          <p className="selected-location-panel__state selected-location-panel__state--error">
            {error ?? 'Failed to load realtime marine conditions.'}
          </p>
        )}

        {selectedLocation && data && status === 'success' && (
          <>
            <div className="selected-location-panel__meta">
              <span>Data time: {data.current.time ?? '—'}</span>
              <span>Fetched: {formatFullDateTime(data.fetched_at, timezone)}</span>
            </div>

            <dl className="selected-location-panel__metrics">
              {METRICS.map((metric) => (
                <div key={metric.key} className="selected-location-panel__metric">
                  <dt>{metric.label}</dt>
                  <dd>
                    {isDirectionMetric(metric.key) ? (
                      <DirectionValue
                        degrees={data.current[metric.key]}
                        unit={data.units[metric.key]}
                        mode={metric.key === 'wave_direction' ? 'from' : 'towards'}
                      />
                    ) : (
                      formatValue(data.current[metric.key], data.units[metric.key])
                    )}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="selected-location-panel__actions">
              <Link
                className="selected-location-panel__more-link"
                to={`/dashboard?lat=${selectedLocation.lat.toFixed(6)}&lon=${selectedLocation.lng.toFixed(6)}`}
              >
                More info
                <span aria-hidden="true">→</span>
              </Link>
            </div>

            <div className="selected-location-panel__attribution">
              Data by{' '}
              <a href={data.attribution.url} target="_blank" rel="noreferrer">
                {data.attribution.name}
              </a>{' '}
              /{' '}
              <a href={data.attribution.provider_url} target="_blank" rel="noreferrer">
                {data.attribution.provider_name}
              </a>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

function RoutePointRow({
  label,
  point,
  onSet,
}: {
  label: string;
  point: { lat: number; lng: number } | null;
  onSet: () => void;
}) {
  return (
    <div className="selected-location-panel__route-point">
      <span className="selected-location-panel__route-point-label">{label}</span>
      {point ? (
        <span className="selected-location-panel__route-point-value">
          {formatCoordinates(point.lat, point.lng)}
        </span>
      ) : (
        <button type="button" className="selected-location-panel__route-set-button" onClick={onSet}>
          Set as {label.toLowerCase()}
        </button>
      )}
    </div>
  );
}

function PredictionRow({ prediction }: { prediction: PredictionPointResult }) {
  const name =
    prediction.source.kind === 'habitat'
      ? `${prediction.source.label} habitat`
      : prediction.source.label;

  return (
    <div className="selected-location-panel__prediction">
      <span className="selected-location-panel__prediction-name">
        {name}
        {prediction.date && (
          <span className="selected-location-panel__prediction-date">{prediction.date}</span>
        )}
      </span>
      {prediction.status === 'loading' && (
        <span className="selected-location-panel__prediction-status">Loading…</span>
      )}
      {prediction.status === 'error' && (
        <span className="selected-location-panel__prediction-status selected-location-panel__state--error">
          Unavailable
        </span>
      )}
      {prediction.status === 'success' && (
        <span className="selected-location-panel__prediction-value">
          {prediction.value !== null ? (
            <>
              {prediction.value.toFixed(2)}
              <span className="selected-location-panel__prediction-unit">
                {prediction.valueLabel}
              </span>
            </>
          ) : (
            <span className="selected-location-panel__prediction-nodata">
              {prediction.outsideCoverage ? 'Outside model region' : 'No data (land or no coverage)'}
            </span>
          )}
        </span>
      )}
      {prediction.status === 'success' && prediction.drivers && prediction.drivers.length > 0 && (
        <div className="selected-location-panel__prediction-drivers">
          {/* Top 3 of the up to 5 the API carries — a presentation choice to
              keep this already-terse panel from growing tall, not a backend
              limit. Don't "fix" this into showing all 5. */}
          {prediction.drivers.slice(0, 3).map((driver) => (
            <span key={driver.feature} className="selected-location-panel__prediction-driver">
              <span>{driver.label}</span>
              <span
                className={`selected-location-panel__prediction-driver-direction selected-location-panel__prediction-driver-direction--${driver.direction}`}
              >
                {driver.direction === 'increases' ? '↑ raises risk' : '↓ lowers risk'}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DirectionValue({
  degrees,
  unit,
  mode,
}: {
  degrees: number | string | null;
  unit: string | null;
  mode: 'from' | 'towards';
}) {
  if (typeof degrees !== 'number') return '—';

  return (
    <span className="selected-location-panel__direction-value">
      <span
        className="selected-location-panel__direction-arrow"
        style={{ transform: `rotate(${degrees}deg)` }}
        aria-hidden="true"
      />
      <span>{formatValue(degrees, unit)}</span>
      <span className="selected-location-panel__direction-mode">{mode}</span>
    </span>
  );
}

function isDirectionMetric(key: keyof RealtimeOceanConditions): key is 'wave_direction' | 'ocean_current_direction' {
  return key === 'wave_direction' || key === 'ocean_current_direction';
}

function formatValue(value: number | string | null, unit: string | null): string {
  if (value == null) return '—';
  if (typeof value === 'number') {
    return `${trimNumber(value)}${unit ? ` ${unit}` : ''}`;
  }
  return unit ? `${value} ${unit}` : value;
}

function trimNumber(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2).replace(/\.0+$|0+$/g, '').replace(/\.$/, '');
}

function formatNearestPort(port: NearestPort | null): string {
  if (!port) return 'Nearest port: Unknown';
  return `Nearest port: ${port.name}, ${port.country} · ${trimNumber(port.distance_km)} km`;
}

function formatCoordinates(lat: number, lng: number): string {
  return `Lat ${lat.toFixed(4)}°, Lon ${lng.toFixed(4)}°`;
}
