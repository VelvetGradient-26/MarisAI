import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Menu, Moon, Sun, X } from 'lucide-react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { rafThrottle } from '../utils/rafThrottle';
import { useTimezoneStore } from '../store/timezoneStore';
import { useThemeStore } from '../store/themeStore';
import './navbar.css';

const NAV_LINKS = [
  { label: 'Home', to: '/' },
  { label: 'Map', to: '/map' },
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Assistant', to: '/assistant' },
  { label: 'Analytics', to: '/analytics' },
  { label: 'Compare', to: '/compare' },
  { label: 'Download', to: '/download' },
  { label: 'Docs', to: '/docs' },
];

export interface NavbarProps {
  /** Map page only: floats over the fullscreen map instead of pushing
   * content down. Visually identical bar either way — see navbar.css. */
  overlay?: boolean;
}

/**
 * The one shared top nav for every page. Replaces the previously
 * independent (and inconsistent) headers each page used to hand-roll —
 * see the plan file for the specific inconsistencies this reconciles
 * (fixed vs. sticky positioning, hamburger vs. flex-wrap mobile handling,
 * active-link logic that didn't actually check the route, etc.).
 *
 * Deliberately does not carry per-page widgets (a live clock, say) — those are
 * page-local concerns rendered by the pages themselves. What does live here is
 * anything that is a single shared, app-wide concern: the dark/light theme
 * toggle (store/themeStore.ts) and the timezone picker (store/timezoneStore.ts).
 *
 * The account control and the "view source" link were both removed — see
 * docs/AUTH_REMOVAL.md for the former.
 */
export function Navbar({ overlay = false }: NavbarProps) {
  const { pathname } = useAppRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const dark = useThemeStore((s) => s.dark);
  const scrolled = useScrolledPastTop();

  return (
    <header
      className={`navbar ${overlay ? 'navbar--overlay' : ''} ${dark ? '' : 'navbar--light'} ${
        scrolled ? 'is-scrolled' : ''
      }`}
    >
      <div className="navbar__inner">
        <Link className="navbar__logo" to="/" aria-label="Maris AI home">
          <WaveMark />
          <span className="navbar__logo-text">Maris AI</span>
        </Link>

        <nav className="navbar__links navbar__links--desktop" aria-label="Primary navigation">
          {NAV_LINKS.map((link) => {
            const active = pathname === link.to;
            return (
              <span key={link.to} className="navbar__link-slot">
                {/* The label is rendered twice and the pair slides on hover
                    (see navbar.css). The duplicate is `aria-hidden`, so the
                    accessible name is still the single label. */}
                <Link className={active ? 'is-active' : ''} to={link.to}>
                  <span className="navbar__label">
                    <span className="navbar__label-face">{link.label}</span>
                    <span className="navbar__label-face" aria-hidden="true">
                      {link.label}
                    </span>
                  </span>
                </Link>
                {/* One indicator for the whole bar, not one per link: a shared
                    `layoutId` makes framer-motion animate the *same* element
                    between slots, so it slides from the old link to the new
                    one instead of blinking off and on. The underline is no
                    longer drawn by `border-color` for the same reason — a
                    border cannot travel between elements. */}
                {active ? (
                  <motion.span
                    className="navbar__indicator"
                    layoutId="navbar-indicator"
                    transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                  />
                ) : null}
              </span>
            );
          })}
        </nav>

        <div className="navbar__actions">
          <TimezonePicker />
          <ThemeButton />
          <button
            className="navbar__menu-button"
            type="button"
            onClick={() => setMenuOpen((value) => !value)}
            aria-label="Toggle navigation"
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
      </div>

      {menuOpen && (
        <nav className="navbar__links navbar__links--mobile" aria-label="Mobile navigation">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.to}
              className={pathname === link.to ? 'is-active' : ''}
              to={link.to}
              onClick={() => setMenuOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          <div className="navbar__timezone-mobile">
            <TimezonePicker />
          </div>
        </nav>
      )}
    </header>
  );
}

/**
 * True once the document has scrolled off the very top.
 *
 * Drives the bar's condensed state: a translucent navbar over a page's own
 * hero has nothing behind it to separate from, and the border and heavier
 * background it needs *once content is passing under it* are exactly what make
 * it look heavy sitting over a hero. So the bar starts nearly weightless and
 * gains its edge on the first scroll.
 *
 * The threshold is 8px rather than 0 so a trackpad's rubber-band overscroll
 * does not flicker the state at rest, and the setter is guarded on the value
 * so the throttled listener re-renders the navbar exactly twice per page
 * rather than on every frame of a scroll.
 *
 * Always false on `/map`, without a special case: that route has no document
 * scroll, so `scrollY` never leaves 0.
 */
function useScrolledPastTop() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const check = rafThrottle(() => {
      setScrolled((was) => {
        const now = window.scrollY > 8;
        return now === was ? was : now;
      });
    });
    window.addEventListener('scroll', check, { passive: true });
    // Measure once on mount: a route change can land on a page already
    // scrolled, and a browser restoring a scroll position fires no event.
    check();
    return () => window.removeEventListener('scroll', check);
  }, []);

  return scrolled;
}

/**
 * The brand mark: three stacked contour lines, which is what a bathymetric
 * chart and a wave trace have in common and is the one glyph that reads as
 * *this* product rather than as a generic globe or droplet.
 *
 * Drawn as strokes with `pathLength` normalised to 1, so the draw-on animation
 * in navbar.css is a `stroke-dashoffset` from 1 to 0 regardless of each path's
 * real length — otherwise the three lines, which are different lengths, would
 * draw at three different speeds.
 */
function WaveMark() {
  return (
    <svg
      className="navbar__mark"
      width="26"
      height="26"
      viewBox="0 0 26 26"
      fill="none"
      aria-hidden="true"
    >
      {[7, 13, 19].map((y, index) => (
        <path
          key={y}
          className="navbar__mark-line"
          style={{ animationDelay: `${index * 0.09}s` }}
          d={`M2 ${y}c3.2 0 3.2-3.4 6.4-3.4S11.6 ${y} 14.8 ${y}s3.2-3.4 6.4-3.4`}
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          pathLength={1}
        />
      ))}
    </svg>
  );
}

function ThemeButton() {
  const dark = useThemeStore((s) => s.dark);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);

  return (
    <button
      className="navbar__icon-button"
      type="button"
      onClick={toggleTheme}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function TimezonePicker() {
  const timezone = useTimezoneStore((s) => s.timezone);
  const setTimezone = useTimezoneStore((s) => s.setTimezone);

  const zones = useMemo(() => {
    const all =
      typeof Intl.supportedValuesOf === 'function'
        ? Intl.supportedValuesOf('timeZone')
        : [timezone];
    return [...all].sort((a, b) => a.localeCompare(b));
  }, [timezone]);

  return (
    <select
      className="navbar__timezone"
      value={timezone}
      onChange={(e) => setTimezone(e.target.value)}
      aria-label="Display timezone"
      title="Display timezone"
    >
      {zones.map((zone) => (
        <option key={zone} value={zone}>
          {zone.replace(/_/g, ' ')}
        </option>
      ))}
    </select>
  );
}
