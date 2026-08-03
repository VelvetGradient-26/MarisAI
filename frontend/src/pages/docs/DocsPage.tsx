import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from '../../app/router';
import { useAppRouter } from '../../app/routerContext';
import { useThemeStore } from '../../store/themeStore';
import {
  CHAPTERS,
  CHAPTER_GROUPS,
  PENDING_GROUPS,
  findChapter,
} from './chapters';
import './docs.css';

/**
 * Docs — long-form reference material.
 *
 * Chapter selection lives in the query string (`/docs?c=<id>`) rather than in
 * component state, so every chapter has a shareable, bookmarkable URL and the
 * browser back button walks the reading order. That works with the hand-rolled
 * router (app/router.tsx) exactly as it stands: `useAppRouter()` already
 * exposes `searchParams`, and `<Link>` already pushes history.
 *
 * The "on this page" rail is derived from the rendered DOM rather than from a
 * heading list declared alongside each chapter. A declared list is a second
 * source of truth that silently goes stale the first time someone edits a
 * heading; reading `h2[id]` back out of the article cannot.
 */
export function DocsPage() {
  const isDark = useThemeStore((s) => s.dark);
  const { searchParams, navigate } = useAppRouter();
  const chapter = findChapter(searchParams.get('c'));

  useEffect(() => {
    document.title = `Maris AI | Docs — ${chapter.title}`;
  }, [chapter.title]);

  const index = CHAPTERS.findIndex((entry) => entry.id === chapter.id);
  const previous = index > 0 ? CHAPTERS[index - 1] : null;
  const next = index < CHAPTERS.length - 1 ? CHAPTERS[index + 1] : null;

  const { Component } = chapter;

  return (
    <div className={`docs-page ${isDark ? '' : 'docs-page--light'}`}>
      <div className="docs-shell">
        <ChapterNav activeId={chapter.id} />

        <main className="docs-article">
          <div className="docs-mobile-nav">
            <label className="visually-hidden" htmlFor="docs-chapter-select">
              Chapter
            </label>
            <select
              id="docs-chapter-select"
              value={chapter.id}
              onChange={(event) => navigate(`/docs?c=${event.target.value}`)}
            >
              {CHAPTERS.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
          </div>

          <ArticleBody key={chapter.id} chapterId={chapter.id}>
            <Component />
          </ArticleBody>

          <nav className="docs-pager" aria-label="Chapter navigation">
            {previous ? (
              <Link className="docs-pager__link" to={`/docs?c=${previous.id}`}>
                <span className="docs-pager__dir">← Previous</span>
                <span className="docs-pager__label">{previous.label}</span>
              </Link>
            ) : (
              <span />
            )}
            {next && (
              <Link className="docs-pager__link docs-pager__link--next" to={`/docs?c=${next.id}`}>
                <span className="docs-pager__dir">Next →</span>
                <span className="docs-pager__label">{next.label}</span>
              </Link>
            )}
          </nav>
        </main>

        <PageOutline chapterId={chapter.id} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Article body                                                        */
/* ------------------------------------------------------------------ */

/**
 * Wrapper that exists purely to give the outline a stable element to read
 * headings back out of. Keyed by chapter id so React tears the subtree down on
 * a chapter switch rather than reconciling two different articles into each
 * other, which would leave the outline observing detached headings.
 */
function ArticleBody({ chapterId, children }: { chapterId: string; children: ReactNode }) {
  return (
    <div id={`docs-body-${chapterId}`} data-docs-body="">
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Left nav                                                            */
/* ------------------------------------------------------------------ */

function ChapterNav({ activeId }: { activeId: string }) {
  return (
    <aside className="docs-nav">
      <p className="docs-nav__title">Documentation</p>

      {CHAPTER_GROUPS.map(({ group, chapters }) => (
        <div className="docs-nav__group" key={group}>
          <p className="docs-nav__group-label">{group}</p>
          <ul className="docs-nav__list">
            {chapters.map((chapter) => (
              <li key={chapter.id}>
                <Link
                  className={`docs-nav__link ${chapter.id === activeId ? 'is-active' : ''}`}
                  to={`/docs?c=${chapter.id}`}
                  aria-current={chapter.id === activeId ? 'page' : undefined}
                >
                  {chapter.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {PENDING_GROUPS.map(({ group, entries }) => (
        <div className="docs-nav__group" key={group}>
          <p className="docs-nav__group-label">
            {group}
            <span className="docs-nav__badge">Soon</span>
          </p>
          <ul className="docs-nav__list">
            {entries.map((entry) => (
              <li key={entry}>
                <span className="docs-nav__link docs-nav__link--pending">{entry}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* On this page                                                        */
/* ------------------------------------------------------------------ */

interface Heading {
  id: string;
  text: string;
}

function PageOutline({ chapterId }: { chapterId: string }) {
  const [headings, setHeadings] = useState<Heading[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const body = document.querySelector('[data-docs-body]');
    if (!body) return;

    const found = Array.from(body.querySelectorAll<HTMLHeadingElement>('h2[id]')).map(
      (element) => ({ id: element.id, text: element.textContent ?? '' })
    );
    setHeadings(found);
    setActiveId(found[0]?.id ?? null);
  }, [chapterId]);

  useEffect(() => {
    if (headings.length === 0) return;

    // rootMargin pulls the "active" band up to just under the fixed navbar, so
    // the highlighted entry is the heading you are actually reading rather than
    // whichever one happens to be closest to the viewport centre.
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { rootMargin: '-88px 0px -70% 0px', threshold: 0 }
    );

    headings.forEach(({ id }) => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });

    return () => observer.disconnect();
  }, [headings]);

  if (headings.length === 0) return <aside className="docs-toc" />;

  return (
    <aside className="docs-toc">
      <p className="docs-toc__title">On this page</p>
      <ul className="docs-toc__list">
        {headings.map((heading) => (
          <li key={heading.id}>
            <button
              type="button"
              className={`docs-toc__link ${heading.id === activeId ? 'is-active' : ''}`}
              onClick={() => {
                const element = document.getElementById(heading.id);
                element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                setActiveId(heading.id);
              }}
            >
              {heading.text}
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
