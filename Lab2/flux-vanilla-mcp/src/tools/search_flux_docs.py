"""Search the upstream Flux documentation.

Hits the URL configured in RuntimeConfig.flux_docs_search_url
(default: GitHub code search against fluxcd/website). Parses the JSON
response and returns the top matches with title, fluxcd.io URL, and a
text snippet.

The default GitHub Code Search endpoint REQUIRES authentication
(GitHub disabled unauthenticated code search in 2022). Set
GITHUB_TOKEN in the environment, or point --flux-docs-search-url at a
different JSON index for an unauthenticated lookup.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

import httpx
import yaml
from mcp.types import ToolAnnotations

from core.config import get_config
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "search_flux_docs"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)

_MAX_RESULTS = 5
_DEFAULT_TIMEOUT = 10.0


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Search Flux documentation",
        readOnlyHint=True,
    ),
)
def search_flux_docs(query: str) -> str:
    """Search the upstream Flux documentation for a free-text query.

    Args:
        query: Free-text query (e.g. "HelmRelease values reference",
            "GitRepository ssh authentication").
    """
    check_scope(TOOL_NAME)
    if not query.strip():
        return yaml.safe_dump({"error": "query is empty"})

    cfg = get_config()
    url = cfg.flux_docs_search_url.format(query=quote_plus(query))

    headers = {"Accept": "application/vnd.github.text-match+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(url, headers=headers, timeout=_DEFAULT_TIMEOUT)
    except httpx.HTTPError as exc:
        return yaml.safe_dump(
            {"error": f"docs search HTTP error: {exc}", "url": url}
        )

    if resp.status_code in (401, 403) and "api.github.com" in url:
        return yaml.safe_dump(
            {
                "error": (
                    "GitHub code search requires authentication. "
                    "Set GITHUB_TOKEN in the server environment (a fine-grained "
                    "token with public-repo read scope is enough) or override "
                    "--flux-docs-search-url with a JSON-returning endpoint."
                ),
                "status": resp.status_code,
                "url": url,
            }
        )
    if resp.status_code != 200:
        return yaml.safe_dump(
            {
                "error": f"docs search returned {resp.status_code}",
                "url": url,
                "body": _truncate(resp.text, 500),
            }
        )

    try:
        data = resp.json()
    except ValueError:
        return yaml.safe_dump({"error": "docs search returned non-JSON", "url": url})

    return yaml.safe_dump(
        {"query": query, "results": _format_results(data)},
        sort_keys=False,
    )


def _format_results(data: dict) -> list[dict]:
    """Map a GitHub code-search response into a compact result list.

    Falls back gracefully for custom index URLs — if the response looks
    nothing like GitHub's schema, returns the raw top-level items as-is.
    """
    items = data.get("items")
    if not isinstance(items, list):
        return [{"raw": data}]

    out: list[dict] = []
    for item in items[:_MAX_RESULTS]:
        path = item.get("path", "")
        out.append(
            {
                "title": _title_from_path(path),
                "url": _public_url_from_path(path),
                "repoPath": path,
                "snippets": _snippets(item),
            }
        )
    return out


def _title_from_path(path: str) -> str:
    """Strip Hugo's `content/en/` prefix and `_index.md`/`.md` suffixes."""
    stripped = path.removeprefix("content/en/")
    if stripped.endswith("/_index.md"):
        stripped = stripped.removesuffix("/_index.md")
    elif stripped.endswith(".md"):
        stripped = stripped.removesuffix(".md")
    return stripped or path


def _public_url_from_path(path: str) -> str:
    """Map `content/en/flux/foo/bar.md` to `https://fluxcd.io/flux/foo/bar/`."""
    if not path.startswith("content/en/"):
        return f"https://github.com/fluxcd/website/blob/main/{path}"
    stripped = path.removeprefix("content/en/")
    if stripped.endswith("/_index.md"):
        stripped = stripped.removesuffix("/_index.md") + "/"
    elif stripped.endswith(".md"):
        stripped = stripped.removesuffix(".md") + "/"
    return f"https://fluxcd.io/{stripped}"


def _snippets(item: dict) -> list[str]:
    matches = item.get("text_matches") or []
    out: list[str] = []
    for m in matches[:2]:
        frag = (m.get("fragment") or "").strip()
        if frag:
            out.append(_truncate(frag, 240))
    return out


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit].rstrip() + "…"
