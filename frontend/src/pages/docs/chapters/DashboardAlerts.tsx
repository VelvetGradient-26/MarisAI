/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Link } from '../../../app/router';
import { Callout, Table, Term } from '../primitives';

export function DashboardAlerts() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean intelligence dashboard</p>
      <h1>Alerts &amp; thresholds</h1>
      <p className="docs-article__lede">
        The alerts panel lists conditions that currently exceed a monitored threshold. Every
        rule, every number and every source is documented here — because an alert whose basis
        you cannot inspect is not information, it is just an alarm.
      </p>

      <Callout kind="warn" title="Read this before anything else on the page">
        <p>
          These alerts are <strong>rules applied to model and satellite data by this
          dashboard</strong>. They are not issued by NOAA, the Met Office, or any national
          weather service. Nobody has reviewed them. They carry no authority.
        </p>
        <p>
          "High seas" here means "the global wave model's maximum exceeded 6 metres somewhere",
          not "a marine warning has been issued". For decisions at sea, use your national
          meteorological service. Nothing on this dashboard is suitable for navigation.
        </p>
      </Callout>

      <h2 id="severity">The three severity levels</h2>
      <Table
        headers={['Level', 'Colour', 'Meaning']}
        rows={[
          [<strong>Critical</strong>, 'Red', 'A threshold associated with severe or irreversible harm'],
          [<strong>Warning</strong>, 'Amber', 'A threshold where significant impact is expected'],
          [<strong>Advisory</strong>, 'Blue', 'Notable but below the impact thresholds above'],
        ]}
      />
      <p>
        Red and amber appear nowhere else on the dashboard. That is deliberate: on a page
        otherwise built from deep blues and teals, a warm colour always means something needs
        attention.
      </p>

      <h2 id="coral">Rule 1 — coral bleaching and mortality</h2>
      <p>
        <strong>Source:</strong> NOAA Coral Reef Watch degree heating weeks.
        {' '}<strong>Thresholds:</strong> NOAA's own, not chosen here.
      </p>
      <Table
        headers={['Condition', 'Severity', 'What it means']}
        rows={[
          ['DHW ≥ 8 °C-weeks', <strong>Critical</strong>, 'Severe bleaching and coral mortality likely'],
          ['DHW ≥ 4 °C-weeks', <strong>Warning</strong>, 'Significant bleaching likely'],
        ]}
      />
      <p>
        Degree heating weeks measure heat <em>accumulated</em> over the previous 12 weeks rather
        than today's temperature — see <Link to="/docs?c=dash-metrics">the indicators chapter</Link>
        {' '}for how the metric is built. Alerts are restricted to 30°S–30°N, where reef-building
        corals actually live.
      </p>

      <Callout kind="lesson" title="Why the top six alerts are not all in one place">
        <p>
          The worst-affected cells are usually adjacent to each other — one large warm pool.
          Listing the top six by value produced six alerts describing the same event, which is
          six times the noise for one piece of information.
        </p>
        <p>
          Alerts are therefore <Term>declustered</Term>: two reported hotspots must be at least
          800 km apart. The panel shows six distinct places rather than six views of one.
        </p>
      </Callout>

      <h2 id="heat-stress">Rule 2 — large marine heat-stress regions</h2>
      <p>
        <strong>Source:</strong> NOAA Coral Reef Watch HotSpot.
        {' '}<strong>Trigger:</strong> a contiguous region larger than 1,000,000 km² where sea
        surface temperature exceeds the warmest month that location normally reaches by at least
        1 °C. Severity is Warning where the peak excess is 2 °C or more, otherwise Advisory.
      </p>
      <p>
        Each alert names its <em>peak</em> location, not the region's geometric centre. These
        patches are long and curved, and the centre of a horseshoe-shaped region routinely falls
        on land — which reads as a bug even when the region is correct.
      </p>

      <h2 id="waves">Rule 3 — high seas</h2>
      <p>
        <strong>Source:</strong> the Copernicus global wave model.
        {' '}<strong>Thresholds:</strong> 9 m peak <Term>significant wave height</Term> is
        Critical; 6 m is a Warning.
      </p>

      <Callout kind="jargon" title="Jargon buster — significant wave height">
        <p>
          Counter-intuitively, <Term>significant wave height</Term> is not the height of the
          biggest wave. It is the average height of the highest one-third of waves — a
          convention dating from when observers estimated sea state by eye, and which turns out
          to match what a trained observer reports.
        </p>
        <p>
          The practical consequence: individual waves are routinely much larger. The largest
          wave in a sea state is commonly about twice the significant height. A "6 m sea" can
          contain a 12 m wave.
        </p>
      </Callout>

      <p>
        This alert is explicitly global rather than located. The dashboard keeps only statistics
        from the wave grid, not the grid itself, so the peak's coordinates are not retained —
        and the alert says "Global maximum" instead of inventing a position.
      </p>

      <h2 id="bloom">Rule 4 — harmful algal bloom probability</h2>
      <p>
        <strong>Source:</strong> MarisAI's own HAB early-warning model, Arabian Sea only.
        {' '}<strong>Trigger:</strong> modelled bloom probability ≥ 0.5 at a 3-day horizon.
        Severity is Warning at 0.7 and above, otherwise Advisory.
      </p>
      <p>
        A <Term>harmful algal bloom</Term> is a rapid overgrowth of algae that can strip oxygen
        from the water, kill fish, and in some species release toxins dangerous to people. The
        model's measured skill at this horizon is PR-AUC 0.661 against a persistence baseline of
        0.511 — better than assuming tomorrow looks like today, but far from certain. The alert
        quotes both figures so the reader can judge it.
      </p>

      <h2 id="unevaluated">When a rule cannot be evaluated</h2>
      <p>
        If a source has not loaded, its rule produces no alerts — and the panel says which rules
        were skipped, in amber, at the bottom.
      </p>
      <p>
        This matters more than it first appears. An empty alerts panel could mean "the ocean is
        calm" or "we could not check". Those are opposite messages, and silently showing the
        first when the second is true would be the most dangerous failure this dashboard could
        have.
      </p>

      <h2 id="dismiss">Dismissing alerts</h2>
      <p>
        The <strong>×</strong> on an alert hides it. Each alert's identifier is derived from its
        content — kind, region and coordinates — so a dismissed alert stays dismissed as the
        panel refreshes, while a genuinely new condition, or the same condition moving
        elsewhere, produces a new identifier and reappears.
      </p>
      <p>
        Dismissals are local to your browser and reset on reload. A "Restore" control appears in
        the header whenever anything is hidden.
      </p>
    </>
  );
}
