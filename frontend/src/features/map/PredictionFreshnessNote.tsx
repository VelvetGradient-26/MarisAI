import { useEffect, useState } from 'react';
import { useMapStore } from '../../store/mapStore';
import { fetchPredictionManifest } from './api/predictions';

/**
 * "Last exported: {date}" for the habitat/HAB layers — these are
 * precomputed batch predictions (see `api/predictions.ts`'s header
 * comment), not a live field, and nothing on the map otherwise tells a
 * viewer how stale the grid they're looking at is. `GET /api/predictions/manifest`
 * already carries this; this was the only consumer missing.
 *
 * Shown whenever any habitat-* or bloom-risk-* layer is active — checked by
 * id prefix against the shared layer-state map rather than importing
 * layerRegistry's id-building helpers, so this stays decoupled from exactly
 * which species/horizons exist.
 */
export function PredictionFreshnessNote() {
  const active = useMapStore((s) =>
    [...s.layers.entries()].some(
      ([id, state]) => state.active && (id.startsWith('habitat-') || id.startsWith('bloom-risk-'))
    )
  );
  const [generated, setGenerated] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    fetchPredictionManifest(controller.signal)
      .then((manifest) => setGenerated(manifest.generated))
      .catch(() => {
        /* silent — this is a freshness footnote, not load-bearing data */
      });
    return () => controller.abort();
  }, [active]);

  if (!active || !generated) return null;

  return (
    <div className="prediction-freshness-note" title="When machine_learning/exports/manifest.json was last written">
      Predictions last exported {generated.slice(0, 10)}
    </div>
  );
}
