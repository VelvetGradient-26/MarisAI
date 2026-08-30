# MarisAI — Fisheries / Biodiversity Data Sources

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

## Fisheries / biodiversity data sources (probed 2026-08-05)

Only `marine_ml/sources/obis.py` is implemented today. This is the survey of
candidates to widen it. **Every endpoint below was probed live on 2026-08-05**;
re-probe before relying on a "works" verdict months later. Sort order is
"worth wiring up next" first.

### Tier 1 — open REST/JSON, no key, occurrence-shaped (drop-in beside OBIS)

| Source | Endpoint | Notes |
| --- | --- | --- |
| **OBIS** | `https://api.obis.org/v3/occurrence` | Already implemented. Also `/statistics` and `/checklist` (both 200) — `statistics` gives record/dataset/year-range counts for a species in one cheap call, which is the right way to size a region+species window *before* paging 200 pages. **`hasextensions=DNADerivedData` filters to eDNA on every one of these plus `/occurrence/grid/{p}`** — 44.5M records, 11,927 species, 131 datasets, 2001–2025, and it is where `backend/services/edna.py` comes from. Adding eDNA to a *model* is a different question and was answered no: see the eDNA section above for why it reopens neither the habitat window nor Arabian Sea HAB. |
| **GBIF** | `https://api.gbif.org/v1/occurrence/search` | 200, no key for reads. Darwin Core, so the column mapping in `obis.py` mostly transfers. |
| **iNaturalist** | `https://api.inaturalist.org/v1/observations` | 200, no key. Citizen science — heavy coastal/shore bias, `quality_grade=research` is mandatory, and it is *not* a survey. |
| **WoRMS** | `https://www.marinespecies.org/rest/AphiaRecordsByName/<name>` | 200. Taxonomic backbone — the right place to resolve/validate a scientific name and its AphiaID before querying anything else. |
| **Marine Regions** | `https://marineregions.org/rest/getGazetteerRecordsByName.json/<name>/` | 200. EEZ/LME/sea-area polygons — the natural way to define a region bound instead of hand-written bboxes. |
| **Sea Around Us** | `https://api.seaaroundus.org/api/v1/eez`, `/eez/tonnage/taxon/?region_id=…` | 200 both. Reconstructed *catch* by EEZ/taxon — aggregate landings, not occurrences. Different table, different join. |
| **ICES DATRAS** | `https://datras.ices.dk/WebServices/DATRASWebService.asmx` (`/getSurveyList` verified, returns XML) | 200. **Trawl surveys with real zero-catch hauls** — the only source here that gives *true absences*. That is a categorically better label source than OBIS pseudo-absences, but North Atlantic/European only. SOAP-ish `.asmx`, returns XML not JSON. |
| **EMODnet Biology** | `https://geo.vliz.be/geoserver/Emodnetbio/wfs?service=WFS&request=GetCapabilities` | 200. WFS, so `GetFeature` with a bbox works without a portal scrape. European. |
| **NASA Earthdata CMR** | `https://cmr.earthdata.nasa.gov/search/collections.json` | 200 unauthenticated for *search*; downloads need Earthdata Login. |
| **NOAA ERDDAP** | `https://coastwatch.pfeg.noaa.gov/erddap/` | 200. Already a known quantity in this codebase — see the ERDDAP flapping and 404-retry notes under the forecasting engine, they apply to every ERDDAP host here (OTN included). |
| **OTN** | `https://members.oceantrack.org/erddap/` | 200 (the `/info/index.json` probe returned 000 = TLS/handshake flake; the HTML index is fine — retry rather than concluding it is down). Acoustic telemetry: individual tracks, not occurrences. |
| **HYCOM** | `https://tds.hycom.org/thredds/` | 200. THREDDS/OPeNDAP. Environmental covariate, overlaps Copernicus — no reason to add unless Copernicus lacks a field. |
| **Zenodo / Dryad / DataONE / PANGAEA** | `zenodo.org/api/records`, `datadryad.org/api/v2/search`, `cn.dataone.org/cn/v2/query/solr/`, `ws.pangaea.de/oai/provider?verb=Identify` | All 200. Generic repositories — per-dataset ad-hoc schemas, so these are for *finding* a dataset, never for a scheduled fetch. PANGAEA's `ws.pangaea.de/es/dataportal-item/_search` is **404 — that ES endpoint is gone**; use the OAI-PMH provider. |

### Tier 2 — reachable but gated, or bulk-download only (no clean API)

- **Global Fishing Watch**: `gateway.api.globalfishingwatch.org/v3/datasets` → **401**, expected — needs the token already in `backend/.env` (`services/gfw.py`). Effort/AIS, not biology.
- **Movebank**: `movebank.org/movebank/service/direct-read` → **401**. Free account + per-study permission from the data owner; most studies are not open.
- **AIMS**: `open-aims.github.io/data-platform` 200 (docs), `api.aims.gov.au` **403** — needs an API key.
- **FishBase**: the ropensci mirror `fishbase.ropensci.org` is **dead (000, DNS)** — do not code against it. `fishbase.se` serves 200 HTML; programmatic use means the `rfishbase` data dumps, not a live API.
- **AquaMaps / Bio-ORACLE / MARSPEC**: 200, but these are **modelled raster products downloaded as files**, not queried. Bio-ORACLE and MARSPEC are environmental covariate layers; AquaMaps output is a *model prediction* — using it as a label would be training on another model.
- **IOTC / ICCAT / CCSBT**: data pages 200. RFMO catch/effort, gridded aggregates behind manual download forms; ICCAT partly requires a request. **WCPFC**: both `/public-domain` and `/public-domain-data` are **404** — the URL moved, needs a fresh look before anyone plans on it.
- **FAO FishStat**: 200. Desktop app + bulk zip; national annual landings. Country-year granularity, useless for a habitat model, fine for context.
- **NOAA Stock SMART**: web app 200; `apps-st.fisheries.noaa.gov/sis/api/` and `/adb/` are **404** — no documented public API found, treat as bulk export.
- **DFO Canada**: use the federal CKAN — `open.canada.ca/data/en/api/3/action/package_search` is 200 (the plain `/dataset?organization=…` URL 400s). Per-dataset formats still vary.
- **CSIRO** (`data.csiro.au`), **NIWA** (`niwa.co.nz` 200; the `/coasts-and-oceans/marine-data` path is **404**), **NCEI**, **MBON**, **GOOS**, **RLS**: all reachable as portals. RLS is genuinely valuable (standardised reef transects **with abundance and real zeros**) but ships as CSV downloads.
- **VertNet**: portal 404 and the appspot API 500s. **Treat as defunct**; its marine content is in GBIF anyway.

### Tier 3 — Indian sources (the gap that motivated this, and the hardest)

**None of these has a machine-readable API.** Everything is PDF/HTML publications
or manual request. Verdict per probe:

- **CMFRI** — `cmfri.org.in` 200 and **`eprints.cmfri.org.in` 200**. The eprints repository is the single most useful Indian handle here: it is EPrints, so it has OAI-PMH, and it holds the annual marine fish landings estimates. Still document-level, not record-level.
- **FSI** — `fsi.gov.in` 200. Survey cruise data; publications only, data by request.
- **IndOBIS** — **verified reachable through the existing OBIS API; no new integration needed.** It is a Regional OBIS Node run by CMLRE, node id `1a3b0f1a-4474-4d73-9ee1-d28f92a83996`, and `?nodeid=` is accepted by `/v3/occurrence`, `/v3/dataset` and `/v3/statistics`. 79 datasets, 110,905 records, 19,210 species, years 1743–2025; the Actinopterygii subset (`taxonid=10194`, the pipeline's existing target group) is 16,701 records / 3,217 species across 36 datasets. `obis.py` already pulls these — the node filter is only useful as a *provenance/diagnostic* facet (e.g. "how much of this region's background is Indian-sourced"), not as extra data. `indobis.in` 200; the older `indobis.org` **403s**.
- **CIFT** → use **`cift.res.in`** (200). **CIBA** → **`ciba.res.in`** (200). The `*.icar.gov.in` hostnames for CIFRI/CIFT/CIBA/CIFA all returned **000 (DNS/TLS failure)** and `cifa.nic.in` 400 — the `icar.gov.in` subdomains are not reliable entry points; prefer the `.res.in` domains and re-probe CIFRI/CIFA.
- CIFRI/CIFA/CIBA are inland/brackishwater/freshwater aquaculture — largely **out of scope** for a marine habitat model regardless of accessibility.

### Two findings that change what to build

- **GBIF is not a superset of OBIS for marine fish.** Measured on *Thunnus
  albacares*: OBIS 246,964 records vs GBIF 174,799 with coordinates. Adding
  GBIF is a genuine union, not a migration, and it **requires deduplication** —
  a large share of GBIF's marine records are OBIS datasets republished, so
  merging naively double-counts and inflates apparent sampling effort exactly
  where the pseudo-absence scheme is most sensitive to it. Dedup on
  `occurrenceID`, falling back to (dataset, catalogNumber, lat, lon, date).
- **Adding GBIF would 3–6x the tuna labels inside the *existing* habitat
  window, but does not extend it.** Measured for `TARGET_SPECIES` inside
  `NORTH_INDIAN_OCEAN` (records, OBIS vs GBIF):

  | species | 2000–2013 OBIS | 2000–2013 GBIF | 2014–2025 OBIS | 2014–2025 GBIF |
  | --- | --- | --- | --- | --- |
  | *Thunnus albacares* | 394 | **1228** | 32 | 34 |
  | *Katsuwonus pelamis* | 280 | **1622** | 14 | 18 |
  | *Thunnus obesus* | 283 | **678** | 4 | 4 |
  | *Rastrelliger kanagurta* | **67** | 9 | 40 | 51 |
  | *Sardinella longiceps* | **112** | 9 | 9 | 17 |

  Two conclusions, both load-bearing:
  - **`HABITAT_END = 2013` stands.** The post-2014 drought that `config.py`
    documents is real in *both* sources — GBIF adds essentially nothing there
    (4 records for bigeye either way). It is not an OBIS artefact, so no
    amount of source-widening moves the window; do not reopen that decision
    on the assumption that more sources means more recent labels.
  - **The union runs both directions**, which is why it must be a union and
    not a switch: GBIF dominates for the three tunas, OBIS dominates ~10x for
    Indian mackerel and oil sardine (67 vs 9, 112 vs 9) — the two species that
    matter most for Indian coastal fisheries. Dropping OBIS for GBIF would
    gut exactly the local species the model exists to serve.
- **ICES DATRAS and RLS are the only true-absence sources found.** Everything
  else in this list is presence-only, which is why `fish_habitat` has to draw
  pseudo-absences from a target group at all. If the model region can be moved
  to somewhere DATRAS or RLS covers, that constraint disappears — that is a
  bigger accuracy lever than any change to the classifier.


