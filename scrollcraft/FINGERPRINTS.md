# Fingerprints

Every site you build with **scrollcraft** gets one row here, appended after it
ships. The registry exists so your next build can prove it is a different page
rather than a re-skin of one you already made.

This file is **yours**. It starts empty on purpose: the gate is about not
repeating *yourself*, so it has nothing to say until you have built something.

The rules and the gate live in the skill's
`references/uniqueness.md`. Short version:

**A new build must differ from EVERY row below on at least 4 of the 6
dimensions.** Four against each row individually, not four on average across the
table. If a planned build fails, change the plan. Never edit a row to make room
for it.

The six dimensions are: **grammar**, **nav treatment**, **hero device**,
**act-sequence shape**, **close pattern**, **signature move**.

Dimension 6 is free, because a signature move is unique by definition. So the
gate really asks for three more out of the remaining five, and a build that
changes only grammar and world will fail it.

---

## The registry

| Build | Grammar | Nav treatment | Hero device | Act-sequence shape | Close pattern | Signature move | World | Port |
|---|---|---|---|---|---|---|---|---|
| marisai-landing-redesign (2026-08-26) | Chaptered editorial | App's own persistent shared `Navbar` (not page-owned chrome) | Existing WebGL `HeroField` vector-field canvas + two-line kinetic split-text title, corner-anchored, sharpened with a new problem-framing kicker line | 8 numbered chapters (Hero/Metrics/Ticker/Forecasting/**Descent**/Coverage/Platform/Research/Rigour/Closing), hard cuts, ~13vh total, one deliberately tall (340vh) pinned chapter mid-sequence | Magnetic CTA pair over a lazy-mounted WebGL aurora backdrop (`ClosingBackdrop`), kept from the prior build | Scroll-scrubbed descent of a real, live, isolated MapManager/MapLibre instance (whole globe → Arabian Sea coastal box, pitch and zoom driven by scroll progress) with real overlay layers (SST, currents, eddies) cross-fading on at threshold bands — not a video, not a screenshot, the platform's own map engine | Deep-sea instrument panel — near-black dark theme (teal in light mode), real bioluminescent-cyan accent, no generated imagery | React 19 + TS + Vite SPA route (not a standalone static build) |

*(First row. Nothing yet to avoid repeating, but this build now claims: chaptered editorial as a grammar fit for a page whose existing structure was already numbered/hard-cut sections; a live-product-embed signature move over a generated-video one; and the shared-app-navbar nav treatment, which is the platform's own convention rather than a scrollcraft-authored chrome — the next MarisAI build should reach for a different grammar, a different kind of signature move, or both.)*

---

## What is taken

Add a bullet here whenever a build claims something a later build should avoid
reusing: a grammar, a nav treatment, a close pattern, a signature move, an
act-count-and-length band. The shared columns are what the next build inherits
as a constraint, so writing them down is the whole point.

- **Chaptered editorial**, claimed by `marisai-landing-redesign`.
- **A live-product-embed signature move** (scroll driving a real, running
  instance of the product itself, not a video/canned animation), claimed by
  `marisai-landing-redesign`'s map descent.
- The **8-chapter, ~13vh, one-pinned-chapter** act shape, claimed by
  `marisai-landing-redesign`.

---

## Appending a row

After shipping, add one line to the table and one bullet to **What is taken** if
the build claimed something new. Fill every column. Say what the build shares
with existing rows.

Rows are append-only. A build that has been superseded stays in the table,
because the space it occupies is still occupied.

---

## Worked example

The skill's author kept a registry of twelve builds across eight page grammars.
If you want to see what a filled-in table looks like, and which shapes tend to
collide, read `EXAMPLES.md` in the scrollcraft repository. Treat it as
illustration only: those rows are somebody else's builds and they do **not**
constrain yours.
