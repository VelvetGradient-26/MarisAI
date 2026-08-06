import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import { Link } from '../app/router';
import { useThemeStore } from '../store/themeStore';
import { HeroField } from './landing/HeroField';
import {
  AssistantGlyph,
  DashboardGlyph,
  DownloadGlyph,
  MapGlyph,
  RollingOriginDiagram,
  SpatialBlockDiagram,
} from './landing/Diagrams';
import { useCountUp, useReveal, useScrollProgress } from './landing/useScrollReveal';
import './landing.css';

const API_DOCS_URL = 'http://127.0.0.1:8000/docs';

/**
 * The landing page is a presentation of what has actually been built.
 *
 * **Every number on this page is read from the codebase or from a measured
 * run** — the model count from `backend/models/forecasting/`, the variable and
 * provider counts from the download registry, the skill scores from the
 * training reports. The page it replaced claimed "40M+ ocean data points
 * ingested daily" and a "15 min forecast refresh interval", neither of which
 * corresponded to anything. In a project whose dashboard rule is *never
 * substitute a number for missing data*, inventing them on the front door was
 * the worst place to do it.
 *
 * If a figure here goes stale, correct it against the source rather than
 * rounding it up.
 */

// --------------------------------------------------------------------------
// Verified figures (2026-08-05)
// --------------------------------------------------------------------------

/** `backend/models/forecasting/` — 29 of 32 configured variables x 4 horizons. */
const TRAINED_MODELS = 109;
const TRAINED_VARIABLES = 29;
const CONFIGURED_VARIABLES = 32;
/** `services/download/registry.py` — 34 of 36 spec variables have a real source. */
const SERVED_VARIABLES = 34;
/** `services/download/catalog.py` — one provider is one upstream dataset. */
const PROVIDERS = 14;
/** `routers/*.py` (39) + `forecasting/api.py` (6). */
const API_ENDPOINTS = 45;
/** `forecasting.yaml` — one global model per variable+horizon across these. */
const TRAINING_POINTS = 24;
/** `services/chat/tools.py::_SPECS` — the assistant's tool surface. */
const AGENT_TOOLS = 9;

export function LandingPage() {
  const isDark = useThemeStore((s) => s.dark);

  useEffect(() => {
    document.title = 'Maris AI | Marine Intelligence';
  }, []);

  return (
    <div className={`lp ${isDark ? 'lp--dark' : 'lp--light'}`}>
      <Hero dark={isDark} />
      <Metrics />
      <Forecasting />
      <Coverage />
      <Platform />
      <Research />
      <Rigour />
      <Closing />
      <Footer />
    </div>
  );
}

// --------------------------------------------------------------------------
// Hero
// --------------------------------------------------------------------------

function Hero({ dark }: { dark: boolean }) {
  const { ref, progress } = useScrollProgress<HTMLDivElement>();

  return (
    <section className="lp-hero" ref={ref}>
      <HeroField dark={dark} />
      <div className="lp-hero__veil" />
      <div
        className="lp-hero__content"
        style={{
          // Parallax: the headline drifts up and dissolves slightly slower
          // than the page scrolls past it.
          transform: `translate3d(0, ${progress * -60}px, 0)`,
          opacity: Math.max(0, 1 - Math.max(0, progress) * 1.6),
        }}
      >
        <p className="lp-eyebrow lp-eyebrow--hero">Marine intelligence platform</p>
        <h1 className="lp-hero__title">
          The ocean, <br />
          quantified.
        </h1>
        <p className="lp-hero__lede">
          Live ocean and atmospheric data from {PROVIDERS} upstream providers, a global
          forecasting engine trained on real skill against persistence, and research
          pipelines for harmful algal blooms and fish habitat — in one platform.
        </p>
        <div className="lp-hero__actions">
          <Link className="lp-button lp-button--primary" to="/map">
            Open the map
            <ArrowRight size={16} />
          </Link>
          <Link className="lp-button lp-button--ghost" to="/dashboard">
            View the dashboard
          </Link>
        </div>
      </div>
      <div className="lp-hero__scroll" aria-hidden="true">
        <span />
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------
// Headline metrics
// --------------------------------------------------------------------------

function Metrics() {
  const { ref, revealed } = useReveal<HTMLDivElement>(0.2);

  return (
    <section className="lp-section lp-section--tight">
      <div ref={ref} className={`lp-metrics ${revealed ? 'is-in' : ''}`}>
        <Metric value={TRAINED_MODELS} label="forecasting models shipped" active={revealed} />
        <Metric value={SERVED_VARIABLES} label="ocean variables served" active={revealed} />
        <Metric value={PROVIDERS} label="upstream data providers" active={revealed} />
        <Metric value={API_ENDPOINTS} label="REST endpoints" active={revealed} />
      </div>
    </section>
  );
}

function Metric({ value, label, active }: { value: number; label: string; active: boolean }) {
  const current = useCountUp(value, active);
  return (
    <div className="lp-metric">
      <div className="lp-metric__value">{Math.round(current)}</div>
      <div className="lp-metric__label">{label}</div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Forecasting engine — the flagship
// --------------------------------------------------------------------------

/** Real validated skill scores, from each model's `metrics.json`. */
const SKILL_ROWS = [
  { variable: 'Chlorophyll-a', horizon: '+1 day', skill: 0.529 },
  { variable: 'Air temperature', horizon: '+30 days', skill: 0.494 },
  { variable: 'Water temperature', horizon: '+30 days', skill: 0.439 },
  { variable: 'Sea surface temp.', horizon: '+30 days', skill: 0.434 },
  { variable: 'Mean wave period', horizon: '+30 days', skill: 0.428 },
  { variable: 'Wind speed', horizon: '+30 days', skill: 0.412 },
];

function Forecasting() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section">
      <div ref={ref} className={`lp-feature ${revealed ? 'is-in' : ''}`}>
        <div className="lp-feature__copy">
          <p className="lp-eyebrow">Forecasting engine</p>
          <h2 className="lp-h2">
            One framework.
            <br />
            Every variable.
          </h2>
          <p className="lp-body">
            Adding a forecastable variable is a single YAML block and a training run — no
            new code. {TRAINED_VARIABLES} of {CONFIGURED_VARIABLES} configured variables are
            trained today, each as a global model across {TRAINING_POINTS} ocean points, so
            it scores arbitrary coordinates rather than a fixed list.
          </p>
          <p className="lp-body">
            Models regress on the <em>change</em>, not the level. Fitting on levels scored
            worse than persistence at every horizon; the delta target moved 7-day skill from
            −0.12 to +0.20 on identical data and features.
          </p>
          <Link className="lp-link" to="/dashboard/sea_surface_temperature">
            Explore a variable
            <ArrowUpRight size={15} />
          </Link>
        </div>

        <div className="lp-skill">
          <div className="lp-skill__head">
            <span>Validated skill vs. persistence</span>
            <span className="lp-skill__unit">skill score</span>
          </div>
          <ul className="lp-skill__list">
            {SKILL_ROWS.map((row, index) => (
              <li key={row.variable} className="lp-skill__row">
                <span className="lp-skill__name">{row.variable}</span>
                <span className="lp-skill__horizon">{row.horizon}</span>
                <span className="lp-skill__bar" aria-hidden="true">
                  <span
                    className="lp-skill__fill"
                    style={{
                      width: revealed ? `${(row.skill / 0.6) * 100}%` : '0%',
                      transitionDelay: `${180 + index * 90}ms`,
                    }}
                  />
                </span>
                <span className="lp-skill__value">+{row.skill.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <p className="lp-skill__note">
            Positive means better than assuming tomorrow equals today — a genuinely hard
            baseline on autocorrelated ocean series. Every shipped horizon clears it.
          </p>
        </div>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------
// Data coverage
// --------------------------------------------------------------------------

const PROVIDER_GROUPS = [
  { name: 'Copernicus Marine', detail: 'physics, waves, biogeochemistry, optics, sea level' },
  { name: 'Open-Meteo', detail: 'atmospheric reanalysis and forecast' },
  { name: 'GEBCO via Ifremer', detail: '15 arc-second global bathymetry' },
  { name: 'NOAA Coral Reef Watch', detail: 'the only true climatology in the stack' },
  { name: 'Global Fishing Watch', detail: 'live vessel activity' },
];

function Coverage() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section lp-section--panel">
      <div ref={ref} className={`lp-coverage ${revealed ? 'is-in' : ''}`}>
        <div className="lp-coverage__head">
          <p className="lp-eyebrow">Data layer</p>
          <h2 className="lp-h2">Every variable traced to its source.</h2>
          <p className="lp-body lp-body--wide">
            {SERVED_VARIABLES} of 36 specified variables resolve to real data across{' '}
            {PROVIDERS} providers. Each carries its dataset, grid spacing, native cadence,
            coverage start, citation and licence. The remaining two have no global source,
            and say so rather than returning a plausible number.
          </p>
        </div>
        <ul className="lp-provider-list">
          {PROVIDER_GROUPS.map((provider, index) => (
            <li
              key={provider.name}
              className="lp-provider"
              style={{ transitionDelay: `${index * 70}ms` }}
            >
              <span className="lp-provider__name">{provider.name}</span>
              <span className="lp-provider__detail">{provider.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------
// Platform surfaces
// --------------------------------------------------------------------------

const SURFACES = [
  {
    title: 'Interactive map',
    body: 'Overlay fields on a GPU-rendered vector basemap, including a live particle layer for wind and forecast rasters drawn from the same models.',
    stats: ['8 overlay layers', '5 basemaps'],
    glyph: <MapGlyph />,
    to: '/map',
    cta: 'Open map',
  },
  {
    title: 'Ocean intelligence dashboard',
    body: 'Global KPIs, threshold alerts over real fields, and a per-variable intelligence page that renders from a capability registry — no variable-specific code.',
    stats: [`${CONFIGURED_VARIABLES} variable pages`, 'cold-start aware'],
    glyph: <DashboardGlyph />,
    to: '/dashboard',
    cta: 'Open dashboard',
  },
  {
    title: 'Universal data downloader',
    body: 'Compose any variables over any box and window. Mixed cadences inner-join to the coarsest, grids reindex to the finest, and provenance travels with the file.',
    stats: [`${SERVED_VARIABLES} variables`, 'CSV · JSON · PDF'],
    glyph: <DownloadGlyph />,
    to: '/download',
    cta: 'Open downloader',
  },
  {
    title: 'Conversational assistant',
    body: 'Tool-calling over the platform’s own endpoints — forecasts, conditions, alerts, bloom risk. A grounding check rejects any number in the answer that no tool returned.',
    stats: [`${AGENT_TOOLS} tools`, 'answers ledgered'],
    glyph: <AssistantGlyph />,
    to: '/assistant',
    cta: 'Open assistant',
  },
];

function Platform() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section">
      <div ref={ref} className={`lp-surfaces ${revealed ? 'is-in' : ''}`}>
        <div className="lp-surfaces__head">
          <p className="lp-eyebrow">Platform</p>
          <h2 className="lp-h2">Four ways in.</h2>
        </div>
        <div className="lp-surface-grid">
          {SURFACES.map((surface, index) => (
            <Link
              key={surface.title}
              to={surface.to}
              className="lp-surface"
              style={{ transitionDelay: `${index * 80}ms` }}
            >
              <span className="lp-glyph" aria-hidden="true">
                {surface.glyph}
              </span>
              <h3 className="lp-surface__title">{surface.title}</h3>
              <p className="lp-surface__body">{surface.body}</p>
              <span className="lp-surface__stats">
                {surface.stats.map((stat) => (
                  <span key={stat} className="lp-chip">
                    {stat}
                  </span>
                ))}
              </span>
              <span className="lp-surface__cta">
                {surface.cta}
                <ArrowRight size={15} />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------
// Research
// --------------------------------------------------------------------------

function Research() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section lp-section--panel">
      <div ref={ref} className={`lp-research ${revealed ? 'is-in' : ''}`}>
        <div className="lp-research__head">
          <p className="lp-eyebrow">Research pipelines</p>
          <h2 className="lp-h2">Methodology that survives review.</h2>
          <p className="lp-body lp-body--wide">
            Two offline pipelines share one Marine Data Fusion Layer: ingestion, regridding,
            a feature store, and a validation harness that refuses the shortcuts these
            problems invite.
          </p>
        </div>

        <div className="lp-research-grid">
          <ResearchCard
            eyebrow="Rolling-origin validation"
            title="Harmful algal bloom early warning"
            body="Bloom probability three to seven days out, over a daily feature table spanning six years of the Arabian Sea."
            diagram={<RollingOriginDiagram />}
            specs={[
              ['Horizons', 't+3 · t+5 · t+7'],
              ['Feature table', '3.9M rows'],
              ['Baseline', 'persistence, not zero'],
            ]}
          />
          <ResearchCard
            eyebrow="Spatial block validation"
            title="Fish habitat / PFZ suitability"
            body="Whole 3° blocks are held out, so the reported score means water the model has never seen — not a neighbouring point from the same transect."
            diagram={<SpatialBlockDiagram />}
            specs={[
              ['Holdout TSS', '0.788'],
              ['Metrics', 'AUC · TSS · Boyce'],
              ['Extrapolation', 'MESS reported'],
            ]}
          />
        </div>

        <p className="lp-research__note">
          Every fit-then-apply pair is two functions, so fitting a climatology or threshold
          on test rows takes deliberate effort. A test suite enforces that exactly one
          forward shift exists in the codebase — the target construction itself.
        </p>
      </div>
    </section>
  );
}

function ResearchCard({
  eyebrow,
  title,
  body,
  diagram,
  specs,
}: {
  eyebrow: string;
  title: string;
  body: string;
  diagram: ReactNode;
  specs: [string, string][];
}) {
  return (
    <article className="lp-research-card">
      <p className="lp-research-card__eyebrow">{eyebrow}</p>
      <h3 className="lp-research-card__title">{title}</h3>
      {diagram}
      <p className="lp-research-card__body">{body}</p>
      <dl className="lp-spec">
        {specs.map(([term, value]) => (
          <div key={term} className="lp-spec__row">
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

// --------------------------------------------------------------------------
// Engineering rigour
// --------------------------------------------------------------------------

const PRINCIPLES: { title: string; body: ReactNode }[] = [
  {
    title: 'Never substitute a number for missing data',
    body: (
      <>
        Every metric carries an availability flag and a reason. A fabricated “0.00 mg/m³” is
        a false ocean reading, not a neutral placeholder — so the interface renders the
        reason instead.
      </>
    ),
  },
  {
    title: 'Beat the trivial baseline, or do not ship',
    body: (
      <>
        A model shows a skill score against persistence before it reaches the platform.
        Three variables were trained, measured, found no better than assuming no change,
        and deliberately left unshipped.
      </>
    ),
  },
  {
    title: 'Check the folds, not the headline',
    body: (
      <>
        Four horizons reported beating persistence on their aggregate while individual
        validation folds were negative. The bar is overall skill above zero{' '}
        <em>and</em> at most one fold in five below it.
      </>
    ),
  },
  {
    title: 'Measure, then decide',
    body: (
      <>
        Outlier filtering is off because it flagged 5–12% of a clean satellite series.
        Chunking strategy, retry policy and cache windows were each chosen from a timed run,
        and the reasoning is recorded next to the code.
      </>
    ),
  },
];

function Rigour() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section">
      <div ref={ref} className={`lp-principles ${revealed ? 'is-in' : ''}`}>
        <div className="lp-principles__head">
          <p className="lp-eyebrow">How it is built</p>
          <h2 className="lp-h2">Honesty is a feature.</h2>
        </div>
        <div className="lp-principle-grid">
          {PRINCIPLES.map((principle, index) => (
            <div
              key={principle.title}
              className="lp-principle"
              style={{ transitionDelay: `${index * 70}ms` }}
            >
              <div className="lp-principle__rule" aria-hidden="true" />
              <h3>{principle.title}</h3>
              <p>{principle.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------
// Closing
// --------------------------------------------------------------------------

function Closing() {
  const { ref, revealed } = useReveal<HTMLDivElement>(0.25);

  return (
    <section className="lp-section lp-section--closing">
      <div ref={ref} className={`lp-closing ${revealed ? 'is-in' : ''}`}>
        <h2 className="lp-closing__title">Start with the map.</h2>
        <p className="lp-body lp-body--wide">
          Sea surface temperature, chlorophyll, wind and forecast fields over live bathymetry
          — then follow any variable into its own intelligence page.
        </p>
        <div className="lp-hero__actions">
          <Link className="lp-button lp-button--primary" to="/map">
            Open the map
            <ArrowRight size={16} />
          </Link>
          <a
            className="lp-button lp-button--ghost"
            href={API_DOCS_URL}
            target="_blank"
            rel="noreferrer"
          >
            API documentation
          </a>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer__inner">
        <div>
          <div className="lp-footer__brand">Maris AI</div>
          <p className="lp-footer__copy">
            Marine intelligence over live ocean, atmospheric and geospatial data.
          </p>
        </div>
        <nav className="lp-footer__links" aria-label="Footer">
          <Link to="/map">Map</Link>
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/download">Download</Link>
          <Link to="/assistant">Assistant</Link>
          <Link to="/contact">Contact</Link>
          <Link to="/feedback">Feedback</Link>
          <a href={API_DOCS_URL} target="_blank" rel="noreferrer">
            API
          </a>
        </nav>
      </div>
      <div className="lp-footer__base">
        © 2026 Maris AI · Data from Copernicus Marine Service, Open-Meteo, GEBCO, NOAA and
        Global Fishing Watch
      </div>
    </footer>
  );
}
