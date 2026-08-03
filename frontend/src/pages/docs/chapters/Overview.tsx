/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Table } from '../primitives';

export function Overview() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Overview: what this section is</h1>
      <p className="docs-article__lede">
        Maris AI runs two machine learning models over open ocean data: one that forecasts
        harmful algal blooms three to seven days ahead, and one that maps where five
        commercially important fish species are likely to be. These pages explain both of them
        completely — the problem, every input variable, how the data was fetched, every feature
        we engineered, the algorithms, the validation, and the measured results, including the
        parts that did not work.
      </p>

      <h2 id="who-this-is-for">Who this is written for</h2>
      <p>
        A student who has finished an introductory machine learning course, or an engineer in
        their first job who has trained a model on a Kaggle CSV but never on data that came out
        of the ocean. You need to know what a train/test split is. You do <em>not</em> need to
        know what a mixed layer depth is, what the Okubo–Weiss parameter measures, or why a
        random K-fold split is a catastrophe on satellite data. All of that gets explained where
        it first comes up.
      </p>
      <p>
        Ocean-science jargon appears in grey <strong>Jargon buster</strong> boxes. Machine
        learning concepts that go beyond a first course — probability calibration, PR-AUC,
        spatial block cross-validation, target-group background sampling — get their own
        sections rather than a passing mention.
      </p>

      <Callout kind="note" title="A note on honesty">
        <p>
          Every number in these docs is a real measurement from a real run in this repository,
          reproducible with the commands in the last chapter. Where a model performs badly, the
          bad number is printed. Two of the most useful sections describe results that got{' '}
          <em>worse</em> after we fixed a bug — because the original higher number was measuring
          the wrong thing.
        </p>
      </Callout>

      <h2 id="the-two-problems">The two problems in one paragraph each</h2>
      <p>
        <strong>Problem A — harmful algal bloom (HAB) early warning.</strong> Certain
        phytoplankton, given enough nutrients and the right water conditions, multiply
        explosively. Some of those blooms strip the water of oxygen and kill fish; some produce
        toxins that close beaches and shellfish beds. We forecast chlorophyll concentration
        three, five and seven days ahead across the Arabian Sea, and declare a bloom wherever
        the forecast crosses a threshold calibrated to that specific grid cell in that specific
        season.
      </p>
      <p>
        <strong>Problem B — fish habitat / Potential Fishing Zone (PFZ).</strong> India's
        national ocean service (INCOIS) publishes advisories telling fishing crews where to go,
        based largely on hand-tuned sea-surface-temperature front detection. We learn the same
        kind of map from data: given ocean conditions at a location and time, how suitable is it
        for yellowfin tuna, skipjack tuna, bigeye tuna, Indian mackerel, or oil sardine.
      </p>

      <h2 id="shape-of-the-code">The shape of the code</h2>
      <p>
        Both problems sit on one shared foundation, called the{' '}
        <strong>Marine Data Fusion Layer</strong>. Data ingestion, regridding, the feature store,
        the geometry and time feature libraries, and the entire validation harness are written
        once and imported by both. Only the labels and the problem-specific derived features
        differ. That is not tidiness for its own sake: it is the guarantee that "sea surface
        temperature gradient" means exactly the same computation in both models.
      </p>

      <Table
        headers={['Directory', 'What lives there']}
        rows={[
          [
            <code>marine_ml/</code>,
            'The shared spine — configuration, data sources, fusion/regridding, the feature store, geometry and temporal feature libraries, splitters and metrics.',
          ],
          [
            <code>hab_early_warning/src/</code>,
            'Problem A only — bloom labelling, HAB-specific features, the training loop for three forecast horizons.',
          ],
          [
            <code>fish_habitat_prediction/src/</code>,
            'Problem B only — presence/background labelling, habitat features, the three model tiers and their ensemble.',
          ],
          [
            <code>scripts/</code>,
            'Populating the raw data zone, and exporting prediction grids for the web app to serve.',
          ],
          [
            <code>tests/</code>,
            'Tests that the pipeline cannot cheat — see the validation chapter.',
          ],
          [
            <code>reports/</code>,
            'Every number quoted in these docs: per-fold scores, held-out metrics, SHAP rankings, calibration curves.',
          ],
        ]}
      />

      <h2 id="what-it-is-not">What this is not</h2>
      <p>
        The models here are what a serious pipeline looks like at the "Tier 1 and Tier 2" stage:
        gradient-boosted trees, regularised linear baselines, and careful validation. There is
        no ConvLSTM, no vision transformer, no GPU. That is deliberate and explained in the{' '}
        <Link to="/docs?c=limits">limitations chapter</Link>. Deep spatio-temporal models are
        worth building on top of a proven pipeline; they are a very expensive way to find out
        that your cross-validation was leaking.
      </p>

      <h2 id="how-to-read">Suggested reading order</h2>
      <p>
        Straight through. But if you are short on time and want the parts that generalise beyond
        this project, read <Link to="/docs?c=validation">Validation &amp; leakage</Link> and{' '}
        <Link to="/docs?c=metrics">Metrics, explained</Link> — those two chapters contain the
        mistakes that are easiest to make and hardest to notice in any applied ML project, not
        just this one.
      </p>
    </>
  );
}
