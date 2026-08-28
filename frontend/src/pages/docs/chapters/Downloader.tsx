/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Formula, Table, Term } from '../primitives';

/**
 * The downloader, written for someone about to use the data for something else.
 *
 * The part worth documenting is not the form — it is what the export has
 * already done to the numbers on your behalf: which grid they were put on, how
 * a mixed-cadence request was aggregated, and why that ordering is not
 * arbitrary. Anyone analysing the CSV needs to know all three.
 */
export function Downloader() {
  return (
    <>
      <p className="docs-article__eyebrow">Using the platform</p>
      <h1>Downloading data</h1>
      <p className="docs-article__lede">
        Pick an area, a date range, a cadence and a set of variables, and get one tidy table
        as CSV, JSON or PDF. Thirty-four variables across fourteen upstream providers arrive
        merged onto a single grid and a single time axis — which means several decisions have
        already been made about your numbers before you open the file.
      </p>

      <h2 id="what">What you can ask for</h2>
      <Table
        headers={['Family', 'Examples']}
        rows={[
          ['Physics', 'Sea surface temperature, salinity, currents, sea surface height'],
          ['Waves', 'Significant and maximum wave height, mean and peak period, direction'],
          [
            'Biogeochemistry',
            'Chlorophyll-a, dissolved oxygen, pH, nitrate, phosphate, silicate, primary productivity',
          ],
          ['Atmosphere', 'Wind, air temperature, pressure, humidity, rainfall'],
          ['Static', 'Seafloor depth'],
        ]}
        caption="Two variables from the original specification are listed as unavailable rather than quietly dropped: ammonium (the global biogeochemistry suite models nitrate, phosphate, silicate and iron, but not ammonium) and tidal height (no global product of the kind the rest of this catalogue uses)."
      />
      <p>
        Two of them — water temperature and salinity — are{' '}
        <Term>depth-resolved</Term>. You choose a depth, and the request snaps to the nearest
        of fifty geometrically spaced model levels; the export metadata says which level
        actually answered. Below the seafloor the model is empty, so an over-deep request
        legitimately returns nothing, and the error says so rather than returning zeros.
      </p>

      <h2 id="grid">Everything lands on one grid</h2>
      <p>
        The providers do not agree on resolution — they range from about 0.083° to 0.25° —
        so the merge reindexes everything onto the <strong>finest</strong> grid present in
        your request. That means a coarse field is repeated across the fine field's cells
        rather than the fine field being thrown away. It also means a column's effective
        resolution is a property of its provider, not of the file: the header states each
        variable's native grid spacing for exactly that reason.
      </p>

      <h2 id="cadence">And on one time axis — in a specific order</h2>
      <p>
        Providers publish hourly, three-hourly, daily, or not in time at all. Getting a mixed
        request onto one cadence takes three stages, and the order they run in was earned the
        hard way.
      </p>
      <Table
        headers={['Stage', 'Why it must be here']}
        rows={[
          [
            <>
              <strong>1.</strong> Resolve derived variables
            </>,
            'A derivation is non-linear. Current speed is √(u² + v²), and the mean of hourly speeds is not the speed of the mean components — a current rotating through the day at a constant 1 m/s averages to almost nothing in components and would be reported as slack water.',
          ],
          [
            <>
              <strong>2.</strong> Aggregate each provider to the requested cadence
            </>,
            'This has to happen before the merge, because the merge cannot aggregate.',
          ],
          [
            <>
              <strong>3.</strong> Merge on the shared time axis
            </>,
            'An inner join, so a row exists only where every requested provider has data.',
          ],
        ]}
      />
      <Callout kind="lesson" title="What happened when stage 2 came last">
        Left to itself, the join kept the coarse provider's timestamps and took the fine
        provider's <em>instantaneous</em> value at each one — an hourly field paired with a
        daily one survived as its 00:00 sample standing in for a 24-hour mean. Nothing raised,
        nothing was blank. On a synthetic 3 °C diurnal cycle the old path reported 23.0 where
        the daily mean is 20.0: wrong by the full amplitude, in every row, always in the same
        direction. Thirteen of the platform's own forecasting variables were being trained on
        covariates fed through it.
      </Callout>
      <Callout kind="note" title="There is deliberately no second resample after the merge">
        Two places that could define the cadence is exactly how the first one silently stops
        mattering.
      </Callout>

      <h2 id="cost">What a request costs</h2>
      <p>
        Requests are bounded before any provider is called, and the bound is{' '}
        <strong>per provider</strong> rather than global — providers differ enormously in what
        the same box and date range costs them, because they differ in grid spacing and in
        how often they publish.
      </p>
      <Formula
        expr="cells = (area ÷ grid spacing²) × timesteps at the provider's native cadence"
        where={
          <>
            Capped at <strong>3,000,000</strong> cells per provider. For scale: a 5°×5° box
            over one month of hourly data is about 2.7M cells and fetches in 8–10 s, while a
            basin-scale box over a full year is ~1.8 billion and took over 270 s.
          </>
        }
      />
      <Callout kind="warn" title="Asking for monthly output does not make it cheaper">
        The fetch always pulls the dataset's <em>native</em> cadence; resampling to daily,
        weekly or monthly happens afterwards, here. So the guardrail counts the fetch, not the
        much smaller table you asked for — the levers that actually reduce cost are a smaller
        area, a shorter date range, or fewer variables.
      </Callout>

      <h2 id="provenance">Provenance travels with the file</h2>
      <p>
        Every export carries, per variable: the product identifier it came from, the native
        grid spacing and cadence, the coverage window, the citation and the licence. This is
        not decoration — a downloaded CSV outlives the session that produced it, and a column
        of numbers with no product identifier is not reusable for anything serious.
      </p>
      <Callout kind="warn" title="Coverage windows genuinely differ">
        Not every variable reaches back as far as every other. The biogeochemistry products
        have a shorter record than the physics; some fields start only a few years ago. A
        request that spans further back than a variable can serve is refused with the reason,
        rather than returned truncated and looking complete.
      </Callout>
    </>
  );
}
