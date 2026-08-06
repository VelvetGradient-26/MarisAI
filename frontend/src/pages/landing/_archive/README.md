# Archived: the "ocean dive" landing page

Superseded 2026-08-05 by a research-oriented landing page. Kept rather than
deleted because it is ~1,600 lines of working, non-trivial scroll choreography
that took real effort, and nothing in it is broken.

| file | what it was |
|---|---|
| `OceanDiveScene.tsx` | scroll-driven dive backdrop — sunlit surface fading through light shafts, a 50-fish school, whales, and a bioluminescent abyss, with a live depth gauge reading to 4,000 m |
| `LandingPage.dive.tsx` | the page that sat on top of it (hero with pier + buoy, layered SVG waves) |
| `landing.dive.css` | its styles, including the depth-colour stops |

## Why it was replaced

Two reasons, and the second is the substantive one:

1. **Register.** The illustrated creatures and depth gauge read as a game or a
   museum exhibit. What this platform actually is — 109 trained forecasting
   models, a 14-provider data downloader, two peer-reviewable ML pipelines —
   is better served by restraint than by whimsy.

2. **The numbers on it were invented.** The old hero claimed "40M+ ocean data
   points ingested daily", "12 satellite & buoy feeds unified" and a "15 min
   forecast refresh interval". None of those were measured; none corresponded
   to anything in the codebase. That sits badly in a project whose dashboard
   rule is *never substitute a number for missing data*. Every figure on the
   replacement page is read from the code or from a measured run.

## Restoring it

Nothing else imports these files. To bring the scene back, move
`OceanDiveScene.tsx` up one directory and render `<OceanDiveScene dark={isDark} />`
as the first child of the page root — it is self-contained and drives itself
from `window.scrollY`.
