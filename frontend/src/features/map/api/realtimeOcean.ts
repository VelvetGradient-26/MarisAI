import type { CursorCoordinates, RealtimeOceanResponse } from '../types';

import { API_BASE_URL } from '../../../utils/apiBase';

export async function fetchRealtimeOceanData(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<RealtimeOceanResponse> {
  const url = API_BASE_URL
    ? new URL('/api/ocean/realtime', API_BASE_URL)
    : new URL('/api/ocean/realtime', window.location.origin);
  url.searchParams.set('lat', String(location.lat));
  url.searchParams.set('lon', String(location.lng));

  let response: Response;

  try {
    response = await fetch(url, { signal });
  } catch (error: unknown) {
    if (signal?.aborted) throw error;

    throw new Error(
      'Could not reach the backend API. Start the FastAPI server or set VITE_API_BASE_URL to a running backend.'
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `Realtime ocean request failed with status ${response.status}`);
  }

  const payload = (await response.json()) as Partial<RealtimeOceanResponse>;
  return normalizeRealtimeOceanResponse(payload, location);
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? null;
  } catch {
    return null;
  }
}

function normalizeRealtimeOceanResponse(
  payload: Partial<RealtimeOceanResponse>,
  location: CursorCoordinates
): RealtimeOceanResponse {
  return {
    requested: payload.requested ?? {
      latitude: location.lat,
      longitude: location.lng,
    },
    resolved: payload.resolved ?? {
      marine: {
        latitude: null,
        longitude: null,
        timezone: null,
        timezone_abbreviation: null,
      },
      weather: {
        latitude: null,
        longitude: null,
        timezone: null,
        timezone_abbreviation: null,
      },
    },
    location_context: payload.location_context ?? {
      ocean_name: null,
      nearest_port: null,
      locality: null,
      continent: null,
    },
    fetched_at: payload.fetched_at ?? new Date().toISOString(),
    current: {
      time: payload.current?.time ?? null,
      sea_surface_temperature: payload.current?.sea_surface_temperature ?? null,
      wave_height: payload.current?.wave_height ?? null,
      wave_direction: payload.current?.wave_direction ?? null,
      wave_period: payload.current?.wave_period ?? null,
      ocean_current_velocity: payload.current?.ocean_current_velocity ?? null,
      ocean_current_direction: payload.current?.ocean_current_direction ?? null,
      sea_level_height_msl: payload.current?.sea_level_height_msl ?? null,
      wind_speed: payload.current?.wind_speed ?? null,
      wind_direction: payload.current?.wind_direction ?? null,
      air_temperature: payload.current?.air_temperature ?? null,
      relative_humidity: payload.current?.relative_humidity ?? null,
      surface_pressure: payload.current?.surface_pressure ?? null,
      visibility: payload.current?.visibility ?? null,
      cloud_cover: payload.current?.cloud_cover ?? null,
      precipitation: payload.current?.precipitation ?? null,
    },
    units: {
      sea_surface_temperature: payload.units?.sea_surface_temperature ?? null,
      wave_height: payload.units?.wave_height ?? null,
      wave_direction: payload.units?.wave_direction ?? null,
      wave_period: payload.units?.wave_period ?? null,
      ocean_current_velocity: payload.units?.ocean_current_velocity ?? null,
      ocean_current_direction: payload.units?.ocean_current_direction ?? null,
      sea_level_height_msl: payload.units?.sea_level_height_msl ?? null,
      wind_speed: payload.units?.wind_speed ?? null,
      wind_direction: payload.units?.wind_direction ?? null,
      air_temperature: payload.units?.air_temperature ?? null,
      relative_humidity: payload.units?.relative_humidity ?? null,
      surface_pressure: payload.units?.surface_pressure ?? null,
      visibility: payload.units?.visibility ?? null,
      cloud_cover: payload.units?.cloud_cover ?? null,
      precipitation: payload.units?.precipitation ?? null,
    },
    attribution: {
      name: payload.attribution?.name ?? 'Open-Meteo',
      url: payload.attribution?.url ?? 'https://open-meteo.com/',
      provider_name: payload.attribution?.provider_name ?? 'DWD',
      provider_url: payload.attribution?.provider_url ?? 'https://www.dwd.de/',
    },
  };
}
