/**
 * Presentational building blocks the docs chapters are written against.
 *
 * Deliberately tiny and hand-rolled, matching the repo's "no UI kit, no CSS
 * framework" convention. The point of having them at all is that a chapter
 * file should read as content — a table of variables, a callout, a formula —
 * rather than as a wall of divs and class names, and that every table on
 * every page shares one set of styles instead of drifting apart.
 */

import type { ReactNode } from 'react';

/* ------------------------------------------------------------------ */
/* Callout                                                             */
/* ------------------------------------------------------------------ */

export type CalloutKind = 'note' | 'warn' | 'lesson' | 'jargon';

const CALLOUT_DEFAULT_TITLE: Record<CalloutKind, string> = {
  note: 'Note',
  warn: 'Watch out',
  lesson: 'What we learned',
  jargon: 'Jargon buster',
};

/**
 * `jargon` is the one that carries the beginner promise of these docs: any
 * term a first-year ML student would have to go and look up gets defined
 * inline, next to where it is used, rather than assumed.
 */
export function Callout({
  kind = 'note',
  title,
  children,
}: {
  kind?: CalloutKind;
  title?: string;
  children: ReactNode;
}) {
  return (
    <aside className={`doc-callout doc-callout--${kind}`}>
      <p className="doc-callout__title">{title ?? CALLOUT_DEFAULT_TITLE[kind]}</p>
      {children}
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* Term                                                                */
/* ------------------------------------------------------------------ */

/** Inline marker for a piece of jargon at its first use. */
export function Term({ children }: { children: ReactNode }) {
  return <dfn className="doc-term">{children}</dfn>;
}

/* ------------------------------------------------------------------ */
/* Code                                                                */
/* ------------------------------------------------------------------ */

export function Code({ children }: { children: string }) {
  return (
    <pre className="doc-code">
      <code>{children}</code>
    </pre>
  );
}

/* ------------------------------------------------------------------ */
/* Formula                                                             */
/* ------------------------------------------------------------------ */

export function Formula({ expr, where }: { expr: string; where?: ReactNode }) {
  return (
    <div className="doc-formula">
      <div className="doc-formula__expr">{expr}</div>
      {where && <p className="doc-formula__where">{where}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Table                                                               */
/* ------------------------------------------------------------------ */

export interface TableProps {
  headers: ReactNode[];
  rows: ReactNode[][];
  /** Column indices rendered as tabular numerals. */
  numeric?: number[];
  caption?: ReactNode;
}

export function Table({ headers, rows, numeric = [], caption }: TableProps) {
  const numericSet = new Set(numeric);
  return (
    <>
      <div className="doc-table-wrap">
        <table className="doc-table">
          <thead>
            <tr>
              {headers.map((header, index) => (
                <th key={index} scope="col">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className={numericSet.has(cellIndex) ? 'is-num' : undefined}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && <p className="doc-table__caption">{caption}</p>}
    </>
  );
}

/** Highlight a winning / losing number inside a table cell. */
export function Best({ children }: { children: ReactNode }) {
  return <span className="is-best">{children}</span>;
}

export function Poor({ children }: { children: ReactNode }) {
  return <span className="is-poor">{children}</span>;
}

/* ------------------------------------------------------------------ */
/* Variable cards                                                      */
/* ------------------------------------------------------------------ */

export interface VariableEntry {
  name: string;
  unit?: string;
  description: ReactNode;
}

/** A grid of source-variable cards — used by the data chapter. */
export function VariableGrid({ variables }: { variables: VariableEntry[] }) {
  return (
    <div className="doc-varlist">
      {variables.map((variable) => (
        <div className="doc-var" key={variable.name}>
          <span className="doc-var__name">{variable.name}</span>
          {variable.unit && <span className="doc-var__unit">{variable.unit}</span>}
          <p className="doc-var__body">{variable.description}</p>
        </div>
      ))}
    </div>
  );
}
