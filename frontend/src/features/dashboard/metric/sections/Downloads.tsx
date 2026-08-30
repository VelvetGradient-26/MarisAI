/** Downloads.
 *
 * CSV and JSON are built from the series already in the React Query cache, so
 * they cost nothing and cannot disagree with what is on screen. Every export
 * carries a provenance header — source, window, coordinates, and the
 * observation-versus-plotted counts — because a bare column of numbers with no
 * attribution is how a model output ends up cited as a measurement.
 *
 * For anything richer (PDF, multi-variable, a bounding box) this links to the
 * existing Universal Ocean Data Downloader rather than reimplementing it.
 */

import { Download, FileJson, FileSpreadsheet, PackageOpen } from 'lucide-react';
import { Link } from '../../../../app/router';
import type { SectionProps } from '../sections';
import { useMetricSeries, useMetricStatistics } from '../hooks/useMetricData';
import { Panel, PanelHeader } from '../../components/Panel';
import { cn } from '../../lib/cn';

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export function Downloads({ variable, latitude, longitude }: SectionProps) {
  const { data: series } = useMetricSeries({
    variable: variable.key,
    latitude,
    longitude,
    range: '1y',
    maxPoints: 6000,
  });
  const { data: stats } = useMetricStatistics({
    variable: variable.key,
    latitude,
    longitude,
    range: '1y',
  });

  const ready = Boolean(series);

  const exportCsv = () => {
    if (!series) return;
    const rows = [
      `# MarisAI — ${series.label} (${series.unit})`,
      `# Point: ${series.latitude}, ${series.longitude}`,
      `# Window: ${series.start} to ${series.end} (${series.resolution})`,
      `# ${series.observation_count} observations; ${series.rendered_count} plotted`,
      `# Source: ${series.sources.join('; ')}`,
      `# Exported: ${new Date().toISOString()}`,
      'time,value',
      ...series.points.map((p) => `${new Date(p.t * 1000).toISOString()},${p.v}`),
    ];
    downloadBlob(
      new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' }),
      `marisai_${variable.key}.csv`
    );
  };

  const exportJson = () => {
    if (!series) return;
    downloadBlob(
      new Blob(
        [
          JSON.stringify(
            {
              variable: series.variable,
              label: series.label,
              unit: series.unit,
              point: { latitude: series.latitude, longitude: series.longitude },
              window: { start: series.start, end: series.end, resolution: series.resolution },
              observation_count: series.observation_count,
              sources: series.sources,
              statistics: stats?.statistics ?? null,
              points: series.points,
              exported_at: new Date().toISOString(),
              disclaimer:
                'Model and satellite-derived values. Not an official marine warning and not suitable for navigation.',
            },
            null,
            2
          ),
        ],
        { type: 'application/json' }
      ),
      `marisai_${variable.key}.json`
    );
  };

  return (
    <Panel>
      <PanelHeader
        icon={<Download size={14} />}
        title="Downloads"
        subtitle="This variable at this point, with its provenance attached"
      />
      <div className="flex flex-wrap gap-2 p-4">
        <Action icon={<FileSpreadsheet size={13} />} label="CSV" onClick={exportCsv} disabled={!ready} />
        <Action icon={<FileJson size={13} />} label="JSON" onClick={exportJson} disabled={!ready} />
        <Link
          to={`/download?lat=${latitude}&lon=${longitude}&variable=${variable.key}`}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5',
            'border-[color:var(--oid-border)] text-[length:var(--oid-text-sm)] no-underline',
            'text-[color:var(--oid-text)] transition-colors hover:bg-[color:var(--oid-track)]'
          )}
        >
          <PackageOpen size={13} />
          Full downloader — PDF, multi-variable, area
        </Link>
      </div>
    </Panel>
  );
}

function Action({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[length:var(--oid-text-sm)]',
        'border-[color:var(--oid-border)] text-[color:var(--oid-text)]',
        'transition-colors hover:bg-[color:var(--oid-track)]',
        'disabled:cursor-not-allowed disabled:opacity-40'
      )}
    >
      {icon}
      {label}
    </button>
  );
}
