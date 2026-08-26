/* oxlint-disable react/jsx-key -- Cells passed to <Table rows={...}> are keyed
 * by Table itself, which wraps every cell in a keyed <td>. */
import { Callout, Table, Term } from '../primitives';

/**
 * The assistant, and specifically what "grounded" does and does not promise.
 *
 * A chat interface over scientific data invites exactly one dangerous
 * assumption — that the model knows the ocean. It does not; it knows how to
 * call the same endpoints the map calls. The chapter is organised around making
 * that legible: who actually answers a question (three specialists behind one
 * conversation), how a figure is checked before it is trusted, and the two
 * domains — hazard alerts and geospatial risk — where getting the source
 * wrong is the whole failure mode.
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

      <h2 id="specialists">Three specialists behind one conversation</h2>
      <p>
        A single conversation is handled by an <Term>orchestrator</Term> that does not call the
        platform's tools itself. It delegates each question to whichever of three specialist
        agents owns that domain, each with its own system prompt and its own narrower set of
        tools — and it can ask more than one before answering, which is what makes "is it safe
        to fish near Kochi today, and where's the nearest good zone" visibly consult two
        specialists in one turn.
      </p>
      <Table
        headers={['Specialist', 'Answers', 'Tools it can call']}
        rows={[
          [
            <strong>Ocean Analytics</strong>,
            'Forecasts, global ocean state, harmful algal bloom risk, fish habitat suitability, potential fishing zones, historical trends',
            'list_available_variables, get_point_forecast, get_global_ocean_summary, get_bloom_risk, get_fishing_habitat, find_fishing_zones, get_historical_series',
          ],
          [
            <strong>Weather &amp; Safety</strong>,
            '"Is it safe to go out" questions: present-day sea/weather conditions, active alerts, tropical cyclones, severe-weather warnings',
            'get_current_conditions, get_active_alerts, get_cyclone_alerts, get_severe_weather_alerts, get_historical_series',
          ],
          [
            <strong>Geospatial Risk</strong>,
            'Distance to a maritime boundary or Marine Protected Area, seafloor depth, safe-route planning',
            'check_geofence, get_seafloor_depth, plan_safe_route',
          ],
        ]}
      />
      <Callout kind="note" title="Why get_historical_series appears twice">
        "How has X changed" is both an ocean-analytics question — a biogeochemistry trend — and
        a safety one — a wave or wind trend building over days. It is the same tool either way,
        so both specialists carry it rather than one specialist having to ask the other to run
        it on its behalf.
      </Callout>
      <p>
        Underneath the answer, a <Term>delegation trace</Term> lists which specialist was asked
        and why — one line per delegation, in the order the orchestrator decided them, arriving
        before that specialist's own tool calls as the answer streams in. It is a record of the
        orchestrator's own reasoning, not of a result: it says <em>who was asked</em>, and the
        tool observations below it say what they found.
      </p>

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

      <h2 id="alerts">Three answers that sound like "any warnings out there"</h2>
      <p>
        The Weather &amp; Safety specialist has three tools that all touch on hazards, and
        they are not interchangeable — each comes from a different source and answers a
        different question.
      </p>
      <Table
        headers={['Tool', 'Source', 'Answers']}
        rows={[
          [
            <code>get_active_alerts</code>,
            "The platform's own threshold rules over real fields (heat stress, wave height, bloom risk)",
            <>Computed rules, not issued marine warnings — the panel never implies otherwise.</>,
          ],
          [
            <code>get_cyclone_alerts</code>,
            'GDACS, aggregating JTWC and other warning centres',
            <>
              Active tropical cyclones worldwide, and proximity to a coordinate. The position is
              the storm's <em>most recently reported fix</em>, not a live track or forecast
              cone.
            </>,
          ],
          [
            <code>get_severe_weather_alerts</code>,
            "IMD's own CAP feed",
            <>
              Nationwide heavy-rain, heatwave, cold-wave and thunderstorm/lightning warnings —
              land included, not scoped to the coast.
            </>,
          ],
        ]}
      />
      <Callout kind="lesson" title="IMD does not publish a cyclone-track feed">
        It looks like it should: IMD is the issuing authority for North Indian Ocean cyclone
        bulletins. But checked against five major landfalls — Biparjoy, Michaung, Tauktae,
        Remal, Dana — IMD's public CAP feed reported every one of them only as a rainfall or
        heat event, never as a tracked storm with a position or category. So a cyclone question
        is answered from GDACS, and IMD's feed is the source for the lightning/heatwave/rain
        half of "any warnings out there" instead. The specialist's own instructions say so
        explicitly, because the two tools' names alone do not make the split obvious.
      </Callout>

      <h2 id="geospatial">Geospatial risk: boundaries, depth and routing</h2>
      <p>
        The three tools behind "am I near the boundary", "how deep is it here" and "plan me a
        route" all resolve to local geometry and live conditions — nothing here depends on an
        external chart provider, which is also why it works even when other tools are down.
      </p>
      <Table
        headers={['Tool', 'Answers']}
        rows={[
          [
            <code>check_geofence</code>,
            "Proximity to India's EEZ (mainland and the Andaman & Nicobar Islands, as separate zones), the India-Sri Lanka maritime boundary (IMBL), and nine named Marine Protected Areas.",
          ],
          [<code>get_seafloor_depth</code>, 'Depth at a coordinate, from GEBCO bathymetry.'],
          [
            <code>plan_safe_route</code>,
            'A route between two coordinates that avoids land, the IMBL and Marine Protected Areas outright, preferring calmer water when a lower-wave detour exists.',
          ],
        ]}
      />
      <Callout kind="note" title="The boundary geometry is real, not a sketch — with one honest surprise">
        The EEZ polygons and the IMBL come from Marine Regions and the 1974/1976 India-Sri
        Lanka treaty line, not a hand-drawn approximation. One consequence of that: a point
        right around Rameswaram / Adam's Bridge reads as <em>outside</em> the mainland EEZ,
        because the source polygon carries a genuine interior exclusion there — the same kind
        of hole it cuts around every river delta and near-shore island on the coast. That is a
        real, mapped detail a coastline sketch could never have represented, not a bug.
        Marine Protected Areas remain a hand-curated list of named sites (a box around each
        one's published centre), because the official WDPA database needs a registered API key
        this deployment does not have.
      </Callout>
      <Callout kind="warn" title="A real search, still not a chart">
        <code>plan_safe_route</code> runs an A* search over a grid built from live bathymetry
        and live wave height — a real router, not a comparison between a few fixed candidate
        paths. It still carries no vessel profile (speed, draft, fuel range) and scores a route
        on wave hazard alone, and every answer from this specialist says the geometry is a
        reference, not a substitute for an official chart before anyone sails on it.
      </Callout>

      <h2 id="reading">Reading an answer properly</h2>
      <Table
        headers={['If you want to know…', 'Look at']}
        rows={[
          ['Which specialist answered, and why it was asked', 'The delegation trace above the tool observations'],
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
