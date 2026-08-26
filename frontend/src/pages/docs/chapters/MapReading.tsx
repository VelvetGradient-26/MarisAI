/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

/**
 * How the map is organised, for someone who has just opened it.
 *
 * The docs explained the science and the models but never the interface: which
 * layers can be on at once, what the four groups mean, why one of them is a
 * dropdown and the others are checkboxes, and what the basemap choice actually
 * changes. That is the first thing anyone needs and it was the one thing not
 * written down.
 */
export function MapReading() {
  return (
    <>
      <p className="docs-article__eyebrow">Using the platform</p>
      <h1>Reading the map</h1>
      <p className="docs-article__lede">
        The map is a stack: a basemap at the bottom, then up to four bands of data drawn on
        top of it. Everything on it is either an observation, a model forecast, or something
        derived from one of those — and the interface never lets those three look alike.
      </p>

      <h2 id="groups">The four layer groups</h2>
      <p>
        Layers are grouped by what kind of thing they are, and the group decides how they
        stack. The order below is also the drawing order, bottom to top.
      </p>
      <Table
        headers={['Group', 'How it behaves', 'What is in it']}
        rows={[
          [
            <strong>Ocean &amp; Atmosphere</strong>,
            <>
              <em>One at a time</em> — a dropdown
            </>,
            'Full-coverage colour fields: sea surface temperature, chlorophyll, salinity, every forecast field. Two of these on at once would simply hide each other, so the panel offers a choice rather than a pile of checkboxes.',
          ],
          [
            <strong>Wind &amp; Currents</strong>,
            'Stackable',
            'The moving fields — wind, surface currents, currents at depth, Stokes drift, combined drift — plus three detectors drawn over them: eddies, marine heatwaves and coastal upwelling.',
          ],
          [
            <strong>AI (Experimental)</strong>,
            'Stackable',
            'Output of the offline models: habitat suitability, bloom risk. Labelled experimental because that is what it is.',
          ],
          [
            <strong>Boundaries &amp; Reference</strong>,
            'Stackable, drawn on top',
            'Marine protected areas, exclusive economic zones, place labels, live AIS vessels, and eDNA sampling coverage. Reference sits above everything so labels and boundaries stay legible over a particle field.',
          ],
        ]}
      />
      <Callout kind="note" title="Why the detectors are filed under currents, not under AI">
        Eddy detection, marine-heatwave flags and the upwelling index are each a calculation
        over an observed field — the same arithmetic an oceanographer would do by hand, not a
        trained model. Putting any of them under "AI (Experimental)" would label an observation
        as an inference. The platform rounds the other way on purpose: something is only called
        a model when a model produced it. Fish habitat and bloom risk stay under AI because
        those genuinely are trained models.
      </Callout>

      <h2 id="basemaps">Basemaps are two different things</h2>
      <p>
        The basemap choice is not only cosmetic — the two kinds behave differently as you
        zoom.
      </p>
      <Table
        headers={['Kind', 'Examples', 'What you will notice']}
        rows={[
          [
            <strong>Vector</strong>,
            'Abyss, Bathymetry (the defaults)',
            'Geometry redrawn by the GPU at every fractional zoom, so zooming is continuous and text stays crisp at any scale.',
          ],
          [
            <strong>Raster</strong>,
            'Satellite, Blue Marble, Dark Marine',
            'Bitmap tiles. Zooming scales the current image until the next level loads, so there is a blur-then-pop no amount of tuning removes. Blue Marble stops at zoom 8 and is upscaled blur past that — it is a whole-planet image, not a street map.',
          ],
        ]}
      />
      <p>
        The default basemap is a near-black ocean, and that is a deliberate choice with a
        cost: it gives colour fields the most room, but it also means a dark ramp end can be
        hard to tell from bare ocean. That is what the hatching described in{' '}
        <em>Directions &amp; colour</em> exists to solve.
      </p>

      <h2 id="honesty">Three things the map will refuse to do</h2>
      <p>
        Most of the interface's unusual behaviour comes from one rule: never substitute a
        number for missing data. In practice that shows up as three refusals.
      </p>
      <Table
        headers={['You might expect', 'What happens instead', 'Why']}
        rows={[
          [
            'A layer that always has a value everywhere',
            'Transparent where there is no data; hatched where there is water but no forecast',
            'Land and "we could not score this water" are different facts and are drawn differently.',
          ],
          [
            'A layer that appears the moment you turn it on',
            'A "warming" state on a cold server',
            'Global fields are tens of megabytes per timestep and are fetched on a schedule, not on demand. Warming and failed are different answers.',
          ],
          [
            'A forecast layer for every variable',
            'Only variables whose models beat the bar, and only where a grid has been built',
            'A horizon ships only if it beats persistence and at most one of five validation folds is negative. The rest are absent, with a reason.',
          ],
        ]}
      />

      <h2 id="attribution">Every layer carries its own paperwork</h2>
      <p>
        Opening a layer's attribution gives you the product it came from, its grid spacing,
        how often it publishes, and — where it matters — what the layer is <em>not</em>. A
        forecast layer states which observation date it is anchored on and when the grid was
        built. A derived layer states the formula. A detection states its threshold.
      </p>
      <Callout kind="jargon" title="Data time, not fetch time">
        Panels report the timestamp of the <em>data</em>, which is not when it was fetched.
        Products publish hours behind real time as a matter of course; judging one on fetch
        time would report a perfectly healthy feed as stale. Where a value is composed of
        several fields, the timestamp shown is the <strong>oldest</strong> of them — a
        composite is only as current as its stalest input.
      </Callout>

      <h2 id="point">Clicking a point</h2>
      <p>
        Clicking anywhere on the ocean selects a coordinate and opens the panel of everything
        known there: live conditions, forecasts at each horizon with their uncertainty, and
        the model output that covers that spot. The same coordinate can be opened as a{' '}
        <Term>point brief</Term> — a document rather than a panel — or set against a second
        coordinate on the compare page.
      </p>
      <p>
        Two details worth knowing. A requested depth <em>snaps</em> to the nearest model level
        and the panel says which, because the ocean model has fifty fixed levels and 200 m
        resolves to 186.13 m. And where the seafloor is shallower than the depth you asked
        for, the answer is legitimately nothing — the model has no water there to report.
      </p>
    </>
  );
}
