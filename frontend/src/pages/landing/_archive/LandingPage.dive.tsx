import { useEffect, useRef, useState } from 'react';
import { Compass, ArrowRight } from 'lucide-react';
import { Link } from '../app/router';
import { useThemeStore } from '../store/themeStore';
import { OceanDiveScene } from './landing/OceanDiveScene';
import { rafThrottle } from '../utils/rafThrottle';
import './landing.css';

const API_DOCS_URL = 'http://127.0.0.1:8000/docs';

/** Zooms a section gently into focus as it crosses the viewport's vertical
 * center — ported from the prototype's `computeScale()`. */
function computeScale(ref: HTMLDivElement | null, falloff = 0.22): number {
  if (!ref) return 1;
  const rect = ref.getBoundingClientRect();
  const vh = window.innerHeight || 800;
  const center = rect.top + rect.height / 2;
  const dist = Math.min(Math.abs(center - vh / 2) / (vh / 2), 1);
  return 1 - dist * falloff;
}

export function LandingPage() {
  const isDark = useThemeStore((s) => s.dark);
  const [scales, setScales] = useState({ stats: 1, features: 1, platform: 1, cta: 1 });
  const statsRef = useRef<HTMLDivElement>(null);
  const featuresRef = useRef<HTMLDivElement>(null);
  const platformRef = useRef<HTMLDivElement>(null);
  const ctaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = 'Maris AI | Marine Intelligence';
  }, []);

  useEffect(() => {
    const onScroll = rafThrottle(() => {
      setScales({
        stats: computeScale(statsRef.current),
        features: computeScale(featuresRef.current),
        platform: computeScale(platformRef.current),
        cta: computeScale(ctaRef.current),
      });
    });
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className={`landing-page ${isDark ? 'landing-page--dark' : 'landing-page--light'}`}>
      <OceanDiveScene dark={isDark} />

      {/* ── HERO (surface) ── */}
      <section className="dive-hero">
        <div className="dive-buoy">
          <div className="dive-buoy__dot">
            <span className="dive-buoy__ring" />
            <span className="dive-buoy__core" />
          </div>
          <div className="dive-buoy__label">BUOY 214 · 18.2°C · 1.4m swell</div>
        </div>

        <div className="dive-pier">
          <PierSvg />
        </div>

        <div className="dive-waves">
          <svg viewBox="0 0 2880 260" preserveAspectRatio="none" className="dive-wave dive-wave--one">
            <path
              d="M0 140 C 240 90, 480 190, 720 140 S 1200 90, 1440 140 S 1920 190, 2160 140 S 2640 90, 2880 140 L2880 260 L0 260 Z"
              fill="oklch(0.62 0.08 220 / 0.5)"
            />
          </svg>
          <svg viewBox="0 0 2880 260" preserveAspectRatio="none" className="dive-wave dive-wave--two">
            <path
              d="M0 170 C 220 210, 460 130, 720 170 S 1180 210, 1440 170 S 1900 130, 2160 170 S 2620 210, 2880 170 L2880 260 L0 260 Z"
              fill="oklch(0.48 0.08 225 / 0.62)"
            />
          </svg>
          <svg viewBox="0 0 2880 260" preserveAspectRatio="none" className="dive-wave dive-wave--three">
            <path
              d="M0 200 C 260 170, 500 220, 760 195 S 1220 165, 1480 200 S 1940 225, 2200 195 S 2660 165, 2880 200 L2880 260 L0 260 Z"
              fill="oklch(0.34 0.06 230 / 0.88)"
            />
          </svg>
        </div>

        <div className="dive-hero__content">
          <div className="dive-badge">
            <span aria-hidden="true" />
            Deep-Sea Intelligence Engine
          </div>
          <h1>AI-powered marine intelligence for the world's oceans.</h1>
          <p>
            Maris AI combines live marine forecasts, atmospheric observations, satellite mapping,
            and geospatial context in one interactive platform.
          </p>
          <Link className="dive-cta-button" to="/map">
            Launch Project
            <Compass size={16} />
          </Link>
          <div className="dive-scroll-hint">Scroll to dive ↓</div>
        </div>
      </section>

      {/* ── STATS ── */}
      <section className="dive-section">
        <div ref={statsRef} className="dive-stats" style={{ transform: `scale(${scales.stats})` }}>
          <div className="dive-stat">
            <div className="dive-stat__value">40M+</div>
            <div className="dive-stat__label">ocean data points ingested daily</div>
          </div>
          <div className="dive-stat">
            <div className="dive-stat__value">12</div>
            <div className="dive-stat__label">satellite &amp; buoy feeds unified</div>
          </div>
          <div className="dive-stat">
            <div className="dive-stat__value">15 min</div>
            <div className="dive-stat__label">forecast refresh interval</div>
          </div>
        </div>
      </section>

      {/* ── FEATURES ── */}
      <section className="dive-section">
        <div ref={featuresRef} className="dive-features" style={{ transform: `scale(${scales.features})` }}>
          <div className="dive-features__head">
            <div className="dive-eyebrow">Capabilities</div>
            <h2>Everything you need to read the ocean, in one view.</h2>
          </div>
          <div className="dive-feature-grid">
            <div className="dive-feature-card">
              <div className="dive-feature-card__icon dive-feature-card__icon--cyan" />
              <h3>Live marine forecasts</h3>
              <p>Swell, current, and temperature forecasts updated continuously from a global sensor network.</p>
            </div>
            <div className="dive-feature-card">
              <div className="dive-feature-card__icon dive-feature-card__icon--teal" />
              <h3>Atmospheric observations</h3>
              <p>Wind, pressure, and storm-system data fused with ocean state for coupled analysis.</p>
            </div>
            <div className="dive-feature-card">
              <div className="dive-feature-card__icon dive-feature-card__icon--cyan" />
              <h3>Satellite &amp; geospatial mapping</h3>
              <p>Layer bathymetry, ice extent, and vessel tracks over a single interactive chart.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── PLATFORM PREVIEW ── */}
      <section className="dive-section">
        <div ref={platformRef} className="dive-platform" style={{ transform: `scale(${scales.platform})` }}>
          <div>
            <div className="dive-eyebrow">Platform</div>
            <h2>One interactive chart, every layer of context.</h2>
            <p>
              Query historical and live conditions side by side, export research-grade datasets, and share
              annotated views with collaborators.
            </p>
            <a className="dive-doc-link" href={API_DOCS_URL} target="_blank" rel="noreferrer">
              View documentation <ArrowRight size={15} />
            </a>
          </div>
          <div className="dive-platform__panel">
            <svg viewBox="0 0 600 375" preserveAspectRatio="none" className="dive-platform__chart">
              <polyline
                points="0,260 60,230 120,245 180,190 240,205 300,150 360,175 420,120 480,140 540,95 600,115"
                fill="none"
                stroke="oklch(0.78 0.14 195)"
                strokeWidth="2"
              />
              <polyline
                points="0,300 60,290 120,300 180,270 240,285 300,250 360,265 420,235 480,250 540,215 600,225"
                fill="none"
                stroke="oklch(0.78 0.14 165 / 0.7)"
                strokeWidth="2"
              />
            </svg>
            <div className="dive-platform__caption">[ platform preview — live chart module ]</div>
            <div className="dive-platform__tags">
              <span className="dive-tag dive-tag--cyan">sea surface temp</span>
              <span className="dive-tag dive-tag--teal">wave height</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA (abyss) ── */}
      <section className="dive-section">
        <div ref={ctaRef} className="dive-cta" style={{ transform: `scale(${scales.cta})` }}>
          <h2>See the ocean the way our researchers do.</h2>
          <Link className="dive-cta-button dive-cta-button--abyss" to="/map">
            Launch Project
            <Compass size={16} />
          </Link>
        </div>
      </section>

      <footer className="dive-footer">
        <div>
          <div className="dive-footer__brand">Maris AI</div>
          <div className="dive-footer__copy">© 2026 Maris AI. Subsurface precision analytics.</div>
        </div>
        <div className="dive-footer__links">
          <Link to="/contact">Contact</Link>
          <Link to="/feedback">Feedback</Link>
          <a href={API_DOCS_URL} target="_blank" rel="noreferrer">
            API Docs
          </a>
        </div>
      </footer>
    </div>
  );
}

function PierSvg() {
  return (
    <svg viewBox="0 0 780 320" preserveAspectRatio="xMinYMax meet" style={{ display: 'block', width: '100%', height: '100%', overflow: 'visible' }}>
      <g fill="rgba(13,38,52,0.9)">
        <rect x="26" y="100" width="11" height="72" />
        <rect x="146" y="100" width="11" height="72" />
        <rect x="266" y="100" width="11" height="72" />
        <rect x="386" y="100" width="11" height="72" />
        <rect x="506" y="100" width="11" height="72" />
        <rect x="620" y="52" width="13" height="120" />
        <rect x="0" y="112" width="640" height="7" />
        <rect x="0" y="141" width="640" height="6" />
        <rect x="654" y="146" width="15" height="28" rx="5" />
        <rect x="0" y="170" width="676" height="17" />
      </g>
      <g fill="rgba(8,26,38,0.92)">
        <rect x="0" y="187" width="676" height="6" />
        <rect x="30" y="193" width="20" height="110" />
        <rect x="176" y="193" width="20" height="118" />
        <rect x="322" y="193" width="20" height="112" />
        <rect x="468" y="193" width="20" height="120" />
        <rect x="600" y="193" width="20" height="114" />
      </g>
      <g stroke="rgba(8,26,38,0.85)" strokeWidth="7" fill="none">
        <path d="M40,206 L186,286" />
        <path d="M186,206 L40,286" />
        <path d="M332,206 L478,288" />
        <path d="M478,206 L332,288" />
        <path d="M478,210 L610,282" />
      </g>
      <g fill="rgba(255,255,255,0.07)">
        <rect x="0" y="170" width="676" height="4" />
      </g>
      <g>
        <rect x="612" y="46" width="30" height="10" rx="3" fill="rgba(13,38,52,0.9)" />
        <rect x="617" y="56" width="20" height="22" rx="4" fill="rgba(255,226,150,0.85)" className="dive-pier-light" />
        <circle cx="627" cy="67" r="26" fill="rgba(255,226,150,0.16)" className="dive-pier-light" />
      </g>
    </svg>
  );
}
