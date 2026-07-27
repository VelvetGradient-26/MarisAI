import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  Activity,
  Anchor,
  ArrowLeft,
  ChevronDown,
  CircuitBoard,
  Compass,
  LocateFixed,
  MapPin,
  Moon,
  Navigation2,
  Sparkles,
  Sun,
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
import './dashboard.css';

type InsightsStatus = 'idle' | 'loading' | 'success' | 'error';

const DEFAULT_LOCATION = { lat: -24.8523, lng: 38.1256 };

type MetricKey = Exclude<keyof RealtimeOceanConditions, 'time'>;

export function DashboardPage() {
  const { searchParams, navigate } = useAppRouter();
  const requestedLocation = readCoordinates(searchParams) ?? DEFAULT_LOCATION;
  const [latitudeInput, setLatitudeInput] = useState(String(requestedLocation.lat));
  const [longitudeInput, setLongitudeInput] = useState(String(requestedLocation.lng));
  const [isDark, setIsDark] = useState(true);
  const [data, setData] = useState<RealtimeOceanResponse | null>(null);
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [requestError, setRequestError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [now, setNow] = useState(() => new Date());
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
    setLatitudeInput(String(requestedLocation.lat));
    setLongitudeInput(String(requestedLocation.lng));
  }, [requestedLocation.lat, requestedLocation.lng]);

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

  const updateLocation = (event: FormEvent<HTMLFormElement>) => {
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

  const timeString = now.toLocaleTimeString('en-GB', {
    timeZone: 'UTC',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const dateString = now
    .toLocaleDateString('en-US', {
      timeZone: 'UTC',
      month: 'short',
      day: '2-digit',
      year: 'numeric',
    })
    .toUpperCase();

  return (
    <div className={`dashboard-shell ${isDark ? 'dashboard-shell--dark' : 'dashboard-shell--light'}`}>
      <header className="dashboard-header">
        <div className="dashboard-header__inner">
          <Link className="dashboard-logo" to="/">
            Maris AI
          </Link>

          <nav className="dashboard-nav" aria-label="Dashboard navigation">
            <span className="is-active">Analytics</span>
            <Link to="/map">Map</Link>
          </nav>

          <div className="dashboard-header__account">
            <div className="dashboard-clock">
              <strong>{timeString} UTC</strong>
              <span>{dateString}</span>
            </div>
            <div className="dashboard-avatar" aria-label="Maris AI account">
              MA
            </div>
            <button
              className="dashboard-theme-button"
              type="button"
              onClick={() => setIsDark((value) => !value)}
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {isDark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
        </div>
      </header>

      <main className="dashboard-main">
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

        <div className="dashboard-grid" aria-busy={status === 'loading'}>
          <DashboardCard active>
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

          <DashboardCard active>
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
              <Radar />
            </div>
          </DashboardCard>
        </div>

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

function DashboardCard({ children, active = false }: { children: ReactNode; active?: boolean }) {
  return <section className={`dashboard-card ${active ? 'dashboard-card--active' : ''}`}>{children}</section>;
}

function CardHeader({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="dashboard-card__header">
      <div>{icon}<span>{title}</span></div>
      <ChevronDown size={16} />
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
  return (
    <div className="dashboard-metric-row">
      <span>{label}</span>
      <strong>{formatMetric(data, metric, { direction })}</strong>
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
  return (
    <div className="dashboard-stat-block">
      <span>{label}</span>
      <strong>{formatMetric(data, metric, { direction, visibility })}</strong>
    </div>
  );
}

function CardFooter({ data }: { data: RealtimeOceanResponse | null }) {
  return (
    <div className="dashboard-card__footer">
      {data ? `Fetched ${formatTimestamp(data.fetched_at)}` : 'Awaiting model data'}
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
  return (
    <div className="dashboard-location-detail">
      {icon}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}

function Radar() {
  const dots = [
    [62, 40], [120, 55], [90, 90], [140, 100], [50, 100], [100, 30], [70, 120],
  ];

  return (
    <div className="dashboard-radar" aria-hidden="true">
      <svg viewBox="0 0 200 150" width="100%" height="100%">
        <g fill="none" strokeWidth="1">
          <circle cx="100" cy="75" r="60" />
          <circle cx="100" cy="75" r="40" />
          <circle cx="100" cy="75" r="20" />
          <line x1="20" y1="75" x2="180" y2="75" />
          <line x1="100" y1="5" x2="100" y2="145" />
        </g>
        {dots.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="2" />)}
        <text x="100" y="16" textAnchor="middle">N</text>
        <text x="100" y="140" textAnchor="middle">S</text>
        <text x="12" y="78">W</text>
        <text x="184" y="78">E</text>
      </svg>
      <div className="dashboard-radar__sweep" />
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

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
