/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

/**
 * The assistant, and specifically what "grounded" does and does not promise.
 *
 * A chat interface over scientific data invites exactly one dangerous
 * assumption — that the model knows the ocean. It does not; it knows how to
 * call the same endpoints the map calls. The chapter is organised around making
 * that legible, including the case where the check itself is wrong.
 */
export function Assistant() {
  return (
    <>
      <p className="docs-article__eyebrow">Using the platform</p>
      <h1>The assistant, and what "grounded" means</h1>
      <p className="docs-article__lede">
        The assistant answers questions by <em>calling the platform's own endpoints</em> — the
        same ones behind the map and the dashboard — and then writing up what came back. It
        has no ocean knowledge of its own, and the interface is built to keep that visible
        rather than to hide it.
      </p>

      <h2 id="loop">It is a tool loop, not a search over documents</h2>
      <p>
        Ask "how warm is it off Kochi, and is that unusual?" and the model does not look the
        answer up in a corpus. It decides which tools to call, the server calls them, the
        results come back, and it may call more before answering. The loop is bounded, and
        every observation it received is available to you underneath the answer.
      </p>
      <Callout kind="jargon" title="Why this is not RAG">
        <Term>Retrieval-augmented generation</Term> searches a body of pre-written text and
        gives the model passages to paraphrase. That would make the assistant only as current
        as the last time someone wrote something down. Calling the live services instead means
        the answer is made of today's ocean — and it means the assistant can only answer
        things the platform can actually measure, which is the correct limit for it to have.
      </Callout>

      <h2 id="grounding">The grounding check</h2>
      <p>
        After the answer is written, every figure in it is checked against everything the
        tools returned. If a number in the prose cannot be traced to a tool result, the
        interface says so. This catches the specific failure that matters most here: a fluent,
        correctly-formatted, entirely invented measurement.
      </p>
      <Table
        headers={['What the badge says', 'What it means']}
        rows={[
          [
            <strong>Unverified</strong>,
            'The answer is still streaming. Nothing has been checked yet — the check needs the finished text.',
          ],
          [
            <strong>Traced</strong>,
            'Every figure in the answer appears in something a tool returned.',
          ],
          [
            <strong>Contains untraceable figures</strong>,
            'At least one number could not be matched. Often that is a unit conversion the model did itself; sometimes it is not. Either way it is worth checking.',
          ],
        ]}
      />
      <Callout kind="warn" title="Text arrives before the verdict does, necessarily">
        The check runs on the whole answer, so it can only exist once the last token has been
        written. Streaming text is therefore shown as unverified and resolves when the answer
        finishes — a "traced" badge displayed any earlier would be asserting the result of a
        check that has not run.
      </Callout>

      <h2 id="crywolf">A checker that cries wolf is worse than none</h2>
      <Callout kind="lesson" title="The thousands-separator bug">
        The number-matching pattern originally split "2,048 m" into "2" and "048", neither of
        which appeared in any tool result — so every correct answer involving a depth over a
        thousand metres was flagged as carrying two untraceable figures. A warning that fires
        on correct answers trains people to ignore the one that matters, which is strictly
        worse than not warning at all. The pattern now handles grouped digits.
      </Callout>
      <p>
        The complementary case is deliberately <em>kept</em>: if the model converts a value
        itself — "roughly 6,700 ft" from a depth reported in metres — that figure is flagged,
        because no tool reported it. That is the checker working, not misfiring. It reports
        traceability, not truth.
      </p>

      <h2 id="reading">Reading an answer properly</h2>
      <Table
        headers={['If you want to know…', 'Look at']}
        rows={[
          ['Where a number came from', 'The tool observations, expandable under the answer'],
          ['Which services were consulted', 'The sources list at the end of the turn'],
          ['Whether anything was invented', 'The grounding badge, once the answer has finished'],
          ['Whether a value is a forecast', 'The answer says so — model output is labelled as model output'],
        ]}
      />
      <p>
        Conversations are kept so you can reopen them. That history is scoped by an identifier
        generated in your browser, which keeps your conversations to your machine — it is not
        a login and it is not access control, and it is documented that way rather than
        implied to be more.
      </p>
      <Callout kind="note" title="Three states, not two">
        The session sidebar distinguishes "loading", "failed to load" and "you have none" —
        the same rule as the dashboard's unavailability reasons. "We do not know yet" and "we
        could not fetch this" are different answers from "there is nothing here", and
        collapsing them is how an interface starts lying quietly.
      </Callout>
    </>
  );
}
