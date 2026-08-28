/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Table, Term } from '../primitives';

export function Problems() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>The two problem statements</h1>
      <p className="docs-article__lede">
        Why harmful algal blooms and fishing zones specifically — out of everything you could
        model in an ocean — and what exactly each model is being asked to output. This chapter is
        the "why", the rest of the section is the "how".
      </p>

      <h2 id="choosing">Why these two</h2>
      <p>
        Both problems share three properties that make them worth building, and that a lot of
        ocean ML ideas fail:
      </p>
      <ol>
        <li>
          <strong>There is a real decision at the other end.</strong> A bloom forecast changes
          whether a coastal agency issues an advisory. A habitat map changes where a boat spends
          its fuel. Neither is a metric with no consumer.
        </li>
        <li>
          <strong>The labels exist without a bespoke field campaign.</strong> Chlorophyll comes
          from an open reanalysis product; species occurrences come from OBIS, an open global
          database. We could not have modelled, say, illegal fishing or plastic transport at this
          cost.
        </li>
        <li>
          <strong>There is an operational incumbent to be measured against.</strong> India's
          INCOIS already publishes PFZ advisories and Algal Bloom Information Service bulletins.
          That means "is this actually better than what exists" is a question with a meaning,
          even where we cannot yet run the comparison.
        </li>
      </ol>

      <h2 id="problem-a">Problem A — harmful algal bloom early warning</h2>

      <Callout kind="jargon" title="Jargon buster — what a harmful algal bloom is">
        <p>
          <Term>Phytoplankton</Term> are microscopic plants drifting in the sunlit surface layer
          of the ocean. Give them light plus a sudden supply of nutrients (nitrate, phosphate,
          silicate) and their population can multiply many times over within days — a{' '}
          <Term>bloom</Term>. Blooms are the base of the marine food web and mostly a good thing.
          A <Term>harmful</Term> algal bloom is one where either (a) the species involved
          produces a toxin that accumulates in shellfish and sickens people, or (b) the bloom is
          so dense that when it dies and decomposes it consumes the oxygen in the water and
          suffocates everything else — a fish kill.
        </p>
        <p>
          <Term>Chlorophyll-a</Term> is the green pigment phytoplankton use for photosynthesis.
          Its concentration (mg per cubic metre) is the standard proxy for how much
          phytoplankton is present, and it is what satellites and ocean models can actually
          measure at scale.
        </p>
      </Callout>

      <h3>The forecast, precisely stated</h3>
      <p>
        For each 0.25° cell of the Arabian Sea on each day <em>t</em>, output the probability
        that chlorophyll at that same cell on day <em>t+3</em>, <em>t+5</em> and <em>t+7</em>{' '}
        will exceed that cell's bloom threshold for that monsoon season. Three separate models,
        one per horizon.
      </p>

      <h3>Forecast-then-threshold, not straight classification</h3>
      <p>
        The obvious framing is "train a binary classifier on bloom / no bloom". We deliberately
        did not. Instead the target is defined by forecasting the underlying continuous quantity
        and comparing it to a locally calibrated threshold. Three things that buys:
      </p>
      <ul>
        <li>
          <strong>A meaningful risk score.</strong> The output is a trajectory of chlorophyll plus
          a distance above the local normal, not an opaque yes/no.
        </li>
        <li>
          <strong>A retunable threshold.</strong> A different region, season, or agency risk
          appetite means a different threshold — and none of that requires retraining the model.
        </li>
        <li>
          <strong>Honesty about what the label is.</strong> A fixed global cutoff is not
          physically meaningful: 1 mg/m³ of chlorophyll is an extreme anomaly in the open Arabian
          Sea and an ordinary Tuesday in a coastal upwelling zone. The threshold has to be local.
        </li>
      </ul>

      <Callout kind="warn" title="Read this before quoting any HAB number">
        <p>
          What we train on is a <strong>weak label</strong>. "Modelled chlorophyll above this
          cell's seasonal 90th percentile" is a <em>proxy</em> for a bloom. It is not a verified
          bloom, and it says nothing at all about toxicity. Verified labels would need in-situ
          cell counts and toxin assays — HABSOS, NCCOS, HAEDAT, or INCOIS advisories — and none
          of those is openly queryable for this coastline.
        </p>
        <p>
          One direct consequence: our positive class rate is around 9.7% in training, not the
          "low single digits" real blooms would give. That is arithmetic, not oceanography — a
          90th-percentile threshold produces ~10% positives by construction.
        </p>
      </Callout>

      <h3>Region and window</h3>
      <Table
        headers={['Setting', 'Value', 'Why']}
        rows={[
          [
            'Region',
            'Arabian Sea — 68–78°E, 6–23°N',
            'A bounded box. Daily fields over a wide region are prohibitively expensive to fetch, so the region gives.',
          ],
          [
            'Cadence',
            'Daily',
            'Non-negotiable: the product is a t+3/t+5/t+7 day forecast.',
          ],
          [
            'Window',
            '2016-01-01 → 2021-12-31',
            'Six years puts five southwest-monsoon bloom seasons in the training period. An earlier two-year window put in exactly one, and the model collapsed — see below.',
          ],
          ['Grid', '0.25°  (≈ 28 km)', "Matches the biogeochemistry product's native resolution — the coarsest input."],
        ]}
      />

      <Callout kind="lesson" title="The window was measured, not chosen">
        <p>
          The first version of this model ran on 2020–2021. It scored well until we moved the
          validation slice out of training, at which point the seven-day model dropped to
          ROC-AUC 0.53 — literally chance. The cause was not tuning: monthly mean chlorophyll in
          the 2021 southwest monsoon ran ~40% higher than 2020's (August: 0.229 vs 0.164 mg/m³),
          so the model was being asked about an ocean regime it had never seen.
        </p>
        <p>
          Extending to six years fixed it outright. The bloom rate across train / validation /
          test went from 10.4% → 16.5% → 21.2% (drifting badly) to 10.2% → 9.4% → 7.6% (flat),
          and t+7 ROC-AUC went from 0.53 to 0.841. <strong>More years beat more features</strong>,
          because no covariate helps a model that has never seen the regime it is being asked
          about.
        </p>
      </Callout>

      <h2 id="problem-b">Problem B — fish habitat / Potential Fishing Zone</h2>

      <Callout kind="jargon" title="Jargon buster — PFZ and SDM">
        <p>
          A <Term>Potential Fishing Zone</Term> advisory is a map published to fishing crews
          showing where fish are likely to aggregate. INCOIS issues these for the Indian coast;
          at heart the operational method is a hand-tuned detector for sea-surface-temperature{' '}
          <Term>fronts</Term> — boundaries where warm and cold water meet. Fronts concentrate
          nutrients and small prey, so predators concentrate there too.
        </p>
        <p>
          A <Term>species distribution model</Term> (SDM) is the ecology term for what we are
          building: a model of the relationship between where a species has been observed and
          the environmental conditions there, used to map suitability everywhere else. The SDM
          literature has its own vocabulary and its own metrics, and we follow it rather than
          generic ML convention — that is why you will see the Boyce index and TSS instead of
          F1.
        </p>
      </Callout>

      <h3>The prediction, precisely stated</h3>
      <p>
        For a given species, location, month and set of ocean conditions, output a habitat
        suitability score between 0 and 1. Five species are modelled in one shared model, with
        the species itself as an input feature:
      </p>
      <Table
        headers={['Key', 'Scientific name', 'Common name']}
        rows={[
          [<code>yellowfin_tuna</code>, <em>Thunnus albacares</em>, 'Yellowfin tuna'],
          [<code>skipjack_tuna</code>, <em>Katsuwonus pelamis</em>, 'Skipjack tuna'],
          [<code>bigeye_tuna</code>, <em>Thunnus obesus</em>, 'Bigeye tuna'],
          [<code>indian_mackerel</code>, <em>Rastrelliger kanagurta</em>, 'Indian mackerel'],
          [<code>oil_sardine</code>, <em>Sardinella longiceps</em>, 'Oil sardine'],
        ]}
        caption="Commercially significant species of the Indian EEZ with enough OBIS occurrence records in the region to model. Record counts were checked against the OBIS API before the list was fixed, not assumed."
      />
      <p>
        Stacking all five into one table rather than training five separate models is deliberate:
        species with few records borrow strength from the shared environmental response. It is
        the tabular equivalent of a shared encoder with per-species output heads.
      </p>

      <h3>The hard part is not the classifier</h3>
      <p>
        OBIS is <strong>presence-only</strong>. There is no record anywhere in it that says "we
        looked here and found nothing". So the negative class has to be manufactured, and how you
        manufacture it decides what the model learns. Get it wrong and you produce a beautiful
        map of where marine biologists work. The <Link to="/docs?c=habitat">habitat chapter</Link>{' '}
        covers the fix — target-group background sampling — in full, because it matters more to
        the credibility of this model than every hyperparameter combined.
      </p>

      <h3>Region and window</h3>
      <Table
        headers={['Setting', 'Value', 'Why']}
        rows={[
          [
            'Region',
            'North Indian Ocean — 55–95°E, 5°S–25°N',
            'Occurrence-record density collapses outside it. A narrow box returns single-digit records for most target species; this one returns 280–400 for the tunas.',
          ],
          [
            'Cadence',
            'Monthly',
            'Occurrence records carry imprecise dates. Sampling daily fields against them would be false precision — and monthly means make a wide region affordable.',
          ],
          [
            'Window',
            '2000-01-01 → 2013-12-31',
            'Set by label availability, not by what Copernicus can serve. Target-species records in this region effectively stop after 2014.',
          ],
          ['Grid', '0.25°', 'The same shared grid as Problem A, so a feature means the same thing in both.'],
        ]}
      />

      <Callout kind="note" title="Two different windows, one shared codebase">
        <p>
          The two problems cover different boxes over different years at different cadences.
          That is not a failure of the shared design — the guarantee the shared layer makes is
          that <em>a feature means the same thing in both</em>, not that both cover the same
          water. Both profiles run through identical ingestion, fusion and feature code.
        </p>
      </Callout>

      <h2 id="not-built">What we deliberately did not build</h2>
      <ul>
        <li>
          <strong>HAB Stage 2 — toxicity classification.</strong> Deciding whether a bloom is
          harmful needs in-situ genus and toxin data. None is openly queryable for this
          coastline, so the interface carries a <code>label_strength</code> field and the
          classifier is left unimplemented rather than faked on data that does not exist.
        </li>
        <li>
          <strong>Fishing-effort data as a label.</strong> Global Fishing Watch data is
          registered in the source inventory but not ingested. Vessel positions must stay a
          covariate and an external validation signal, never a target — "fish are where boats
          are, and boats are where fish are" is a circular model that would score well and mean
          nothing.
        </li>
      </ul>
    </>
  );
}
