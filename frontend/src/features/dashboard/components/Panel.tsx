/** Glass panel primitives shared by every dashboard section. */

import type { ReactNode } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { cn } from '../lib/cn';

export function Panel({
  className,
  children,
  as: Component = 'section',
  ...rest
}: {
  className?: string;
  children: ReactNode;
  as?: 'section' | 'div' | 'article';
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Component
      className={cn(
        'relative overflow-hidden rounded-[var(--radius-panel)]',
        'border border-[color:var(--oid-border)]',
        'bg-[color:var(--oid-panel)] backdrop-blur-xl',
        'shadow-[var(--oid-shadow)]',
        className
      )}
      {...rest}
    >
      {children}
    </Component>
  );
}

export function PanelHeader({
  icon,
  title,
  subtitle,
  actions,
  className,
}: {
  icon?: ReactNode;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        'flex items-start justify-between gap-3 border-b',
        'border-[color:var(--oid-border)] px-4 py-3',
        className
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && (
          <span className="mt-0.5 shrink-0 text-[color:var(--oid-accent)]">{icon}</span>
        )}
        <div className="min-w-0">
          <h2 className="truncate text-[13px] font-semibold tracking-wide text-[color:var(--oid-text-strong)] uppercase">
            {title}
          </h2>
          {subtitle && (
            <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--oid-text-muted)]">{subtitle}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </header>
  );
}

/** Skeleton shown while a section's first request is in flight. */
export function PanelSkeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-2.5 p-4', className)} aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="h-9 animate-[var(--animate-shimmer)] rounded-lg bg-[color:var(--oid-track)]"
          style={{ animationDelay: `${index * 120}ms` }}
        />
      ))}
    </div>
  );
}

/**
 * The empty state this dashboard leans on hardest.
 *
 * Every unavailable widget explains *why* and offers a retry rather than
 * showing a zero or a dash — the backend always sends a reason, and hiding it
 * would turn "this source has not loaded" into "the ocean has no chlorophyll".
 */
export function PanelEmpty({
  title,
  reason,
  onRetry,
  icon,
  className,
}: {
  title: string;
  reason?: string | null;
  onRetry?: () => void;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 px-5 py-8 text-center',
        className
      )}
      role="status"
    >
      <span className="text-[color:var(--oid-text-faint)]">{icon ?? <AlertCircle size={20} />}</span>
      <p className="text-[13px] font-medium text-[color:var(--oid-text)]">{title}</p>
      {reason && <p className="max-w-sm text-[11.5px] leading-relaxed text-[color:var(--oid-text-faint)]">{reason}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={cn(
            'mt-1 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5',
            'border border-[color:var(--oid-border)] text-[11.5px] text-[color:var(--oid-text)]',
            'transition-colors hover:bg-[color:var(--oid-track)]'
          )}
        >
          <RefreshCw size={12} />
          Retry
        </button>
      )}
    </div>
  );
}

export function PanelLoading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-5 py-8 text-[color:var(--oid-text-muted)]" role="status">
      <Loader2 size={15} className="animate-spin" />
      <span className="text-[12px]">{label}</span>
    </div>
  );
}

/** A small "live" indicator that pulses while a query is refetching. */
export function LiveDot({ active, className }: { active: boolean; className?: string }) {
  return (
    <span className={cn('relative inline-flex h-2 w-2', className)}>
      <span
        className={cn(
          'absolute inline-flex h-full w-full rounded-full',
          active
            ? 'animate-[var(--animate-pulse-ring)] bg-[color:var(--color-emerald-400)] text-[color:var(--color-emerald-400)]'
            : 'bg-[color:var(--oid-text-ghost)]'
        )}
      />
    </span>
  );
}

