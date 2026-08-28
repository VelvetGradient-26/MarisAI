/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Formula, Table, Term } from '../primitives';

/**
 * The first detector, and what a detector is.
 *
 * Every other layer in this product is a field: a number everywhere. This one
 * turns a field into a list of *things*, and the difference matters to a reader
 * — a count can be compared, quoted and misread in ways a colour ramp cannot.
 * So the chapter spends as much space on what the count is not as on the method.
 */
export function Eddies() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean &amp; atmosphere</p>
      <h1>Eddies, and what a detector is</h1>
      <p className="docs-article__lede">
        Every other layer here is a field — a number at every point. Eddy detection is the
        first layer that is a <em>list of things</em>: rotating features with a position, a
        size, a direction of spin and an intensity. That difference changes how the output
        should be read.
      </p>

      <h2 id="what">What an eddy is</h2>
      <p>
        A <Term>mesoscale eddy</Term> is a rotating body of water, typically 50–250 km across,
        that holds together for weeks to months and travels — usually westward — carrying its
        own water with it. They are the ocean's weather systems, and they matter for the same
        reasons weather systems do: they move heat and salt across the ocean, they trap and
        transport whatever is inside them, and they concentrate life at their edges.
      </p>
      <Table
        headers={['Polarity', 'Rotation', 'Typically']}
        rows={[
          [
            <strong>Cyclonic</strong>,
            'The same way the planet turns at that latitude — anticlockwise in the north, clockwise in the south',
            'Draws deep water upward at its centre: cold-core, nutrient-rich, often productive',
          ],
          [
            <strong>Anticyclonic</strong>,
            'Against the planet',
            'Pushes surface water down at its centre: warm-core, and often a nutrient-poor lens',
          ],
        ]}
      />
      <Callout kind="warn" title="Polarity is not the sign of the rotation">
        Cyclonic means turning <em>with the planet</em>, and which way that is depends on which
        hemisphere you are in. An identical anticlockwise vortex is cyclonic at 25°N and
        anticyclonic at 25°S. A detector that reads the rotation sign alone is right in one
        hemisphere and confidently wrong in the other — so polarity here is computed against
        latitude, and the band within 5° of the equator is excluded entirely, because the
        Coriolis parameter vanishes there and the label would be a coin flip.
      </Callout>

      <h2 id="method">How they are found</h2>
      <p>
        The method is <Term>Okubo-Weiss</Term>, applied to the live surface-current field. It
        asks a simple question at every point: is the water here mostly <em>rotating</em>, or
        mostly being <em>stretched and sheared</em>?
      </p>
      <Formula
        expr="W = Sₙ² + Sₛ² − ζ²"
        where={
          <>
            <strong>Sₙ</strong> and <strong>Sₛ</strong> are the normal and shear strain,{' '}
            <strong>ζ</strong> is the vorticity. Where <strong>W</strong> is strongly negative,
            rotation dominates — that is an eddy core.
          </>
        }
      />
      <p>
        The cut is <code>W &lt; −0.2σ</code>, where σ is the standard deviation of W over the
        water in view. Connected regions passing that test become candidate features; each one
        gets a centre (a circular mean, so a feature on the dateline is not relocated to the
        Gulf of Guinea), an area, an equivalent radius and a mean rotation.
      </p>
      <Callout kind="note" title="Why the current field and not sea level">
        Detecting eddies from closed contours of sea surface height is equally standard. The
        current field wins here for a practical reason: it is already fetched, global and
        hourly for the particle layers, so detection costs a pass over an array that is
        already in memory rather than a second global fetch. The whole planet takes about a
        tenth of a second, which is why it is computed on demand rather than scheduled.
      </Callout>

      <h2 id="count">The count is not a census</h2>
      <p>
        This is the most important thing on the page. The threshold is defined{' '}
        <em>relative to the variance of the field in view</em>, so the same ocean can yield a
        different number under a different mask. That makes it a consistent{' '}
        <strong>detector</strong> — good for comparing one region against another, or today
        against yesterday — and not a <strong>measurement</strong> of how many eddies exist.
        Every response carries the threshold, the σ it was taken against, and the fraction of
        the field that had data, because a count without them is not reproducible.
      </p>
      <Table
        headers={['Limit', 'Consequence']}
        rows={[
          [
            'The grid is about 0.25°',
            'A feature needs several cells across to be resolved at all. Anything smaller is absent rather than zero — submesoscale eddies are simply invisible here.',
          ],
          [
            'Features are capped at 300 km',
            'Above that it is a gyre, a meander of a boundary current, or two features the threshold merged. The Somali current does exactly this in the southwest monsoon.',
          ],
          [
            'Poleward of 60° is excluded',
            'Aggregates there are dominated by very small cells and sea-ice artefacts in the velocity field.',
          ],
          [
            'Coasts are under-detected',
            'The derivative meets the land mask, so nearshore features are systematically missed.',
          ],
        ]}
      />

      <h2 id="tracking">It detects; it does not track</h2>
      <Callout kind="lesson" title="Why there is no age, and no trajectory">
        Nothing is held between refreshes, deliberately. Following an eddy from one hour to
        the next is a frame-to-frame assignment problem, and a matcher that flickers identity
        produces tracks that are artefacts of the matcher presented as observations of the
        ocean. Detection ships first; tracking ships when it can be validated against a
        published eddy atlas rather than against how plausible the lines look.
      </Callout>
      <p>
        This is why nothing in the interface offers an eddy's age, its speed of travel, or
        where it will be tomorrow. It is also why the layer does not animate: each refresh is
        an independent detection over the current snapshot, not the next frame of a track.
      </p>

      <h2 id="reading">Reading the layer</h2>
      <p>
        Two colours and no ramp — teal for cyclonic, amber for anticyclonic — because polarity
        is the only categorical thing a detection carries. The <strong>ring is drawn at the
        eddy's real equivalent radius</strong>, so it grows and shrinks with the zoom like
        anything else on the map, rather than sitting at a fixed pixel size: the size is a
        measurement, and a dot that stayed the same at every zoom would be asserting something
        the detector never said.
      </p>
      <Callout kind="warn" title="The ring is not the eddy's outline">
        It is the equivalent radius of the detected core — the radius of a circle with the same
        area as the region where rotation beat strain. Real eddies are lumpy, and the region
        found by the threshold is lumpier still. The centre dot, not the ring, is the thing
        with a defined position.
      </Callout>
      <p>
        A point brief for any coordinate reports whether that point is inside a detected eddy
        and, if not, how far away the nearest one is. An absence with a distance is a real
        answer; an omitted row is not.
      </p>
    </>
  );
}
