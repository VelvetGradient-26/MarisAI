import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const MODEL_URL = '/models/atlantic_salmon.glb';

/**
 * School size. Cheap to raise — the whole school draws in one call per
 * material regardless of count (see the merge/instance note below) — but
 * 3D fish read as much heavier than the flat SVG ones this replaced, so
 * this is a visual-density choice rather than a performance ceiling.
 */
const COUNT = 26;

/** World half-width the school swims across before wrapping around. */
const SPAN = 9;

/**
 * The glTF has 47 meshes across 10 materials, and no skin, no baked
 * animation. Drawing it naively would be 47 draw calls per fish; instead
 * every mesh sharing a material is merged into one geometry (with each
 * node's world transform baked in) and drawn as a single InstancedMesh.
 * That is 10 draw calls for the entire school, whatever COUNT is.
 *
 * The tradeoff is that instances share geometry, so no fish can move its
 * fins independently of the others. The swim is therefore carried by each
 * fish's own transform — forward travel, a yaw oscillation that reads as
 * the body fishtailing, plus a slow roll and vertical bob on separate
 * periods so no two fish stay in step.
 */
interface Instanced {
  mesh: THREE.InstancedMesh;
}

interface Swimmer {
  x: number;
  y: number;
  z: number;
  scale: number;
  speed: number;
  /** +1 swims right, -1 swims left (the model's nose points +X). */
  direction: number;
  phase: number;
  wagRate: number;
  wagAmount: number;
  bobRate: number;
  bobAmount: number;
}

/** Deterministic pseudo-random, so the school looks identical on every
 * load rather than reshuffling on each mount. Mirrors the `rnd` helper the
 * rest of the dive scene uses. */
function rnd(i: number, salt: number): number {
  const v = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453;
  return v - Math.floor(v);
}

function buildSwimmers(): Swimmer[] {
  const out: Swimmer[] = [];
  for (let i = 0; i < COUNT; i++) {
    const direction = i % 2 === 0 ? 1 : -1;
    // Stratified rather than purely hashed: a plain hash clumps visibly at
    // this count, leaving bands of empty water. Each fish gets its own slice
    // of the range and is jittered within it, which keeps the school even
    // without looking like a grid.
    const slot = (i + rnd(i, 11)) / COUNT;
    out.push({
      x: (slot * 2 - 1) * SPAN,
      // Golden-ratio stepping spreads successive fish across the full height
      // instead of leaving the top and bottom bands empty.
      y: (((i * 0.618 + rnd(i, 2) * 0.22) % 1) * 2 - 1) * 3.3,
      // Depth spread: nearer fish are larger and faster, which does most of
      // the work of making a flat plane of fish read as a volume.
      z: -1.5 - rnd(i, 3) * 5.5,
      scale: 0.55 + rnd(i, 4) * 0.75,
      speed: 0.55 + rnd(i, 5) * 0.85,
      direction,
      phase: rnd(i, 6) * Math.PI * 2,
      wagRate: 2.2 + rnd(i, 7) * 1.6,
      wagAmount: 0.1 + rnd(i, 8) * 0.12,
      bobRate: 0.5 + rnd(i, 9) * 0.6,
      bobAmount: 0.06 + rnd(i, 10) * 0.12,
    });
  }
  return out;
}

export function SalmonSchool({ opacity }: { opacity: number }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Opacity changes on every scroll frame; holding it in a ref keeps the
  // WebGL scene out of React's render path entirely.
  const opacityRef = useRef(opacity);
  opacityRef.current = opacity;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearAlpha(0);
    container.appendChild(renderer.domElement);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(0, 0, 7);

    // Underwater key/fill: a dim blue ambient with a cooler light from above,
    // so the salmon's back reads darker than its belly the way a real one does
    // under surface light.
    scene.add(new THREE.HemisphereLight(0xbfe4ff, 0x0a2233, 2.1));
    const key = new THREE.DirectionalLight(0xdff1ff, 1.5);
    key.position.set(2, 6, 4);
    scene.add(key);

    const swimmers = buildSwimmers();
    const instanced: Instanced[] = [];
    let frame = 0;
    let disposed = false;
    const dummy = new THREE.Object3D();

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    new GLTFLoader().load(
      MODEL_URL,
      (gltf) => {
        if (disposed) return;

        // Bake every node's world transform into its geometry, then group by
        // material so each material becomes exactly one merged geometry.
        gltf.scene.updateMatrixWorld(true);
        const byMaterial = new Map<THREE.Material, THREE.BufferGeometry[]>();

        gltf.scene.traverse((child) => {
          if (!(child instanceof THREE.Mesh)) return;
          const material = Array.isArray(child.material) ? child.material[0] : child.material;
          const geometry = child.geometry.clone();
          geometry.applyMatrix4(child.matrixWorld);
          // mergeGeometries requires identical attribute sets; UVs are absent
          // on some parts of this model (it is untextured, colour comes from
          // the materials) and would otherwise abort the merge.
          geometry.deleteAttribute('uv');
          geometry.deleteAttribute('uv1');
          const list = byMaterial.get(material);
          if (list) list.push(geometry);
          else byMaterial.set(material, [geometry]);
        });

        for (const [material, geometries] of byMaterial) {
          const merged = mergeGeometries(geometries, false);
          geometries.forEach((g) => g.dispose());
          if (!merged) continue;

          const instancedMaterial = (material as THREE.MeshStandardMaterial).clone();
          instancedMaterial.transparent = true;
          const mesh = new THREE.InstancedMesh(merged, instancedMaterial, COUNT);
          mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
          mesh.frustumCulled = false;
          scene.add(mesh);
          instanced.push({ mesh });
        }

        const applyTransforms = (time: number, delta: number) => {
          for (let i = 0; i < swimmers.length; i++) {
            const s = swimmers[i];

            if (!reducedMotion) {
              // Real elapsed time, not a per-frame constant — otherwise the
              // school swims at double speed on a 120Hz display. Clamped so
              // a backgrounded tab does not teleport every fish on return.
              s.x += s.direction * s.speed * Math.min(delta, 0.05);
              // Wrap around rather than reversing, so a fish never appears to
              // stop and turn at the edge of the viewport.
              if (s.direction > 0 && s.x > SPAN) s.x = -SPAN;
              if (s.direction < 0 && s.x < -SPAN) s.x = SPAN;
            }

            const wag = Math.sin(time * s.wagRate + s.phase) * s.wagAmount;
            const bob = Math.sin(time * s.bobRate + s.phase) * s.bobAmount;

            dummy.position.set(s.x, s.y + bob, s.z);
            dummy.rotation.set(
              // Slight nose-up/down following the bob, so vertical motion
              // looks driven rather than like the fish is being lifted.
              Math.cos(time * s.bobRate + s.phase) * 0.09,
              // Face travel direction, plus the fishtailing yaw.
              (s.direction > 0 ? 0 : Math.PI) + wag,
              Math.sin(time * s.wagRate * 0.5 + s.phase) * 0.07
            );
            dummy.scale.setScalar(s.scale);
            dummy.updateMatrix();

            for (const { mesh } of instanced) mesh.setMatrixAt(i, dummy.matrix);
          }
          for (const { mesh } of instanced) mesh.instanceMatrix.needsUpdate = true;
        };

        const clock = new THREE.Clock();
        // Tracks the last visibility decision so the fade-out teardown runs
        // once on the transition rather than every frame.
        let wasVisible: boolean | null = null;

        // One loop for both motion preferences. Reduced motion freezes time
        // and delta at zero instead of skipping the loop, because the school
        // must still redraw when its scroll-driven opacity changes — drawing
        // a single frame at mount would render it at opacity 0 (the page
        // starts at the surface) and it would never appear at all.
        const tick = () => {
          if (disposed) return;
          frame = requestAnimationFrame(tick);

          const delta = reducedMotion ? 0 : clock.getDelta();
          const time = reducedMotion ? 0 : clock.getElapsedTime();
          const visible = opacityRef.current > 0.01;

          if (visible !== wasVisible) {
            // Skipping render() is not enough to make the school disappear:
            // the canvas keeps compositing whatever was last drawn, so the
            // faded fish stayed frozen on screen after scrolling back up to
            // the surface. Clear the buffer once on the way out, and hide
            // the element so nothing is composited while faded.
            renderer.domElement.style.visibility = visible ? '' : 'hidden';
            if (!visible) renderer.clear();
            wasVisible = visible;
          }

          if (!visible) return;

          applyTransforms(time, delta);
          for (const { mesh } of instanced) {
            (mesh.material as THREE.Material).opacity = opacityRef.current;
          }
          renderer.render(scene, camera);
        };

        tick();
      },
      undefined,
      () => {
        // A missing or corrupt model leaves an empty transparent canvas —
        // the rest of the dive scene (light shafts, bubbles, whales) still
        // reads fine without the school, so this is not worth surfacing.
      }
    );

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      for (const { mesh } of instanced) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
        scene.remove(mesh);
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={containerRef} className="dive-salmon-canvas" aria-hidden="true" />;
}
