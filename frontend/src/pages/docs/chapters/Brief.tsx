/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

/**
 * One coordinate as a document, and two coordinates against each other.
 *
 * The interesting content here is not what the brief contains — everything in
 * it has an endpoint of its own — but the three editorial decisions: it does
 * not compute, it does not rank, and it keeps rows only one side has.
 */
export function Brief() {
  return (
    <>
      <p className="docs-article__eyebrow">Using the platform</p>
      <h1>The point brief, and comparing two places</h1>
      <p className="docs-article__lede">
        A brief is one coordinate rendered as a document rather than as a panel: everything
        the platform knows about that spot, laid out in sections, exportable as a PDF. Compare
        is the same thing for two coordinates, aligned row by row.
      </p>

      <h2 id="composition">Composition, not computation</h2>
      <p>
        Nothing in a brief is calculated for the brief. Every number in it already has an
        endpoint that the map or the dashboard uses — the brief's job is layout, ordering and
        labelling. That is a deliberate constraint: a document that computed its own version
        of a value could disagree with the map showing the same value, and the reader would
        have no way to tell which was wrong.
      </p>
      <Table
        headers={['Section', 'What it answers']}
        rows={[
          ['Location', 'Where this is, and how deep the seafloor is beneath it'],
          ['Observed conditions', 'Live sea and air state at the point'],
          [
            'Water movement',
            'Current, Stokes drift, what carries a floating object — and whether the point sits inside a detected eddy or how far the nearest one is',
          ],
          ['Forecast', 'Each trained variable at each horizon, with its uncertainty'],
          ['Fish habitat suitability', 'The offline habitat model, where its region covers this point'],
          ['Harmful algal bloom risk', 'The offline bloom model, on the same terms'],
          ['Recorded biodiversity', 'What has been recorded near here, and the bias in that record'],
        ]}
      />
      <Callout kind="note" title="Every section can be empty, with a reason">
        A section carries an availability flag and a reason the document prints. This is
        stricter than the on-screen rule, for a specific reason: a PDF is read somewhere
        nobody can hover over a blank panel to find out why it is blank. Model output is
        labelled as model output in the same spirit — a printed page loses the interface's
        visual cues about what came from where.
      </Callout>

      <h2 id="compare">Comparing two points</h2>
      <p>
        Compare gathers two briefs and aligns them on section and row label. It is a{' '}
        <em>view over</em> the brief rather than a second assembly — a parallel pipeline would
        let the two halves disagree about one coordinate, which is fatal for a feature whose
        entire output is a difference.
      </p>
      <Table
        headers={['Situation', 'What you get']}
        rows={[
          [
            'Both sides are numbers in the same unit',
            'The difference, computed and shown',
          ],
          [
            'Both sides exist but are not comparable numbers',
            'Both values, side by side, and no delta invented',
          ],
          [
            'Only one side has the row',
            <>
              The row is kept and marked <Term>only at</Term>
            </>,
          ],
        ]}
      />
      <p>
        That last case is not an edge case — it is often the most informative line in the
        document. "Habitat suitability 0.71 here, outside the model's region there" tells you
        something a dropped row would hide, and dropping it would report two places as more
        alike than they are.
      </p>
      <Callout kind="lesson" title="Thousands separators, again">
        A delta is only computed when both sides parse as numbers in the same unit, and the
        number parser has to handle grouped digits. Reading "1,204 m" as "1" turns a 1,200 m
        difference into a 1 m difference — in the right units, and silently. The assistant's
        grounding checker learned the identical lesson independently, which is why it is worth
        writing down twice.
      </Callout>

      <h2 id="ranking">It does not rank</h2>
      <p>
        There is no composite score, no "overall suitability", no single number that says one
        place is better than the other. The reason is the same one that got an earlier
        "Fishing Opportunity Index" rejected: <strong>there is nothing to validate it
        against</strong>. Every individual number in a brief is checked against something —
        an observation, a held-out fold, a published product. A weighted blend of them is
        checked against nothing, and it would be the most confidently-read line on the page.
      </p>

      <h2 id="biodiversity">The biodiversity section, and why it carries a warning</h2>
      <p>
        Recorded biodiversity comes from OBIS — two cheap queries over a box around the point,
        giving record counts, year range and a species checklist.
      </p>
      <Callout kind="warn" title="Those counts are survey effort, not biodiversity">
        Record density tracks marine institutes, research cruises and shipping lanes, not
        life. A stretch of ocean with ten thousand records and one with none may differ only
        in who sailed through. The bias note is a required part of the response rather than
        small print — the same bias the habitat model spends its whole target-group background
        scheme correcting, and printing an uncorrected headline beside a corrected model would
        be indefensible.
      </Callout>
      <p>
        OBIS is also presence-only: it records what was seen, never what was looked for and
        not found. So an empty box is an answer with a reason attached, and never "nothing
        lives here."
      </p>
    </>
  );
}
