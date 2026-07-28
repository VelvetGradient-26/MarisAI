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
