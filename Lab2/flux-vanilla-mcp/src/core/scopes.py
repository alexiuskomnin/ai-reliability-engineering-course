"""Permission gating for MCP tools.

Each tool declares (read_only, in_cluster) at import time; the dispatcher
calls `check_scope` before invoking the handler.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_config


@dataclass(frozen=True)
class ToolScope:
    read_only: bool
    in_cluster: bool  # whether the tool may run inside the cluster


# Populated by tool modules on import via register_scope().
_SCOPES: dict[str, ToolScope] = {}


def register_scope(tool_name: str, *, read_only: bool, in_cluster: bool) -> None:
    _SCOPES[tool_name] = ToolScope(read_only=read_only, in_cluster=in_cluster)


def get_scope(tool_name: str) -> ToolScope | None:
    return _SCOPES.get(tool_name)


class ScopeError(RuntimeError):
    """Raised when a tool is invoked in a context where it is not permitted."""


def check_scope(tool_name: str) -> None:
    scope = _SCOPES.get(tool_name)
    if scope is None:
        raise ScopeError(f"tool {tool_name!r} is not registered with a scope")

    cfg = get_config()
    if cfg.read_only and not scope.read_only:
        raise ScopeError(
            f"tool {tool_name!r} is a write operation "
            f"but the server is in read-only mode"
        )
    if cfg.in_cluster and not scope.in_cluster:
        raise ScopeError(
            f"tool {tool_name!r} cannot run in in-cluster mode "
            f"(no kubeconfig file available)"
        )
    if cfg.enabled_tools and tool_name not in cfg.enabled_tools:
        raise ScopeError(f"tool {tool_name!r} is not in the enabled allowlist")
