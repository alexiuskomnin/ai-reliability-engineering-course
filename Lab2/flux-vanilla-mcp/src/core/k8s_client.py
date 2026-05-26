"""Kubernetes client factory.

Builds a `kubernetes.client.ApiClient` from either:
  * the in-cluster service account (when KUBERNETES_SERVICE_HOST is set), or
  * the kubeconfig path configured in RuntimeConfig, honoring an in-memory
    context override (set by the set_kubeconfig_context tool).

Tool handlers should call `get_api_client()` per invocation rather than
caching, so context switches take effect immediately.
"""

from __future__ import annotations

from kubernetes import client
from kubernetes import config as kubeconfig
from kubernetes.dynamic import DynamicClient

from .config import get_config


class KubeClientError(RuntimeError):
    pass


def get_api_client() -> client.ApiClient:
    cfg = get_config()
    if cfg.in_cluster:
        try:
            kubeconfig.load_incluster_config()
        except kubeconfig.ConfigException as e:
            raise KubeClientError(f"failed to load in-cluster config: {e}") from e
        return client.ApiClient()

    try:
        kubeconfig.load_kube_config(
            config_file=cfg.kubeconfig_path,
            context=cfg.kube_context_override,
        )
    except kubeconfig.ConfigException as e:
        raise KubeClientError(
            f"failed to load kubeconfig (path={cfg.kubeconfig_path!r}, "
            f"context={cfg.kube_context_override!r}): {e}"
        ) from e
    return client.ApiClient()


def get_dynamic_client() -> DynamicClient:
    """Dynamic client for any GVK without precompiled API stubs."""
    return DynamicClient(get_api_client())


def list_contexts() -> tuple[list[dict], str | None]:
    """Return (contexts, active_context_name) from the configured kubeconfig.

    Does not honor the in-memory override — returns the file's view.
    """
    cfg = get_config()
    contexts, active = kubeconfig.list_kube_config_contexts(
        config_file=cfg.kubeconfig_path
    )
    active_name = active["name"] if active else None
    return contexts, active_name
