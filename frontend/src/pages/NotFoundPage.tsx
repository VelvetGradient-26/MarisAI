import { useEffect } from 'react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { useThemeStore } from '../store/themeStore';
import './notfound.css';

/** Where an unknown URL is most likely trying to go. Kept short deliberately —
 *  a full sitemap here just reproduces the navbar directly above it. */
const DESTINATIONS = [
  { to: '/map', label: 'Ocean map', hint: 'Live SST, wind, vessels and forecast layers' },
  { to: '/dashboard', label: 'Ocean intelligence', hint: 'Global KPIs, alerts and per-metric pages' },
  { to: '/download', label: 'Data downloader', hint: '34 variables, CSV / JSON / PDF' },
  { to: '/docs', label: 'Documentation', hint: 'How the data and models work' },
];

/**
 * Shown for any path the router does not recognise.
 *
 * It exists because the fallthrough used to be the landing page: a mistyped or
 * stale URL silently rendered the home page with a 200-looking address bar, so
 * a broken link was indistinguishable from a working one. Saying "this path
 * does not exist" is the whole point — the suggestions below are a courtesy.
 */
export function NotFoundPage() {
  const isDark = useThemeStore((s) => s.dark);
  const { pathname } = useAppRouter();

  useEffect(() => {
    document.title = 'Maris AI | Page not found';
  }, []);

  return (
    <div className={`nf-page ${isDark ? '' : 'nf-page--light'}`}>
      <main className="nf-card">
        <p className="nf-eyebrow">404 — not found</p>
        <h1 className="nf-title">No such page</h1>
        <p className="nf-body">
          Nothing is served at <code className="nf-path">{pathname}</code>. The link may be out of
          date, or the path may have a typo.
        </p>

        <nav className="nf-links" aria-label="Suggested destinations">
          {DESTINATIONS.map((destination) => (
            <Link key={destination.to} to={destination.to} className="nf-link">
              <span className="nf-link__label">{destination.label}</span>
              <span className="nf-link__hint">{destination.hint}</span>
            </Link>
          ))}
        </nav>

        <Link to="/" className="nf-home">
          Back to the home page
        </Link>
      </main>
    </div>
  );
}
