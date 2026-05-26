"""Runtime configuration singleton for the Flux MCP server.

Populated once from CLI flags / env at startup in main.py, then read by
tool handlers and helpers. Importing this module never touches the
filesystem or the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _running_in_cluster() -> bool:
    return os.getenv("KUBERNETES_SERVICE_HOST") is not None


@dataclass
class RuntimeConfig:
    read_only: bool = False
    mask_secrets: bool = True
    timeout_seconds: int = 60
    kubeconfig_path: str | None = None
    kube_context_override: str | None = None
    enabled_tools: list[str] = field(default_factory=list)
    in_cluster: bool = field(default_factory=_running_in_cluster)
    allow_destructive: bool = False
    flux_docs_search_url: str = (
        # GitHub code search against the upstream Flux docs repo.
        # `{query}` is substituted at call time. No auth required for low rates
        # (10 req/min unauthenticated); set GITHUB_TOKEN env to raise the limit.
        "https://api.github.com/search/code?q={query}+repo:fluxcd/website+path:content/en"
    )


_config: RuntimeConfig = RuntimeConfig()


def get_config() -> RuntimeConfig:
    return _config


def set_config(cfg: RuntimeConfig) -> None:
    global _config
    _config = cfg


def set_context_override(name: str | None) -> None:
    """Used by set_kubeconfig_context to switch the active context in-memory."""
    _config.kube_context_override = name
