# Vendored React Bits components

Source: <https://reactbits.dev>, the **TS-CSS** variant of each component,
fetched from its shadcn registry (`https://reactbits.dev/r/<Name>-TS-CSS.json`).

React Bits is not an npm dependency and is not meant to be one — it ships
source you copy in and own. That is why it fits here despite CLAUDE.md's
"hand-roll it, minimal deps" rule: what lands in the repo is plain TSX + CSS
that stays hand-editable, not a black box. The TS-CSS variant specifically,
because the TW variants would have pulled Tailwind out of `features/dashboard/`,
which is the one place it is allowed to live.

## The three things every vendored component needs

Upstream ships none of these, and all three have already bitten:

1. **Colours must become `--ma-*` tokens.** Components arrive with literal hex
   values chosen for a dark demo page (`SpotlightCard` shipped `#111` on
   `#222`). Left alone they ignore the theme toggle entirely and render a dark
   card on the light theme.

2. **`motion/react` imports must be retargeted to `framer-motion`.** Upstream
   depends on `motion@^12`, which is the same codebase under a newer name;
   this repo already has `framer-motion@^12` for the dashboard. Rewriting the
   import avoids a second copy of the same library in the bundle.

3. **Reduced motion must be handled explicitly where the animation is
   JS-driven.** `styles/tokens.css` has an app-wide rule, but it only collapses
   CSS durations — a gsap timeline or a WebGL render loop runs straight
   through it. Prefer resolving to the *finished* state, per
   `pages/landing/useScrollReveal.ts`.

## What is vendored, and what it costs

| Component | Runtime dep | Used by |
| --- | --- | --- |
| `SpotlightCard` | none | landing cards |
| `ShinyText` | framer-motion (retargeted) | chat pending turn |
| `SplitText` | `gsap`, `@gsap/react` | landing hero headline |
| `Aurora` | `ogl` | landing closing backdrop |

**`CountUp` was vendored and then deleted.** `pages/landing/useScrollReveal.ts`
already exports a `useCountUp` that is better suited here: it is driven by
`useReveal`, which measures geometry directly rather than trusting an
`IntersectionObserver`, and it already resolves to the final value under
reduced motion. React Bits' version is `useInView`-based, so adopting it would
have swapped a safe implementation for one needing both fixes — and a counter
whose trigger never fires renders `0`, which on this page is a false statistic.
Check for an existing hook before vendoring the next one.

`ogl` is a ~30 KB WebGL wrapper, chosen over the `three` + `@react-three/fiber`
components (`Silk`) which would have added ~600 KB for a background.

**Deliberately not vendored:** `PillNav` and `CardNav` (require
`react-router-dom`, and this app's router is hand-rolled — see
`app/router.tsx`), and anything needing `react-icons` (the app uses
`lucide-react` plus inline SVG for brand marks).

## Re-vendoring

Re-fetch the registry JSON and re-apply the three changes above; the diff
should be small and readable. Keeping upstream's class names
(`.card-spotlight`, etc.) is intentional for exactly this reason.
