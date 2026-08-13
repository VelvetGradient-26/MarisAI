/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Best, Callout, Code, Poor, Table } from '../primitives';

export function Results() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Results, in one place</h1>
      <p className="docs-article__lede">
        Every measured number from the runs in this repository, collected. These are results, not
        targets — reproduce them with the commands at the bottom, and the artifacts land in{' '}
        <code>machine_learning/reports/</code>.
      </p>

      <h2 id="hab-holdout">Problem A — HAB, held-out period</h2>
      <p>
        2021. 577,608 grid-cell-days. Bloom rate 7.3–7.6% depending on horizon. Scored once, at
        the end.
      </p>
      <Table
        headers={['Horizon', 'Model PR-AUC', 'Persistence PR-AUC', 'ROC-AUC', 'TSS', 'Brier (raw → cal.)']}
        numeric={[1, 2, 3, 4, 5]}
        rows={[
          ['t+3', <Best>0.661</Best>, '0.511', '0.942', '0.751', '0.056 → 0.038'],
          ['t+5', <Best>0.493</Best>, '0.384', '0.884', '0.635', '0.073 → 0.049'],
          ['t+7', <Best>0.362</Best>, '0.309', '0.841', '0.564', '0.085 → 0.057'],
        ]}
        caption="The model beats the persistence baseline at every horizon. Base rate is ~0.074, so t+7's PR-AUC of 0.362 is roughly 5× chance."
      />

      <h3>Rolling-origin cross-validation (4 folds)</h3>
      <p>Mean PR-AUC across folds, model versus baseline:</p>
      <Table
        headers={['Horizon', 'LightGBM', 'Persistence', 'Holdout (for comparison)']}
        numeric={[1, 2, 3]}
        rows={[
          ['t+3', '0.653', '0.449', '0.661'],
          ['t+5', '0.474', '0.335', '0.493'],
          ['t+7', '0.363', '0.271', '0.362'],
        ]}
        caption="Cross-validation and the final holdout agree closely at every horizon. That agreement is the reason to believe the holdout number rather than treat it as one lucky period."
      />

      <h3>Operating point at 80% recall</h3>
      <Table
        headers={['Horizon', 'Threshold', 'Precision', 'Recall', 'False-alarm rate', 'Deployable?']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['t+3', '0.178', '0.449', '0.807', '0.551', <Best>Plausibly</Best>],
          ['t+5', '0.122', '0.280', '0.801', '0.720', 'Marginal'],
          ['t+7', '0.094', '0.202', '0.811', '0.798', <Poor>No</Poor>],
        ]}
        caption="Four in five week-ahead alerts are false. The three-day alert, where roughly half of alerts are genuine, is the one that would survive contact with a coastal agency."
      />

      <h2 id="habitat-results">Problem B — fish habitat</h2>
      <h3>Spatial block cross-validation, 5 folds, 3° blocks</h3>
      <Table
        headers={['Model', 'ROC-AUC', 'PR-AUC', 'TSS', 'Boyce']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['LightGBM', '0.959', '0.896', <Best>0.826</Best>, '0.892'],
          ['Random Forest', '0.953', '0.888', '0.821', <Best>0.955</Best>],
          ['MaxEnt', '0.861', '0.672', '0.619', '0.944'],
        ]}
      />
      <h3>Held-out spatial block — 885 points, 167 presences</h3>
      <Table
        headers={['Model', 'ROC-AUC', 'PR-AUC', 'TSS', 'Boyce']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['LightGBM', <Best>0.946</Best>, <Best>0.816</Best>, '0.788', '0.895'],
          ['Random Forest', '0.927', '0.741', '0.774', '0.927'],
          ['Ensemble', '0.944', '0.803', <Best>0.792</Best>, '0.905'],
          ['MaxEnt', <Poor>0.722</Poor>, <Poor>0.365</Poor>, <Poor>0.365</Poor>, '0.884'],
        ]}
        caption="9.0% of held-out points are environmentally extrapolating (MESS < 0); median MESS 0.44."
      />

      <h2 id="dataset-sizes">Dataset sizes</h2>
      <Table
        headers={['', 'Problem A (HAB)', 'Problem B (habitat)']}
        rows={[
          ['Rows', '≈ 3.84 million grid-cell-days', '2,787 labelled points'],
          ['Positives', '≈ 8% (weak labels)', '877 presences (31.5%)'],
          ['Features', '136', '40'],
          ['Region', 'Arabian Sea, 68–78°E / 6–23°N', 'North Indian Ocean, 55–95°E / 5°S–25°N'],
          ['Window', '2016–2021, daily', '2000–2013, monthly'],
          ['Grid', '0.25°', '0.25°'],
          ['Raw data on disk', '≈ 840 MB (both profiles combined)', ''],
        ]}
      />

      <h2 id="two-stories">The two results that got worse, and why that was progress</h2>

      <Callout kind="lesson" title="1. HAB: t+3 fell from 0.755 to 0.661">
        <p>
          The higher number came from fitting on train + validation, right up to the test
          boundary, on a two-year window whose label rate was drifting badly (bloom rate 10.4% →
          16.5% → 21.2% across the three periods). Moving the validation slice out of training
          exposed it: the seven-day model dropped to ROC-AUC 0.53, which is chance.
        </p>
        <p>
          Fixing the window to six years flattened the label drift (10.2% → 9.4% → 7.6%) and moved
          t+7 from chance to ROC-AUC 0.841. The reported t+3 is lower and trustworthy.
        </p>
      </Callout>

      <Callout kind="lesson" title="2. Habitat: TSS rose from 0.53 to 0.788 — after finding the model had no species input">
        <p>
          The opposite direction, same discipline. The original model's feature list was
          discovered by inspecting the table, and it happened to be computed before the thermal
          niche columns existed. With <code>species_key</code> also excluded, the model had{' '}
          <strong>no species-dependent input at all</strong> — five species sharing one pooled
          surface.
        </p>
        <p>
          It was caught by checking whether the exported per-species map tiles differed. They were
          byte-identical. No metric would have revealed it.
        </p>
      </Callout>

      <h2 id="reproduce">Reproducing all of this</h2>
      <Code>{`cd machine_learning
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

export PYTHONPATH=.

.venv/bin/python scripts/fetch_raw.py                      # ~4 min, ~840 MB
.venv/bin/python -m fish_habitat_prediction.src.pipeline   # ~1 min
.venv/bin/python -m hab_early_warning.src.pipeline         # ~13 min

.venv/bin/python -m pytest -q                              # the anti-cheating tests`}</Code>
      <Callout kind="lesson" title="These tests were invisible for longer than they should have been">
        <p>
          A bare <code>pytest</code> used to fail at collection with{' '}
          <code>ModuleNotFoundError: No module named 'marine_ml'</code> — there was no{' '}
          <code>pyproject.toml</code>, <code>pytest.ini</code> or <code>setup.cfg</code> anywhere
          in <code>machine_learning/</code>, so the package was only importable if you happened to
          set <code>PYTHONPATH</code> first.
        </p>
        <p>
          Worse than a normal broken path, because of <em>what</em> these tests are: they are what
          enforce "only one forward shift exists", "never random K-fold" and "climatology fitted on
          training rows only". The guardrails against silent methodology error were the thing
          invisible to anyone running pytest the obvious way. A <code>pytest.ini</code> fixed it;
          the <code>PYTHONPATH</code> export above is still needed for the pipelines themselves.
        </p>
      </Callout>
      <p>
        Copernicus credentials are read from the backend's untracked <code>backend/.env</code> —
        there is deliberately no second place for secrets to live. Both pipelines cache their
        built feature table and reuse it; pass <code>--refresh-features</code> to rebuild.
      </p>

      <h3>What lands in <code>reports/</code></h3>
      <Table
        headers={['File', 'Contents']}
        rows={[
          [<code>hab_early_warning_fold_scores.csv</code>, 'Every rolling-origin fold, model and baseline, all three horizons.'],
          [<code>hab_early_warning_holdout.csv</code>, 'Held-out scores: raw, calibrated, and persistence.'],
          [<code>hab_early_warning_reliability_t{'{3,5,7}'}.csv</code>, 'Calibration curves, raw versus calibrated.'],
          [<code>hab_early_warning_shap_t{'{3,5,7}'}.csv</code>, 'Full SHAP ranking per horizon.'],
          [<code>fish_habitat_fold_scores.csv</code>, 'Every spatial fold × every model tier.'],
          [<code>fish_habitat_holdout.csv</code>, 'Held-out block, all four models, plus MESS.'],
          [<code>fish_habitat_shap.csv</code>, 'Full SHAP ranking.'],
          [<code>*_summary.json</code>, 'Operating points, ensemble weights, top features.'],
        ]}
      />
      <p>
        Predictions themselves are exported as NetCDF rasters plus a manifest, and served by the
        API — batch inference, not live inference, so what the <Link to="/map">map</Link> shows is
        exactly the artifact that was cross-validated. The numbers on this page are the ones that
        run produced; re-running the pipelines rewrites <code>reports/</code>, and this chapter is
        updated by hand from it.
      </p>

      <h3>Run history, because a rewritten report is a lost one</h3>
      <p>
        Every file above is written to a fixed filename, so each re-run destroys the previous
        result — which makes the one question that matters during modelling, <em>did that change
        help?</em>, unanswerable. Runs are therefore also appended to an MLflow store, one
        experiment per producer:
      </p>
      <Table
        headers={['Producer', 'How it logs', 'Experiment']}
        rows={[
          ['Fish habitat', <>on <code>save()</code></>, <code>fish_habitat_prediction</code>],
          ['HAB early warning', <>on <code>save()</code>, one run per horizon</>, <code>hab_early_warning</code>],
          ['Forecasting engine', <>JSON → <code>marine_ml.ingest_forecasting</code></>, <code>forecasting_engine</code>],
        ]}
      />
      <Code>{`cd machine_learning
uvx --from mlflow mlflow ui --backend-store-uri sqlite:///mlruns.db`}</Code>
      <p>
        The third row is the interesting one. The backend never learns that tracking exists: it
        writes an immutable directory of plain standard-library JSON per training invocation, and
        the ML side <em>reads</em> it. The dependency points inward rather than outward, so the
        backend keeps no modelling-infrastructure import — and a test asserts that, because the
        obvious later "improvement" is to log directly from the training script.
      </p>
      <p>
        What gets logged is deliberately more than a headline number: the fold <em>spread</em>
        sits beside the mean, and the shipping rule — overall skill above zero{' '}
        <em>and</em> at most one fold in five negative — is itself recorded as a metric. An
        aggregate that reads healthy over folds that include negatives is the failure this
        project keeps hitting. Tracking also never fails a training run: a HAB run is around 40
        minutes, and losing one to a locked database would be worse than not tracking at all, so
        every path degrades to a warning.
      </p>
    </>
  );
}
