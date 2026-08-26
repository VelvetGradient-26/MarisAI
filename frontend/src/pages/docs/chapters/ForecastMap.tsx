/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Code, Table } from '../primitives';

export function ForecastMap() {
  return (
    <>
      <p className="docs-article__eyebrow">Forecasting engine</p>
      <h1>The same engine, drawn as a map</h1>
      <p className="docs-article__lede">
        A point forecast answers "what happens here". A field answers "where is something about
        to happen", which is a different and usually more useful question. The forecast map runs
        the identical pipeline over a global grid and renders the result as a raster layer on{' '}
        <Link to="/map">the map</Link> — the same models, the same features, the same code path,
        with the network replaced by an in-memory slice.
      </p>

      <h2 id="two-modes">Two modes, and only one of them is interesting</h2>
      <Table
        headers={['Mode', 'What it draws', 'Why']}
        rows={[
          ['Absolute', 'The predicted field itself.', 'Reads like the observation layer it forecasts. Familiar, and largely redundant.'],
          [
            'Change',
            'Forecast minus the latest observation.',
            'The informative one. At +7 days the absolute field looks almost exactly like today\'s, so the signal is entirely in the difference.',
          ],
        ]}
      />
      <p>
        The change ramp is diverging and must stay symmetric around zero, or "no change" drifts
        off the neutral colour and the map starts implying a trend that is not there.
      </p>

      <h2 id="same-path">The grid path is the point path</h2>
      <p>
        This is the design decision the whole feature rests on. The gridded builder does{' '}
        <strong>not</strong> have its own feature engineering. Its history stack exposes a
        per-cell slice in exactly the shape the point path's fetcher returns, and the cell loop
        then calls the same build → clean → featurise chain that a single-point forecast calls.
      </p>
      <Callout kind="warn" title="Why there is deliberately no grid-native feature builder">
        <p>
          A vectorised, grid-aware reimplementation of the feature engineering would be much
          faster — and it is exactly how train/serve skew gets in. The model was fitted on
          features produced by one code path; if the map produces them by another, the two will
          agree at first and drift apart at the first change to either.
        </p>
        <p>
          A 40,000-cell loop is precisely where the temptation to write one is strongest, so the
          test that compares both paths cell-for-cell on identical synthetic inputs is what makes
          optimising the loop safe to attempt at all. They agree to 1e-6.
        </p>
      </Callout>

      <h2 id="fetch">The fetch is inverted</h2>
      <p>
        This is a third access pattern the platform did not previously have. The downloader asks
        for one bounded area over many timesteps; the map tiles ask for the whole globe at one
        timestep. A gridded forecast needs <em>the whole globe over many timesteps</em>, which is
        the expensive corner of that space.
      </p>
      <p>
        Copernicus publishes two zarr services with opposite chunking, and picking the wrong one
        turns a ten-second read into hours. The geo-series service stores one global timestep per
        chunk, which is right here; the time-series service would touch every spatial chunk on
        the planet. Striding to the output resolution happens while the array is still lazy,
        which is not an optimisation but a requirement: a global 0.083° float64 field is about
        70 MB per timestep per variable, so 45 timesteps of two variables at full resolution is
        over 6 GB.
      </p>

      <h2 id="cost">What it costs, and what does not change it</h2>
      <Table
        headers={['Stage', 'Cost', 'Scales with output resolution?']}
        rows={[
          ['Fetch', '~1080 whole-globe reads, ~35 min', 'No'],
          ['Cell loop', '~15 min at 1° (22 ms/cell × ~42,000 cells)', 'Yes'],
        ]}
      />
      <p>
        The consequence is worth internalising before anyone tunes it: <strong>cost is dominated
        by the fetch, and the fetch does not care about the output resolution.</strong> Passing{' '}
        <code>--resolution 4.0</code> speeds up the loop and nothing else. Reads are disk-cached
        for six hours and shared across every variable drawing on the same dataset, so building
        several variables together is far cheaper than building them one at a time.
      </p>
      <Callout kind="note" title="A 40× cheaper option was measured and deliberately not taken">
        <p>
          Daily Copernicus products exist and would cut the fetch dramatically. Adopting them
          would also make the dataframe builder's inner join collapse hourly wind onto a daily
          axis — turning wind speed from a 24-hour mean into one instantaneous value, silently,
          for every model that uses it as a covariate. That has to be solved first.
        </p>
      </Callout>

      <h2 id="gaps">Some variables can never be gridded</h2>
      <p>
        Open-Meteo is a point API capped at 900 points, so <code>air_temperature</code> — itself
        a trained variable, and a covariate of sea surface temperature — has no global field and
        never will through this route. The builder states this rather than absorbing it:
      </p>
      <ul>
        <li>
          An ungriddable <strong>target</strong> is skipped before paying for any fetch, with the
          reason recorded.
        </li>
        <li>
          An ungriddable <strong>covariate</strong> is recorded in the grid file's{' '}
          <code>missing_covariates</code> attribute and surfaced in the layer's attribution —
          because LightGBM routes an absent feature down its missing-value branch without
          complaint, and the resulting map would otherwise look exactly as confident as a
          complete one.
        </li>
      </ul>

      <h2 id="legend">The legend lives in the data file</h2>
      <p>
        Display bounds and the change scale are computed at build time as robust percentiles
        rounded outward, and stored as attributes on the grid itself. The tile renderer and the
        frontend legend both read them from there, so they cannot disagree about what a colour
        means — a legend that describes a different scale than the pixels is a quietly wrong map,
        not a cosmetic bug.
      </p>
      <p>
        Sea surface temperature is colour-matched to the existing observation layer, because
        comparing the forecast against observed SST is the first thing anyone does with it.
      </p>

      <h2 id="registration">Layers appear without a frontend edit</h2>
      <p>
        A forecast layer exists only where a model is trained <em>and</em> its grid has been
        built, which is not knowable at build time. So these layers are not in the static layer
        registry: the map fetches the forecast tile catalog at runtime and registers whatever it
        finds. A newly built grid becomes a map layer with no code change.
      </p>
      <Code>{`python scripts/build_forecast_grid.py --variable chlorophyll_a --resolution 1.0`}</Code>
      <p>
        Grids are rebuilt by a twice-daily scheduled job that skips anything already fresh, and{' '}
        <code>save_grid</code> writes only after a successful build — so a failed rebuild leaves
        the previous grid in place rather than blanking the layer.
      </p>
      <Callout kind="lesson" title="The build must run off the event loop, and a timing test would not catch it">
        <p>
          Everything past the fetch — the cell loop, inference, assembly — is roughly 15 minutes
          of CPU with no await in it, and the scheduler starts it at boot. Awaited inline, it
          stalls every request on the process for that entire window, which presents as an API
          that mysteriously dies twice a day rather than as an error.
        </p>
        <p>
          The test asserts on the <em>thread</em> the work runs on, not on how long it takes,
          because the synthetic stack used in tests builds in milliseconds — any timing-based
          check would pass happily with the work back on the event loop.
        </p>
      </Callout>

      <h2 id="vectors">Forecast particles are a second, separate case</h2>
      <p>
        Everything above is the <em>scalar</em> grid — one raster, one legend, one colour per
        cell. A forecast of a moving field (wind, currents) is drawn a different way entirely:
        as forecast particles, the same GPU particle layer the live wind and currents already
        use, built once both a variable's eastward and northward components are trained{' '}
        <em>and</em> gridded. It registers at runtime exactly like the scalar layers do, from a
        separate vector catalog endpoint, so a newly-trained pair becomes a map layer with no
        frontend edit either.
      </p>
      <p>
        These land in the stackable <strong>Wind &amp; Currents</strong> group, not the
        exclusive one the scalar forecasts use — deliberately, because the point of a forecast
        particle layer is running it <em>alongside</em> its live counterpart and watching where
        the two disagree, which only works if both can be on screen at once.
      </p>
      <Callout kind="lesson" title="Every forecast pair used to be drawn as currents, and it looked fine">
        Before the wind components were trained, the vector layer had only ever drawn currents,
        so every forecast pair — including an early wind forecast — inherited the currents
        ramp and speed scale. An 8 m/s wind field on a ramp whose domain tops out at 2 m/s
        renders as one flat top colour, and at the currents speed scale it advects roughly
        265 px/s. Both failures animate convincingly: a wrong legend and a wrong pace each look
        exactly like a working layer, which is the same hazard the scalar grids solve with
        hatching for a different kind of wrongness. The fix was a lookup keyed on the pair
        itself, so a forecast field is always drawn with its own live layer's identity — never
        an unrelated one's.
      </Callout>
      <p>
        Direction still has to be handled as an angle end to end (see{' '}
        <em>Directions &amp; colour</em>) — which is exactly why these are forecast{' '}
        <em>components</em> rather than a forecast bearing: a model trained on the raw compass
        change treats a five-degree veer across north as a 355° swing, an error these particle
        layers were built to avoid inheriting.
      </p>
    </>
  );
}
