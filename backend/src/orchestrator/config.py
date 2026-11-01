"""Settings from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    """Read KEY=VALUE lines from the repo's .env (then backend/.env) without overriding real env vars."""
    for path in (BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip().strip('"').strip("'")
            if key.strip() and value and key.strip() not in os.environ:
                os.environ[key.strip()] = value


load_dotenv()


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


DEV_JWT_SECRET = "dev-jwt-secret-change-me-in-production-0123"
DEV_ADMIN_TOKEN = "dev-admin-token"
DEV_SERVICE_TOKEN = "dev-service-token"


@dataclass
class Settings:
    mocks_url: str = field(default_factory=lambda: os.environ.get("MOCKS_URL", "http://localhost:8100"))
    packs_dir: Path = field(default_factory=lambda: Path(os.environ.get("PACKS_DIR", BACKEND_DIR / "packs")))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", DEV_JWT_SECRET))
    admin_token: str = field(default_factory=lambda: os.environ.get("ADMIN_TOKEN", DEV_ADMIN_TOKEN))
    # demo OTP codes on screen, persona list, chaos controls. Off unless asked for: `make up` and .env.example turn it on
    demo_mode: bool = field(default_factory=lambda: _flag("DEMO_MODE", False))
    today: date = field(default_factory=lambda: date.fromisoformat(os.environ.get("DEMO_TODAY", "2026-10-27")))
    llm_mode: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "auto"))  # auto | llm | fallback
    # which provider in orchestrator/providers.yaml: native | abhi | selfhosted | bedrock | vertex | any you add
    llm_provider: str = field(default_factory=lambda: (
        os.environ.get("LLM_PROVIDER") or os.environ.get("ANTHROPIC_MODE") or "native").lower())
    model_planner: str = field(default_factory=lambda: os.environ.get("MODEL_PLANNER", "claude-haiku-5-5"))
    # tried automatically when the planner model errors (rate limit, overload, outage); empty = no failover
    model_failover: str = field(default_factory=lambda: os.environ.get("MODEL_FAILOVER", ""))
    planner_effort: str = field(default_factory=lambda: os.environ.get("PLANNER_EFFORT", "low"))
    llm_fallbacks: bool = field(default_factory=lambda: _flag("LLM_SERVER_FALLBACKS", True))
    cors_origins: list[str] = field(default_factory=lambda: os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","))
    turn_deadline_text_s: float = 2.5
    turn_deadline_voice_s: float = 1.8
    max_tool_rounds: int = 4

    def check_secrets(self) -> None:
        """Refuse to start outside demo mode with the development secrets that ship in this repo."""
        if self.demo_mode:
            return
        weak = [name for name, value, dev in (
            ("JWT_SECRET", self.jwt_secret, DEV_JWT_SECRET), ("ADMIN_TOKEN", self.admin_token, DEV_ADMIN_TOKEN),
            ("SERVICE_TOKEN", os.environ.get("SERVICE_TOKEN", DEV_SERVICE_TOKEN), DEV_SERVICE_TOKEN))
            if value == dev or len(value) < 24]
        if weak:
            raise RuntimeError(f"DEMO_MODE is off but {', '.join(weak)} still use development values (or are shorter "
                               "than 24 characters). Set real secrets, or DEMO_MODE=true for a local demo.")

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode in ("fallback", "stub"):  # stub simulates model latency and never calls the API
            return False
        if self.llm_mode == "llm":
            return True
        from orchestrator.llm import PROVIDERS

        provider = PROVIDERS.get(self.llm_provider)
        return bool(provider and provider.has_credentials())

    def models_for(self, provider) -> tuple[str, str | None]:
        """Planner and failover model for a provider. <PROVIDER>_MODEL / <PROVIDER>_FAILOVER win; providers that
        accept any id (self-hosted, Bedrock, Vertex) ignore MODEL_PLANNER, which names Claude API ids."""
        prefix = provider.name.upper()
        model = os.environ.get(f"{prefix}_MODEL") or (self.model_planner if provider.models is not None else provider.default_model)
        failover = os.environ.get(f"{prefix}_FAILOVER")
        if failover is None and provider.models is not None:
            failover = self.model_failover or None
        return model, failover

    def system_urls(self) -> dict[str, str]:
        names = ["crm", "loans", "payments", "policy", "ops", "cards"]
        return {n: os.environ.get(f"{n.upper()}_URL", self.mocks_url) for n in names}
