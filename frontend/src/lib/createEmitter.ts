/**
 * Minimal typed pub-sub. Managers (MapManager, BasemapManager, LayerManager)
 * use this instead of importing Zustand directly, so they stay plain,
 * framework-agnostic classes that are usable and testable outside React.
 * The React-facing hook (useMapManager) is the only place that bridges
 * manager events into the Zustand store.
 */
export function createEmitter<T>() {
  const listeners = new Set<(value: T) => void>();

  return {
    emit(value: T) {
      listeners.forEach((listener) => listener(value));
    },
    subscribe(listener: (value: T) => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    clear() {
      listeners.clear();
    },
  };
}
