/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Code, Table, Term } from '../primitives';

export function Fusion() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>The Marine Data Fusion Layer</h1>
      <p className="docs-article__lede">
        Raw products arrive on four different grids at four different cadences. This layer
        brings them onto one common grid, computes the shared derived fields, records how
        complete each row actually is, and hands both problems an identical view of the ocean.
        It is written once and imported by both.
      </p>

      <h2 id="why">Why this exists at all</h2>
      <p>
        Physics arrives at 1/12°, biogeochemistry at 1/4°, bathymetry at 15 arc-seconds, wind at
        1/8°. If each problem's pipeline did its own regridding, "sea surface temperature
        gradient" would end up meaning two subtly different computations in two places — and
        nobody would notice until the two models disagreed for reasons no one could explain.
      </p>
      <p>The layer supports exactly two access shapes, because the two problems genuinely need different ones:</p>
      <Table
        headers={['Function', 'Returns', 'Used by']}
        rows={[
          [
            <code>build_gridded_frame()</code>,
            'The full (latitude, longitude, date) cube as a tidy table — one row per cell per day.',
            'Problem A, and the prediction-raster export for the map.',
          ],
          [
            <code>sample_at_points()</code>,
            'Ocean state at scattered observation points.',
            'Problem B — occurrence records are points, not a grid, and materialising the whole cube to read a few thousand cells would be wasteful.',
          ],
        ]}
        caption="Both paths share the same regridding and derived-field code, so a feature means the same thing whichever way it was obtained. That is train/serve parity enforced by construction rather than by discipline."
      />

      <h2 id="grid">The common grid</h2>
      <p>
        Everything is interpolated onto a regular 0.25° latitude/longitude grid. That is the
        biogeochemistry product's native resolution — the coarsest real input — so the operation
        is a genuine downsample of the fine physics rather than an invented upsample of
        biogeochemistry. Inventing resolution you do not have is a way of manufacturing
        confidence you have not earned.
      </p>
      <p>
        Cell centres are snapped to exact multiples of the resolution, so two regions built at the
        same resolution share cell boundaries exactly. Without that, the shared feature store
        would not actually be shareable.
      </p>
      <p>
        Interpolation is linear, and <strong>land stays NaN</strong> — there is no interpolation
        across a coastline. Linear is the right choice in the downsampling direction and stays
        honest in the other: it will not invent structure finer than the source had.
      </p>

      <h2 id="derived">Shared derived fields</h2>
      <p>
        Once everything is on the grid, the fields that both problems need get computed once,
        here, rather than twice and slightly differently in two pipelines:
      </p>
      <Table
        headers={['Field', 'Computed from', 'Meaning']}
        rows={[
          [<code>sst_gradient</code>, 'thetao', 'Frontal strength — how sharply temperature changes across space.'],
          [
            <code>chl_gradient</code>,
            'log(1 + chl)',
            'Chlorophyll front strength. Taken in log space, because chlorophyll spans orders of magnitude and a raw-unit gradient just tracks the local mean.',
          ],
          [<code>current_speed</code>, 'uo, vo', 'Magnitude of the surface current.'],
          [<code>okubo_weiss</code>, 'uo, vo', 'Separates eddy interiors from the strain-dominated filaments between them.'],
          [<code>relative_vorticity</code>, 'uo, vo', 'Sign distinguishes cyclonic from anticyclonic rotation.'],
          [<code>eddy_kinetic_energy</code>, 'uo, vo', 'Energy in the flow relative to the time-mean flow at each cell.'],
          [<code>wind_stress_magnitude</code>, 'eastward/northward_stress', 'Total force per unit area on the sea surface.'],
          [<code>upwelling_index</code>, 'observed wind stress', 'Bakun-style coastal upwelling index.'],
          [<code>ekman_pumping</code>, 'stress_curl', 'Open-ocean upwelling velocity.'],
          [<code>wind_speed</code>, 'eastward/northward_wind', '10 m wind speed.'],
          [<code>depth</code>, 'bathymetry', 'Seafloor depth, positive down.'],
          [<code>seafloor_slope</code>, 'depth', 'Gradient magnitude of the depth field.'],
          [<code>distance_to_coast</code>, 'elevation ≥ 0', 'Great-circle distance to the nearest land cell.'],
        ]}
      />
      <p>
        The physics behind each of these is explained in the{' '}
        <Link to="/docs?c=features">feature engineering chapter</Link>. What matters here is{' '}
        <em>when</em> they are computed.
      </p>

      <Callout kind="warn" title="Ordering matters, and getting it wrong is silent">
        <p>
          For the point-sampling path, derived fields are computed <strong>on the grid, before
          sampling</strong> — never from the sampled values afterwards. A spatial gradient or an
          Okubo–Weiss parameter is a property of a field's <em>neighbourhood</em>; it simply
          cannot be recovered from an isolated point. Computing it after sampling would produce a
          different, wrong feature under the same name, and the two pipelines would silently
          disagree.
        </p>
      </Callout>

      <h2 id="quality">Data quality as a feature, not a cleanup step</h2>
      <p>
        Every row carries a <code>data_quality</code> column: the fraction of core ocean variables
        (thetao, so, chl, uo, vo) actually present, rather than gap-filled.
      </p>
      <p>
        This is a feature, deliberately, not something silently imputed away. A prediction
        standing on three gap-filled inputs should be able to say so, and the model can learn to
        condition its own confidence on it. Rows with <em>no</em> ocean variable at all are land
        or outside coverage, and those are dropped — keeping them would just be a hole in every
        downstream feature.
      </p>

      <h2 id="merge-guard">A guard that caught a real failure mode</h2>
      <p>
        Merging the source grids uses an inner join on time, which silently truncates to the
        shortest input. A half-finished wind fetch would therefore shrink the entire feature store
        down to the wind window — and still look like a successful build. The model would train on
        a fraction of the intended record with nothing to indicate it.
      </p>
      <Code>{`core_steps = len(np.intersect1d(physics_grid["time"], bgc_grid["time"]))
if merged.sizes["time"] < core_steps:
    raise FusionError(
        f"merging dropped {core_steps - merged.sizes['time']} of {core_steps} "
        "timesteps. An optional covariate (wind?) covers a shorter period than "
        "physics/bgc — re-fetch it for the full window, or pass wind=None."
    )`}</Code>
      <p>
        The reference is the physics-and-biogeochemistry overlap, which defines the ocean-state
        record we intend to model. An optional covariate is not allowed to shorten it.
      </p>

      <h2 id="feature-store">The feature store</h2>
      <p>
        The built table is written once to Parquet and reused. Rebuilding the HAB feature table
        costs about 7 minutes, so caching it means re-runs go straight to training. Passing{' '}
        <code>--refresh-features</code> forces a rebuild.
      </p>

      <h3>Memory: why every column is float32</h3>
      <p>
        The HAB feature table is roughly 3.9 million rows × 151 columns. At float64 that is
        ~4.7 GB for <em>one</em> copy — and scikit-learn's <code>ColumnTransformer</code> plus
        LightGBM each make more. On a 9 GB machine that is an out-of-memory kill with no
        traceback.
      </p>
      <p>
        So numeric columns are downcast to float32 on write and again on read. float32 carries
        about 7 significant digits; these are geophysical measurements good to 3–4 digits at
        best, so the precision lost is far below the measurement error already in the data.
        Peak memory went from ~9 GB to ~2.5 GB.
      </p>

      <h3>Downcasting on read is not enough</h3>
      <p>
        For a while the store on disk was still float64 — it predated the downcast being wired
        into the write path, and the read path compensated. But it compensated{' '}
        <em>after</em> <code>read_parquet</code> had already materialised the full-width table,
        so every experiment still paid the doubled peak the downcast exists to avoid. Rewriting
        the file once removed that permanently:
      </p>
      <Table
        headers={['', 'Before', 'After']}
        numeric={[1, 2]}
        rows={[
          ['File on disk', '2.80 GB', '1.59 GB'],
          ['Full read, peak memory', '~7 GB', '2.82 GB'],
          ['20-of-151-column read', '3.5 s / 2.82 GB', '0.1 s / 1.08 GB'],
        ]}
      />
      <p>
        That last row is the one that changes day-to-day work. Parquet is columnar, so asking
        for 20 of 151 columns reads about 13% of the file rather than all of it — and an
        experiment usually wants a handful of features, not the whole matrix. Selecting columns
        <em> after</em> the read returns an identical frame while paying the full cost, which is
        why the projection is pushed down into Parquet and why the test asserts on what Parquet
        was asked for rather than on the frame that comes back.
      </p>
      <p>
        The rewrite itself streams row group by row group and casts with Arrow rather than
        pandas, for the obvious reason: loading 3.9M × 151 float64 values in order to downcast
        them would need exactly the peak being removed.
      </p>

      <Callout kind="note" title="Two exceptions, both deliberate">
        <ul>
          <li>
            <strong>Coordinates stay float64.</strong> Everything downstream groups on latitude
            and longitude — climatology, spatial blocks, per-cell lags. float32 rounding could
            make two rows of the same grid cell compare unequal and silently split one cell into
            two groups.
          </li>
          <li>
            <strong>Pandas nullable integer columns become float32.</strong> A single{' '}
            <code>Int8</code> column makes <code>ColumnTransformer</code> fall back to{' '}
            <code>object</code> dtype for the <em>entire</em> concatenated matrix, which is far
            larger and far slower than the float32 it should be. Missing values land as NaN,
            which LightGBM handles natively anyway.
          </li>
        </ul>
      </Callout>

      <h2 id="depth-gotcha">A gotcha worth knowing about</h2>
      <p>
        Surface-level Copernicus datasets carry a scalar <Term>depth coordinate</Term> at
        slightly different float precision between products — 0.494025 in one, 0.49402538 in
        another. <code>xarray.merge</code> treats that as a conflict, which broke every mixed
        physics + biogeochemistry request until the depth coordinate was dropped after the
        surface level is selected. It is the kind of bug that looks like nonsense until you print
        the coordinate to full precision.
      </p>
    </>
  );
}
