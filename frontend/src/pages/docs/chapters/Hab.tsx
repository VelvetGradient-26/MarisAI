/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Best, Callout, Code, Formula, Poor, Table, Term } from '../primitives';

export function Hab() {
  return (
    <>
      <p className="docs-article__eyebrow">Problem A</p>
      <h1>HAB early warning: labels, model, results</h1>
      <p className="docs-article__lede">
        Forecasting harmful algal blooms three, five and seven days ahead across the Arabian Sea:
        how the labels are constructed, what the model is, how it is validated against a
        deliberately strong baseline, why its probabilities need calibrating, and what it
        actually scores.
      </p>

      <h2 id="labels">Building the labels</h2>
      <p>
        Nobody hands you a column that says "bloom". It has to be constructed, in three steps,
        and the order matters enormously.
      </p>

      <h3>Step 1 — fit a threshold, on training rows only</h3>
      <p>
        For each grid cell and each monsoon season, take the <strong>90th percentile</strong> of
        chlorophyll observed there during the training period. That is the bloom threshold for
        that cell in that season.
      </p>
      <p>Two fallbacks handle sparse groups:</p>
      <ul>
        <li>
          Fewer than 24 observations in a (cell, season) group → fall back to that cell's
          all-season threshold.
        </li>
        <li>Still nothing → fall back to a single global threshold.</li>
      </ul>
      <p>
        A percentile estimated from a handful of points is noise, and would define blooms in
        places they never occur.
      </p>

      <h3>Step 2 — apply it everywhere</h3>
      <p>
        Every row gets <code>is_bloom</code> (is chlorophyll ≥ threshold right now) and{' '}
        <code>bloom_exceedance</code> (how far above the local normal — the severity signal).
        Rows with missing chlorophyll get a missing label rather than a false zero.
      </p>

      <h3>Step 3 — shift forward to make the target</h3>
      <Code>{`for horizon in (3, 5, 7):
    chl_t{h}       = grouped["chl"].shift(-horizon)        # future chlorophyll
    threshold_t{h} = grouped["threshold"].shift(-horizon)  # its threshold
    bloom_t{h}     = chl_t{h} >= threshold_t{h}`}</Code>

      <Callout kind="warn" title="This is the only forward shift in the entire codebase">
        <p>
          And it is correct here, because it constructs the <em>target</em>, not a feature. It is
          deliberately isolated in <code>labels.py</code> so that auditing "does anything in this
          project read the future" is a single-file question. The tests enforce that everything in
          the temporal feature library is trailing by construction.
        </p>
      </Callout>

      <h3>What the label rate actually is</h3>
      <Table
        headers={['Period', 'Bloom rate at t+7']}
        numeric={[1]}
        rows={[
          ['Train (2016 → mid-2020)', '10.2%'],
          ['Validation', '9.4%'],
          ['Test (2021)', '7.6%'],
        ]}
        caption="Flat across periods, which is what you want — the thresholds are fitted on training years only, so drift in the label rate would mean the model is being scored on a differently-defined target than it was trained on. On the earlier two-year window this went 10.4% → 16.5% → 21.2%, and that drift was destroying the model."
      />

      <h2 id="model">The model</h2>
      <p>
        One LightGBM classifier per horizon, inside a scikit-learn pipeline that casts numeric
        columns to float32 and one-hot encodes the two categorical features (monsoon phase and
        depth bucket).
      </p>
      <Table
        headers={['Hyperparameter', 'Value', 'Reasoning']}
        rows={[
          ['n_estimators', '500', 'With a learning rate of 0.05, enough rounds to fit without needing early stopping machinery.'],
          ['learning_rate', '0.05', 'Conservative. Each tree contributes little, so the sum is stable.'],
          ['num_leaves', '31', 'LightGBM default; paired with a depth cap so trees stay shallow.'],
          ['max_depth', '6', 'Hard cap on interaction order. Deeper trees memorise the training years.'],
          ['min_child_samples', '50', 'No leaf may be built from fewer than 50 rows — prevents splits on noise.'],
          ['subsample / colsample', '0.8 / 0.8', 'Row and column sampling per tree; standard variance reduction.'],
          ['reg_lambda', '1.0', 'L2 penalty on leaf weights.'],
          ['class_weight', 'balanced', 'Blooms are ~8% of rows. Without reweighting the model learns to always say no.'],
        ]}
        caption="Hand-chosen and deliberately conservative. There is no hyperparameter search — nested rolling-origin tuning is the documented next step, and an un-nested search would just be another way to leak the test period."
      />

      <h3>Training stride: fitting on every 4th day</h3>
      <p>
        Consecutive daily fields in this basin are nearly identical — the same autocorrelation
        that makes persistence a strong baseline. So the <em>effective</em> sample size is far
        below the row count, and fitting on every 4th calendar day discards little information
        while cutting fit time and memory proportionally.
      </p>
      <p>
        Whole days are dropped, never individual cells, so every retained timestep is still a
        complete spatial field. Training still sees ~550 days spread across six years and all six
        monsoon cycles.
      </p>
      <Callout kind="note" title="Fitting only">
        <p>
          The stride applies to model fitting. <strong>Evaluation always uses every row</strong> of
          the test period — subsampling what you score on would be a different and much less
          defensible thing to do.
        </p>
      </Callout>

      <h2 id="validation">Validation: rolling-origin CV with an embargo</h2>
      <p>
        Each fold trains on everything before a cutoff and tests on the window after it, with{' '}
        <code>horizon</code> days dropped in between.
      </p>
      <Code>{`fold 1:  [========== train ==========]  x  [== test ==]
fold 2:  [============== train ==============]  x  [== test ==]
fold 3:  [================== train ==================]  x  [== test ==]
                                                  ↑
                                            embargo gap`}</Code>
      <p>
        The gap is not fussiness. The label at time <em>t</em> is chlorophyll at{' '}
        <em>t+7</em>, so a training row within 7 days of the test window shares its target's
        observation period. Without the gap the model is partly scored on data it was trained on,
        and the metric is fiction.
      </p>

      <h3>The persistence baseline, scored on every fold</h3>
      <Callout kind="jargon" title="Jargon buster — a persistence baseline">
        <p>
          For an autocorrelated field, "whatever is happening now will still be happening later"
          is a genuinely strong forecast. In weather forecasting this is the standard sanity
          check. <Term>Persistence</Term> here means: it is blooming now, therefore it will be
          blooming at t+h.
        </p>
        <p>
          Any model that cannot beat persistence has demonstrated nothing, no matter how good its
          absolute score looks.
        </p>
      </Callout>
      <p>
        Our baseline uses the standardised chlorophyll anomaly squashed through a sigmoid rather
        than a bare 0/1, so it is a ranked score — otherwise ranking metrics would penalise it
        unfairly for ties.
      </p>

      <Callout kind="lesson" title="The baseline earned its place immediately">
        <p>
          On the first (2020–2021) run, the model <strong>lost</strong> to persistence at t+5 and
          t+7. That finding is invisible without the baseline — the raw PR-AUC looked
          respectable. It is what drove the window out to six years.
        </p>
      </Callout>

      <h2 id="calibration">Calibration: making the probability mean something</h2>
      <p>
        <code>class_weight="balanced"</code> deliberately distorts the decision boundary to keep
        the minority class learnable. The side effect is systematic <Term>overconfidence</Term>:
        the raw model's 0.9–1.0 prediction bin actually fires on only 57% of occasions.
      </p>
      <p>
        Ranking metrics do not care — PR-AUC and TSS only look at the ordering. But the product
        surfaces a probability to a coastal agency, and "70% chance of a bloom" has to mean
        something.
      </p>
      <p>
        The fix is <Term>isotonic regression</Term>: fit a monotonic step function mapping raw
        scores onto observed frequencies. Where it is fitted is the entire question:
      </p>
      <Table
        headers={['Slice', 'Can it be the calibration set?', 'Why']}
        rows={[
          ['Training', <Poor>No</Poor>, 'The model is near-perfect there, so the mapping learned would be roughly the identity.'],
          ['Validation', <Best>Yes</Best>, 'Unseen by the model, and not used for the final score.'],
          ['Test', <Poor>No</Poor>, 'That would be fitting on the data you are about to report.'],
        ]}
        caption="This is why the validation slice is no longer folded back into training for the final fit — having something honest to calibrate on is worth more than the extra three months of training data."
      />
      <p>
        Isotonic regression is monotonic, so PR-AUC and ROC-AUC are unchanged to three decimals by
        construction. The improvement shows up exactly where it should — in the Brier score:
      </p>
      <Table
        headers={['Horizon', 'Brier (raw)', 'Brier (calibrated)', 'Improvement']}
        numeric={[1, 2, 3]}
        rows={[
          ['t+3', '0.056', <Best>0.038</Best>, '32%'],
          ['t+5', '0.073', <Best>0.049</Best>, '32%'],
          ['t+7', '0.085', <Best>0.057</Best>, '33%'],
        ]}
      />

      <h2 id="results">Results</h2>
      <p>
        Held-out final period: 2021, 577,608 grid-cell-days, 7.3–7.6% bloom rate. This period was
        touched exactly once, at the end.
      </p>
      <Table
        headers={['Horizon', 'PR-AUC', 'Persistence', 'ROC-AUC', 'TSS', 'Brier']}
        numeric={[1, 2, 3, 4, 5]}
        rows={[
          ['t+3', <Best>0.661</Best>, '0.511', '0.942', '0.751', '0.038'],
          ['t+5', <Best>0.493</Best>, '0.384', '0.884', '0.635', '0.049'],
          ['t+7', <Best>0.362</Best>, '0.309', '0.841', '0.564', '0.057'],
        ]}
        caption="The model beats persistence at every horizon. Rolling-origin cross-validation agrees at every horizon too (t+7: 0.363 CV vs 0.362 holdout), which is the sign that the holdout number is not a fluke of one lucky period."
      />

      <h3>The number that decides deployability</h3>
      <p>
        PR-AUC is a summary across all thresholds. An operational system runs at{' '}
        <em>one</em> threshold, and it is chosen by the recall a coastal agency demands — missing
        a bloom costs far more than a false alarm. Set the threshold to catch 80% of blooms and
        this is what you get:
      </p>
      <Table
        headers={['Horizon', 'Precision', 'Recall', 'False-alarm rate']}
        numeric={[1, 2, 3]}
        rows={[
          ['t+3', <Best>0.449</Best>, '0.807', '0.551'],
          ['t+5', '0.280', '0.801', '0.720'],
          ['t+7', <Poor>0.202</Poor>, '0.811', <Poor>0.798</Poor>],
        ]}
      />
      <Callout kind="warn" title="Read the false-alarm column before treating t+7 as deployable">
        <p>
          Catching 80% of blooms a week out means <strong>four in five alerts are false</strong>.
          No coastal agency will keep acting on that; operator trust erodes and then the true
          alerts get ignored too.
        </p>
        <p>
          The t+3 alert, where roughly half of alerts are genuine, is the one that would survive
          contact with a real agency. That is a more useful conclusion than any AUC on this page.
        </p>
      </Callout>

      <h2 id="drivers">What the model actually uses</h2>
      <p>
        Mean absolute SHAP value — how much each feature moves predictions on average — at t+3:
      </p>
      <Table
        headers={['Rank', 'Feature', 'Mean |SHAP|', 'What it is']}
        numeric={[0, 2]}
        rows={[
          ['1', <code>chl_anomaly</code>, '0.573', 'Chlorophyll minus this cell\'s seasonal normal.'],
          ['2', <code>chl_zanomaly</code>, '0.551', 'The same, standardised by local variability.'],
          ['3', <code>chl</code>, '0.480', 'Current chlorophyll level.'],
          ['4', <code>is_bloom</code>, '0.470', 'Is it blooming right now.'],
          ['5', <code>chl_delta</code>, '0.355', 'Day-over-day change — the growth rate.'],
          ['6', <code>chl_gradient</code>, '0.291', 'Spatial sharpness of the chlorophyll field.'],
          ['7', <code>doy_cos</code>, '0.259', 'Season.'],
          ['8', <code>po4</code>, '0.200', 'Phosphate.'],
          ['9', <code>chl_accel</code>, '0.192', 'Is the growth rate itself accelerating.'],
          ['13', <code>upwelling_index_roll30_std</code>, '0.096', 'Variability of upwelling over the past 30 days.'],
        ]}
      />
      <p>
        At t+7 the split of total |SHAP| is <strong>chlorophyll and its 18 derivatives 36.8%</strong>{' '}
        against <strong>14.4% for all 41 wind-derived features combined</strong>. Wind is a real
        but secondary contributor.
      </p>
      <Callout kind="lesson" title="A sanity check that passed">
        <p>
          The highest-ranked <em>upwelling</em> features at t+7 are the 30-day rolling statistics
          — <code>upwelling_index_roll30_std</code> at rank 16 and{' '}
          <code>upwelling_index_roll30_mean</code> at rank 28 — rather than any instantaneous
          value. That is the physically expected shape: sustained upwelling over weeks drives
          nutrient supply, not one windy day. When a feature ranks the way the physics predicts it
          should, that is mild evidence it is measuring what it claims to.
        </p>
      </Callout>

      <h2 id="the-wrong-numbers">The earlier, higher, worse numbers</h2>
      <p>
        An earlier 2020–2021 run reported t+3 0.755 / t+5 0.525 / t+7 0.468 — higher absolute
        numbers that were <strong>worse models</strong>. Two compounding problems:
      </p>
      <p>
        <strong>1. It lost to persistence at t+5 and t+7</strong> (0.548 and 0.492). Invisible
        without the baseline.
      </p>
      <p>
        <strong>2. Even those figures were propped up by an evaluation artifact.</strong> They came
        from fitting on train + validation, i.e. right up to the test boundary. Moving the
        validation slice out of training — necessary to have anything to calibrate on — collapsed
        the model:
      </p>
      <Table
        headers={['Training window', 'PR-AUC', 'ROC-AUC', 'TSS']}
        numeric={[1, 2, 3]}
        rows={[
          ['train + val, ends Sep 2021', '0.468', '0.764', '0.389'],
          ['train only, ends May 2021', '0.235', <Poor>0.531</Poor>, '0.064'],
        ]}
        caption="ROC-AUC 0.53 is chance. A 3.5-month gap between the end of training and the start of testing destroyed it. On six years of data the same honest gap gives 0.841."
      />
      <Callout kind="lesson" title="The lesson worth keeping">
        <p>
          The current numbers are <em>lower</em> and far more trustworthy. Absolute metric values
          are not comparable across evaluation setups, and{' '}
          <strong>a rising number can mean a leakier evaluation rather than a better model</strong>.
          If your score jumps after a change, the first question is what the change did to the
          split, not whether to celebrate.
        </p>
      </Callout>

      <h2 id="caveats">Caveats that still stand</h2>
      <ul>
        <li>
          <strong>Weak labels.</strong> Everything here trains on modelled chlorophyll above a
          percentile. Verified in-situ blooms would be far rarer, and the whole class-imbalance
          strategy would need revisiting with them.
        </li>
        <li>
          <strong>No toxicity classification.</strong> "Bloom" here does not mean "harmful". Stage
          2 needs in-situ genus and toxin data that is not openly available for this coastline.
        </li>
        <li>
          <strong>Regime shift is the dominant risk.</strong> Six years contains five monsoon
          seasons. ENSO and the Indian Ocean Dipole operate on longer cycles than that, so a
          sufficiently unusual year remains outside what the model has seen. The MESS metric,
          described in <Link to="/docs?c=metrics">Metrics</Link>, is how you detect that at
          prediction time.
        </li>
      </ul>

      <Formula
        expr={'PYTHONPATH=. .venv/bin/python -m hab_early_warning.src.pipeline'}
        where="~13 minutes: three horizons × (four rolling-origin folds + a final fit + isotonic calibration + SHAP) of LightGBM over 3.84M grid-cell-days with 136 features. Peak memory ~2.5 GB."
      />
    </>
  );
}
