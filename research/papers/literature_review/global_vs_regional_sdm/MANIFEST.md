# Literature review: global vs. regional SDM training extent

Deep-pass literature check for candidate 1.2 in `research/research.md`
(MarisAI's finding: a global-extent fish-habitat SDM scores worse than the
regional model on identical held-out regional rows, despite 64.7x the
training data — diagnosed via comparative MESS, ruling out extrapolation, and
SHAP, showing the mechanism is feature-importance displacement from
coastal-geometry to water-chemistry features). Compiled 2026-08-26.

**One correction from the earlier lighter-pass search:** the paper previously
attributed to "Sillero et al." is actually **El-Gabbas & Dormann (2018)** —
confirmed by fetching the paper directly. No author named Sillero appears on
it. Cite it correctly.

---

## Papers considered

### 1. El-Gabbas, A. & Dormann, C.F. (2018). "Wrong, but useful: regional species distribution models may not be improved by range-wide data under biased sampling." *Ecology and Evolution* 8(4):2196-2206. https://doi.org/10.1002/ece3.3834

**PDF:** downloaded — `elgabbas_dormann_2018_regional_sdm_range_wide_data.pdf` (11 pp, via Europe PMC OA render of PMC5817152).

**Relevance:** Closest prior work. 17 Egyptian bat species, Maxent + elastic net in a point-process framework, regional (Egypt-only) vs. species-specific global-extent training, evaluated by Schoener's D (geographic congruence) and spatial-block-CV AUC. Confirms MarisAI's qualitative direction: global data did not improve the biased regional models. Diagnosis used Maxent permutation importance (not SHAP) and found *accessibility-bias* predictors (distance to cities/roads) dominating — a different, sampling-artifact mechanism from MarisAI's water-chemistry-vs-coastal-geometry SHAP shift. Did **not** use MESS. Despite their own negative result, their discussion recommends building *larger*-scale models spanning adjacent regions — a direct tension MarisAI's paper should address explicitly, since MarisAI's controlled comparison argues the opposite for the fisheries case. 86 citations on Semantic Scholar as of this search; citing-paper sweep (see below) found nothing that closes the MESS+SHAP gap.

### 2. Hanberry, B.B. (2026). "Model bigger to avoid unrepresentative species distribution models from truncated spatial extents, with the modulating influence of prevalence." *Environmental Challenges* 24:101551. https://doi.org/10.1016/j.envc.2026.101551

**PDF:** downloaded — `hanberry_2026_model_bigger_truncated_extents.pdf` (retrieved manually by the user past Elsevier's Cloudflare wall; automated fetch was blocked). Read in full 2026-08-26.

**Relevance — resolved, no conflict, but must be cited and distinguished explicitly.** Hanberry manipulates the *sampling extent of both presence and background/absence samples* (truncated to small ecological units vs. the full North American continent) for 14 wide-ranging tree species, random forests, evaluated by IoU-against-range-maps and standard accuracy metrics. His mechanism: when both classes are drawn from too small an area, there is too little climate contrast between "present" and "absent" samples for the classifier to separate them, so truncated models produce unconstrained predictions that bleed outside the modeled unit (or the reverse) — an **absence/background-sampling-extent artifact**, using plain random background points (not target-group background). His conclusion, "model bigger, at continental scales," is about not truncating background extent when the model is meant to represent a species' *full range*.

This differs from MarisAI's claim on three structural points, not just topic: (1) Hanberry's untruncated model is evaluated against the *full continental range*, and truncated models against their own within-extent withheld samples — there is no single shared, identical holdout scored by both conditions, unlike MarisAI's matched-regional-holdout design; (2) his absences are random background, susceptible to exactly the climate-contrast collapse his finding depends on, whereas target-group background (used by both MarisAI and El-Gabbas & Dormann) is designed to avoid that specific artifact; (3) his "bigger is better" is about *not truncating* background sampling extent to preserve representativeness of the full range, not about whether *adding* a large volume of weakly-relevant external data helps or hurts skill *on a fixed target region* — the question MarisAI's MESS-plus-SHAP analysis answers, and MESS explicitly rules out his mechanism (the global model extrapolates *less*, 1.24% vs 9.04%, not more).

**Required action, not optional:** MarisAI's paper must cite this and state the distinction explicitly in one sentence, or a reviewer familiar with Hanberry's abstract alone will flag an apparent contradiction. Suggested framing: "Hanberry (2026) shows truncating background-sampling extent degrades representativeness across the omitted geography — a distinct failure mode from ours, where extent is expanded rather than truncated, evaluation is held fixed on the target region, and MESS rules out the climate-contrast/extrapolation mechanism his finding depends on."

### 3. "Species distribution models built with local species data perform better for current time, but suffer from niche truncation" (2024). *Agricultural and Forest Meteorology* (or companion Elsevier journal — exact journal title not confirmed past the DOI). https://doi.org/10.1016/j.agrformet.2024.110361

**PDF:** not downloaded — same ScienceDirect CAPTCHA wall. Confirmed **CC-BY open access** via Unpaywall.

**Relevance:** Same qualitative direction as MarisAI (local/regional beats broad-extent for current-time accuracy) but frames the *cost* of going local as niche truncation — a real trade-off MarisAI's paper should acknowledge rather than present regional-only as free of downside. Complements rather than conflicts with the finding.

### 4. "Zooming In: Assessing the Transferability of SDMs From Large to Small Spatial Extents." *Ecology and Evolution*. https://doi.org/10.1002/ece3.72419 (PMC12696477)

**PDF:** downloaded — `zooming_in_transferability_sdm_extents.pdf` (8 pp, via Europe PMC).

**Relevance:** General transferability-by-extent study; supports MarisAI's finding as an instance of a broader, non-monotonic extent-performance relationship rather than an isolated anomaly.

### 5. Guisan, A. et al. (2025). "Spatially nested species distribution models (N-SDM): An effective tool to overcome niche truncation for more robust inference and projections." *Journal of Ecology*. https://doi.org/10.1111/1365-2745.70063

**PDF:** downloaded — `guisan_2025_nested_sdm_niche_truncation.pdf` (18 pp, via the Ifremer Archimer institutional repository OA copy, not the Wiley paywall).

**Relevance:** New find from the citing-paper sweep, not in the original list. Reviews the "combine a whole-range coarse model with a subrange fine model" (N-SDM) solution to niche truncation. Does not use MESS or SHAP per the abstract/search snippets. Useful as the "field's proposed compromise" to cite: MarisAI's finding motivates *why* such nested approaches matter (regional-only wins on skill but risks truncation; N-SDM is the field's answer to getting both), positioning MarisAI's result as motivation for, not a rebuttal of, this line of work.

### 6. "Distribution model transferability for a wide-ranging species, the Gray Wolf." *Scientific Reports* 12, 11409 (2022). https://doi.org/10.1038/s41598-022-16121-6

**PDF:** downloaded — `graywolf_2022_transferability_sci_reports.pdf` (11 pp, open access, direct from Nature).

**Relevance:** General transferability-across-extent case study (terrestrial, not marine); supporting citation for the "extent choice matters and is taxon/domain-independent" framing.

### 7. "A Comparative Machine Learning Study Identifies Light Gradient Boosting Machine (LightGBM) as the Optimal Model for Unveiling the Environmental Drivers of Yellowfin Tuna (*Thunnus albacares*) Distribution Using SHapley Additive exPlanations (SHAP) Analysis" (2025). *Biology* 14(11):1567. https://doi.org/10.3390/biology14111567 (PMC12650498)

**PDF:** downloaded — `lightgbm_shap_yellowfin_tuna_2025.pdf` (26 pp, MDPI open access via Europe PMC).

**Relevance:** Same species family, same model class (LightGBM), same diagnostic tool (SHAP) as MarisAI's methodology — but single-region (western/central Pacific), no extent comparison at all. Its own stated future work explicitly calls for "comparative analysis across diverse fleets and fishing regions," which MarisAI's global-vs-regional result directly answers. This is the strongest direct methodological precedent and the paper to open with in a related-work section.

### 8. Elith, J., Kearney, M. & Phillips, S. (2010). "The art of modelling range-shifting species." *Methods in Ecology and Evolution* 1(4):330-342. https://doi.org/10.1111/j.2041-210X.2010.00036.x

**PDF:** downloaded — `elith_2010_mess_range_shifting_species.pdf` (13 pp, via an open course-materials mirror; the canonical Wiley copy is paywalled/bot-walled).

**Relevance:** The originating MESS (Multivariate Environmental Similarity Surface) paper — the standard citation for MarisAI's extrapolation-diagnosis method. Confirmed as standard/widely used via search; no example found anywhere of MESS being used *comparatively* between two models of differing training extent to rule out "the larger model must be extrapolating more" — that comparative use is a genuine methodological contribution of MarisAI's paper, not just an application of an existing tool.

### 9. Zhang, W. et al. "A Survey on Negative Transfer." arXiv:2009.00909.

**PDF:** downloaded — `negative_transfer_survey_arxiv_2009.00909.pdf` (13 pp).

**Relevance:** General ML-theoretic grounding for the mechanism (dataset dilution / domain mismatch causing more-data-to-hurt-performance). Confirms the survey explicitly flags that overabundant target-irrelevant data exacerbates source/target divergence — matches MarisAI's mechanism (123k global rows diluting locally relevant signal) almost exactly. No prior source found connecting this ML-theoretic literature to an ecological SDM extent-choice debate at all, let alone via MESS+SHAP.

### 10. Ecography, "Factors influencing transferability in species distribution models." https://doi.org/10.1111/ecog.06060

**PDF:** not downloaded — Wiley Online Library is behind a Cloudflare bot-check wall (confirmed via claude-in-chrome; not bypassed). Confirmed open access via Unpaywall (`is_oa: true`) — retrievable by a human directly at the DOI.

**Relevance:** General finding that SDM transferability depends more on environmental distance than geographic distance or algorithm choice, and that performance-by-extent can be non-monotonic. Supports MarisAI's finding as an instance of a known-but-unresolved pattern.

---

## Downloaded: 7 of 10
## Skipped (citation kept, PDF not obtained): 3 — all confirmed open-access by Unpaywall but blocked by Cloudflare bot-detection on ScienceDirect (×2: Hanberry 2026, niche-truncation 2024) and Wiley (×1: Ecography transferability). No CAPTCHA-solving was attempted, per policy. A human can retrieve all three directly at the DOIs listed above with no subscription required.

## Final novelty verdict

**Confirmed, with one open risk to close before submission.** The exact
combination MarisAI has — (a) a matched-holdout controlled comparison
(identical rows, spatial blocks removed) between a global and a regional
model, (b) MESS used *comparatively* to rule out "the bigger model
extrapolates more" rather than to flag novelty within a single model, (c)
SHAP used to diagnose the mechanism as feature-importance displacement
(coastal geometry → water chemistry), and (d) all of this in a marine
fisheries/tuna-habitat context — was not found published anywhere in this
search, including a full citing-paper sweep (86 citations) of the closest
prior work (El-Gabbas & Dormann 2018) through 2026.

**The one open risk:** Hanberry (2026), "Model bigger to avoid
unrepresentative species distribution models... with the modulating
influence of prevalence," is recent, cites the same lineage, and argues (per
title alone — full text could not be extracted past the ScienceDirect bot
wall) for the opposite prescription. Its metadata gives no indication it
uses MESS or SHAP, and "prevalence" is a different lens than "training
extent size" — but this should be read in full by a human before the paper
is finalized, since it is the single most likely candidate to already
contain a conflicting or overlapping result. Everything else strengthens
rather than undermines the novelty claim.

**What changed from the earlier lighter pass:** the author attribution
correction (El-Gabbas & Dormann, not "Sillero"); two new supporting citations
found via the citing-paper sweep (Hanberry 2026, Guisan et al. 2025 N-SDM);
and explicit confirmation, via a citation-graph check rather than a single
search pass, that no 2022-2026 paper citing the closest prior work has
already combined MESS with SHAP or with a comparative-extent design.
