/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Formula, Table, Term } from '../primitives';

/**
 * The second and third detectors, and the one place they share a baseline.
 *
 * Eddies asked "is the water rotating". These two ask "is the water unusually
 * warm" and "is the wind pushing water offshore" — and upwelling's second claim
 * borrows heatwaves' own arithmetic, sign reversed, which is why they are one
 * chapter rather than two. Both follow the house rule from the eddies chapter:
 * state what the count is not, as carefully as what it is.
 */
export function UpwellingHeatwaves() {
  return (
    <>
      <p className="docs-article__eyebrow">Ocean &amp; atmosphere</p>
      <h1>Upwelling and marine heatwaves</h1>
      <p className="docs-article__lede">
        The second and third detectors on the map. Marine heatwaves ask whether SST is
        unusual enough, for long enough, to count as an event rather than a warm afternoon.
        Coastal upwelling asks whether the wind is currently favourable for pulling deep water
        to the surface — and, where it can, whether the water actually answered. The second
        claim there is built from the first detector's own baseline, which is why they belong
        together.
      </p>

      <h2 id="heatwaves">Marine heatwaves, to a published definition</h2>
      <p>
        A heatwave is <em>not</em> the SST anomaly already on the dashboard. An anomaly
        compares today's temperature to a climatological <em>mean</em>, and a mean-based
        threshold cannot tell "unusual" from "normal for a place with a wide seasonal swing".
        This detector instead follows{' '}
        <Term>Hobday et al.'s marine heatwave definition</Term>: SST above the
        seasonally-varying <strong>90th percentile</strong> for at least{' '}
        <strong>five consecutive days</strong>. Both clauses matter — the percentile is a
        statement about the local distribution a mean-based climatology cannot express, and
        the five-day minimum is what separates an event from one warm reading.
      </p>
      <Table
        headers={['Category', 'How far past the threshold']}
        rows={[
          ['Moderate', '1–2× the gap between the mean and the 90th percentile'],
          ['Strong', '2–3×'],
          ['Severe', '3–4×'],
          ['Extreme', '4×+'],
        ]}
      />
      <Callout kind="note" title="Why the mean is stored beside the threshold">
        Hobday's categories are multiples of <em>the gap between the climatological mean and
        the 90th percentile</em>, not multiples of the percentile itself — so the category
        cannot be recovered from the threshold alone, and the fitted mean travels with every
        cell for exactly that reason.
      </Callout>
      <p>
        Detection needs a short stack of consecutive daily fields, not a single snapshot — a
        detector that compared today against today's threshold would flag a large fraction of
        the ocean on any given day and call it a heatwave. What is reported is
        "this cell is in its <em>N</em>th consecutive day above threshold within the window
        examined": a real run length can be longer than the window shows, and the response
        says the count is censored rather than implying it knows a true onset date.
      </p>
      <Callout kind="lesson" title="It detects; it does not track">
        Same rule, same reason, as eddies: a duration, an onset date and a cumulative
        intensity all require holding identity across days, which is the same
        frame-to-frame assignment problem eddy tracking has not solved yet either. Aggregate
        statistics (a global mean extent) are restricted to 60°S–60°N — polar ice-margin cells
        carry anomalies past +15 °C because the climatology expects ice and a summer retreat
        leaves water, the same masking `services/crw.py` found necessary for the dashboard's
        heat-stress numbers. The per-cell map is <em>not</em> masked this way — a heatwave in
        the Barents Sea is real and is drawn — only the headline aggregate is.
      </Callout>

      <h2 id="upwelling">Coastal upwelling, from wind alone</h2>
      <p>
        <Term>Coastal upwelling</Term> is what happens when wind-driven surface transport
        moves water away from a coast and deeper, colder, nutrient-rich water rises to
        replace it — one of the ocean's most productive processes, and the reason some of the
        world's best fishing grounds sit off otherwise unremarkable coastlines.
      </p>
      <Formula
        expr="upwelling = M · n_offshore"
        where={
          <>
            <strong>M</strong> is the wind-driven Ekman transport; <strong>n_offshore</strong>{' '}
            is the local coastal normal. Positive is upwelling-favourable, negative is
            downwelling-favourable — the sign is the whole point, since reporting only the
            magnitude would call a coast that is being <em>piled up</em> an upwelling zone.
          </>
        }
      />
      <p>
        Two things this needs and does not have a ready-made source for: which way is
        "offshore", and where the equator makes the physics break down.
      </p>
      <Table
        headers={['Problem', 'How it is handled']}
        rows={[
          [
            'Nothing here supplies coastline geometry',
            "The coastal normal is derived from the ocean mask the currents field already carries — smoothed, then differentiated, so the gradient points from land into water by construction. It is coarse at 1/4°, so a cell whose surroundings are ambiguous is dropped rather than given a made-up bearing (reported as coastline_confidence).",
          ],
          [
            'The Coriolis parameter f vanishes at the equator',
            'Ekman transport is τ/(ρf), so the index diverges as f → 0 — and equatorial upwelling is driven by divergence, not the coast, a different mechanism entirely. The ±5° band is excluded outright, the same cut eddy polarity makes and for the same reason.',
          ],
        ]}
      />
      <Callout kind="warn" title="A wind index, not an observation of upwelled water">
        This is what the wind is doing, not proof that cold water has actually reached the
        surface — stratification, topography and how long the wind has been blowing all
        intervene between a favourable index and real upwelled water at the surface.
      </Callout>

      <h2 id="corroboration">A second claim, corroborated against heatwaves' own baseline</h2>
      <p>
        Because the heatwave detector already fits a per-cell, per-day-of-year percentile
        climatology from OISST, coastal upwelling can ask a second question of the same
        record: was the water at this coast actually cool for the season, at the same time
        the wind looked favourable? A favourable-wind cell with a coincident cold anomaly is
        a materially stronger statement than either half alone — but the two claims are kept
        in separate response fields rather than merged, because a cell with no SST coverage
        is a coverage gap, not evidence against upwelling.
      </p>
      <Table
        headers={['Tier', 'Test']}
        rows={[
          [
            <strong>Cool anomaly</strong>,
            'SST at least 0.5 °C below its seasonal mean — a threshold chosen by hand.',
          ],
          [
            <strong>Confirmed below p10</strong>,
            "SST below its own seasonal 10th percentile — defined by the local distribution, no chosen constant, and reported separately as the stronger of the two claims.",
          ],
        ]}
      />
      <Callout kind="warn" title="The two fields are never simultaneous — and the response says so">
        Wind and current fields are hourly; OISST publishes daily with a lag of a week or
        more (16 days, measured live). So this is never "the water responded to this wind" —
        it is "the wind is favourable now, and at the most recent SST field, N days ago, this
        coast was cool for the season." Past 30 days of lag even that weaker statement is
        withheld, with a reason.
      </Callout>
      <Callout kind="lesson" title="The agreement was measured, and it is weak — quote it with its control">
        On the live global field: <strong>19.9%</strong> of upwelling-favourable coastal cells
        were cool for the season, against <strong>17.2%</strong> of downwelling-favourable
        ones — where cool water is not expected at all. Below the seasonal 10th percentile the
        two are indistinguishable (4.1% vs 3.9%), and the mean anomaly is <em>warmer</em> under
        favourable wind (+0.91 °C) than under downwelling (+0.60 °C). A corroborated cell is a
        real observation of cool water and a weak coincidence, not evidence the wind drove it —
        with a two-week-old SST field it could hardly be anything else. That control figure
        rides with every response rather than being left for a reader to reconstruct, the same
        rule this platform applies to HAB precision: a level is not a finding without its base
        rate.
      </Callout>
      <p>
        The obvious fix — score the <em>live</em> hourly SST field instead of the lagged OISST
        record — was tried and made things worse: the weak tier's contrast was unchanged and
        the strong tier inverted, because the climatology is fitted on OISST and the live
        physics field disagrees with it by more than the 0.5 °C threshold itself, across the
        coastal band. Latency was not the binding constraint; the baseline product was. Fixing
        it means a climatology fitted on the same reanalysis the live field comes from, not a
        faster fetch.
      </p>
    </>
  );
}
