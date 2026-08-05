/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

export function DashboardSources() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean intelligence dashboard</p>
      <h1>Sources, satellites &amp; instruments</h1>
      <p className="docs-article__lede">
        Seven providers stand behind this page, drawing on satellites, moored buoys, physics
        models and one machine-learning pipeline of our own. This chapter lists every one:
        what it measures, which spacecraft or instrument does the measuring, the exact dataset
        identifier, its resolution and update cadence, and its licence.
      </p>

      <h2 id="how-measured">First: how do you measure an ocean?</h2>
      <p>
        Four fundamentally different methods feed this dashboard, and knowing which is which
        explains most of the differences you will see between panels.
      </p>
      <Table
        headers={['Method', 'How it works', 'Strength', 'Weakness']}
        rows={[
          [
            <strong>In-situ</strong>,
            'A physical instrument in the water — a moored buoy, a drifting float',
            'A real, direct measurement',
            'One point only; the ocean is mostly empty of instruments',
          ],
          [
            <strong>Satellite remote sensing</strong>,
            'A spacecraft measures radiation leaving the sea surface',
            'Global coverage, repeated daily',
            'Surface only; cloud blocks optical and infrared sensors',
          ],
          [
            <strong>Numerical model</strong>,
            'Physics equations solved forward in time on a grid',
            'Complete, gap-free, includes depth',
            'A simulation — as good as its physics and its inputs',
          ],
          [
            <strong>Reanalysis / analysis</strong>,
            'A model with observations continuously assimilated into it',
            'Physically consistent and observation-anchored',
            'Computationally heavy, so published with a lag',
          ],
        ]}
      />

      <Callout kind="jargon" title="Jargon buster — processing levels">
        <p>
          Satellite products are labelled by how much processing they have had.
        </p>
        <ul>
          <li><strong>Level 1</strong> — raw sensor readings, calibrated.</li>
          <li>
            <strong>Level 2</strong> — a geophysical quantity (temperature, chlorophyll) along
            the satellite's actual track, with gaps between passes and holes under cloud.
          </li>
          <li>
            <strong>Level 3</strong> — Level 2 resampled onto a regular map grid, still with
            gaps.
          </li>
          <li>
            <strong>Level 4</strong> — gaps filled by combining sensors and modelling, giving a
            complete map. Most products here are L4, which is why the map has no holes.
          </li>
        </ul>
      </Callout>

      <h2 id="copernicus">Copernicus Marine Service (EU)</h2>
      <p>
        The European Union's operational oceanography programme, and the single largest
        contributor to this dashboard. It runs a global ocean model, assimilating satellite and
        in-situ observations, and publishes the result as analysis (recent past) and forecast
        (near future). Access requires a free account; credentials stay server-side and never
        reach the browser.
      </p>
      <Table
        headers={['Dataset ID', 'Provides', 'Grid', 'Cadence']}
        rows={[
          [
            <code>cmems_mod_glo_phy_anfc_0.083deg_PT1H-m</code>,
            'Sea surface temperature, currents (uo/vo), salinity',
            '1/12° (~9 km)',
            'Hourly',
          ],
          [
            <code>cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m</code>,
            'Temperature through 50 depth levels — used for ocean heat content',
            '1/12°',
            'Daily',
          ],
          [
            <code>cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m</code>,
            'Salinity through depth',
            '1/12°',
            'Daily',
          ],
          [
            <code>cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m</code>,
            'Chlorophyll-a',
            '1/4° (~28 km)',
            'Daily',
          ],
          [
            <code>cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m</code>,
            'Dissolved oxygen',
            '1/4°',
            'Daily',
          ],
          [
            <code>cmems_mod_glo_wav_anfc_0.083deg_PT3H-i</code>,
            'Significant wave height',
            '1/12°',
            '3-hourly',
          ],
          [
            <code>WIND_GLO_PHY_L4_NRT_012_004</code>,
            'Surface wind — blended scatterometer and model',
            '0.125°',
            'Hourly',
          ],
        ]}
      />
      <p>
        <strong>Licence:</strong> Copernicus Marine licence — free, open and full access.
      </p>

      <Callout kind="lesson" title="The chunking choice that decides between 15 seconds and 15 minutes">
        <p>
          Copernicus publishes each dataset through two storage layouts, and picking the wrong
          one is the single most expensive mistake available here.
        </p>
        <ul>
          <li>
            <code>arco-geo-series</code> stores one timestep per chunk across a huge area — right
            for "the whole globe, right now", which is what the indicator cards need.
          </li>
          <li>
            <code>arco-time-series</code> stores a long time span per chunk over a small area —
            right for "one location, across years", which is what the charts need.
          </li>
        </ul>
        <p>
          Requesting a global snapshot through the time-series layout touches roughly 35,000
          tiny chunks and takes over ten minutes. The same data through the geo-series layout
          takes about twelve seconds. Both layouts are used on this dashboard, each for the
          access pattern it was built for.
        </p>
      </Callout>

      <h2 id="crw">NOAA Coral Reef Watch (USA)</h2>
      <p>
        The source of everything on this dashboard involving <em>how unusual</em> today is. It
        is the only integration carrying a real long-term climatology, which is what makes
        anomalies, heat stress and bleaching risk possible at all.
      </p>
      <Table
        headers={['Field', 'Meaning']}
        rows={[
          [<code>CRW_SST</code>, 'Sea surface temperature (CoralTemp v3.1)'],
          [<code>CRW_SSTANOMALY</code>, 'Difference from the 1985–2012 daily climatology'],
          [<code>CRW_HOTSPOT</code>, 'Excess above the warmest month normally reached'],
          [<code>CRW_DHW</code>, 'Degree heating weeks — accumulated heat stress'],
          [<code>CRW_BAA</code>, "Bleaching Alert Area — NOAA's own 0–4 category"],
          [<code>CRW_SEAICE</code>, 'Sea-ice fraction, used to mask polar cells'],
        ]}
      />
      <p>
        <strong>Underlying satellites:</strong> CoralTemp blends NOAA/NESDIS geostationary and
        polar-orbiting infrared sensors — the GOES series over the Americas, Himawari over the
        western Pacific, Meteosat over Africa and the Indian Ocean, plus AVHRR and VIIRS on
        polar orbiters. <strong>Grid:</strong> 0.05° (~5 km) native, sampled to 1° here.
        {' '}<strong>Cadence:</strong> daily, 1–2 days behind real time. <strong>Access:</strong>
        {' '}NOAA CoastWatch ERDDAP, no credentials. <strong>Licence:</strong> public domain.
      </p>

      <h2 id="ndbc">NOAA National Data Buoy Center (USA)</h2>
      <p>
        The only <em>direct physical measurements</em> on the dashboard. Roughly 880 moored
        buoys and coastal stations report water temperature, wave height, wind, air pressure
        and dew point. Everything else here is inferred from radiation or simulated by physics;
        these are instruments actually in the sea.
      </p>
      <p>
        The dashboard reads one file containing the newest report from every station, refreshed
        every 10 minutes. Missing readings are marked <code>MM</code> in the feed and become
        "no reading" — never zero, which would invent a calm sea or freezing water.
      </p>

      <Callout kind="note" title="Relative humidity is derived, not measured">
        <p>
          NDBC buoys report air temperature and <Term>dew point</Term> (the temperature at which
          air becomes saturated), not humidity directly. The dashboard converts them using the
          Magnus formula — a closed-form relationship, so this is a unit conversion rather than
          an estimate. Where a station reports no dew point, humidity is left blank.
        </p>
      </Callout>

      <Callout kind="warn" title="NDBC is a US network">
        <p>
          Coverage is dense around North America and thin elsewhere. Ask for the nearest buoy to
          a point in the Arabian Sea and the honest answer is often a station thousands of
          kilometres away — so the distance is always shown. A far-away buoy is not a local
          measurement, and the panel does not pretend otherwise.
        </p>
      </Callout>

      <h2 id="gibs">NASA GIBS — Global Imagery Browse Services (USA)</h2>
      <p>
        NASA's imagery service, used here to report which satellite products are current and
        how far behind real time each one is. Eleven ocean-relevant layers are tracked.
      </p>
      <Table
        headers={['Satellite / instrument', 'What it provides', 'Resolution']}
        rows={[
          [
            <><strong>Aqua / MODIS</strong> — NASA, launched 2002</>,
            'True-colour imagery, chlorophyll-a',
            '250 m / 1 km',
          ],
          [
            <><strong>Suomi NPP / VIIRS</strong> — NASA-NOAA, 2011</>,
            'True-colour imagery',
            '250 m',
          ],
          [
            <><strong>NOAA-21 / VIIRS</strong> — NOAA, 2022</>,
            'Chlorophyll-a',
            '1 km',
          ],
          [
            <><strong>PACE / OCI</strong> — NASA, 2024</>,
            'Chlorophyll-a from a hyperspectral ocean-colour instrument',
            '1 km',
          ],
          [
            <><strong>GHRSST MUR</strong> — multi-sensor blend</>,
            'Sea surface temperature and its anomaly',
            '1 km',
          ],
          [
            <><strong>GCOM-W1 / AMSR2</strong> — JAXA, 2012</>,
            'Sea ice concentration (microwave — sees through cloud)',
            '2 km',
          ],
          [
            <><strong>OSCAR</strong> — multi-mission</>,
            'Surface currents derived from altimetry and winds',
            '2 km',
          ],
        ]}
      />

      <Callout kind="note" title="Some rows say 'Stale', and that is real information">
        <p>
          The satellite table marks a product stale when its newest available date is more than
          a week old. Several tracked layers genuinely are: the AVHRR-OI temperature layer stops
          in 2020 and OSCAR currents in 2024, because those layers were retired upstream.
        </p>
        <p>
          That is worth surfacing rather than hiding. A stale row reflects the state of the
          NASA layer, not a fault in this dashboard.
        </p>
      </Callout>

      <h2 id="openmeteo">Open-Meteo (Germany)</h2>
      <p>
        A free weather API, used for the historical charts. Two of its models are queried: a
        marine model for waves, currents, sea level and sea surface temperature, and the
        {' '}<Term>ERA5</Term> reanalysis archive for wind, air temperature and pressure.
      </p>
      <p>
        ERA5 is the European Centre for Medium-Range Weather Forecasts' flagship reanalysis: a
        consistent hourly reconstruction of Earth's atmosphere from 1940 to the present. It is
        why the wind and air-temperature charts can show ten years while the ocean charts
        cannot.
      </p>
      <p>
        <strong>Licence:</strong> CC BY 4.0. <strong>Note:</strong> the free tier rate-limits,
        so the dashboard caches responses for ten minutes.
      </p>

      <h2 id="marisai">MarisAI ML exports (this project)</h2>
      <p>
        Two model outputs produced by our own offline pipeline: fish habitat suitability for
        five species across the north Indian Ocean, and harmful-algal-bloom probability for the
        Arabian Sea at 3, 5 and 7-day horizons. Both ship with measured skill scores, and both
        are regional. The full methodology is in the machine learning section of these docs.
      </p>

      <h2 id="summary">Everything, in one table</h2>
      <Table
        headers={['Provider', 'Method', 'Refresh here', 'Credentials']}
        rows={[
          ['Copernicus Marine', 'Model analysis + assimilation', '1–3 hours', 'Account required'],
          ['NOAA Coral Reef Watch', 'Satellite infrared composite', '6 hours', 'None'],
          ['NOAA NDBC', 'In-situ instruments', '10 minutes', 'None'],
          ['NASA GIBS', 'Satellite imagery catalogue', '6 hours', 'None'],
          ['Open-Meteo', 'Model + ERA5 reanalysis', 'On demand, cached 10 min', 'None'],
          ['MarisAI ML', 'Offline machine learning', 'On pipeline re-run', 'None'],
        ]}
      />
    </>
  );
}
