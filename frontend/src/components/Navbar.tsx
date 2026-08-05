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
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Assistant', to: '/assistant' },
  { label: 'Analytics', to: '/analytics' },
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
