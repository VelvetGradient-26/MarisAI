import { useEffect } from 'react';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';

/**
 * Brings a clicked point back toward the centre of the globe — rotation only,
 * never zoom.
 *
 * **This deliberately narrows a request rather than implementing it as stated.**
 * `useSelectedLocationFocus` records the existing rule and its reason: a plain
 * map click never moves the camera, "since the user is already looking at that
 * point and yanking the camera onto it would fight them". That argument holds
 * on a flat map. It is genuinely weaker on the globe, where a point near the
 * limb is foreshortened, compressed and partly self-occluded — "already looking
 * at it" is much less true there. So the camera moves, but only where the
 * original objection does not apply, and only in the axis that fixes the
 * problem:
 *
 * * **Rotate, do not zoom.** Zoom changes how much ocean is on screen, which is
 *   the part that would fight the user. Rotation only changes which face of the
 *   sphere is toward them, which is the actual complaint.
 * * **Only past a threshold**, measured in screen space rather than in degrees.
 *   A fixed angular threshold is wrong at every zoom but one: the visible arc
 *   spans most of a hemisphere at z2 and a few degrees at z8, so an angle that
 *   means "out at the limb" zoomed out means "off the map entirely" zoomed in.
 *   The projected offset from the canvas centre, as a fraction of its radius,
 *   is both zoom-invariant and the thing the user actually sees.
 * * **Only while it is really a sphere.** `'globe'` is MapLibre's *adaptive*
 *   projection — it eases back into mercator as you zoom in — so past that
 *   transition there is no limb, no foreshortening, and no reason to move.
 * * **Never when `pendingFocus` is set.** That is an off-map request
 *   (the dashboard's coordinate form) and `useSelectedLocationFocus` owns it;
 *   both hooks acting would ease the camera twice.
 *
 * Reduced motion resolves to the finished state — an instant recentre — rather
 * than to a degraded animation, the same rule the rest of the app follows.
 */

/**
 * Distance from the canvas centre, as a fraction of its inner radius, past
 * which a clicked point is considered to be out toward the limb. At 0.45 the
 * middle ~half of the disc is left alone entirely, so ordinary clicks near
 * where you are already looking do nothing at all.
 */
const LIMB_THRESHOLD = 0.45;

/**
 * MapLibre's globe projection has fully become mercator by this zoom, so above
 * it there is no sphere to rotate. Kept a touch below the transition's start so
 * the behaviour stops before the geometry stops being spherical, rather than
 * exactly at the boundary where it is half of each.
 */
const SPHERICAL_MAX_ZOOM = 11;

const RECENTRE_DURATION_MS = 650;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

export function useGlobeClickRecenter(manager: MapManager | null, ready: boolean) {
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const pendingFocus = useMapStore((s) => s.pendingFocus);

  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map || !selectedLocation) return;
    // An off-map focus request; useSelectedLocationFocus is moving the camera.
    if (pendingFocus) return;
    if (manager?.getProjectionMode() !== 'globe') return;
    if (map.getZoom() > SPHERICAL_MAX_ZOOM) return;

    const canvas = map.getCanvas();
    const centreX = canvas.clientWidth / 2;
    const centreY = canvas.clientHeight / 2;
    // The inner radius, so the test means the same thing on a tall phone and a
    // wide desktop — the globe is inscribed in the smaller dimension.
    const radius = Math.min(centreX, centreY);
    if (radius <= 0) return;

    const projected = map.project([selectedLocation.lng, selectedLocation.lat]);
    const offset = Math.hypot(projected.x - centreX, projected.y - centreY);
    if (offset <= radius * LIMB_THRESHOLD) return;

    map.easeTo({
      center: [selectedLocation.lng, selectedLocation.lat],
      // Zoom, bearing and pitch are deliberately absent: easeTo leaves
      // unspecified properties alone, which is the whole point of this hook.
      duration: prefersReducedMotion() ? 0 : RECENTRE_DURATION_MS,
      essential: true,
    });
  }, [manager, ready, selectedLocation, pendingFocus]);
}
