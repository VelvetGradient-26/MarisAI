/**
 * Exports every docs chapter's plain-text content to
 * `backend/data/docs_index.json`, for the Ocean Assistant's
 * `get_documentation` tool (`backend/services/docs.py`).
 *
 * The backend has no JS runtime and the chapters are React/TSX source, not
 * markdown, so this is the plain-text mirror the assistant's self-knowledge
 * tool needs — see TODO.md's "Ocean Assistant: answer questions about the
 * software itself" for why. Renders each chapter with `react-dom/server`
 * (a real render pass, not a hand-rolled tree walk like
 * `chapters/searchIndex.tsx`'s in-browser search index) because several
 * chapters use `<Link>`, which calls `useAppRouter()` — a hook needs an
 * active dispatcher, which only a real render provides. Chapters are
 * wrapped in the same `RouterContext` `<Link>` reads through, with a no-op
 * `navigate` since nothing here is ever clicked.
 *
 * `React.createElement` rather than JSX deliberately: this file lives
 * outside `tsconfig.app.json`'s `"include": ["src"]` (it is tooling, not
 * app source, and that tsconfig's `noUnusedLocals`/`verbatimModuleSyntax`
 * strictness is tuned for the app, not a one-off script), so there is no
 * `jsx: "react-jsx"` compiler option in scope for `tsx` to pick up here —
 * calling `createElement` directly needs no JSX transform at all.
 *
 * Run after editing any chapter — nothing invalidates the committed export
 * automatically:
 *
 *   cd frontend && npm run export-docs
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { RouterContext } from '../src/app/routerContext';
import { CHAPTERS } from '../src/pages/docs/chapters/index';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ROUTER_VALUE = {
  pathname: '/docs',
  searchParams: new URLSearchParams(),
  navigate: () => {},
};

const ENTITIES: Record<string, string> = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&#x27;': "'",
  '&nbsp;': ' ',
};

function htmlToText(html: string): string {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x?[0-9a-fA-F]+;|&[a-zA-Z]+;/g, (entity) => ENTITIES[entity] ?? ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const entries = CHAPTERS.map((chapter) => {
  const html = renderToStaticMarkup(
    createElement(RouterContext.Provider, { value: ROUTER_VALUE }, createElement(chapter.Component)),
  );
  return {
    id: chapter.id,
    label: chapter.label,
    title: chapter.title,
    group: chapter.group,
    url: `/docs?c=${chapter.id}`,
    text: htmlToText(html),
  };
});

const outPath = path.resolve(__dirname, '../../backend/data/docs_index.json');
writeFileSync(outPath, `${JSON.stringify(entries, null, 2)}\n`);
console.log(`Wrote ${entries.length} chapters to ${outPath}`);
