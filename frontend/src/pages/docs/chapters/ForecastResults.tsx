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
        <code>metrics.json</code>. Thirty-one variables are trained and 116 models shipped —
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

      <h2 id="distribution">Skill by horizon, across all 116 models</h2>
      <Table
        headers={['Horizon', 'Models', 'Median skill', 'Weakest', 'Strongest']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['+1 day', '30', '+0.252', '+0.069', '+0.532'],
          ['+3 days', '28', '+0.172', '+0.026', '+0.421'],
          ['+7 days', '29', '+0.232', '+0.068', '+0.428'],
          ['+30 days', '29', <Best>+0.380</Best>, '+0.120', '+0.494'],
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
          ['Biogeochemistry', '24', '+0.068 (nitrate, +7d)', '+0.449 (dissolved oxygen, +30d)'],
          ['Waves', '20', '+0.098 (wave direction, +1d)', '+0.430 (mean wave period, +30d)'],
          ['Wind', '16', '+0.217 (wind gust, +1d)', '+0.450 (wind v, +30d)'],
          ['Meteorology', '15', '+0.167 (humidity, +3d)', <Best>+0.494 (air temperature, +30d)</Best>],
          ['Ocean currents', '12', '+0.065 (current u, +3d)', '+0.411 (current v, +30d)'],
          ['Ocean colour', '12', '+0.026 (diffuse attenuation, +3d)', <Best>+0.532 (chlorophyll-a, +1d)</Best>],
          ['Temperature', '8', '+0.065 (sea surface temperature, +3d)', '+0.434 (sea surface temperature, +30d)'],
          ['Sea level', '7', '+0.091 (sea surface height, +7d)', '+0.388 (sea level anomaly, +3d)'],
          ['Salinity', '2', '+0.069 (+1d)', '+0.120 (+30d)'],
        ]}
      />
      <p>
        <strong>Chlorophyll-a at +1 day (+0.532) is the strongest result in the repository</strong>{' '}
        — a 53% error reduction against persistence — and it is strong for the mirror-image
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
        the training log prints the aggregate, and <strong>four</strong> of the rejected horizons
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
            <>−0.131 with 4/5 folds negative; −0.050 with 4/5</>,
          ],
          [
            <><code>bottom_temperature</code> +3d, +7d, +30d</>,
            'marginal',
            <>−0.061, −0.073 (2/5 folds negative each); −0.060 (3/5)</>,
          ],
          [
            <><code>water_temperature</code> +3d</>,
            <>+0.018 — barely <em>beats persistence</em></>,
            <>2/5 folds negative; a positive aggregate with one fold in five wrong is exactly what the bar exists to catch</>,
          ],
          [
            <><code>humidity</code> +1d</>,
            'marginal',
            <>−0.020 with 2/5 negative, one at −0.435</>,
          ],
          [
            <><code>sea_level_anomaly</code> +30d</>,
            <>+0.077 — <em>beats persistence</em></>,
            <>2/5 folds negative, spanning −0.112 to +0.242</>,
          ],
        ]}
        caption="One variable dropped outright and eight further horizons trained, measured and deleted. Two rows that once stood here — nitrate +3d and sea_level_anomaly +7d — have since been retrained clean and now ship; this table only ever reflects what is rejected today."
      />
      <Callout kind="lesson" title="An average is not a result">
        <p>
          <code>sea_level_anomaly</code> at +30 days is the current example in the project. It
          posted +0.077 overall and the training log said <code>beats persistence</code>. Two of
          its five folds were negative — +0.009, +0.242, −0.085, +0.233 and −0.112 — a model
          that helps in most conditions and gives measurable ground back in two out of five,
          averaged into something that looks like modest, dependable competence.
        </p>
        <p>
          Shipping it would have put a forecast on the map with no way to tell a reader which
          kind of month they were looking at. The fold spread is logged beside the mean in
          experiment tracking for this exact reason, and the shipping rule — skill positive{' '}
          <em>and</em> at most one fold in five negative — is itself recorded as a metric rather
          than applied by eye. This is also the row most likely to flip: its neighbour at +7 days
          failed by the same margin in an earlier pass and has since been retrained clean.
        </p>
      </Callout>

      <h3>Where the decision differed, and why</h3>
      <p>
        <code>sea_surface_salinity</code> was dropped entirely while <code>water_salinity</code>{' '}
        kept its +1d and +30d models — same physics, same covariates, the same target measured
        at the surface versus at depth, and two different outcomes. Neither surviving{' '}
        <code>water_salinity</code> horizon is spotless (each still carries one negative fold in
        five), but both clear the bar the same way every other shipped horizon does, while every
        attempt at <code>sea_surface_salinity</code> — including its two best, at +0.085 and
        +0.106 — did not. The physics is the same; the evidence is not, and the decision follows
        the evidence rather than the family.
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
        One variable of the 34 configured. <code>sea_surface_salinity</code> is configured, its provider
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
