# Maintenance cleanup handoff

Completed 2026-10-13 in the existing local folder. This is a maintenance pass over the original five-agent project and the preceding P0 security implementation. No new frontend, demonstration, deployment, real credentials or application database changes were introduced. No Git operations were performed. The original video reference in `frontend/Post.html` remains unchanged at the owner's request.

## What changed

- Kept the five agents and sequential CrewAI workflow. Added explicit task contexts and a typed `BaseTool` adapter for the Image_Generator. The adapter accepts an image description, not a filesystem path, and allows one provider attempt per workflow.
- Moved the existing image-generation operation into its intended agent stage. The draft uses the actual generated artifact and the Poster task's final text; previously the image task had no tool and the Poster output was discarded. Missing text, missing image generation and failed image requests cannot produce a supposedly complete draft.
- Made the Hugging Face model configurable with `HUGGINGFACE_MODEL`, using the HF Inference router. Image requests have timeouts, sanitized failures and redirect protection; generated PNGs retain private filenames, permissions and provenance checks.
- Fixed Gmail parsing for nested plain-text MIME parts, unpadded base64, header capitalization and missing plain-text bodies. A newer HTML-only message cannot accidentally reuse an older message's body. Gmail and Calendar remain user-scoped integrations.
- Removed unused imports, unused state/session helpers, redundant database wrappers and LLM setup, the unreachable save-as-published helper, unused optional Imgur code and unreferenced template/sample files. Removed obsolete CLI entries pointing at nonexistent functions. Retained legacy database columns and revision IDs to preserve data compatibility.
- Standardized Python imports/formatting and shortened migration boilerplate. Existing P0 authentication, ownership, OAuth-state, CORS, image validation, publishing claims and failure-state protections remain. Security modules and existing revisions received formatting/import cleanup, not a replacement architecture or new migration.
- Removed duplicated frontend text-cleaning functions and unused private-content debug output. Active frontend requests now use the shared API base. Existing pages, styles, vendors, layouts and video markup remain.
- Made `pyproject.toml` the single direct-dependency source. Both requirement wrappers use a pinned `requirements.lock`; `.python-version` and package metadata specify Python 3.12. Removed unused direct dependencies (`langchain-groq`, `passlib`, `flask-cors`), duplicate PyYAML, and the redundant direct protobuf pin. Protobuf remains locked transitively where needed by CrewAI. Removed the obsolete `uv.lock` instead of leaving two conflicting dependency sets.
- Rewrote the README with the actual architecture, five agents, setup, environment variables, database precautions, startup, workflow, tests, video-reference status and known limitations. The historical P0 handoff now points to current maintenance/setup documentation.

## Validation actually performed

| Check | Result |
| --- | --- |
| Baseline suite before cleanup | 142 passed |
| Fresh Python 3.12.3 environment installed from `requirements-test.txt` with uv | Success; 186 packages including the editable project |
| README-style `python -m pip install -r requirements-test.txt` in that disposable environment | Success |
| Final `python -m pytest -q`, temporary SQLite | **157 passed in 18.83s**, no skips/failures |
| Final suite with disposable PostgreSQL 16, private Unix socket | **157 passed in 16.22s**, no skips/failures |
| `python -m pip check` | No broken requirements found |
| Ruff check and format check | Passed; 25 Python files formatted |
| Python syntax / application JavaScript syntax | 25 Python files and 19 JS files/inline blocks passed |
| Provider/private-key pattern scan of project text | No matches; excludes the unchanged local `.env`, dependency environments, caches and unavailable Git history |

The new runtime check imports the real installed CrewAI package, constructs all five agents/tasks and executes real CrewAI orchestration with deterministic mocked LLM responses and a mocked Hugging Face HTTP response. It verifies the image tool call, private image persistence, final Poster text and an owned `Pending`/`Draft` record. No real model or image-provider request is made. Tests also resolve both installed console entry points, invoke the local server entry-point wiring with a mocked server, and initialize a brand-new temporary database in a separate Python process.

All existing operational P0 security tests remain. One parameterized case for the removed, unreachable save-as-published helper was removed along with that helper; publishing-service confirmation/ownership/duplicate tests remain. Added regression tests cover the corrected workflow, image failure handling, MIME parsing, package entry points and fresh-process initialization.

The PostgreSQL test server was stopped after validation. The existing application database was not accessed or migrated. Local `.env` contents were compared by hash and remained unchanged. No credential values were included in reports.

## What remains unverified or manual

- Live Groq model/tool behavior, Hugging Face model availability/output, Gemini replies, Google OAuth/Gmail/Calendar calls and LinkedIn publishing/permissions have not been tested. Configure your own credentials and currently available model identifiers later. No new real demonstration was produced.
- Python 3.12 on Linux is the validated platform. Other OS/platform combinations and production deployment are unverified. The supported installation is an editable checkout; the frontend and Alembic workspace are not packaged as standalone wheel assets.
- The existing video file/public URL is missing from this folder. Its `test.mp4` reference was deliberately preserved for you to edit later.
- Existing application data still needs any pending P0 migration/ownership review. Never run initialization or the disposable PostgreSQL tests against your application database. Legacy ownership and ambiguous publication-state reconciliation are described in `P0_SECURITY.md`.
- Rotate previously exposed credentials manually and provide a private encryption key. The cleanup does not revoke keys or inspect nonexistent Git history. Do not copy old credentials into new example files.
- Gmail supports the first returned page of matching messages and plain-text bodies. Existing frontend placeholders remain, including password-change UI without a backend implementation. No new schedule dashboard was added.
- The preserved older CrewAI stack has many mandatory transitive packages. The lock improves repeatability; it is not a full dependency vulnerability audit. Existing rate-limit, production-session, external-service data-retention and prompt-injection concerns remain outside this cleanup.
- The existing ignored `.venv` and local credentials were retained. Use a fresh `.venv-local`; do not synchronize environments, caches, generated images or `.env` to GitHub.

## Commands for later use

Run from the repository root on a system with Python 3.12, PostgreSQL/Docker and Node.js:

```bash
python3.12 -m venv .venv-local
.venv-local/bin/python -m pip install -r requirements-test.txt
.venv-local/bin/python -m pip check
.venv-local/bin/python -m pytest -q
```

Merge `.env.example` variable names into your local `.env` without overwriting an existing file; configure real values yourself. `HUGGINGFACE_MODEL` is now required for generation. Choose one database path:

```bash
# NEW, EMPTY database only:
docker compose up -d postgres
.venv-local/bin/python -m slogancraftai.initialize_db

# EXISTING database: back up and verify its schema/revision first:
.venv-local/bin/alembic current
.venv-local/bin/alembic upgrade head
```

Then run the backend and frontend in separate terminals:

```bash
.venv-local/bin/python -m slogancraftai.main
.venv-local/bin/python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:5500/index.html`. Serve only `frontend/`, not the repository root. The installed `slogancraftai` and `run_crew` console commands both call the same local backend entry point. The README contains the detailed workflow and provider configuration.

## Final source structure

```text
.python-version, .env.example, .gitignore
README.md
pyproject.toml
requirements.txt, requirements-test.txt, requirements.lock
docker-compose.yml, alembic.ini
frontend/
  *.html, *.css, script.js
  js/{api,auth,approve_reject,runAgents,signin,signup}.js
  assets/, images/, vendor/      existing static assets
src/slogancraftai/
  __init__.py
  main.py, crew.py
  settings.py, auth_utils.py, security.py, publishing.py
  db.py, models.py, initialize_db.py
  config/{agents,tasks}.yaml
  tools/{read_mail,image_generator,image_tool,linkedin_poster}.py
migrations/
  env.py, script.py.mako, README
  versions/                     original revision + P0 revision, unchanged IDs
tests/
  conftest.py
  test_p0_security.py, test_migrations.py
  test_crew_security.py, test_runtime_compatibility.py
  test_frontend_security.py, test_integrations.py
docs/
  P0_SECURITY.md, CLEANUP.md
```

## Complete file inventory for this cleanup

Compared against content hashes recorded at the start of this cleanup, not the earlier P0 baseline. Python formatting/import changes are included. No files under `.git` were touched.

### Modified (35)

- `.env.example`
- `.gitignore`
- `README.md`
- `alembic.ini`
- `docs/P0_SECURITY.md`
- `frontend/js/approve_reject.js`
- `frontend/js/runAgents.js`
- `frontend/js/signin.js`
- `frontend/js/signup.js`
- `migrations/README`
- `migrations/env.py`
- `migrations/versions/3d33747b84ae_initial_migration_for_linkedinpost.py`
- `migrations/versions/p0_security_20261013.py`
- `pyproject.toml`
- `requirements-test.txt`
- `requirements.txt`
- `src/slogancraftai/auth_utils.py`
- `src/slogancraftai/config/tasks.yaml`
- `src/slogancraftai/crew.py`
- `src/slogancraftai/db.py`
- `src/slogancraftai/initialize_db.py`
- `src/slogancraftai/main.py`
- `src/slogancraftai/models.py`
- `src/slogancraftai/publishing.py`
- `src/slogancraftai/security.py`
- `src/slogancraftai/settings.py`
- `src/slogancraftai/tools/image_generator.py`
- `src/slogancraftai/tools/linkedin_poster.py`
- `src/slogancraftai/tools/read_mail.py`
- `tests/conftest.py`
- `tests/test_crew_security.py`
- `tests/test_frontend_security.py`
- `tests/test_migrations.py`
- `tests/test_p0_security.py`
- `tests/test_runtime_compatibility.py`

### Added (5)

- `.python-version`
- `docs/CLEANUP.md`
- `requirements.lock`
- `src/slogancraftai/tools/image_tool.py`
- `tests/test_integrations.py`

### Removed (9)

- `config.py`
- `frontend/Readme.md`
- `frontend/frontend/assets/illustrations/scene.svg`
- `frontend/js/hide_auth.js`
- `knowledge/user_preference.txt`
- `src/slogancraftai/tools/db_operations.py`
- `src/slogancraftai/tools/imgur_uploader.py`
- `test_image.png`
- `uv.lock`
