"""GVK constants for upstream Flux v2 CRDs.

This is the ONLY Flux API surface the server uses. No fluxcd.controlplane.io
(operator) types — that's the whole point of the vanilla build.
"""

from __future__ import annotations

GVK = tuple[str, str]  # (apiVersion, kind)

SOURCE_GVKS: list[GVK] = [
    ("source.toolkit.fluxcd.io/v1", "GitRepository"),
    ("source.toolkit.fluxcd.io/v1beta2", "OCIRepository"),
    ("source.toolkit.fluxcd.io/v1", "HelmRepository"),
    ("source.toolkit.fluxcd.io/v1", "Bucket"),
    ("source.toolkit.fluxcd.io/v1beta2", "HelmChart"),
]

KUSTOMIZATION_GVK: GVK = ("kustomize.toolkit.fluxcd.io/v1", "Kustomization")
HELMRELEASE_GVK: GVK = ("helm.toolkit.fluxcd.io/v2", "HelmRelease")

NOTIFICATION_GVKS: list[GVK] = [
    ("notification.toolkit.fluxcd.io/v1beta3", "Alert"),
    ("notification.toolkit.fluxcd.io/v1beta3", "Provider"),
    ("notification.toolkit.fluxcd.io/v1", "Receiver"),
]

IMAGE_GVKS: list[GVK] = [
    ("image.toolkit.fluxcd.io/v1beta2", "ImageRepository"),
    ("image.toolkit.fluxcd.io/v1beta2", "ImagePolicy"),
    ("image.toolkit.fluxcd.io/v1beta2", "ImageUpdateAutomation"),
]

FLUX_GROUP_SUFFIX = ".toolkit.fluxcd.io"
FLUX_SYSTEM_NAMESPACE = "flux-system"
RECONCILE_ANNOTATION = "reconcile.fluxcd.io/requestedAt"
