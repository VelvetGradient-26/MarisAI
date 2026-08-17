/**
 * Where the backend is, in one place.
 *
 * Every API client in this app opened with the same line —
 * `const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;` — and **that line
 * is a bug without a fallback.** Vite only defines a `VITE_*` variable when an
 * `.env` file declares it. There is no committed `.env` here (credentials live
 * in `backend/.env`, and the dev server proxies `/api` to `127.0.0.1:8000`
 * instead), so in an ordinary checkout the value is `undefined` and every
 * template literal built from it produces `"undefined/api/ocean/eddies"` — a
 * *relative* path. The dev server answers any unmatched path with `index.html`,
 * so the fetch resolves **200 OK with an HTML body**, sails past the
 * `response.ok` check every one of those clients performs, and fails in
 * `.json()` as:
 *
 *     Unexpected token '<', "<!doctype "... is not valid JSON
 *
 * which names neither the URL nor the missing variable. Three of the twenty-odd
 * clients had independently grown `|| window.location.origin`, which is why the
 * raster layers worked while the eddy, marine-heatwave, upwelling and eDNA
 * layers — the ones that fetch JSON — did not.
 *
 * Same-origin is the right default rather than merely a safe one: in
 * development it hands the path to Vite's `/api` proxy, and in a normal
 * deployment the API is served from the same origin as the app. Setting
 * `VITE_API_BASE_URL` remains the way to point at a backend somewhere else.
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || window.location.origin;

/** `API_BASE_URL` joined to an absolute path such as `/api/ocean/eddies`. */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/**
 * `fetch` + `.json()`, with the one failure this app has actually hit made
 * legible.
 *
 * A misrouted API call does not fail — it *succeeds* with the SPA's own
 * `index.html`, because a dev server answers any unmatched path that way. The
 * status is 200, so an `if (!response.ok)` guard passes it through, and the
 * error surfaces from `JSON.parse` as `Unexpected token '<', "<!doctype "...`,
 * naming neither the URL nor the cause. Checking the content type turns that
 * into a message that says what was requested and what came back.
 */
export async function fetchJson<T>(
  path: string,
  init: RequestInit | undefined,
  describe: (status: number) => string
): Promise<T> {
  const target = apiUrl(path);
  const response = await fetch(target, init);
  if (!response.ok) throw new Error(describe(response.status));

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) {
    throw new Error(
      `Expected JSON from ${target} but the server sent ${contentType || 'no content type'}. ` +
        'The request did not reach the API — check that the backend is running and that ' +
        'the dev server is proxying /api to it.'
    );
  }
  return (await response.json()) as T;
}
