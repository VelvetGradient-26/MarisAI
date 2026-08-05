# Authentication removal

Sign-in was removed from MarisAI. Nothing was rewritten to work around its
absence and no code was rewritten from scratch — every file below still exists
in git history and can be restored verbatim.

**Restore point: `8fd1b89`** (`8fd1b8982e492a51962ae468dfe213a275cf41ec`) — the
last commit in which the full authenticated stack was present and working.

## What was removed

### Removed entirely

Sign-in (Google OAuth + signed session cookie), the MongoDB user store, and
the two features that existed only for signed-in users.

| File | What it was |
|---|---|
| `backend/routers/auth.py` | `/api/v1/auth/*` — login redirect, OAuth callback, `/me`, logout |
| `backend/services/auth.py` | Session token issue/verify, Google token exchange, user upsert |
| `backend/dependencies/auth.py` | `current_user` FastAPI dependency |
| `backend/app/database/mongo.py` | Mongo client, `USERS` / `SAVED_LOCATIONS` / `DOWNLOAD_HISTORY` collections, index setup |
| `backend/routers/saved_locations.py` | `/api/v1/saved-locations` CRUD |
| `backend/services/saved_locations.py` | Saved-location persistence |
| `backend/services/download_history.py` | Per-user download audit trail |
| `backend/tests/test_auth.py` | Auth unit tests |
| `frontend/src/store/authStore.ts` | Zustand auth store (`status`, `user`, `fetchMe`, `logout`) |
| `frontend/src/features/map/api/auth.ts` | `loginUrl()` and the `/auth/me` client |
| `frontend/src/features/map/api/savedLocations.ts` | Saved-location client |
| `frontend/src/pages/AccountPage.tsx` | Account page (saved locations + download history tabs) |
| `frontend/src/pages/account.css` | Its stylesheet |
| `backend/dependencies/` | Package became empty once `auth.py` went |

### Kept, with the gate removed

These were sign-in gated but are useful without accounts, so they stay open.
**Sign-in was their only abuse control**, so each gained or tightened a limiter
— per-IP, and therefore weaker than a user id, which a caller cannot rotate by
switching networks.

| Endpoint | Before | Now |
|---|---|---|
| `POST /api/v1/download` | Sign-in required, no limiter | Open · **10/hour per IP** (new) |
| `POST /api/insights/generate` | Sign-in required · 10/min keyed on user id | Open · **5/min per IP** (halved) |

`GET /api/v1/download-history` went with the audit trail — a per-user record
has no meaning without users.

## Also changed

- **`backend/main.py`** — dropped the auth and saved-locations routers, the
  Mongo lifespan hooks (`ensure_indexes` / `close_mongo`) and the
  `MongoUnavailableError` → 503 handler. `allow_credentials=True` is
  deliberately still on the CORS middleware; see the comment there.
- **`backend/app/core/config.py`** — removed `MONGODB_URI`, `MONGODB_DB_NAME`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`,
  `SESSION_SECRET`, `COOKIE_SECURE` and the `cookie_secure` property. These
  must come back with the modules.
- **`backend/pyproject.toml`** — dropped `pymongo` and `authlib`; removed
  `dependencies*` from the packaging `include` list.
- **`backend/tests/test_security.py`** — dropped `TestCookieSecurity` and
  `TestSessionSecret` (12 tests total across this and `test_auth.py`).
- **Frontend** — `providers.tsx` lost `AuthBootstrap`; `App.tsx` lost the
  `/account` route; `Navbar.tsx` lost the account control; `DownloadPage`,
  `DashboardPage` and `AiInsights` lost their sign-in branches;
  `SelectedLocationPanel` lost its save button; `navbar.css` lost the account
  and sign-in rules.

### Unrelated change made at the same time

The **GitHub "view source" link was removed from the navbar** at the user's
request. This is cosmetic and independent of authentication — it hides the
entry point but does **not** make the repository private. If the repo is public
on GitHub it remains publicly discoverable; that is a repository visibility
setting, not a frontend one.

## Restoring

```bash
# 1. Bring back every removed file, exactly as it was.
git checkout 8fd1b89 -- \
  backend/routers/auth.py \
  backend/services/auth.py \
  backend/dependencies/ \
  backend/app/database/mongo.py \
  backend/routers/saved_locations.py \
  backend/services/saved_locations.py \
  backend/services/download_history.py \
  backend/tests/test_auth.py \
  frontend/src/store/authStore.ts \
  frontend/src/features/map/api/auth.ts \
  frontend/src/features/map/api/savedLocations.ts \
  frontend/src/pages/AccountPage.tsx \
  frontend/src/pages/account.css

# 2. Restore the dependencies.
cd backend && uv add "pymongo>=4.9" "authlib>=1.3"
```

Then re-wire by hand — these files changed after the restore point, so
checking them out wholesale would revert unrelated work:

3. `backend/main.py` — import and `include_router` the auth and
   saved-locations routers; restore the `ensure_indexes` / `close_mongo`
   lifespan calls and the `MongoUnavailableError` handler.
4. `backend/app/core/config.py` — restore the seven settings listed above and
   the `cookie_secure` property.
5. `backend/pyproject.toml` — put `dependencies*` back in the packaging
   `include` list, or every guarded router dies at import with
   `No module named 'dependencies'`.
6. `backend/routers/download.py` and `backend/routers/insights.py` — restore
   the `current_user` dependency; decide whether to keep the new rate limiters
   alongside it (recommended — they are cheap and defend a different axis).
7. Frontend — restore `AuthBootstrap` in `providers.tsx`, the `/account` route
   in `App.tsx`, `AccountControl` in `Navbar.tsx` plus its CSS, and the
   sign-in branches in `DownloadPage`, `DashboardPage`, `AiInsights` and
   `SelectedLocationPanel`.
8. Restore the `.env` keys: `MONGODB_URI`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`.

Diff any single file against the restore point with:

```bash
git diff 8fd1b89 -- backend/main.py
```
