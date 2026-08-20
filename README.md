# LogLlama

LLM observability in two lines of Python.

LogLlama captures OpenAI, Anthropic, and Gemini requests, provides client-side provider switching and approved comparison tests, and shows costs, latency, tokens, prompts, responses, errors, and metadata in a developer dashboard.

## Quick SDK Usage

For local development from this repo:

```bash
cd sdk/python
pip install -e .
```

In your app:

```python
import logllama
from openai import OpenAI

logllama.init(api_key="llama-dev-key")
client = logllama.wrap_openai(OpenAI(api_key="your-openai-key"))

with logllama.context(
    route="/demo",
    user_id="local-dev",
    tenant_id="tenant_demo",
    conversation_id="conv_demo",
    prompt_template="hello_world",
    prompt_version="v1",
):
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say hello"}],
    )
```

Or configure with `.env`:

```text
LOGLLAMA_API_KEY=llama-dev-key
LOGLLAMA_ENDPOINT=http://localhost:8000
```

Then:

```python
import logllama
from openai import OpenAI

logllama.init()
client = logllama.wrap_openai(OpenAI())
```

The older `track_openai(...)` API still works, but `init(...)` + `wrap_openai(...)` is the preferred developer flow.

For provider-neutral calls:

```python
llm = logllama.LLM(
    openai=openai_client,
    anthropic=anthropic_client,
    gemini=gemini_client,
    models={
        "openai": "gpt-model",
        "anthropic": "claude-model",
        "gemini": "gemini-model",
    },
)

response = llm.generate("Explain this error.", provider="anthropic")
```

## What Is Included

- Python SDK with OpenAI, Anthropic, and Gemini request capture.
- Provider-neutral `LLM.generate(..., provider=...)` routing.
- Admin-approved, concurrent cross-provider comparison tests.
- Managed provider credentials with startup/background SDK caching.
- FastAPI ingestion backend.
- PostgreSQL storage through SQLAlchemy.
- React dashboard for request logs, cost, latency, token usage, prompts, responses, metadata, and errors.
- First-class enterprise correlation fields for service, environment, route, tenant, user, request, trace, conversation, prompt template, and prompt version.
- SDK privacy controls for prompt/response capture, key redaction, payload size limits, metadata allowlists/denylists, and sampling.
- Optional FastAPI request context helper and OpenTelemetry trace/span capture.
- Docker Compose for local PostgreSQL.

## Project Layout

```text
backend/        FastAPI API and database models
sdk/python/     Python SDK package
dashboard/      React dashboard
examples/       Minimal instrumented OpenAI app
scripts/        Local sample event senders
```

## Local Setup

1. Create the ignored local environment file and generate separate privileged keys:

```bash
test -f .env || cp .env.example .env
admin_key="$(openssl rand -hex 32)"
runtime_key="$(openssl rand -hex 32)"
printf '\nLOGLLAMA_ADMIN_API_KEY=%s\n' "$admin_key" >> .env
printf 'LOGLLAMA_DEFAULT_RUNTIME_KEY=%s\n' "$runtime_key" >> .env
printf 'LOGLLAMA_RUNTIME_KEY=%s\n' "$runtime_key" >> .env
unset admin_key runtime_key
```

Privileged keys must be random and at least 32 characters. Runtime keys must not
exceed 255 characters. The known `llama-admin-key` and `llama-runtime-key`
values are intentionally rejected.

2. Start PostgreSQL and bootstrap persistent local OpenBao:

```bash
docker compose up -d postgres
scripts/openbao-local-bootstrap.sh
```

The bootstrap script initializes or unseals OpenBao and writes ignored AppRole
configuration to `.openbao/backend.env`.

3. Start the backend with both environment files loaded:

```bash
set -a
source .env
source .openbao/backend.env
set +a
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

AWS Secrets Manager is an optional backend dependency:

```bash
pip install -r requirements-aws.txt
```

The backend seeds a default project with this SDK key:

```text
llama-dev-key
```

4. Start the dashboard:

```bash
cd dashboard
npm install
npm run dev
```

Open the local dashboard URL printed by Vite, usually:

```text
http://127.0.0.1:5173
```

If that port is occupied, Vite may use `5174`.

5. Send a sample captured request without a provider key:

```bash
python3 scripts/send_sample_event.py
python3 scripts/send_second_sample_event.py
```

## Environment Variables

Backend:

```text
DATABASE_URL=postgresql+asyncpg://logllama:logllama@localhost:5432/logllama
LOGLLAMA_DEFAULT_API_KEY=llama-dev-key
LOGLLAMA_DEFAULT_RUNTIME_KEY=<32-to-255-character-random-key>
LOGLLAMA_DEFAULT_PROJECT_NAME=Development
LOGLLAMA_ADMIN_API_KEY=<32+-character-random-key>
LOGLLAMA_SECRET_BACKEND=openbao
LOGLLAMA_SECRET_STORE_ADDR=http://127.0.0.1:8200
LOGLLAMA_SECRET_STORE_ROLE_ID_FILE=/absolute/path/to/.openbao/role-id
LOGLLAMA_SECRET_STORE_SECRET_ID_FILE=/absolute/path/to/.openbao/secret-id
```

SDK:

```text
LOGLLAMA_API_KEY=llama-dev-key
LOGLLAMA_RUNTIME_KEY=<same-value-as-LOGLLAMA_DEFAULT_RUNTIME_KEY>
LOGLLAMA_ENDPOINT=http://localhost:8000
LOGLLAMA_TIMEOUT_SECONDS=1
LOGLLAMA_CAPTURE_PROMPTS=true
LOGLLAMA_CAPTURE_RESPONSES=true
LOGLLAMA_SERVICE_NAME=demo-api
LOGLLAMA_ENVIRONMENT=local
LOGLLAMA_VERSION=0.1.0
LOGLLAMA_GIT_SHA=local-dev
LOGLLAMA_TAGS=demo,local
LOGLLAMA_REDACT_KEYS=password,authorization,api_key,email
LOGLLAMA_MAX_PROMPT_SIZE=20000
LOGLLAMA_MAX_RESPONSE_SIZE=50000
LOGLLAMA_METADATA_ALLOWLIST=service_name,environment,route,user_id,tenant_id,trace_id
LOGLLAMA_METADATA_DENYLIST=ssn,credit_card
LOGLLAMA_SAMPLE_RATE=1
LOGLLAMA_CAPTURE_ERRORS=true
LOGLLAMA_CAPTURE_OTEL=true
LOGLLAMA_ENABLED=true
```

`scripts/openbao-local-bootstrap.sh` is the recommended local setup. It uses
persistent Raft storage and AppRole files, so provider credentials survive
backend and OpenBao restarts. The backend stores only secret references and
fingerprints in PostgreSQL.

Memory storage is available only for disposable development and must be
explicitly enabled:

```text
LOGLLAMA_SECRET_BACKEND=memory
LOGLLAMA_ALLOW_EPHEMERAL_SECRETS=true
```

Do not use memory storage for credentials that must survive a restart.
Production choices are `aws`, `vault`, and `openbao`. Static Vault/OpenBao
tokens remain supported, but AppRole or workload identity should be injected
into the backend instead of being stored in the admin portal. Managed provider
credentials are fetched with the separate runtime key during SDK startup and
refreshed in the background, never during a normal model call. This keeps
secret-manager network latency out of customer model requests.
Non-loopback Vault and OpenBao endpoints must use HTTPS.

Benchmark local secret-store control-plane latency with:

```bash
cd backend
PYTHONPATH=. ../.venv/bin/python benchmarks/secret_store_latency.py \
  --vault-addr http://127.0.0.1:8200 --vault-token test-token \
  --openbao-addr http://127.0.0.1:8300 --openbao-token test-token
```

Measure the full SDK preload endpoint separately:

```bash
cd backend
PYTHONPATH=. .venv/bin/python benchmarks/runtime_preload_latency.py \
  --endpoint http://127.0.0.1:8000 \
  --runtime-key "$LOGLLAMA_RUNTIME_KEY"
```

## API

- `POST /v1/events` ingests SDK events. Requires `X-LogLlama-Api-Key`.
- `POST /v1/test-plans` requests an admin-approved provider comparison.
- `GET /v1/test-plans/{id}` checks the immutable comparison plan.
- `GET /v1/runtime/provider-credentials` preloads managed credentials. Requires `X-LogLlama-Runtime-Key`.
- `/api/admin/provider-credentials` manages write-only provider secrets.
- `/api/admin/test-plans` lists, approves, and rejects comparison plans.
- `GET /api/requests` lists captured requests.
- `GET /api/requests?tenant_id=...&route=...&trace_id=...` filters captured requests by enterprise correlation fields.
- `GET /api/requests/{request_id}` fetches one captured request.
- `GET /api/metadata/facets` returns filter values for the dashboard.
- `GET /api/traces/{trace_id}` returns all requests for one distributed trace.
- `GET /api/conversations/{conversation_id}` returns all requests in one AI conversation.
- `GET /api/metrics/summary` returns dashboard metrics.
- `GET /health` checks service health.

## SDK Integration Tests

The SDK includes opt-in OpenAI and Gemini integration tests under
`sdk/python/tests/integration`.

```bash
cd sdk/python
python -m pip install -e ".[openai,gemini,test]"
python -m pytest tests/unit -q
```

The recommended paid E2E path is the manual `provider-e2e` job in
`.github/workflows/sdk-tests.yml`. Configure the `OPENAI_API_KEY` and
`GEMINI_API_KEY` GitHub secrets, open **Actions > SDK Tests > Run workflow**,
and set `run_provider_e2e` to `true`. The job:

- boots PostgreSQL and OpenBao;
- generates strong admin and runtime keys;
- saves both provider keys through the admin Providers API;
- removes provider API keys from the SDK test environment; and
- runs exactly five OpenAI and five Gemini requests through
  `LLM.from_managed(...)`.

For a local paid run, first complete the OpenBao setup above, save provider
keys in the dashboard Providers tab, and leave the backend running. Then load
the root `.env`, explicitly opt in, and select only the bounded success tests:

```bash
set -a
source ../../.env
set +a
unset OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY ANTHROPIC_API_KEY
RUN_LOGLLAMA_OPENAI_INTEGRATION=1 \
LOGLLAMA_OPENAI_SUCCESS_RUNS=5 \
RUN_LOGLLAMA_GEMINI_INTEGRATION=1 \
LOGLLAMA_GEMINI_SUCCESS_RUNS=5 \
python -m pytest -q \
  tests/integration/test_openai_capture.py::test_valid_openai_managed_credentials_capture_bounded_billable_calls \
  tests/integration/test_gemini_capture.py::test_valid_gemini_managed_credentials_capture_bounded_calls
```

Keep both `RUN_LOGLLAMA_*_INTEGRATION` values at `0` during ordinary local
test runs to avoid accidental provider charges.

## Packaging Status

The SDK is structured for PyPI packaging, but it has not been published from this repo yet.

Build locally:

```bash
cd sdk/python
python -m build
```

Publish later, after creating PyPI credentials:

```bash
python -m twine upload dist/*
```
