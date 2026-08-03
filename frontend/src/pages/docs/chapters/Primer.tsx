/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Code, Formula, Table, Term } from '../primitives';

export function Primer() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>A primer: ML vocabulary, in ocean terms</h1>
      <p className="docs-article__lede">
        If you already know what supervised learning, features, labels, class imbalance and
        overfitting are, skip to the next chapter. This one maps the standard vocabulary onto
        what the ocean data actually looks like, so the rest of the docs can move fast.
      </p>

      <h2 id="supervised">Supervised learning, and what a "row" is here</h2>
      <p>
        Both of our models are <Term>supervised classifiers</Term>: you hand the model a table
        where each row describes one situation, and one column is the answer you want it to
        learn to predict. The model learns a function from the other columns (the{' '}
        <Term>features</Term>) to the answer (the <Term>label</Term>). The interesting part of
        applied ML is almost never the classifier — it is deciding what a row <em>is</em>, and
        where the label comes from.
      </p>

      <Table
        headers={['', 'Problem A (HAB)', 'Problem B (habitat)']}
        rows={[
          [
            'One row is…',
            'one 0.25° grid cell on one calendar day',
            'one observation point — a place and date where a fish was recorded, or where the survey recorded something else',
          ],
          [
            'The label is…',
            'will chlorophyll here exceed this cell\'s seasonal bloom threshold in 3 / 5 / 7 days? (1 or 0)',
            'was this species present here? (1) or is this a background point? (0)',
          ],
          ['Number of rows', '≈ 3.84 million', '2,787'],
          ['Number of features', '136', '40'],
          [
            'Where the label comes from',
            'the data itself — a percentile of modelled chlorophyll (a "weak" label)',
            'OBIS, a global database of species occurrence records',
          ],
        ]}
        caption="The two problems could not be more different in shape: millions of rows of a regular grid versus a few thousand scattered points. Almost every design decision downstream follows from that difference."
      />

      <h2 id="features">Features, and why "feature engineering" matters so much here</h2>
      <p>
        A feature is any number you compute from what you know, and hand to the model as input.
        The raw ocean data gives us temperature, salinity, chlorophyll, currents and so on — but
        handed to a model raw, those numbers answer the wrong question. A model told only "the
        temperature here is 28.4 °C" has no way to know whether that is unusually warm{' '}
        <em>for this place, in this season</em>, or whether it has been climbing for a fortnight.
      </p>
      <p>
        So most of the work is turning raw fields into features that encode the physics and the
        ecology:
      </p>
      <ul>
        <li>
          <strong>Anomalies</strong> — how far today's value is from this cell's normal value for
          this month.
        </li>
        <li>
          <strong>Lags</strong> — what the value was 3, 7, 14 and 30 days ago.
        </li>
        <li>
          <strong>Rolling statistics</strong> — the average and variability over the past week or
          month.
        </li>
        <li>
          <strong>Spatial derivatives</strong> — how sharply temperature changes across space
          (that's a "front", and fish gather at them).
        </li>
        <li>
          <strong>Interactions</strong> — warm water <em>over</em> a shallow mixed layer traps a
          bloom near the surface; neither term alone says that.
        </li>
      </ul>
      <p>
        The <Link to="/docs?c=features">feature engineering chapter</Link> works through every one of
        them.
      </p>

      <h2 id="splitting">Train, validation, test — and why random splitting is banned here</h2>
      <p>
        Standard practice: hold out part of your data, train on the rest, and measure on what you
        held out. The universal beginner default is to shuffle the rows and take a random 20%.
      </p>
      <p>
        <strong>On this data that is not a small inaccuracy, it is meaningless.</strong> Ocean
        fields are <Term>autocorrelated</Term> — a fancy word for "today looks almost exactly
        like yesterday, and this pixel looks almost exactly like the pixel next to it". If you
        shuffle randomly, a grid cell's Tuesday lands in training and its Wednesday lands in
        test. The model does not have to learn any oceanography to score beautifully; it just has
        to recognise near-duplicates of rows it already saw.
      </p>

      <Callout kind="warn" title="The single most important idea in these docs">
        <p>
          A validation score is not a property of a model. It is a property of a model{' '}
          <em>and</em> the way you split the data. Change the split and the same model reports a
          wildly different number. Everywhere in this project you will see scores that look worse
          than a random split would have given — that gap is the honest part.
        </p>
      </Callout>

      <p>So we use two structured splits instead, one per problem:</p>
      <ul>
        <li>
          <strong>Rolling-origin (time series) splits</strong> for the bloom forecast. Train on
          the past, test on the future, and throw away a few days in between. Chapter:{' '}
          <Link to="/docs?c=validation">Validation &amp; leakage</Link>.
        </li>
        <li>
          <strong>Spatial block splits</strong> for the habitat model. Hold out whole 3° squares
          of ocean, so the test points are physically far from any training point.
        </li>
      </ul>

      <h2 id="leakage">Leakage</h2>
      <p>
        <Term>Leakage</Term> is when information that would not be available at prediction time
        sneaks into training. It is the reason a model can look excellent in a notebook and be
        useless in production, and it is far easier to introduce than to detect — because its
        only symptom is a score that looks <em>good</em>.
      </p>
      <p>Three ways it happens on time-series ocean data, all of which we guard against:</p>
      <ol>
        <li>
          <strong>A "lag" feature that reads forwards.</strong> One misplaced sign in a{' '}
          <code>shift()</code> and your model is told tomorrow's chlorophyll while predicting
          tomorrow's bloom.
        </li>
        <li>
          <strong>A rolling window that includes the current timestep.</strong> A "past 7 days"
          average that quietly includes today.
        </li>
        <li>
          <strong>A statistic fitted on all the data.</strong> This one is subtle and it bit us:
          our bloom labels are defined by a percentile threshold. Compute that percentile over
          the whole record, including the test years, and you have leaked the future into the
          definition of the target itself.
        </li>
      </ol>
      <p>
        The codebase handles this structurally rather than by being careful: every
        "fit-then-apply" pair is split into two separate functions, so fitting on the wrong rows
        requires actively passing the wrong table.
      </p>

      <Code>{`# Correct by construction — you have to name the training rows.
thresholds  = fit_bloom_thresholds(train_frame)     # fit: training only
frame       = apply_bloom_thresholds(frame, thresholds)   # apply: everywhere`}</Code>

      <h2 id="imbalance">Class imbalance</h2>
      <p>
        Blooms are rare. In our held-out year about 7.4% of grid-cell-days are labelled as
        blooms. A model that predicts "no bloom" every single time is 92.6% accurate and
        completely worthless.
      </p>
      <p>Two consequences run through the whole project:</p>
      <ul>
        <li>
          <strong>Accuracy is never reported.</strong> We use PR-AUC, TSS and Brier score
          instead — all explained in <Link to="/docs?c=metrics">Metrics, explained</Link>.
        </li>
        <li>
          <strong>The training loss is reweighted</strong> (<code>class_weight="balanced"</code>),
          so a missed bloom costs the model much more than a false alarm. This keeps the rare
          class learnable — but it distorts the predicted probabilities, which is why we then
          have to <Link to="/docs?c=hab">calibrate</Link> them.
        </li>
      </ul>

      <h2 id="trees">Gradient-boosted trees, in sixty seconds</h2>
      <p>
        Both problems' best model is <Term>LightGBM</Term>, a gradient-boosting library. The idea:
        train a small decision tree; look at where it was wrong; train a second small tree to
        predict those errors; add it to the first; repeat a few hundred times. Each tree is weak,
        the sum is strong.
      </p>
      <p>Why it suits this data specifically:</p>
      <ul>
        <li>
          It handles <strong>missing values natively</strong> — and our data is full of them,
          because clouds, satellite swath gaps and land all produce holes.
        </li>
        <li>
          It captures <strong>thresholds and interactions</strong> automatically. Ecology is full
          of "below 200 m depth everything changes" effects that a linear model cannot express.
        </li>
        <li>
          It does not need features scaled to the same range, so depth in metres and chlorophyll
          in mg/m³ can sit side by side.
        </li>
        <li>
          It stays explainable through <Term>SHAP</Term> — a method that attributes each
          individual prediction to the features that drove it, so the product can say{' '}
          <em>why</em> a cell is flagged, not just that it is.
        </li>
      </ul>

      <Formula
        expr={'prediction = tree₁(x) + tree₂(x) + … + tree₅₀₀(x)  →  sigmoid → probability'}
        where="Each tree is depth-limited (max_depth 5–6 here) so no single tree can memorise the training set. The learning rate (0.05) shrinks each tree's contribution, which is what makes the sum stable."
      />

      <h2 id="what-good-looks-like">What "a good result" looks like on this data</h2>
      <p>
        Coming from tutorial datasets, the scores in these docs may look low. A held-out PR-AUC of
        0.36 for the seven-day bloom forecast is not a failing grade — it is a real forecast of a
        rare, chaotic biological event a week into the future, measured on water and time the
        model never saw, against a baseline that scores 0.31. Whether that is <em>useful</em> is
        a separate question from whether it is good, and we answer it with false-alarm rates
        rather than with AUCs.
      </p>
    </>
  );
}
