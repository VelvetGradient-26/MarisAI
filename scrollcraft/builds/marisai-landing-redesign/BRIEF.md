# MarisAI landing page redesign — BRIEF

**Interviewed 2026-08-26, in-conversation (not self-authored).**

**Platform-integration note, stated up front because it changes how this skill
applies:** this is not a new standalone marketing site. `frontend/src/pages/LandingPage.tsx`
is a live route inside a real React 19 + TS + Vite SPA with strict, checked-in
conventions (`CLAUDE.md`): hand-rolled router, per-page CSS custom-property
tokens aliasing `styles/tokens.css`, framer-motion/gsap/ogl as the only animation
deps, and — specifically for this page — a hard rule that **every number on it
is read from the codebase or a measured run, never invented**. The existing page
is already a mature scroll-reveal build (WebGL hero field, `KineticText`,
`SplitText`, CSS `animation-timeline` parallax, 3D-tilt platform cards, a
spotlight-card research grid). So this build:

- Uses the skill's *method* — interview, journey, feeling curve, grammar,
  fingerprint-style device variety, one signature move, screenshot verification.
- Does **not** copy in `engine/scrollcraft.js`/`.css` or spin up a Playwright/
  kie.ai asset pipeline. There is no separate build folder that ships; the
  output is edits to the real route, in the real stack, reusing the real
  `MapManager`/`layerRegistry` for the signature move rather than faking it.
- Treats "real app screenshots" as: live embedded instances of the actual map
  (`MapManager`) and dashboard components where credible, not static PNGs of
  them — screenshots would be stale the moment a layer changes, and the whole
  page's ethic is "this is really running."

## 1. Vibe

**Deep-sea instrument panel.** Cold, precise, bioluminescent — a research
vessel's bridge at night. References: submersible cockpits, oceanographic
survey ships, NASA mission control. (Close to the existing dark palette
already in `landing.css`, so this is a sharpening, not a repaint.)

## 2. Journey (their words → structure)

**"Problem then platform."** Chosen over "straight into the product." The
existing page opens directly on the brand claim ("The ocean, quantified") with
no framing of *why* this is hard. The redesign opens on the ocean's scale and
unpredictability first, then resolves into the platform turning it legible.

Journey beats:

1. **Scale** — the ocean is too big and too fast-changing to hold in your head.
   No claim yet, no product yet. Just the size of the problem.
2. **Turn** — that scale becomes legible: {PROVIDERS} live providers, a global
   forecasting engine. This is where the brand claim now lands, having earned
   it.
3. **Proof** — the forecasting engine's real skill-vs-persistence numbers
   (kept from the current page verbatim, they're already real).
4. **Peak: the descent** — scroll drives a real MapLibre camera down through
   the platform's own live map (basemap → SST → currents/eddies), ending on
   the actual `/map` route's own layer stack. This is where "raw ocean becomes
   legible" is *shown*, not claimed.
5. **Range** — the four surfaces (map, dashboard, download, assistant),
   kept from the current `Platform` section with its 3D-tilt cards, since
   that device hasn't been used yet in this journey.
6. **Rigour** — the "Honesty is a feature" principles section, kept close to
   as-is; it's already the platform's actual voice and needs no redesign, only
   a new position in the sequence (mid-resolve, not tacked on at the end).
7. **Commitment** — close on the map CTA, kept.

## 3. Structure: distinct scenes

Chosen over one continuous world. The current page is already scene-based
(numbered `Eyebrow` sections, hard `lp-section--panel` cuts) — this is a
continuation of that shape, not a break from it. **Grammar: chaptered
editorial** (§2.2 of uniqueness.md) is the closest existing-page fit: numbered
chapters, hard cuts between grounds (no continuous drift interpolation), media
in its own column with a caption rather than bleeding under type, prose that
reads as "read something" not "watched something" — which matches this page's
already-dense, evidence-heavy copy better than filmic one-shot's carried-along
feel. Filmic one-shot was the runner-up and is rejected because the journey
answer ("distinct scenes") explicitly argues against continuous handoff, and
because the current page's own numbered-eyebrow structure already reads as
chapters, not a single shot.

Chaptered editorial's bans (`scrub` beyond one chapter, `spotlight`, `magnet`)
are relaxed by exactly one chapter for the signature move, which is
necessarily a live, driven surface — the same "one deliberate deviation, not a
drift back to the default" allowance the skill gives magnetic CTAs on two
specific hero/close calls today. `SpotlightCard` in the Research chapter and
the magnetic hero/close CTAs are existing, working, on-brand devices and are
kept rather than stripped for grammar purity — ripping out working, tasteful,
already-convention-compliant devices to satisfy a bans list drawn up for
generated marketing sites is not what "redesign" was asked for here.

## 4. Energy curve

**Calm open, intense middle, resolved close.** Scale (calm, spare, mostly
type and dark water) → Turn/Proof/Descent (intensity rises, peaking at the
live map camera move) → Range/Rigour/Commitment (settles into confident,
information-dense resolve, not a fade-out).

## 5. Feeling curve and peak

| Act | Feeling | Cause |
|---|---|---|
| Scale | Small, quiet unease | Dark water, sparse type, no UI chrome yet |
| Turn | Recognition | The claim lands now that the problem is stated |
| Proof | Trust building | Real skill numbers, not adjectives |
| **Descent (peak)** | **Awe / relief** | **Raw ocean visually resolves into read data as the real map camera descends and layers snap on** |
| Range | Curiosity | Four real surfaces, tactile 3D cards |
| Rigour | Respect | The platform admits its own limits |
| Commitment | Confidence | One clear action, held |

**Peak, as a visitor would say it:** "the map just came alive under my
scroll, and suddenly I could see the whole ocean." Lives in the Descent act
(new — inserted between the existing Forecasting and Platform sections).

**Tell-someone sentence:** "It's the site where scrolling actually flies the
map down into the live ocean data."

## 6. Signature move

**Scroll-scrubbed map descent.** Scrolling through the Descent chapter drives
a real, mounted `MapManager` instance (the same engine `/map` uses) through a
scripted `flyTo`/zoom/pitch sequence keyed off scroll progress (`--sc-p`-style,
via the existing `useScrollProgress` hook already in `landing/useScrollReveal.ts`),
starting on the whole-globe Abyss basemap and descending toward a real coastal
box, cross-fading on real overlay layers in sequence (SST → currents
particles → eddies) as the descent completes, ending held on a live frame the
visitor could be looking at on `/map` right now. Not a video: a live MapLibre
instance, scroll-driven, showing the actual product. This is the platform's
own "live surface" ethic (`services/*` never fabricate a reading) applied to
the hero device itself, and it's why the section fetches real cached
endpoints rather than a canned animation.

Rejected alternative: a "live data cameo" pulling one live number inline into
copy. Real and cheap, but it's an amplification of what `Metrics`/`Ticker`
already do, not a new kind of moment — the map descent is the one that
delivers "the ocean, quantified" as an experienced fact rather than a
sentence, and it's the only device on the page that touches the live, running
product rather than a rendering of numbers about it.

## 7. Aesthetic range

**Premium-minimal**, as recommended and matching "deep-sea instrument panel."
No departure from the existing dark palette; sharpen rather than reskin.

## 8. Assets

**Real app screenshots → real, live, embedded product**, upgraded per above:
the Descent chapter embeds a genuine `MapManager` (read-only, scroll-driven,
no user pan/zoom controls) rather than a static image of the map. The four
`Platform` surface cards keep their existing SVG glyphs (`Diagrams.tsx`) —
those are already accurate abstract diagrams of real capabilities, not stock
imagery, and swapping them for screenshots would be a downgrade (a glyph
reads at card size; a screenshot of `/dashboard` at 280px is illegible). No
generated imagery, no kie.ai spend.

## Fingerprint gate

No prior scrollcraft builds exist for this user (`FINGERPRINTS.md` seeded
empty) — gate trivially passes. This build's row, once shipped: grammar
*chaptered editorial*; nav = the app's persistent shared `Navbar`, not
page-owned chrome; hero device = existing WebGL `HeroField` + kinetic two-line
title (kept, sharpened); act shape = 8 chapters (Scale/Turn/Proof/Descent/
Range/Rigour/Commitment/Close) at an estimated ~11–13vh; close = magnetic CTA
pair over `ClosingBackdrop`, kept; signature move = live scroll-driven
MapLibre descent.
