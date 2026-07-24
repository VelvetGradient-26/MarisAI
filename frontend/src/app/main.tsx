import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// maplibre-gl v6 ships ESM-only and loads its render worker as a separate
// file. Vite's dev-mode dependency optimizer doesn't resolve that worker
// automatically, which surfaces as: "The file does not exist at
// '.../maplibre-gl-worker.mjs' which is in the optimize deps directory."
// Registering the worker URL explicitly (per MapLibre's own Vite guidance)
// fixes it in both dev and production builds. This must run before any
// `new maplibregl.Map()` call, so it lives here at the entry point rather
// than inside MapManager.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import '../index.css';
import { App } from './App';
import { AppProviders } from './providers';

setWorkerUrl(workerUrl);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>
);
