/** Alerts panel.
 *
 * Every alert shows its `basis` — the threshold and value that produced it.
 * These are rules applied to model and satellite fields, not issued marine
 * warnings, and the panel says so; presenting them as authoritative warnings
 * would be the single most dangerous thing this dashboard could do.
 *
 * Dismissals are local and keyed by the backend's content-derived id, so a
 * dismissed alert stays dismissed across polls but returns if the underlying
 * condition moves or recurs.
 */

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { BellRing, ShieldAlert, X } from 'lucide-react';
import type { OceanAlert } from '../api/types';
import { useAlerts } from '../hooks/useDashboardData';
import { formatAge, SEVERITY_STYLES } from '../lib/format';
import { cn } from '../lib/cn';
import { LiveDot, Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

function ageSeconds(iso: string | null): number | null {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : Math.max(0, (Date.now() - parsed) / 1000);
}

function AlertRow({
  alert,
  onDismiss,
  onLocate,
}: {
  alert: OceanAlert;
  onDismiss: (id: string) => void;
  onLocate?: (latitude: number, longitude: number) => void;
}) {
  const style = SEVERITY_STYLES[alert.severity];
  const locatable = alert.latitude != null && alert.longitude != null && onLocate;

  return (
    <motion.li
      layout
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 8, transition: { duration: 0.18 } }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className={cn('rounded-xl border p-3', style.border, style.bg)}
    >
      <div className="flex items-start gap-2.5">
        <span className={cn('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', style.dot)} />

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-[12.5px] font-semibold text-[color:var(--oid-text-strong)]">{alert.title}</h4>
            <button
              type="button"
              onClick={() => onDismiss(alert.id)}
              aria-label={`Dismiss ${alert.title} at ${alert.region}`}
              className="shrink-0 text-[color:var(--oid-text-ghost)] transition-colors hover:text-[color:var(--oid-text)]"
            >
              <X size={13} />
            </button>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px]">
            <span className={cn('font-semibold tracking-wide uppercase', style.text)}>
              {style.label}
            </span>
            <span className="text-[color:var(--oid-text-faint)]">·</span>
            {locatable ? (
              <button
                type="button"
                onClick={() => onLocate(alert.latitude as number, alert.longitude as number)}
                className="text-[color:var(--oid-text)] underline decoration-dotted underline-offset-2 transition-colors hover:text-[color:var(--oid-accent)]"
              >
                {alert.region}
              </button>
            ) : (
              <span className="text-[color:var(--oid-text-muted)]">{alert.region}</span>
            )}
            <span className="text-[color:var(--oid-text-faint)]">·</span>
            <span className="text-[color:var(--oid-text-faint)]">{formatAge(ageSeconds(alert.observed_at))}</span>
          </div>

          <p className="mt-1.5 text-[11px] leading-relaxed text-[color:var(--oid-text-muted)]">{alert.basis}</p>
        </div>
      </div>
    </motion.li>
  );
}

export function AlertsPanel({
  onLocate,
}: {
  onLocate?: (latitude: number, longitude: number) => void;
}) {
  const { data, isPending, isError, error, isFetching, refetch } = useAlerts();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const visible = (data?.alerts ?? []).filter((alert) => !dismissed.has(alert.id));
  const dismissedCount = (data?.alerts.length ?? 0) - visible.length;

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<BellRing size={15} />}
        title="Alerts"
        subtitle={
          data
            ? `${data.counts.critical} critical · ${data.counts.warning} warning · ${data.counts.advisory} advisory`
            : 'Threshold-derived'
        }
        actions={
          <div className="flex items-center gap-2">
            {dismissedCount > 0 && (
              <button
                type="button"
                onClick={() => setDismissed(new Set())}
                className="text-[10px] text-[color:var(--oid-text-faint)] transition-colors hover:text-[color:var(--oid-text)]"
              >
                Restore {dismissedCount}
              </button>
            )}
            <LiveDot active={isFetching} />
          </div>
        }
      />

      {isPending && <PanelSkeleton rows={3} />}

      {isError && (
        <PanelEmpty
          title="Alerts unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && visible.length === 0 && (
        <PanelEmpty
          title={
            data.alerts.length === 0 ? 'No active alerts' : 'All alerts dismissed'
          }
          reason={
            data.alerts.length === 0
              ? 'No monitored threshold is currently exceeded.'
              : undefined
          }
          icon={<ShieldAlert size={20} />}
        />
      )}

      {data && visible.length > 0 && (
        <ul className="oid-scroll flex-1 space-y-2 overflow-y-auto p-3">
          <AnimatePresence initial={false}>
            {visible.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                onDismiss={(id) => setDismissed((prev) => new Set(prev).add(id))}
                onLocate={onLocate}
              />
            ))}
          </AnimatePresence>
        </ul>
      )}

      {data && (
        <footer className="space-y-1 border-t border-[color:var(--oid-border)] px-3 py-2">
          {data.sources_unavailable.length > 0 && (
            <p className="text-[10px] text-[color:var(--color-alert-warning)]">
              Not evaluated: {data.sources_unavailable.join('; ')}
            </p>
          )}
          <p className="text-[9.5px] leading-relaxed text-[color:var(--oid-text-ghost)]">{data.disclaimer}</p>
        </footer>
      )}
    </Panel>
  );
}
