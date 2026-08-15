/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Formula, Table, Term, VariableGrid } from '../primitives';

/**
 * What the platform actually serves, field by field.
 *
 * This chapter exists because the docs could explain how the models were
 * validated but not what sea surface temperature *is* in this product, which
 * product it came from, or how often it changes. That knowledge lived in module
 * docstrings and in CLAUDE.md, where no user ever sees it.
 */
export function OceanFields() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean &amp; atmosphere</p>
      <h1>The fields, and where they come from</h1>
      <p className="docs-article__lede">
        Every layer on the map and every number in the dashboard is one of about forty
        physical fields, drawn from a handful of upstream products. This chapter is the
        reference: what each field measures, which product publishes it, how often it
        changes, and — where it matters — what it is not.
      </p>

      <Callout kind="note" title="Nothing here is synthetic">
        Every field below is a real, publicly documented product. Where a value is
        unavailable the interface says so and gives a reason; it never substitutes a number.
        That rule is the reason some panels are blank rather than reassuring.
      </Callout>

      <h2 id="three-kinds">Three kinds of field</h2>
      <p>
        The distinction that matters most when reading the map is not ocean-versus-atmosphere
        but how the number came to exist.
      </p>
      <Table
        headers={['Kind', 'Example', 'What it means for you']}
        rows={[
          [
            <strong>Observed / analysed</strong>,
            'Sea surface temperature, wind, currents',
            'A model with real observations assimilated into it. The best available answer for "now", published with a short lag.',
          ],
          [
            <strong>Forecast</strong>,
            'Any layer labelled +1d / +3d / +7d / +30d',
            'Model output. Skill is measured against persistence and published per variable and horizon — some variables forecast well, some do not, and the untrained ones are simply absent.',
          ],
          [
            <strong>Derived</strong>,
            'Ocean heat content, the combined drift field, bloom risk',
            'Computed here from other fields. The formula is stated wherever the value appears.',
          ],
        ]}
      />

      <h2 id="ocean">The ocean</h2>
      <p>
        The physical ocean fields come from the Copernicus Marine Service global
        analysis-forecast system, on a <Term>1/12°</Term> grid — roughly 8 km at the equator.
        The hourly product carries a single surface level; anything below the surface comes
        from a separate daily product with fifty levels.
      </p>
      <VariableGrid
        variables={[
          {
            name: 'Sea surface temperature',
            unit: '°C',
            description:
              'The temperature of the topmost model level — about 0.49 m down, not the skin temperature a satellite infrared sensor sees. Hourly.',
          },
          {
            name: 'Surface currents',
            unit: 'm/s',
            description:
              'Eastward and northward water velocity as components, which is what makes the particle animation possible. Hourly.',
          },
          {
            name: 'Currents at depth',
            unit: 'm/s',
            description:
              'The same field below the surface, at six chosen levels from 0 to 1000 m. A daily mean rather than hourly — the depth-resolved product publishes once a day. A requested depth snaps to the nearest model level and the panel says which: 200 m resolves to 186.13 m.',
          },
          {
            name: 'Salinity',
            unit: 'PSU',
            description:
              'Practical salinity, at the surface or at depth. Notable for being the one variable the forecasting engine could not beat persistence on — it barely moves, so "the same as yesterday" is very hard to improve on.',
          },
          {
            name: 'Sea surface height',
            unit: 'm',
            description:
              'Height above the geoid. Its anomaly is what reveals eddies: a warm-core eddy sits as a bump, a cold-core one as a dip.',
          },
          {
            name: 'Ocean heat content',
            unit: 'GJ/m²',
            description:
              'Derived here, not fetched: ρ·cp·∫T dz over a depth layer. Offered over 0–50, 0–100, 0–200 and 0–700 m, because they answer different questions — the shallow layers carry the heat available to a storm within days, while 0–700 m is the climate-scale reference.',
          },
        ]}
      />

      <h2 id="waves">Waves and Stokes drift</h2>
      <p>
        Waves come from the Copernicus global wave model, three-hourly. The wave{' '}
        <em>heights</em> and <em>periods</em> are ordinary scalar fields. The one worth
        singling out is Stokes drift.
      </p>
      <Callout kind="note" title="Stokes drift is not a current">
        A wave does not just move water up and down — over a full orbit each parcel is
        carried a little way in the direction the wave travels. That net transport is Stokes
        drift, and it is what actually moves a floating object along with the current beneath
        it. In the trade-wind belts and the Southern Ocean it is a large fraction of the
        total. It is drawn as its own layer rather than being folded into the currents,
        because a layer showing only the sum could not tell you which of the two put an
        object where it is — and the two routinely disagree in direction.
      </Callout>

      <h2 id="atmosphere">The atmosphere</h2>
      <p>
        Wind comes from a different kind of product: a Level-4 blended analysis of satellite
        scatterometer passes, on a 1/8° grid, hourly. Air temperature, pressure, humidity and
        rainfall come from a reanalysis-backed point API instead.
      </p>
      <Callout kind="warn" title="Some fields can never be a map layer">
        The point API is capped at a few hundred coordinates per request, so the variables it
        serves — air temperature, humidity, pressure, rainfall, sea level anomaly — can be
        charted and forecast at a point but can never be painted as a global field. The
        interface says so explicitly rather than leaving a permanently empty layer: a missing
        layer with a reason is information, a missing layer without one is a bug report.
      </Callout>

      <h2 id="drift">The combined drift field</h2>
      <p>
        What carries a floating object is not any single field but the sum of three:
      </p>
      <Formula
        expr="u_total = u_current + u_stokes + α · u_wind"
        where={
          <>
            <strong>α</strong> is the leeway coefficient of the drifting object
          </>
        }
      />
      <p>
        The third term is <Term>leeway</Term> — the fraction of the wind speed an object picks
        up directly from air drag on whatever stands above the waterline. Crucially,{' '}
        <strong>α is a property of the object, not of the ocean</strong>: roughly 1–2% for a
        swamped hull sitting almost flush, around 3% for a surface slick, several times that
        for a life raft with freeboard and no drogue. The same water takes them along
        measurably different tracks, which is why the map offers a layer per object rather
        than one "drift" layer with a hidden constant baked in.
      </p>
      <Callout kind="warn" title="A field, not a trajectory">
        The drift layers show where the water is going <em>right now, everywhere</em>. They
        are not a prediction of where one object will be in two days: the particles are
        advected against a single snapshot, so they never cross the changing field a real
        trajectory would. A genuine drift forecast also has to be run as an ensemble and
        drawn as a probability envelope — a single confident line on a map, in a product
        someone might actually search from, would be the most dangerous thing here.
      </Callout>

      <h2 id="biogeochemistry">Biogeochemistry</h2>
      <p>
        Chlorophyll-a, dissolved oxygen, pH, nitrate, phosphate, silicate and primary
        productivity come from the Copernicus biogeochemistry suite — a coarser 1/4° grid,
        daily, and with a shorter record than the physics. Chlorophyll is the one to watch:
        it is patchy and advected rather than smooth, which is exactly why it forecasts
        better than anything else here. Persistence is a weak baseline for a field that moves.
      </p>
      <Callout kind="note" title="Ammonium and tidal height are absent, deliberately">
        Two of the variables in the original specification have no global source — the
        Copernicus biogeochemistry suite models nitrate, phosphate, silicate and iron but not
        ammonium, and there is no global tidal-height product of the kind the rest of this
        catalogue uses. They are listed as unavailable rather than quietly dropped.
      </Callout>
    </>
  );
}
