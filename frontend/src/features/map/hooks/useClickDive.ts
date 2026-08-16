import { useEffect, useRef } from 'react';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';

/**
 * Clicking a point flies the camera down onto it, with a reticle that locks
 * on during the descent.
 *
 * **This reverses a rule the codebase previously held, deliberately and on
 * request.** `useSelectedLocationFocus` recorded that "a plain
 * `setSelectedLocation` (a map click) never moves the camera, since the user
 * is already looking at that point and yanking the camera onto it would fight
 * them", and `useGlobeClickRecenter` — which this replaces — narrowed that to
 * rotation-only, globe-only, limb-only. The old objection was a real one, so
 * it is answered rather than ignored: the three properties below are what stop
 * a dive from fighting the user.
 *
 * - **It converges.** Each click descends by a fixed step and stops at
 *   `MAX_DIVE_ZOOM`; past that a click only recentres. Without a ceiling,
 *   inspecting five points in a row would leave you at street level over an
 *   ocean, and the way out would be five scroll gestures. With one, repeated
 *   clicking settles at a zoom that still shows the surrounding coastline —
 *   which is the context that makes a single point's conditions readable at
 *   all.
 * - **It is skipped when the camera is already there.** A click within a small
 *   screen-space radius of the centre, at or past the ceiling, does nothing.
 *   That is the case the original objection was actually about.
 * - **It never runs on an off-map focus request.** `pendingFocus` (the
 *   dashboard's coordinate form) belongs to `useSelectedLocationFocus`; both
 *   hooks easing at once would fight each other rather than the user.
 *
 * Unlike the hook it replaces this applies to the flat map as well as the
 * globe. The limb-foreshortening argument was globe-specific, but "I clicked
 * that, take me to it" is not.
 */

/** How much closer each click takes you. Roughly 4.5x the area, which is a
 *  descent you can feel without losing your place on the way down. */
const DIVE_STEP = 2.2;

/**
 * The floor. Chosen from what the data can support rather than from feel: the
 * ocean fields behind this map are 0.083° products (~9 km), so past roughly
 * this zoom the imagery keeps sharpening while every value being read out
 * stops changing. Diving further would promise a precision the sources do not
 * have.
 */
const MAX_DIVE_ZOOM = 7.5;

/** Screen-space slack, in pixels, inside which the point counts as already
 *  centred. Larger than it looks it needs to be, because at the ceiling the
 *  only remaining motion is a recentre and a 30px nudge is a twitch. */
const CENTRED_SLACK_PX = 48;

const DIVE_DURATION_MS = 1500;

/**
 * The camera curve.
 *
 * `flyTo`'s own default arcs *out* before coming back in — correct for a long
 * lateral journey, and exactly wrong here, where the target is usually already
 * on screen and the retreat reads as the map flinching. `curve` near 1 flattens
 * that arc almost away, and the easing below supplies the drama instead:
 * an ease-in-out cubic, so the descent gathers speed from rest and then has a
 * long settle rather than arriving and stopping dead.
 */
const DIVE_CURVE = 1.15;

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

export function useClickDive(manager: MapManager | null, ready: boolean) {
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const pendingFocus = useMapStore((s) => s.pendingFocus);
  const reticleRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map || !selectedLocation) return;
    // An off-map focus request; useSelectedLocationFocus owns the camera.
    if (pendingFocus) return;

    const target: [number, number] = [selectedLocation.lng, selectedLocation.lat];
    const currentZoom = map.getZoom();
    const targetZoom = Math.min(currentZoom + DIVE_STEP, MAX_DIVE_ZOOM);

    // Already as close as this hook will take you, and already looking at it.
    const projected = map.project(target);
    const canvas = map.getCanvas();
    const offset = Math.hypot(
      projected.x - canvas.clientWidth / 2,
      projected.y - canvas.clientHeight / 2
    );
    if (targetZoom <= currentZoom + 0.01 && offset < CENTRED_SLACK_PX) return;

    const reduced = prefersReducedMotion();

    map.flyTo({
      center: target,
      zoom: targetZoom,
      curve: DIVE_CURVE,
      easing: easeInOutCubic,
      duration: reduced ? 0 : DIVE_DURATION_MS,
      // The camera is answering something the user just did, so it must not be
      // cancelled by a `prefers-reduced-motion` check inside MapLibre — the
      // reduced path above is an instant jump, which is the right degradation.
      essential: true,
    });

    if (reduced) return;

    // --- reticle ---------------------------------------------------------
    // A DOM overlay rather than a MapLibre layer, for two reasons. It has to
    // *contract* smoothly over 1.5s, and a circle layer's radius can only be
    // driven by repainting a paint property every frame — which is the one
    // thing that must not be added to a frame budget already running a globe,
    // a raster overlay and a GPU particle field. And it belongs to this
    // interaction, not to the map's state: `useSelectedLocationMarker` owns
    // the persistent pin, and reaching into its source from here would give
    // two hooks a claim on the same layers.
    //
    // It is reprojected every frame instead of being placed once, so it stays
    // locked to the geography while the camera moves under it. That tracking
    // is the whole effect — a reticle that sits still on screen during a dive
    // is a decoration, one that holds its ground is a lock-on.
    const container = map.getContainer();
    const reticle = document.createElement('div');
    reticle.className = 'map-dive-reticle';
    reticle.setAttribute('aria-hidden', 'true');
    container.appendChild(reticle);
    reticleRef.current = reticle;

    const started = performance.now();
    const track = () => {
      const elapsed = performance.now() - started;
      const point = map.project(target);
      reticle.style.transform = `translate3d(${point.x}px, ${point.y}px, 0) translate(-50%, -50%)`;
      if (elapsed < DIVE_DURATION_MS) {
        frameRef.current = requestAnimationFrame(track);
      }
    };
    frameRef.current = requestAnimationFrame(track);

    // The CSS animation is `forwards`, so it holds at zero opacity until this
    // removes the node. Timed rather than hung off `moveend`, because a user
    // who grabs the map mid-flight cancels `moveend` and would strand it.
    const clear = window.setTimeout(() => {
      reticle.remove();
      reticleRef.current = null;
    }, DIVE_DURATION_MS);

    return () => {
      window.clearTimeout(clear);
      if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      reticleRef.current?.remove();
      reticleRef.current = null;
    };
  }, [manager, ready, selectedLocation, pendingFocus]);
}
