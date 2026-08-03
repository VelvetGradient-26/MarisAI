/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Callout, Code, Table, Term } from '../primitives';

export function Validation() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Validation &amp; leakage</h1>
      <p className="docs-article__lede">
        The chapter that generalises furthest beyond this project. Everything here is about one
        question: is the number you are reporting a measurement of your model, or an artefact of
        how you split the data? On autocorrelated geophysical data the default answer is
        "artefact", and you have to work to change it.
      </p>

      <h2 id="why-random-fails">Why random K-fold fails on this data</h2>
      <p>
        Random cross-validation assumes rows are independent draws from one distribution. Ocean
        data violates that in both dimensions at once:
      </p>
      <ul>
        <li>
          <strong>In time.</strong> Today's chlorophyll field is nearly identical to yesterday's.
          A random split puts a cell's Tuesday in training and its Wednesday in test.
        </li>
        <li>
          <strong>In space.</strong> This pixel is nearly identical to the one next to it. A
          random split puts one half of a survey transect in training and the other in test.
        </li>
      </ul>
      <p>
        In both cases the model is scored on near-duplicates of rows it already saw. That is not
        a mild inaccuracy; it is a way of measuring memorisation and calling it generalisation.
      </p>

      <h2 id="splitters">The three splitters</h2>
      <p>
        All three live in <code>marine_ml/validation/splits.py</code> and are shared by both
        problems.
      </p>

      <h3>1. Rolling-origin splits, with an embargo</h3>
      <p>Expanding-window time-series cross-validation. Used for Problem A.</p>
      <Code>{`fold 1:  [====== train ======]  ××  [== test ==]
fold 2:  [========== train ==========]  ××  [== test ==]
fold 3:  [============== train ==============]  ××  [== test ==]
fold 4:  [================== train ==================]  ××  [== test ==]

  ××  =  embargo gap, exactly "horizon" days wide`}</Code>
      <p>
        Training always precedes testing, and the first fold starts after 30% of the record so
        there is something to train on. The <Term>embargo gap</Term> is the part people skip: the
        label at time <em>t</em> is chlorophyll at <em>t+7</em>, so a training row within 7 days
        of the test window shares its target's observation period. Without the gap, part of the
        test period's information is inside training and the score is fiction.
      </p>

      <h3>2. Spatial block splits</h3>
      <p>Used for Problem B. Points are binned into 3° squares and whole blocks are held out.</p>
      <p>
        The block size must exceed the autocorrelation range of the drivers. 3° is ~330 km, which
        comfortably exceeds mesoscale eddy scales here. Too small and adjacent blocks are still
        correlated; too large and you have too few blocks to make folds from.
      </p>

      <h3>3. Leave-one-region-out</h3>
      <p>
        Coarser and more honest still, for the specific question "does this transfer to a
        coastline segment we never trained on". Sub-basins are labelled by the conventional
        oceanographic boundaries — the Indian peninsula at ~77°E separates the Arabian Sea from
        the Bay of Bengal, ~5°N marks the transition to the equatorial Indian Ocean.
      </p>

      <h3>Plus: the chronological three-way split</h3>
      <p>
        Separately from cross-validation, the final fit uses a plain calendar-time split: 70%
        train, 15% validation, 15% test. The test period is the most recent slice and is touched
        exactly once, at the end. Validation exists specifically so there is a slice to calibrate
        probabilities on that is neither training nor test.
      </p>

      <h2 id="structural">Leakage prevention is structural, not procedural</h2>
      <p>
        "Be careful" is not a strategy. Every fit-then-apply pair in the codebase is split into
        two named functions, so fitting on the wrong rows requires actively passing the wrong
        frame:
      </p>
      <Table
        headers={['Fit (training rows only)', 'Apply (everywhere)', 'What would leak']}
        rows={[
          [
            <code>fit_climatology</code>,
            <code>apply_climatology</code>,
            "The test period's own mean, folded into every anomaly feature.",
          ],
          [
            <code>fit_bloom_thresholds</code>,
            <code>apply_bloom_thresholds</code>,
            'The test period\'s distribution, folded into the definition of the target itself — leakage of an especially confusing kind, because it corrupts the label rather than a feature.',
          ],
          [
            <code>fit_thermal_niche</code>,
            <code>apply_thermal_niche</code>,
            'Held-out temperatures, folded into a training feature.',
          ],
        ]}
      />
      <p>Three more structural rules:</p>
      <ul>
        <li>
          <strong>Rolling windows are trailing and shifted by one step</strong>, so the value at{' '}
          <em>t</em> summarises strictly earlier observations.
        </li>
        <li>
          <strong>Lags shift backwards on dates, not on row positions</strong>, so a gap in a
          cell's series produces NaN rather than silently borrowing an adjacent row.
        </li>
        <li>
          <strong>Exactly one forward shift exists in the codebase</strong> — the target
          construction in <code>hab_early_warning/src/labels.py</code>. It is isolated there
          specifically so the audit is a one-file question.
        </li>
      </ul>

      <h2 id="tests">Tests that the pipeline cannot cheat</h2>
      <p>
        <code>tests/test_leakage.py</code> is not a test of model quality. Every test in it
        corresponds to a specific way this kind of system reports skill it does not have.
      </p>
      <p>
        The fixture is deliberately adversarial: two cells, 60 consecutive days, a{' '}
        <strong>strictly increasing</strong> value per cell. Monotonic values make time-direction
        errors impossible to miss — if a "backward" feature ever exceeds the current value, it read
        the future.
      </p>
      <Table
        headers={['Test', 'What it prevents']}
        rows={[
          [<code>test_lag_features_look_backwards</code>, 'A lag with the wrong sign.'],
          [<code>test_lag_features_do_not_cross_cells</code>, "One grid cell's history leaking into another's."],
          [
            <code>test_rolling_features_exclude_current_timestep</code>,
            'A "past 7 days" window that quietly includes today.',
          ],
          [<code>test_difference_features_are_backward</code>, 'A growth rate computed from the future.'],
          [
            <code>test_climatology_fitted_on_training_only_does_not_see_test</code>,
            'A climatology fitted over the full record.',
          ],
          [
            <code>test_rolling_origin_train_always_precedes_test_with_a_gap</code>,
            'Folds that overlap or abut without an embargo.',
          ],
          [
            <code>test_spatial_blocks_hold_out_whole_blocks</code>,
            'A spatial fold whose held-out points sit next to training points.',
          ],
          [
            <code>test_training_stride_drops_whole_days_not_cells</code>,
            'Subsampling that would leave incomplete spatial fields.',
          ],
          [
            <code>test_fusion_rejects_a_covariate_that_would_truncate_the_record</code>,
            'A half-finished fetch silently shrinking the training record.',
          ],
        ]}
        caption="Plus physics tests — that the upwelling index has the right sign for an upwelling-favourable wind, that it is masked at the equator, that Ekman pumping's sign matches the physics, and that the stress-based and bulk-formula indices agree in sign."
      />

      <Callout kind="lesson" title="Why physics assertions belong in the test suite">
        <p>
          A sign error in the Coriolis term or the alongshore projection produces a feature that
          is smoothly wrong everywhere — no NaNs, no crashes, plausible magnitudes, and a model
          that quietly learns the inverse relationship. The only way to catch it is to assert the
          expected sign for a wind you constructed to be unambiguously upwelling-favourable.
        </p>
      </Callout>

      <h2 id="checklist">A portable checklist</h2>
      <p>If you take one thing from this chapter to your own project:</p>
      <ol>
        <li>
          <strong>Ask what your rows are correlated along</strong> — time, space, patient, user,
          device, session — and split along that, not at random.
        </li>
        <li>
          <strong>Put a gap between train and test</strong> whenever your label is computed over a
          window of future observations.
        </li>
        <li>
          <strong>Any statistic that defines your target must be fitted on training rows only.</strong>{' '}
          Thresholds, normalisations, encodings, class definitions.
        </li>
        <li>
          <strong>Always score a stupid baseline on every fold.</strong> Persistence, majority
          class, last value. If you cannot beat it you have learned nothing, and you will not
          notice from the AUC alone.
        </li>
        <li>
          <strong>Be suspicious of improvements.</strong> When a change makes the score jump, first
          ask what it did to the split.
        </li>
      </ol>
    </>
  );
}
