import { createContext, useContext } from 'react';

export interface RouterContextValue {
  pathname: string;
  searchParams: URLSearchParams;
  navigate: (to: string, options?: { replace?: boolean }) => void;
}

export const RouterContext = createContext<RouterContextValue | null>(null);

export function useAppRouter() {
  const context = useContext(RouterContext);
  if (!context) throw new Error('useAppRouter must be used inside AppRouter');
  return context;
}
