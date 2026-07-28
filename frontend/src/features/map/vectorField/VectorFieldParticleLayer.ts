import type { Map as MapLibreMap, CustomRenderMethodInput } from 'maplibre-gl';
import type { CustomVectorFieldLayer } from '../types';
import {
  UPDATE_VERTEX_SHADER,
  UPDATE_FRAGMENT_SHADER,
  DRAW_VERTEX_SHADER,
  DRAW_FRAGMENT_SHADER,
  COMPOSITE_VERTEX_SHADER,
  COMPOSITE_FRAGMENT_SHADER,
} from './shaders';
import { buildColorRampTexture, type ColorStop } from './colorRamp';

type ProjectionMatrix = CustomRenderMethodInput['modelViewProjectionMatrix'];

export interface VectorFieldMeta {
  u_min: number;
  u_max: number;
  v_min: number;
  v_max: number;
  speed_max_legend: number;
}

/**
 * Everything a concrete field (wind today; currents/waves later) needs to
 * supply — the particle engine itself (advection, bilinear sampling,
 * density, coloring, trails, blending) is entirely generic. See
 * vectorField/windLayer.ts for the wind-specific instantiation.
 */
export interface VectorFieldConfig {
  fieldTextureUrl: string;
  fetchMeta: (signal?: AbortSignal) => Promise<VectorFieldMeta>;
  colorStops: ColorStop[];
}

const DENSITY_COUNTS = { world: 8000, regional: 20000, local: 50000 } as const;
type DensityTier = keyof typeof DENSITY_COUNTS;

// Real seconds, not a frame count — a particle's lifetime must be
// independent of the actual frame rate (see shaders.ts's v_age comment).
const MAX_AGE_SECONDS = 3.0;
// Trail decay expressed as "fraction remaining after 1 real second" and
// converted to a per-frame multiplier via Math.pow(_, dt) each frame, so the
// visible trail length stays consistent regardless of instantaneous fps
// (a fixed per-call multiplier would make trails on a slower machine fade
// less per real second than on a faster one).
const TRAIL_FADE_PER_SECOND = 0.15;
const POINT_SIZE_PX = 2.5;
const MAX_DT_SECONDS = 0.1; // clamps huge jumps after tab backgrounding/frame drops

interface ParticleBufferSet {
  lonlat: WebGLBuffer;
  age: WebGLBuffer;
  seed: WebGLBuffer;
}

/**
 * Generic GPU particle engine for gridded U/V vector fields, implemented as
 * a MapLibre CustomLayerInterface. Particle state (lon, lat, age) lives in
 * GPU buffers and is advected via transform feedback (WebGL2) — no
 * per-frame readback to the CPU, no re-fetching/recomputing the field.
 *
 * Per-frame sequence in render(): UPDATE (transform feedback advects every
 * particle) -> DRAW (renders particles as soft speed-colored points into an
 * offscreen trail framebuffer, which is faded slightly before each frame's
 * new points are added) -> COMPOSITE (blits the trail framebuffer onto the
 * map's real framebuffer). See shaders.ts for the per-stage GLSL.
 */
export class VectorFieldParticleLayer implements CustomVectorFieldLayer {
  id: string;
  type = 'custom' as const;
  renderingMode = '2d' as const;

  private config: VectorFieldConfig;
  private opacity: number;
  private speedMultiplier = 1;
  private densityTierOverride: DensityTier | 'auto' = 'auto';

  private gl: WebGL2RenderingContext | null = null;
  private map: MapLibreMap | null = null;

  private updateProgram: WebGLProgram | null = null;
  private drawProgram: WebGLProgram | null = null;
  private compositeProgram: WebGLProgram | null = null;

  private windTexture: WebGLTexture | null = null;
  private colorRampTexture: WebGLTexture | null = null;
  private quadBuffer: WebGLBuffer | null = null;
  private quadVAO: WebGLVertexArrayObject | null = null;
  private transformFeedback: WebGLTransformFeedback | null = null;

  private particleBuffers: [ParticleBufferSet, ParticleBufferSet] | null = null;
  private updateVAOs: [WebGLVertexArrayObject, WebGLVertexArrayObject] | null = null;
  private drawVAOs: [WebGLVertexArrayObject, WebGLVertexArrayObject] | null = null;
  private current = 0;
  private particleCount = 0;

  private trailFBOs: [WebGLFramebuffer, WebGLFramebuffer] | null = null;
  private trailTextures: [WebGLTexture, WebGLTexture] | null = null;
  private trailCurrent = 0;
  private trailWidth = 0;
  private trailHeight = 0;

  private meta: VectorFieldMeta | null = null;
  private loadError = false;
  private lastFrameTimeMs = 0;
  private elapsedSeconds = 0;
  private destroyed = false;
  private animationFrameId = 0;

  constructor(id: string, config: VectorFieldConfig, initialOpacity = 1) {
    this.id = id;
    this.config = config;
    this.opacity = initialOpacity;
  }

  setOpacity(opacity: number): void {
    this.opacity = Math.min(1, Math.max(0, opacity));
  }

  setSpeedMultiplier(multiplier: number): void {
    this.speedMultiplier = Math.max(0, multiplier);
  }

  setDensityTier(tier: 'world' | 'regional' | 'local' | 'auto'): void {
    this.densityTierOverride = tier;
  }

  onAdd(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    this.map = map;
    this.gl = gl;

    this.updateProgram = createProgram(gl, UPDATE_VERTEX_SHADER, UPDATE_FRAGMENT_SHADER, [
      'v_lonlat',
      'v_age',
    ]);
    this.drawProgram = createProgram(gl, DRAW_VERTEX_SHADER, DRAW_FRAGMENT_SHADER);
    this.compositeProgram = createProgram(gl, COMPOSITE_VERTEX_SHADER, COMPOSITE_FRAGMENT_SHADER);

    this.colorRampTexture = buildColorRampTexture(gl, this.config.colorStops);
    this.quadBuffer = createFullscreenQuad(gl);
    // A dedicated VAO for the fullscreen-quad blit, rather than touching the
    // "default" VAO (id 0) — MapLibre manages its own VAO state internally
    // and raw operations against the default VAO while sharing its GL
    // context are a known source of subtle cross-contamination, since it
    // isn't necessarily what MapLibre's own Context wrapper expects to be
    // bound between draw calls.
    this.quadVAO = gl.createVertexArray();
    gl.bindVertexArray(this.quadVAO);
    bindAttribute(gl, this.compositeProgram, this.quadBuffer, 'a_position', 2);
    gl.bindVertexArray(null);

    this.transformFeedback = gl.createTransformFeedback();

    const initialCount = DENSITY_COUNTS[this.pickDensityTier(map.getZoom())];
    this.rebuildParticles(gl, initialCount);

    loadTexture(gl, this.config.fieldTextureUrl)
      .then((texture) => {
        if (this.destroyed) {
          gl.deleteTexture(texture);
          return;
        }
        this.windTexture = texture;
      })
      .catch((err: unknown) => {
        console.warn(`[VectorFieldParticleLayer:${this.id}] field texture load failed`, err);
        this.loadError = true;
      });

    this.config
      .fetchMeta()
      .then((meta) => {
        if (this.destroyed) return;
        this.meta = meta;
      })
      .catch((err: unknown) => {
        console.warn(`[VectorFieldParticleLayer:${this.id}] meta fetch failed`, err);
        this.loadError = true;
      });

    // MapLibre only keeps invoking a layer's render() while it considers the
    // map "dirty" (camera moving, style/source transitions, etc.), and
    // map.triggerRepaint() only *asks* for a frame via its own internal
    // _frameRequest bookkeeping — in practice this did not reliably keep
    // producing frames once the map settled (verified: calling it from
    // inside render() sometimes stopped after a handful of frames with no
    // error). map.redraw() is different: it synchronously forces
    // _render(0) right now, with no scheduling/dirty-checking involved, so
    // an external requestAnimationFrame loop calling it every tick
    // guarantees this layer's render() actually runs every frame for as
    // long as the layer is active, independent of MapLibre's own idle
    // detection.
    const driveAnimation = () => {
      if (this.destroyed) return;
      this.map?.redraw();
      this.animationFrameId = requestAnimationFrame(driveAnimation);
    };
    this.animationFrameId = requestAnimationFrame(driveAnimation);
  }

  onRemove(): void {
    const gl = this.gl;
    this.destroyed = true;
    if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
    if (!gl) return;

    if (this.updateProgram) gl.deleteProgram(this.updateProgram);
    if (this.drawProgram) gl.deleteProgram(this.drawProgram);
    if (this.compositeProgram) gl.deleteProgram(this.compositeProgram);
    if (this.windTexture) gl.deleteTexture(this.windTexture);
    if (this.colorRampTexture) gl.deleteTexture(this.colorRampTexture);
    if (this.quadBuffer) gl.deleteBuffer(this.quadBuffer);
    if (this.quadVAO) gl.deleteVertexArray(this.quadVAO);
    if (this.transformFeedback) gl.deleteTransformFeedback(this.transformFeedback);
    this.deleteParticleResources(gl);
    this.deleteTrailResources(gl);

    this.gl = null;
    this.map = null;
  }

  render(_gl: WebGL2RenderingContext, options: CustomRenderMethodInput): void {
    const gl = this.gl;
    const map = this.map;
    // Matches MapLibre's own documented pattern for animated custom layers
    // ("keep repainting while the icon is on the map"). The actual
    // continuity guarantee comes from the independent requestAnimationFrame
    // + map.redraw() loop started in onAdd, not from this call alone (see
    // that loop's comment) — kept here too since it's harmless and costs
    // nothing if a frame is already pending.
    map?.triggerRepaint();
    if (!gl || !map || !this.windTexture || !this.meta || this.loadError) {
      return;
    }

    // The whole frame is wrapped: an uncaught exception here would otherwise
    // escape into MapLibre's own render loop and silently stop it from
    // scheduling further frames for this layer, freezing the animation with
    // no visible error.
    try {
      const now = performance.now();
      const dt =
        this.lastFrameTimeMs === 0 ? 0 : Math.min((now - this.lastFrameTimeMs) / 1000, MAX_DT_SECONDS);
      this.lastFrameTimeMs = now;
      this.elapsedSeconds += dt;

      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;
      this.ensureTrailFramebuffers(gl, width, height);

      const desiredCount = DENSITY_COUNTS[this.pickDensityTier(map.getZoom())];
      if (desiredCount !== this.particleCount) {
        this.rebuildParticles(gl, desiredCount);
      }

      const bounds = map.getBounds();
      const boundsArray: [number, number, number, number] = [
        Math.max(bounds.getWest(), -180),
        Math.max(bounds.getSouth(), -85),
        Math.min(bounds.getEast(), 180),
        Math.min(bounds.getNorth(), 85),
      ];

      const previousFBO = gl.getParameter(gl.FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
      const worldSize = 512 * Math.pow(2, map.getZoom());

      this.runUpdatePass(gl, dt, boundsArray, worldSize);
      this.runDrawPass(gl, width, height, options.modelViewProjectionMatrix, worldSize, dt);
      this.runCompositePass(gl, previousFBO, width, height);
    } catch (err) {
      console.error(`[VectorFieldParticleLayer:${this.id}] render failed`, err);
    }
  }

  private pickDensityTier(zoom: number): DensityTier {
    if (this.densityTierOverride !== 'auto') return this.densityTierOverride;
    if (zoom < 3) return 'world';
    if (zoom < 6) return 'regional';
    return 'local';
  }

  private runUpdatePass(
    gl: WebGL2RenderingContext,
    dt: number,
    bounds: [number, number, number, number],
    worldSize: number
  ) {
    if (!this.updateProgram || !this.updateVAOs || !this.particleBuffers || !this.windTexture || !this.meta)
      return;

    const next = 1 - this.current;
    const program = this.updateProgram;

    gl.useProgram(program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
    gl.uniform1i(gl.getUniformLocation(program, 'u_wind'), 0);
    gl.uniform4f(
      gl.getUniformLocation(program, 'u_uv_range'),
      this.meta.u_min,
      this.meta.u_max,
      this.meta.v_min,
      this.meta.v_max
    );
    gl.uniform1f(gl.getUniformLocation(program, 'u_dt'), dt);
    gl.uniform1f(gl.getUniformLocation(program, 'u_speedMultiplier'), this.speedMultiplier);
    gl.uniform1f(gl.getUniformLocation(program, 'u_maxAge'), MAX_AGE_SECONDS);
    gl.uniform1f(gl.getUniformLocation(program, 'u_time'), this.elapsedSeconds);
    gl.uniform4f(gl.getUniformLocation(program, 'u_bounds'), bounds[0], bounds[1], bounds[2], bounds[3]);
    gl.uniform1f(gl.getUniformLocation(program, 'u_worldSize'), worldSize);

    gl.bindVertexArray(this.updateVAOs[this.current]);

    // bindBufferBase attaches to whichever transform feedback object is
    // CURRENTLY bound — it must come after binding our own TF object, not
    // before, or the buffers attach to the default object instead and
    // beginTransformFeedback fails (that object has none bound).
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, this.transformFeedback);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, this.particleBuffers[next].lonlat);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 1, this.particleBuffers[next].age);
    // Defensive: VAO setup (bindAttribute) leaves whichever buffer it last
    // touched bound to the global ARRAY_BUFFER point, independent of VAO
    // state. If that happens to be one of the buffers just bound above as a
    // transform-feedback target, some drivers treat "same buffer bound to
    // TRANSFORM_FEEDBACK_BUFFER and still bound elsewhere" as a hazard and
    // reject the draw — unbinding here removes any such aliasing.
    gl.bindBuffer(gl.ARRAY_BUFFER, null);

    gl.enable(gl.RASTERIZER_DISCARD);
    gl.beginTransformFeedback(gl.POINTS);
    gl.drawArrays(gl.POINTS, 0, this.particleCount);
    gl.endTransformFeedback();
    gl.disable(gl.RASTERIZER_DISCARD);
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);

    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, null);
    gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 1, null);
    gl.bindVertexArray(null);

    this.current = next;
  }

  private runDrawPass(
    gl: WebGL2RenderingContext,
    width: number,
    height: number,
    matrix: ProjectionMatrix,
    worldSize: number,
    dt: number
  ) {
    if (
      !this.drawProgram ||
      !this.drawVAOs ||
      !this.trailFBOs ||
      !this.trailTextures ||
      !this.windTexture ||
      !this.colorRampTexture ||
      !this.meta
    )
      return;

    const trailNext = 1 - this.trailCurrent;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.trailFBOs[trailNext]);
    gl.viewport(0, 0, width, height);

    // Fade the previous trail frame into this one (plain overwrite blit —
    // blending must be off, we're replacing the buffer's contents). Raised
    // to the power of dt (real seconds) rather than applied as a flat
    // per-call multiplier, so the visible trail length is consistent
    // regardless of instantaneous frame rate.
    const fade = dt > 0 ? Math.pow(TRAIL_FADE_PER_SECOND, dt) : 1;
    gl.disable(gl.BLEND);
    this.blit(gl, this.trailTextures[this.trailCurrent], fade);

    // Draw this frame's particles on top, additively blended (premultiplied
    // alpha from the fragment shader — see shaders.ts).
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    const program = this.drawProgram;
    gl.useProgram(program);
    gl.uniformMatrix4fv(gl.getUniformLocation(program, 'u_matrix'), false, matrix);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.windTexture);
    gl.uniform1i(gl.getUniformLocation(program, 'u_wind'), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.colorRampTexture);
    gl.uniform1i(gl.getUniformLocation(program, 'u_colorRamp'), 1);
    gl.uniform4f(
      gl.getUniformLocation(program, 'u_uv_range'),
      this.meta.u_min,
      this.meta.u_max,
      this.meta.v_min,
      this.meta.v_max
    );
    gl.uniform1f(gl.getUniformLocation(program, 'u_maxAge'), MAX_AGE_SECONDS);
    gl.uniform1f(gl.getUniformLocation(program, 'u_pointSize'), POINT_SIZE_PX);
    gl.uniform1f(gl.getUniformLocation(program, 'u_speedMax'), this.meta.speed_max_legend);
    gl.uniform1f(gl.getUniformLocation(program, 'u_opacity'), this.opacity);
    gl.uniform1f(gl.getUniformLocation(program, 'u_worldSize'), worldSize);

    gl.bindVertexArray(this.drawVAOs[this.current]);
    gl.drawArrays(gl.POINTS, 0, this.particleCount);
    gl.bindVertexArray(null);

    this.trailCurrent = trailNext;
  }

  private runCompositePass(
    gl: WebGL2RenderingContext,
    targetFBO: WebGLFramebuffer | null,
    width: number,
    height: number
  ) {
    if (!this.trailTextures) return;
    gl.bindFramebuffer(gl.FRAMEBUFFER, targetFBO);
    gl.viewport(0, 0, width, height);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    this.blit(gl, this.trailTextures[this.trailCurrent], 1.0);
  }

  private blit(gl: WebGL2RenderingContext, texture: WebGLTexture, fade: number) {
    if (!this.compositeProgram || !this.quadVAO) return;
    gl.useProgram(this.compositeProgram);
    gl.bindVertexArray(this.quadVAO);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.uniform1i(gl.getUniformLocation(this.compositeProgram, 'u_source'), 0);
    gl.uniform1f(gl.getUniformLocation(this.compositeProgram, 'u_fade'), fade);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }

  private ensureTrailFramebuffers(gl: WebGL2RenderingContext, width: number, height: number) {
    if (this.trailFBOs && this.trailWidth === width && this.trailHeight === height) return;

    this.deleteTrailResources(gl);
    this.trailWidth = width;
    this.trailHeight = height;

    const makeTarget = (): { fbo: WebGLFramebuffer; texture: WebGLTexture } => {
      const texture = gl.createTexture()!;
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      const fbo = gl.createFramebuffer()!;
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      return { fbo, texture };
    };

    const a = makeTarget();
    const b = makeTarget();
    this.trailFBOs = [a.fbo, b.fbo];
    this.trailTextures = [a.texture, b.texture];
    this.trailCurrent = 0;
  }

  private deleteTrailResources(gl: WebGL2RenderingContext) {
    if (this.trailFBOs) {
      gl.deleteFramebuffer(this.trailFBOs[0]);
      gl.deleteFramebuffer(this.trailFBOs[1]);
      this.trailFBOs = null;
    }
    if (this.trailTextures) {
      gl.deleteTexture(this.trailTextures[0]);
      gl.deleteTexture(this.trailTextures[1]);
      this.trailTextures = null;
    }
  }

  private rebuildParticles(gl: WebGL2RenderingContext, count: number) {
    if (!this.updateProgram || !this.drawProgram) return;
    this.deleteParticleResources(gl);

    const lonlatA = new Float32Array(count * 2);
    const ageA = new Float32Array(count);
    const seedA = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      lonlatA[i * 2] = Math.random() * 360 - 180;
      lonlatA[i * 2 + 1] = Math.random() * 170 - 85;
      // Stagger initial ages so particles don't all respawn in lockstep.
      ageA[i] = Math.random() * MAX_AGE_SECONDS;
      seedA[i] = Math.random() * 1000;
    }

    const setA = createParticleBufferSet(gl, lonlatA, ageA, seedA);
    const setB = createParticleBufferSet(
      gl,
      new Float32Array(count * 2),
      new Float32Array(count),
      seedA
    );
    this.particleBuffers = [setA, setB];
    this.particleCount = count;
    this.current = 0;

    this.updateVAOs = [
      createUpdateVAO(gl, this.updateProgram, setA),
      createUpdateVAO(gl, this.updateProgram, setB),
    ];
    this.drawVAOs = [
      createDrawVAO(gl, this.drawProgram, setA),
      createDrawVAO(gl, this.drawProgram, setB),
    ];
  }

  private deleteParticleResources(gl: WebGL2RenderingContext) {
    if (this.particleBuffers) {
      for (const set of this.particleBuffers) {
        gl.deleteBuffer(set.lonlat);
        gl.deleteBuffer(set.age);
        gl.deleteBuffer(set.seed);
      }
      this.particleBuffers = null;
    }
    if (this.updateVAOs) {
      gl.deleteVertexArray(this.updateVAOs[0]);
      gl.deleteVertexArray(this.updateVAOs[1]);
      this.updateVAOs = null;
    }
    if (this.drawVAOs) {
      gl.deleteVertexArray(this.drawVAOs[0]);
      gl.deleteVertexArray(this.drawVAOs[1]);
      this.drawVAOs = null;
    }
  }
}

function createParticleBufferSet(
  gl: WebGL2RenderingContext,
  lonlat: Float32Array,
  age: Float32Array,
  seed: Float32Array
): ParticleBufferSet {
  return {
    lonlat: createBuffer(gl, lonlat),
    age: createBuffer(gl, age),
    seed: createBuffer(gl, seed),
  };
}

function createBuffer(gl: WebGL2RenderingContext, data: Float32Array): WebGLBuffer {
  const buffer = gl.createBuffer()!;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_COPY);
  return buffer;
}

function createUpdateVAO(
  gl: WebGL2RenderingContext,
  program: WebGLProgram,
  buffers: ParticleBufferSet
): WebGLVertexArrayObject {
  const vao = gl.createVertexArray()!;
  gl.bindVertexArray(vao);
  bindAttribute(gl, program, buffers.lonlat, 'a_lonlat', 2);
  bindAttribute(gl, program, buffers.age, 'a_age', 1);
  bindAttribute(gl, program, buffers.seed, 'a_seed', 1);
  gl.bindVertexArray(null);
  return vao;
}

function createDrawVAO(
  gl: WebGL2RenderingContext,
  program: WebGLProgram,
  buffers: ParticleBufferSet
): WebGLVertexArrayObject {
  const vao = gl.createVertexArray()!;
  gl.bindVertexArray(vao);
  bindAttribute(gl, program, buffers.lonlat, 'a_lonlat', 2);
  bindAttribute(gl, program, buffers.age, 'a_age', 1);
  gl.bindVertexArray(null);
  return vao;
}

function bindAttribute(
  gl: WebGL2RenderingContext,
  program: WebGLProgram,
  buffer: WebGLBuffer,
  name: string,
  size: number
) {
  const location = gl.getAttribLocation(program, name);
  if (location < 0) return; // attribute unused/optimized out (e.g. a_seed in the draw program)
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.enableVertexAttribArray(location);
  gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
}

function createFullscreenQuad(gl: WebGL2RenderingContext): WebGLBuffer {
  const buffer = gl.createBuffer()!;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
    gl.STATIC_DRAW
  );
  return buffer;
}

function compileShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader compile error: ${info}`);
  }
  return shader;
}

function createProgram(
  gl: WebGL2RenderingContext,
  vsSource: string,
  fsSource: string,
  transformFeedbackVaryings?: string[]
): WebGLProgram {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram()!;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  if (transformFeedbackVaryings) {
    gl.transformFeedbackVaryings(program, transformFeedbackVaryings, gl.SEPARATE_ATTRIBS);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Program link error: ${info}`);
  }
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  return program;
}

async function loadTexture(gl: WebGL2RenderingContext, url: string): Promise<WebGLTexture> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Failed to fetch ${url}: ${response.status}`);
  const blob = await response.blob();
  const bitmap = await createImageBitmap(blob);

  const texture = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  bitmap.close();
  return texture;
}
