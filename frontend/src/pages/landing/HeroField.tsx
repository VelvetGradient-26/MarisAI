import { useEffect, useRef } from 'react';

/**
 * The hero backdrop: a slow, flowing vector field on a 2D canvas.
 *
 * It replaces the illustrated dive scene, and the choice of *what* to draw is
 * deliberate rather than decorative — a vector field is what ocean current
 * data actually looks like, and the map's wind layer already renders one for
 * real. So the hero previews the product's own visual language instead of
 * putting a cartoon in front of it.
 *
 * Strictly 2D: no perspective, no depth sorting, no WebGL. The motion comes
 * from advecting particles through a smooth curl-like field, which is cheap
 * enough to run on the main thread at a few hundred particles.
 *
 * Honest about being decorative: this is a *synthetic* field, not live data,
 * so it carries no labels, no scale and no units. Dressing it up as a reading
 * would be the same failure as the invented statistics it replaced.
 */

interface HeroFieldProps {
  dark: boolean;
}

interface Particle {
  x: number;
  y: number;
  age: number;
  life: number;
  /** Per-particle brightness, so the field has depth instead of one flat tone. */
  weight: number;
}

const PARTICLE_COUNT = 420;
/**
 * How hard each frame veils the previous one — this alone sets trail length.
 * At 0.055 a trail was gone in ~18 frames and read as loose dust; at 0.018 it
 * persists for ~55 frames, which is what makes the field look like flow rather
 * than noise. Lower still and old trails never fully clear, leaving smear.
 */
const TRAIL_FADE = 0.018;

/** Smooth pseudo-noise. Cheap, periodic, and good enough for a background —
 * a real simplex implementation would be ~150 lines for no visible gain. */
function flow(x: number, y: number, t: number): number {
  return (
    Math.sin(x * 1.7 + t * 0.22) * 0.6 +
    Math.cos(y * 2.1 - t * 0.17) * 0.5 +
    Math.sin((x + y) * 1.1 + t * 0.13) * 0.4
  );
}

export function HeroField({ dark }: HeroFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    let width = 0;
    let height = 0;
    let ratio = 1;
    const particles: Particle[] = [];

    const seed = (particle: Particle) => {
      particle.x = Math.random() * width;
      particle.y = Math.random() * height;
      particle.age = 0;
      particle.life = 120 + Math.random() * 240;
      // Skewed toward dim: a few bright filaments over a quiet field reads as
      // depth, whereas uniform brightness reads as static.
      particle.weight = 0.35 + Math.random() ** 2 * 0.65;
    };

    const resize = () => {
      // The container drives the size, not the window: the hero is not
      // full-viewport on every breakpoint.
      const rect = canvas.getBoundingClientRect();
      ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.floor(width * ratio));
      canvas.height = Math.max(1, Math.floor(height * ratio));
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
    };

    resize();
    for (let index = 0; index < PARTICLE_COUNT; index += 1) {
      const particle: Particle = { x: 0, y: 0, age: 0, life: 0, weight: 1 };
      seed(particle);
      particle.age = Math.random() * particle.life;
      particles.push(particle);
    }

    const observer =
      'ResizeObserver' in window ? new ResizeObserver(() => resize()) : undefined;
    observer?.observe(canvas);
    window.addEventListener('resize', resize);

    let frame = 0;
    let time = 0;
    let running = true;

    // A background animation must not burn battery in a hidden tab.
    const onVisibility = () => {
      running = !document.hidden;
      if (running) frame = requestAnimationFrame(draw);
    };
    document.addEventListener('visibilitychange', onVisibility);

    // Two hues so the field has colour depth rather than one flat tint: a cool
    // core with a warmer-cyan highlight on the brightest filaments.
    const core = dark ? '150, 226, 255' : '11, 105, 115';
    const hot = dark ? '196, 245, 255' : '6, 78, 86';
    // Must track --ma-bg-deep. The veil is what the canvas converges to
    // between strokes, so a mismatch here shows up as the hero being a
    // different shade from the section under it — and at 0.018 per frame it
    // accumulates into the dominant colour of the whole hero, not a tint.
    const fade = dark ? 'rgba(0, 1, 3, ' : 'rgba(247, 250, 251, ';

    function draw() {
      if (!running || !context) return;
      time += 0.006;

      // Trail: veil the previous frame rather than clearing it. This must run
      // in source-over even when the strokes are additive, or the veil brightens
      // the canvas instead of dimming it and the whole field washes to white.
      context.globalCompositeOperation = 'source-over';
      context.fillStyle = `${fade}${TRAIL_FADE})`;
      context.fillRect(0, 0, width, height);

      // Additive blending makes overlapping trails bloom where flow converges,
      // which is exactly where a current field is most interesting. Only on
      // dark — on a light background 'lighter' drives everything to white.
      context.globalCompositeOperation = dark ? 'lighter' : 'source-over';
      context.lineCap = 'round';

      for (const particle of particles) {
        const nx = particle.x / Math.max(width, 1);
        const ny = particle.y / Math.max(height, 1);
        const angle = flow(nx * 3, ny * 3, time) * Math.PI;
        const speed = 0.55 + (1 - ny) * 0.5;

        const px = particle.x;
        const py = particle.y;
        particle.x += Math.cos(angle) * speed;
        particle.y += Math.sin(angle) * speed * 0.55;
        particle.age += 1;

        // Fade in and out over the particle's life so nothing pops.
        const t = particle.age / particle.life;
        const envelope = Math.sin(Math.PI * Math.min(t, 1));
        const alpha = envelope * particle.weight * (dark ? 0.85 : 0.62);

        // The brightest tenth get the highlight hue and a wider stroke, so the
        // eye lands on a few filaments instead of an even wash.
        const isHot = particle.weight > 0.9;
        context.strokeStyle = `rgba(${isHot ? hot : core}, ${alpha.toFixed(3)})`;
        context.lineWidth = isHot ? 1.6 : 0.9 + particle.weight * 0.4;

        context.beginPath();
        context.moveTo(px, py);
        context.lineTo(particle.x, particle.y);
        context.stroke();

        if (
          particle.age >= particle.life ||
          particle.x < -20 ||
          particle.x > width + 20 ||
          particle.y < -20 ||
          particle.y > height + 20
        ) {
          seed(particle);
        }
      }

      context.globalCompositeOperation = 'source-over';
      frame = requestAnimationFrame(draw);
    }

    if (reduced) {
      // Reduced motion still gets the field — drawn once, held still. A blank
      // rectangle would read as a failed load.
      context.fillStyle = `${fade}1)`;
      context.fillRect(0, 0, width, height);
      for (let step = 0; step < 260; step += 1) draw();
      running = false;
      cancelAnimationFrame(frame);
    } else {
      frame = requestAnimationFrame(draw);
    }

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [dark]);

  return <canvas ref={canvasRef} className="lp-hero__field" aria-hidden="true" />;
}
