import { useEffect, useMemo, useState } from 'react';
import type { SubmitEvent } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from '../app/router';
import { DrawableAreaMap } from '../features/map/DrawableAreaMap';
import type { DrawnBbox } from '../features/map/DrawableAreaMap';
import { useThemeStore } from '../store/themeStore';
import { useToastStore } from '../store/toastStore';
import {
  downloadOceanData,
  fetchDownloadProgress,
  fetchVariableCategories,
  type Area,
  type OutputFormat,
  type Resolution,
  type VariableCategory,
} from '../features/map/api/download';
import './download.css';

/**
 * How often to ask the server where the download has got to.
 *
 * The signal being watched is one upstream provider finishing, of which there
 * are at most fourteen across a request measured in tens of seconds — so this
 * is fast enough that the bar never visibly lags a real step, and slow enough
 * that a two-minute download costs ~160 dict lookups rather than thousands.
 */
const PROGRESS_POLL_MS = 750;

/** Plain-language stage names. The API's own words are internal. */
const STAGE_LABELS: Record<string, string> = {
  preparing: 'Checking coverage and limits',
  fetching: 'Fetching from data providers',
  merging: 'Merging and cleaning',
  formatting: 'Formatting your file',
  done: 'Finishing up',
};

type AreaMode = 'point' | 'draw';

interface BboxFields {
  west: string;
  south: string;
  east: string;
  north: string;
}

const DEFAULT_BBOX: BboxFields = { west: '72.5', south: '8.0', east: '77.5', north: '13.0' };

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function parseNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function DownloadPage() {
  const isDark = useThemeStore((s) => s.dark);
  const pushToast = useToastStore((s) => s.push);
  const updateToast = useToastStore((s) => s.update);
  const patchToast = useToastStore((s) => s.patch);
  const dismissToast = useToastStore((s) => s.dismiss);
  const [areaMode, setAreaMode] = useState<AreaMode>('draw');
  const [lat, setLat] = useState('10.0');
  const [lon, setLon] = useState('75.0');
  const [bbox, setBbox] = useState<BboxFields>(DEFAULT_BBOX);

  const [startDate, setStartDate] = useState('2025-01-01');
  const [endDate, setEndDate] = useState('2025-01-05');
  const [resolution, setResolution] = useState<Resolution>('daily');
  const [format, setFormat] = useState<OutputFormat>('csv');

  const [categories, setCategories] = useState<VariableCategory[]>([]);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);
  const [selectedVariables, setSelectedVariables] = useState<Set<string>>(
    () => new Set(['sea_surface_temperature'])
  );

  const [depth, setDepth] = useState('0');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Download Ocean Data';
  }, []);

  // A pending toast is owned by the request that raised it, so a user who
  // navigates away mid-download would otherwise leave a spinner up forever.
  useEffect(() => {
    return () => {
      useToastStore.getState().toasts.forEach((toast) => {
        if (toast.tone === 'pending') dismissToast(toast.id);
      });
    };
  }, [dismissToast]);

  useEffect(() => {
    const controller = new AbortController();
    fetchVariableCategories(controller.signal)
      .then(setCategories)
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setCategoriesError(err instanceof Error ? err.message : 'Failed to load variable list');
      });
    return () => controller.abort();
  }, []);

  const drawnBbox: DrawnBbox | null = useMemo(() => {
    const west = parseNumber(bbox.west);
    const south = parseNumber(bbox.south);
    const east = parseNumber(bbox.east);
    const north = parseNumber(bbox.north);
    if (west === null || south === null || east === null || north === null) return null;
    return { west, south, east, north };
  }, [bbox]);

  // Which of the selected variables actually read the depth setting. Depth is
  // meaningless for the other 30-odd, so the control only comes alive here.
  const depthVariables = useMemo(
    () =>
      categories
        .flatMap((cat) => cat.variables)
        .filter((v) => v.depth_resolved && selectedVariables.has(v.code)),
    [categories, selectedVariables]
  );
  const needsDepth = depthVariables.length > 0;

  // Depth lives under Advanced Options, which starts collapsed — so selecting
  // a depth-resolved variable would otherwise silently use the default with
  // the one control that matters hidden. Reveal it instead.
  useEffect(() => {
    if (needsDepth) setAdvancedOpen(true);
  }, [needsDepth]);

  function toggleVariable(code: string) {
    setSelectedVariables((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function handleDraw(next: DrawnBbox) {
    setBbox({
      west: next.west.toFixed(4),
      south: next.south.toFixed(4),
      east: next.east.toFixed(4),
      north: next.north.toFixed(4),
    });
  }

  async function handleSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitError(null);

    let area: Area;
    if (areaMode === 'point') {
      const parsedLat = parseNumber(lat);
      const parsedLon = parseNumber(lon);
      if (parsedLat === null || parsedLon === null) {
        setSubmitError('Enter a valid latitude and longitude.');
        return;
      }
      area = { type: 'point', lat: parsedLat, lon: parsedLon };
    } else {
      const west = parseNumber(bbox.west);
      const south = parseNumber(bbox.south);
      const east = parseNumber(bbox.east);
      const north = parseNumber(bbox.north);
      if (west === null || south === null || east === null || north === null) {
        setSubmitError('Enter a valid bounding box, or draw one on the map.');
        return;
      }
      if (east <= west || north <= south) {
        setSubmitError('East must be greater than West, and North greater than South.');
        return;
      }
      area = { type: 'bbox', west, south, east, north };
    }

    if (!startDate || !endDate) {
      setSubmitError('Choose a start and end date.');
      return;
    }
    if (endDate < startDate) {
      setSubmitError('End date must not be before start date.');
      return;
    }
    if (selectedVariables.size === 0) {
      setSubmitError('Select at least one variable.');
      return;
    }

    const parsedDepth = parseNumber(depth);
    if (needsDepth && (parsedDepth === null || parsedDepth < 0 || parsedDepth > 6000)) {
      setSubmitError('Enter a depth between 0 and 6000 metres.');
      return;
    }

    setSubmitStatus('loading');
    // A real request fetches from up to 14 upstream providers and can run well
    // past 30 seconds. The button's label changing was the only sign anything
    // was happening, and the *result* — a file landing in the browser's
    // download tray — happened entirely off-page. The toast covers both: it
    // stays pending for the duration, then reports the outcome.
    const variableCount = selectedVariables.size;
    const summary = `${variableCount} variable${variableCount === 1 ? '' : 's'}, ${startDate} to ${endDate}`;
    const toastId = pushToast({
      tone: 'pending',
      title: 'Preparing your download…',
      detail: summary,
      // No `progress` yet, so the bar starts indeterminate. Nothing is known
      // until the server has registered the request — see ToastProgress.
    });

    // The id is generated here rather than returned by the server because the
    // POST does not resolve until the entire download is finished; by the time
    // it could hand back an id, there would be nothing left to report on.
    const requestId =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `dl-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    // Polls alongside the download. `stopped` guards the tail: the interval is
    // cleared in `finally`, but a poll already awaiting a response would
    // otherwise resolve afterwards and overwrite the finished toast's title
    // with a stage that is no longer true.
    let stopped = false;
    const poll = window.setInterval(async () => {
      const state = await fetchDownloadProgress(requestId);
      if (stopped || !state.tracked || state.failed) return;

      const stageLabel = state.stage ? STAGE_LABELS[state.stage] : null;
      const sourceCount =
        state.stage === 'fetching' && state.providersTotal
          ? ` · ${state.providersDone ?? 0} of ${state.providersTotal} sources`
          : '';

      patchToast(toastId, {
        title: stageLabel ? `${stageLabel}…` : 'Preparing your download…',
        detail: `${summary}${sourceCount}`,
        progress: state.fraction,
      });
    }, PROGRESS_POLL_MS);

    try {
      const { blob, filename } = await downloadOceanData({
        area,
        start_date: startDate,
        end_date: endDate,
        resolution,
        variables: Array.from(selectedVariables),
        format,
        depth_m: needsDepth ? (parsedDepth ?? 0) : 0,
        request_id: requestId,
      });
      saveBlob(blob, filename);
      setSubmitStatus('idle');
      updateToast(toastId, { tone: 'success', title: 'Download ready', detail: filename });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Download failed.';
      setSubmitStatus('error');
      // Kept inline as well as in the toast: the inline copy sits with the
      // form the user is about to correct, and does not time out.
      setSubmitError(message);
      updateToast(toastId, { tone: 'error', title: 'Download failed', detail: message });
    } finally {
      stopped = true;
      window.clearInterval(poll);
    }
  }

  return (
    <div className={`download-page ${isDark ? '' : 'download-page--light'}`}>
      <header className="download-header">
        <Link to="/map" className="download-back-link">
          <ArrowLeft size={14} /> Back to map
        </Link>
        <h1>Download Ocean Data</h1>
        <p className="download-subtitle">
          Pick an area, a date range, and the variables you need — MarisAI handles the rest.
        </p>
      </header>

      <form className="download-form" onSubmit={handleSubmit}>
        <section className="download-section">
          <h2>Area</h2>
          <div className="download-tabs" role="tablist">
            <button
              type="button"
              className={areaMode === 'point' ? 'active' : ''}
              onClick={() => setAreaMode('point')}
            >
              Point
            </button>
            <button
              type="button"
              className={areaMode === 'draw' ? 'active' : ''}
              onClick={() => setAreaMode('draw')}
            >
              Bounding Box
            </button>
            <button type="button" disabled title="Coming soon — not yet available">
              Upload GeoJSON
            </button>
          </div>

          {areaMode === 'point' ? (
            <div className="download-field-row">
              <label>
                Latitude
                <input
                  type="number"
                  step="any"
                  min={-90}
                  max={90}
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                />
              </label>
              <label>
                Longitude
                <input
                  type="number"
                  step="any"
                  min={-180}
                  max={180}
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                />
              </label>
            </div>
          ) : (
            <>
              {areaMode === 'draw' && (
                <DrawableAreaMap bbox={drawnBbox} onDraw={handleDraw} />
              )}
              <div className="download-field-row">
                <label>
                  North
                  <input
                    type="number"
                    step="any"
                    value={bbox.north}
                    onChange={(e) => setBbox((b) => ({ ...b, north: e.target.value }))}
                  />
                </label>
                <label>
                  South
                  <input
                    type="number"
                    step="any"
                    value={bbox.south}
                    onChange={(e) => setBbox((b) => ({ ...b, south: e.target.value }))}
                  />
                </label>
                <label>
                  East
                  <input
                    type="number"
                    step="any"
                    value={bbox.east}
                    onChange={(e) => setBbox((b) => ({ ...b, east: e.target.value }))}
                  />
                </label>
                <label>
                  West
                  <input
                    type="number"
                    step="any"
                    value={bbox.west}
                    onChange={(e) => setBbox((b) => ({ ...b, west: e.target.value }))}
                  />
                </label>
              </div>
            </>
          )}
        </section>

        <section className="download-section">
          <h2>Date Range</h2>
          <div className="download-field-row">
            <label>
              Start Date
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label>
              End Date
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
          </div>
        </section>

        <section className="download-section">
          <h2 id="download-resolution-heading">Temporal Resolution</h2>
          {/* Every other control on this form nests its own <label>; this one
              is labelled by the section heading instead, since the heading is
              already the field's name and a second visible label would only
              repeat it. It was the form's one unlabelled control. */}
          <select
            aria-labelledby="download-resolution-heading"
            value={resolution}
            onChange={(e) => setResolution(e.target.value as Resolution)}
          >
            <option value="hourly">Hourly</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </section>

        <section className="download-section">
          <h2>Variables</h2>
          {categoriesError && <p className="download-error">{categoriesError}</p>}
          {/* The variable catalogue is fetched, so this section was an empty
              box until it arrived — indistinguishable from "the catalogue came
              back empty". The placeholder mirrors the real grid's shape so the
              layout does not jump when it resolves. */}
          {categories.length === 0 && !categoriesError && (
            <div className="download-variable-groups" aria-busy="true">
              {[0, 1, 2, 3].map((group) => (
                <fieldset key={group} className="download-variable-group">
                  <legend>
                    <span className="ma-skeleton ma-skeleton--sub" style={{ width: '5.5rem' }} />
                  </legend>
                  {[0, 1, 2, 3].map((row) => (
                    <label key={row}>
                      <span
                        className="ma-skeleton ma-skeleton--sub"
                        style={{ width: `${6 + ((row * 3) % 5)}rem` }}
                      />
                    </label>
                  ))}
                </fieldset>
              ))}
            </div>
          )}
          <div className="download-variable-groups">
            {categories.map((cat) => (
              <fieldset key={cat.category} className="download-variable-group">
                <legend>{cat.category}</legend>
                {cat.variables.map((variable) => (
                  <label
                    key={variable.code}
                    className={variable.available ? '' : 'disabled'}
                    title={variable.available ? variable.unit : 'Coming soon — not yet available'}
                  >
                    <input
                      type="checkbox"
                      disabled={!variable.available}
                      checked={selectedVariables.has(variable.code)}
                      onChange={() => toggleVariable(variable.code)}
                    />
                    {variable.label}
                    {!variable.available && <span className="badge">coming soon</span>}
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
        </section>

        <section className="download-section">
          <button
            type="button"
            className="download-advanced-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            Advanced Options {advancedOpen ? '▲' : '▼'}
          </button>
          {advancedOpen && (
            <div className="download-advanced">
              <label className={needsDepth ? '' : 'disabled'}>
                Depth (m)
                <input
                  type="number"
                  step="any"
                  min={0}
                  max={6000}
                  value={needsDepth ? depth : '0'}
                  disabled={!needsDepth}
                  onChange={(e) => setDepth(e.target.value)}
                  title={
                    needsDepth
                      ? 'Snapped to the nearest of the model’s 50 levels'
                      : 'Only used by Water Temperature and Water Salinity'
                  }
                />
              </label>
              <label>
                Interpolation
                <select disabled defaultValue="nearest">
                  <option value="nearest">Nearest</option>
                </select>
              </label>
              <label>
                Coordinate System
                <select disabled defaultValue="wgs84">
                  <option value="wgs84">WGS84</option>
                </select>
              </label>
              <label>
                Units
                <select disabled defaultValue="default">
                  <option value="default">Default</option>
                </select>
              </label>
              <label>
                Missing Data Strategy
                <select disabled defaultValue="nan">
                  <option value="nan">Keep as NaN</option>
                </select>
              </label>
              <p className="download-advanced__note">
                {needsDepth
                  ? `Depth applies to ${depthVariables
                      .map((v) => v.label)
                      .join(' and ')}; it is snapped to the nearest of the model’s 50 levels, and
                      the level actually used is recorded in the export’s metadata. The remaining
                      settings support one option each — more unlock as new providers land.`
                  : 'These settings support one option each — more unlock as new providers land.'}
              </p>
            </div>
          )}
        </section>

        <section className="download-section">
          <h2>Output Format</h2>
          <div className="download-format-options">
            <label>
              <input
                type="radio"
                name="format"
                value="csv"
                checked={format === 'csv'}
                onChange={() => setFormat('csv')}
              />
              CSV
            </label>
            <label>
              <input
                type="radio"
                name="format"
                value="json"
                checked={format === 'json'}
                onChange={() => setFormat('json')}
              />
              JSON
            </label>
            <label>
              <input
                type="radio"
                name="format"
                value="pdf"
                checked={format === 'pdf'}
                onChange={() => setFormat('pdf')}
              />
              PDF Report
            </label>
          </div>
        </section>

        {submitError && <p className="download-error">{submitError}</p>}

        {/* Downloads are open to everyone since authentication was removed
            (docs/AUTH_REMOVAL.md); the backend rate-limits them per address
            instead, and returns a 429 with an explanation this form surfaces
            through `submitError`. */}
        <button type="submit" className="download-submit" disabled={submitStatus === 'loading'}>
          {submitStatus === 'loading' ? 'Preparing download…' : 'Download Dataset'}
        </button>
      </form>
    </div>
  );
}
