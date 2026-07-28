import { useEffect, useRef } from 'react';
import { Compass } from 'lucide-react';
import { Link } from '../app/router';
import { useThemeStore } from '../store/themeStore';
import './landing.css';

const VERTEX_SOURCE = `attribute vec2 a_position;
varying vec2 v_texCoord;
void main() {
  v_texCoord = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}`;

const LIGHT_FRAGMENT_SOURCE = `precision highp float;
varying vec2 v_texCoord;
uniform float u_time;
void main() {
  vec2 uv = v_texCoord;
  float wave1 = sin(uv.x * 4.0 + u_time * 0.5) * 0.1;
  float wave2 = sin(uv.x * 2.5 - u_time * 0.3) * 0.05;
  float wave3 = cos(uv.y * 3.0 + u_time * 0.4) * 0.08;
  vec3 color1 = vec3(0.53, 0.92, 0.90);
  vec3 color2 = vec3(1.0, 1.0, 1.0);
  float mixFactor = clamp(uv.y + wave1 + wave2 + wave3, 0.0, 1.0);
  vec3 finalColor = mix(color1, color2, mixFactor);
  finalColor *= 1.0 - distance(uv, vec2(0.5)) * 0.15;
  gl_FragColor = vec4(finalColor, 1.0);
}`;

const DARK_FRAGMENT_SOURCE = `precision highp float;
uniform float u_time;
varying vec2 v_texCoord;
void main() {
  vec2 uv = v_texCoord;
  float noise = sin(uv.x * 3.0 + u_time * 0.5) * cos(uv.y * 2.0 - u_time * 0.3);
  noise += sin(uv.y * 5.0 + u_time * 0.2) * 0.5;
  vec3 black = vec3(0.05, 0.06, 0.06);
  vec3 deepCyan = vec3(0.0, 0.32, 0.42);
  vec3 deepTealBlack = vec3(0.02, 0.08, 0.10);
  vec3 color = mix(black, deepTealBlack, uv.y + noise * 0.1);
  color = mix(color, deepCyan, (1.0 - uv.y) * 0.5 + noise * 0.2);
  color *= 1.0 - length(uv - 0.5) * 0.7;
  gl_FragColor = vec4(color, 1.0);
}`;

export function LandingPage() {
  const isDark = useThemeStore((s) => s.dark);

  useEffect(() => {
    document.title = 'Maris AI | Marine Intelligence';
  }, []);

  return (
    <div className={`landing-page ${isDark ? 'landing-page--dark' : 'landing-page--light'}`}>
      <ShaderBackground dark={isDark} />
      <div className="landing-page__overlay" aria-hidden="true" />

      <main className="landing-hero">
        <div className="landing-hero__content">
          <div className="landing-badge landing-fade landing-fade--one">
            <span aria-hidden="true" />
            Deep-Sea Intelligence Engine
          </div>

          <h1 className="landing-fade landing-fade--two">
            AI-powered marine intelligence for the world's oceans
          </h1>

          <p className="landing-fade landing-fade--three">
            Maris AI combines live marine forecasts, atmospheric observations, satellite mapping,
            and geospatial context in one interactive platform.
          </p>

          <div className="landing-hero__actions landing-fade landing-fade--four">
            <Link className="landing-action landing-action--primary" to="/map">
              Launch project
              <Compass size={17} />
            </Link>
          </div>
        </div>
      </main>

      <footer className="landing-footer">
        <div>
          <strong>Maris AI</strong>
          <span>© 2026 Maris AI. Subsurface precision analytics.</span>
        </div>
        <div className="landing-footer__links">
          <Link to="/contact">Contact</Link>
          <Link to="/feedback">Feedback</Link>
          <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">
            API Docs
          </a>
        </div>
      </footer>
    </div>
  );
}

function ShaderBackground({ dark }: { dark: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl');
    if (!gl) return;

    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vertexShader = compile(gl.VERTEX_SHADER, VERTEX_SOURCE);
    const fragmentShader = compile(
      gl.FRAGMENT_SHADER,
      dark ? DARK_FRAGMENT_SOURCE : LIGHT_FRAGMENT_SOURCE
    );
    if (!vertexShader || !fragmentShader) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    );
    const positionLocation = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
    const timeLocation = gl.getUniformLocation(program, 'u_time');

    const syncSize = () => {
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.round(canvas.clientWidth * pixelRatio);
      const height = Math.round(canvas.clientHeight * pixelRatio);
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
    };

    const resizeObserver = new ResizeObserver(syncSize);
    resizeObserver.observe(canvas);
    syncSize();

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let animationFrame = 0;
    const render = (time: number) => {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform1f(timeLocation, time * 0.001);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (!reduceMotion) animationFrame = requestAnimationFrame(render);
    };
    render(0);

    return () => {
      cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vertexShader);
      gl.deleteShader(fragmentShader);
    };
  }, [dark]);

  return <canvas ref={canvasRef} className="landing-shader" aria-hidden="true" />;
}
