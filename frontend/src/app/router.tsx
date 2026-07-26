import { useEffect, useState } from 'react';
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from 'react';
import { RouterContext, useAppRouter } from './routerContext';

export function AppRouter({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation);

  useEffect(() => {
    const handlePopState = () => setLocation(readLocation());
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (to: string, options?: { replace?: boolean }) => {
    const url = new URL(to, window.location.origin);
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (options?.replace) window.history.replaceState(null, '', next);
    else window.history.pushState(null, '', next);
    setLocation(readLocation());
    window.scrollTo({ top: 0, behavior: 'auto' });
  };

  return (
    <RouterContext.Provider
      value={{
        pathname: location.pathname,
        searchParams: new URLSearchParams(location.search),
        navigate,
      }}
    >
      {children}
    </RouterContext.Provider>
  );
}

export function Link({
  to,
  onClick,
  ...props
}: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { to: string }) {
  const { navigate } = useAppRouter();

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (props.target && props.target !== '_self')
    ) {
      return;
    }

    event.preventDefault();
    navigate(to);
  };

  return <a {...props} href={to} onClick={handleClick} />;
}

function readLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}
