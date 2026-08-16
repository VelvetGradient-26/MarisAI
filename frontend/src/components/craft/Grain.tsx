import './craft.css';

/**
 * Fixed film grain over the whole viewport.
 *
 * The reasoning for it — and every value it uses — is in craft.css, because it
 * is entirely a material decision rather than a behavioural one. This file
 * exists only so App.tsx mounts a named thing rather than a bare `<div>` with
 * a class nobody can search for.
 *
 * Not rendered on the map route: MapLibre's canvas is the content there, and
 * texturing live satellite imagery and a bathymetric hillshade with noise
 * degrades data the user is reading. Everywhere else the ground is a flat
 * near-black that genuinely benefits.
 */
export function Grain() {
  return <div className="craft-grain" aria-hidden="true" />;
}
