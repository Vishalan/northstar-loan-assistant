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


def _has_llm_credentials(mode: str = "native") -> bool:
    if mode == "abhi":
        return bool(os.environ.get("ANTHROPIC_ABHI_API_KEY"))
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


@dataclass
class Settings:
    mocks_url: str = field(default_factory=lambda: os.environ.get("MOCKS_URL", "http://localhost:8100"))
    packs_dir: Path = field(default_factory=lambda: Path(os.environ.get("PACKS_DIR", BACKEND_DIR / "packs")))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", "dev-jwt-secret-change-me-in-production-0123"))
    admin_token: str = field(default_factory=lambda: os.environ.get("ADMIN_TOKEN", "dev-admin-token"))
    demo_mode: bool = field(default_factory=lambda: _flag("DEMO_MODE", True))
    today: date = field(default_factory=lambda: date.fromisoformat(os.environ.get("DEMO_TODAY", "2026-10-27")))
    llm_mode: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "auto"))  # auto | llm | fallback
    # which Anthropic endpoint and key: native (ANTHROPIC_API_KEY) | abhi (proxy, ANTHROPIC_ABHI_API_KEY)
    anthropic_mode: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODE", "native").lower())
    abhi_base_url: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_ABHI_BASE_URL", "https://opus.abhibots.com"))
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

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode in ("fallback", "stub"):  # stub simulates model latency and never calls the API
            return False
        if self.llm_mode == "llm":
            return True
        return _has_llm_credentials(self.anthropic_mode)

    def api_key(self) -> str | None:
        """The key for the selected provider; None lets the SDK resolve native credentials itself."""
        return os.environ.get("ANTHROPIC_ABHI_API_KEY") if self.anthropic_mode == "abhi" else os.environ.get("ANTHROPIC_API_KEY")

    def system_urls(self) -> dict[str, str]:
        names = ["crm", "loans", "payments", "policy", "ops", "cards"]
        return {n: os.environ.get(f"{n.upper()}_URL", self.mocks_url) for n in names}
