const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export type Resolution = 'hourly' | 'daily' | 'weekly' | 'monthly';
export type OutputFormat = 'csv' | 'json' | 'pdf';

export interface PointArea {
  type: 'point';
  lat: number;
  lon: number;
}

export interface BboxArea {
  type: 'bbox';
  west: number;
  south: number;
  east: number;
  north: number;
}

export type Area = PointArea | BboxArea;

export interface DownloadRequest {
  area: Area;
  start_date: string;
  end_date: string;
  resolution: Resolution;
  variables: string[];
  format: OutputFormat;
}

export interface VariableOption {
  code: string;
  label: string;
  unit: string;
  available: boolean;
}

export interface VariableCategory {
  category: string;
  variables: VariableOption[];
}

export interface DownloadFile {
  blob: Blob;
  filename: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchVariableCategories(signal?: AbortSignal): Promise<VariableCategory[]> {
  const response = await fetch(url('/api/v1/variables'), { signal });
  if (!response.ok) {
    throw new Error(`Variable list request failed with status ${response.status}`);
  }
  const payload = (await response.json()) as { categories: VariableCategory[] };
  return payload.categories;
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      // FastAPI/pydantic request-validation error shape.
      return payload.detail
        .map((item) => (item as { msg?: string }).msg ?? '')
        .filter(Boolean)
        .join('; ');
    }
  } catch {
    // Response body wasn't JSON — fall through to the generic message below.
  }
  return `Download request failed with status ${response.status}`;
}

function filenameFromContentDisposition(header: string | null): string {
  const match = header?.match(/filename="?([^"]+)"?/);
  return match?.[1] ?? 'ocean_data_download';
}

export async function downloadOceanData(
  request: DownloadRequest,
  signal?: AbortSignal
): Promise<DownloadFile> {
  const response = await fetch(url('/api/v1/download'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }

  const blob = await response.blob();
  const filename = filenameFromContentDisposition(response.headers.get('Content-Disposition'));
  return { blob, filename };
}
