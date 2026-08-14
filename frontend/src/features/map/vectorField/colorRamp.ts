export type ColorStop = { value: number; color: [number, number, number] };

/**
 * Generic value -> RGB color ramp, built once into a small lookup texture
 * rather than branching in the fragment shader per-pixel. Not specific to
 * wind speed — any future vector-field layer (currents, waves) supplies its
 * own `stops` and gets the same smooth-interpolation behavior. Mirrors
 * backend/services/colormaps.py's `build_colormap` (same piecewise-linear
 * approach), a separate implementation because one runs in Python for PNG
 * tiles and this one runs in JS to build a GPU texture — not shareable code,
 * same algorithm.
 */
export function buildColorRampTexture(
  gl: WebGL2RenderingContext,
  stops: ColorStop[],
  size = 256
): WebGLTexture {
  const sorted = [...stops].sort((a, b) => a.value - b.value);
  const min = sorted[0].value;
  const max = sorted[sorted.length - 1].value;

  const data = new Uint8Array(size * 4);
  for (let i = 0; i < size; i++) {
    const t = min + ((max - min) * i) / (size - 1);
    const [r, g, b] = interpolateColor(sorted, t);
    data[i * 4] = r;
    data[i * 4 + 1] = g;
    data[i * 4 + 2] = b;
    data[i * 4 + 3] = 255;
  }

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, size, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return texture;
}

function interpolateColor(stops: ColorStop[], value: number): [number, number, number] {
  if (value <= stops[0].value) return stops[0].color;
  if (value >= stops[stops.length - 1].value) return stops[stops.length - 1].color;

  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (value >= a.value && value <= b.value) {
      const t = (value - a.value) / (b.value - a.value);
      return [
        Math.round(a.color[0] + (b.color[0] - a.color[0]) * t),
        Math.round(a.color[1] + (b.color[1] - a.color[1]) * t),
        Math.round(a.color[2] + (b.color[2] - a.color[2]) * t),
      ];
    }
  }
  return stops[stops.length - 1].color;
}

/** Wind speed stops per the Windy-style spec: 0-2 dark blue through 25+
 * purple (open-ended top bucket — interpolateColor clamps anything >=25 to
 * pure purple, it doesn't extrapolate past it), smoothly interpolated (no
 * discrete bands). */
export const WIND_SPEED_COLOR_STOPS: ColorStop[] = [
  { value: 0, color: [30, 58, 138] }, // dark blue
  { value: 2, color: [6, 182, 212] }, // cyan
  { value: 5, color: [34, 197, 94] }, // green
  { value: 8, color: [234, 179, 8] }, // yellow
  { value: 12, color: [249, 115, 22] }, // orange
  { value: 18, color: [220, 38, 38] }, // red
  { value: 25, color: [147, 51, 234] }, // purple
];

/**
 * Current speed, 0 to 2+ m/s. **Single-hue amber, dark to light** — and the
 * single hue is the point.
 *
 * Wind and currents are both in the stackable `flow` group and are meant to be
 * read together, so the two ramps have to be told apart at a glance. Hue alone
 * cannot do it: wind's ramp is a full rainbow and has already spent every hue,
 * so any second rainbow collides with it somewhere. What separates them is
 * *structure* — one field cycles through hues, the other never leaves amber —
 * and that reads instantly even where a current pixel and a wind pixel happen
 * to land on the same colour.
 *
 * It is also what a sequential scale is supposed to be (one hue, monotonic
 * lightness), which wind's Windy-convention rainbow is not. Measured against
 * the Abyss basemap's near-black ocean (#030f1e): lightness rises
 * 0.149 -> 0.926 with no reversal, and the darkest stop clears 3.65:1 — the
 * whole ramp is above the 3:1 floor, unlike the raster ramps in
 * `services/colormaps.py`, whose dark ends bottom out near the basemap and had
 * to be rescued with a hatch.
 *
 * Anchors: open ocean sits at 0.1-0.4 m/s, so most of the map lives in the
 * first two stops; the top of the scale exists for the western boundary
 * currents (Gulf Stream, Kuroshio, Agulhas) that actually reach 2 m/s.
 */
export const CURRENT_SPEED_COLOR_STOPS: ColorStop[] = [
  { value: 0, color: [150, 96, 28] }, // #96601c — slack water, still visible
  { value: 0.15, color: [184, 116, 16] }, // #b87410
  { value: 0.3, color: [220, 148, 24] }, // #dc9418
  { value: 0.6, color: [245, 183, 60] }, // #f5b73c
  { value: 1.0, color: [255, 212, 122] }, // #ffd47a
  { value: 1.5, color: [255, 234, 184] }, // #ffeab8
  { value: 2.0, color: [255, 246, 224] }, // #fff6e0 — boundary-current core
];

/**
 * Stokes drift — a third field, and therefore a third *structure* rather than a
 * third palette.
 *
 * The rule this follows is the one the currents ramp set: wind cycles hues
 * (Windy convention), currents never leave amber, and this never leaves violet
 * — hue is locked at ~269° across every stop. Two single-hue ramps can be told
 * apart at a glance in a way two rainbows cannot, and all three of these layers
 * live in the stackable `flow` group and are meant to be read together.
 *
 * Measured against the Abyss basemap's near-black ocean (#030f1e): lightness
 * rises 0.498 → 0.971 with no reversal and the darkest stop clears **3.30:1**,
 * so the whole ramp is above the 3:1 floor the currents ramp holds.
 *
 * One honest caveat: at their extreme tops this ramp and the amber one converge
 * toward near-white and are ~33 RGB apart. That is inherent to two sequential
 * scales that both end light, and it only bites where both fields are
 * simultaneously at maximum — Stokes at 1 m/s is a storm sea and currents at
 * 2 m/s is a boundary-current core. Everywhere the map actually lives, violet
 * and amber are unmistakable.
 *
 * Anchors: open-ocean Stokes drift is 0.05-0.3 m/s, so most of the map sits in
 * the first three stops; the top exists for storm seas.
 */
export const STOKES_DRIFT_COLOR_STOPS: ColorStop[] = [
  { value: 0, color: [126, 78, 176] }, // #7e4eb0 — calm, still visible
  { value: 0.08, color: [146, 96, 198] }, // #9260c6
  { value: 0.15, color: [166, 118, 216] }, // #a676d8
  { value: 0.3, color: [190, 148, 234] }, // #be94ea
  { value: 0.5, color: [212, 180, 244] }, // #d4b4f4
  { value: 0.75, color: [232, 212, 250] }, // #e8d4fa
  { value: 1.0, color: [247, 240, 255] }, // #f7f0ff — storm sea
];

/**
 * Combined drift — the fourth field, and therefore the fourth *structure*.
 *
 * Wind cycles hues, currents never leave amber, Stokes drift never leaves
 * violet, and this never leaves green (hue locked at 150°). Four single-hue
 * ramps against one rainbow is still legible in a way four rainbows would not
 * be, and all four layers live in the stackable `flow` group and are meant to
 * be switched between rather than memorised.
 *
 * Measured against the Abyss basemap's near-black ocean (#030f1e): lightness
 * rises 0.318 → 0.917 with no reversal, and the darkest stop clears **6.75:1**
 * — comfortably above the 3:1 floor the currents and Stokes ramps hold. Green
 * is the one remaining hue that is far from both amber and violet at the dark
 * end, where the map actually lives: the darkest stop sits 156 RGB from the
 * nearest amber stop and 146 from the nearest violet one.
 *
 * The same caveat the Stokes ramp records applies and for the same reason: all
 * three sequential ramps end near white, so at their extreme tops they
 * converge. That only bites where two fields are simultaneously at maximum,
 * which is a storm over a boundary current.
 *
 * The scale reaches 2.5 rather than currents' 2.0 because this field is a sum:
 * the three terms add rather than averaging, so a boundary current under a gale
 * with a raft's leeway goes past where the currents ramp ends.
 */
export const DRIFT_SPEED_COLOR_STOPS: ColorStop[] = [
  { value: 0, color: [41, 174, 107] }, // #29ae6b — slack water, still visible
  { value: 0.1, color: [51, 204, 128] }, // #33cc80
  { value: 0.25, color: [96, 210, 153] }, // #60d299
  { value: 0.5, color: [142, 215, 178] }, // #8ed7b2
  { value: 1.0, color: [186, 222, 204] }, // #badecc
  { value: 1.7, color: [220, 234, 227] }, // #dceae3
  { value: 2.5, color: [244, 246, 245] }, // #f4f6f5 — current + sea + gale
];
