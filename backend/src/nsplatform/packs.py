"""Workflow packs: how a new use case plugs into the platform without changing it.

A pack is a folder with `manifest.yaml` (systems, tools, actions, rules, intents, prompt), an optional
`handlers.py` (composite tools and action preparers), `rules/*.yaml` and `evals/golden.yaml`.
The loader registers everything under the pack's namespace, generates the LLM tool definitions from the
manifest, and runs tools through the connector gateway with the session's customer id injected.
"""

from __future__ import annotations

import importlib.util
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from nsplatform import telemetry
from nsplatform.connector import CallPolicy, ConnectorGateway, SystemConfig, ToolResult
from nsplatform.policy import Decision, PolicyEngine

TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class ToolOutput:
    status: str = "ok"  # ok | degraded | unavailable | error | refused
    data: dict = field(default_factory=dict)
    cards: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    figures: dict = field(default_factory=dict)
    focus: str | None = None
    message: str | None = None
    latency_ms: float = 0
    from_cache: bool = False

    def for_model(self) -> dict:
        out = {"status": self.status, **self.data}
        if self.message:
            out["note"] = self.message
        return out


@dataclass
class ToolSpec:
    name: str
    pack: str
    local: str
    description: str
    params: dict
    required: list[str]
    label: str
    system: str | None = None
    http: dict | None = None
    handler: Callable[..., Awaitable[ToolOutput]] | None = None
    policy: CallPolicy = field(default_factory=CallPolicy)
    expose: bool = True
    prefetch: bool = False

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.params, "required": self.required,
                                 "additionalProperties": False}}


@dataclass
class Proposal:
    title: str
    summary: list[dict]
    request_type: str
    payload: dict
    request_summary: str
    spoken: str
    cards: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


@dataclass
class ActionSpec:
    name: str
    pack: str
    local: str
    description: str
    params: dict
    required: list[str]
    tier: str  # read | confirm | confirm_otp
    system: str
    label: str
    prepare: Callable[..., Awaitable[Proposal | ToolOutput]]

    def definition(self) -> dict:
        tier_note = {"read": "Runs immediately.",
                     "confirm": "Proposes the action; the customer must confirm before anything is filed.",
                     "confirm_otp": "Proposes the action; the customer must confirm with a one-time password."}[self.tier]
        return {"name": self.name, "description": f"{self.description} {tier_note}",
                "input_schema": {"type": "object", "properties": self.params, "required": self.required,
                                 "additionalProperties": False}}


@dataclass
class Intent:
    id: str
    pack: str
    patterns: list[re.Pattern]
    tool: str
    args: dict
    speculative: bool = True


@dataclass
class Pack:
    name: str
    namespace: str
    version: str
    applies_when: dict
    prompt: str
    voice_prompt: str
    tools: dict[str, ToolSpec]
    actions: dict[str, ActionSpec]
    intents: list[Intent]
    suggestions: list[str]
    path: Path
    products: dict | None = None  # {tool, list_key, type, id_field, label, warm}
    overview: Callable[..., Awaitable[dict]] | None = None  # contributes to the account panel

    def applies(self, products: list[dict]) -> bool:
        needed = self.applies_when.get("has_product")
        return not needed or any(p["type"] in needed for p in products)


class ToolContext:
    """What a tool handler can use. The customer id comes from the authenticated session, never the model."""

    def __init__(self, registry: "Registry", customer_id: str, session: dict, today: date):
        self.registry = registry
        self.customer_id = customer_id
        self.session = session
        self.today = today
        self._clause_cache: dict[str, dict] = {}

    async def call(self, tool: str, **args) -> ToolResult:
        spec = self.registry.tools[tool]
        return await self.registry.call_http(spec, args, self.customer_id)

    async def call_many(self, calls: list[tuple[str, dict]], deadline_s: float = 3.5) -> list[ToolResult]:
        # long enough for one retry of the slowest system (1.5 s timeout x 2 + backoff), short enough for a turn
        return await self.registry.gateway.gather([self.call(t, **a) for t, a in calls], deadline_s)

    def decide(self, ruleset: str, facts: dict) -> Decision:
        with telemetry.span("policy.evaluate", ruleset=ruleset):
            return self.registry.policy.evaluate(ruleset, facts)

    async def cite(self, clause_ids: list[str]) -> list[dict]:
        """Clause text for the sources footer (Policy system, cached)."""
        missing = [c for c in clause_ids if c not in self._clause_cache]
        if missing:
            res = await self.registry.gateway.request(
                "policy", "GET", "/policy/clauses", customer_id=self.customer_id, params={"ids": ",".join(missing)},
                policy=CallPolicy(timeout_ms=600, retries=1, cache_s=3600, stale_ok_s=86400), tool="policy.cite")
            for c in (res.data or {}).get("clauses", []):
                self._clause_cache[c["clause_id"]] = c
        return [{"kind": "policy", "ref": c, "text": self._clause_cache.get(c, {}).get("text", "")}
                for c in clause_ids]


def _validate(schema_props: dict, required: list[str], args: dict) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be an object"
    for r in required:
        if r not in args or args[r] in (None, ""):
            return f"missing required argument '{r}'"
    for key, value in args.items():
        prop = schema_props.get(key)
        if prop is None:
            return f"unknown argument '{key}'"
        t = prop.get("type")
        if t == "string" and not isinstance(value, str):
            return f"'{key}' must be a string"
        if t in ("number", "integer") and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return f"'{key}' must be a number"
        if "enum" in prop and value not in prop["enum"]:
            return f"'{key}' must be one of {prop['enum']}"
        if t in ("number", "integer") and "minimum" in prop and value < prop["minimum"]:
            return f"'{key}' must be at least {prop['minimum']}"
    return None


class Registry:
    def __init__(self, gateway: ConnectorGateway, policy: PolicyEngine):
        self.gateway = gateway
        self.policy = policy
        self.packs: dict[str, Pack] = {}
        self.tools: dict[str, ToolSpec] = {}
        self.actions: dict[str, ActionSpec] = {}

    # ------------------------------------------------------------------ loading
    def load_pack(self, path: Path, system_urls: dict[str, str]) -> Pack:
        manifest = yaml.safe_load((path / "manifest.yaml").read_text())
        for key in ("pack", "namespace", "version", "tools"):
            if key not in manifest:
                raise ValueError(f"{path}: manifest missing '{key}'")
        ns = manifest["namespace"]
        handlers = self._load_handlers(path, ns)

        for name, cfg in (manifest.get("systems") or {}).items():
            self.gateway.add_system(SystemConfig(name, cfg["display_name"], system_urls.get(name) or cfg["base_url"]))

        tools: dict[str, ToolSpec] = {}
        for local, cfg in manifest["tools"].items():
            name = f"{ns}_{local}"
            if not TOOL_NAME.match(name) or name in self.tools:
                raise ValueError(f"invalid or duplicate tool name {name}")
            handler = None
            if "handler" in cfg:
                handler = getattr(handlers, cfg["handler"], None)
                if handler is None:
                    raise ValueError(f"{path}: handler {cfg['handler']} not found in handlers.py")
            elif "http" not in cfg:
                raise ValueError(f"{path}: tool {local} needs http or handler")
            if cfg.get("system") and cfg["system"] not in self.gateway.systems:
                raise ValueError(f"{path}: tool {local} uses unknown system {cfg['system']}")
            spec = ToolSpec(
                name=name, pack=manifest["pack"], local=local, description=cfg.get("description", "").strip(),
                params=cfg.get("params") or {}, required=cfg.get("required") or [], label=cfg.get("label", local),
                system=cfg.get("system"), http=cfg.get("http"), handler=handler,
                policy=CallPolicy(timeout_ms=cfg.get("timeout_ms", 800), retries=cfg.get("retries", 1),
                                  cache_s=cfg.get("cache_s", 0), stale_ok_s=cfg.get("stale_ok_s", 0)),
                expose=cfg.get("expose", True), prefetch=cfg.get("prefetch", False))
            tools[name] = spec

        actions: dict[str, ActionSpec] = {}
        for local, cfg in (manifest.get("actions") or {}).items():
            name = f"{ns}_{local}"
            if not TOOL_NAME.match(name) or name in self.actions or name in tools:
                raise ValueError(f"invalid or duplicate action name {name}")
            if cfg["tier"] not in ("read", "confirm", "confirm_otp"):
                raise ValueError(f"{path}: action {local} has invalid tier {cfg['tier']}")
            prepare = getattr(handlers, cfg["prepare"], None)
            if prepare is None:
                raise ValueError(f"{path}: action {local} prepare {cfg['prepare']} not found")
            actions[name] = ActionSpec(name, manifest["pack"], local, cfg.get("description", "").strip(),
                                       cfg.get("params") or {}, cfg.get("required") or [], cfg["tier"],
                                       cfg.get("system", "ops"), cfg.get("label", local), prepare)

        for rules_file in sorted((path / "rules").glob("*.yaml")) if (path / "rules").exists() else []:
            self.policy.load_file(rules_file, manifest["pack"])

        intents = [Intent(i["id"], manifest["pack"], [re.compile(p, re.I) for p in i["match"]], f"{ns}_{i['tool']}",
                          i.get("args") or {}, i.get("speculative", True))
                   for i in manifest.get("intents") or []]
        for intent in intents:
            if intent.tool not in tools and intent.tool not in actions:
                raise ValueError(f"{path}: intent {intent.id} targets unknown tool {intent.tool}")

        prompts = path / "prompts"
        pack = Pack(manifest["pack"], ns, manifest["version"], manifest.get("applies_when") or {},
                    (prompts / "system.md").read_text() if (prompts / "system.md").exists() else "",
                    (prompts / "voice.md").read_text() if (prompts / "voice.md").exists() else "",
                    tools, actions, intents, manifest.get("suggestions") or [], path, manifest.get("products"))
        if manifest.get("overview"):
            pack.overview = getattr(handlers, manifest["overview"])
        if pack.products:
            pack.products["tool"] = f"{ns}_{pack.products['tool']}"
            if pack.products.get("warm"):
                pack.products["warm"] = f"{ns}_{pack.products['warm']}"
        self.packs[pack.name] = pack
        self.tools.update(tools)
        self.actions.update(actions)
        return pack

    @staticmethod
    def _load_handlers(path: Path, namespace: str):
        file = path / "handlers.py"
        if not file.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"packs_{namespace}_handlers", file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # ------------------------------------------------------------------ queries
    def active_packs(self, products: list[dict]) -> list[Pack]:
        return [p for p in self.packs.values() if p.applies(products)]

    def definitions(self, packs: list[Pack]) -> list[dict]:
        defs = []
        for pack in sorted(packs, key=lambda p: p.name):  # deterministic order keeps the prompt cache stable
            defs += [t.definition() for t in pack.tools.values() if t.expose]
            defs += [a.definition() for a in pack.actions.values()]
        return defs

    # ------------------------------------------------------------------ execution
    async def call_http(self, spec: ToolSpec, args: dict, customer_id: str) -> ToolResult:
        path = spec.http["path"].format(customer_id=customer_id, **args)
        query = {k: v for k, v in args.items() if "{" + k + "}" not in spec.http["path"]}
        query.update(spec.http.get("query") or {})
        method = spec.http.get("method", "GET")
        return await self.gateway.request(
            spec.system, method, path, customer_id=customer_id, params=query if method == "GET" else None,
            body=query if method != "GET" else None, policy=spec.policy, tool=spec.name)

    async def run_tool(self, name: str, args: dict, ctx: ToolContext) -> ToolOutput:
        spec = self.tools.get(name)
        if spec is None:
            return ToolOutput("error", message=f"unknown tool {name}")
        problem = _validate(spec.params, spec.required, args)
        if problem:
            return ToolOutput("error", message=f"invalid arguments: {problem}")
        started = time.perf_counter()
        try:
            if spec.handler:
                out = await spec.handler(ctx, **args)
            else:
                res = await self.call_http(spec, args, ctx.customer_id)
                data = {k: v for k, v in (res.data or {}).items() if k != "source_ref"}
                out = ToolOutput(res.status, data, sources=[{"kind": "record", **res.source_ref}] if res.source_ref else [],
                                 message=res.message, from_cache=res.from_cache)
        except Exception as e:  # a pack bug must not take the turn down
            out = ToolOutput("error", message=f"{spec.label} failed: {type(e).__name__}: {e}")
        out.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        telemetry.record("tool.run", out.latency_ms, system=spec.system, status=out.status, tool=name)
        return out


def match_intents(packs: list[Pack], text: str) -> list[Intent]:
    """Intents whose patterns match, most specific (longest matched span) first; ties keep manifest order."""
    hits = []
    for pack in packs:
        for intent in pack.intents:
            spans = [m.end() - m.start() for p in intent.patterns if (m := p.search(text))]
            if spans:
                hits.append((max(spans), intent))
    hits.sort(key=lambda h: -h[0])
    return [intent for _, intent in hits]


def tool_label(registry: Registry, name: str) -> str:
    if name in registry.tools:
        return registry.tools[name].label
    if name in registry.actions:
        return registry.actions[name].label
    return name
