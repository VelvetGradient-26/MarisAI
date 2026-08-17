import { useEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import { Link } from '../app/router';
import { KineticText, Marquee } from '../components/craft';
import { useMagnetic } from '../hooks/useMagnetic';
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
import {
  supportsViewTimeline,
  useCountUp,
  useReveal,
  useScrollProgress,
} from './landing/useScrollReveal';
import SplitText from '../components/reactbits/SplitText/SplitText';
import SpotlightCard from '../components/reactbits/SpotlightCard/SpotlightCard';
import { ClosingBackdrop } from './landing/ClosingBackdrop';
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
// Verified figures (2026-08-06)
// --------------------------------------------------------------------------

/**
 * `backend/models/forecasting/` — 31 of 32 configured variables, up to 4
 * horizons each. It is not 31 x 4: a horizon that failed to beat persistence
 * on its folds was deleted rather than shipped, so the model count is the
 * count of horizons that actually passed.
 */
const TRAINED_MODELS = 115;
const TRAINED_VARIABLES = 31;
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
      <Ticker />
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
// Shared page furniture
// --------------------------------------------------------------------------

/**
 * A numbered eyebrow.
 *
 * The ordinal is passed rather than derived, because the sections are separate
 * components rendered in a fixed order and an auto-incrementing counter would
 * mean either a context or an index prop threaded through every one of them —
 * more machinery than the six literals it would replace. If a section is
 * reordered, renumber it here; the numbers are part of the copy.
 */
function Eyebrow({ index, children }: { index: string; children: ReactNode }) {
  return (
    <p className="lp-eyebrow">
      <span className="lp-eyebrow__index" aria-hidden="true">
        {index}
      </span>
      {children}
    </p>
  );
}

/**
 * A `Link` that leans toward the pointer.
 *
 * Separated from the buttons themselves so the pull is opt-in per call site.
 * It is applied to the two primary calls to action and nowhere else: a page on
 * which every control is magnetic is a page where none of them is, and the
 * effect stops meaning "this is the thing to press".
 */
function MagneticLink({
  to,
  className,
  children,
}: {
  to: string;
  className: string;
  children: ReactNode;
}) {
  const ref = useMagnetic<HTMLAnchorElement>();
  return (
    <Link ref={ref} to={to} className={className}>
      {children}
    </Link>
  );
}

// --------------------------------------------------------------------------
// Hero
// --------------------------------------------------------------------------

function Hero({ dark }: { dark: boolean }) {
  const contentRef = useRef<HTMLDivElement>(null);

  // Parallax: the headline drifts up and dissolves slightly slower than the
  // page scrolls past it.
  //
  // **Where a browser can drive this from scroll itself, CSS does it** — see
  // `lp-hero-parallax` in landing.css, which runs on the compositor with no
  // listener, no measurement and no React involvement at all. This hook is the
  // fallback for browsers without `animation-timeline`, and it is disabled
  // rather than merely ignored when the CSS is in charge: the animation would
  // win the cascade regardless (animations outrank inline styles), so leaving
  // it on would measure every frame to write a value nothing paints.
  //
  // In the fallback the value is written straight to the node instead of held
  // in React state. Same formula, same rAF — but this subtree contains
  // `HeroField`'s WebGL canvas, and routing a per-frame number through state
  // reconciled all of it once per scroll frame to move one headline. The inline
  // style below is the value at rest, so first paint, reduced motion and the
  // CSS path all start from the neutral transform.
  const cssDriven = supportsViewTimeline();
  const { ref } = useScrollProgress<HTMLDivElement>((progress) => {
    const node = contentRef.current;
    if (!node) return;
    node.style.transform = `translate3d(0, ${progress * -60}px, 0)`;
    node.style.opacity = String(Math.max(0, 1 - Math.max(0, progress) * 1.6));
  }, !cssDriven);

  return (
    <section className="lp-hero" ref={ref}>
      <HeroField dark={dark} />
      <div className="lp-hero__veil" />
      <div
        className="lp-hero__content"
        ref={contentRef}
        style={{ transform: 'translate3d(0, 0, 0)', opacity: 1 }}
      >
        {/* A status pill rather than a plain eyebrow. Both figures in it are
            the same constants the metrics row counts up to, so the sentence
            cannot drift from the numbers a screen below it. */}
        <p className="lp-live">
          <span className="lp-live__dot" aria-hidden="true" />
          Live
          <span className="lp-live__sep" aria-hidden="true">
            /
          </span>
          <strong>{PROVIDERS}</strong> providers
          <span className="lp-live__sep" aria-hidden="true">
            /
          </span>
          <strong>{TRAINED_MODELS}</strong> models
        </p>
        {/* Two lines, two SplitText instances, because the component takes a
            flat string — a `<br />` inside it would be split into characters
            along with everything else.

            Each is wrapped in a block span rather than being made block
            itself: SplitText writes `display: inline-block` to the element's
            *inline style*, which no class rule can outrank, so styling its own
            node put both lines on one baseline side by side. The wrapper owns
            the layout, the component owns its node.

            Under reduced motion SplitText renders the text untouched and never
            splits it, so this stays a plain two-line heading in that mode. */}
        <h1 className="lp-hero__title">
          <span className="lp-hero__title-line">
            <SplitText text="The ocean," tag="span" textAlign="left" delay={28} duration={0.9} />
          </span>
          <span className="lp-hero__title-line">
            <SplitText text="quantified." tag="span" textAlign="left" delay={28} duration={0.9} />
          </span>
        </h1>
        <p className="lp-hero__lede">
          Live ocean and atmospheric data from {PROVIDERS} upstream providers, a global
          forecasting engine trained on real skill against persistence, and research
          pipelines for harmful algal blooms and fish habitat — in one platform.
        </p>
        <div className="lp-hero__actions">
          <MagneticLink className="lp-button lp-button--primary" to="/map">
            Open the map
            <ArrowRight size={16} />
          </MagneticLink>
          <MagneticLink className="lp-button lp-button--ghost" to="/dashboard">
            View the dashboard
          </MagneticLink>
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
// Variable ticker
// --------------------------------------------------------------------------

/**
 * Every entry is a real key from `services/download/registry.py`, with its
 * real unit. The row exists to answer the question the metrics row leaves
 * open — "{SERVED_VARIABLES} variables *of what*" — so a placeholder or a
 * padded-out list would defeat its only purpose. If a variable leaves the
 * registry it should leave this array, exactly like every other figure on this
 * page.
 *
 * This is a subset, not the full 34: the ticker is a sample that reads at a
 * glance, and a complete enumeration is what `/download` is for.
 */
const TICKER_VARIABLES: [string, string][] = [
  ['sea_surface_temperature', '°C'],
  ['chlorophyll', 'mg/m³'],
  ['current_speed', 'm/s'],
  ['wave_height', 'm'],
  ['wind_speed', 'm/s'],
  ['salinity', 'PSU'],
  ['ocean_depth', 'm'],
  ['dissolved_oxygen', 'mmol/m³'],
  ['nitrate', 'mmol/m³'],
  ['sea_level_anomaly', 'm'],
  ['mixed_layer_depth', 'm'],
  ['air_temperature', '°C'],
  ['rainfall', 'mm'],
  ['mean_wave_period', 's'],
  ['phytoplankton', 'mmol/m³'],
  ['ph', 'pH'],
];

function Ticker() {
  return (
    <Marquee
      className="lp-ticker"
      // Scaled to the item count so the row moves at a readable ~55 px/s
      // regardless of how long this list grows.
      durationSeconds={TICKER_VARIABLES.length * 3.5}
    >
      {TICKER_VARIABLES.map(([name, unit]) => (
        <span key={name} className="lp-ticker__item">
          {name}
          <span className="lp-ticker__unit">{unit}</span>
        </span>
      ))}
    </Marquee>
  );
}

// --------------------------------------------------------------------------
// Forecasting engine — the flagship
// --------------------------------------------------------------------------

/** Real validated skill scores, from each model's `metrics.json`. */
const SKILL_ROWS = [
  { variable: 'Chlorophyll-a', horizon: '+1 day', skill: 0.529 },
  { variable: 'Air temperature', horizon: '+30 days', skill: 0.494 },
  { variable: 'Rainfall', horizon: '+30 days', skill: 0.475 },
  { variable: 'Water temperature', horizon: '+30 days', skill: 0.439 },
  { variable: 'Sea surface temp.', horizon: '+30 days', skill: 0.434 },
  { variable: 'Mean wave period', horizon: '+30 days', skill: 0.428 },
];

function Forecasting() {
  const { ref, revealed } = useReveal<HTMLDivElement>();

  return (
    <section className="lp-section">
      <div ref={ref} className={`lp-feature ${revealed ? 'is-in' : ''}`}>
        <div className="lp-feature__copy">
          <Eyebrow index="01">Forecasting engine</Eyebrow>
          {/* The one heading that keeps its hard line break, because the two
              halves are a parallel construction and letting them reflow turns
              a rhetorical pair into a run-on. KineticText takes a flat string,
              so this stays two instances — the same reason the hero does. */}
          <h2 className="lp-h2">
            <KineticText text="One framework." />
            <br />
            <KineticText text="Every variable." delay={0.08} />
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
          <Eyebrow index="02">Data layer</Eyebrow>
          <KineticText as="h2" className="lp-h2" text="Every variable traced to its source." />
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
          <Eyebrow index="03">Platform</Eyebrow>
          <KineticText as="h2" className="lp-h2" text="Four ways in." />
        </div>
        <div className="lp-surface-grid">
          {SURFACES.map((surface, index) => (
            <Link
              key={surface.title}
              to={surface.to}
              className="lp-surface"
              style={{ transitionDelay: `${index * 80}ms` }}
              // Feeds the card's wash and its top-edge highlight (see
              // landing.css). Written straight to the element rather than held
              // in state: this fires on every pointer move over a grid of four
              // cards, and a setState per move would re-render the section —
              // and the SVG glyph inside each card — dozens of times a second
              // for something no React code reads.
              onPointerMove={(event: ReactPointerEvent<HTMLAnchorElement>) => {
                const rect = event.currentTarget.getBoundingClientRect();
                const x = (event.clientX - rect.left) / rect.width;
                const y = (event.clientY - rect.top) / rect.height;
                const card = event.currentTarget;
                card.style.setProperty('--px', `${x * 100}%`);
                card.style.setProperty('--py', `${y * 100}%`);
                // Signed and unitless, because a percentage cannot be multiplied
                // into an angle. These drive the object's tilt toward the
                // cursor; the wash above still wants the percentages.
                card.style.setProperty('--pxn', `${(x - 0.5) * 2}`);
                card.style.setProperty('--pyn', `${(y - 0.5) * 2}`);
              }}
              onPointerLeave={(event: ReactPointerEvent<HTMLAnchorElement>) => {
                // Back to square-on rather than frozen at whatever angle the
                // pointer left at. The transition on `.lp-glyph__tilt` carries
                // it, so this is one property write and no animation frame.
                event.currentTarget.style.setProperty('--pxn', '0');
                event.currentTarget.style.setProperty('--pyn', '0');
              }}
            >
              {/* The artwork as a solid object rather than a flat icon.
                  
                  **The same glyph is drawn three times at three depths.** An
                  abstract plate behind an icon is just a shadow; repeating the
                  *content* into the distance makes the object legible as a
                  stack of layers, which is what all four of these surfaces
                  actually are. It has to be built from HTML boxes because
                  `transform-style: preserve-3d` is flattened inside an `<svg>`,
                  so the glyph's own paths cannot be separated in depth however
                  natural that looks.
                  
                  Three nested transforms, each owned by exactly one input:
                  `__stage` is the scroll timeline's, `__tilt` is the pointer's,
                  and the echoes' own translateZ is static. A running animation
                  beats a transition on the same property, so sharing an element
                  between two of them means one of them silently never shows. */}
              <span className="lp-glyph" aria-hidden="true">
                <span className="lp-glyph__stage">
                  <span className="lp-glyph__tilt">
                    <span className="lp-glyph__grid" />
                    <span className="lp-glyph__echo lp-glyph__echo--far">
                      {surface.glyph}
                    </span>
                    <span className="lp-glyph__echo lp-glyph__echo--mid">
                      {surface.glyph}
                    </span>
                    <span className="lp-glyph__face">{surface.glyph}</span>
                    <span className="lp-glyph__gloss" />
                  </span>
                </span>
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
          <Eyebrow index="04">Research pipelines</Eyebrow>
          <KineticText as="h2" className="lp-h2" text="Methodology that survives review." />
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
    // SpotlightCard renders a plain <div> with a pointer-tracked glow. The
    // card keeps its own `lp-research-card` styling — the vendored component
    // supplies only the spotlight, with its geometry handed back to this page
    // through the two custom properties so it does not impose its own padding
    // and radius (see the vendored CSS).
    <SpotlightCard className="lp-research-card">
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
    </SpotlightCard>
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
        One variable and nine further horizons were trained, measured, found no better
        than assuming no change, and deleted rather than shipped.
      </>
    ),
  },
  {
    title: 'Check the folds, not the headline',
    body: (
      <>
        Six horizons reported beating persistence on their aggregate while individual
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
          <Eyebrow index="05">How it is built</Eyebrow>
          <KineticText as="h2" className="lp-h2" text="Honesty is a feature." />
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
      <ClosingBackdrop />
      <div ref={ref} className={`lp-closing ${revealed ? 'is-in' : ''}`}>
        <KineticText as="h2" className="lp-closing__title" text="Start with the map." />
        <p className="lp-body lp-body--wide">
          Sea surface temperature, chlorophyll, wind and forecast fields over live bathymetry
          — then follow any variable into its own intelligence page.
        </p>
        <div className="lp-hero__actions">
          <MagneticLink className="lp-button lp-button--primary" to="/map">
            Open the map
            <ArrowRight size={16} />
          </MagneticLink>
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
