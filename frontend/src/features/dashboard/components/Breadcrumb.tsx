/** Shared breadcrumb for the dashboard's standalone detail pages
 * (`ModelDossierPage`, and the station/satellite/source detail pages) — one
 * implementation rather than four near-identical copies, since all of them
 * are "Home > Dashboard > <this item>" with nothing page-specific about the
 * first two crumbs. */

import { ChevronRight } from 'lucide-react';
import { Link } from '../../../app/router';

export function Breadcrumb({ current }: { current: string }) {
  const crumb = 'text-[color:var(--oid-text-faint)] no-underline hover:text-[color:var(--oid-accent)]';
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[length:var(--oid-text-sm)]">
      <Link to="/" className={crumb}>
        Home
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <Link to="/dashboard" className={crumb}>
        Dashboard
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <span className="text-[color:var(--oid-text)]">{current}</span>
    </nav>
  );
}
