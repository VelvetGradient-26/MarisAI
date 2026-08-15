/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

/**
 * How to read a layer without getting it backwards.
 *
 * The direction conventions are the important part and the reason this chapter
 * exists separately: currents and wind are named by opposite conventions, they
 * are 180° apart, and both readings look entirely plausible on screen. Every
 * bug this codebase has had in that area rendered perfectly.
 */
export function OceanConventions() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean &amp; atmosphere</p>
      <h1>Directions, colour &amp; how to read a layer</h1>
      <p className="docs-article__lede">
        A vector field can be drawn perfectly and still be telling you the opposite of what
        you think. This chapter covers the conventions the map uses — which way an arrow
        points, what a colour means, and why the ramps look the way they do.
      </p>

      <h2 id="directions">The two direction conventions</h2>
      <Callout kind="warn" title="Wind and currents are named opposite ways round">
        A <strong>current</strong> is named for where the water is <em>going</em>. A{' '}
        <strong>wind</strong> is named for where the air is <em>coming from</em>. A
        "northward current" flows toward the north; a "north wind" blows <em>from</em> the
        north, moving air southward. The two conventions are 180° apart, and both are
        standard in their own field — this is not a quirk of this platform.
      </Callout>
      <p>
        Because getting this wrong is invisible — every arrow would be exactly reversed and
        the map would still look like a plausible ocean — the platform never uses a bare
        "direction". Each field names its convention in the value itself:
      </p>
      <Table
        headers={['Field', 'Reported as', 'Reads as']}
        rows={[
          [
            'Surface currents, currents at depth, Stokes drift, combined drift',
            <code>direction_toward_deg</code>,
            'the direction the water carries toward',
          ],
          ['Wind', <code>direction_from_deg</code>, 'the direction the wind blows from'],
          [
            'Wave direction',
            <code>direction_from_deg</code>,
            'the direction the waves come from, matching the meteorological convention',
          ],
        ]}
      />
      <p>
        The particle layers follow the same rule visually: current, Stokes and drift
        particles travel the way the water travels, and wind particles travel the way the air
        travels — which is <em>away</em> from the direction the wind is named for.
      </p>

      <h2 id="circular">Why directions are handled separately everywhere</h2>
      <p>
        A bearing is <Term>circular</Term>: 359° and 1° are two degrees apart, not 358. Every
        ordinary operation gets this wrong. Averaging them gives 180° — the exact opposite
        heading — and a colour ramp with different colours at each end puts a hard seam
        through due north where there is no discontinuity in the ocean at all.
      </p>
      <p>So directions are treated as angles at every stage between the model and the screen:</p>
      <Table
        headers={['Stage', 'Naive result', 'What the platform does']}
        rows={[
          [
            'Resampling to screen resolution',
            'The midpoint of 359° and 1° comes out as 180°',
            'Interpolates sine and cosine separately, then recombines — giving 0°',
          ],
          [
            'Showing a change ("+7d minus now")',
            'A 5° veer across north reads as −355°',
            'A signed veer wrapped to ±180°, so it reads as +5°',
          ],
          [
            'The colour scale',
            'A seam at due north where the ramp ends meet',
            'A cyclic ramp whose first and last colour are identical by construction',
          ],
        ]}
      />
      <Callout kind="lesson" title="One place where it is still linear">
        The forecast <em>models</em> for direction are trained on the change in degrees, so a
        veer across north is still a −355° training target for them. The proper fix is to
        forecast the eastward and northward components and derive the angle from those — which
        is exactly what the current components already do, and why the currents particle layer
        was never affected. It is recorded as open rather than hidden.
      </Callout>

      <h2 id="colour">Reading the colour ramps</h2>
      <p>
        Four vector fields can be on screen at once, so they are distinguished by{' '}
        <strong>structure</strong> rather than by four different palettes. Wind cycles through
        hues in the convention most weather maps use; every other flow field stays in a single
        hue and varies only in lightness.
      </p>
      <Table
        headers={['Layer', 'Ramp', 'Scale tops out at']}
        rows={[
          ['Wind', 'Multi-hue, blue → green → yellow → red → purple', '25 m/s'],
          ['Surface currents & currents at depth', 'Single hue, amber', '2 m/s'],
          ['Stokes drift', 'Single hue, violet', '1 m/s'],
          ['Combined drift', 'Single hue, green', '2.5 m/s'],
        ]}
        caption="Two single-hue ramps can be told apart at a glance in a way two multi-hue ramps cannot. The drift scale reaches further than the currents scale because its three terms add rather than average."
      />
      <p>
        The depth layers deliberately share the surface currents ramp <em>and</em> its
        maximum. The entire point of a depth selector is comparing one level against another,
        and a legend that rescaled itself per level would make that comparison meaningless.
        For the same reason the legend maximum is fixed rather than derived from the data —
        two screenshots of the same ocean taken an hour apart have to be comparable.
      </p>

      <h2 id="edges">Coastlines, gaps and hatching</h2>
      <p>
        Land, and water the model cannot score, are different things and are drawn
        differently. A transparent cell means there is no data there at all — land, or outside
        the product's coverage. A <strong>hatched</strong> cell on a forecast layer means the
        opposite: there is water there and we can see it, but the forecast could not be
        produced for it.
      </p>
      <Callout kind="note" title="Why hatching rather than a colour">
        The default basemap is a near-black ocean and every ramp bottoms out dark, so at the
        layer's working opacity the darkest step of each ramp is barely distinguishable from
        bare basemap — a cell showing strong cooling and a cell showing nothing measured as
        nearly the same pixel. Lightening the ramps was tried and rejected on measurement, so
        the distinguishing channel had to be texture rather than colour.
      </Callout>

      <h2 id="cadence">Freshness and cadence</h2>
      <p>
        Fields update at the rate their upstream product publishes, not at a rate chosen here:
        hourly for surface currents, wind and SST; three-hourly for waves and Stokes drift;
        daily for depth-resolved currents and biogeochemistry. Refreshing faster than the
        product publishes would just refetch a field that cannot have changed.
      </p>
      <p>
        Every panel therefore reports the timestamp of the <em>data</em>, distinct from when
        it was fetched — a product that publishes several hours behind real time is working
        normally, and judging it on fetch time would report a healthy feed as stale. Where a
        value is a composite of several fields, the timestamp shown is the{' '}
        <strong>oldest</strong> of them: a combined field is only as current as its stalest
        input.
      </p>
      <Callout kind="jargon" title="Warming, not broken">
        Global fields are tens of megabytes per timestep and take minutes to fetch, so they
        are fetched on a schedule and served from memory rather than fetched when you ask. A
        layer that has just come up says it is warming rather than showing an error or, worse,
        an empty ocean — "we do not have this yet" and "this failed" are different answers and
        the interface keeps them apart.
      </Callout>
    </>
  );
}
