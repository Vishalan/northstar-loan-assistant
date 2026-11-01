"""LLM client wrapper: switchable provider, hot-swappable model, failover, cost per call.

Providers are data (providers.yaml, or the file named by LLM_PROVIDERS_FILE) and are picked with LLM_PROVIDER:
the Anthropic API, an Anthropic-compatible proxy, open-weight models on our own GPU (Ollama speaks the Messages
API), or Claude on Bedrock or Vertex. Every response's served model is recorded and a substitution is logged:
the proxy was observed answering a request for claude-haiku-5-5 with claude-opus-4-8.

The active model can be changed at runtime (admin endpoint); a failover model is tried when the active one
errors. The server-side refusal fallback is only sent on the native API to models that support it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import yaml

FALLBACK_BETA = "server-side-fallback-2026-07-01"
SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}

# USD per million tokens at Anthropic list price: (input, output, cache read). On the proxy the plan is billed
# differently; these give the list-price equivalent so models can be compared.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str                        # anthropic | bedrock | vertex
    key_env: str | None
    base_url: str | None
    models: tuple[str, ...] | None   # verified to be served as asked; None accepts any id
    default_model: str
    default_failover: str
    server_fallbacks: bool = False
    supports_effort: bool = True
    no_effort_models: frozenset[str] = field(default_factory=frozenset)
    key_optional: bool = False
    request_params: dict = field(default_factory=dict)  # merged into every request (e.g. thinking off)

    def api_key(self) -> str | None:
        return os.environ.get(self.key_env) if self.key_env else None

    def has_credentials(self) -> bool:
        """Whether this provider can be used as configured (LLM_MODE=auto turns the planner on only then)."""
        if self.kind == "bedrock":
            return bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")
                        or (Path.home() / ".aws" / "credentials").exists())
        if self.kind == "vertex":
            return bool(os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"))
        if self.key_optional:
            return bool(self.base_url)
        if self.api_key():
            return True
        return self.name == "native" and bool(os.environ.get("ANTHROPIC_AUTH_TOKEN")
                                              or (Path.home() / ".config" / "anthropic").exists())

    def client(self, api_key: str | None = None, base_url: str | None = None):
        timeout = anthropic.Timeout(30.0, connect=3.0)
        if self.kind == "bedrock":
            return anthropic.AsyncAnthropicBedrock(max_retries=1, timeout=timeout)
        if self.kind == "vertex":
            return anthropic.AsyncAnthropicVertex(max_retries=1, timeout=timeout)
        key = api_key or self.api_key() or ("not-needed" if self.key_optional else None)
        return anthropic.AsyncAnthropic(api_key=key, base_url=base_url or self.base_url, max_retries=1, timeout=timeout)


def load_providers(path: str | Path | None = None) -> dict[str, Provider]:
    path = Path(path or os.environ.get("LLM_PROVIDERS_FILE") or Path(__file__).with_name("providers.yaml"))
    providers = {}
    for name, cfg in yaml.safe_load(path.read_text()).items():
        models = cfg.get("models")
        base_url = os.environ.get(cfg["base_url_env"]) if cfg.get("base_url_env") else None
        providers[name] = Provider(
            name=name, kind=cfg.get("kind", "anthropic"), key_env=cfg.get("key_env"),
            base_url=base_url or cfg.get("base_url"),
            models=None if models in (None, "any") else tuple(models),
            default_model=cfg.get("default_model", ""),
            default_failover=cfg.get("default_failover", ""), server_fallbacks=cfg.get("server_fallbacks", False),
            supports_effort=cfg.get("supports_effort", True), no_effort_models=frozenset(cfg.get("no_effort_models", [])),
            key_optional=cfg.get("key_optional", False),
            # <PROVIDER>_REQUEST_PARAMS='{"thinking": {"type": "enabled", "budget_tokens": 2000}}' overrides the file
            request_params=json.loads(os.environ.get(f"{name.upper()}_REQUEST_PARAMS") or "null")
            or cfg.get("request_params") or {})
    return providers


PROVIDERS = load_providers()


def cost_usd(model: str, usage) -> float:
    inp, out, cached = PRICES.get(model, (0.0, 0.0, 0.0))
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return round((usage.input_tokens * inp + written * inp * 1.25 + read * cached + usage.output_tokens * out) / 1e6, 6)


def is_retryable(error: Exception) -> bool:
    """Errors worth retrying on the failover model: capacity and availability, not bad requests."""
    if isinstance(error, (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError)):
        return True
    return isinstance(error, anthropic.APIStatusError) and error.status_code in (408, 409, 429, 500, 502, 503, 504, 529)


def same_model(asked: str, served: str | None) -> bool:
    """Served ids may carry a date suffix (claude-haiku-4-5-20251001)."""
    return not served or served == asked or served.startswith(asked + "-")


class LLM:
    def __init__(self, provider: Provider, api_key: str | None, model: str, effort: str,
                 failover_model: str | None = None, use_server_fallbacks: bool = True, base_url: str | None = None):
        self.provider = provider
        self.client = provider.client(api_key, base_url)
        self.warnings: list[str] = []
        self.model = self._resolve(model, provider.default_model, "MODEL_PLANNER")
        failover = failover_model if failover_model is not None else provider.default_failover
        self.failover_model = self._resolve(failover, None, "MODEL_FAILOVER") if failover else None
        if self.failover_model == self.model:
            self.failover_model = None
        self.effort = effort
        self.use_server_fallbacks = use_server_fallbacks and provider.server_fallbacks

    def _serves(self, model: str) -> bool:
        return bool(model) and (self.provider.models is None or model in self.provider.models)

    def _resolve(self, model: str, default: str | None, setting: str) -> str | None:
        if self._serves(model):
            return model
        self.warnings.append(f"{setting}={model} is not served as asked on the {self.provider.name} provider; "
                             f"using {default or 'none'}")
        return default

    @property
    def swappable(self) -> list[str]:
        return list(self.provider.models or [m for m in (self.model, self.failover_model) if m])

    def swap(self, model: str, failover_model: str | None = None) -> None:
        """Change the active model at runtime; the next turn uses it."""
        if not self._serves(model):
            raise ValueError(f"model must be one of {self.swappable}")
        self.model = model
        if failover_model is not None:
            if failover_model and not self._serves(failover_model):
                raise ValueError(f"failover model must be one of {self.swappable}")
            self.failover_model = failover_model or None
        if self.failover_model == self.model:
            self.failover_model = None

    def describe(self) -> dict:
        return {"provider": self.provider.name, "model": self.model, "failover_model": self.failover_model,
                "effort": self.effort, "swappable": self.swappable, "warnings": self.warnings,
                "list_prices_usd_per_mtok": {m: {"input": PRICES[m][0], "output": PRICES[m][1]}
                                             for m in self.swappable if m in PRICES}}

    def _kwargs(self, model: str, effort: str | None = None) -> dict:
        extra = dict(self.provider.request_params)
        if not self.provider.supports_effort or model in self.provider.no_effort_models:
            return extra
        return {**extra, "output_config": {"effort": effort or self.effort}}

    def stream(self, *, model: str, system: list[dict], tools: list[dict], messages: list[dict],
               max_tokens: int = 8000, tool_choice: dict | None = None):
        kwargs = dict(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages,
                      **self._kwargs(model))
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if self.use_server_fallbacks and model in SERVER_FALLBACK_MODELS:
            return self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.stream(**kwargs)

    async def complete(self, *, system: list[dict], messages: list[dict], max_tokens: int = 2000) -> str:
        """Non-tool call used to rewrite an answer that failed the grounding check."""
        async with self.client.messages.stream(model=self.model, max_tokens=max_tokens, system=system,
                                               messages=messages, **self._kwargs(self.model, "low")) as stream:
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in final.content if b.type == "text")

    def disable_server_fallbacks_if(self, error: Exception) -> bool:
        """True if the error was the fallback beta being rejected (then it is turned off)."""
        if self.use_server_fallbacks and isinstance(error, anthropic.BadRequestError) and "fallback" in str(error).lower():
            self.use_server_fallbacks = False
            return True
        return False
