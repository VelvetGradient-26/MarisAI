/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Link } from '../../../app/router';
import { Best, Callout, Code, Formula, Poor, Table, Term } from '../primitives';

export function Habitat() {
  return (
    <>
      <p className="docs-article__eyebrow">Problem B</p>
      <h1>Fish habitat / PFZ: labels, models, results</h1>
      <p className="docs-article__lede">
        Mapping habitat suitability for five species from presence-only occurrence records. The
        hard part is not the classifier — it is manufacturing a negative class that does not
        teach the model to find marine biologists. This chapter covers that, the three model
        tiers, spatial block validation, and the measured results.
      </p>

      <h2 id="presence-only">The presence-only problem</h2>
      <p>
        OBIS records say "this species was seen here, on this date". There is no record anywhere
        in it that says "we looked here and found nothing". So there is no negative class, and
        one has to be manufactured.
      </p>
      <p>
        The naive approach — scatter random points across the ocean and call them absences — is
        catastrophic here, and it is catastrophic in a way that looks like success. Presences
        cluster near research institutes, ports, ferry routes and shipping lanes, because that is
        where sampling effort is. Random points do not. So the model learns to separate{' '}
        <strong>sampled water from unsampled water</strong>, scores brilliantly, and produces a
        beautiful map of where marine biologists work.
      </p>

      <h3>The fix: target-group background sampling</h3>
      <Callout kind="jargon" title="Jargon buster — pseudo-absence and target-group background">
        <p>
          A <Term>pseudo-absence</Term> (or background point) is a manufactured negative: a
          location and time treated as "not a presence" for training purposes. It is not a claim
          the species was absent.
        </p>
        <p>
          <Term>Target-group background sampling</Term> draws those points from occurrence records
          of the wider taxonomic group — here, all other ray-finned fishes recorded in the same
          region and period. Those records come from the same surveys, in the same places, with
          the same effort bias as the presences. So the sampling bias largely cancels, and what
          remains is the environmental signal.
        </p>
      </Callout>
      <p>Three rules make it work:</p>
      <ol>
        <li>
          <strong>Exclude the focal species from its own background pool.</strong> Those are
          presences, not background.
        </li>
        <li>
          <strong>Exclude the exact (cell, month) slots the presences occupy</strong>, so a
          background point never contradicts a presence at the same place and time.
        </li>
        <li>
          <strong>Thin the background the same way as the presences</strong> — one point per
          (cell, month) slot — so both classes are sampled at the same spatial granularity.
        </li>
      </ol>

      <h3>Spatial thinning of presences</h3>
      <p>
        Before any of that, presences are thinned to at most one per grid cell per month per
        species.
      </p>
      <p>
        Ten trawl records from one survey in one bay on one afternoon are ten copies of a single
        environmental observation. Left in, they weight that cell's conditions ten times over, and
        the model reads the survey's itinerary as the species' preference. The survivor of each
        group is chosen at random rather than first-seen, so no ordering artefact creeps in.
      </p>

      <h3>What the labelled table looks like</h3>
      <Table
        headers={['Quantity', 'Value']}
        numeric={[1]}
        rows={[
          ['Rows after thinning, background and quality filtering', '2,787'],
          ['Presences', '877 (31.5%)'],
          ['Background points', '1,910'],
          ['Target background ratio', '3 background per presence'],
          ['Features', '40'],
        ]}
        caption="The realised ratio is below the requested 3:1 for some species because the target-group pool simply runs out of unoccupied (cell, month) slots — which is honest, and the class weighting in training compensates."
      />

      <h2 id="models">Three model tiers</h2>
      <p>
        Rather than one model, three, spanning a deliberate range of flexibility — plus a
        skill-weighted ensemble. This mirrors standard practice in species distribution modelling
        (the biomod2 convention in ecology), where no single method dominates across species and
        regions.
      </p>

      <h3>Tier 1 — MaxEnt</h3>
      <Callout kind="jargon" title="Jargon buster — MaxEnt">
        <p>
          <Term>MaxEnt</Term> (maximum entropy) is the most widely used species distribution model
          in ecology, and a fisheries scientist reviewing this work will look for it. It fits the
          distribution that is maximally uniform subject to matching the observed feature means.
        </p>
      </Callout>
      <p>
        We implement it as <strong>L1-regularised logistic regression with quadratic and hinge
        feature expansion</strong>. This is not an approximation of convenience: Phillips &amp;
        Dudík (2008) showed MaxEnt's Gibbs distribution is exactly the solution of regularised
        logistic regression on presence-background data, and Renner &amp; Warton (2013) tied both
        to an inhomogeneous Poisson point process. It is MaxEnt's estimator, expressed in
        scikit-learn.
      </p>
      <p>The feature expansion is what gives a linear model ecological shape:</p>
      <Formula
        expr={'expanded = [ X,  X²,  max(0, X − k₁),  max(0, X − k₂),  max(0, X − k₃) ]'}
        where="Quadratic terms let a response peak at an intermediate optimum — which is what an ecological niche looks like. Hinge terms let the response change slope at a threshold (knots at the 20th, 50th and 80th percentiles). Without these, a linear model can only say 'warmer is always better', which is never true of a thermal niche."
      />

      <h3>Tier 2 — Random Forest and LightGBM</h3>
      <Table
        headers={['Model', 'Settings', 'Reasoning']}
        rows={[
          [
            'Random Forest',
            '500 trees, min_samples_leaf 3, max_features sqrt, class_weight balanced_subsample',
            'Many deep, decorrelated trees averaged. Robust with little tuning, and a useful contrast to boosting.',
          ],
          [
            'LightGBM',
            '400 rounds, lr 0.05, num_leaves 15, max_depth 5, min_child_samples 20, subsample/colsample 0.8, reg_lambda 1.0',
            'Deliberately more constrained than the HAB model. With order-1,000 presences, an unconstrained booster memorises the training set within a few dozen rounds and the spatial CV score collapses.',
          ],
        ]}
      />

      <h3>The ensemble</h3>
      <p>
        A weighted average of the three, with weights proportional to each model's
        cross-validated TSS. TSS is 0 at chance, so it is its own floor — a model no better than
        chance gets zero weight rather than dragging the ensemble.
      </p>
      <Table
        headers={['Model', 'CV TSS', 'Ensemble weight']}
        numeric={[1, 2]}
        rows={[
          ['LightGBM', '0.826', '0.364'],
          ['Random Forest', '0.821', '0.362'],
          ['MaxEnt', '0.619', '0.273'],
        ]}
      />

      <h2 id="validation">Validation: spatial block cross-validation</h2>
      <p>
        This is the single most consequential choice in the whole problem. Occurrence records are
        strongly spatially autocorrelated. A random split puts points from the same survey
        transect in both training and test, and the model scores near-perfectly by recognising its
        neighbours.
      </p>
      <p>
        Instead, points are binned into <strong>3° squares</strong> (~330 km) and whole blocks —
        not individual points — are assigned to folds. Held-out points are therefore spatially
        distant from every training point.
      </p>
      <Code>{`lat_block = floor(latitude  / 3.0)
lon_block = floor(longitude / 3.0)
block_id  = f"{lat_block}_{lon_block}"

# whole blocks are shuffled and dealt round-robin into 5 folds
fold_of_block = {block: i % 5 for i, block in enumerate(shuffled_blocks)}`}</Code>
      <p>
        3° comfortably exceeds the mesoscale eddy scale here, which is the rule: the block size
        must exceed the autocorrelation range of the drivers, or blocks are not independent.
      </p>
      <p>
        A block containing only background points (or only presences) cannot produce a meaningful
        score, so it is skipped. Skipping is honest; scoring it is not.
      </p>
      <p>
        The thermal niche is <strong>refitted inside every fold</strong>, on that fold's training
        presences only. Fitting it once outside the loop would leak held-out temperatures into a
        training feature and quietly inflate every fold.
      </p>

      <h2 id="results">Results</h2>
      <h3>Spatial block cross-validation — mean over 5 folds</h3>
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
      <p>
        One spatial fold generated from a different random seed, never used for model selection.
      </p>
      <Table
        headers={['Model', 'ROC-AUC', 'PR-AUC', 'TSS', 'Boyce']}
        numeric={[1, 2, 3, 4]}
        rows={[
          ['LightGBM', <Best>0.946</Best>, <Best>0.816</Best>, <Best>0.788</Best>, '0.895'],
          ['Random Forest', '0.927', '0.741', '0.774', '0.927'],
          ['Ensemble', '0.917', '0.752', '0.694', <Best>0.936</Best>],
          ['MaxEnt', <Poor>0.722</Poor>, <Poor>0.365</Poor>, <Poor>0.365</Poor>, '0.884'],
        ]}
        caption="9% of held-out points are environmentally extrapolating (MESS < 0) — i.e. at least one variable falls outside the range the model was fitted on. Median MESS is 0.44."
      />

      <Callout kind="note" title="The CV-to-holdout gap is information, not a defect">
        <p>
          LightGBM drops from 0.826 to 0.788 TSS; MaxEnt collapses from 0.619 to 0.365. That gap
          is the difference between interpolating among neighbouring records and generalising to
          water the model has never seen. A random K-fold split would have hidden it entirely and
          reported the higher number for everything.
        </p>
        <p>
          It is also informative that the tree models hold up and the linear one does not — with
          only ~880 presences, the linear tier's regularisation path is the least stable thing in
          the set.
        </p>
      </Callout>

      <h2 id="drivers">What the model actually uses</h2>
      <Table
        headers={['Rank', 'Feature', 'Mean |SHAP|', 'Interpretation']}
        numeric={[0, 2]}
        rows={[
          ['1', <code>depth</code>, '1.085', 'Seafloor depth — the strongest single driver by a wide margin.'],
          ['2', <code>distance_to_coast</code>, '0.847', 'Coastal versus pelagic.'],
          ['3', <code>species_key = yellowfin_tuna</code>, '0.510', 'Species identity genuinely changes the surface.'],
          ['4', <code>zos</code>, '0.372', 'Sea surface height — the eddy signature.'],
          ['5', <code>doy_cos</code>, '0.369', 'Season.'],
          ['6', <code>log_depth</code>, '0.322', 'The non-linear form of depth.'],
          ['7', <code>species_key = oil_sardine</code>, '0.315', ''],
          ['9', <code>thermal_distance</code>, '0.280', "Departure from the species' thermal optimum."],
          ['11', <code>thermal_position</code>, '0.250', 'Position within its thermal range.'],
          ['13', <code>okubo_weiss</code>, '0.219', 'Eddy interior versus filament.'],
          ['15', <code>chl_trend_30d</code>, '0.199', 'Whether the prey base is building or collapsing.'],
        ]}
      />

      <Callout kind="warn" title="One honest caveat about that ranking">
        <p>
          <code>depth</code> and <code>distance_to_coast</code> dominate. Target-group background
          sampling corrects <em>horizontal</em> sampling bias well, but the background pool still
          skews shallower and more coastal than the pelagic tunas that make up most presences. So
          some of that signal is residual sampling geometry rather than pure habitat preference.
        </p>
        <p>
          Constraining background draws to match the presence depth distribution is the natural
          next step. It is worth stating plainly rather than presenting depth as an ecological
          discovery.
        </p>
      </Callout>

      <h2 id="lessons">Design decisions worth carrying elsewhere</h2>
      <ul>
        <li>
          <strong>How you build the negative class matters more than which classifier you pick.</strong>{' '}
          Target-group background versus random background is the difference between a habitat
          model and a survey-effort model, and no amount of tuning fixes the wrong choice.
        </li>
        <li>
          <strong>Coordinates are not features.</strong> Excluding latitude and longitude costs
          some apparent skill and buys all of the model's credibility.
        </li>
        <li>
          <strong>Keep the trusted baseline even when it loses.</strong> MaxEnt scores worst here,
          and it stays — because it is the method ecologists reviewing the work already trust, and
          "the boosted model beats MaxEnt on held-out blocks" is a far more persuasive claim than
          a bare 0.79 TSS.
        </li>
        <li>
          <strong>Check that outputs actually differ.</strong> The single worst bug in this
          project was caught by noticing that per-species map tiles were byte-identical, not by
          any metric. See the <Link to="/docs?c=features">features chapter</Link>.
        </li>
      </ul>

      <Formula
        expr={'PYTHONPATH=. .venv/bin/python -m fish_habitat_prediction.src.pipeline'}
        where="~1 minute end to end, including five folds × three models plus the final held-out block and SHAP."
      />
    </>
  );
}
