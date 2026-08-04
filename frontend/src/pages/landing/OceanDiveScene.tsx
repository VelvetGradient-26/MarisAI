import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { rafThrottle } from '../../utils/rafThrottle';

/**
 * Ported from the Claude Design prototype "Maris AI Landing.dc.html" — a
 * scroll-driven dive: bright sunlit surface at the top, fading through
 * light shafts, a fish school, whales, and a bioluminescent abyssal zone as
 * `depth` (0..1, derived from scroll position) increases. The prototype's
 * `class Component extends DCLogic` scroll math is ported near-verbatim
 * below (rnd/clamp01/band/lerp/depthColor/zoneFor); its `sc-for`/`sc-if`
 * template becomes plain `.map()`/`&&`.
 */

const FISH_COUNT = 50;
const CREATURE_SPEED = 1.1;
const CLOUD_SPEED = 1;
const SUN_INTENSITY = 1.6;
const BIOLUM_INTENSITY = 1.6;
const MAX_DEPTH_M = 4000;

type SwimAnim = 'swimR' | 'swimL';

interface CloudItem {
  key: string;
  top: number;
  w: number;
  h: number;
  dur: number;
  delay: number;
  op: number;
  blur: number;
}

interface BirdItem {
  key: string;
  top: number;
  scale: number;
  dur: number;
  delay: number;
  flap: number;
  anim: SwimAnim;
  color: string;
}

interface FishItem {
  key: string;
  top: number;
  dur: number;
  delay: number;
  scale: number;
  wag: number;
  anim: SwimAnim;
  fill: string;
  fin: string;
}

interface BubbleItem {
  key: string;
  left: number;
  size: number;
  dur: number;
  delay: number;
}

interface JellyItem {
  key: string;
  top: number;
  left: number;
  scale: number;
  dur: number;
  sway: number;
  delay: string;
  bell: string;
  glow: string;
}

interface PlanktonItem {
  key: string;
  top: number;
  left: number;
  size: number;
  glow: number;
  color: string;
  dur: number;
  delay: number;
}

interface WhaleItem {
  key: string;
  top: number;
  dur: number;
  delay: string;
  scale: number;
  bob: number;
  wag: number;
  anim: SwimAnim;
  body: string;
  dark: string;
}

const WHALES: WhaleItem[] = [
  {
    key: 'w0',
    top: 46,
    dur: 72 / CREATURE_SPEED,
    delay: '-10s',
    scale: 1.05,
    bob: 14 / CREATURE_SPEED,
    wag: 6.5 / CREATURE_SPEED,
    anim: 'swimR',
    body: 'rgba(58,92,116,0.95)',
    dark: 'rgba(38,66,86,0.95)',
  },
  {
    key: 'w1',
    top: 14,
    dur: 98 / CREATURE_SPEED,
    delay: '-46s',
    scale: 0.6,
    bob: 18 / CREATURE_SPEED,
    wag: 8.2 / CREATURE_SPEED,
    anim: 'swimL',
    body: 'rgba(46,74,96,0.8)',
    dark: 'rgba(30,54,72,0.8)',
  },
];

/** Seeded pseudo-random in [0, 1) — same trig-hash trick as the prototype, so
 * the creature layout is stable across renders without storing random state. */
function rnd(i: number, salt: number): number {
  const x = Math.sin((i + 1) * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

/** Smooth 0..1 ramp up over [inA, inB], flat, then ramp down over an
 * unrelated [outA, outB] window — used to fade layers in and back out across
 * depth (e.g. the fish school appears then the whale layer takes over). */
function band(d: number, inA: number, inB: number, outA: number, outB: number): number {
  return clamp01((d - inA) / (inB - inA)) * clamp01((outB - d) / (outB - outA));
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

type DepthStop = [number, number, number, number];

// Dark theme: sea-surface blue down to a near-black abyss, matching the
// prototype's original stops.
const DEPTH_STOPS_DARK: DepthStop[] = [
  [0, 56, 122, 150],
  [0.18, 26, 70, 94],
  [0.4, 14, 38, 58],
  [0.65, 8, 22, 38],
  [0.85, 4, 12, 22],
  [1, 2, 6, 12],
];

// Light theme: same shape/spacing, but the abyss floor stays a teal-charcoal
// rather than near-black, so it reads as "light mode" throughout the dive
// and against the light-mode chrome's teal accent (#0f766e).
const DEPTH_STOPS_LIGHT: DepthStop[] = [
  [0, 224, 240, 240],
  [0.18, 170, 205, 210],
  [0.4, 110, 156, 166],
  [0.65, 66, 108, 118],
  [0.85, 40, 76, 86],
  [1, 24, 54, 64],
];

function depthColor(depth: number, dark: boolean): string {
  const stops = dark ? DEPTH_STOPS_DARK : DEPTH_STOPS_LIGHT;
  for (let i = 0; i < stops.length - 1; i++) {
    const [p0, r0, g0, b0] = stops[i];
    const [p1, r1, g1, b1] = stops[i + 1];
    if (depth >= p0 && depth <= p1) {
      const t = (depth - p0) / (p1 - p0);
      return `rgb(${Math.round(lerp(r0, r1, t))}, ${Math.round(lerp(g0, g1, t))}, ${Math.round(lerp(b0, b1, t))})`;
    }
  }
  return dark ? 'rgb(2,6,12)' : 'rgb(24,54,64)';
}

function zoneFor(d: number): string {
  if (d < 0.2) return 'Sunlight zone';
  if (d < 0.45) return 'Twilight zone';
  if (d < 0.75) return 'Midnight zone';
  return 'Abyssal zone';
}

function buildFish(count: number, speed: number): FishItem[] {
  const skins = [
    { fill: 'rgba(150,204,222,0.82)', fin: 'rgba(120,180,205,0.6)' },
    { fill: 'rgba(122,186,208,0.78)', fin: 'rgba(96,158,186,0.58)' },
    { fill: 'rgba(196,222,230,0.8)', fin: 'rgba(160,198,212,0.55)' },
    { fill: 'rgba(108,166,196,0.72)', fin: 'rgba(84,140,172,0.55)' },
    { fill: 'rgba(214,196,152,0.6)', fin: 'rgba(184,164,122,0.5)' },
  ];
  const out: FishItem[] = [];
  for (let i = 0; i < count; i++) {
    const a = rnd(i, 1);
    const b = rnd(i, 2);
    const c = rnd(i, 3);
    const d = rnd(i, 4);
    const right = i % 2 === 0;
    const skin = skins[i % skins.length];
    out.push({
      key: `f${i}`,
      top: 6 + a * 80,
      dur: (17 + b * 26) / speed,
      delay: -d * 40,
      scale: 0.3 + c * 0.85,
      wag: 1.1 + b * 1.1,
      anim: right ? 'swimR' : 'swimL',
      fill: skin.fill,
      fin: skin.fin,
    });
  }
  return out;
}

function buildBubbles(speed: number): BubbleItem[] {
  const out: BubbleItem[] = [];
  for (let i = 0; i < 16; i++) {
    out.push({
      key: `b${i}`,
      left: 2 + rnd(i, 7) * 96,
      size: 3 + rnd(i, 8) * 8,
      dur: (11 + rnd(i, 9) * 13) / speed,
      delay: -rnd(i, 10) * 24,
    });
  }
  return out;
}

function buildClouds(cloudSpeed: number): CloudItem[] {
  const out: CloudItem[] = [];
  for (let i = 0; i < 6; i++) {
    const a = rnd(i, 21);
    const b = rnd(i, 22);
    const c = rnd(i, 23);
    const w = 200 + b * 300;
    out.push({
      key: `c${i}`,
      top: 3 + a * 34,
      w,
      h: (w * 130) / 360,
      dur: (130 + c * 130) / cloudSpeed,
      delay: -c * 220,
      op: 0.5 + b * 0.45,
      blur: 1 + (1 - b) * 3,
    });
  }
  return out;
}

function buildBirds(cloudSpeed: number): BirdItem[] {
  const out: BirdItem[] = [];
  for (let i = 0; i < 7; i++) {
    const a = rnd(i, 31);
    const b = rnd(i, 32);
    const c = rnd(i, 33);
    const right = i % 3 !== 1;
    out.push({
      key: `bd${i}`,
      top: 8 + a * 30,
      scale: 0.4 + b * 0.7,
      dur: (26 + c * 30) / cloudSpeed,
      delay: -c * 46,
      flap: 0.5 + b * 0.5,
      anim: right ? 'swimR' : 'swimL',
      color: b > 0.55 ? 'rgba(16,44,62,0.75)' : 'rgba(24,58,80,0.55)',
    });
  }
  return out;
}

function buildJellies(speed: number): JellyItem[] {
  const jellyGlow = ['rgba(120,255,220,0.95)', 'rgba(130,220,255,0.9)', 'rgba(180,200,255,0.85)'];
  return [
    {
      key: 'j0',
      top: 12,
      left: 12,
      scale: 0.85,
      dur: 13 / speed,
      sway: 5.2 / speed,
      delay: '-2s',
      bell: 'rgba(180,255,235,0.55)',
      glow: jellyGlow[0],
    },
    {
      key: 'j1',
      top: 44,
      left: 74,
      scale: 1.15,
      dur: 17 / speed,
      sway: 6.4 / speed,
      delay: '-7s',
      bell: 'rgba(170,230,255,0.5)',
      glow: jellyGlow[1],
    },
    {
      key: 'j2',
      top: 62,
      left: 34,
      scale: 0.6,
      dur: 11 / speed,
      sway: 4.6 / speed,
      delay: '-4s',
      bell: 'rgba(200,215,255,0.45)',
      glow: jellyGlow[2],
    },
  ];
}

function buildPlankton(): PlanktonItem[] {
  const out: PlanktonItem[] = [];
  for (let i = 0; i < 14; i++) {
    const g = rnd(i, 11);
    out.push({
      key: `p${i}`,
      top: 5 + rnd(i, 12) * 90,
      left: 3 + rnd(i, 13) * 94,
      size: 3 + g * 5,
      glow: 8 + g * 12,
      color:
        i % 3 === 0
          ? 'rgba(140,255,215,0.95)'
          : i % 3 === 1
            ? 'rgba(140,225,255,0.9)'
            : 'rgba(190,205,255,0.85)',
      dur: 2.8 + rnd(i, 14) * 2.6,
      delay: -rnd(i, 15) * 4,
    });
  }
  return out;
}

export function OceanDiveScene({ dark }: { dark: boolean }) {
  const [depth, setDepth] = useState(0);
  const reducedMotion = useMemo(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    []
  );

  useEffect(() => {
    if (reducedMotion) return;

    const onScroll = rafThrottle(() => {
      const max = document.body.scrollHeight - window.innerHeight;
      setDepth(max > 0 ? clamp01(window.scrollY / max) : 0);
    });
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, [reducedMotion]);

  const fish = useMemo(() => buildFish(FISH_COUNT, CREATURE_SPEED), []);
  const bubbles = useMemo(() => buildBubbles(CREATURE_SPEED), []);
  const clouds = useMemo(() => buildClouds(CLOUD_SPEED), []);
  const birds = useMemo(() => buildBirds(CLOUD_SPEED), []);
  const jellies = useMemo(() => buildJellies(CREATURE_SPEED), []);
  const plankton = useMemo(() => buildPlankton(), []);
  const anglerDur = 110 / CREATURE_SPEED;

  const bgColor = depthColor(depth, dark);
  const skyOpacity = clamp01(1 - depth / 0.085);
  const gaugeScrim = 0.45 + clamp01(1 - depth / 0.12) * 0.45;
  const sunGlow = Math.min(1, 0.62 * SUN_INTENSITY);
  const shaftOpacity = band(depth, 0.05, 0.16, 0.34, 0.5) * SUN_INTENSITY;
  const bubbleOpacity = band(depth, 0.04, 0.18, 0.68, 0.82);
  const fishOpacity = band(depth, 0.05, 0.16, 0.74, 0.88);
  const whaleOpacity = band(depth, 0.4, 0.52, 0.88, 0.97);
  const biolumOpacity = clamp01((depth - 0.6) / 0.18) * BIOLUM_INTENSITY;
  const depthMeters = Math.round(depth * MAX_DEPTH_M).toLocaleString() + ' m';
  const depthZone = zoneFor(depth);
  const gaugeFill = `${(depth * 100).toFixed(1)}%`;

  return (
    <>
      <div
        className="dive-layer"
        style={{ zIndex: 0, background: bgColor, transition: 'background 0.15s linear' }}
      />

      <div className="dive-layer" style={{ zIndex: 1, opacity: skyOpacity }}>
        <div className="dive-sky-gradient" />

        <div className="dive-sun" style={{ opacity: sunGlow }}>
          <div className="dive-sun__rays">
            <svg viewBox="0 0 540 540" className="dive-sun__rays-svg">
              <g fill="rgba(255,250,225,0.85)">
                <path d="M270,0 L282,240 L258,240 Z" />
                <path d="M540,270 L300,282 L300,258 Z" />
                <path d="M270,540 L258,300 L282,300 Z" />
                <path d="M0,270 L240,258 L240,282 Z" />
                <path d="M461,79 L292,251 L275,234 Z" />
                <path d="M461,461 L289,292 L306,275 Z" />
                <path d="M79,461 L248,289 L265,306 Z" />
                <path d="M79,79 L251,248 L234,265 Z" />
              </g>
            </svg>
          </div>
          <div className="dive-sun__glow" />
        </div>

        {clouds.map((c) => (
          <div
            key={c.key}
            className="dive-cloud"
            style={{ top: `${c.top}%`, animationDuration: `${c.dur}s`, animationDelay: `${c.delay}s` }}
          >
            <svg width={c.w} height={c.h} viewBox="0 0 360 130" style={{ display: 'block', opacity: c.op, filter: `blur(${c.blur}px)` }}>
              <g fill="#ffffff">
                <ellipse cx="96" cy="84" rx="72" ry="32" />
                <ellipse cx="158" cy="62" rx="60" ry="42" />
                <ellipse cx="222" cy="76" rx="66" ry="33" />
                <ellipse cx="276" cy="90" rx="50" ry="24" />
                <rect x="34" y="80" width="256" height="28" rx="14" />
              </g>
              <g fill="rgba(196,224,244,0.55)">
                <rect x="46" y="98" width="232" height="12" rx="6" />
              </g>
            </svg>
          </div>
        ))}

        {birds.map((b) => (
          <div
            key={b.key}
            className="dive-bird"
            style={{
              top: `${b.top}%`,
              animationName: b.anim,
              animationDuration: `${b.dur}s`,
              animationDelay: `${b.delay}s`,
            }}
          >
            <div style={{ transform: `scale(${b.scale})`, transformOrigin: 'center' }}>
              <svg width="52" height="20" viewBox="0 0 52 20" style={{ display: 'block', overflow: 'visible' }}>
                <g fill={b.color}>
                  <ellipse cx="26" cy="11" rx="5.4" ry="2.3" />
                  <g style={{ animation: `wingFlap ${b.flap}s ease-in-out infinite`, transformOrigin: '50% 55%' }}>
                    <path d="M25,10 C19,3 10,0 2,2 C9,5 17,8 25,12 Z" />
                    <path d="M27,10 C33,3 42,0 50,2 C43,5 35,8 27,12 Z" />
                  </g>
                </g>
              </svg>
            </div>
          </div>
        ))}

        <div className="dive-sky-horizon" />
      </div>

      <div className="dive-layer" style={{ zIndex: 1, opacity: shaftOpacity }}>
        {[
          { left: '30%', width: 150, sk: -14, dur: 11, delay: 0 },
          { left: '44%', width: 220, sk: -4, dur: 8.5, delay: 0.7 },
          { left: '58%', width: 130, sk: 9, dur: 13, delay: 1.4 },
          { left: '70%', width: 90, sk: 18, dur: 10, delay: 2.1 },
          { left: '18%', width: 80, sk: -22, dur: 12.5, delay: 1 },
        ].map((s, i) => (
          <div
            key={i}
            className="dive-shaft"
            style={
              {
                left: s.left,
                width: s.width,
                '--sk': `${s.sk}deg`,
                transform: `skewX(${s.sk}deg)`,
                animationDuration: `${s.dur}s`,
                animationDelay: `${s.delay}s`,
              } as CSSProperties
            }
          />
        ))}
      </div>

      {bubbles.length > 0 && (
        <div className="dive-layer" style={{ zIndex: 1, opacity: bubbleOpacity }}>
          {bubbles.map((b) => (
            <div
              key={b.key}
              className="dive-bubble"
              style={{
                left: `${b.left}%`,
                width: b.size,
                height: b.size,
                animationDuration: `${b.dur}s`,
                animationDelay: `${b.delay}s`,
              }}
            />
          ))}
        </div>
      )}

      <div className="dive-layer" style={{ zIndex: 1, opacity: fishOpacity }}>
        {fish.map((f) => (
          <div key={f.key} className="dive-fish-lane" style={{ top: `${f.top}%` }}>
            <div
              style={{
                animationName: f.anim,
                animationDuration: `${f.dur}s`,
                animationTimingFunction: 'linear',
                animationIterationCount: 'infinite',
                animationDelay: `${f.delay}s`,
              }}
            >
              <div style={{ transform: `scale(${f.scale})`, transformOrigin: 'center' }}>
                <FishSvg fill={f.fill} fin={f.fin} wag={f.wag} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="dive-layer" style={{ zIndex: 1, opacity: whaleOpacity }}>
        {WHALES.map((w) => (
          <div key={w.key} className="dive-fish-lane" style={{ top: `${w.top}%` }}>
            <div
              style={{
                animationName: w.anim,
                animationDuration: `${w.dur}s`,
                animationTimingFunction: 'linear',
                animationIterationCount: 'infinite',
                animationDelay: w.delay,
              }}
            >
              <div style={{ transform: `scale(${w.scale})`, transformOrigin: 'center' }}>
                <div style={{ animation: `hover3 ${w.bob}s ease-in-out infinite` }}>
                  <WhaleSvg body={w.body} dark={w.dark} wag={w.wag} />
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="dive-layer" style={{ zIndex: 1, opacity: biolumOpacity }}>
        {jellies.map((j) => (
          <div
            key={j.key}
            style={{
              position: 'absolute',
              top: `${j.top}%`,
              left: `${j.left}%`,
              animation: `hover3 ${j.dur}s ease-in-out infinite`,
              animationDelay: j.delay,
            }}
          >
            <div
              style={{
                transform: `scale(${j.scale})`,
                transformOrigin: 'top center',
                filter: `drop-shadow(0 0 14px ${j.glow})`,
              }}
            >
              <JellySvg bell={j.bell} glow={j.glow} sway={j.sway} />
            </div>
          </div>
        ))}

        <div className="dive-angler" style={{ animationDuration: `${anglerDur}s`, animationDelay: '-22s' }}>
          <div style={{ transform: 'scale(1.05)', filter: 'drop-shadow(0 0 10px rgba(80,240,200,0.35))' }}>
            <AnglerfishSvg />
          </div>
        </div>

        {plankton.map((p) => (
          <div
            key={p.key}
            className="dive-plankton"
            style={{
              top: `${p.top}%`,
              left: `${p.left}%`,
              width: p.size,
              height: p.size,
              background: p.color,
              boxShadow: `0 0 ${p.glow}px ${p.color}`,
              animationDuration: `${p.dur}s`,
              animationDelay: `${p.delay}s`,
            }}
          />
        ))}
      </div>

      <div className={`dive-gauge ${dark ? '' : 'dive-gauge--light'}`} aria-hidden="true">
        <div
          className="dive-gauge__readout"
          style={{
            textShadow: dark
              ? `0 1px 6px rgba(4,20,30,${gaugeScrim}), 0 0 18px rgba(4,20,30,${gaugeScrim})`
              : `0 1px 6px rgba(255,255,255,${gaugeScrim}), 0 0 18px rgba(255,255,255,${gaugeScrim})`,
          }}
        >
          <div className="dive-gauge__meters">{depthMeters}</div>
          <div className="dive-gauge__zone">{depthZone}</div>
        </div>
        <div className="dive-gauge__track">
          <div className="dive-gauge__fill" style={{ height: gaugeFill }} />
        </div>
      </div>
    </>
  );
}

function FishSvg({ fill, fin, wag }: { fill: string; fin: string; wag: number }) {
  return (
    <svg
      width="130"
      height="62"
      viewBox="0 0 130 62"
      style={{
        display: 'block',
        overflow: 'visible',
        animation: `tailWag ${wag}s ease-in-out infinite`,
        transformOrigin: '80% 50%',
      }}
    >
      <path d="M28,31 C18,21 10,12 3,3 C10,15 14,24 17,31 C14,38 10,47 3,59 C10,50 18,41 28,31 Z" fill={fin} />
      <path d="M99,14 C89,3 74,-2 57,1 C69,5 80,9 89,15 Z" fill={fin} />
      <path d="M86,50 C78,58 67,62 55,60 C65,57 73,54 79,49 Z" fill={fin} />
      <path
        d="M28,31 C40,16 60,8 82,8 C104,8 120,17 126,31 C120,45 104,54 82,54 C60,54 40,46 28,31 Z"
        fill={fill}
      />
      <path
        d="M28,31 C40,20 60,13 82,13 C104,13 120,20 126,31 C112,26 104,22 82,22 C60,22 40,26 28,31 Z"
        fill="rgba(255,255,255,0.15)"
      />
      <path d="M101,37 C95,47 85,53 74,53 C84,47 92,42 96,36 Z" fill={fin} />
      <path
        d="M44,32 C64,29 88,29 108,31"
        fill="none"
        stroke="rgba(255,255,255,0.26)"
        strokeWidth="1.2"
        strokeDasharray="5 6"
      />
      <path d="M107,16 C101,23 101,39 107,46" fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="1.3" />
      <path
        d="M126,31 C123,33.5 121,34.5 118,34.5"
        fill="none"
        stroke="rgba(10,25,35,0.55)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="114" cy="25" r="3.1" fill="rgba(8,20,30,0.85)" />
      <circle cx="115.2" cy="23.8" r="1.05" fill="rgba(255,255,255,0.85)" />
    </svg>
  );
}

function WhaleSvg({ body, dark, wag }: { body: string; dark: string; wag: number }) {
  return (
    <svg width="300" height="122" viewBox="0 0 300 122" style={{ display: 'block', overflow: 'visible' }}>
      <g style={{ animation: `flukeWag ${wag}s ease-in-out infinite`, transformOrigin: '22% 52%' }}>
        <path
          d="M58,62 C44,52 30,38 14,20 C26,38 34,50 40,62 C34,74 26,86 14,104 C30,86 44,72 58,62 Z"
          fill={dark}
        />
      </g>
      <path d="M120,24 C132,13 149,11 159,15 C145,17 131,20 120,24 Z" fill={dark} />
      <path d="M150,46 C160,31 176,22 191,20 C175,31 161,40 153,49 Z" fill={dark} opacity="0.65" />
      <path
        d="M58,62 C72,31 122,16 176,18 C226,20 270,35 290,60 C272,83 230,99 177,100 C122,101 72,92 58,62 Z"
        fill={body}
      />
      <path
        d="M64,56 C86,33 128,21 176,22 C224,23 264,36 286,56 C260,42 220,32 176,32 C128,32 88,42 64,56 Z"
        fill="rgba(255,255,255,0.13)"
      />
      <path d="M290,60 C266,76 226,88 182,90 C214,96 258,88 290,60 Z" fill="rgba(245,250,252,0.75)" />
      <path
        d="M286,64 C258,79 220,89 184,91"
        fill="none"
        stroke="rgba(10,25,35,0.35)"
        strokeWidth="1.6"
      />
      <g stroke="rgba(10,25,35,0.22)" strokeWidth="1.3" fill="none">
        <path d="M228,80 C226,86 226,90 229,95" />
        <path d="M242,78 C240,84 240,89 243,94" />
        <path d="M256,74 C254,80 254,85 257,90" />
        <path d="M270,69 C268,75 268,79 271,84" />
      </g>
      <path d="M168,88 C186,106 216,118 240,118 C218,105 194,94 180,84 Z" fill={body} />
      <path
        d="M170,90 C188,106 214,116 236,117 C216,106 194,96 180,87 Z"
        fill="rgba(245,250,252,0.55)"
      />
      <ellipse cx="214" cy="21" rx="5" ry="2.4" fill="rgba(10,25,35,0.5)" />
      <circle cx="268" cy="55" r="3.6" fill="rgba(8,20,30,0.9)" />
      <circle cx="269.4" cy="53.6" r="1.2" fill="rgba(255,255,255,0.8)" />
    </svg>
  );
}

function JellySvg({ bell, glow, sway }: { bell: string; glow: string; sway: number }) {
  return (
    <svg width="120" height="205" viewBox="0 0 120 205" style={{ display: 'block', overflow: 'visible' }}>
      <path
        d="M14,70 C14,32 40,8 60,8 C80,8 106,32 106,70 C96,62 88,74 76,68 C66,76 54,76 44,68 C32,74 24,62 14,70 Z"
        fill={bell}
        opacity="0.42"
      />
      <path
        d="M28,66 C28,40 44,20 60,20 C76,20 92,40 92,66 C84,60 78,68 70,64 C64,70 56,70 50,64 C42,68 36,60 28,66 Z"
        fill={glow}
        opacity="0.3"
      />
      <path
        d="M14,70 C14,32 40,8 60,8 C80,8 106,32 106,70"
        fill="none"
        stroke={glow}
        strokeWidth="1.6"
        opacity="0.85"
      />
      <g stroke={glow} strokeWidth="1.1" fill="none" opacity="0.5">
        <path d="M36,60 C38,40 46,24 58,14" />
        <path d="M60,64 C60,44 60,26 60,14" />
        <path d="M84,60 C82,40 74,24 62,14" />
      </g>
      <g style={{ animation: `tentacleSway ${sway}s ease-in-out infinite`, transformOrigin: '50% 0%' }}>
        <g stroke={glow} strokeWidth="3" strokeLinecap="round" fill="none" opacity="0.75">
          <path d="M46,70 C42,96 52,118 44,142 C40,156 48,168 42,182" />
          <path d="M60,70 C58,98 66,120 58,146 C54,160 62,172 56,190" />
          <path d="M74,70 C72,96 80,116 72,140 C68,154 76,166 70,180" />
        </g>
        <g stroke={glow} strokeWidth="1" strokeLinecap="round" fill="none" opacity="0.4">
          <path d="M32,68 C28,92 36,110 30,132" />
          <path d="M40,70 C36,98 44,116 38,140" />
          <path d="M52,70 C50,100 56,124 50,152" />
          <path d="M68,70 C66,100 72,122 66,150" />
          <path d="M82,68 C80,94 86,112 80,136" />
          <path d="M90,66 C88,88 94,104 88,126" />
        </g>
      </g>
    </svg>
  );
}

function AnglerfishSvg() {
  return (
    <svg width="200" height="140" viewBox="0 0 200 140" style={{ display: 'block', overflow: 'visible' }}>
      <path d="M60,72 L26,44 C36,58 41,65 46,72 C41,79 36,88 26,102 Z" fill="rgba(12,32,44,0.95)" />
      <path d="M92,30 C98,17 110,12 120,15 C110,19 100,24 92,30 Z" fill="rgba(12,32,44,0.95)" />
      <path d="M118,96 C126,110 138,116 146,114 C136,106 126,100 120,92 Z" fill="rgba(12,32,44,0.95)" />
      <path
        d="M60,72 C62,42 84,26 112,26 C143,26 168,45 174,70 C168,96 143,112 112,110 C84,108 62,100 60,72 Z"
        fill="rgba(16,40,54,0.97)"
      />
      <path
        d="M64,66 C70,44 88,32 112,32 C140,32 162,48 170,66 C158,50 138,40 112,40 C88,40 72,50 64,66 Z"
        fill="rgba(120,220,215,0.1)"
      />
      <path
        d="M174,70 C160,83 142,90 122,90"
        fill="none"
        stroke="rgba(140,235,220,0.55)"
        strokeWidth="1.6"
      />
      <g fill="rgba(230,255,250,0.85)">
        <path d="M168,76 L166,86 L172,78 Z" />
        <path d="M158,82 L156,92 L162,84 Z" />
        <path d="M148,86 L146,95 L152,87 Z" />
        <path d="M136,88 L134,96 L140,89 Z" />
        <path d="M126,89 L125,96 L130,90 Z" />
      </g>
      <g fill="none" stroke="rgba(140,235,220,0.35)" strokeWidth="1.1">
        <path d="M96,44 C104,42 116,42 126,45" />
        <path d="M92,58 C104,55 120,55 134,58" />
      </g>
      <path
        d="M114,28 C108,8 132,0 150,8"
        fill="none"
        stroke="rgba(190,250,240,0.7)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <circle cx="153" cy="10" r="8" fill="rgba(150,255,225,0.35)" style={{ animation: 'lureGlow 3.2s ease-in-out infinite' }} />
      <circle cx="153" cy="10" r="4" fill="rgba(225,255,245,0.95)" style={{ animation: 'lureGlow 3.2s ease-in-out infinite' }} />
      <circle cx="150" cy="56" r="3.6" fill="rgba(220,255,248,0.9)" />
      <circle cx="151" cy="55" r="1.3" fill="rgba(10,30,40,0.9)" />
    </svg>
  );
}
