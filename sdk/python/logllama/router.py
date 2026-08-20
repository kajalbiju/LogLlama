from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, request

from .anthropic import wrap_anthropic
from .client import flush
from .config import get_config
from .credentials import ManagedCredentialCache
from .cursor import wrap_cursor
from .gemini import wrap_gemini
from .openai import wrap_openai
from .providers import AnthropicAdapter, CursorAdapter, GenerationResponse, GeminiAdapter, OpenAIAdapter, ProviderAdapter


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    comparison_id: str
    test_plan_id: str
    responses: dict[str, GenerationResponse]
    errors: dict[str, str]


class ApprovalRequiredError(RuntimeError):
    pass


class TestApprovalClient:
    def __init__(self, *, endpoint: str, api_key: str, timeout_seconds: float = 3.0):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def request_test(
        self,
        *,
        prompt: str,
        targets: list[dict[str, str]],
        max_output_tokens: int,
        max_runs: int = 1,
        system: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/test-plans",
            {
                "prompt": prompt,
                "system": system,
                "targets": targets,
                "max_output_tokens": max_output_tokens,
                "max_runs": max_runs,
            },
        )

    def get_test_plan(self, test_plan_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/test-plans/{test_plan_id}")

    def lease_test_plan(self, test_plan_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/test-plans/{test_plan_id}/lease", {})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        encoded = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(
            f"{self.endpoint}{path}",
            data=encoded,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-LogLlama-Api-Key": self.api_key,
                "User-Agent": "logllama-python/0.2.0",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail")
            except Exception:
                detail = None
            message = detail or f"LogLlama control API returned {exc.code}."
            if exc.code == 409:
                raise ApprovalRequiredError(message) from exc
            raise RuntimeError(message) from exc


class LLM:
    def __init__(
        self,
        *,
        providers: dict[str, ProviderAdapter | Any] | None = None,
        openai: Any = None,
        anthropic: Any = None,
        cursor: Any = None,
        gemini: Any = None,
        models: dict[str, str] | None = None,
        routes: dict[str, dict[str, str]] | None = None,
        approval_client: TestApprovalClient | None = None,
        instrument: bool = True,
        instrumentation: dict[str, Any] | None = None,
    ):
        clients = dict(providers or {})
        if openai is not None:
            clients["openai"] = openai
        if anthropic is not None:
            clients["anthropic"] = anthropic
        if cursor is not None:
            clients["cursor"] = cursor
        if gemini is not None:
            clients["gemini"] = gemini

        self._instrument = instrument
        self._instrumentation = dict(instrumentation or {})
        self._providers = {
            _normalize_provider(name): self._to_adapter(name, client)
            for name, client in clients.items()
        }
        self.models = {_normalize_provider(key): value for key, value in (models or {}).items()}
        self.routes = dict(routes or {})
        self.approval_client = approval_client
        self._credential_cache: ManagedCredentialCache | None = None
        self._provider_factories: dict[str, Callable[[str], Any]] = {}

    @classmethod
    def from_env(
        cls,
        *,
        models: dict[str, str],
        provider_factories: dict[str, Callable[[str], Any]] | None = None,
        **kwargs: Any,
    ) -> "LLM":
        factories = provider_factories or _default_provider_factories()
        credentials = {
            "openai": os.getenv("OPENAI_API_KEY"),
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
            "cursor": os.getenv("CURSOR_API_KEY"),
            "gemini": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        }
        clients = {
            provider: factories[provider](api_key)
            for provider, api_key in credentials.items()
            if api_key and provider in factories
        }
        return cls(providers=clients, models=models, **kwargs)

    @classmethod
    def from_managed(
        cls,
        *,
        models: dict[str, str],
        endpoint: str | None = None,
        runtime_key: str | None = None,
        refresh_seconds: float = 300.0,
        provider_factories: dict[str, Callable[[str], Any]] | None = None,
        **kwargs: Any,
    ) -> "LLM":
        config = get_config(endpoint=endpoint)
        runtime_key = runtime_key or os.getenv("LOGLLAMA_RUNTIME_KEY")
        if not runtime_key:
            raise ValueError("A LogLlama runtime key is required for managed credentials.")
        cache = ManagedCredentialCache(
            endpoint=config.endpoint,
            runtime_key=runtime_key,
            timeout_seconds=max(1.0, config.timeout_seconds),
            refresh_seconds=refresh_seconds,
        )
        cache.prefetch()
        factories = provider_factories or _default_provider_factories()
        clients = {
            provider: factories[provider](secret)
            for provider, secret in cache.snapshot().items()
            if provider in factories
        }
        llm = cls(providers=clients, models=models, **kwargs)
        llm._credential_cache = cache
        llm._provider_factories = factories
        cache.start_background_refresh(llm._refresh_managed_providers)
        return llm

    def close(self, timeout_seconds: float = 5.0) -> None:
        if self._credential_cache:
            self._credential_cache.close()
        flush(timeout_seconds)

    def available_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def generate(
        self,
        prompt: str | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        route: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> GenerationResponse:
        provider, model = self._resolve_target(provider, model, route)
        adapter = self._providers.get(provider)
        if adapter is None:
            raise ValueError(f"Provider '{provider}' is not configured.")
        return adapter.generate(
            prompt=prompt,
            messages=messages,
            model=model,
            system=system,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            metadata=metadata,
            provider_options=provider_options,
        )

    def request_test(
        self,
        *,
        prompt: str,
        targets: list[tuple[str, str]],
        max_output_tokens: int = 256,
        max_runs: int = 1,
        system: str | None = None,
    ) -> dict[str, Any]:
        if not self.approval_client:
            raise ValueError("An approval_client is required to request comparison tests.")
        normalized_targets = [
            {"provider": _normalize_provider(provider), "model": model}
            for provider, model in targets
        ]
        return self.approval_client.request_test(
            prompt=prompt,
            targets=normalized_targets,
            max_output_tokens=max_output_tokens,
            max_runs=max_runs,
            system=system,
        )

    def compare(self, *, test_plan_id: str) -> ComparisonResult:
        if not self.approval_client:
            raise ValueError("An approval_client is required for comparison tests.")
        plan = self.approval_client.lease_test_plan(test_plan_id)
        if plan.get("status") != "approved":
            raise ApprovalRequiredError(
                f"Test plan '{test_plan_id}' is {plan.get('status', 'not approved')}."
            )
        expires_at = plan.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ) <= datetime.now(timezone.utc):
            raise ApprovalRequiredError(f"Test plan '{test_plan_id}' has expired.")

        comparison_id = f"cmp_{uuid.uuid4().hex}"
        targets = list(plan.get("targets") or [])
        responses: dict[str, GenerationResponse] = {}
        errors: dict[str, str] = {}

        def run_target(target: dict[str, str]) -> GenerationResponse:
            provider = _normalize_provider(target["provider"])
            return self.generate(
                str(plan.get("prompt") or ""),
                provider=provider,
                model=target["model"],
                system=plan.get("system"),
                max_output_tokens=int(plan.get("max_output_tokens") or 256),
                metadata={
                    "comparison_id": comparison_id,
                    "test_plan_id": test_plan_id,
                    "test_mode": True,
                },
            )

        with ThreadPoolExecutor(max_workers=max(1, len(targets)), thread_name_prefix="logllama-test") as executor:
            futures = {executor.submit(run_target, target): target for target in targets}
            for future in as_completed(futures):
                target = futures[future]
                key = f"{_normalize_provider(target['provider'])}:{target['model']}"
                try:
                    responses[key] = future.result()
                except Exception as exc:
                    errors[key] = f"{exc.__class__.__name__}: {exc}"

        return ComparisonResult(comparison_id, test_plan_id, responses, errors)

    def _resolve_target(
        self,
        provider: str | None,
        model: str | None,
        route: str | None,
    ) -> tuple[str, str]:
        if route:
            target = self.routes.get(route)
            if not target:
                raise ValueError(f"Unknown route '{route}'.")
            provider = target.get("provider")
            model = target.get("model")
        if not provider:
            raise ValueError("Specify provider= or route=.")
        provider = _normalize_provider(provider)
        model = model or self.models.get(provider)
        if not model:
            raise ValueError(f"No model configured for provider '{provider}'.")
        return provider, model

    def _to_adapter(self, provider: str, client: ProviderAdapter | Any) -> ProviderAdapter:
        normalized = _normalize_provider(provider)
        if getattr(client, "name", None) == normalized and callable(getattr(client, "generate", None)):
            return client
        if self._instrument:
            wrappers = {
                "openai": wrap_openai,
                "anthropic": wrap_anthropic,
                "cursor": wrap_cursor,
                "gemini": wrap_gemini,
            }
            client = wrappers[normalized](client, **self._instrumentation)
        adapters = {
            "openai": OpenAIAdapter,
            "anthropic": AnthropicAdapter,
            "cursor": CursorAdapter,
            "gemini": GeminiAdapter,
        }
        if normalized not in adapters:
            raise ValueError(f"Unsupported provider '{provider}'.")
        return adapters[normalized](client)

    def _refresh_managed_providers(self, changed: set[str], credentials: dict[str, str]) -> None:
        next_providers = dict(self._providers)
        for provider in changed:
            factory = self._provider_factories.get(provider)
            secret = credentials.get(provider)
            if factory and secret:
                next_providers[provider] = self._to_adapter(provider, factory(secret))
            elif provider not in credentials:
                next_providers.pop(provider, None)
        self._providers = next_providers


def _default_provider_factories() -> dict[str, Callable[[str], Any]]:
    factories: dict[str, Callable[[str], Any]] = {}
    try:
        from openai import OpenAI

        factories["openai"] = lambda api_key: OpenAI(api_key=api_key)
    except ImportError:
        pass
    try:
        from anthropic import Anthropic

        factories["anthropic"] = lambda api_key: Anthropic(api_key=api_key)
    except ImportError:
        pass
    try:
        from google import genai

        factories["gemini"] = lambda api_key: genai.Client(api_key=api_key)
    except ImportError:
        pass
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

        factories["cursor"] = lambda api_key: Agent.create(
            AgentOptions(
                model=os.getenv("CURSOR_MODEL", "auto-smart"),
                api_key=api_key,
                local=LocalAgentOptions(cwd=os.getenv("CURSOR_SDK_WORKSPACE", os.getcwd())),
            )
        )
    except ImportError:
        pass
    return factories


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    return "anthropic" if normalized == "claude" else normalized
