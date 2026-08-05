import type { ReactNode } from 'react';

/**
 * A small Markdown renderer for the subset language models actually emit.
 *
 * **Why hand-rolled.** The repo's convention outside `features/dashboard/` is
 * to hand-roll rather than add a dependency for a single component, and
 * `react-markdown` brings the whole remark/unified tree along for what is,
 * here, six constructs.
 *
 * **Why it builds React elements and never `dangerouslySetInnerHTML`.** The
 * input is model output that has had tool results — including strings from
 * external providers — fed through it. Constructing elements makes injection
 * impossible by construction rather than by sanitising afterwards, which is
 * the part that is easy to get subtly wrong.
 *
 * Supported: headings, bullet and numbered lists, fenced and inline code,
 * bold, italic, links, blockquotes, tables, and paragraphs. Anything else
 * falls through as literal text, which is the right failure: an unrendered
 * construct is legible, whereas a half-parsed one is not.
 */

interface InlineRule {
  pattern: RegExp;
  render: (match: RegExpExecArray, key: string) => ReactNode;
}

/**
 * Order matters on a tie. `**bold**` and `*italic*` can both match the same
 * run, so the longer marker has to be tried first or every bold span renders
 * as an italic wrapping a stray asterisk.
 */
const INLINE_RULES: InlineRule[] = [
  {
    // Code first and unconditionally: everything inside a span is literal, so
    // `**not bold**` in code has to survive intact.
    pattern: /`([^`]+)`/,
    render: (match, key) => (
      <code key={key} className="md-code">
        {match[1]}
      </code>
    ),
  },
  {
    // The URL allows one level of balanced parentheses. A plain `[^)\s]+`
    // stops at the first `)`, which truncates real links —
    // `.../Ocean_(disambiguation)` — and leaves the surplus bracket sitting in
    // the prose.
    pattern: /\[([^\]]+)\]\(([^()\s]*(?:\([^()]*\)[^()\s]*)*)\)/,
    render: (match, key) => {
      const href = match[2];
      // Only http(s). A `javascript:` or `data:` URL in an href is script
      // execution on click, and this text is not ours.
      const safe = /^https?:\/\//i.test(href);
      if (!safe) return <span key={key}>{match[1]}</span>;
      return (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer">
          {match[1]}
        </a>
      );
    },
  },
  {
    pattern: /\*\*([^*]+)\*\*/,
    render: (match, key) => <strong key={key}>{match[1]}</strong>,
  },
  {
    pattern: /__([^_]+)__/,
    render: (match, key) => <strong key={key}>{match[1]}</strong>,
  },
  {
    pattern: /\*([^*\n]+)\*/,
    render: (match, key) => <em key={key}>{match[1]}</em>,
  },
  {
    // Underscores only when flanked by whitespace or string edges, so
    // snake_case identifiers such as sea_surface_temperature — which this
    // assistant emits constantly — do not turn into italics.
    pattern: /(?:^|(?<=\s))_([^_\n]+)_(?=\s|$|[.,;:!?)])/,
    render: (match, key) => <em key={key}>{match[1]}</em>,
  },
];

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  let index = 0;

  while (rest.length > 0) {
    let earliest: { rule: InlineRule; match: RegExpExecArray } | null = null;

    for (const rule of INLINE_RULES) {
      const match = rule.pattern.exec(rest);
      if (!match) continue;
      if (earliest === null || match.index < earliest.match.index) {
        earliest = { rule, match };
      }
    }

    if (earliest === null) {
      nodes.push(rest);
      break;
    }

    const { rule, match } = earliest;
    if (match.index > 0) nodes.push(rest.slice(0, match.index));
    nodes.push(rule.render(match, `${keyPrefix}-i${index}`));
    rest = rest.slice(match.index + match[0].length);
    index += 1;
  }

  return nodes;
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$/.test(line) && line.includes('-');
}

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

export function Markdown({ text }: { text: string }): ReactNode {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];

  let paragraph: string[] = [];
  let key = 0;

  function flushParagraph() {
    if (paragraph.length === 0) return;
    const joined = paragraph.join('\n');
    blocks.push(
      <p key={`p${key++}`} className="md-p">
        {renderInline(joined, `p${key}`)}
      </p>
    );
    paragraph = [];
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    // --- fenced code -----------------------------------------------------
    if (/^\s*```/.test(line)) {
      flushParagraph();
      const language = line.replace(/^\s*```/, '').trim();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push(
        <pre key={`f${key++}`} className="md-pre" data-language={language || undefined}>
          <code>{body.join('\n')}</code>
        </pre>
      );
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      continue;
    }

    // --- heading ---------------------------------------------------------
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const Tag = (['h3', 'h4', 'h5', 'h6'] as const)[level - 1];
      blocks.push(
        <Tag key={`h${key++}`} className="md-h">
          {renderInline(heading[2], `h${key}`)}
        </Tag>
      );
      continue;
    }

    // --- table -----------------------------------------------------------
    if (line.includes('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      flushParagraph();
      const headers = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      i -= 1;
      blocks.push(
        <div key={`tw${key++}`} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {headers.map((cell, index) => (
                  <th key={index}>{renderInline(cell, `th${key}-${index}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{renderInline(cell, `td${key}-${rowIndex}-${cellIndex}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // --- blockquote ------------------------------------------------------
    if (/^\s*>\s?/.test(line)) {
      flushParagraph();
      const body: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ''));
        i += 1;
      }
      i -= 1;
      blocks.push(
        <blockquote key={`q${key++}`} className="md-quote">
          {renderInline(body.join('\n'), `q${key}`)}
        </blockquote>
      );
      continue;
    }

    // --- lists -----------------------------------------------------------
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = numbered !== null;
      const items: string[] = [];
      while (i < lines.length) {
        const current = lines[i];
        const nextBullet = /^\s*[-*+]\s+(.*)$/.exec(current);
        const nextNumbered = /^\s*\d+[.)]\s+(.*)$/.exec(current);
        const match = ordered ? nextNumbered : nextBullet;
        if (match) {
          items.push(match[1]);
          i += 1;
          continue;
        }
        // A plain indented line continues the item above rather than starting
        // a paragraph — models wrap long bullets.
        if (/^\s{2,}\S/.test(current) && items.length > 0) {
          items[items.length - 1] += ` ${current.trim()}`;
          i += 1;
          continue;
        }
        break;
      }
      i -= 1;

      const rendered = items.map((item, index) => (
        <li key={index}>{renderInline(item, `li${key}-${index}`)}</li>
      ));
      blocks.push(
        ordered ? (
          <ol key={`o${key++}`} className="md-list">
            {rendered}
          </ol>
        ) : (
          <ul key={`u${key++}`} className="md-list">
            {rendered}
          </ul>
        )
      );
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return <>{blocks}</>;
}
