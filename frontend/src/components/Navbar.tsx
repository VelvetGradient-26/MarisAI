import { useEffect, useMemo, useRef, useState } from 'react';
import { Menu, Moon, Sun, X } from 'lucide-react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { useTimezoneStore } from '../store/timezoneStore';
import { useThemeStore } from '../store/themeStore';
import { useAuthStore } from '../store/authStore';
import { loginUrl } from '../features/map/api/auth';
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
 * Deliberately does not carry per-page widgets (a live clock, say) — those are
 * page-local concerns rendered by the pages themselves. What does live here is
 * anything that is a single shared, app-wide concern: the dark/light theme
 * toggle (store/themeStore.ts), the timezone picker (store/timezoneStore.ts),
 * and the account control (store/authStore.ts). Sign-in state qualifies on the
 * same grounds as the theme — it's one piece of state every page reads, so one
 * control in the shared nav is correct, and it replaces the fake hardcoded
 * avatar the dashboard used to render on its own.
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
          <AccountControl />
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
          <div className="navbar__account-mobile">
            <AccountControl onNavigate={() => setMenuOpen(false)} />
          </div>
        </nav>
      )}
    </header>
  );
}

const ACCOUNT_LINKS = [
  { label: 'Saved locations', to: '/account' },
  { label: 'Download history', to: '/account?tab=history' },
];

/**
 * Sign-in entry point and account menu. Renders nothing while the boot-time
 * /auth/me call is still in flight, so the bar doesn't flash "Sign in" at
 * someone who is in fact already signed in.
 */
function AccountControl({ onNavigate }: { onNavigate?: () => void }) {
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (status === 'loading') return null;

  if (status === 'anonymous' || !user) {
    // A real navigation, not a Link: the OAuth flow is a redirect chain
    // through Google that the hand-rolled router can't take part in.
    return (
      <a className="navbar__signin" href={loginUrl()}>
        Sign in
      </a>
    );
  }

  return (
    <div className="navbar__account" ref={containerRef}>
      <button
        className="navbar__avatar"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label={`Account menu for ${user.name}`}
        aria-expanded={open}
        aria-haspopup="menu"
        title={user.email}
      >
        {user.picture ? (
          <img src={user.picture} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span>{initialsOf(user.name || user.email)}</span>
        )}
      </button>

      {open && (
        <div className="navbar__account-menu" role="menu">
          <div className="navbar__account-identity">
            <strong>{user.name}</strong>
            <span>{user.email}</span>
          </div>
          {ACCOUNT_LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
            >
              {link.label}
            </Link>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
              void logout();
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/** "Deepak Krishna" -> "DK"; falls back to the first character for one-word
 * names and email addresses. */
function initialsOf(value: string): string {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
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
