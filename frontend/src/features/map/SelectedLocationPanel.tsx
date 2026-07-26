import { useMapStore } from '../../store/mapStore';
import type { RealtimeOceanConditions, RealtimeOceanUnits } from './types';

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

  return (
    <aside className="selected-location-panel">
      <div className="selected-location-panel__header">
        <h3>Realtime Marine Conditions</h3>
<<<<<<< HEAD
        {selectedLocation && data ? (
          <>
            <span>{data.location_context.ocean_name ?? 'Ocean: Unknown'}</span>
            <span>{data.location_context.country_name ?? 'Country: Unknown'}</span>
            <span>{formatCoordinates(selectedLocation.lat, selectedLocation.lng)}</span>
          </>
        ) : (
          <span>{selectedLocation ? formatCoordinates(selectedLocation.lat, selectedLocation.lng) : 'No location selected'}</span>
        )}
=======
        <span>
          {selectedLocation
            ? `${selectedLocation.lat.toFixed(4)}°, ${selectedLocation.lng.toFixed(4)}°`
            : 'No location selected'}
        </span>
>>>>>>> feature/map-label
      </div>

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
            <span>Fetched: {formatTimestamp(data.fetched_at)}</span>
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
        </>
      )}
    </aside>
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

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
<<<<<<< HEAD

function formatCoordinates(lat: number, lng: number): string {
  return `Lat ${lat.toFixed(4)}°, Lon ${lng.toFixed(4)}°`;
}
=======
>>>>>>> feature/map-label
