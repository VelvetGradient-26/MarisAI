import { useEffect, useMemo, useState } from 'react';
import {
  fetchPredictionManifest,
  type HabHorizon,
  type PredictionManifest,
} from '../features/map/api/predictions';
import { Link } from '../app/router';
import { useThemeStore } from '../store/themeStore';
import './predictions.css';

type Status = 'loading' | 'ready' | 'error';
type ProductId = 'habitat' | 'hab';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Model Insights — what the ML models predict, how well they actually do, and
 * where they should not be trusted.
 *
 * The organising principle is that **a skill number without its baseline is
 * not a result**. The HAB section therefore leads with the model-vs-persistence
 * comparison rather than a bare PR-AUC, because "it is blooming now so it will
 * be blooming in three days" is a genuinely strong forecast and a model that
 * cannot beat it has demonstrated nothing. The limitations panel is given the
 * same visual weight as the metrics for the same reason.
 */
export function PredictionsPage() {
  const isDark = useThemeStore((s) => s.dark);
  const [manifest, setManifest] = useState<PredictionManifest | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const [product, setProduct] = useState<ProductId>('habitat');

  useEffect(() => {
    document.title = 'Maris AI | Model Insights';
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchPredictionManifest(controller.signal)
      .then((data) => {
        setManifest(data);
        setStatus('ready');
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load model metadata.');
        setStatus('error');
      });
    return () => controller.abort();
  }, []);

  return (
    <div className={`predictions-page ${isDark ? '' : 'predictions-page--light'}`}>
      <div className="predictions-shell">
        <header className="predictions-header">
          <p className="predictions-eyebrow">Machine learning</p>
          <h1>Model Insights</h1>
          <p className="predictions-lede">
            Two models run offline over Copernicus Marine, GEBCO and OBIS data, and their
            predictions are served as map layers. This page is the honest accounting: measured
            skill, what drives each model, and where each one breaks down.
          </p>
        </header>

        {status === 'loading' && (
          <div className="predictions-state">Loading model metadata…</div>
        )}

        {status === 'error' && (
          <div className="predictions-state predictions-state--error">
            <p>{error}</p>
            <p className="predictions-state__hint">
              Predictions are precomputed offline. Run{' '}
              <code>PYTHONPATH=. python scripts/export_predictions.py</code> in{' '}
              <code>machine_learning/</code>, then reload.
            </p>
          </div>
        )}

        {status === 'ready' && manifest && (
          <>
            <nav className="product-tabs" aria-label="Model">
              {(['habitat', 'hab'] as ProductId[]).map((id) => (
                <button
                  key={id}
                  type="button"
                  className={`product-tab ${product === id ? 'product-tab--active' : ''}`}
                  onClick={() => setProduct(id)}
                  aria-pressed={product === id}
                >
                  {manifest.products[id].title}
                </button>
              ))}
            </nav>

            {product === 'habitat' ? (
              <HabitatPanel manifest={manifest} />
            ) : (
              <HabPanel manifest={manifest} />
            )}

            <footer className="predictions-footer">
              Predictions generated {manifest.generated}. These are batch outputs, not live
              inference — the map serves exactly the artifact that was cross-validated.
            </footer>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Habitat                                                             */
/* ------------------------------------------------------------------ */

function HabitatPanel({ manifest }: { manifest: PredictionManifest }) {
  const habitat = manifest.products.habitat;
  const [month, setMonth] = useState(() => new Date().getUTCMonth() + 1);

  // Best tier by cross-validated TSS. TSS is the SDM literature's standard and,
  // unlike accuracy, is not fooled by the presence/background class ratio.
  const best = useMemo(() => {
    const entries = Object.entries(habitat.metrics);
    return entries.reduce((a, b) => ((b[1].tss ?? 0) > (a[1].tss ?? 0) ? b : a));
  }, [habitat.metrics]);

  return (
    <>
      <p className="product-subtitle">{habitat.subtitle}</p>

      <section className="stat-row">
        <StatTile
          label="Best cross-validated TSS"
          value={best[1].tss.toFixed(2)}
          detail={`${best[0].replace(/_/g, ' ')} · 0 = chance, 1 = perfect`}
        />
        <StatTile
          label="ROC-AUC"
          value={best[1].roc_auc.toFixed(2)}
          detail="spatial block cross-validation"
        />
        <StatTile
          label="Boyce index"
          value={best[1].boyce.toFixed(2)}
          detail="needs no true absences — the right metric for presence-only data"
        />
        <StatTile
          label="Species modelled"
          value={String(habitat.species.length)}
          detail={`${habitat.training_window[0].slice(0, 4)}–${habitat.training_window[1].slice(0, 4)} occurrence records`}
        />
      </section>

      <div className="panel-grid">
        <Card
          title="Skill by model tier"
          note="Cross-validated over 3° spatial blocks. Whole blocks are held out, so held-out points are far from anything the model trained on — the only way to measure generalisation rather than memorisation."
        >
          <table className="metric-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>ROC-AUC</th>
                <th>PR-AUC</th>
                <th>TSS</th>
                <th>Boyce</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(habitat.metrics).map(([name, row]) => (
                <tr key={name} className={name === best[0] ? 'metric-table__best' : ''}>
                  <td>{name.replace(/_/g, ' ')}</td>
                  <td>{row.roc_auc.toFixed(3)}</td>
                  <td>{row.pr_auc.toFixed(3)}</td>
                  <td>{row.tss.toFixed(3)}</td>
                  <td>{row.boyce.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="card-footnote">
            No tier dominates — which is exactly the case an ensemble exists for. The map layers
            serve the skill-weighted blend of all three.
          </p>
        </Card>

        <Card
          title="What drives the predictions"
          note="Mean absolute SHAP value — how much each input moves a prediction, on average."
        >
          <DriverBars drivers={habitat.drivers} />
          <p className="card-footnote card-footnote--warn">
            Depth and distance-to-coast dominate. Some of that is real ecology (pelagic tunas and
            coastal sardines occupy different habitats) — but some is residual sampling geometry:
            the background pool skews shallower than the pelagic species. Read the ranking with
            that in mind.
          </p>
        </Card>
      </div>

      <Card
        title="View on the map"
        note="Layers appear under “AI (Experimental)” in the map's layer panel."
      >
        <div className="species-picker">
          <label className="field">
            <span>Season</span>
            <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {habitat.months.map((m) => (
                <option key={m} value={m}>
                  {MONTH_NAMES[m - 1]}
                </option>
              ))}
            </select>
          </label>
          <p className="field-note">
            The map shows the current calendar month by default. This is a {habitat.year}{' '}
            climatology, not a forecast for a specific year.
          </p>
        </div>
        <ul className="species-list">
          {habitat.species.map((species) => (
            <li key={species.key}>
              <span className="species-label">{species.label}</span>
              <span className="species-latin">{species.scientific_name}</span>
            </li>
          ))}
        </ul>
        <Link className="map-link" to="/map">
          Open the map →
        </Link>
      </Card>

      <Limitations items={habitat.caveats} />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* HAB                                                                 */
/* ------------------------------------------------------------------ */

function HabPanel({ manifest }: { manifest: PredictionManifest }) {
  const hab = manifest.products.hab;
  const [horizonDays, setHorizonDays] = useState(hab.horizons[0]?.horizon_days ?? 3);
  const horizon = hab.horizons.find((h) => h.horizon_days === horizonDays) ?? hab.horizons[0];

  return (
    <>
      <p className="product-subtitle">{hab.subtitle}</p>

      <section className="stat-row">
        {hab.horizons.map((h) => (
          <StatTile
            key={h.horizon_days}
            label={`+${h.horizon_days} day lead`}
            value={h.pr_auc?.toFixed(2) ?? '—'}
            detail={`PR-AUC vs ${h.persistence_pr_auc?.toFixed(2) ?? '—'} baseline`}
            tone={h.beats_baseline ? 'good' : 'bad'}
          />
        ))}
      </section>

      <div className="panel-grid">
        <Card
          title="Does it beat doing nothing?"
          note="“It is blooming now, so it will be blooming then” is a strong forecast for a field this autocorrelated. A model that cannot beat it has demonstrated nothing, so the baseline is scored on every fold."
        >
          <BaselineComparison horizons={hab.horizons} />
          <p className="card-footnote">
            An earlier two-year version of this model <em>lost</em> to persistence at +5 and +7
            days. Extending the training window to six years — five monsoon seasons instead of one
            — is what fixed it.
          </p>
        </Card>

        <Card
          title="Are the probabilities trustworthy?"
          note="A model can rank perfectly and still be badly calibrated. If the map says 70%, that has to mean something."
        >
          <div className="horizon-tabs">
            {hab.horizons.map((h) => (
              <button
                key={h.horizon_days}
                type="button"
                className={`horizon-tab ${h.horizon_days === horizonDays ? 'horizon-tab--active' : ''}`}
                onClick={() => setHorizonDays(h.horizon_days)}
              >
                +{h.horizon_days}d
              </button>
            ))}
          </div>
          <ReliabilityPlot horizon={horizon} />
          <p className="card-footnote">
            Brier score improves from {horizon.brier_uncalibrated?.toFixed(3) ?? '—'} to{' '}
            {horizon.brier?.toFixed(3) ?? '—'} after isotonic calibration, with ranking metrics
            unchanged — exactly how a monotonic transform should behave.
          </p>
        </Card>
      </div>

      <Card title={`What drives the +${horizon.horizon_days}-day forecast`}>
        <DriverBars drivers={horizon.drivers} />
        <p className="card-footnote">
          Chlorophyll and its anomalies lead, which is expected. Wind-driven upwelling contributes
          through <em>30-day rolling</em> statistics rather than instantaneous values — sustained
          upwelling drives nutrient supply, not any single windy day.
        </p>
      </Card>

      <Limitations items={hab.caveats} />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Pieces                                                              */
/* ------------------------------------------------------------------ */

function StatTile({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: 'good' | 'bad';
}) {
  return (
    <div className={`stat-tile ${tone ? `stat-tile--${tone}` : ''}`}>
      <p className="stat-tile__label">{label}</p>
      <p className="stat-tile__value">{value}</p>
      {detail && <p className="stat-tile__detail">{detail}</p>}
    </div>
  );
}

function Card({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {note && <p className="card-note">{note}</p>}
      {children}
    </section>
  );
}

/**
 * Horizontal bars for SHAP importance. One series, one colour — bar length
 * already encodes magnitude, so colouring each bar by its own value would
 * double-encode and burn the only free channel.
 */
function DriverBars({ drivers }: { drivers: Array<{ feature: string; importance: number }> }) {
  if (!drivers.length) return <p className="empty-note">No driver data exported.</p>;
  const max = Math.max(...drivers.map((d) => d.importance));

  return (
    <ul className="driver-bars">
      {drivers.map((driver) => (
        <li key={driver.feature}>
          <span className="driver-name">{driver.feature}</span>
          <span className="driver-track">
            <span
              className="driver-fill"
              style={{ width: `${Math.max(2, (driver.importance / max) * 100)}%` }}
            />
          </span>
          <span className="driver-value">{driver.importance.toFixed(3)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Model vs baseline per horizon — a paired bar per lead time, on one axis. */
function BaselineComparison({ horizons }: { horizons: HabHorizon[] }) {
  const max = Math.max(
    ...horizons.flatMap((h) => [h.pr_auc ?? 0, h.persistence_pr_auc ?? 0])
  );

  return (
    <>
      <ul className="baseline-rows">
        {horizons.map((h) => (
          <li key={h.horizon_days}>
            <span className="baseline-label">+{h.horizon_days}d</span>
            <span className="baseline-track">
              <span
                className="baseline-fill baseline-fill--model"
                style={{ width: `${((h.pr_auc ?? 0) / max) * 100}%` }}
              />
              <span
                className="baseline-fill baseline-fill--persistence"
                style={{ width: `${((h.persistence_pr_auc ?? 0) / max) * 100}%` }}
              />
            </span>
            <span className={`baseline-verdict ${h.beats_baseline ? 'is-good' : 'is-bad'}`}>
              {h.beats_baseline ? 'beats' : 'loses'}
            </span>
          </li>
        ))}
      </ul>
      <div className="baseline-legend">
        <span>
          <i className="swatch swatch--model" /> model
        </span>
        <span>
          <i className="swatch swatch--persistence" /> persistence baseline
        </span>
        <span className="baseline-legend__unit">PR-AUC</span>
      </div>
    </>
  );
}

/**
 * Reliability diagram: predicted probability against observed frequency. A
 * perfectly calibrated model sits on the diagonal. Drawn as inline SVG rather
 * than pulling in a charting dependency — the repo's convention is to
 * hand-roll rather than add a library for one component.
 */
function ReliabilityPlot({ horizon }: { horizon: HabHorizon }) {
  const points = horizon.reliability;
  if (!points.length) return <p className="empty-note">No calibration data exported.</p>;

  const size = 220;
  const pad = 28;
  const scale = (v: number) => pad + v * (size - pad * 2);

  return (
    <svg
      className="reliability-plot"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Calibration for the ${horizon.horizon_days}-day forecast`}
    >
      {/* Perfect-calibration reference. */}
      <line
        x1={scale(0)}
        y1={size - scale(0)}
        x2={scale(1)}
        y2={size - scale(1)}
        className="reliability-diagonal"
      />
      <polyline
        className="reliability-line"
        points={points.map((p) => `${scale(p.predicted)},${size - scale(p.observed)}`).join(' ')}
      />
      {points.map((p) => (
        <circle
          key={p.predicted}
          cx={scale(p.predicted)}
          cy={size - scale(p.observed)}
          r={3.5}
          className="reliability-dot"
        />
      ))}
      <text x={size / 2} y={size - 4} className="reliability-axis">
        predicted probability
      </text>
      <text
        x={10}
        y={size / 2}
        className="reliability-axis"
        transform={`rotate(-90 10 ${size / 2})`}
      >
        observed frequency
      </text>
    </svg>
  );
}

function Limitations({ items }: { items: string[] }) {
  return (
    <section className="card card--limits">
      <h2>Limitations</h2>
      <p className="card-note">
        Read before using any of this operationally. These are the things the metrics above do
        not capture.
      </p>
      <ul className="limits-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
