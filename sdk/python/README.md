# LogLlama Python SDK

LLM observability in two lines of Python.

```bash
pip install logllama
```

```python
import logllama
from openai import OpenAI

logllama.init(api_key="YOUR_LOGLLAMA_KEY")
client = logllama.wrap_openai(OpenAI())
```

Every supported OpenAI call made through `client` is captured automatically.

Anthropic, Gemini, and Cursor SDK clients use the same pattern:

```python
from cursor_sdk import Agent, LocalAgentOptions

anthropic_client = logllama.wrap_anthropic(Anthropic())
gemini_client = logllama.wrap_gemini(genai.Client())
# A Cursor run is captured when .wait() or .text() returns its terminal result.
cursor_agent = logllama.wrap_cursor(
    Agent.create(model="auto-smart", local=LocalAgentOptions(cwd="."))
)
```

## Provider Switching

Use the normalized client when the provider should be selected per request:

```python
llm = logllama.LLM(
    openai=openai_client,
    anthropic=anthropic_client,
    cursor=cursor_agent,
    gemini=gemini_client,
    models={
        "openai": "gpt-model",
        "anthropic": "claude-model",
        "cursor": "auto-smart",
        "gemini": "gemini-model",
    },
)

response = llm.generate(
    "Summarize this support ticket.",
    provider="anthropic",  # "claude" is accepted as an alias
    max_output_tokens=200,
)

print(response.text)
print(response.usage)
print(response.raw)
```

Provider packages are optional:

```bash
pip install "logllama[openai]"
pip install "logllama[anthropic]"
pip install "logllama[gemini]"
pip install "logllama[cursor]"
pip install "logllama[all]"
```

## Approved Comparison Tests

Comparison mode cannot call providers until the exact prompt, models, and output limit are approved in the admin portal:

```python
approvals = logllama.TestApprovalClient(
    endpoint="http://localhost:8000",
    api_key="YOUR_LOGLLAMA_KEY",
)
llm.approval_client = approvals

plan = llm.request_test(
    prompt="Reply with only: ok",
    targets=[
        ("openai", "gpt-model"),
        ("anthropic", "claude-model"),
        ("cursor", "auto-smart"),
        ("gemini", "gemini-model"),
    ],
    max_output_tokens=16,
    max_runs=1,
)

# After an administrator approves plan["id"]:
results = llm.compare(test_plan_id=plan["id"])
```

Targets run concurrently and share a `comparison_id` in telemetry.

## Managed Credentials

Managed keys are preloaded before the client is returned and refreshed on a background thread:

```python
llm = logllama.LLM.from_managed(
    models={
        "openai": "gpt-model",
        "anthropic": "claude-model",
        "cursor": "auto-smart",
        "gemini": "gemini-model",
    },
    endpoint="http://localhost:8000",
    runtime_key="YOUR_LOGLLAMA_RUNTIME_KEY",
)
```

The normal `generate()` path reads an already-built provider adapter and performs no LogLlama or secret-manager network request. Call `llm.close()` during application shutdown.

```python
client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Write a support email."}],
    logllama_metadata={
        "route": "/support/email",
        "user_id": "user_123",
        "tenant_id": "tenant_acme",
        "conversation_id": "conv_123",
        "prompt_template": "support_email",
        "prompt_version": "v3",
    },
)
```

Use `logllama_metadata` for LogLlama-only correlation data. The SDK removes it before calling OpenAI, which avoids provider validation limits such as OpenAI requiring `metadata` values to be strings.

## Correlation Metadata

Configure service-level metadata once:

```python
logllama.init(
    api_key="YOUR_LOGLLAMA_KEY",
    service_name="support-api",
    environment="production",
    version="1.8.0",
    git_sha="abc123",
    tags=["support"],
)
```

Attach request-scoped context with a convenience API:

```python
with logllama.context(
    route="/tickets/reply",
    user_id="user_123",
    tenant_id="tenant_acme",
    session_id="sess_123",
    conversation_id="conv_123",
    request_id="req_123",
    prompt_template="ticket_reply",
    prompt_version="v7",
):
    client.chat.completions.create(model="gpt-4o-mini", messages=[...])
```

You can also attach rich metadata to a single OpenAI call:

```python
client.responses.create(
    model="gpt-5-nano",
    input="Write a concise answer.",
    metadata={"provider_tag": "safe-string-value"},
    logllama_metadata={
        "route": "/answers",
        "tenant_id": "tenant_acme",
        "tags": ["answers", "production"],
        "custom_metadata": {"experiment": "v2"},
    },
)
```

## Environment Variables

You can configure the SDK with a `.env` file instead of passing arguments:

```text
LOGLLAMA_API_KEY=YOUR_LOGLLAMA_KEY
LOGLLAMA_ENDPOINT=http://localhost:8000
```

Then your code becomes:

```python
import logllama
from openai import OpenAI

logllama.init()
client = logllama.wrap_openai(OpenAI())
```

## Captured Data

- provider and operation
- model
- prompt/messages
- response
- input/output/total tokens
- latency
- estimated cost, calculated by the backend
- errors
- metadata
- service, environment, version, and git SHA
- route, user, tenant, session, conversation, request, trace, and span identifiers
- prompt template and prompt version
- tags and custom metadata

## Privacy Controls

Disable prompt or response capture, redact sensitive keys, limit payload size, and filter metadata:

```python
logllama.init(
    api_key="YOUR_LOGLLAMA_KEY",
    capture_prompts=False,
    capture_responses=False,
    redact_keys=["password", "authorization", "api_key", "email"],
    max_prompt_size=20000,
    max_response_size=50000,
    metadata_allowlist=["service_name", "environment", "route", "user_id", "tenant_id", "trace_id"],
    metadata_denylist=["ssn", "credit_card"],
)
```

Or through environment variables:

```text
LOGLLAMA_CAPTURE_PROMPTS=false
LOGLLAMA_CAPTURE_RESPONSES=false
LOGLLAMA_REDACT_KEYS=password,authorization,api_key,email
LOGLLAMA_MAX_PROMPT_SIZE=20000
LOGLLAMA_MAX_RESPONSE_SIZE=50000
LOGLLAMA_METADATA_ALLOWLIST=service_name,environment,route,user_id,tenant_id,trace_id
LOGLLAMA_METADATA_DENYLIST=ssn,credit_card
LOGLLAMA_SAMPLE_RATE=1
```

Errors are captured by default even when successful requests are sampled.

## Reliable Delivery

The SDK uses one bounded background queue per LogLlama destination and sends
events in batches. Provider calls only pay the cost of adding an event to the
local queue; telemetry HTTP retries happen on the delivery worker.

```python
import logllama

logllama.init(
    delivery_queue_size=1000,
    delivery_batch_size=20,
    delivery_flush_interval_seconds=0.25,
    delivery_max_attempts=3,
    delivery_retry_backoff_seconds=0.25,
    delivery_spool_path="/var/lib/my-service/logllama-events.jsonl",
)
```

The spool is optional because it contains captured event payloads. When set,
failed deliveries and queue overflow are written with file mode `0600` and
replayed before new in-memory events. Without a spool, a full queue or exhausted
delivery retries emits a `RuntimeWarning` and increments `delivery_stats()["dropped"]`.

Call `logllama.flush()` during graceful application shutdown. `LLM.close()`
flushes automatically.

```text
LOGLLAMA_DELIVERY_QUEUE_SIZE=1000
LOGLLAMA_DELIVERY_BATCH_SIZE=20
LOGLLAMA_DELIVERY_FLUSH_INTERVAL_SECONDS=0.25
LOGLLAMA_DELIVERY_MAX_ATTEMPTS=3
LOGLLAMA_DELIVERY_RETRY_BACKOFF_SECONDS=0.25
LOGLLAMA_DELIVERY_SPOOL_PATH=/var/lib/my-service/logllama-events.jsonl
```

## FastAPI Helper

```python
from logllama.integrations.fastapi import LogLlamaMiddleware

app.add_middleware(
    LogLlamaMiddleware,
    service_name="support-api",
    environment="production",
    get_user_id=lambda request: request.state.user_id,
    get_tenant_id=lambda request: request.state.tenant_id,
)
```

When OpenTelemetry is installed and active, the SDK automatically attaches the current `trace_id` and `span_id`.

## Tests

Install the SDK test dependencies:

```bash
cd sdk/python
python -m pip install -e ".[openai,anthropic,gemini,cursor,test]"
```

Run normal SDK tests:

```bash
python -m pytest tests/unit -q
```

Run paid integration tests through the repository's manual `provider-e2e`
GitHub Actions job. It boots OpenBao, saves OpenAI, Anthropic, Gemini, and
Cursor keys through the admin Providers API, removes provider API keys from the
SDK process, and runs five bounded calls per provider through
`LLM.from_managed(...)`. Cursor runs locally with tools disabled.

Configure the `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and
`CURSOR_API_KEY` secrets for the
`provider-e2e` GitHub environment. Then open **Actions > SDK Tests > Run
workflow** and set `run_provider_e2e` to `true`. Keep both local
`RUN_LOGLLAMA_*_INTEGRATION` flags at `0` during ordinary test runs to avoid
accidental provider charges.

## Local Development

From this repository:

```bash
cd sdk/python
pip install -e .
```

For the local backend, use:

```text
LOGLLAMA_API_KEY=llama-dev-key
LOGLLAMA_ENDPOINT=http://localhost:8000
```
