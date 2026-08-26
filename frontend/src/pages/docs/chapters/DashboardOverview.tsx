/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Link } from '../../../app/router';
import { Callout, Table, Term } from '../primitives';

export function DashboardOverview() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean intelligence dashboard</p>
      <h1>What the dashboard shows, and what it does not</h1>
      <p className="docs-article__lede">
        The dashboard exists to answer one question: what is happening in the world's oceans
        right now, what has changed, and what needs attention. This chapter explains how the
        page is organised and — more importantly — the one rule that governs every number on
        it. No background in oceanography or data science is assumed anywhere in this section.
      </p>

      <h2 id="rule">The rule: nothing is ever invented</h2>
      <p>
        A dashboard full of confident-looking numbers is easy to build if you are willing to
        make some of them up. Plenty of "ocean dashboards" do exactly that — a plausible
        temperature here, a filler percentage there — because an empty panel looks broken and
        a filled one looks finished.
      </p>
      <p>
        This one never does that. Every figure is computed from a real measurement or model
        output that was fetched from a named provider. When a source has not loaded, the panel
        says so and explains what it is waiting for. When a number is regional rather than
        global, or a proxy rather than the formal quantity it resembles, the card says that
        too — press the <strong>ⓘ</strong> icon on any indicator to see its exact scope.
      </p>

      <Callout kind="warn" title="Why this matters more here than on most dashboards">
        <p>
          People make decisions from ocean data. A fabricated coral-bleaching risk or an
          invented wave height is not a harmless placeholder — it is a false reading that can
          be screenshotted, forwarded, and acted on. An empty panel that explains itself is
          always better than a filled one that cannot be trusted.
        </p>
        <p>
          Nothing on this dashboard is suitable for navigation, and its alerts are not official
          marine warnings. See <Link to="/docs?c=dash-alerts">Alerts &amp; thresholds</Link>.
        </p>
      </Callout>

      <h2 id="sections">The nine sections</h2>
      <Table
        headers={['Section', 'The question it answers', 'How often it updates']}
        rows={[
          [
            <strong>Key indicators</strong>,
            'Six headline numbers about the global ocean today',
            'Every 5 minutes',
          ],
          [
            <strong>Ocean map</strong>,
            'Where things are — temperature, chlorophyll, wind, vessels, protected areas',
            'On interaction',
          ],
          [
            <strong>Live ocean feed</strong>,
            'What was measured most recently, by instruments in the water and satellites overhead',
            'Every minute',
          ],
          [
            <strong>AI insights</strong>,
            'A plain-language reading of conditions at one chosen point',
            'On request',
          ],
          [
            <strong>Alerts</strong>,
            'Which monitored thresholds are currently exceeded, and where',
            'Every 30 seconds',
          ],
          [
            <strong>Historical analytics</strong>,
            'What has changed at a chosen point, over hours to decades',
            'On demand',
          ],
          [
            <strong>Recent satellite products</strong>,
            'Which NASA imagery is current, and how far behind real time',
            'Every 15 minutes',
          ],
          [
            <strong>Data source status</strong>,
            'Whether each provider is reachable and how fresh its data is',
            'Every 5 minutes',
          ],
          [
            <strong>Data quality</strong>,
            'What every dataset actually is (resolution, cadence, coverage, licence) and how every trained forecast model scores',
            'Every 30 minutes',
          ],
        ]}
      />
      <Callout kind="note" title="Data source status and data quality answer different questions">
        The two provenance panels sit side by side but are not duplicates. Data source status
        asks "is the feed up right now" — a live health check. Data quality asks the question
        underneath it: what a dataset resolves to, how far each processing stage actually
        reaches, and — for every trained forecast model — its skill against persistence and the
        spread across validation folds, never a single invented confidence percentage.
      </Callout>

      <h2 id="global-vs-point">Global numbers versus point numbers</h2>
      <p>
        This trips people up, so it is worth stating plainly. The dashboard mixes two different
        kinds of quantity:
      </p>
      <ul>
        <li>
          <strong>Global</strong> — the six indicator cards at the top summarise the entire
          ocean at once. "Global mean sea surface temperature" is a single number describing
          every square kilometre of ocean surface on Earth.
        </li>
        <li>
          <strong>Point</strong> — the charts, the AI insights and the nearest-buoy list all
          describe <em>one coordinate</em>, the one in the location box at the top right.
          Change it and those panels change with it; the six global cards do not.
        </li>
      </ul>

      <Callout kind="jargon" title="Jargon buster — area weighting">
        <p>
          Every global average here is <Term>area-weighted</Term>. Ocean models store data on a
          grid of equal-angle cells — every cell spans the same number of degrees. But a degree
          of longitude is about 111 km at the equator and nearly zero at the pole, so polar
          cells cover far less actual ocean.
        </p>
        <p>
          Averaging the cells naively would count a tiny Arctic cell as heavily as an enormous
          tropical one, and drag the global mean several degrees too cold. Multiplying each cell
          by the cosine of its latitude fixes this. Every "global mean" on this dashboard is
          computed that way.
        </p>
      </Callout>

      <h2 id="freshness">Why nothing here is truly "live"</h2>
      <p>
        Satellites orbit, models run on schedules, and buoys report when they report. "Live"
        on this dashboard means <em>the most recent value that exists</em>, not a reading from
        this second. The gap varies enormously by source:
      </p>
      <Table
        headers={['Source', 'Typical lag behind real time', 'Why']}
        rows={[
          ['NOAA buoys', 'Minutes to an hour', 'Instruments transmit on their own schedule'],
          ['Copernicus ocean model', '3–12 hours', 'A global physics model must finish its run'],
          ['Copernicus wind', 'Up to ~30 hours', 'Blended satellite and model product'],
          ['NOAA Coral Reef Watch', '1–2 days', 'Daily composite of multiple satellite passes'],
          ['NASA satellite imagery', '0–2 days', 'Depends on orbit and processing level'],
        ]}
        numeric={[1]}
      />
      <p>
        Every panel shows the age of what it is displaying. If a figure is two days old, the
        card says "2d ago" rather than implying it is current.
      </p>

      <Callout kind="note" title="A source can be healthy and its data still old">
        <p>
          The data-source panel separates these two ideas deliberately. "Healthy" means the
          dashboard successfully fetched from that provider recently. The <em>data timestep</em>
          {' '}is a separate line, because some products routinely publish a day or more behind
          real time and that is normal, not a fault.
        </p>
      </Callout>

      <h2 id="where-next">Where to go next</h2>
      <ul>
        <li>
          <Link to="/docs?c=dash-metrics">The six indicators, explained</Link> — what each
          number means, how it is computed, and what it does not cover.
        </li>
        <li>
          <Link to="/docs?c=dash-sources">Sources, satellites &amp; instruments</Link> — every
          provider, spacecraft and dataset behind the page.
        </li>
        <li>
          <Link to="/docs?c=dash-charts">Charts &amp; historical coverage</Link> — the ten
          chartable variables and why their time ranges differ.
        </li>
        <li>
          <Link to="/docs?c=dash-alerts">Alerts &amp; thresholds</Link> — every rule, with its
          numbers and its limits.
        </li>
      </ul>
    </>
  );
}
