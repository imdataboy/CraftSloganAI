# P0 security implementation handoff

This is the historical P0 handoff. The subsequent cleanup is documented in [CLEANUP.md](CLEANUP.md); use the current README for installation and dependency instructions.

Implementation date: 2026-10-13. Scope: the three requested P0 issues, retaining Flask, SQLAlchemy/PostgreSQL, the existing five CrewAI agents and YAML tasks, and the HTML/JavaScript frontend. No live provider calls or publishing were performed. No application database was migrated during this work.

## P0.1 — Credentials and configuration

Hardcoded database credentials, JWT signing material, provider keys, OAuth client secrets, and shared token-file loading were replaced with centralized environment configuration. Provider credentials are checked on use; missing core variables stop startup with errors naming variables, never their values. `.env.example` contains placeholders. OAuth credentials are stored per user and provider, encrypted with Fernet using a separate environment key. Provider response bodies and exception details are not returned by publishing errors. The development access logger omits query strings so OAuth authorization codes and states are not recorded.

Four credential/token JSON files were removed. `.gitignore` excludes local environments, secret/token JSON files, keys, generated images, local databases and caches while allowing explicit safe example files. The existing local `.env` was retained and restricted to mode 0600; its values were not rotated. Existing compiled Python caches were removed during cleanup. Deletion and ignore rules do not revoke credentials or remove them from past copies or Git history.

### Required manual rotation

| Material | Required action |
| --- | --- |
| Groq API key from the local environment | Revoke/replace it in Groq, update the local environment, review usage. |
| Hugging Face key formerly embedded in the crew | Revoke/replace it, update `HUGGINGFACE_API_KEY`, review usage. |
| Gemini API key formerly embedded in browser JavaScript | Revoke/replace it in the Google project, update `GEMINI_API_KEY`, review quota/billing and restrictions. The replacement stays on the backend. |
| Google OAuth client secrets and access/refresh tokens from credential JSON | Rotate the affected client secret(s), revoke old user grants/tokens, update `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, reconnect each user. Check both former Google client configurations. |
| LinkedIn client secret and access token | Rotate the client secret, revoke the old token/grant, update the environment and reconnect each user. |
| PostgreSQL username/password from source/configuration | Rotate the database role password and update `DATABASE_URL`/Compose variables. Existing database volumes do not change passwords just because Compose environment variables change; change the role in PostgreSQL without deleting data. |
| Old JWT signing secret | Replace with independent, strong random signing material. All users must log in again; the new issuer/audience/subject checks also invalidate old tokens. |
| New `TOKEN_ENCRYPTION_KEY` | Generate locally using a secret manager or `Fernet.generate_key()`; this patch does not supply a real key. Store it securely and back it up separately from the database. Replacing it without a re-encryption procedure makes existing tokens unreadable; users must reconnect. |
| Imgur client identifier in local configuration | Review the app and usage. A client identifier alone is not a private client secret; rotate any associated private credentials if they were shared. The optional unused uploader is not part of the protected publishing path. |

Also review copies, backups, shell history, shared archives and past logs for these credential categories. Do not paste credential values into issues, screenshots, logs or a pull request. Ensure `.env.example` and other allowed examples stay placeholders only.

### Git/history limitation

This folder's `.git` directory is empty and read-only. Historical exposure cannot be verified here. Per your instruction, no branch, commit, history rewrite, remote change or pull request was attempted after the clarification. Treat credentials formerly present in the project as potentially exposed. In your actual Git checkout, scan all refs/history with a secret scanner configured to redact findings; review tracked ignored files before synchronizing. Rotate first, then decide separately whether reviewed history cleanup is needed. `.gitignore` does not untrack previously committed files.

## P0.2 — Authentication, ownership and isolation

All operational endpoints require a valid HS256 JWT with issuer, audience, expiration and an existing user subject. Signup and login remain public; OAuth callbacks validate state instead of requiring a JWT because providers cannot supply the user's Bearer header. The informational root and CORS preflights are public and perform no protected operations.

Post review, approval, rejection, scheduling, deletion, publishing, generation, OAuth initiation/status, image retrieval and CraftBot calls are authenticated. New emails, slogans, images, posts and OAuth credentials belong to the authenticated user. Queries and modifications enforce that owner; persistence helpers also reject foreign related records. Existing records with `NULL` ownership remain inaccessible, including to the scheduler. No owner is guessed or assigned automatically.

LinkedIn and Google authorization use cryptographically random, hashed, provider-specific state plus a separate HttpOnly SameSite=Lax browser nonce. State expires after ten minutes and is consumed atomically once, including on denied authorization. Credentials are saved to the initiating user, regardless of which user is currently logged in at callback time. HTTPS backend configuration enables Secure cookies.

CORS accepts only configured complete origins and rejects other supplied origins. CORS is not used as an authentication mechanism: clients without an Origin still need JWTs. The development API binds only to loopback with debug/reloader disabled. Successful OAuth callbacks redirect to the trusted frontend URL; responses forbid caching and referrer forwarding.

Images must be owned, registered application-generated PNGs with a UUID basename, private per-user directory, matching stored SHA-256 digest, valid PNG data, and a 10 MB size cap. Traversal, absolute paths, symlinks, foreign images, changed files and unregistered legacy images are refused. Approval checks the image, and publication validates it again and passes bytes to LinkedIn. No publishing endpoint accepts a filesystem path or arbitrary raw post text. New generated files use mode 0600. Keep the image directory writable only by the application OS account.

Frontend calls attach Bearer tokens only to the configured API origin. Images are retrieved through authenticated requests. Provider secrets were removed from browser code; CraftBot uses the authenticated backend proxy. Post text and saved chat messages render as text to prevent stored script injection. Chat history is separated by user and cleared on sign-out; the old unsafe HTML history is intentionally discarded.

## P0.3 — Confirmed LinkedIn publishing

Every LinkedIn HTTP call has connect/read timeouts (5/30 seconds), disallows redirects, validates its expected response status and raises structured failures. Tokens are checked for expiry; image-upload destinations are restricted to HTTPS LinkedIn hosts. Publication requires HTTP 201 plus a provider post identifier from the response header or JSON. This follows LinkedIn's [documented creation response](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin).

The API and scheduler share one publishing service. It commits an atomic `Publishing` claim before any provider request. Concurrent approval requests, duplicate clicks and retries cannot claim the same post again. Only a confirmed response records `Published` and the LinkedIn identifier. Failed requests remain explicitly unpublished; frontend alerts follow the actual HTTP result.

| State | Meaning and recovery |
| --- | --- |
| `Draft` + review `Pending` | Awaiting owner review. |
| `Scheduled` + review `Approved` | Calendar creation confirmed; scheduler may claim when due. |
| `Publishing` | An attempt was claimed. A crash can leave this state behind; do not blindly reset it. |
| `Published` | LinkedIn creation confirmed with an identifier. |
| `Failed` | Definite publishing/preparation failure; no automatic retry. Fix credentials or inputs and reconcile before an administrator explicitly permits a new attempt. |
| `PublicationUnknown` | Timeout, connection loss, malformed confirmation, server error or unexpected error may hide a remote success. Inspect the LinkedIn account/provider evidence before any retry. |
| `Scheduling` / `ScheduleUnknown` | Calendar creation was claimed or its outcome is uncertain. Reconcile Calendar before resetting. |
| `Cancelling` | Cancellation claimed; failed Calendar deletion leaves this state to block publication until reconciled. |

This provides durable duplicate-attempt protection, not a distributed exactly-once guarantee. A remote success followed by a lost response or failed database commit requires manual reconciliation. There is deliberately no public endpoint that blindly resets attempted posts. Scheduled outcomes are stored accurately, but there is no new failure-monitoring dashboard in this P0 scope.

## Migration and compatibility

1. Stop all old backend/scheduler instances. Back up the database and verify that the backup can be restored. Protect backups as sensitive data.
2. Configure the new environment variables; revoke old credentials and reconnect accounts after migration.
3. For an **empty** database, run `PYTHONPATH=src .venv-p0/bin/python -m slogancraftai.initialize_db`. It creates the current schema and stamps Alembic head. It refuses nonempty databases.
4. For an **existing** database, run `PYTHONPATH=src .venv-p0/bin/alembic current` and inspect its schema first. The expected predecessor revision is `3d33747b84ae`. That original migration only adds `google_calendar_event_id`; it is not a complete empty-database bootstrap. If migration bookkeeping is missing, have an administrator verify the existing schema against that revision before deliberately stamping it. Do not blindly stamp a mismatched schema.
5. Once the predecessor schema is verified, run `PYTHONPATH=src .venv-p0/bin/alembic upgrade head`. Revision `p0_security_20261013` adds nullable ownership fields, image provenance, a LinkedIn identifier and OAuth tables. It preserves existing rows. Downgrade intentionally refuses to remove ownership; use a reviewed backup if rollback is necessary.
6. Review legacy email/slogan/image/post relationships offline and assign owners only with evidence, consistently across related records. Until then, leave them quarantined. Legacy images have no proven generation provenance and cannot be published; regenerate them rather than marking arbitrary old paths as trusted. Review historical scheduled times and statuses before enabling any previously unowned schedules.
7. Start the new backend and frontend, log in again, reconnect Google/LinkedIn and use newly generated drafts.

The live application database has **not** been migrated or inspected for ownership assignments. Migration verification used synthetic databases only.

Compatibility changes required for security:

- `/auth/gmail` and `/auth/linkedin` require JWT-authenticated fetches and return an authorization URL; the frontend then navigates there. Old direct unauthenticated links no longer work.
- `/post/linkedin` accepts an approved owned `post_id`, not text or an image path. `/schedule_post` requires an owned `post_id` and a future timezone-aware `start_time`.
- Upcoming events expose only the user's application-managed schedules, not the entire Google Calendar.
- Repeated approval/rejection/publication returns a conflict rather than repeating a side effect. Ambiguous failures require reconciliation.
- Shared token JSON files are no longer read. Existing users must reconnect their own integrations.
- Database utility helpers require an authenticated crew instance. The legacy save-post helper creates drafts only; it cannot manufacture `Published` records.
- Scheduling requires the backend process to remain running. Use one local backend process for this demonstration.
- Signup passwords must be 8–72 UTF-8 bytes; existing supported bcrypt hashes still verify.
- Use consistent `127.0.0.1` frontend/backend origins for the local browser-bound OAuth flow. Register exact callbacks `http://127.0.0.1:5000/auth/gmail/callback` and `http://127.0.0.1:5000/auth/linkedin/callback` with the providers if their developer settings permit local callbacks. Otherwise configure a reviewed HTTPS deployment and matching frontend API URLs/origins; provider acceptance was not tested live.
- Serve **only `frontend/`**, never the repository root. For different API origins, update the existing frontend endpoint constants and the shared `frontend/js/api.js` together; the transport deliberately rejects other origins.

## Verification

The automated suite covers absent/invalid/expired JWTs and claim validation; foreign-user and legacy records; valid, invalid, expired, browser-mismatched and reused OAuth state for both providers; encrypted credentials; allowed/disallowed CORS; unsafe image paths, symlinks and altered content; LinkedIn 401/403/429/500 at the profile, image and publication stages; network timeouts/connection errors; malformed confirmations; successful mocked text/image publishing; unpublished failure states; sequential/concurrent duplicates; scheduling/cancellation; database migration preservation; frontend transport and truthful messages; and real offline construction of the five agents.

External requests are mocked or blocked at HTTP/socket boundaries. Tests use synthetic credentials. No live LinkedIn publication, Gmail fetch, Calendar modification, paid model call or image generation occurred.

Run the default suite with `.venv-p0/bin/python -m pytest -q`. For just the API/security layer, a clean environment may install `requirements-test.txt`; the real CrewAI construction test skips unless the full requirements are installed. Frontend tests skip without Node.js, so install Node to include them.

Optional PostgreSQL verification is **destructive to the explicitly designated test database**. Create a disposable database named exactly `p0_security_tests`, set `P0_TEST_DATABASE_URL` to its SQLAlchemy URL, and run the same pytest command. Its tables are dropped/recreated by fixtures. Never point this variable at application data. PostgreSQL verification also needs the existing `psycopg2-binary` dependency from `requirements.txt`.

Actual final results and the full modified-file inventory follow below.

## Remaining risks and manual follow-up

- Credential revocation/rotation, historical secret review and database migration/ownership assignment remain manual. Code changes cannot revoke already exposed keys.
- Provider entitlement, current model availability, Hugging Face endpoint compatibility, OAuth redirect acceptance and actual provider workflows were not tested live. The original model/image integration may require a separate compatibility update before a real demonstration.
- This is a local development setup. TLS, production serving, deployment access-log redaction, login/generation rate limits, abuse controls and a stronger browser-session design need separate deployment work. JWTs still live in browser localStorage; reducing stored-XSS exposure does not make localStorage immune to malicious extensions or future scripts. Tokens remain valid until expiry or signing-key rotation.
- Private email/post content is sent to configured model providers during generation. Existing agent prompt-injection and data-retention concerns remain outside these P0 changes. Agents cannot directly publish through the approved-post service.
- The original broad dependency ranges/transitives, legacy `uv.lock`, frontend vendor assets and other P1 issues have not received a full dependency/security modernization. A passing dependency check establishes installation consistency, not absence of vulnerabilities. The preserved older CrewAI version needs a setuptools compatibility pin.
- The database and private image storage remain trusted application infrastructure. User ownership is enforced in application code, not PostgreSQL row-level security. Local administrative filesystem/database access can bypass application controls.
- Retention/cleanup for expired OAuth states, generated artifacts and failed drafts is not implemented. Standalone optional tools outside the active publishing path, including the unused Imgur uploader, retain their original behavior.

## Recorded final results

Verified on Python 3.12.3 in an isolated Linux environment with the full application and test requirements installed:

| Check | Actual result |
| --- | --- |
| `/tmp/slogancraft-p0-py312/bin/python -m pytest -q` (temporary SQLite) | **142 passed in 16.41s**, zero skips/failures. |
| Same suite with `P0_TEST_DATABASE_URL` pointing to a disposable PostgreSQL 16 database through a private Unix socket | **142 passed in 15.93s**, zero skips/failures. |
| `uv pip check --python /tmp/slogancraft-p0-py312/bin/python --cache-dir /tmp/slogancraft-p0-uvcache` | **197 packages checked; all installed packages compatible.** |
| Python AST syntax validation | **26 files passed.** |
| `node --check` on application JavaScript and inline scripts | **20 files/blocks passed.** |
| Redacted provider-key/private-key pattern scan | **69 text files scanned, zero matching patterns.** Excludes the retained local `.env`, dependency environments, caches and unavailable history; this is not an exhaustive secret-detection guarantee. |

The tests include the real CrewAI offline construction check; all actual provider workflows remain mocked. A fresh install initially lacked `pkg_resources`; pinning `setuptools==80.9.0` resolved that startup failure for the preserved CrewAI version. Earlier exploratory failures were corrected before these final runs. The PostgreSQL fixtures were also corrected to let the database allocate IDs instead of leaving sequences behind explicit fixture IDs.

## Complete file inventory

Compared with the content hashes recorded before implementation (Git was unavailable). No real credential values are included here.

### Modified (35)

- `.gitignore`
- `README.md`
- `alembic.ini`
- `config.py`
- `docker-compose.yml`
- `frontend/CraftBot.html`
- `frontend/Post.html`
- `frontend/change-password.html`
- `frontend/draft.html`
- `frontend/gmail.html`
- `frontend/index.html`
- `frontend/js/approve_reject.js`
- `frontend/js/auth.js`
- `frontend/js/runAgents.js`
- `frontend/js/signin.js`
- `frontend/js/signup.js`
- `frontend/menuPage.html`
- `frontend/run.html`
- `frontend/script.js`
- `frontend/signin.html`
- `frontend/signup.html`
- `migrations/env.py`
- `pyproject.toml`
- `requirements.txt`
- `src/slogancraftai/auth_utils.py`
- `src/slogancraftai/config/agents.yaml`
- `src/slogancraftai/crew.py`
- `src/slogancraftai/db.py`
- `src/slogancraftai/initialize_db.py`
- `src/slogancraftai/main.py`
- `src/slogancraftai/models.py`
- `src/slogancraftai/tools/db_operations.py`
- `src/slogancraftai/tools/image_generator.py`
- `src/slogancraftai/tools/linkedin_poster.py`
- `src/slogancraftai/tools/read_mail.py`

### Added (14)

- `.env.example`
- `docs/P0_SECURITY.md`
- `frontend/js/api.js`
- `migrations/versions/p0_security_20261013.py`
- `requirements-test.txt`
- `src/slogancraftai/publishing.py`
- `src/slogancraftai/security.py`
- `src/slogancraftai/settings.py`
- `tests/conftest.py`
- `tests/test_crew_security.py`
- `tests/test_frontend_security.py`
- `tests/test_migrations.py`
- `tests/test_p0_security.py`
- `tests/test_runtime_compatibility.py`

### Removed credential files (4)

- `src/slogancraftai/tools/credentials/ggl_calendar.json`
- `src/slogancraftai/tools/credentials/linkedin_token.json`
- `src/slogancraftai/tools/credentials/web_ggl_creds.json`
- `src/slogancraftai/tools/credentials/web_token.json`

Additional local-only change: `.env` permissions were restricted to 0600; its contents were retained. Python cache cleanup/regeneration and disposable test environments are not source changes. No `.git` files were changed.
