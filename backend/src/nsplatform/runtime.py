"""Assemble the platform: shared systems, connector gateway, policy engine, packs, action executor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from nsplatform.actions import ActionExecutor
from nsplatform.connector import ConnectorGateway, SystemConfig
from nsplatform.db import get_db
from nsplatform.packs import Registry
from nsplatform.policy import PolicyEngine
from nsplatform.store import make_store

PACK_ORDER = ["core", "loans", "cards"]  # core first; others in this order, then any extra packs found


@dataclass
class Platform:
    registry: Registry
    gateway: ConnectorGateway
    policy: PolicyEngine
    executor: ActionExecutor
    store: object


def build_platform(packs_dir: Path, system_urls: dict[str, str], demo_mode: bool = True, store=None,
                   client: httpx.AsyncClient | None = None, only_packs: list[str] | None = None) -> Platform:
    store = store or make_store()
    shared = yaml.safe_load((Path(__file__).parent / "systems.yaml").read_text())
    systems = {name: SystemConfig(name, cfg["display_name"], system_urls[name]) for name, cfg in shared.items()}
    gateway = ConnectorGateway(systems, store, client)
    policy = PolicyEngine()
    registry = Registry(gateway, policy)
    found = [p.name for p in sorted(packs_dir.iterdir()) if (p / "manifest.yaml").exists()]
    ordered = [p for p in PACK_ORDER if p in found] + [p for p in found if p not in PACK_ORDER]
    for name in ordered:
        if only_packs is None or name in only_packs:
            registry.load_pack(packs_dir / name, system_urls)
    executor = ActionExecutor(registry, store, get_db(), demo_mode)
    return Platform(registry, gateway, policy, executor, store)
