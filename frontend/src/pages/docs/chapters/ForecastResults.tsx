/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Best, Callout, Poor, Table } from '../primitives';

export function ForecastResults() {
  return (
    <>
      <p className="docs-article__eyebrow">Forecasting engine</p>
      <h1>What it actually achieves</h1>
      <p className="docs-article__lede">
        Every number here is a validated skill score against persistence, read from each model's{' '}
        <code>metrics.json</code>. Thirty-one variables are trained and 115 models shipped —
        which is <em>not</em> 31 × 4, because a horizon that failed its folds was deleted rather
        than served. The deletions are the more informative half of this page.
      </p>

      <h2 id="reading">How to read a skill score</h2>
      <p>
        Skill compares the model's error against the trivial forecast's error on the same rows.
        Zero means "no better than assuming no change". Positive means the error shrank by that
        fraction: +0.20 is a 20% reduction in RMSE against persistence. Negative means the model
        is actively worse than doing nothing.
      </p>
      <Callout kind="note" title="These are not R² values, and they are much harder to inflate">
        <p>
          Most of these models also post an R² above 0.9, which sounds excellent and means very
          little: on an autocorrelated series, predicting "the same as yesterday" scores a high
          R² too. Skill removes exactly that free credit. A skill of +0.23 with an R² of 0.95 is
          an honest description of a useful model; the R² alone is not.
        </p>
      </Callout>

      <h2 id="distribution">Skill by horizon, across all 115 models</h2>
      <Table
        headers={['Horizon', 'Models', 'Median skill', 'Weakest', 'Strongest']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['+1 day', '30', '+0.231', '+0.063', '+0.529'],
          ['+3 days', '28', '+0.151', '+0.026', '+0.421'],
          ['+7 days', '28', '+0.201', '+0.077', '+0.428'],
          ['+30 days', '29', <Best>+0.357</Best>, '+0.081', '+0.494'],
        ]}
        caption="Every shipped model has positive skill; the weakest thing in the entire set is +0.026."
      />
      <p>
        <strong>Skill rises with horizon on nearly every variable</strong>, which is the opposite
        of what people expect and is the signature of a forecast doing real work. Persistence
        decays fast on a dynamic field — "the same as today" is a fine guess for tomorrow and a
        poor one for next month — while the model holds. A system that merely echoed the last
        value would show the reverse.
      </p>
      <p>
        The exceptions are diagnostic rather than embarrassing. Where skill <em>falls</em> with
        horizon — salinity, bottom temperature — the target barely moves at all, so persistence
        is close to unbeatable and there is little headroom to compete for.
      </p>

      <h2 id="families">By variable family</h2>
      <Table
        headers={['Family', 'Models', 'Weakest', 'Strongest']}
        numeric={[1, 2, 3]}
        rows={[
          ['Biogeochemistry', '23', '+0.077 (nitrate, +7d)', '+0.429 (silicate, +1d)'],
          ['Waves', '20', '+0.079 (wave direction, +1d)', '+0.428 (mean wave period, +30d)'],
          ['Ocean currents', '16', '+0.063 (current direction, +1d)', '+0.411 (current v, +30d)'],
          ['Meteorology', '15', '+0.167 (humidity, +3d)', <Best>+0.494 (air temperature, +30d)</Best>],
          ['Ocean colour', '12', '+0.026 (diffuse attenuation, +3d)', <Best>+0.529 (chlorophyll-a, +1d)</Best>],
          ['Wind', '12', '+0.118 (wind direction, +3d)', '+0.412 (wind speed, +30d)'],
          ['Temperature', '9', '+0.047 (water temperature, +3d)', '+0.439 (water temperature, +30d)'],
          ['Sea level', '6', '+0.091 (sea surface height, +7d)', '+0.394 (sea level anomaly, +3d)'],
          ['Salinity', '2', '+0.153 (+30d)', '+0.179 (+1d)'],
        ]}
      />
      <p>
        <strong>Chlorophyll-a at +1 day (+0.529) is the strongest result in the repository</strong>{' '}
        — a 31% error reduction against persistence — and it is strong for the mirror-image
        reason that salinity is weak. Chlorophyll is patchy and advected, it moves between one
        day and the next, so persistence is a weak baseline with real headroom above it. The
        variables where the ocean barely changes are the ones where there is nothing to win.
      </p>
      <p>
        Salinity holds only two models for a reason covered below, and it is the clearest case in
        the set of the difference between a model that is bad and a target that is easy.
      </p>

      <h2 id="the-bar">The bar, and why the headline number is not it</h2>
      <p>
        A horizon ships only if <strong>overall skill is above zero <em>and</em> at most one of
        five validation folds is negative</strong>. The second clause is the load-bearing one:
        the training log prints the aggregate, and <strong>six</strong> of the rejected horizons
        below print <code>beats persistence</code> on it. Every shipped horizon was re-read from
        its per-fold scores rather than accepted from the summary line.
      </p>
      <Table
        headers={['Rejected', 'Aggregate said', 'Folds said']}
        rows={[
          [
            <><code>sea_surface_salinity</code> — dropped entirely</>,
            'two horizons passed',
            <>+3d <Poor>−0.152</Poor>, +7d <Poor>−0.118</Poor>; the passing horizons sat inside fold noise</>,
          ],
          [
            <><code>water_salinity</code> +3d, +7d</>,
            'marginal',
            <>−0.065 with 3/5 folds negative; −0.029 with 4/5</>,
          ],
          [
            <><code>bottom_temperature</code> +3d, +7d, +30d</>,
            'marginal',
            <>−0.056, −0.060, −0.025 (4/5 folds negative)</>,
          ],
          [
            <><code>humidity</code> +1d</>,
            'marginal',
            <>−0.020 with 2/5 negative, one at −0.435</>,
          ],
          [
            <><code>nitrate</code> +3d</>,
            <>+0.050 — <em>beats persistence</em></>,
            <>folds span −0.123 to +0.208; the mean is carried by a minority</>,
          ],
          [
            <><code>sea_level_anomaly</code> +7d, +30d</>,
            <>+0.073 and +0.111 — <em>beats persistence</em></>,
            <>2/5 folds negative on each; +7d spans −0.296 to +0.222</>,
          ],
        ]}
        caption="One variable dropped outright and nine further horizons trained, measured and deleted."
      />
      <Callout kind="lesson" title="An average is not a result">
        <p>
          <code>sea_level_anomaly</code> at +7 days is the cleanest example in the project. It
          posted +0.073 overall and the training log said <code>beats persistence</code>. Its
          five folds were −0.296, +0.186, +0.222, +0.110 and −0.006 — a model that helps in some
          periods and hurts badly in others, averaged into something that looks like modest
          competence.
        </p>
        <p>
          Shipping it would have put a forecast on the map that is worse than useless whenever
          conditions resemble fold one, with nothing in the interface to say so. The fold spread
          is logged beside the mean in experiment tracking for this exact reason, and the
          shipping rule is itself recorded as a metric.
        </p>
      </Callout>

      <h3>Where the decision differed, and why</h3>
      <p>
        <code>sea_surface_salinity</code> was dropped entirely while <code>water_salinity</code>{' '}
        kept its +1d and +30d models, which looks inconsistent until you read the folds. Surface
        salinity's best horizon was a noisy +0.085; water salinity's +1d is +0.179 with zero
        negative folds, tightly clustered between +0.110 and +0.225. The physics is the same; the
        evidence is not, and the decision follows the evidence rather than the family.
      </p>
      <p>
        The weakest thing kept anywhere is <code>diffuse_attenuation</code> at +3 days, +0.026
        with one fold in five negative. If the bar is ever tightened, that is the first model to
        revisit.
      </p>

      <h2 id="coverage">The failure mode that is worse than an error</h2>
      <p>
        Two variables needed Open-Meteo, whose free tier ran out mid-run — training the full
        variable set in one day exceeds the daily quota. The two failures did not look alike, and
        the difference matters more than the outage did.
      </p>
      <p>
        <code>sea_level_anomaly</code> failed <strong>loudly</strong>: all 24 points were lost, so
        the run raised a hard error and wrote nothing. <code>rainfall</code>{' '}
        <strong>degraded silently</strong> — enough points survived to train a model, but only 10
        of 24, every one of them in the northern hemisphere, with a different subset per horizon.
        Its metrics looked fine.
      </p>
      <p>
        Those models were deleted rather than shipped. A global model carries latitude as a
        feature, so one trained without a single southern-hemisphere point would extrapolate
        across the equator on the one variable whose seasonality inverts there. On the retrain,
        rate limiting still cost three or four points per horizon, but each horizon kept four of
        the six southern points — and that, not the skill score, is what made the retrain
        shippable:
      </p>
      <Table
        headers={['Rainfall', 'Skill', 'Folds negative', 'Points', 'Southern points']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['+1 day', '+0.334', '0/5', '21/24', '4/6'],
          ['+3 days', '+0.421', '0/5', '20/24', '4/6'],
          ['+7 days', '+0.428', '0/5', '21/24', '4/6'],
          ['+30 days', <Best>+0.475</Best>, '0/5', '21/24', '4/6'],
        ]}
      />
      <p>
        The first attempt at +1 day kept only 14 of 24 points despite clean folds, and was
        retrained on its own to reach 21. Every artifact records <code>skipped_points</code> with
        the reason, which is the only thing that made any of this reviewable — skill and folds
        can look perfect on a model that has quietly lost a third of the planet.
      </p>

      <h2 id="untrained">What is deliberately not trained</h2>
      <p>
        One variable of the 32. <code>sea_surface_salinity</code> is configured, its provider
        works, and it will not be trained — the YAML block says so, with the numbers, so that
        nobody retrains it in the belief that it was an oversight. Point salinity barely moves
        day to day, which makes persistence near-unbeatable; retraining reproduces those numbers
        rather than better ones. The covariates are not the problem, the target's own persistence
        is.
      </p>
      <p>
        Each such variable still gets a metric page at <code>/dashboard/&lt;variable&gt;</code>{' '}
        that renders its history and correctly omits the forecast section, with the command to
        train it. A page that implied a working forecast where none passed the bar would be worse
        than no page at all.
      </p>
      <p>
        Next: <Link to="/docs?c=forecast-map">the same engine rendered as a global map</Link>.
      </p>
    </>
  );
}
