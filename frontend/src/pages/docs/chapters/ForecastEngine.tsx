/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Code, Formula, Table, Term } from '../primitives';

export function ForecastEngine() {
  return (
    <>
      <p className="docs-article__eyebrow">Forecasting engine</p>
      <h1>One framework, every variable</h1>
      <p className="docs-article__lede">
        The two machine learning problems in the previous section each answer one question with
        one purpose-built model. This is the opposite kind of system: a single pipeline that
        forecasts <em>any</em> variable the platform carries, where adding a new one is a block
        of YAML and a training run rather than a new model implementation. Thirty-one of the
        thirty-two configured variables are trained today, as 115 models.
      </p>

      <h2 id="shape">The shape of it</h2>
      <Code>{`variable + point + horizon
        │
        ▼
  history adapter ──► preprocessing ──► feature engineering
        │                                       │
        │                                       ▼
        │                          one LightGBM per (variable, horizon)
        │                                       │
        ▼                                       ▼
   provenance              prediction + interval + SHAP drivers`}</Code>
      <p>
        Nothing in the package branches on a variable's name. The history adapter asks the same
        download registry that serves the <Link to="/download">downloader</Link>, so a variable
        that can be downloaded can be forecast, and a variable that cannot is rejected at import
        time rather than at 3am inside a training run.
      </p>

      <h3>Adding a variable is three steps and no Python</h3>
      <Code>{`# 1. confirm the code exists and is available: true in
#    services/download/registry.py — that is what supplies its history

# 2. add a block to forecasting/config/forecasting.yaml
turbidity:
  code: turbidity
  covariates: [chlorophyll_a, significant_wave_height]
  valid_min: 0.0
  log_transform: true

# 3. train it
python scripts/train_forecasting.py --variable turbidity`}</Code>
      <p>
        An empty block — <code>turbidity: {'{code: turbidity}'}</code> — is valid and inherits
        every default. What you get back is not just a model: the metric page at{' '}
        <code>/dashboard/turbidity</code> renders completely with no frontend edit, because that
        page resolves the variable against the catalog and each section declares the{' '}
        <em>capability</em> it needs rather than a list of variable names.
      </p>

      <h2 id="delta">The finding that made it work at all</h2>
      <p>
        The first version of this engine fitted models on the value itself, which is the obvious
        thing to do, and it scored <strong>worse than persistence at every horizon</strong> —
        including one day ahead, where forecasting is easiest.
      </p>
      <Callout kind="jargon" title="Persistence">
        <p>
          The trivial forecast: tomorrow will be the same as today. On ocean variables this is a
          genuinely hard baseline, because the ocean has enormous inertia — sea surface
          temperature at a point rarely moves much in a day. Any real forecast has to beat it,
          and many published ones quietly do not.
        </p>
      </Callout>
      <Table
        headers={['Horizon', 'RMSE (level)', 'RMSE (delta)', 'Persistence', 'Skill: level → delta']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['1 day', '0.831', '0.702', '0.785', '−0.122 → +0.201'],
          ['3 days', '1.191', '1.062', '1.173', '−0.030 → +0.181'],
          ['7 days', '1.430', '1.246', '1.341', '−0.137 → +0.138'],
        ]}
        caption="Same data, same features, same hyperparameters. The only change is what the model is asked to predict."
      />
      <p>
        The reason is structural, not a tuning problem. A gradient-boosted tree predicts a
        piecewise-constant function, so it <em>cannot represent the identity</em>{' '}
        <code>y(t+h) = y(t)</code>. On a strongly autocorrelated series that identity is
        precisely what the baseline is, so the model was being asked to reconstruct, from
        scratch and imperfectly, a function it has no way to express.
      </p>
      <p>
        Fitting on the <strong>change</strong> instead makes persistence the constant zero —
        which a tree represents exactly. The model starts at parity with the baseline and only
        ever learns the departure from it.
      </p>
      <Formula
        expr="target = y(t+h) − y(t),   prediction = y(t) + model(features)"
        where={
          <>
            <code>defaults.target_mode: delta</code>. Because decoding needs{' '}
            <code>y(t)</code> as an anchor, a missing final observation is a hard error rather
            than a guess — the one thing the predictor refuses to improvise.
          </>
        }
      />
      <Callout kind="lesson" title="Why the skill score is not optional">
        <p>
          Every metric except skill looked <em>fine</em> on the level-fitted models. R² was high,
          RMSE was small in absolute terms, the charts looked like forecasts. The models were
          simply worse than doing nothing, and nothing in a conventional metrics table says so.
        </p>
        <p>
          The <code>skill_score</code> metric compares against persistence on every fold, and the
          training log prints <code>WORSE THAN PERSISTENCE</code> in as many words. It exists so
          this class of failure cannot ship quietly, and it is the reason a dozen trained
          horizons were deleted rather than served.
        </p>
      </Callout>

      <h2 id="global">Global models, not per-point models</h2>
      <p>
        Each model is fitted across <strong>24 ocean points at once</strong> — Arabian Sea, Bay
        of Bengal, Kuroshio, Gulf Stream, Peru and Benguela upwellings, Southern Ocean and so on
        — with latitude, longitude, ocean depth and basin as features. One model per (variable,
        horizon), not per (variable, horizon, place).
      </p>
      <p>
        That is what lets a user click an arbitrary coordinate and get an answer. A per-point
        model would only ever score the points it was trained on, and the map is global. It also
        means the geographic spread of the training points is part of the model's validity: a
        variable that lost its southern-hemisphere points to a provider outage would extrapolate
        across the equator, which is why every training run records{' '}
        <code>skipped_points</code> and why partial success is treated as a failure mode rather
        than a partial win.
      </p>

      <h2 id="features">Features, and the single forward shift</h2>
      <p>
        Between 59 and 116 features per model, depending on how many covariates the variable
        declares. All of them are built by one shared module:
      </p>
      <Table
        headers={['Family', 'What it contributes']}
        rows={[
          ['Lags', 'The value 1, 3, 7, 14 and 30 steps back.'],
          ['Rolling statistics', 'Mean, standard deviation, min and max over 7, 14 and 30 steps.'],
          ['Differences', 'Step-to-step change — the recent direction of travel.'],
          ['Trends', 'Slope over the last 7 and 30 steps.'],
          ['Calendar & cyclical', 'Day of year and month, encoded as sine/cosine pairs so December is adjacent to January.'],
          ['Static', 'Latitude, longitude, ocean depth, basin — what makes the model global.'],
          ['Covariates', "Each declared covariate's own lags and rolling statistics."],
        ]}
      />
      <Callout kind="warn" title="Exactly one forward shift exists in this package">
        <p>
          <code>add_forecast_target</code> is the only place anything looks forward, because
          that is the target. Everything else is trailing by construction, and a test scans the
          package source and fails if a second forward shift ever appears — so the property
          holds for features nobody has written yet.
        </p>
        <p>
          Rolling windows close at <code>t</code> <em>inclusive</em>, which is safe only because
          the horizon is always at least 1; a horizon of 0 is rejected rather than discouraged.
          Closing at <code>t−1</code> instead would silently discard the most recent observation
          and make every model behave like the next horizon up.
        </p>
      </Callout>

      <h2 id="validation">Validation is chronological, with a gap</h2>
      <p>
        Five <Term>rolling-origin</Term> folds: train on everything before a cut point, test on
        what follows, then move the cut forward and expand the training set. Never a random
        split — on a series this autocorrelated, a random split puts yesterday in training and
        today in test, and measures memorisation.
      </p>
      <p>
        Between train and test sits an <Term>embargo</Term> gap defaulting to the forecast
        horizon itself. Without it, a training row within <code>h</code> steps of the test window
        shares part of its target period with the test rows, which is leakage even though no
        individual row was duplicated.
      </p>

      <h2 id="uncertainty">What a prediction carries with it</h2>
      <Table
        headers={['Component', 'How it is produced']}
        rows={[
          ['Prediction', <>Decoded from the delta against the latest observation.</>],
          [
            'Confidence interval',
            <>
              Residual bootstrap over the validation residuals — 500 resamples, 95% by default.
              Not a model-reported variance: an empirical spread of how wrong this model actually
              was.
            </>,
          ],
          [
            'Top drivers',
            <>
              TreeSHAP per prediction, with humanised feature names, so the answer to "why" is
              per-request rather than a global importance chart.
            </>,
          ],
          ['Data quality', <>Row count, and which gaps were filled versus left unfilled.</>],
          ['Sources', <>Every upstream dataset that contributed, by name.</>],
        ]}
      />

      <h2 id="operations">Four operational findings</h2>
      <h3>A fetch needs a timeout, not just a retry</h3>
      <p>
        The most expensive failure here was not an error. A Copernicus zarr read simply never
        returned, and a training run sat on it for <strong>98 minutes</strong> looking perfectly
        healthy — process alive, no exception pending, nothing that would ever have raised.
        Silence and progress are indistinguishable without a deadline. Each attempt is now
        bounded at 300 seconds and retried per <em>provider</em>, rather than retrying the whole
        group and re-issuing slow reads to work around one fast blip.
      </p>

      <h3>Retry only what can succeed — but 404 is not proof of permanence</h3>
      <p>
        Retrying a permanently failed request three times with backoff adds about 8 seconds to{' '}
        <em>every</em> forecast, turning a warm 2.2-second response into 14.5. So 408, 425, 429
        and 5xx retry; 400, 403, 410 and 422 never do. The interesting case is 404, which retries
        exactly once: ERDDAP servers unload a dataset while reloading it and answer 404
        "Currently unknown datasetID" meanwhile, indistinguishably from a dataset that was
        genuinely removed. A reload window recovers; a dead dataset costs one 2-second backoff.
      </p>

      <h3>Every horizon must request the same window</h3>
      <p>
        The fetch window is padded by the variable's <em>largest</em> configured horizon, not the
        one being trained. Padding by the current horizon shifts the start date each pass, which
        changes the cache key, which silently refetches all 24 points once per horizon — a 4×
        cost that presents as nothing but slowness. A test asserts on the cache keys the trainer
        actually emits.
      </p>

      <h3>Outlier filtering is off, from measurement</h3>
      <p>
        Every source behind this engine is a quality-controlled model or reanalysis product, not
        a raw instrument. Run against real Copernicus SST, a Hampel filter flagged{' '}
        <strong>5–12% of a clean daily series</strong> at every window and threshold tried: its
        local-scale assumption inverts on a smooth field, and in one 365-day series 74 values had
        a local median absolute deviation of <em>exactly zero</em> precisely because the field is
        smooth. Interpolating over 12% of a good record is the same fabrication this platform
        refuses everywhere else. Turning it off raised 7-day skill from +0.138 to +0.202.
      </p>

      <h2 id="api">The API</h2>
      <Table
        headers={['Endpoint', 'Purpose']}
        rows={[
          [<code>POST /api/v1/forecast</code>, 'One variable, one point, one horizon.'],
          [<code>POST /api/v1/forecast/batch</code>, 'Several horizons at one point — the forecast curve.'],
          [<code>GET /api/v1/forecast/catalog</code>, 'What can be forecast, and what is actually trained.'],
          [<code>GET /api/v1/forecast/models</code>, 'Registry contents with headline metrics.'],
          [<code>GET /api/v1/forecast/models/{'{variable}/{horizon}'}</code>, 'Full metrics, folds, SHAP importance, diagnostics.'],
        ]}
      />
      <p>
        Status codes follow the dashboard's rule: an untrained model is a <strong>404 that tells
        you how to train it</strong>, not a 500, and a configured-but-untrained variable appears
        in the catalog with <code>available: false</code> and a reason, so the interface can grey
        it out rather than offer a forecast that fails. Training is offline only — a forecast
        request must never be able to start a job that fetches two years of data from 24 points.
      </p>
      <p>
        Diagnostics are served as JSON arrays rather than images, so charts render in the
        viewer's theme rather than as a PNG baked at training time in whichever theme the
        trainer happened to use.
      </p>
    </>
  );
}
