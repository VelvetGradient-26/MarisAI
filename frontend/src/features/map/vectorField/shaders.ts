/**
 * GLSL ES 3.00 sources for the particle system. Three programs:
 *
 * - UPDATE: no rasterization (RASTERIZER_DISCARD) — a vertex shader that
 *   advects each particle's (lon, lat, age) and captures the result via
 *   transform feedback into the next frame's buffers. Bilinear sampling of
 *   the wind field is free (native GL_LINEAR texture filtering), satisfying
 *   "no pixel hopping" without any interpolation code of our own.
 * - DRAW: renders each particle as a soft, speed-colored point sprite into
 *   an offscreen trail framebuffer.
 * - COMPOSITE: fades the previous trail frame slightly, then blends the
 *   result onto the map's real framebuffer.
 *
 * Shared math (kept identical between update/draw, pasted rather than
 * `#include`d — GLSL has no includes) — windUV() must match exactly how
 * backend/services/copernicus_wind.py encodes the field texture:
 * col = (lon+180)/360, row = (90-lat)/180, row 0 = north (image was
 * flipped vertically before encoding specifically so this matches the
 * conventional top-left-origin texture layout).
 */

const WIND_UV_GLSL = `
vec2 windUV(vec2 lonlat) {
  float u = mod(lonlat.x + 180.0, 360.0) / 360.0;
  float v = (90.0 - lonlat.y) / 180.0;
  return vec2(u, v);
}
`;

const HASH_GLSL = `
float hash(float n) { return fract(sin(n) * 43758.5453123); }
`;

export const UPDATE_VERTEX_SHADER = `#version 300 es
precision highp float;

in vec2 a_lonlat;
in float a_age;
in float a_seed;

out vec2 v_lonlat;
out float v_age;

uniform sampler2D u_wind;
uniform vec4 u_uv_range;   // uMin, uMax, vMin, vMax (m/s)
uniform float u_dt;        // seconds since last frame, clamped
uniform float u_speedMultiplier;
uniform float u_maxAge;    // seconds — a particle's lifetime, NOT a frame count
uniform float u_time;
uniform vec4 u_bounds;     // minLon, minLat, maxLon, maxLat (current viewport)
// Same "world size" (tileSize(512) * 2^zoom) used to scale the draw pass's
// mercator projection — see that shader's comment. Used here, inversely, to
// keep apparent on-screen particle speed in a lively, Windy-like range at
// ANY zoom level. Real wind speed (a few m/s) is physically imperceptible
// against an entire-planet-wide view: at world-view zoom a realistic 8 m/s
// wind covers roughly 4e-4 screen pixels per second — literal physical
// accuracy would look completely static for tens of minutes. Dividing by
// worldSize (rather than Earth's real circumference) cancels the draw
// pass's zoom-dependent projection scaling, so apparent speed stays
// consistent regardless of zoom, exactly like Windy's own particles.
uniform float u_worldSize;

const float DEG2RAD = 3.14159265358979 / 180.0;
// Tuned, not physically derived: gives roughly VISUAL_SPEED_SCALE/360
// on-screen pixels/second per 1 m/s of wind, independent of zoom (see
// u_worldSize comment above) — chosen so a typical ~8 m/s wind reads as a
// lively ~40px/s, matching Windy's pace rather than real-world crawl.
const float VISUAL_SPEED_SCALE = 1800.0;

${WIND_UV_GLSL}
${HASH_GLSL}

void main() {
  vec2 uv = windUV(a_lonlat);
  vec4 windSample = texture(u_wind, uv);

  bool valid = windSample.a > 0.5;
  bool inBounds = a_lonlat.x >= u_bounds.x && a_lonlat.x <= u_bounds.z &&
                  a_lonlat.y >= u_bounds.y && a_lonlat.y <= u_bounds.w;
  bool tooOld = a_age >= u_maxAge;

  if (!valid || !inBounds || tooOld) {
    float r1 = hash(a_seed + u_time);
    float r2 = hash(a_seed * 1.618034 + u_time * 1.37);
    v_lonlat = vec2(mix(u_bounds.x, u_bounds.z, r1), mix(u_bounds.y, u_bounds.w, r2));
    v_age = 0.0;
    gl_Position = vec4(0.0, 0.0, 0.0, 1.0);
    return;
  }

  float uComp = mix(u_uv_range.x, u_uv_range.y, windSample.r);
  float vComp = mix(u_uv_range.z, u_uv_range.w, windSample.g);

  // 1/cos(lat) keeps flow direction/shape correct (meridians converge
  // toward the poles, so the same real eastward speed is a larger
  // longitude-degree change at higher latitudes) — only the relative
  // lon-vs-lat ratio matters here, not absolute physical units, since the
  // whole quantity is re-scaled for visibility below.
  float lonScale = 1.0 / max(cos(a_lonlat.y * DEG2RAD), 0.05);
  float speedScale = u_speedMultiplier * VISUAL_SPEED_SCALE / u_worldSize;
  float dLon = uComp * lonScale * u_dt * speedScale;
  float dLat = vComp * u_dt * speedScale;

  v_lonlat = a_lonlat + vec2(dLon, dLat);
  // Accumulated real seconds, not a per-call frame counter — a particle's
  // lifetime must be independent of instantaneous frame rate. Incrementing
  // by a fixed 1.0 per call previously meant that on a lower/uneven frame
  // rate a particle would hit u_maxAge (and respawn) long before it had
  // actually traveled anywhere, since real movement is scaled by u_dt but
  // age wasn't — the particle would sit still, then abruptly jump to a new
  // spot, reading as "blinking" instead of continuous flow.
  v_age = a_age + u_dt;
  gl_Position = vec4(0.0, 0.0, 0.0, 1.0);
}
`;

// Transform feedback still requires a fragment shader to link the program,
// even with RASTERIZER_DISCARD enabled (it never actually runs).
export const UPDATE_FRAGMENT_SHADER = `#version 300 es
precision highp float;
out vec4 fragColor;
void main() {
  fragColor = vec4(0.0);
}
`;

export const DRAW_VERTEX_SHADER = `#version 300 es
precision highp float;

in vec2 a_lonlat;
in float a_age;

uniform mat4 u_matrix;
uniform sampler2D u_wind;
uniform vec4 u_uv_range;
uniform float u_maxAge;    // seconds — must match the value used in the update pass
uniform float u_pointSize;
// MapLibre's modelViewProjectionMatrix expects mercator coordinates scaled by
// its internal "world size" (tileSize(512) * 2^zoom), not the plain [0,1]
// normalized mercator range — verified empirically: unscaled coordinates for
// the current map center projected to ndc (-1.37, 2.33), miles outside clip
// space, while worldSize-scaled coordinates for the same point landed
// exactly at (0, 0). Recomputed every frame since it depends on zoom.
uniform float u_worldSize;

out float v_speed;
out float v_alpha;

const float PI = 3.14159265358979;

${WIND_UV_GLSL}

vec2 lonLatToMercator(vec2 lonlat) {
  float x = (lonlat.x + 180.0) / 360.0;
  float latRad = lonlat.y * PI / 180.0;
  float y = 0.5 - log(tan(PI / 4.0 + latRad / 2.0)) / (2.0 * PI);
  return vec2(x, y) * u_worldSize;
}

void main() {
  vec2 uv = windUV(a_lonlat);
  vec4 windSample = texture(u_wind, uv);
  float uComp = mix(u_uv_range.x, u_uv_range.y, windSample.r);
  float vComp = mix(u_uv_range.z, u_uv_range.w, windSample.g);
  v_speed = length(vec2(uComp, vComp));

  // Fade in over the first fraction of a second, fade out approaching max
  // age — avoids sudden pop-in/pop-out at (re)spawn. a_age is real seconds.
  float fadeIn = smoothstep(0.0, 0.15, a_age);
  float fadeOut = 1.0 - smoothstep(u_maxAge * 0.75, u_maxAge, a_age);
  v_alpha = fadeIn * fadeOut * step(0.5, windSample.a);

  vec2 merc = lonLatToMercator(a_lonlat);
  gl_Position = u_matrix * vec4(merc, 0.0, 1.0);
  gl_PointSize = u_pointSize;
}
`;

export const DRAW_FRAGMENT_SHADER = `#version 300 es
precision highp float;

in float v_speed;
in float v_alpha;

uniform sampler2D u_colorRamp;
uniform float u_speedMax;
uniform float u_opacity;

out vec4 fragColor;

void main() {
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = length(c);
  if (d > 0.5) {
    discard;
  }
  float edge = 1.0 - smoothstep(0.25, 0.5, d);

  float t = clamp(v_speed / u_speedMax, 0.0, 1.0);
  vec3 color = texture(u_colorRamp, vec2(t, 0.5)).rgb;

  float alpha = v_alpha * edge * u_opacity;
  // Premultiplied, matching MapLibre's default custom-layer blend func
  // (gl.blendFunc(ONE, ONE_MINUS_SRC_ALPHA)).
  fragColor = vec4(color * alpha, alpha);
}
`;

export const COMPOSITE_VERTEX_SHADER = `#version 300 es
precision highp float;

in vec2 a_position;
out vec2 v_uv;

void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

// Reused for two purposes depending on u_fade: fading the previous trail
// frame slightly (u_fade < 1, drawn into the offscreen trail framebuffer)
// and a plain blit of the trail framebuffer onto the map's real framebuffer
// (u_fade = 1).
export const COMPOSITE_FRAGMENT_SHADER = `#version 300 es
precision highp float;

in vec2 v_uv;
uniform sampler2D u_source;
uniform float u_fade;

out vec4 fragColor;

void main() {
  vec4 color = texture(u_source, v_uv);
  fragColor = vec4(color.rgb * u_fade, color.a * u_fade);
}
`;
