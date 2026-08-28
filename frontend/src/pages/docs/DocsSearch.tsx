import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Search, X } from 'lucide-react';

import { useAppRouter } from '../../app/routerContext';
import { searchChapters } from './chapters/searchIndex';
import type { SearchResult } from './chapters/searchIndex';

/**
 * Full-text search over every chapter, not just titles — the index is built
 * by evaluating the same components the page renders (see
 * `chapters/searchIndex.tsx`), so a search only goes stale when a chapter's
 * own content does.
 *
 * Results render inline, in normal document flow, rather than as an
 * absolutely-positioned dropdown: the desktop nav (`.docs-nav`) is a sticky,
 * `overflow-y: auto` sidebar, and an absolutely-positioned child is clipped
 * by that overflow the moment it would extend past the sidebar's own edge —
 * exactly the case a results list needs to handle. Rendered in flow, the
 * results simply push the rest of the sidebar down and the sidebar's own
 * scroll takes care of the rest.
 *
 * Used twice — once in the desktop sidebar, once above the mobile chapter
 * `<select>` — each instance owns its own query, deliberately: they are never
 * visible at the same time (one is `display: none` per the responsive
 * breakpoint), so there is nothing to keep in sync between them.
 */
export function DocsSearch() {
  const { navigate } = useAppRouter();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const statusId = useId();

  const results = searchChapters(query);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  function go(result: SearchResult) {
    navigate(`/docs?c=${result.chapter.id}`);
    setQuery('');
    inputRef.current?.blur();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      if (query) {
        event.preventDefault();
        setQuery('');
      } else {
        inputRef.current?.blur();
      }
      return;
    }
    if (results.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => (index - 1 + results.length) % results.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      go(results[activeIndex]);
    }
  }

  const showResults = query.trim().length > 0;

  return (
    <div className="docs-search">
      <div className="docs-search__field">
        <Search size={14} className="docs-search__icon" aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          className="docs-search__input"
          placeholder="Search documentation…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Search documentation"
          aria-describedby={showResults ? statusId : undefined}
          autoComplete="off"
        />
        {query && (
          <button
            type="button"
            className="docs-search__clear"
            aria-label="Clear search"
            onClick={() => {
              setQuery('');
              inputRef.current?.focus();
            }}
          >
            <X size={13} />
          </button>
        )}
      </div>

      {showResults && (
        <div className="docs-search__results">
          <p id={statusId} className="visually-hidden" aria-live="polite">
            {results.length === 0
              ? `No chapters match "${query}"`
              : `${results.length} chapter${results.length === 1 ? '' : 's'} match "${query}"`}
          </p>
          {results.length === 0 ? (
            <p className="docs-search__empty">No chapters match "{query}"</p>
          ) : (
            <ul className="docs-search__list">
              {results.map((result, index) => (
                <li key={result.chapter.id}>
                  <button
                    type="button"
                    className={`docs-search__result ${index === activeIndex ? 'is-active' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => go(result)}
                  >
                    <span className="docs-search__result-group">{result.chapter.group}</span>
                    <span className="docs-search__result-label">{result.chapter.label}</span>
                    <span className="docs-search__result-snippet">{result.snippet}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
