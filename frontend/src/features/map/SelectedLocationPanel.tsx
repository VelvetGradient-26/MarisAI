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
import type { CurrentsPointResponse } from './api/currents';
import { useSelectedLocationPredictions } from './hooks/useSelectedLocationPredictions';
import type { PredictionPointResult } from './hooks/useSelectedLocationPredictions';
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
