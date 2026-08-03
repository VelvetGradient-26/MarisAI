/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Callout, Table } from '../primitives';

export function Limits() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Limitations &amp; what comes next</h1>
      <p className="docs-article__lede">
        What these models cannot do, what was deliberately left unbuilt and why, and what the
        next real improvement would be. A model's limitations are part of its documentation, not
        an appendix to it.
      </p>

      <h2 id="labels">The label limitations</h2>

      <h3>HAB labels are weak, and "bloom" does not mean "harmful"</h3>
      <p>
        Everything Problem A trains on is a proxy: modelled chlorophyll above a high local
        percentile. It is not a verified bloom, and it says nothing about toxicity. The label
        rate (~9.7% in training) is a property of the labelling rule, not of the ocean — a
        90th-percentile threshold yields ~10% positives by construction. Verified in-situ blooms
        would be far rarer, and the entire class-imbalance strategy would need revisiting with
        them.
      </p>
      <p>
        Strong labels would enter through the same interface with{' '}
        <code>label_strength='strong'</code>. The data — in-situ cell counts and toxin assays from
        HABSOS, NCCOS or HAEDAT, or INCOIS Algal Bloom Information Service advisories — is not
        openly queryable for this coastline.
      </p>

      <h3>Habitat labels are presence-only, and the background still skews</h3>
      <p>
        Target-group background sampling corrects horizontal sampling bias well, but the pool
        still skews shallower and more coastal than the pelagic tunas that make up most
        presences. That is visible directly in the SHAP ranking, where <code>depth</code> and{' '}
        <code>distance_to_coast</code> dominate. Some of that signal is residual sampling
        geometry, not habitat preference.
      </p>
      <p>
        <strong>The concrete next step:</strong> constrain background draws to match the presence
        depth distribution, and see how much of the depth signal survives.
      </p>

      <h2 id="deployability">Deployability, honestly</h2>
      <Table
        headers={['Product', 'Status', 'Reason']}
        rows={[
          [
            'HAB t+3 alert',
            'Plausibly deployable',
            'Roughly half of alerts at 80% recall are genuine. Would survive contact with a coastal agency.',
          ],
          ['HAB t+5 alert', 'Marginal', '72% of alerts are false.'],
          [
            'HAB t+7 alert',
            'Not deployable as an alert',
            'Four in five alerts are false. Useful as a continuous risk surface; not as a binary warning.',
          ],
          [
            'Habitat suitability maps',
            'Useful with caveats',
            'Strong held-out skill, but 9% of a held-out block is environmentally extrapolating, and the depth signal is partly sampling geometry.',
          ],
        ]}
      />

      <h2 id="not-built">Deliberately not built</h2>

      <h3>Tier 3 — deep spatio-temporal models</h3>
      <p>
        No ConvLSTM, no 3D-CNN, no vision-transformer patch encoder, no TFT/LSTM sequence models.
        The reasoning is order of operations: ship Tier 1–2 first and reserve GPU-backed Tier 3
        for a pilot phase once the pipeline and validation framework are proven. A deep model
        trained on a leaking pipeline is a very expensive way to learn that your pipeline leaks.
        The feature store and validation harness those models would consume are already in place.
      </p>

      <h3>HAB Stage 2 — toxicity classification</h3>
      <p>
        Left unimplemented rather than faked on data that does not exist. See above.
      </p>

      <h3>Hyperparameter tuning</h3>
      <p>
        Model settings are hand-chosen and conservative. There is no Optuna sweep. The correct
        version is <em>nested</em> rolling-origin tuning — an inner loop inside each outer fold —
        and anything less is just another way to leak the test period into model selection. It is
        the documented next step, not an oversight.
      </p>

      <h3>Global Fishing Watch as a label</h3>
      <p>
        Registered in the source inventory, deliberately not ingested. Vessel activity must stay a
        covariate and an external validation signal, never a target. "Fish are where boats are,
        and boats are where fish are" is a circular model that would score beautifully and mean
        nothing. It is the main circularity risk in Problem B and it is worth naming explicitly.
      </p>

      <h3>ERA5 winds</h3>
      <p>
        Superseded rather than pending. The need was wind stress for the Bakun index, and
        Copernicus Marine serves scatterometer-derived stress directly — reachable with
        credentials we already have and with no drag-coefficient assumption. ERA5 via the CDS API
        would have added a second account for a strictly worse version of the same covariate. It
        remains the right source for variables Copernicus does not carry (precipitation, air–sea
        heat flux).
      </p>

      <h3>Other registered but un-ingested sources</h3>
      <p>NASA Ocean Color, CMFRI landings data, GRDC river discharge. All would be additive; none is load-bearing for the current results.</p>

      <h2 id="risks">Standing risks</h2>

      <Callout kind="warn" title="Regime shift is the dominant risk, not a footnote">
        <p>
          Six years of HAB data contains five monsoon seasons. ENSO and the Indian Ocean Dipole
          operate on longer cycles than that. A sufficiently unusual year is outside anything
          either model has seen, and the failure mode is not a graceful degradation — the
          two-year model scored ROC-AUC 0.53 on a season it had never encountered.
        </p>
        <p>
          The mitigation is not a better model, it is a longer record plus{' '}
          <Link to="/docs?c=metrics">MESS</Link> at prediction time to flag when a prediction is
          extrapolation rather than interpolation.
        </p>
      </Callout>

      <ul>
        <li>
          <strong>Reanalysis products get reprocessed.</strong> The dataset ID alone is not enough
          to reproduce a training run, which is why region, window, cadence and dataset ID are
          written into every cached NetCDF's attributes.
        </li>
        <li>
          <strong>Model chlorophyll is not satellite chlorophyll.</strong> Using modelled
          biogeochemistry buys gap-free daily coverage (satellite ocean colour is cloud-limited,
          and the monsoon is exactly when it is cloudiest) at the cost of fidelity. Satellite
          ocean colour remains the higher-fidelity source when it is available.
        </li>
        <li>
          <strong>Wind stress has a fixed 39% spatial mask.</strong> Those rows keep their 10 m
          wind features and LightGBM handles the gap natively, but upwelling features are simply
          absent over part of the domain.
        </li>
        <li>
          <strong>Habitat records stop in 2014.</strong> The model describes 2000–2013 conditions.
          Applying it to today's ocean is a projection, and the MESS number is how you tell how
          far a projection it is.
        </li>
      </ul>

      <h2 id="next">The ordered improvement list</h2>
      <ol>
        <li>
          <strong>More years for the HAB model.</strong> Measured to matter more than more
          features — no covariate helps a model that has never seen the regime it is being asked
          about.
        </li>
        <li>
          <strong>Depth-matched background sampling</strong> for the habitat model, to separate
          the depth signal from residual sampling geometry.
        </li>
        <li>
          <strong>Nested rolling-origin hyperparameter tuning.</strong>
        </li>
        <li>
          <strong>Strong HAB labels</strong> from any in-situ source that becomes available, and
          Stage 2 toxicity classification on top of them.
        </li>
        <li>
          <strong>Tier 3 spatio-temporal models</strong>, once the above is done and there is a
          proven pipeline for them to sit on.
        </li>
      </ol>

      <h2 id="elsewhere">Where to go next in the app</h2>
      <ul>
        <li>
          <Link to="/predictions">Model Insights</Link> — the live version of these results, read
          from the exported manifest, with the prediction rasters themselves.
        </li>
        <li>
          <Link to="/map">The map</Link> — model outputs as layers over live ocean data.
        </li>
        <li>
          <Link to="/download">The downloader</Link> — 34 ocean variables across 14 providers, if
          you want to build something of your own on the same data.
        </li>
      </ul>
    </>
  );
}
