/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Link } from '../../../app/router';
import { Callout, Formula, Table, Term } from '../primitives';

export function DashboardMetrics() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean intelligence dashboard</p>
      <h1>The six indicators, explained</h1>
      <p className="docs-article__lede">
        Six numbers sit at the top of the dashboard. Each one compresses a global dataset into
        a single figure, and each compression throws something away. This chapter explains what
        every indicator physically means, exactly how it is computed, and — the part usually
        left out — what it deliberately excludes and why.
      </p>

      <h2 id="sst">1. Global mean sea surface temperature</h2>
      <p>
        <strong>What it is.</strong> The average temperature of the ocean's surface, across the
        whole planet, right now. Typical values sit between 18 °C and 20 °C. That may sound
        cold for "the sea", but it is an average over everything — tropical water at 30 °C and
        polar water near freezing included.
      </p>
      <p>
        <strong>How it is measured.</strong> Not with thermometers. It comes from the Copernicus
        Marine global analysis model, which assimilates satellite infrared measurements, ship
        and buoy readings, and Argo float profiles into a single physically consistent grid at
        1/12° resolution — roughly 9 km per cell, about 6 million ocean cells in total.
      </p>
      <p>
        <strong>"Surface" means 0.49 metres.</strong> The model's shallowest layer is centred
        just under half a metre down. That is what this figure reports.
      </p>

      <Callout kind="jargon" title="Jargon buster — what is an anomaly?">
        <p>
          The card also shows a figure like <strong>+1.00 °C vs baseline</strong>. That is an
          {' '}<Term>anomaly</Term>: not the temperature, but the difference between today's
          temperature and what is <em>normal for this date</em>.
        </p>
        <p>
          Normal is defined by a <Term>climatology</Term> — an average built from decades of
          past observations. Ours comes from NOAA and covers 1985–2012. So "+1.00 °C" means
          the ocean is a full degree warmer than the 1985–2012 average for early August.
        </p>
        <p>
          Anomalies matter more than raw temperatures for spotting change, because they remove
          the seasons. The ocean is always warmer in August than in February; an anomaly tells
          you whether it is warmer <em>than August should be</em>.
        </p>
      </Callout>

      <h2 id="chlorophyll">2. Mean chlorophyll-a</h2>
      <p>
        <strong>What it is.</strong> Chlorophyll-a is the green pigment in <Term>phytoplankton</Term>
        {' '}— microscopic drifting plants that form the base of nearly every marine food web.
        Measuring it is the standard way to estimate how much plant life the surface ocean is
        carrying. Global means sit around 0.2–0.3 mg/m³.
      </p>
      <p>
        <strong>Why it is worth watching.</strong> Chlorophyll is a proxy for food. Where it
        rises, fish and the animals that eat them usually follow. Sudden spikes can also signal
        a <Term>harmful algal bloom</Term> — an overgrowth that strips oxygen from the water
        and can produce toxins.
      </p>
      <p>
        <strong>How it is measured.</strong> From the Copernicus biogeochemistry model, at 1/4°
        resolution (~28 km), which combines satellite ocean-colour observations with a model of
        plankton growth. Satellites infer chlorophyll from the colour of the sea: water rich in
        phytoplankton reflects proportionally more green and less blue.
      </p>

      <Callout kind="note" title="Why the chlorophyll figure covers fewer cells">
        <p>
          The biogeochemistry grid is coarser than the physics grid — about 680,000 ocean cells
          against 6 million. Both cover the whole ocean; the chlorophyll one just does it in
          bigger squares. That is a property of the source product, not a gap in coverage.
        </p>
      </Callout>

      <h2 id="currents">3. Mean surface current speed</h2>
      <p>
        <strong>What it is.</strong> How fast the top layer of the ocean is moving, averaged
        globally. Typical value: about 0.23 m/s — a slow walk. But the average hides the
        interesting part, so the card also shows the 99th percentile and the maximum.
      </p>
      <p>
        <strong>How it is computed.</strong> Ocean models store currents as two components:
        {' '}<code>uo</code> (eastward) and <code>vo</code> (northward). Speed is the length of
        that arrow:
      </p>
      <Formula
        expr="speed = √(uo² + vo²)"
        where={
          <>
            computed per grid cell <em>before</em> averaging. Averaging the components first
            would let an eastward current and a westward one cancel to zero, reporting a
            still ocean where there is a fast one.
          </>
        }
      />
      <p>
        The strongest surface currents on Earth — the Gulf Stream, the Kuroshio, the Agulhas —
        reach 2–3 m/s. Those show up in the maximum, not the mean.
      </p>

      <h2 id="heat-stress">4. Marine heat stress regions</h2>
      <p>
        <strong>What it is.</strong> A count of distinct areas of ocean that are currently
        unusually hot — specifically, at least 1 °C hotter than the warmest month they normally
        reach.
      </p>
      <p>
        <strong>How a "region" is defined.</strong> The grid is scanned for cells over that
        threshold, touching cells are grouped into one region, and groups smaller than eight
        cells (~100,000 km²) are discarded as noise. Regions crossing the 180° meridian are
        merged so a single patch is not counted twice.
      </p>

      <Callout kind="lesson" title="The threshold we started with was useless">
        <p>
          The obvious definition — "sea surface temperature at least 1 °C above the climatology"
          — flagged <strong>42% of the entire ocean</strong>. A measure that describes nearly
          half the planet tells you nothing about where to look.
        </p>
        <p>
          The version now in use is NOAA's own <Term>HotSpot</Term> criterion: temperature above
          the <em>maximum monthly mean</em> — the warmest that location normally gets in any
          month of the year, not merely warmer than today's average. That flags about 13% of
          the tracked ocean, and correctly reports near-zero across the Southern Ocean in its
          winter, which the first version did not.
        </p>
      </Callout>

      <Callout kind="warn" title="This is not the formal definition of a marine heatwave">
        <p>
          Scientists define a marine heatwave (Hobday et al., 2016) as temperatures above the
          90th percentile of the local climatology, sustained for at least five consecutive
          days. That needs a full statistical distribution per location, which the source data
          does not publish.
        </p>
        <p>
          What this card shows is a defensible, published heat-stress criterion — but it is a
          different quantity, and the card says so in its scope note. Do not cite it as a
          marine-heatwave count.
        </p>
      </Callout>

      <h2 id="bleaching">5. Coral bleaching risk</h2>
      <p>
        <strong>What bleaching is.</strong> Corals live in partnership with algae inside their
        tissue, which feed them and give them colour. When water stays too warm for too long,
        the coral expels the algae, turns white, and begins to starve. Brief stress is
        survivable. Prolonged stress kills reefs.
      </p>
      <p>
        <strong>How it is measured — degree heating weeks.</strong> Bleaching depends on heat
        <em> accumulated over time</em>, not peak temperature. NOAA's <Term>degree heating
        weeks</Term> (DHW) metric adds up how far above the local bleaching threshold the water
        has been over the previous 12 weeks.
      </p>
      <Formula
        expr="DHW = Σ (temperature above the bleaching threshold) × (weeks at that excess)"
        where={<>units are "°C-weeks". Four weeks at 1 °C over gives DHW = 4, as does one week at 4 °C over.</>}
      />
      <Table
        headers={['DHW', 'What NOAA expects', 'Alert level']}
        rows={[
          ['0', 'No accumulated stress', 'No Stress'],
          ['0–4', 'Possible stress, bleaching unlikely', 'Watch / Warning'],
          ['4–8', 'Significant bleaching likely', 'Alert Level 1'],
          ['8+', 'Severe bleaching and mortality likely', 'Alert Level 2'],
        ]}
        numeric={[0]}
      />
      <p>
        The card reports <strong>Low</strong>, <strong>Moderate</strong> or <strong>High</strong>
        {' '}based on how much reef water sits at DHW ≥ 4: under 1% is Low, 1–5% Moderate, above
        5% High.
      </p>

      <Callout kind="lesson" title="Why this is restricted to 30°S–30°N">
        <p>
          NOAA computes DHW for every water pixel it has, including places where the number is
          meaningless. Taken globally, the highest values on Earth came from the St. Lawrence
          estuary, the Caspian Sea and the Gulf of Finland at 40–52 °C-weeks — physically
          impossible for reefs, and thousands of kilometres from the nearest coral.
        </p>
        <p>
          Reef-building corals live in warm, shallow, tropical water. Restricting the statistic
          to 30°S–30°N brings the maximum back to a plausible ~26 °C-weeks in the central
          Pacific, which is where a severe bleaching event actually is. This is a latitude
          approximation for reef distribution, not a true reef map, and the card says so.
        </p>
      </Callout>

      <h2 id="habitat">6. Fish habitat suitability</h2>
      <p>
        <strong>What it is.</strong> The output of MarisAI's own machine-learning model, which
        estimates how suitable the water is for a given fish species — a 0-to-1 score where
        higher means more suitable. The card shows the mean score for yellowfin tuna in the
        current month.
      </p>
      <p>
        <strong>How the model works.</strong> It is a <Term>species distribution model</Term>
        {' '}trained on real occurrence records from OBIS — places and times where the species was
        actually observed — against the ocean conditions there. It learns which combinations of
        temperature, chlorophyll, depth and other variables the species is associated with.
        Measured skill is ROC-AUC 0.959 and TSS 0.826.
      </p>

      <Callout kind="warn" title="This one is regional, not global">
        <p>
          Unlike the other five cards, this model covers the <strong>north Indian Ocean only</strong>
          {' '}(55–95°E, 5°S–25°N), because that is where the training occurrence data supports it.
          It is not a global index and the card labels it accordingly.
        </p>
        <p>
          The full modelling methodology — training windows, validation strategy, leakage
          controls and honest limitations — is documented in the
          {' '}<Link to="/docs?c=habitat">machine learning section</Link>.
        </p>
      </Callout>

      <h2 id="sparklines">The sparklines, and why they start empty</h2>
      <p>
        Each card carries a small trend line. On a freshly started server it reads "Collecting
        history…" instead, which is deliberate.
      </p>
      <p>
        None of these providers can answer "what was the global mean SST six hours ago" — they
        publish the current snapshot, not a history of global averages. So the dashboard records
        its own: every 15 minutes it stores the values it observed, keeping about 24 hours'
        worth. Those recorded points are the sparkline.
      </p>
      <p>
        The consequence is honest and worth knowing: <strong>this history does not survive a
        restart</strong>, and a server started ten minutes ago genuinely has nothing to plot.
        Drawing a flat line from a single reading would imply a stability that had not been
        observed, so the card says what it is doing instead.
      </p>
    </>
  );
}
