/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Code, Table, Term, VariableGrid } from '../primitives';

export function Data() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Every variable, and how we fetched it</h1>
      <p className="docs-article__lede">
        Five data sources: seventeen gridded ocean-state variables, a seafloor relief grid,
        species occurrence records — and a set of fetch decisions that are the difference between
        a pipeline that runs in minutes and one that never finishes. This chapter lists every
        input and explains what each one physically means.
      </p>

      <h2 id="sources">The four sources</h2>
      <Table
        headers={['Source', 'What it gives us', 'Access', 'Native resolution']}
        rows={[
          [
            <strong>Copernicus Marine — physics reanalysis</strong>,
            'Temperature, salinity, currents, sea surface height, mixed layer depth',
            <code>cmems_mod_glo_phy_my_0.083deg_P1D-m</code>,
            '1/12° (≈ 9 km), daily & monthly',
          ],
          [
            <strong>Copernicus Marine — biogeochemistry</strong>,
            'Chlorophyll, nutrients, oxygen, primary production',
            <code>cmems_mod_glo_bgc_my_0.25deg_P1D-m</code>,
            '1/4° (≈ 28 km), daily & monthly',
          ],
          [
            <strong>Copernicus Marine — L4 scatterometer wind</strong>,
            'Wind stress, stress curl, 10 m winds',
            <code>cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H</code>,
            '0.125°, hourly',
          ],
          [
            <strong>NOAA ERDDAP (ETOPO / GEBCO-class relief)</strong>,
            'Seafloor depth and elevation → slope, distance to coast',
            <>
              <code>etopo180</code> griddap endpoint
            </>,
            '≈ 15 arc-seconds, static',
          ],
          [
            <strong>OBIS</strong>,
            'Species occurrence records (Problem B labels + background pool)',
            <code>api.obis.org/v3/occurrence</code>,
            'Point records',
          ],
        ]}
      />

      <Callout kind="jargon" title="Jargon buster — reanalysis vs. near-real-time">
        <p>
          A <Term>reanalysis</Term> is a physics model of the ocean, run backwards over history
          with every observation available at the time assimilated into it. It produces a
          gap-free, physically consistent record of the past, reprocessed as one consistent
          product. That is what training needs.
        </p>
        <p>
          The <Term>near-real-time</Term> products the Maris AI map page uses are the opposite
          trade: fast and current, but only reaching back a couple of years and without the same
          consistency. The <code>_my_</code> in the dataset IDs above stands for "multi-year" —
          it is the reanalysis edition, and it is why the ML pipeline and the live map read from
          different products.
        </p>
      </Callout>

      <h2 id="physics">Physical ocean variables</h2>
      <p>
        Six variables from the physics reanalysis, all taken at the surface layer (~0.49 m
        depth).
      </p>
      <VariableGrid
        variables={[
          {
            name: 'thetao',
            unit: '°C — sea water potential temperature',
            description:
              'At the surface layer this is sea surface temperature. It sets metabolic rates for everything living in the water, defines fronts, and is the single most-used field in marine ecology.',
          },
          {
            name: 'so',
            unit: 'PSU — practical salinity',
            description:
              'How salty the water is. Distinguishes water masses: river-influenced coastal water, high-salinity Arabian Sea water, and monsoon-freshened surface layers are different habitats.',
          },
          {
            name: 'uo',
            unit: 'm/s — eastward current velocity',
            description:
              'The east–west component of surface current. Combined with vo it gives speed, vorticity and the eddy diagnostics.',
          },
          {
            name: 'vo',
            unit: 'm/s — northward current velocity',
            description:
              'The north–south component. Its sign near a coast also acts as a crude upwelling proxy when observed wind stress is unavailable.',
          },
          {
            name: 'zos',
            unit: 'm — sea surface height above geoid',
            description:
              'Where the sea surface bulges up or dips down. Highs and lows are the signature of eddies and of the large-scale circulation, and this turned out to be one of the habitat model\'s strongest predictors.',
          },
          {
            name: 'mlotst',
            unit: 'm — mixed layer thickness',
            description:
              'How deep the surface layer is that wind and waves keep well stirred. A shallow mixed layer traps phytoplankton in the sunlight (bloom-friendly); a deep one mixes them down into the dark.',
          },
        ]}
      />

      <h2 id="bgc">Biogeochemical variables</h2>
      <p>
        Six variables from the biogeochemistry reanalysis. This is <em>model</em>{' '}
        biogeochemistry, not satellite ocean colour, and that is a deliberate choice for the HAB
        problem: it is not cloud-limited, so it gives continuous daily coverage where satellite
        chlorophyll has holes — and the southwest monsoon, precisely when blooms happen, is
        exactly when the Arabian Sea is cloudiest.
      </p>
      <VariableGrid
        variables={[
          {
            name: 'chl',
            unit: 'mg/m³ — chlorophyll-a concentration',
            description:
              'The quantity Problem A forecasts, and the proxy for how much phytoplankton is in the water. Spans orders of magnitude, so it is usually handled in log space.',
          },
          {
            name: 'no3',
            unit: 'mmol/m³ — nitrate',
            description:
              'The nitrogen source that most commonly limits phytoplankton growth in these waters. A pulse of nitrate into the sunlit layer is the classic precursor to a bloom.',
          },
          {
            name: 'po4',
            unit: 'mmol/m³ — phosphate',
            description:
              'The other major macronutrient. Its ratio to nitrate is more informative than either level alone — see the Redfield ratio in the features chapter.',
          },
          {
            name: 'si',
            unit: 'mmol/m³ — silicate',
            description:
              'Diatoms build glass shells out of silicate; flagellates do not. When silicate runs out relative to nitrogen, the competitive advantage shifts toward the flagellates that dominate harmful blooms.',
          },
          {
            name: 'o2',
            unit: 'mmol/m³ — dissolved oxygen',
            description:
              'What fish breathe. The Arabian Sea has one of the world\'s most intense oxygen minimum zones, which compresses habitat vertically and is why this is a habitat feature, not just a bloom aftermath signal.',
          },
          {
            name: 'nppv',
            unit: 'mg/m³/day — net primary production',
            description:
              'The rate at which carbon is being fixed by photosynthesis — the productivity of the water, as opposed to chl which is the standing stock already there.',
          },
        ]}
      />

      <h2 id="wind">Wind and wind stress (Problem A only)</h2>
      <p>
        Five variables from an L4 reprocessed scatterometer wind product. Wind matters because it
        is the <em>forcing</em> — the mechanism that injects nutrients into the sunlit layer and
        starts a bloom in the first place.
      </p>
      <VariableGrid
        variables={[
          {
            name: 'eastward_stress',
            unit: 'Pa — zonal wind stress',
            description:
              'The eastward force per unit area the wind exerts on the sea surface. This is the direct driver of Ekman transport.',
          },
          {
            name: 'northward_stress',
            unit: 'Pa — meridional wind stress',
            description: 'The northward component of the same force.',
          },
          {
            name: 'stress_curl',
            unit: 'Pa/m — curl of the wind stress',
            description:
              'How much the stress field rotates in space. Positive curl in the northern hemisphere pushes surface water apart and pulls deep, nutrient-rich water up — open-ocean upwelling.',
          },
          {
            name: 'eastward_wind',
            unit: 'm/s — 10 m eastward wind',
            description:
              'Wind speed at 10 m above the sea. Fully populated even where the stress fields are masked, which is why it is kept alongside them.',
          },
          {
            name: 'northward_wind',
            unit: 'm/s — 10 m northward wind',
            description: 'The northward component of the 10 m wind.',
          },
        ]}
      />

      <Callout kind="note" title="Why observed stress instead of ERA5 winds">
        <p>
          The classic recipe is to take 10 m winds from ERA5 and convert them to stress with a
          bulk formula: <code>τ = ρ_air · C_d · |U| · U</code>. The problem is{' '}
          <code>C_d</code>, the drag coefficient — it is treated as a constant (1.3 × 10⁻³) but
          in reality varies with sea state and atmospheric stability. It is the least defensible
          number in the calculation.
        </p>
        <p>
          This Copernicus product serves scatterometer-derived stress <em>directly</em>, reachable
          with credentials we already have, with no drag-coefficient assumption entering at all.
          ERA5 would have meant a second account for a strictly worse version of the same
          covariate. (It remains the right source for things Copernicus does not carry —
          precipitation, air–sea heat flux.)
        </p>
      </Callout>

      <h3>The coverage caveat</h3>
      <p>
        The stress fields cover about 61% of grid cells, and the missing 39% is a{' '}
        <strong>fixed spatial mask</strong>, not scattered gaps — every cell is either always
        present or always absent. Daily averaging cannot repair that. The 10 m wind fields are
        fully populated, so rows without stress still carry wind speed, LightGBM handles the
        missing stress natively, and a <code>data_quality</code> column records the difference so
        the model can condition on it.
      </p>

      <h2 id="bathymetry">Bathymetry</h2>
      <p>
        NOAA's ERDDAP serves the same global relief grid GEBCO publishes, over plain HTTP with the
        bounding box in the URL and no account required. It returns <em>altitude</em> (positive
        up, so ocean is negative); we convert once, at ingestion, to depth in positive metres with
        land as NaN.
      </p>
      <VariableGrid
        variables={[
          {
            name: 'depth',
            unit: 'm, positive down',
            description:
              'Seafloor depth. Ecologically enormous — the shelf break at ~200 m separates two completely different worlds — and non-linear, which is why it also enters as log-depth and as a categorical bucket.',
          },
          {
            name: 'seafloor_slope',
            unit: 'm per degree',
            description:
              'How steeply the bottom drops away. Steep slopes and shelf breaks force water upward and are persistent aggregation features for fish.',
          },
          {
            name: 'distance_to_coast',
            unit: 'km',
            description:
              'Great-circle distance from each ocean cell to the nearest land cell. Derived from the elevation grid (land = elevation ≥ 0) rather than from gaps in the ocean fields, so a genuine data hole over water is never mistaken for a coastline.',
          },
        ]}
      />

      <h2 id="obis">OBIS occurrence records</h2>
      <p>
        The Ocean Biodiversity Information System is a global aggregator of marine species
        occurrence records — museum specimens, research surveys, tagging programmes, citizen
        science. Two distinct queries are made:
      </p>
      <ul>
        <li>
          <strong>Target species occurrences</strong> — records of the five modelled species.
          These become the positive class.
        </li>
        <li>
          <strong>The target group</strong> — every occurrence record for Actinopterygii
          (ray-finned fishes, OBIS taxon ID 10194) in the same region and window. These are{' '}
          <em>not</em> absences; they are the pool that pseudo-absences get drawn from. Why that
          matters is the core of the <Link to="/docs?c=habitat">habitat chapter</Link>.
        </li>
      </ul>
      <p>
        Practical details that cost real debugging time: OBIS caps a single response well below
        the size of these queries, so deep paging through the <code>after</code> cursor is
        mandatory — an un-paged call silently truncates. And <code>eventDate</code> is a
        heterogeneous free-text-ish field that sometimes carries ranges like{' '}
        <code>2013-02-01/2013-02-28</code>, so the parser takes the start of any range before
        parsing. Records without a usable latitude, longitude or date are dropped.
      </p>

      <h2 id="fetch-engineering">Fetch engineering: three things that are load-bearing</h2>
      <p>
        Getting these variables out of Copernicus is not a formality. Three decisions each turn a
        request that takes seconds into one that takes hours, or never completes.
      </p>

      <h3>1. Service choice: <code>arco-time-series</code>, never <code>arco-geo-series</code></h3>
      <p>
        Copernicus serves the same data through two Zarr services with opposite chunking.{' '}
        <code>arco-geo-series</code> stores huge latitude/longitude chunks with one timestep
        each — right for "the whole globe, latest snapshot", which is what map tile rendering
        needs. <code>arco-time-series</code> stores fine lat/lon chunks with huge time chunks —
        right for "one bounded area, many timesteps", which is exactly our access pattern.
      </p>
      <p>
        Pick the wrong one and the client effectively fetches the globe once per day of your
        range. The difference is seconds versus hours.
      </p>

      <h3>2. The depth bound must be server-side</h3>
      <p>
        These reanalysis products carry <strong>50 depth levels</strong>. Only the surface is
        ever used here. Passing <code>minimum_depth</code>/<code>maximum_depth</code> into{' '}
        <code>open_dataset</code> makes the server do the selection:
      </p>
      <Code>{`ds = copernicusmarine.open_dataset(
    dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",
    variables=["thetao", "so", "uo", "vo", "zos", "mlotst"],
    service="arco-time-series",          # bounded area, many timesteps
    minimum_longitude=68.0, maximum_longitude=78.0,
    minimum_latitude=6.0,   maximum_latitude=23.0,
    start_datetime="2016-01-01T00:00:00",
    end_datetime="2021-12-31T23:59:59",
    minimum_depth=0.0, maximum_depth=1.0,  # <- surface only, server-side
)`}</Code>
      <Callout kind="warn" title="Measured, not assumed">
        <p>
          With the depth bound, one representative request takes <strong>~63 seconds</strong>.
          Without it, the identical request <strong>did not complete in 15 minutes</strong>. This
          is specific to these 50-level reanalysis products — the near-real-time products the
          live map uses have a singleton depth dimension where a post-hoc{' '}
          <code>isel(depth=0)</code> is harmless.
        </p>
      </Callout>

      <h3>3. Hourly products must be downsampled inside the fetch loop</h3>
      <p>
        The only multi-year wind product is hourly. One calendar month of five variables over the
        Arabian Sea box is ~324 MB in memory and takes ~85 seconds. Six years fetched in one call
        would be ~7.8 GB held at once — to produce ~160 MB of daily means.
      </p>
      <p>
        So <code>fetch_wind</code> requests one calendar month, averages it to daily (skipping
        the swath-gap NaNs rather than letting one missing hour void the day), and only then
        requests the next month. Peak memory stays at one month regardless of window length.
      </p>

      <h2 id="timings">Measured fetch performance</h2>
      <Table
        headers={['Product', 'Request', 'Time']}
        numeric={[2]}
        rows={[
          ['physics 1/12° daily', '8×14° box, 30 days', '~63 s'],
          ['physics 1/12° daily', '10×17° box, 2 years', '~60 s'],
          ['physics 1/12° monthly', '40×30° box, 14 years', '~76 s'],
          ['bgc 1/4° daily', '10×17° box, 2 years', '~24 s'],
          ['bgc 1/4° monthly', '40×30° box, 14 years', '~34 s'],
          ['wind 1/8° hourly', '10×17° box, 1 month', '~85 s (324 MB)'],
        ]}
        caption="A full raw-zone fetch for both problems is about 4 minutes and 840 MB on disk. Everything is cached as NetCDF with the dataset ID, region, window and cadence written into the file attributes — these products get reprocessed periodically, so the dataset ID alone is not enough to reproduce a training run."
      />

      <h2 id="two-profiles">Two fetch profiles, and why they differ</h2>
      <Table
        headers={['', 'Problem B (habitat)', 'Problem A (HAB)']}
        rows={[
          ['Region', 'North Indian Ocean, 55–95°E / 5°S–25°N', 'Arabian Sea, 68–78°E / 6–23°N'],
          ['Cadence', 'Monthly', 'Daily'],
          ['Window', '2000–2013', '2016–2021'],
          ['Sources', 'physics, BGC, bathymetry, OBIS', 'physics, BGC, wind stress, bathymetry'],
          ['Constrained by', 'label availability', 'interannual variability'],
        ]}
        caption="Wind is HAB-only: the habitat pipeline runs on monthly means, where daily wind stress has no meaning. The fusion layer takes wind as an optional argument precisely so that omitting it changes nothing else about the resulting table."
      />
    </>
  );
}
