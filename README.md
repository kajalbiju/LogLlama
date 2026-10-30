# LogLlama

LLM observability for apps that call OpenAI, Anthropic, and Gemini.

LogLlama captures each model call with its cost, latency, tokens, prompt, response, errors, and correlation metadata (route, tenant, user, trace, conversation, prompt version). A multi-user dashboard shows the results, and admins can gate provider comparison tests behind approvals.

Status: pre-release and proprietary. See [LICENSE](LICENSE). The open-source split is not decided yet.

## What is included

- **Python SDK** (`sdk/python`): wrappers for the OpenAI, Anthropic, and Gemini clients, provider-neutral `LLM.generate(provider=...)` routing, privacy controls, and batched delivery through a bounded queue.
- **TypeScript SDK** (`sdk/typescript`): the same wrappers for `openai`, `@anthropic-ai/sdk`, and `@google/genai` clients, with batched delivery and AsyncLocalStorage context.
- **Backend** (`backend`): FastAPI and PostgreSQL. Accounts with sessions, organizations and roles, projects, hashed API keys, batch ingestion, dashboard queries, provider credentials, and comparison-test approvals.
- **Dashboard** (`dashboard`): React and Vite. Sign in, switch organizations and projects, inspect traces, manage API keys, manage team and projects, and handle provider credentials and approvals.
- **Schema migrations** (`backend/migrations`): Alembic. The backend never changes the schema at startup.

## Quick start

1. Start PostgreSQL. If port 5432 is taken by another PostgreSQL, set a different host port first:

   ```powershell
   $env:LOGLLAMA_POSTGRES_HOST_PORT = "5433"
   docker compose up -d postgres
   ```

   On macOS or Linux, run `LOGLLAMA_POSTGRES_HOST_PORT=5433 docker compose up -d postgres` instead.

2. Install and migrate the backend, then start it:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   $env:DATABASE_URL = "postgresql+asyncpg://logllama:logllama@127.0.0.1:5433/logllama"
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

   Set `DATABASE_URL` to match the host port you started PostgreSQL on (`5432` by default). On macOS or Linux, activate the venv with `source .venv/bin/activate` and run the same commands with `python` and `DATABASE_URL=... python ...`.

3. Start the dashboard:

   ```bash
   cd dashboard
   npm install
   npm run dev
   ```

   Open `http://127.0.0.1:5173`. The first account you create on a fresh install claims the seeded **Development** organization, so `llama-dev-key` keeps working. Later accounts get their own organization. The dev server forwards `/api` to the backend, so open the dashboard on whichever host you like.

4. Create an ingest key in the **API keys** tab, or provision one from the command line:

   ```powershell
   $env:LOGLLAMA_PROVISION_PASSWORD = [System.Net.NetworkCredential]::new("", (Read-Host "Account password (12+ characters)" -AsSecureString)).Password
   python scripts\provision_local.py --email you@example.com
   ```

   The script prints the project ID and the new ingest and runtime keys. Copy them from the output; they are shown once.

## Accounts, roles, and keys

Each organization has members with one of five roles. The backend enforces every permission. The dashboard only hides controls.

| Role | Can do |
| --- | --- |
| `viewer` | Read traces, metrics, and test requests |
| `developer` | Viewer, plus create projects and API keys |
| `test_approver` | Viewer, plus approve or reject comparison tests |
| `credential_admin` | Viewer, plus store and remove provider credentials |
| `owner` | All of the above, plus invite and remove members and change roles |

Non-members get `404` for an organization or project, so IDs cannot be probed across organizations.

API keys belong to a project and come in two kinds:

- **Ingest** (`llm_...`) sends events. Use it with the SDKs.
- **Runtime** (`llrt_...`) fetches managed provider credentials on trusted servers.

A key is shown once, at creation. The database stores only its SHA-256 hash, a display prefix, and metadata. Keys can expire and can be revoked immediately.

Browser sessions use an HTTP-only cookie. Cookie-authenticated writes must send the `X-LogLlama-Request: 1` header, which forces a CORS preflight for other origins.

## Migrations

Every schema change is an Alembic revision in `backend/migrations/versions`.

```bash
cd backend
alembic upgrade head      # apply pending migrations
alembic check            # fail if the models differ from the migrations
alembic current          # show the database revision
```

The baseline migration is idempotent, so a database created by an earlier version adopts it without losing data. Revision `0002` is forward-only: the plaintext keys it hashes cannot be recovered. Startup refuses to run against a database that is not at head.

## SDK usage

### Python

```python
import logllama
from openai import OpenAI

logllama.init(api_key="llm_...", endpoint="http://localhost:8000")
client = logllama.wrap_openai(OpenAI())

with logllama.context(route="/demo", tenant_id="tenant_demo"):
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say hello"}],
    )

logllama.flush()     # optional: deliver queued events before a short-lived process exits
```

Events are queued in memory and sent in batches (`batch_size`, default 50, or every `flush_interval_seconds`, default 1). The queue holds 10,000 events. When it is full, new events are dropped and counted, so telemetry never blocks a model call. `logllama.transport_stats()` returns queued, sent, dropped, failed, and pending counts.

Anthropic and Gemini use the same pattern: `wrap_anthropic(...)` and `wrap_gemini(...)`. The SDK strips the `logllama_metadata` argument before calling the provider.

### TypeScript

```ts
import { context, init, wrapOpenAI, flush } from "logllama";
import OpenAI from "openai";

init({ apiKey: "llm_...", endpoint: "http://localhost:8000" });
const client = wrapOpenAI(new OpenAI());

await context({ route: "/demo", tenant_id: "tenant_demo" }, () =>
  client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "Say hello" }],
  }),
);

await flush();
```

Streamed responses (`stream: true`) pass through without capture in this version. The SDK refuses to send events when no API key is configured.

## Pricing

`backend/app/pricing.py` holds the list prices used to estimate cost. Prices were checked against the vendor pricing pages on 2026-10-26. Models are matched by ID prefix, and the longest match wins. Tiered prices apply above a prompt-size threshold where a vendor publishes one.

- A model with no published text-token price gets an unknown cost (`null`), which the dashboard shows as `unknown`. It is never shown as $0.
- Cache, batch, priority, and regional pricing are not modeled. Costs are estimates.
- Audio, image, live, and embedding models are left unpriced.
- OpenAI prices were not re-verified in this pass.

## Environment variables

Backend:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://logllama:logllama@localhost:5432/logllama` | Database connection |
| `LOGLLAMA_DEFAULT_API_KEY` | `llama-dev-key` | Development ingest key, seeded into the Development organization |
| `LOGLLAMA_DEFAULT_RUNTIME_KEY` | unset | Development runtime key. Must be 32+ characters. |
| `LOGLLAMA_ALLOW_SIGNUP` | `true` | Set `false` to disable self-service sign-up |
| `LOGLLAMA_SESSION_TTL_HOURS` | `12` | Browser session lifetime |
| `LOGLLAMA_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `LOGLLAMA_CORS_ORIGINS` | local dashboard origins | Comma-separated origins that may call the API with credentials |
| `LOGLLAMA_MAX_BATCH_EVENTS` | `500` | Maximum events per batch request |
| `LOGLLAMA_MAX_REQUEST_BYTES` | `5000000` | Maximum request body size |
| `LOGLLAMA_SECRET_BACKEND` | `memory` | `memory`, `aws`, `vault`, or `openbao`. Memory is development only. |

SDK (Python), also readable from the environment: `LOGLLAMA_API_KEY`, `LOGLLAMA_ENDPOINT`, `LOGLLAMA_BATCH_SIZE`, `LOGLLAMA_FLUSH_INTERVAL_SECONDS`, `LOGLLAMA_MAX_QUEUE_SIZE`, `LOGLLAMA_CAPTURE_PROMPTS`, `LOGLLAMA_CAPTURE_RESPONSES`, `LOGLLAMA_REDACT_KEYS`, `LOGLLAMA_SAMPLE_RATE`, and the rest listed in `.env.example`.

Copy `.env.example` to `.env` to start. `.env` is gitignored.

## API

Authentication: `X-LogLlama-Api-Key` for ingest, `X-LogLlama-Runtime-Key` for runtime, or the session cookie for everything under `/api`.

- `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `POST /api/organizations`, `GET|POST /api/organizations/{id}/members`, `DELETE /api/organizations/{id}/members/{user_id}`
- `GET|POST /api/projects`, `GET|POST /api/projects/{id}/api-keys`, `DELETE /api/projects/{id}/api-keys/{key_id}`
- `GET /api/requests`, `GET /api/requests/{id}`, `GET /api/metrics/summary`, `GET /api/metadata/facets`, `GET /api/traces/{trace_id}`, `GET /api/conversations/{conversation_id}`. All take `project_id`.
- `GET|POST /api/admin/provider-credentials`, `DELETE /api/admin/provider-credentials/{id}`, `GET /api/admin/test-plans`, `POST /api/admin/test-plans/{id}/approve|reject`. All take `project_id` where the route lists it.
- `POST /v1/events`, `POST /v1/events/batch`, `POST /v1/test-plans`, `GET /v1/test-plans/{id}`, `POST /v1/test-plans/{id}/lease`
- `GET /v1/runtime/provider-credentials`
- `GET /health`

## Tests and CI

These commands are for Windows PowerShell, run from the repository root. Each Python suite has its own virtual environment, so use `.\.venv\Scripts\python.exe` rather than the system `python`, which does not have pytest.

First-time setup:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd ..\sdk\python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[all,test]"
cd ..\typescript
npm ci
cd ..\..\dashboard
npm ci
```

Create the backend test database once, with PostgreSQL running. The backend test run wipes this database, so never point `TEST_DATABASE_URL` at one you want to keep. If it already exists, the command reports that and changes nothing.

```powershell
docker compose exec postgres createdb -U logllama logllama_test
```

Run every suite:

```powershell
cd backend
$env:TEST_DATABASE_URL = "postgresql+asyncpg://logllama:logllama@127.0.0.1:5433/logllama_test"
.\.venv\Scripts\python.exe -m pytest tests -v
cd ..\sdk\python
.\.venv\Scripts\python.exe -m pytest tests -v
cd ..\typescript
npm run typecheck
npm test
cd ..\..\dashboard
npm run build
```

Set `5433` to the host port PostgreSQL runs on (`5432` by default). If `TEST_DATABASE_URL` is not set, the database-backed backend tests skip, and pytest lists them as skipped. Set it, or check the skip count, before reading the run as passing.

On macOS or Linux, activate each venv with `source .venv/bin/activate`, then run the same commands with `python`. Set the database URL inline: `TEST_DATABASE_URL=... python -m pytest tests -v`.

The backend test run resets its database, applies migrations, and exercises the account, tenancy, key, ingestion, pricing, and approval flows against PostgreSQL.

GitHub Actions runs the backend, Python SDK, TypeScript SDK, and dashboard checks on every pull request. The live provider test is opt-in: it runs only from a manual dispatch with the `run_provider_e2e` input, and it provisions its own account and keys with `scripts/provision_local.py`.

The opt-in OpenAI integration tests make billable calls. They load provider keys through the managed-credential path, so they need a persistent secret store (see the Providers tab), `LOGLLAMA_RUNTIME_KEY`, and `LOGLLAMA_DASHBOARD_EMAIL`, `LOGLLAMA_DASHBOARD_PASSWORD`, and `LOGLLAMA_PROJECT_ID` to read captured events back. Without that store, use `sdk/python/real_token_test.py`, which calls each provider directly with the key you set in the environment.

## Project layout

```text
backend/        FastAPI API, Alembic migrations, and backend tests
dashboard/      React dashboard
sdk/python/     Python SDK
sdk/typescript/ TypeScript SDK
examples/       Minimal instrumented OpenAI app
scripts/        Local sample senders and account provisioning
deploy/         OpenBao configuration
docs/           Production readiness plan and secret-store evaluation
```

## Packaging

The Python package is named `logllama`, but it is not published to PyPI. The TypeScript package is marked `private`. Publishing waits for the open-source decision in [LICENSE](LICENSE).
