import { useMemo, useState } from 'react';
import { Menu, Moon, Sun, X } from 'lucide-react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { useTimezoneStore } from '../store/timezoneStore';
import { useThemeStore } from '../store/themeStore';
import './navbar.css';

const NAV_LINKS = [
  { label: 'Home', to: '/' },
  { label: 'Map', to: '/map' },
  { label: 'Analytics', to: '/dashboard' },
  { label: 'Model Insights', to: '/predictions' },
  { label: 'Download', to: '/download' },
];

const GITHUB_URL = 'https://github.com/VelvetGradient-26/MarisAI';

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
 * Deliberately does not carry per-page widgets (live clock, account avatar)
 * — those are page-local concerns rendered by the pages themselves. The
 * dark/light theme toggle DOES live here, though: it's a single shared
 * preference (store/themeStore.ts), not a page-local one, so one control in
 * the shared nav is correct even though only Landing/Dashboard currently
 * render differently per theme.
 */
export function Navbar({ overlay = false }: NavbarProps) {
  const { pathname } = useAppRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const dark = useThemeStore((s) => s.dark);

  return (
    <header
      className={`navbar ${overlay ? 'navbar--overlay' : ''} ${dark ? '' : 'navbar--light'}`}
    >
      <div className="navbar__inner">
        <Link className="navbar__logo" to="/" aria-label="Maris AI home">
          Maris AI
        </Link>

        <nav className="navbar__links navbar__links--desktop" aria-label="Primary navigation">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.to}
              className={pathname === link.to ? 'is-active' : ''}
              to={link.to}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="navbar__actions">
          <TimezonePicker />
          <ThemeButton />
          <a
            className="navbar__icon-button"
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="View source on GitHub"
            title="View source on GitHub"
          >
            <GithubIcon size={18} />
          </a>
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

function GithubIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 0C5.37 0 0 5.5 0 12.3c0 5.44 3.44 10.05 8.21 11.68.6.11.82-.27.82-.6 0-.29-.01-1.06-.02-2.08-3.34.75-4.04-1.66-4.04-1.66-.55-1.44-1.34-1.82-1.34-1.82-1.09-.77.08-.75.08-.75 1.21.09 1.84 1.28 1.84 1.28 1.07 1.87 2.8 1.33 3.49 1.02.11-.79.42-1.33.76-1.64-2.67-.31-5.47-1.38-5.47-6.15 0-1.36.47-2.47 1.24-3.34-.12-.31-.54-1.57.12-3.28 0 0 1.01-.33 3.3 1.28a11.2 11.2 0 0 1 6 0c2.29-1.61 3.3-1.28 3.3-1.28.66 1.71.24 2.97.12 3.28.77.87 1.24 1.98 1.24 3.34 0 4.79-2.81 5.83-5.49 6.14.43.38.81 1.13.81 2.28 0 1.65-.01 2.98-.01 3.38 0 .33.21.72.83.6C20.57 22.34 24 17.74 24 12.3 24 5.5 18.63 0 12 0Z" />
    </svg>
  );
}

export { GithubIcon };
