/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. Keying them again at
 * the call site would put noise on every row of every table in this chapter for
 * no runtime benefit. */
import { Callout, Formula, Table, Term } from '../primitives';

export function Metrics() {
  return (
    <>
      <p className="docs-article__eyebrow">Machine learning</p>
      <h1>Metrics, explained</h1>
      <p className="docs-article__lede">
        Accuracy is never reported in this project, and F1 barely. Each problem uses the metrics
        its own field trusts, for reasons this chapter works through from first principles. If
        you have only ever used accuracy and ROC-AUC, this is the chapter to read slowly.
      </p>

      <h2 id="confusion">Start here: the four outcomes</h2>
      <p>
        Every binary prediction, once you pick a threshold, lands in one of four boxes. All the
        metrics below are built out of counts of these.
      </p>
      <Table
        headers={['', 'Actually a bloom', 'Actually not']}
        rows={[
          ['Predicted bloom', 'True positive (TP)', 'False positive (FP) — a false alarm'],
          ['Predicted no bloom', 'False negative (FN) — a miss', 'True negative (TN)'],
        ]}
      />
      <Formula
        expr={
          'precision   = TP / (TP + FP)     "when I raise an alarm, how often am I right?"\n' +
          'recall      = TP / (TP + FN)     "of all the real blooms, how many did I catch?"\n' +
          'specificity = TN / (TN + FP)     "of all the calm days, how many did I leave alone?"\n' +
          'accuracy    = (TP + TN) / total  "how often am I right about anything?"'
        }
      />

      <Callout kind="warn" title="Why accuracy is banned here">
        <p>
          Blooms are ~7.4% of held-out grid-cell-days. A model that predicts "no bloom" every
          single time is <strong>92.6% accurate</strong> and completely worthless. Any metric that
          a constant predictor can score well on is not measuring skill on an imbalanced problem.
        </p>
      </Callout>

      <h2 id="roc-vs-pr">ROC-AUC versus PR-AUC</h2>
      <p>
        Both summarise performance across <em>all</em> thresholds, so neither requires you to pick
        one. They differ in what they are sensitive to, and on imbalanced data that difference is
        enormous.
      </p>
      <p>
        <Term>ROC-AUC</Term> plots recall against the false-positive rate (FP / all negatives).
        The catch: on our data "all negatives" is over half a million rows. A model can produce
        tens of thousands of false alarms and barely move the false-positive rate, because the
        denominator is gigantic. So ROC-AUC stays flatteringly high while the model is useless at
        any threshold an agency would actually alert on.
      </p>
      <p>
        <Term>PR-AUC</Term> (average precision) plots precision against recall. Precision's
        denominator is "everything I flagged", which is small — so every false alarm hurts.
        That is the correct sensitivity for a rare-event alerting product.
      </p>
      <Table
        headers={['Horizon', 'ROC-AUC', 'PR-AUC', 'What the gap tells you']}
        numeric={[1, 2]}
        rows={[
          ['t+3', '0.942', '0.661', 'Genuinely useful ranking.'],
          ['t+5', '0.884', '0.493', 'Degrading.'],
          ['t+7', '0.841', '0.362', 'ROC-AUC still looks strong; PR-AUC says most alerts will be false.'],
        ]}
        caption="Same model, same data, same predictions. If you only reported the first column you would conclude the seven-day forecast is nearly as good as the three-day one. It is not."
      />
      <Callout kind="note" title="What counts as a good PR-AUC">
        <p>
          A random model's PR-AUC equals the positive class rate. Here that is ~0.074. So a t+7
          PR-AUC of 0.362 is roughly <strong>5× better than chance</strong> — while an ROC-AUC of
          0.5 would be chance regardless of imbalance. Always compare PR-AUC to the base rate, not
          to 0.5.
        </p>
      </Callout>

      <h2 id="tss">TSS — the True Skill Statistic</h2>
      <p>
        Standard in ecology, and used for both problems here. It is threshold-based rather than
        threshold-free:
      </p>
      <Formula
        expr={'TSS = sensitivity + specificity − 1\n    = recall + (TN / (TN + FP)) − 1'}
        where="Ranges −1 to +1. Zero is exactly chance, regardless of class balance — which is what makes it a fair floor for ensemble weighting. +1 is perfect."
      />
      <p>
        The threshold is not left at 0.5 — that number is meaningless when the class balance is
        an artefact of how many background points you happened to draw. Instead we scan 201
        candidate thresholds and report the TSS at the best one.
      </p>

      <h2 id="boyce">The continuous Boyce index</h2>
      <p>
        This one is specific to presence-only data, and it is the honest choice for Problem B
        because it <strong>needs no true absences</strong> — which is exactly the situation OBIS
        leaves us in.
      </p>
      <Callout kind="jargon" title="How it works">
        <p>
          Slide a window across the range of predicted suitability scores. In each window,
          compute the ratio of (fraction of presences falling in it) to (fraction of background
          points falling in it) — the <Term>predicted-to-expected ratio</Term>. Then take the
          Spearman rank correlation between that ratio and the suitability score.
        </p>
        <p>
          A well-behaved habitat model puts monotonically more presences than background in
          successively higher suitability bins, so the correlation approaches <strong>+1</strong>.
          Near 0 means predictions are no better than the background distribution. Negative means
          the model is inverted.
        </p>
      </Callout>
      <p>
        Windows containing no background points have an undefined expectation and are skipped;
        inventing a ratio there would manufacture skill.
      </p>
      <p>
        Notice that Random Forest wins on Boyce (0.955 in CV) while LightGBM wins on TSS (0.826).
        They are asking different questions — TSS asks "can you draw a good boundary", Boyce asks
        "is your continuous surface well-ordered" — and reporting only one would hide a real
        difference between the two models.
      </p>

      <h2 id="brier">Brier score and reliability</h2>
      <p>
        Everything above measures <em>ranking</em>. None of it cares whether your predicted 0.7
        actually corresponds to a 70% chance. But the product surfaces a probability to a coastal
        agency, so that number has to mean something.
      </p>
      <Formula
        expr={'Brier = mean( (predicted_probability − actual_outcome)² )'}
        where="Just mean squared error on probabilities. Lower is better; 0 is perfect. It is sensitive both to ranking and to calibration, which is why it improves when you calibrate even though AUC does not move."
      />
      <p>
        A <Term>reliability curve</Term> is the diagnostic behind it: bin predictions into deciles
        and plot the mean predicted probability against the observed frequency in each bin. A
        perfectly calibrated model lies on the diagonal.
      </p>
      <p>
        Our raw model's 0.9–1.0 bin fires on 57% of occasions — badly overconfident, a direct
        consequence of <code>class_weight="balanced"</code> shifting the decision boundary.
        Isotonic regression fitted on the validation slice pulls it back onto the diagonal, and
        the Brier score improves 25–33% at every horizon while ROC-AUC is unchanged to three
        decimals. That is precisely how a monotonic transform must behave, and the fact that it
        does is a check that nothing else changed.
      </p>

      <h2 id="operating-point">The operating point: precision, recall and false-alarm rate</h2>
      <p>
        Threshold-free metrics summarise a model. A deployed system runs at one threshold, and
        the honest way to report it is to fix the number the user cares about and report the
        consequences.
      </p>
      <p>
        For an early-warning system, the fixed quantity is <strong>recall</strong> — missing a
        bloom costs far more than a false alarm, so an agency specifies "catch at least 80% of
        them". We then find the lowest-alarm threshold achieving that and report:
      </p>
      <Formula
        expr={'false_alarm_rate = FP / (TP + FP) = 1 − precision'}
        where="The fraction of raised alarms that were not events. This is what erodes operator trust, and once trust is gone the true alerts get ignored too."
      />
      <p>
        This is why the docs say the seven-day forecast is not deployable despite an ROC-AUC of
        0.841: at 80% recall its false-alarm rate is 0.798.
      </p>

      <h2 id="mess">MESS — is this prediction extrapolation?</h2>
      <p>
        <Term>MESS</Term> (Multivariate Environmental Similarity Surface, Elith et al. 2010)
        answers a different kind of question: not "how good is the model" but "should this
        specific prediction be trusted at all".
      </p>
      <p>
        For each row being predicted, and each variable, it computes how far inside the training
        range that value sits, as a percentage. <strong>Negative means extrapolation</strong> —
        the value is outside anything the model ever saw. The most dissimilar variable governs:
        one variable out of range is enough to make the whole prediction an extension of a fitted
        curve into unobserved conditions.
      </p>
      <p>
        On our held-out spatial block, <strong>9.0% of points are extrapolating</strong> (median
        MESS 0.44). This matters directly for climate-driven range shift: a habitat model trained
        on 2000–2013 sea temperatures and asked about a marine heatwave is extrapolating, and the
        product should say so rather than quietly returning a confident number.
      </p>

      <h2 id="nan">A small thing that matters: single-class folds</h2>
      <p>
        A cross-validation fold containing only one class has no defined ranking metric. The
        codebase returns <code>NaN</code> rather than 0 or 1, and fold averaging skips it.
        Substituting a number there — in either direction — is quietly making up a result.
      </p>

      <h2 id="summary">Summary: which metric for which question</h2>
      <Table
        headers={['Question', 'Metric', 'Used in']}
        rows={[
          ['Can the model rank rare events well?', 'PR-AUC', 'Problem A (primary)'],
          ['Can it separate classes at all?', 'ROC-AUC', 'Both (secondary — never quoted alone on imbalanced data)'],
          ['Can it draw a good decision boundary?', 'TSS', 'Both, and the ensemble weighting'],
          ['Is the continuous surface well-ordered, with no true absences?', 'Boyce index', 'Problem B'],
          ['Does the probability mean what it says?', 'Brier + reliability curve', 'Problem A'],
          ['What happens at the threshold we would deploy?', 'Precision / recall / false-alarm rate', 'Problem A'],
          ['Should this individual prediction be trusted?', 'MESS', 'Both'],
          ['Have we beaten doing nothing clever?', 'Persistence baseline', 'Problem A, every fold'],
        ]}
      />
    </>
  );
}
