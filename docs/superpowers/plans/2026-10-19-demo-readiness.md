# Demo Readiness (24 Oct 2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the audit's deployment and business-logic findings and make the EC2 instance demo-ready, so that starting the instance is the only manual step on 24 Oct 2026.

**Architecture:** All fixes land in the repo first, behind tests, and the EC2 instance is then rebuilt from GitHub `main`, so instance and GitHub are identical again.
Production gets its own compose file (`docker-compose.prod.yml`, nginx frontend, internal backend) selected on EC2 through a root `.env`, leaving the local dev compose untouched.
The instance gets a bigger, cleaned disk, log rotation, a backend that discovers its own public URL from EC2 instance metadata (no Elastic IP, by the user's choice), a start script that prints the current URL, and a readiness script that reports when every demo surface is warm.

**Tech Stack:** Python 3.11 / FastAPI / pytest (backend), React + Vite + nginx (frontend), docker compose, AWS EC2 + EBS + Elastic IP (AWS CLI, region ap-south-1).

**Spec:** Part III ("Audit report") of `docs/guide/MarisAI_How_It_Works.pdf`, finding IDs D1-D10 and L1-L15.
The table under "Findings coverage" maps each ID to its task.

## Global Constraints

- Demo: **Fri 24 Oct 2026**. Code freeze **Thu 23 Oct 18:00 IST**; after that, only the Task 18 rehearsal and its fixes.
- Instance: `i-0c7686f701d6b0af1`, volume `vol-006a8e0ab51d0cd14`, SG `sg-0c2bd5f32efbdd067`, key `~/Downloads/my-web-server-key.pem`, user `ec2-user`, repo at `~/maris/MarisAI`.
- Never substitute a number for missing data. "Unknown" must never be reported as "low", "calm" or "safe".
- No em dash characters (U+2014) in code, comments, docs or commit messages. Use "-".
- Commit messages: no agent co-author lines (user's global CLAUDE.md overrides the harness attribution reminder).
- Before any destructive step on EC2 (`git reset --hard`, container removal, `docker * prune`), the Task 0 backup must exist. Never run `docker volume prune` or `docker system prune --volumes`.
- Sea-state thresholds have exactly one definition (Task 6 `services/sea_state.py`): wave 1.5 / 2.5 m, wind 40 / 62 km/h.
- Run `graphify update .` after code changes (repo rule).
- Backend tests: `cd backend && uv run pytest tests/ -q`. Frontend: `cd frontend && npm run lint && npx tsc -b && npm run build`. Local `frontend/node_modules` is root-owned: fix it once with `sudo rm -rf frontend/node_modules` (Task 13).

## Review Focus

- **Instance started after days stopped.** Caches restored from disk are days old; every layer must serve them marked stale, never 503 or blank. Test: Task 17, `test_restore_from_disk_serves_an_old_cache_marked_stale`.
- **Route starting inside the IMBL band.** Rameswaram sits within 20 km of the India-Sri Lanka line; a route from there must still plan (endpoint edges are exempt from the geofence, grid edges are not). Test: Task 6, `test_route_from_a_port_inside_the_imbl_band_still_plans`.
- **"Tomorrow morning" in the point's own time zone.** The resolved hour must be 06:00 local at the point (Open-Meteo `timezone=auto`), not 06:00 UTC or server time. Test: Task 5, `test_tomorrow_morning_resolves_in_point_local_time`.
- **Open-Meteo wind in a unit other than km/h.** The router must convert (m/s, kn, mph) before applying the 40/62 km/h thresholds. Test: Task 6, `test_wind_in_metres_per_second_is_converted`.
- **Chat streaming through nginx.** SSE must arrive incrementally, not in one block at the end. Test: Task 2 smoke step, first `event:` line within 10 s on `curl -N`.

## Findings coverage

| Finding | Task |
|---|---|
| D1 production fixes only on EC2 | 0, 1, 2, 16 |
| D2 disk 99% full | 14 |
| D3 stray `20` / `nvm` packages | 2 (not ported) |
| D4 emails link to localhost | 2, 15 |
| D5 exposed / unused credentials | 16 |
| D6 X-Forwarded-For bypass, D7 no chat limit | 3 |
| D8 SSH open, HTTP only | 15 (SSH); HTTPS is a non-goal |
| D9 NetCDF lock gaps | 1 |
| D10 local hygiene | 13 |
| L1 2021 HAB grid shown as current | 4 |
| L2 row-based embargo | 9, 10 |
| L3 "tomorrow" answered with now | 5 |
| L4 "low" when unverified | 5 |
| L5, L6, L7 routing | 6 |
| L8 alert repeats, L9 IMD gaps | 8 |
| L10 PFZ distance | 7 |
| L11 grounding laundering | 11 |
| L12 heatwave tracking | 12 |
| L13 doc drift, L14 ML pins, L15 unhandled task | 13 |

## Non-goals

- A live (near-real-time) HAB pipeline. The 2021 grid stays and is labelled as a historical hindcast.
- HTTPS / a domain name. The demo runs on `http://<Elastic IP>/`.
- Frontend bundle splitting, GDACS forecast cones, WDPA protected areas.

## Schedule

| Day | Tasks |
|---|---|
| Mon 20 Oct | 0, 1, 2, 3, 14, 15 |
| Tue 21 Oct | 4, 5, 6, 7, 8 |
| Wed 22 Oct | 9, 10 (retrain runs overnight), 11, 12, 13 |
| Thu 23 Oct | 19, 16, 17, 18 (freeze 18:00) |
| Fri 24 Oct | Start the instance at least 15 min before the demo; run `deploy/demo_ready.sh` |

---

### Task 0: Back up the EC2 state

**Files:** none in the repo. Artefacts go to `~/maris-ec2-backup-2026-10-20/` on the workstation.

- [ ] **Step 1: Snapshot the volume**

Run: `aws ec2 create-snapshot --volume-id vol-006a8e0ab51d0cd14 --description "pre-demo backup 2026-10-20" --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=maris-pre-demo}]'`
Then: `aws ec2 wait snapshot-completed --snapshot-ids <id>`
Expected: state `completed`.

- [ ] **Step 2: Start the instance and save its uncommitted work**

Run `aws ec2 start-instances` and wait as before, then over SSH in `~/maris/MarisAI`:
`git diff > ~/ec2-uncommitted.patch && tar czf ~/ec2-untracked.tgz backend/app/core/netcdf_lock.py frontend/nginx.conf && cp backend/.env ~/backend.env.bak && sudo docker volume ls > ~/volumes.txt && sudo docker inspect marisai-db-1 --format '{{json .Mounts}}' > ~/db-mounts.json`
Copy all five files to the workstation with `scp`.
Expected: the patch is about 2,600 lines, and `db-mounts.json` names the volume whose name starts `2d5b7a79dfe4`.

- [ ] **Step 3: Leave the instance running** for Task 14 on the same day, or stop it if Task 14 waits.

### Task 1: Port the HDF5 lock and close its gaps

**Files:**
- Create: `backend/app/core/netcdf_lock.py` (from the EC2 tarball)
- Modify: the 7 call sites in the EC2 patch (`forecasting/grid_history.py`, `forecasting/grid_predictor.py`, `services/climatology/oisst.py`, `services/climatology/store.py`, `services/forecast_tiles.py`, `services/ocean_heat_content_field.py`, `services/predictions.py`)
- Modify: `backend/routers/forecast_tiles.py` (grid loads off the event loop)
- Test: `backend/tests/test_netcdf_lock.py`

**Interfaces:**
- Produces: `app.core.netcdf_lock.NETCDF_LOCK: threading.RLock`

- [ ] **Step 1: Apply the EC2 hunks for those 7 files only** with `git apply --include=...`, then add `netcdf_lock.py`. Change `threading.Lock()` to `threading.RLock()`, because `_derive_grid_from_components` holds the lock while calling into code that may take it again.

- [ ] **Step 2: Write the failing tests**

```python
def test_nested_acquire_does_not_deadlock():
    with NETCDF_LOCK:
        with NETCDF_LOCK:
            pass

def test_oisst_open_returns_a_loaded_dataset(tmp_path, small_oisst_bytes):
    ds = oisst._open(small_oisst_bytes, tmp_path / "x.nc", START, END)
    assert all(ds[v].variable._in_memory for v in ds.data_vars)
```

Build the fixture `small_oisst_bytes` from a 2x2x3 `xr.Dataset` written with `to_netcdf()`, carrying the `zlev` dimension that `_drop_zlev` expects.

- [ ] **Step 3: Run** `uv run pytest tests/test_netcdf_lock.py -v`. Expected: the second test FAILS (lazy dataset).

- [ ] **Step 4: Make `oisst._open` and `oisst.fetch_recent` call `.load()` inside the lock**, and wrap every route in `routers/forecast_tiles.py` that reaches `forecast_tiles._load_grid` or `_derive_grid_from_components` in `await asyncio.to_thread(...)`.

- [ ] **Step 5: Run** `uv run pytest tests/ -q -k "netcdf or forecast_grid or oisst or climatology or predictions or ocean_heat"`. Expected: PASS.

- [ ] **Step 6: Commit** `git commit -m "Serialize every local NetCDF/HDF5 access behind one re-entrant lock"`

### Task 2: Production compose and nginx frontend

**Files:**
- Create: `docker-compose.prod.yml`, `frontend/Dockerfile.prod`, `frontend/Dockerfile.prod.dockerignore` (a copy of `frontend/Dockerfile.dockerignore`), `frontend/nginx.conf`, `deploy/README.md`, `deploy/env.prod.example`
- Modify: `frontend/src/features/map/styles/map.css` (the EC2 `.map-root .map-container` hunk), `backend/app/core/config.py`
- Leave unchanged: `docker-compose.yml`, `frontend/Dockerfile` (local dev stays as it is)

**Interfaces:**
- Produces: settings `TRUST_FORWARDED_FOR: bool = False`, `PUBLIC_BASE_URL: str | None = None`, `PUBLIC_BASE_URL_FROM_EC2: bool = False`. When `PUBLIC_BASE_URL` is set, it is used as `FRONTEND_BASE_URL` and is the only `CORS_ORIGINS` entry (Pydantic `model_validator`).
- Produces: `app.core.public_url.public_base_url() -> str`: `PUBLIC_BASE_URL` if set; else, when `PUBLIC_BASE_URL_FROM_EC2`, `http://<public-ipv4>` read once from IMDSv2 (token PUT then GET `latest/meta-data/public-ipv4`, 1 s timeouts, cached for the process); else `FRONTEND_BASE_URL`. `watch_alerts._confirm_url`/`_unsubscribe_url` use it.
- Produces: root `.env` keys on EC2: `COMPOSE_FILE=docker-compose.prod.yml`, `MARIS_DB_VOLUME=<name from db-mounts.json>`, `POSTGRES_PASSWORD=<existing>`. The prod compose sets `PUBLIC_BASE_URL_FROM_EC2: "true"`.

- [ ] **Step 1: Write `docker-compose.prod.yml`** from the EC2 compose with these changes:
  - the db volume is `external: true, name: ${MARIS_DB_VOLUME:?set in .env}`;
  - backend `environment` adds `PUBLIC_BASE_URL_FROM_EC2: "true"`, `TRUST_FORWARDED_FOR: "true"`, `FORECAST_GRID_REFRESH_ON_BOOT: "false"` and `COPERNICUS_MAX_CONCURRENT_FETCHES: "2"`;
  - every service gets `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`.
  - Do not port the `"20"` or `"nvm"` dependencies, or the EC2 `package-lock.json` (D3); keep the lockfile from `2f64b5f`.

- [ ] **Step 2: Write `frontend/nginx.conf`** from the EC2 file, but set `proxy_set_header X-Forwarded-For $remote_addr;` (overwrite, never append) and add `add_header Cache-Control "public, max-age=31536000, immutable"` for `/assets/`.

- [ ] **Step 3: Write the failing config test** in `backend/tests/test_security.py`:

```python
def test_public_base_url_drives_email_links_and_cors(monkeypatch):
    s = Settings(PUBLIC_BASE_URL="http://13.0.0.1")
    assert s.FRONTEND_BASE_URL == "http://13.0.0.1"
    assert s.cors_origins == ["http://13.0.0.1"]
```

- [ ] **Step 4: Run it** (FAIL), implement the validator, run again (PASS).

- [ ] **Step 5: Local smoke of the prod stack.** Create a throwaway root `.env` (`MARIS_DB_VOLUME=maris_smoke` after `docker volume create maris_smoke`, `PUBLIC_BASE_URL=http://localhost`), then run `docker compose -f docker-compose.prod.yml up -d --build`.
Expected:
  - `curl -s -o /dev/null -w '%{http_code}' localhost/` is `200`;
  - `curl -s localhost/api/dashboard/health` returns JSON;
  - `curl -s localhost:8000` fails (backend not published);
  - `curl -N -s -X POST localhost/api/v1/chat/stream -H 'content-type: application/json' -d '{"question":"What can you do?"}' | head -c 300` prints an `event:` line within 10 s.

Tear down with `docker compose -f docker-compose.prod.yml down` and `docker volume rm maris_smoke`.

- [ ] **Step 6: Write `deploy/README.md`** (one page): the root `.env` keys, the deploy commands from Task 16, the start-of-demo routine from Task 17, and the rollback (Task 0 snapshot).

- [ ] **Step 7: Commit** `git commit -m "Add a production compose with an nginx frontend and internal backend"`

### Task 3: Rate limits that cannot be spoofed, and a chat limit

**Files:**
- Modify: `backend/services/rate_limit.py:71-86`, `backend/routers/chat.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: `settings.TRUST_FORWARDED_FOR` (Task 2)
- Produces: `client_key(request: Request) -> str` reads the left-most `X-Forwarded-For` only when `settings.TRUST_FORWARDED_FOR`; otherwise it uses `request.client.host`.

- [ ] **Step 1: Failing tests**

```python
def test_forwarded_for_is_ignored_when_untrusted(monkeypatch): ...
    # header "1.2.3.4", client host "10.0.0.9" -> key == "10.0.0.9"
def test_forwarded_for_is_used_when_trusted(monkeypatch): ...
    # TRUST_FORWARDED_FOR=True -> key == "1.2.3.4"
def test_chat_is_rate_limited(client, monkeypatch):
    # 41st POST /api/v1/chat inside 600 s -> 429 with a Retry-After header; stub agent.answer
```

- [ ] **Step 2: Run** and confirm all three FAIL.

- [ ] **Step 3: Implement.** Add `_CHAT_LIMITER = RateLimiter(limit=40, window_seconds=600)` in `routers/chat.py`, shared by `/chat` and `/chat/stream` and enforced before any model call, with the message "Too many questions in a short time. Please wait a few minutes."

- [ ] **Step 4: Run** `uv run pytest tests/test_security.py tests/test_chat.py -q`. Expected: PASS.

- [ ] **Step 5: Commit** `git commit -m "Key rate limits on the real client and limit the chat endpoints"`

### Task 4: Never present the 2021 HAB grid as current

**Files:**
- Modify: `backend/services/predictions.py` (`hab_point`, new helpers), `backend/services/brief.py` (`_bloom_section`), `backend/services/watch_alerts.py` (`_evaluate_one`), `backend/services/chat/tools.py` (`get_bloom_risk` description), `backend/services/chat/agent.py` (`_SYSTEM_PROMPT` rule)
- Test: `backend/tests/test_predictions.py`, `test_brief.py`, `test_watch_alerts.py`

**Interfaces:**
- Produces: `predictions.hab_export_window() -> tuple[date, date]` (first/last exported date) and `predictions.HAB_CURRENT_MAX_AGE_DAYS = 7`.
- Produces: `hab_point(...)` gains `"is_historical": bool` (last exported date older than 7 days before today, UTC) and `"export_window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`.

- [ ] **Step 1: Failing tests**
  - `test_hab_point_marks_an_old_export_historical`: freeze today at 2026-10-24, grid dates in 2021, assert `is_historical is True` and `export_window == {"start": "2021-11-25", "end": "2021-12-24"}`.
  - `test_bloom_section_names_the_export_date_when_historical`: the row labels read `"+3 days (from 2021-12-24)"`, and the note starts with `"HISTORICAL HINDCAST (2021-11-25 to 2021-12-24), not a current forecast."`.
  - `test_historical_bloom_export_never_alerts`: `_evaluate_one` with risk 0.9 and `is_historical=True` returns no `"bloom"` part.

- [ ] **Step 2: Run them** (FAIL), implement, run again (PASS).

- [ ] **Step 3: Prompt and tool copy.** Append to the `get_bloom_risk` description: "Results carry is_historical; when true, say plainly that this is a 2021 hindcast and give its date, never present it as a current forecast."
Add the same rule to `_SYSTEM_PROMPT`.
Then run `uv run pytest tests/test_chat.py -q` (the grounding tests read the prompt).

- [ ] **Step 4: Commit** `git commit -m "Label the exported bloom grid as a historical hindcast everywhere it is shown"`

### Task 5: Risk verdict with a time horizon and an honest "unknown"

**Files:**
- Create: `backend/services/sea_state.py` (shared with Task 6; create it here)
- Modify: `backend/services/marine_risk.py`, `backend/services/openmeteo.py`, `backend/services/severe_weather.py` (`check_point` gains `at`), `backend/services/chat/tools.py` (`assess_marine_risk` args + description), `frontend/src/features/map/api/pointTools.ts:33`, `frontend/src/features/map/styles/map.css` (badge `--unknown`)
- Test: `backend/tests/test_marine_risk.py`, `test_severe_weather.py`

**Interfaces:**
- Produces `services/sea_state.py`: `WAVE_CAUTION_M = 1.5`, `WAVE_HAZARD_M = 2.5`, `WIND_CAUTION_KMH = 40.0`, `WIND_HAZARD_KMH = 62.0`, `HazardLevel = Literal["calm", "caution", "hazardous", "unknown"]`, `def hazard_level(wave_m: float | None, wind_kmh: float | None) -> HazardLevel` (worst of the known inputs; `"unknown"` only when both are None).
- Produces: `openmeteo.get_forecast_ocean_conditions(latitude: float, longitude: float, *, when: When, hours_ahead: int | None = None) -> dict[str, Any]`. Same shape as `get_realtime_ocean_conditions`, with the `current` block taken from the `hourly` arrays at the resolved hour, plus `"valid_time"` (local ISO) and `"timezone"`.
- Produces: `When = Literal["now", "tonight", "tomorrow_morning", "tomorrow_afternoon", "tomorrow_evening"]`. Resolved in the point's local time from Open-Meteo `timezone=auto`: tonight 21:00 today (tomorrow 21:00 if already past), tomorrow_morning 06:00, tomorrow_afternoon 14:00, tomorrow_evening 18:00. `hours_ahead` (1-72) overrides `when`.
- Produces: `marine_risk.assess(latitude, longitude, *, when: When = "now", hours_ahead: int | None = None)`. `RiskLevel` adds `"unknown"`, and the result adds `"valid_time"` and `"verified": bool`.
- Produces: `severe_weather.check_point(latitude, longitude, at: datetime | None = None)`. An alert counts only if it is active at `at` (default now).

- [ ] **Step 1: Failing tests** (mock the three upstreams, as the existing tests do):
  - `test_all_live_checks_failing_reads_unknown_not_low`: all three raise; `risk_level == "unknown"`, `verified is False`, and `len(could_not_verify) == 3`.
  - `test_missing_wave_and_wind_is_recorded_as_unverified`: conditions return None for both; `risk_level == "unknown"`, and `could_not_verify` contains `"wave height and wind speed were not reported"`.
  - `test_a_real_hazard_still_wins_over_a_failed_check`: the cyclone is inside the radius and conditions fail; `risk_level == "extreme"`.
  - `test_tomorrow_morning_uses_the_forecast_hour`: the hourly payload has 3.0 m at 06:00 local tomorrow; `risk_level == "high"` and `valid_time` ends with `"T06:00"`.
  - `test_tomorrow_morning_resolves_in_point_local_time`: payload `timezone == "Asia/Kolkata"`, now = 2026-10-24T01:00Z; the resolved hour is 2026-10-25T06:00 (+05:30).
  - `test_imd_alert_expiring_before_target_is_ignored` (in test_severe_weather.py).

- [ ] **Step 2: Run them** (FAIL).

- [ ] **Step 3: Implement.**
  - Escalation starts from `"low"` as now.
  - After all checks, if the conditions check failed or reported neither wave nor wind, and the level is still `"low"`, set `"unknown"`.
  - The rank table puts `"unknown"` at the same rank as `"low"` for escalation purposes.
  - The `note` says "unknown means the sea state could not be verified, not that it is calm".
  - Cyclones keep the last fix and the note says so for future times.

- [ ] **Step 4: Tool args and copy.** Add a `MarineRiskArgs(PointArgs)` model with `when` and `hours_ahead`. Set the description's first sentence to: "Deterministic 'is it safe to go out' verdict for a coordinate, now or at a future time (pass when='tomorrow_morning' for 'tomorrow morning')."

- [ ] **Step 5: Frontend.** Add `'unknown'` to the `risk_level` union, and add a `.selected-location-panel__risk-badge--unknown` rule using the existing neutral grey token. Run `npm run lint && npx tsc -b`.

- [ ] **Step 6: Run** `uv run pytest tests/test_marine_risk.py tests/test_severe_weather.py tests/test_chat.py -q`. Expected: PASS.

- [ ] **Step 7: Commit** `git commit -m "Give the risk verdict a time horizon and report unverified sea state as unknown"`

### Task 6: Routing: pessimistic unknowns, wind, and edge geofencing

**Files:**
- Modify: `backend/services/routing.py` (`_edge_cost`, `_hazard_level`, adjacency loop, response), `backend/services/geofencing.py` (new function), `backend/services/marine_risk.py` (import thresholds from `sea_state`)
- Test: `backend/tests/test_routing.py`, `backend/tests/test_geofencing.py`

**Interfaces:**
- Consumes: `services/sea_state.py` (Task 5).
- Produces: `geofencing.segment_restricted(a: tuple[float, float], b: tuple[float, float]) -> bool`, where points are (lat, lon). True when the segment intersects any `PROTECTED_AREAS` polygon, or when its haversine distance to `IMBL_INDIA_SRI_LANKA` is at most `PROXIMITY_THRESHOLD_KM`. Distance comes from the `shapely.ops.nearest_points` pair, then `_haversine_km`.
- Produces: `_edge_cost(a, b) = distance_km * (1 + wave_term + wind_term)`. `wave_term` = mean known wave in metres, or `WAVE_HAZARD_M` if both are unknown. `wind_term` = mean known wind km/h / `WIND_HAZARD_KMH`, or `1.0` if both are unknown. The factor stays >= 1, so the A* heuristic stays admissible.
- Produces: `_Hazard.wind_speed` is always km/h. Convert from `current_units` (`m/s` ×3.6, `kn` ×1.852, `mp/h` ×1.609344), and keep the original unit in the waypoint as `wind_speed_unit: "km/h"`.
- Produces: the response's `hazard_level` = `sea_state.hazard_level` worst over path nodes; if the worst known is `"calm"` and any node is unknown, `"unknown"`. Adds `"unknown_hazard_nodes": int` and `"max_wind_speed_kmh": float | None`.

- [ ] **Step 1: Failing tests**
  - `test_unknown_hazard_costs_more_than_calm`
  - `test_wind_gale_marks_route_hazardous` (waves 0.5 m, wind 70 km/h)
  - `test_wind_in_metres_per_second_is_converted` (20 m/s becomes 72 km/h)
  - `test_route_never_crosses_a_small_mpa_between_nodes` (monkeypatch `PROTECTED_AREAS` to one 0.05° box exactly between two grid nodes and stub an all-water depth grid; assert no consecutive path pair has `segment_restricted` True, ignoring the start/end edges)
  - `test_route_from_a_port_inside_the_imbl_band_still_plans` (start 9.288N 79.313E)
  - `test_segment_crossing_imbl_is_restricted` (in test_geofencing.py)

- [ ] **Step 2: Run them** (FAIL), implement, run (PASS).

- [ ] **Step 3: Apply `segment_restricted` to grid-to-grid edges only**; `_connect_endpoint` edges stay exempt (the user's own endpoints are trusted, as today). Update the module docstring sentence that claims structural exclusion so it describes node and edge checks.

- [ ] **Step 4: Run** `uv run pytest tests/test_routing.py tests/test_geofencing.py tests/test_marine_risk.py -q`. Expected: PASS.

- [ ] **Step 5: Commit** `git commit -m "Route around unknown water, wind and excluded zones between grid nodes"`

### Task 7: PFZ "nearest" means nearest

**Files:** Modify `backend/services/pfz.py`; test `backend/tests/test_pfz.py`.

**Interfaces:**
- Produces: each zone gains `"distance_km": float` (haversine from the query point, 1 decimal). Sorting is `(-score, distance_km)`. The response gains `"nearest_full_match"`: the nearest zone with `score == 2`, or `None`.

- [ ] **Step 1: Failing tests** `test_each_zone_reports_its_distance`, `test_zones_rank_nearer_first_within_a_score`, and `test_nearest_full_match_is_none_when_no_cell_scores_two`.
- [ ] **Step 2: Run** (FAIL), implement, run (PASS).
- [ ] **Step 3: Commit** `git commit -m "Rank fishing-zone candidates by distance within a score"`

### Task 8: IMD feed coverage and alert-email de-duplication

**Files:**
- Modify: `backend/services/severe_weather.py`, `backend/services/marine_risk.py` (`_assess_severe_weather`), `backend/services/watch_alerts.py`
- Test: `backend/tests/test_severe_weather.py`, `backend/tests/test_watch_alerts.py`

**Interfaces:**
- Produces: `severe_weather` reads every RSS item (hard cap 200), fetched with `asyncio.Semaphore(8)`.
  - An alert without `expires` is active until `onset` (or `sent`) + 24 h.
  - Naive timestamps are read as IST (+05:30).
  - `check_point` and `get_active_alerts` gain `"fetch_failures": int` and `"unlocated": list[summary]`, the active alerts with no polygon or circle.
- Produces: `watch_alerts._next_signature(previous: set[str], current: set[str], failed_kinds: set[str]) -> tuple[set[str], set[str]]` returns `(to_store, newly_appeared)`. Parts whose kind (`severe`, `cyclone`, `bloom`, the prefix before `:`) failed this run are carried over from `previous`; email only `newly_appeared`. `_evaluate_one` returns `(parts, reasons_by_part, failed_kinds)`.
- marine_risk: `fetch_failures > 0` or a non-empty `unlocated` list adds a `could_not_verify` line naming the count.

- [ ] **Step 1: Failing tests**
  - `test_alert_without_expires_is_active_for_24h_from_onset`
  - `test_naive_timestamps_are_read_as_ist`
  - `test_alert_without_geometry_is_reported_unlocated`
  - `test_partial_fetch_failure_is_counted`
  - `test_more_than_twenty_items_are_all_read`
  - `test_failed_feed_keeps_previous_parts`
  - `test_shrinking_alert_set_sends_nothing`
  - `test_new_part_is_emailed`

The three `_next_signature` tests are pure and need no DB.

- [ ] **Step 2: Run** (FAIL), implement, run (PASS).
- [ ] **Step 3: Commit** `git commit -m "Read the whole IMD feed and stop re-sending alerts after a feed outage"`

### Task 9: Date-based embargo in forecast validation

**Files:** Modify `backend/forecasting/evaluator.py:58-131`; test `backend/tests/test_forecasting.py`.

**Interfaces:**
- Produces: `rolling_origin_splits(...)` and `chronological_split(...)` keep their signatures and return row indices. Cutoffs, test windows and the gap are counted in **unique timestamps** (days at daily resolution), not rows.
  - Fold k: `test = rows whose date is in [D[c_k], D[c_{k+1}])`.
  - `train = rows whose date is < D[c_k - gap]`, where `D` is the sorted unique dates.
  - The "too short" error counts unique dates.

- [ ] **Step 1: Failing tests**
  - `test_pooled_frame_embargo_spans_whole_dates`: 24 points × 200 days, horizon 7. For every fold, `min(test dates) - max(train dates) >= 8 days`.
  - `test_no_date_straddles_train_and_test`
  - `test_chronological_split_is_date_based_on_a_pooled_frame`
- [ ] **Step 2: Run** (FAIL), implement, run the whole `tests/test_forecasting.py` (existing single-series tests must still PASS unchanged).
- [ ] **Step 3: Commit** `git commit -m "Count the validation embargo in dates, not rows, on pooled frames"`

### Task 10: Revalidate and retrain the shipped forecasting models

**Files:** `backend/models/forecasting/**` (Git LFS), `backend/models/forecasting/_reports/`.

- [ ] **Step 1: Record the baseline** with `uv run python scripts/apply_shipping_bar.py --dry-run > /tmp/bar-before.txt` (on the workstation, after `git lfs pull`).
- [ ] **Step 2: Retrain overnight 22 Oct** with `uv run python scripts/train_forecasting.py --all 2>&1 | tee /tmp/train.log`, then `uv run python scripts/apply_shipping_bar.py`.
- [ ] **Step 3: Rebuild forecast grids** for the shipped variables with `uv run python scripts/build_forecast_grid.py` (see its `--help`), so the demo forecast layers match the new models.
- [ ] **Step 4: Diff** `bar-before.txt` against the new report and list every horizon that newly failed. Those forecast layers will no longer appear, and that is the honest result.
- [ ] **Step 5: Decision rule.** If training has not finished by **Thu 23 Oct 12:00 IST**, do not ship partial artefacts. Keep the current ones, and add one line to the model dossier note: "validated under a row-based embargo; revalidation pending (finding L2)".
- [ ] **Step 6: Commit** `git commit -m "Retrain forecasting models under the date-based embargo"`

### Task 11: Grounding check cannot be laundered through history

**Files:** Modify `backend/services/chat/store.py` (`history`), `backend/services/chat/agent.py` (`answer`, `answer_stream`); test `backend/tests/test_chat.py`.

**Interfaces:**
- Produces: `store.history(...)` assistant entries gain `"unsupported_numbers": list[str]` (from the existing column; `[]` when null).
- Produces: `agent._permitted_history_text(prior: list[dict], *, trusted: bool) -> str`. User turns are included in full. Assistant turns are included only when `trusted` (they come from the DB), with each of their own `unsupported_numbers` tokens removed. Client-supplied history (`trusted=False`) contributes user turns only.

- [ ] **Step 1: Failing tests** `test_number_flagged_in_an_earlier_turn_is_still_flagged_when_repeated` and `test_client_supplied_assistant_history_does_not_whitelist_numbers` (ScriptedModel harness, as the existing tests use).
- [ ] **Step 2: Run** (FAIL), implement in both `answer` and `answer_stream`, then run the whole `tests/test_chat.py` (PASS).
- [ ] **Step 3: Commit** `git commit -m "Stop earlier unverified answers from whitelisting numbers"`

### Task 12: Heatwave tracking to the Hobday definition, persisted

**Files:** Modify `backend/services/heatwave_tracking.py`, `backend/services/heatwaves.py` (restore on boot); test `backend/tests/test_heatwave_tracking.py`.

**Interfaces:**
- Produces: the per-cell state adds `gap_days: int16`.
  - A day above p90 extends the run.
  - A day not above p90 (including a missing calendar day or NaN) increments `gap_days` while the run has qualified (≥5 days).
  - Up to 2 gap days keep the event open, and the next above-threshold day resumes it with the same onset.
  - A third gap day, or any gap before qualifying, closes the run.
  - Days are walked by calendar date (`epoch_day`), not array index, so a missing date counts as a gap day.
- Produces: `heatwave_tracking.save_state() -> bool` and `heatwave_tracking.restore_state() -> bool`, via `disk_cache.save`/`load` key `"heatwave_tracking"`. Called after each `advance()` and once at boot before the first refresh.

- [ ] **Step 1: Failing tests** `test_two_day_gap_joins_one_event`, `test_three_day_gap_splits_events`, `test_missing_calendar_day_counts_as_a_gap` and `test_state_survives_a_restart`.
- [ ] **Step 2: Run** (FAIL), implement, run the whole `tests/test_heatwave_tracking.py tests/test_heatwaves.py` (PASS).
- [ ] **Step 3: Commit** `git commit -m "Join heatwave events across short gaps and persist tracked state"`

### Task 13: Hygiene

**Files:**
- Modify: `backend/services/dashboard/history.py:105-111`, `backend/tests/conftest.py`, `machine_learning/requirements.txt`, `docs/features/ocean-assistant.md`

- [ ] **Step 1: `_persist` catches `Exception`** (with the existing log message), so a refused connection is logged, not leaked as "Task exception was never retrieved".
- [ ] **Step 2: DB tests skip when the DB is unreachable.** Add a session fixture `database_reachable` in `conftest.py` that opens one connection with a 2 s timeout. `test_chat_store.py`, `test_dashboard_history_db.py` and the DB tests in `test_watch_alerts.py` skip with "DATABASE_URL set but Postgres unreachable".
Run: `uv run pytest tests/ -q` with Postgres stopped. Expected: 0 failed.
- [ ] **Step 3: Pin `sqlalchemy>=2.0,<2.1`** in `machine_learning/requirements.txt`, then recreate the venv and run `.venv/bin/pytest -q`. Expected: 0 failed.
- [ ] **Step 4: Docs.** "three specialists" becomes four (add `external_research`: web_search, fetch_webpage, search_scientific_literature). Then run `graphify update .`.
- [ ] **Step 5: Local workstation.** Run `sudo rm -rf frontend/node_modules && (cd frontend && npm ci)` and `git fetch --prune`. Not committed.
- [ ] **Step 6: Commit** `git commit -m "Fix test skips, ML pins, KPI persistence logging and assistant docs"`

### Task 14: Disk: grow, clean, rotate

**Files:** none in the repo (instance only). Requires Task 0.

- [ ] **Step 1: Grow the volume to 30 GB**

Run: `aws ec2 modify-volume --volume-id vol-006a8e0ab51d0cd14 --size 30`, then poll `aws ec2 describe-volumes-modifications --volume-ids vol-006a8e0ab51d0cd14` until `optimizing` or `completed`.
On the instance: `sudo growpart /dev/nvme0n1 1 && sudo xfs_growfs -d /`.
Expected: `df -h /` shows about 30G.

- [ ] **Step 2: Clean**

```bash
sudo docker rm my-postgres stupefied_keller beautiful_mayer reverent_kalam   # exited containers only; volumes stay
sudo docker builder prune -af
sudo docker image prune -f
rm -rf ~/.cache/pip ~/.cache/uv ~/.npm
sudo journalctl --vacuum-size=200M
```

First confirm against `db-mounts.json` that `marisai-db-1` mounts the `2d5b7a79...` volume; removing `my-postgres` does not delete it.
Expected: `df -h /` shows at least 18 GB free.

- [ ] **Step 3: Log rotation for any container** without compose settings. Write `/etc/docker/daemon.json` as `{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}`, then run `sudo systemctl restart docker && systemctl is-enabled docker`. Expected: `enabled`, and the stack is back up and healthy within 90 s.

### Task 15: Stable address and network hygiene

- [ ] **Step 1: No Elastic IP (user's choice). Let containers reach IMDS and give the user one start command**

Run: `aws ec2 modify-instance-metadata-options --instance-id i-0c7686f701d6b0af1 --http-tokens required --http-put-response-hop-limit 2` (a bridge-networked container is one extra hop).
Create `deploy/start_demo.sh`: `aws ec2 start-instances`, wait for `instance-running`, read `PublicIpAddress`, authorize SSH for the caller's current IPv4 (Step 2), print `http://<ip>/`, then run `deploy/demo_ready.sh http://<ip>`.
Also create `deploy/stop_demo.sh` (stop and wait).

- [ ] **Step 2: Restrict SSH to the workstation.** Revoke `22 0.0.0.0/0` and authorize `22 <workstation IPv4>/32` (the address is dynamic, so `deploy/start_demo.sh` re-authorizes the current one each run). Keep 80 open. Remove 443, since nothing listens on it.

### Task 16: Deploy GitHub `main` to the instance

Requires Tasks 0-15 merged to `main` and pushed (ask before pushing).

- [ ] **Step 1: On EC2 in `~/maris/MarisAI`:**

```bash
git fetch origin && git status --short          # must match the Task 0 patch list
git reset --hard origin/main && git clean -fd -e .env -e backend/.env
git lfs pull
```

- [ ] **Step 2: Root `.env`** with the keys from Task 2 (copy `deploy/env.prod.example`; `MARIS_DB_VOLUME` from `db-mounts.json`; `POSTGRES_PASSWORD` unchanged).

- [ ] **Step 3: `backend/.env`.** Remove the `MONGODB_*`, `GOOGLE_CLIENT_*` and `SESSION_SECRET` lines (unused since auth removal).
**Ask the user** whether the MongoDB Atlas password flagged in the comment was rotated; if not, they rotate it in Atlas. Nothing else changes.

- [ ] **Step 4: Build and start**

```bash
sudo docker compose build --pull && sudo docker compose up -d
sudo docker compose ps          # all healthy
sudo docker image prune -f && sudo docker builder prune -af
```

- [ ] **Step 5: Verify version parity** with `git rev-parse HEAD` on EC2 against `git ls-remote origin main`. Expected: identical, and `git status --short` is empty.

### Task 17: Boot-to-ready and the readiness script

**Files:**
- Create: `deploy/demo_ready.sh`
- Test: `backend/tests/test_copernicus_sst.py`

- [ ] **Step 1: Failing test** `test_restore_from_disk_serves_an_old_cache_marked_stale`: a cache with `fetched_at` 6 days old restores, `is_available()` is True, and `is_stale()` is True. Then repeat the assertion for wind and currents (`tests/test_copernicus_wind.py`, `tests/test_vector_source.py`).
- [ ] **Step 2: Run.** If it passes already, keep it as a guard. If it fails, make restore accept any age (staleness is reported, never a reason to drop the copy). Then commit.

- [ ] **Step 3: Write `deploy/demo_ready.sh BASE_URL [--ask]`.** Poll every 10 s, for at most 15 min:
  - `GET /` must return 200;
  - `GET /api/dashboard/health` must return 200;
  - `GET /api/ocean/{sst,wind,currents,stokes,drift}/meta` must be available, with its timestamp printed;
  - `GET /api/ocean/eddies` and `GET /api/ocean/heatwaves` must return 200;
  - with `--ask`, one `POST /api/v1/chat` "What can you do?" must return an answer.

Print a table (surface, status, data time, age), and exit 0 only when every row is green.
Run it from the workstation: `deploy/demo_ready.sh http://<public IP> --ask`.

- [ ] **Step 4: Cold-start rehearsal.** Run `aws ec2 stop-instances`, wait, then `start-instances` and run `deploy/demo_ready.sh` immediately.
Record two times in `deploy/README.md`: start until `/` is 200 (target ≤ 2 min), and start until all green (target ≤ 10 min).
If the second exceeds 10 min, record which surface is slowest.

- [ ] **Step 5: Commit** `git commit -m "Add a demo readiness check and guard stale-cache restore"`

### Task 18: End-to-end rehearsal (Thu 23 Oct, before 18:00)

**Files:** `deploy/demo-script.md` (create).

- [ ] **Step 1: Write the demo script**, five questions, and run each through the UI in a real browser (`chrome-devtools-axi`) at `http://<public IP>/assistant`:
  1. "Is it safe to go out near Rameswaram tomorrow morning?" (expect a `valid_time` at 06:00 local tomorrow and a moderate-or-higher boundary note)
  2. The same question in Tamil
  3. "Where is the nearest potential fishing zone to Kochi today?" (expect distances)
  4. "Plan a safe route from Kochi to Kollam" (expect a route on the map, with wind in km/h)
  5. "What is the harmful algal bloom risk off Mumbai?" (expect "2021 hindcast" wording)
- [ ] **Step 2: Walk** `/map` (SST, currents particles, eddies, heatwaves, forecast layer), `/dashboard`, one metric page, a point brief PDF and a small `/download` CSV. Screenshot each, and fix anything that looks off before the freeze.
- [ ] **Step 3: Check the grounding badge** on every answer. Any "not fully traced" banner on a correct answer is a bug to fix before the freeze.
- [ ] **Step 4: Leave the instance stopped** after the rehearsal. Its disk caches are now from 23 Oct, so on 24 Oct the first screen serves day-old data marked stale while it refreshes.
- [ ] **Step 5: Demo day.** Start the instance at least 15 min before the demo, run `deploy/demo_ready.sh http://<public IP> --ask`, and open the five screens. If anything is red, roll back to the Task 0 snapshot only as a last resort (`deploy/README.md`).

### Task 19: Make the site smoother (measured)

Added at the user's request ("make the whole site smoother"). Measure first, fix the biggest costs, re-measure.

**Files:** decided by the measurement; expected candidates: `frontend/vite.config.ts` (chunking), `frontend/src/App.tsx` / route modules (lazy routes), `frontend/nginx.conf` (caching), `backend/routers/tiles.py` / `backend/routers/forecast_tiles.py` (tile `Cache-Control`, rendered-PNG LRU).

- [ ] **Step 1: Baseline.** On the local prod stack (Task 2 smoke), record with `chrome-devtools-axi` a performance trace for `/`, `/map`, `/dashboard` and `/assistant`: LCP, total JS transferred, long tasks, and map tile response times (p50/p95 from the network log). Save the numbers to `deploy/perf.md`.
- [ ] **Step 2: Fix the top items the trace shows**, each as its own commit with the before/after number in the message. Defaults if the trace agrees: route-level `React.lazy` so `/map` and `/assistant` code is not in the landing bundle; keep the 939 kB `esri` chunk out of first load; `Cache-Control: public, max-age=300` on data tiles keyed by timestep; a bounded LRU (256 entries) of rendered tile PNGs per layer/timestep.
- [ ] **Step 3: Re-measure** with the same four traces and append to `deploy/perf.md`. Expected: every page's LCP and first-load JS no worse, and the landing and map first-load JS lower than the baseline.
- [ ] **Step 4: Frontend checks** `npm run lint && npx tsc -b && npm run build`, and backend tests for any touched router. Commit.
