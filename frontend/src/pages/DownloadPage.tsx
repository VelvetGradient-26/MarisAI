import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from '../app/router';
import { DrawableAreaMap } from '../features/map/DrawableAreaMap';
import type { DrawnBbox } from '../features/map/DrawableAreaMap';
import { useThemeStore } from '../store/themeStore';
import {
  downloadOceanData,
  fetchVariableCategories,
  type Area,
  type OutputFormat,
  type Resolution,
  type VariableCategory,
} from '../features/map/api/download';
import './download.css';

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

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [submitError, setSubmitError] = useState<string | null>(null);

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

  async function handleSubmit(e: FormEvent) {
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

    setSubmitStatus('loading');
    try {
      const { blob, filename } = await downloadOceanData({
        area,
        start_date: startDate,
        end_date: endDate,
        resolution,
        variables: Array.from(selectedVariables),
        format,
      });
      saveBlob(blob, filename);
      setSubmitStatus('idle');
    } catch (err) {
      setSubmitStatus('error');
      setSubmitError(err instanceof Error ? err.message : 'Download failed.');
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
          <h2>Temporal Resolution</h2>
          <select value={resolution} onChange={(e) => setResolution(e.target.value as Resolution)}>
            <option value="hourly">Hourly</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </section>

        <section className="download-section">
          <h2>Variables</h2>
          {categoriesError && <p className="download-error">{categoriesError}</p>}
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
              <label>
                Depth
                <select disabled defaultValue="surface">
                  <option value="surface">Surface</option>
                </select>
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
                Phase 1 supports one option per setting — more unlock as new providers and features
                land.
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

        <button type="submit" className="download-submit" disabled={submitStatus === 'loading'}>
          {submitStatus === 'loading' ? 'Preparing download…' : 'Download Dataset'}
        </button>
      </form>
    </div>
  );
}
