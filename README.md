# Craftslogan_AI (SloganCraftAI)

An AI engineering portfolio project that turns a product announcement or Gmail message into a slogan, a generated image, and a LinkedIn draft. Five CrewAI agents collaborate in sequence; an authenticated user reviews the result before publishing or scheduling it.

This repository preserves the original Flask backend and HTML/CSS/JavaScript frontend. It includes the existing security protections and a pinned Python 3.12 dependency set. Automated verification uses mocked providers, not real API keys or live publishing.

## Features and technologies

- Manual announcement input or the latest returned unread Gmail message matching `subject:slogan`.
- Five-agent draft generation using CrewAI with Groq, plus Hugging Face image generation.
- Signup/login, private drafts and images, approval/rejection, LinkedIn publication and Google Calendar scheduling.
- Gemini-powered CraftBot in the existing frontend.
- JWT authentication, per-user ownership, encrypted OAuth credentials, expiring single-use OAuth state and duplicate-publication protection.

Built with Python 3.12, CrewAI 0.86, Flask, SQLAlchemy, PostgreSQL, Alembic, APScheduler, PyJWT, cryptography, Pillow and vanilla frontend JavaScript. Pytest and Node.js cover backend/security and frontend behavior.

## The five agents

| Agent | Responsibility | Output/use |
| --- | --- | --- |
| `Mail_Reader` | Analyze the supplied email or announcement | Summary passed to the slogan, image-description and posting tasks |
| `Slogan_Maker` | Write a marketing slogan | Stored slogan and context for the next tasks |
| `Image_Creator` | Describe a matching visual | Prompt supplied to the image agent |
| `Image_Generator` | Call the registered `generate_marketing_image` tool | Actual private PNG generated through Hugging Face |
| `Poster` | Compose the LinkedIn draft | Final post text stored for human review |

Task contexts explicitly connect these outputs. Only `Image_Generator` has an external tool. Gmail ingestion runs before the crew; LinkedIn publication runs through the authenticated publishing service **after approval**, never through an agent. A filename claimed by model text is not accepted as proof that an image was generated.

## Architecture

```text
Browser frontend → Flask API → authenticated user + owned records
                              ├─ manual input / Gmail → five-agent crew → private draft
                              ├─ review → LinkedIn publishing service
                              ├─ scheduling → Google Calendar + APScheduler
                              └─ CraftBot → Gemini
```

```text
frontend/                       Existing pages, JavaScript and static assets
src/slogancraftai/
  main.py                       Flask routes and local scheduler entry point
  crew.py                       Five-agent orchestration and owned draft persistence
  config/{agents,tasks}.yaml    Agent roles and task instructions
  settings.py                   Validated environment configuration
  auth_utils.py, security.py    JWTs, ownership-related helpers, OAuth and image validation
  db.py, models.py               Shared SQLAlchemy models and session factory
  publishing.py                 Confirmed, duplicate-protected publication
  initialize_db.py              Guarded empty-database initialization
  tools/
    read_mail.py                Google OAuth, Gmail and Calendar client
    image_generator.py          Hugging Face HTTP client and private PNG storage
    image_tool.py               Typed CrewAI image-tool adapter
    linkedin_poster.py          LinkedIn OAuth/upload/publication client
migrations/                     Existing schema revision and additive P0 revision
tests/                         Mocked integration, workflow, frontend and security tests
docs/                          Security handoff and cleanup validation report
pyproject.toml                  Authoritative direct dependencies and entry points
requirements*.txt               Installation wrappers for the project/test extra
requirements.lock              Pinned transitive dependencies for Python 3.12
```

## Prerequisites

- **Python 3.12** with `venv` and pip. Linux is the validated platform; other operating systems have not been tested.
- PostgreSQL, or Docker with Compose to use the included database service.
- Node.js on `PATH` to run the frontend behavior tests. No npm packages are needed.
- Provider accounts/permissions only for real application use. Tests require no real credentials.

Run all setup commands from the repository root. The old copied `.venv` folder is not portable; create a separate environment.

## Installation

```bash
python3.12 -m venv .venv-local
.venv-local/bin/python -m pip install -r requirements-test.txt
.venv-local/bin/python -m pip check
```

`requirements-test.txt` installs the editable application and test extra. Use `requirements.txt` instead if you do not need tests. Both constrain dependencies using `requirements.lock`. Versions were retained from a tested environment rather than upgraded wholesale. The obsolete `uv.lock` and nonexistent training/replay/test CLI entries were removed.

For maintainers, regenerate the lock deliberately and rerun the suite after dependency changes:

```bash
uv pip compile pyproject.toml --extra test --python-version 3.12 -c requirements.lock -o requirements.lock
```

The lock records versions, not a guarantee of future model availability or a complete vulnerability assessment. CrewAI retains substantial transitive dependencies. This checkout/editable installation is the supported setup; a standalone wheel does not bundle the root frontend and Alembic workspace.

## Environment configuration

Copy `.env.example` to `.env` **only if `.env` does not already exist**. Otherwise merge missing names into the existing file. Replace placeholders locally; do not commit secrets. On Linux/macOS, restrict access with `chmod 600 .env`.

| Variables | Used for |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection URL, e.g. the PostgreSQL URL shape in `.env.example` |
| `JWT_SECRET_KEY` | Independent random signing secret of at least 32 characters |
| `TOKEN_ENCRYPTION_KEY` | Fernet key generated locally; encrypts users' OAuth credentials |
| `FRONTEND_ORIGINS` | Comma-separated explicit origins; local default `http://127.0.0.1:5500` |
| `FRONTEND_URL`, `BACKEND_URL` | Trusted frontend and callback origins, matching the example local URLs |
| `GENERATED_IMAGE_DIR` | Private image storage, default `generated_images`; keep outside the served frontend |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compose database settings; must match `DATABASE_URL` |
| `MODEL`, `GROQ_API_KEY` | CrewAI/LiteLLM model identifier `groq/<model-id>` and Groq key; choose a model supporting the agent/tool workflow |
| `HUGGINGFACE_API_KEY`, `HUGGINGFACE_MODEL` | Token and `owner/model` served by the HF Inference text-to-image provider |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Web OAuth client for Gmail read-only and Calendar access |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | LinkedIn OAuth client with sign-in/profile and member publishing permissions |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | CraftBot key and model ID, without a `models/` prefix |

Core settings are required at startup; integration settings are required when that integration is used. The Hugging Face client uses the [HF Inference provider](https://huggingface.co/docs/inference-providers/providers/hf-inference) at `https://router.huggingface.co/hf-inference/models/<owner/model>`. Confirm that your selected model is actually served and your account has access; the original hardcoded model is not assumed to remain available.

Register these exact development callback URLs if the providers permit them:

- Google: `http://127.0.0.1:5000/auth/gmail/callback`
- LinkedIn: `http://127.0.0.1:5000/auth/linkedin/callback`

Use consistent `127.0.0.1` origins for the local browser flow. Provider-side OAuth consent, test users, scopes, quotas and any HTTPS requirements must be configured in the provider dashboards. No credentials are supplied by this repository. Previously exposed credentials still require manual rotation; see [the security handoff](docs/P0_SECURITY.md).

## Database setup

The cleanup does not modify an existing application database or introduce a new schema migration.

For a **new empty database**:

```bash
docker compose up -d postgres
.venv-local/bin/python -m slogancraftai.initialize_db
```

Initialization refuses nonempty databases. For an **existing database**, stop old backend/scheduler processes and take a verified backup first:

```bash
.venv-local/bin/alembic current
# After verifying the existing schema/migration revision:
.venv-local/bin/alembic upgrade head
```

The P0 migration follows `3d33747b84ae` and adds ownership, image provenance and encrypted OAuth storage. The original first migration is not an empty-database bootstrap. If Alembic bookkeeping is missing, inspect the schema before deliberately stamping anything. Do not blindly stamp a mismatched database or delete its volume. If already at `p0_security_20261013`, no new migration is required.

Legacy rows are preserved but remain hidden until an administrator verifies ownership. Legacy images without generation provenance must be regenerated before publishing. Follow the [migration and reconciliation instructions](docs/P0_SECURITY.md) for existing data. Changing Compose variables does not rotate the password of an existing PostgreSQL role.

## Start the application

Backend:

```bash
.venv-local/bin/python -m slogancraftai.main
```

The installed `.venv-local/bin/slogancraftai` command is equivalent; `run_crew` remains a compatibility alias. The backend binds to `127.0.0.1:5000` with debug/reloader disabled and starts the local scheduler.

In another terminal, start the existing frontend:

```bash
.venv-local/bin/python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:5500/index.html`. **Serve only `frontend/`, never the repository root**, which contains private configuration. If changing the backend origin later, update `frontend/js/api.js` and the environment origins together.

## Execute the workflow

1. Sign up and sign in through the existing frontend.
2. Use the connection page (`gmail.html`) to connect your own Google and LinkedIn accounts. Manual generation does not need Gmail; publishing needs LinkedIn, and scheduling needs Google Calendar.
3. On `run.html`, supply a product description or request generation from Gmail. Gmail reads an unread message whose subject matches `slogan`; it does not mark messages as read.
4. Open `draft.html` and review the generated post and image. Reject it, publish now, or choose a future scheduling time.
5. Keep the backend running for scheduled publishing. Scheduling creates a Calendar event; APScheduler performs publication when due.
6. Use `CraftBot.html` for the separate Gemini chat integration.

Provider/API failures are reported as failures. Publication is recorded as `Published` only after LinkedIn confirms it. A timeout or lost confirmation may require manual reconciliation; repeated clicks do not blindly resubmit the same post.

## Automated tests

```bash
.venv-local/bin/python -m pytest -q
```

Tests use synthetic credentials, temporary SQLite databases, mocked providers and blocked outbound sockets. They cover JWTs, ownership, OAuth state, CORS, image paths, LinkedIn failures, duplicate attempts, migrations, MIME parsing, frontend messages and actual CrewAI orchestration with mocked LLM/image responses. Entry-point and empty-database initialization checks run without using your application database. Node.js is required to avoid skipping frontend checks.

Optional PostgreSQL testing requires a **disposable** database named `p0_security_tests`. Set `P0_TEST_DATABASE_URL` to its SQLAlchemy URL before pytest; fixtures drop/recreate its tables. Never point that variable at application data. Recorded results and platform details are in [the cleanup report](docs/CLEANUP.md).

## Existing video demonstration

The original video player is preserved in [the workflow page](frontend/Post.html), referencing `frontend/test.mp4`. That file and a public video URL are not included in this checkout. The reference is left unchanged for the project owner to update; no new demonstration was created.

## Known limitations

- Real Groq, Hugging Face, Gemini, Gmail, Calendar and LinkedIn calls were **not** validated. Mocked execution verifies code paths, not model quality, entitlement, current API availability or real publication.
- An image-task tool call is required; if the model fails to call it or produces incomplete output, generation fails safely. Failed runs may leave owned intermediate records/artifacts for later cleanup.
- Gmail currently reads the first returned page of matching messages and requires a plain-text MIME body. HTML-only/attachment-only emails fail clearly instead of reusing unrelated content.
- Run one local backend process and keep it alive for schedules. Uncertain remote results require manual reconciliation; there is no automatic retry or new monitoring dashboard.
- Existing presentation pages may contain historical labels or placeholders. For example, password-change UI has no implemented backend action, and there is no new schedule-management dashboard.
- This is a preserved local portfolio project, not a production deployment. Credential rotation, rate limiting, production TLS/session hardening, third-party dependency review and provider data-retention decisions remain separate work. JWTs are still stored in browser localStorage.
