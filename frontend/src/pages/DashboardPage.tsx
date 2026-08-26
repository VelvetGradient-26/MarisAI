import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode, SubmitEvent } from 'react';
import {
  Activity,
  Anchor,
  ArrowLeft,
  CircuitBoard,
  Compass,
  LocateFixed,
  MapPin,
  Navigation2,
  Sparkles,
  Thermometer,
  Waves,
} from 'lucide-react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { fetchRealtimeOceanData } from '../features/map/api/realtimeOcean';
import type {
  NearestPort,
  RealtimeOceanConditions,
  RealtimeOceanResponse,
} from '../features/map/types';
import { generateOceanInsights } from '../features/insights/api/generateInsights';
import { useTimezoneStore } from '../store/timezoneStore';
import { useThemeStore } from '../store/themeStore';
import { useMapStore } from '../store/mapStore';
import { formatClockDate, formatClockTime, formatShortTime } from '../utils/formatTime';
import './dashboard.css';

type InsightsStatus = 'idle' | 'loading' | 'success' | 'error';

const DEFAULT_LOCATION = { lat: -24.8523, lng: 38.1256 };

type MetricKey = Exclude<keyof RealtimeOceanConditions, 'time'>;

/**
 * Whether the panels below are still waiting on their first response.
 *
 * A context rather than a prop because the flag is read by three leaf
 * components across ~20 call sites that all already take `data`; threading it
 * through each would be noise around a single boolean.
 *
 * It exists because every metric rendered an em dash while loading — which is
 * exactly what this page renders when a value genuinely is not available. The
 * two must not look alike: one resolves into a reading, the other already is
 * the answer.
 */
const PendingContext = createContext(false);

export function DashboardPage() {
  const { searchParams, navigate } = useAppRouter();
  // The map's selected point doubles as "last viewed location" here: it's one
  // shared point of interest, so arriving with no ?lat=&lon= (the navbar's
  // plain "Analytics" link) picks up whatever was last chosen on either page.
  const sharedLocation = useMapStore((s) => s.selectedLocation);
  const focusSelectedLocation = useMapStore((s) => s.focusSelectedLocation);
  const urlLocation = readCoordinates(searchParams);
  const requestedLocation = urlLocation ?? sharedLocation ?? DEFAULT_LOCATION;
  const [latitudeInput, setLatitudeInput] = useState(String(requestedLocation.lat));
  const [longitudeInput, setLongitudeInput] = useState(String(requestedLocation.lng));
  const isDark = useThemeStore((s) => s.dark);
  const [data, setData] = useState<RealtimeOceanResponse | null>(null);
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [requestError, setRequestError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const timezone = useTimezoneStore((s) => s.timezone);
  const [insightsStatus, setInsightsStatus] = useState<InsightsStatus>('idle');
  const [insightsText, setInsightsText] = useState<string | null>(null);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const insightsAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Ocean Analytics';
    const interval = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    setLatitudeInput(formatCoordinateInput(requestedLocation.lat));
    setLongitudeInput(formatCoordinateInput(requestedLocation.lng));
  }, [requestedLocation.lat, requestedLocation.lng]);

  // Every explicitly chosen coordinate reaches this page through the URL —
  // the form and the geolocation button both navigate() rather than setting
  // state directly — so this is the one place that publishes a choice to the
  // shared map state. The DEFAULT_LOCATION fallback deliberately doesn't
  // publish: nobody picked it, so it shouldn't drop a pin on the map.
  const urlLat = urlLocation?.lat ?? null;
  const urlLng = urlLocation?.lng ?? null;
  useEffect(() => {
    if (urlLat === null || urlLng === null) return;
    focusSelectedLocation({ lat: urlLat, lng: urlLng });
  }, [urlLat, urlLng, focusSelectedLocation]);

  useEffect(() => {
    const abortController = new AbortController();
    setStatus('loading');
    setRequestError(null);
    setData(null);

    fetchRealtimeOceanData(
      { lat: requestedLocation.lat, lng: requestedLocation.lng },
      abortController.signal
    )
      .then((response) => {
        setData(response);
        setStatus('success');
      })
      .catch((error: unknown) => {
        if (abortController.signal.aborted) return;
        setData(null);
        setStatus('error');
        setRequestError(error instanceof Error ? error.message : 'Failed to load ocean analytics');
      });

    return () => abortController.abort();
  }, [requestedLocation.lat, requestedLocation.lng, requestVersion]);

  useEffect(() => {
    insightsAbortRef.current?.abort();
    setInsightsStatus('idle');
    setInsightsText(null);
    setInsightsError(null);
  }, [requestedLocation.lat, requestedLocation.lng, requestVersion]);

  const runInsights = () => {
    if (!data || insightsStatus === 'loading') return;

    insightsAbortRef.current?.abort();
    const controller = new AbortController();
    insightsAbortRef.current = controller;

    setInsightsStatus('loading');
    setInsightsError(null);

    generateOceanInsights(data, controller.signal)
      .then((response) => {
        setInsightsText(response.insights);
        setInsightsStatus('success');
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setInsightsStatus('error');
        setInsightsError(error instanceof Error ? error.message : 'Failed to generate insights');
      });
  };

  const updateLocation = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextLocation = validateCoordinates(latitudeInput, longitudeInput);
    if (!nextLocation) {
      setFormError('Enter a latitude from -90 to 90 and longitude from -180 to 180.');
      return;
    }

    setFormError(null);
    navigate(dashboardUrl(nextLocation.lat, nextLocation.lng));
    setRequestVersion((value) => value + 1);
  };

  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setFormError('Location services are not available in this browser.');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = Number(position.coords.latitude.toFixed(6));
        const lng = Number(position.coords.longitude.toFixed(6));
        setLatitudeInput(String(lat));
        setLongitudeInput(String(lng));
        setFormError(null);
        navigate(dashboardUrl(lat, lng));
        setRequestVersion((value) => value + 1);
      },
      () => setFormError('Unable to access your current location.')
    );
  };

  const timeString = formatClockTime(now, timezone);
  const dateString = formatClockDate(now, timezone);

  return (
    <div className={`dashboard-shell ${isDark ? 'dashboard-shell--dark' : 'dashboard-shell--light'}`}>
      <main className="dashboard-main">
        <div className="dashboard-toolbar">
          <div className="dashboard-clock">
            <strong>{timeString}</strong>
            <span>
              {dateString} · {timezone}
            </span>
          </div>
        </div>

        <div className="dashboard-title-row">
          <div>
            <Link to="/map" className="dashboard-back-link">
              <ArrowLeft size={14} /> Back to map
            </Link>
            <h1>Ocean intelligence</h1>
            <p>Live model conditions for a selected coordinate.</p>
          </div>
          <div className={`dashboard-live-status dashboard-live-status--${status}`}>
            <Activity size={14} />
            {status === 'loading' ? 'Updating feed' : status === 'success' ? 'Live data' : 'Feed error'}
          </div>
        </div>

        <form className="dashboard-coordinate-form" onSubmit={updateLocation}>
          <div className="dashboard-coordinate-form__label">Input target coordinates</div>
          <CoordinateInput
            label="LAT"
            value={latitudeInput}
            onChange={setLatitudeInput}
            ariaLabel="Latitude"
          />
          <CoordinateInput
            label="LON"
            value={longitudeInput}
            onChange={setLongitudeInput}
            ariaLabel="Longitude"
          />
          <button className="dashboard-update-button" type="submit">
            <Compass size={16} />
            Update analytics
          </button>
          <button
            className="dashboard-location-button"
            type="button"
            onClick={useCurrentLocation}
            aria-label="Use current location"
          >
            <LocateFixed size={18} />
          </button>
          {formError && <p className="dashboard-form-error">{formError}</p>}
        </form>

        {requestError && <div className="dashboard-request-error">{requestError}</div>}

        {/* `!data` matters: on a *refresh* the previous readings are still on
            screen and correct, so only the cold start shows skeletons. Replacing
            live values with shimmer on every location change would be worse
            than the em dashes this replaces. */}
        <PendingContext.Provider value={status === 'loading' && !data}>
          <div className="dashboard-grid" aria-busy={status === 'loading'}>
            <DashboardCard>
              <CardHeader icon={<Waves size={17} />} title="Ocean metrics" />
              <div className="dashboard-metric-list">
                <MetricRow label="Sea Surface Temp" metric="sea_surface_temperature" data={data} />
                <MetricRow label="Wave Height" metric="wave_height" data={data} />
                <MetricRow label="Wave Direction" metric="wave_direction" data={data} direction />
                <MetricRow label="Wave Period" metric="wave_period" data={data} />
                <MetricRow label="Current Speed" metric="ocean_current_velocity" data={data} />
                <MetricRow
                  label="Current Direction"
                  metric="ocean_current_direction"
                  data={data}
                  direction
                />
                <MetricRow label="Sea Level MSL" metric="sea_level_height_msl" data={data} />
              </div>
              <CardFooter data={data} />
            </DashboardCard>

            <DashboardCard>
              <CardHeader icon={<Thermometer size={17} />} title="Atmospheric" />
              <div className="dashboard-stat-grid">
                <StatBlock label="Wind Speed" metric="wind_speed" data={data} />
                <StatBlock label="Wind Direction" metric="wind_direction" data={data} direction />
                <StatBlock label="Air Temp" metric="air_temperature" data={data} />
                <StatBlock label="Humidity" metric="relative_humidity" data={data} />
                <StatBlock label="Pressure" metric="surface_pressure" data={data} />
                <StatBlock label="Visibility" metric="visibility" data={data} visibility />
                <StatBlock label="Cloud Cover" metric="cloud_cover" data={data} />
                <StatBlock label="Precipitation" metric="precipitation" data={data} />
              </div>
            </DashboardCard>

            <DashboardCard>
              <CardHeader icon={<Compass size={17} />} title="Geo-location" />
              <div className="dashboard-location-content">
                <LocationDetail
                  icon={<MapPin size={18} />}
                  label="Ocean sector"
                  value={
                    data?.location_context.ocean_name ??
                    data?.location_context.locality ??
                    'Open ocean'
                  }
                  description={data?.location_context.continent ?? 'International waters'}
                />
                <LocationDetail
                  icon={<Anchor size={18} />}
                  label="Nearest port"
                  value={data?.location_context.nearest_port?.name ?? '—'}
                  description={formatNearestPort(data?.location_context.nearest_port ?? null)}
                />
                <LocationDetail
                  icon={<Navigation2 size={18} />}
                  label="Requested point"
                  value={`${requestedLocation.lat.toFixed(4)}°, ${requestedLocation.lng.toFixed(4)}°`}
                  description={formatResolvedPoint(data)}
                />
                <div className="dashboard-location-summary">
                  <div>
                    <span>Timezone</span>
                    <strong>{formatTimezone(data)}</strong>
                  </div>
                  <div>
                    <span>Status</span>
                    <strong className="dashboard-status-badge">
                      {status === 'success' ? 'LIVE' : status.toUpperCase()}
                    </strong>
                  </div>
                </div>
              </div>
            </DashboardCard>
          </div>
        </PendingContext.Provider>

        {insightsStatus !== 'idle' && (
          <section className="dashboard-card dashboard-insights-card">
            <CardHeader icon={<Sparkles size={17} />} title="AI Insights" />
            <div className="dashboard-insights-body">
              {insightsStatus === 'loading' && (
                <p className="dashboard-insights-loading">Analyzing live conditions…</p>
              )}
              {insightsStatus === 'error' && (
                <p className="dashboard-insights-error">{insightsError}</p>
              )}
              {insightsStatus === 'success' && insightsText && (
                <ul className="dashboard-insights-list">
                  {formatInsightLines(insightsText).map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}

        <div className="dashboard-attribution">
          {data ? (
            <span>
              Marine and weather data by{' '}
              <a href={data.attribution.url} target="_blank" rel="noreferrer">
                {data.attribution.name}
              </a>{' '}
              /{' '}
              <a href={data.attribution.provider_url} target="_blank" rel="noreferrer">
                {data.attribution.provider_name}
              </a>
            </span>
          ) : (
            <span>Marine and weather data by Open-Meteo / DWD</span>
          )}
          <span>Forecast data is not suitable for navigation.</span>
        </div>
      </main>

      <button
        className="dashboard-neural-badge"
        type="button"
        onClick={runInsights}
        disabled={!data || insightsStatus === 'loading'}
        aria-label="Generate AI insights from current conditions"
      >
        <span><CircuitBoard size={14} /></span>
        {insightsStatus === 'loading' ? 'Analyzing…' : 'Neuralcore'}
      </button>
    </div>
  );
}

function CoordinateInput({
  label,
  value,
  onChange,
  ariaLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <label className="dashboard-coordinate-input">
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="decimal"
        aria-label={ariaLabel}
      />
      <span>{label}</span>
    </label>
  );
}

function DashboardCard({ children }: { children: ReactNode }) {
  return <section className="dashboard-card">{children}</section>;
}

function CardHeader({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="dashboard-card__header">
      <div>{icon}<span>{title}</span></div>
    </div>
  );
}

function MetricRow({
  label,
  metric,
  data,
  direction = false,
}: {
  label: string;
  metric: MetricKey;
  data: RealtimeOceanResponse | null;
  direction?: boolean;
}) {
  const pending = useContext(PendingContext);
  return (
    <div className="dashboard-metric-row">
      <span>{label}</span>
      <strong>
        {pending ? (
          <span className="ma-skeleton ma-skeleton--bubble" style={{ width: '3.5rem' }} />
        ) : (
          formatMetric(data, metric, { direction })
        )}
      </strong>
    </div>
  );
}

function StatBlock({
  label,
  metric,
  data,
  direction = false,
  visibility = false,
}: {
  label: string;
  metric: MetricKey;
  data: RealtimeOceanResponse | null;
  direction?: boolean;
  visibility?: boolean;
}) {
  const pending = useContext(PendingContext);
  return (
    <div className="dashboard-stat-block">
      <span>{label}</span>
      <strong>
        {pending ? (
          <span className="ma-skeleton ma-skeleton--bubble" style={{ width: '3rem' }} />
        ) : (
          formatMetric(data, metric, { direction, visibility })
        )}
      </strong>
    </div>
  );
}

function CardFooter({ data }: { data: RealtimeOceanResponse | null }) {
  const timezone = useTimezoneStore((s) => s.timezone);
  return (
    <div className="dashboard-card__footer">
      {data ? `Fetched ${formatShortTime(data.fetched_at, timezone)}` : 'Awaiting model data'}
    </div>
  );
}

function LocationDetail({
  icon,
  label,
  value,
  description,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  description: string;
}) {
  const pending = useContext(PendingContext);
  return (
    <div className="dashboard-location-detail">
      {icon}
      <div>
        <span>{label}</span>
        <strong>{pending ? <span className="ma-skeleton ma-skeleton--bubble" style={{ width: '7rem' }} /> : value}</strong>
        <p>{pending ? <span className="ma-skeleton ma-skeleton--bubble" style={{ width: '9rem' }} /> : description}</p>
      </div>
    </div>
  );
}

function readCoordinates(searchParams: URLSearchParams) {
  const lat = Number(searchParams.get('lat'));
  const lng = Number(searchParams.get('lon'));
  if (!searchParams.has('lat') || !searchParams.has('lon')) return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  return { lat, lng };
}

/** A map click arrives at full float precision (`23.193346783178256`), which
 * is unreadable in a coordinate field and finer than any model grid cell.
 * Six decimals is ~10cm and matches what the map's "More info" link writes
 * into the URL. */
function formatCoordinateInput(value: number) {
  return String(Number(value.toFixed(6)));
}

function dashboardUrl(lat: number, lng: number) {
  const params = new URLSearchParams({ lat: String(lat), lon: String(lng) });
  return `/dashboard?${params}`;
}

function validateCoordinates(latitude: string, longitude: string) {
  const lat = Number(latitude);
  const lng = Number(longitude);
  if (!latitude.trim() || !longitude.trim()) return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  return { lat, lng };
}

function formatMetric(
  data: RealtimeOceanResponse | null,
  metric: MetricKey,
  options: { direction?: boolean; visibility?: boolean } = {}
) {
  const value = data?.current[metric];
  const unit = data?.units[metric];
  if (typeof value !== 'number') return '—';

  if (options.direction) return `${trimNumber(value)}° ${cardinalDirection(value)}`;
  if (options.visibility && unit === 'm') return `${trimNumber(value / 1000)} km`;
  return `${trimNumber(value)}${unit ? ` ${unit}` : ''}`;
}

function cardinalDirection(degrees: number) {
  const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  return directions[Math.round(((degrees % 360) + 360) % 360 / 45) % directions.length];
}

function trimNumber(value: number) {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2).replace(/\.0+$|0+$/g, '').replace(/\.$/, '');
}

function formatResolvedPoint(data: RealtimeOceanResponse | null) {
  const point = data?.resolved.marine;
  if (typeof point?.latitude !== 'number' || typeof point.longitude !== 'number') {
    return 'Resolving nearest marine model cell';
  }
  return `Model cell ${point.latitude.toFixed(3)}°, ${point.longitude.toFixed(3)}°`;
}

function formatNearestPort(port: NearestPort | null) {
  if (!port) return 'Resolving nearest port';
  return `${trimNumber(port.distance_km)} km · ${port.country}`;
}

function formatTimezone(data: RealtimeOceanResponse | null) {
  const point = data?.resolved.marine;
  if (!point?.timezone) return '—';
  return point.timezone_abbreviation ? `${point.timezone_abbreviation} · ${point.timezone}` : point.timezone;
}

function formatInsightLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/^[\s*•-]+/, '').replace(/^\d+\.\s*/, '').trim())
    .filter(Boolean);
}

