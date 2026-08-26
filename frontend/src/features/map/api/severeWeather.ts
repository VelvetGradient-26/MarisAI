import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * IMD severe-weather alerts (heavy rain, heatwave, cold wave, thunderstorm/
 * lightning, ...) — `GET /api/ocean/severe-weather`. Nationwide, not
 * scoped to the coast, and not a cyclone-track bulletin; see
 * `services/severe_weather.py`. No per-alert geometry is exposed (a CAP
 * polygon/circle is internal to the backend), so this drives a panel/badge
 * rather than a map layer.
 */
export interface SevereWeatherAlert {
  event: string;
  headline: string;
  description: string;
  severity: string;
  urgency: string;
  certainty: string;
  onset: string | null;
  expires: string | null;
  area: string;
  url: string;
}

export interface SevereWeatherResponse {
  alerts: SevereWeatherAlert[];
  count: number;
  source: string;
  note: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchSevereWeatherAlerts(signal?: AbortSignal): Promise<SevereWeatherResponse> {
  const response = await fetch(url('/api/ocean/severe-weather'), { signal });
  if (!response.ok) {
    throw new Error(`Severe-weather alerts unavailable (${response.status})`);
  }
  return (await response.json()) as SevereWeatherResponse;
}
