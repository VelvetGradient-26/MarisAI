/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Formula, Table, Term } from '../primitives';

export function DashboardCharts() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean intelligence dashboard</p>
      <h1>Charts &amp; historical coverage</h1>
      <p className="docs-article__lede">
        Ten variables can be charted at any coordinate, over windows from 24 hours to 10 years.
        But the available window differs enormously between them — one reaches back to 1940 and
        another only to 2024 — and that is a property of the underlying products, not a
        limitation of the interface. This chapter explains each variable and why its range
        buttons are what they are.
      </p>

      <h2 id="ranges">Why some range buttons are greyed out</h2>
      <p>
        Every product has a <Term>coverage start</Term> — the earliest date it can serve. Ask
        for ten years of a product that began in 2024 and there is no honest answer, so the
        dashboard disables that button and explains why on hover, rather than returning a chart
        that silently begins three-quarters of the way along.
      </p>
      <Table
        headers={['Variable', 'Source', 'Data from', 'Longest range']}
        rows={[
          ['Wind speed', 'ERA5 reanalysis', '1940', '10 years'],
          ['Air temperature', 'ERA5 reanalysis', '1940', '10 years'],
          ['Surface pressure', 'ERA5 reanalysis', '1940', '10 years'],
          ['Wave height', 'Open-Meteo marine', '2022', '1 year'],
          ['Current velocity', 'Open-Meteo marine', '2022', '1 year'],
          ['Sea level (MSL)', 'Open-Meteo marine', '2023', '1 year'],
          ['Sea surface temperature', 'Open-Meteo marine', '2024', '1 year'],
          ['Chlorophyll-a', 'Copernicus BGC', '2021', '1 year'],
          ['Sea surface salinity', 'Copernicus physics', '2022', '1 year'],
          ['Ocean heat content', 'Copernicus physics', '2022', '1 year'],
        ]}
      />

      <Callout kind="jargon" title="Jargon buster — why the atmosphere has a longer memory">
        <p>
          Weather has been recorded systematically for over a century, and ERA5 reconstructs
          the global atmosphere back to 1940 by feeding every historical observation into a
          modern weather model. Air temperature and pressure have deep archives because people
          have been measuring them for a very long time.
        </p>
        <p>
          Operational <em>ocean</em> models are far younger. Global ocean forecasting at this
          resolution only became routine in the last few years, so the marine records start in
          the 2020s. It is not that the ocean was not there — it is that nobody was modelling
          it globally, daily, at 9 km.
        </p>
      </Callout>

      <h2 id="daily-only">Why chlorophyll, salinity and heat content have no 24-hour view</h2>
      <p>
        Those three come from daily-mean products: one value per day, per location. A 24-hour
        window would contain a single point, which is not a chart. The button is therefore
        disabled, and the shortest offered range is 7 days.
      </p>

      <Callout kind="lesson" title="These three were nearly declared impossible">
        <p>
          An earlier version of this dashboard marked chlorophyll, salinity and ocean heat
          content as permanently unavailable, on the assumption that no point-in-time source
          responded fast enough for an interactive chart.
        </p>
        <p>
          That assumption was never measured, and it was wrong. A one-year daily series costs
          about 7–13 seconds from the Copernicus time-series store — slow for a chart, but
          entirely workable behind a cache. Assuming instead of testing cost three real charts.
        </p>
      </Callout>

      <h2 id="ohc">Ocean heat content: the one that is computed, not fetched</h2>
      <p>
        Nine of the ten variables are read from a provider. Ocean heat content is not published
        by anyone at this resolution — it is derived here from a temperature profile.
      </p>
      <p>
        <strong>What it means.</strong> Sea surface temperature describes a thin skin. Ocean
        heat content describes the whole upper column: how much thermal energy is stored in the
        water beneath each square metre of sea surface. It is the better measure of whether the
        ocean is genuinely accumulating heat, because a warm surface can be a passing condition
        while a warm 700-metre column cannot.
      </p>
      <Formula
        expr="OHC = ρ · cₚ · ∫₀⁷⁰⁰ T(z) dz"
        where={
          <>
            ρ = 1025 kg/m³ (seawater density), cₚ = 3985 J/(kg·K) (specific heat capacity),
            T(z) = temperature at depth z, integrated from the surface to 700 m — the standard
            reference depth for upper-ocean heat content. Reported in GJ/m².
          </>
        }
      />
      <p>
        In practice the model supplies about 33 depth levels between 0.5 m and 644 m, unevenly
        spaced, and the integral is evaluated over them by the trapezoidal rule. Typical values
        in tropical water are 40–45 GJ/m². For intuition: a 700 m column at a uniform 15 °C
        works out to 42.9 GJ/m² — roughly the energy in 1,200 litres of petrol, stored under
        every single square metre of sea.
      </p>

      <Callout kind="note" title="Below the seafloor there is no water">
        <p>
          In shallow water the model has valid temperatures for only the top few levels and
          reports nothing below the seabed. Where fewer than two levels are usable, the chart
          reports no value rather than integrating a stub of a column and presenting the result
          as a heat content.
        </p>
      </Callout>

      <h2 id="aggregation">Daily means versus daily maxima</h2>
      <p>
        When an hourly series is compressed to daily points, the choice of summary matters and
        is made per variable:
      </p>
      <ul>
        <li>
          <strong>Maximum</strong> for wave height and wind speed. For these the peak is the
          point — a day whose average wave was 2 m but which peaked at 8 m was a dangerous day,
          and an average would erase that.
        </li>
        <li>
          <strong>Mean</strong> for temperature, pressure, salinity and the rest, where the
          typical condition is what the chart is about.
        </li>
      </ul>

      <h2 id="reading">Reading a chart</h2>
      <Table
        headers={['Element', 'What it tells you']}
        rows={[
          ['Header range', 'Minimum, maximum and mean across the visible window'],
          ['Coloured figure, top right', 'Net change from the first point to the last'],
          ['Hovering', 'Exact value and timestamp at that point'],
          ['Download icon', 'CSV export, including a header naming the source and window'],
          ['Image icon', 'PNG export of the chart as displayed'],
          ['Footer', 'The provider, the resolution served, and the number of points'],
        ]}
      />

      <Callout kind="warn" title="A ten-year chart is not a climate trend">
        <p>
          These are single-point series, and a decade at one coordinate is dominated by weather
          and natural variability. The "+2.90 hPa" style figure in the corner is the change
          between two individual endpoints — not a fitted trend, and not evidence of long-term
          change at that location.
        </p>
        <p>
          For questions about change over time, the anomaly figure on the temperature indicator
          — measured against a 28-year climatology — is the more meaningful number.
        </p>
      </Callout>
    </>
  );
}
