/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table } from '../primitives';

/**
 * Where the ocean has been sampled molecularly — not what lives where.
 *
 * The whole chapter exists to prevent one misreading: an empty map here does
 * not mean an empty ocean, it means nobody has sequenced that water yet. Every
 * section works to keep that distinction in view, the same discipline the
 * biodiversity section of the brief chapter applies to OBIS counts generally.
 */
export function Edna() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean &amp; atmosphere</p>
      <h1>eDNA sampling coverage</h1>
      <p className="docs-article__lede">
        Environmental DNA — genetic material shed into the water by everything that lives
        there, filtered from a bottle of seawater and sequenced without ever seeing the
        animal. This layer does not map what species live where; it maps <em>where the ocean
        has been sampled this way at all</em>, which turns out to be almost nowhere.
      </p>

      <h2 id="source">No new integration — a filter on data already in use</h2>
      <p>
        eDNA records live in OBIS beside every ordinary occurrence record, tagged with the
        extension <code>DNADerivedData</code>. So this layer adds a question to a source the
        platform already calls (the same one the biodiversity section of a point brief uses),
        rather than adding a new provider.
      </p>

      <h2 id="empty">The empty map is the finding</h2>
      <Callout kind="lesson" title="Smaller than Belgium">
        Measured live: <strong>44,548,350</strong> eDNA records worldwide occupy{' '}
        <strong>1,475 cells</strong>, <strong>27,286 km²</strong> at the reference grid
        resolution — <strong>0.0075% of the ocean</strong>. A reader arriving from the SST
        layer, where colour covers the whole planet, reads that blankness as a failed load.
        The coverage panel states the fraction unprompted, rather than leaving a mostly-black
        map to speak for itself.
      </Callout>
      <p>
        Zooming out does not mean there is more data — it means each cell on screen is bigger.
        Quoting the fraction at whatever grid the map happens to be drawn at would make the
        number swing with the zoom level rather than the ocean: the same records cover{' '}
        <strong>23.1%</strong> of the ocean at a coarse grid and <strong>0.0075%</strong> at a
        fine one, a roughly 3,000× difference produced entirely by cell size — a coarse cell
        credits one water bottle with crediting everything around it. So the headline fraction
        is always quoted at one fixed reference resolution, never at whatever the map is
        currently drawing, and a request scoped to a box reports no whole-ocean fraction at
        all rather than a ratio between two unrelated areas.
      </p>

      <h2 id="reading">Reading the layer</h2>
      <p>
        Colour is a logarithmic scale on a fixed domain, because occupied cells span six
        orders of magnitude — from a single record to over four million at the busiest
        monitoring site. A linear ramp on that range is a black planet with one bright pixel;
        normalising against whatever happens to be loaded was rejected too, because a cell
        would then change colour as you zoomed and the legend could not name a number.
      </p>
      <Table
        headers={['Records in the cell', 'Roughly']}
        rows={[
          ['1 – 100', 'A single study passed through'],
          ['100 – 10,000', 'Repeat sampling'],
          ['10,000 – 1,000,000', 'An active monitoring programme'],
          ['1,000,000+', 'A standing time-series station'],
        ]}
      />
      <p>
        The ramp is a single violet hue, deliberately unlike the physical layers' colour
        schemes: sampling effort is not a property of the water, and should not look like a
        physical field such as temperature or chlorophyll.
      </p>

      <h2 id="counts">Counts are detections, not abundance</h2>
      <p>
        A number here is <em>taxon-detections</em>, not samples, individuals, or biomass. A
        single microbial run can return thousands of records from one bottle where a
        traditional fish survey returns a handful — so a cell with more records is not
        necessarily a richer one, it may just be a different kind of study. Sequence-read
        counts do exist in the data, but scale with primer chemistry and PCR cycles as much as
        with how much of an organism was actually there, and are never reported as a stand-in
        for abundance.
      </p>
      <Callout kind="warn" title="Absence means even less here than in an ordinary occurrence record">
        OBIS is already presence-only — it records what was found, never what was looked for
        and not found. eDNA adds three more ways a real organism can go unrecorded before that
        rule even applies: its DNA can degrade before sampling, the primer used may not
        amplify that taxon, or no reference sequence exists to name a match once sequenced.
        Four independent links, any one of which can break, sit between "this animal was
        there" and "this animal appears in the data."
      </Callout>
      <p>
        A single coordinate distinguishes <em>three</em> different kinds of empty, not two:
        the request itself failing, water nobody has sampled at all, and water that has
        ordinary occurrence records but has never been sequenced. That third case is the
        Arabian Sea's own: hundreds of conventional biodiversity records exist there, and zero
        molecular ones.
      </p>

      <h2 id="share">Molecular share needs a real denominator</h2>
      <p>
        Where a box has both conventional and eDNA records, the panel reports what share of
        everything OBIS knows about that water is molecular — and that share is{' '}
        <code>null</code>, not zero, wherever the conventional count is itself zero.
        "0% molecular" would read as a finding about method choice, when the true state is a
        missing denominator to divide by.
      </p>

      <h2 id="limits">Two questions this cannot answer — checked, not assumed</h2>
      <Table
        headers={['Question', 'What the data actually shows']}
        rows={[
          [
            'Does eDNA extend the fishery-model training window past 2013?',
            <>
              No. Records for the habitat model's target species: yellowfin tuna{' '}
              <strong>0</strong>, oil sardine <strong>0</strong>, skipjack 44, bigeye 19,
              Indian mackerel 45. The post-2014 drought behind the platform's habitat window
              survives a change of method, the same way it survived widening to a second
              occurrence source.
            </>,
          ],
          [
            'Can it validate harmful algal bloom risk in the Arabian Sea?',
            <>
              No. The whole Arabian Sea box holds under a hundred eDNA records across four
              datasets, and zero for any of the three bloom-forming taxa the model targets.
              Those organisms are sequenced elsewhere, not in this region's own record.
            </>,
          ],
        ]}
      />

      <h2 id="refresh">No poll timer, and a 502 means the upstream failed</h2>
      <p>
        OBIS publishes on a release cadence measured in weeks, not minutes, so each precision
        level is cached for a day and the layer only refetches when you <em>zoom</em> — not on
        a timer, and with no viewport filtering, since even the finest global level is a
        payload of a few hundred kilobytes. And because every request here is a live call to
        OBIS rather than a cache this server warms itself, an unavailable answer is reported
        as <code>502</code> — the same convention the recorded-biodiversity section of a point
        brief uses, and the opposite of the eddy layer's <code>503</code>, which blames a cold
        cache this server owns.
      </p>
    </>
  );
}
